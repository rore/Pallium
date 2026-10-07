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
const { deriveContainerRef, getPinnedContainer, removeSessionPin } = await import("../.opencode/plugins/pallium-common.mjs");

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
  const retired = [];
  const events = [];
  let eventReady;
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
      while (!signal.aborted) {
        if (events.length) { yield events.shift(); continue; }
        await new Promise((resolve) => {
          eventReady = resolve;
          signal.addEventListener("abort", resolve, { once: true });
        });
      }
    } },
  };
  const dispose = await v2.setup(ctx);
  await pause();
  return {
    calls, native, hooks, history, retired, dispose, listed: () => listed,
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
  const f = await callerFixture({ context: async () => { await gate.wait(); return { data: [{ type: "assistant", id: "msg_answer", content: [{ type: "text", text: "an answer" }] }] }; } });
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
