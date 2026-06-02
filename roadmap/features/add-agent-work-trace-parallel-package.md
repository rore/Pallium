---
id: add-agent-work-trace-parallel-package
title: Agent work trace parallel semantic package
status: done
priority: medium
commitment: committed
milestone: Done
---

## Summary

Add a third production semantic package, `agent_work_trace`, that captures
the structural trail of agent work per turn (files read, commands run,
exploratory vs. productive split, failure classification) and aggregates
it into a compact `task_trace` memory object per session. Injected on
session resume so the next session skips orientation and goes directly
to the relevant location.

## Why

`agent_conversation_memory` captures what the agent *said*; it does not
capture what it *did*. Agents doing engineering work repeatedly pay to
rediscover the same things — which files matter, which commands work,
where a bug lives. The structural trail is what carries that signal, and
neither the continuity package nor the fact extraction package has a home
for it.

## In Scope

- `agent_work_trace` parallel semantic package
- Per-turn `agent_work_trace_turn` metadata captured by the Stop hook
- Aggregation into a `task_trace` memory object per session, with
  supersession on resume
- Deterministic structural trace (files, commands, path normalization,
  failure classes); optional best-effort LLM `outcome` summary
- Offline measurement via `{STATE_DIR}/{session_id}.work_trace_state.json`
  and an append-only `work_trace_metrics.jsonl`

## Out of Scope

- Duplicating findings extraction — decisions and investigation outcomes
  remain owned by `agent_conversation_memory`
- Real-time metric computation (deferred — v1 is offline analysis)
- `WebFetch` capture (excluded in v1)

## Done When

1. Package extracts and aggregates work trace from Stop hook metadata.
2. `task_trace` is injected on session resume and supersedes prior
   traces without destroying the measurement history.
3. Runs in parallel with `agent_conversation_memory` and
   `conversational_knowledge` via the multi-package processing
   infrastructure.

## Notes

Shipped. Design lives in
[docs/specs/2026-05-05-agent-work-trace-design.md](../../docs/specs/2026-05-05-agent-work-trace-design.md).
Implementation in [semantic/agent_work_trace.py](../../semantic/agent_work_trace.py).
This roadmap item was originally tracked only on the board; the file is
backfilled to keep the roadmap audit trail consistent with peer items.
