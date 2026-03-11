---
id: add-explicit-shared-memory-derivation
title: Add explicit shared-memory derivation
status: queued
priority: medium
commitment: committed
milestone: Later
---

## Summary

Add the explicit shared-derived-memory path and provenance model that lets a semantic package publish broader-scope memory objects intentionally instead of widening local memory objects in place.

This slice should bridge the gap between native-scope enforcement and later cross-container reuse.

## Why

The privacy-aware scope foundation defines local visibility boundaries, but later cross-container memory also needs an explicit way to create broader-scope memory safely. Without a separate shared-memory path, Pallium would be forced to blur local memory and shared memory into the same object lifecycle, which would make auditing, revocation, and false-share debugging much harder.

## In Scope

- add a separate shared-derived-memory path rather than in-place scope widening
- define target scope and share provenance metadata for shared derived memory
- define package-owned share eligibility rules and policy versioning hooks
- preserve lineage from shared derived memory back to its supporting local memory and source evidence
- define lifecycle and supersession expectations for shared derived memory
- extend retrieval trace and evaluation outputs so runs can explain whether a returned object is local or explicitly shared
- add privacy-focused evaluation requirements for false-share and stale-share scenarios

## Out of Scope

- cross-container candidate grouping and reuse policy itself
- broad global sharing
- final user/application authorization integration
- forcing every package to publish shared memory
- replacing native-scope enforcement with shared-memory heuristics

## Done When

1. Pallium can represent a shared derived memory object separately from the local memory object it was derived from.
2. Shared derived memory records target scope, share provenance, and policy version metadata.
3. Shared derived memory keeps explicit lineage back to supporting local memory and source evidence.
4. Retrieval trace can distinguish local and shared returned memory objects.
5. Evaluation coverage includes false-share and stale-share scenarios.
6. Later cross-container memory can build on this contract instead of redefining sharing behavior.

## Notes

Dependency note:

- this feature should follow `add-privacy-aware-memory-scope-and-sharing-foundation`
- this feature should precede `add-cross-container-bounded-memory`

Design note:

- the broader architectural model for native scope, shared scope, and package ownership lives in `docs/designs/007-privacy-aware-scope-and-sharing.md`
