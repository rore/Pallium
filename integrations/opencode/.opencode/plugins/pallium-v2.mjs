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

    const log = (message) => { try { ctx.app?.log?.({ service: "pallium", level: "warn", message }); } catch {} };
    const state = (id) => {
      if (disposed) return null;
      let item = sessions.get(id);
      if (!item) { item = { busy: false, wakeBusy: false, seen: new Set(), captures: new Set(), completedCaptures: new Set(), lastAssistant: null,
        roleTurns: new Map(), naturalClaims: new Map(), abort: new AbortController() }; sessions.set(id, item); }
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
    const scope = (id) => pallium.resolveContainerRef(cwd, id);
    const base = (id, item) => ({
      session_ref: id, container_ref: scope(id), endpoint_id: item.endpointId,
      scope_generation: item.scopeGeneration, native_location: cwd, owner_id: ownerId,
    });
    const wakeRequest = (id, item, operation, extra = {}, onHttpError) => !live(id, item) || item.endpointId == null ? null :
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
        item.memory = null;
        item.wake = null;
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
      const payload = item?.endpointId ? { operation: "detach", ...base(id, item) } : null;
      retire(id, item);
      if (!disposed && payload) await pallium.relayRequest("POST", "/relay/opencode/wake", payload, 500, abort.signal);
    };
    const wakeResponseContext = (id, item) => ({ signal: item.abort.signal, binding: base(id, item),
      wake: item.wake, witness: item.witness, flight: item.wakeBusy });
    const applyWakeResponse = (id, item, request, response) => {
      if (!live(id, item, request.signal) || item.wake !== request.wake ||
          !Object.entries(request.binding).every(([key, value]) => base(id, item)[key] === value)) return false;
      const reject = () => {
        if (item.witness === request.witness) item.witness = null;
        // Cancel this flight, never a newer one started while HTTP was pending.
        if (item.wakeBusy === request.flight) item.wakeBusy = false;
        return false;
      };
      const session = response?.session, wake = response?.wake, known = item.wake;
      if (session?.runtime !== "opencode" || session.session_ref !== id || session.container_ref !== request.binding.container_ref ||
          session.endpoint_id !== request.binding.endpoint_id || session.scope_generation !== request.binding.scope_generation ||
          session.state !== "recent" || session.destination_health !== "active") return reject();
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
      return true;
    };
    const enroll = async (id, item) => {
      const signal = item?.abort.signal;
      if (!live(id, item, signal) || !item.endpointId || !await owned(id, item, signal)) return;
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
        await wakeRequest(id, item, "admitted", fields);
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
        if (!await owned(id, item, signal)) { if (live(id, item, signal)) await detach(id, item); return; }
        const request = wakeResponseContext(id, item);
        let registrationMissing = false;
        let response = await wakeRequest(id, item, "poll", {}, (status, error) => {
          registrationMissing = status === 409 && error?.detail === "OpenCode registration is missing or stale";
        });
        if (!live(id, item, signal)) return;
        // Only an explicit registration conflict warrants another enrollment write.
        let applied = false;
        if (!response && registrationMissing) { response = await enroll(id, item); applied = !!response; }
        if (!await owned(id, item, signal) || !response) {
          if (item.witness === witness) item.witness = null;
          return;
        }
        if (applied ? item.wake !== response.wake : !applyWakeResponse(id, item, request, response)) return;
        if (response.wake && !response.wake.terminal && sameLocation(response.wake.native_location, cwd))
          void runWake(id, item, response.wake);
      } finally { if (live(id, item, signal)) item.busy = false; }
    };
    const requestNaturalTurn = (id, item, inputId, relayBudget, discovery, claim, roleTurn = null) => {
      if (claim.response) return Promise.resolve(claim.response);
      if (claim.promise) return claim.promise;
      const pending = (async () => {
        const maxChars = relayClaimBudget(relayBudget);
        const response = await pallium.relayRequest("POST", "/relay/turn", {
          runtime: "opencode", session_ref: id, container_ref: scope(id), max_chars: maxChars,
          structural_work_refs: pallium.structuralWorkRefsPayload(scope(id), discovery.structuralRefs, pallium.repositoryScopeRef(cwd)),
        }, pallium.HTTP_TIMEOUT_MS, item.abort.signal);
        if (!live(id, item)) return null;
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
        if (!await owned(id, sessions.get(id), undefined, token) || disposed || !token.valid) return;
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
        if (!live(id, item, signal)) return;
        const messages = rows(await ctx.session.context({ sessionID: id }));
        if (!await owned(id, item, signal)) return;
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
          const actor = pallium.resolveActorRef(cwd, id);
          const container = scope(id);
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
                response[0].source_item_id.trim() && await owned(id, item, signal) && live(id, item, signal)) {
              item.completedCaptures.add(sourceId);
              item.lastAssistant = sourceId;
            }
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
      if (!await owned(id, item, signal)) {
        if (item.witness === firstWitness) item.witness = null;
        return;
      }
      if (event.metadata?.pallium_relay_wake === true && event.prompt?.text === WAKE_TEXT) {
        if (!item.endpointId) await restore(id);
        if (!live(id, item, signal)) return;
        if (item.wake?.native_input_id === event.messageID && item.wake.generation === event.metadata.generation &&
            item.wake.delivery_id === event.metadata.delivery_id) return;
      }
      const content = pallium.stripIdeContext(event.prompt?.text || "");
      if (!content || content.startsWith("/") || item.seen.has(event.messageID)) return;
      item.seen.add(event.messageID);
      const actor = pallium.resolveActorRef(cwd, id);
      const container = scope(id);
      pallium.pinContainer(id, container, undefined, actor);
      const discovery = pallium.discoverWorkRefs(cwd);
      const scopeText = pallium.formatInjection([], container, BUDGET, id, actor, pallium.AGENT_REF, "private", null,
        pallium.injectedWorkRef(discovery));
      const claim = event.metadata?.pallium_relay_wake === true ? null :
        ensureNaturalTurn(id, item, event.messageID, content, relayRenderBudget(scopeText), discovery);
      if (claim) await claim.promise;
      if (!await owned(id, item, signal)) return;
      const roleTurn = item.roleTurns.get(event.messageID);
      if (roleTurn?.inputHash !== createHash("sha256").update(content).digest("hex")) return;
      const roleSnapshot = roleTurn?.snapshot || { relay_name: null, relay_attribution_state: "unavailable" };
      const response = await pallium.palliumRequest("POST", "/item-and-query", {
        source_type: pallium.SOURCE_TYPE, source_id: pallium.ocNativeMessageSourceId("user", id, event.messageID), content_type: "text/plain",
        content, role: "user", agent_ref: pallium.AGENT_REF, container_ref: container,
        thread_ref: id, actor_ref: actor, visibility: "private", artifact_kind: "message",
        source_turn_id: roleTurn ? event.messageID : undefined,
        relay_name: roleSnapshot.relay_name, relay_attribution_state: roleSnapshot.relay_attribution_state,
        query_text: content.slice(0, 500), query_limit: 5, query_actor_ref: actor,
        query_trigger_origin: "user_prompt_submit", metadata: pallium.buildWorkRefsMetadata(cwd, event.metadata?.pallium_work_refs, discovery),
      }, signal);
      if (!await owned(id, item, signal)) return;
      if (!response) item.seen.delete(event.messageID);
      const text = pallium.formatInjection(response?.injectable_blocks || [], container, BUDGET, id, actor, pallium.AGENT_REF, "private", response?.source_item_id);
      if (text) item.memory = { inputId: event.messageID, text };
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
      let signal = item.abort.signal;
      const reservedWake = () => internal(user) && item.wake?.native_input_id === user.id &&
        item.wake.generation === user.metadata.generation && item.wake.delivery_id === user.metadata.delivery_id &&
        sameLocation(item.wake.native_location, cwd);
      wake = reservedWake();
      if (!await owned(id, item, signal)) {
        if (wake && !live(id, item, signal)) throw new Error("Pallium internal wake owner retired");
        return;
      }
      const discovery = pallium.discoverWorkRefs(cwd);
      const scopeText = pallium.formatInjection([], scope(id), BUDGET, id,
        pallium.resolveActorRef(cwd, id), pallium.AGENT_REF, "private", null, pallium.injectedWorkRef(discovery));
      const relayBudget = relayRenderBudget(scopeText);
      const maxChars = relayClaimBudget(relayBudget);
      if (internal(user) && !item.endpointId) await restore(id);
      if (!live(id, item, signal)) {
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
      if (!await owned(id, item, signal)) {
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
        const results = await pallium.acknowledgeRelay(rendered.deliveries, scope(id), signal);
        if (!live(id, item, signal)) return;
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

    const restore = async (id) => {
      const item = state(id);
      const signal = item?.abort.signal;
      if (!await owned(id, item, signal)) return;
      const listed = await pallium.relayRequest("GET", "/relay/sessions", {
        runtime: "opencode", session_ref: id, container_ref: scope(id), include_inactive: false,
      }, pallium.HTTP_TIMEOUT_MS, signal);
      if (!await owned(id, item, signal)) return;
      const session = (Array.isArray(listed) ? listed : []).find((entry) => entry?.session_ref === id);
      if (remember(id, item, session)) await enroll(id, item);
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
            await detach(id, item);
            if (disposed || sessions.has(id)) continue;
            await pallium.relayRequest("POST", "/relay/sessions/close", {
              runtime: "opencode", session_ref: id, container_ref: scope(id),
            }, pallium.HTTP_TIMEOUT_MS, abort.signal);
            if (!disposed && !sessions.has(id)) pallium.removeSessionPin(id);
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
    let discoveryNeeded = true;
    let discovering = false;
    const discover = async () => {
      if (disposed || !discoveryNeeded || discovering) return;
      discovering = true;
      const started = retirement;
      try {
        const listed = await pallium.relayRequest("GET", "/relay/sessions", {
          runtime: "opencode", container_ref: pallium.deriveContainerRef(cwd), include_inactive: false,
        }, pallium.HTTP_TIMEOUT_MS, abort.signal);
        if (disposed || started !== retirement || !Array.isArray(listed)) return;
        discoveryNeeded = listed.length === 0;
        for (const session of listed) {
          if (disposed || started !== retirement) { discoveryNeeded = true; return; }
          if (!session?.session_ref) continue;
          const item = state(session.session_ref);
          const signal = item.abort.signal;
          if (!await owned(session.session_ref, item, signal)) continue;
          if (remember(session.session_ref, item, session)) await enroll(session.session_ref, item);
        }
      } finally { discovering = false; }
    };
    void discover();
    const timer = setInterval(() => { void discover(); for (const id of sessions.keys()) void poll(id); }, POLL_MS);
    timer.unref?.();
    return () => {
      if (cleanup) return cleanup;
      disposed = true;
      // Publish the cleanup promise before abort listeners can re-enter disposal.
      cleanup = Promise.resolve().then(async () => {
        clearInterval(timer);
        abort.abort();
        const pending = [...sessions].filter(([, item]) => item.endpointId)
          .map(([id, item]) => ({ operation: "detach", ...base(id, item) }));
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
