---
id: add-agent-historical-lookup-tool
title: Agent-facing historical lookup tool
status: done
priority: high
commitment: committed
milestone: pallium-vnext-p1
---

## Summary

Give agents a deliberate way to search prior agent work: an MCP tool
(`pallium_search_history`) whose default interaction is simply "search prior work
for X", tagged as an agent-initiated pull, plus skill/CLAUDE.md guidance on *when*
to reach for it. The full filter surface exists only as optional advanced
parameters — the agent should not have to understand Pallium's schema to use it.

## Why

Today the only agent-facing retrieval tool (`pallium_query`) is framed as memory
retrieval, exposes just `container_ref`/`thread_ref`/`actor_ref`/`visibility`, and
does not distinguish who initiated the call — so agent-initiated lookups are
invisible in the audit log and indistinguishable from proactive injection. Bet 1
needs a first-class "search prior work" affordance the agent chooses to use, and a
signal that distinguishes a deliberate agent pull from a proactive push. Since
Experiment 1 tests whether agents *naturally* use the capability, the tool must be
dead simple by default — a confusing schema-heavy surface would confound low
adoption (tool too hard) with the real question (history not useful).

## In Scope

- a `pallium_search_history` MCP tool + client method invoking the raw search mode
- default surface is a single query ("search prior work for X") + scope; the raw
  filters (`source_type`/`role`/`artifact_kind`/`work_refs`) are **optional advanced
  parameters**, not required to call the tool
- record the call as an agent-issued MCP lookup with a distinct origin
  (e.g. `agent_pull` / `mcp_pull`) — a new attribution value, **not** the existing
  `user_explicit` label. This origin marks *that an agent issued a lookup*; it does
  **not** assert the agent decided independently. Whether the user directed the
  search ("search our history for X") vs the agent decided on its own is a
  **retrospective judgment** from the preceding conversation, not a deterministic
  tool field (see `add-historical-lookup-funnel-telemetry`)
- return the `lookup_event_id` from the measurement contract so the caller/turn can
  be linked to exposures and follow-up
- skill copy / CLAUDE.md guidance describing the deliberate-lookup workflow
  (`current work → historical lookup → prior work → optional source expansion`)

## Out of Scope

- the retrieval mode itself (`add-raw-historical-search-mode`)
- source-context expansion (`add-source-context-expansion`)
- automatic/proactive invocation — this is an agent-pull affordance
- measuring adoption (that's `add-historical-lookup-funnel-telemetry` + Experiment 1)

## Done When

1. An agent can call a dedicated historical-search tool with just a query and get
   ranked prior turns; the filter surface is available but optional.
2. The lookup is recorded in `query_audit_log` with an agent-pull origin that
   distinguishes it from proactive injection, returns a `lookup_event_id`, and does
   not itself assert independent-vs-directed decision (that is judged retrospectively).
3. Skill/CLAUDE.md guidance tells the agent when to use it.

## Experiment note

Experiment 1 should compare the **base** arm (block-level permit nudge) against
**strong** guidance (base plus a "call it first" directive): both arms carry a
permit, so the delta isolates the call-first directive. Heavy "when to search"
prompting measures instruction
adherence as much as genuine agent recognition, so the guidance level is itself a
variable to control, not a fixed given.

## Notes

Guarded paths: `app/mcp/`, integration skills, `api/`. Start with `/agent-workflow`.
This tool is the subject of Experiment 1 (does the agent pull unprompted?).
Execution context: `docs/designs/015-vnext-historical-work-execution.md` (Phase 1).
