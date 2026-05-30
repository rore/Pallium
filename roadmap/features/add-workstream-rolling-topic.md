---
id: add-workstream-rolling-topic
title: Workstream rolling-topic primitive (observability experiment, 4A diagnostic-only)
status: queued
priority: high
commitment: committed
milestone: Next
lane: stabilization-semantics
---

## Status update — 2026-05-30 eval bootstrap

A diagnostic eval bootstrap ran 34 scenarios across `agent_conversation_runner`
+ `memory_routing_benchmark` against the merged Phase 4A code. Telemetry
plumbing is sound — tables populate, dry-run metrics emit, no behavior drift.
The workstream signal, however, is weak on this corpus:

- 0 of 7 resolved workstreams have structural-only signatures; 6 of 7 are
  language-derived. Likely a corpus artifact (library scenarios contain no
  paths/symbols), but currently violates the language-agnostic principle.
- `split_with_unknown_or_overlap / total = 45%` vs design gate ≤ 5%.
- `split_resolved_groups / single_workstream_group = 0.012` vs design gate
  ≥ 0.10.
- Audit-side workstream coverage was unmeasurable (all queries returned
  `no_relevant_memory` and the skip path bypassed the audit-log writer).
- Behavior unchanged (fact_summary grouping still uses the old key).

**Verdict: WEAK_SIGNAL.** Workstream is useful as observability only. It has
not earned consolidation behavior, and it has not earned routing behavior.

Full report: `.local/research/workstream_eval_bootstrap_2026-05-30/RESULTS.md`.

**Phase 4B is held indefinitely. Do not flip the consolidation re-key flag on
this evidence.**

## Summary

Add a deterministic structural **workstream** id, computed cheaply at
thread-rebuild time from existing signals, persist it on source items and
memories, and surface it in the audit log + a structural dry-run metric on
consolidation grouping.

This is **an observability experiment after mixed/negative validation**. It is
not a proven workstream architecture. The 2026-05-29 night-job leaned on a
positive framing of cluster signal and cross-thread mismatch, but the
2026-05-30 replay (`.local/research/workstream_replay_2026-05-30/RESULTS.md`)
returned **UNCERTAIN, leaning FAIL**:

- broad-container contamination drop only **22.7%** (bar 40%)
- focused-container fragmentation **above** the gate (1.50 ws/10 items vs ≤1.0)
- R6 thread-continuity carries **63–73%** of assignments — the gate mostly
  classifies by thread identity, not by structural workstream signal
- consolidation simulation direction-wrong on `atomic_fact` (already
  singleton-grouped under the existing key, so the new key can only merge
  or no-op; the night-job's "+13.7% useful split" headline did not
  reproduce)

Independent earlier evidence (2026-05-29 Layer 2) ruled out using the cluster
boundary as a retrieval gate (Sonnet judge n=300: 60 better / 240 worse / 0
neutral). That ruling stands; **routing-aware workstream filtering is
explicitly rejected for this milestone.**

The slice ships in two phases:

- **Phase 4A** (this slice, approved 2026-05-30): persistence, audit-log
  fields, structural dry-run consolidation metric. **No retrieval-routing
  change. No consolidation-behavior change.** It is observability that lets
  us decide whether workstream is the right primitive at production scale.
- **Phase 4B** (future, **NOT approved**, gated): turn on consolidation
  re-key behind a feature flag, with rollback CLI. Gated on (a) Phase 4A
  structural telemetry, (b) closing two specific Layer-1 negatives the
  2026-05-30 replay surfaced, (c) redesigning the consolidation simulation
  baseline.

## Why

Pallium's `container_ref` is overloaded across visibility, extraction scope,
and the implicit topic boundary used by consolidation strategies. There is a
real signal here — strong-signal coverage clears 30% on every slice, cluster
sizes are sane, and 81.5% of broad-slice production injections land on a
different cascade-tagged workstream than the query.

There is also real evidence that the obvious consumers are wrong-shaped or
undersized:

- The retrieval gate consumer is net-negative (Layer 2, n=300).
- The consolidation re-key consumer's headline number (the night-job's
  "+13.7% useful split") could not be reproduced on a stricter harness;
  on `atomic_fact` it can only no-op.
- Focused containers fragment above the bar; the cascade is closer to
  "thread-aware grouping" than "structural-signal grouping" on this corpus.

The defensible move is **observability first**: ship the persistence + audit
surface so we can answer the open questions on live data without committing
to a behavior change the data does not yet support. Phase 4B activation is
explicitly held until evidence catches up.

## In Scope (Phase 4A only — observability, not behavior)

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
- **Structural dry-run consolidation metric**: at every consolidation event,
  emit `consolidation.workstream_aware_dryrun{kind=...}` classifying per group
  with **neutral structural labels, NOT quality verdicts**:
  - `split_resolved_groups` — old-key merged ≥2 candidates; new-key splits
    them across ≥2 distinct resolved workstreams (no unknown buckets)
  - `single_workstream_group` — old-key merged; new-key sees one workstream
    covering the group
  - `split_with_unknown_or_overlap` — split with at least one unknown
    pseudo-id partition
  - `split_all_unknown` — every partition is an unknown pseudo-id

  These describe *what the new key would do*, not whether the new grouping is
  correct. The classification is purely structural — no LLM call. Daily
  roll-up to `.local/observability/workstream_dryrun/<date>.json` for
  architect spot-check.
- For anchor-based strategies (`container_topic_window`,
  `thread_summary_anchored`) emit a secondary
  `consolidation.workstream_homogeneity` metric with kinds
  `cluster_homogeneous` / `cluster_mixed_resolved` / `cluster_mixed_unknown`.
- Tests:
  - `tests/test_workstream_cascade.py` (8 stages + self-ref + monorepo +
    pseudo-id non-joining)
  - `tests/test_workstream_signals.py` (R3-disciplined regexes)
  - `tests/test_workstream_assignment_persisted.py` (table population)
  - `tests/test_audit_log_workstream_field.py` (audit-log additions)
  - `tests/test_consolidation_dryrun_metric.py` (metric correctness against
    the four neutral structural kinds)
- New eval runner `evals/workstream_consolidation/` reproducing the
  consolidation dry-run on the live DB; this is the regression guard for the
  metric and a tool for re-verifying the 4A → 4B acceptance criteria over time.

## In Scope (Phase 4B, gated, **NOT approved at this milestone**)

Phase 4B is documented in `docs/designs/014-workstream-consolidation-rekey.md`
§"Phase 4B" and is **not approved by this roadmap entry**. It activates only
after **all** of the following hold:

**Structural gates from Phase 4A telemetry:**

- ≥7 days of live 4A telemetry on production
- ≥200 consolidation events recorded
- `split_with_unknown_or_overlap / total ≤ 5%`
- `split_resolved_groups / single_workstream_group ≥ 0.10`
- Architect spot-check on ≥20 `split_with_unknown_or_overlap` cases
- Workstream id stability ≥95% across consecutive rebuilds when no new
  strong signals arrive

**Open preconditions surfaced by the 2026-05-30 replay AND the 2026-05-30 eval
bootstrap (additional, not substitutes for the structural gates):**

- A diagnostic-only schema patch lands first: add `stage` to
  `source_item_workstreams` (or a sibling event table), populated from
  `AssignmentResult.stage`. Without it, R6 thread-continuity vs structural
  attribution cannot be audited from the merged schema, and every gate
  below is uncheckable.
- Re-run the eval bootstrap on a software-engineering corpus
  (`evals/conversational_knowledge/structural_triage_scenarios.json`,
  `evals/external_memory_pressure/`) and report the F-section
  structural-vs-language coverage. Structural-only coverage on resolved
  workstreams must be ≥30% before `language-only signatures dominate`
  ceases to be a blocker.
- Build or pick an injection-positive corpus so the audit-log workstream
  coverage measurement (`query_workstream_id`, per-candidate
  `workstream_id`) actually produces non-zero rows. The current bootstrap
  produced 0 audit rows because the skip path bypasses the audit writer.
- Focused-container fragmentation drops below 1.0 ws / 10 items on live
  data (the replay measured `focused_A` 1.50 — needs to confirm whether
  the cascade as shipped over-splits focused threads at production scale,
  or whether the replay was a corpus artifact)
- Wrong-topic contamination drop on the broad slice reaches ≥40% relative,
  with confidence intervals tight enough to clear the bar (replay measured
  22.7% on n=35 rated; either more ratings accumulate or an
  architect-approved Class B Sonnet judge pass on unrated injections)
- Consolidation-simulation baseline is redesigned away from `atomic_fact`
  (which is already singleton-grouped) toward `fact_summary` or another
  consolidation seed where the new key can produce a meaningful split rate

If any precondition fails, **Phase 4B is held**. The right next step is a
new investigation to address the gap, not a 4B activation. A separate
roadmap update will mark Phase 4B approved or held when the evidence is in.

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
- **Any claim that workstream is a proven primitive.** It is not yet. Phase
  4A is observability; Phase 4B is held until the open preconditions close.

## Done When (Phase 4A only)

1. `capabilities/workstreams.py` and `capabilities/workstream_signals.py`
   port the offline reference implementation.
2. Three new tables ship in `storage/sqlite_schema.py`; thread-rebuild
   populates them.
3. `MemoryEnvelopeScope.workstream_id` and the `query_audit_log` workstream
   fields are populated on every new write/query.
4. Structural dry-run consolidation metric emits at every consolidation event
   with the four neutral structural kinds; daily roll-up file is produced.
5. `query/debug` output includes workstream ids.
6. All Phase 4A tests pass.
7. `evals/workstream_consolidation/` runs against the live DB and produces a
   markdown report — the regression guard for the dry-run metric.
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
  structural gates **and** the open preconditions in §"In Scope (Phase 4B)".

References:

- Approved design: `docs/designs/014-workstream-consolidation-rekey.md`
- **2026-05-30 replay (the harder evidence)**:
  `.local/research/workstream_replay_2026-05-30/RESULTS.md`
- Source-of-truth research note (v5):
  `.local/research/topic_continuity_model_2026-05-29.md`
- Layer 1 results: `.local/research/topic_continuity_layer1_results_2026-05-29.md`
- Layer 2 results (the routing-gate refutation):
  `.local/research/topic_continuity_layer2_results_2026-05-29.md`
- Phase 4A implementation log:
  `.local/research/phase_4a_implementation_log.md`
- Execution journal: `.local/research/night_job_2026-05-29_log.md`
- Reference cascade implementation:
  `.local/research/_workstream_replay/cascade.py` and `signals.py`
- Prior art: `roadmap/features/add-subject-workstream-anchor-filtering.md`
  (subject anchors, shipped) and
  `docs/designs/013-work-ref-cross-surface-continuity.md` (work_refs,
  cross-surface continuity).
