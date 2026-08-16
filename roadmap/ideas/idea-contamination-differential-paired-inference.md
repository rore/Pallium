---
id: idea-contamination-differential-paired-inference
title: Use paired inference for the contamination differential bands
status: queued
priority: low
commitment: uncommitted
---

## Summary

`_diff_with_band` in `evals/pull_contamination/harness.py` composes the `relevant_lift` and
`contamination_harm` confidence bands from two INDEPENDENT Wilson intervals (Newcombe method
10). But the three condition arms are PAIRED — the same scenarios and repetition indices run
across no-history / relevant / contaminating. Independent-proportions inference ignores that
pairing.

## Why

Raised by CodeRabbit on PR #32. The current interval is mildly CONSERVATIVE (the safe
direction), and the code documents the caveat. Verified by hand on the ambiguous run that a
paired McNemar test gives the SAME qualitative conclusions (relevant_lift discordant b=0/c=3
→ p≈0.25 not significant; contamination_harm ~0 discordant), so no conclusion changed. Still,
a paired estimator (McNemar / paired difference CI) is the correct instrument and could matter
when a point estimate is non-zero (e.g. a real `relevant_lift` in the arbitrary-convention set,
where a tighter paired CI might legitimately exclude 0).

## In Scope

- A paired estimator for the two differentials: McNemar exact test (discordant pair counts)
  and/or a paired difference-of-proportions CI, keyed on (scenario_id, seed) matched trials.
- Report paired AND unpaired side by side (the unpaired stays as a conservative cross-check),
  consistent with the harness's dual-detector reporting style.
- Tests over crafted matched-arm trials (concordant vs discordant) verifying the paired stat.

## Out of Scope

- Changing the point estimates or the detectors.

## Done When

1. `relevant_lift` and `contamination_harm` carry a paired inference alongside the Newcombe band.
2. Tests cover concordant/discordant matched pairs.

## Notes

Evidence: `evals/pull_contamination/harness.py` `_diff_with_band` (documents the pairing
caveat). CodeRabbit PR #32 thread on `harness.py`. Depends conceptually on
`idea-arbitrary-convention-contamination-scenarios` (where a non-zero effect is more likely and
paired tightening would matter).
