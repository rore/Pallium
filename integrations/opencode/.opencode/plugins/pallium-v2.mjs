import path from "node:path";
import { createHash, randomUUID } from "node:crypto";
import * as pallium from "./pallium-common.mjs";

const WAKE_TEXT = "[Pallium Relay wake: check the lower-authority Relay context before acting.]";
const POLL_MS = 2500;
const BUDGET = 2300;
const MAX_HISTORY = 20000;
const validInput = (id) => typeof id === "string" && /^msg_[A-Za-z0-9_-]+$/.test(id);
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
    const registrations = [];
    const abort = new AbortController();
    let disposed = false;
    let cleanup;
    let retirement = 0;

    const log = (message) => { try { ctx.app?.log?.({ service: "pallium", level: "warn", message }); } catch {} };
    const state = (id) => {
      if (disposed) return null;
      let item = sessions.get(id);
      if (!item) { item = { busy: false, wakeBusy: false, seen: new Set(), captures: new Set(), lastAssistant: null, abort: new AbortController() }; sessions.set(id, item); }
      return item;
    };
    const live = (id, item, signal = item?.abort.signal) => !disposed && item &&
      sessions.get(id) === item && item.abort.signal === signal && !signal.aborted;
    const retire = (id, item) => {
      item?.abort.abort();
      if (sessions.get(id) === item) { sessions.delete(id); retirement++; }
    };
    const scope = (id) => pallium.resolveContainerRef(cwd, id);
    const base = (id, item) => ({
      session_ref: id, container_ref: scope(id), endpoint_id: item.endpointId,
      scope_generation: item.scopeGeneration, native_location: cwd, owner_id: ownerId,
    });
    const wakeRequest = (id, item, operation, extra = {}) => !live(id, item) || item.endpointId == null ? null :
      pallium.relayRequest("POST", "/relay/opencode/wake", { operation, ...base(id, item), ...extra }, pallium.HTTP_TIMEOUT_MS, item.abort.signal);
    const remember = (id, item, session) => {
      if (!live(id, item) || session?.runtime !== "opencode" || session.session_ref !== id || session.container_ref !== scope(id) ||
          session.state !== "recent" || session.destination_health !== "active" ||
          typeof session.endpoint_id !== "string" || !Number.isInteger(session.scope_generation)) return false;
      if (item.endpointId && (item.endpointId !== session.endpoint_id || item.scopeGeneration !== session.scope_generation)) {
        item.abort.abort();
        item.abort = new AbortController();
        item.captures = new Set();
        item.lastAssistant = null;
        item.busy = false;
        item.wakeBusy = false;
        item.naturalClaim = null;
        item.memory = null;
        item.wake = null;
      }
      item.endpointId = session.endpoint_id;
      item.scopeGeneration = session.scope_generation;
      return true;
    };
    const owned = async (id, item, signal = item?.abort.signal) => {
      try {
        if (!live(id, item, signal)) return false;
        const session = await ctx.session.get({ sessionID: id });
        return live(id, item, signal) && sameLocation(session?.location?.directory, cwd);
      } catch { return false; }
    };
    const detach = async (id, item) => {
      const payload = item?.endpointId ? { operation: "detach", ...base(id, item) } : null;
      retire(id, item);
      if (!disposed && payload) await pallium.relayRequest("POST", "/relay/opencode/wake", payload, 500, abort.signal);
    };
    const enroll = async (id, item) => {
      const signal = item?.abort.signal;
      if (!live(id, item, signal) || !item.endpointId || !await owned(id, item, signal)) return;
      const response = await wakeRequest(id, item, "enroll");
      if (!live(id, item, signal)) return;
      if (response?.session) remember(id, item, response.session);
      if (response) item.wake = response.wake;
      return response;
    };
    const terminalAfter = (messages, inputId) => {
      const index = messages.findIndex((m) => m?.type === "user" && m.id === inputId);
      if (index < 0) return null;
      const nextUser = messages.findIndex((m, n) => n > index && m?.type === "user");
      const end = nextUser < 0 ? messages.length : nextUser;
      const idle = messages.slice(index + 1, end).find((m) => m?.type === "idle" && validInput(m.id));
      return idle?.id || null;
    };
    const runWake = async (id, item, wake) => {
      const signal = item?.abort.signal;
      if (!live(id, item, signal) || item.wakeBusy || !validInput(wake?.native_input_id) || !validDelivery(wake?.delivery_id) || !Number.isInteger(wake?.generation)) return;
      item.wakeBusy = true;
      try {
        if (!await owned(id, item, signal)) return;
        const fields = { generation: wake.generation, delivery_id: wake.delivery_id, native_input_id: wake.native_input_id };
        const history = rows(await ctx.session.context({ sessionID: id }));
        if (!await owned(id, item, signal)) return;
        const observed = (messages) => messages.some((m) => m?.type === "user" && m.id === wake.native_input_id &&
          m.text === WAKE_TEXT && m.metadata?.pallium_relay_wake === true &&
          m.metadata.generation === wake.generation && m.metadata.delivery_id === wake.delivery_id);
        if (!observed(history)) {
          if (wake.admitted) return; // A compacted or missing input cannot prove a new admission.
          // The stable native ID makes a lost prompt response safe to retry.
          await ctx.session.prompt({ sessionID: id, id: wake.native_input_id, text: WAKE_TEXT, delivery: "queue",
            metadata: { pallium_relay_wake: true, generation: wake.generation, delivery_id: wake.delivery_id } });
        }
        if (!await owned(id, item, signal)) return;
        if (!observed(rows(await ctx.session.context({ sessionID: id })))) return;
        if (!await owned(id, item, signal)) return;
        await wakeRequest(id, item, "admitted", fields);
        if (!live(id, item, signal)) return;
        await ctx.session.wait({ sessionID: id });
        if (!await owned(id, item, signal)) return;
        const after = rows(await ctx.session.context({ sessionID: id }));
        if (!await owned(id, item, signal)) return;
        const terminalId = terminalAfter(after, wake.native_input_id);
        if (terminalId) await wakeRequest(id, item, "terminal", { ...fields, terminal_message_id: terminalId });
      } catch (error) { log(`V2 wake deferred: ${String(error)}`); }
      finally { if (live(id, item, signal)) item.wakeBusy = false; }
    };
    const poll = async (id) => {
      const item = sessions.get(id);
      const signal = item?.abort.signal;
      if (!live(id, item, signal) || item.busy || !item.endpointId) return;
      item.busy = true;
      try {
        if (!await owned(id, item, signal)) { if (live(id, item, signal)) await detach(id, item); return; }
        let response = await wakeRequest(id, item, "poll");
        if (!live(id, item, signal)) return;
        // A restart or outage can outlive the owner lease. Enrollment still
        // refuses a competing live owner and requires this exact native location.
        if (!response) response = await enroll(id, item);
        if (!await owned(id, item, signal) || !response?.session || !remember(id, item, response.session)) return;
        item.wake = response.wake;
        if (response.wake && !response.wake.terminal && sameLocation(response.wake.native_location, cwd))
          void runWake(id, item, response.wake);
      } finally { if (live(id, item, signal)) item.busy = false; }
    };
    const ingestAssistant = async (id) => {
      const item = state(id);
      const signal = item?.abort.signal;
      const captures = item?.captures;
      let sourceId;
      let reserved = false;
      try {
        if (!live(id, item, signal)) return;
        const messages = rows(await ctx.session.context({ sessionID: id }));
        if (!await owned(id, item, signal)) return;
        const lastUser = messages.findLastIndex((message) => message?.type === "user");
        const assistants = messages.slice(lastUser + 1).filter((message) => message?.type === "assistant");
        if (!assistants.length || assistants.some((message) => !validInput(message.id) || !Number.isFinite(message.time?.completed))) return;
        const turn = pallium.extractV2AssistantTurn(messages);
        if (!turn?.assistant_text || turn.assistant_text.length > MAX_HISTORY) return;
        const actor = pallium.resolveActorRef(cwd, id);
        const container = scope(id);
        sourceId = "oc-assistant-" + createHash("sha256").update(JSON.stringify([
          "opencode-assistant/v1", pallium.AGENT_REF, actor, container, id, assistants.at(-1).id,
        ])).digest("hex");
        if (sourceId === item.lastAssistant || captures.has(sourceId)) return;
        const workTrace = pallium.buildWorkTraceMetadata(turn);
        const metadata = { ...pallium.buildWorkRefsMetadata(cwd), ...(workTrace ? { agent_work_trace_turn: workTrace, cwd } : {}) };
        captures.add(sourceId);
        reserved = true;
        const response = await pallium.palliumRequest("POST", "/items", [{
          source_type: pallium.SOURCE_TYPE, source_id: sourceId, content_type: "text/plain",
          content: turn.assistant_text, role: "assistant", agent_ref: pallium.AGENT_REF,
          container_ref: container, thread_ref: id, actor_ref: actor,
          visibility: "private", artifact_kind: "message", ...(Object.keys(metadata).length ? { metadata } : {}),
        }], signal);
        if (Array.isArray(response) && response.length === 1 && typeof response[0]?.source_item_id === "string" &&
            response[0].source_item_id.trim() && await owned(id, item, signal)) item.lastAssistant = sourceId;
      } catch (error) { log(`V2 assistant ingest failed: ${String(error)}`); }
      finally { if (reserved) captures.delete(sourceId); }
    };

    registrations.push(await ctx.session.hook("prompt", async (event) => {
      try {
      const id = event?.sessionID;
      if (!id || !validInput(event.messageID) || disposed) return;
      const item = state(id);
      const signal = item.abort.signal;
      if (!await owned(id, item, signal)) return;
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
      const response = await pallium.palliumRequest("POST", "/item-and-query", {
        source_type: pallium.SOURCE_TYPE, source_id: pallium.ocSourceId(), content_type: "text/plain",
        content, role: "user", agent_ref: pallium.AGENT_REF, container_ref: container,
        thread_ref: id, actor_ref: actor, visibility: "private", artifact_kind: "message",
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
      const relayBudget = BUDGET - scopeText.length - 2;
      if (internal(user) && !item.endpointId) await restore(id);
      if (!live(id, item, signal)) {
        if (wake) throw new Error("Pallium internal wake owner retired");
        return;
      }
      wake = reservedWake();
      let response;
      if (wake) {
        response = await wakeRequest(id, item, "context", {
          generation: user.metadata.generation, delivery_id: user.metadata.delivery_id,
          native_input_id: user.id, max_chars: relayBudget,
        });
        if (!response || (!response.deliveries?.length && !response.restored))
          throw new Error("Pallium internal wake has no current Relay work");
      } else if (!internal(user)) {
        // A natural turn is the only path that can register a new Relay session.
        if (!item.naturalClaim || item.naturalClaim.inputId !== user.id) {
          response = await pallium.relayRequest("POST", "/relay/turn", {
            runtime: "opencode", session_ref: id, container_ref: scope(id), max_chars: relayBudget,
            structural_work_refs: pallium.structuralWorkRefsPayload(scope(id), discovery.structuralRefs, pallium.repositoryScopeRef(cwd)),
          }, pallium.HTTP_TIMEOUT_MS, signal);
          if (!await owned(id, item, signal)) return;
          if (response?.session) {
            if (!remember(id, item, response.session)) return;
            signal = item.abort.signal;
            item.naturalClaim = { inputId: user.id, response };
            void enroll(id, item);
          }
        } else response = item.naturalClaim.response;
      }
      // Unproven marker inputs remain fail-open but cannot register or claim.
      // This also fences an overtaken real wake without treating a forged marker
      // as authority to abort somebody's ordinary work.
      if (!await owned(id, item, signal)) {
        if (wake) throw new Error("Pallium internal wake owner retired");
        return;
      }
      const deliveries = response?.deliveries || [];
      const continuation = response?.restored || (!wake && item.naturalClaim?.inputId === user.id && item.naturalClaim.acked);
      const rendered = continuation ? null : pallium.formatRelay(deliveries, relayBudget, response?.remaining_count || 0);
      const formatted = continuation ? pallium.formatRelayContinuation(deliveries, relayBudget) : rendered.text;
      if (wake && !formatted) throw new Error("Pallium internal wake has no model-bound Relay context");
      const memory = !formatted && !wake && item.memory?.inputId === user.id ? item.memory.text : scopeText;
      const text = [formatted, memory].filter(Boolean).join("\n\n");
      if (!text) return;
      user.content = [...(user.content || []), { type: "text", text: `\n\n<system-reminder>\n${text}\n</system-reminder>` }];
      if (!continuation && rendered.deliveries.length) {
        const results = await pallium.acknowledgeRelay(rendered.deliveries, scope(id), signal);
        if (!live(id, item, signal)) return;
        if (!wake && item.naturalClaim?.inputId === user.id && results.every((result) => result.success))
          item.naturalClaim.acked = true;
      }
      } catch (error) {
        if (wake) throw error;
        log(`V2 ordinary context failed: ${String(error)}`);
      }
    }));

    registrations.push(await ctx.session.hook("compaction", async (event) => {
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
          if (disposed || !event?.data?.sessionID || (event.location?.directory && !sameLocation(event.location.directory, cwd))) continue;
          const id = event.data.sessionID;
          if (event.type === "session.deleted") {
            const item = sessions.get(id);
            await detach(id, item);
            if (disposed || sessions.has(id)) continue;
            await pallium.relayRequest("POST", "/relay/sessions/close", {
              runtime: "opencode", session_ref: id, container_ref: scope(id),
            }, pallium.HTTP_TIMEOUT_MS, abort.signal);
            if (!disposed && !sessions.has(id)) pallium.removeSessionPin(id);
          } else if (event.type === "session.execution.succeeded" || event.type === "session.execution.failed") {
            void ingestAssistant(id);
          } else if (event.type === "session.created") {
            void restore(id);
          }
        }
      } catch (error) { if (!disposed) log(`V2 event stream failed: ${String(error)}`); }
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
        discoveryNeeded = false;
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
