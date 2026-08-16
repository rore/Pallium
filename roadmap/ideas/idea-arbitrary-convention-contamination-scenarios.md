---
id: idea-arbitrary-convention-contamination-scenarios
title: Contamination probe — arbitrary-convention scenario set (the history-decisive regime)
status: queued
priority: high
commitment: uncommitted
---

## Summary

Add a third `evals/pull_contamination/` scenario set whose correct answer A is a
PROJECT-SPECIFIC ARBITRARY CONVENTION that is NOT inferable from general engineering
best practice ("we use X here, though Y is equally valid"). This is the regime the
explicit-task and ambiguous-task passes both failed to reach.

## Why

Both prior passes reported ~0 contamination — but neither actually stressed filtering:
- Explicit-task (PR #31): the task text pinned A, so baseline ~1.0 A.
- Ambiguous-task (PR #32): the situational cues still let the agent reason to A from
  general knowledge, so baseline came out ~0.90 A (decision-first detector). Cue-determined,
  not history-determined.

The dangerous, and most REPRESENTATIVE, case for the vNext pull model is when the answer
is a project-local decision the agent CANNOT derive from best practice — so the no-history
baseline is a genuine coin-flip and pulled history is the only tie-breaker. Only there can
"relevant history helps" and "wrong history contaminates" be measured cleanly. This is also
what many real Pallium memories ARE (project-specific decisions/conventions).

## In Scope

- New `scenarios_arbitrary.json` (`case: "arbitrary-convention"`): each task states a
  situation where A and B are BOTH defensible under general knowledge, and A is correct ONLY
  because of a stated-nowhere project convention. Target: no-history baseline near 50/50
  (verified empirically, not assumed) so history has room to move the answer.
- Reuse the existing harness + BOTH detectors + the differential (`relevant_lift`,
  `contamination_harm`) unchanged.
- Verification: adversarial clean-context review of the set BEFORE the LLM run (as in #32);
  then a real pass. Design invariant this time: baseline must NOT be pinned — if baseline
  A-rate is far from ~0.5, the scenario leaks a general-knowledge cue and must be reworked.

## Out of Scope

- Real-corpus validation (separate follow-up once a scenario set reaches the split regime).
- Production behavior changes.

## Done When

1. A scenario set whose measured no-history baseline is genuinely split (not pinned to A or B).
2. A real pass reports `relevant_lift` and `contamination_harm` with bands under the
   decision-first detector, so the causal-influence question ("relevant helps, wrong hurts")
   is actually answerable.
3. Findings recorded honestly, including whether contamination appears once history is decisive.

## Notes

Follow-up to PR #31 (explicit) and #32 (ambiguous). Evidence for why the prior sets missed
the regime: `.agent-workflow/tasks/pull-contamination-ambiguous-task-variant.md` Evidence
section (baseline ~0.90 A). No internal/product names in scenarios.
