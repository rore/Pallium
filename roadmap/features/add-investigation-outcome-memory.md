---
id: add-investigation-outcome-memory
title: Add investigation outcome memory
status: queued
priority: high
commitment: committed
milestone: Next
---

## Summary

Add a second typed memory object for investigation outcomes so important diagnostic or learned information does not collapse into `discussion_summary`.

## Why

The current semantic layer can promote `decision`, but many high-value agent events are findings, conclusions, or root-cause statements rather than decisions. Without a second typed memory, Pallium loses important structure on the exact event types it now ingests.

## In Scope

- add `investigation_outcome` as a promoted memory type
- add the supporting typed candidate path in deterministic and LLM-backed extraction
- make query results surface `investigation_outcome` as a first-class memory hit
- expand semantic eval fixtures and assertions for decision vs investigation separation

## Out of Scope

- broad ontology expansion across many new memory types
- tiered consolidation of investigation memories
- deep graph reasoning over findings and incidents

## Done When

1. Investigation-like source items can promote a typed `investigation_outcome` memory object.
2. Decision-like and investigation-like inputs are distinguished in tests and evals.
3. `/query` can return investigation outcomes as memory hits with evidence.

## Notes

Sources: `roadmap/scope.md`, `docs/context/architecture.md`, `docs/context/lessons.md`
