---
id: idea-reuse-judge-evidence-span-enforcement
title: Enforce the reuse judge's evidence_span output contract (overlap + rung consistency)
status: done
priority: low
commitment: committed
---

## Summary

The reuse judge's `JUDGE_SYSTEM_PROMPT` (post `reuse-judge-rubric-hardening`) requires
`evidence_span` to be a non-empty, ≤200-char span that appears in BOTH RETRIEVED HISTORY
and WORK AFTER when rung is "incorporation", and empty otherwise. This is currently a
PROMPT-ONLY contract: `_judge_once` stores `str(parsed.get("evidence_span",""))[:300]`
(note: truncates at 300, not the prompt's 200) without validating overlap, length, or
rung-consistency, so a malformed or work-only evidence_span returns with `failed=False`.

## Why

Raised by CodeRabbit on PR #26 (`evals/historical_lookup_judge.py`). Enforcing the
contract would let a judge that emits an "incorporation" rung with a non-overlapping (or
empty) evidence_span be routed through the existing failure path rather than silently
accepted — a stronger guard on the rung-1 signal that drives the KPI.

Deliberately deferred out of the rubric-wording PR: this is a CODE-LOGIC change, not a
prompt edit, and it carries measurement-bias risk — hard-rejecting a verdict on a soft,
model-emitted field could raise the judge-failure rate and bias rung rates downward.
That trade-off needs its own design + eval, not a drive-by add to a wording PR.

## In Scope

- Post-parse validation in `_judge_once`, applied to the RAW `parsed["evidence_span"]`
  BEFORE any coercion or truncation: require a string type (reject non-string), enforce
  the ≤200-char limit on the ORIGINAL value (not the post-`[:300]` value), and — for
  "incorporation" — require it be substring-present in BOTH the retrieved history and the
  work-after text under ONE clearly-defined normalization (e.g. casefold + whitespace
  collapse). For "influence"/"none", require empty. Invalid → route through the existing
  `failed=True` handling.
- Reconcile the `[:300]` truncation with the prompt's ≤200 contract (validate the
  pre-truncation length; truncate only for storage after the check passes).
- Tests: valid shared-evidence incorporation accepted; rejected cases — work-only /
  empty evidence on "incorporation" (current `_StubJudge` returns a work-only "marker"),
  a non-string evidence_span, an overlong (>200-char) span, and a non-empty span on an
  "influence"/"none" verdict.

## Out of Scope

- Any rubric-wording change (shipped in `reuse-judge-rubric-hardening`).
- Changing the rung taxonomy, consensus, or gold fixture.

## Done When

1. `_judge_once` validates the raw evidence_span (type, pre-truncation length, rung
   consistency, and cross-text overlap under a defined normalization) and routes invalid
   output through the failure path.
2. Tests cover the valid and invalid evidence_span shapes (work-only, empty-on-incorp,
   non-string, overlong, non-empty-on-influence/none).
3. The judge-failure-rate impact is measured (does enforcement materially change rung
   rates on the gold set / a replay window?) and noted, so the measurement-bias risk is
   quantified rather than assumed benign.

## Notes

Evidence: `evals/historical_lookup_judge.py` `_judge_once` (evidence_span stored, not
enforced); `tests/test_historical_lookup_judge.py` `_StubJudge` (work-only "marker").
Related: `reuse-judge-rubric-hardening` (the prompt contract this would enforce),
`idea-reuse-judge-calibration` (the calibration story this guards).
## Result

Completed 2026-08-23. The validator now fails closed on raw type, the 200-character
boundary, incorporation evidence not present in both normalized text sides, and
non-empty influence/none evidence. Focused evaluator/reference suites pass.

The cache-disabled maintained-reference run measured a real reliability cost:
16/72 judge calls failed validation (22.2%; 8/36 in each seed group). Group A
compared 10/12 events and group B 11/12; mutual comparison covered 10/12. The
remaining labels agreed perfectly, but incomplete-subset kappa is not a pass, so
the overall reference gate correctly failed and downstream-task-effect
observational rung rates remain untrusted. The calibration item is reopened;
the validator and fixture were not weakened or tuned to hide the failures.
