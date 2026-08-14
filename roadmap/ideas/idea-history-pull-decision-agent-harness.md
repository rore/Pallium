---
id: idea-history-pull-decision-agent-harness
title: Decision-making agent harness for unprompted history-pull (non-circular Experiment 1)
status: done
priority: high
commitment: committed
milestone: pallium-vnext-p1
---

## Summary

Build a simulation harness in which an LLM agent is given the history-search and
source-expansion tools and, for each scenario, **decides on its own** whether to
pull prior history and whether the pulled context helped — then have the
retrospective judge label the result. This is the only way to produce
Experiment-1-shaped data (lookup rate, unprompted-pull rate, did-it-help)
**without waiting for real usage to accumulate**, and the only way to make those
numbers non-circular.

## Why

The vNext funnel plumbing, rollup math, and governance invariants are all
demonstrably correct and can be exercised at volume today. But the make-or-break
question the strategy rides on — *do agents pull historical work unprompted, and
does it help?* (design 015 decision-point 1) — cannot be simulated by any
existing harness: they either script the pull themselves (so the answer is
authored, not measured) or only exercise the proactive-injection path, which
never calls the pull tools. A decision-making agent (given the tools, choosing
when to use them) is net-new behaviour and the missing piece for validating the
thesis ahead of, or alongside, slow live accumulation.

## In Scope

- A scenario-driven harness where an LLM agent, given a task + prior turns and
  the history-search / source-expansion tools, chooses whether/when to call
  them; the calls flow through the real service so funnel events persist
  naturally.
- Metrics: lookup rate, unprompted-pull rate, lookup->useful-result rate; feed
  the persisted events into the existing rollup + judge.
- Run the existing reuse-ladder judge (multi-seed, report kappa + Wilson) over
  the agent-produced lookups rather than hand-seeded labels.
- Reuse existing scenario/agent scaffolding where it fits rather than a new
  stack.

## Out of Scope

- Replacing live measurement — this complements it; a simulated pull rate is a
  proxy, not the live gate.
- Rung-3 downstream benefit (controlled-exposure-only).
- Any change to production retrieval/injection behaviour.

## Done When

1. An agent that is merely *permitted* (not scripted) to pull history produces
   funnel events, yielding a first simulated lookup / unprompted-pull rate.
2. The reuse ladder is labelled by the real judge over agent-produced lookups,
   reported with kappa + Wilson bands (calibrated per the judge-calibration
   item).
3. The harness is documented and rerunnable, with an explicit statement of how a
   simulated rate relates to (and cannot fully substitute for) the live gate.

## Notes

Identified as the true simulation gap in the vNext eval-capability assessment.
Depends on the shipped P1 pull/expand tools and the funnel/rollup. Strongest
paired with `idea-reuse-judge-calibration` (labels are only as good as the
calibrated judge). Net-new behaviour -> its own Work Record when scoped.
