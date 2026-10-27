import test, { after } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
const profile = mkdtempSync(path.join(tmpdir(), "pallium-caller-"));
const previousEnv = Object.fromEntries(["HOME", "USERPROFILE", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "PALLIUM_HOOK_ACTOR_REF"].map((key) => [key, process.env[key]]));
for (const key of Object.keys(previousEnv)) process.env[key] = key === "PALLIUM_HOOK_ACTOR_REF" ? "fixture-actor" : profile;
after(() => { for (const [key, value] of Object.entries(previousEnv)) { if (value === undefined) delete process.env[key]; else process.env[key] = value; } rmSync(profile, { recursive: true, force: true }); });
const { default: v1 } = await import("../.opencode/plugins/pallium.mjs");
const { default: v2 } = await import("../server.js");
const { deriveContainerRef, getPinnedContainer, ocNativeMessageSourceId, pinContainer, removeSessionPin } = await import("../.opencode/plugins/pallium-common.mjs");

const sessionID = "ses_abc123";
const deliveryID = "relay-delivery-" + "a".repeat(32);
const endpointID = "relay-session-" + "b".repeat(32);
const nativeID = "msg_relaywake123";
const location = "/tmp/pallium-v2-exact";
const container = deriveContainerRef(location);
const relaySession = { runtime: "opencode", session_ref: sessionID, container_ref: container,
  endpoint_id: endpointID, scope_generation: 0, alias: "planner", state: "recent", destination_health: "active" };
const delivery = { delivery_id: deliveryID, claim_token: "claim-token", message_id: "relay-message-test",
  sender_runtime: "codex", sender_session_ref: "sender", payload: "שלום wake payload",
  created_at: "2026-10-07T00:00:00Z", attempts: 1 };

test("package keeps V1 default and exports the V2 raw plugin", () => {
  assert.equal(typeof v1, "function");
  assert.equal(v2.id, "pallium-v2");
  assert.equal(typeof v2.setup, "function");
});

test("V2 exact session wakes once, attaches to model context, ACKs, and settles correlated idle", async () => {
  const oldFetch = globalThis.fetch;
  const calls = [];
  const hooks = {};
  const messages = [];
  let owner;
  let waitCount = 0;
  let contextCount = 0;
  const wake = { generation: 1, delivery_id: deliveryID, native_input_id: nativeID,
    native_location: location, scope_generation: 0, admitted: false, terminal: false };
  globalThis.fetch = async (url, init) => {
    const u = new URL(url);
    const body = init?.body ? JSON.parse(init.body) : {};
    calls.push({ path: u.pathname, body });
    let result;
    if (u.pathname === "/relay/sessions") result = [relaySession];
    else if (u.pathname === "/relay/opencode/wake") {
      owner = body.owner_id;
      if (body.operation === "admitted") wake.admitted = true;
      if (body.operation === "terminal") wake.terminal = true;
      if (body.operation === "context") contextCount++;
      result = { session: relaySession, wake: { ...wake },
        deliveries: body.operation === "context" ? [contextCount === 1 ? delivery : { ...delivery, claim_token: undefined }] : [],
        restored: body.operation === "context" && contextCount > 1 };
    } else if (u.pathname === "/relay/deliveries/ack") result = {
      delivery_id: deliveryID, state: "delivered", already_delivered: false,
    };
    else result = {};
    return { ok: true, text: async () => JSON.stringify(result) };
  };
  const ctx = {
    location: { directory: location }, app: { log() {} },
    session: {
      hook: async (name, fn) => { hooks[name] = fn; return { dispose: async () => {} }; },
      get: async ({ sessionID: id }) => ({ id, location: { directory: id === sessionID ? location : "/tmp/other" } }),
      context: async () => ({ data: messages }),
      prompt: async ({ id, text, metadata }) => { messages.push({ type: "user", id, text, metadata }); return { id }; },
      wait: async () => {
        waitCount++;
        const user = messages.find((m) => m.id === nativeID);
        const projected = { id: user.id, role: "user", content: [{ type: "text", text: user.text }], metadata: user.metadata };
        await hooks.context({ sessionID, messages: [projected] });
        assert.match(projected.content.at(-1).text, /שלום wake payload/);
        const continuation = { id: user.id, role: "user", content: [{ type: "text", text: user.text }], metadata: user.metadata };
        await hooks.context({ sessionID, messages: [continuation] });
        assert.match(continuation.content.at(-1).text, /שלום wake payload/);
        messages.push({ type: "idle", id: "msg_terminal123", outcome: "succeeded" });
      },
    },
    event: { subscribe: async function* ({ signal }) { while (!signal.aborted) await new Promise((resolve) => {
      const timer = setTimeout(resolve, 10);
      signal.addEventListener("abort", () => { clearTimeout(timer); resolve(); }, { once: true });
    }); } },
  };
  try {
    const dispose = await v2.setup(ctx);
    await new Promise((resolve) => setTimeout(resolve, 2700));
    assert.equal(waitCount, 1);
    assert.match(owner, /^opencode-owner-[0-9a-f]{32}$/);
    assert.equal(calls.filter((c) => c.body.operation === "admitted").length, 1);
    assert.equal(calls.filter((c) => c.body.operation === "terminal")[0].body.terminal_message_id, "msg_terminal123");
    assert.equal(calls.filter((c) => c.path === "/relay/deliveries/ack").length, 1);
    assert.equal(contextCount, 2);
    await dispose();
    assert.equal(calls.filter((c) => c.body.operation === "detach").length, 1);
  } finally { globalThis.fetch = oldFetch; }
});

test("V2 ignores another directory and treats an uncommitted marker as ordinary input", async () => {
  const oldFetch = globalThis.fetch;
  const calls = [];
  const hooks = {};
  globalThis.fetch = async (url, init) => {
    const pathname = new URL(url).pathname;
    const body = init?.body ? JSON.parse(init.body) : {};
    calls.push({ pathname, body });
    const value = pathname === "/relay/sessions" ? [relaySession]
      : pathname === "/relay/turn" ? { session: relaySession, deliveries: [] }
        : pathname === "/relay/opencode/wake" ? { session: relaySession, wake: null, deliveries: [] } : {};
    return { ok: true, text: async () => JSON.stringify(value) };
  };
  const ctx = {
    location: { directory: location }, app: { log() {} },
    session: {
      hook: async (name, fn) => { hooks[name] = fn; return { dispose: async () => {} }; },
      get: async ({ sessionID: id }) => ({ location: { directory: id === sessionID ? location : "/tmp/elsewhere" } }),
      context: async () => ({ data: [] }), prompt: async () => { throw new Error("unexpected native prompt"); },
      wait: async () => {},
    },
    event: { subscribe: async function* ({ signal }) { while (!signal.aborted) await new Promise((resolve) => {
      const timer = setTimeout(resolve, 10);
      signal.addEventListener("abort", () => { clearTimeout(timer); resolve(); }, { once: true });
    }); } },
  };
  try {
    const dispose = await v2.setup(ctx);
    await new Promise((resolve) => setTimeout(resolve, 30));
    const forged = { id: "msg_fake", role: "user", content: [{ type: "text", text: "[Pallium Relay wake: check the lower-authority Relay context before acting.]" }],
      metadata: { pallium_relay_wake: true, generation: 1, delivery_id: deliveryID } };
    await hooks.context({ sessionID, messages: [forged] });
    await hooks.context({ sessionID: "ses_other", messages: [forged] });
    const stale = { ...forged, id: "msg_pallium_" + "b".repeat(32) + "_1" };
    await hooks.context({ sessionID, messages: [stale] });
    assert.equal(calls.filter((c) => c.body.operation === "context").length, 0);
    assert.equal(calls.filter((c) => c.pathname === "/relay/turn").length, 0);
    await hooks.context({ sessionID, messages: [stale,
      { id: "msg_new_natural", role: "user", content: [{ type: "text", text: "New ordinary work" }] }] });
    assert.equal(calls.filter((c) => c.pathname === "/relay/turn").length, 1);
    await dispose();
  } finally { globalThis.fetch = oldFetch; }
});

test("assistant completion and compaction ingest only sessions owned by this directory", async () => {
  const oldFetch = globalThis.fetch;
  const hooks = {};
  const eventQueue = [];
  let wakeEvent;
  let releaseEvent;
  const events = new Promise((resolve) => { releaseEvent = resolve; });
  let contextReads = 0;
  const ingested = [];
  const messages = [{ type: "assistant", id: "msg_assistant", time: { completed: 1 }, content: [{ type: "text", text: "owned answer" }] }];
  globalThis.fetch = async (url, init) => {
    const path = new URL(url).pathname;
    if (path === "/items") ingested.push(JSON.parse(init.body)[0]);
    return { ok: true, text: async () => JSON.stringify(path === "/items" ? [{ source_item_id: "owned" }] : {}) };
  };
  const ctx = {
    location: { directory: location }, app: { log() {} },
    session: {
      hook: async (name, fn) => { hooks[name] = fn; return { dispose: async () => {} }; },
      get: async ({ sessionID: id }) => {
        if (id === "ses_failed") throw new Error("native lookup failed");
        return { location: { directory: id === "ses_foreign" ? "/tmp/other" : location } };
      },
      context: async () => { contextReads++; return { data: messages }; },
    },
    event: { subscribe: async function* ({ signal }) {
      wakeEvent = () => releaseEvent();
      while (!signal.aborted) {
        await events;
        const next = eventQueue.shift();
        if (next) yield next;
        await new Promise((resolve) => setTimeout(resolve, 0));
      }
    } },
  };
  let dispose;
  try {
    dispose = await v2.setup(ctx);
    const emit = async (id) => {
      eventQueue.push({ type: "session.execution.succeeded", data: { sessionID: id } });
      wakeEvent();
      await pause();
    };
    await emit("ses_owned");
    const ownedReads = contextReads;
    const ownedWrites = ingested.length;
    await emit("ses_foreign");
    await emit("ses_failed");
    assert.ok(ownedReads > 0);
    assert.equal(contextReads, ownedReads);
    assert.equal(ingested.length, ownedWrites);
    assert.equal(ownedWrites, 0, "an assistant without a captured native user source is not attributed or ingested");
    await hooks.compaction({ sessionID: "ses_foreign" });
    await hooks.compaction({ sessionID: "ses_failed" });
    assert.equal(contextReads, ownedReads);
    assert.equal(ingested.length, ownedWrites);
    await hooks.compaction({ sessionID: "ses_owned" });
    assert.equal(ingested.length, ownedWrites);
  } finally {
    try { await dispose?.(); } finally { globalThis.fetch = oldFetch; }
  }
});

const pause = () => new Promise((resolve) => setTimeout(resolve, 20));
const snapshot = (overrides = {}) => ({ generation: 1, delivery_id: deliveryID, native_input_id: nativeID,
  native_location: location, scope_generation: 0, admitted: false, terminal: false, ...overrides });
const projectedWake = () => ({ id: nativeID, role: "user", content: [{ type: "text",
  text: "[Pallium Relay wake: check the lower-authority Relay context before acting.]" }],
metadata: { pallium_relay_wake: true, generation: 1, delivery_id: deliveryID } });

async function callerFixture(options = {}) {
  const previousFetch = globalThis.fetch;
  const previousInterval = globalThis.setInterval;
  const previousClear = globalThis.clearInterval;
  const calls = [];
  const native = { prompt: [], wait: 0, interrupt: 0 };
  const hooks = {};
  const history = options.history || [];
  const retired = [];
  const events = [];
  let eventReady;
  let eventRetired = false;
  let interval;
  let listed = 0;
  globalThis.setInterval = (fn) => { interval = fn; return { unref() {} }; };
  globalThis.clearInterval = () => {};
  globalThis.fetch = async (url, init) => {
    const path = new URL(url).pathname;
    const body = init?.body ? JSON.parse(init.body) : {};
    calls.push({ path, body, signal: init?.signal });
    const intercepted = options.fetch ? await options.fetch(path, body, init) : undefined;
    if (intercepted !== undefined) return intercepted;
    if (path === "/relay/sessions") {
      listed++;
      if (options.list && listed <= options.list.length) {
        const value = options.list[listed - 1];
        if (value === null) return { ok: false, body: { cancel: async () => {} } };
        return { ok: true, text: async () => JSON.stringify(value) };
      }
      return { ok: true, text: async () => JSON.stringify([relaySession]) };
    }
    const result = options.response ? await options.response(path, body, calls) : undefined;
    const value = result === undefined ? path === "/relay/opencode/wake"
      ? { session: relaySession, wake: options.wake ?? null, deliveries: [] }
      : path === "/relay/turn" ? { session: relaySession, deliveries: [] } : {} : result;
    if (value === null) return { ok: false, body: { cancel: async () => {} } };
    return { ok: true, text: async () => JSON.stringify(value) };
  };
  const ctx = {
    location: { directory: location }, app: { log() {} },
    session: {
      hook: async (name, fn) => { hooks[name] = fn; return { dispose: () => { retired.push(name); return options.dispose?.(name); } }; },
      get: async (input) => options.get ? options.get(input) : ({ location: { directory: location } }),
      context: async (input) => options.context ? options.context(input, history) : ({ data: history }),
      prompt: async (input) => {
        native.prompt.push(input);
        history.push({ type: "user", id: input.id, text: input.text, metadata: input.metadata });
        if (options.prompt) return options.prompt(input);
        return { id: input.id };
      },
      wait: async () => { native.wait++; if (options.wait) await options.wait(history, hooks); },
      interrupt: async () => { native.interrupt++; },
    },
    event: { subscribe: async function* ({ signal }) {
      try {
      while (!signal.aborted) {
        if (events.length) { const event = events.shift(); yield event; options.afterEvent?.(event); continue; }
        await new Promise((resolve) => {
          eventReady = resolve;
          signal.addEventListener("abort", resolve, { once: true });
        });
      }
      } finally { eventRetired = true; }
    } },
  };
  const dispose = await v2.setup(ctx);
  await pause();
  if (options.roleHistory || history.some((message) => message?.type === "assistant")) {
    const startId = options.roleStartId || "msg_role_source";
    const startText = "role source prompt";
    let userIndex = history.findIndex((message) => message?.type === "user" && /^msg_[A-Za-z0-9_-]+$/.test(message.id));
    if (userIndex < 0) {
      history.unshift({ type: "user", id: startId, text: startText });
      userIndex = 0;
    }
    if (userIndex > 0 && history[userIndex - 1]?.type !== "idle") {
      history.splice(userIndex, 0, { type: "idle", id: "msg_role_prior_idle" });
      userIndex++;
    }
    if (history.at(-1)?.type !== "idle") history.push({ type: "idle", id: "msg_role_idle" });
    const sessionForRole = options.roleSessionID || sessionID;
    for (const user of history.filter((message) => message?.type === "user" && /^msg_[A-Za-z0-9_-]+$/.test(message.id))) {
      await hooks.prompt({ sessionID: sessionForRole, messageID: user.id,
        prompt: { text: user.text || startText } });
    }
  }
  return {
    calls, native, hooks, history, retired, dispose, listed: () => listed, eventRetired: () => eventRetired,
    emit: async (event) => { events.push(event); eventReady?.(); await pause(); },
    tick: async () => { interval(); await pause(); },
    close: async () => {
      try { await dispose(); } finally {
        globalThis.fetch = previousFetch;
        globalThis.setInterval = previousInterval;
        globalThis.clearInterval = previousClear;
      }
    },
  };
}

for (const failure of ["503", "timeout"]) {
  test(`transient poll ${failure} does not reenroll an established owner`, { timeout: 12000 }, async () => {
    let fail = true;
    let timedOut;
    const timeoutObserved = new Promise((resolve) => { timedOut = resolve; });
    const f = await callerFixture({ fetch: async (route, body, init) => {
      if (route !== "/relay/opencode/wake" || body.operation !== "poll" || !fail) return;
      if (failure === "503") return { ok: false, status: 503, text: async () => JSON.stringify({ detail: { code: "relay_busy" } }), body: { cancel: async () => {} } };
      return new Promise((_, reject) => init.signal.addEventListener("abort", () => {
        timedOut();
        reject(new Error("request deadline"));
      }, { once: true }));
    } });
    try {
      assert.equal(f.calls.filter((c) => c.body.operation === "enroll").length, 1, "startup still enrolls");
      await f.tick();
      if (failure === "timeout") { await timeoutObserved; await pause(); }
      assert.equal(f.calls.filter((c) => c.body.operation === "enroll").length, 1, "a transient failure cannot require an enrollment write");
      fail = false;
      await f.tick();
      assert.equal(f.calls.filter((c) => c.body.operation === "poll").length, 2, "ordinary polling resumes independently");
      assert.equal(f.calls.filter((c) => c.body.operation === "enroll").length, 1);
    } finally { await f.close(); }
  });
}

for (const [name, status, raw, reenroll] of [
  ["missing or expired registration", 409, JSON.stringify({ detail: "OpenCode registration is missing or stale" }), true],
  ["closed or moved scope", 409, JSON.stringify({ detail: "OpenCode endpoint is closed or its scope changed" }), false],
  ["missing endpoint", 404, JSON.stringify({ detail: "relay entity not found in the requested scope" }), false],
  ["unrelated conflict", 409, JSON.stringify({ detail: "other conflict" }), false],
  ["truncated registration error", 409, '{"detail":"OpenCode registration is missing or stale"', false],
  ["unreadable registration error", 409, null, false],
]) {
  test(`poll recovery distinguishes ${name}`, async () => {
    const f = await callerFixture({ fetch: async (route, body) => {
      if (route === "/relay/opencode/wake" && body.operation === "poll") return {
        ok: false, status, text: async () => { if (raw === null) throw new Error("body failed"); return raw; },
        body: { cancel: async () => {} },
      };
    } });
    try {
      await f.tick();
      const enrollments = f.calls.filter((c) => c.body.operation === "enroll");
      assert.equal(enrollments.length, reenroll ? 2 : 1);
      for (const call of enrollments) {
        assert.equal(call.body.endpoint_id, endpointID);
        assert.equal(call.body.scope_generation, 0);
        assert.equal(call.body.native_location, location);
        assert.equal(call.body.owner_id, enrollments[0].body.owner_id);
      }
      assert.equal(f.native.prompt.length, 0);
    } finally { await f.close(); }
  });
}

test("registration recovery cannot replace a competing native owner", async () => {
  let enrollments = 0;
  const f = await callerFixture({ fetch: async (route, body) => {
    if (route !== "/relay/opencode/wake") return;
    const detail = body.operation === "poll" ? "OpenCode registration is missing or stale"
      : body.operation === "enroll" && ++enrollments > 1 ? "OpenCode endpoint already has a live native owner" : null;
    if (detail) return { ok: false, status: 409, text: async () => JSON.stringify({ detail }), body: { cancel: async () => {} } };
  } });
  try {
    await f.tick();
    assert.equal(enrollments, 2);
    assert.equal(f.native.prompt.length, 0);
    assert.equal(f.calls.filter((c) => c.body.operation === "context" || c.body.operation === "admitted").length, 0);
  } finally { await f.close(); }
});

test("retirement during a registration error body forbids reenrollment", async () => {
  const bodyRead = barrier();
  const f = await callerFixture({ fetch: async (route, body) => {
    if (route === "/relay/opencode/wake" && body.operation === "poll") return {
      ok: false, status: 409, body: { cancel: async () => {} },
      text: async () => { await bodyRead.wait(); return JSON.stringify({ detail: "OpenCode registration is missing or stale" }); },
    };
  } });
  try {
    await f.tick();
    await bodyRead.entered;
    await f.close();
    bodyRead.release();
    await pause();
    assert.equal(f.calls.filter((c) => c.body.operation === "enroll").length, 1);
  } finally { bodyRead.release(); await f.close(); }
});

test("lost native admission reply retries the same ID after durable readback", async () => {
  const f = await callerFixture({ wake: snapshot(), prompt: async () => { throw new Error("reply lost"); },
    wait: async (history) => { history.push({ type: "idle", id: "msg_terminal123" }); } });
  try {
    await f.tick();
    await f.tick();
    assert.equal(f.native.prompt.length, 1);
    assert.equal(f.native.prompt[0].id, nativeID);
    assert.equal(f.calls.filter((c) => c.body.operation === "admitted").length, 1);
    assert.equal(f.calls.filter((c) => c.body.operation === "terminal").length, 1);
  } finally { await f.close(); }
});

test("missing admitted input and unrelated idle cannot settle or issue a new native ID", async () => {
  const compacted = await callerFixture({ wake: snapshot({ admitted: true }), history: [{ type: "idle", id: "msg_unrelated" }] });
  try {
    await compacted.tick();
    assert.equal(compacted.native.prompt.length, 0);
    assert.equal(compacted.calls.filter((c) => ["admitted", "terminal"].includes(c.body.operation)).length, 0);
  } finally { await compacted.close(); }
  const overtaken = await callerFixture({ wake: snapshot(), wait: async (history) => {
    history.push({ type: "user", id: "msg_newer", text: "newer natural work" }, { type: "idle", id: "msg_newer_idle" });
  } });
  try {
    await overtaken.tick();
    assert.equal(overtaken.calls.filter((c) => c.body.operation === "terminal").length, 0);
    assert.deepEqual(overtaken.native.prompt.map((p) => p.id), [nativeID]);
  } finally { await overtaken.close(); }
});

test("committed empty wake fails visibly while newer natural work remains usable", async () => {
  const f = await callerFixture({ wake: snapshot() });
  try {
    await assert.rejects(f.hooks.context({ sessionID, messages: [projectedWake()] }), /no current Relay work/);
    assert.equal(f.calls.filter((c) => c.body.operation === "context").length, 1);
    assert.equal(f.calls.filter((c) => c.path === "/relay/turn").length, 0);
    await f.hooks.context({ sessionID, messages: [projectedWake(),
      { id: "msg_newer", role: "user", content: [{ type: "text", text: "Do newer work" }] }] });
    assert.equal(f.calls.filter((c) => c.path === "/relay/turn").length, 1);
  } finally { await f.close(); }
});

test("lost ACK response restores continuation without another ACK or claim", async () => {
  let contextCalls = 0;
  const f = await callerFixture({ wake: snapshot(), response: (path, body) => {
    if (path === "/relay/deliveries/ack") return null;
    if (body.operation === "context") {
      contextCalls++;
      return { session: relaySession, wake: snapshot(), restored: contextCalls > 1,
        deliveries: [contextCalls === 1 ? delivery : { ...delivery, claim_token: undefined }] };
    }
  } });
  try {
    const first = projectedWake();
    await f.hooks.context({ sessionID, messages: [first] });
    const later = projectedWake();
    await f.hooks.context({ sessionID, messages: [later] });
    assert.match(later.content.at(-1).text, /שלום wake payload/);
    assert.equal(f.calls.filter((c) => c.path === "/relay/deliveries/ack").length, 1);
    assert.equal(f.calls.filter((c) => c.path === "/relay/turn").length, 0);
  } finally { await f.close(); }
});

test("disposal during native submission suppresses later callbacks", async () => {
  let release;
  const pending = new Promise((resolve) => { release = resolve; });
  const f = await callerFixture({ wake: snapshot(), prompt: async () => pending });
  try {
    await f.tick();
    assert.equal(f.native.prompt.length, 1);
    await f.close();
    release({ id: nativeID });
    await pause();
    assert.equal(f.native.interrupt, 0);
    assert.equal(f.calls.filter((c) => ["admitted", "terminal"].includes(c.body.operation)).length, 0);
  } finally { release({ id: nativeID }); }
});

test("failed startup session discovery retries and enrolls only a returned endpoint", async () => {
  const f = await callerFixture({ list: [null, [relaySession]] });
  try {
    assert.equal(f.listed(), 1);
    assert.equal(f.calls.filter((c) => c.body.operation === "enroll").length, 0);
    await f.tick();
    assert.equal(f.listed(), 2);
    assert.equal(f.calls.filter((c) => c.body.operation === "enroll").length, 1);
  } finally { await f.close(); }
});

test("scope identity and Relay payload share the 2300-character model budget", async () => {
  const f = await callerFixture({ response: (path) => path === "/relay/turn"
    ? { session: relaySession, deliveries: [{ ...delivery, payload: "שלום ".repeat(240) }] } : undefined });
  try {
    const user = { id: "msg_budget", role: "user", content: [{ type: "text", text: "ordinary" }] };
    await f.hooks.context({ sessionID, messages: [user] });
    const request = f.calls.find((c) => c.path === "/relay/turn").body;
    assert.equal(request.session_ref, sessionID);
    assert.equal(request.container_ref, container);
    assert.ok(request.max_chars > 0 && request.max_chars < 2300);
    const attached = user.content.at(-1).text;
    assert.match(attached, /Pallium Relay message/);
    assert.match(attached, /container_ref/);
    assert.match(attached, /thread_ref/);
    assert.match(attached, /agent_ref/);
    assert.ok([...attached].length <= 2300 + 40);
  } finally { await f.close(); }
});

const barrier = () => {
  let enter, release;
  const entered = new Promise((resolve) => { enter = resolve; });
  const pending = new Promise((resolve) => { release = resolve; });
  return {
    get entered() { return new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("caller did not reach the expected barrier")), 5000);
      entered.then(() => { clearTimeout(timer); resolve(); });
    }); },
    release, wait: () => { enter(); return pending; },
  };
};
const natural = (id = "msg_ordinary") => ({ id, role: "user", content: [{ type: "text", text: "ordinary work" }] });
const jsonResponse = (value) => ({ ok: true, text: async () => JSON.stringify(value) });
const completedAssistant = (id = "msg_answer", text = "שלום answer 😀") => ({
  type: "assistant", id, time: { completed: 1 }, content: [{ type: "text", text }],
});
const captureCalls = (f) => f.calls.filter((call) => call.path === "/items");
const captureReceipt = [{ source_item_id: "source-capture" }];
const sourceUser = (id, text = "question") => ({ type: "user", id, text });

test("V2 freezes each prompt name and links delayed distinct outputs only inside its idle-delimited source segment", async () => {
  let alias = "planner-a";
  const history = [];
  const f = await callerFixture({ history, response: async (route) => {
    if (route === "/relay/turn") return { session: { ...relaySession, alias }, deliveries: [] };
    if (route === "/items") return captureReceipt;
  } });
  try {
    history.push(sourceUser("msg_turn_a", "first question"));
    await f.hooks.prompt({ sessionID, messageID: "msg_turn_a", prompt: { text: "first question" } });
    alias = "planner-b";
    history.push(completedAssistant("msg_answer_a1", "first answer"),
      completedAssistant("msg_answer_a2", "second answer"), { type: "idle", id: "msg_idle_a" },
      sourceUser("msg_turn_b", "second question"));
    await f.hooks.prompt({ sessionID, messageID: "msg_turn_b", prompt: { text: "second question" } });
    history.push(completedAssistant("msg_answer_b", "later answer"), { type: "idle", id: "msg_idle_b" });
    await f.hooks.compaction({ sessionID });
    const records = new Map(captureCalls(f).map((call) => [call.body[0].source_id, call.body[0]]));
    for (const id of ["msg_answer_a1", "msg_answer_a2"]) {
      const record = records.get(ocNativeMessageSourceId("assistant", sessionID, id));
      assert.equal(record.source_turn_id, "msg_turn_a");
      assert.equal(record.relay_name, "planner-a");
      assert.equal(record.relay_attribution_state, "named");
    }
    const later = records.get(ocNativeMessageSourceId("assistant", sessionID, "msg_answer_b"));
    assert.equal(later.source_turn_id, "msg_turn_b");
    assert.equal(later.relay_name, "planner-b");
    assert.equal(records.size, 3);
  } finally { await f.close(); }
});

test("V2 leaves steered multi-user and incomplete post-compaction segments unassociated", async () => {
  const history = [];
  const f = await callerFixture({ history, response: async (route) => {
    if (route === "/relay/turn") return { session: { ...relaySession, alias: "planner" }, deliveries: [] };
    if (route === "/items") return captureReceipt;
  } });
  try {
    history.push(sourceUser("msg_steer_a", "first"));
    await f.hooks.prompt({ sessionID, messageID: "msg_steer_a", prompt: { text: "first" } });
    history.push(sourceUser("msg_steer_b", "steered"));
    await f.hooks.prompt({ sessionID, messageID: "msg_steer_b", prompt: { text: "steered" } });
    history.push(completedAssistant("msg_ambiguous", "ambiguous"), { type: "idle", id: "msg_steer_idle" });
    await f.hooks.compaction({ sessionID });
    assert.equal(captureCalls(f).length, 0);
    history.splice(0, history.length, sourceUser("msg_after_compaction", "resumed"),
      completedAssistant("msg_unbounded", "unbounded"));
    await f.hooks.prompt({ sessionID, messageID: "msg_after_compaction", prompt: { text: "resumed" } });
    await f.hooks.compaction({ sessionID });
    assert.equal(captureCalls(f).length, 0);
  } finally { await f.close(); }
});

test("V2 retries Relay delivery from context without relabeling a failed source-time snapshot", async () => {
  let attempts = 0;
  const history = [sourceUser("msg_failed_snapshot", "question"), completedAssistant("msg_failed_answer", "answer"),
    { type: "idle", id: "msg_failed_idle" }];
  const f = await callerFixture({ history, response: async (route) => {
    if (route === "/relay/turn") {
      attempts++;
      return attempts === 1 ? null : { session: { ...relaySession, alias: "takeover" }, deliveries: [delivery] };
    }
    if (route === "/relay/deliveries/ack") return { delivery_id: deliveryID, state: "delivered", already_delivered: false };
    if (route === "/items") return captureReceipt;
  } });
  try {
    await f.hooks.prompt({ sessionID, messageID: "msg_failed_snapshot", prompt: { text: "question" } });
    const userCapture = f.calls.find((call) => call.path === "/item-and-query").body;
    assert.equal(userCapture.source_turn_id, "msg_failed_snapshot");
    assert.equal(userCapture.relay_attribution_state, "unavailable");
    const user = { id: "msg_failed_snapshot", role: "user", content: [{ type: "text", text: "question" }] };
    await f.hooks.context({ sessionID, messages: [user] });
    assert.equal(attempts, 2);
    assert.match(user.content.at(-1).text, /שלום wake payload/);
    await f.hooks.compaction({ sessionID });
    const assistant = captureCalls(f)[0].body[0];
    assert.equal(assistant.source_turn_id, "msg_failed_snapshot");
    assert.equal(assistant.relay_name, null);
    assert.equal(assistant.relay_attribution_state, "unavailable");
  } finally { await f.close(); }
});

test("assistant capture reserves one identity across completion, failure and compaction callbacks", async () => {
  const gate = barrier();
  const f = await callerFixture({ history: [completedAssistant()], fetch: async (route) => {
    if (route === "/items") { await gate.wait(); return jsonResponse(captureReceipt); }
  } });
  const running = f.hooks.compaction({ sessionID });
  try {
    await gate.entered;
    for (const type of ["session.execution.succeeded", "session.execution.failed"])
      await f.emit({ type, location: { directory: location }, data: { sessionID } });
    const overlap = f.hooks.compaction({ sessionID });
    await new Promise(setImmediate);
    assert.equal(captureCalls(f).length, 1);
    gate.release();
    await Promise.all([running, overlap]);
    await f.hooks.compaction({ sessionID });
    assert.equal(captureCalls(f).length, 1, "valid receipt suppresses a repeated callback");
    assert.equal(captureCalls(f)[0].body[0].content, "שלום answer 😀");
  } finally { gate.release(); await running; await f.close(); }
});

for (const fault of ["precommit", "committed response lost", "malformed", "empty", "multiple", "blank id", "nonstring id"]) {
  test(`assistant capture retries the same source identity after ${fault}`, async () => {
    const stored = new Map();
    let attempts = 0;
    const f = await callerFixture({ history: [completedAssistant()], fetch: async (route, body) => {
      if (route !== "/items") return;
      attempts++;
      if (attempts === 1 && fault === "precommit") return { ok: false };
      if (!stored.has(body[0].source_id)) stored.set(body[0].source_id, structuredClone(body[0]));
      if (attempts === 1) {
        if (fault === "committed response lost") throw new Error("committed response lost");
        const invalid = { malformed: {}, empty: [], multiple: [...captureReceipt, ...captureReceipt],
          "blank id": [{ source_item_id: "  " }], "nonstring id": [{ source_item_id: 1 }] };
        return jsonResponse(invalid[fault]);
      }
      return jsonResponse(captureReceipt);
    } });
    try {
      await f.hooks.compaction({ sessionID });
      await f.hooks.compaction({ sessionID });
      await f.hooks.compaction({ sessionID });
      assert.equal(attempts, 2);
      assert.equal(stored.size, 1);
      assert.equal(captureCalls(f)[0].body[0].source_id, captureCalls(f)[1].body[0].source_id);
      assert.equal([...stored.values()][0].content, "שלום answer 😀");
    } finally { await f.close(); }
  });
}

test("assistant capture identity survives reload and separates actor, container, session and native IDs", async () => {
  const sources = [];
  const capture = async (id = sessionID, native = "msg_answer") => {
    const f = await callerFixture({ roleSessionID: id, history: [completedAssistant(native)], fetch: async (route) => {
      if (route === "/items") return jsonResponse(captureReceipt);
    } });
    try {
      await f.hooks.compaction({ sessionID: id });
      const payload = captureCalls(f)[0].body[0];
      sources.push(payload.source_id);
      assert.equal(payload.source_id, ocNativeMessageSourceId("assistant", id, native));
      assert.equal(payload.content, "שלום answer 😀");
    } finally { await f.close(); }
  };
  removeSessionPin(sessionID);
  try {
    await capture();
    await capture();
    await capture(sessionID, "msg_other_answer");
    await capture("ses_other_capture");
    process.env.PALLIUM_HOOK_ACTOR_REF = "other-actor";
    await capture();
    process.env.PALLIUM_HOOK_ACTOR_REF = "fixture-actor";
    pinContainer(sessionID, "path:other:123", undefined, "fixture-actor");
    await capture();
    assert.equal(sources[0], sources[1]);
    assert.equal(new Set(sources).size, 3);
  } finally { process.env.PALLIUM_HOOK_ACTOR_REF = "fixture-actor"; removeSessionPin(sessionID); removeSessionPin("ses_other_capture"); }
});

test("different assistant identities can capture while another identity is in flight", async () => {
  const gate = barrier();
  const history = [completedAssistant()];
  const f = await callerFixture({ history, fetch: async (route, body) => {
    if (route !== "/items") return;
    if (body[0].content === "שלום answer 😀") await gate.wait();
    return jsonResponse(captureReceipt);
  } });
  const first = f.hooks.compaction({ sessionID });
  try {
    await gate.entered;
    history.splice(0, history.length, { type: "user", id: "msg_next_user", text: "next question" },
      completedAssistant("msg_next", "next"), { type: "idle", id: "msg_next_idle" });
    await f.hooks.prompt({ sessionID, messageID: "msg_next_user", prompt: { text: "next question" } });
    await f.hooks.compaction({ sessionID });
    assert.equal(captureCalls(f).length, 2);
    assert.notEqual(captureCalls(f)[0].body[0].source_id, captureCalls(f)[1].body[0].source_id);
  } finally { gate.release(); await first; await f.close(); }
});

for (const invalid of [undefined, "", "not-native", "msg_", 1]) {
  test(`assistant capture does not fall back from invalid latest ID ${String(invalid)}`, async () => {
    const history = [completedAssistant("msg_old"), { ...completedAssistant(), id: invalid }];
    const f = await callerFixture({ history });
    try { await f.hooks.compaction({ sessionID }); assert.equal(captureCalls(f).length, 0); }
    finally { await f.close(); }
  });
}

for (const completed of [undefined, null, "1", NaN, Infinity]) {
  test(`assistant capture requires finite completion on every selected assistant: ${String(completed)}`, async () => {
    const earlier = completedAssistant("msg_step");
    const history = [earlier, completedAssistant()];
    earlier.time.completed = completed;
    const f = await callerFixture({ history, fetch: async (route) => {
      if (route === "/items") return jsonResponse(captureReceipt);
    } });
    try {
      await f.hooks.compaction({ sessionID });
      assert.equal(captureCalls(f).length, 0);
      earlier.time.completed = 1;
      await f.hooks.compaction({ sessionID });
      assert.equal(captureCalls(f).length, 2, "each valid native assistant output keeps its own source identity");
    } finally { await f.close(); }
  });
}

for (const text of ["", "   ", "😀".repeat(10000), "😀".repeat(10000) + "x"]) {
  test(`assistant capture preserves the nonempty and UTF-16 boundary: ${text.length} units`, async () => {
    const f = await callerFixture({ history: [completedAssistant("msg_boundary", text)], fetch: async (route) => {
      if (route === "/items") return jsonResponse(captureReceipt);
    } });
    try {
      await f.hooks.compaction({ sessionID });
      const eligible = text.trim().length > 0 && text.length <= 20000;
      assert.equal(captureCalls(f).length, eligible ? 1 : 0);
      if (eligible) assert.equal(captureCalls(f)[0].body[0].content, text);
    } finally { await f.close(); }
  });
}

test("assistant capture keeps latest-user multi-step text and work trace while skipping tool-only", async () => {
  const tool = { type: "tool", name: "read", state: { status: "completed", input: { filePath: "/tmp/fixture.txt" }, content: [{ type: "text", text: "read result" }] } };
  const history = [{ ...completedAssistant("invalid", "previous turn"), time: {} }, { type: "idle", id: "msg_prior_idle" },
    { type: "user", id: "msg_question", text: "question" }, { ...completedAssistant("msg_tool", ""), content: [tool] }];
  const f = await callerFixture({ history, fetch: async (route) => {
    if (route === "/items") return jsonResponse(captureReceipt);
  } });
  try {
    await f.hooks.compaction({ sessionID });
    assert.equal(captureCalls(f).length, 0);
    history.splice(history.length - 1, 0, completedAssistant("msg_middle", "first"), completedAssistant("msg_final", "last 😀"));
    await f.hooks.compaction({ sessionID });
    assert.equal(captureCalls(f).length, 2);
    const first = captureCalls(f).find((call) => call.body[0].source_id === ocNativeMessageSourceId("assistant", sessionID, "msg_middle")).body[0];
    const last = captureCalls(f).find((call) => call.body[0].source_id === ocNativeMessageSourceId("assistant", sessionID, "msg_final")).body[0];
    assert.equal(first.content, "first");
    assert.equal(last.content, "last 😀");
    assert.deepEqual(first.metadata.agent_work_trace_turn.files_read, ["/tmp/fixture.txt"]);
    assert.deepEqual(last.metadata.agent_work_trace_turn.files_read, ["/tmp/fixture.txt"]);
    await f.hooks.compaction({ sessionID });
    assert.equal(captureCalls(f).length, 2);
  } finally { await f.close(); }
});

test("assistant capture ignores no assistant and unfinished latest without older fallback", async () => {
  const history = [];
  const f = await callerFixture({ history, fetch: async (route) => {
    if (route === "/items") return jsonResponse(captureReceipt);
  } });
  try {
    await f.hooks.compaction({ sessionID });
    history.push(sourceUser("msg_incomplete_source", "question"), completedAssistant("msg_old"),
      { ...completedAssistant(), time: {} }, { type: "idle", id: "msg_incomplete_idle" });
    await f.hooks.prompt({ sessionID, messageID: "msg_incomplete_source", prompt: { text: "question" } });
    await f.hooks.compaction({ sessionID });
    assert.equal(captureCalls(f).length, 0);
    history.at(-2).time.completed = 2;
    await f.hooks.compaction({ sessionID });
    assert.equal(captureCalls(f).length, 2);
  } finally { await f.close(); }
});

test("assistant history move is revalidated before writing", async () => {
  const gate = barrier();
  let directory = location;
  const f = await callerFixture({ get: async () => ({ location: { directory } }), context: async () => {
    await gate.wait(); return { data: [completedAssistant()] };
  } });
  const running = f.hooks.compaction({ sessionID });
  try {
    await gate.entered;
    directory = "/tmp/other-owner";
    gate.release();
    await running;
    assert.equal(captureCalls(f).length, 0);
  } finally { gate.release(); await running; await f.close(); }
});

test("assistant capture requires valid IDs on earlier selected steps too", async () => {
  const earlier = completedAssistant("invalid");
  const history = [earlier, completedAssistant()];
  const f = await callerFixture({ history, fetch: async (route) => {
    if (route === "/items") return jsonResponse(captureReceipt);
  } });
  try {
    await f.hooks.compaction({ sessionID });
    assert.equal(captureCalls(f).length, 0);
    earlier.id = "msg_step";
    await f.hooks.compaction({ sessionID });
    assert.equal(captureCalls(f).length, 2);
  } finally { await f.close(); }
});

test("assistant receipt with lost native ownership remains retryable", async () => {
  let directory = location;
  let attempts = 0;
  const f = await callerFixture({ history: [completedAssistant()], get: async () => ({ location: { directory } }),
    fetch: async (route) => {
      if (route !== "/items") return;
      if (++attempts === 1) directory = "/tmp/new-owner";
      return jsonResponse(captureReceipt);
    } });
  try {
    await f.hooks.compaction({ sessionID });
    directory = location;
    await f.hooks.compaction({ sessionID });
    await f.hooks.compaction({ sessionID });
    assert.equal(captureCalls(f).length, 2);
    assert.equal(captureCalls(f)[0].body[0].source_id, captureCalls(f)[1].body[0].source_id);
  } finally { await f.close(); }
});

test("disposed assistant HTTP continuation cannot capture again", async () => {
  const gate = barrier();
  const f = await callerFixture({ history: [completedAssistant()], fetch: async (route) => {
    if (route !== "/items") return;
    return { ok: true, text: async () => { await gate.wait(); return JSON.stringify(captureReceipt); } };
  } });
  const running = f.hooks.compaction({ sessionID });
  try {
    await gate.entered;
    await f.dispose();
    gate.release();
    await running;
    await f.hooks.compaction({ sessionID });
    await f.emit({ type: "session.execution.succeeded", data: { sessionID } });
    assert.equal(captureCalls(f).length, 1);
    assert.equal(captureCalls(f)[0].signal.aborted, true);
  } finally { gate.release(); await running; await f.close(); }
});

for (const retire of ["delete", "rebind"]) {
  test(`assistant ${retire} releases the captured reservation without clearing a successor`, async () => {
    const firstGate = barrier(), successorGate = barrier();
    let generation = 0, attempts = 0;
    const history = [completedAssistant()];
    const f = await callerFixture({ history, fetch: async (route) => {
      if (route !== "/items") return;
      const gate = ++attempts === 1 ? firstGate : successorGate;
      // The transport resolves on abort, but its underlying body may finish late.
      return { ok: true, text: async () => { await gate.wait(); return JSON.stringify(captureReceipt); } };
    }, response: async (route) => {
      if (route === "/relay/turn") return { session: { ...relaySession, scope_generation: generation }, deliveries: [] };
      if (route === "/relay/opencode/wake") return { session: { ...relaySession, scope_generation: generation }, wake: null, deliveries: [] };
    } });
    const first = f.hooks.compaction({ sessionID });
    let successor;
    try {
      await firstGate.entered;
      if (retire === "delete") {
        await f.emit({ type: "session.deleted", data: { sessionID } });
        firstGate.release();
        await first;
        await f.hooks.compaction({ sessionID });
        assert.equal(captureCalls(f).length, 1, "a deleted session has no surviving source snapshot for a successor capture");
        return;
      } else {
        generation = 1;
        history.splice(0, history.length, sourceUser("msg_rebind", "new turn"),
          completedAssistant("msg_rebound_answer", "successor"), { type: "idle", id: "msg_rebound_idle" });
        await f.hooks.prompt({ sessionID, messageID: "msg_rebind", prompt: { text: "new turn" } });
      }
      successor = f.hooks.compaction({ sessionID });
      await successorGate.entered;
      firstGate.release();
      await first;
      await f.hooks.compaction({ sessionID });
      assert.equal(captureCalls(f).length, 2, "old finally cannot release successor reservation or mark its success");
      successorGate.release();
      await successor;
      await f.hooks.compaction({ sessionID });
      assert.equal(captureCalls(f).length, 2);
    } finally { firstGate.release(); successorGate.release(); await first; await successor; await f.close(); }
  });
}

test("fresh owned assistant completion captures once while foreign and failed lookups read no context", async () => {
  const id = "ses_first_completion";
  const captured = barrier();
  const reads = [];
  const history = [{ type: "assistant", id: "msg_first_answer", time: { completed: 1 }, content: [{ type: "text", text: "first owned answer" }] }];
  const f = await callerFixture({ roleSessionID: id, history, get: async ({ sessionID: requested }) => {
    if (requested === "ses_failed_completion") throw new Error("native lookup failed");
    return { location: { directory: requested === "ses_foreign_completion" ? "/tmp/foreign" : location } };
  }, context: async ({ sessionID: requested }) => { reads.push(requested); return { data: history }; },
  response: async (route) => { if (route === "/items") { await captured.wait(); return [{ source_item_id: "first-answer" }]; } } });
  try {
    await f.emit({ type: "session.execution.succeeded", data: { sessionID: id } });
    await captured.entered;
    captured.release();
    await new Promise(setImmediate);
    await f.hooks.compaction({ sessionID: id });
    const items = f.calls.filter((call) => call.path === "/items");
    assert.equal(items.length, 1);
    assert.equal(items[0].body[0].thread_ref, id);
    assert.equal(items[0].body[0].container_ref, container);
    assert.equal(items[0].body[0].content, "first owned answer");
    const ownedReads = reads.length;
    for (const requested of ["ses_foreign_completion", "ses_failed_completion"]) {
      await f.hooks.compaction({ sessionID: requested });
    }
    assert.equal(reads.length, ownedReads);
    assert.equal(f.calls.filter((call) => call.path === "/items").length, 1);
  } finally { captured.release(); await f.close(); }
});

test("fresh assistant ownership lookup cannot read context after disposal", async () => {
  const id = "ses_initial_disposal";
  const gate = barrier();
  let reads = 0;
  const f = await callerFixture({ get: async ({ sessionID: requested }) => {
    if (requested === id) await gate.wait();
    return { location: { directory: location } };
  }, context: async () => { reads++; return { data: [] }; } });
  const running = f.hooks.compaction({ sessionID: id });
  try {
    await gate.entered;
    await f.dispose();
    gate.release();
    await running;
    assert.equal(reads, 0);
    assert.equal(f.calls.filter((call) => call.path === "/items").length, 0);
  } finally { gate.release(); await running; await f.close(); }
});

for (const deleted of [false, true]) {
  test(`assistant ownership lookup ${deleted ? "rejects deletion and recreation" : "survives session creation"} with a source snapshot`, async () => {
    const id = deleted ? "ses_initial_replaced" : "ses_initial_created";
    const gate = barrier();
    const history = [{ type: "assistant", id: "msg_initial_answer", time: { completed: 1 }, content: [{ type: "text", text: "current answer" }] }];
    let lookups = 0, reads = 0, blockLookup = false;
    const f = await callerFixture({ history, roleSessionID: id, get: async ({ sessionID: requested }) => {
      if (requested === id && blockLookup && ++lookups === 1) await gate.wait();
      return { location: { directory: location } };
    }, context: async () => { reads++; return { data: history }; } });
    blockLookup = true;
    const running = f.hooks.compaction({ sessionID: id });
    try {
      await gate.entered;
      if (deleted) await f.emit({ type: "session.deleted", data: { sessionID: id } });
      await f.emit({ type: "session.created", data: { sessionID: id } });
      assert.ok(lookups > 1, "ownership is rechecked after the session event races with lookup");
      gate.release();
      await running;
      assert.equal(reads, deleted ? 0 : 1);
      assert.equal(f.calls.filter((call) => call.path === "/items").length, deleted ? 0 : 1);
      if (deleted) {
        history.splice(0, history.length, sourceUser("msg_recreated_source", "question"),
          completedAssistant("msg_recreated_answer"), { type: "idle", id: "msg_recreated_idle" });
        await f.hooks.prompt({ sessionID: id, messageID: "msg_recreated_source", prompt: { text: "question" } });
        await f.hooks.compaction({ sessionID: id });
        assert.equal(reads, 1);
        assert.equal(f.calls.filter((call) => call.path === "/items").length, 1);
      }
    } finally { gate.release(); await running; await f.close(); }
  });
}

for (const existing of [false, true]) {
  test(`unrelated session retirement preserves ${existing ? "existing" : "fresh"} assistant capture`, async () => {
    const id = `ses_assistant_${existing ? "existing" : "fresh"}`;
    const gate = barrier();
    const history = [{ type: "assistant", id: "msg_unrelated_retirement", time: { completed: 1 }, content: [{ type: "text", text: "captured answer" }] }];
    let block = false, reads = 0;
    const f = await callerFixture({ history, roleSessionID: id, get: async ({ sessionID: requested }) => {
      if (block && requested === id) await gate.wait();
      return { location: { directory: location } };
    }, context: async () => { reads++; return { data: history }; } });
    try {
      if (existing) await f.hooks.context({ sessionID: id, messages: [natural("msg_seed_existing")] });
      const initialReads = reads;
      block = true;
      const running = f.hooks.compaction({ sessionID: id });
      await gate.entered;
      await f.emit({ type: "session.deleted", data: { sessionID: "ses_unrelated_retirement" } });
      gate.release();
      await running;
      assert.equal(reads, initialReads + 1);
      assert.equal(f.calls.filter((call) => call.path === "/items").length, 1);
    } finally { gate.release(); await f.close(); }
  });
}

test("concurrent assistant probes keep successor retirement tokens through stale cleanup", async () => {
  const id = "ses_concurrent_assistant";
  const oldGate = barrier(), successorGate = barrier();
  let gets = 0, reads = 0;
  const history = [{ type: "assistant", id: "msg_concurrent_assistant", time: { completed: 1 }, content: [{ type: "text", text: "answer" }] }];
  const f = await callerFixture({ history, get: async ({ sessionID: requested }) => {
    if (requested !== id) return { location: { directory: location } };
    const call = ++gets;
    if (call <= 2) await oldGate.wait();
    else await successorGate.wait();
    return { location: { directory: location } };
  }, context: async () => { reads++; return { data: history }; } });
  const old = [f.hooks.compaction({ sessionID: id }), f.hooks.compaction({ sessionID: id })];
  let successor;
  try {
    await oldGate.entered;
    assert.equal(gets, 2, "both same-ID probes registered before retirement");
    await f.emit({ type: "session.deleted", data: { sessionID: id } });
    successor = f.hooks.compaction({ sessionID: id });
    await successorGate.entered;
    oldGate.release();
    await Promise.all(old);
    await f.emit({ type: "session.deleted", data: { sessionID: id } });
    successorGate.release();
    await successor;
    assert.equal(reads, 0, "the second deletion must still find and invalidate the successor probe");
    assert.equal(f.calls.filter((call) => call.path === "/items").length, 0);
  } finally { oldGate.release(); successorGate.release(); await Promise.all([...old, successor]); await f.close(); }
});

for (const sameSession of [true, false]) test(`${sameSession ? "same-session" : "unrelated"} deletion after ownership ${sameSession ? "fences" : "preserves"} assistant completion`, async () => {
  const id = "ses_helper_success_retired";
  const retiredId = sameSession ? id : "ses_helper_unrelated";
  const deletion = barrier();
  const previousFetch = globalThis.fetch;
  const previousInterval = globalThis.setInterval;
  const previousClear = globalThis.clearInterval;
  const hooks = {};
  const calls = [];
  let nextEvent, reads = 0, queueDeletion = false, deletionQueued = false, deletionDelivered = false;
  let resolveDeletionHandled, deletionHandledResolved = false;
  const deletionHandled = new Promise((resolve) => { resolveDeletionHandled = resolve; });
  let dispose;
  globalThis.setInterval = () => ({ unref() {} });
  globalThis.clearInterval = () => {};
  globalThis.fetch = async (url, init) => {
    const route = new URL(url).pathname;
    calls.push({ path: route, body: init?.body ? JSON.parse(init.body) : {} });
    if (route === "/relay/sessions/close") await deletion.wait();
    return jsonResponse(route === "/relay/sessions" ? [] : {});
  };
  const ctx = {
    location: { directory: location }, app: { log() {} },
    session: {
      hook: async (name, callback) => { hooks[name] = callback; return { dispose() {} }; },
      get: async ({ sessionID: requested }) => {
        assert.equal(requested, id, "only the fresh completion performs this lookup");
        return { location: { get directory() {
        if (queueDeletion && !deletionQueued) {
          deletionQueued = true;
          deletionDelivered = true;
          assert.equal(typeof nextEvent, "function", "the public subscriber already awaits its next event");
          // Resolve the supported event iterator after owned's final current check.
          // Its consumer retires the absent entry in the next microtask, before
          // ingestAssistant resumes from the successfully resolved owned promise.
          nextEvent({ value: { type: "session.deleted", data: { sessionID: retiredId } }, done: false });
        }
        return location;
      } } };
      },
      context: async () => {
        reads++;
        return { data: history };
      },
    },
    event: { subscribe: ({ signal }) => ({
      [Symbol.asyncIterator]() { return this; },
      next() {
        if (deletionDelivered && !deletionHandledResolved) {
          deletionHandledResolved = true;
          resolveDeletionHandled();
        }
        if (signal.aborted) return Promise.resolve({ done: true });
        return new Promise((resolve) => {
          nextEvent = resolve;
          signal.addEventListener("abort", () => resolve({ done: true }), { once: true });
        });
      },
    }) },
  };
  const history = [sourceUser("msg_overtaken_source", "question"),
    { type: "assistant", id: "msg_overtaken_answer", time: { completed: 1 }, content: [{ type: "text", text: "retired answer" }] },
    { type: "idle", id: "msg_overtaken_idle" }];
  try {
    removeSessionPin(id);
    dispose = await v2.setup(ctx);
    await hooks.prompt({ sessionID: id, messageID: "msg_overtaken_source", prompt: { text: "question" } });
    queueDeletion = true;
    await hooks.compaction({ sessionID: id });
    assert.equal(reads, sameSession ? 0 : 1);
    assert.equal(calls.filter((call) => call.path === "/items").length, sameSession ? 0 : 1);
    await deletion.entered;
    deletion.release();
    await deletionHandled;
    assert.equal(deletionQueued, true, "the supported location read succeeds before deletion");
    assert.equal(calls.filter((call) => call.path === "/relay/sessions/close" && call.body.session_ref === retiredId).length, 1,
      "the public deletion callback retired the absent entry and issued its close");
    assert.equal(getPinnedContainer(id), sameSession ? null : container);
    await dispose();
    assert.equal(calls.filter((call) => call.body.operation === "detach").length, 0,
      "the retired callback must not recreate state with a remote endpoint");
  } finally {
    deletion.release();
    try { await dispose?.(); } finally {
      globalThis.fetch = previousFetch;
      globalThis.setInterval = previousInterval;
      globalThis.clearInterval = previousClear;
    }
  }
});

test("assistant ownership helper cannot mark a rebound lifetime as captured", async () => {
  const captureOwned = barrier(), rebindOwned = barrier();
  let captureCheck = false, rebindCheck = false, generation = 0;
  const f = await callerFixture({ history: [completedAssistant()], get: () => {
    if (captureCheck) { captureCheck = false; return captureOwned.wait().then(() => ({ location: { directory: location } })); }
    if (rebindCheck) { rebindCheck = false; return rebindOwned.wait().then(() => ({ location: { directory: location } })); }
    return { location: { directory: location } };
  }, fetch: async (route) => {
    if (route === "/items") { captureCheck = true; return jsonResponse(captureReceipt); }
  }, response: async (route) => {
    if (route === "/relay/turn") { rebindCheck = true; return { session: { ...relaySession, scope_generation: generation }, deliveries: [] }; }
    if (route === "/relay/opencode/wake") return { session: { ...relaySession, scope_generation: generation }, wake: null, deliveries: [] };
  } });
  let rebound;
  const first = f.hooks.compaction({ sessionID });
  try {
    await captureOwned.entered;
    generation = 1;
    rebound = f.hooks.context({ sessionID, messages: [natural("msg_helper_rebind")] });
    await rebindOwned.entered;
    // Both helpers finish under the old lifetime; rebind resumes before capture.
    rebindOwned.release();
    captureOwned.release();
    await Promise.all([rebound, first]);
    assert.ok(f.calls.some((call) => call.body.operation === "enroll" && call.body.scope_generation === 1),
      "same-item rebind must establish the successor generation");
    await f.hooks.compaction({ sessionID });
    assert.equal(captureCalls(f).length, 2, "old success must not suppress the successor's capture");
    assert.equal(captureCalls(f)[0].body[0].source_id, captureCalls(f)[1].body[0].source_id);
  } finally { captureOwned.release(); rebindOwned.release(); await first; await rebound; await f.close(); }
});

for (const bodyStall of [false, true]) {
  test(`retired natural context cannot attach or ACK after stalled Relay ${bodyStall ? "body" : "turn"}`, async () => {
    const gate = barrier();
    const value = { session: relaySession, deliveries: [delivery] };
    const f = await callerFixture({ fetch: async (route) => {
      if (route !== "/relay/turn") return;
      if (!bodyStall) { await gate.wait(); return jsonResponse(value); }
      return { ok: true, text: async () => { await gate.wait(); return JSON.stringify(value); } };
    } });
    const user = natural();
    const before = structuredClone(user);
    const running = f.hooks.context({ sessionID, messages: [user] });
    try {
      await gate.entered;
      await f.dispose();
      const enrolled = f.calls.filter((c) => c.body.operation === "enroll").length;
      gate.release();
      await running;
      await pause();
      assert.deepEqual(user, before);
      assert.equal(f.calls.filter((c) => c.path === "/relay/deliveries/ack").length, 0);
      assert.equal(f.calls.filter((c) => c.body.operation === "enroll").length, enrolled);
    } finally { gate.release(); await running; await f.close(); }
  });
}

test("retired verified wake context fails closed without attachment or ACK", async () => {
  const gate = barrier();
  const f = await callerFixture({ wake: snapshot(), response: async (_route, body) => {
    if (body.operation === "context") { await gate.wait(); return { session: relaySession, wake: snapshot(), deliveries: [delivery] }; }
  } });
  const user = projectedWake();
  const before = structuredClone(user);
  const running = f.hooks.context({ sessionID, messages: [user] });
  // Attach a rejection handler immediately; a cancelled request may reject before release.
  const outcome = running.then(() => null, (error) => error);
  try {
    await gate.entered;
    await f.dispose();
    gate.release();
    assert.ok(await outcome, "verified internal wake must reject when its context cannot attach");
    assert.deepEqual(user, before);
    assert.equal(f.calls.filter((c) => c.path === "/relay/deliveries/ack").length, 0);
  } finally { gate.release(); await outcome; await f.close(); }
});

test("retired prompt ownership continuation cannot capture or pin", async () => {
  const gate = barrier();
  let block = false;
  const f = await callerFixture({ get: async () => { if (block) await gate.wait(); return { location: { directory: location } }; } });
  removeSessionPin(sessionID);
  block = true;
  const running = f.hooks.prompt({ sessionID, messageID: "msg_retired", prompt: { text: "ordinary work" } });
  try {
    await gate.entered;
    await f.dispose();
    gate.release();
    await running;
    assert.equal(f.calls.filter((c) => c.path === "/item-and-query").length, 0);
    assert.equal(getPinnedContainer(sessionID), null);
  } finally { gate.release(); await running; await f.close(); }
});

test("retired assistant history continuation cannot capture", async () => {
  const gate = barrier();
  const f = await callerFixture({ context: async () => { await gate.wait(); return { data: [completedAssistant()] }; } });
  const running = f.hooks.compaction({ sessionID });
  try {
    await gate.entered;
    await f.dispose();
    gate.release();
    await running;
    assert.equal(f.calls.filter((c) => c.path === "/items").length, 0);
  } finally { gate.release(); await running; await f.close(); }
});

test("retired context ownership continuation cannot create a Relay session", async () => {
  const gate = barrier();
  let block = false;
  const f = await callerFixture({ get: async () => { if (block) await gate.wait(); return { location: { directory: location } }; } });
  block = true;
  const user = natural();
  const before = structuredClone(user);
  const running = f.hooks.context({ sessionID, messages: [user] });
  try {
    await gate.entered;
    await f.dispose();
    gate.release();
    await running;
    assert.equal(f.calls.filter((c) => c.path === "/relay/turn").length, 0);
    assert.deepEqual(user, before);
  } finally { gate.release(); await running; await f.close(); }
});

test("retired discovery ownership continuation cannot resurrect an entry", async () => {
  const gate = barrier();
  const f = await callerFixture({ get: async () => { await gate.wait(); return { location: { directory: location } }; } });
  try {
    await gate.entered;
    await f.dispose();
    gate.release();
    await pause();
    const detached = f.calls.filter((c) => c.body.operation === "detach").length;
    await f.dispose();
    assert.equal(f.calls.filter((c) => c.body.operation === "detach").length, detached);
    assert.equal(f.calls.filter((c) => c.body.operation === "enroll").length, 0);
  } finally { gate.release(); await f.close(); }
});

test("retired restore discovery cannot enroll or resurrect an entry", async () => {
  const gate = barrier();
  let block = false;
  const f = await callerFixture({ list: [[]], fetch: async (route) => {
    if (block && route === "/relay/sessions") { await gate.wait(); return jsonResponse([relaySession]); }
  } });
  try {
    block = true;
    await f.emit({ type: "session.created", location: { directory: location }, data: { sessionID } });
    await gate.entered;
    await f.dispose();
    gate.release();
    await pause();
    assert.equal(f.calls.filter((c) => c.body.operation === "enroll").length, 0);
    await f.dispose();
    assert.equal(f.calls.filter((c) => c.body.operation === "detach").length, 0);
  } finally { gate.release(); await f.close(); }
});

test("retired enrollment response cannot resurrect a disposed entry", async () => {
  const gate = barrier();
  const f = await callerFixture({ response: async (_route, body) => {
    if (body.operation === "enroll") { await gate.wait(); return { session: relaySession, wake: snapshot() }; }
  } });
  try {
    await gate.entered;
    await f.dispose();
    const detached = f.calls.filter((c) => c.body.operation === "detach").length;
    gate.release();
    await pause();
    await f.dispose();
    assert.equal(f.calls.filter((c) => c.body.operation === "detach").length, detached);
    assert.equal(f.native.prompt.length, 0);
  } finally { gate.release(); await f.close(); }
});

test("retired startup discovery cannot enroll returned sessions", async () => {
  const gate = barrier();
  const f = await callerFixture({ fetch: async (route) => {
    if (route === "/relay/sessions") { await gate.wait(); return jsonResponse([relaySession]); }
  } });
  try {
    await gate.entered;
    await f.dispose();
    gate.release();
    await pause();
    assert.equal(f.calls.filter((c) => c.body.operation === "enroll").length, 0);
    await f.dispose();
    assert.equal(f.calls.filter((c) => c.body.operation === "detach").length, 0);
  } finally { gate.release(); await f.close(); }
});

test("retired enrollment ownership continuation cannot start enrollment", async () => {
  const gate = barrier();
  let ownershipCalls = 0;
  const f = await callerFixture({ get: async () => {
    if (++ownershipCalls === 2) await gate.wait();
    return { location: { directory: location } };
  } });
  try {
    await gate.entered;
    await f.dispose();
    gate.release();
    await pause();
    assert.equal(f.calls.filter((c) => c.body.operation === "enroll").length, 0);
  } finally { gate.release(); await f.close(); }
});

test("retired wake history continuation cannot issue a native prompt", async () => {
  const gate = barrier();
  const f = await callerFixture({ wake: snapshot(), context: async () => { await gate.wait(); return { data: [] }; } });
  try {
    await f.tick();
    await gate.entered;
    await f.dispose();
    gate.release();
    await pause();
    assert.equal(f.native.prompt.length, 0);
    assert.equal(f.native.wait, 0);
  } finally { gate.release(); await f.close(); }
});

test("retired admitted response cannot start native wait", async () => {
  const gate = barrier();
  const f = await callerFixture({ wake: snapshot(), response: async (_route, body) => {
    if (body.operation === "admitted") { await gate.wait(); return { session: relaySession, wake: snapshot({ admitted: true }) }; }
  } });
  try {
    await f.tick();
    await gate.entered;
    await f.dispose();
    gate.release();
    await pause();
    assert.equal(f.native.wait, 0);
    assert.equal(f.calls.filter((c) => c.body.operation === "terminal").length, 0);
  } finally { gate.release(); await f.close(); }
});

test("retired native admission history cannot initiate admitted HTTP", async () => {
  const gate = barrier();
  let reads = 0;
  const f = await callerFixture({ wake: snapshot(), context: async (_input, history) => {
    if (++reads === 2) await gate.wait();
    return { data: history };
  } });
  try {
    await f.tick();
    await gate.entered;
    await f.dispose();
    gate.release();
    await pause();
    assert.equal(f.calls.filter((c) => c.body.operation === "admitted").length, 0);
    assert.equal(f.native.wait, 0);
  } finally { gate.release(); await f.close(); }
});

test("retired native wait continuation cannot settle terminal state", async () => {
  const gate = barrier();
  const f = await callerFixture({ wake: snapshot(), wait: async (history) => {
    await gate.wait(); history.push({ type: "idle", id: "msg_terminal_retired" });
  } });
  try {
    await f.tick();
    await gate.entered;
    await f.dispose();
    gate.release();
    await pause();
    assert.equal(f.calls.filter((c) => c.body.operation === "terminal").length, 0);
    assert.equal(f.native.interrupt, 0);
  } finally { gate.release(); await f.close(); }
});

test("deletion during ACK1 forbids ACK2 and preserves successor context", async () => {
  const gate = barrier();
  const second = { ...delivery, delivery_id: "relay-delivery-" + "c".repeat(32), message_id: "relay-message-second", payload: "second" };
  let turns = 0;
  let committed = false;
  const f = await callerFixture({ response: async (route, body) => {
    if (route === "/relay/turn") return { session: relaySession, deliveries: ++turns === 1 ? [delivery, second] : [] };
    if (route === "/relay/deliveries/ack") {
      if (body.delivery_id === deliveryID) { await gate.wait(); committed = true; }
      return { delivery_id: body.delivery_id, state: "delivered", already_delivered: false };
    }
  } });
  const running = f.hooks.context({ sessionID, messages: [natural()] });
  try {
    await gate.entered;
    await f.emit({ type: "session.deleted", location: { directory: location }, data: { sessionID } });
    const successor = natural("msg_successor");
    await f.hooks.context({ sessionID, messages: [successor] });
    const before = structuredClone(successor);
    gate.release();
    await running;
    assert.equal(committed, true, "an already-issued ACK may commit after retirement");
    assert.deepEqual(f.calls.filter((c) => c.path === "/relay/deliveries/ack").map((c) => c.body.delivery_id), [deliveryID]);
    assert.deepEqual(successor, before);
    await f.hooks.context({ sessionID, messages: [natural("msg_successor")] });
    assert.equal(turns, 2, "retired claim must not erase successor claim cache");
  } finally { gate.release(); await running; await f.close(); }
});

test("replaced scope generation fences an older response inside the same entry", async () => {
  const gate = barrier();
  const replacement = { ...relaySession, scope_generation: 1 };
  const f = await callerFixture({ response: async (route, body) => {
    if (route === "/relay/turn") { await gate.wait(); return { session: relaySession, deliveries: [delivery] }; }
    if (body.operation === "poll") return { session: replacement, wake: null, deliveries: [] };
  } });
  const user = natural();
  const before = structuredClone(user);
  const running = f.hooks.context({ sessionID, messages: [user] });
  try {
    await gate.entered;
    await f.tick();
    gate.release();
    await running;
    assert.deepEqual(user, before);
    assert.equal(f.calls.filter((c) => c.path === "/relay/deliveries/ack").length, 0);
    await f.tick();
    assert.equal(f.calls.filter((c) => c.body.operation === "poll").at(-1).body.scope_generation, 1);
  } finally { gate.release(); await running; await f.close(); }
});

for (const blocked of ["detach", "close"]) {
  test(`deletion waiting for ${blocked} preserves a replacement entry and pin`, async () => {
    const gate = barrier();
    let completed;
    const eventDone = new Promise((resolve) => { completed = resolve; });
    let block = true;
    const f = await callerFixture({ afterEvent: completed, fetch: async (route, body) => {
      if (block && (blocked === "detach" ? body.operation === "detach" : route === "/relay/sessions/close")) {
        await gate.wait();
        return jsonResponse({});
      }
    } });
    try {
      await f.emit({ type: "session.deleted", location: { directory: location }, data: { sessionID } });
      await gate.entered;
      await f.hooks.prompt({ sessionID, messageID: "msg_replacement_pin", prompt: { text: "ordinary work" } });
      const successor = natural("msg_replacement_context");
      await f.hooks.context({ sessionID, messages: [successor] });
      const before = structuredClone(successor);
      const pin = getPinnedContainer(sessionID);
      assert.equal(pin, container);
      block = false;
      gate.release();
      await eventDone;
      assert.equal(f.calls.filter((c) => c.path === "/relay/sessions/close").length, blocked === "close" ? 1 : 0);
      assert.equal(getPinnedContainer(sessionID), pin);
      assert.deepEqual(successor, before);
      const turns = f.calls.filter((c) => c.path === "/relay/turn").length;
      await f.hooks.context({ sessionID, messages: [natural("msg_replacement_context")] });
      assert.equal(f.calls.filter((c) => c.path === "/relay/turn").length, turns, "replacement claim survives old deletion cleanup");
    } finally { block = false; gate.release(); await f.close(); }
  });
}

test("successful bounded cleanup detaches every session once after local retirement", async () => {
  const entries = Array.from({ length: 9 }, (_, n) => ({ ...relaySession, session_ref: `ses_drain_${n}` }));
  const detached = [];
  let inflight = 0, maximum = 0;
  const f = await callerFixture({ list: [entries], fetch: async (_route, body) => {
    if (body.operation !== "detach") return;
    assert.deepEqual([...f.retired].sort(), ["compaction", "context", "prompt"]);
    assert.equal(f.eventRetired(), true, "event registration retires before every remote request");
    detached.push(body.session_ref);
    maximum = Math.max(maximum, ++inflight);
    await new Promise(setImmediate);
    inflight--;
    return jsonResponse({});
  } });
  try {
    const cleanup = f.dispose();
    assert.equal(f.dispose(), cleanup);
    await cleanup;
    assert.deepEqual(detached.sort(), entries.map((entry) => entry.session_ref).sort());
    assert.equal(maximum, 4);
    await f.dispose();
    assert.equal(detached.length, entries.length);
  } finally { await f.close(); }
});

test("cleanup attempts all hooks and reports failures after pending retirement finishes", async () => {
  const gate = barrier();
  const f = await callerFixture({ dispose: (name) => {
    if (name === "prompt") throw new Error("synchronous retirement failure");
    if (name === "context") return Promise.reject(new Error("asynchronous retirement failure"));
    return gate.wait();
  } });
  const cleanup = f.dispose();
  let settled = false;
  cleanup.then(() => { settled = true; }, () => { settled = true; });
  try {
    await gate.entered;
    assert.deepEqual(f.retired.sort(), ["compaction", "context", "prompt"]);
    assert.equal(settled, false, "a failure cannot finish cleanup before other hooks retire");
    gate.release();
    await assert.rejects(cleanup, (error) => error instanceof AggregateError && error.errors.length === 2);
    assert.equal(f.dispose(), cleanup);
  } finally { gate.release(); await f.close().catch(() => {}); }
});

test("abort listeners can re-enter disposal without repeating local cleanup", async () => {
  const gate = barrier();
  let nested;
  const f = await callerFixture({ fetch: async (route, _body, init) => {
    if (route !== "/relay/turn") return;
    init.signal.addEventListener("abort", () => { nested = f.dispose(); gate.release(); }, { once: true });
    await gate.wait();
    return jsonResponse({ session: relaySession, deliveries: [delivery] });
  } });
  const running = f.hooks.context({ sessionID, messages: [natural()] });
  try {
    await gate.entered;
    const cleanup = f.dispose();
    await cleanup;
    assert.equal(nested, cleanup);
    await running;
    assert.deepEqual(f.retired.sort(), ["compaction", "context", "prompt"]);
    assert.equal(f.calls.filter((c) => c.path === "/relay/deliveries/ack").length, 0);
  } finally { gate.release(); await running; await f.close(); }
});

for (const count of [0, 1, 9]) {
  test(`bounded disposal retires hooks with ${count} sessions in one remote window`, async () => {
    const entries = Array.from({ length: count }, (_, n) => ({ ...relaySession, session_ref: `ses_cleanup_${n}` }));
    const requests = [];
    let inflight = 0, maximum = 0;
    const f = await callerFixture({ list: [entries], fetch: async (_route, body, init) => {
      if (body.operation !== "detach") return;
      assert.deepEqual([...f.retired].sort(), ["compaction", "context", "prompt"]);
      assert.equal(f.eventRetired(), true, "event registration retires before every remote request");
      const gate = barrier();
      requests.push({ gate, signal: init.signal });
      maximum = Math.max(maximum, ++inflight);
      if (init.signal?.aborted) gate.release();
      init.signal?.addEventListener("abort", gate.release, { once: true });
      await gate.wait();
      inflight--;
      return jsonResponse({});
    } });
    const previousTimeout = globalThis.setTimeout;
    const previousClearTimeout = globalThis.clearTimeout;
    const deadlines = [];
    globalThis.setTimeout = (fn, ms, ...args) => {
      if (ms !== 500) return previousTimeout(fn, ms, ...args);
      const timer = { fn: () => fn(...args), unref() {}, cancelled: false };
      deadlines.push(timer);
      return timer;
    };
    globalThis.clearTimeout = (timer) => {
      if (deadlines.includes(timer)) timer.cancelled = true;
      else previousClearTimeout(timer);
    };
    let finished = false;
    const disposing = f.dispose().then(() => { finished = true; });
    const again = f.dispose();
    try {
      await new Promise(setImmediate);
      assert.deepEqual(f.retired.sort(), ["compaction", "context", "prompt"], "local registrations retire before remote responses");
      assert.equal(requests.length, Math.min(4, count), "start every available cleanup slot after local retirement");
      assert.ok(maximum <= 4, "at most four remote detach requests may be in flight");
      if (count) assert.equal(finished, false, "shutdown must wait for cleanup or its deadline");
      // Advance exactly the existing 500 ms deadlines once. A serial per-session
      // timeout would create another deadline and cannot finish in this window.
      for (const timer of [...deadlines]) if (!timer.cancelled) timer.fn();
      await new Promise(setImmediate);
      assert.equal(finished, true, "all detach requests share one bounded shutdown window");
      assert.ok(requests.length <= count, "repeated disposal cannot repeat cleanup");
      assert.ok(requests.every((request) => request.signal?.aborted || count === 0), "hanging remote cleanup is cancelled at the shared deadline");
      const issued = requests.length;
      await pause();
      assert.equal(requests.length, issued, "no new detach may start after the window closes");
    } finally {
      globalThis.setTimeout = previousTimeout;
      globalThis.clearTimeout = previousClearTimeout;
      for (const request of requests) request.gate.release();
      // Baseline serial cleanup may issue more after a failed assertion.
      const oldFetch = globalThis.fetch;
      globalThis.fetch = async () => jsonResponse({});
      try { await Promise.all([disposing, again]); } finally { globalThis.fetch = oldFetch; await f.close(); }
    }
  });
}
