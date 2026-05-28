# Post-routing selection audit

Offline audit measuring whether Pallium's post-routing selection layer (the work
between the scored candidate set and the final injected set) improves or hurts
**rated** retrieval quality versus a simple top-K-by-`routing_score` baseline.

## Problem

A prior offline replay surfaced that for a meaningful fraction of audit rows
where injection happened, the production-injected set differed from
top-K-by-`routing_score`. That means selection (dedup, companion-fill,
constraint supplement, cap-by-token-budget, packaging) is doing real work — but
we did not know whether the work was *gaining* precision or *losing* recall.

## What this script does

For each `query_audit_log` row in the rated window where injection happened
(`carry_forward_available` decision_reason is the only one with both
`candidate_scores_json` and `injected_blocks_json`), the script defines:

- `P` — production injected set (`injected_blocks_json` mids).
- `T` — top-`|P|` by `routing_score` (restricted to candidates with a real
  `memory_object_id`; `source_evidence`-style records have no mid and are
  invisible to ratings).
- `R` — `T \ P` (top-K candidates dropped by selection) and the populations
  flagged with `excluded_reason_code` / `suppression_reason_code`.

Then for each candidate it cross-references `memory_feedback` ratings (rated
against the same `query_audit_log_id`) and computes per-row:

```
net = kept_relevant + dropped_not_relevant
    - kept_not_relevant - dropped_relevant
```

Aggregates and breaks down by `decision_reason`, `container_ref`, candidate
`type`, `excluded_reason_code`, `suppression_reason_code`, and original
`routing_rank` displacement.

## Constraints

- Read-only on the live DB.
- Zero LLM calls.
- No production code changes.

## Running

```bash
python -m evals.post_routing_selection_audit.audit
```

Outputs:

- `.local/research/post_routing_selection_audit_2026-05-28.md` — main report.
- `.local/research/_post_routing_selection_audit_run.md` — run log (decision
  reason distribution, JSON shape samples, rated coverage, edge cases).

## Known blind spots

- Candidates with `memory_object_id=None` (`source_evidence`-style records,
  ~72% of all rows) cannot be rated and therefore cannot enter net-win/loss
  analysis. The audit reports their volume in the run log but does not score
  them.
- Only `carry_forward_available` rows have both candidate_scores AND
  injected_blocks. `orientation_recency` injects without storing candidates and
  is not in scope (see Goal B in
  `.local/research/audit_observability_plan_2026-05-28.md`).
- `post_routing_drop_reason` IS now in the `candidate_scores_json` snapshot
  (added 2026-05-28 alongside the Goal A annotation work). The R2b
  subject-overlap gate populates it. Pre-2026-05-28 rows do not carry the
  field.
- Pre-2026-05-28 rows lack the Goal A `displaced_by_*` codes
  (`displaced_by_dedup`, `displaced_by_fact_summary_cap`,
  `displaced_by_expansion_ratio`, `displaced_by_hard_ceiling`,
  `displaced_by_companion_fill`, `displaced_by_constraint_supplement`,
  `displaced_by_locality_compatibility`,
  `displaced_by_cross_thread_checkpoint_suppression`,
  `displaced_by_per_candidate_eligibility`,
  `displaced_by_r2b_subject_overlap`). On those rows
  `excluded_reason_code` may be `None` for selection-layer drops — treat as
  `unannotated_legacy`. Re-run on a post-2026-05-28 window to see the new
  codes.

