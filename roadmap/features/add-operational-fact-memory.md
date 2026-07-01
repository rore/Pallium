---
id: add-operational-fact-memory
title: Operational fact memory — reduce agent rediscovery waste
status: shipped
priority: medium
commitment: shipping
milestone: 2026-07-shaped-memory-contract
shipped_at: 2026-07-01
---

> **Shipped 2026-07-01** as W4 of the [Shaped Memory Contract milestone](milestone-shaped-memory-contract.md).
> Phase 0 verification spike resolved: Surface B (UserPromptSubmit,
> both integrations), Bash-primary predicate, files_read secondary,
> apply_patch deferred pending Codex live-DB evidence.
> Five PRs merged (a0ef64c → b5bf26e):
>
> - PR 0 (a0ef64c) — docs reconciliation, Phase 0 outcome frozen.
> - PR 1 (afa8766) — derivation predicate + shared redaction helper (83 tests).
> - PR 2 (c9f42cd) — routing gate + partial indexes + `operational_intent` signal (89 tests).
> - PR 3 (dcc9cd5) — derivation wiring + backfill scaffolding + Invariant-1 diff-grep (50 tests).
> - PR 4 (b5bf26e) — narrow-target scenarios 1+2+negative wired end-to-end (14 tests).
>
> Milestone acceptance met: scenarios 1+2 pass with cross-integration
> parity; zero proactive `operational_fact` injections verified with
> positive-control regression test; every scenario carries the
> `# measures:` header; Invariant 1 code-level guard active.
>
> Deferred to follow-ups: full delivery-side end-to-end pass
> (`timing='on_time'` vs current `write_only`); Codex `apply_patch`
> predicate branch (PR 5, contingent on Codex live-DB evidence);
> slot-scoped supersession with agent_explicit priority; backfill
> live-DB corpus scan + `--commit` persistence.

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

1. ✅ Phase 0 verification spike complete (2026-07-01,
   `.local/milestone-progress-2026-07/w4-phase0-spike-2026-07-01.md`).
2. ✅ Operational facts derived from `agent_work_trace_turn` metadata
   without altering capture (`semantic/operational_fact.py`,
   `semantic/agent_work_trace.py` wiring).
3. ✅ Facts surfaced on-demand via routing gate + `operational_intent`
   signal; zero proactive injections enforced by three-layer guard
   (config default + gate built-in default + audit-log invariant test).
4. ✅ Regression covers the rediscovery scenario end-to-end
   (`evals/narrow_target_claude_code/scenario_01_repeat_failed_command.py`,
   `scenario_02_recall_python_on_windows_constraint.py`,
   `scenario_negative_no_operational_fact.py`; W3-style write-side
   PASS, delivery-side `write_only` with honest diagnostic).

## Notes

Shipped as five sequenced PRs under the Shaped Memory Contract
milestone, W4. Every PR passed architect design review + independent
code review before merge. Zero regressions across the 236 W4-specific
tests added (2686 → 2922 total).
