---
id: idea-raw-derived-hybrid-shadow-eval
title: RAW / DERIVED / HYBRID continuous shadow evaluation
status: queued
priority: medium
commitment: uncommitted
milestone: pallium-vnext-p2
---

## Summary

Make "is derivation worth it?" a standing measurement. On real historical lookups,
shadow three representations — RAW (source turns), DERIVED (memory objects),
HYBRID — and continuously record which recovers the needed information, at what
completeness, misleading rate, and context cost, plus periodic controlled A/B.

## Why

Corpus studies found current derived memory gives no retrieval-recall advantage
and is a lossy consumption representation (~29% misleading). The strategy keeps
derivation as a *continuously evaluated optimization layer*, not a removed feature
and not an assumption. This turns a one-off study into a live signal that tells us
whether to invest in better derivation or simplify around raw history
(strategy decision-point 3).

## In Scope (outline — detail when Phase 1 lands)

- a shadow runner reusing the `subtask_selector_shadow` seam + a new side table
- per-lookup record: recovered info, RAW-only vs DERIVED-only wins, completeness,
  misleading/unsupported, context size, derivation-failure vs retrieval-failure,
  downstream material use
- store the raw fusion score so a RAW arm is reconstructable from history
- extend `evals/retrieval_ablation/` with RAW/DERIVED/HYBRID variants for periodic A/B
- shadow-only: never affects live injection/output

## Out of Scope

- promoting derived memory before it demonstrates a repeated, measured advantage
- building a synthetic benchmark to prove derived memory superior (explicit non-goal)

## Done When

1. Real lookups are shadow-evaluated across RAW/DERIVED/HYBRID without affecting output.
2. We can state, from live data, whether derived beats RAW/HYBRID on precision,
   misleading rate, context-for-equivalent-quality, normalization recall, or
   downstream performance.

## Notes

Gate: Experiment 3. Depends on Phase 1 raw search (no RAW arm without it).
Execution context: `docs/designs/015-vnext-historical-work-execution.md` (Phase 2).
