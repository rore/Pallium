---
id: idea-cross-user-raw-history-value
title: Scoped cross-user raw-history value
status: queued
priority: medium
commitment: uncommitted
milestone: pallium-vnext-p3
---

## Summary

Test the simplest useful form of shared knowledge first: can scoped historical
work — including raw history — produced by user/agent A materially help user B,
within visibility bounds, in a real multi-user deployment? Validate that value
before building any shared-derived-memory publication machinery.

## Why

The prior Phase-4 plan led with `add-explicit-shared-memory-derivation` and bounded
cross-container derived memory — a mechanism inherited from the older
derived-memory-first architecture. The vNext strategy no longer justifies starting
there. If raw historical lookup is the validated substrate (Phase 1) and derivation
is only a continuously-evaluated layer, then the first shared-knowledge question is
a *value* question, not a *mechanism* question: does one user's prior work help
another at all? Answer that with the substrate we already have (raw history +
visibility enforcement) before investing in publication, provenance, and lifecycle
for a shared-derived object.

## In Scope (outline — detail only after a real multi-user environment exists)

- a scoped cross-user lookup: user B searches, and visibility-permitted work from
  user A (raw history first) is eligible
- measure whether cross-user results are materially used by B (post-hoc judge, same
  method as the P1 funnel — not an online matcher)
- hard invariant: visibility violations = 0 (fail-closed, enforce-before-ranking)
- reuse `visibility_context` enforcement; no new sharing object required for this test

## Out of Scope

- shared-derived-memory publication (`add-explicit-shared-memory-derivation`) —
  only build it if this experiment or the continuous derived eval shows raw
  cross-user sharing is insufficient
- bounded cross-container derived memory (`add-cross-container-bounded-memory`)
- assuming cross-user frequency; instrument before investing
- any global/ambient sharing

## Done When

1. In a real multi-user deployment, user B can receive visibility-permitted prior
   work from user A via lookup, with 0 visibility violations.
2. We have a measured answer to "does scoped cross-user history materially help?"
   before committing to shared-derivation mechanism work.

## Notes

Gate: Experiment 4 (requires a genuine multi-user environment — validation-blocked
by design until then). Depends on Phase 1 lookup + visibility reconciliation
(`idea-visibility-vocab-reconciliation`). This item precedes, and may obviate,
`add-explicit-shared-memory-derivation`.
Execution context: `docs/designs/015-vnext-historical-work-execution.md` (Phase 3).
