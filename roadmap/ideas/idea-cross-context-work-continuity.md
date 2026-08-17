---
id: idea-cross-context-work-continuity
title: Work continuity across sessions and agents
status: queued
priority: medium
commitment: uncommitted
milestone: pallium-vnext-p2
---

## Summary

Make continuing work from another context easy enough to reduce the manual
"summarize this so I can give it to the other session" / "go read that transcript"
ritual, while preserving correct understanding of the prior work. Covers
same-agent new session, parallel sessions, and Claude↔Codex handoff.

## Why

Cross-session transfer is common in the corpus but orchestrated manually today.
Two concrete gaps: (1) each new session mints a fresh `thread_ref`, so the
`resumed_session` fast-path doesn't fire for genuinely new sessions — cross-session
continuity leans entirely on container-scoped retrieval + work_ref affinity; and
(2) cross-agent continuity is only an emergent side effect of shared
`container_ref`/`actor_ref` — `agent_ref` is stored but is not a routing/handoff
dimension and there is no explicit handoff packaging.

## In Scope (outline — detail after Experiment 1)

Test the simplest form first, and only invest in mechanism if it beats the manual
baseline:

- **First mechanism to test — pointers before synthesis:** a source session is
  *identified* by the user or agent (no automatic session-identity solving); Pallium
  hands the receiving session **compact pointers/handles** to the relevant prior work
  (reusing the P1 lookup + source-context-expansion primitives), and the receiving
  session **pulls the raw context it needs on demand**. Measure against the manual
  baselines (paste-a-summary / read-the-transcript) on user-orchestration cost and
  correctness of understanding.
- **Then compare an eager-synthesis handoff package** as a second mechanism — tested
  against pointer+pull rather than assuming either wins; pointer+pull is tried first
  because it reuses primitives P1 already ships.
- **Only if that wins (invest in mechanism):** stable work/session correlation
  across `session_id`s so resumption ranking spans sessions automatically; make
  `agent_ref` a first-class handoff dimension (Claude↔Codex); richer explicit
  continuation packaging.
- build on shipped `work_refs`, `task_checkpoint`, `resumed_session`

## Out of Scope

- cross-*user* sharing (Phase 4 — visibility-bounded)
- assuming cross-agent frequency; instrument before investing heavily there
- proactive injection beyond high-confidence resumption

## Done When

1. A new session in the same work continues with prior progress/blockers/next-step
   without the user re-explaining.
2. Pallium-supported continuation beats the manual baselines (summary / pointer /
   raw transcript) on user-orchestration cost while preserving correct
   understanding.

## Notes

Gate: Experiment 2. Depends on Phase 1 (lookup/expand); independent of the
continuous derived eval. Sequence within the item: prove the value of
identified-source handoff before building automatic session correlation or
`agent_ref` routing — don't start by solving session identity.
Execution context: `docs/designs/015-vnext-historical-work-execution.md` (Phase 2).
Related shipped work: `add-work-ref-cross-surface-continuity`, design 013.

**Experiment 2 promoted + delivered:** the measurement slice is now the committed
feature `measure-cross-context-handoff-experiment` (harness + authored scenarios
+ report `docs/reports/vnext-p2-continuity-handoff-experiment.md`). On authored
scenarios, identified-source **pointer+pull** matched the manual baselines on
correctness at markedly lower user-orchestration cost. This idea now tracks only
the **deferred mechanism** (stable session/work correlation across `session_id`s,
`agent_ref` as a first-class handoff dimension, eager-synthesis continuation
packaging), to be invested in only if that value signal holds under harder inputs.

## Harder-scenario DoD (external review item 13)

The authored Experiment-2 scenarios were easy enough that all context-bearing arms saturated
correctness — that proves context helps, NOT that a new continuity mechanism is necessary. Before any
mechanism proceeds, add scenarios that expose a repeatable failure ordinary pull cannot solve:

- several plausible prior sessions;
- stale handoff summary plus a newer corrective raw turn;
- unfinished work with ambiguous status;
- a failed earlier approach that must not be repeated;
- renamed files or changed architecture;
- two agents with divergent partial work;
- task resumed after substantial unrelated activity;
- private prior context that must not cross actors;
- very long history where only a small episode matters.

**Compare arms:** (1) no historical context; (2) raw historical pull; (3) derived-memory injection;
(4) raw plus derived; (5) any proposed continuity mechanism.

**Gate:** a new mechanism proceeds only if it produces a meaningful downstream improvement over ordinary
pull, after accounting for token cost, latency, and contamination.
