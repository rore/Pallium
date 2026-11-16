#!/usr/bin/env node
// Smoke tests for the OpenCode adapter: each hook behaves against the structural
// OpenCode hook shapes with a mocked Pallium daemon + SDK client. No live
// OpenCode and no live Pallium needed. Mirrors the intent of the codex/claude
// integration hook tests (dedup gating, item-and-query -> inject, assistant-turn
// ingest, opt-in post-tool triggers) against the JS surface OpenCode drives.

import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import childProcess from "node:child_process";
import { syncBuiltinESMExports } from "node:module";

const tmpHome = fs.mkdtempSync(path.join(os.tmpdir(), "pallium-oc-plugin-"));
process.env.USERPROFILE = tmpHome;
process.env.HOME = tmpHome;
delete process.env.PALLIUM_POSTTOOL_TRIGGERS;

const nonGitDir = fs.mkdtempSync(path.join(os.tmpdir(), "pallium-oc-cwd-"));

let loadPlugin;
let formatRelay;
test.before(async () => {
  const url = pathToFileURL(path.join(process.cwd(), ".opencode", "plugins", "pallium.mjs"));
  loadPlugin = (await import(url)).default;
  const commonUrl = pathToFileURL(path.join(process.cwd(), ".opencode", "plugins", "pallium-common.mjs"));
  formatRelay = (await import(commonUrl)).formatRelay;
});

test.after(() => {
  for (const d of [tmpHome, nonGitDir]) {
    try { fs.rmSync(d, { recursive: true, force: true }); } catch { /* ignore */ }
  }
});

// --- fetch mock -------------------------------------------------------------

let fetchCalls = [];
function installFetch(routes) {
  fetchCalls = [];
  global.fetch = async (url, init) => {
    const body = init && init.body ? JSON.parse(init.body) : null;
    fetchCalls.push({ url: String(url), method: init && init.method, body });
    const key = Object.keys(routes).find((k) => String(url).includes(k));
    const result = key ? (typeof routes[key] === "function" ? routes[key](body) : routes[key]) : {};
    const resolved = result && typeof result.then === "function" ? await result : result;
    const status = Number.isInteger(resolved?.__status) ? resolved.__status : 200;
    const payload = Number.isInteger(resolved?.__status) ? resolved.payload : resolved;
    return { ok: status >= 200 && status < 300, status, text: async () => JSON.stringify(payload) };
  };
}

function makeClient(messages, logs = null) {
  return {
    app: { log: async (entry) => { if (logs) logs.push(entry); return true; } },
    session: {
      messages: async () => ({ data: messages }),
    },
  };
}

const oneBlock = {
  source_item_id: "request-opencode-1",
  should_inject: true,
  injectable_blocks: [{ title: "Prior Decision", memory_object_id: "ref-xyz", text: "we chose sqlite", expand_available: false }],
};

async function systemTransform(hooks, sessionID) {
  const output = { system: [] };
  await hooks["experimental.chat.system.transform"]({ message: { sessionID } }, output);
  return output.system;
}
async function messagesTransform(hooks, message, parts) {
  const output = { messages: [{ info: message, parts }] };
  await hooks["experimental.chat.messages.transform"]({}, output);
  return output.messages[0];
}

// --- chat.message -> /item-and-query -> inject ------------------------------

test("chat.message ingests the user prompt and queues memory for the system prompt", async () => {
  installFetch({ "/item-and-query": oneBlock });
  const hooks = await loadPlugin({ client: makeClient([]), directory: nonGitDir });

  const parts = [{ type: "text", text: "How does the injection policy abstention work here?" }];
  const output = { message: { sessionID: "sesA", role: "user" }, parts };
  await hooks["chat.message"]({ metadata: { pallium_work_refs: ["ISSUE-1"] } }, output);

  const iq = fetchCalls.find((c) => c.url.includes("/item-and-query"));
  assert.ok(iq, "should call /item-and-query");
  assert.equal(iq.body.agent_ref, "opencode");
  assert.equal(iq.body.role, "user");
  assert.equal(iq.body.thread_ref, "sesA");
  assert.equal(iq.body.query_trigger_origin, "user_prompt_submit");
  assert.deepEqual(iq.body.metadata.pallium_work_refs, ["ISSUE-1"]);
  assert.match(iq.body.source_id, /^oc-[0-9a-f]{12}$/);
  const modelMessage = await messagesTransform(hooks, output.message, output.parts);
  assert.match(modelMessage.parts[0].text, /<system-reminder>\n\[Pallium scope — /);

  const system = await systemTransform(hooks, "sesA");
  assert.equal(system.length, 1);
  assert.match(system[0], /"request_source_item_id":"request-opencode-1"/);
  assert.match(system[0], /\[Pallium memory — container: path:/);
  assert.match(system[0], /ref:ref-xyz\]/);
assert.match(system[0], /\[End Pallium memory\]/);
  assert.match(system[0], /Relay association enrichment was unavailable/);
});

test("V1 role history keeps the start-name snapshot and links delayed Stop by native parentID", async () => {
  let currentAlias = "planner";
  const relayTurn = (body) => ({
    session: {
      runtime: "opencode", session_ref: "sesRoleHistory", container_ref: body.container_ref,
      alias: currentAlias,
    },
    deliveries: [],
  });
  installFetch({
    "/relay/turn": relayTurn,
    "/item-and-query": oneBlock,
    "/items": [{ source_item_id: "assistant-role-history" }],
  });
  const client = makeClient([{
    info: { role: "user", id: "user-role-turn-1" },
    parts: [{ type: "text", text: "remember this prompt for its exact turn role" }],
  }, {
    info: { role: "assistant", id: "assistant-role-turn-1", parentID: "user-role-turn-1" },
    parts: [{ type: "text", text: "assistant output arrives after ownership changed" }],
  }]);
  const hooks = await loadPlugin({ client, directory: nonGitDir });
  await hooks["chat.message"]({}, {
    message: { sessionID: "sesRoleHistory", role: "user", id: "user-role-turn-1" },
    parts: [{ type: "text", text: "remember this prompt for its exact turn role" }],
  });

  const userCapture = fetchCalls.find((call) => call.url.includes("/item-and-query"));
  assert.equal(userCapture.body.source_turn_id, "user-role-turn-1");
  assert.equal(userCapture.body.relay_name, "planner");
  assert.equal(userCapture.body.relay_attribution_state, "named");
  assert.match(userCapture.body.source_id, /^oc-user-[0-9a-f]{64}$/);

  // Simulate a takeover after prompt admission. The delayed assistant capture
  // must use the source message's parentID, not query current ownership.
  currentAlias = "successor";
  await hooks.event({ event: { type: "session.idle", properties: { sessionID: "sesRoleHistory" } } });
  const assistantCapture = fetchCalls.find((call) => call.url.endsWith("/items"));
  assert.ok(assistantCapture);
  assert.equal(assistantCapture.body[0].source_turn_id, "user-role-turn-1");
  assert.match(assistantCapture.body[0].source_id, /^oc-assistant-[0-9a-f]{64}$/);
  assert.equal(Object.hasOwn(assistantCapture.body[0], "relay_name"), false);
  assert.equal(fetchCalls.filter((call) => call.url.includes("/relay/turn")).length, 1);
});

test("V1 retries of one in-flight native message share one immutable Relay snapshot", async () => {
  const P = await import(pathToFileURL(path.join(process.cwd(), ".opencode", "plugins", "pallium-common.mjs")));
  const previousActor = process.env.PALLIUM_HOOK_ACTOR_REF;
  process.env.PALLIUM_HOOK_ACTOR_REF = "concurrent-actor";
  const container = P.pathContainer(nonGitDir);
  const run = async (mode, gate) => {
    const sessionID = mode === "cold" ? "sesRoleRetry" : "sesRoleRetry_" + mode;
    let enterTurn, releaseTurn, timer, first, second;
    const entered = new Promise((resolve) => { enterTurn = resolve; });
    const turn = new Promise((resolve) => { releaseTurn = resolve; });
    installFetch({
      "/relay/turn": async (body) => {
        enterTurn();
        await turn;
        return { session: { runtime: "opencode", session_ref: sessionID,
          container_ref: body.container_ref, alias: "planner" }, deliveries: [] };
      },
      "/item-and-query": oneBlock,
      "/query": oneBlock,
    });
    const hooks = await loadPlugin({ client: makeClient([]), directory: nonGitDir });
    const output = {
      message: { sessionID, role: "user", id: "user-role-retry" },
      parts: [{ type: "text", text: "retry the exact same native message without changing its turn snapshot" }],
    };
    try {
      if (mode === "pinned" || mode === "removed") P.pinContainer(sessionID, container, undefined, "concurrent-actor");
      first = hooks["chat.message"]({}, output);
      if (gate) await gate.started;
      second = hooks["chat.message"]({}, output);
      await Promise.race([entered, new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error(`${mode}: Relay turn was not reached`)), 5000);
      })]);
      assert.equal(fetchCalls.filter((call) => call.url.includes("/relay/turn")).length, 1);
      assert.equal(P.getPinnedContainer(sessionID), container, `${mode}: sibling published its actual derived pin`);
      assert.equal(P.getPinnedActor(sessionID), "concurrent-actor");
      if (mode === "removed") P.removeSessionPin(sessionID);
      if (mode === "retired") {
        await hooks.event({ event: { type: "session.deleted", properties: { sessionID } } });
        await hooks.event({ event: { type: "session.created", properties: { sessionID } } });
        assert.equal(P.getPinnedContainer(sessionID), container, "successor deliberately has the same pin");
      }
      gate?.release();
      releaseTurn();
      await Promise.all([first, second]);
      const captures = fetchCalls.filter((call) => call.url.includes("/item-and-query"));
      if (mode === "removed" || mode === "retired") {
        assert.equal(captures.length, 0, `${mode}: old callbacks cannot capture or restore a removed pin`);
        assert.equal(P.getPinnedContainer(sessionID), mode === "removed" ? null : container);
        if (mode === "retired") assert.ok((await systemTransform(hooks, sessionID)).length > 0,
          "retired callbacks cannot purge the successor's output");
      } else if (mode === "conflicting") {
        assert.equal(captures.length, 1, "held discovery of a different container cannot adopt the sibling's pin");
        assert.equal(captures[0].body.container_ref, container);
        assert.equal(captures[0].body.actor_ref, "concurrent-actor");
        assert.equal(P.getPinnedContainer(sessionID), container);
      } else {
        assert.equal(captures.length, 2, `${mode}: both concurrent retries retain capture authority`);
        assert.deepEqual(captures.map((call) => call.body.source_turn_id), ["user-role-retry", "user-role-retry"]);
        assert.deepEqual(captures.map((call) => call.body.relay_name), ["planner", "planner"]);
        assert.equal(captures[0].body.source_id, captures[1].body.source_id);
        assert.ok(captures.every((call) => call.body.container_ref === container && call.body.actor_ref === "concurrent-actor"));
      }
      assert.equal(fetchCalls.filter((call) => call.url.includes("/relay/turn")).length, 1);
    } finally {
      clearTimeout(timer);
      gate?.release();
      releaseTurn();
      await Promise.allSettled([first, second]);
      P.removeSessionPin(sessionID);
    }
  };
  try {
    await run("cold");
    await run("pinned");
    for (const mode of ["matching", "conflicting", "removed", "retired"]) {
      // A whitespace root has the same path fallback as the real non-repository
      // sibling. A canonical remote instead derives a conflicting container.
      await heldGit(mode === "conflicting" ? "remote get-url origin" : "rev-list --max-parents=0 HEAD",
        mode === "conflicting" ? "https://git.example.test/Other/Repo.git" : "\n",
        (gate) => run(mode, gate));
    }
  } finally {
    if (previousActor === undefined) delete process.env.PALLIUM_HOOK_ACTOR_REF;
    else process.env.PALLIUM_HOOK_ACTOR_REF = previousActor;
  }
});

test("V1 same-ID retry after ingestion failure reuses the captured turn snapshot", async () => {
  let identity = "planner";
  let ingestionAttempts = 0;
  installFetch({
    "/relay/turn": (body) => ({
      session: {
        runtime: "opencode", session_ref: "sesRoleFailureRetry", container_ref: body.container_ref,
        alias: identity,
      },
      deliveries: [],
    }),
    "/item-and-query": () => {
      ingestionAttempts += 1;
      return ingestionAttempts === 1
        ? { __status: 503, payload: { detail: "temporary failure" } }
        : oneBlock;
    },
  });
  const hooks = await loadPlugin({ client: makeClient([]), directory: nonGitDir });
  const output = {
    message: { sessionID: "sesRoleFailureRetry", role: "user", id: "user-role-failure-retry" },
    parts: [{ type: "text", text: "retry after a transient ingestion failure with the exact same native message" }],
  };
  await hooks["chat.message"]({}, output);
  identity = "successor";
  await hooks["chat.message"]({}, output);

  const captures = fetchCalls.filter((call) => call.url.includes("/item-and-query"));
  assert.equal(captures.length, 2);
  assert.deepEqual(captures.map((call) => call.body.source_turn_id), [
    "user-role-failure-retry", "user-role-failure-retry",
  ]);
  assert.deepEqual(captures.map((call) => call.body.relay_name), ["planner", "planner"]);
  assert.equal(fetchCalls.filter((call) => call.url.includes("/relay/turn")).length, 1);
});

test("chat.message treats empty response work-ref metadata as authoritative", async () => {
  installFetch({ "/item-and-query": { ...oneBlock, work_ref_metadata: {} } });
  const hooks = await loadPlugin({ client: makeClient([]), directory: nonGitDir });
  const output = { message: { sessionID: "sesAuthoritativeEmpty", role: "user" }, parts: [{ type: "text", text: "Explain this substantial work reference flow in detail" }] };
  await hooks["chat.message"]({}, output);
  const system = await systemTransform(hooks, "sesAuthoritativeEmpty");
  assert.doesNotMatch(system.join("\n"), /Relay association enrichment was unavailable/);
});
test("chat.message skips short prompts, slash-commands, and duplicates", async () => {
  installFetch({ "/item-and-query": oneBlock });
  const hooks = await loadPlugin({ client: makeClient([]), directory: nonGitDir });

  await hooks["chat.message"]({}, { message: { sessionID: "sesB" }, parts: [{ type: "text", text: "hi" }] });
  await hooks["chat.message"]({}, { message: { sessionID: "sesB" }, parts: [{ type: "text", text: "/commit please do it now" }] });
  assert.equal(fetchCalls.filter((c) => c.url.includes("/item-and-query")).length, 0, "short + slash prompts must not ingest");

  const longPrompt = [{ type: "text", text: "please investigate the retrieval grounding gates in detail" }];
  await hooks["chat.message"]({}, { message: { sessionID: "sesB" }, parts: longPrompt });
  assert.equal(fetchCalls.filter((c) => c.url.includes("/item-and-query")).length, 1, "first real prompt ingests");
  await hooks["chat.message"]({}, { message: { sessionID: "sesB" }, parts: longPrompt });
  assert.equal(fetchCalls.filter((c) => c.url.includes("/item-and-query")).length, 1, "identical prompt within the dedup window is skipped");
});

// --- event: session.created -> orientation ----------------------------------

test("event session.created runs an orientation query and queues it for injection", async () => {
  installFetch({ "/query": oneBlock });
  const hooks = await loadPlugin({ client: makeClient([]), directory: nonGitDir });

  await hooks.event({ event: { type: "session.created", properties: { sessionID: "sesC" } } });
  const q = fetchCalls.find((c) => c.url.includes("/query"));
  assert.ok(q, "should call /query for orientation");
  assert.equal(q.body.trigger_origin, "session_start_orientation");

  const system = await systemTransform(hooks, "sesC");
  assert.equal(system.length, 1);
  assert.match(system[0], /\[Pallium memory/);

  // Orientation runs once per session.
  const before = fetchCalls.length;
  await hooks.event({ event: { type: "session.created", properties: { sessionID: "sesC" } } });
  assert.equal(fetchCalls.length, before, "orientation must not re-run for the same session");
});

// --- event: session.idle -> ingest assistant turn ---------------------------

test("event session.idle reads the last assistant message and ingests it via /items", async () => {
  const messages = [
    { info: { role: "user", id: "u1" }, parts: [{ type: "text", text: "do the thing" }] },
    {
      info: { role: "assistant", id: "a1", parentID: " u1 " },
      parts: [
        { type: "text", text: "Done. I edited the file." },
        { type: "tool", tool: "read", state: { status: "completed", input: { filePath: "src/a.js" }, output: "" } },
        { type: "tool", tool: "edit", state: { status: "completed", input: { filePath: "src/b.js" } } },
      ],
    },
  ];
  const logs = [];
  installFetch({ "/items": [{ source_item_id: "sid-1" }] });
  const hooks = await loadPlugin({ client: makeClient(messages, logs), directory: nonGitDir });

  await hooks.event({ event: { type: "session.idle", properties: { sessionID: "sesD" } } });
  const items = fetchCalls.find((c) => c.url.includes("/items"));
  assert.ok(items, "should call /items");
  assert.ok(Array.isArray(items.body), "/items body is an array of one item");
  const item = items.body[0];
  assert.equal(item.role, "assistant");
  assert.equal(item.agent_ref, "opencode");
  assert.equal(item.thread_ref, "sesD");
  assert.equal(item.content, "Done. I edited the file.");
  assert.equal(Object.hasOwn(item, "source_turn_id"), false, "missing native parent linkage stays uncorrelated");
  assert.ok(item.metadata && item.metadata.agent_work_trace_turn, "attaches work-trace metadata");
  assert.deepEqual(item.metadata.agent_work_trace_turn.files_read, ["src/a.js"]);
  assert.deepEqual(item.metadata.agent_work_trace_turn.files_modified, ["src/b.js"]);
  assert.equal(logs.some((entry) => /Relay association enrichment was unavailable/.test(entry.body?.message || "")), true);

  // Idempotent: a second session.idle for the same turn does not re-ingest.
  const before = fetchCalls.length;
  await hooks.event({ event: { type: "session.idle", properties: { sessionID: "sesD" } } });
  assert.equal(fetchCalls.length, before, "same assistant message must not be re-ingested");
});

test("assistant ingest treats empty response work-ref metadata as authoritative", async () => {
  const logs = [];
  const messages = [{ info: { role: "assistant", id: "aAuthoritativeEmpty" }, parts: [{ type: "text", text: "Recorded without a stale warning." }] }];
  installFetch({ "/items": [{ source_item_id: "sid-authoritative-empty", work_ref_metadata: {} }] });
  const hooks = await loadPlugin({ client: makeClient(messages, logs), directory: nonGitDir });
  await hooks.event({ event: { type: "session.idle", properties: { sessionID: "sesAssistantAuthoritativeEmpty" } } });
  assert.equal(fetchCalls.find((call) => call.url.includes("/items")).body[0].metadata.pallium_relay_work_refs_status, "unavailable");
  assert.equal(logs.some((entry) => /Relay association enrichment was unavailable/.test(entry.body?.message || "")), false);
});
test("a failed /items ingest is retried on a later lifecycle event", async () => {
  const messages = [
    { info: { role: "assistant", id: "aRetry" }, parts: [{ type: "text", text: "Ingest me, please." }] },
  ];
  // First attempt: daemon unreachable -> palliumRequest returns null.
  global.fetch = async () => { throw new Error("ECONNREFUSED"); };
  fetchCalls = [];
  const hooks = await loadPlugin({ client: makeClient(messages), directory: nonGitDir });
  await hooks.event({ event: { type: "session.idle", properties: { sessionID: "sesRetryIngest" } } });

  // Second attempt: daemon back up -> the turn must be retried, not skipped.
  installFetch({ "/items": [{ source_item_id: "sid-r" }] });
  await hooks.event({ event: { type: "session.idle", properties: { sessionID: "sesRetryIngest" } } });
  assert.equal(fetchCalls.filter((c) => c.url.includes("/items")).length, 1, "failed turn is retried once daemon recovers");
});

test("a JSON HTTP-error /items response (4xx/5xx) is treated as failure and retried", async () => {
  const messages = [
    { info: { role: "assistant", id: "aHttpErr" }, parts: [{ type: "text", text: "Persist me after a 500." }] },
  ];
  // First attempt: 500 with a JSON error body -> palliumRequest must return null.
  fetchCalls = [];
  global.fetch = async (url, init) => {
    fetchCalls.push({ url: String(url), method: init && init.method });
    return { ok: false, status: 500, text: async () => JSON.stringify({ error: "boom" }) };
  };
  const hooks = await loadPlugin({ client: makeClient(messages), directory: nonGitDir });
  await hooks.event({ event: { type: "session.idle", properties: { sessionID: "sesHttpErr" } } });
  assert.equal(fetchCalls.filter((c) => c.url.includes("/items")).length, 1, "first attempt hits /items");

  // Second attempt succeeds -> retried, not skipped.
  installFetch({ "/items": [{ source_item_id: "sid-h" }] });
  await hooks.event({ event: { type: "session.idle", properties: { sessionID: "sesHttpErr" } } });
  assert.equal(fetchCalls.filter((c) => c.url.includes("/items")).length, 1, "HTTP-error turn retried on recovery");
});

// --- cross-session isolation + state cleanup --------------------------------

test("system.transform does not bleed one session's private blocks into another", async () => {
  installFetch({ "/item-and-query": oneBlock });
  const hooks = await loadPlugin({ client: makeClient([]), directory: nonGitDir });
  // Two sessions each queue their own container-scoped, private memory.
  const p = (t) => [{ type: "text", text: t }];
  await hooks["chat.message"]({}, { message: { sessionID: "sX" }, parts: p("investigate the retrieval grounding gates thoroughly") });
  await hooks["chat.message"]({}, { message: { sessionID: "sY" }, parts: p("explain the container derivation logic in depth") });

  // A transform that can't resolve a session id must NOT drain either bucket
  // (both remain pending), since blocks are private + container-scoped.
  const ambiguous = { system: [] };
  await hooks["experimental.chat.system.transform"]({}, ambiguous);
  assert.deepEqual(ambiguous.system, [], "no drain when the session is ambiguous and >1 pending");

  // A transform for sX drains only sX's block.
  const forX = await systemTransform(hooks, "sX");
  assert.equal(forX.length, 1);
  // sY's block is still pending and only surfaces for sY.
  const forY = await systemTransform(hooks, "sY");
  assert.equal(forY.length, 1);
});

test("session.deleted purges pending per-session state", async () => {
  installFetch({ "/item-and-query": oneBlock });
  const hooks = await loadPlugin({ client: makeClient([]), directory: nonGitDir });
  await hooks["chat.message"]({}, { message: { sessionID: "sZ" }, parts: [{ type: "text", text: "a real prompt about memory injection budgets" }] });
  await hooks.event({ event: { type: "session.deleted", properties: { sessionID: "sZ" } } });
  const system = await systemTransform(hooks, "sZ");
  assert.deepEqual(system, []);
});

// --- experimental.session.compacting -> ingest before compaction -----------

test("experimental.session.compacting ingests the latest assistant turn via /items", async () => {
  const messages = [
    { info: { role: "user", id: "u1" }, parts: [{ type: "text", text: "work" }] },
    { info: { role: "assistant", id: "a9" }, parts: [{ type: "text", text: "Captured before compaction." }] },
  ];
  installFetch({ "/items": [{ source_item_id: "sid-c" }] });
  const hooks = await loadPlugin({ client: makeClient(messages), directory: nonGitDir });

  await hooks["experimental.session.compacting"]({ sessionID: "sesCompact" });
  const items = fetchCalls.find((c) => c.url.includes("/items"));
  assert.ok(items, "compaction should ingest via /items");
  assert.equal(items.body[0].role, "assistant");
  assert.equal(items.body[0].content, "Captured before compaction.");

  // Shares the idempotence guard with session.idle: a following idle for the
  // same turn must not re-ingest.
  const before = fetchCalls.length;
  await hooks.event({ event: { type: "session.idle", properties: { sessionID: "sesCompact" } } });
  assert.equal(fetchCalls.length, before, "already-ingested turn is not re-sent on idle");
});

test("assistant turns without a message id are ingested once (content-hash dedup)", async () => {
  const messages = [
    { info: { role: "assistant" }, parts: [{ type: "text", text: "no id on this message" }] },
  ];
  installFetch({ "/items": [{ source_item_id: "sid-n" }] });
  const hooks = await loadPlugin({ client: makeClient(messages), directory: nonGitDir });
  await hooks.event({ event: { type: "session.idle", properties: { sessionID: "sesNoId" } } });
  assert.equal(fetchCalls.filter((c) => c.url.includes("/items")).length, 1);
  await hooks.event({ event: { type: "session.idle", properties: { sessionID: "sesNoId" } } });
  assert.equal(fetchCalls.filter((c) => c.url.includes("/items")).length, 1, "content-hash dedup prevents re-ingest");
});

// --- tool.execute.after opt-in ----------------------------------------------

test("tool.execute.after is inert unless PALLIUM_POSTTOOL_TRIGGERS=1", async () => {
  installFetch({ "/query": oneBlock });
  const hooks = await loadPlugin({ client: makeClient([]), directory: nonGitDir });
  await hooks["tool.execute.after"](
    { tool: "bash", sessionID: "sesE" },
    { output: "command failed: exit code: 1", metadata: { error: true } },
  );
  assert.equal(fetchCalls.length, 0, "triggers off by default -> no daemon calls");
});

test("tool.execute.after fires a failure query when explicitly enabled", async () => {
  process.env.PALLIUM_POSTTOOL_TRIGGERS = "1";
  try {
    installFetch({ "/query": oneBlock });
    // Re-import a fresh module instance so the env flag is re-read at load.
    const url = pathToFileURL(path.join(process.cwd(), ".opencode", "plugins", "pallium.mjs")) + `?t=${Date.now()}`;
    const freshLoad = (await import(url)).default;
    const hooks = await freshLoad({ client: makeClient([]), directory: nonGitDir });
    await hooks["tool.execute.after"](
      { tool: "bash", sessionID: "sesF" },
      { output: "npm test\nTests failed: 3 failing\ncommand failed", args: { command: "npm test" }, metadata: { error: true } },
    );
    const q = fetchCalls.find((c) => c.url.includes("/query"));
    assert.ok(q, "enabled triggers should query the daemon");
    assert.equal(q.body.trigger_origin, "post_tool_failure");
  } finally {
    delete process.env.PALLIUM_POSTTOOL_TRIGGERS;
  }
});

test("tool.execute.after escalates to a retry_threshold query after repeated failures", async () => {
  process.env.PALLIUM_POSTTOOL_TRIGGERS = "1";
  try {
    installFetch({ "/query": { should_inject: false, injectable_blocks: [] } });
    const url = pathToFileURL(path.join(process.cwd(), ".opencode", "plugins", "pallium.mjs")) + `?t=${Date.now()}-retry`;
    const freshLoad = (await import(url)).default;
    const hooks = await freshLoad({ client: makeClient([]), directory: nonGitDir });
    const failOut = { output: "make build\ncommand failed", args: { command: "make build" }, metadata: { error: true } };
    // Same normalized target failing 3x crosses RETRY_THRESHOLD.
    for (let i = 0; i < 3; i++) {
      await hooks["tool.execute.after"]({ tool: "bash", sessionID: "sesRetry" }, failOut);
    }
    const origins = fetchCalls.filter((c) => c.url.includes("/query")).map((c) => c.body.trigger_origin);
    assert.ok(origins.includes("post_tool_failure"), "each failure fires a failure query");
    assert.ok(origins.includes("retry_threshold"), "3rd repeated failure escalates to retry_threshold");
  } finally {
    delete process.env.PALLIUM_POSTTOOL_TRIGGERS;
  }
});

// --- fail-safe --------------------------------------------------------------
test("hooks never throw even when the daemon is unreachable", async () => {
  global.fetch = async () => { throw new Error("ECONNREFUSED"); };
  const hooks = await loadPlugin({ client: makeClient([]), directory: nonGitDir });
  // None of these should reject.
  await hooks["chat.message"]({}, { message: { sessionID: "sesG" }, parts: [{ type: "text", text: "a real prompt about memory retrieval systems" }] });
  await hooks.event({ event: { type: "session.created", properties: { sessionID: "sesG" } } });
  await hooks.event({ event: { type: "session.idle", properties: { sessionID: "sesG" } } });
  const system = await systemTransform(hooks, "sesG");
  assert.ok(Array.isArray(system), "system.transform still returns cleanly");
});

test("chat.message injects a near-budget Relay preview and acknowledges after mutation", async () => {
  const basePreview = {
    delivery_id: "d-1", claim_token: "claim-1", message_id: "m-1",
    sender_runtime: "claude-code", sender_session_ref: "sender-a",
    recipient: "opencode:sesRelay", redacted: false, in_reply_to: null,
    created_at: "2026-08-25T10:00:00+00:00",
    expires_at: "2026-08-26T10:00:00+00:00",
    payload_offset: 0, payload_total_chars: 16000, content_truncated: true,
    attempts: 2,
  };
  let low = 1;
  let high = 15999;
  while (low < high) {
    const middle = Math.ceil((low + high) / 2);
    const candidate = { ...basePreview, payload: "😀".repeat(middle), next_offset: middle };
    if ([...formatRelay([candidate]).text].length <= 2360) low = middle;
    else high = middle - 1;
  }
  const preview = { ...basePreview, payload: "😀".repeat(low), next_offset: low };
  assert.ok([...formatRelay([preview]).text].length > 2350);

  const relay = {
    deliveries: [{
      delivery_id: "d-skipped", claim_token: "claim-skipped", message_id: "m-skipped",
      sender_runtime: "claude-code", sender_session_ref: "sender-a",
      recipient: "opencode:sesRelay", payload: "bad\u0000value",
      redacted: false, in_reply_to: null,
      created_at: "2026-08-25T10:00:00+00:00", expires_at: "2026-08-26T10:00:00+00:00",
    }, preview],
    has_more: true,
    remaining_count: 1,
  };
  installFetch({
    "/item-and-query": oneBlock,
    "/relay/turn": relay,
    "/relay/deliveries/ack": { delivery_id: "d-1", state: "delivered" },
  });
  const hooks = await loadPlugin({ client: makeClient([]), directory: nonGitDir });
  const output = {
    message: { sessionID: "sesRelay", role: "user", system: "existing system" },
    parts: [{ type: "text", text: "please inspect this migration approach carefully" }],
  };
  await hooks["chat.message"]({}, output);
  assert.equal(fetchCalls.filter((call) => call.url.includes("/relay/deliveries/ack")).length, 0);
  const modelMessage = await messagesTransform(hooks, output.message, output.parts);
  const modelText = modelMessage.parts[0].text;
  assert.ok(modelText.startsWith("please inspect this migration approach carefully\n\n<system-reminder>\n[Pallium Relay"));
  const relayStart = modelText.indexOf("[Pallium Relay");
  const scopeStart = modelText.indexOf("\n\n[Pallium scope", relayStart);
  const relayText = modelText.slice(relayStart, scopeStart);
  assert.ok(relayStart >= 0 && scopeStart > relayStart);
  assert.ok([...relayText].length <= 2400);
  assert.match(relayText, /Lower-authority context/);
  assert.match(relayText, /claim_attempt: 2\npossible_redelivery: true/);
  assert.match(relayText, /Check exact delivery_id in context\/artifacts\./);
  assert.match(relayText, /ACK: receipt, not completion/);
  assert.match(relayText, /Pallium Relay: \d+ characters omitted/);
  assert.match(relayText, /pallium_relay_status\(message_id="m-1", offset=\d+\)/);
  const turn = fetchCalls.find((call) => call.url.includes("/relay/turn"));
  assert.equal(turn.body.runtime, "opencode");
  assert.equal(turn.body.session_ref, "sesRelay");
  assert.equal(turn.body.max_chars, 2360);
  assert.match(modelText, /\[Relay: 1 more; Pallium continues\.\]/);
  const ack = fetchCalls.find((call) => call.url.includes("/relay/deliveries/ack"));
  assert.equal(fetchCalls.filter((call) => call.url.includes("/relay/deliveries/ack")).length, 1);
  assert.deepEqual(
    { delivery_id: ack.body.delivery_id, claim_token: ack.body.claim_token },
    { delivery_id: "d-1", claim_token: "claim-1" },
  );
});

test("V1 attaches a pageable prefix and its sibling before separate acknowledgements", async () => {
  const makeDelivery = (id, payload) => ({
    delivery_id: `d-${id}`, claim_token: `claim-${id}`, message_id: `m-${id}`,
    sender_runtime: "claude-code", sender_session_ref: "sender-a", payload,
    created_at: "2026-08-25T10:00:00+00:00", attempts: 1,
  });
  const first = { ...makeDelivery(1, "界".repeat(600)), payload_offset: 0,
    payload_total_chars: 8000, content_truncated: true, next_offset: 600 };
  const second = makeDelivery(2, "ordinary sibling");
  installFetch({
    "/relay/turn": { deliveries: [first, second], has_more: true, remaining_count: 1 },
    "/relay/deliveries/ack": { state: "delivered" },
  });
  const hooks = await loadPlugin({ client: makeClient([]), directory: nonGitDir });
  const output = {
    message: { sessionID: "sesBatch", role: "user" },
    parts: [{ type: "text", text: "inspect this migration approach carefully" }],
  };
  await hooks["chat.message"]({}, output);
  const acks = () => fetchCalls.filter((call) => call.url.includes("/relay/deliveries/ack"));
  assert.equal(acks().length, 0);
  const model = await messagesTransform(hooks, output.message, output.parts);
  assert.match(model.parts[0].text, /offset=600[\s\S]*ordinary sibling[\s\S]*\[Relay: 1 more;/);
  assert.deepEqual(acks().map((call) => call.body.delivery_id), ["d-1", "d-2"]);
});

test("chat.message with no delivery exposes current Relay identity", async () => {
  installFetch({ "/relay/turn": { deliveries: [] } });
  const hooks = await loadPlugin({ client: makeClient([]), directory: nonGitDir });
  const output = { message: { sessionID: "sesIdentity", role: "user" }, parts: [{ type: "text", text: "hi" }] };
  await hooks["chat.message"]({}, output);
  const modelMessage = await messagesTransform(hooks, output.message, output.parts);
  assert.match(modelMessage.parts[0].text, /<system-reminder>\n\[Pallium scope — /);
  assert.match(modelMessage.parts[0].text, /"thread_ref":"sesIdentity"/);
  assert.match(modelMessage.parts[0].text, /"agent_ref":"opencode"/);
});

test("Relay claim survives a transform with no model-visible text part", async () => {
  installFetch({
    "/relay/turn": { deliveries: [{
      delivery_id: "d-retry", claim_token: "claim-retry", message_id: "m-retry",
      sender_runtime: "codex", sender_session_ref: "sender-retry",
      recipient: "opencode:sesRetry", payload: "retry me", redacted: false,
      in_reply_to: null, created_at: "2026-08-25T10:00:00+00:00",
      expires_at: "2026-08-26T10:00:00+00:00",
    }] },
    "/relay/deliveries/ack": { delivery_id: "d-retry", state: "delivered" },
  });
  const hooks = await loadPlugin({ client: makeClient([]), directory: nonGitDir });
  const message = { sessionID: "sesRetry", role: "user" };
  await hooks["chat.message"]({}, { message, parts: [{ type: "image", url: "data:image/png;base64,x" }] });
  await hooks["experimental.chat.messages.transform"]({}, { messages: [{ info: message, parts: [] }] });
  assert.equal(fetchCalls.filter((call) => call.url.includes("/relay/deliveries/ack")).length, 0);
  await hooks["chat.message"]({}, { message, parts: [{ type: "text", text: "next turn" }] });
  assert.equal(fetchCalls.filter((call) => call.url.includes("/relay/turn")).length, 1);
  const modelMessage = await messagesTransform(hooks, message, [{ type: "text", text: "next turn" }]);
  assert.match(modelMessage.parts[0].text, /retry me/);
  assert.equal(fetchCalls.filter((call) => call.url.includes("/relay/deliveries/ack")).length, 1);
});
test("chat.message without mutable message does not claim Relay", async () => {
  installFetch({ "/relay/turn": { deliveries: [] } });
  const hooks = await loadPlugin({ client: makeClient([]), directory: nonGitDir });
  await hooks["chat.message"]({ sessionID: "sesNoMessage" }, { parts: [{ type: "text", text: "hi" }] });
  assert.equal(fetchCalls.filter((call) => call.url.includes("/relay/turn")).length, 0);
});
test("session.deleted closes Relay with pinned scope and removes the pin", async () => {
  installFetch({ "/relay/sessions/close": { state: "closed" } });
  const pinDir = path.join(tmpHome, ".pallium", "hooks", "state", "sessions");
  const pinFile = path.join(pinDir, "sesClose.json");
  fs.mkdirSync(pinDir, { recursive: true });
  fs.writeFileSync(pinFile, JSON.stringify({
    container_ref: "git:example.test/team/project",
    actor_ref: "Relay Operator",
  }));
  const hooks = await loadPlugin({ client: makeClient([]), directory: nonGitDir });
  await hooks.event({ event: { type: "session.deleted", properties: { sessionID: "sesClose" } } });
  const close = fetchCalls.find((call) => call.url.includes("/relay/sessions/close"));
  assert.ok(close);
  assert.equal(close.body.runtime, "opencode");
  assert.equal(close.body.session_ref, "sesClose");
  assert.equal(close.body.container_ref, "git:example.test/team/project");
  assert.equal("actor_ref" in close.body, false);
  assert.equal(fs.existsSync(pinFile), false);
});


test("assistant ingest includes structural work references", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "pallium-oc-plugin-work-ref-"));
  try {
    fs.mkdirSync(path.join(dir, ".git"));
    fs.writeFileSync(path.join(dir, ".git", "HEAD"), "ref: refs/heads/fix/item\n");
    const tasks = path.join(dir, ".agent-workflow", "tasks");
    fs.mkdirSync(tasks, { recursive: true });
    fs.writeFileSync(
      path.join(tasks, "item.md"),
      "<!-- agent-workflow:start -->\n<!-- agent-workflow:end -->",
    );
    installFetch({ "/items": [{ source_item_id: "sid-work-ref" }] });
    const messages = [
      { info: { role: "assistant", id: "a-work-ref" }, parts: [{ type: "text", text: "Done." }] },
    ];
    const hooks = await loadPlugin({ client: makeClient(messages), directory: dir });
    await hooks.event({ event: { type: "session.idle", properties: { sessionID: "ses-work-ref" } } });
    const item = fetchCalls.find((call) => call.url.includes("/items")).body[0];
    if (process.platform === "win32") {
      assert.equal(item.metadata?.pallium_work_refs, undefined);
    } else {
      assert.deepEqual(item.metadata.pallium_work_refs, [
        "git-branch:fix/item",
        "agent-workflow:item",
      ]);
    }
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});


test("chat.message does not suppress ingestion for an oversized explicit-ref list", async () => {
  installFetch({ "/item-and-query": oneBlock });
  const hooks = await loadPlugin({ client: makeClient([]), directory: nonGitDir });
  const refs = Array(200000).fill("KEEP");
  await hooks["chat.message"](
    { metadata: { pallium_work_refs: refs } },
    {
      message: { sessionID: "sesHugeRefs", role: "user" },
      parts: [{ type: "text", text: "Continue this substantial task safely" }],
    },
  );
  const request = fetchCalls.find((call) => call.url.includes("/item-and-query"));
  assert.ok(request, "oversized explicit refs must not suppress ordinary ingestion");
  assert.equal(request.body.metadata.pallium_work_refs.length, refs.length);
});

test("Relay scope carries the first structural OpenCode work_ref when supported", async (t) => {
  if (process.platform === "win32") return t.skip("structural discovery is intentionally disabled on Windows");
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "pallium-oc-relay-work-ref-"));
  try {
    fs.mkdirSync(path.join(dir, ".git"));
    fs.writeFileSync(path.join(dir, ".git", "HEAD"), "ref: refs/heads/fix/relay\n");
    const tasks = path.join(dir, ".agent-workflow", "tasks"); fs.mkdirSync(tasks, { recursive: true });
    fs.writeFileSync(path.join(tasks, "relay.md"), "<!-- agent-workflow:start -->\n<!-- agent-workflow:end -->");
    installFetch({
      "/item-and-query": oneBlock,
      "/relay/turn": { deliveries: [{
        delivery_id: "d-r", claim_token: "c-r", message_id: "m-r", sender_runtime: "claude-code",
        sender_session_ref: "sender", payload: "handoff", created_at: "2026-01-01T00:00:00Z",
      }] },
      "/relay/deliveries/ack": { delivery_id: "d-r", state: "delivered" },
    });
    const hooks = await loadPlugin({ client: makeClient([]), directory: dir });
    const output = { message: { sessionID: "sesRelayRef", role: "user" }, parts: [{ type: "text", text: "inspect this substantial migration carefully" }] };
    await hooks["chat.message"]({}, output);
    const modelMessage = await messagesTransform(hooks, output.message, output.parts);
    assert.match(modelMessage.parts[0].text, /"work_ref":"git-branch:fix\/relay"/);
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});

test("chat.message warns when associated refs exceed the five-ref History limit", async () => {
  const associated = ["work:v1:" + "a".repeat(64), "work:v1:" + "b".repeat(64)];
  installFetch({
    "/relay/turn": {
      deliveries: [], has_more: false, remaining_count: 0,
      structural_work_refs_status: "complete",
      work_refs: associated.map((work_ref) => ({ origin: "explicit", work_ref })),
    },
    "/item-and-query": {
      ...oneBlock,
      work_ref_metadata: {
        pallium_relay_work_refs_status: "partial",
        pallium_work_refs: ["s", "white-space", "strasse", "one", "two"],
        pallium_work_refs_omitted_registry: associated,
        pallium_work_refs_diagnostics: {
          omitted_valid_count: 4,
          invalid_count: 0,
          caller_input_count: 10,
          caller_examined_count: 10,
          caller_input_truncated: false,
          counts_complete: true,
        },
      },
    },
  });
  const hooks = await loadPlugin({ client: makeClient([]), directory: nonGitDir });
  await hooks["chat.message"](
    { metadata: { pallium_work_refs: ["s", "S", "white space", "white_space", "Straße", "STRASSE", "one", "two", "three", "four"] } },
    {
      message: { sessionID: "sesWorkRefWarning", role: "user" },
      parts: [{ type: "text", text: "Continue this substantial associated task safely" }],
    },
  );
  const system = (await systemTransform(hooks, "sesWorkRefWarning")).join("\n");
  assert.match(system, /not searchable from this turn/);
  assert.ok(associated.every((key) => system.includes(key)));
  assert.ok([...system].length <= 2400);
});

test("V1 lifetime authority covers every first entry and keeps retired callbacks inert", async () => {
  const previousTrigger = process.env.PALLIUM_POSTTOOL_TRIGGERS;
  const previousActor = process.env.PALLIUM_HOOK_ACTOR_REF;
  process.env.PALLIUM_POSTTOOL_TRIGGERS = "1";
  process.env.PALLIUM_HOOK_ACTOR_REF = "fixture-actor";
  const commonUrl = pathToFileURL(path.join(process.cwd(), ".opencode", "plugins", "pallium-common.mjs"));
  const P = await import(commonUrl);
  const freshLoad = (await import(pathToFileURL(path.join(process.cwd(), ".opencode", "plugins", "pallium.mjs")) +
    "?oc6-lifetime-first-entry")).default;
  try {
    for (const first of ["create", "assistant", "tool", "chat-without-id", "chat-with-id"]) {
      const sessionID = "ses_v1_life_" + first;
      installFetch({ "/query": oneBlock, "/item-and-query": oneBlock,
        "/items": [{ source_item_id: "v1-lifetime-answer" }] });
      const messages = [{ info: { role: "user", id: "msg_life_user" }, parts: [{ type: "text", text: "ordinary work" }] },
        { info: { role: "assistant", id: "msg_life_answer", parentID: "msg_life_user" },
          parts: [{ type: "text", text: "completed ordinary work שלום" }] }];
      const hooks = await freshLoad({ client: makeClient(messages), directory: nonGitDir });
      const event = (type) => hooks.event({ event: { type, properties: { sessionID } } });
      const chat = (withId, text = "substantial lifetime work without losing caller identity") => hooks["chat.message"]({}, {
        message: { sessionID, role: "user", ...(withId ? { id: "msg_life_start" } : {}) },
        parts: [{ type: "text", text }],
      });
      const tool = () => hooks["tool.execute.after"]({ sessionID, tool: "bash" },
        { output: "command failed", args: { command: "test" }, metadata: { error: true } });
      try {
        if (first === "create") await event("session.created");
        else if (first === "assistant") await event("session.idle");
        else if (first === "tool") await tool();
        else await chat(first === "chat-with-id");
        assert.ok(fetchCalls.length > 0, `${first}: an unseen/resumed session still works`);
        await event("session.deleted");
        const retired = fetchCalls.length;
        await event("session.idle");
        await hooks["experimental.session.compacting"]({ sessionID });
        await tool();
        await event("session.deleted");
        assert.equal(fetchCalls.length, retired, `${first}: passive callbacks and duplicate close cannot reactivate a retired ID`);
        assert.deepEqual(await systemTransform(hooks, sessionID), [], `${first}: all retired payload is purged`);
        if (first === "chat-without-id") {
          await chat(false);
          assert.equal(fetchCalls.slice(retired).filter((c) => c.url.includes("/item-and-query")).length, 0,
            "deletion does not erase the no-ID prompt's disk dedup window");
          assert.deepEqual(await systemTransform(hooks, sessionID), [], "duplicate optional memory still abstains");
          const pin = P.getPinnedContainer(sessionID);
          assert.ok(pin, "duplicate no-ID chat publishes a successor pin without querying memory");
          const model = await messagesTransform(hooks, { sessionID, role: "user" },
            [{ type: "text", text: "duplicate prompt" }]);
          assert.ok(model.parts[0].text.includes(pin),
            "duplicate no-ID chat still activates a model-bound successor scope");
        }
        await chat(false, "fresh substantial successor work after retiring the original lifetime");
        assert.ok(fetchCalls.length > retired, `${first}: explicit no-ID chat starts a NEW live incarnation`);
        assert.ok((await systemTransform(hooks, sessionID)).length > 0);
      } finally { P.removeSessionPin(sessionID); }
    }
  } finally {
    if (previousTrigger === undefined) delete process.env.PALLIUM_POSTTOOL_TRIGGERS;
    else process.env.PALLIUM_POSTTOOL_TRIGGERS = previousTrigger;
    if (previousActor === undefined) delete process.env.PALLIUM_HOOK_ACTOR_REF;
    else process.env.PALLIUM_HOOK_ACTOR_REF = previousActor;
  }
});

test("V1 close response cannot purge an explicit same-ID successor with identical pin values", async () => {
  const P = await import(pathToFileURL(path.join(process.cwd(), ".opencode", "plugins", "pallium-common.mjs")));
  const sessionID = "ses_v1_close_successor";
  let entered, release;
  const held = new Promise((resolve) => { entered = resolve; });
  const close = new Promise((resolve) => { release = resolve; });
  installFetch({ "/query": oneBlock, "/item-and-query": oneBlock,
    "/relay/sessions/close": () => { entered(); return close; } });
  const hooks = await loadPlugin({ client: makeClient([]), directory: nonGitDir });
  const event = (type) => hooks.event({ event: { type, properties: { sessionID } } });
  let closing;
  try {
    await event("session.created");
    const originalPin = P.getPinnedContainer(sessionID);
    assert.ok(originalPin);
    await systemTransform(hooks, sessionID);
    closing = event("session.deleted");
    await held;
    const boundary = fetchCalls.length;
    await event("session.idle");
    await hooks["experimental.session.compacting"]({ sessionID });
    assert.equal(fetchCalls.length, boundary, "closing state is not live callback authority");
    await event("session.created");
    assert.equal(P.getPinnedContainer(sessionID), originalPin, "successor deliberately uses identical pin values");
    release({ closed: true });
    await closing;
    assert.equal(P.getPinnedContainer(sessionID), originalPin, "old close must not remove successor pin");
    assert.ok((await systemTransform(hooks, sessionID)).length > 0, "old close must not purge successor output");
  } finally {
    release({ closed: true });
    await closing;
    P.removeSessionPin(sessionID);
  }
});

test("V1 assistant captures its original lifetime before native history awaits", async () => {
  const P = await import(pathToFileURL(path.join(process.cwd(), ".opencode", "plugins", "pallium-common.mjs")));
  const sessionID = "ses_v1_delayed_history";
  let entered, release;
  const held = new Promise((resolve) => { entered = resolve; });
  const history = new Promise((resolve) => { release = resolve; });
  const client = makeClient([]);
  client.session.messages = async () => { entered(); return history; };
  installFetch({ "/items": [{ source_item_id: "retired-answer" }], "/item-and-query": oneBlock });
  const hooks = await loadPlugin({ client, directory: nonGitDir });
  let pending;
  try {
    pending = hooks.event({ event: { type: "session.idle", properties: { sessionID } } });
    await held;
    await hooks.event({ event: { type: "session.deleted", properties: { sessionID } } });
    await hooks["chat.message"]({}, { message: { sessionID, role: "user" },
      parts: [{ type: "text", text: "a fresh substantial successor message without a native ID" }] });
    const pin = P.getPinnedContainer(sessionID);
    release({ data: [{ info: { role: "assistant", id: "msg_retired_history" },
      parts: [{ type: "text", text: "retired answer must never be ingested" }] }] });
    await pending;
    assert.equal(fetchCalls.filter((c) => c.url.endsWith("/items")).length, 0);
    assert.equal(P.getPinnedContainer(sessionID), pin);
    assert.ok((await systemTransform(hooks, sessionID)).length > 0);
  } finally {
    release({ data: [] });
    await pending;
    P.removeSessionPin(sessionID);
  }
});

async function heldGit(argsText, output, run) {
  const saved = childProcess.spawn;
  const directory = fs.mkdtempSync(path.join(tmpHome, "held-git-界-"));
  const release = path.join(directory, "release");
  let entered, armed = true, child, closed;
  const started = new Promise((resolve) => { entered = resolve; });
  childProcess.spawn = (command, args, options) => {
    if (!armed || command !== "git" || args.join(" ") !== argsText) return saved(command, args, options);
    armed = false;
    child = saved(process.execPath, ["-e", `
      const fs = require("node:fs");
      process.stdout.write(${JSON.stringify(output)});
      const timer = setInterval(() => { if (fs.existsSync(${JSON.stringify(release)})) {
        clearInterval(timer); process.exit(0);
      } }, 5);
      setTimeout(()=>process.exit(0), 1500).unref();
    `], { ...options, cwd: directory });
    closed = new Promise((resolve) => child.once("close", resolve));
    child.stdout.once("data", entered);
    return child;
  };
  syncBuiltinESMExports();
  try { await run({ started, release: () => fs.writeFileSync(release, "release"), child: () => child }); }
  finally {
    fs.writeFileSync(release, "release");
    if (child && child.exitCode === null && child.signalCode === null) child.kill();
    await closed;
    childProcess.spawn = saved;
    syncBuiltinESMExports();
    fs.rmSync(directory, { recursive: true, force: true });
  }
}

test("V1 delayed Git cannot publish after deletion and same-ID activation on any caller", { timeout: 20000 }, async () => {
  const P = await import(pathToFileURL(path.join(process.cwd(), ".opencode", "plugins", "pallium-common.mjs")));
  const previousActor = process.env.PALLIUM_HOOK_ACTOR_REF;
  const previousTrigger = process.env.PALLIUM_POSTTOOL_TRIGGERS;
  process.env.PALLIUM_HOOK_ACTOR_REF = "fixture-actor";
  process.env.PALLIUM_POSTTOOL_TRIGGERS = "1";
  const fresh = (await import(pathToFileURL(path.join(process.cwd(), ".opencode", "plugins", "pallium.mjs")) +
    "?oc6-git-retirement")).default;
  try {
    for (const entry of ["orientation", "assistant", "tool", "chat-with-id", "chat-without-id"]) {
      const id = "ses_git_retired_" + entry;
      const sibling = id + "_sibling";
      installFetch({ "/query": oneBlock, "/item-and-query": oneBlock, "/items": [{ source_item_id: "saved" }] });
      const hooks = await fresh({ directory: nonGitDir, client: makeClient([
        { info: { role: "assistant", id: "msg_git_old" }, parts: [{ type: "text", text: "retired old answer" }] },
      ]) });
      const chat = (sessionID, nativeId) => hooks["chat.message"]({}, {
        message: { sessionID, role: "user", ...(nativeId ? { id: nativeId } : {}) },
        parts: [{ type: "text", text: "substantial original work with independent scope" }],
      });
      let pending;
      try {
        await heldGit("remote get-url origin", "https://git.example.test/Old/Repo.git", async (gate) => {
          if (entry === "orientation") pending = hooks.event({ event: { type: "session.created", properties: { sessionID: id } } });
          else if (entry === "assistant") pending = hooks.event({ event: { type: "session.idle", properties: { sessionID: id } } });
          else if (entry === "tool") pending = hooks["tool.execute.after"]({ sessionID: id, tool: "bash" },
            { output: "command failed", metadata: { error: true } });
          else pending = chat(id, entry === "chat-with-id" ? "msg_git_old" : null);
          await gate.started;
          await chat(sibling, "msg_git_sibling");
          assert.ok(fetchCalls.some((c) => c.body?.thread_ref === sibling), `${entry}: unrelated session makes progress`);
          await hooks.event({ event: { type: "session.deleted", properties: { sessionID: id } } });
          await chat(id, "msg_git_successor");
          const pin = P.getPinnedContainer(id), boundary = fetchCalls.length;
          gate.release();
          await pending;
          assert.equal(fetchCalls.length, boundary, `${entry}: no old pin/claim/query/capture after reactivation`);
          assert.equal(P.getPinnedContainer(id), pin);
          const model = await messagesTransform(hooks, { sessionID: id, role: "user" }, [{ type: "text", text: "successor" }]);
          assert.match(model.parts[0].text, /\[Pallium scope/);
          assert.doesNotMatch(model.parts[0].text, /git:git\.example\.test\/old\/repo/);
        });
      } finally {
        await pending;
        P.removeSessionPin(id);
        P.removeSessionPin(sibling);
      }
    }
  } finally {
    if (previousActor === undefined) delete process.env.PALLIUM_HOOK_ACTOR_REF;
    else process.env.PALLIUM_HOOK_ACTOR_REF = previousActor;
    if (previousTrigger === undefined) delete process.env.PALLIUM_POSTTOOL_TRIGGERS;
    else process.env.PALLIUM_POSTTOOL_TRIGGERS = previousTrigger;
  }
});

test("V1 ordinary role, capture and orientation updates do not replace a live Git lifetime", { timeout: 10000 }, async () => {
  const P = await import(pathToFileURL(path.join(process.cwd(), ".opencode", "plugins", "pallium-common.mjs")));
  const id = "ses_git_live_updates";
  const previousActor = process.env.PALLIUM_HOOK_ACTOR_REF;
  process.env.PALLIUM_HOOK_ACTOR_REF = "fixture-actor";
  P.pinContainer(id, P.pathContainer(nonGitDir), undefined, "fixture-actor");
  installFetch({ "/query": oneBlock, "/item-and-query": oneBlock, "/items": [{ source_item_id: "answer" }] });
  const hooks = await loadPlugin({ directory: nonGitDir, client: makeClient([
    { info: { role: "assistant", id: "msg_git_live_answer" }, parts: [{ type: "text", text: "live answer" }] },
  ]) });
  let pending;
  try {
    await heldGit("rev-parse --abbrev-ref HEAD", "feature/live-updates", async (gate) => {
      pending = hooks.event({ event: { type: "session.created", properties: { sessionID: id } } });
      await gate.started;
      await hooks["chat.message"]({}, { message: { sessionID: id, role: "user", id: "msg_live_role" },
        parts: [{ type: "text", text: "ordinary role insertion while orientation is pending" }] });
      await hooks.event({ event: { type: "session.idle", properties: { sessionID: id } } });
      gate.release();
      await pending;
      assert.ok(fetchCalls.some((c) => c.body?.trigger_origin === "session_start_orientation"),
        "live Map entry/capture/orientation changes are not lifetime replacement");
      assert.ok(fetchCalls.some((c) => c.url.endsWith("/items")));
    });
  } finally {
    await pending;
    P.removeSessionPin(id);
    if (previousActor === undefined) delete process.env.PALLIUM_HOOK_ACTOR_REF;
    else process.env.PALLIUM_HOOK_ACTOR_REF = previousActor;
  }
});

test("V1 unpinned close discovery cannot target a recreated same-ID session", { timeout: 10000 }, async () => {
  const P = await import(pathToFileURL(path.join(process.cwd(), ".opencode", "plugins", "pallium-common.mjs")));
  const id = "ses_git_close_recreated";
  const previousActor = process.env.PALLIUM_HOOK_ACTOR_REF;
  process.env.PALLIUM_HOOK_ACTOR_REF = "fixture-actor";
  installFetch({ "/item-and-query": oneBlock });
  const hooks = await loadPlugin({ directory: nonGitDir, client: makeClient([]) });
  const chat = (nativeId) => hooks["chat.message"]({}, { message: { sessionID: id, role: "user", id: nativeId },
    parts: [{ type: "text", text: "substantial same ID work before and after closing" }] });
  let closing;
  try {
    await chat("msg_close_before");
    P.removeSessionPin(id);
    await heldGit("remote get-url origin", "https://git.example.test/Retired/Repo.git", async (gate) => {
      closing = hooks.event({ event: { type: "session.deleted", properties: { sessionID: id } } });
      await gate.started;
      await chat("msg_close_after");
      const pin = P.getPinnedContainer(id);
      gate.release();
      await closing;
      assert.equal(fetchCalls.filter((c) => c.url.endsWith("/relay/sessions/close")).length, 0,
        "unsubmitted old close has no authority over the successor");
      assert.equal(P.getPinnedContainer(id), pin);
      assert.ok((await systemTransform(hooks, id)).length > 0);
    });
  } finally {
    await closing; P.removeSessionPin(id);
    if (previousActor === undefined) delete process.env.PALLIUM_HOOK_ACTOR_REF;
    else process.env.PALLIUM_HOOK_ACTOR_REF = previousActor;
  }
});
