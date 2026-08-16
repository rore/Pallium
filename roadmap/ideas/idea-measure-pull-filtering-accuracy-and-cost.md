---
id: idea-measure-pull-filtering-accuracy-and-cost
title: Measure agent filtering accuracy on irrelevant pull returns + per-task probe cost
status: queued
priority: high
commitment: uncommitted
---

## Summary

The 2026-08-16 injection-vs-pull validation showed the vNext pull trigger is NOT the
bottleneck — a guided agent readily (over-)probes history even on cold tasks
(opportunity_pull_rate 1.0; no_opportunity_pull_rate 0.75). It also showed raw search
returns non-empty results even when nothing relevant exists (`lookup_to_nonempty=1.0` on
no-opportunity tasks). So the pull model's advantage over injection is NOT better ranking
— it is **agent-in-the-loop filtering**: the agent must reliably discard irrelevant
returns. That filtering accuracy, and the cost of probing on ~every task, are the new
make-or-break — and are currently UNMEASURED.

## Why

If the agent over-pulls (which it does) and raw retrieval is non-discriminative (returns
top-k regardless of true relevance, same as injection), then the entire value of the pivot
rests on the agent correctly ignoring irrelevant raw turns. If it instead gets misled by
plausible-but-irrelevant returns, we have merely moved the injection noise problem into the
pull path — while adding a per-task search+expand token/latency cost. Neither the filtering
accuracy nor the probe cost was measured in the validation cycle; they are the load-bearing
unknowns for whether pure-pull actually beats injection end-to-end.

## In Scope

- Extend the decision-agent harness (or a sibling) to measure, on no-opportunity scenarios
  where search returns irrelevant turns: does the agent's FINAL answer correctly ignore
  them (filtering accuracy / false-incorporation rate)? Use realistic neutral tasks (see
  `evals/history_pull_decision/scenarios_overpull_control.json`).
- Measure the per-task cost of the probe: added tokens (search + expand + filtering
  reasoning) and round-trips, on both opportunity and no-opportunity tasks.
- Report filtering accuracy + cost alongside the existing behavioural metrics, with Wilson
  bands; scale the scenario set beyond the current small n.

## Out of Scope

- Changing production retrieval/injection behavior.
- The reuse-ladder rung labelling (separate signal).

## Done When

1. A rerunnable measurement of agent filtering accuracy on irrelevant pull returns exists
   (does the final answer avoid using them), on a non-trivial scenario set.
2. Per-task probe cost (tokens + round-trips) is reported for opportunity and
   no-opportunity tasks.
3. The result is stated as a clear go/no-go input: does agent filtering + cost make
   pull-from-raw a net win over injection.

## Notes

Surfaced by the injection-vs-pull validation cycle (see
`docs/research/2026-08-16-injection-vs-pull-validation.md`). Related:
`idea-reconcile-unprompted-pull-direction-signal`,
`idea-history-pull-decision-agent-harness` (Done).
