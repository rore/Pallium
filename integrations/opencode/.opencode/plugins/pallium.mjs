// pallium.mjs — Pallium memory integration for OpenCode.
//
// Adapts OpenCode's plugin lifecycle to Pallium's local REST daemon so memory
// auto-injection and auto-ingestion work exactly as they do in Claude Code and
// Codex. OpenCode does NOT run Claude's settings.json hooks and has no
// Claude-style JSONL transcript, so this adapter reads structured messages via
// the injected SDK `client` and maps OpenCode's hook surface onto Pallium's
// five behaviours:
//
//   Pallium behaviour            Claude hook       OpenCode adapter
//   ---------------------------  ----------------  --------------------------------
//   Orientation query + inject   SessionStart      event: session.created -> /query
//                                                  -> queued for system.transform
//   Ingest user msg + inject     UserPromptSubmit  chat.message -> /item-and-query
//                                                  -> queued for system.transform
//   Ingest assistant turn        Stop              event: session.idle -> read
//                                                  messages via client -> /items
//   Failure/retry triggers       PostToolUse       tool.execute.after (opt-in via
//                                                  PALLIUM_POSTTOOL_TRIGGERS=1)
//   Ingest before compaction     PreCompact        experimental.session.compacting
//                                                  -> /items (best-effort)
//
// Every hook is fail-safe: it swallows errors and never breaks the user's turn,
// matching the Python hooks' try/except + exit-0 behaviour. HTTP calls use a
// short (~6s) timeout. The port is read from PALLIUM_PORT (default 19836); no
// secrets or ports are hardcoded.
//
// OpenCode loads this as a server plugin — add it to opencode.json:
//   { "plugin": ["@pallium/opencode"] }              (from npm)
//   { "plugin": ["./integrations/opencode/.opencode/plugins/pallium.mjs"] }

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import * as pallium from "./pallium-common.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const SESSION_START_BUDGET = 1200;
const USER_PROMPT_BUDGET = 2400;
const TRIGGER_BUDGET = 1200;
const CONTENT_LENGTH_GATE = 20000;
const RETRY_THRESHOLD = 3;
const MIN_PROMPT_LEN = 20;

const POSTTOOL_TRIGGERS_ENABLED = process.env.PALLIUM_POSTTOOL_TRIGGERS === "1";

// Parse a command markdown file's frontmatter into { description, template }.
// Kept in a tiny local helper (not exported from the plugin module) because
// OpenCode's plugin loader treats every exported function as a plugin factory.
function parseCommandFile(filePath) {
  let raw;
  try {
    raw = fs.readFileSync(filePath, "utf8");
  } catch {
    return null;
  }
  const m = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/.exec(raw);
  if (!m) return null;
  const front = m[1];
  const body = (m[2] || "").replace(/^\r?\n/, "").trim();
  const descMatch = /^description:\s*(.+)$/m.exec(front);
  const description = descMatch ? descMatch[1].trim() : "";
  return { description, template: body };
}

export default async ({ client, directory, worktree } = {}) => {
  const cwd = directory || worktree || process.cwd();

  const log = (level, message) => {
    try {
      client && client.app && client.app.log({ body: { service: "pallium", level, message } });
    } catch { /* ignore */ }
  };

  // Per-session queue of formatted injection chunks awaiting the next
  // system-prompt transform. Orientation (session.created), per-message memory
  // (chat.message), and opt-in trigger output (tool.execute.after) all enqueue
  // here; system.transform drains it. All per-session state is bounded: it is
  // purged on `session.deleted` (see the event hook) so the long-lived server
  // process does not accumulate entries for closed sessions.
  const pendingInjections = new Map(); // sessionID -> string[]
  const orientedSessions = new Set(); // sessionID
  const ingestedBySession = new Map(); // sessionID -> Set(dedupKey)
  const retryCounters = new Map(); // `${sessionID}::${tool}::${target}` -> count

  function purgeSession(sessionId) {
    if (!sessionId) return;
    pendingInjections.delete(sessionId);
    orientedSessions.delete(sessionId);
    ingestedBySession.delete(sessionId);
    const prefix = `${sessionId}::`;
    for (const k of retryCounters.keys()) {
      if (k.startsWith(prefix)) retryCounters.delete(k);
    }
  }

  function enqueueInjection(sessionId, text) {
    if (!text) return;
    const key = sessionId || "__default__";
    const arr = pendingInjections.get(key) || [];
    arr.push(text);
    pendingInjections.set(key, arr);
  }

  function drainInjections(sessionId) {
    const out = [];
    if (sessionId && pendingInjections.has(sessionId)) {
      out.push(...pendingInjections.get(sessionId));
      pendingInjections.delete(sessionId);
      return out;
    }
    // No resolvable session (or no bucket for it). Injectable blocks are
    // visibility:"private" and scoped to a container_ref, so draining another
    // session's bucket here would cross a session/container boundary. Only
    // drain when exactly one session has pending blocks (the common
    // single-session case); otherwise leave them pending.
    if (!sessionId && pendingInjections.size === 1) {
      for (const [k, v] of pendingInjections) {
        out.push(...v);
        pendingInjections.delete(k);
      }
    }
    return out;
  }

  function resolveSessionId(obj) {
    if (!obj || typeof obj !== "object") return undefined;
    return (
      obj.sessionID || obj.sessionId || obj.session_id ||
      (obj.message && (obj.message.sessionID || obj.message.sessionId)) ||
      (obj.info && (obj.info.sessionID || obj.info.id)) ||
      (obj.properties && (obj.properties.sessionID || obj.properties.sessionId || obj.properties.session_id)) ||
      undefined
    );
  }

  async function orient(sessionId) {
    if (!sessionId || orientedSessions.has(sessionId)) return;
    orientedSessions.add(sessionId);
    try {
      const containerRef = pallium.deriveContainerRef(cwd);
      pallium.pinContainer(sessionId, containerRef, undefined);
      const actorRef = pallium.deriveActorRef();
      const queryText = pallium.deriveOrientationQuery(cwd);
      const resp = await pallium.palliumRequest("POST", "/query", {
        text: queryText,
        container_ref: containerRef,
        actor_ref: actorRef,
        visibility: "private",
        limit: 5,
        trigger_origin: "session_start_orientation",
      });
      const blocks = (resp && resp.injectable_blocks) || [];
      const output = pallium.formatInjection(blocks, containerRef, SESSION_START_BUDGET);
      if (output) enqueueInjection(sessionId, output);
    } catch (e) {
      log("error", `orientation failed: ${e && e.message}`);
    }
  }

  async function ingestAssistantTurn(sessionId) {
    if (!sessionId || !client || !client.session || typeof client.session.messages !== "function") return;
    try {
      const res = await client.session.messages({ path: { id: sessionId } });
      const messages = (res && (res.data || res)) || [];
      if (!Array.isArray(messages) || messages.length === 0) return;

      // Dedup: don't re-ingest the same assistant message if session.idle
      // (and/or experimental.session.compacting) fires more than once for the
      // same turn.
      let lastAssistantId = null;
      for (const m of messages) {
        const role = m && m.info ? m.info.role : (m ? m.role : undefined);
        if (role === "assistant") lastAssistantId = (m.info && m.info.id) || m.id || lastAssistantId;
      }

      const turn = pallium.extractAssistantTurn(messages);
      if (!turn) return;
      if (!turn.assistant_text && turn.tool_calls.length === 0) return;
      const content = turn.assistant_text;
      if (content.length > CONTENT_LENGTH_GATE) return;

      // Fall back to a content hash when the message carries no id, so a
      // turn without an id can't be re-ingested on every idle/compacting event.
      const dedupKey = lastAssistantId || ("sha:" + pallium.shortHash(sessionId + "\u0000" + content));
      const seen = ingestedBySession.get(sessionId) || new Set();
      if (seen.has(dedupKey)) return;
      // Mark before the awaited POST so a re-entrant event during the in-flight
      // request also short-circuits (Node is single-threaded).
      seen.add(dedupKey);
      ingestedBySession.set(sessionId, seen);

      const containerRef = pallium.resolveContainerRef(cwd, sessionId);
      const actorRef = pallium.deriveActorRef();

      const item = {
        source_type: pallium.SOURCE_TYPE,
        source_id: pallium.ocSourceId(),
        content_type: "text/plain",
        content,
        role: "assistant",
        agent_ref: pallium.AGENT_REF,
        container_ref: containerRef,
        thread_ref: sessionId,
        actor_ref: actorRef,
        visibility: "private",
        artifact_kind: "message",
      };
      const workTrace = pallium.buildWorkTraceMetadata(turn);
      if (workTrace) item.metadata = { agent_work_trace_turn: workTrace, cwd };

      await pallium.palliumRequest("POST", "/items", [item]);
    } catch (e) {
      log("error", `assistant-turn ingest failed: ${e && e.message}`);
    }
  }

  // --- opt-in PostToolUse triggers ------------------------------------------
  // (retryCounters is declared with the other per-session state above so it is
  //  purged on session.deleted.)

  function normalizeTarget(toolName, toolInput) {
    if (!toolInput || typeof toolInput !== "object") return "";
    if (toolName === "bash" || toolName === "shell") {
      const cmd = toolInput.command || toolInput.cmd || "";
      return pallium.redactSensitive(String(cmd)).slice(0, 80).trim();
    }
    for (const key of ["filePath", "file_path", "path", "pattern"]) {
      if (toolInput[key]) return String(toolInput[key]).slice(0, 200);
    }
    return "";
  }

  async function handleToolTrigger(sessionId, toolName, toolInput, outputText, isError) {
    const containerRef = pallium.resolveContainerRef(cwd, sessionId);
    const actorRef = pallium.deriveActorRef();
    const exitCode = isError ? 1 : pallium.inferExitCode(outputText);
    const failed = isError || exitCode !== 0;
    const blocks = [];

    if (failed) {
      const cls = toolName === "bash" || toolName === "shell"
        ? pallium.classifyBashFailure(outputText, exitCode)
        : "tool_error";
      const tail = outputText ? pallium.redactSensitive(outputText).slice(-400).trim() : "";
      const sig = tail ? `${cls}: ${tail}` : cls;
      const resp = await pallium.palliumRequest("POST", "/query", {
        text: sig,
        container_ref: containerRef,
        actor_ref: actorRef,
        visibility: "private",
        limit: 3,
        trigger_origin: "post_tool_failure",
      });
      if (resp && resp.injectable_blocks) blocks.push(...resp.injectable_blocks);
    }

    const target = normalizeTarget(toolName, toolInput);
    if (target) {
      const key = `${sessionId}::${toolName}::${target}`;
      let count = retryCounters.get(key) || 0;
      if (failed) {
        count += 1;
        retryCounters.set(key, count);
      } else {
        retryCounters.delete(key);
      }
      if (failed && count >= RETRY_THRESHOLD) {
        const resp = await pallium.palliumRequest("POST", "/query", {
          text: `${toolName} ${target}`.trim() || "retried operation",
          container_ref: containerRef,
          actor_ref: actorRef,
          visibility: "private",
          limit: 3,
          trigger_origin: "retry_threshold",
        });
        if (resp && resp.injectable_blocks) blocks.push(...resp.injectable_blocks);
      }
    }

    const output = pallium.formatInjection(blocks, containerRef, TRIGGER_BUDGET);
    if (output) enqueueInjection(sessionId, output);
  }

  const pluginSkillsDir = path.resolve(__dirname, "..", "..", "skills");

  return {
    // Register the pallium-memory skill dir + slash commands so they resolve
    // when the package is installed from npm (mirrors the Codex plugin.json
    // skills channel and the ponytail OpenCode adapter).
    config: async (config) => {
      try {
        if (!config.command) config.command = {};
        const commandDir = path.join(__dirname, "..", "command");
        if (fs.existsSync(commandDir)) {
          for (const file of fs.readdirSync(commandDir).filter((f) => f.endsWith(".md"))) {
            const name = path.basename(file, ".md");
            const parsed = parseCommandFile(path.join(commandDir, file));
            if (parsed) config.command[name] = parsed;
          }
        }
        config.skills = config.skills || {};
        config.skills.paths = config.skills.paths || [];
        if (fs.existsSync(pluginSkillsDir) && !config.skills.paths.includes(pluginSkillsDir)) {
          config.skills.paths.push(pluginSkillsDir);
        }
      } catch (e) {
        log("error", `config hook failed: ${e && e.message}`);
      }
    },

    // Inject queued memory blocks into the system prompt (orientation +
    // per-message memory + opt-in trigger output).
    "experimental.chat.system.transform": async (input, output) => {
      try {
        const sessionId = resolveSessionId(input);
        const chunks = drainInjections(sessionId);
        if (!chunks.length) return;
        const text = chunks.join("\n\n");
        if (!output || !Array.isArray(output.system)) return;
        if (output.system.length > 0) {
          output.system[output.system.length - 1] += "\n\n" + text;
        } else {
          output.system.push(text);
        }
      } catch (e) {
        log("error", `system.transform failed: ${e && e.message}`);
      }
    },

    // UserPromptSubmit equivalent: ingest the user message and fetch memories
    // in one /item-and-query call, queueing the blocks for system.transform.
    "chat.message": async (input, output) => {
      try {
        const message = (output && output.message) || (input && input.message) || {};
        const parts = (output && output.parts) || [];
        const sessionId = resolveSessionId(output) || resolveSessionId(input) || message.sessionID || "unknown";

        const promptRaw = pallium.extractTextFromParts(parts);
        if (!promptRaw || promptRaw.length < MIN_PROMPT_LEN) return;
        if (promptRaw.startsWith("/")) return;
        if (pallium.checkDedup(promptRaw, sessionId)) return;

        const content = pallium.stripIdeContext(promptRaw);
        if (!content) return;

        const containerRef = pallium.resolveContainerRef(cwd, sessionId);
        const actorRef = pallium.deriveActorRef();
        const queryText = content.length > 500 ? content.slice(0, 500) : content;

        const resp = await pallium.palliumRequest("POST", "/item-and-query", {
          source_type: pallium.SOURCE_TYPE,
          source_id: pallium.ocSourceId(),
          content_type: "text/plain",
          content,
          role: "user",
          agent_ref: pallium.AGENT_REF,
          container_ref: containerRef,
          thread_ref: sessionId,
          actor_ref: actorRef,
          visibility: "private",
          artifact_kind: "message",
          query_text: queryText,
          query_limit: 5,
          query_actor_ref: actorRef,
          query_trigger_origin: "user_prompt_submit",
        });
        if (!resp) return;
        const output_text = pallium.formatInjection(resp.injectable_blocks || [], containerRef, USER_PROMPT_BUDGET);
        if (output_text) enqueueInjection(sessionId, output_text);
      } catch (e) {
        log("error", `chat.message failed: ${e && e.message}`);
      }
    },

    // Event stream: session-start orientation + assistant-turn ingest.
    event: async ({ event } = {}) => {
      try {
        if (!event || typeof event !== "object") return;
        const type = event.type;
        const sessionId = resolveSessionId(event.properties) || resolveSessionId(event);
        if (type === "session.created") {
          await orient(sessionId);
        } else if (type === "session.idle") {
          await ingestAssistantTurn(sessionId);
        } else if (type === "session.deleted") {
          // Bound in-memory state: drop everything for a closed session.
          purgeSession(sessionId);
        }
      } catch (e) {
        log("error", `event hook failed: ${e && e.message}`);
      }
    },

    // PostToolUse equivalent — OFF unless PALLIUM_POSTTOOL_TRIGGERS=1.
    "tool.execute.after": async (input, output) => {
      try {
        if (!POSTTOOL_TRIGGERS_ENABLED) return;
        const sessionId = resolveSessionId(input) || "unknown";
        const toolName = String((input && input.tool) || "").toLowerCase();
        const toolInput = (output && (output.args || output.input)) || (input && input.args) || {};
        let outputText = "";
        if (output) {
          if (typeof output.output === "string") outputText = output.output;
          else if (typeof output.title === "string") outputText = output.title;
        }
        const isError = !!(output && (output.error || (output.metadata && output.metadata.error)));
        await handleToolTrigger(sessionId, toolName, toolInput, outputText, isError);
      } catch (e) {
        log("error", `tool.execute.after failed: ${e && e.message}`);
      }
    },

    // PreCompact equivalent: capture the latest assistant turn before the
    // session is compacted so pre-compaction work is not lost. Best-effort.
    "experimental.session.compacting": async (input) => {
      try {
        const sessionId = resolveSessionId(input);
        await ingestAssistantTurn(sessionId);
      } catch (e) {
        log("error", `session.compacting failed: ${e && e.message}`);
      }
    },
  };
};
