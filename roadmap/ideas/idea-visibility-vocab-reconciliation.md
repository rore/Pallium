---
id: idea-visibility-vocab-reconciliation
title: Reconcile visibility authorization semantics + raw-sharing grant contract
status: queued
priority: medium
commitment: uncommitted
milestone: pallium-vnext-p3
---

## Summary

Turn the visibility drift into an **authorization-semantics** task, then define an
explicit raw-history sharing/grant contract, before any cross-user work. This is not
a naming cleanup: the implemented model has no per-user grant, so cross-user raw
sharing cannot be done safely on top of it as-is.

## Why

The shipped enforcement (`core/visibility.py`) implements
`public | container | private | global`, while design-007 documents
`public | limited | user`. More importantly, the *semantics* don't support consented
cross-user sharing: a public candidate requires `actor_ref is None` (raw source items
keep their producer actor); a private/unspecified query sees everything in the same
container regardless of actor (container-wide, not per-user consent); and
`core/filters.py` actor filters exclude another user's raw sources. Building
cross-user sharing on this — or treating "same container" as consent — risks
auditing, revocation, and false-share bugs. The reconciliation must therefore land an
authorization model with an explicit grant, not just a shared vocabulary.

## In Scope (outline)

- decide the canonical authorization model and map implemented terms
  (`public|container|private|global`) to it, aligning `core/visibility.py`, schema,
  and design 007
- define an explicit **raw-history sharing/grant contract**: consent, target
  audience, revocation, provenance, access audit, fail-closed default
- preserve current enforcement guarantees (enforce-before-ranking, fail-closed) while
  adding per-user grant semantics distinct from container co-location
- update the sharing roadmap items to reference the reconciled contract

## Out of Scope

- the shared-derived-memory object itself (`add-explicit-shared-memory-derivation`)
- bounded cross-container reuse (`add-cross-container-bounded-memory`)
- the multi-user value experiment itself (`idea-cross-user-raw-history-value`)

## Done When

1. One documented authorization model matches the implementation, with per-user
   grant semantics distinct from container co-location.
2. An explicit raw-history sharing/grant + revocation contract exists (consent,
   audience, provenance, access audit, fail-closed).
3. Design 007 and the sharing roadmap items reference it consistently.
4. No enforcement regressions; visibility violations = 0, reported with attempted
   disallowed-access counts/types.

## Notes

Gate: prerequisite for Phase 3 (Experiment 4) — the authorization model and grant
contract must precede `idea-cross-user-raw-history-value` and any
`add-explicit-shared-memory-derivation` work.
Execution context: `docs/designs/015-vnext-historical-work-execution.md` (Phase 3).
