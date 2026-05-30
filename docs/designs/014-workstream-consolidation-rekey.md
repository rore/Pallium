# Workstream Consolidation Re-Key — Diagnostic First, Behavior Second

Date: 2026-05-30
Status: Phase 4A approved · Phase 4B gated on telemetry · routing consumer rejected for this milestone

## Problem

Pallium's `container_ref` is overloaded. It carries visibility scope,
extraction scope, *and* the implicit topic boundary used by the consolidation
strategies in `agent_conversation_memory` and `conversational_knowledge`. In
focused single-topic containers this is invisible. In broad mixed-topic
containers and self-referential sessions it collapses retrieval and
consolidation quality.

A 2026-05-29 night-job investigation under `.local/research/` exhaustively
tested whether modelling **workstream** as a separate primitive — derived from
strong structural signals at thread-rebuild time — would lift retrieval and
consolidation quality. The investigation produced two clear results:

1. **The cluster signal is real.** A deterministic cascade over strong signals
   (work_refs, file paths, symbol names, command/error tokens, explicit memory
   titles, subject anchors of kind `workstream`) clusters source items and
   memories in a way that aligns with human-recognisable workstreams across
   focused, broad, self-referential, and Slack-style slices. Coverage on
   strong signals is 73.8–100% per slice. Cluster sizes are sane;
   fragmentation is acceptable. **81.5% of broad-slice production injections
   come from a different cascade-tagged workstream than the query** — i.e. the
   cascade detects a real boundary that production routing currently does not.

2. **Using the cluster boundary as a retrieval gate is net-negative.** Sonnet
   LLM-as-judge on n=300 candidates across four slices and two routing
   variants (hard equality and -200pp soft prior) returned 60 better / 240
   worse / 0 neutral. Architect-classified cross-thread sample (n=20) returned
   4 helpful candidates dropped vs 2 harmful avoided. The cluster boundary is
   tighter than the human notion of "same work"; ws-equality filtering throws
   away genuine cross-workstream recall faster than it removes harmful
   cross-topic noise.

The re-scoped design ships only what the data supports: workstream as a
**diagnostic primitive** in Phase 4A, then a **consolidation-only behavior
consumer** in Phase 4B once live telemetry has earned the behavior change.
Retrieval routing is **explicitly out of scope** for this milestone.

## Goals

- Persist a per-source-item, per-memory workstream id derived from existing
  signals — no new LLM calls, no new write-time semantic dependency.
- Surface workstream ids in `query_audit_log` and `query/debug` so any future
  retrieval investigation can compare candidates by workstream without
  re-running extraction.
- In Phase 4A, run a **structural dry-run metric** that compares
  `(container_ref, subject, category)` consolidation grouping with
  `(container_ref, workstream_id_or_pseudo_id, subject, category)` grouping
  on every consolidation event, and emit one of four kinds per group:
  `bad_merge_avoided`, `good_merge_preserved`, `good_merge_lost_suspected`,
  `novel_split_unknown`. No LLM call.
- In Phase 4B (gated on Phase 4A telemetry), switch consolidation strategies
  to the new key behind a feature flag, with a CLI rollback path.

## Non-Goals

- No retrieval-routing change. The Layer 2 evidence rules out hard
  ws-equality and a -200pp soft ws prior; a different routing shape is a
  separate investigation that the diagnostic surface this milestone ships
  will support.
- No rewrite of `same_thread_context_sufficient`.
- No packaging-locality-gate relaxation.
- No `pallium_workstream_hint` integrator-supplied API. The cascade derives
  workstream from existing signals only.
- No new memory type. Workstream is a scope/grouping concept, not a memory
  kind.

## Background

The full investigation history is in:

- `.local/research/topic_continuity_model_2026-05-29.md` (v5, the original
  research note — §4 strong-signal definition, §6 cascade lifecycle, §7.4
  Class A/B/C metric split, §10 explicit "do not build" warnings)
- `.local/research/topic_continuity_layer1_results_2026-05-29.md` (cluster
  evidence; consolidation-key dry-run preview)
- `.local/research/topic_continuity_layer2_results_2026-05-29.md` (the
  routing-gate refutation)
- `.local/research/topic_continuity_layer3_design_2026-05-29.md` (the
  rescoped design, of which this `docs/designs/` document is the
  human-architect-approved promotion)
- `.local/research/night_job_2026-05-29_log.md` (the execution journal)

Reference implementation of the cascade and signal extraction lives at
`.local/research/_workstream_replay/cascade.py` and
`.local/research/_workstream_replay/signals.py`. Phase 4A ports these to
`capabilities/workstreams.py` and `capabilities/workstream_signals.py`.

## Design — Phase 4A (diagnostic + dry-run)

Phase 4A introduces the schema, the cascade, the diagnostic surface, and the
dry-run metric. **No retrieval behavior changes. No consolidation behavior
changes.** Existing consolidation continues to use the
`(container_ref, subject, category)` key.

### Tables

Three new tables, all under `storage/sqlite_schema.py`. Existing tables are
not modified.

```sql
CREATE TABLE workstreams (
    id              VARCHAR PRIMARY KEY,         -- "ws:<sha1[:16]>" or pseudo-id
    container_ref   VARCHAR NOT NULL,
    visibility      VARCHAR NOT NULL,
    kind            VARCHAR NOT NULL,            -- "resolved" | "unknown"
    signature_blob  TEXT NOT NULL,               -- JSON of dominant signal set
    opened_at       DATETIME NOT NULL,
    last_touched_at DATETIME NOT NULL,
    closed_at       DATETIME,
    closed_reason   VARCHAR,                     -- "decay" | "merged_into" | NULL
    canonical_id    VARCHAR,                     -- if merged: target ws id
    created_by      VARCHAR NOT NULL DEFAULT 'thread_rebuild'
);
CREATE INDEX ws_container_visibility ON workstreams(container_ref, visibility);
CREATE INDEX ws_last_touched ON workstreams(last_touched_at);

CREATE TABLE memory_workstreams (
    memory_object_id VARCHAR NOT NULL,
    workstream_id    VARCHAR NOT NULL,
    assigned_at      DATETIME NOT NULL,
    PRIMARY KEY (memory_object_id, workstream_id),
    FOREIGN KEY (memory_object_id) REFERENCES memory_objects(id),
    FOREIGN KEY (workstream_id)    REFERENCES workstreams(id)
);
CREATE INDEX mw_ws ON memory_workstreams(workstream_id);
CREATE INDEX mw_mid ON memory_workstreams(memory_object_id);

CREATE TABLE source_item_workstreams (
    source_item_id  VARCHAR NOT NULL,
    workstream_id   VARCHAR NOT NULL,
    watermark       VARCHAR NOT NULL,            -- the rebuild watermark that assigned
    assigned_at     DATETIME NOT NULL,
    PRIMARY KEY (source_item_id, workstream_id, watermark),
    FOREIGN KEY (source_item_id) REFERENCES source_items(id),
    FOREIGN KEY (workstream_id)  REFERENCES workstreams(id)
);
CREATE INDEX siw_si ON source_item_workstreams(source_item_id);
CREATE INDEX siw_ws ON source_item_workstreams(workstream_id);
CREATE INDEX siw_wm ON source_item_workstreams(watermark);
```

Notes:

- Resolved id = `"ws:" + sha1(sorted-deduped strong-signal set)[:16]`.
  Replay-deterministic: same signal set always produces the same id.
- Unknown pseudo-id = `"unknown:{container_ref}:{thread_ref or 'NULL'}:{watermark}"`.
  Stored verbatim. **Non-joining by construction**: two unknown buckets in
  different (thread, watermark) tuples never collide. This is the property
  that prevents unknown groups from re-creating the broad-container merge
  problem the design is trying to fix.
- `canonical_id` + `closed_reason="merged_into"` is how stable-hash ids
  handle merges without rewriting history.
- Junction tables (not a column on `source_items` / `memory_objects`) because
  assignment is mutable across rebuild watermarks and we want
  re-running the cascade to be idempotent.

### Cascade

The reference implementation in
`.local/research/_workstream_replay/cascade.py` ports verbatim to
`capabilities/workstreams.py`. The 8 stages are, in order:

1. work_ref exact-match
2. file-path 2-segment-prefix overlap
3. distinctive symbol overlap (R3-disciplined regex: ≥2 internal capitals
   for CamelCase; snake_case callsites with ≥1 underscore and length ≥6)
4. explicit memory-title 3-gram overlap
5. workstream-anchor key match
6. same-thread recency tiebreaker (≤30 min, no other strong signal disagrees)
7. open-new (with self-referential protection: signals must differ from the
   most-recent open workstream in the scope)
8. unknown pseudo-id

A `STAGE_SELF_REF_ATTACH` defensive branch is retained — it does not fire
under stable-hash resolved ids in our corpus, but a future
non-deterministic-id strategy would need it.

Mechanism is **M1 delayed assignment** (per v5 §6.1): per-item extraction is
unchanged. The thread-rebuild that the per-item path already enqueues runs
the cascade against items new since the last watermark, then writes the
junction-table rows. Watermark = 5-minute bucket of `created_at` per
`(container_ref, thread_ref)`. Open workstreams remain open until
`last_touched_at + 14 days`; unknown workstreams older than 30 days that
never resolved are deleted.

### Diagnostic surface

Three additive surfaces, all populated from day 1:

1. **`query_audit_log.candidate_scores_json`** gains a `workstream_id` field
   per candidate, alongside existing `routing_score` / `lexical_score` /
   `vector_score` / `excluded_reason_code` / etc.
2. **`query_audit_log`** gains a row-level `query_workstream_id` next to
   `decision_reason`.
3. **`MemoryEnvelopeScope`** gains an optional `workstream_id`. Read-only
   for Phase 4A consumers; surfaced in API responses for debug only.
4. **`query/debug`** endpoint output includes the query workstream id and
   per-candidate workstream ids in the existing debug JSON.

These are additive — readers tolerate their absence on legacy rows.

### Dry-run consolidation metric

This is the metric that earns Phase 4B.

At consolidation time the existing strategies in
`semantic/conversational_knowledge.py:FactConsolidationStrategy` and the
`agent_conversation_memory` consolidation strategies (`thread_summary_anchored`,
`container_topic_window`, `thread_local_carry_forward`) compute **both** keys:

- old: `(container_ref, subject, category)`
- new: `(container_ref, workstream_id_or_pseudo_id, subject, category)`

Behavior uses the **old** key. The new key is recorded as a structural
metric:

```
consolidation.workstream_aware_dryrun{
    kind="bad_merge_avoided"     // old-key merged 2+ facts; new-key splits them across
                                  // workstreams; both new groups are resolved ws with
                                  // distinct signatures → split looks correct
  | "good_merge_preserved"        // old-key merged; new-key still merges (same workstream)
  | "good_merge_lost_suspected"   // old-key merged; new-key splits but the splits look
                                  // structurally suspicious (one workstream is unknown
                                  // pseudo-id; signatures share dominant signals; etc.)
  | "novel_split_unknown"         // splits caused by unknown pseudo-id only; informational
}
```

Classification is purely structural — no LLM call, no human-in-the-loop. A
periodic export rolls events into a daily report under
`.local/observability/workstream_dryrun/<date>.json` for architect spot-check.

### Acceptance criteria for promoting Phase 4A → Phase 4B

After ≥7 days of live Phase 4A telemetry on the production DB, with at least
200 consolidation events recorded:

- `good_merge_lost_suspected / total ≤ 5%` (gate; conservative because the
  offline T1.7 sample was small)
- `bad_merge_avoided / good_merge_preserved ≥ 0.10` (gate; the new key must
  *do something useful* often enough to justify shipping it into behavior)
- Architect spot-check on ≥20 `good_merge_lost_suspected` cases confirms the
  structural heuristic is not under-reporting real harm
- Workstream id stability ≥95% across consecutive rebuilds when no new strong
  signals arrive (gate; instability would mean the cascade is not yet
  deterministic enough to feed a behavior consumer)

If any gate fails, the design either iterates on the cascade signals or
holds Phase 4B until evidence improves. Phase 4A is permanent regardless —
the diagnostic surface and dry-run metric are useful even if Phase 4B never
ships.

## Design — Phase 4B (guarded consolidation re-key)

Phase 4B is **gated** on Phase 4A acceptance and is not approved at this
milestone. This section is the design that takes effect *if and when* the
gates clear.

Once the Phase 4A → 4B gates are met, the consolidation strategies switch
their grouping key to
`(container_ref, workstream_id_or_pseudo_id, subject, category)` behind
feature flag `consolidation.workstream_aware_key`. Default is `false`; it is
flipped to `true` to enable Phase 4B. The flag is at config level, not
per-call — the whole instance commits to one key at a time, otherwise
fact lineage diverges.

### Migration of existing `fact_summary` objects

- Existing `fact_summary` objects keep their evidence links; their old-key
  group identity is preserved.
- At Phase 4B activation, each existing group is given a unique sentinel
  pseudo-id of form `unknown:migration:{group_hash}` so the new key does
  not accidentally merge legacy groups under the new key. This deviates
  from the v5 §6.5 unknown shape (`unknown:{container}:{thread}:{watermark}`)
  because legacy groups have no thread/watermark; per-group migration hash
  is non-joining by construction (the hash differs across groups), which
  preserves the property that matters.
- A new flag `pallium consolidate-rekey --container <ref>` (CLI only,
  off-by-default) re-runs consolidation with the new key for one container,
  for operators who want to re-consolidate post-flag-flip. Bounded, opt-in.

## Backout

### Phase 4A backout — disable, don't drop

The Phase 4A surface is additive. Backout means **disable population and
use; leave the additive schema in place**:

1. Stop populating `workstreams`, `memory_workstreams`,
   `source_item_workstreams` from the thread-rebuild path (a single guard
   at the entry point of `capabilities/workstreams.py`).
2. Stop emitting the new `workstream_id` / `query_workstream_id` fields in
   `query_audit_log` rows. Readers tolerate their absence.
3. Stop emitting the dry-run metric.
4. Leave the schema in place. The empty/legacy rows are inert.

Dropping the columns/tables is a migration risk and is **not** the default
backout path. It is reserved for a fresh-DB reset that is explicitly chosen
by the operator. Production-class instances should not need to drop tables
to back out behavior-neutral diagnostics.

### Phase 4B backout

If Phase 4B live signal disagrees with Phase 4A telemetry — i.e. the
re-keyed consolidation produces unexpected harm at scale despite the
dry-run metric being green:

1. **Read-side backout (immediate, no migration):** flip
   `consolidation.workstream_aware_key` to `false`. New consolidations
   revert to the old key. Existing workstream-keyed `fact_summary` rows on
   disk remain valid memories; no new merges align with them.
2. **Write-side migration (only if consolidation produced bad data on
   disk):** `pallium consolidate-rollback --container <ref>` re-runs
   consolidation under the old key and replaces the workstream-keyed
   `fact_summary` rows.
3. **Schema retention:** the `workstreams`, `memory_workstreams`, and
   `source_item_workstreams` tables stay populated regardless — same
   principle as 4A: backout disables behavior, it does not drop additive
   schema.

## Verification

### Phase 4A tests

- `tests/test_workstream_cascade.py` — each of the 8 stages, plus
  self-ref protection, plus monorepo split, plus the unknown pseudo-id
  non-joining property.
- `tests/test_workstream_signals.py` — port the offline-reference
  R3-disciplined regexes (≥2 internal capitals for CamelCase; file-extension
  / top-dir / drive-prefix for paths; English-pair rejection).
- `tests/test_workstream_assignment_persisted.py` — ingest a fixture, run
  thread-rebuild, assert `workstreams` / `memory_workstreams` /
  `source_item_workstreams` rows match expectations.
- `tests/test_audit_log_workstream_field.py` — verify `query_audit_log`
  rows after this lands include the new fields.
- `tests/test_consolidation_dryrun_metric.py` — ingest a fixture with two
  clearly-separate workstreams; assert the metric records `bad_merge_avoided`
  for at least one collision and `good_merge_preserved` for at least one
  preserved group.

No new agent-simulation harness required for Phase 4A.

### Phase 4B tests (in addition)

- `tests/test_fact_consolidation_workstream.py` — behavioral test for the
  new key. Two clearly-separate workstreams; assert that with
  `consolidation.workstream_aware_key=true` the resulting `fact_summary`
  objects do not cross-merge; with the flag false they cross-merge exactly
  as today.
- `tests/test_fact_summary_migration_unknown_id.py` — flag-flip on a DB
  with existing `fact_summary` rows; assert legacy groups retain their
  evidence links and get unique sentinel ids.
- **Live-telemetry guard:** Phase 4B activation in production is
  conditional on the §3.5 acceptance criteria computed from
  `.local/observability/workstream_dryrun/`. This is a process gate, not
  a test.

### Eval addition (Phase 4A)

`evals/workstream_consolidation/` runner reproduces the offline T1.7
finding on the live DB. This is the regression guard for the dry-run
metric and the basis for re-verifying the Phase 4A → 4B acceptance
criteria over time.

## Boundary fit

- `capabilities/workstreams.py` (cascade, registry, lifecycle) and
  `capabilities/workstream_signals.py` (strong-signal extraction) — the
  new shared infrastructure. `capabilities/` is the right boundary because
  workstream assignment will be consumed by both `agent_conversation_memory`
  and `conversational_knowledge`, plus the audit-log surface (`api/`, `core/`)
  and any future routing investigation. `core/` is too low-level for code
  that depends on signal-extraction adapters; `semantic/` is too
  package-specific for shared infrastructure.
- Package-specific signal-extraction adapters MAY live near the semantic
  packages they belong to and register additional signal extractors with
  `capabilities/workstream_signals.py`.
- `semantic/conversational_knowledge.py:FactConsolidationStrategy` is the
  call site for the dry-run metric (Phase 4A) and the new key (Phase 4B).
  Its current shape takes an additional grouping field cleanly. No
  restructure needed.
- `core/models.py:MemoryEnvelopeScope` gets one additional optional field.
  Read-only for Phase 4A.
- `storage/sqlite_schema.py` adds three tables. No existing schema
  modification.

## What this design does not solve

For roadmap awareness, this milestone deliberately leaves three problems
open:

- The broad-container precision collapse at retrieval time (0–36% precision
  on monorepo-style containers) — Layer 2 evidence ruled out the
  workstream-as-routing-gate consumer; a different routing shape must come
  from a separate investigation.
- The `same_thread_context_sufficient` brittleness identified in the
  qualitative trace — same reason.
- The periodic injector probe degeneracy (a meaningful fraction of self-ref
  queries land in `unknown_query_tag` because the probe carries no
  workstream-bearing signals) — needs a different design surface, not
  workstream-aware retrieval.

The Phase 4A diagnostic surface this milestone ships is the workspace for
the next investigation on those problems.

## References

- v5 research note: `.local/research/topic_continuity_model_2026-05-29.md`
- Layer 1 results: `.local/research/topic_continuity_layer1_results_2026-05-29.md`
- Layer 2 results: `.local/research/topic_continuity_layer2_results_2026-05-29.md`
- Rescoped design draft (this document's source):
  `.local/research/topic_continuity_layer3_design_2026-05-29.md`
- Execution journal: `.local/research/night_job_2026-05-29_log.md`
- Reference cascade implementation: `.local/research/_workstream_replay/`
- Prior art on subject anchors:
  `roadmap/features/add-subject-workstream-anchor-filtering.md`,
  `semantic/agent_conversation_memory_anchors.py`
- Prior art on cross-surface continuity:
  `docs/designs/013-work-ref-cross-surface-continuity.md`
