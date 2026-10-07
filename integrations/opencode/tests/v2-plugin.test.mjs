import test from "node:test";
import assert from "node:assert/strict";
import v1 from "../.opencode/plugins/pallium.mjs";
import v2 from "../server.js";
import { deriveContainerRef } from "../.opencode/plugins/pallium-common.mjs";

const sessionID = "ses_abc123";
const deliveryID = "relay-delivery-" + "a".repeat(32);
const endpointID = "relay-session-" + "b".repeat(32);
const nativeID = "msg_relaywake123";
const location = "/tmp/pallium-v2-exact";
const container = deriveContainerRef(location);
const relaySession = { runtime: "opencode", session_ref: sessionID, container_ref: container,
  endpoint_id: endpointID, scope_generation: 0, state: "recent", destination_health: "active" };
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
  let interval;
  let listed = 0;
  globalThis.setInterval = (fn) => { interval = fn; return { unref() {} }; };
  globalThis.clearInterval = () => {};
  globalThis.fetch = async (url, init) => {
    const path = new URL(url).pathname;
    const body = init?.body ? JSON.parse(init.body) : {};
    calls.push({ path, body });
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
      hook: async (name, fn) => { hooks[name] = fn; return { dispose: async () => {} }; },
      get: async () => ({ location: { directory: location } }),
      context: async () => ({ data: history }),
      prompt: async (input) => {
        native.prompt.push(input);
        history.push({ type: "user", id: input.id, text: input.text, metadata: input.metadata });
        if (options.prompt) return options.prompt(input);
        return { id: input.id };
      },
      wait: async () => { native.wait++; if (options.wait) await options.wait(history, hooks); },
      interrupt: async () => { native.interrupt++; },
    },
    event: { subscribe: async function* ({ signal }) { while (!signal.aborted) await new Promise((resolve) => {
      const timer = setTimeout(resolve, 10);
      signal.addEventListener("abort", () => { clearTimeout(timer); resolve(); }, { once: true });
    }); } },
  };
  const dispose = await v2.setup(ctx);
  await pause();
  return {
    calls, native, hooks, history, listed: () => listed,
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
