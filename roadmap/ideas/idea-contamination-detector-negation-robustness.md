---
id: idea-contamination-detector-negation-robustness
title: Make the decision-first contamination detector negation-aware
status: queued
priority: low
commitment: uncommitted
---

## Summary

`classify_answer_leading` in `evals/pull_contamination/harness.py` returns the choice whose
marker appears FIRST in the answer. That mis-scores an answer that leads with the REJECTED
option via negation ("Do not use synchronous REST; use a message queue" → first marker is
the B marker, but the choice is A).

## Why

Raised by CodeRabbit on PR #32. Verified as a NON-artifact on that run (all `chose_B` trials
were genuine "I will use optimistic concurrency"; the one negation-first answer led with the
CORRECT marker, so it scored right). Documented as a caveat, and both detectors are reported
so divergence is visible — but the detector is a reusable instrument and the next scenario set
(arbitrary-convention) may surface negation-first phrasings, so hardening is worth doing before
relying on it more heavily.

## In Scope

- A lightweight negation guard: if a negation cue ("not", "don't", "avoid", "rather than",
  "instead of") immediately precedes the earliest marker match (within a small char window)
  and not the other, treat the choice as the OTHER marker. Guard must be conservative — a
  wrong flip is worse than an occasional ambiguous.
- Tests over crafted negation-first answers (both directions) + the existing decision-first
  cases (must not regress).
- Optional: a small LLM-judge fallback for the residual, gated OFF by default (never the
  primary signal), consistent with the harness's deterministic-first stance.

## Out of Scope

- Replacing the deterministic detector with a judge (explicitly rejected design).

## Done When

1. Negation-first answers are scored to the actually-chosen option, with tests.
2. No regression on the existing decision-first and strict-detector tests.

## Notes

Evidence: `evals/pull_contamination/harness.py` `classify_answer_leading` (documents the
caveat). CodeRabbit PR #32 thread on `harness.py`.
