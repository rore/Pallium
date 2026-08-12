---
id: idea-derivation-fidelity-eval
title: Source → derived fidelity evaluation
status: queued
priority: medium
commitment: uncommitted
milestone: pallium-vnext-derived-eval
---

## Summary

Sample derived memory objects against the source turns they were built from and
score derivation quality directly — completeness, unsupported claims, drift, and
compression — independent of whether the memory was ever retrieved.

## Why

The strategy demotes derivation to a continuously-evaluated optimization layer,
and one live hypothesis is "maybe our derivation process itself is lossy." The
RAW/DERIVED/HYBRID shadow (`idea-raw-derived-hybrid-shadow-eval`) tells us whether
DERIVED loses *at retrieval time*, but it cannot separate a retrieval failure from
a derivation failure: a memory can be retrieved perfectly and still be a bad
representation of its source. This eval isolates derivation quality so we know
whether to invest in better derivation or simplify around raw history — the same
distinction the corpus handoff study measured once (≈29% misleading, ≈29%
fully-complete, ≈2.8× compression), now made standing.

## In Scope (outline — detail alongside the shadow eval)

- sample derived memories with their supporting source turns (reverse
  `supported_by`) across memory types
- an offline judge scoring each on: completeness (is the key information present?),
  unsupported claims (statements not backed by any source turn), drift (subject or
  scope shifted from the source), and compression ratio
- report per memory type, so we can see which derivations are trustworthy and which
  are lossy
- reuse the study harness pattern (selector ≠ evaluator); no production coupling

## Out of Scope

- retrieval-time RAW vs DERIVED comparison (`idea-raw-derived-hybrid-shadow-eval`)
- building a synthetic benchmark to prove derivation superior (explicit non-goal)
- changing the derivation pipeline (this measures; fixes are separate items)

## Done When

1. A sampled fidelity report exists, per memory type, on completeness, unsupported
   claims, drift, and compression.
2. We can state whether DERIVED's shadow losses are driven by bad derivation vs bad
   retrieval, independently.

## Notes

Continuous track (runs alongside P2/P3 once P1 lands), paired with
`idea-raw-derived-hybrid-shadow-eval`. Feeds strategy decision-point 3 (is derived
memory worth its complexity?).
Execution context: `docs/designs/015-vnext-historical-work-execution.md`
(Continuous evaluation track).
