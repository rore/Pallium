---
id: add-operational-fact-memory
title: Operational fact memory — reduce agent rediscovery waste
status: paused
priority: medium
commitment: shaping
milestone: Next
---

> **Paused 2026-06-27** pending outcome of the abstention-policy work in
> [`docs/specs/2026-06-27-injection-policy-abstention.md`](../../docs/specs/2026-06-27-injection-policy-abstention.md).
> The data analysis under that spec showed:
> 1. The dominant injection failure is targeting, not coverage — adding
>    another extracted memory type without an on-demand retrieval path
>    would land in the same off-topic-injection failure mode (~55% bad
>    rate, ~92% off-topic).
> 2. The operational-fact spec itself already flagged this risk: "if no
>    on-demand surfacing path exists, storing facts is dead code."
> 3. Phase 4 of the abstention plan establishes deterministic triggers
>    for on-demand retrieval. Operational-fact memory should be revisited
>    only after those triggers are live and proven, so it can ship as a
>    trigger-targeted type rather than a proactive one.
>
> Resume gate: Phase 4 trigger pass-bar met; consider whether
> operational-fact content is best modeled as its own type or absorbed
> into existing `decision`/`task_checkpoint` types under triggered recall.

## Summary

Add a derived memory class for cross-session operational orientation (Python
path, test command, package manager, local service port, wrapper script,
shell behavior, etc.), owned by the existing `agent_work_trace` semantic
package. Goal: a fresh agent session starts from known evidence instead of
repeating reconnaissance from zero.

## Why

The recurring waste pattern is **not** mainly "an agent ran a failed command
and should avoid it next time." The higher-value pattern is the
*successful-but-rediscovered-each-session* operational fact: session A
spends tool calls discovering how the repo or machine works, uses the
result successfully, then session B repeats the same reconnaissance.

Both shipped Claude Code memory plugins surveyed (`ClawMem`,
`agentmemory`) ship `PreToolUse` hooks for `Edit|Write|Read|Glob|Grep` but
neither intercepts `Bash` based on prior session evidence. The capture
pipeline (Stop hook + `agent_work_trace_turn` metadata, see
[semantic/agent_work_trace.py](../../semantic/agent_work_trace.py)) is
already in place; what's missing is the derivation that turns those
traces into reusable operational facts and the surfacing that delivers
them at the right moment without crowding existing memory.

Must be implemented as a generic memory-system capability, not as
scenario-specific behavior keyed to product names, ticket ids, tool names,
or one-off phrasing.

## Design Spec

Full design lives in
[docs/specs/2026-05-31-operational-fact-memory-design.md](../../docs/specs/2026-05-31-operational-fact-memory-design.md).
That document is the source of truth for scope, type schema, derivation
rules, surfacing strategy, and Phase 0 verification gates.

## In Scope

- New derived memory class for operational orientation, owned by
  `agent_work_trace`
- Derivation from existing `agent_work_trace_turn` metadata — no new
  capture surface
- Surfacing rules that deliver facts only when relevant; no crowding of
  existing continuity memory

## Out of Scope

- Failed-command-avoidance memory (already covered by existing types)
- New `PreToolUse` hooks or capture pipeline changes
- Scenario- or product-specific keying

## Done When

1. Phase 0 verification spike from the spec is complete and the spec is
   updated with direct file references.
2. Operational facts are derived from `agent_work_trace_turn` metadata
   without altering capture.
3. Facts are surfaced at the right moment in fresh sessions and do not
   crowd existing memory cards.
4. A regression covers the rediscovery scenario end-to-end.

## Notes

Status is `proposed` until Phase 0 lands. No code changes before the
verification spike updates the spec.
