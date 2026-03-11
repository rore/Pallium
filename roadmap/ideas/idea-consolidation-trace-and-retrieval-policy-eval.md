---
id: idea-consolidation-trace-and-retrieval-policy-eval
title: Add consolidation trace and higher-level retrieval-policy evaluation
status: idea
priority: medium
commitment: uncommitted
---

## Summary

Extend tiered-memory evaluation beyond construction and strategy selection by recording richer merge rationale and explicitly testing when `pattern_memory` should beat lower-level memory or source evidence.

## Why

Tiered memory is only worth productizing if:

- grouping remains inspectable and trustworthy
- false merges are diagnosable
- retrieval uses higher-level memory in the right situations

Recent research and current Pallium experience both point to the same unresolved problem:

- principled consolidation policy and retrieval policy are still the hardest part of higher-level memory

## In Scope

- store richer consolidation trace such as:
  - anchor memory id where applicable
  - grouping signals that fired
  - merge rationale / confidence
- extend eval output to show why a higher-level group formed
- add benchmark cases where:
  - broad recurring questions should prefer `pattern_memory`
  - precise factual questions should still prefer lower-level memory or source evidence
  - evidence-heavy questions should not be answered only from `pattern_memory`

## Out of Scope

- changing the public query API
- vector-assisted consolidation policy
- broad new higher-level memory ontology

## Notes

This is a likely follow-up after the current retrieval-layer explainability work, and after more evidence accumulates about how useful the first `pattern_memory` default really is.
