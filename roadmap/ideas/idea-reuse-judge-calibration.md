---
id: idea-reuse-judge-calibration
title: Reuse-ladder judge calibration (gold set + agreement threshold)
status: queued
priority: high
commitment: uncommitted
milestone: pallium-vnext-p1
---

## Summary

The retrospective reuse KPI (the three-rung ladder) rests entirely on an
LLM-judge's rung-1/rung-2 verdicts. There is a judge harness that computes
inter-seed Cohen's kappa, but **no human-labelled gold set and no target
agreement threshold**. Add a small committed gold fixture of hand-labelled
lookups and a documented minimum kappa (judge-vs-gold, not only seed-vs-seed)
below which rung rates are reported as uncalibrated.

## Why

Inter-rater agreement between seeded copies of the same model measures judge
*stability*, not correctness — a confidently-wrong judge can be perfectly
self-consistent. Design 015 lists "judge rubric + calibration" as a P0
deliverable; it shipped without the calibration half. Single-seed judge rungs
also carry the repo's documented ~20pp variance. Until a gold set exists, every
rung number the dashboard shows is uncalibrated, so the KPI cannot yet mean what
it claims — and the Experiment-1 window is now open.

## In Scope

- A small committed gold fixture: N hand-labelled lookup events (before/after
  turns + assigned rung), scoped to the current product slice, no product names.
- Judge-vs-gold agreement (Cohen's kappa or equivalent) reported alongside the
  existing seed-vs-seed kappa in the judge output.
- A documented minimum agreement threshold; below it, the rollup/dashboard marks
  rung rates "uncalibrated" rather than presenting them as confident.
- Reuse the existing judge harness and rollup; do not build a new judge.

## Out of Scope

- Rung-3 (downstream benefit) — remains controlled-exposure-only by design.
- Replacing the judge model or the rubric (this calibrates the current one).
- Growing the gold set to a large corpus — smallest fixture that yields a
  meaningful agreement read.

## Done When

1. A committed gold fixture exists and the judge reports judge-vs-gold agreement.
2. A documented threshold gates whether rung rates are presented as calibrated.
3. The dashboard/rollup distinguishes calibrated from uncalibrated rung rates.

## Notes

Highest-value verification gap from the vNext architect review. Should land
before the Experiment-1 window produces enough data to be interpreted as a
result. Judge variance context: `docs/context/validation.md` (~20pp, ≥3 seeds,
consensus). Related: `add-historical-lookup-funnel-telemetry` (shipped the
judge + rollup), `evals/historical_lookup_judge.py`,
`evals/historical_lookup_measurement.py`.
