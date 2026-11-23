#!/usr/bin/env node
// Parity tests for the OpenCode integration's shared helpers — the JS twin of
// tests/test_hook_common_parity.py. Asserts container derivation, actor/redaction
// behaviour, the 5-minute dedup window, injection budget trimming, and turn
// extraction / work-trace metadata match the Claude Code / Codex contract.

import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";
import childProcess from "node:child_process";
import { syncBuiltinESMExports } from "node:module";
import { pathToFileURL } from "node:url";

// Redirect the state dir to a temp HOME BEFORE the module is imported, so
// dedup/pin state never touches the real ~/.pallium. STATE_DIR is resolved once
// at module load, so we must set the env then dynamic-import (imports are
// hoisted; a static import would run before this assignment).
const tmpHome = fs.mkdtempSync(path.join(os.tmpdir(), "pallium-oc-common-"));
process.env.USERPROFILE = tmpHome;
process.env.HOME = tmpHome;

let P;
test.before(async () => {
  const url = pathToFileURL(
    path.join(process.cwd(), ".opencode", "plugins", "pallium-common.mjs"),
  );
  P = await import(url);
});

test.after(() => {
  try { fs.rmSync(tmpHome, { recursive: true, force: true }); } catch { /* ignore */ }
});

for (const [name, request] of [
  ["history", (signal) => P.palliumRequest("POST", "/items", [], signal)],
  ["relay", (signal) => P.relayRequest("GET", "/relay/sessions", {}, 6000, signal)],
]) test(`${name}: cancelled requests do not start and stalled bodies respect retirement`, async () => {
  const previous = globalThis.fetch;
  try {
    let calls = 0;
    globalThis.fetch = async () => { calls++; return { ok: true, text: async () => "{}" }; };
    const cancelled = new AbortController();
    cancelled.abort();
    assert.equal(await request(cancelled.signal), null);
    assert.equal(calls, 0, "an already-retired caller cannot issue HTTP");

    let entered;
    const bodyStarted = new Promise((resolve) => { entered = resolve; });
    let observedSignal;
    globalThis.fetch = async (_, { signal }) => {
      observedSignal = signal;
      return { ok: true, text: () => {
        entered();
        return new Promise((_, reject) => signal.addEventListener("abort", () => reject(new Error("body cancelled")), { once: true }));
      } };
    };
    const owner = new AbortController();
    const pending = request(owner.signal);
    await bodyStarted;
    owner.abort();
    assert.equal(observedSignal.aborted, true);
    assert.equal(await pending, null);
  } finally { globalThis.fetch = previous; }
});

test("Relay HTTP error observation preserves legacy null results and body cleanup", async () => {
  const previous = globalThis.fetch;
  let reads = 0;
  let cancelled = 0;
  globalThis.fetch = async () => ({ ok: false, status: 409,
    text: async () => { reads++; return JSON.stringify({ detail: "registration conflict" }); },
    body: { cancel: async () => { cancelled++; } },
  });
  try {
    const request = (observer) => P.relayRequest("POST", "/relay/opencode/wake", {}, 1000, undefined, observer);
    assert.equal(await request(), null);
    assert.equal(reads, 0, "legacy callers do not read error bodies");
    let observed;
    assert.equal(await request((status, error) => { observed = { status, error }; }), null);
    assert.deepEqual(observed, { status: 409, error: { detail: "registration conflict" } });
    assert.equal(await request(() => { throw new Error("observer failed"); }), null);
    assert.equal(cancelled, 3);
  } finally { globalThis.fetch = previous; }
});

test("Relay error observer excludes bodies that complete after the request deadline", async () => {
  const previous = globalThis.fetch;
  let release;
  let aborted;
  const expired = new Promise((resolve) => { aborted = resolve; });
  let observed = 0;
  globalThis.fetch = async (_, { signal }) => ({ ok: false, status: 409,
    text: () => new Promise((resolve) => {
      release = () => resolve(JSON.stringify({ detail: "registration conflict" }));
      signal.addEventListener("abort", aborted, { once: true });
    }), body: { cancel: async () => {} },
  });
  try {
    const pending = P.relayRequest("POST", "/relay/opencode/wake", {}, 10, undefined, () => { observed++; });
    await expired;
    release();
    assert.equal(await pending, null);
    assert.equal(observed, 0);
  } finally { release?.(); globalThis.fetch = previous; }
});

test("retirement during an issued receipt prevents later receipts without retracting a commit", async () => {
  const previous = globalThis.fetch;
  const owner = new AbortController();
  const calls = [];
  let started, release;
  const entered = new Promise((resolve) => { started = resolve; });
  const response = new Promise((resolve) => { release = resolve; });
  globalThis.fetch = async (_, init) => {
    const body = JSON.parse(init.body);
    calls.push(body.delivery_id);
    started();
    // The server already committed; cancellation does not undo that receipt.
    await response;
    return { ok: true, text: async () => JSON.stringify({ delivery_id: body.delivery_id, state: "delivered", already_delivered: false }) };
  };
  try {
    const pending = P.acknowledgeRelay([
      { delivery_id: "issued", claim_token: "first" },
      { delivery_id: "later", claim_token: "second" },
    ], "path:fixture", owner.signal);
    await entered;
    owner.abort();
    release();
    const results = await pending;
    assert.deepEqual(calls, ["issued"]);
    assert.equal(results.some((result) => result.delivery_id === "later" && result.success), false);
  } finally { release(); globalThis.fetch = previous; }
});

// --- container_ref derivation ----------------------------------------------

test("normalizeRemoteUrl canonicalizes ssh/https/user forms", () => {
  assert.equal(P.normalizeRemoteUrl("git@github.com:user/repo.git"), "github.com/user/repo");
  assert.equal(P.normalizeRemoteUrl("https://github.com/user/repo.git"), "github.com/user/repo");
  assert.equal(P.normalizeRemoteUrl("https://github.com/User/Repo/"), "github.com/user/repo");
  assert.equal(P.normalizeRemoteUrl("https://token@github.com/user/repo"), "github.com/user/repo");
});

test("pathContainer emits path:<label>:<hash12> and path:<hash12> when label empty", () => {
  const withLabel = P.pathContainer(path.join(os.tmpdir(), "My Project"));
  assert.match(withLabel, /^path:my_project:[0-9a-f]{12}$/);
  // A basename that sanitizes to empty falls back to the bare-hash form.
  const bare = P.pathContainer("/@@@");
  assert.match(bare, /^path:[0-9a-f]{12}$/);
});

test("deriveContainerRef returns path:<...> for a non-git dir and is stable", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "pallium-oc-nogit-"));
  const ref = await P.deriveContainerRef(dir);
  assert.ok(ref.startsWith("path:"), `expected path: prefix, got ${ref}`);
  assert.equal(ref, P.pathContainer(dir));
  assert.equal(ref, await P.deriveContainerRef(dir)); // stable across calls
});

test("deriveContainerRef derives a stable ref for this repo checkout", async () => {
  // Runs inside a git checkout; the derivation contract (git:/repo:/path:) is
  // covered above. Assert the shape + determinism rather than the exact remote,
  // so this passes in a fork, a renamed-remote clone, or a git-less tarball.
  const ref = await P.deriveContainerRef(process.cwd());
  assert.match(ref, /^(git:|repo:|path:)/);
  assert.equal(ref, await P.deriveContainerRef(process.cwd()));
});

test("deriveActorRef uses the repository identity when the plugin cwd differs", async () => {
  const prior = process.env.PALLIUM_HOOK_ACTOR_REF;
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "pallium-oc-actor-"));
  try {
    delete process.env.PALLIUM_HOOK_ACTOR_REF;
    execFileSync("git", ["init"], { cwd: dir, stdio: "ignore" });
    execFileSync("git", ["config", "user.name", "Relay Operator"], { cwd: dir });
    assert.equal(await P.deriveActorRef(dir), "Relay Operator");
  } finally {
    if (prior === undefined) delete process.env.PALLIUM_HOOK_ACTOR_REF;
    else process.env.PALLIUM_HOOK_ACTOR_REF = prior;
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("deriveActorRef trims the configured actor, while a pinned actor remains authoritative", async () => {
  const prior = process.env.PALLIUM_HOOK_ACTOR_REF;
  try {
    process.env.PALLIUM_HOOK_ACTOR_REF = "  מפעיל 統一  ";
    assert.equal(await P.deriveActorRef(process.cwd()), "מפעיל 統一");
    P.pinContainer("configured-pin", "path:configured", undefined, "Pinned Actor");
    process.env.PALLIUM_HOOK_ACTOR_REF = "Different Actor";
    assert.equal(await P.resolveActorRef(process.cwd(), "configured-pin"), "Pinned Actor");
  } finally {
    if (prior === undefined) delete process.env.PALLIUM_HOOK_ACTOR_REF;
    else process.env.PALLIUM_HOOK_ACTOR_REF = prior;
    P.removeSessionPin("configured-pin");
  }
});
// --- redaction --------------------------------------------------------------

test("redactSensitive matches the Python behavioral-parity cases exactly", () => {
  assert.equal(P.redactSensitive("Bearer sk-12345"), "Bearer [REDACTED]");
  assert.equal(P.redactSensitive("DB_PASSWORD=secret"), "DB_PASSWORD=[REDACTED]");
  assert.equal(P.redactSensitive("postgres://user:pass@host/db"), "postgres://[REDACTED]");
  assert.equal(P.redactSensitive("clean text here"), "clean text here");
});

test("redactSensitive strips Authorization headers and key blocks", () => {
  assert.equal(P.redactSensitive("Authorization: Bearer abc123"), "Authorization: [REDACTED]");
  const key = "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----";
  assert.equal(P.redactSensitive(key), "[REDACTED KEY BLOCK]");
});

// --- dedup ------------------------------------------------------------------

test("checkDedup: first false, immediate repeat true, distinct prompt false", () => {
  const sid = "dedup-session-1";
  assert.equal(P.checkDedup("some unique prompt about widgets", sid), false);
  assert.equal(P.checkDedup("some unique prompt about widgets", sid), true);
  assert.equal(P.checkDedup("a completely different prompt", sid), false);
});

test("checkDedup expires entries older than the 5-minute window", () => {
  const sid = "dedup-session-2";
  assert.equal(P.checkDedup("aging prompt", sid), false);
  // Rewrite the state file with a stale timestamp to simulate >5 min elapsed.
  const stateFile = path.join(tmpHome, ".pallium", "hooks", "state", `${sid}.json`);
  const state = JSON.parse(fs.readFileSync(stateFile, "utf8"));
  for (const k of Object.keys(state)) state[k] = Date.now() / 1000 - (P.DEDUP_EXPIRY_SECONDS + 60);
  fs.writeFileSync(stateFile, JSON.stringify(state));
  assert.equal(P.checkDedup("aging prompt", sid), false); // expired -> not a dup
});

test("checkDedup rejects an unsafe session id (no path escape, safe default)", () => {
  const before = fs.readdirSync(path.join(tmpHome, ".pallium", "hooks", "state"));
  // A traversal-y id must not dedup and must not write a state file for it.
  assert.equal(P.checkDedup("some prompt", "../../evil"), false);
  assert.equal(P.checkDedup("some prompt", "a/b"), false);
  const after = fs.readdirSync(path.join(tmpHome, ".pallium", "hooks", "state"));
  assert.deepEqual(after.sort(), before.sort(), "no state file created for unsafe ids");
});

// --- session pinning --------------------------------------------------------

test("session scope pins container and actor across resume, then disposes both", async () => {
  const sid = "pin-session-1";
  P.pinContainer(sid, "git:example.com/a/b", undefined, "Relay Operator");
  assert.equal(await P.resolveContainerRef("/some/other/dir", sid), "git:example.com/a/b");
  assert.equal(await P.resolveActorRef("/some/other/dir", sid), "Relay Operator");
  P.pinContainer(sid, "git:example.com/a/b");
  assert.equal(P.getPinnedActor(sid), "Relay Operator");
  P.pinContainer(sid, "git:example.com/x/y", "resume", "Other Operator");
  assert.equal(P.getPinnedContainer(sid), "git:example.com/a/b");
  assert.equal(P.getPinnedActor(sid), "Relay Operator");
  P.removeSessionPin(sid);
  assert.equal(P.getPinnedContainer(sid), null);
  assert.equal(P.getPinnedActor(sid), null);
  P.pinContainer("bad id!", "git:z", undefined, "actor");
  assert.equal(P.getPinnedContainer("bad id!"), null);
});

// --- injection budget -------------------------------------------------------

function blocks(n) {
  const out = [];
  for (let i = 0; i < n; i++) {
    out.push({ title: `T${i}`, memory_object_id: `ref-${i}`, text: "x".repeat(60), expand_available: i === 0 });
  }
  return out;
}

test("formatInjection includes scope, header/footer, and all blocks under a generous budget", () => {
  const out = P.formatInjection(blocks(3), "git:example.com/a/b", 5000, "任务:α", "actor", "opencode", "private", "请求:42");
  assert.match(out, /^\[Pallium scope — /);
  assert.match(out, /"request_source_item_id":"请求:42"/);
  assert.match(out, /\[Pallium memory — container: git:example\.com\/a\/b\]/);
  assert.match(out, /\[End Pallium memory\]$/);
  assert.match(out, /ref:ref-0\]/);
  assert.match(out, /ref:ref-2\]/);
  assert.match(out, /\[\+expand\]/); // block 0 was expandable
});

test("formatInjection trims blocks that overflow the char budget", () => {
  const full = P.formatInjection(blocks(5), "c", 5000);
  const trimmed = P.formatInjection(blocks(5), "c", 400);
  assert.ok(trimmed.length <= 400 || trimmed === "", "trimmed output must respect the budget");
  assert.ok(trimmed.length < full.length, "tight budget must drop blocks");
  // First block is kept preferentially (blocks are popped from the end).
  if (trimmed) assert.match(trimmed, /ref:ref-0\]/);
});

test("formatInjection emits bounded scope without blocks and rejects unsafe identity", () => {
  const scoped = P.formatInjection([], "c", 2400, "任务:α", "actor", "opencode", "private", "请求:42");
  assert.match(scoped, /"request_source_item_id":"请求:42"/);
  assert.ok(scoped.length <= 2400);
  assert.equal(P.formatInjection([], "c", 2400), "");
  assert.equal(P.formatInjection(null, "c", 2400), "");
  assert.equal(P.formatInjection([], "c", 2400, "thread", null, null, null, "bad\nid"), "");
  assert.equal(P.formatInjection([], "c", 10, "thread", null, null, null, "request"), "");
});

// --- turn extraction + work-trace metadata ----------------------------------

function assistantMessages() {
  return [
    { info: { role: "user", id: "u1" }, parts: [{ type: "text", text: "please build it" }] },
    {
      info: { role: "assistant", id: "a1" },
      parts: [
        { type: "text", text: "Working on it." },
        { type: "tool", tool: "read", state: { status: "completed", input: { filePath: "src/a.js" }, output: "" } },
        { type: "tool", tool: "bash", state: { status: "error", input: { command: "npm test" }, output: "FAIL 1 test" } },
        { type: "tool", tool: "grep", state: { status: "completed", input: { pattern: "TODO", path: "src" }, output: "src/a.js:1: TODO x" } },
        { type: "tool", tool: "edit", state: { status: "completed", input: { filePath: "src/b.js" } } },
        { type: "tool", tool: "todowrite", state: { status: "completed", input: {} } },
      ],
    },
  ];
}

test("extractAssistantTurn folds OpenCode parts into the normalized TurnData shape", () => {
  const turn = P.extractAssistantTurn(assistantMessages());
  assert.ok(turn);
  assert.equal(turn.assistant_text, "Working on it.");
  assert.equal(turn.has_productive_action, true);
  assert.deepEqual(turn.files_modified, ["src/b.js"]);
  const toolNames = turn.tool_calls.map((c) => c.tool).sort();
  // Read/Bash/Grep are recorded; Edit (productive) and TodoWrite are excluded
  // from tool_calls per the shared EXCLUDED_TOOLS contract.
  assert.deepEqual(toolNames, ["Bash", "Grep", "Read"]);
  const bash = turn.tool_calls.find((c) => c.tool === "Bash");
  assert.equal(bash.exit_code, 1); // status:"error" -> synthetic exit code
  assert.equal(bash.failure_class, "command_error");
});

test("buildWorkTraceMetadata produces the shared work-trace shape", () => {
  const turn = P.extractAssistantTurn(assistantMessages());
  const meta = P.buildWorkTraceMetadata(turn);
  assert.ok(meta);
  assert.deepEqual(meta.files_read, ["src/a.js"]);
  assert.deepEqual(meta.grep_patterns, ["TODO"]);
  assert.deepEqual(meta.files_modified, ["src/b.js"]);
  assert.equal(meta.has_productive_action, true);
  assert.equal(meta.commands.length, 1);
  assert.equal(meta.commands[0].failure_class, "command_error");
});

test("extractAssistantTurn returns null when there is no assistant content", () => {
  assert.equal(P.extractAssistantTurn([]), null);
  assert.equal(P.extractAssistantTurn([{ info: { role: "user" }, parts: [{ type: "text", text: "hi" }] }]), null);
  assert.equal(
    P.extractAssistantTurn([{ info: { role: "assistant" }, parts: [{ type: "text", text: "   " }] }]),
    null,
  );
});

test("extractV2AssistantTurn reads public context messages and ignores idle records", () => {
  const turn = P.extractV2AssistantTurn([
    { type: "user", id: "u1", text: "prompt" },
    { type: "assistant", id: "a1", content: [{ type: "text", text: "Done שלום" }] },
    { type: "idle", outcome: "succeeded" },
  ]);
  assert.equal(turn.assistant_text, "Done שלום");
  assert.deepEqual(turn.tool_calls, []);
  assert.equal(P.extractV2AssistantTurn([{ type: "user", text: "only user" }, { type: "idle" }]), null);
});

test("extractV2AssistantTurn joins native tool and text steps in the current user turn", () => {
  // V2 2.0.22 /context records a separate assistant message for the tool step.
  const messages = [
    { type: "user", id: "msg_old", text: "old" },
    { type: "assistant", id: "msg_old_answer", content: [{ type: "text", text: "old answer" }] },
    { type: "user", id: "msg_toolprobe0001", text: "Run a harmless tool call" },
    { type: "assistant", id: "msg_tool", content: [{ type: "tool", id: "call_probe_1", name: "execute",
      state: { status: "completed", input: { code: "return 1" }, content: [{ type: "text", text: "1" }] } }] },
    { type: "assistant", id: "msg_final", content: [{ type: "text", text: "PROBE_ASSISTANT_שלום" }] },
    { type: "idle", id: "msg_idle", outcome: "succeeded" },
  ];
  assert.equal(P.extractV2AssistantTurn(messages).assistant_text, "PROBE_ASSISTANT_שלום");
  assert.deepEqual(P.extractV2AssistantTurn(messages).tool_calls, []); // execute has no existing work-trace semantic.
  messages[3].content[0] = { type: "tool", name: "bash", state: { status: "completed",
    input: { command: "pwd" }, content: [{ type: "text", text: "workspace" }] } };
  const turn = P.extractV2AssistantTurn(messages);
  assert.equal(turn.tool_calls[0].tool, "Bash");
  assert.equal(turn.tool_calls[0].command, "pwd");
  assert.equal(turn.tool_calls[0].output_tail, "workspace");
});

test("extractTextFromParts / stripIdeContext behave like the user-prompt path", () => {
  assert.equal(P.extractTextFromParts([{ type: "text", text: "hello" }, { type: "reasoning", text: "x" }]), "hello");
  assert.equal(
    P.stripIdeContext("real prompt <ide_selection>noise</ide_selection> more"),
    "real prompt  more",
  );
});

test("extractAssistantTurn captures apply_patch productive edits + patch_bodies metadata", () => {
  const messages = [
    { info: { role: "user", id: "u1" }, parts: [{ type: "text", text: "patch it" }] },
    {
      info: { role: "assistant", id: "a2" },
      parts: [
        { type: "text", text: "Patched." },
        {
          type: "tool",
          tool: "patch",
          state: {
            status: "completed",
            input: { operation: { path: "src/patched.js", diff: "@@ -1 +1 @@\n-old\n+new" } },
            output: "applied",
          },
        },
      ],
    },
  ];
  const turn = P.extractAssistantTurn(messages);
  assert.equal(turn.has_productive_action, true);
  assert.deepEqual(turn.files_modified, ["src/patched.js"]);
  const patch = turn.tool_calls.find((c) => c.tool === "apply_patch");
  assert.ok(patch, "apply_patch tool call recorded");
  assert.equal(patch.operation.path, "src/patched.js");
  const meta = P.buildWorkTraceMetadata(turn);
  assert.equal(meta.patch_bodies.length, 1);
  assert.equal(meta.patch_bodies[0].operation.path, "src/patched.js");
});

test("extractToolCall Glob splits and caps output paths", () => {
  const call = P.extractToolCall("Glob", { pattern: "**/*.js" }, "a.js\nb.js\nc.js");
  assert.deepEqual(call, { tool: "Glob", pattern: "**/*.js", paths: ["a.js", "b.js", "c.js"] });
});

test("deriveContainerRef returns repo:<hash12> for a git repo with no remote", async () => {
  const repo = fs.mkdtempSync(path.join(os.tmpdir(), "pallium-oc-repo-"));
  const run = (args) => execFileSync("git", args, { cwd: repo, stdio: ["ignore", "pipe", "ignore"] });
  run(["init"]);
  run(["config", "user.email", "t@e.st"]);
  run(["config", "user.name", "Tester"]);
  run(["config", "commit.gpgsign", "false"]);
  fs.writeFileSync(path.join(repo, "f.txt"), "hi");
  run(["add", "f.txt"]);
  run(["commit", "-m", "init"]);
  const ref = await P.deriveContainerRef(repo);
  const root = run(["rev-list", "--max-parents=0", "HEAD"]).toString().trim().toLowerCase();
  assert.equal(await P.repositoryScopeRef(repo), "repo:" + root);
  assert.match(ref, /^repo:[0-9a-f]{12}$/, `expected repo:<hash12>, got ${ref}`);
});

test("redactSensitive is unicode-safe (non-ASCII text is preserved, secrets still stripped)", () => {
  assert.equal(P.redactSensitive("提交说明 Bearer sk-üñ"), "提交说明 Bearer [REDACTED]");
  assert.equal(P.redactSensitive("café notes, no secrets"), "café notes, no secrets");
});

test("formatRelay preserves complete attributed messages and enforces budget", () => {
  const delivery = {
    delivery_id: "d-1", claim_token: "claim-1", message_id: "m-1",
    sender_runtime: "claude-code", sender_session_ref: "session-a",
    payload: "handoff שלום 你好", created_at: "2026-08-25T10:00:00+00:00",
    in_reply_to: "m-0",
  };
  const out = P.formatRelay([delivery], 2000);
  assert.match(out.text, /^\[Pallium Relay message from claude-code:session-a\]/);
  assert.match(out.text, /Lower-authority context/);
  assert.match(out.text, /handoff שלום 你好/);
  assert.match(out.text, /delivery_id: d-1/);
  assert.match(out.text, /pallium_relay_reply/);
  assert.match(out.text, /identify as Pallium Relay/);
  assert.match(out.text, /in_reply_to: m-0/);
  assert.deepEqual(out.deliveries, [delivery]);
  assert.equal(P.formatRelay([delivery], 20).text, "");
  assert.equal(P.formatRelay([{ ...delivery, payload: "bad\u0000value" }], 2000).text, "");
  const maximum = {
    ...delivery, message_id: "m".repeat(128), sender_session_ref: "s".repeat(255),
    in_reply_to: "p".repeat(128), payload: "😀".repeat(1400),
    payload_offset: 0, payload_total_chars: 16000,
    content_truncated: true, next_offset: 1400,
  };
  const tooLong = P.formatRelay([maximum], 2400, 1000);
  assert.equal(tooLong.text, "");
  assert.deepEqual(tooLong.deliveries, []);
  const shorter = { ...maximum, payload: "😀".repeat(700), next_offset: 700 };
  const preview = P.formatRelay([shorter], 2400, 1000);
  assert.match(preview.text, /Pallium Relay: 15300 characters omitted/);
  assert.match(preview.text, /offset=700/);
  assert.match(preview.text, /\[Relay: 999\+ more; Pallium continues\.\]$/);
  assert.ok([...preview.text].length <= 2400);
  assert.equal(P.formatRelay([{ ...shorter, next_offset: 699 }], 2400).text, "");
  assert.match(P.formatRelay([{ ...delivery, payload: "line one\nline two\tvalue" }]).text, /line one\nline two\tvalue/);
  const continuation = { ...delivery };
  delete continuation.claim_token;
  assert.match(P.formatRelayContinuation([continuation]), /handoff שלום 你好/);
  assert.equal(P.formatRelay([continuation]).text, "");
  assert.equal(typeof P.formatRelayContinuation([continuation]), "string");
  assert.equal(P.formatRelayContinuation([{ ...continuation, payload: "bad\u0000value" }]), "");
});

test("acknowledgeRelay reports successful, failed, and malformed outcomes", async () => {
  const previousFetch = globalThis.fetch;
  globalThis.fetch = async (_url, options) => {
    const deliveryId = JSON.parse(options.body).delivery_id;
    if (deliveryId === "failed") return { ok: false, body: { cancel: async () => {} } };
    return {
      ok: true,
      text: async () => JSON.stringify(deliveryId === "malformed"
        ? { state: "delivered" }
        : { delivery_id: deliveryId, state: "delivered", delivered_at: "now", already_delivered: false }),
    };
  };
  try {
    assert.deepEqual(await P.acknowledgeRelay([
      { delivery_id: "good", claim_token: "token" },
      { delivery_id: "failed", claim_token: "token" },
      { delivery_id: "malformed", claim_token: "token" },
      { delivery_id: "no-token" },
    ], "container"), [
      { delivery_id: "good", success: true },
      { delivery_id: "failed", success: false, error: "ack_failed" },
      { delivery_id: "malformed", success: false, error: "ack_failed" },
      { delivery_id: "no-token", success: false, error: "invalid_delivery" },
    ]);
  } finally {
    globalThis.fetch = previousFetch;
  }
});

test("ACK observation retains response headers before an unreadable body without changing results", async () => {
  const previousFetch = globalThis.fetch;
  const delivery = { delivery_id: "observed", claim_token: "secret" };
  try {
    for (const [status, body] of [[503, "lost"], [200, "lost"], [200, "malformed"], [503, "timeout"], [200, "timeout"]]) {
      const observations = [];
      globalThis.fetch = async (_url, { signal }) => ({
        ok: status === 200, status, headers: new Headers({ "Retry-After": "12" }),
        text: async () => {
          if (body === "timeout") return new Promise((_, reject) => signal.addEventListener("abort",
            () => reject(new Error("body timed out")), { once: true }));
          if (body === "malformed") return "{";
          throw new Error("body lost");
        }, body: { cancel: async () => {} },
      });
    assert.deepEqual(await P.acknowledgeRelay([delivery], "container", undefined,
      (item, observation) => { assert.equal(item, delivery); observations.push(observation); }),
    [{ delivery_id: "observed", success: false, error: "ack_failed" }]);
    assert.deepEqual(observations.map(({ at, ...row }) => row), [
      { phase: "headers", status, retryAfter: "12" },
      { phase: "outcome", status, error: undefined, success: false },
    ]);
    assert.ok(observations[1].at >= observations[0].at);
    assert.equal(JSON.stringify(observations).includes("secret"), false);
    }
  } finally { globalThis.fetch = previousFetch; }
});

test("formatRelay normalizes claim attempts and retains payloads with unknown metadata", () => {
  const base = {
    delivery_id: "relay-Ünicode-😀", claim_token: "claim-1", message_id: "m-1",
    sender_runtime: "claude-code", sender_session_ref: "session-a",
    payload: "safe payload", created_at: "2026-08-25T10:00:00+00:00",
  };
  for (const [attempts, claimAttempt, possible] of [
    [1, "1", "false"], [2, "2", "true"], [undefined, "unknown", "unknown"],
    [true, "unknown", "unknown"], [1.5, "unknown", "unknown"], ["2", "unknown", "unknown"],
    [0, "unknown", "unknown"], [-1, "unknown", "unknown"],
    [Number.MAX_SAFE_INTEGER, String(Number.MAX_SAFE_INTEGER), "true"],
    [Number.MAX_SAFE_INTEGER + 1, "unknown", "unknown"], [Infinity, "unknown", "unknown"],
    [NaN, "unknown", "unknown"], [1.0, "1", "false"],
  ]) {
    const delivery = { ...base, attempts };
    const { text, deliveries } = P.formatRelay([delivery]);
    assert.deepEqual(deliveries, [delivery]);
    assert.match(text, new RegExp(`delivery_id: relay-Ünicode-😀\\nclaim_attempt: ${claimAttempt}`));
    assert.match(text, new RegExp(`possible_redelivery: ${possible}`));
    assert.match(text, /Check exact delivery_id in context\/artifacts\./);
    assert.match(text, /Skip completed actions; if unknown, inspect target state before irreversible retry\./);
    assert.match(text, /Attempts do not prove emission\/actions\./);
    assert.match(text, /ACK: receipt, not completion/);
    assert.ok(text.includes(
      "Check exact delivery_id in context/artifacts. Skip completed actions; if unknown, inspect target state before irreversible retry. " +
      "Attempts do not prove emission/actions. ACK: receipt, not completion",
    ));
  }
  const full = P.formatRelay([{ ...base, attempts: 2 }]).text;
  assert.deepEqual(P.formatRelay([{ ...base, attempts: 2 }], [...full].length).deliveries.length, 1);
  assert.equal(P.formatRelay([{ ...base, attempts: 2 }], [...full].length - 1).deliveries.length, 0);
});


test("buildWorkRefsMetadata is filesystem-only and rechecks state", { skip: process.platform === "win32" }, () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "pallium-oc-work-ref-"));
  try {
    fs.mkdirSync(path.join(dir, ".git"), { recursive: true });
    fs.writeFileSync(path.join(dir, ".git", "HEAD"), "ref: refs/heads/demo/item\r\n");
    const tasks = path.join(dir, ".agent-workflow", "tasks");
    fs.mkdirSync(tasks, { recursive: true });
    const record = path.join(tasks, "item.md");
    fs.writeFileSync(record, "<!-- agent-workflow:start -->\n<!-- agent-workflow:end -->");
    const oldPath = process.env.PATH; process.env.PATH = "";
    try { assert.deepEqual(P.buildWorkRefsMetadata(dir, ["Ticket_Ünicode"]), { pallium_work_refs: ["git-branch:demo/item", "agent-workflow:item", "Ticket_Ünicode"] }); } finally { process.env.PATH = oldPath; }
    fs.rmSync(record); assert.deepEqual(P.buildWorkRefsMetadata(dir), { pallium_work_refs: ["git-branch:demo/item"] });
    fs.writeFileSync(record, "<!-- agent-workflow:end -->\n<!-- agent-workflow:start -->"); assert.deepEqual(P.buildWorkRefsMetadata(dir), { pallium_work_refs: ["git-branch:demo/item"] });
    fs.writeFileSync(record, "<!-- agent-workflow:start -->\n<!-- agent-workflow:end -->"); assert.deepEqual(P.buildWorkRefsMetadata(dir), { pallium_work_refs: ["git-branch:demo/item", "agent-workflow:item"] });
    fs.rmSync(path.join(dir, ".git", "HEAD")); assert.deepEqual(P.buildWorkRefsMetadata(dir, ["ISSUE-2"]), { pallium_work_refs: ["ISSUE-2"] });
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});

test("buildWorkRefsMetadata handles linked gitdirs and rejects unsafe cwd", { skip: process.platform === "win32" }, () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "pallium-oc-worktree-"));
  try {
    fs.mkdirSync(path.join(dir, "gitdir", "one"), { recursive: true });
    fs.writeFileSync(path.join(dir, ".git"), `gitdir: ${path.join(dir, "gitdir", "one")}\n`);
    fs.writeFileSync(path.join(dir, "gitdir", "one", "HEAD"), "ref: refs/heads/feature/one\n");
    const tasks = path.join(dir, ".agent-workflow", "tasks"); fs.mkdirSync(tasks, { recursive: true });
    fs.writeFileSync(path.join(tasks, "one.md"), "<!-- agent-workflow:start -->\n<!-- agent-workflow:end -->");
    assert.deepEqual(P.buildWorkRefsMetadata(dir), { pallium_work_refs: ["git-branch:feature/one", "agent-workflow:one"] });
    for (const cwd of ["relative", "", "x".repeat(4097), "\\\\server\\share", "\\\\?\\C:\\device"]) assert.deepEqual(P.buildWorkRefsMetadata(cwd), {});
    fs.writeFileSync(path.join(dir, "gitdir", "one", "HEAD"), Buffer.from([0xff])); assert.deepEqual(P.buildWorkRefsMetadata(dir), {});
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});

test("buildWorkRefsMetadata rejects malformed bounded metadata and deep discovery", { skip: process.platform === "win32" }, () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "pallium-oc-defensive-"));
  try {
    const git = path.join(dir, ".git");
    fs.mkdirSync(git);
    const head = path.join(git, "HEAD");
    const explicit = { pallium_work_refs: ["KEEP"] };
    for (const value of [
      "deadbeef\n",
      "ref: refs/tags/v1\n",
      "ref: refs/heads/main\n",
      "ref: refs/heads/feature/../escape\n",
      "ref: refs/heads/bad branch\n",
      "ref: refs/heads/feature/item\nsecond\n",
    ]) {
      fs.writeFileSync(head, value);
      assert.deepEqual(P.buildWorkRefsMetadata(dir, ["KEEP"]), explicit);
    }
    fs.writeFileSync(head, Buffer.alloc(4097, 97));
    assert.deepEqual(P.buildWorkRefsMetadata(dir, ["KEEP"]), explicit);
    fs.writeFileSync(head, Buffer.from([0xff, 0xfe]));
    assert.deepEqual(P.buildWorkRefsMetadata(dir, ["KEEP"]), explicit);

    fs.writeFileSync(head, "ref: refs/heads/feature/item\n");
    const tasks = path.join(dir, ".agent-workflow", "tasks");
    fs.mkdirSync(tasks, { recursive: true });
    const record = path.join(tasks, "item.md");
    fs.writeFileSync(record, Buffer.alloc(256 * 1024 + 1, 120));
    assert.deepEqual(P.buildWorkRefsMetadata(dir), { pallium_work_refs: ["git-branch:feature/item"] });
    fs.writeFileSync(record, Buffer.from([0xff]));
    assert.deepEqual(P.buildWorkRefsMetadata(dir), { pallium_work_refs: ["git-branch:feature/item"] });

    let nested = dir;
    for (let i = 0; i < 65; i++) {
      nested = path.join(nested, "d");
      fs.mkdirSync(nested);
    }
    assert.deepEqual(P.buildWorkRefsMetadata(nested, ["KEEP"]), explicit);
    assert.deepEqual(P.buildWorkRefsMetadata(path.join(dir, "missing"), ["KEEP"]), explicit);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("buildWorkRefsMetadata rejects malformed gitdir pointers and symlinks", { skip: process.platform === "win32" }, () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "pallium-oc-pointer-"));
  try {
    const marker = path.join(dir, ".git");
    for (const value of [
      "gitdir:",
      "other: metadata\n",
      "gitdir: relative\nextra\n",
      "gitdir: " + "\\\\server\\share\\repo" + "\n",
      "gitdir: " + "x".repeat(4097),
    ]) {
      fs.writeFileSync(marker, value);
      assert.deepEqual(P.buildWorkRefsMetadata(dir, ["KEEP"]), { pallium_work_refs: ["KEEP"] });
    }

    const target = path.join(dir, "metadata");
    fs.mkdirSync(target);
    fs.writeFileSync(path.join(target, "HEAD"), "ref: refs/heads/fix/link\n");
    fs.writeFileSync(marker, "gitdir: metadata\n");
    assert.deepEqual(P.buildWorkRefsMetadata(dir), { pallium_work_refs: ["git-branch:fix/link"] });

    fs.rmSync(marker);
    try {
      fs.symlinkSync(target, marker, "junction");
      assert.deepEqual(P.buildWorkRefsMetadata(dir, ["KEEP"]), { pallium_work_refs: ["KEEP"] });
    } catch (error) {
      if (!["EPERM", "EACCES", "UNKNOWN"].includes(error?.code)) throw error;
    }
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});


test("buildWorkRefsMetadata rejects intermediate symlink components", { skip: process.platform === "win32" }, () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "pallium-oc-components-"));
  try {
    const real = path.join(dir, "real");
    fs.mkdirSync(path.join(real, ".git"), { recursive: true });
    fs.writeFileSync(path.join(real, ".git", "HEAD"), "ref: refs/heads/fix/link\n");
    fs.mkdirSync(path.join(real, "nested"));
    const alias = path.join(dir, "alias");
    try {
      fs.symlinkSync(real, alias, "junction");
    } catch (error) {
      if (["EPERM", "EACCES", "UNKNOWN"].includes(error?.code)) return;
      throw error;
    }
    assert.deepEqual(P.buildWorkRefsMetadata(path.join(alias, "nested"), ["KEEP"]), { pallium_work_refs: ["KEEP"] });

    const checkout = path.join(dir, "checkout");
    const metadata = path.join(dir, "metadata");
    fs.mkdirSync(checkout);
    fs.mkdirSync(path.join(metadata, "one"), { recursive: true });
    fs.writeFileSync(path.join(metadata, "one", "HEAD"), "ref: refs/heads/fix/link\n");
    const metadataAlias = path.join(dir, "metadata-alias");
    fs.symlinkSync(metadata, metadataAlias, "junction");
    fs.writeFileSync(path.join(checkout, ".git"), `gitdir: ${path.join(metadataAlias, "one")}\n`);
    assert.deepEqual(P.buildWorkRefsMetadata(checkout, ["KEEP"]), { pallium_work_refs: ["KEEP"] });
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});


test("buildWorkRefsMetadata performs no structural filesystem access on Windows", { skip: process.platform !== "win32" }, () => {
  const original = fs.lstatSync;
  fs.lstatSync = () => { throw new Error("structural filesystem access"); };
  try {
    assert.deepEqual(P.buildWorkRefsMetadata("C:\\repo", ["KEEP"]), { pallium_work_refs: ["KEEP"] });
    assert.deepEqual(P.buildWorkRefsMetadata("C:\\repo"), {});
    assert.deepEqual(P.discoverWorkRefs("C:\\repo"), { structuralRefs: [] });
  } finally {
    fs.lstatSync = original;
  }
});


test("buildWorkRefsMetadata rejects BOM, dot branches, Git overrides, and HEAD races", { skip: process.platform === "win32" }, () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "pallium-oc-parity-"));
  try {
    const git = path.join(dir, ".git");
    fs.mkdirSync(git);
    const head = path.join(git, "HEAD");
    for (const value of [
      "\ufeffref: refs/heads/fix/item\n",
      "ref: refs/heads/fix/.hidden\n",
    ]) {
      fs.writeFileSync(head, value);
      assert.deepEqual(P.buildWorkRefsMetadata(dir, ["KEEP"]), { pallium_work_refs: ["KEEP"] });
    }

    fs.writeFileSync(head, "ref: refs/heads/fix/item\n");
    const previous = process.env.GIT_DIR;
    process.env.GIT_DIR = path.join(dir, "elsewhere");
    try {
      assert.deepEqual(P.buildWorkRefsMetadata(dir, ["KEEP"]), { pallium_work_refs: ["KEEP"] });
    } finally {
      if (previous === undefined) delete process.env.GIT_DIR;
      else process.env.GIT_DIR = previous;
    }

    const originalRead = fs.readSync;
    let changed = false;
    fs.readSync = function (...args) {
      const length = originalRead.apply(this, args);
      if (!changed) {
        changed = true;
        fs.writeFileSync(head, "ref: refs/heads/fix/other\n");
      }
      return length;
    };
    try {
      assert.deepEqual(P.buildWorkRefsMetadata(dir, ["KEEP"]), { pallium_work_refs: ["KEEP"] });
    } finally {
      fs.readSync = originalRead;
    }
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("formatInjection omits only unsafe work_ref and preserves scope", () => {
  for (const workRef of [
    "ghp_abcdefghijklmnopqrstuvwxyz1234567890",
    `xoxb-${"1".repeat(10)}-${"2".repeat(10)}-${"a".repeat(24)}`,
    "AKIAABCDEFGHIJKLMNOP",
    "eyJabcdefghijk.eyJabcdefghijk.abcdefghijk",
    "[REDACTED]",
    "bad\nref",
    "x".repeat(129),
  ]) {
    const out = P.formatInjection([], "git:repo", 2400, "thread", null, null, null, null, workRef);
    const scope = JSON.parse(out.slice(out.indexOf("{"), out.lastIndexOf("}") + 1));
    assert.deepEqual(scope, { container_ref: "git:repo", thread_ref: "thread" });
  }
});

test("injectedWorkRef selects first safe structural ref and ignores explicit-only refs", () => {
  assert.equal(P.injectedWorkRef({ structuralRefs: ["bad\nref", "git-branch:feature/任务"] }), "git-branch:feature/任务");
  assert.equal(P.injectedWorkRef({ structuralRefs: [] }), null);
  assert.deepEqual(P.buildWorkRefsMetadata("", ["EXPLICIT-REF"], { structuralRefs: [] }), { pallium_work_refs: ["EXPLICIT-REF"] });
  assert.equal(P.injectedWorkRef({ structuralRefs: ["[REDACTED]", "x".repeat(129)] }), null);
});

test("canonical repository and roadmap identity matches Python vectors", async () => {
  assert.equal(P.canonicalGitRemote("https://github.com/User/Repo.git"), "git:github.com/user/repo");
  assert.equal(P.canonicalGitRemote("ssh://git@git.example.test:22/team/Repo.git"), "git:git.example.test/team/Repo");
  assert.equal(P.canonicalGitRemote("ssh://git@git.example.test:2222/team/Repo.git"), "git:git.example.test:2222/team/Repo");
  assert.equal(P.canonicalGitRemote("git@github.com:User/Repo.git"), "git:github.com/user/repo");
  assert.equal(P.canonicalGitRemote("https://git.example.test/Team/Repo.git"), "git:git.example.test/Team/Repo");
  assert.equal(P.canonicalGitRemote("https://user:password@example.test/repo.git"), null);
  assert.equal(P.canonicalGitRemote("https://example.test:65536/repo.git"), null);
  assert.equal(P.roadmapScopeRef("git:github.com/owner/repo", "roadmap\\é space"), "roadmap:v1:git:github.com/owner/repo#roadmap/%C3%A9%20space");
  assert.deepEqual(P.structuralWorkRefsPayload("git:wrong/container", ["git-branch:feature/x", "agent-workflow:item"], "git:github.com/owner/repo"), [
    { scope_ref: "git:github.com/owner/repo", local_ref: "git-branch:feature/x" },
    { scope_ref: "roadmap:v1:git:github.com/owner/repo#roadmap", local_ref: "agent-workflow:item" },
  ]);
});

test("shared repository and roadmap vectors stay aligned with Python", () => {
  const vectors = JSON.parse(fs.readFileSync(
    path.resolve("..", "..", "tests", "fixtures", "relay_work_identity_vectors.json"),
    "utf8",
  ));
  for (const row of vectors.canonical_remotes) {
    assert.equal(P.canonicalGitRemote(row.input), row.expected);
  }
  for (const remote of vectors.invalid_remotes) {
    assert.equal(P.canonicalGitRemote(remote), null);
  }
  const repository = "git:github.com/owner/repo";
  for (const row of vectors.roadmap_roots) {
    assert.equal(P.roadmapScopeRef(repository, row.input), "roadmap:v1:" + repository + "#" + row.expected);
  }
  for (const root of vectors.invalid_roadmap_roots) {
    assert.throws(() => P.roadmapScopeRef(repository, root));
  }
});

// Run the actual helper against real owned Node children, without changing Git
// configuration or adding a production command-injection seam.
async function withGitProcess(program, run, onChild = () => {}) {
  const saved = childProcess.spawn;
  const previousActor = process.env.PALLIUM_HOOK_ACTOR_REF;
  const calls = [], children = [];
  delete process.env.PALLIUM_HOOK_ACTOR_REF;
  childProcess.spawn = (command, args, options) => {
    if (command !== "git") return saved(command, args, options);
    calls.push(args);
    const source = program(args);
    const child = source === null
      ? saved(path.join(tmpHome, "missing-bin", "git"), args, options)
      : saved(process.execPath, ["-e", source], options);
    const closed = new Promise((resolve) => child.once("close", resolve));
    children.push({ child, closed });
    onChild(child, args, options);
    return child;
  };
  syncBuiltinESMExports();
  try { return await run(calls); }
  finally {
    for (const { child } of children) if (child.exitCode === null && child.signalCode === null) child.kill();
    await Promise.all(children.map(({ closed }) => closed));
    childProcess.spawn = saved;
    syncBuiltinESMExports();
    if (previousActor === undefined) delete process.env.PALLIUM_HOOK_ACTOR_REF;
    else process.env.PALLIUM_HOOK_ACTOR_REF = previousActor;
  }
}

test("async Git shares callback facts without merging container and repository semantics", async () => {
  const root = "a".repeat(40);
  for (const [remote, code, containerRef, repositoryRef, probes] of [
    ["https://git.example.test/Team/Repo.git", 0, "git:git.example.test/team/repo", "git:git.example.test/Team/Repo", 1],
    ["https://user:password@example.test/Team/Repo.git", 0, "git:example.test/team/repo", "repo:" + root, 2],
    ["unusable nonzero stdout", 128, "repo:" + root.slice(0, 12), "repo:" + root, 2],
    [null, 0, P.pathContainer(process.cwd()), "repo:" + root, 2],
  ]) {
    await withGitProcess((args) => args[0] === "remote" ? remote === null ? null
      : `process.stdout.write(${JSON.stringify(remote)},()=>process.exit(${code}))`
      : `process.stdout.write(${JSON.stringify(root)})`, async (calls) => {
      assert.deepEqual(await P.deriveGitRefs(process.cwd()), { containerRef, repositoryRef });
      assert.equal(calls.length, probes, "remote/root results are local to this single discovery");
      assert.equal(calls.filter((args) => args[0] === "remote").length, 1);
    });
  }
  await withGitProcess(() => null, async (calls) => {
    assert.equal(await P.deriveContainerRef(process.cwd()), P.pathContainer(process.cwd()));
    assert.equal(calls.length, 1, "container-only spawn failure must not try a root probe");
  });
});

test("async Git enforces byte bounds and ignores stderr rather than truncating identity", async () => {
  const maximum = 1024 * 1024;
  for (const [source, expected] of [
    ["process.stdout.write('')", "local"],
    ['process.stdout.write("nonzero actor",()=>process.exit(2))', "local"],
    [`process.stdout.write("é".repeat(${maximum / 2}),()=>process.exit(0))`, "é".repeat(maximum / 2)],
    [`process.stdout.write("a".repeat(${maximum + 1}),()=>process.exit(0))`, "local"],
    [`process.stderr.write("x".repeat(${maximum * 2}));process.stdout.write("named actor",()=>process.exit(0))`, "named actor"],
  ]) {
    await withGitProcess(() => source, async () => assert.equal(await P.deriveActorRef(process.cwd()), expected));
  }
});

test("async Git distinguishes pre-abort, cancellation, signal and timeout outcomes", { timeout: 12000 }, async () => {
  const before = new AbortController(); before.abort();
  await withGitProcess(() => "process.exit(0)", async (calls) => {
    await assert.rejects(() => P.deriveContainerRef(process.cwd(), before.signal), { name: "AbortError" });
    assert.equal(calls.length, 0);
  });
  const owner = new AbortController();
  await withGitProcess(() => 'process.stdout.write("ready");setInterval(()=>{},50)', async () => {
    await assert.rejects(() => P.deriveActorRef(process.cwd(), owner.signal), { name: "AbortError" });
  }, (child) => child.stdout.once("data", () => owner.abort()));
  await withGitProcess(() => "setInterval(()=>{},50)", async (calls) => {
    assert.equal(await P.deriveContainerRef(process.cwd()), P.pathContainer(process.cwd()));
    assert.equal(calls.length, 1, "a killed child is not a numeric nonzero root fallback");
  }, (child) => child.once("spawn", () => child.kill()));
  await withGitProcess(() => "setInterval(()=>{},50)", async (calls) => {
    assert.equal(await P.deriveContainerRef(process.cwd()), P.pathContainer(process.cwd()));
    assert.equal(calls.length, 1, "the native command timeout keeps the legacy spawn-error class");
  });
});

test("async Git bounds owned stdout after parent exit without losing terminal outcomes", { timeout: 25000 }, async () => {
  const bounded = async (promise, message, ms = 5000) => {
    let timer;
    try { return await Promise.race([promise, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(message)), ms);
    })]); } finally { clearTimeout(timer); }
  };
  const observe = (child, signal) => {
    let start = -1, serial = 0, pipeError = false;
    const at = { exit: -1, close: -1, pipe: -1, error: -1 };
    const order = { exit: 0, close: 0, pipe: 0, error: 0 };
    const elapsed = () => start < 0 ? -1 : Math.min(60000, Math.max(0, Math.round(performance.now() - start)));
    const mark = (name) => { at[name] = elapsed(); order[name] = ++serial; };
    child.once("spawn", () => { start = performance.now(); });
    child.once("exit", () => mark("exit"));
    child.once("close", () => mark("close"));
    child.once("error", () => mark("error"));
    child.stdout.once("close", () => mark("pipe"));
    child.stdout.once("error", () => { pipeError = true; });
    return (mode, stage, holder = { ready: -1, release: -1, end: -1, terminal: -1 }) => {
      const code = child.exitCode === null ? "none" : Number.isInteger(child.exitCode) && child.exitCode >= 0 && child.exitCode <= 255
        ? child.exitCode : "other";
      const exitSignal = child.signalCode === null ? "none" : child.signalCode === "SIGTERM" ? "term"
        : child.signalCode === "SIGKILL" ? "kill" : "other";
      return `Git failure witness stage=${stage} mode=${mode} clock=test_spawn_event elapsed_ms=${elapsed()} exit_ms=${at.exit} exit_n=${order.exit} close_ms=${at.close} close_n=${order.close} pipe_ms=${at.pipe} pipe_n=${order.pipe} error_ms=${at.error} error_n=${order.error} pipe_error=${Number(pipeError)} code=${code} signal=${exitSignal} aborted=${Number(signal.aborted)} destroyed=${Number(child.stdout.destroyed)} ready=${holder.ready} release=${holder.release} end=${holder.end} terminal=${holder.terminal}`;
    };
  };
  const annotate = (error, before, after) => {
    const stack = error.stack;
    const context = `${before}\n${after}`;
    error.message += `\n${context}`;
    error.stack = `${context}\n${stack}`; // Put safe context before the exporter's bounded failure selection.
    return error;
  };
  const nativeSpawn = childProcess.spawn;
  const builtins = await import("node:child_process");
  {
    let sample = (stage) => `Git failure witness stage=${stage} mode=kill-error clock=test_spawn_event elapsed_ms=-1`;
    let firstEvidence;
    try {
    const owner = new AbortController();
    let child, nativeKill, closed = false, kills = 0, notify;
    const attempted = new Promise((resolve) => { notify = resolve; });
    await withGitProcess(() => 'process.stdout.write("ready");setInterval(()=>{},50)', async () => {
      let settled = false;
      const running = P.deriveActorRef(process.cwd(), owner.signal);
      const outcome = running.then((value) => { settled = true; return { value }; },
        (error) => { settled = true; return { error }; });
      try {
        await bounded(attempted, "abort must attempt native child termination");
        assert.equal(kills, 1, "a synchronous kill error must not issue a re-entrant kill");
        assert.equal(child.stdout.destroyed, true, "kill failure still closes owned stdout");
        await new Promise((resolve) => setImmediate(resolve));
        assert.equal(settled, false, "pipe cleanup must not complete before the real child closes");
        assert.equal(child.exitCode, null);
        nativeKill.call(child); // The fixture, not the failed production kill, ends this real child.
        const result = await bounded(outcome, "owned child must close after fixture termination");
        assert.equal(result.error?.name, "AbortError", "the first abort outcome survives the later kill error");
        assert.equal(closed, true);
        assert.equal(kills, 1);
      } catch (error) { firstEvidence = sample("failed_check"); throw error; }
      finally {
        child.kill = nativeKill;
        if (child.exitCode === null && child.signalCode === null) nativeKill.call(child);
        await outcome;
      }
    }, (spawned) => {
      child = spawned; nativeKill = child.kill;
      const snapshot = observe(child, owner.signal);
      sample = (stage) => snapshot("kill-error", stage);
      child.once("close", () => { closed = true; });
      child.kill = () => {
        kills++; notify();
        if (kills > 1) throw new Error("re-entrant fixture kill");
        child.emit("error", Object.assign(new Error("fixture kill denied"), { code: "EPERM" }));
        return false;
      };
      child.stdout.once("data", () => owner.abort());
    });
    assert.equal(childProcess.spawn, nativeSpawn);
    assert.equal(builtins.spawn, nativeSpawn, "named built-in binding must be restored too");
    } catch (error) { throw annotate(error, firstEvidence || sample("failed_check"), sample("after_cleanup")); }
  }
  for (const mode of ["abort", "timeout", "drain", "nonzero", "fallback-drain"]) {
    let sample = (stage) => `Git failure witness stage=${stage} mode=${mode} clock=test_spawn_event elapsed_ms=-1`;
    let firstEvidence;
    try {
    const directory = fs.mkdtempSync(path.join(tmpHome, "stdio-界-"));
    const release = path.join(directory, "release"), pidFile = path.join(directory, "pid");
    const ended = path.join(directory, "ended");
    const owner = new AbortController();
    const forced = mode === "fallback-drain";
    const forcedError = new Error("fixture primary failure before emergency holder drain");
    let primaryError, terminalConfirmed = false;
    const cleanupErrors = [];
    let root, running, exited, snapshot;
    sample = (stage) => snapshot ? snapshot(mode, stage, {
      ready: Number(fs.existsSync(pidFile)), release: Number(fs.existsSync(release)),
      end: Number(fs.existsSync(ended)), terminal: Number(terminalConfirmed),
    }) : `Git failure witness stage=${stage} mode=${mode} clock=test_spawn_event elapsed_ms=-1`;
    const holder = `
      const fs = require("node:fs");
      process.once("exit", () => fs.writeFileSync(${JSON.stringify(ended)}, "ended"));
      process.stdout.on("error", () => process.exit(0));
      const timer = setInterval(() => {
        if (!${forced} && fs.existsSync(${JSON.stringify(release)})) {
          clearInterval(timer);
          process.stdout.write("/Repo.git", () => process.exit(0));
        }
      }, 5);
      setTimeout(() => process.exit(0), 10000).unref();
      process.send("ready");
      process.disconnect();
    `;
    const parent = `
      const fs = require("node:fs");
      const child = require("node:child_process").spawn(process.execPath, ["-e", ${JSON.stringify(holder)}],
        { stdio: ["ignore", 1, "ignore", "ipc"], windowsHide: true, detached: true });
      child.on("message", () => {
        fs.writeFileSync(${JSON.stringify(pidFile)}, String(child.pid));
        process.stdout.write("https://git.example.test/Team", () => process.exit(${mode === "nonzero" ? 128 : 0}));
      });
    `;
    try {
      await withGitProcess((args) => args[0] === "remote" ? parent
        : `process.stdout.write("${"a".repeat(40)}")`, async (calls) => {
        running = P.deriveContainerRef(process.cwd(), owner.signal);
        // Attach a rejection handler before any readiness await.
        const outcome = running.then((value) => ({ value }), (error) => ({ error }));
        let actionError;
        try {
          await bounded(exited, "the real Git parent must exit");
          await new Promise((resolve) => setImmediate(resolve)); // after production's exit listener
          assert.equal(root.stdout.destroyed, false, "root exit alone must not discard buffered stdout");
          if (mode === "abort" || forced) owner.abort();
          if (mode === "drain" || mode === "nonzero") {
            let settled = false;
            void outcome.then(() => { settled = true; });
            await new Promise((resolve) => setImmediate(resolve));
            assert.equal(settled, false, "numeric exit must still wait for owned stdout close");
            fs.writeFileSync(release, "release");
          }
          const result = await bounded(outcome, "owned stdout must close under its original controls");
          if (mode === "abort" || forced) assert.equal(result.error?.name, "AbortError");
          else {
            assert.ifError(result.error);
            assert.equal(result.value, mode === "timeout" ? P.pathContainer(process.cwd())
              : mode === "nonzero" ? "repo:" + "a".repeat(12) : "git:git.example.test/team/repo");
            assert.equal(calls.length, mode === "nonzero" ? 2 : 1,
              "only numeric nonzero may fall through to the root probe");
          }
          assert.equal(root.stdout.destroyed, true, "helper completion is owned-stream close, not root exit");
          if (mode === "abort" || mode === "timeout" || forced)
            assert.equal(fs.existsSync(ended), false, "the helper closes only its pipe, not arbitrary descendants");
          if (forced) throw forcedError;
        } catch (error) { firstEvidence = sample("failed_check"); actionError = error; throw error; }
        finally {
          try { fs.writeFileSync(release, "release"); }
          catch (error) {
            firstEvidence ||= sample("cleanup_check");
            if (actionError) throw new AggregateError([actionError, error], "Git fixture release failed", { cause: actionError });
            throw error;
          } finally { await outcome; }
        }
      }, (child, args) => {
        if (args[0] !== "remote") return;
        root = child;
        snapshot = observe(child, owner.signal);
        exited = new Promise((resolve, reject) => { child.once("exit", resolve); child.once("error", reject); });
      });
    } catch (error) { firstEvidence ||= sample("failed_check"); primaryError = error; }
    finally {
      // This test owns the holder too; production deliberately owns only its pipe.
      try {
        if (fs.existsSync(pidFile)) {
          const pid = Number(fs.readFileSync(pidFile, "utf8"));
          try {
            fs.writeFileSync(release, "release");
            const deadline = Date.now() + (forced ? 0 : 5000);
            while (!fs.existsSync(ended)) {
              assert.ok(Date.now() < deadline, "the test-owned stdout holder must finish after release");
              await new Promise((resolve) => setTimeout(resolve, 5));
            }
          } catch (error) {
            firstEvidence ||= sample("cleanup_check");
            cleanupErrors.push(error);
            try { process.kill(pid); }
            catch (killError) { if (killError.code !== "ESRCH") throw killError; }
            const deadline = Date.now() + 5000;
            while (!terminalConfirmed) {
              try { process.kill(pid, 0); }
              catch (probeError) {
                if (probeError.code !== "ESRCH") throw probeError;
                terminalConfirmed = true;
              }
              if (!terminalConfirmed) {
                assert.ok(Date.now() < deadline, "emergency kill must be followed by holder terminal confirmation");
                await new Promise((resolve) => setTimeout(resolve, 5));
              }
            }
          }
        } else fs.writeFileSync(release, "release");
      } catch (error) { firstEvidence ||= sample("cleanup_check"); cleanupErrors.push(error); }
      finally { await running?.catch(() => {}); }
    }
    const errors = [primaryError, ...cleanupErrors].filter(Boolean);
    const failure = errors.length > 1 ? new AggregateError(errors, "Git fixture failed with cleanup errors", { cause: primaryError })
      : errors[0];
    assert.equal(childProcess.spawn, nativeSpawn);
    assert.equal(builtins.spawn, nativeSpawn);
    if (forced) {
      if (primaryError !== forcedError || cleanupErrors.length !== 1 || !terminalConfirmed)
        throw failure || new Error("forced emergency drain did not exercise its required path");
      assert.ok(failure instanceof AggregateError);
      assert.equal(failure.cause, forcedError, "cleanup must preserve the primary failure");
      assert.equal(failure.errors[0], forcedError);
      assert.equal(failure.errors.length, 2, "only the forced primary and release/drain failures are expected");
      assert.match(failure.errors[1].message, /holder must finish after release/);
      assert.equal(terminalConfirmed, true, "the emergency path must observe termination, not just send kill");
    } else if (failure) throw failure;
    } catch (error) { throw annotate(error, firstEvidence || sample("failed_check"), sample("after_cleanup")); }
  }
});

test("async actor resolution checks lifetime and keeps actor and container pins coherent", async () => {
  const sid = "async-actor-pin";
  for (const change of ["retire", "new-actor", "new-container", "removed"]) {
    let current = true;
    P.removeSessionPin(sid);
    P.pinContainer(sid, "git:example.test/original");
    try {
      await withGitProcess(() => 'process.stdout.write("derived actor");setTimeout(()=>{},50)', async () => {
        const resolution = P.resolveActorRef(process.cwd(), sid, { current: () => current });
        if (change === "new-actor") assert.equal(await resolution, "authoritative actor");
        else await assert.rejects(() => resolution, { name: "AbortError" });
        assert.notEqual(P.getPinnedActor(sid), "derived actor", "retired/conflicting discovery cannot publish its actor");
        if (change === "new-container") assert.equal(P.getPinnedContainer(sid), "git:example.test/replacement");
        if (change === "removed") assert.equal(P.getPinnedContainer(sid), null);
      }, (child) => child.stdout.once("data", () => {
        if (change === "retire") current = false;
        if (change === "new-actor") P.pinContainer(sid, "git:example.test/original", undefined, "authoritative actor");
        if (change === "new-container") P.pinContainer(sid, "git:example.test/replacement", undefined, "authoritative actor");
        if (change === "removed") P.removeSessionPin(sid);
      }));
    } finally { P.removeSessionPin(sid); }
  }
});

test("async Git preserves root validation and first-root container truncation", async () => {
  for (const root of ["", "not-a-root", "A".repeat(40), "b".repeat(64), "c".repeat(65),
    "d".repeat(40) + "\n" + "e".repeat(40)]) {
    await withGitProcess((args) => args[0] === "remote" ? "process.exit(128)"
      : `process.stdout.write(${JSON.stringify(root)})`, async (calls) => {
      const first = root.split("\n")[0];
      assert.deepEqual(await P.deriveGitRefs(process.cwd()), {
        containerRef: first ? "repo:" + first.slice(0, 12) : P.pathContainer(process.cwd()),
        repositoryRef: /^[0-9a-f]{40,64}$/i.test(first) ? "repo:" + first.toLowerCase() : null,
      });
      assert.equal(calls.length, 2);
    });
  }
});

test("async orientation preserves command order, token order, Unicode, redaction and eight stems", async () => {
  const outputs = ["feature/lazy-git_fix", " M src/alpha.js\nR  old.js -> new/beta.ts\n?? src/שלום.py\n",
    "src/alpha.js\nc.txt\nd.txt\ne.txt\nf.txt\ng.txt\nh.txt\n"];
  await withGitProcess((args) => {
    const output = args[0] === "rev-parse" ? outputs[0] : args[0] === "status" ? outputs[1] : outputs[2];
    return `process.stdout.write(${JSON.stringify(output)})`;
  }, async (calls) => {
    assert.equal(await P.deriveOrientationQuery(process.cwd()), "feature lazy git fix alpha beta שלום c d e f g");
    assert.deepEqual(calls, [["rev-parse", "--abbrev-ref", "HEAD"], ["status", "--porcelain"],
      ["log", "-3", "--name-only", "--pretty=format:"]]);
  });
  await withGitProcess((args) => `process.stdout.write(${JSON.stringify(args[0] === "rev-parse" ? "main" : "")})`,
    async () => assert.equal(await P.deriveOrientationQuery(process.cwd()), P.RETRIEVAL_FALLBACK_QUERY));
  await withGitProcess((args) => `process.stdout.write(${JSON.stringify(args[0] === "status" ? " M TOKEN=example.txt" : "")})`,
    async () => assert.equal(await P.deriveOrientationQuery(process.cwd()), "TOKEN=[REDACTED]"));
});

test("async identity follows Unicode nested cwd and linked worktree Git configuration", async () => {
  const root = fs.mkdtempSync(path.join(tmpHome, "repo-界-"));
  const repo = path.join(root, "primary"), linked = path.join(root, "linked-שלום");
  const previousActor = process.env.PALLIUM_HOOK_ACTOR_REF;
  const run = (args) => execFileSync("git", args, { cwd: repo, stdio: ["ignore", "pipe", "ignore"] });
  fs.mkdirSync(repo);
  delete process.env.PALLIUM_HOOK_ACTOR_REF;
  try {
    run(["init"]);
    run(["config", "user.name", "מפעיל 界"]);
    run(["config", "user.email", "fixture@example.test"]);
    run(["config", "commit.gpgsign", "false"]);
    fs.writeFileSync(path.join(repo, "entry.txt"), "initial");
    run(["add", "entry.txt"]);
    run(["commit", "-m", "initial"]);
    run(["worktree", "add", "--detach", linked]);
    const nested = path.join(linked, "nested-é");
    fs.mkdirSync(nested);
    const hash = run(["rev-list", "--max-parents=0", "HEAD"]).toString().trim();
    for (const cwd of [repo, nested]) {
      assert.deepEqual(await P.deriveGitRefs(cwd), { containerRef: "repo:" + hash.slice(0, 12), repositoryRef: "repo:" + hash });
      assert.equal(await P.deriveActorRef(cwd), "מפעיל 界");
    }
    run(["remote", "add", "origin", "https://git.example.test/Team/Repo.git"]);
    assert.deepEqual(await P.deriveGitRefs(nested),
      { containerRef: "git:git.example.test/team/repo", repositoryRef: "git:git.example.test/Team/Repo" });
  } finally {
    if (previousActor === undefined) delete process.env.PALLIUM_HOOK_ACTOR_REF;
    else process.env.PALLIUM_HOOK_ACTOR_REF = previousActor;
    fs.rmSync(root, { recursive: true, force: true });
  }
});
