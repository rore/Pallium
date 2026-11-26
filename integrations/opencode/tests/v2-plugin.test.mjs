import test, { after } from "node:test";
import assert from "node:assert/strict";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import childProcess from "node:child_process";
import { syncBuiltinESMExports } from "node:module";
import { setTimeout as delay } from "node:timers/promises";
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
const container = await deriveContainerRef(location);
const relaySession = { runtime: "opencode", session_ref: sessionID, container_ref: container,
  endpoint_id: endpointID, scope_generation: 0, alias: "planner", state: "recent", destination_health: "active" };
const delivery = { delivery_id: deliveryID, claim_token: "claim-token", message_id: "relay-message-test",
  sender_runtime: "codex", sender_session_ref: "sender", payload: "שלום wake payload",
  created_at: "2026-10-07T00:00:00Z", attempts: 1 };

test("receipt policy uses strict UTC calendars, original request age and conservative fractional rounding", async () => {
  const { relayReceiptTiming: timing, relayAckNotBefore: due } = await import("../.opencode/plugins/pallium-v2.mjs");
  const base = { claimed_at: "2026-11-17T00:00:00.000001Z", lease_expires_at: "2026-11-17T00:01:00.999999Z", expires_at: null };
  const result = timing(base, 1000, 9000);
  assert.equal(result.deadline, 61998);
  assert.equal(result.deadline - 27000, 34998, "body/cache/emission age is not added back");
  for (const suffix of ["", "Z", "+00:00"]) {
    assert.equal(timing({ ...base, claimed_at: "2026-11-17T00:00:00" + suffix,
      lease_expires_at: "2026-11-17T00:01:00" + suffix }, 1000, 9000).deadline, 61000);
  }
  assert.equal(timing({ ...base, claimed_at: "2026-11-17T02:00:00+02:00",
    lease_expires_at: "2026-11-16T23:01:00-01:00" }, 1000, 9000).deadline, 61000);
  assert.equal(timing({ ...base, expires_at: "2026-11-17T00:00:30Z" }, 1000, 9000).deadline, 30999);
  for (const invalid of [undefined, "", "2026-02-29T00:00:00Z", "2026-04-31T00:00:00Z", "0000-01-01T00:00:00Z",
    "2026-11-17T24:00:00Z", "2026-11-17T00:00:60Z", "2026-11-17T00:00:00+24:00",
    "2026-11-17T00:00:00+00:60", "2026-11-17T00:00:00.1234567Z", " 2026-11-17T00:00:00Z",
    "2026-11-17T00:00:00Z\n", "2026-11-17 00:00:00"]) {
    assert.equal(timing({ ...base, claimed_at: invalid }, 1000, 9000), null, String(invalid));
  }
  for (const patch of [{ expires_at: undefined }, { expires_at: "bad" }, { expires_at: "2026-11-16T00:00:00Z" },
    { lease_expires_at: base.claimed_at }]) assert.equal(timing({ ...base, ...patch }, 1000, 9000), null);
  assert.equal(timing(base, 1000, 999), null);
  assert.equal(timing(base, Infinity, 9000), null);
  assert.equal(due(" \t0002\t ", 10000, result), 12000);
  assert.equal(due("0", 10000, result), 10000);
  assert.equal(due("", 10000, result), -Infinity);
  assert.equal(due(null, 10000, result), -Infinity);
  const date = "Tue, 17 Nov 2026 00:00:10 GMT";
  assert.equal(due(date, 16000, result), 19000);
  assert.equal(due("Tue, 17 Nov 2026 00:00:00 GMT", 16000, result), 16000);
  for (const invalid of ["-1", "+1", "1.5", "1e3", "Infinity", "9".repeat(100), "Mon, 17 Nov 2026 00:00:10 GMT",
    "Tuesday, 17-Nov-26 00:00:10 GMT", "Tue Nov 17 00:00:10 2026", "Tue, 17 Nov 2026 24:00:00 GMT", "\n2\n", "2\n"]) {
    assert.equal(due(invalid, 10000, result), null, invalid);
  }
  const oldNow = Date.now;
  try {
    for (const wall of [0, 1e15, -1e15]) {
      Date.now = () => wall;
      assert.deepEqual(timing(base, 1000, 9000), result);
      assert.equal(due(date, 16000, result), 19000);
    }
  } finally { Date.now = oldNow; }
});

test("ordinary emitted receipt coalesces repeated contexts and recovers on the existing interval", async () => {
  const ackCalls = [];
  const receipt = { ...delivery, claimed_at: "2026-11-17T00:00:00Z",
    lease_expires_at: "2026-11-17T00:01:00Z", expires_at: null };
  const f = await callerFixture({ response: (pathname, body) => {
    if (pathname === "/relay/turn") return { session: relaySession, deliveries: [receipt] };
    if (pathname === "/relay/deliveries/ack") {
      ackCalls.push(body);
      return ackCalls.length === 1 ? null : { delivery_id: body.delivery_id, state: "delivered", already_delivered: false };
    }
  } });
  const projected = () => ({ id: "msg_receipt", role: "user", content: [{ type: "text", text: "ordinary work" }] });
  try {
    const first = projected();
    await f.hooks.context({ sessionID, messages: [first] });
    assert.equal(ackCalls.length, 1);
    const repeated = projected();
    await f.hooks.context({ sessionID, messages: [repeated] });
    assert.equal(repeated.content.at(-1).text, first.content.at(-1).text);
    assert.equal(ackCalls.length, 1, "a repeated context cannot restart the initial ACK");
    await f.tick();
    assert.equal(ackCalls.length, 2, "the existing interval must recover without a new prompt");
    assert.deepEqual(ackCalls[1], ackCalls[0]);
    const confirmed = projected();
    await f.hooks.context({ sessionID, messages: [confirmed] });
    assert.equal(confirmed.content.at(-1).text, first.content.at(-1).text);
    await f.tick();
    assert.equal(ackCalls.length, 2);
    assert.equal(f.native.prompt.length, 0);
  } finally { await f.close(); }
});

const receiptDelivery = (letter = "a", overrides = {}) => ({
  ...delivery, delivery_id: "relay-delivery-" + letter.repeat(32), claim_token: "token-" + letter,
  claimed_at: "2026-11-17T00:00:00Z", lease_expires_at: "2026-11-17T00:01:00Z", expires_at: null, ...overrides,
});
const ordinaryProjection = (id = "msg_receipt_policy") => ({
  id, role: "user", content: [{ type: "text", text: "ordinary receipt work" }],
});
const deferredReceipt = () => {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
};
const receiptSuccess = (body, already_delivered = false) => ({
  ok: true, status: 200, text: async () => JSON.stringify({ delivery_id: body.delivery_id, state: "delivered", already_delivered }),
});

test("receipt headers survive unknown bodies, contexts cannot reset due time or revive stops", async () => {
  const oldPerformance = globalThis.performance;
  let mono = 1000;
  globalThis.performance = { now: () => mono };
  try {
    for (const hint of ["2", "invalid", "9".repeat(100), "Tue, 17 Nov 2026 00:00:03 GMT"]) {
      let attempts = 0;
      const f = await callerFixture({ fetch: (pathname, body) => {
        if (pathname === "/relay/turn") return { ok: true, text: async () => {
          mono = 1500; // The original response body's lag is retained.
          return JSON.stringify({ session: relaySession, deliveries: [receiptDelivery()] });
        } };
        if (pathname === "/relay/deliveries/ack") {
          attempts++;
          if (attempts > 1) return receiptSuccess(body, true);
          return { ok: false, status: 503, headers: { get: () => hint },
            text: async () => { mono = 2000; throw new Error("body lost after headers"); }, body: { cancel: async () => {} } };
        }
      } });
      try {
        mono = 1000;
        await f.hooks.context({ sessionID, messages: [ordinaryProjection()] });
        for (const time of [2000, 3499]) {
          mono = time;
          await f.hooks.context({ sessionID, messages: [ordinaryProjection()] });
          await f.tick();
          assert.equal(attempts, 1, hint);
        }
        mono = 4500;
        await f.tick();
        assert.equal(attempts, hint === "2" || hint.startsWith("Tue") ? 2 : 1);
        mono = 5000;
        await f.hooks.context({ sessionID, messages: [ordinaryProjection()] });
        await f.tick();
        assert.equal(attempts, hint === "2" || hint.startsWith("Tue") ? 2 : 1);
      } finally { await f.close(); }
    }
  } finally { globalThis.performance = oldPerformance; }
});

test("receipt expiry includes claim-body and emission lag and rechecks the strict full slot after ownership", async () => {
  const oldPerformance = globalThis.performance;
  let mono = 1000;
  globalThis.performance = { now: () => mono };
  try {
    for (const remaining of [501, 500, 499, 0]) {
      let attempts = 0, held = false;
      const get = deferredReceipt();
      const f = await callerFixture({
        get: async ({ sessionID: id }) => {
          if (held) await get.promise;
          return { id, location: { directory: location } };
        },
        fetch: (pathname) => pathname === "/relay/turn" ? { ok: true, text: async () => {
          mono = 20000;
          return JSON.stringify({ session: relaySession, deliveries: [receiptDelivery()] });
        } } : undefined,
        response: (pathname, body) => {
          if (pathname === "/relay/deliveries/ack") {
            attempts++;
            return attempts === 1 ? null : { delivery_id: body.delivery_id, state: "delivered", already_delivered: false };
          }
        },
      });
      try {
        mono = 1000;
        await f.hooks.prompt({ sessionID, messageID: "msg_receipt_policy", prompt: { text: "ordinary receipt work" } });
        mono = 27000; // Cached response and model emission do not restart the lease.
        await f.hooks.context({ sessionID, messages: [ordinaryProjection()] });
        assert.equal(attempts, 1);
        held = true;
        await f.tick();
        mono = 61000 - remaining;
        get.resolve();
        await pause();
        assert.equal(attempts, remaining > 500 ? 2 : 1, String(remaining));
        mono = 1000; // A later apparent clock improvement cannot revive a stopped entry.
        held = false;
        await f.hooks.context({ sessionID, messages: [ordinaryProjection()] });
        await f.tick();
        assert.equal(attempts, remaining > 500 ? 2 : 1);
      } finally { get.resolve(); await f.close(); removeSessionPin(sessionID); }
    }
  } finally { globalThis.performance = oldPerformance; }
});

test("overlapping contexts never join an initial or recovery receipt flight", async () => {
  let attempts = 0, gate = deferredReceipt();
  const f = await callerFixture({ fetch: (pathname, body) => {
    if (pathname === "/relay/turn") return { ok: true, text: async () => JSON.stringify({
      session: relaySession, deliveries: [receiptDelivery()],
    }) };
    if (pathname === "/relay/deliveries/ack") {
      attempts++;
      const original = gate;
      return original.promise.then((success) => success ? receiptSuccess(body) : { ok: false });
    }
  } });
  try {
    const first = f.hooks.context({ sessionID, messages: [ordinaryProjection()] });
    await until(() => attempts === 1, "initial ACK must be held");
    await f.hooks.context({ sessionID, messages: [ordinaryProjection()] });
    await f.tick();
    assert.equal(attempts, 1);
    gate.resolve(false);
    await first;
    gate = deferredReceipt();
    await f.tick();
    assert.equal(attempts, 2);
    await f.hooks.context({ sessionID, messages: [ordinaryProjection()] });
    for (let n = 0; n < 10; n++) await f.tick();
    assert.equal(attempts, 2);
    gate.resolve(true);
    await pause();
    await f.hooks.context({ sessionID, messages: [ordinaryProjection()] });
    await f.tick();
    assert.equal(attempts, 2);
  } finally { gate.resolve(false); await f.close(); }
});

test("maintenance reserves the whole ownership flight, remains independent of poll and rotates three receipts", async () => {
  let hold = false, gets = 0;
  const gate = deferredReceipt(), inventory = [];
  const batch = ["a", "b", "c"].map((letter) => receiptDelivery(letter, { payload: letter }));
  const f = await callerFixture({
    get: async ({ sessionID: id }) => { if (hold) { gets++; await gate.promise; } return { id, location: { directory: location } }; },
    response: (pathname, body) => {
      if (pathname === "/relay/turn") return { session: relaySession, deliveries: [...batch] };
      if (pathname === "/relay/deliveries/ack") { inventory.push(body.claim_token); return null; }
    },
  });
  try {
    // Three small envelopes fit only if scope is short enough; independent
    // claims also exercise the same cursor across cached-claim boundaries.
    for (let n = 0; n < 3; n++) {
      batch.splice(0, batch.length, receiptDelivery("abc"[n], { payload: "abc"[n] }));
      await f.hooks.context({ sessionID, messages: [ordinaryProjection("msg_fair_" + n)] });
    }
    assert.deepEqual(inventory, ["token-a", "token-b", "token-c"]);
    hold = true;
    for (let n = 0; n < 10; n++) await f.tick();
    assert.equal(gets, 2, "one maintenance ownership plus one independently held poll, not ten queued flights");
    assert.equal(inventory.length, 3);
    hold = false;
    gate.resolve();
    await pause();
    await f.tick();
    await f.tick();
    assert.deepEqual(inventory.slice(3), ["token-a", "token-b", "token-c"]);
    assert.equal(f.native.prompt.length, 0);
  } finally { hold = false; gate.resolve(); await f.close(); }
});

test("ordinary receipt rendering preserves every partial-batch and budget transition", async () => {
  const P = await import("../.opencode/plugins/pallium-common.mjs");
  const oldActor = process.env.PALLIUM_HOOK_ACTOR_REF;
  const a = receiptDelivery("a", { payload: "A_שלום" }), b = receiptDelivery("b", { payload: "B_界" });
  const scopeFor = (actor) => P.formatInjection([], container, 2300, sessionID, actor, P.AGENT_REF, "private");
  const renderedFor = (actor) => {
    const budget = 2300 - scopeFor(actor).length - 2;
    let rendered = P.formatRelay([a, b], budget, 1), omitted = 0;
    while (omitted < 2 - rendered.deliveries.length) {
      omitted = 2 - rendered.deliveries.length;
      rendered = P.formatRelay([a, b], budget, 1 + omitted);
    }
    return rendered;
  };
  const shortActor = "fixture-actor";
  const longActor = Array.from({ length: 1500 }, (_, n) => "x".repeat(n + 1))
    .find((actor) => renderedFor(actor).deliveries.length === 1);
  assert.ok(longActor);
  assert.equal(renderedFor(shortActor).deliveries.length, 2);
  const expected = (actor, continuation) => {
    const scopeText = scopeFor(actor), budget = 2300 - scopeText.length - 2;
    const text = continuation ? P.formatRelayContinuation([a, b], budget) : renderedFor(actor).text;
    return `\n\n<system-reminder>\n${[text, scopeText].filter(Boolean).join("\n\n")}\n</system-reminder>`;
  };
  try {
    for (const scenario of ["partial", "shrink-promotes", "omitted", "grow-pending", "terminal"]) {
      removeSessionPin(sessionID);
      const tokens = [], counts = new Map();
      const f = await callerFixture({ fetch: (pathname, body) => {
        if (pathname === "/relay/deliveries/ack") {
          tokens.push(body.claim_token);
          counts.set(body.claim_token, (counts.get(body.claim_token) || 0) + 1);
          const failedInitial = scenario === "grow-pending" ? body.claim_token === "token-a" :
            ["partial", "shrink-promotes", "terminal"].includes(scenario) && body.claim_token === "token-b";
          if (failedInitial && counts.get(body.claim_token) === 1) return {
            ok: false, status: scenario === "terminal" ? 409 : 503, text: async () => '{"detail":"refused"}',
          };
          return receiptSuccess(body);
        }
      }, response: (pathname) => pathname === "/relay/turn"
        ? { session: relaySession, deliveries: [a, b], has_more: true, remaining_count: 1 } : undefined });
      const render = async (actor, continuation) => {
        process.env.PALLIUM_HOOK_ACTOR_REF = actor;
        const user = ordinaryProjection();
        await f.hooks.context({ sessionID, messages: [user] });
        assert.equal(user.content.at(-1).text, expected(actor, continuation), scenario);
        assert.ok(tokens.every((token) => !user.content.at(-1).text.includes(token)));
      };
      try {
        const initiallySmall = scenario === "omitted" || scenario === "grow-pending";
        await render(initiallySmall ? longActor : shortActor, false);
        assert.deepEqual(tokens, initiallySmall ? ["token-a"] : ["token-a", "token-b"]);
        if (scenario === "omitted") {
          await render(shortActor, true); // Legacy omitted-B continuation, no B authority.
          await render(longActor, true);
          await f.tick();
          assert.deepEqual(tokens, ["token-a"]);
        } else if (scenario === "shrink-promotes") {
          await render(longActor, false); // Context promotes A-only while emitted B is pending.
          await render(shortActor, true);
          assert.deepEqual(tokens, ["token-a", "token-b"]);
          await f.tick();
          assert.deepEqual(tokens, ["token-a", "token-b", "token-b"]);
          await render(shortActor, true);
        } else if (scenario === "grow-pending") {
          await render(shortActor, false); // B first becomes freshly emitted here.
          assert.deepEqual(tokens, ["token-a", "token-b"]);
          await render(shortActor, false); // Pending A does not get another initial ACK.
          await f.tick();
          assert.deepEqual(tokens, ["token-a", "token-b", "token-a"]);
          await render(shortActor, false); // Maintenance did not promote claim.acked.
          await render(longActor, true);
        } else {
          await render(shortActor, false);
          assert.deepEqual(tokens, ["token-a", "token-b"]);
          await f.tick();
          if (scenario === "terminal") {
            await render(shortActor, false);
            assert.deepEqual(tokens, ["token-a", "token-b"]);
          } else {
            assert.deepEqual(tokens, ["token-a", "token-b", "token-b"]);
            await render(shortActor, false);
            await render(shortActor, true);
          }
        }
      } finally { await f.close(); }
    }
  } finally { process.env.PALLIUM_HOOK_ACTOR_REF = oldActor; removeSessionPin(sessionID); }
});

test("retirement fences held ownership and late ACKs without waiting or mutating same-ID successor", async () => {
  for (const phase of ["ownership", "ack"]) {
    let hold = false, successor = false, attempts = 0, gets = 0;
    const gate = deferredReceipt();
    const f = await callerFixture({
      get: async ({ sessionID: id }) => { if (hold && phase === "ownership") { gets++; await gate.promise; } return { id, location: { directory: location } }; },
      fetch: async (pathname, body) => {
        if (pathname === "/relay/turn") return { ok: true, text: async () => JSON.stringify({
          session: relaySession, deliveries: [receiptDelivery("a", { claim_token: successor ? "successor" : "original" })],
        }) };
        if (pathname === "/relay/deliveries/ack") {
          attempts++;
          if (hold && phase === "ack" && body.claim_token === "original") {
            await gate.promise; // Deliberately ignores AbortSignal to exercise late callback fencing.
            return receiptSuccess(body, true);
          }
          if (body.claim_token === "successor") return receiptSuccess(body);
          return { ok: false };
        }
      },
    });
    try {
      await f.hooks.context({ sessionID, messages: [ordinaryProjection()] });
      hold = true;
      await f.tick();
      assert.equal(attempts, phase === "ack" ? 2 : 1);
      assert.equal(gets, phase === "ownership" ? 2 : 0);
      await f.emit({ type: "session.deleted", data: { sessionID } });
      hold = false; successor = true; // Successor never joins the retired native get/ACK.
      await f.hooks.context({ sessionID, messages: [ordinaryProjection("msg_successor")] });
      const before = attempts;
      gate.resolve();
      hold = false;
      await pause();
      await f.tick();
      assert.equal(attempts, before);
      const tokenInventory = f.calls.filter((c) => c.path === "/relay/deliveries/ack").map((c) => c.body.claim_token);
      assert.equal(tokenInventory.filter((t) => t === "original").length, phase === "ack" ? 2 : 1);
      assert.equal(tokenInventory.filter((t) => t === "successor").length, 1);
    } finally { gate.resolve(); await f.close(); removeSessionPin(sessionID); }
  }
});

test("receipt recovery progresses during a held native wake wait and a held poll", async () => {
  const work = deferredReceipt(), poll = deferredReceipt();
  let attempts = 0, holdPoll = false;
  const f = await callerFixture({ wake: snapshot(),
    wait: async () => work.promise,
    fetch: async (pathname, body) => {
      if (pathname === "/relay/opencode/wake" && body.operation === "poll" && holdPoll) await poll.promise;
      if (pathname === "/relay/turn") return { ok: true, text: async () => JSON.stringify({
        session: relaySession, deliveries: [receiptDelivery()],
      }) };
      if (pathname === "/relay/deliveries/ack") return ++attempts === 1 ? { ok: false } : receiptSuccess(body);
    },
  });
  try {
    await f.tick();
    await until(() => f.native.wait === 1, "native work must be held");
    const user = ordinaryProjection();
    await f.hooks.context({ sessionID, messages: [user] });
    const original = JSON.stringify(user);
    assert.equal(attempts, 1);
    holdPoll = true;
    await f.tick();
    assert.equal(attempts, 2, "wakeBusy and a pending poll do not own receipt maintenance");
    for (let n = 0; n < 3; n++) await f.tick();
    assert.equal(attempts, 2);
    assert.equal(JSON.stringify(user), original);
    assert.equal(f.native.wait, 1);
    assert.equal(f.native.prompt.length, 1, "only the original unrelated wake");
  } finally { holdPoll = false; work.resolve(); poll.resolve(); await pause(); await f.close(); }
});

test("missing authority and no feasible Retry-After slot cannot be revived by cached contexts", async () => {
  for (const reason of ["missing", "no-slot"]) {
    let attempts = 0;
    const f = await callerFixture({ fetch: (pathname, body) => {
      if (pathname === "/relay/turn") return { ok: true, text: async () => JSON.stringify({
        session: relaySession, deliveries: [receiptDelivery("a", reason === "missing" ? { expires_at: undefined } : {})],
      }) };
      if (pathname === "/relay/deliveries/ack") {
        attempts++;
        return { ok: false, status: 503, headers: { get: () => reason === "no-slot" ? "60" : null },
          text: async () => '{"detail":{"code":"relay_busy","retryable":true}}' };
      }
    } });
    try {
      await f.hooks.context({ sessionID, messages: [ordinaryProjection()] });
      assert.equal(attempts, 1, "the legacy initial allowance does not depend on recovery metadata");
      await f.tick();
      removeSessionPin(sessionID);
      await f.hooks.context({ sessionID, messages: [ordinaryProjection()] });
      await f.tick();
      assert.equal(attempts, 1, reason);
    } finally { removeSessionPin(sessionID); await f.close(); }
  }
});

test("ordinary receipt maintenance fences pins, generation replacement and disposal during native ownership", async () => {
  for (const change of ["pin", "generation", "dispose"]) {
    let held = false, generation = 0, gets = 0;
    const gate = deferredReceipt(), inventory = [];
    const f = await callerFixture({
      get: async ({ sessionID: id }) => {
        if (held) { gets++; await gate.promise; }
        return { id, location: { directory: location } };
      },
      fetch: (pathname, body) => {
        if (pathname === "/relay/turn") return { ok: true, text: async () => JSON.stringify({
          session: { ...relaySession, scope_generation: generation },
          deliveries: [receiptDelivery("a", { claim_token: generation ? "replacement" : "original" })],
        }) };
        if (pathname === "/relay/deliveries/ack") {
          inventory.push(body.claim_token);
          return body.claim_token === "replacement" ? receiptSuccess(body) : { ok: false };
        }
      },
    });
    try {
      await f.hooks.context({ sessionID, messages: [ordinaryProjection()] });
      held = true;
      await f.tick();
      assert.equal(gets, 2);
      if (change === "dispose") await f.dispose(); // Must finish while unabortable SDK get remains held.
      else if (change === "pin") pinContainer(sessionID, "path:replacement:123", undefined, "fixture-actor");
      else {
        generation = 1; held = false;
        await f.hooks.context({ sessionID, messages: [ordinaryProjection("msg_new_generation")] });
        await f.hooks.context({ sessionID, messages: [ordinaryProjection("msg_new_generation")] });
      }
      held = false; gate.resolve();
      await pause();
      assert.deepEqual(inventory, change === "generation" ? ["original", "replacement"] : ["original"]);
    } finally { held = false; gate.resolve(); removeSessionPin(sessionID); await f.close(); }
  }
});

test("package keeps V1 default and exports the V2 raw plugin", () => {
  assert.equal(typeof v1, "function");
  assert.equal(v2.id, "pallium-v2");
  assert.equal(typeof v2.setup, "function");
});

for (const batch of [false, true]) test(`V2 exact ${batch ? "batch" : "singleton"} wakes once, attaches, ACKs and settles`, async () => {
  const oldFetch = globalThis.fetch;
  const calls = [];
  const hooks = {};
  const messages = [];
  let owner;
  let waitCount = 0;
  let contextCount = 0;
  let modelBound;
  const sibling = { ...delivery, delivery_id: "relay-delivery-" + "c".repeat(32),
    message_id: "relay-message-sibling", claim_token: "claim-sibling", payload: "fitting sibling" };
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
      if (body.operation === "context") {
        contextCount++;
        assert.equal(body.max_messages, 3);
      }
      result = { session: relaySession, wake: { ...wake },
        deliveries: body.operation !== "context" ? [] : contextCount > 1
          ? [{ ...delivery, state: "delivered", claim_token: undefined }] : batch ? [delivery, sibling] : [delivery],
        has_more: batch, remaining_count: batch ? 1 : 0,
        restored: body.operation === "context" && contextCount > 1 };
    } else if (u.pathname === "/relay/deliveries/ack") {
      assert.ok(modelBound.content.at(-1).text.includes(body.delivery_id));
      result = { delivery_id: body.delivery_id, state: "delivered", already_delivered: false };
    }
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
        modelBound = projected;
        await hooks.context({ sessionID, messages: [projected] });
        assert.match(projected.content.at(-1).text, /שלום wake payload/);
        if (batch) assert.match(projected.content.at(-1).text, /fitting sibling[\s\S]*\[Relay: 1 more;/);
        const continuation = { id: user.id, role: "user", content: [{ type: "text", text: user.text }], metadata: user.metadata };
        await hooks.context({ sessionID, messages: [continuation] });
        assert.match(continuation.content.at(-1).text, /שלום wake payload/);
        assert.doesNotMatch(continuation.content.at(-1).text, /fitting sibling|\[Relay: 1 more;/);
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
    assert.deepEqual(calls.filter((c) => c.path === "/relay/deliveries/ack").map((c) => c.body.delivery_id),
      batch ? [deliveryID, sibling.delivery_id] : [deliveryID]);
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
async function until(predicate, message) {
  const deadline = Date.now() + 5000;
  while (!predicate()) {
    assert.ok(Date.now() < deadline, message);
    await delay(5);
  }
}
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
  const trace = [];
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
    if (body.operation) trace.push(body.operation);
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
    location: { directory: location }, app: { log: (entry) => options.log?.(entry) },
    session: {
      hook: async (name, fn) => { hooks[name] = fn; return { dispose: () => { retired.push(name); return options.dispose?.(name); } }; },
      get: async (input) => { trace.push("get"); return options.get ? options.get(input) : ({ id: input.sessionID, location: { directory: location } }); },
      context: async (input) => { trace.push("raw"); return options.context ? options.context(input, history) : ({ data: history }); },
      prompt: async (input) => {
        native.prompt.push(input);
        history.push({ type: "user", id: input.id, text: input.text, metadata: input.metadata });
        if (options.prompt) return options.prompt(input);
        return { id: input.id };
      },
      wait: async () => { trace.push("wait"); native.wait++; if (options.wait) await options.wait(history, hooks); },
      interrupt: async () => { native.interrupt++; },
    },
    event: { subscribe: async function* ({ signal }) {
      try {
      while (!signal.aborted) {
        if (events.length) {
          const event = events.shift();
          if (event.fixtureEnd) return;
          if (event.fixtureError) throw new Error("subscription failed");
          yield event; options.afterEvent?.(event); continue;
        }
        await new Promise((resolve) => {
          eventReady = resolve;
          signal.addEventListener("abort", resolve, { once: true });
        });
      }
      } finally { eventRetired = true; }
    } },
  };
  const dispose = await v2.setup(ctx);
  await until(() => calls.some((c) => c.path === "/relay/sessions"), "startup Git must finish before fixture actions");
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
    calls, trace, native, hooks, history, retired, dispose, listed: () => listed, eventRetired: () => eventRetired,
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

test("Git discovery yields to unrelated caller work while child waits", async () => {
  const directory = mkdtempSync(path.join(profile, "git-yield-界-"));
  const ready = path.join(directory, "ready");
  const release = path.join(directory, "release");
  const work = path.join(directory, "work.json");
  const result = path.join(directory, "result.json");
  const sibling = "ses_git_sibling";
  const siblingSession = { ...relaySession, session_ref: sibling,
    endpoint_id: "relay-session-" + "c".repeat(32) };
  const previousPin = getPinnedContainer(sessionID);
  const nativeGets = [];
  const savedSync = childProcess.execFileSync, savedSpawn = childProcess.spawn;
  let armed = false, intercepted = false, child, closed, primary, siblingWork, f;
  const program = String.raw`
    import { existsSync, readFileSync, writeFileSync } from "node:fs";
    import path from "node:path";
    import { setTimeout } from "node:timers/promises";
    const directory = process.argv[1];
    const file = name => path.join(directory, name);
    writeFileSync(file("ready"), "ready");
    const until = Date.now() + 1000;
    while (!existsSync(file("release")) && Date.now() < until) await setTimeout(5);
    const released = existsSync(file("release"));
    const work = released && existsSync(file("work.json"))
      ? JSON.parse(readFileSync(file("work.json"), "utf8")) : null;
    writeFileSync(file("result.json"), JSON.stringify({
      released, workCompleted: work?.completed === true,
    }));
  `;
  const take = (command, args) => {
    if (!armed || command !== "git" || args.join(" ") !== "remote get-url origin") return false;
    armed = false;
    intercepted = true;
    siblingWork = new Promise((resolve, reject) => setImmediate(async () => {
      try {
        const until = Date.now() + 5000;
        while (!existsSync(ready)) {
          assert.ok(Date.now() < until, "controlled Git child did not become ready");
          await delay(5);
        }
        const messages = [{ id: "msg_git_sibling", role: "user",
          content: [{ type: "text", text: "unrelated ordinary work שלום" }] }];
        await f.hooks.context({ sessionID: sibling, messages });
        assert.ok(nativeGets.includes(sibling), "real sibling context must check native ownership");
        const turns = f.calls.filter((c) => c.path === "/relay/turn" && c.body.session_ref === sibling);
        assert.equal(turns.length, 1, "real sibling context must complete its exact Relay turn");
        assert.equal(turns[0].body.container_ref, container);
        assert.ok(messages[0].content.length > 1, "real sibling context must publish its scoped readback");
        writeFileSync(work, JSON.stringify({ completed: true }));
        writeFileSync(release, "release");
        resolve();
      } catch (error) { reject(error); }
    }));
    siblingWork.catch(() => {}); // Joined below; avoid an early unhandled rejection while the child drains.
    return true;
  };
  try {
    // Pinned startup cannot consume the gate; the primary hook is unpinned later.
    pinContainer(sessionID, container, undefined, "fixture-actor");
    pinContainer(sibling, container, undefined, "fixture-actor");
    f = await callerFixture({
      get: async ({ sessionID: id }) => {
        nativeGets.push(id);
        return { id, location: { directory: location } };
      },
      response: async (route, body) => body.session_ref === sibling &&
        ["/relay/turn", "/relay/opencode/wake"].includes(route)
        ? { session: siblingSession, wake: null, deliveries: [] } : undefined,
    });
    await f.tick();
    assert.ok(f.calls.some((c) => c.body.operation === "enroll"), "startup enrollment must precede the shim");
    childProcess.execFileSync = (command, args, options) => {
      if (!take(command, args)) return savedSync(command, args, options);
      return savedSync(process.execPath, ["--input-type=module", "-e", program, directory],
        { ...options, cwd: directory });
    };
    childProcess.spawn = (command, args, options) => {
      if (!take(command, args)) return savedSpawn(command, args, options);
      child = savedSpawn(process.execPath, ["--input-type=module", "-e", program, directory],
        { ...options, cwd: directory });
      closed = new Promise((resolve) => child.once("close", resolve));
      return child;
    };
    syncBuiltinESMExports();
    removeSessionPin(sessionID);
    armed = true;
    primary = f.hooks.prompt({ sessionID, messageID: "msg_git_primary",
      prompt: { text: "primary discovery work while a sibling remains responsive" } });
    await primary;
    assert.equal(intercepted, true, "production primary prompt must reach unpinned Git discovery");
    await siblingWork;
    await closed;
    const observed = JSON.parse(readFileSync(result, "utf8"));
    assert.ok(observed.released && observed.workCompleted,
      "Git discovery must yield to unrelated caller work");
  } finally {
    writeFileSync(release, "release");
    if (child && child.exitCode === null && child.signalCode === null) child.kill();
    await Promise.allSettled([primary, siblingWork, closed]);
    childProcess.execFileSync = savedSync;
    childProcess.spawn = savedSpawn;
    syncBuiltinESMExports();
    await f?.close();
    removeSessionPin(sibling);
    removeSessionPin(sessionID);
    if (previousPin) pinContainer(sessionID, previousPin, undefined, "fixture-actor");
    rmSync(directory, { recursive: true, force: true });
  }
});

for (const outcome of ["rejected", "foreign", "retired"]) {
  test(`poll ownership lookup: ${outcome}`, async () => {
    const lookup = barrier();
    let armed = false;
    const f = await callerFixture({ get: async ({ sessionID: id }) => {
      if (!armed) return { id, location: { directory: location } };
      armed = false;
      await lookup.wait();
      if (outcome !== "foreign") throw new Error("native lookup unavailable");
      return { id, location: { directory: location + "-other" } };
    } });
    const operations = () => f.calls.filter((c) => c.body.operation).map((c) => c.body.operation);
    try {
      await until(() => operations().includes("enroll"), "startup enrollment");
      armed = true;
      await f.tick();
      await lookup.entered;
      assert.deepEqual(operations(), ["enroll"]);
      if (outcome === "retired") await f.dispose();
      lookup.release();
      await f.tick();
      if (outcome === "rejected") {
        await f.tick();
        await until(() => operations().includes("poll") || operations().includes("detach"), "poll must recover");
        assert.ok(operations().slice(1).every((operation) => operation === "poll"));
        const [enroll, poll] = f.calls.filter((c) => ["enroll", "poll"].includes(c.body.operation));
        assert.deepEqual(poll.body, { ...enroll.body, operation: "poll" });
      } else {
        assert.deepEqual(operations(), ["enroll", "detach"]);
      }
      assert.equal(f.calls.filter((c) => c.path === "/relay/turn" || c.path === "/relay/deliveries/ack").length, 0);
      assert.equal(f.native.prompt.length, 0);
    } finally { lookup.release(); await f.close(); }
  });
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

test("known admitted wake reentry preserves admission and uncertainty", async () => {
  for (const scenario of ["known", "fresh", "rejected-wait", "flag-reentry", "reload",
    "lost-admitted-committed", "lost-admitted-uncommitted", "lost-terminal"]) {
    const startsFalse = ["fresh", "flag-reentry", "lost-admitted-committed", "lost-admitted-uncommitted"].includes(scenario);
    const projected = projectedWake();
    const history = startsFalse ? [] : [{ type: "user", id: nativeID,
      text: projected.content[0].text, metadata: projected.metadata }];
    let backend = snapshot({ admitted: !startsFalse });
    let admissions = 0, waits = 0, terminals = 0;
    const firstWait = barrier(), replacementWait = barrier();
    const options = {
      history,
      response: async (route, body) => {
        if (route !== "/relay/opencode/wake") return;
        if (body.operation === "admitted") {
          admissions++;
          if (scenario === "lost-admitted-uncommitted" && admissions === 1) return null;
          backend = { ...backend, admitted: true };
          if (scenario.startsWith("lost-admitted") && admissions === 1) return null;
        }
        if (body.operation === "terminal") {
          terminals++;
          backend = { ...backend, terminal: true };
          if (scenario === "lost-terminal") return null;
        }
        return { session: relaySession, wake: { ...backend }, deliveries: [] };
      },
      wait: async (rows) => {
        waits++;
        if (scenario === "rejected-wait" && waits === 1) throw new Error("settlement unavailable");
        if (scenario === "flag-reentry") {
          if (waits === 1) await firstWait.wait();
          else { await replacementWait.wait(); rows.push({ type: "idle", id: "msg_reentry_terminal", outcome: "succeeded" }); }
        }
      },
    };
    let f = await callerFixture(options);
    const writes = () => f.calls.filter((c) => c.body.operation === "admitted");
    try {
      await f.tick();
      assert.equal(writes().length, startsFalse ? 1 : 0, "known admitted wake must not rewrite admission");
      assert.equal(terminals, 0, `${scenario}: admission/wait alone is not terminal proof`);
      assert.deepEqual(f.native.prompt.map((p) => p.id), startsFalse ? [nativeID] : []);
      if (scenario === "flag-reentry") {
        await firstWait.entered;
        await f.tick(); // Authoritative false -> true readback while the old wait is pending.
        assert.equal(f.native.wait, 1, "in-flight poll cannot overlap the old flight");
        firstWait.release(); await pause();
        assert.equal(terminals, 0, "changed admitted flag fences the old false-snapshot flight");
        await f.tick(); await replacementWait.entered;
        assert.equal(writes().length, 1, "true-snapshot replacement must not repeat the first admission");
        await f.tick();
        assert.equal(f.native.wait, 2, "replacement flight retains its busy reservation");
        replacementWait.release(); await pause();
        assert.equal(terminals, 1, "replacement settles only after its own terminal proof");
      } else {
        if (scenario === "reload") {
          await f.close();
          f = await callerFixture(options); // No adapter-local admission history survives setup.
        }
        await f.tick();
        const expected = scenario === "lost-admitted-uncommitted" ? 2 : startsFalse ? 1 : 0;
        assert.equal(writes().length, expected, `${scenario}: only authoritative true can suppress admission`);
        assert.equal(terminals, 0, `${scenario}: repeated polls cannot invent terminal evidence`);
        await f.tick();
        assert.equal(writes().length, expected, `${scenario}: genuine true readback prevents further writes`);
        assert.equal(terminals, 0);
        history.push({ type: "idle", id: "msg_reentry_terminal", outcome: "succeeded" });
        await f.tick();
        assert.equal(terminals, 1, `${scenario}: exact later terminal still progresses`);
        assert.equal(writes().length, expected);
      }
      const settledWaits = f.native.wait;
      await f.tick(); await f.tick(); // Includes reconciliation of a committed-but-lost terminal reply.
      assert.equal(terminals, 1, `${scenario}: terminal readback suppresses stale follow-up`);
      assert.equal(f.native.wait, settledWaits);
      assert.equal(admissions, scenario === "lost-admitted-uncommitted" ? 2 : startsFalse ? 1 : 0);
      assert.equal(f.native.interrupt, 0);
      assert.equal(f.native.prompt.length, scenario === "reload" ? 0 : startsFalse ? 1 : 0);
      for (const call of f.calls.filter((c) => ["admitted", "terminal"].includes(c.body.operation))) {
        assert.deepEqual([call.body.endpoint_id, call.body.scope_generation, call.body.generation,
          call.body.delivery_id, call.body.native_input_id], [endpointID, 0, 1, deliveryID, nativeID]);
      }
      if (scenario === "fresh") {
        backend = snapshot({ generation: 2, native_input_id: "msg_reentry_next",
          delivery_id: "relay-delivery-" + "e".repeat(32) });
        await f.tick();
        assert.equal(admissions, 2, "a fresh false generation still requires its own admission");
        assert.equal(terminals, 1);
        assert.deepEqual(f.native.prompt.map((p) => p.id), [nativeID, "msg_reentry_next"]);
        history.push({ type: "idle", id: "msg_reentry_next_terminal", outcome: "succeeded" });
        await f.tick();
        assert.equal(admissions, 2, "new generation's true readback also suppresses redundant admission");
        assert.equal(terminals, 2);
        const last = f.calls.filter((c) => c.body.operation === "terminal").at(-1);
        assert.deepEqual([last.body.generation, last.body.delivery_id, last.body.native_input_id,
          last.body.terminal_message_id], [2, backend.delivery_id, "msg_reentry_next", "msg_reentry_next_terminal"]);
      }
    } finally { firstWait.release(); replacementWait.release(); await f.close(); }
  }
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

for (const outcome of ["succeeded", "failed", "interrupted"]) {
  test(`coalesced native wake settles from exact outcome-bearing idle: ${outcome}`, async () => {
    const f = await callerFixture({ wake: snapshot(), wait: async (history) => {
      history.push({ type: "user", id: "msg_ordinary_unicode", text: "ordinary work שלום 😀" },
        { type: "user", id: "msg_later_ordinary", text: "more work" },
        { type: "idle", id: "msg_coalesced_terminal", outcome });
    } });
    try {
      await f.tick();
      const terminal = f.calls.filter((c) => c.body.operation === "terminal");
      assert.equal(terminal.length, 1, "coalesced exact wake must settle activation without replay");
      assert.equal(terminal[0].body.terminal_message_id, "msg_coalesced_terminal");
      assert.deepEqual([terminal[0].body.generation, terminal[0].body.delivery_id, terminal[0].body.native_input_id],
        [1, deliveryID, nativeID]);
      assert.deepEqual(f.native.prompt.map((p) => p.id), [nativeID]);
      assert.equal(f.native.wait, 1);
      assert.equal(f.calls.filter((c) => c.body.operation === "admitted").length, 1);
      assert.equal(f.calls.filter((c) => c.path === "/relay/deliveries/ack").length, 0);
      assert.equal(f.native.interrupt, 0);
    } finally { await f.close(); }
  });
}

for (const fault of ["missing-id", "invalid-id", "same-id", "outcomeless", "unknown-outcome", "nonstring-outcome",
  "before-input", "compacted", "wrong-input", "wrong-text", "wrong-marker", "wrong-generation", "wrong-delivery",
  "uncertain-first-idle"]) {
  test(`coalesced native wake rejects unproven after-wait evidence: ${fault}`, async () => {
    const f = await callerFixture({ wake: snapshot(), wait: async (history) => {
      const input = history[0];
      const idle = { type: "idle", id: "msg_coalesced_terminal", outcome: "succeeded" };
      history.push({ type: "user", id: "msg_newer", text: "ordinary work" });
      if (fault === "missing-id") delete idle.id;
      if (fault === "invalid-id") idle.id = "not-a-native-id";
      if (fault === "same-id") idle.id = nativeID;
      if (fault === "outcomeless") delete idle.outcome;
      if (fault === "unknown-outcome") idle.outcome = "completed";
      if (fault === "nonstring-outcome") idle.outcome = true;
      if (fault === "wrong-input") input.id = "msg_other_input";
      if (fault === "wrong-text") input.text = "not the exact native wake";
      if (fault === "wrong-marker") input.metadata.pallium_relay_wake = false;
      if (fault === "wrong-generation") input.metadata.generation++;
      if (fault === "wrong-delivery") input.metadata.delivery_id = "relay-delivery-" + "f".repeat(32);
      if (fault === "compacted") history.splice(0, 1);
      if (fault === "before-input") history.unshift(idle);
      else if (fault === "uncertain-first-idle") history.push(
        { type: "idle", id: "msg_unknown_terminal" }, idle);
      else history.push(idle);
    } });
    try {
      await f.tick();
      assert.equal(f.calls.filter((c) => c.body.operation === "admitted").length, 1);
      assert.equal(f.calls.filter((c) => c.body.operation === "terminal").length, 0);
      assert.deepEqual(f.native.prompt.map((p) => p.id), [nativeID]);
      assert.equal(f.native.wait, 1);
    } finally { await f.close(); }
  });
}

test("coalesced native wake waits for settlement and successor work", async () => {
  const gate = barrier();
  const f = await callerFixture({ wake: snapshot(), wait: async (history) => {
    history.push({ type: "user", id: "msg_successor_work", text: "ordinary work" });
    await gate.wait();
    history.push({ type: "idle", id: "msg_successor_terminal", outcome: "succeeded" });
  } });
  try {
    await f.tick();
    await gate.entered;
    await f.tick();
    assert.equal(f.calls.filter((c) => c.body.operation === "terminal").length, 0);
    assert.equal(f.native.wait, 1);
    gate.release();
    await pause();
    assert.equal(f.calls.filter((c) => c.body.operation === "terminal").length, 1);
    assert.deepEqual(f.native.prompt.map((p) => p.id), [nativeID]);
  } finally { gate.release(); await f.close(); }
});

for (const change of ["dispose", "location", "endpoint", "scope", "wake-generation", "wake-delivery", "wake-input", "wake-location"]) {
  test(`coalesced native wake fences changed binding after wait: ${change}`, async () => {
    const gate = barrier();
    let moved = false;
    let polled = false;
    const original = snapshot();
    const changed = { ...original };
    const f = await callerFixture({ wake: original,
      get: async () => ({ location: { directory: moved ? location + "/other" : location } }),
      response: async (route, body) => {
        if (route !== "/relay/opencode/wake" || body.operation !== "poll") return;
        if (!polled) { polled = true; return { session: relaySession, wake: original, deliveries: [] }; }
        const session = { ...relaySession };
        if (change === "endpoint") session.endpoint_id = "relay-session-" + "f".repeat(32);
        if (change === "scope") session.scope_generation++;
        return { session, wake: ["endpoint", "scope"].includes(change) ? null : changed, deliveries: [] };
      },
      wait: async (history) => {
        history.push({ type: "user", id: "msg_coalesced_ordinary", text: "ordinary work" });
        await gate.wait();
        history.push({ type: "idle", id: "msg_coalesced_terminal", outcome: "succeeded" });
      },
    });
    try {
      await f.tick();
      await gate.entered;
      if (change === "dispose") await f.dispose();
      else if (change === "location") moved = true;
      else {
        if (change === "wake-generation") changed.generation++;
        if (change === "wake-delivery") changed.delivery_id = "relay-delivery-" + "f".repeat(32);
        if (change === "wake-input") changed.native_input_id = "msg_other_generation";
        if (change === "wake-location") changed.native_location = location + "/other";
        await f.tick();
      }
      gate.release();
      await pause();
      assert.equal(f.calls.filter((c) => c.body.operation === "terminal").length, 0);
      assert.deepEqual(f.native.prompt.map((p) => p.id), [nativeID]);
      assert.equal(f.native.interrupt, 0);
    } finally { gate.release(); await f.close(); }
  });
}

for (const failure of ["wait", "context", "terminal-rejected", "terminal-reply-lost"]) {
  test(`coalesced native wake keeps uncertainty without replay: ${failure}`, async () => {
    let reads = 0;
    let settled = false;
    const wake = snapshot();
    const f = await callerFixture({ wake,
      context: async (_input, history) => {
        if (++reads === 3 && failure === "context") throw new Error("readback unavailable");
        return { data: history };
      },
      wait: async (history) => {
        history.push({ type: "user", id: "msg_coalesced_ordinary", text: "ordinary work" });
        if (failure === "wait") throw new Error("settlement unknown");
        history.push({ type: "idle", id: "msg_coalesced_terminal", outcome: "succeeded" });
      },
      response: async (route, body) => {
        if (route !== "/relay/opencode/wake") return;
        if (body.operation === "poll" && settled) return { session: relaySession, wake: snapshot({ terminal: true }), deliveries: [] };
        if (body.operation === "terminal") {
          if (failure === "terminal-reply-lost") settled = true;
          return null;
        }
      },
    });
    try {
      await f.tick();
      assert.equal(f.calls.filter((c) => c.body.operation === "terminal").length,
        failure.startsWith("terminal") ? 1 : 0);
      assert.equal(wake.terminal, false, "uncertain response cannot rotate local wake authority");
      if (failure === "terminal-reply-lost") {
        await f.tick();
        assert.equal(f.calls.filter((c) => c.body.operation === "terminal").length, 1);
      }
      assert.deepEqual(f.native.prompt.map((p) => p.id), [nativeID]);
      assert.equal(f.native.interrupt, 0);
    } finally { await f.close(); }
  });
}

async function contextRecoveryFixture(options = {}) {
  const known = snapshot({ admitted: true });
  const count = { context: 0, enroll: 0 };
  let armed = false, phase = "setup", backend = { session: relaySession, wake: known };
  const result = (value) => ({ ...value, restored: true,
    deliveries: [{ ...delivery, state: "delivered", claim_token: undefined, receipt: undefined }] });
  const encoded = (value, next) => ({ ok: true, text: async () => {
    const raw = JSON.stringify(value); phase = next; return raw;
  } });
  const f = await callerFixture({ wake: known, history: [{ type: "user", id: nativeID,
    text: projectedWake().content[0].text, metadata: projectedWake().metadata }],
    get: (input) => options.get?.(input, phase) ?? { id: input.sessionID, location: { directory: location } },
    wait: options.wait,
    fetch: async (route, body, init) => {
      if (!armed || route !== "/relay/opencode/wake") return;
      if (body.operation === "poll") return await options.poll?.(body) ?? jsonResponse(backend);
      if (body.operation === "enroll") {
        count.enroll++; phase = "enroll-response";
        return await options.enroll?.(body, count.enroll, init) ?? encoded(backend, "pre-retry-get");
      }
      if (body.operation === "context") {
        count.context++;
        if (count.context <= (options.initialCount || 1)) {
          phase = "enroll-get";
          return options.initial ? options.initial(body) : { ok: false, status: 409,
            text: async () => JSON.stringify({ detail: "OpenCode registration is missing or stale" }) };
        }
        phase = "retry-response";
        return await options.retry?.(body) ?? encoded(result(backend), "final-get");
      }
      if (body.operation === "terminal") {
        backend = { ...backend, wake: { ...backend.wake, terminal: true } };
        return jsonResponse(backend);
      }
    } });
  await until(() => f.calls.some((c) => c.body.operation === "enroll"), "seed enrollment");
  await pause(); armed = true;
  return { ...f, count, known, result, setBackend: (value) => { backend = value; },
    run: (user = projectedWake()) => f.hooks.context({ sessionID, messages: [user] }),
    acks: () => f.calls.filter((c) => c.path === "/relay/deliveries/ack").length };
}

const outageFlush = async () => { for (let n = 0; n < 12; n++) await new Promise(setImmediate); };
async function outageUntil(check) {
  const end = Date.now() + 5000;
  while (!check()) { assert.ok(Date.now() < end, "outage boundary was not reached"); await new Promise(setImmediate); }
  await outageFlush();
}
const outageResponse = (value, status = 200) => new Response(JSON.stringify(value), { status });
const outageBusy = () => outageResponse({ detail: { retryable: true } }, 503);
async function contextOutageFixture(t, options = {}) {
  const known = snapshot({ admitted: options.admitted ?? true }), originalPerformance = globalThis.performance;
  let armed = false, attempts = 0, enrollments = 0, mono = 0;
  const logs = [];
  const restored = () => ({ session: relaySession, wake: known, restored: true,
    deliveries: [{ ...delivery, state: "delivered", claim_token: undefined }] });
  pinContainer(sessionID, container, undefined, "fixture-actor");
  const f = await callerFixture({ wake: known, list: options.list, response: options.response,
    log: (entry) => logs.push(entry.message),
    history: [{ type: "user", id: nativeID, text: projectedWake().content[0].text, metadata: projectedWake().metadata }],
    get: (input) => options.get?.(input, armed) ?? { id: input.sessionID, location: { directory: location } },
    fetch: async (route, body, init) => {
      if (route === "/relay/deliveries/ack") {
        if (options.confirm === "uncertain") throw new Error("ACK response lost");
        if (options.confirm === "ack-body-lost") return { ok: true, status: 200, text: async () => { throw new Error("ACK body lost"); } };
        return receiptSuccess(body);
      }
      if (route !== "/relay/opencode/wake") return;
      if (body.operation === "context") {
        if (!armed) return outageResponse(options.confirm === "restored" ? restored() :
          { session: relaySession, wake: known, deliveries: [delivery], restored: false });
        attempts++;
        return await options.reply?.(attempts, body, init, restored) ?? outageResponse(restored());
      }
      if (armed && body.operation === "enroll") {
        enrollments++;
        return await options.enroll?.(body, init) ?? outageResponse({ session: relaySession, wake: known });
      }
      if (armed && body.operation === "poll") return await options.poll?.(body, init) ??
        outageResponse({ session: relaySession, wake: known });
    },
  });
  if (options.confirm !== "admitted") await f.hooks.context({ sessionID, messages: [projectedWake()] });
  armed = true;
  globalThis.performance = { now: () => mono };
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const advance = async (ms) => { mono += ms; t.mock.timers.tick(ms); await outageFlush(); };
  return { ...f, known, restored, logs, attempts: () => attempts, enrollments: () => enrollments,
    acks: () => f.calls.filter((c) => c.path === "/relay/deliveries/ack").length,
    run: (user = projectedWake()) => f.hooks.context({ sessionID, messages: [user] }),
    advance,
    close: async () => {
      t.mock.timers.reset(); globalThis.performance = originalPerformance;
      try { await f.close(); } finally { removeSessionPin(sessionID); }
    },
  };
}

for (const fault of ["none", "no-ack", "lost-ack", "wrong-attempt", "wrong-generation",
  "wrong-endpoint", "wrong-location", "terminal", "missing-admission", "admission-regression", "503"]) {
  test(`pending admission continuation requires exact local ACK: ${fault}`, async (t) => {
    const f = await contextOutageFixture(t, {
      admitted: false,
      confirm: fault === "no-ack" ? "admitted" : fault === "lost-ack" ? "ack-body-lost" : "ack",
      poll: () => outageResponse({ session: relaySession, wake: snapshot({ admitted: true }) }),
      reply: (attempt, _body, _init, restored) => {
        if (fault === "503") return outageBusy();
        const value = restored();
        if (fault === "wrong-attempt") value.deliveries[0].attempts++;
        if (fault === "wrong-generation") value.wake = { ...value.wake, generation: 2 };
        if (fault === "wrong-endpoint") value.session = { ...value.session, endpoint_id: "relay-session-" + "f".repeat(32) };
        if (fault === "wrong-location") value.wake = { ...value.wake, native_location: location + "/other" };
        if (fault === "terminal") value.wake = { ...value.wake, terminal: true };
        if (fault === "missing-admission") value.wake = { ...value.wake, admitted: undefined };
        if (fault === "admission-regression" && attempt === 1) value.wake = { ...value.wake, admitted: true };
        return outageResponse(value);
      },
    });
    try {
      if (fault === "admission-regression") {
        await f.run();
        const before = f.calls.filter((c) => c.body.operation === "poll").length;
        const tick = f.tick();
        await outageUntil(() => f.calls.filter((c) => c.body.operation === "poll").length > before);
        await f.advance(20);
        await tick;
      }
      const user = projectedWake();
      if (fault === "none") {
        await f.run(user);
        assert.match(user.content.at(-1).text, /שלום wake payload/);
        assert.doesNotMatch(user.content.at(-1).text, /claim_token:/);
      } else {
        await assert.rejects(f.run(user), new RegExp(fault === "503" ?
          "lookup did not return a usable result" : "restored authority refused"));
        assert.equal(user.content.length, 1);
      }
      assert.equal(f.attempts(), fault === "admission-regression" ? 2 : 1);
      assert.equal(f.acks(), fault === "no-ack" ? 0 : 1);
      assert.equal(f.enrollments(), 0);
      assert.equal(f.native.prompt.length, 0);
    } finally { await f.close(); }
  });
}

for (const shape of ["valid", "missing-session", "runtime", "session", "container", "endpoint",
  "scope", "scope-type", "closed", "unhealthy", "wake-input", "wake-generation", "wake-delivery",
  "wake-scope", "wake-location", "unadmitted", "terminal", "not-delivered", "missing-state",
  "zero-attempt", "attempt-type"]) {
  test(`outage bootstrap validates first restored authority: ${shape}`, async (t) => {
    const f = await contextOutageFixture(t, { confirm: "admitted", reply: (attempt, _body, _init, restored) => {
      if (attempt === 2) return outageBusy();
      const value = restored();
      if (attempt !== 1) return outageResponse(value);
      if (shape === "missing-session") delete value.session;
      else value.session = { ...value.session };
      if (shape === "runtime") value.session.runtime = "codex";
      if (shape === "session") value.session.session_ref = "ses_other";
      if (shape === "container") value.session.container_ref = container + "/other";
      if (shape === "endpoint") value.session.endpoint_id = "relay-session-" + "f".repeat(32);
      if (shape === "scope") value.session.scope_generation = 1;
      if (shape === "scope-type") value.session.scope_generation = "0";
      if (shape === "closed") value.session.state = "closed";
      if (shape === "unhealthy") value.session.destination_health = "unavailable";
      value.wake = { ...value.wake };
      if (shape === "wake-input") value.wake.native_input_id = "msg_wrong";
      if (shape === "wake-generation") value.wake.generation = 2;
      if (shape === "wake-delivery") value.wake.delivery_id = "relay-delivery-" + "f".repeat(32);
      if (shape === "wake-scope") value.wake.scope_generation = 1;
      if (shape === "wake-location") value.wake.native_location = location + "/other";
      if (shape === "unadmitted") value.wake.admitted = false;
      if (shape === "terminal") value.wake.terminal = true;
      if (shape === "not-delivered") value.deliveries[0].state = "claimed";
      if (shape === "missing-state") delete value.deliveries[0].state;
      if (shape === "zero-attempt") value.deliveries[0].attempts = 0;
      if (shape === "attempt-type") value.deliveries[0].attempts = "1";
      return outageResponse(value);
    } });
    const first = projectedWake(), second = projectedWake();
    try {
      const initialError = await f.run(first).then(() => null, (error) => error);
      const result = f.run(second).then(() => null, (error) => error);
      await outageUntil(() => f.attempts() === 2);
      await f.advance(2500);
      const laterError = await result;
      assert.equal(Boolean(initialError), shape !== "valid", "first bootstrap must validate before attachment");
      assert.equal(Boolean(laterError), shape !== "valid", "a rejected bootstrap cannot authorize outage retry");
      assert.equal(first.content.length, shape === "valid" ? 2 : 1);
      assert.equal(second.content.length, shape === "valid" ? 2 : 1);
      assert.equal(f.attempts(), shape === "valid" ? 3 : 2);
      assert.equal(f.acks(), 0); assert.equal(f.enrollments(), 0); assert.equal(f.native.prompt.length, 0);
    } finally { await f.close(); }
  });
}

for (const entry of ["restored", "forged", "unrestorable", "late-owned"]) {
  test(`outage bootstrap restores authority acquired during callback: ${entry}`, async (t) => {
    const held = barrier();
    let holding = false;
    const f = await contextOutageFixture(t, { confirm: "admitted",
      list: entry === "unrestorable" ? [[], []] : [[]],
      get: async (input, armed) => {
        if (armed && entry === "late-owned") { holding = true; await held.wait(); }
        return { id: input.sessionID, location: { directory: location } };
      } });
    const user = projectedWake();
    if (entry === "forged") user.id = "msg_unproven_marker";
    const result = f.run(user).then(() => null, (error) => error);
    try {
      if (entry === "late-owned") {
        await outageUntil(() => holding); await f.advance(120000);
        const before = f.calls.length;
        held.release();
        assert.ok(await result);
        assert.equal(f.calls.length, before, "expired provisional work cannot restore or enroll late");
      } else {
        assert.equal(await result, null);
        assert.equal(f.attempts(), entry === "restored" ? 1 : 0,
          JSON.stringify({ logs: f.logs, calls: f.calls.map(({ path, body }) => ({ path, body })) }));
        if (entry === "restored") assert.match(user.content.at(-1).text, /שלום wake payload/);
        else assert.ok(!user.content.some((part) => part.text?.includes("שלום wake payload")));
      }
      assert.equal(f.acks(), 0); assert.equal(f.native.prompt.length, 0);
      assert.equal(f.calls.filter((c) => c.path === "/relay/turn").length, 0);
    } finally { held.release(); await f.close(); await result; }
  });
}

for (const fault of ["retryable503", "unreadable503", "transport", "per-request-timeout",
  "nonretryable503", "unknown503", "startup-lookalike", "lost200", "empty200", "malformed200", "malformed-shape",
  "empty-deliveries", "wrong-attempt", "not-restored", "404", "conflict", "expired"]) {
  test(`outage continuation classifies exact HTTP outcome: ${fault}`, async (t) => {
    const retryable = ["retryable503", "unreadable503", "transport", "per-request-timeout"].includes(fault);
    const f = await contextOutageFixture(t, { reply: async (attempt, _body, init, restored) => {
      if (attempt > 2) return outageResponse(restored());
      if (fault === "transport") throw new Error("no headers");
      if (fault === "per-request-timeout") return new Promise((_, reject) =>
        init.signal.addEventListener("abort", () => reject(new Error("request timed out")), { once: true }));
      if (fault === "retryable503") return outageBusy();
      if (fault === "unreadable503") return { ok: false, status: 503, text: async () => { throw new Error("lost error body"); } };
      if (fault === "nonretryable503") return outageResponse({ detail: { retryable: false } }, 503);
      if (fault === "unknown503") return outageResponse({ detail: "refused" }, 503);
      if (fault === "startup-lookalike") return outageResponse({
        error: "service not initialized", detail: { retryable: false },
      }, 503);
      if (fault === "lost200") return { ok: true, status: 200, text: async () => { throw new Error("lost after 200 headers"); } };
      if (fault === "empty200") return new Response("", { status: 200 });
      if (fault === "malformed200") return new Response("{", { status: 200 });
      if (fault === "malformed-shape") return outageResponse({});
      if (fault === "empty-deliveries") return outageResponse({ ...restored(), deliveries: [] });
      if (fault === "wrong-attempt") return outageResponse({ ...restored(),
        deliveries: [{ ...restored().deliveries[0], attempts: 2 }] });
      if (fault === "not-restored") return outageResponse({ ...restored(), restored: false });
      return outageResponse({ detail: fault === "expired" ? "receipt expired" : "definitive conflict" }, fault === "404" ? 404 : 409);
    } });
    const user = projectedWake(), result = f.run(user).then(() => null, (error) => error);
    try {
      await outageUntil(() => f.attempts() === 1);
      if (retryable) {
        if (fault === "per-request-timeout") await f.advance(6000);
        await f.advance(2500);
        await outageUntil(() => f.attempts() === 2);
        if (fault === "per-request-timeout") await f.advance(6000);
        await f.advance(2500);
        await outageUntil(() => f.attempts() === 3);
      }
      const error = await result;
      assert.equal(Boolean(error), !retryable);
      assert.equal(user.content.length, retryable ? 2 : 1);
      assert.equal(f.attempts(), retryable ? 3 : 1);
      assert.equal(f.enrollments(), 0); assert.equal(f.acks(), 1);
      assert.equal(f.native.prompt.length, 0);
      assert.equal(f.calls.filter((c) => c.path === "/relay/turn").length, 0);
    } finally { await f.close(); await result; }
  });
}

for (const mode of ["ack", "restored", "admitted", "uncertain", "ack-body-lost", "unconfirmed-startup"]) {
  test(`outage continuation requires confirmed original custody: ${mode}`, async (t) => {
    const confirm = mode === "unconfirmed-startup" ? "admitted" : mode;
    const f = await contextOutageFixture(t, { confirm, reply: (attempt) => attempt !== 1 ? undefined :
      mode === "unconfirmed-startup" ? outageResponse({ error: "service not initialized" }, 503) : outageBusy() });
    const user = projectedWake(), result = f.run(user).then(() => null, (error) => error);
    try {
      await outageUntil(() => f.attempts() === 1);
      const eligible = ["ack", "restored"].includes(confirm);
      if (eligible) { await f.advance(2500); await outageUntil(() => f.attempts() === 2); }
      const error = await result;
      assert.equal(Boolean(error), !eligible);
      if (!eligible) assert.equal(error.message,
        `Pallium wake context lookup did not return a usable result (delivery_id=${deliveryID})`);
      assert.equal(user.content.length, eligible ? 2 : 1);
      assert.equal(f.enrollments(), 0);
      assert.equal(f.acks(), ["restored", "admitted"].includes(confirm) ? 0 : 1);
    } finally { await f.close(); await result; }
  });
}

for (const first of ["poll", "enroll"]) {
  test(`outage continuation preserves equivalent registration response order: ${first}`, async (t) => {
    const enrollment = barrier(), polling = barrier();
    const f = await contextOutageFixture(t, {
      reply: (attempt) => attempt <= 2 ? outageBusy() : attempt === 3 ?
        outageResponse({ detail: "OpenCode registration is missing or stale" }, 409) : undefined,
      enroll: async () => { await enrollment.wait(); return outageResponse({ session: relaySession, wake: f.known }); },
      poll: async () => { await polling.wait(); return outageResponse({ session: relaySession, wake: f.known }); },
    });
    const user = projectedWake(), result = f.run(user).then(() => null, (error) => error);
    try {
      await outageUntil(() => f.attempts() === 1); await f.advance(2500);
      await outageUntil(() => f.attempts() === 2); await f.advance(2500);
      await enrollment.entered;
      const tick = f.tick(); await polling.entered;
      (first === "poll" ? polling : enrollment).release(); await outageFlush();
      (first === "poll" ? enrollment : polling).release(); await outageFlush();
      await f.advance(20); await tick;
      assert.equal(await result, null); assert.match(user.content.at(-1).text, /שלום wake payload/);
      assert.equal(f.attempts(), 4); assert.equal(f.enrollments(), 1); assert.equal(f.acks(), 1);
    } finally { enrollment.release(); polling.release(); await f.close(); await result; }
  });
}

for (const after of ["restored", "stale", "malformed", "higher-scope"]) {
  test(`outage continuation spends enrollment once across temporary failure: ${after}`, async (t) => {
    const f = await contextOutageFixture(t, {
      reply: (attempt) => attempt === 1 ? outageBusy() : attempt === 2 || after === "stale" ?
        outageResponse({ detail: "OpenCode registration is missing or stale" }, 409) : undefined,
      enroll: () => after === "malformed" ? outageResponse({}) : after === "higher-scope" ?
        outageResponse({ session: { ...relaySession, scope_generation: 1 }, wake: snapshot() }) : outageBusy(),
    });
    const result = f.run().then(() => null, (error) => error);
    try {
      await outageUntil(() => f.attempts() === 1); await f.advance(2500);
      await outageUntil(() => f.enrollments() === 1); await outageFlush();
      if (["restored", "stale"].includes(after)) await f.advance(2500);
      assert.equal(Boolean(await result), after !== "restored");
      assert.equal(f.enrollments(), 1); assert.equal(f.acks(), 1);
    } finally { await f.close(); await result; }
  });
}

for (const stop of ["deadline-held-get", "dispose-held-get", "deadline-response", "just-before",
  "at-cutoff", "terminal", "replacement", "scope", "location", "input"]) {
  test(`outage continuation bounds local lifetime and late effects: ${stop}`, async (t) => {
    const held = barrier();
    let holding = false, moved = false, responseSignal;
    const f = await contextOutageFixture(t, {
      response: (route, body) => route === "/relay/turn" ? {
        session: { ...relaySession, container_ref: body.container_ref }, deliveries: [],
      } : undefined,
      get: async (input, armed) => {
        if (armed && stop.includes("held-get")) { holding = true; await held.wait(); }
        return { id: input.sessionID, location: { directory: moved ? location + "/other" : location } };
      },
      reply: async (attempt, _body, init, restored) => {
        responseSignal = init.signal;
        if (stop === "just-before" && attempt === 1) return outageBusy();
        if (["deadline-response", "at-cutoff", "just-before"].includes(stop)) { await held.wait(); return outageResponse(restored()); }
        return attempt === 1 ? outageBusy() : undefined;
      },
      poll: () => outageResponse({ session: { ...relaySession, scope_generation: stop === "scope" ? 1 : 0 },
        wake: snapshot({ admitted: true, ...(stop === "terminal" ? { terminal: true } :
          { generation: 2, native_input_id: "msg_replacement" }) }) }),
    });
    const user = projectedWake(), result = f.run(user).then(() => null, (error) => error);
    try {
      if (stop.includes("held-get")) await outageUntil(() => holding);
      else await outageUntil(() => f.attempts() === 1);
      if (stop === "dispose-held-get") await f.dispose();
      else if (["deadline-held-get", "deadline-response", "at-cutoff"].includes(stop)) await f.advance(120000);
      else if (stop === "just-before") {
        await f.advance(117499); await outageUntil(() => f.attempts() === 2);
        await f.advance(2500); held.release();
      }
      else if (stop === "input") { user.id = "msg_replaced"; await f.advance(2500); }
      else if (stop === "location") { moved = true; await f.advance(2500); }
      else { const tick = f.tick(); await outageFlush(); await f.advance(20); await tick; }
      const error = await result;
      assert.equal(Boolean(error), stop !== "just-before");
      assert.equal(user.content.length, stop === "just-before" ? 2 : 1);
      const count = f.calls.length;
      held.release(); await outageFlush();
      assert.equal(f.calls.length, count, "late SDK/response completion cannot dispatch or attach");
      assert.equal(f.acks(), 1);
      if (stop === "deadline-held-get") {
        const successor = container + "/successor";
        pinContainer(sessionID, successor, undefined, "successor-actor");
        const ordinary = ordinaryProjection("msg_after_abandoned_read");
        await f.hooks.context({ sessionID, messages: [ordinary] }); // Retire the old scope.
        await f.hooks.context({ sessionID, messages: [ordinary] }); // Resolve the successor lifetime.
        assert.equal(getPinnedContainer(sessionID), successor);
        assert.equal(f.calls.filter((c) => c.path === "/relay/turn").at(-1).body.container_ref, successor);
        assert.ok(ordinary.content.at(-1).text.includes(successor));
        assert.equal(user.content.length, 1, "abandoned context stays unattached after successor work");
        assert.equal(f.acks(), 1);
      }
      if (stop === "deadline-response") assert.equal(responseSignal.aborted, true);
    } finally { held.release(); await f.close(); await result; }
  });
}

for (const fault of ["registration", "empty", "snapshot", "closed", "404", "503", "other",
  "truncated", "unreadable", "null", "transport"]) {
  test(`context recovery accepts only an explicit registration conflict: ${fault}`, async () => {
    const initial = fault === "registration" ? undefined : () => {
      if (fault === "transport") throw new Error("transport");
      if (fault === "empty") return jsonResponse({ session: relaySession, wake: snapshot(), deliveries: [] });
      if (fault === "null") return jsonResponse(null);
      const detail = fault === "snapshot" ? "OpenCode native wake snapshot is stale" :
        fault === "closed" ? "OpenCode endpoint is closed or its scope changed" : "other";
      return { ok: false, status: ["404", "503"].includes(fault) ? Number(fault) : 409,
        text: async () => { if (fault === "unreadable") throw new Error("body");
          return fault === "truncated" ? '{"detail":' : JSON.stringify({ detail }); } };
    };
    const f = await contextRecoveryFixture({ initial }), user = projectedWake(), before = structuredClone(user);
    try {
      if (fault === "registration") {
        await f.run(user); assert.match(user.content.at(-1).text, /שלום wake payload/);
      } else { await assert.rejects(f.run(user)); assert.deepEqual(user, before); }
      assert.deepEqual(f.count, { context: fault === "registration" ? 2 : 1, enroll: fault === "registration" ? 1 : 0 });
      assert.equal(f.acks(), 0); assert.equal(f.native.prompt.length, 0);
    } finally { await f.close(); }
  });
}

for (const phase of ["enroll", "retry"]) for (const fault of ["409", "503", "malformed"]) {
  test(`context recovery stops after one enrollment and one exact retry: ${phase}/${fault}`, async () => {
    const fail = () => fault === "malformed" ? jsonResponse(phase === "enroll" ? {} :
      { session: relaySession, wake: snapshot({ admitted: true }), deliveries: [] }) :
      { ok: false, status: Number(fault), text: async () => JSON.stringify({
        detail: "OpenCode registration is missing or stale" }) };
    const f = await contextRecoveryFixture({ [phase]: fail }), user = projectedWake(), before = structuredClone(user);
    try {
      await assert.rejects(f.run(user));
      assert.deepEqual(f.count, { context: phase === "enroll" ? 1 : 2, enroll: 1 });
      assert.deepEqual(user, before); assert.equal(f.acks(), 0);
      assert.equal(f.native.prompt.length, 0);
    } finally { await f.close(); }
  });
}

for (const change of ["terminal", "generation", "dispose"]) {
  test(`context recovery guards enrollment internal ownership await: ${change}`, async () => {
    const gate = barrier(); let held = false;
    const f = await contextRecoveryFixture({ get: async (input, phase) => {
      if (phase === "enroll-get" && !held) { held = true; await gate.wait(); }
      return { id: input.sessionID, location: { directory: location } };
    } }), user = projectedWake(), before = structuredClone(user);
    const outcome = f.run(user).then(() => null, (error) => error);
    try {
      await gate.entered;
      if (change === "dispose") await f.dispose();
      else {
        f.setBackend({ session: relaySession, wake: snapshot({ admitted: true,
          ...(change === "terminal" ? { terminal: true } : { generation: 2, native_input_id: "msg_successor" }) }) });
        await f.tick();
      }
      gate.release(); assert.ok(await outcome);
      assert.deepEqual(f.count, { context: 1, enroll: 0 });
      assert.deepEqual(user, before); assert.equal(f.acks(), 0); assert.equal(f.native.prompt.length, 0);
    } finally { gate.release(); await outcome; await f.close(); }
  });
}

for (const first of ["enroll", "poll"]) {
  test(`context recovery preserves equivalent poll progress in either response order: ${first}`, async () => {
    const enrollment = barrier(), polling = barrier(), waiting = barrier();
    let holdPoll = false;
    const value = { session: relaySession, wake: snapshot({ admitted: true }) };
    const f = await contextRecoveryFixture({ enroll: async () => { await enrollment.wait(); return jsonResponse(value); },
      poll: async () => { if (holdPoll) await polling.wait(); return jsonResponse(value); },
      wait: () => waiting.wait() });
    const user = projectedWake(), before = structuredClone(user);
    let outcome;
    try {
      await f.tick(); await waiting.entered;
      outcome = f.run(user).then(() => null, (error) => error); await enrollment.entered;
      holdPoll = true; await f.tick(); await polling.entered;
      (first === "enroll" ? enrollment : polling).release(); await pause();
      (first === "enroll" ? polling : enrollment).release();
      const error = await outcome; await pause(); holdPoll = false;
      assert.equal(Boolean(error), first === "poll");
      if (error) assert.deepEqual(user, before); else assert.match(user.content.at(-1).text, /שלום wake payload/);
      assert.deepEqual(f.count, { context: first === "poll" ? 1 : 2, enroll: 1 });
      await f.tick(); assert.equal(f.native.wait, 1); assert.equal(f.acks(), 0);
      f.history.push({ type: "idle", id: "msg_preserved_terminal", outcome: "succeeded" });
      waiting.release(); await until(() => terminals(f).length === 1, "preserved flight terminal");
    } finally { enrollment.release(); polling.release(); waiting.release(); await outcome; await f.close(); }
  });
}

for (const shape of ["terminal", "null", "replacement"]) for (const first of ["enroll", "poll"]) {
  test(`context recovery discards terminal null and replacement enrollment replies: ${shape}/${first}`, async () => {
    const gate = barrier(), original = snapshot({ admitted: true });
    const changed = shape === "null" ? null : { ...original,
      ...(shape === "terminal" ? { terminal: true } : { generation: 2, native_input_id: "msg_successor" }) };
    const f = await contextRecoveryFixture({ enroll: async () => {
      await gate.wait(); return jsonResponse({ session: relaySession, wake: changed });
    } }), user = projectedWake(), before = structuredClone(user);
    const outcome = f.run(user).then(() => null, (error) => error);
    try {
      await gate.entered;
      if (first === "poll") { f.setBackend({ session: relaySession, wake: changed }); await f.tick(); }
      gate.release(); assert.ok(await outcome);
      assert.deepEqual(f.count, { context: 1, enroll: 1 }); assert.deepEqual(user, before);
      assert.equal(f.acks(), 0); assert.equal(f.native.prompt.length, 0);
      if (first === "enroll") {
        const stillCurrent = projectedWake(); await f.run(stillCurrent);
        assert.match(stillCurrent.content.at(-1).text, /שלום wake payload/,
          "rejected reply must not adopt terminal/null/replacement authority");
        f.setBackend({ session: relaySession, wake: changed }); await f.tick();
      }
    } finally { gate.release(); await outcome; await f.close(); }
  });
}

for (const successor of [false, true]) {
  test(`context recovery preserves higher-scope retirement and newer lifetimes: ${successor}`, async () => {
    const gate = barrier(), pending = barrier();
    const f = await contextRecoveryFixture({ enroll: async () => {
      await gate.wait(); return jsonResponse({ session: { ...relaySession, scope_generation: 1 }, wake: snapshot() });
    }, retry: async () => { await pending.wait(); } }), user = projectedWake(), before = structuredClone(user);
    const outcome = f.run(user).then(() => null, (error) => error);
    let active;
    try {
      await gate.entered;
      active = f.run(projectedWake()).then(() => null, (error) => error);
      await pending.entered;
      if (successor) {
        f.setBackend({ session: { ...relaySession, scope_generation: 2 }, wake: null });
        await f.tick();
      }
      gate.release(); assert.ok(await outcome);
      assert.deepEqual(user, before); assert.deepEqual(f.count, { context: 2, enroll: 1 });
      assert.equal(f.calls.filter((c) => c.body.operation === "context").at(-1).signal.aborted, true);
      pending.release(); assert.ok(await active);
      const scopeGeneration = successor ? 2 : 1;
      f.setBackend({ session: { ...relaySession, scope_generation: scopeGeneration }, wake: null });
      await f.tick();
      assert.equal(f.calls.filter((c) => c.body.operation === "poll").at(-1).body.scope_generation, scopeGeneration);
      assert.equal(f.acks(), 0); assert.equal(f.native.prompt.length, 0);
    } finally { gate.release(); pending.release(); await outcome; await active; await f.close(); }
  });
}

test("context recovery discards malformed enrollment without clearing proof", async () => {
  const responseGate = barrier(), waitGate = barrier(); let first = true;
  const value = { session: relaySession, wake: snapshot({ admitted: true }) };
  const f = await contextRecoveryFixture({ enroll: async () => {
    if (first) { first = false; await responseGate.wait(); return jsonResponse({}); }
    return jsonResponse(value);
  }, wait: () => waitGate.wait() }), user = projectedWake(), before = structuredClone(user);
  const outcome = f.run(user).then(() => null, (error) => error);
  try {
    await responseGate.entered;
    f.history.splice(0); await observePrompt(f); f.history.push(freshUser());
    await f.tick(); await waitGate.entered;
    responseGate.release(); assert.ok(await outcome);
    assert.deepEqual(user, before); assert.equal(f.count.context, 1); assert.equal(f.acks(), 0);
    await f.tick(); assert.equal(f.native.wait, 1); assert.equal(terminals(f).length, 0);
    f.history.push(freshIdle()); waitGate.release();
    await until(() => terminals(f).length === 1, "successor witness survives old malformed reply");
    assert.equal(terminals(f)[0].body.native_input_id, nativeID);
    assert.equal(terminals(f)[0].body.terminal_message_id, freshIdle().id);
    assert.equal(f.native.prompt.length, 0);
  } finally { responseGate.release(); waitGate.release(); await outcome; await f.close(); }
});

for (const [point, change] of [["retry-response", "terminal"], ["retry-response", "generation"],
  ["pre-retry-get", "scope"], ["final-get", "generation"], ["final-get", "location"], ["final-get", "dispose"]]) {
  test(`context recovery fences retry and final attachment awaits: ${point}/${change}`, async () => {
    const gate = barrier(); let held = false, moved = false;
    const f = await contextRecoveryFixture({
      get: async (input, phase) => {
        if (phase === point && !held) { held = true; await gate.wait(); }
        return { id: input.sessionID, location: { directory: moved ? location + "/other" : location } };
      },
      retry: point === "retry-response" ? async () => { await gate.wait(); } : undefined,
    }), user = projectedWake(), before = structuredClone(user);
    const outcome = f.run(user).then(() => null, (error) => error);
    try {
      await gate.entered;
      if (change === "dispose") await f.dispose();
      else if (change === "location") moved = true;
      else {
        const scopeGeneration = change === "scope" ? 1 : 0;
        f.setBackend({ session: { ...relaySession, scope_generation: scopeGeneration },
          wake: snapshot({ admitted: true, scope_generation: scopeGeneration,
            ...(change === "terminal" ? { terminal: true } : { generation: 2, native_input_id: "msg_fence_new" }) }) });
        await f.tick();
      }
      gate.release(); assert.ok(await outcome);
      assert.deepEqual(user, before); assert.equal(f.acks(), 0);
      assert.deepEqual(f.count, { enroll: 1, context: point === "pre-retry-get" ? 1 : 2 });
      if (["generation", "scope"].includes(change)) {
        f.history.push({ type: "user", id: "msg_fence_new", text: projectedWake().content[0].text,
          metadata: { ...projectedWake().metadata, generation: 2 } },
        { type: "idle", id: "msg_fence_terminal", outcome: "succeeded" });
        await f.tick(); await until(() => terminals(f).length === 1, "successor still progresses");
        assert.equal(terminals(f)[0].body.native_input_id, "msg_fence_new");
        assert.equal(terminals(f)[0].body.scope_generation, change === "scope" ? 1 : 0);
      }
      assert.equal(f.native.prompt.length, 0);
    } finally { gate.release(); await outcome; await f.close(); }
  });
}

test("overlapping context recoveries retain per-invocation bounds", async () => {
  const gates = [barrier(), barrier()];
  const f = await contextRecoveryFixture({ initialCount: 2, enroll: async (_body, count) => {
    await gates[count - 1].wait();
    return jsonResponse({ session: relaySession, wake: snapshot({ admitted: true }) });
  } }), users = [projectedWake(), projectedWake()];
  const outcomes = users.map((user) => f.run(user).then(() => null, (error) => error));
  try {
    await Promise.all(gates.map((gate) => gate.entered));
    gates[0].release(); await pause(); gates[1].release();
    const errors = await Promise.all(outcomes);
    assert.equal(errors.filter(Boolean).length, 1);
    assert.equal(users.filter((user) => user.content.length === 2).length, 1);
    assert.deepEqual(f.count, { context: 3, enroll: 2 });
    assert.equal(f.acks(), 0); assert.equal(f.native.prompt.length, 0);
  } finally { gates.forEach((gate) => gate.release()); await Promise.all(outcomes); await f.close(); }
});

for (const mismatch of [false, true]) test(`committed ${mismatch ? "mismatched" : "empty"} wake fails visibly while newer natural work remains usable`, async () => {
  const f = await callerFixture({ wake: snapshot(), response: (_path, body) => {
    if (mismatch && body.operation === "context")
      return { deliveries: [{ delivery_id: "relay-delivery-" + "f".repeat(32), payload: "untrusted response data" }] };
  } });
  try {
    await assert.rejects(f.hooks.context({ sessionID, messages: [projectedWake()] }), {
      message: `Pallium wake context response has no matching delivery (delivery_id=${deliveryID})`,
    });
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
      return { session: relaySession, wake: snapshot({ admitted: true }), restored: contextCalls > 1,
        deliveries: [contextCalls === 1 ? delivery : { ...delivery, state: "delivered", claim_token: undefined }] };
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

for (const [name, list] of [
  ["empty then eligible", [[], [relaySession]]],
  ["error and repeated empty then eligible", [null, [], [], [relaySession]]],
]) {
  test(`startup empty discovery recovers without a recipient prompt: ${name}`, async () => {
    const f = await callerFixture({ list });
    try {
      for (let index = 1; index < list.length; index++) {
        assert.equal(f.listed(), index);
        assert.equal(f.calls.filter((c) => c.body.operation === "enroll").length, 0);
        await f.tick();
      }
      const [enrollment] = f.calls.filter((c) => c.body.operation === "enroll");
      assert.ok(enrollment, "a later eligible endpoint must enroll without a recipient turn");
      assert.equal(f.listed(), list.length);
      assert.match(enrollment.body.owner_id, /^opencode-owner-[0-9a-f]{32}$/);
      const binding = { session_ref: sessionID, container_ref: container, endpoint_id: endpointID,
        scope_generation: 0, native_location: location, owner_id: enrollment.body.owner_id };
      assert.deepEqual(enrollment.body, { operation: "enroll", ...binding });
      await f.tick();
      await f.tick();
      assert.equal(f.listed(), list.length, "nonempty success stops startup discovery");
      assert.equal(f.calls.filter((c) => c.body.operation === "enroll").length, 1);
      const polls = f.calls.filter((c) => c.body.operation === "poll");
      assert.equal(polls.length, 2);
      for (const poll of polls) assert.deepEqual(poll.body, { operation: "poll", ...binding });
      assert.ok(f.calls.every((c) => c.path === "/relay/sessions" ||
        c.path === "/relay/opencode/wake" && ["enroll", "poll"].includes(c.body.operation)));
      assert.deepEqual(f.native, { prompt: [], wait: 0, interrupt: 0 });
      assert.deepEqual(f.history, []);
    } finally { await f.close(); }
  });
}

test("startup nonempty discovery enrolls once and only polls thereafter", async () => {
  const f = await callerFixture();
  try {
    await f.tick();
    await f.tick();
    assert.equal(f.listed(), 1);
    assert.equal(f.calls.filter((c) => c.body.operation === "enroll").length, 1);
    assert.equal(f.calls.filter((c) => c.body.operation === "poll").length, 2);
    assert.equal(f.calls.filter((c) => c.path === "/relay/turn" || c.path === "/relay/deliveries/ack" ||
      ["context", "admitted", "terminal"].includes(c.body.operation)).length, 0);
    assert.deepEqual(f.native, { prompt: [], wait: 0, interrupt: 0 });
  } finally { await f.close(); }
});

for (const eligible of [false, true]) {
  test(`startup empty discovery does not overlap an in-flight ${eligible ? "eligible" : "empty"} response`, async () => {
    const gate = barrier();
    let requests = 0;
    const f = await callerFixture({ list: [[]], fetch: async (route) => {
      if (route === "/relay/sessions" && ++requests === 2) return {
        ok: true, text: async () => { await gate.wait(); return JSON.stringify(eligible ? [relaySession] : []); },
      };
    } });
    try {
      await f.tick();
      await gate.entered;
      await Promise.all([f.tick(), f.tick()]);
      assert.equal(requests, 2, "timer callbacks cannot overlap the held discovery body");
      assert.equal(f.calls.filter((c) => c.body.operation === "enroll").length, 0);
      gate.release();
      await f.tick(); // The existing tick settles the released response; no new sleep.
      assert.equal(requests, 2);
      assert.equal(f.calls.filter((c) => c.body.operation === "enroll").length, eligible ? 1 : 0);
      await f.tick();
      assert.equal(requests, eligible ? 2 : 3);
      assert.equal(f.calls.filter((c) => c.body.operation === "enroll").length, 1);
      assert.equal(f.calls.filter((c) => c.path === "/relay/turn" || c.path === "/relay/deliveries/ack" ||
        c.body.operation === "context").length, 0);
      assert.deepEqual(f.native, { prompt: [], wait: 0, interrupt: 0 });
    } finally { gate.release(); await f.close(); }
  });
}

for (const retire of ["dispose", "delete"]) for (const eligible of [false, true]) {
  test(`startup empty discovery fences a retired ${eligible ? "eligible" : "empty"} response after ${retire}`, async () => {
    const gate = barrier();
    let requests = 0;
    const f = await callerFixture({ list: [[]], fetch: async (route) => {
      if (route === "/relay/sessions" && ++requests === 2) return {
        ok: true, text: async () => { await gate.wait(); return JSON.stringify(eligible ? [relaySession] : []); },
      };
    } });
    try {
      await f.tick();
      await gate.entered;
      if (retire === "dispose") await f.dispose();
      else await f.emit({ type: "session.deleted", location: { directory: location }, data: { sessionID } });
      gate.release();
      await f.tick();
      assert.equal(requests, 2);
      assert.equal(f.calls.filter((c) => c.body.operation === "enroll").length, 0,
        "a retired discovery response cannot enroll late");
      await f.tick();
      assert.equal(requests, retire === "dispose" ? 2 : 3);
      assert.equal(f.calls.filter((c) => c.body.operation === "enroll").length, retire === "dispose" ? 0 : 1,
        "a new valid discovery after retirement is distinct from the stale response");
      assert.equal(f.calls.filter((c) => c.path === "/relay/turn" || c.path === "/relay/deliveries/ack" ||
        ["context", "admitted", "terminal"].includes(c.body.operation)).length, 0);
      assert.deepEqual(f.native, { prompt: [], wait: 0, interrupt: 0 });
    } finally { gate.release(); await f.close(); }
  });
}

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

const freshUser = () => sourceUser("msg_fresh_ordinary", "fresh ordinary work שלום 😀");
const freshIdle = (outcome = "succeeded") => ({ type: "idle", id: "msg_fresh_terminal", outcome });
const observePrompt = (f, user = freshUser()) => f.hooks.prompt({ sessionID, messageID: user.id, prompt: { text: user.text } });
const terminals = (f) => f.calls.filter((c) => c.body.operation === "terminal");

for (const outcome of ["succeeded", "failed", "interrupted"]) {
  test(`fresh supersession settles exact frozen generation: ${outcome}`, async () => {
    const f = await callerFixture({ wake: snapshot({ admitted: true }), wait: async (history) => history.push(freshIdle(outcome)) });
    try {
      await observePrompt(f); // Real first observation before native preparation/promotion.
      f.history.push(freshUser());
      await f.tick();
      assert.equal(terminals(f).length, 1, "fresh promoted ordinary work must release the missing admitted anchor");
      assert.deepEqual([terminals(f)[0].body.generation, terminals(f)[0].body.delivery_id,
        terminals(f)[0].body.native_input_id, terminals(f)[0].body.terminal_message_id],
      [1, deliveryID, nativeID, freshIdle().id]);
      assert.equal(f.calls.filter((c) => c.body.operation === "admitted" || c.path === "/relay/deliveries/ack").length, 0);
      assert.deepEqual(f.native, { prompt: [], wait: 1, interrupt: 0 });
      assert.deepEqual(f.trace.slice(f.trace.lastIndexOf("wait") - 2),
        ["get", "raw", "wait", "get", "raw", "poll", "get", "raw", "terminal"], "canonical final raw ordering");
      await f.tick();
      assert.equal(terminals(f).length, 1, "consumed proof cannot replay even before backend reconciliation");
    } finally { await f.close(); }
  });
}

for (const preparation of ["prompt-await", "queued"]) {
  test(`fresh supersession retains unpromoted candidate: ${preparation}`, async () => {
    const gate = barrier();
    const f = await callerFixture({ wake: snapshot({ admitted: true }),
      fetch: async (route) => { if (route === "/item-and-query" && preparation === "prompt-await") await gate.wait(); },
      wait: async (history) => history.push(freshIdle()) });
    const prompt = observePrompt(f);
    try {
      if (preparation === "prompt-await") await gate.entered;
      else await prompt;
      await f.tick();
      await f.tick(); // wakeBusy must have been released, without rearming.
      assert.equal(terminals(f).length, 0);
      assert.equal(f.native.wait, 0, "queued/prepared U is not native promotion");
      gate.release();
      await prompt;
      f.history.push(freshUser());
      await f.tick();
      assert.equal(terminals(f).length, 1, "same frozen U must recover without a second prompt");
      assert.equal(f.native.prompt.length, 0);
      assert.equal(f.calls.filter((c) => c.path === "/item-and-query").length, 1);
    } finally { gate.release(); await prompt; await f.close(); }
  });
}

test("fresh supersession requires observed producer promotion before admission", async () => {
  for (const knownBeforePrompt of [false, true]) {
    const wake = snapshot(), readbacks = []; let promoted = false;
    const f = await callerFixture({ wake,
      prompt: async () => { if (!promoted) f.history.pop(); return { queued: true }; },
      response: async (route, body) => {
        if (route !== "/relay/opencode/wake") return;
        if (body.operation === "admitted") wake.admitted = true; // Backend write is NOT a local cache update.
        if (body.operation === "poll") readbacks.push({ ...wake });
      },
      wait: async (history) => { if (!history.some((row) => row.id === nativeID)) history.push(freshIdle()); } });
    try {
      await f.tick();
      assert.equal(f.calls.filter((c) => c.body.operation === "admitted").length, 0, "queue acceptance is not native promotion");
      const input = f.native.prompt[0];
      promoted = true;
      f.history.push({ type: "user", id: input.id, text: input.text, metadata: input.metadata });
      await f.tick();
      assert.equal(wake.admitted, true, "certified native producer committed admission in backend");
      assert.equal(readbacks.at(-1).admitted, false, "preceding poll did not yet tell the adapter admission was committed");
      assert.equal(terminals(f).length, 0, "promotion alone is not terminal evidence");
      if (knownBeforePrompt) {
        const waits = f.native.wait;
        await f.tick(); // Genuine normal-poll readback while G remains visible.
        assert.equal(readbacks.at(-1).admitted, true, "admitted G was returned BEFORE first observation of U");
        assert.equal(f.native.wait, waits + 1, "adapter consumed that poll and progressed its bound visible-G flight");
      }
      f.history.length = 0;
      await observePrompt(f);
      f.history.push(freshUser());
      if (!knownBeforePrompt) f.history.push(freshIdle()); // Even completed later U cannot retrofit eligibility.
      await f.tick();
      await f.tick();
      assert.equal(terminals(f).length, knownBeforePrompt ? 1 : 0,
        knownBeforePrompt ? "poll-established admitted G permits fresh witnessed settlement" : "later enrollment/poll must not retrofit first observation");
      assert.equal(f.native.prompt.length, 1, "fresh witness must not replay G");
    } finally { await f.close(); }
  }
});

test("fresh supersession keeps native ID and ordinary input boundaries", async () => {
  for (const [id, text, expected] of [["", "ordinary", 0], ["invalid", "ordinary", 0],
    ["msg_" + "a".repeat(508), "boundary שלום 😀", 1], ["msg_" + "a".repeat(509), "over boundary", 0],
    ["msg_empty", "", 0], ["msg_command", "/command", 0]]) {
    const f = await callerFixture({ wake: snapshot({ admitted: true }), wait: async (history) => history.push(freshIdle()) });
    try {
      const user = sourceUser(id, text);
      await observePrompt(f, user); f.history.push(user); await f.tick();
      assert.equal(terminals(f).length, expected, `${id.length}/${text}`);
    } finally { await f.close(); }
  }
});

test("fresh supersession never retrofits duplicate or historical observations", async () => {
  for (const fault of ["no-known-G", "unadmitted-G", "terminal-G", "duplicate", "memory-retry", "context-only", "delayed-enroll", "duplicate-owned-await"]) {
    let known = !["no-known-G", "delayed-enroll"].includes(fault), hold = false, later = false;
    const gate = barrier();
    const f = await callerFixture({ wake: null,
      get: async ({ sessionID: id }) => { if (hold) { hold = false; await gate.wait(); } return { id, location: { directory: location } }; },
      response: async (route) => {
        if (route === "/item-and-query" && fault === "memory-retry") return null;
        if (route === "/relay/opencode/wake" && fault === "delayed-enroll" && !known) await gate.wait();
        if (route === "/relay/opencode/wake") return { session: relaySession,
          wake: known ? snapshot({ admitted: fault !== "unadmitted-G" || later, terminal: fault === "terminal-G" }) : null };
      }, wait: async (history) => history.push(freshIdle()) });
    try {
      if (fault === "context-only") await f.hooks.context({ sessionID, messages: [natural(freshUser().id)] });
      else if (fault === "duplicate-owned-await") {
        hold = true;
        const first = observePrompt(f);
        await gate.entered;
        await observePrompt(f);
        gate.release(); await first;
      } else {
        await observePrompt(f);
        if (["duplicate", "memory-retry"].includes(fault)) await observePrompt(f);
      }
      known = true; later = true;
      f.history.push(freshUser(), freshIdle());
      if (fault === "delayed-enroll") { gate.release(); await pause(); }
      await f.tick();
      assert.equal(terminals(f).length, 0, fault);
      // Null freshness tombstones must not break ordinary snapshots or capture.
      assert.equal(f.native.interrupt, 0);
    } finally { gate.release(); await f.close(); }
  }
});

test("fresh supersession rejects malformed or lost promoted proof", async () => {
  for (const fault of ["missing-U", "wrong-text", "wrong-type", "internal", "duplicate-U", "nonlatest", "missing-T", "different-T",
    "missing-id", "invalid-id", "same-U", "same-G", "outcomeless", "unknown-outcome", "before-U", "uncertain-first-idle", "malformed-context"]) {
    let contexts = 0;
    const f = await callerFixture({ wake: snapshot({ admitted: true }),
      context: async (_input, history) => { contexts++; return fault === "malformed-context" && contexts > 1 ? {} : { data: history }; },
      wait: async (history) => {
        const u = history[0], t = freshIdle();
        if (fault === "missing-U") history.shift();
        if (fault === "wrong-text") u.text += "changed";
        if (fault === "wrong-type") u.type = "assistant";
        if (fault === "internal") u.metadata = { pallium_relay_wake: true };
        if (fault === "duplicate-U") history.push({ ...u });
        if (fault === "nonlatest") history.push(sourceUser("msg_other_fresh"));
        if (fault === "missing-id") delete t.id;
        if (fault === "invalid-id") t.id = "invalid";
        if (fault === "same-U") t.id = u.id;
        if (fault === "same-G") t.id = nativeID;
        if (fault === "outcomeless") delete t.outcome;
        if (fault === "unknown-outcome") t.outcome = "completed";
        if (fault === "before-U") history.unshift(t);
        else if (fault === "uncertain-first-idle") history.push({ type: "idle", id: "msg_uncertain" }, t);
        else if (fault !== "missing-T") history.push(t);
      },
      response: async (route, body) => {
        if (fault === "different-T" && route === "/relay/opencode/wake" && body.operation === "poll" && contexts >= 3)
          f.history.at(-1).id = "msg_replacement_terminal";
      } });
    try {
      await observePrompt(f); f.history.push(freshUser());
      await f.tick();
      assert.equal(terminals(f).length, 0, fault);
      assert.equal(f.native.prompt.length, 0);
    } finally { await f.close(); }
  }
});

test("fresh supersession rechecks raw evidence across final asynchronous fences", async () => {
  for (const stage of ["poll", "final-get", "final-context"]) for (const mutation of ["remove-U", "change-U", "new-user", "remove-T", "replace-T"]) {
    let armed = false, polled = false, got = false;
    const mutate = (history) => {
      if (mutation === "remove-U") history.shift();
      if (mutation === "change-U") history[0].text += "changed";
      if (mutation === "new-user") history.push(sourceUser("msg_later_raw"));
      if (mutation === "remove-T") history.pop();
      if (mutation === "replace-T") history.at(-1).id = "msg_different_terminal";
    };
    const f = await callerFixture({ wake: snapshot({ admitted: true }),
      wait: async (history) => { history.push(freshIdle()); armed = true; },
      get: async ({ sessionID: id }) => {
        if (polled) { got = true; if (stage === "final-get") mutate(f.history); }
        return { id, location: { directory: location } };
      },
      context: async (_input, history) => { if (got && stage === "final-context") mutate(history); return { data: history }; },
      response: async (route, body) => {
        if (armed && route === "/relay/opencode/wake" && body.operation === "poll") {
          polled = true; if (stage === "poll") mutate(f.history);
        }
      } });
    try {
      await observePrompt(f); f.history.push(freshUser());
      await f.tick(); // No event hints at all: raw read, not event delivery, must fence this.
      assert.equal(terminals(f).length, 0, `${stage}/${mutation}`);
      assert.equal(f.native.prompt.length, 0);
    } finally { await f.close(); }
  }
});

test("fresh supersession fences lifecycle and backend changes during settlement", async () => {
  for (const stage of ["wait", "postwait-get", "postwait-context", "final-poll", "final-get", "final-context"])
    for (const fault of ["dispose", "compaction-hook", "compaction-event", "move", "revert-staged", "revert-cleared", "revert-committed", "shutdown", "delete", "archive",
    "subscription-end", "subscription-error", "endpoint", "scope", "generation", "delivery", "input", "terminal", "admitted", "owner", "location", "native-session", "native-revert"]) {
    const gate = barrier(); let changed = false, waitEnded = false, fenced = false, contexts = 0, heldGets = 0, getCalls = 0;
    const f = await callerFixture({ wake: snapshot({ admitted: true }),
      wait: async (history) => { if (stage === "wait") await gate.wait(); history.push(freshIdle()); waitEnded = true; },
      get: async ({ sessionID: id }) => {
        getCalls++;
        if (!heldGets && (waitEnded && !fenced && stage === "postwait-get" || fenced && stage === "final-get")) {
          heldGets++; // Hold only the selected verification lookup, not compaction's ownership lookup.
          await gate.wait();
        }
        return { id: changed && fault === "native-session" ? "ses_other" : id,
          location: { directory: changed && fault === "location" ? location + "/other" : location },
          ...(changed && fault === "native-revert" ? { revert: { messageID: freshUser().id } } : {}) };
      },
      context: async (_input, history) => {
        contexts++;
        if (contexts === 3 && stage === "postwait-context" || contexts === 4 && stage === "final-context") await gate.wait();
        return { data: history };
      },
      response: async (route, body) => {
        if (waitEnded && route === "/relay/opencode/wake" && body.operation === "poll") {
          if (stage === "final-poll") await gate.wait();
          fenced = true;
        }
        if (!changed || route !== "/relay/opencode/wake") return;
        if (body.operation === "terminal") return null; // Server rejects the frozen stale fence, never rebinds it.
        if (fault === "owner" && body.operation === "poll") return null;
        const session = { ...relaySession }, wake = snapshot({ admitted: true });
        if (fault === "endpoint") session.endpoint_id += "f";
        if (fault === "scope") session.scope_generation++;
        if (fault === "generation") wake.generation++;
        if (fault === "delivery") wake.delivery_id = "relay-delivery-" + "e".repeat(32);
        if (fault === "input") wake.native_input_id = "msg_other_wake";
        if (fault === "terminal") wake.terminal = true;
        if (fault === "admitted") wake.admitted = false;
        return { session, wake };
      } });
    try {
      await observePrompt(f); f.history.push(freshUser()); await f.tick(); await gate.entered;
      if (stage.endsWith("-get")) assert.equal(heldGets, 1, "selected verification lookup reached its one-shot barrier");
      assert.equal(terminals(f).length, 0, "no terminal before the held verification boundary");
      changed = true;
      if (fault === "dispose") await f.dispose();
      else if (fault === "compaction-hook") {
        const before = getCalls;
        await f.hooks.compaction({ sessionID });
        assert.ok(getCalls > before, "compaction performed its own ownership lookup while verification stayed held");
        if (stage.endsWith("-get")) assert.equal(heldGets, 1, "compaction must not re-enter the verification barrier");
        assert.equal(terminals(f).length, 0, "compaction cannot retire before the verification barrier is released");
      } else if (fault === "subscription-end") await f.emit({ fixtureEnd: true });
      else if (fault === "subscription-error") await f.emit({ fixtureError: true });
      else if (["compaction-event", "move", "delete", "archive", "shutdown"].includes(fault) || fault.startsWith("revert-")) {
        const type = { "compaction-event": "session.compaction.started", move: "session.moved", delete: "session.deleted", archive: "session.archived", shutdown: "session.execution.interrupted" }[fault]
          || "session.revert." + fault.slice(7);
        await f.emit({ type, location: { directory: fault === "move" ? location + "/other" : location }, data: { sessionID, reason: "shutdown" } });
      } else await f.tick();
      gate.release(); await pause();
      const lateBackend = ["final-get", "final-context"].includes(stage) &&
        ["endpoint", "scope", "generation", "delivery", "input", "terminal", "admitted", "owner"].includes(fault);
      if (lateBackend) {
        assert.ok(terminals(f).length <= 1, `${stage}/${fault}`);
        for (const call of terminals(f)) assert.deepEqual(
          [call.body.endpoint_id, call.body.scope_generation, call.body.generation, call.body.delivery_id, call.body.native_input_id],
          [endpointID, 0, 1, deliveryID, nativeID], "late server changes reject the old fence, never retarget it");
      } else assert.equal(terminals(f).length, 0, `${stage}/${fault}`);
      assert.equal(f.native.prompt.length, 0);
    } finally { gate.release(); await f.close(); }
  }
  for (const writer of ["poll", "enroll"]) for (const flag of ["admitted", "terminal"]) {
    const original = snapshot({ admitted: true, terminal: flag === "terminal" });
    let regress = false;
    const f = await callerFixture({ wake: original, wait: async (history) => history.push(freshIdle()),
      response: async (route) => route === "/relay/opencode/wake"
        ? { session: relaySession, wake: regress ? { ...original, [flag]: false } : original } : undefined });
    try {
      regress = true;
      const boundary = f.trace.length;
      if (writer === "enroll") await f.emit({ type: "session.created", data: { sessionID } });
      await f.tick(); await f.tick();
      assert.equal(f.native.prompt.length, 0, `${writer}/${flag}: regressed same-G snapshot cannot authorize replay`);
      assert.equal(terminals(f).length, 0, `${writer}/${flag}: no terminal from rejected response`);
      assert.ok(!f.trace.slice(boundary).includes("raw"), `${writer}/${flag}: rejected snapshot cannot launch a legacy wake flight`);
      if (flag === "admitted") {
        regress = false; // Server repair alone is not a cache observation before hook entry.
        await observePrompt(f); f.history.push(freshUser()); await f.tick();
        assert.equal(terminals(f).length, 1, `${writer}: rejection retained the known admitted snapshot, not the regressed flag`);
      }
    } finally { await f.close(); }
  }
  for (const writer of ["poll", "enroll"]) for (const fault of ["runtime", "session", "container", "endpoint", "scope", "state", "health",
    "missing-wake", "invalid-wake", "zero-generation", "lower-generation", "same-input-new-generation", "same-generation-delivery", "same-generation-input", "wake-scope", "wake-location", "invalid-admitted", "invalid-terminal"]) {
    const original = snapshot({ admitted: true, generation: 2 }); let invalid = false;
    const f = await callerFixture({ wake: original, response: async (route) => {
      if (route !== "/relay/opencode/wake" || !invalid) return;
      const session = { ...relaySession }, wake = { ...original }, response = { session, wake };
      if (fault === "runtime") session.runtime = "codex";
      if (fault === "session") session.session_ref = "ses_other";
      if (fault === "container") session.container_ref = "other";
      if (fault === "endpoint") session.endpoint_id += "f";
      if (fault === "scope") session.scope_generation++;
      if (fault === "state") session.state = "closed";
      if (fault === "health") session.destination_health = "inactive";
      if (fault === "missing-wake") delete response.wake;
      if (fault === "invalid-wake") response.wake = {};
      if (fault === "zero-generation") wake.generation = 0;
      if (fault === "lower-generation") wake.generation--;
      if (fault === "same-input-new-generation") wake.generation++;
      if (fault === "same-generation-delivery") wake.delivery_id = "relay-delivery-" + "d".repeat(32);
      if (fault === "same-generation-input") wake.native_input_id = "msg_conflicting";
      if (fault === "wake-scope") wake.scope_generation++;
      if (fault === "wake-location") wake.native_location += "/other";
      if (fault === "invalid-admitted") wake.admitted = "true";
      if (fault === "invalid-terminal") wake.terminal = 0;
      return response;
    } });
    try {
      invalid = true;
      const boundary = f.trace.length;
      if (writer === "enroll") await f.emit({ type: "session.created", data: { sessionID } });
      await f.tick();
      assert.ok(!f.trace.slice(boundary).includes("raw"), `${writer}/${fault}: invalid response cannot launch a flight`);
      assert.equal(terminals(f).length, 0, `${writer}/${fault}`);
      assert.equal(f.native.prompt.length, 0, `${writer}/${fault}`);
    } finally { await f.close(); }
  }
  for (const writer of ["poll", "enroll"]) for (const stale of ["older", "empty", "released", "foreign-higher"]) {
    const gate = barrier(), original = snapshot({ admitted: true });
    const newer = snapshot({ admitted: true, generation: 2, native_input_id: "msg_retry_generation" });
    let backend = original, hold = false;
    const f = await callerFixture({ wake: original, wait: async (history) => history.push(freshIdle()),
      response: async (route, body) => {
        if (route !== "/relay/opencode/wake") return;
        if (hold && body.operation === writer) {
          hold = false;
          const captured = stale === "empty" ? null : { ...backend };
          await gate.wait();
          return { session: stale === "foreign-higher" ? { ...relaySession, scope_generation: 1, endpoint_id: endpointID + "f" } : relaySession, wake: captured };
        }
        return { session: relaySession, wake: backend };
      } });
    try {
      hold = true;
      if (writer === "poll") await f.tick();
      else await f.emit({ type: "session.created", data: { sessionID } });
      await gate.entered;
      backend = stale === "released" ? null : newer;
      if (writer === "poll") await f.emit({ type: "session.created", data: { sessionID } });
      else await f.tick();
      // First-observe U only AFTER the other writer has accepted newer G/null.
      await observePrompt(f); f.history.push(freshUser());
      gate.release(); await pause();
      if (stale === "released") {
        await assert.doesNotReject(() => f.hooks.context({ sessionID, messages: [projectedWake()] }),
          `${writer}: delayed pre-release response cannot restore internal-context authority`);
        assert.equal(f.calls.filter((c) => c.body.operation === "context").length, 0, `${writer}: released anchor remains absent`);
      }
      await f.tick();
      assert.equal(terminals(f).length, stale === "released" ? 0 : 1, `${writer}/${stale}: stale reply cannot erase newer candidate or restore old anchor`);
      if (stale !== "released") {
        assert.equal(terminals(f)[0].body.generation, 2);
        assert.equal(terminals(f)[0].body.native_input_id, newer.native_input_id);
        assert.equal(terminals(f)[0].body.scope_generation, 0, "stale higher registration cannot rebind the newer candidate");
      }
      assert.equal(f.native.prompt.length, 0, `${writer}/${stale}: no old native replay`);
    } finally { gate.release(); await f.close(); }
  }
  for (const generation of [1, 2]) {
    const gate = barrier(); let backend = null, hold = false;
    const wakeFor = (value) => snapshot({ generation: value, native_input_id: "msg_aba_" + value,
      delivery_id: "relay-delivery-" + String(value).repeat(32) });
    const f = await callerFixture({
      wait: async (history) => history.push({ ...freshIdle(), id: "msg_aba_terminal_" + backend.generation }),
      response: async (route, body) => {
        if (route !== "/relay/opencode/wake") return;
        if (body.operation === "enroll" && hold) {
          hold = false;
          const captured = { ...backend };
          await gate.wait();
          return { session: relaySession, wake: captured };
        }
        if (body.operation === "admitted") backend = { ...backend, admitted: true };
        if (body.operation === "terminal") backend = { ...backend, terminal: true };
        if (body.operation === "poll" && backend?.terminal) backend = null;
        return { session: relaySession, wake: backend };
      } });
    const counts = () => [f.native.prompt.length,
      f.calls.filter((c) => c.body.operation === "admitted").length, terminals(f).length];
    try {
      if (generation === 2) {
        backend = wakeFor(1);
        await f.tick();
        assert.equal(backend.terminal, true, "warmup generation completed through normal prompt/admission/terminal");
        await f.tick();
        assert.equal(backend, null, "normal poll returned null release before the newer generation");
      }
      backend = wakeFor(generation);
      const staleWake = { ...projectedWake(), id: backend.native_input_id,
        metadata: { pallium_relay_wake: true, generation, delivery_id: backend.delivery_id } };
      hold = true;
      await f.emit({ type: "session.created", data: { sessionID } });
      await gate.entered; // Enroll captured LOCAL null, but its backend G body is held.
      await f.tick();
      assert.equal(backend.admitted, true, "intervening normal poll drove genuine admission");
      assert.equal(backend.terminal, true, "intervening normal poll drove genuine terminal");
      assert.deepEqual(counts(), [generation, generation, generation]);
      await f.tick();
      assert.equal(backend, null, "normal poll returned null release, completing null -> G -> null");
      const retiredCounts = counts();
      gate.release(); await pause();
      // No repair poll is allowed between the delayed body and this readback.
      await assert.doesNotReject(() => f.hooks.context({ sessionID, messages: [staleWake] }),
        `null ABA generation ${generation}: retired input cannot regain internal-context authority`);
      assert.equal(f.calls.filter((c) => c.body.operation === "context").length, 0, "no stale internal context request before repair poll");
      assert.deepEqual(counts(), retiredCounts, "no new native prompt, admission or terminal from the old response");
      backend = wakeFor(generation + 1);
      await f.tick();
      assert.equal(f.native.prompt.at(-1).id, backend.native_input_id, "current new generation still progresses after ABA rejection");
      assert.deepEqual(counts(), [generation + 1, generation + 1, generation + 1]);
      await f.tick();
      assert.equal(backend, null, "current null release remains accepted");
    } finally { gate.release(); await f.close(); }
  }
  for (const writer of ["poll", "enroll"]) {
    const oldWait = barrier(), newWait = barrier(), original = snapshot({ admitted: true });
    let regress = false, waits = 0;
    const projected = projectedWake();
    const f = await callerFixture({ wake: original,
      history: [{ type: "user", id: nativeID, text: projected.content[0].text, metadata: projected.metadata }],
      response: async (route) => route === "/relay/opencode/wake"
        ? { session: relaySession, wake: regress ? { ...original, admitted: false } : original } : undefined,
      wait: async (history) => {
        if (++waits === 1) await oldWait.wait();
        else { await newWait.wait(); history.push(freshIdle()); }
      } });
    try {
      await f.tick(); await oldWait.entered;
      regress = true;
      if (writer === "enroll") await f.emit({ type: "session.created", data: { sessionID } });
      else await f.tick();
      regress = false;
      await f.tick(); await newWait.entered;
      oldWait.release(); await pause();
      assert.equal(terminals(f).length, 0, `${writer}: cancelled old flight cannot finish after valid replacement starts`);
      await f.tick();
      assert.equal(waits, 2, `${writer}: old finally cannot clear replacement flight's busy reservation`);
      newWait.release(); await pause();
      assert.equal(terminals(f).length, 1, `${writer}: replacement flight can finish normally`);
      assert.equal(f.native.prompt.length, 0);
    } finally { oldWait.release(); newWait.release(); await f.close(); }
  }
  for (const writer of ["poll", "enroll"]) for (const bodyKind of ["null", "old-wake", "new-wake", "malformed"]) {
    const turnGate = barrier(), captureGate = barrier(), scopeGate = barrier(), original = snapshot({ admitted: true });
    const nextScope = ["new-wake", "malformed"].includes(bodyKind) ? 3 : 1;
    const replacement = { ...relaySession, scope_generation: nextScope };
    const carried = bodyKind === "null" ? null : bodyKind === "old-wake" ? original : bodyKind === "malformed" ? {}
      : snapshot({ scope_generation: nextScope, generation: 2, native_input_id: "msg_scope_reply" });
    let registration = relaySession, backendWake = original, replace = false, registered = true;
    let holdTurn = false, deliver = false, turns = 0, captures = 0;
    const f = await callerFixture({ history: [sourceUser("msg_scope_source"), completedAssistant(), freshIdle()],
      fetch: async (route, body) => {
        if (route === "/relay/sessions") return jsonResponse([registration]);
        if (route === "/items") {
          const first = ++captures === 1;
          return { ok: true, text: async () => { if (first) await captureGate.wait(); return JSON.stringify(captureReceipt); } };
        }
        if (route === "/relay/opencode/wake" && body.operation === "poll" && body.scope_generation === nextScope && !registered)
          return { ok: false, status: 409, text: async () => JSON.stringify({ detail: "OpenCode registration is missing or stale" }), body: { cancel: async () => {} } };
      },
      response: async (route, body) => {
        if (route === "/relay/turn") {
          turns++;
          const current = registration, batch = deliver ? [delivery] : [];
          if (holdTurn) { holdTurn = false; await turnGate.wait(); }
          return { session: current, deliveries: batch };
        }
        if (route === "/relay/deliveries/ack") return { delivery_id: body.delivery_id, state: "delivered", already_delivered: false };
        if (route !== "/relay/opencode/wake") return;
        if (replace && body.operation === writer) {
          replace = false;
          await scopeGate.wait();
          registration = replacement; backendWake = null; registered = false;
          return { session: replacement, wake: carried };
        }
        if (body.operation === "enroll" && body.scope_generation === nextScope) registered = true;
        if (body.operation === "admitted") backendWake = { ...backendWake, admitted: true };
        if (body.operation === "terminal") backendWake = { ...backendWake, terminal: true };
        if (body.operation === "poll" && backendWake?.terminal) backendWake = null;
        return { session: registration, wake: backendWake };
      }, wait: async (history) => history.push({ type: "idle", id: "msg_scope_terminal", outcome: "succeeded" }) });
    const oldCapture = f.hooks.compaction({ sessionID });
    let running;
    try {
      await captureGate.entered;
      const captureCall = f.calls.filter((c) => c.path === "/items").at(-1);
      const user = natural("msg_scope_context"), before = structuredClone(user), initialTurns = turns;
      deliver = true; holdTurn = true;
      running = f.hooks.context({ sessionID, messages: [user] });
      await turnGate.entered;
      const turnCall = f.calls.filter((c) => c.path === "/relay/turn").at(-1);
      replace = true;
      if (writer === "poll") await f.tick();
      else await f.emit({ type: "session.created", data: { sessionID } });
      await scopeGate.entered;
      backendWake = ["null", "new-wake"].includes(bodyKind) ? null : original;
      if (writer === "poll") await f.emit({ type: "session.created", data: { sessionID } });
      else await f.tick();
      assert.equal(turnCall.signal.aborted, false, "same-binding wake/null cache advancement is not a registration reset");
      assert.equal(captureCall.signal.aborted, false);
      scopeGate.release(); await pause();
      assert.equal(turnCall.signal.aborted, true, `${writer}/${bodyKind}: positive replacement retires old ordinary transport`);
      assert.equal(captureCall.signal.aborted, true, `${writer}/${bodyKind}: positive replacement retires old capture transport`);
      for (const wake of [original, carried].filter((w) => w?.native_input_id)) {
        const input = { ...projectedWake(), id: wake.native_input_id,
          metadata: { pallium_relay_wake: true, generation: wake.generation, delivery_id: wake.delivery_id } };
        await assert.doesNotReject(() => f.hooks.context({ sessionID, messages: [input] }));
      }
      assert.equal(f.calls.filter((c) => c.body.operation === "context").length, 0, "replacement invalidates registration without accepting ANY carried wake body");
      assert.equal(f.native.prompt.length, 0); assert.equal(terminals(f).length, 0);
      assert.equal(f.calls.filter((c) => c.path === "/relay/deliveries/ack").length, 0);
      await f.tick(); // New binding receives exact missing-registration409 and enrolls itself.
      assert.equal(f.calls.filter((c) => c.body.operation === "poll").at(-1).body.scope_generation, nextScope);
      assert.ok(f.calls.some((c) => c.body.operation === "enroll" && c.body.scope_generation === nextScope));
      await f.hooks.compaction({ sessionID }); // Old capture reservation/cache cannot suppress current capture.
      assert.equal(captures, 2);
      await f.hooks.context({ sessionID, messages: [structuredClone(before)] }); // Same user ID needs a NEW claim after replacement.
      assert.equal(turns, initialTurns + 2);
      assert.equal(f.calls.filter((c) => c.path === "/relay/deliveries/ack").length, 1);
      turnGate.release(); captureGate.release(); await Promise.all([running, oldCapture]);
      assert.deepEqual(user, before, "old context cannot revive after newer claim commits");
      await f.hooks.context({ sessionID, messages: [structuredClone(before)] });
      await f.hooks.compaction({ sessionID });
      assert.equal(turns, initialTurns + 2, "old response cannot erase successor claim cache");
      assert.equal(captures, 2, "old capture finally/receipt cannot erase or complete successor capture state");
      assert.equal(f.calls.filter((c) => c.path === "/relay/deliveries/ack").length, 1);
      const queries = f.calls.filter((c) => c.path === "/item-and-query").length;
      await f.hooks.prompt({ sessionID, messageID: "msg_scope_source", prompt: { text: "question" } });
      assert.equal(f.calls.filter((c) => c.path === "/item-and-query").length, queries, "reset preserves seen first-observation identity");
      assert.equal(turns, initialTurns + 2, "reset retains immutable source/role identity without a new claim");
      backendWake = snapshot({ scope_generation: nextScope, generation: 4, native_input_id: "msg_scope_recovered" });
      await f.tick();
      assert.deepEqual(f.native.prompt.map((p) => p.id), ["msg_scope_recovered"], "only a FRESH new-scope snapshot may start a new wake");
      assert.equal(terminals(f).length, 1); assert.equal(terminals(f)[0].body.scope_generation, nextScope);
      assert.equal(f.calls.filter((c) => c.body.operation === "admitted").length, 1);
      await f.tick(); assert.equal(backendWake, null, "new-scope terminal release remains usable");
    } finally { scopeGate.release(); turnGate.release(); captureGate.release(); await running; await oldCapture; await f.close(); }
  }
  for (const writer of ["poll", "enroll"]) for (const fault of ["lower", "negative", "fraction", "string", "missing", "runtime", "session", "container", "endpoint", "state", "health"]) {
    const gate = barrier(); let registration = relaySession, advance = false, invalid = false, hold = false;
    const current = { ...relaySession, scope_generation: 1 }, bad = { ...relaySession, scope_generation: 2 };
    if (fault === "lower") bad.scope_generation = 0;
    if (fault === "negative") bad.scope_generation = -1;
    if (fault === "fraction") bad.scope_generation = 1.5;
    if (fault === "string") bad.scope_generation = "2";
    if (fault === "missing") delete bad.scope_generation;
    if (fault === "runtime") bad.runtime = "codex";
    if (fault === "session") bad.session_ref = "ses_other";
    if (fault === "container") bad.container_ref = "other";
    if (fault === "endpoint") bad.endpoint_id += "f";
    if (fault === "state") bad.state = "closed";
    if (fault === "health") bad.destination_health = "inactive";
    const f = await callerFixture({ fetch: async (route) => route === "/relay/sessions" ? jsonResponse([registration]) : undefined,
      response: async (route, body) => {
        if (route === "/relay/turn") { const session = registration; if (hold) { hold = false; await gate.wait(); } return { session, deliveries: [delivery] }; }
        if (route === "/relay/deliveries/ack") return { delivery_id: body.delivery_id, state: "delivered", already_delivered: false };
        if (route !== "/relay/opencode/wake") return;
        if (advance && body.operation === "poll") { advance = false; registration = current; }
        if (invalid && body.operation === writer) { invalid = false; return { session: bad, wake: null }; }
        return { session: registration, wake: null };
      } });
    let running;
    try {
      advance = true; await f.tick();
      hold = true;
      const user = natural("msg_scope_reject"), before = structuredClone(user);
      running = f.hooks.context({ sessionID, messages: [user] }); await gate.entered;
      const call = f.calls.filter((c) => c.path === "/relay/turn").at(-1);
      invalid = true;
      if (writer === "poll") await f.tick(); else await f.emit({ type: "session.created", data: { sessionID } });
      assert.equal(call.signal.aborted, false, `${writer}/${fault}: invalid/lower/foreign registration cannot reset the current lifetime`);
      gate.release(); await running;
      assert.notDeepEqual(user, before, `${writer}/${fault}: valid current claim remains usable`);
      assert.equal(f.calls.filter((c) => c.path === "/relay/deliveries/ack").length, 1);
      await f.tick();
      assert.equal(f.calls.filter((c) => c.body.operation === "poll").at(-1).body.scope_generation, 1, `${writer}/${fault}: no binding downgrade`);
      assert.equal(f.native.prompt.length, 0); assert.equal(terminals(f).length, 0);
    } finally { gate.release(); await running; await f.close(); }
  }
  for (const writer of ["poll", "enroll"]) for (const fault of ["lower", "foreign", "malformed"]) {
    const responseGate = barrier(), waitGate = barrier(); let hold = false;
    const session = { ...relaySession, scope_generation: 1 }, wake = snapshot({ admitted: true, scope_generation: 1 });
    const bad = fault === "lower" ? { ...session, scope_generation: 0 } : fault === "foreign"
      ? { ...session, scope_generation: 2, endpoint_id: endpointID + "f" } : { ...session, scope_generation: 1.5 };
    const f = await callerFixture({ fetch: async (route) => route === "/relay/sessions" ? jsonResponse([session]) : undefined,
      response: async (route, body) => {
        if (route === "/relay/turn") return { session, deliveries: [] };
        if (route !== "/relay/opencode/wake") return;
        if (hold && body.operation === writer) { hold = false; await responseGate.wait(); return { session: bad, wake }; }
        return { session, wake };
      }, wait: async (history) => { await waitGate.wait(); history.push(freshIdle()); } });
    try {
      await observePrompt(f); f.history.push(freshUser()); await f.tick(); await waitGate.entered;
      hold = true;
      if (writer === "poll") await f.tick(); else await f.emit({ type: "session.created", data: { sessionID } });
      await responseGate.entered;
      if (writer === "poll") await f.emit({ type: "session.created", data: { sessionID } }); else await f.tick();
      // The SAME wake keeps the SAME witness/flight but advances its opaque cache revision.
      responseGate.release(); await pause(); await f.tick();
      assert.equal(f.native.wait, 1, `${writer}/${fault}: stale registration rejection cannot release a still-current flight`);
      assert.equal(terminals(f).length, 0);
      waitGate.release(); await pause();
      assert.equal(terminals(f).length, 1, `${writer}/${fault}: equivalent cache progress protects the existing witness from stale rejection`);
      assert.equal(terminals(f)[0].body.scope_generation, 1);
      assert.equal(f.native.prompt.length, 0);
    } finally { responseGate.release(); waitGate.release(); await f.close(); }
  }
  for (const writer of ["poll", "enroll"]) {
    const responseGate = barrier(), waitGate = barrier(); let hold = false, advance = false;
    let session = { ...relaySession, scope_generation: 1 }, wake = snapshot({ admitted: true, scope_generation: 1 });
    const f = await callerFixture({ fetch: async (route) => route === "/relay/sessions" ? jsonResponse([session]) : undefined,
      response: async (route, body) => {
        if (route === "/relay/turn") return { session, deliveries: [] };
        if (route !== "/relay/opencode/wake") return;
        if (hold && body.operation === writer) {
          hold = false;
          const captured = { session: { ...session, scope_generation: 2 }, wake: { ...wake } };
          await responseGate.wait(); return captured;
        }
        if (advance) {
          advance = false; session = { ...session, scope_generation: 3 };
          wake = snapshot({ admitted: true, scope_generation: 3, generation: 3, native_input_id: "msg_new_scope_generation" });
        }
        return { session, wake };
      }, wait: async (history) => { await waitGate.wait(); history.push(freshIdle()); } });
    try {
      hold = true;
      if (writer === "poll") await f.tick(); else await f.emit({ type: "session.created", data: { sessionID } });
      await responseGate.entered;
      advance = true;
      if (writer === "poll") await f.emit({ type: "session.created", data: { sessionID } }); else await f.tick();
      await f.tick(); // NEW-scope request, not the old higher-registration response, learns the wake.
      await observePrompt(f); f.history.push(freshUser()); await f.tick(); await waitGate.entered;
      responseGate.release(); await pause(); await f.tick();
      assert.equal(f.native.wait, 1, `${writer}: old-signal/base completion cannot clear the successor flight`);
      assert.equal(terminals(f).length, 0);
      waitGate.release(); await pause();
      assert.equal(terminals(f).length, 1, `${writer}: old scope2 response cannot erase new scope3 proof`);
      assert.equal(terminals(f)[0].body.scope_generation, 3);
      assert.equal(terminals(f)[0].body.native_input_id, "msg_new_scope_generation");
      assert.equal(f.native.prompt.length, 0);
    } finally { responseGate.release(); waitGate.release(); await f.close(); }
  }
  const first = snapshot({ admitted: true, terminal: true });
  let backend = first;
  const f = await callerFixture({ wake: first, wait: async (history) => history.push({ ...freshIdle(), id: "msg_terminal_" + backend.generation }),
    response: async (route, body) => {
      if (route !== "/relay/opencode/wake") return;
      if (body.operation === "admitted") backend = { ...backend, admitted: true };
      if (body.operation === "terminal") backend = { ...backend, terminal: true };
      return { session: relaySession, wake: backend };
    } });
  try {
    for (const generation of [2, 3]) {
      backend = snapshot({ generation, native_input_id: "msg_progress_" + generation,
        delivery_id: generation === 2 ? deliveryID : "relay-delivery-" + "c".repeat(32) });
      await f.tick();
      assert.equal(f.native.prompt.at(-1).id, backend.native_input_id, "new generation is eligible even with reset admission/terminal flags");
      assert.equal(terminals(f).at(-1).body.generation, generation);
      await f.tick(); // Learn committed terminal normally; same-generation bits only advance.
      backend = null;
      await f.tick(); // Legitimate terminal release must not be mistaken for a stale null reply.
    }
    assert.deepEqual(f.native.prompt.map((p) => p.id), ["msg_progress_2", "msg_progress_3"], "pending retry/new delivery use NEW native IDs only");
  } finally { await f.close(); }
});

test("fresh supersession consumes uncertain terminal without stale follow-up", async () => {
  for (const failure of ["get", "context", "wait", "terminal-rejected", "terminal-reply-lost", "newer-candidate"]) {
    const firstReply = failure === "newer-candidate" ? barrier() : null;
    let entered = false, committed = false, f, waits = 0;
    f = await callerFixture({ wake: snapshot({ admitted: true }),
      get: async ({ sessionID: id }) => { if (entered && failure === "get") throw new Error("get unavailable"); return { id, location: { directory: location } }; },
      context: async (_input, history) => { if (entered && failure === "context") throw new Error("context unavailable"); return { data: history }; },
      wait: async (history) => { entered = true; if (failure === "wait") throw new Error("wait unavailable"); history.push({ ...freshIdle(), id: "msg_settled_" + ++waits }); },
      response: async (route, body) => {
        if (route !== "/relay/opencode/wake") return;
        if (body.operation === "poll" && committed) return { session: relaySession, wake: snapshot({ admitted: true, terminal: true }) };
        if (body.operation === "terminal") {
          committed = failure === "terminal-reply-lost";
          if (firstReply && terminals(f).length === 1) {
            const user = sourceUser("msg_next_ordinary", "next ordinary work");
            await observePrompt(f, user); f.history.push(user);
            await firstReply.wait();
          }
          return null;
        }
      } });
    try {
      await observePrompt(f); f.history.push(freshUser()); await f.tick();
      if (firstReply) await until(() => f.history.at(-1)?.id === "msg_next_ordinary", "successor prompt reached the fixture");
      const submitted = failure.startsWith("terminal") || failure === "newer-candidate";
      assert.equal(terminals(f).length, submitted ? 1 : 0, failure);
      await f.tick();
      if (firstReply) {
        assert.equal(terminals(f).length, 1, "no successor terminal while the first reply is held");
        firstReply.release();
        const deadline = Date.now() + 5000;
        while (terminals(f).length < 2) {
          assert.ok(Date.now() < deadline, "successor terminal was not submitted");
          await f.tick();
        }
        assert.equal(terminals(f)[1].body.terminal_message_id, "msg_settled_2");
      }
      assert.equal(terminals(f).length, failure === "newer-candidate" ? 2 : submitted ? 1 : 0, failure);
      assert.equal(f.native.prompt.length, 0);
    } finally { firstReply?.release(); await f.close(); }
  }
});

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
    if (route === "/relay/turn") {
      if (generation === 1) rebindCheck = true;
      return { session: { ...relaySession, scope_generation: generation }, deliveries: [] };
    }
    if (route === "/relay/opencode/wake") return { session: { ...relaySession, scope_generation: generation }, wake: null, deliveries: [] };
  } });
  let rebound;
  let first;
  try {
    const seedTurn = f.calls.findLastIndex((call) => call.path === "/relay/turn");
    assert.ok(seedTurn >= 0, "fixture must seed its actual role-source turn");
    await until(() => f.calls.slice(seedTurn + 1).some((call) =>
      call.body.operation === "enroll" && call.body.scope_generation === 0),
      "seed enrollment must finish before arming the generation1 fence");
    first = f.hooks.compaction({ sessionID });
    await captureOwned.entered;
    generation = 1;
    rebound = f.hooks.context({ sessionID, messages: [natural("msg_helper_rebind")] });
    await rebindOwned.entered;
    // The actual generation1 enrollment, not seed startup, owns this fence.
    rebindOwned.release();
    await until(() => f.calls.some((call) => call.body.operation === "enroll" && call.body.scope_generation === 1),
      "wait for the actual successor enrollment before releasing the old capture");
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

async function holdNativeGit(commandArgs, stdout, run) {
  const saved = childProcess.spawn;
  const directory = mkdtempSync(path.join(profile, "held-native-界-"));
  const release = path.join(directory, "release");
  let child, closed, ready = false;
  childProcess.spawn = (command, args, options) => {
    if (ready || child || command !== "git" || args.join(" ") !== commandArgs) return saved(command, args, options);
    child = saved(process.execPath, ["-e", `
      const fs = require("node:fs");
      process.stdout.write(${JSON.stringify(stdout)});
      const timer = setInterval(() => {
        if (fs.existsSync(${JSON.stringify(release)})) { clearInterval(timer); process.exit(0); }
      }, 5);
      setTimeout(()=>process.exit(0),1500).unref();
    `], { ...options, cwd: directory });
    closed = new Promise((resolve) => child.once("close", resolve));
    child.stdout.once("data", () => { ready = true; });
    return child;
  };
  syncBuiltinESMExports();
  try {
    await run({
      started: () => until(() => ready, "production caller must reach the held native Git child"),
      release: () => writeFileSync(release, "release"),
    });
  } finally {
    writeFileSync(release, "release");
    if (child && child.exitCode === null && child.signalCode === null) child.kill();
    await closed;
    childProcess.spawn = saved;
    syncBuiltinESMExports();
    rmSync(directory, { recursive: true, force: true });
  }
}

async function withScopeGit(run) {
  const saved = childProcess.spawn;
  const directory = mkdtempSync(path.join(profile, "scope-git-界-"));
  const children = [];
  let remote = null;
  childProcess.spawn = (command, args, options) => {
    if (command !== "git") return saved(command, args, options);
    const source = args[0] === "remote" && remote !== null
      ? `process.stdout.write(${JSON.stringify(remote)})` : "process.exit(128)";
    const child = saved(process.execPath, ["-e", source], { ...options, cwd: directory });
    children.push({ child, closed: new Promise((resolve) => child.once("close", resolve)) });
    return child;
  };
  syncBuiltinESMExports();
  try { await run((value) => { remote = value; }); }
  finally {
    for (const { child } of children) if (child.exitCode === null && child.signalCode === null) child.kill();
    await Promise.all(children.map(({ closed }) => closed));
    childProcess.spawn = saved;
    syncBuiltinESMExports();
    rmSync(directory, { recursive: true, force: true });
  }
}

test("V2 timer-only scope mismatch re-arms discovery without native callbacks", { timeout: 30000 }, async () => {
  for (const boundary of ["recover", "delete", "dispose", "native-owner"]) {
    await withScopeGit(async (setRemote) => {
      removeSessionPin(sessionID);
      let registration = relaySession, ownedHere = true, deleted = false;
      const f = await callerFixture({
        get: async ({ sessionID: id }) => ({ id, location: { directory: ownedHere ? location : "/tmp/foreign" } }),
        fetch: async (route) => route === "/relay/sessions" ? jsonResponse(deleted ? [] : [registration]) : undefined,
        response: (route) => route === "/relay/opencode/wake" ? { session: registration, wake: null, deliveries: [] } : undefined,
      });
      try {
        await until(() => f.calls.some((c) => c.body.operation === "enroll"), "fallback scope must enroll first");
        assert.equal(getPinnedContainer(sessionID), null, "timer discovery must stay unpinned");
        const lists = f.calls.filter((c) => c.path === "/relay/sessions").length;
        if (boundary === "delete") {
          deleted = true;
          await f.emit({ type: "session.deleted", data: { sessionID } });
          await until(() => f.calls.some((c) => c.path === "/relay/sessions/close"), "delete must finish its own close");
        } else if (boundary === "dispose") await f.dispose();
        else if (boundary === "native-owner") ownedHere = false;
        const recovered = "git:git.example.test/team/recovered";
        registration = { ...relaySession, container_ref: recovered, scope_generation: 1 };
        setRemote("https://git.example.test/Team/Recovered.git");
        await f.tick();
        if (boundary !== "dispose" && boundary !== "delete")
          await until(() => f.calls.some((c) => c.body.operation === "detach"), "old timer binding must retire");
        if (boundary === "recover") {
          const [detach] = f.calls.filter((c) => c.body.operation === "detach");
          assert.equal(detach.body.container_ref, container);
          assert.equal(detach.body.scope_generation, 0);
          await f.tick();
          await until(() => f.calls.some((c) => c.body.operation === "enroll" && c.body.container_ref === recovered),
            "a later timer alone must rediscover the recovered scope");
          await f.tick();
          await until(() => f.calls.some((c) => c.body.operation === "poll" && c.body.container_ref === recovered),
            "the recovered registration must actually poll");
          assert.equal(f.calls.filter((c) => c.path === "/relay/sessions").length, lists + 1);
          const enrolled = f.calls.filter((c) => c.body.operation === "enroll");
          assert.deepEqual(enrolled.map((c) => [c.body.container_ref, c.body.scope_generation]), [[container, 0], [recovered, 1]]);
        } else {
          await f.tick();
          assert.equal(f.calls.filter((c) => c.path === "/relay/sessions").length, lists,
            `${boundary}: ordinary retirement must not start discovery again`);
          assert.equal(f.calls.filter((c) => c.body.operation === "enroll").length, 1);
        }
        assert.equal(f.calls.filter((c) => ["/relay/turn", "/item-and-query", "/relay/deliveries/ack"].includes(c.path)).length, 0);
        assert.deepEqual(f.native, { prompt: [], wait: 0, interrupt: 0 });
        assert.deepEqual(f.history, []);
        assert.equal(getPinnedContainer(sessionID), null);
      } finally { await f.close(); removeSessionPin(sessionID); }
    });
  }
});

test("V2 in-flight discovery cannot consume a scope-mismatch re-arm", { timeout: 30000 }, async () => {
  for (const boundary of ["git", "list", "ownership"]) {
    await withScopeGit(async (setRemote) => {
      removeSessionPin(sessionID);
      const pollGate = barrier(), discoveryGate = barrier();
      let armed = false, pollHeld = false, discoveryHeld = false, listStarted = false;
      let registration = relaySession;
      const f = await callerFixture({ list: [[]],
        get: async ({ sessionID: id }) => {
          if (armed && !pollHeld) { pollHeld = true; await pollGate.wait(); }
          else if (armed && boundary === "ownership" && listStarted && !discoveryHeld) {
            discoveryHeld = true; await discoveryGate.wait();
          }
          return { id, location: { directory: location } };
        },
        fetch: async (route, body) => {
          if (armed && route === "/relay/sessions" && !body.session_ref) {
            listStarted = true;
            if (boundary === "list" && !discoveryHeld) { discoveryHeld = true; await discoveryGate.wait(); }
            return jsonResponse([registration]);
          }
          if (route === "/relay/sessions" && (body.session_ref || registration !== relaySession)) return jsonResponse([registration]);
        },
        response: (route) => route === "/relay/opencode/wake" ? { session: registration, wake: null, deliveries: [] } : undefined,
      });
      try {
        // Restore a real old binding without consuming startup's empty-discovery retry.
        await f.emit({ type: "session.created", data: { sessionID } });
        await until(() => f.calls.some((c) => c.body.operation === "enroll"), "old scope must finish restore");
        const recovered = "git:git.example.test/team/recovered";
        registration = { ...relaySession, container_ref: recovered, scope_generation: 1 };
        setRemote("https://git.example.test/Team/Recovered.git");
        const race = async (gitGate) => {
          armed = true;
          await f.tick();
          if (gitGate) await gitGate.started();
          else await until(() => discoveryHeld, `discovery must reach its ${boundary} boundary`);
          assert.equal(pollHeld, true);
          pollGate.release();
          await until(() => f.calls.some((c) => c.body.operation === "detach"), "concurrent timer poll must retire the mismatched item");
          if (gitGate) gitGate.release();
          discoveryGate.release();
          armed = false;
          // Real repeated timer ticks, not a sleep claiming the old Git child has closed.
          const deadline = Date.now() + 5000;
          while (!f.calls.some((c) => c.body.operation === "enroll" && c.body.container_ref === recovered)) {
            assert.ok(Date.now() < deadline, `stale ${boundary} discovery cannot consume the new re-arm`);
            await f.tick();
          }
          assert.equal(f.calls.filter((c) => c.body.operation === "enroll").length, 2);
          assert.equal(f.calls.filter((c) => c.body.operation === "detach").length, 1);
          await f.tick();
          await until(() => f.calls.some((c) => c.body.operation === "poll" && c.body.container_ref === recovered),
            "only the new scope may resume polling");
          assert.equal(f.calls.filter((c) => ["/relay/turn", "/item-and-query", "/relay/deliveries/ack"].includes(c.path)).length, 0);
          assert.deepEqual(f.native, { prompt: [], wait: 0, interrupt: 0 });
        };
        if (boundary === "git")
          await holdNativeGit("remote get-url origin", "https://git.example.test/Team/Recovered.git", race);
        else await race();
      } finally { pollGate.release(); discoveryGate.release(); await f.close(); removeSessionPin(sessionID); }
    });
  }
});

test("V2 prompt capture reservations retry only unissued original attempts", { timeout: 30000 }, async () => {
  const event = { sessionID, messageID: "msg_reservation_retry", prompt: { text: "ordinary unicode 界 source" } };
  for (const failure of ["scope", "after-git", "actor", "actor-pin", "after-claim", "prewrite-error", "null-write"]) {
    let armed = false, gets = 0, foreign = false;
    const f = await callerFixture({
      get: async ({ sessionID: id }) => {
        const call = armed ? ++gets : 0;
        if (call === ({ scope: 2, "after-git": 3, actor: 4 })[failure] || foreign)
          return { id, location: { directory: "/tmp/foreign" } };
        return { id, location: { get directory() {
          if (call === 4 && failure === "actor-pin")
            queueMicrotask(() => { removeSessionPin(sessionID); pinContainer(sessionID, container); });
          return location;
        } } };
      },
      response: (route) => {
        if (armed && route === "/relay/turn" && failure === "after-claim") foreign = true;
        if (armed && route === "/item-and-query" && failure === "null-write") return null;
      },
    });
    try {
      pinContainer(sessionID, container, undefined, "fixture-actor");
      armed = true;
      const metadata = failure === "prewrite-error"
        ? { get pallium_work_refs() { throw new Error("prewrite metadata failure"); } } : undefined;
      await f.hooks.prompt({ ...event, metadata });
      const writes = () => f.calls.filter((c) => c.path === "/item-and-query");
      assert.equal(writes().length, failure === "null-write" ? 1 : 0, failure);
      armed = false; foreign = false;
      pinContainer(sessionID, container, undefined, "fixture-actor");
      await f.hooks.prompt(event);
      assert.equal(writes().length, failure === "null-write" ? 2 : 1,
        `${failure}: the same native ID must retry an uncommitted capture`);
      const captured = writes().at(-1).body;
      assert.equal(captured.source_id, ocNativeMessageSourceId("user", sessionID, event.messageID));
      assert.equal(captured.source_turn_id, event.messageID);
      assert.equal(captured.content, event.prompt.text);
      assert.equal(captured.container_ref, container);
      assert.equal(captured.actor_ref, "fixture-actor");
      await f.hooks.prompt(event);
      assert.equal(writes().length, failure === "null-write" ? 2 : 1, "successful capture stays deduplicated");
      assert.equal(f.calls.filter((c) => c.path === "/relay/turn").length, 1,
        "retry reuses the immutable claim instead of reserving a new causal turn");
    } finally { await f.close(); removeSessionPin(sessionID); }
  }
  {
    let rejectCapture = true;
    const f = await callerFixture({ response: (route) => route === "/item-and-query" && rejectCapture ? null : undefined });
    try {
      await f.hooks.prompt(event); // retain its immutable input hash after an explicit failed write
      rejectCapture = false;
      await f.hooks.prompt({ ...event, prompt: { text: "different text for the same native ID" } });
      assert.equal(f.calls.filter((c) => c.path === "/item-and-query").length, 1, "role hash mismatch cannot capture");
      await f.hooks.prompt(event);
      assert.equal(f.calls.filter((c) => c.path === "/item-and-query").length, 2,
        "hash rejection must not poison the original input's retry");
      assert.equal(f.calls.filter((c) => c.path === "/relay/turn").length, 1);
    } finally { await f.close(); removeSessionPin(sessionID); }
  }
  for (const lifetime of ["generation", "delete", "dispose", "issued-generation"]) {
    const oldGate = barrier(), newGate = barrier();
    let phase = null, gets = 0, oldEntered = false, newEntered = false;
    let registration = relaySession;
    const f = await callerFixture({
      get: async ({ sessionID: id }) => {
        if (phase && ++gets === 4) {
          if (phase === "old") { oldEntered = true; await oldGate.wait(); }
          else { newEntered = true; await newGate.wait(); }
        }
        return { id, location: { directory: location } };
      },
      fetch: async (route) => route === "/relay/sessions" ? jsonResponse([registration]) : undefined,
      response: async (route) => {
        if (route === "/item-and-query" && lifetime === "issued-generation") {
          oldEntered = true; await oldGate.wait();
          return null; // a retired/uncertain issued write must not be released as unissued
        }
        if (route === "/relay/turn" || route === "/relay/opencode/wake")
          return { session: registration, wake: null, deliveries: [] };
      },
    });
    let old, newer;
    try {
      pinContainer(sessionID, container, undefined, "fixture-actor");
      if (lifetime !== "issued-generation") phase = "old";
      old = f.hooks.prompt(event);
      await until(() => oldEntered, "original attempt must reach its owned boundary");
      phase = null;
      if (lifetime === "dispose") {
        await f.dispose(); oldGate.release(); await old;
        await f.hooks.prompt(event);
        assert.equal(f.calls.filter((c) => c.path === "/item-and-query").length, 0);
        continue;
      }
      if (lifetime === "delete") {
        await f.emit({ type: "session.deleted", data: { sessionID } });
        await until(() => f.calls.some((c) => c.path === "/relay/sessions/close"), "old item must close before recreation");
      }
      registration = { ...relaySession, scope_generation: 1 };
      await f.emit({ type: "session.created", data: { sessionID } });
      await until(() => f.calls.some((c) => c.body.operation === "enroll" && c.body.scope_generation === 1),
        "the successor signal must enroll before retry");
      if (lifetime === "issued-generation") {
        oldGate.release(); await old;
        await f.hooks.prompt(event);
        assert.equal(f.calls.filter((c) => c.path === "/item-and-query").length, 1,
          "retired null response cannot authorize replay of an already issued capture");
        continue;
      }
      phase = "new"; gets = 0;
      newer = f.hooks.prompt(event);
      await until(() => newEntered, "same-ID successor must reserve its own unissued capture");
      oldGate.release(); await old;
      phase = null;
      await f.hooks.prompt(event);
      assert.equal(f.calls.filter((c) => c.path === "/item-and-query").length, 0,
        "old cleanup cannot delete the successor reservation or admit an overlapping duplicate");
      newGate.release(); await newer;
      await f.hooks.prompt(event);
      const writes = f.calls.filter((c) => c.path === "/item-and-query");
      assert.equal(writes.length, 1);
      assert.equal(writes[0].body.source_turn_id, event.messageID);
      assert.equal(writes[0].body.content, event.prompt.text);
    } finally {
      phase = null; oldGate.release(); newGate.release();
      await Promise.allSettled([old, newer]);
      await f.close(); removeSessionPin(sessionID);
    }
  }
});

test("V2 Git waits retain original lifetime, scalar, pin and native owner on every caller", { timeout: 30000 }, async () => {
  for (const entry of ["prompt", "context", "assistant"]) {
    for (const change of ["delete", "dispose", "pin", "generation", "native-owner"]) {
      let ownedHere = true, registration = relaySession;
      const f = await callerFixture({ history: [completedAssistant()], get: async ({ sessionID: id }) =>
        ({ id, location: { directory: ownedHere ? location : "/tmp/foreign" } }),
      fetch: async (route) => route === "/relay/sessions" ? jsonResponse([registration]) : undefined,
      response: (route) => ["/relay/turn", "/relay/opencode/wake"].includes(route)
        ? { session: registration, wake: null, deliveries: [] } : undefined });
      const originalPin = getPinnedContainer(sessionID);
      removeSessionPin(sessionID);
      let pending;
      const user = natural("msg_git_context");
      const before = structuredClone(user);
      const boundary = f.calls.length;
      try {
        await holdNativeGit("remote get-url origin", "https://git.example.test/Old/Repo.git", async (gate) => {
          pending = entry === "prompt"
            ? f.hooks.prompt({ sessionID, messageID: "msg_git_retired_prompt", prompt: { text: "retired source" } })
            : entry === "context" ? f.hooks.context({ sessionID, messages: [user] })
              : f.hooks.compaction({ sessionID });
          await gate.started();
          if (change === "delete") await f.emit({ type: "session.deleted", data: { sessionID } });
          if (change === "dispose") await f.dispose();
          if (change === "pin") pinContainer(sessionID, "git:example.test/replacement", undefined, "replacement actor");
          if (change === "generation") {
            registration = { ...relaySession, scope_generation: 1 };
            await f.emit({ type: "session.created", data: { sessionID } });
            await until(() => f.calls.some((c) => c.body.operation === "enroll" && c.body.scope_generation === 1),
              "new registration must replace the original signal while Git waits");
          }
          if (change === "native-owner") ownedHere = false;
          gate.release();
          await pending;
          const later = f.calls.slice(boundary);
          assert.equal(later.filter((c) => ["/relay/turn", "/item-and-query", "/items",
            "/relay/deliveries/ack"].includes(c.path)).length, 0, `${entry}/${change}: no old publication`);
          assert.deepEqual(user, before, `${entry}/${change}: no old attachment`);
          assert.equal(f.native.prompt.length, 0);
          if (change === "pin") assert.equal(getPinnedContainer(sessionID), "git:example.test/replacement");
          else assert.equal(getPinnedContainer(sessionID), null, `${entry}/${change}: no late fallback pin`);
        });
      } finally {
        await pending;
        await f.close();
        removeSessionPin(sessionID);
        if (originalPin) pinContainer(sessionID, originalPin, undefined, "fixture-actor");
      }
    }
  }
});

test("V2 older Git resolution cannot overwrite concurrent successor scope or capture", { timeout: 10000 }, async () => {
  const f = await callerFixture();
  removeSessionPin(sessionID);
  let old;
  try {
    await holdNativeGit("remote get-url origin", "https://git.example.test/Old/Repo.git", async (gate) => {
      old = f.hooks.prompt({ sessionID, messageID: "msg_git_older", prompt: { text: "older source" } });
      await gate.started();
      await f.hooks.prompt({ sessionID, messageID: "msg_git_newer", prompt: { text: "newer source" } });
      assert.equal(getPinnedContainer(sessionID), container);
      gate.release();
      await old;
      const writes = f.calls.filter((c) => c.path === "/item-and-query");
      assert.deepEqual(writes.map((c) => c.body.source_turn_id), ["msg_git_newer"]);
      assert.ok(writes.every((c) => c.body.container_ref === container));
      assert.equal(getPinnedContainer(sessionID), container);
    });
  } finally { await old; await f.close(); removeSessionPin(sessionID); }
});

test("V2 actor wait cannot pair a newer actor with an older container", { timeout: 10000 }, async () => {
  const previousActor = process.env.PALLIUM_HOOK_ACTOR_REF;
  const P = await import("../.opencode/plugins/pallium-common.mjs");
  try {
    for (const change of ["same-container", "different-container", "remove-after-owned"]) {
      const sameContainer = change !== "different-container";
      let removeActor = false;
      const f = await callerFixture({ get: async ({ sessionID: id }) => ({
        id, location: { get directory() {
          if (removeActor) {
            removeActor = false;
            queueMicrotask(() => { removeSessionPin(sessionID); pinContainer(sessionID, container); });
          }
          return location;
        } },
      }) });
      removeSessionPin(sessionID);
      pinContainer(sessionID, container);
      delete process.env.PALLIUM_HOOK_ACTOR_REF;
      let pending;
      try {
        await holdNativeGit("config user.name", "derived actor", async (gate) => {
          pending = f.hooks.prompt({ sessionID, messageID: "msg_git_actor", prompt: { text: "coherent actor source" } });
          await gate.started();
          const pinned = sameContainer ? container : "git:example.test/replacement";
          if (change === "remove-after-owned") removeActor = true;
          else pinContainer(sessionID, pinned, undefined, "authoritative actor");
          gate.release();
          await pending;
          const writes = f.calls.filter((c) => c.path === "/item-and-query");
          assert.equal(writes.length, change === "same-container" ? 1 : 0);
          if (change === "same-container") {
            assert.equal(writes[0].body.actor_ref, "authoritative actor");
            assert.equal(writes[0].body.container_ref, container);
          }
          assert.equal(getPinnedContainer(sessionID), pinned);
          assert.equal(P.getPinnedActor(sessionID), change === "remove-after-owned" ? null : "authoritative actor");
        });
      } finally {
        await pending; await f.close(); removeSessionPin(sessionID);
        process.env.PALLIUM_HOOK_ACTOR_REF = previousActor || "fixture-actor";
      }
    }
  } finally {
    if (previousActor === undefined) delete process.env.PALLIUM_HOOK_ACTOR_REF;
    else process.env.PALLIUM_HOOK_ACTOR_REF = previousActor;
  }
});

test("V2 restore reuses callback-local Git facts in prompt and context", { timeout: 10000 }, async () => {
  for (const entry of ["prompt", "context"]) {
    const remote = "https://git.example.test/Team/Repo.git";
    const ref = "git:git.example.test/team/repo";
    const registration = { ...relaySession, container_ref: ref };
    let armed = false;
    const f = await callerFixture({ list: [[]], fetch: async (route) =>
      armed && route === "/relay/sessions" ? jsonResponse([registration]) : undefined,
    response: () => ({ session: registration, wake: snapshot(), deliveries: [delivery] }) });
    const saved = childProcess.spawn, calls = [], children = [];
    const directory = mkdtempSync(path.join(profile, "refs-reuse-界-"));
    removeSessionPin(sessionID);
    childProcess.spawn = (command, args, options) => {
      if (command !== "git") return saved(command, args, options);
      calls.push(args);
      const child = saved(process.execPath, ["-e", `process.stdout.write(${JSON.stringify(remote)})`],
        { ...options, cwd: directory });
      children.push(new Promise((resolve) => child.once("close", resolve)));
      return child;
    };
    syncBuiltinESMExports();
    try {
      armed = true;
      const user = projectedWake();
      if (entry === "prompt") await f.hooks.prompt({ sessionID, messageID: user.id,
        metadata: user.metadata, prompt: { text: user.content[0].text } });
      else {
        await f.hooks.context({ sessionID, messages: [user] });
        assert.match(user.content.at(-1).text, /שלום wake payload/);
      }
      assert.deepEqual(calls, [["remote", "get-url", "origin"]], `${entry}: restore must not rediscover the same callback's Git facts`);
      assert.ok(f.calls.some((c) => c.body.operation === "enroll" && c.body.container_ref === ref));
      assert.equal(f.calls.filter((c) => c.path === "/item-and-query").length, 0);
    } finally {
      await Promise.all(children);
      childProcess.spawn = saved;
      syncBuiltinESMExports();
      await f.close();
      removeSessionPin(sessionID);
      rmSync(directory, { recursive: true, force: true });
    }
  }
});

test("V2 checks the original pin after an owned helper returns success", async () => {
  for (const entry of ["prompt", "context", "assistant"]) {
    let change = false;
    const f = await callerFixture({ history: [completedAssistant()], get: async ({ sessionID: id }) => ({
      id, location: { get directory() {
        if (change) {
          change = false;
          queueMicrotask(() => pinContainer(sessionID, "git:example.test/new", undefined, "new actor"));
        }
        return location;
      } },
    }) });
    const boundary = f.calls.length, user = natural("msg_after_owned");
    const before = structuredClone(user);
    try {
      change = true;
      if (entry === "prompt") await f.hooks.prompt({ sessionID, messageID: user.id, prompt: { text: "original owned work" } });
      else if (entry === "context") await f.hooks.context({ sessionID, messages: [user] });
      else await f.hooks.compaction({ sessionID });
      assert.equal(f.calls.slice(boundary).filter((c) =>
        ["/relay/turn", "/item-and-query", "/items", "/relay/deliveries/ack"].includes(c.path)).length, 0);
      assert.deepEqual(user, before);
      assert.equal(getPinnedContainer(sessionID), "git:example.test/new");
    } finally { await f.close(); removeSessionPin(sessionID); }
  }
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
