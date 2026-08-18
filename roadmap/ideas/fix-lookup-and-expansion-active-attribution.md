---
id: fix-lookup-and-expansion-active-attribution
title: Lookup and expansion events must carry active session + agent identity
status: queued
priority: high
commitment: uncommitted
---

## Summary

Historical-lookup telemetry cannot be attributed to the active session or agent. Lookup events derive
`session_id`/`actor_ref` from optional MCP params the default local setup never injects, so both land
**NULL**. Expansion events are attributed to the **historical anchor's** thread and actor, not the
requesting session — so activity in session B looks like activity in old session A. This breaks
per-session, cross-session, and cross-agent reuse analysis even when retrieval works.

## Why

Verified against the code (reviewer's "schema has no agent field" claim is REFUTED — `actor_ref` exists
at `sqlite_schema.py:341`; the real defect is NULL/anchor population):
- `core/service.py:731` — lookup event `"session_id": thread_ref`; `:733` `"actor_ref": actor_ref`.
- `app/mcp/server.py:57-62` — `pallium_search_history` takes `thread_ref`/`actor_ref` as optional; docstring never tells the agent to pass them. `app/mcp/context.py:38-39` falls back to env `PALLIUM_THREAD_REF`/`PALLIUM_ACTOR_REF`, but `app/cli/setup_codex.py:159-164` injects only transport/base-url/pythonpath — so both resolve NULL by default.
- `core/service.py:1598` — expansion event `"session_id": anchor.thread_ref`; `:1503`/`:1600` write `effective_actor_ref = query_actor_ref or anchor.actor_ref` → attributed to the anchor when caller omits actor.
- Schema columns that DO exist: `sqlite_schema.py:339-342` (`session_id`, `container_ref`, `actor_ref`, `trigger_origin`) plus `parent_lookup_id`.

This is the Phase-0 "linked event chain — session/agent identity, expansion parentage" requirement
(scope.md) shipped with the fields present but unpopulated.

## In Scope

- Make active session and agent first-class request context sourced from the **client invocation**, not
  inferred from the retrieved source: `active_session_ref`, `agent_ref`, `actor_ref`, `container_ref`,
  and separately `source_session_ref` where applicable; `parent_lookup_event_id` on expansion.
- Expansion inherits active identity by resolving its persisted parent lookup (prefer requiring
  `parent_lookup_event_id`) rather than accepting duplicate client identity or the anchor's.
- Decide explicitly what happens when a client cannot supply identity: reject measurement-bearing calls,
  generate an installation-scoped anonymous session, or mark the event `unattributed` and **exclude it
  visibly** from the KPI. Silent NULL is disallowed.

## Out of Scope

- Automatic session correlation / agent-ref routing (Phase 2).
- The KPI denominator taxonomy (`fix-reuse-kpi-artifact-taxonomy`).

## Done When

1. Active-session E2E: source in session A, search from session B → event has `active_session_ref=B`, `source_session_ref=A`, correct agent/actor/container; no field labels A as active.
2. Lookup→expansion chain E2E: both events active-session B, both retain source session A, expansion points to the lookup, funnel shows one lookup + one expansion. Invalid chaining (nonexistent/foreign-actor/foreign-container/expired parent) rejected.
3. Cross-agent reuse counted once (agent B reusing agent A's material is not self-reuse by A); concurrency test — two agents against one source get distinct events with correct active session and no server-global contamination.
4. Missing-identity contract is tested explicitly (rejected / generated / `unattributed`+excluded+data-quality-counted).
5. Expansion idempotency: retrying the same expansion does not count as two reuse journeys.

## Notes

External-review register items 2 + 3 (severity High) — merged; the code fix is one coherent telemetry
contract change. Touches red `core/service.py` — clean-context plan review required. Related:
`add-historical-lookup-funnel-telemetry`, `add-agent-event-contract-and-compact-query-results`.

## Scope note — telemetry identity, NOT authorization

This is a **telemetry** contract: record which session/agent *requested* a lookup/expansion and link it
via `parent_lookup_id`. It is NOT authorization. Pallium is trusted-local — do NOT introduce
actor-authentication machinery, actor-scoped access checks, or "deny cross-actor" gates here (that path
was tried and reverted in #42 as pseudo-authorization). Identity fields are for measurement attribution
only; enforcing them as an access boundary is out of scope and premature without an auth layer.

## Additional DoD detail (external review items 2 + 3 — full matrix)

**Cross-agent / cross-session attribution matrix** (telemetry only — assert the event records the
correct requesting identity, NOT that access is granted/denied): same agent, different session;
different agent, same actor; different actor. Each case asserts the lookup/expansion event carries the
*requesting* session + agent, never the source's.

**Expansion invalid-chaining cases:** nonexistent parent lookup; expansion attached to a lookup from
another actor; expansion attached to another container's lookup; expansion attached to a completed or
expired lookup (if expiry exists); repeated expansion of the same source; expansion of two results from
one lookup (funnel counts correctly). (These test event LINKAGE integrity, not authorization.)

**Concurrency:** two agents concurrently against the same historical source get distinct lookup events,
each with the correct active session; expansions and downstream-use events attach to the correct lookup;
no last-writer or server-global context contamination.

**Missing-identity contract (test the chosen one explicitly):** absent session identity is rejected with
a defined error; OR a generated installation-scoped identity is persisted consistently; OR the event is
marked `unattributed`, excluded from the KPI, and counted in a visible data-quality metric. Silent NULL
is disallowed.
