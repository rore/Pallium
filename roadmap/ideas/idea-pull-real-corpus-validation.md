---
id: idea-pull-real-corpus-validation
title: Real-corpus pull decision gate — value, filtering, contamination, cost (consolidated)
status: queued
priority: high
commitment: uncommitted
---

> **Consolidated 2026-08-18 (roadmap refinement).** This is now the single product-decision gate for
> historical pull. It absorbs `idea-measure-pull-filtering-accuracy-and-cost` (filtering accuracy,
> contamination, token/latency cost) and the direction-metric portion of
> `idea-reconcile-unprompted-pull-direction-signal` (both superseded → point here). The headline question
> is NOT "will agents pull unprompted?" (answered: they over-pull) but: **does agent-filtered historical
> pull improve the work enough to justify its token, latency, and contamination cost?** Runs only after
> measurement integrity (KPI taxonomy + attribution + continuous-eval population) and a calibrated reuse
> judge (κ≥0.70) are in place. See the merged tickets for their full DoD detail.

## Summary

Validate the pull proposition on REAL corpus cases (from the live DB snapshot, with human
spot-checking), and run a focused probe of the one synthetic weak spot: superseded/older-state
scope applicability.

## Why

The synthetic arc is complete and gave a clear, satisfying answer (PRs #31 explicit, #32 ambiguous,
#33 applicability-judgment):
- **Pull VALUE validated:** when the correct answer is an arbitrary project-specific convention the
  task cannot reconstruct, applicable (in-scope) history reliably supplies it — relevant went 3/3 in
  all 10 applicability scenarios; relevant_lift +0.57 [+0.36, +0.73], baseline genuinely split (0.43).
- **Scope/applicability is the real hard edge:** aggregate contamination_harm ≈ 0, but per-scenario
  the SUPERSEDED type contaminated cleanly — `branch-naming` flipped 3/3 correct→wrong when given a
  plausible "earlier standard" convention. Other scope types the agent handled well (even moved AWAY
  from the out-of-scope value).

Per the reviewer's decision rule ("if it works, go directly to real-corpus"), the value side works,
so the next step is real-corpus — with a targeted watch on superseded scope, the demonstrated risk.

## In Scope

- Real-corpus pass: sample real historical-lookup cases from a DB snapshot (scratch copy, never the
  live DB), reuse the `evals/pull_contamination/` harness shape where possible, and human-spot-check
  whether the synthetic susceptibility (superseded-scope contamination) appears under realistic
  retrieval noise. Deterministic detection where feasible; human adjudication for the residual.
- A focused synthetic SUPERSEDED probe: more than one scenario (n>1 scenario, more reps) of the
  branch-naming shape (task says "current standard", history describes a superseded standard from the
  same lineage) to see whether the correct→wrong flip is systematic or a single-scenario artifact.
- Report both against the decision-first detector + differential (relevant_lift, contamination_harm),
  with per-scenario breakdowns (aggregate hides the superseded signal).

## Out of Scope

- More general-knowledge synthetic sets (explicit/ambiguous/applicability arc is done).
- Production behavior changes.

## Done When

1. A real-corpus read of whether applicable history helps and whether non-applicable (esp. superseded)
   history contaminates, with human spot-checks.
2. A focused superseded probe establishing whether the correct→wrong flip generalizes.
3. A recommendation: does the pull model need a scope/recency guard (e.g. surfacing provenance/age to
   the agent, or down-weighting superseded sources) before broad rollout?

## Notes

Evidence: `.agent-workflow/tasks/pull-applicability-judgment-experiment.md` Evidence section;
`.local/research/pull_contamination_applicability_run.json`. Depends on the merged applicability
harness. Related: `idea-arbitrary-convention-contamination-scenarios` (superseded by this — the
arbitrary-convention set was built and run in #33), `idea-measure-pull-filtering-accuracy-and-cost`.

### Directional real-corpus pilot — 2026-08-23

A budget-capped offline run sampled five actual non-empty historical pulls from a private scratch
snapshot. At the same task, the answer with bounded history won 5/5 blinded comparisons; the judge
labelled the retrieved history useful in 4 cases, irrelevant in 1, and harmful in 0. History added a
mean 340.6 estimated tokens; mean latency was 8.56s with history versus 3.42s without. The run used
6,796 estimated model-input tokens and had no failures.

This is **offline controlled downstream-task-effect**, not candidate recovery, injection precision,
or observed live improvement. It is encouraging directional evidence only: five cases, one draw per
case, one uncalibrated model judge, no human spot-check, no linked work-after, and reconstructed bounded excerpts that may differ from the original agent-visible excerpts. It does not satisfy
this item's Done When criteria; the human review and focused superseded-history probe remain open.

## Product DoD (external review item 11 — ranking precision)

Build a real-corpus validation set from anonymized historical sessions that includes: long-running
projects; stale decisions; reversed decisions; duplicated turns; unrelated sessions with shared
vocabulary; Unicode; ambiguous terms; private and public data; source/derived disagreement.

**Per query, label:** whether useful history exists; every relevant source episode; harmful or
misleading results; the minimum context needed to answer correctly.

**Measure separately** (do not conflate): candidate recovery at K; precision at K; reciprocal rank;
duplicate-adjusted diversity; stale/contradicted result rate; downstream task effect with and without
retrieved context; total context tokens.

**Required lifecycle cases:** decision made → later superseded → old wording queried; source forgotten
after derivation; multiple similar projects; same phrase with different meanings; relevant raw source
ranked below many derived objects; chain length greater than two.

Every output must state whether it measures candidate recovery, injection precision, or downstream
effect — a shadow replay must never be labeled observed downstream improvement.
