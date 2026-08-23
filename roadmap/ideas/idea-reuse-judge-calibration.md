---
id: idea-reuse-judge-calibration
title: Reuse-ladder judge calibration (gold set + agreement threshold)
status: done
priority: high
commitment: committed
milestone: pallium-vnext-p1
---

> **Reopened 2026-08-17 (external review item 12):** the original κ≈0.50 was below
> the stated ≥0.70 threshold. The hardened rubric later produced a provisional
> κ=0.75 on N=12, but the fixture is single-author synthetic evidence. Two
> independent human raters are not part of the intended product workflow, so
> this item now closes only a narrower, maintainable claim: reference-set
> regression accuracy plus repeat-run stability. It must never be described as
> independent human calibration. Keep deterministic facts (lookup, exposure,
> expansion, citation) separate from judged use.

## Summary

The reuse KPI depends on an LLM judge. The repository has a small maintained
single-author reference fixture and a threshold, but its evidence has been
single-run and lacked per-class diagnostics. Add repeatable reference-set
validation: per-class metrics, prompt provenance, and agreement across two
cache-disabled seed groups over the same cases.

## Why

Agreement among seeded copies of one model measures stability, not objective
correctness. Agreement with the maintained examples catches known rubric
regressions, while a second disjoint seed group catches unstable results. The
combined signal is useful for deciding whether the judged rung rates are safe
to track, provided it is not presented as independent human calibration.

## In Scope

- Reuse the existing 12-case generic reference fixture and real judge path.
- Report group-vs-reference kappa, confusion matrix, per-class
  precision/recall/support, prompt id/version, and mutual seed-group kappa.
- Require the sole live κ≥0.70 gate for both group-vs-reference comparisons and
  mutual agreement, with no missing or all-failed event.
- Preserve visibly uncalibrated rollup/dashboard behavior on failure.

## Out of Scope

- Independent human labeling or adjudication.
- Rung-3 downstream benefit, which remains controlled-exposure-only.
- Replacing the judge model/rubric or growing a large corpus.
- Changing or weakening executable evidence-span validation; the enforced
  contract is now a prerequisite for this gate.

## Done When

1. The maintained reference fixture reports confusion matrix and per-class precision/recall/support.
2. The sole live threshold is κ≥0.70 and the report records judge prompt id/version.
3. Two cache-disabled, disjoint seed groups judge identical ordered events; each
   group-vs-reference κ and their mutual κ meet the threshold, with no missing or failed event.
4. The report and validation docs call this a single-author reference-set check,
   not independent human calibration; the dashboard/rollup keeps failed checks visibly uncalibrated.

## Notes

Historical pre-enforcement result, 2026-08-23: cache-disabled groups 0/1/2 and
3/4/5 produced group-vs-reference kappa 0.750 and 0.875, with mutual kappa
0.870 (N=12, zero failures).

Reopened 2026-08-23 after executable evidence-span enforcement: 16/72 calls
failed because the judge supplied work-only or history-only spans. The overall
gate failed despite perfect agreement on the incomplete surviving subset.

Completed 2026-08-23: prompt version 2026-08-23-evidence-v6 made the output
contract explicit without changing the validator or fixture. Cache-disabled
seed groups 0/1/2 and 3/4/5 each matched the maintained reference set at
kappa 1.0 (N=12), their mutual kappa was 1.0 (N=12), and there were zero failed
or missing events. This establishes reference-set regression stability only;
it does not show that retrieved memory improves real downstream work.


Highest-value verification gap from the vNext architect review. Should land
before the Experiment-1 window produces enough data to be interpreted as a
result. Judge variance context: `docs/context/validation.md` (~20pp, ≥3 seeds,
consensus). Related: `add-historical-lookup-funnel-telemetry` (shipped the
judge + rollup), `evals/historical_lookup_judge.py`,
`evals/historical_lookup_measurement.py`.
