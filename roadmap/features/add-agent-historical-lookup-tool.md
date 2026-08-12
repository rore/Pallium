---
id: add-agent-historical-lookup-tool
title: Agent-facing historical lookup tool
status: queued
priority: high
commitment: committed
milestone: pallium-vnext-p1
---

## Summary

Give agents a deliberate way to search prior agent work: an MCP tool
(`pallium_search_history`) that invokes the raw historical search mode with the
full filter surface and tags the query as an explicit, on-demand lookup, plus
skill/CLAUDE.md guidance on *when* to reach for it.

## Why

Today the only agent-facing retrieval tool (`pallium_query`) is framed as memory
retrieval, exposes just `container_ref`/`thread_ref`/`actor_ref`/`visibility`, and
does not pass `trigger_origin` — so agent-initiated lookups are invisible in the
audit log and indistinguishable from proactive injection. Bet 1 needs a first-class
"search prior work" affordance the agent chooses to use, and a signal that
distinguishes a deliberate pull from a proactive push.

## In Scope

- a `pallium_search_history` MCP tool + client method invoking the raw search mode
- expose the raw-search filters (source_type/role/artifact_kind/work_refs) and
  scope params to the agent
- send `trigger_origin="user_explicit"` (already a validated abstention-bypass
  label) so lookups are attributable
- skill copy / CLAUDE.md guidance describing the deliberate-lookup workflow
  (`current work → historical lookup → prior work → optional source expansion`)

## Out of Scope

- the retrieval mode itself (`add-raw-historical-search-mode`)
- source-context expansion (`add-source-context-expansion`)
- automatic/proactive invocation — this is an agent-pull affordance
- measuring adoption (that's `add-historical-lookup-funnel-telemetry` + Experiment 1)

## Done When

1. An agent can call a dedicated historical-search tool with the raw-search
   filters and receive ranked prior turns.
2. The lookup is recorded in `query_audit_log` with an origin that distinguishes it
   from proactive injection.
3. Skill/CLAUDE.md guidance tells the agent when to use it.

## Notes

Guarded paths: `app/mcp/`, integration skills, `api/`. Start with `/agent-workflow`.
This tool is the subject of Experiment 1 (does the agent pull unprompted?).
Execution context: `docs/designs/015-vnext-historical-work-execution.md` (Phase 1).
