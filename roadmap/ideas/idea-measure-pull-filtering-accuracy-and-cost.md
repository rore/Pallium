---
id: idea-measure-pull-filtering-accuracy-and-cost
title: Experiment 1 (sharpened) — is indiscriminate-but-agent-filtered pull net-positive?
status: queued
priority: high
commitment: uncommitted
---

## Summary

The 2026-08-16 validation reframed the vNext make-or-break. It is NOT "will agents pull?"
— a guided agent readily (over-)probes: opportunity_pull_rate 1.0, and no_opportunity_pull_
rate 0.75 on neutral tasks. And raw search returns non-empty results even when nothing is
relevant. So the pull model's distinctive hypothesis is **agent-in-the-loop filtering**:
the agent, not a Pallium-side score, decides what to keep. The open question becomes:

> **Is indiscriminate-but-agent-filtered pull actually good product behavior — does its
> benefit exceed its context/latency cost, and does irrelevant history contaminate the
> agent's reasoning?**

This replaces the old Experiment-1 framing.

## Why

The proactive-injection score is non-discriminative (relevant vs not-relevant vector score
878 vs 877), so a Pallium-side confidence threshold is a dead route — do NOT build one yet.
The distinctive bet of pull is that the agent filters noise better than a background gate
did. If it does, pull solves the old relevance problem. If plausible historical noise
contaminates the agent's work, we have merely moved the relevance problem one step
downstream while adding per-task cost. That contamination outcome is the thing to catch.

## In Scope — measure four things

1. **Pull selectivity** — opportunity pull rate vs no-opportunity pull rate (does the agent
   pull discriminately, or on ~everything?).
2. **Returned-result precision** — when the pull returns history, is any of it actually
   useful for the task?
3. **Agent filtering** — when the returned results are irrelevant, does the agent's FINAL
   answer correctly discard them (rather than let them shape the work)?
4. **Cost** — extra context tokens, tool calls, and latency per substantive session.

Plus an explicitly tracked **dangerous outcome**:

> **irrelevant historical result → materially influences the agent's work** (the pull
> equivalent of bad proactive injection).

## Constraints / method

- **Run against REAL history, not only synthetic scenarios.** The contamination risk only
  shows up against genuinely-ambiguous real noise; hand-seeded relevant/irrelevant history
  cannot stress the agent's filter honestly. Use the decision-agent harness for discovery
  (see `evals/history_pull_decision/scenarios_cold.json` + `scenarios_overpull_control.json`)
  but validate on real containers.
- **Do NOT build a new Pallium-side confidence threshold** as part of this — first establish
  whether agent-in-the-loop filtering works. That is the distinctive hypothesis under test.
- Report with Wilson bands; scale beyond the current small (n=4–30) synthetic sets.

## Out of Scope

- Any production retrieval/injection change.
- Reuse-ladder rung labelling (separate signal).
- Re-litigating raw-vs-derived representation quality — prior FAIR studies already cover it
  (~29% misleading; raw≈derived tied at top-5); this run's larger magnitudes were biased.

## Done When

1. Pull selectivity, returned-result precision, agent filtering accuracy, and per-session
   cost are all measured and reported (with bands), on REAL history.
2. The contamination outcome (irrelevant result materially influencing the agent) has an
   explicit measured rate.
3. The result is a clear go/no-go on: is indiscriminate-but-agent-filtered pull net-positive
   vs the (now-deprecated) proactive injection?

## Notes

Surfaced + reframed by the injection-vs-pull validation cycle
(`docs/research/2026-08-16-injection-vs-pull-validation.md`) and a follow-up review. Fair
prior context: `docs/context/strategy-vnext.md`, `docs/designs/015-vnext-historical-work-
execution.md`, `docs/designs/006-vector-retrieval-validation-report.md`. Related:
`idea-reconcile-unprompted-pull-direction-signal`, `idea-history-pull-decision-agent-harness`
(Done).
