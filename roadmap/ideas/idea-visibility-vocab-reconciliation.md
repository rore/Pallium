---
id: idea-visibility-vocab-reconciliation
title: Reconcile visibility vocabulary before shared-derivation
status: queued
priority: medium
commitment: uncommitted
milestone: pallium-vnext-p3
---

## Summary

Reconcile the implemented visibility vocabulary (`public | container | private |
global`) with the design-007 contract (`public | limited | user`) before building
explicit shared-memory derivation, so Phase 4 sharing is built on an unambiguous
contract.

## Why

The shipped sharing foundation added `global` (same-actor cross-container) — a
primitive that is ahead of / outside the documented phase-1 contract and is the
de-facto cross-container continuity mechanism today. Design 007 Phase 2
(`add-explicit-shared-memory-derivation`) assumes the documented `visibility_context`
vocabulary. Building shared derivation on a drifted contract risks auditing,
revocation, and false-share bugs.

## In Scope (outline)

- decide the canonical vocabulary and map the implemented terms to it
- align `core/visibility.py`, schema, and design 007 wording
- preserve current enforcement semantics (enforce-before-ranking, fail-closed)
- update the sharing roadmap items to reference the reconciled contract

## Out of Scope

- the shared-derived-memory object itself (`add-explicit-shared-memory-derivation`)
- bounded cross-container reuse (`add-cross-container-bounded-memory`)

## Done When

1. One documented visibility vocabulary that matches the implementation.
2. Design 007 and the sharing roadmap items reference it consistently.
3. No enforcement behavior regressions; visibility violations = 0.

## Notes

Gate: prerequisite for Phase 3 (Experiment 4) — clean the visibility contract
before any cross-user work, including the raw-first `idea-cross-user-raw-history-value`
experiment. Precedes `add-explicit-shared-memory-derivation`.
Execution context: `docs/designs/015-vnext-historical-work-execution.md` (Phase 3).
