---
id: add-workstream-rolling-topic
title: Workstream rolling-topic primitive (consolidation re-key, diagnostic-first)
status: queued
priority: high
commitment: committed
milestone: Next
lane: stabilization-semantics
---

## Summary

Add a rolling **workstream** primitive — a per-source-item, per-memory id
derived deterministically from existing strong signals at thread-rebuild
time — and use it as the consolidation grouping key (write-side) once live
telemetry has earned the behavior change.

This feature ships in two phases:

- **Phase 4A** (this slice, approved 2026-05-30): diagnostic + dry-run only.
  Tables, cascade, audit-log fields, dry-run consolidation metric. **No
  retrieval-routing change. No consolidation-behavior change.**
- **Phase 4B** (future, gated on Phase 4A telemetry): turn on consolidation
  re-key behind a feature flag, with rollback CLI. Still no routing change.

Routing-aware workstream filtering is **explicitly rejected** for this
milestone.

## Why

Pallium's `container_ref` is overloaded across visibility, extraction scope,
and the implicit topic boundary used by consolidation strategies. In broad
mixed-topic containers and self-referential sessions this overload collapses
quality at write time (cross-workstream `atomic_fact` merges) and at read
time (off-topic injections).

A 2026-05-29 night-job investigation under `.local/research/` validated that
a deterministic cascade over strong signals (work_refs, file paths, symbol
names, command/error tokens, explicit memory titles, workstream-kind
anchors) clusters source items and memories in a way that aligns with
human-recognisable workstreams. Coverage 73.8–100% per slice; **81.5% of
broad-slice production injections come from a different cascade-tagged
workstream than the query**.

The same investigation tested whether the cluster boundary could be used as
a retrieval gate. It cannot: Sonnet LLM-as-judge on n=300 candidates
returned 60 better / 240 worse / 0 neutral; architect cross-thread sample
returned 4 helpful drops vs 2 harmful avoided. The cluster signal is
real; the cluster boundary is the wrong shape for routing.

The remaining defensible value is **write-side**: re-keying consolidation
to `(container_ref, workstream_id_or_pseudo_id, subject, category)`
prevents cross-workstream `atomic_fact` merges (offline T1.7 dry-run:
1014 → 1153 useful groups, +13.7% on the self-referential slice). Plus
a diagnostic surface lets the next routing investigation compare candidates
by workstream id without re-running extraction.

The 4A/4B split makes the write-side change earn its complexity with live
telemetry rather than relying on a small offline qualitative sample.

## In Scope (Phase 4A only)

- Three new tables: `workstreams`, `memory_workstreams`,
  `source_item_workstreams`. All populated from the existing thread-rebuild
  path. No modification of existing tables.
- Cascade implementation in `capabilities/workstreams.py` and
  `capabilities/workstream_signals.py`, ported from the reference impl in
  `.local/research/_workstream_replay/`.
- Per-item workstream assignment via M1 delayed-assignment mechanism: the
  thread-rebuild that the per-item path already enqueues runs the cascade
  against items new since the last watermark. Per-item extraction unchanged.
- `MemoryEnvelopeScope.workstream_id` field — read-only in 4A; surfaced for
  debug/observability only.
- `query_audit_log.candidate_scores_json[].workstream_id` and row-level
  `query_workstream_id` — additive, populated from day 1.
- `query/debug` endpoint output gains workstream ids for query and
  candidates.
- **Dry-run consolidation metric**:
  `consolidation.workstream_aware_dryrun{kind=...}` emitted at every
  consolidation event, classifying per-group as `bad_merge_avoided`,
  `good_merge_preserved`, `good_merge_lost_suspected`, or
  `novel_split_unknown`. No LLM call. Daily roll-up to
  `.local/observability/workstream_dryrun/<date>.json` for architect
  spot-check.
- Tests:
  - `tests/test_workstream_cascade.py` (8 stages + self-ref + monorepo +
    pseudo-id non-joining)
  - `tests/test_workstream_signals.py` (R3-disciplined regexes)
  - `tests/test_workstream_assignment_persisted.py` (table population)
  - `tests/test_audit_log_workstream_field.py` (audit-log additions)
  - `tests/test_consolidation_dryrun_metric.py` (metric correctness)
- New eval runner `evals/workstream_consolidation/` reproducing the offline
  T1.7 finding on the live DB; regression guard for the dry-run metric and
  the basis for re-verifying the 4A → 4B acceptance criteria over time.

## In Scope (Phase 4B, gated, NOT approved at this milestone)

Phase 4B is documented in `docs/designs/014-workstream-consolidation-rekey.md`
§"Phase 4B" and is **not approved by this roadmap entry**. It activates
only after the 4A → 4B acceptance gates clear:

- ≥7 days of live 4A telemetry on production
- ≥200 consolidation events recorded
- `good_merge_lost_suspected / total ≤ 5%`
- `bad_merge_avoided / good_merge_preserved ≥ 0.10`
- Architect spot-check on ≥20 `good_merge_lost_suspected` cases confirms
  the structural heuristic isn't under-reporting real harm
- Workstream id stability ≥95% across consecutive rebuilds when no new
  strong signals arrive

A separate roadmap update will mark Phase 4B approved (or held) when the
gates have been evaluated.

## Out of Scope (this milestone)

- **Workstream-aware retrieval routing.** Hard ws-equality and -200pp soft
  ws prior were both tested and refuted by Layer 2 (Sonnet LLM-as-judge
  60 better / 240 worse / 0 neutral). A routing consumer may return as a
  separate investigation, but its consumer shape must be different from
  what Layer 2 ruled out.
- Rewrite of `same_thread_context_sufficient`.
- Packaging-locality-gate relaxation.
- Cross-thread join policy changes.
- `pallium_workstream_hint` integrator-supplied API. The cascade derives
  workstream from existing signals only.
- New memory type. Workstream is a scope/grouping concept, not a memory
  kind.
- Retroactive rewrite of historical `fact_summary` rows on upgrade.
  Re-consolidation under the new key is opt-in via CLI in Phase 4B.

## Done When (Phase 4A only)

1. `capabilities/workstreams.py` and `capabilities/workstream_signals.py`
   port the offline reference implementation.
2. Three new tables ship in `storage/sqlite_schema.py`; thread-rebuild
   populates them.
3. `MemoryEnvelopeScope.workstream_id` and the `query_audit_log` workstream
   fields are populated on every new write/query.
4. Dry-run consolidation metric emits at every consolidation event with
   the four-kind classification; daily roll-up file is produced.
5. `query/debug` output includes workstream ids.
6. All Phase 4A tests pass.
7. `evals/workstream_consolidation/` reproduces the offline T1.7 finding
   on the live DB.
8. Phase 4A backout drill (disable population/use, leave schema in place)
   is verified in a staging environment.
9. The committed design `docs/designs/014-workstream-consolidation-rekey.md`
   is referenced from this feature and from any code module that ships the
   work.

## Notes

Recommended sequencing:

- Land schema and `capabilities/workstreams.py` cascade first; populate
  tables and audit-log fields before touching consolidation strategies.
- Add the dry-run metric to consolidation strategies as a no-op observer
  that compares old-key and new-key groupings; no behavior changes in this
  step.
- Ship the eval runner alongside the metric so the regression guard exists
  from day 1.
- Run for ≥7 days against production data, then evaluate the 4A → 4B
  acceptance criteria.

References:

- Approved design: `docs/designs/014-workstream-consolidation-rekey.md`
- Source-of-truth research note (v5):
  `.local/research/topic_continuity_model_2026-05-29.md`
- Layer 1 results: `.local/research/topic_continuity_layer1_results_2026-05-29.md`
- Layer 2 results (the routing-gate refutation):
  `.local/research/topic_continuity_layer2_results_2026-05-29.md`
- Execution journal: `.local/research/night_job_2026-05-29_log.md`
- Reference cascade implementation:
  `.local/research/_workstream_replay/cascade.py` and `signals.py`
- Prior art: `roadmap/features/add-subject-workstream-anchor-filtering.md`
  (subject anchors, shipped) and
  `docs/designs/013-work-ref-cross-surface-continuity.md` (work_refs,
  cross-surface continuity).
