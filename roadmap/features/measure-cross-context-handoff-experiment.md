---
id: measure-cross-context-handoff-experiment
title: Measure cross-context handoff (Experiment 2)
status: done
priority: medium
commitment: committed
milestone: pallium-vnext-p2
---

## Summary

Experiment-2 measurement harness (measurement only, no mechanism): does a
**pointer+pull** handoff — an identified source session plus the shipped P1
`source_only` search and `GET /source/{id}/context` expansion — let a receiving
session continue prior work as correctly as the manual baselines
(paste-a-summary / read-the-transcript), at lower user-orchestration cost?

This is the "prove the value first" gate carved out of
`idea-cross-context-work-continuity`. It builds no continuity mechanism; it
measures whether the primitives P1 already ships are enough.

## Why

The parent idea's sequencing is explicit: prove identified-source handoff before
investing in automatic session correlation or an agent-handoff dimension. A
measurement harness that compares pull+expand against the manual rituals it would
replace is the smallest valuable slice, and it reuses primitives P1 already ships.

## In Scope

- `evals/continuity_handoff_benchmark.py`: four context-source arms
  (`no_memory`, `pull_backed`, `manual_transcript`, `manual_summary`) feeding one
  reused continuation-generation + rubric-scoring path (from
  `work_resumption_benchmark`), so arms differ only in context source.
- `pull_backed` arm assembled from the **actual API response surface**:
  `source_only` search → top-K source hits → `/source/{id}/context` expansion.
- A deterministic **orchestration-cost proxy** = user-supplied context tokens per
  arm (pull's raw context is pulled agent-side and does not count as user cost).
- **≥3-seed consensus** verdict (never single-seed); deterministic scorer.
- `evals/continuity_handoff/scenarios.json`: authored cross-session scenarios,
  private + container-scoped, including a no-value guard.
- Deterministic self-test (`tests/test_continuity_handoff_benchmark.py`), no live
  LLM.
- Committed report: `docs/reports/vnext-p2-continuity-handoff-experiment.md`.

## Out of Scope

- Any continuity **mechanism**: session correlation across `session_id`s,
  `agent_ref` as a handoff/routing dimension, eager-synthesis continuation
  packaging. These stay in `idea-cross-context-work-continuity`, deferred until
  this experiment's value signal holds up under harder inputs.
- Modifying `work_resumption_benchmark.py` (reused by import only) or the
  historical-lookup measurement/judge harnesses.

## Done When

1. The harness runs the four arms with a multi-seed consensus verdict and emits
   results/summary/report; the deterministic self-test passes with no live LLM.
2. A real-provider run reports genuine per-arm correctness and
   orchestration-cost, with a consensus winner.
3. The committed report states the result and the honest realism/variance
   ceiling.

## Notes

Result (run `real-run-s3-v2`, `claude-sonnet-4-6`, 3 seeds): pointer+pull tied the
manual baselines on correctness (rubric saturates at 6.00 ± 0.00 for all
context-bearing arms) and won the consensus verdict in all value scenarios at
strictly lower user-orchestration cost (~19.75 vs 55.0/70.75 tokens); the
falsifiable no-value guard held. Discriminator is orchestration cost, not
correctness. See the report for the ceiling (authored scenarios bound realism; no
session-identity or cross-agent claim). Whether to invest in the deferred
mechanism is decided against these results, per
`idea-cross-context-work-continuity`.
