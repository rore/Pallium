---
id: idea-reconcile-unprompted-pull-direction-signal
title: Reconcile the two conflicting "unprompted-pull / direction" signals
status: superseded
priority: low
commitment: uncommitted
---

> **Superseded 2026-08-18 → `idea-pull-real-corpus-validation`.** The reframed headline (net value of
> agent-filtered pull, not unprompted-pull rate) demotes direction to a secondary signal. The one
> durable requirement — a single documented definition of "agent-decided" direction with a divergence
> check — is folded into the consolidated experiment's measurement contract. No longer a standalone gate.

## Summary

The decision-agent harness (`evals/history_pull_decision/`) and the retrospective
reuse judge (`evals/historical_lookup_judge.py`) each compute a "was this pull
user-directed or agent-decided?" signal — and on the same run they DISAGREE
materially. On a first real run (7 scenarios × 3 seeds, 15 lookup events):

- Harness `unprompted_pull_rate = 0.60` (≈9/15 agent-decided).
- Judge `direction_split = {agent_decided: 1, user_directed: 14}` (≈1/15 agent-decided).

Both claim to measure the make-or-break vNext thesis (design 015 decision-point 1:
*do agents pull historical work UNPROMPTED?*), but they measure different things and
cannot both be the KPI.

## Why

The unprompted-pull rate is the headline number the whole historical-lookup strategy
rides on. Two harnesses producing ~0.60 vs ~0.07 for the same events means at least
one definition is wrong for the KPI's purpose — and today nothing flags the conflict,
so whichever is quoted first becomes "the result." This must be reconciled before any
simulated OR live unprompted-pull rate is reported as a decision input.

Root of the divergence (hypothesis, to confirm):
- The **harness** derives direction from the agent's DECISION CONTEXT — was the pull
  tool-call scripted/instructed by the scenario, or self-initiated by the agent?
- The **judge** derives direction from reading CONTEXT-BEFORE turns — did the USER
  explicitly ask to recall/look up past context? A scenario whose user turn merely
  references the past ("what did we settle on before?") reads as user_directed to the
  judge even when the agent's decision to CALL the tool was unprompted.

These are both legitimate but answer different questions ("was the tool-call scripted?"
vs "did the user reference the past?").

## In Scope

- Pin down ONE definition of "unprompted / agent-decided" that matches decision-point 1's
  intent, and document it in the measurement contract.
- Make the harness and the judge compute direction consistently against that definition
  (or explicitly record them as two named, different metrics — never conflated as "the"
  unprompted rate).
- A cross-check assertion / report field that surfaces the disagreement when the two
  signals diverge beyond a tolerance, so it can never silently pass again.

## Out of Scope

- The reuse-ladder rung labels (incorporation/influence) — separate signal.
- Growing the scenario set or the gold fixture (tracked elsewhere).

## Done When

1. A single documented definition of unprompted/agent-decided direction exists in the
   measurement contract.
2. Harness and judge agree with that definition (or are recorded as distinct, clearly
   named metrics), and a divergence check exists.
3. The first simulated unprompted-pull rate is re-reported under the reconciled
   definition.

## Notes

Surfaced by the first real decision-agent run + judge pass (2026-08-16), scratch DB at
`.local/research/history_pull_decision.db`, reports in `.local/research/`. Related:
`idea-history-pull-decision-agent-harness` (built the harness, Done),
`idea-reuse-judge-calibration` (the rung-label calibration story, separate signal).
