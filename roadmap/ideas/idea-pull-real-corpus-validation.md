---
id: idea-pull-real-corpus-validation
title: Real-corpus pull decision gate — value, filtering, contamination, cost (consolidated)
status: in-progress
priority: high
commitment: committed
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

After `add-outdated-history-guard` ships, run a larger, more varied real-corpus
before/after study. Verify that the guard reduces harm from replaced decisions without
removing the benefit of relevant history, and measure whether historical pull remains
worth its token and latency cost.

This is the second next vNext item. The completed 12-case run is its directional
baseline, not the final product-value claim.

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

- Use 20-30 real cases from as many distinct sessions and task shapes as the available
  corpus supports; do not spend budget repeatedly sampling the same narrow sessions.
- Before running, label cases as applicable, unrelated, or containing a replaced
  decision. Preserve those labels independently of the model judge.
- Compare three conditions where possible: no history, the pre-guard historical
  result, and the guarded result. Keep task, model, and token budget comparable.
- Include the focused superseded-history probe unchanged so its 9-of-10 contamination
  baseline remains directly comparable.
- Have one human review every loss or harmful result and a bounded random sample of
  wins. A second independent reviewer is not required.
- Report downstream answer effect, harmful-result rate, useful-history rate, context
  tokens, and latency separately, including per-case-category breakdowns.

## Out of Scope

- More general-knowledge synthetic sets (explicit/ambiguous/applicability arc is done).
- Production behavior changes.
- Repeating the same small sample merely to increase the call count.

## Done When

1. `add-outdated-history-guard` is complete before this run starts.
2. The study contains 20-30 usable real cases, or explicitly reports that the live
   corpus lacks enough diverse sessions instead of padding the count with repeats.
3. Applicable history improves the answer in at least 70% of reviewed applicable
   cases; unrelated history changes the answer in fewer than 5%; replaced decisions
   mislead in no more than 10%.
4. The unchanged focused stale-history probe falls from 9 misleading trials out of
   10 to no more than 1 out of 10.
5. Every harmful or losing case and a bounded random sample of wins receive one human
   spot-check; automatic-judge and human results are reported separately.
6. Results state sample diversity, failures, exclusions, model calls, estimated
   input tokens, added-history tokens, and latency for each condition.
7. The conclusion is an explicit product decision: proceed to Phase 2, revise the
   guard and repeat, or stop broader investment in historical pull.

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
case, one uncalibrated model judge that sees the history and may infer the history arm, no human
spot-check, no linked work-after, and reconstructed bounded excerpts that may differ from the
original agent-visible excerpts. It does not satisfy
this item's Done When criteria; the human review and focused superseded-history probe remain open.

### Expanded baseline — 2026-08-24

The budget-capped run reached 12 usable paired cases: history won 11, lost 1,
and tied 0; the judge labelled history useful in 10, irrelevant in 2, and harmful
in 0. The cases came from only four requester sessions. A separate two-scenario,
five-repetition stale-history probe found that plausible superseded guidance was
adopted in 9 of 10 contaminating trials. These results justify fixing outdated
history first, then running the larger before/after study above. They do not yet
prove broad product value.

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

### Guarded real-corpus review — 2026-08-24

The fixed stale probe passed at 0/10 obsolete adoptions, down from 9/10. A
20-case comparable run completed with zero failures under the 100-call /
50,000-estimated-input-token caps (43,282 estimated input tokens). Its automated
judge reported strong applicable-history value, but the required spot-check
found that several keyword-fragment tasks were unanswerable and all arms merely
invented plausible responses. The user delegated the seven-case review to the
agent; this is explicitly agent review, not human validation.

More importantly, the review exposed that the only apparent replaced-decision
case came from a superseded thread summary. For roll-up memories, supported_by is
provenance across many turns, not a claim that the summary's successor replaces
each raw passage. The production guard and evaluator now restrict replacement
guidance to direct durable claim types. Public MCP search/expand and evaluator
regressions prove summary and atomic-fact roll-ups are excluded while a
superseded decision remains visible.

After that correction, the same 20-case snapshot contains zero qualifying
claim-level replacements. Therefore the larger run is invalid as evidence of
the guard's real-corpus effect; rerunning the model would spend budget without
testing the feature. Decision: ship the guard based on its focused 0/10
regression and public lifecycle coverage, but keep this product gate in progress.
Collect genuinely superseded decision/constraint/operational cases across more
sessions, then repeat before Phase 2. Do not pad or claim broad product value.