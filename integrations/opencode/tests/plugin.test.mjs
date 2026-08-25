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

const tmpHome = fs.mkdtempSync(path.join(os.tmpdir(), "pallium-oc-plugin-"));
process.env.USERPROFILE = tmpHome;
process.env.HOME = tmpHome;
delete process.env.PALLIUM_POSTTOOL_TRIGGERS;

const nonGitDir = fs.mkdtempSync(path.join(os.tmpdir(), "pallium-oc-cwd-"));

let loadPlugin;
test.before(async () => {
  const url = pathToFileURL(path.join(process.cwd(), ".opencode", "plugins", "pallium.mjs"));
  loadPlugin = (await import(url)).default;
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
    const payload = key ? routes[key] : {};
    return { ok: true, status: 200, text: async () => JSON.stringify(payload) };
  };
}

function makeClient(messages) {
  return {
    app: { log: async () => true },
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

// --- chat.message -> /item-and-query -> inject ------------------------------

test("chat.message ingests the user prompt and queues memory for the system prompt", async () => {
  installFetch({ "/item-and-query": oneBlock });
  const hooks = await loadPlugin({ client: makeClient([]), directory: nonGitDir });

  const parts = [{ type: "text", text: "How does the injection policy abstention work here?" }];
  await hooks["chat.message"]({}, { message: { sessionID: "sesA" }, parts });

  const iq = fetchCalls.find((c) => c.url.includes("/item-and-query"));
  assert.ok(iq, "should call /item-and-query");
  assert.equal(iq.body.agent_ref, "opencode");
  assert.equal(iq.body.role, "user");
  assert.equal(iq.body.thread_ref, "sesA");
  assert.equal(iq.body.query_trigger_origin, "user_prompt_submit");
  assert.match(iq.body.source_id, /^oc-[0-9a-f]{12}$/);

  const system = await systemTransform(hooks, "sesA");
  assert.equal(system.length, 1);
  assert.match(system[0], /^\[Pallium scope — /);
  assert.match(system[0], /"request_source_item_id":"request-opencode-1"/);
  assert.match(system[0], /\[Pallium memory — container: path:/);
  assert.match(system[0], /ref:ref-xyz\]/);
  assert.match(system[0], /\[End Pallium memory\]$/);
});

test("chat.message skips short prompts, slash-commands, and duplicates", async () => {
  installFetch({ "/item-and-query": oneBlock });
  const hooks = await loadPlugin({ client: makeClient([]), directory: nonGitDir });

  await hooks["chat.message"]({}, { message: { sessionID: "sesB" }, parts: [{ type: "text", text: "hi" }] });
  await hooks["chat.message"]({}, { message: { sessionID: "sesB" }, parts: [{ type: "text", text: "/commit please do it now" }] });
  assert.equal(fetchCalls.length, 0, "short + slash prompts must not hit the daemon");

  const longPrompt = [{ type: "text", text: "please investigate the retrieval grounding gates in detail" }];
  await hooks["chat.message"]({}, { message: { sessionID: "sesB" }, parts: longPrompt });
  assert.equal(fetchCalls.length, 1, "first real prompt hits the daemon");
  await hooks["chat.message"]({}, { message: { sessionID: "sesB" }, parts: longPrompt });
  assert.equal(fetchCalls.length, 1, "identical prompt within the dedup window is skipped");
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
      info: { role: "assistant", id: "a1" },
      parts: [
        { type: "text", text: "Done. I edited the file." },
        { type: "tool", tool: "read", state: { status: "completed", input: { filePath: "src/a.js" }, output: "" } },
        { type: "tool", tool: "edit", state: { status: "completed", input: { filePath: "src/b.js" } } },
      ],
    },
  ];
  installFetch({ "/items": [{ source_item_id: "sid-1" }] });
  const hooks = await loadPlugin({ client: makeClient(messages), directory: nonGitDir });

  await hooks.event({ event: { type: "session.idle", properties: { sessionID: "sesD" } } });
  const items = fetchCalls.find((c) => c.url.includes("/items"));
  assert.ok(items, "should call /items");
  assert.ok(Array.isArray(items.body), "/items body is an array of one item");
  const item = items.body[0];
  assert.equal(item.role, "assistant");
  assert.equal(item.agent_ref, "opencode");
  assert.equal(item.thread_ref, "sesD");
  assert.equal(item.content, "Done. I edited the file.");
  assert.ok(item.metadata && item.metadata.agent_work_trace_turn, "attaches work-trace metadata");
  assert.deepEqual(item.metadata.agent_work_trace_turn.files_read, ["src/a.js"]);
  assert.deepEqual(item.metadata.agent_work_trace_turn.files_modified, ["src/b.js"]);

  // Idempotent: a second session.idle for the same turn does not re-ingest.
  const before = fetchCalls.length;
  await hooks.event({ event: { type: "session.idle", properties: { sessionID: "sesD" } } });
  assert.equal(fetchCalls.length, before, "same assistant message must not be re-ingested");
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
  assert.deepEqual(system, [], "deleted session's queued injection is purged");
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
