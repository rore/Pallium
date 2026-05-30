# Workstream Consolidation Re-Key — Observability Experiment After Mixed Validation

Date: 2026-05-30
Status: Phase 4A approved as a **diagnostic-only observability experiment** · Phase 4B gated on telemetry **and** on closing two open Layer-1 negatives · routing consumer rejected for this milestone

## What this document is, after 2026-05-30 evidence

This is **not** a proven workstream architecture. It is a small, behavior-neutral
slice that lets us answer one question we cannot otherwise answer: **does a
deterministic structural workstream id, computed cheaply at thread-rebuild time,
move consolidation grouping toward something useful at production scale?**

A 2026-05-29 night-job draft of this design leaned on a positive framing
(high coverage, sane clusters, 81.5% broad-container mismatch). A subsequent
2026-05-30 replay (`.local/research/workstream_replay_2026-05-30/RESULTS.md`)
returned **UNCERTAIN, leaning FAIL**: broad-container contamination drop was
only 22.7% (bar 40%), focused containers fragmented above the bar
(1.50 ws/10 items vs gate ≤1.0), and R6 thread-continuity was responsible for
~67% of all assignments — meaning the gate mostly classifies by thread
identity, not by structural workstream signal. The consolidation simulation
direction was inverted: with `atomic_fact` already singleton-grouped under the
existing key, layering workstream on top can only merge or no-op, not split.

The slice is approved on a tighter framing than the night-job draft asked for:

- Phase 4A ships persistence + audit-log fields + structural dry-run metric.
  **No retrieval change. No consolidation behavior change.** It is observability
  only.
- The dry-run metric kinds are **neutral structural labels**, not quality
  verdicts (see §"Phase 4A — diagnostic + dry-run consolidation metric"). They
  describe what the new key would do to the old grouping; whether that is
  actually better is a separate question this slice does not answer.
- Phase 4B (turning the new key on for behavior) is **not approved**. It is
  gated on (a) the §"Acceptance criteria" telemetry, **and** (b) closing the
  two specific Layer-1 negatives the 2026-05-30 replay surfaced (focused
  fragmentation, weak structural signal coverage), **and** (c) a redesign of
  the consolidation-simulation baseline so the metric measures something
  meaningful on the live `fact_summary` corpus, not the singleton-grouped
  `atomic_fact` corpus.
- A future routing consumer is **explicitly rejected** for this milestone. The
  2026-05-29 Layer-2 evidence (Sonnet judge n=300: 60 better / 240 worse / 0
  neutral) ruled out workstream-as-routing-gate in both hard-equality and
  soft-prior forms. A workstream consumer at retrieval time would require a
  different consumer shape and a fresh investigation.

## Background — what we know from data, with caveats

A 2026-05-29 night-job exhaustively tested workstream-as-clustering and
workstream-as-routing-gate. The 2026-05-30 replay re-ran the cluster-side
metrics with a more rigorous harness. Combining both:

1. **The cluster signal exists, but is signal-thin and continuity-dominated.**
   Strong-signal coverage clears the ≥30% bar on every slice (35–49%),
   matching the night-job cascade's ability to extract real structural
   evidence. But work_refs are present at 4–11% only; commands /
   error-templates / durable-titles are sparse (<3% in 3 of 4 slices). The
   load-bearing strong signal is CamelCase symbol matching, which is mostly
   a side-effect of code references in the conversational corpus — not
   workstream identity. R6 thread-continuity carries 63–73% of assignments
   across slices; R1–R5 (the structural rules) seed each thread but R6 does
   the propagation. **The cascade is closer to "thread-aware grouping" than
   "structural-signal grouping" on this corpus.**

2. **Wrong-topic contamination drop is real but undersized.** On the 35
   rated injections in `broad_A`, the workstream gate would correctly drop
   ~9 of 22 `not_relevant` injections — a relative drop of 22.7%, well
   below the 40% bar. On `self_ref_A` (n=306 rated) the relative drop is
   16.7%. **This is structural lift, but a small fraction of what the
   night-job draft anticipated.** Sample size on `broad_A` is small enough
   that the 95% Wilson interval easily spans 10–40%; either more ratings or
   an architect-approved Class B judge pass is needed before declaring a
   hard FAIL.

3. **Focused containers fragment above the bar.** `focused_A` produces 27
   workstreams over 180 items (1.50 ws/10 items vs gate ≤1.0); `focused_B`
   1.17. Only the largest slice `self_ref_A` (0.90) passes. The cascade
   over-splits coherent topics in focused containers. Whether this is
   fixable by lengthening R6's thread-lookback or adding an "explicit
   thread-task continuity" anchor is an open design question, not part of
   this slice.

4. **Using the cluster boundary as a retrieval gate is net-negative
   (independent evidence from 2026-05-29 Layer 2).** Sonnet LLM-as-judge
   on n=300 candidates across four slices and two routing variants (hard
   equality and -200pp soft prior) returned 60 better / 240 worse / 0
   neutral. Architect-classified cross-thread sample (n=20) returned 4
   helpful candidates dropped vs 2 harmful avoided. The cluster boundary
   is tighter than the human notion of "same work"; ws-equality filtering
   throws away genuine cross-workstream recall faster than it removes
   harmful cross-topic noise. **The retrieval consumer is therefore out of
   scope for this design; a future routing consumer must have a
   fundamentally different shape than what was tested.**

5. **Consolidation simulation is direction-wrong against `atomic_fact`.**
   `atomic_fact` rows in the live DB are already singleton-grouped under
   `(container_ref, subject, category)`; adding workstream as a fourth key
   dimension can only merge or no-op, not split. The night-job's "1014 →
   1153 groups (+13.7%)" headline was on a different baseline that the
   2026-05-30 replay could not reproduce. **The Phase 4A dry-run metric
   therefore mostly measures `single_workstream_group` events on
   `atomic_fact`** — which is fine (it confirms the new key doesn't
   accidentally re-merge facts that should stay split), but it means the
   metric is not the primary evidence for whether 4B should activate. The
   primary evidence will come from `fact_summary` and the
   `agent_conversation_memory` consolidation strategies once the slice
   runs against live data.

The re-scoped design ships only what 4A's data supports: persistence and
observability. Phase 4B's evidence requirement is now larger than the night
job assumed — see §"Acceptance criteria for promoting Phase 4A → Phase 4B"
below.

## Goals

- Persist a per-source-item, per-memory workstream id derived from existing
  signals — no new LLM calls, no new write-time semantic dependency.
- Surface workstream ids in `query_audit_log` and `query/debug` so any future
  retrieval investigation can compare candidates by workstream without
  re-running extraction.
- In Phase 4A, run a **structural dry-run metric** that compares the existing
  consolidation grouping with a workstream-aware variant on every consolidation
  event. The metric kinds are **heuristic structural labels, not judged
  quality**: `split_resolved_groups`, `single_workstream_group`,
  `split_with_unknown_or_overlap`, `split_all_unknown`. No LLM call. The
  metric tells us *what the new key would do*; whether that is good or bad
  is a Class B/C question this slice does not answer.
- In Phase 4B (gated on Phase 4A telemetry **and** the additional
  preconditions in §"Acceptance criteria"), switch consolidation strategies
  to the new key behind a feature flag, with a CLI rollback path.

## Non-Goals

- No retrieval-routing change. The 2026-05-29 Layer 2 evidence rules out
  hard ws-equality and a -200pp soft ws prior; a different routing shape is
  a separate investigation that the diagnostic surface this milestone ships
  will support.
- No rewrite of `same_thread_context_sufficient`.
- No packaging-locality-gate relaxation.
- No `pallium_workstream_hint` integrator-supplied API. The cascade derives
  workstream from existing signals only.
- No new memory type. Workstream is a scope/grouping concept, not a memory
  kind.
- **No claim that workstream is the right primitive yet.** Phase 4A is
  observability that lets us decide. Phase 4B activation requires real
  evidence beyond what 4A's structural metric alone can produce.

## Background — full investigation history

The investigation that produced this slice ran in two passes with a substantive
disagreement between them:

- `.local/research/topic_continuity_model_2026-05-29.md` (v5 night-job draft;
  §4 strong-signal definition, §6 cascade lifecycle, §7.4 Class A/B/C metric
  split, §10 explicit "do not build" warnings)
- `.local/research/topic_continuity_layer1_results_2026-05-29.md` (Layer 1
  cluster evidence; positive framing)
- `.local/research/topic_continuity_layer2_results_2026-05-29.md` (Layer 2
  routing-gate refutation)
- `.local/research/topic_continuity_layer3_design_2026-05-29.md` (rescoped
  Layer 3 design; the source of this `docs/designs/` doc)
- `.local/research/night_job_2026-05-29_log.md` (execution journal)
- **`.local/research/workstream_replay_2026-05-30/RESULTS.md`** (independent
  re-run of the Layer 1 cluster metrics with a more rigorous harness;
  **UNCERTAIN-leaning-FAIL on contamination drop and focused fragmentation**;
  this is the harder evidence and is reflected in §"What this document is" above)
- `.local/research/phase_4a_implementation_log.md` (this implementation's
  pre/post-implementation architect-review journal)

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

This metric is **observability**, not a decision oracle. It tells us what the
new key would do at production scale; whether the new key is actually better
is a separate Class B/C question that this slice does not answer.

At consolidation time the existing strategies in
`capabilities/consolidation.py:FactConsolidationStrategy` and the
`agent_conversation_memory` consolidation strategies (`thread_summary_anchored`,
`container_topic_window`, `thread_local_carry_forward`) compute **both** keys:

- old: `(container_ref, subject, category)` (or, for fact_consolidation, the
  4-tuple `(container_ref, subject, category, visibility)` — same idea)
- new: same key plus `workstream_id_or_pseudo_id` as an additional dimension

Behavior uses the **old** key. The new key is recorded as a structural
metric **with neutral, descriptive kind names** — chosen after the
2026-05-30 replay rejected the night-job's quality-laden draft names
(`bad_merge_avoided`, `good_merge_preserved`, `good_merge_lost_suspected`,
`novel_split_unknown`) as implying judgements the data does not support:

```
consolidation.workstream_aware_dryrun{
    kind="split_resolved_groups"          // old-key merged ≥2 candidates; new-key splits
                                          //   them across ≥2 distinct *resolved* workstreams
                                          //   (no unknown buckets in the partition)
  | "single_workstream_group"             // old-key merged; new-key sees one workstream
                                          //   covering the group (no split)
  | "split_with_unknown_or_overlap"       // old-key merged; new-key splits but at least
                                          //   one resulting partition is an unknown
                                          //   pseudo-id (mixed resolved + unknown)
  | "split_all_unknown"                   // splits caused entirely by unknown pseudo-id
                                          //   partitioning (every partition is unknown)
}
```

These names are heuristic structural categories: they describe *what would
happen to the grouping*, not whether the new grouping is correct. A
`split_resolved_groups` event is **not** a "bad merge avoided" — it is a
record that the new key would split, and the resulting partitions both
carry resolved (non-unknown) workstream ids. Whether that split is
genuinely useful, harmful, or noise is a Class B/C judgement question.

Classification is purely structural — no LLM call, no human-in-the-loop. A
periodic export rolls events into a daily report under
`.local/observability/workstream_dryrun/<date>.json` for architect spot-check.

### Acceptance criteria for promoting Phase 4A → Phase 4B

These criteria are **necessary, not sufficient**. They are the minimum
structural signal Phase 4A can produce. Even if every gate below passes,
Phase 4B activation requires three additional preconditions (in §"Open
preconditions" below) that the 2026-05-30 replay surfaced and which Phase
4A's structural metric alone cannot resolve.

After ≥7 days of live Phase 4A telemetry on the production DB, with at least
200 consolidation events recorded:

- `split_with_unknown_or_overlap / total ≤ 5%` (structural gate; high values
  mean the new key is mostly creating ambiguous splits where unknown buckets
  contaminate resolved groupings — exactly what the unknown pseudo-id design
  was trying to prevent at the grouping level)
- `split_resolved_groups / single_workstream_group ≥ 0.10` (structural gate;
  the new key has to *do something* often enough to justify the schema
  change shipping into behavior; if effectively every event is
  `single_workstream_group`, the new key changes nothing and Phase 4B is
  pointless)
- Architect spot-check on ≥20 `split_with_unknown_or_overlap` cases to read
  whether the events look like real ambiguity or instrumentation artifacts
- Workstream id stability ≥95% across consecutive rebuilds when no new strong
  signals arrive (gate; instability would mean the cascade is not yet
  deterministic enough to feed a behavior consumer)

### Open preconditions (in addition to the structural gates above)

The 2026-05-30 replay surfaced three additional gaps that Phase 4A's
structural metric alone cannot close. Phase 4B activation requires all
three:

- **Focused-container fragmentation must drop below 1.0 ws / 10 items.** The
  replay measured `focused_A` 1.50, `focused_B` 1.17. Phase 4A telemetry on
  live data (using the cascade as shipped) needs to confirm whether this
  improved or whether the cascade still over-splits focused threads. If
  focused fragmentation is still above the bar, the cascade itself needs
  redesign before turning the new key on for behavior — likely a longer
  R6 thread-lookback, or a thread-pinning anchor.

- **Wrong-topic contamination drop on the broad slice must reach ≥40%
  relative**, with confidence intervals tight enough to clear the bar. The
  replay measured 22.7% (n=35); doubling the rated injections (or running
  an architect-approved Class B Sonnet judge pass on unrated injections)
  is required before any Phase 4B claim.

- **Consolidation-simulation baseline must be redesigned away from
  `atomic_fact`.** Atomic facts are already singleton-grouped under the
  existing key, so the dry-run metric on `atomic_fact` mostly produces
  `single_workstream_group` events that are uninformative. The simulation
  needs either a `fact_summary` baseline or a different consolidation seed
  before the structural metric can be read as evidence for or against the
  new key.

If any of these three preconditions fails, **Phase 4B is held**. Phase 4A
is permanent regardless — the diagnostic surface, audit-log fields, and
dry-run telemetry remain useful even if Phase 4B never ships, because they
are the workspace for the follow-up investigation that would close the gaps.

If a 4A telemetry window completes and the structural gates above pass but
the open preconditions do not, the right outcome is **a new investigation
to address the preconditions**, not a 4B activation. Workstream is the
right primitive *iff* the data eventually says it is.

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
  clearly-separate workstreams; assert the metric records `split_resolved_groups`
  for at least one collision and `single_workstream_group` for at least one
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
