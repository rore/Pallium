import path from "node:path";
import { createHash, randomUUID } from "node:crypto";
import * as pallium from "./pallium-common.mjs";

const WAKE_TEXT = "[Pallium Relay wake: check the lower-authority Relay context before acting.]";
const POLL_MS = 2500;
const BUDGET = 2300;
const RELAY_NOTICE_RESERVE = 40;
// Use the real renderer with the shortest possible required fields.
const MIN_RELAY_ENVELOPE = pallium.formatRelay([{
  delivery_id: `relay-delivery-${"0".repeat(32)}`, claim_token: "x", message_id: "x",
  sender_runtime: "codex", sender_session_ref: "x", payload: "x", created_at: "x", attempts: 1,
}]).text.length;
const relayRenderBudget = (scopeText) => BUDGET - scopeText.length - 2;
const relayClaimBudget = (renderBudget) => {
  const available = renderBudget - RELAY_NOTICE_RESERVE;
  return available >= MIN_RELAY_ENVELOPE ? available : 1;
};
const MAX_HISTORY = 20000;
const validInput = (id) => typeof id === "string" && id.length <= 512 && /^msg_[A-Za-z0-9_-]+$/.test(id);
const validDelivery = (id) => typeof id === "string" && /^relay-delivery-[0-9a-f]{32}$/.test(id);
const sameLocation = (a, b) => typeof a === "string" && typeof b === "string" &&
  (process.platform === "win32" ? path.resolve(a).toLowerCase() === path.resolve(b).toLowerCase() : path.resolve(a) === path.resolve(b));
const rows = (response) => Array.isArray(response?.data) ? response.data : Array.isArray(response) ? response : [];
const currentUser = (messages) => [...(messages || [])].reverse().find((m) => m?.role === "user" && validInput(m.id));
const internal = (message) => message?.metadata?.pallium_relay_wake === true && message?.content?.[0]?.text === WAKE_TEXT &&
  validInput(message.id) && validDelivery(message.metadata.delivery_id) && Number.isInteger(message.metadata.generation) && message.metadata.generation >= 1;

// Storage's naive timestamps are UTC. Validate the calendar before applying an
// offset; Date.parse alone accepts normalized invalid dates and local time.
const receiptTimestamp = (value) => {
  const match = typeof value === "string" && /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})?$/.exec(value);
  if (!match || match[0] !== value) return null;
  const [, y, mo, d, h, mi, s, fraction = "", zone = "Z"] = match;
  const parts = [y, mo, d, h, mi, s].map(Number);
  if (+y < 1 || +mo < 1 || +mo > 12 || +d < 1 || +d > 31 || +h > 23 || +mi > 59 || +s > 59) return null;
  const date = new Date(0);
  date.setUTCFullYear(+y, +mo - 1, +d);
  date.setUTCHours(+h, +mi, +s, 0);
  if ([date.getUTCFullYear(), date.getUTCMonth() + 1, date.getUTCDate(), date.getUTCHours(), date.getUTCMinutes(), date.getUTCSeconds()]
    .some((part, index) => part !== parts[index])) return null;
  let offset = 0;
  if (zone !== "Z") {
    if (+zone.slice(1, 3) > 23 || +zone.slice(4) > 59) return null;
    offset = (zone[0] === "+" ? 1 : -1) * (+zone.slice(1, 3) * 60 + +zone.slice(4)) * 60000;
  }
  const micros = Number(fraction.padEnd(6, "0"));
  const base = date.getTime() - offset;
  return { floor: base + Math.floor(micros / 1000), ceil: base + Math.ceil(micros / 1000) };
};

export function relayReceiptTiming(delivery, issuedAt, receivedAt) {
  const claimed = receiptTimestamp(delivery?.claimed_at), lease = receiptTimestamp(delivery?.lease_expires_at);
  const expiry = delivery?.expires_at === null ? { floor: Infinity } : receiptTimestamp(delivery?.expires_at);
  if (!claimed || !lease || !expiry || !Number.isFinite(issuedAt) || !Number.isFinite(receivedAt) || receivedAt < issuedAt) return null;
  const duration = Math.min(lease.floor - claimed.ceil, expiry.floor - claimed.ceil);
  const deadline = issuedAt + duration;
  return duration > 0 && Number.isFinite(deadline) ? { deadline, claimedFloor: claimed.floor, receivedAt } : null;
}

export function relayAckNotBefore(value, at, timing) {
  if (value == null || value === "") return -Infinity;
  const text = typeof value === "string" ? value.replace(/^[ \t]+|[ \t]+$/g, "") : "";
  if (!text) return typeof value === "string" ? -Infinity : null;
  if (!/\D/.test(text)) {
    const seconds = Number(text), candidate = at + seconds * 1000;
    return Number.isSafeInteger(seconds) && seconds * 1000 <= Number.MAX_SAFE_INTEGER &&
      Number.isFinite(candidate) && candidate <= Number.MAX_SAFE_INTEGER ? candidate : null;
  }
  if (!timing || !/^(Mon|Tue|Wed|Thu|Fri|Sat|Sun), \d{2} (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{4} \d{2}:\d{2}:\d{2} GMT$/.test(text)) return null;
  const date = new Date(text);
  return Number.isFinite(date.getTime()) && date.toUTCString() === text
    ? Math.max(at, timing.receivedAt + Math.max(0, date.getTime() - timing.claimedFloor)) : null;
}

export default {
  id: "pallium-v2",
  async setup(ctx) {
    const cwd = ctx.location.directory;
    const ownerId = "opencode-owner-" + randomUUID().replaceAll("-", "");
    const sessions = new Map();
    const assistantChecks = new Map();
    const registrations = [];
    const abort = new AbortController();
    let disposed = false;
    let cleanup;
    let retirement = 0;
    let freshWitnessEnabled = true;
    let discoveryNeeded = true;

    const log = (message) => { try { ctx.app?.log?.({ service: "pallium", level: "warn", message }); } catch {} };
    const state = (id) => {
      if (disposed) return null;
      let item = sessions.get(id);
      if (!item) { item = { busy: false, wakeBusy: false, seen: new Set(), captures: new Set(), completedCaptures: new Set(), lastAssistant: null,
        roleTurns: new Map(), naturalClaims: new Map(), wakeRevision: {}, abort: new AbortController() }; sessions.set(id, item); }
      return item;
    };
    const live = (id, item, signal = item?.abort.signal) => !disposed && item &&
      sessions.get(id) === item && item.abort.signal === signal && !signal.aborted;
    const retire = (id, item) => {
      if (item) item.witness = null;
      item?.abort.abort();
      if (sessions.get(id) === item) {
        sessions.delete(id);
        retirement++;
        const pending = assistantChecks.get(id);
        if (pending) { for (const token of pending) token.valid = false; assistantChecks.delete(id); }
      }
    };
    // A known request binding, not a Git cache. Unpinned async entries refresh
    // it; proof/admission guards must never discover Git or yield.
    const scope = (id) => pallium.getPinnedContainer(id) || sessions.get(id)?.containerRef || null;
    const scopeCurrent = (id, item, signal = item?.abort.signal) => {
      const scalar = item?.containerRef, pin = pallium.getPinnedContainer(id);
      return () => live(id, item, signal) && item.containerRef === scalar && pallium.getPinnedContainer(id) === pin;
    };
    const base = (id, item) => ({
      session_ref: id, container_ref: scope(id), endpoint_id: item.endpointId,
      scope_generation: item.scopeGeneration, native_location: cwd, owner_id: ownerId,
    });
    const wakeRequest = (id, item, operation, extra = {}, onHttpError) => !live(id, item) || !scope(id) || item.endpointId == null ? null :
      pallium.relayRequest("POST", "/relay/opencode/wake", { operation, ...base(id, item), ...extra }, pallium.HTTP_TIMEOUT_MS, item.abort.signal, onHttpError);
    const remember = (id, item, session) => {
      if (!live(id, item) || session?.runtime !== "opencode" || session.session_ref !== id || session.container_ref !== scope(id) ||
          session.state !== "recent" || session.destination_health !== "active" ||
          typeof session.endpoint_id !== "string" || !Number.isInteger(session.scope_generation)) return false;
      if (item.endpointId && (item.endpointId !== session.endpoint_id || item.scopeGeneration !== session.scope_generation)) {
        item.witness = null;
        item.abort.abort();
        item.abort = new AbortController();
        item.captures = new Set();
        item.completedCaptures = new Set();
        item.lastAssistant = null;
        item.busy = false;
        item.wakeBusy = false;
        // Relay claims are generation-scoped; role snapshots remain immutable
        // so delayed assistant output can still bind to its original input.
        item.naturalClaims = new Map();
        item.ackMaintenanceFlight = null;
        item.ackCursor = null;
        item.memory = null;
        item.wake = null;
        item.wakeRevision = {};
      }
      item.endpointId = session.endpoint_id;
      item.scopeGeneration = session.scope_generation;
      return true;
    };
    const owned = async (id, item = sessions.get(id), signal = item?.abort.signal, token) => {
      const started = retirement;
      const current = () => (!token || token.valid) && (item ? live(id, item, signal) : !disposed && (token != null || retirement === started) &&
        (!sessions.has(id) || live(id, sessions.get(id))));
      try {
        if (!current()) return false;
        const witness = item?.witness;
        const session = await ctx.session.get({ sessionID: id });
        if (witness && item.witness === witness && (session?.id !== id || session.revert != null)) item.witness = null;
        return current() && sameLocation(session?.location?.directory, cwd);
      } catch { return false; }
    };
    const detach = async (id, item) => {
      const payload = item?.endpointId && item.containerRef
        ? { operation: "detach", ...base(id, item), container_ref: item.containerRef } : null;
      retire(id, item);
      if (!disposed && payload) await pallium.relayRequest("POST", "/relay/opencode/wake", payload, 500, abort.signal);
    };
    const resolveScope = async (id, item, signal, structural = false) => {
      const current = scopeCurrent(id, item, signal);
      if (!await owned(id, item, signal) || !current()) return null;
      const pinned = pallium.getPinnedContainer(id);
      const refs = structural ? await pallium.deriveGitRefs(cwd, signal) : null;
      if (!current()) return null;
      const container = pinned || refs?.containerRef || await pallium.deriveContainerRef(cwd, signal);
      if (!current() || !await owned(id, item, signal) || !current()) return null;
      if (item.containerRef && item.containerRef !== container) {
        discoveryNeeded = true;
        await detach(id, item); // Never reuse another container's endpoint/generation.
        return null;
      }
      item.containerRef = container;
      return { container, repositoryRef: refs?.repositoryRef, current: scopeCurrent(id, item, signal) };
    };
    const resolveIdentity = async (id, item, signal, structural = false, resolved = null) => {
      const binding = resolved || await resolveScope(id, item, signal, structural);
      if (!binding?.current()) return null;
      const previousActorPin = pallium.getPinnedActor(id);
      const actor = await pallium.resolveActorRef(cwd, id, { signal, current: binding.current });
      if (!binding.current()) return null;
      const actorPin = pallium.getPinnedActor(id);
      if (actorPin ? actorPin !== actor : previousActorPin !== null) return null;
      const current = () => binding.current() && pallium.getPinnedActor(id) === actorPin;
      if (!await owned(id, item, signal) || !current()) return null;
      return { ...binding, actor, current };
    };
    const wakeResponseContext = (id, item) => ({ signal: item.abort.signal, binding: base(id, item),
      revision: item.wakeRevision, witness: item.witness, flight: item.wakeBusy });
    const applyWakeResponse = (id, item, request, response) => {
      if (!live(id, item, request.signal) ||
          !Object.entries(request.binding).every(([key, value]) => base(id, item)[key] === value)) return false;
      const reject = () => {
        if (item.wakeRevision !== request.revision) return false;
        if (item.witness === request.witness) item.witness = null;
        // Cancel this flight, never a newer one started while HTTP was pending.
        if (item.wakeBusy === request.flight) item.wakeBusy = false;
        return false;
      };
      const session = response?.session, wake = response?.wake, known = item.wake;
      if (session?.runtime !== "opencode" || session.session_ref !== id || session.container_ref !== request.binding.container_ref ||
          session.endpoint_id !== request.binding.endpoint_id || !Number.isInteger(session.scope_generation) ||
          session.scope_generation < request.binding.scope_generation ||
          session.state !== "recent" || session.destination_health !== "active") return reject();
      // Cache progress cannot hide a valid registration replacement.
      if (session.scope_generation > request.binding.scope_generation) {
        remember(id, item, session); // Invalidate the old lifetime, never adopt this old request's wake body.
        return false;
      }
      if (item.wakeRevision !== request.revision) return false;
      if (wake !== null) {
        if (!validInput(wake?.native_input_id) || !validDelivery(wake?.delivery_id) || !Number.isInteger(wake?.generation) || wake.generation < 1 ||
            wake.scope_generation !== request.binding.scope_generation || !sameLocation(wake.native_location, request.binding.native_location) ||
            typeof wake.admitted !== "boolean" || typeof wake.terminal !== "boolean") return reject();
        if (known && (wake.generation < known.generation ||
            wake.generation > known.generation && wake.native_input_id === known.native_input_id ||
            wake.generation === known.generation && (wake.delivery_id !== known.delivery_id || wake.native_input_id !== known.native_input_id ||
              known.admitted && !wake.admitted || known.terminal && !wake.terminal))) return reject();
      }
      if (item.witness && !sameWake(item.witness.wake, wake)) item.witness = null;
      item.wake = wake;
      item.wakeRevision = {}; // Null releases also advance freshness; null itself can recur.
      return true;
    };
    const enroll = async (id, item) => {
      const signal = item?.abort.signal;
      const current = scopeCurrent(id, item, signal);
      if (!current() || !scope(id) || !item.endpointId || !await owned(id, item, signal) || !current()) return;
      const request = wakeResponseContext(id, item);
      const response = await wakeRequest(id, item, "enroll");
      if (applyWakeResponse(id, item, request, response)) return response;
    };
    const terminalAfter = (messages, inputId) => {
      const index = messages.findIndex((m) => m?.type === "user" && m.id === inputId);
      if (index < 0) return null;
      const nextUser = messages.findIndex((m, n) => n > index && m?.type === "user");
      const end = nextUser < 0 ? messages.length : nextUser;
      const idle = messages.slice(index + 1, end).find((m) => m?.type === "idle" && validInput(m.id));
      return idle?.id || null;
    };
    const coalescedTerminalAfter = (messages, wake) => {
      const index = messages.findIndex((m) => m?.type === "user" && m.id === wake.native_input_id &&
        m.text === WAKE_TEXT && m.metadata?.pallium_relay_wake === true &&
        m.metadata.generation === wake.generation && m.metadata.delivery_id === wake.delivery_id);
      if (index < 0) return null;
      // Native idle covers the entire busy period, including steered inputs.
      const idle = messages.slice(index + 1).find((m) => m?.type === "idle");
      return validInput(idle?.id) && idle.id !== wake.native_input_id &&
        ["succeeded", "failed", "interrupted"].includes(idle.outcome) ? idle.id : null;
    };
    const sameWake = (a, b) => a && b &&
      ["generation", "delivery_id", "native_input_id", "scope_generation", "admitted", "terminal"].every((key) => a[key] === b[key]) &&
      sameLocation(a.native_location, b.native_location);
    const settleFreshWitness = async (id, item) => {
      const proof = item.witness;
      if (!proof) return;
      const current = () => freshWitnessEnabled && item.witness === proof && live(id, item, proof.signal) &&
        Object.entries(proof.binding).every(([key, value]) => base(id, item)[key] === value) && sameWake(proof.wake, item.wake);
      let notReady = false;
      try {
        const nativeGet = async () => {
          if (!current()) throw new Error("fresh witness binding changed");
          const session = await ctx.session.get({ sessionID: id });
          if (!current() || session?.id !== id || !sameLocation(session?.location?.directory, cwd) || session.revert != null)
            throw new Error("fresh witness native owner changed");
        };
        const raw = async () => {
          if (!current()) throw new Error("fresh witness binding changed");
          const response = await ctx.session.context({ sessionID: id });
          const messages = Array.isArray(response) ? response : response?.data;
          if (!current() || !Array.isArray(messages) || messages.some((m) => !m || typeof m.type !== "string"))
            throw new Error("fresh witness raw context unavailable");
          return messages;
        };
        const userIndex = (messages) => {
          const matches = messages.filter((m) => m.id === proof.inputId);
          if (!matches.length) return -1;
          const user = matches[0], index = messages.indexOf(user);
          if (matches.length !== 1 || user.type !== "user" || typeof user.text !== "string" ||
              user.metadata?.pallium_relay_wake === true || user.text === WAKE_TEXT ||
              createHash("sha256").update(user.text).digest("hex") !== proof.inputHash ||
              messages.slice(index + 1).some((m) => m.type === "user")) throw new Error("fresh witness user changed");
          return index;
        };
        const terminal = (messages) => {
          const index = userIndex(messages);
          const idle = index < 0 ? null : messages.slice(index + 1).find((m) => m.type === "idle");
          if (!validInput(idle?.id) || idle.id === proof.inputId || idle.id === proof.wake.native_input_id ||
              !["succeeded", "failed", "interrupted"].includes(idle.outcome)) throw new Error("fresh witness terminal unavailable");
          return { id: idle.id, outcome: idle.outcome };
        };
        // Certified admitted G predates first observation of U. Neither queued U
        // nor an old context row can create this ephemeral causal relationship.
        await nativeGet();
        const before = await raw();
        if (userIndex(before) < 0) {
          if (proof.promoted) throw new Error("promoted fresh witness disappeared");
          notReady = true; // Same frozen candidate; runWake releases wakeBusy.
          return;
        }
        proof.promoted = true;
        await ctx.session.wait({ sessionID: id });
        await nativeGet();
        const selected = terminal(await raw());
        if (!current()) return;
        const response = await wakeRequest(id, item, "poll");
        const session = response?.session;
        if (!current() || !sameWake(proof.wake, response?.wake) || session?.runtime !== "opencode" ||
            session.session_ref !== id || session.container_ref !== proof.binding.container_ref ||
            session.endpoint_id !== proof.binding.endpoint_id || session.scope_generation !== proof.binding.scope_generation ||
            session.state !== "recent" || session.destination_health !== "active") return;
        await nativeGet();
        const final = terminal(await raw());
        if (!current() || final.id !== selected.id || final.outcome !== selected.outcome) return;
        // No unrelated await after final raw proof/full guard. Backend commit
        // fences backend changes, not an atomic native/backend snapshot.
        item.witness = null;
        await wakeRequest(id, item, "terminal", { generation: proof.wake.generation,
          delivery_id: proof.wake.delivery_id, native_input_id: proof.wake.native_input_id,
          terminal_message_id: selected.id });
      } catch (error) { log(`V2 fresh witness deferred: ${String(error)}`); }
      finally { if (!notReady && item.witness === proof) item.witness = null; }
    };
    const runWake = async (id, item, wake) => {
      const signal = item?.abort.signal;
      if (!live(id, item, signal) || item.wakeBusy || !validInput(wake?.native_input_id) || !validDelivery(wake?.delivery_id) || !Number.isInteger(wake?.generation)) return;
      const fields = { generation: wake.generation, delivery_id: wake.delivery_id, native_input_id: wake.native_input_id };
      const endpointId = item.endpointId, scopeGeneration = item.scopeGeneration, container = scope(id), nativeLocation = wake.native_location;
      const flight = {};
      const current = () => live(id, item, signal) && item.wakeBusy === flight && item.endpointId === endpointId && item.scopeGeneration === scopeGeneration &&
        scope(id) === container && sameWake(item.wake, wake) && item.wake?.scope_generation === scopeGeneration &&
        sameLocation(item.wake?.native_location, nativeLocation) && sameLocation(nativeLocation, cwd);
      item.wakeBusy = flight;
      const witness = item.witness;
      const discardWitness = () => { if (item.witness === witness) item.witness = null; };
      try {
        if (!await owned(id, item, signal) || !current()) { discardWitness(); return; }
        const history = rows(await ctx.session.context({ sessionID: id }));
        if (!await owned(id, item, signal) || !current()) { discardWitness(); return; }
        const observed = (messages) => messages.some((m) => m?.type === "user" && m.id === fields.native_input_id &&
          m.text === WAKE_TEXT && m.metadata?.pallium_relay_wake === true &&
          m.metadata.generation === fields.generation && m.metadata.delivery_id === fields.delivery_id);
        if (!observed(history)) {
          if (wake.admitted) { await settleFreshWitness(id, item); return; } // Never replay a missing admitted input.
          // The stable native ID makes a lost prompt response safe to retry.
          await ctx.session.prompt({ sessionID: id, id: fields.native_input_id, text: WAKE_TEXT, delivery: "queue",
            metadata: { pallium_relay_wake: true, generation: fields.generation, delivery_id: fields.delivery_id } });
        }
        if (!await owned(id, item, signal) || !current()) return;
        if (!observed(rows(await ctx.session.context({ sessionID: id })))) return;
        if (!await owned(id, item, signal) || !current()) return;
        if (wake.admitted !== true) await wakeRequest(id, item, "admitted", fields);
        if (!await owned(id, item, signal) || !current()) return;
        await ctx.session.wait({ sessionID: id });
        if (!await owned(id, item, signal) || !current()) return;
        const after = rows(await ctx.session.context({ sessionID: id }));
        if (!await owned(id, item, signal) || !current()) return;
        const terminalId = terminalAfter(after, fields.native_input_id) || coalescedTerminalAfter(after, fields);
        if (terminalId) await wakeRequest(id, item, "terminal", { ...fields, terminal_message_id: terminalId });
      } catch (error) { discardWitness(); log(`V2 wake deferred: ${String(error)}`); }
      finally { if (live(id, item, signal) && item.wakeBusy === flight) item.wakeBusy = false; }
    };
    const poll = async (id) => {
      const item = sessions.get(id);
      const signal = item?.abort.signal;
      const witness = item?.witness;
      if (!live(id, item, signal) || item.busy || !item.endpointId) return;
      item.busy = true;
      try {
        const initial = scopeCurrent(id, item, signal);
        if (!await owned(id, item, signal)) { if (initial()) await detach(id, item); return; }
        if (!initial()) return;
        const binding = await resolveScope(id, item, signal);
        if (!binding?.current()) return;
        const request = wakeResponseContext(id, item);
        let registrationMissing = false;
        let response = await wakeRequest(id, item, "poll", {}, (status, error) => {
          registrationMissing = status === 409 && error?.detail === "OpenCode registration is missing or stale";
        });
        if (!binding.current()) return;
        // Only an explicit registration conflict warrants another enrollment write.
        let applied = false;
        if (!response && registrationMissing) { response = await enroll(id, item); applied = !!response; }
        if (!await owned(id, item, signal) || !binding.current() || !response) {
          if (item.witness === witness) item.witness = null;
          return;
        }
        if (applied ? item.wake !== response.wake : !applyWakeResponse(id, item, request, response)) return;
        if (response.wake && !response.wake.terminal && sameLocation(response.wake.native_location, cwd))
          void runWake(id, item, response.wake);
      } catch (error) { if (live(id, item, signal)) log(`V2 poll deferred: ${String(error)}`); }
      finally { if (live(id, item, signal)) item.busy = false; }
    };
    const requestNaturalTurn = (id, item, inputId, relayBudget, discovery, claim, roleTurn = null) => {
      if (claim.response) return Promise.resolve(claim.response);
      if (claim.promise) return claim.promise;
      const pending = (async () => {
        const signal = item.abort.signal;
        const current = scopeCurrent(id, item, signal);
        if (!current() || !scope(id)) return null;
        const maxChars = relayClaimBudget(relayBudget);
        claim.issuedAt = performance.now();
        const response = await pallium.relayRequest("POST", "/relay/turn", {
          runtime: "opencode", session_ref: id, container_ref: scope(id), max_chars: maxChars,
          structural_work_refs: discovery.repositoryRef
            ? pallium.structuralWorkRefsPayload(scope(id), discovery.structuralRefs, discovery.repositoryRef) : [],
        }, pallium.HTTP_TIMEOUT_MS, signal);
        claim.receivedAt = performance.now();
        if (!current()) return null;
        if (response?.session) {
          if (!remember(id, item, response.session)) return null;
          if (roleTurn) roleTurn.snapshot = pallium.relayNameSnapshot(response, id, scope(id));
          // remember() clears generation-scoped claims; restore this already
          // validated response for the input that made the exact request.
          if (!item.naturalClaims.has(inputId)) item.naturalClaims.set(inputId, claim);
          void enroll(id, item);
        }
        claim.response = response?.session
          ? (maxChars === 1 ? { ...response, deliveries: [] } : response)
          : null;
        return claim.response;
      })();
      claim.promise = pending;
      const clearPending = () => { if (claim.promise === pending) claim.promise = null; };
      void pending.then(clearPending, clearPending);
      return pending;
    };
    const receiptReady = (entry) => {
      if (entry.state !== "pending") return false;
      if (!entry.current() || entry.disabled || !entry.timing ||
          Math.max(performance.now(), entry.notBefore) + 500 >= entry.timing.deadline) {
        entry.state = "stopped";
        return false;
      }
      return performance.now() >= entry.notBefore;
    };
    const sendReceipt = async (entry, flight) => {
      const current = () => entry.current() && entry.flight === flight && entry.state === "flight";
      if (!current()) return { delivery_id: entry.delivery.delivery_id, success: false };
      const [result] = await pallium.acknowledgeRelay([entry.delivery], entry.container, entry.signal, (_delivery, observation) => {
        if (!current()) return;
        if (observation.phase === "headers") {
          const due = relayAckNotBefore(observation.retryAfter, observation.at, entry.timing);
          if (due === null) entry.disabled = true;
          else entry.notBefore = Math.max(entry.notBefore, due);
        } else {
          entry.notBefore = Math.max(entry.notBefore, observation.at);
          if (observation.success) entry.state = "confirmed";
          else {
            const terminal = observation.status >= 400 && observation.status < 500 &&
              ![408, 429].includes(observation.status) && observation.error?.detail?.code !== "relay_busy";
            entry.state = terminal || entry.disabled ? "stopped" : "pending";
            receiptReady(entry); // Expiry/missing authority is a retained tombstone.
          }
        }
      });
      if (entry.flight === flight) entry.flight = null;
      return result;
    };
    const acknowledgeOrdinary = async (id, item, inputId, claim, deliveries, identity) => {
      claim.receipts ||= new Map();
      // Reserve the entire rendered subset before yielding, including later
      // entries in this legacy sequential initial ACK batch.
      const entries = deliveries.map((delivery) => {
        let entry = claim.receipts.get(delivery.delivery_id);
        if (entry) return { entry };
        const token = delivery.claim_token, attempt = delivery.attempts, signal = item.abort.signal;
        const binding = base(id, item), response = claim.response, flight = {};
        entry = { delivery, container: identity.container, signal, state: "flight", flight,
          timing: relayReceiptTiming(delivery, claim.issuedAt, claim.receivedAt), notBefore: -Infinity, disabled: false };
        entry.current = () => identity.current() && live(id, item, signal) &&
          Object.entries(binding).every(([key, value]) => base(id, item)[key] === value) &&
          item.naturalClaims.get(inputId) === claim && claim.response === response &&
          claim.receipts.get(delivery.delivery_id) === entry && response?.deliveries?.includes(delivery) &&
          delivery.claim_token === token && delivery.attempts === attempt;
        claim.receipts.set(delivery.delivery_id, entry);
        return { entry, flight };
      });
      const results = [];
      for (const { entry, flight } of entries) {
        results.push(flight ? await sendReceipt(entry, flight) :
          { delivery_id: entry.delivery.delivery_id, success: entry.current() && entry.state === "confirmed" });
      }
      return results;
    };
    const maintainReceipts = async (id, item) => {
      if (!live(id, item) || item.ackMaintenanceFlight) return;
      const flight = {}, signal = item.abort.signal;
      item.ackMaintenanceFlight = flight; // BEFORE selection or native ownership.
      const current = () => live(id, item, signal) && item.ackMaintenanceFlight === flight;
      try {
        const entries = [...item.naturalClaims.values()].flatMap((claim) => [...(claim.receipts?.values() || [])]);
        const start = entries.indexOf(item.ackCursor) + 1;
        for (let n = 0; n < entries.length; n++) {
          const entry = entries[(start + n) % entries.length];
          if (!receiptReady(entry)) continue;
          item.ackCursor = entry;
          if (!await owned(id, item, signal) || !current() || !receiptReady(entry)) return;
          const receiptFlight = {};
          // No await between the full-slot/authority recheck and dispatch.
          entry.flight = receiptFlight;
          entry.state = "flight";
          await sendReceipt(entry, receiptFlight);
          return;
        }
      } catch (error) { if (current()) log(`V2 receipt maintenance deferred: ${String(error)}`); }
      finally { if (current()) item.ackMaintenanceFlight = null; }
    };
    const ensureNaturalTurn = (id, item, inputId, promptText, relayBudget, discovery) => {
      const inputHash = createHash("sha256").update(String(promptText || "")).digest("hex");
      const existing = item.naturalClaims.get(inputId);
      if (existing) return existing.inputHash === inputHash ? existing : null;
      const roleTurn = { inputHash, snapshot: { relay_name: null, relay_attribution_state: "unavailable" } };
      const claim = { inputHash, acked: false, response: null, promise: null };
      item.roleTurns.set(inputId, roleTurn);
      item.naturalClaims.set(inputId, claim);
      void requestNaturalTurn(id, item, inputId, relayBudget, discovery, claim, roleTurn);
      return claim;
    };
    const ingestAssistant = async (id) => {
      const token = { valid: true };
      let pending = assistantChecks.get(id);
      if (!pending) assistantChecks.set(id, pending = new Set());
      pending.add(token);
      let item;
      try {
        const original = sessions.get(id);
        const current = original ? scopeCurrent(id, original) : () => !disposed && token.valid;
        if (!await owned(id, original, undefined, token) || !current() || disposed || !token.valid) return;
        item = state(id);
      } finally {
        token.valid = false;
        pending.delete(token);
        if (!pending.size && assistantChecks.get(id) === pending) assistantChecks.delete(id);
      }
      const signal = item?.abort.signal;
      const captures = item?.captures;
      const reserved = [];
      try {
        const initial = scopeCurrent(id, item, signal);
        if (!initial()) return;
        const messages = rows(await ctx.session.context({ sessionID: id }));
        if (!initial() || !await owned(id, item, signal) || !initial()) return;
        const identity = await resolveIdentity(id, item, signal);
        if (!identity?.current()) return;
        const { actor, container, current } = identity;
        let boundary = -1;
        for (let end = 0; end < messages.length; end++) {
          if (messages[end]?.type !== "idle") continue;
          const segment = messages.slice(boundary + 1, end);
          boundary = end;
          const users = segment.filter((message) => message?.type === "user");
          const assistants = segment.filter((message) => message?.type === "assistant");
          if (users.length !== 1 || !validInput(users[0]?.id) || !assistants.length || assistants.some((message) =>
            !validInput(message.id) || !Number.isFinite(message.time?.completed))) continue;
          const roleTurn = item.roleTurns.get(users[0].id);
          if (!roleTurn) continue;
          const segmentTurn = pallium.extractV2AssistantTurn(segment);
          if (!segmentTurn?.assistant_text || segmentTurn.assistant_text.length > MAX_HISTORY) continue;
          for (const assistant of assistants) {
            const sourceId = pallium.ocNativeMessageSourceId("assistant", id, assistant.id);
            if (!sourceId || sourceId === item.lastAssistant || item.completedCaptures.has(sourceId) || captures.has(sourceId)) continue;
            const turn = pallium.extractV2AssistantTurn([assistant]);
            if (!turn?.assistant_text || turn.assistant_text.length > MAX_HISTORY) continue;
            const workTrace = pallium.buildWorkTraceMetadata(segmentTurn);
            const metadata = { ...pallium.buildWorkRefsMetadata(cwd), ...(workTrace ? { agent_work_trace_turn: workTrace, cwd } : {}) };
            captures.add(sourceId);
            reserved.push(sourceId);
            const response = await pallium.palliumRequest("POST", "/items", [{
              source_type: pallium.SOURCE_TYPE, source_id: sourceId, content_type: "text/plain",
              content: turn.assistant_text, role: "assistant", agent_ref: pallium.AGENT_REF,
              container_ref: container, thread_ref: id, actor_ref: actor,
              visibility: "private", artifact_kind: "message", source_turn_id: users[0].id,
              relay_name: roleTurn.snapshot.relay_name,
              relay_attribution_state: roleTurn.snapshot.relay_attribution_state,
              ...(Object.keys(metadata).length ? { metadata } : {}),
            }], signal);
            if (Array.isArray(response) && response.length === 1 && typeof response[0]?.source_item_id === "string" &&
                response[0].source_item_id.trim() && current() && await owned(id, item, signal) && current()) {
              item.completedCaptures.add(sourceId);
              item.lastAssistant = sourceId;
            }
            if (!current()) return;
          }
        }
      } catch (error) { log(`V2 assistant ingest failed: ${String(error)}`); }
      finally { for (const sourceId of reserved) captures.delete(sourceId); }
    };

    registrations.push(await ctx.session.hook("prompt", async (event) => {
      try {
      const id = event?.sessionID;
      if (!id || !validInput(event.messageID) || disposed) return;
      const item = state(id);
      const signal = item.abort.signal;
      // Reserve before any await: delayed enrollment/history retries must never
      // retrofit a prompt first observed without a known promoted generation.
      const ordinary = event.metadata?.pallium_relay_wake !== true && typeof event.prompt?.text === "string" &&
        event.prompt.text !== WAKE_TEXT && pallium.stripIdeContext(event.prompt.text).trim() &&
        !pallium.stripIdeContext(event.prompt.text).startsWith("/");
      if (ordinary) {
        const fresh = !item.roleTurns.has(event.messageID) && !item.naturalClaims.has(event.messageID) && !item.seen.has(event.messageID);
        if (fresh) item.roleTurns.set(event.messageID, null);
        item.witness = null;
        const wake = item.wake;
        if (fresh && freshWitnessEnabled && live(id, item, signal) && item.endpointId && Number.isInteger(item.scopeGeneration) &&
            wake?.admitted === true && wake.terminal === false && validInput(wake.native_input_id) && validDelivery(wake.delivery_id) &&
            Number.isInteger(wake.generation) && wake.generation >= 1 && wake.scope_generation === item.scopeGeneration &&
            sameLocation(wake.native_location, cwd) && wake.native_input_id !== event.messageID)
          item.witness = { signal, binding: Object.freeze(base(id, item)), wake: Object.freeze({ ...wake }),
            inputId: event.messageID, inputHash: createHash("sha256").update(event.prompt.text).digest("hex"), promoted: false };
      }
      const firstWitness = item.witness;
      const initial = scopeCurrent(id, item, signal);
      if (!await owned(id, item, signal) || !initial()) {
        if (item.witness === firstWitness) item.witness = null;
        return;
      }
      let resolved = null;
      if (event.metadata?.pallium_relay_wake === true && event.prompt?.text === WAKE_TEXT) {
        if (!item.endpointId) {
          resolved = await resolveScope(id, item, signal, true);
          if (!resolved?.current()) return;
          await restore(id, resolved);
        }
        if (resolved ? !resolved.current() : !initial()) return;
        if (item.wake?.native_input_id === event.messageID && item.wake.generation === event.metadata.generation &&
            item.wake.delivery_id === event.metadata.delivery_id) return;
      }
      const content = pallium.stripIdeContext(event.prompt?.text || "");
      const captures = item.captures;
      if (!content || content.startsWith("/") || item.seen.has(event.messageID) || captures.has(event.messageID)) return;
      captures.add(event.messageID);
      try {
      const identity = await resolveIdentity(id, item, signal, true, resolved);
      if (!identity?.current()) return;
      const { actor, container, repositoryRef } = identity;
      pallium.pinContainer(id, container, undefined, actor);
      if (pallium.getPinnedContainer(id) && pallium.getPinnedContainer(id) !== container ||
          pallium.getPinnedActor(id) && pallium.getPinnedActor(id) !== actor) return;
      const bound = scopeCurrent(id, item, signal);
      const actorPin = pallium.getPinnedActor(id);
      const current = () => bound() && pallium.getPinnedActor(id) === actorPin;
      const discovery = { ...pallium.discoverWorkRefs(cwd), repositoryRef };
      const scopeText = pallium.formatInjection([], container, BUDGET, id, actor, pallium.AGENT_REF, "private", null,
        pallium.injectedWorkRef(discovery));
      const claim = event.metadata?.pallium_relay_wake === true ? null :
        ensureNaturalTurn(id, item, event.messageID, content, relayRenderBudget(scopeText), discovery);
      if (claim) await claim.promise;
      if (!current() || !await owned(id, item, signal) || !current()) return;
      const roleTurn = item.roleTurns.get(event.messageID);
      if (roleTurn?.inputHash !== createHash("sha256").update(content).digest("hex")) return;
      const roleSnapshot = roleTurn?.snapshot || { relay_name: null, relay_attribution_state: "unavailable" };
      const request = {
        source_type: pallium.SOURCE_TYPE, source_id: pallium.ocNativeMessageSourceId("user", id, event.messageID), content_type: "text/plain",
        content, role: "user", agent_ref: pallium.AGENT_REF, container_ref: container,
        thread_ref: id, actor_ref: actor, visibility: "private", artifact_kind: "message",
        source_turn_id: roleTurn ? event.messageID : undefined,
        relay_name: roleSnapshot.relay_name, relay_attribution_state: roleSnapshot.relay_attribution_state,
        query_text: content.slice(0, 500), query_limit: 5, query_actor_ref: actor,
        query_trigger_origin: "user_prompt_submit", metadata: pallium.buildWorkRefsMetadata(cwd, event.metadata?.pallium_work_refs, discovery),
      };
      item.seen.add(event.messageID); // Issued writes retain existing uncertain-response semantics.
      const response = await pallium.palliumRequest("POST", "/item-and-query", request, signal);
      if (!current() || !await owned(id, item, signal) || !current()) return;
      if (!response) item.seen.delete(event.messageID);
      const text = pallium.formatInjection(response?.injectable_blocks || [], container, BUDGET, id, actor, pallium.AGENT_REF, "private", response?.source_item_id);
      if (text) item.memory = { inputId: event.messageID, text };
      } finally { captures.delete(event.messageID); } // Only this attempt's original Set, never a successor's.
      } catch (error) { log(`V2 user ingest failed: ${String(error)}`); }
    }));

    registrations.push(await ctx.session.hook("context", async (event) => {
      let wake = false;
      try {
      if (disposed || !event?.sessionID || !Array.isArray(event.messages)) return;
      const id = event.sessionID;
      const user = currentUser(event.messages);
      if (!user) return;
      const item = state(id);
      const signal = item.abort.signal;
      const reservedWake = () => internal(user) && item.wake?.native_input_id === user.id &&
        item.wake.generation === user.metadata.generation && item.wake.delivery_id === user.metadata.delivery_id &&
        sameLocation(item.wake.native_location, cwd);
      wake = reservedWake();
      const initial = scopeCurrent(id, item, signal);
      if (!await owned(id, item, signal) || !initial()) {
        if (wake && !live(id, item, signal)) throw new Error("Pallium internal wake owner retired");
        return;
      }
      const identity = await resolveIdentity(id, item, signal, true);
      if (!identity?.current()) {
        if (wake) throw new Error("Pallium internal wake scope retired");
        return;
      }
      const { actor, container, repositoryRef, current } = identity;
      const discovery = { ...pallium.discoverWorkRefs(cwd), repositoryRef };
      const scopeText = pallium.formatInjection([], container, BUDGET, id,
        actor, pallium.AGENT_REF, "private", null, pallium.injectedWorkRef(discovery));
      const relayBudget = relayRenderBudget(scopeText);
      const maxChars = relayClaimBudget(relayBudget);
      if (internal(user) && !item.endpointId) await restore(id, identity);
      if (!current()) {
        if (wake) throw new Error("Pallium internal wake owner retired");
        return;
      }
      wake = reservedWake();
      let response;
      if (wake) {
        if (maxChars === 1) throw new Error("Pallium internal wake has no Relay output budget");
        response = await wakeRequest(id, item, "context", {
          generation: user.metadata.generation, delivery_id: user.metadata.delivery_id,
          native_input_id: user.id, max_chars: maxChars, max_messages: 3,
        });
        if (response?.deliveries?.[0]?.delivery_id !== user.metadata.delivery_id)
          throw new Error("Pallium internal wake has no current Relay work");
      } else if (!internal(user)) {
        // The prompt hook freezes the role snapshot at source time and owns the
        // first Relay turn claim. Context may recover deliveries later, but
        // never writes that later identity into an existing role snapshot.
        let claim = item.naturalClaims.get(user.id);
        if (!claim) {
          claim = { inputHash: null, acked: false, response: null, promise: null };
          item.naturalClaims.set(user.id, claim);
        }
        response = await requestNaturalTurn(id, item, user.id, relayBudget, discovery, claim);
      }
      // Unproven marker inputs remain fail-open but cannot register or claim.
      // This also fences an overtaken real wake without treating a forged marker
      // as authority to abort somebody's ordinary work.
      if (!current() || !await owned(id, item, signal) || !current()) {
        if (wake) throw new Error("Pallium internal wake owner retired");
        return;
      }
      const deliveries = response?.deliveries || [];
      const claim = item.naturalClaims.get(user.id);
      const continuation = response?.restored || (!wake && claim?.acked);
      let rendered = { text: "", deliveries: [] };
      if (!continuation && maxChars !== 1) {
        const eligible = response?.has_more === true && Number.isInteger(response.remaining_count)
          ? Math.max(0, response.remaining_count) : 0;
        rendered = pallium.formatRelay(deliveries, relayBudget, eligible);
        let omitted = 0;
        while (omitted < deliveries.length - rendered.deliveries.length) {
          omitted = deliveries.length - rendered.deliveries.length;
          rendered = pallium.formatRelay(deliveries, relayBudget, eligible + omitted);
        }
      }
      const formatted = continuation && maxChars !== 1
        ? pallium.formatRelayContinuation(deliveries, relayBudget)
        : rendered.text;
      if (wake && (!formatted || (!continuation && rendered.deliveries[0]?.delivery_id !== user.metadata.delivery_id)))
        throw new Error("Pallium internal wake has no model-bound Relay context");
      const memory = !formatted && !wake && item.memory?.inputId === user.id ? item.memory.text : scopeText;
      const text = [formatted, memory].filter(Boolean).join("\n\n");
      if (!text) return;
      user.content = [...(user.content || []), { type: "text", text: `\n\n<system-reminder>\n${text}\n</system-reminder>` }];
      if (!continuation && rendered.deliveries.length) {
        const results = wake ? await pallium.acknowledgeRelay(rendered.deliveries, container, signal) :
          await acknowledgeOrdinary(id, item, user.id, claim, rendered.deliveries, identity);
        if (!current()) return;
        if (!wake && claim && results.every((result) => result.success)) claim.acked = true;
      }
      } catch (error) {
        if (wake) throw error;
        log(`V2 ordinary context failed: ${String(error)}`);
      }
    }));

    registrations.push(await ctx.session.hook("compaction", async (event) => {
      const item = sessions.get(event?.sessionID);
      if (item) item.witness = null;
      if (event?.sessionID) await ingestAssistant(event.sessionID);
    }));

    const restore = async (id, resolved = null) => {
      const item = state(id);
      const signal = item?.abort.signal;
      try {
      const binding = resolved || await resolveScope(id, item, signal);
      if (!binding?.current()) return;
      const listed = await pallium.relayRequest("GET", "/relay/sessions", {
        runtime: "opencode", session_ref: id, container_ref: binding.container, include_inactive: false,
      }, pallium.HTTP_TIMEOUT_MS, signal);
      if (!binding.current() || !await owned(id, item, signal) || !binding.current()) return;
      const session = (Array.isArray(listed) ? listed : []).find((entry) => entry?.session_ref === id);
      if (remember(id, item, session)) await enroll(id, item);
      } catch (error) { if (live(id, item, signal)) log(`V2 restore deferred: ${String(error)}`); }
    };
    const events = (async () => {
      try {
        for await (const event of ctx.event.subscribe({ signal: abort.signal })) {
          if (disposed || !event?.data?.sessionID) continue;
          const id = event.data.sessionID;
          // Cancel known proof BEFORE filtering a move's new location. This does
          // not broaden the existing detach/claim/close authority below.
          if (["session.deleted", "session.archived", "session.moved", "session.revert.staged", "session.revert.cleared", "session.revert.committed"].includes(event.type) ||
              event.type?.startsWith("session.compaction.") ||
              event.type === "session.execution.interrupted" && event.data.reason === "shutdown") {
            const item = sessions.get(id);
            if (item) item.witness = null;
          }
          if (event.location?.directory && !sameLocation(event.location.directory, cwd)) continue;
          if (event.type === "session.deleted") {
            const item = sessions.get(id);
            const pinned = pallium.getPinnedContainer(id), actor = pallium.getPinnedActor(id);
            const known = item?.containerRef || pinned;
            const detaching = detach(id, item); // retire runs before this promise's first yield.
            const started = retirement;
            const current = () => !disposed && !sessions.has(id) && started === retirement &&
              pallium.getPinnedContainer(id) === pinned && pallium.getPinnedActor(id) === actor;
            await detaching;
            if (!current()) continue;
            const container = known || await pallium.deriveContainerRef(cwd, abort.signal);
            if (!current()) continue;
            await pallium.relayRequest("POST", "/relay/sessions/close", {
              runtime: "opencode", session_ref: id, container_ref: container,
            }, pallium.HTTP_TIMEOUT_MS, abort.signal);
            if (current()) pallium.removeSessionPin(id);
          } else if (event.type === "session.execution.succeeded" || event.type === "session.execution.failed" || event.type === "session.idle") {
            void ingestAssistant(id);
          } else if (event.type === "session.created") {
            void restore(id);
          }
        }
      } catch (error) { if (!disposed) log(`V2 event stream failed: ${String(error)}`); }
      finally {
        freshWitnessEnabled = false;
        for (const item of sessions.values()) item.witness = null;
      }
    })();
    let discovering = false;
    const discover = async () => {
      if (disposed || !discoveryNeeded || discovering) return;
      discovering = true;
      const started = retirement;
      try {
        const container = await pallium.deriveContainerRef(cwd, abort.signal);
        if (disposed || started !== retirement) return;
        const listed = await pallium.relayRequest("GET", "/relay/sessions", {
          runtime: "opencode", container_ref: container, include_inactive: false,
        }, pallium.HTTP_TIMEOUT_MS, abort.signal);
        if (disposed || started !== retirement || !Array.isArray(listed)) return;
        discoveryNeeded = listed.length === 0;
        for (const session of listed) {
          if (disposed || started !== retirement) { discoveryNeeded = true; return; }
          if (!session?.session_ref) continue;
          const item = state(session.session_ref);
          const signal = item.abort.signal;
          const current = scopeCurrent(session.session_ref, item, signal);
          if (!await owned(session.session_ref, item, signal) || !current() || started !== retirement) continue;
          const pinned = pallium.getPinnedContainer(session.session_ref);
          if (pinned && pinned !== container || item.containerRef && item.containerRef !== container) continue;
          item.containerRef = container;
          if (remember(session.session_ref, item, session)) await enroll(session.session_ref, item);
        }
      } catch (error) { if (!disposed) log(`V2 discovery deferred: ${String(error)}`); }
      finally { discovering = false; }
    };
    void discover();
    const timer = setInterval(() => {
      void discover();
      for (const [id, item] of sessions) { void maintainReceipts(id, item); void poll(id); }
    }, POLL_MS);
    timer.unref?.();
    return () => {
      if (cleanup) return cleanup;
      disposed = true;
      // Publish the cleanup promise before abort listeners can re-enter disposal.
      cleanup = Promise.resolve().then(async () => {
        clearInterval(timer);
        abort.abort();
        const pending = [...sessions].filter(([, item]) => item.endpointId && item.containerRef)
          .map(([id, item]) => ({ operation: "detach", ...base(id, item), container_ref: item.containerRef }));
        for (const [id, item] of sessions) retire(id, item);
        const retired = await Promise.allSettled(registrations.map(async (registration) => registration.dispose()));
        await events;
        const remote = new AbortController();
        const deadline = setTimeout(() => remote.abort(), 500);
        try {
          await Promise.all(Array.from({ length: Math.min(4, pending.length) }, async () => {
            while (pending.length && !remote.signal.aborted) {
              await pallium.relayRequest("POST", "/relay/opencode/wake", pending.shift(), 500, remote.signal);
            }
          }));
        } finally { clearTimeout(deadline); }
        const failures = retired.filter((result) => result.status === "rejected");
        if (failures.length) throw new AggregateError(failures.map((result) => result.reason), "Pallium hook disposal failed");
      });
      return cleanup;
    };
  },
};
