---
id: add-semantic-regression-set
title: Add a committed semantic regression set
status: done
priority: high
commitment: committed
milestone: Done
---

## Summary

Add a maintained semantic regression set that reflects the current event model and lets Pallium compare prompt variants, model choices, and typed-memory behavior over a stable batch.

## Why

Semantic quality is now the main product risk. The eval harness exists, but the roadmap should treat the labeled regression set itself as a product asset so prompt and extraction changes can be measured instead of guessed.

## In Scope

- commit a larger labeled eval batch for message events and assistant artifacts
- record expected semantic outcomes for decision, investigation, and non-memory cases
- make prompt and model comparisons easy to run against the same batch
- document baseline metrics for the chosen prompt/model path

## Out of Scope

- provider-agnostic benchmark infrastructure beyond the current eval harness
- automatic CI gating on semantic metrics
- large-scale production replay evaluation

## Done When

1. A committed labeled eval set exists for the current event model.
2. The repo documents the expected baseline prompt/model metrics on that set.
3. Future semantic changes can be compared against the same batch without ad hoc fixture creation.

## Notes

Completed on 2026-03-09.
Current recorded baseline: `gpt-5-mini` + `strict_decision_v2_source_aware` at `27 / 30` overall correct.
See `evals/semantic/baseline.md`.
