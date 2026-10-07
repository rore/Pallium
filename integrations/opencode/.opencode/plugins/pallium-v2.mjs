import path from "node:path";
import { randomUUID } from "node:crypto";
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

    const log = (message) => { try { ctx.app?.log?.({ service: "pallium", level: "warn", message }); } catch {} };
    const state = (id) => {
      let item = sessions.get(id);
      if (!item) { item = { busy: false, wakeBusy: false, seen: new Set(), lastAssistant: null }; sessions.set(id, item); }
      return item;
    };
    const scope = (id) => pallium.resolveContainerRef(cwd, id);
    const base = (id, item) => ({
      session_ref: id, container_ref: scope(id), endpoint_id: item.endpointId,
      scope_generation: item.scopeGeneration, native_location: cwd, owner_id: ownerId,
    });
    const wakeRequest = (id, item, operation, extra = {}) => item.endpointId == null ? null :
      pallium.relayRequest("POST", "/relay/opencode/wake", { operation, ...base(id, item), ...extra }, pallium.HTTP_TIMEOUT_MS);
    const remember = (id, session) => {
      if (session?.runtime !== "opencode" || session.session_ref !== id || session.container_ref !== scope(id) ||
          session.state !== "recent" || session.destination_health !== "active" ||
          typeof session.endpoint_id !== "string" || !Number.isInteger(session.scope_generation)) return false;
      const item = state(id);
      if (item.endpointId && (item.endpointId !== session.endpoint_id || item.scopeGeneration !== session.scope_generation)) {
        item.naturalClaim = null;
        item.memory = null;
        item.wake = null;
      }
      item.endpointId = session.endpoint_id;
      item.scopeGeneration = session.scope_generation;
      return true;
    };
    const owned = async (id) => {
      try {
        const session = await ctx.session.get({ sessionID: id });
        return sameLocation(session?.location?.directory, cwd);
      } catch { return false; }
    };
    const detach = async (id, item) => {
      if (item?.endpointId) await wakeRequest(id, item, "detach");
      sessions.delete(id);
    };
    const enroll = async (id, item) => {
      if (!item.endpointId || !await owned(id)) return;
      const response = await wakeRequest(id, item, "enroll");
      if (response?.session) remember(id, response.session);
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
      if (item.wakeBusy || !validInput(wake?.native_input_id) || !validDelivery(wake?.delivery_id) || !Number.isInteger(wake?.generation)) return;
      item.wakeBusy = true;
      try {
        if (!await owned(id) || disposed) return;
        const fields = { generation: wake.generation, delivery_id: wake.delivery_id, native_input_id: wake.native_input_id };
        const history = rows(await ctx.session.context({ sessionID: id }));
        const observed = (messages) => messages.some((m) => m?.type === "user" && m.id === wake.native_input_id &&
          m.text === WAKE_TEXT && m.metadata?.pallium_relay_wake === true &&
          m.metadata.generation === wake.generation && m.metadata.delivery_id === wake.delivery_id);
        if (!observed(history)) {
          if (wake.admitted) return; // A compacted or missing input cannot prove a new admission.
          // The stable native ID makes a lost prompt response safe to retry.
          await ctx.session.prompt({ sessionID: id, id: wake.native_input_id, text: WAKE_TEXT, delivery: "queue",
            metadata: { pallium_relay_wake: true, generation: wake.generation, delivery_id: wake.delivery_id } });
        }
        if (disposed || !await owned(id)) return;
        if (!observed(rows(await ctx.session.context({ sessionID: id })))) return;
        await wakeRequest(id, item, "admitted", fields);
        await ctx.session.wait({ sessionID: id });
        if (disposed || !await owned(id)) return;
        const after = rows(await ctx.session.context({ sessionID: id }));
        const terminalId = terminalAfter(after, wake.native_input_id);
        if (terminalId) await wakeRequest(id, item, "terminal", { ...fields, terminal_message_id: terminalId });
      } catch (error) { log(`V2 wake deferred: ${String(error)}`); }
      finally { item.wakeBusy = false; }
    };
    const poll = async (id) => {
      const item = state(id);
      if (disposed || item.busy || !item.endpointId) return;
      item.busy = true;
      try {
        if (!await owned(id)) { await detach(id, item); return; }
        let response = await wakeRequest(id, item, "poll");
        // A restart or outage can outlive the owner lease. Enrollment still
        // refuses a competing live owner and requires this exact native location.
        if (!response) response = await enroll(id, item);
        if (!response?.session || !remember(id, response.session)) return;
        item.wake = response.wake;
        if (response.wake && !response.wake.terminal && sameLocation(response.wake.native_location, cwd))
          void runWake(id, item, response.wake);
      } finally { item.busy = false; }
    };
    const ingestAssistant = async (id) => {
      if (!await owned(id)) return;
      const item = state(id);
      try {
        const messages = rows(await ctx.session.context({ sessionID: id }));
        const assistant = [...messages].reverse().find((m) => m?.type === "assistant" && validInput(m.id));
        if (!assistant || assistant.id === item.lastAssistant) return;
        const turn = pallium.extractV2AssistantTurn(messages);
        if (!turn || (!turn.assistant_text && !turn.tool_calls?.length) || turn.assistant_text.length > MAX_HISTORY) return;
        const workTrace = pallium.buildWorkTraceMetadata(turn);
        const metadata = { ...pallium.buildWorkRefsMetadata(cwd), ...(workTrace ? { agent_work_trace_turn: workTrace, cwd } : {}) };
        const response = await pallium.palliumRequest("POST", "/items", [{
          source_type: pallium.SOURCE_TYPE, source_id: pallium.ocSourceId(), content_type: "text/plain",
          content: turn.assistant_text, role: "assistant", agent_ref: pallium.AGENT_REF,
          container_ref: scope(id), thread_ref: id, actor_ref: pallium.resolveActorRef(cwd, id),
          visibility: "private", artifact_kind: "message", ...(Object.keys(metadata).length ? { metadata } : {}),
        }]);
        if (response) item.lastAssistant = assistant.id;
      } catch (error) { log(`V2 assistant ingest failed: ${String(error)}`); }
    };

    registrations.push(await ctx.session.hook("prompt", async (event) => {
      try {
      const id = event?.sessionID;
      if (!id || !validInput(event.messageID) || disposed || !await owned(id)) return;
      const item = state(id);
      if (event.metadata?.pallium_relay_wake === true && event.prompt?.text === WAKE_TEXT) {
        if (!item.endpointId) await restore(id);
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
      });
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
      if (!user || !await owned(id)) return;
      const item = state(id);
      const discovery = pallium.discoverWorkRefs(cwd);
      const scopeText = pallium.formatInjection([], scope(id), BUDGET, id,
        pallium.resolveActorRef(cwd, id), pallium.AGENT_REF, "private", null, pallium.injectedWorkRef(discovery));
      const relayBudget = BUDGET - scopeText.length - 2;
      if (internal(user) && !item.endpointId) await restore(id);
      const reserved = item.wake;
      wake = internal(user) && reserved?.native_input_id === user.id &&
        reserved.generation === user.metadata.generation && reserved.delivery_id === user.metadata.delivery_id &&
        sameLocation(reserved.native_location, cwd);
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
          }, pallium.HTTP_TIMEOUT_MS);
          if (response?.session) {
            remember(id, response.session);
            item.naturalClaim = { inputId: user.id, response };
            void enroll(id, item);
          }
        } else response = item.naturalClaim.response;
      }
      // Unproven marker inputs remain fail-open but cannot register or claim.
      // This also fences an overtaken real wake without treating a forged marker
      // as authority to abort somebody's ordinary work.
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
        const results = await pallium.acknowledgeRelay(rendered.deliveries, scope(id));
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
      if (!await owned(id)) return;
      const listed = await pallium.relayRequest("GET", "/relay/sessions", {
        runtime: "opencode", session_ref: id, container_ref: scope(id), include_inactive: false,
      }, pallium.HTTP_TIMEOUT_MS);
      const session = (Array.isArray(listed) ? listed : []).find((entry) => entry?.session_ref === id);
      if (remember(id, session)) await enroll(id, state(id));
    };
    const events = (async () => {
      try {
        for await (const event of ctx.event.subscribe({ signal: abort.signal })) {
          if (disposed || !event?.data?.sessionID || (event.location?.directory && !sameLocation(event.location.directory, cwd))) continue;
          const id = event.data.sessionID;
          if (event.type === "session.deleted") {
            const item = sessions.get(id);
            await detach(id, item);
            await pallium.relayRequest("POST", "/relay/sessions/close", {
              runtime: "opencode", session_ref: id, container_ref: scope(id),
            }, pallium.HTTP_TIMEOUT_MS);
            pallium.removeSessionPin(id);
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
      try {
        const listed = await pallium.relayRequest("GET", "/relay/sessions", {
          runtime: "opencode", container_ref: pallium.deriveContainerRef(cwd), include_inactive: false,
        }, pallium.HTTP_TIMEOUT_MS);
        if (!Array.isArray(listed)) return;
        discoveryNeeded = false;
        for (const session of listed) {
          if (disposed || !session?.session_ref || !await owned(session.session_ref)) continue;
          if (remember(session.session_ref, session)) await enroll(session.session_ref, state(session.session_ref));
        }
      } finally { discovering = false; }
    };
    void discover();
    const timer = setInterval(() => { void discover(); for (const id of sessions.keys()) void poll(id); }, POLL_MS);
    timer.unref?.();
    return async () => {
      disposed = true;
      clearInterval(timer);
      abort.abort();
      for (const [id, item] of sessions) await detach(id, item);
      for (const registration of registrations) await registration.dispose();
      await events;
    };
  },
};
