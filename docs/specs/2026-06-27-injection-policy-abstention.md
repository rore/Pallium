# Injection Policy: Abstention Over Mechanism

**Date:** 2026-06-27
**Status:** Plan — not yet implemented
**Owner:** Rotem Hermon
**Supersedes / gates:** `add-operational-fact-memory`, `investigate-thread-level-interest-and-threadless-aggregation` (paused pending this experiment)

## Background

Pallium has shipped ~14 major mechanism iterations in 6 months (FTS5, RRF fusion,
multilingual tokenization, cue-free routing, anchor prefilter tiers, work_refs,
lifecycle states, etc.). Despite all of it, real-use feedback signal indicates
proactive injection is the dominant failure surface.

A directed analysis (2026-06-27, see also Codex independent review) on 593–617
self-rated injections joined to `query_audit_log` shows:

- Base precision: ~44% across all containers.
- Bad-injection rates: 68% on multi-context container (xlm), 53% on focused
  containers (pallium, minimap).
- ~95% of bad injections are topically-similar-but-question-irrelevant for the
  current turn (free-text manual classification; not a labeled field).
- Score distributions overlap heavily for `investigation_outcome` (the most
  injected type), `thread_summary`, and `fact_summary`.
- The repo already evaluated workstream-based routing in
  `docs/designs/014-workstream-consolidation-rekey.md` and rejected it
  (60 better / 240 worse judged variants, only 22.7% contamination reduction).

**Conclusion:** The next-direction failure mode is not extraction, retrieval,
routing, lifecycle, scope, or graph structure. It is that the proactive
injection signal cannot reliably tell whether a topically-similar memory
answers the current question. The right next move is **abstention discipline
and selective delivery**, not a 15th mechanism.

Three independent reviews (me, reviewer 1, Codex architect review) converge on
this direction.

## Goals

1. Reduce proactive-injection bad rate from ~55% to ≤25% (≥75% precision)
   measured on held-out data.
2. Preserve the high-value subset: stable project facts that the agent
   could not recover from session context, git, CLAUDE.md, or asking.
3. Avoid building any new mechanism (no graph, no structural_scope, no
   episode segmentation, no new memory type).
4. Establish a measurement loop that distinguishes "relevant" from "useful"
   (next-action change), not just self-rated relevance.

## Non-Goals

- Building structural scope, component nodes, work-episode segmentation, or
  a graph layer. The 014-workstream investigation and the score-overlap data
  both argue against these.
- Deleting any memory type or stored data. Disable proactive injection only;
  preserve the data and bring types back if on-demand proves useful.
- Re-tuning extraction prompts or retrieval scoring. Those have been
  shipped repeatedly without moving the product-usefulness needle.

## Final Policy Shape

| Type | Mode | Trigger |
|---|---|---|
| `constraint_memory` | proactive | block-score ≥ holdout-validated threshold (initial ~20) |
| `decision` | proactive | block-score ≥ holdout-validated threshold (initial ~22) |
| `task_checkpoint` | **event-triggered** | session resumption / "where was I" / branch+path matches recent checkpoint — NOT score-based |
| `investigation_outcome` | trigger-based on-demand | failure events, "have we hit this before", N retries |
| `thread_summary` | explicit on-demand only | `pallium_query` only |
| `fact_summary` | suspended | insufficient data (n=10) + pipeline known broken (see 616f2f55 review) |

### Critical implementation note (from Codex review)

The gate is **the injected-block `score` field** (from result evidence), NOT
`routing_score`. Same thresholds applied to `routing_score` only yield ~52%
precision instead of ~76%. Implementation must document the field explicitly
and reference it in code.

## Plan — Phases

### Phase 0 — Persist plan and freeze findings (today)

- [x] This spec written and committed.
- [ ] Snapshot the analysis as a reproducible script:
      `evals/injection_policy_2026_06/analyze.py` — pulls feedback joined to
      audit log, computes per-type precision/recall and current proposed
      thresholds. Re-runnable as new data arrives.
  - Output: stdout always. `--output <path>` writes ad-hoc runs to
    `.local/research/` by default. One committed reference snapshot at
    `evals/injection_policy_2026_06/snapshot_2026-06-27.json` backs the
    spec's headline numbers (75%/92%/29%).
  - Script also reports the same precision/recall computation against
    `routing_score` as a sanity check on the field-choice claim
    (~52% precision vs ~76% under result `score`).
  - Join key: `(memory_object_id, query_audit_log_id)` so each rating
    scores a specific injection event. Reuse `majority_rating()` from
    `evals/retrieval_ablation/evaluate.py` for duplicate-rating handling.
  - Holdout split is **out of scope for Phase 0** — that's Phase 1.
- [ ] Snapshot the current state of the open roadmap items being paused
      (`add-operational-fact-memory`, `investigate-thread-level-interest-and-threadless-aggregation`) with a note pointing back here.

### Phase 0.5 — Audit-data instrumentation prerequisite

**Blocker for Phase 2 surfaced in architect review:** current
`candidate_scores_json` written by `core/service.py` snapshots
`routing_score`, `lexical_score`, `vector_score` per candidate but does
NOT carry the result `score` field that the policy actually gates on.
That means historical `candidate_scores_json` cannot support an exact
decision-simulation replay against the proposed thresholds.

- [ ] Extend the candidate snapshot in `core/service.py` (`ranked_candidates`
      loop, ~line 709) to additionally persist:
  - `score` (result evidence score — same field used by the policy)
  - `retrieval_source` (lexical / vector / both / fused)
- [ ] Schema-compatible — `candidate_scores_json` is opaque JSON, no SQL
      migration needed. Old rows simply omit the new fields.
- [ ] Land this BEFORE Phase 1's holdout analysis so the held-out window
      includes the new fields; otherwise Phase 2 has to be flagged as
      "approximate historical replay + exact prospective replay" and we
      need a fresh-data window for the exact replay.

### Phase 1 — Chronological holdout validation

Goal: produce real (not selection-on-train) precision numbers for the
proposed thresholds.

**Phase 1 RESULT (2026-06-27)** — see
[`evals/injection_policy_2026_06/holdout_2026-06-27.json`](../../evals/injection_policy_2026_06/holdout_2026-06-27.json):

After deduplicating duplicate ratings (617 → 606 events; 11 pairs
collapsed, 3 ties resolved to `not_relevant`) and applying the
chronological 80/20 split (train n=484, holdout n=122):

| Type | Train thr | Holdout precision | Holdout kept | Disposition |
|---|---|---|---|---|
| `constraint_memory` | 12.0 | 0.00% (kept=2) | n/a | demote_to_on_demand |
| `decision` | 19.0 | **62.50%** (kept=16) | n/a | demote_to_on_demand |
| `investigation_outcome` | 23.0 | 50.00% (kept=6) | n/a | demote_to_on_demand |
| `task_checkpoint` | 13.0 | 50.00% (kept=6) | n/a | reference_only |
| `thread_summary` | — | — | n/a | demote_to_on_demand |
| `fact_summary` | — | — | n/a | suspend_insufficient_data |

**No type met the ≥70% precision pass bar on held-out data.**
`recommended_final_policy` is empty.

This is exactly the selection-on-train risk reviewer 1 flagged: the
Phase 0 "75%" was best-threshold-on-the-same-data; on chronologically
later data the same thresholds do not hold.

**Implication for downstream phases:**
- Phase 3a's TOML config cannot ship a per-type proactive threshold
  derived from current data. The honest production state if we shipped
  this today is **no proactive injection for any type**, with all
  current types moving to event-/trigger-based or on-demand only.
- That outcome aligns with the spec's "abstention discipline" framing
  but is more drastic than the original policy table proposed.
- Phase 3a should ship a config schema that supports per-type
  proactive thresholds (so future tighter data can opt types back in)
  but its **initial values** must be empty or extremely conservative
  pending fresh data.


- [ ] Split `memory_feedback` joined rows by `created_at`: 80% train / 20%
      held-out tail.
- [ ] Derive per-type thresholds on train only.
- [ ] Report precision, recall, kept count on held-out tail per type AND
      overall.
- [ ] Pass bar per type:
  - `constraint_memory`, `decision`: held-out precision ≥ 70% with
    ≥10 kept. Failing → demote to on-demand.
  - `task_checkpoint`: does **not** use a score-threshold gate (Phase 4
    event-trigger is its real path). Phase 1 just reports its
    held-out separability for reference; no gate decision is made
    here for this type.
  - `investigation_outcome`, `thread_summary`, `fact_summary`: reported
    but already slated for on-demand demotion regardless.

### Phase 2 — Decision-simulation replay (not just filter-over-injected)

The Phase 1 calculation filters blocks that were already chosen by the
existing pipeline. Production behavior is different — the policy interacts
with candidate filling, caps, replacement, supplements.

**Architect-review caveat:** historical `candidate_scores_json` does
**not** carry the result `score` field. Until Phase 0.5's
instrumentation has accumulated a fresh data window, this phase splits:

- **Phase 2a — approximate historical replay:** use existing
  `candidate_scores_json` with available signals (`routing_score`,
  `lexical_score`, `vector_score`). Report as upper bound on bad-rate
  impact only; do not rely on precision numbers here.
- **Phase 2b — exact prospective replay:** after Phase 0.5 instrumentation
  has run for ≥1 week of fresh audit data, replay against the new
  candidate snapshots using the real `score` field.

**Phase 2a RESULT (2026-06-27)** — audit-trail artifact, not a
validation step (see
[`evals/injection_policy_2026_06/decision_replay_2026-06-27.json`](../../evals/injection_policy_2026_06/decision_replay_2026-06-27.json)):

Across 3313 audit rows / 2487 evaluated queries / 15,717 historical
candidates, applying the proposed thresholds to `routing_score` (the
only score field present in historical snapshots — see Phase 0.5):

| Variant | Thresholds | Precision | Kept | Substituted | Prod-Dropped |
|---|---|---|---|---|---|
| `spec_headline` | constraint_memory>=20, decision>=22, task_checkpoint>=14 | **51.38%** | 5459 | 4807 | 867 |
| `phase1_derived` | constraint_memory>=12, decision>=19, investigation_outcome>=23, task_checkpoint>=13 | **44.86%** | 8029 | 6826 | 316 |

The 51.38% reproduces Codex's prior ~52% prediction for the routing-score
sanity check exactly. Confirms `routing_score` is the wrong field; the
real `score` field is what the policy must gate on. The high
`substituted_in` counts (4807, 6826) show that the simulation diverges
substantially from production-injected sets — a per-type score gate
would surface many candidates production did not inject. Whether those
substitutions are useful injections cannot be judged from this data
alone (most are unrated).

Phase 2a is now closed. Phase 2b will re-run after fresh data
accumulates with Phase 0.5's `score` field.

- [ ] Update or replace `evals/injection_precision_eval.py` to mirror
      current production gates (per inspection in
      `semantic/agent_conversation_memory_routing_selection.py`).
- [ ] Replay against `candidate_scores_json` modeling: type-aware
      allowlist, per-type score threshold, candidate filling order,
      top-K caps.
- [ ] Pass bar (Phase 2b only): simulated precision close to Phase 1's
      filter precision (within 5%) and total injection volume per query
      within reason (not collapsed to zero, not exploded).

### Phase 3 — Implementation (staged, NOT a single flag flip)

Architect-review finding: if Phase 3 demotes `task_checkpoint` and
`investigation_outcome` before Phase 4's triggers are live, those types
become dead — no proactive path and no on-demand path. Sequence the
flag rollout to prevent that.

**Phase 3a STATUS (shipped 2026-06-27):** config schema + gate landed.
With absent `[injection]` section the gate is a bit-exact no-op
(verified across 2314 tests, 218 in the routing/selection/audit
neighbourhood).

The Phase 3a config schema is concretely:

```toml
[injection.policy.types.constraint_memory]
mode = "proactive"      # or "event" | "on_demand" | "suspended"
min_score = 20.0        # required when mode = "proactive"

[injection.policy.types.decision]
mode = "proactive"
min_score = 22.0

[[injection.policy.containers]]
container_ref = "git:github.com/rore/pallium"

[injection.policy.containers.types.constraint_memory]
mode = "proactive"
min_score = 20.0
```

Container override matching is exact string equality against
`query_filters.container_ref`. Duplicate `container_ref` entries are
rejected at load time. The loader is in
`app/config.py::_build_injection_config`; the gate lives at
`semantic/agent_conversation_memory_routing_selection.py::_policy_allows_proactive_injection`.

**Per Phase 1 finding (no type passes ≥70% on holdout) the default
`pallium.local.toml` does NOT set any `[injection.policy.*]` keys.**
Phase 3b will be a TOML-only edit (no code change) that flips the
non-proactive types to `event`/`on_demand`/`suspended` once Phase 4
triggers are live.

**Phase 3a — proactive thresholds for the surviving types only** (ship first):

This is a staging step, not the final abstention policy. The headline
≥75% precision goal is achieved only after Phase 3b + Phase 4 ship
together. Phase 3a deliberately leaves `investigation_outcome`,
`thread_summary`, and `fact_summary` proactive (unchanged) to avoid
making them dead before triggers exist.

- [ ] Add config block in `pallium.local.toml` schema. TOML keys cannot
      cleanly hold raw container refs like `git:github.com/rore/pallium`
      or `path:xlm:2889e4f8fd37` as bare path segments. Use an array of
      tables keyed by an explicit `container_ref` field:

      ```toml
      [injection.policy]
      # default per-type policy applied when no container override matches
      [injection.policy.types.constraint_memory]
      mode = "proactive"
      min_score = 20

      [injection.policy.types.decision]
      mode = "proactive"
      min_score = 22

      # other types omitted in Phase 3a — they keep current behavior

      [[injection.policy.containers]]
      container_ref = "git:github.com/rore/pallium"
      # per-type overrides under .types.*
      [injection.policy.containers.types.constraint_memory]
      mode = "proactive"
      min_score = 20
      ```

      Matching: exact `container_ref` match wins; otherwise falls back
      to global `[injection.policy.types.*]`; otherwise current behavior.
- [ ] First flag value (`proactive_thresholds_only`): apply per-type
      score thresholds **only to `constraint_memory` and `decision`**.
      All other types (`task_checkpoint`, `investigation_outcome`,
      `thread_summary`, `fact_summary`) keep current behavior in Phase 3a.
      `task_checkpoint`'s real path is the Phase 4 event trigger, not a
      score threshold — it is intentionally untouched here.
- [ ] Enforce in `semantic/agent_conversation_memory_routing_selection.py`
      candidate-filtering path. **Implementation must gate on the result
      `score` field (the same field surfaced into
      `injected_blocks_json[*].score`), NOT `routing_score`.** Documented
      inline and verified by a unit test that asserts the field name.
- [ ] Tests: per-type unit tests on the gate, snapshot test that default
      config preserves today's behavior, eval-driven regression that
      replays the holdout corpus on every PR touching routing/selection.

**Phase 3b — demote weak types** (ship together with Phase 4):
- [ ] Flip `investigation_outcome`, `thread_summary`, `fact_summary` to
      non-proactive modes only AFTER Phase 4 triggers are live and
      passing their own quality gate (see Phase 4 pass bar).
- [ ] `task_checkpoint` switches from score-threshold to event-trigger
      mode in the same flag flip.

### Phase 4 — Deterministic triggers for on-demand types

Without triggers, on-demand types become dead code (agents don't know what
they don't know — Reviewer 1 explicit warning).

**Phase 4 STATUS (shipped 2026-06-27).** Pallium-side infrastructure
landed; integration hooks (Claude Code) updated. Codex parity deferred.

Architect-review finding: triggers must stay structural to honor the
"language-agnostic structural signals" decision (`docs/context/decisions.md`
2026-05-30). NL phrase cues are allowed only as **explicit user-issued
commands**, never as the primary signal.

**Pallium-side surface (this commit):**
- `QueryRequest.trigger_origin` (string, optional, validated against an
  enum-like set at the route handler).
- `ItemAndQueryRequest.query_trigger_origin` (same shape).
- `query_audit_log.trigger_origin` column (additive migration —
  backward compatible; NULL for legacy rows).
- Whitelisted values: `session_start_orientation`, `user_prompt_submit`,
  `pre_compact`, `session_start_checkpoint`, `post_tool_failure`,
  `retry_threshold`, `user_explicit`.
- The abstention gate from Phase 3a now also accepts `trigger_origin`.
  When the value is in `_TRIGGER_BYPASS_ORIGINS` (the deterministic
  on-demand triggers — `session_start_checkpoint`, `post_tool_failure`,
  `retry_threshold`, `user_explicit`), `event`/`on_demand`/`suspended`
  type candidates are allowed through. Proactive thresholds still
  apply regardless of trigger.

**Integration hooks updated:**
- `session_start.py`: tags the existing orientation query with
  `trigger_origin="session_start_orientation"` for audit-log analysis.
- `pre_compact.py`: tags pre-compact queries with
  `trigger_origin="pre_compact"`.
- `user_prompt_submit.py`: tags proactive prompt-submit queries with
  `query_trigger_origin="user_prompt_submit"`.
- **New** `post_tool_use.py`: registered as `PostToolUse` hook via
  setup_claude_code. Two triggers:
  - `post_tool_failure`: fires on non-zero exit code; queries with
    a redacted error signature.
  - `retry_threshold`: counts per `(session, tool, normalized_target)`;
    at N≥3 same-target failures, fires a second query. Counter is
    reset on success. State file at `~/.pallium/hooks/state/retry_counters/<session>.json`.

**Triggers NOT implemented (out of scope; documented):**
- `task_checkpoint` cwd-change and branch-checkout triggers — Claude
  Code does not expose hooks for these events. Possible future work
  via a git post-checkout hook or external watcher.
- Codex integration triggers — the Codex hook layer has no
  PostToolUse-equivalent. Deferred to a follow-up.

**Phase 3b STATUS (shipped 2026-06-27).** The demotion config is now
documented in `pallium.example.toml` as a commented-out block. Users
opt in by copying the block into their `pallium.local.toml`. The
default behaviour remains: no `[injection.policy]` section → bit-exact
no-op (Phase 3a property preserved).

The recommended Phase 3b config:
- `task_checkpoint`: `event` (uses Phase 4 PostToolUse / SessionStart
  triggers)
- `investigation_outcome`: `on_demand` (uses PostToolUse failure +
  retry triggers)
- `thread_summary`: `on_demand` (explicit `pallium_query` only)
- `fact_summary`: `suspended` (pipeline known broken)

**Phase 4 pass bar (required before Phase 3b flip on a real container):**
- Triggers fire on ≥X% of structurally eligible turns (number set during
  Phase 4 dry-run on existing audit data).
- At least one structural trigger type produces hits with held-out
  precision ≥70%.

**Known limitation:** this run ships Phase 4 INFRASTRUCTURE (trigger
plumbing + reference hooks + audit-log enhancement). It cannot validate
Phase 4 OUTCOMES (whether agents actually use on-demand types via these
triggers and whether the resulting injections are useful). That requires
the Phase 6 measurement window — 4 weeks of live data — which is the
final phase.

### Phase 5 — Useful-not-just-relevant feedback

Current feedback signal is "did this seem on-topic." The product metric
is "did the agent's next action change because of it."

Architect-review finding: this is a usage-telemetry signal, not a human
rating. It does NOT belong on `memory_feedback` (which is a
human/self-rating table). Many injections never get a rating; mixing
auto-usage with explicit rating would undercount and conflate.

**Phase 5a STATUS (shipped 2026-06-27).** Pallium-side surface
landed. Phase 5b (the integration-side populator hook) deferred per
the staging discipline used in Phases 3a/3b and 4.

**Phase 5a — Pallium-side (shipped):**
- New `memory_usage_audit` table (declarative `MemoryUsageAuditRecord`).
- Indexes: `(query_audit_log_id)`, `(memory_object_id, created_at DESC)`,
  `(memory_type, trigger_origin, created_at)`, `(container_ref,
  created_at)`, and a partial index on `populated_at IS NULL` for
  populator-sweep efficiency.
- Denormalized fields (`memory_type`, `container_ref`, `thread_ref`,
  `trigger_origin`) so Phase 6 rollup queries are a single indexed
  scan, not multi-join.
- Storage methods:
  `write_memory_usage_audit_rows(query_audit_log_id, injected_blocks, ...)`,
  `list_memory_usage_audit_rows(query_audit_log_id)`,
  `update_memory_usage_audit_row(audit_row_id, ...)`.
- Service-level `write_query_audit` now writes one usage-audit row per
  injected block alongside the audit-log row, with
  `referenced_in_next_turn=NULL` / `populated_at=NULL`.
- API endpoints:
  - `GET /memory-usage-audit?query_audit_log_id=...`
  - `POST /memory-usage-audit/{audit_row_id}` with
    `{referenced_in_next_turn, reference_kind, observation_window_turns}`.
    Validation: `reference_kind` is required when
    `referenced_in_next_turn=true`; must be one of
    `id_quote / verbatim_snippet / entity_match`.
  - Idempotent: POSTing to an already-populated row returns
    `updated: false`. Phase 5b populator can safely retry.

**Phase 5b — populator hook (deferred):**
- Lives in `integrations/claude-code/hooks/stop.py`. After ingesting
  the assistant response, observe recent queries in the thread, run
  a heuristic matcher against the transcript, and POST results.
- Minimum-viable matcher: id_quote OR verbatim_snippet ≥ 40 chars.
- `entity_match` deferred (NER-heavy; high false-positive risk).
- Contract documented in `stop.py` docstring so Phase 5b reads
  straightforwardly.

`memory_feedback` stays the human-rating table — unchanged by Phase 5.

### Phase 6 — One-month measurement window

**Phase 6 STATUS (infrastructure shipped 2026-06-27, measurement
window pending live data accumulation).**

- [x] Phase 6 measurement script committed at
      `evals/injection_policy_2026_06/phase6_measurement.py` with full
      pure-rollup test coverage. Produces three reports:
  - Per-`memory_type` proactive precision (usage_rate from
    `memory_usage_audit` + rating_precision from `memory_feedback`).
  - Per-`trigger_origin` usage rates.
  - Demoted-type discovery: how often each on-demand type is actually
    retrieved via a trigger.
- [x] Phase 6 runbook committed at
      [`docs/runbooks/2026-06-27-injection-policy-phase6.md`](../runbooks/2026-06-27-injection-policy-phase6.md)
      with preconditions, the decision matrix, and sample-size
      guardrails.

- [ ] Ship Phase 3a (proactive thresholds for `constraint_memory` +
      `decision` only) behind flag in default config; opt-in per
      container via `[[injection.policy.containers]]` entries keyed by
      `container_ref`.
- [ ] Turn flag on for `xlm` and `pallium` containers via per-container
      override. Default behavior stays unchanged for all other
      containers until Phase 6 measurement.
- [ ] Ship Phase 3b + Phase 4 together once Phase 4 pass bar is met.
- [ ] After 4 weeks of live data:
  - Held-out precision per type from new feedback.
  - Per-type `referenced_in_next_turn` rate (from Phase 5
    `memory_usage_audit`).
  - On-demand query frequency by trigger type, hit rate, useful rate.
  - Compare proactive-only-active types vs prior all-active baseline.
- [ ] Decide:
  - Hold policy if precision is up and on-demand is used.
  - Tighten thresholds if precision regressed.
  - Permanently delete on-demand types that are never queried.

## Decision Gates Between Phases

- Phase 1 fails (precision <70% on holdout) → revisit per-type policy or
  re-examine score field choice before Phase 2.
- Phase 2 fails (simulated production behavior diverges materially from
  Phase 1 numbers) → rethink the implementation surface; do not ship.
- Phase 4 measurement shows triggers never fire → triggers are wrong
  shape; revisit before scaling.
- Phase 6 shows on-demand types unused → delete them; the product is
  just the small proactive set.

## What This Plan Avoids

- Another extraction/prompt iteration.
- Structural scope, components, episodes.
- Graph nodes/edges.
- New memory types.
- Routing-layer or scoring-layer changes.
- Anything that requires an LLM classifier at write or query time.

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| 71% of relevant signal is sacrificed for 92% noise reduction | Phase 5 useful-not-relevant signal will show whether lost relevant signal was actually being used |
| On-demand types are never queried | Phase 4 deterministic triggers + Phase 6 decision gate (delete if unused) |
| Holdout numbers regress from filter-on-injected | Phase 2 production-simulation replay before code lands |
| Wrong score field is gated against | Implementation references `score` field explicitly, documented inline + in this spec |
| New feedback signal is itself noisy | Two cheap options prototyped in parallel; pick after one day |

## Reference Material

- Analysis script: `evals/injection_policy_2026_06/analyze.py` (Phase 0)
- Decision-simulation replay: `evals/injection_precision_eval.py` (Phase 2 update target)
- Workstream-routing prior negative result: `docs/designs/014-workstream-consolidation-rekey.md`
- Operational-fact spec on-demand caveat: `docs/specs/2026-05-31-operational-fact-memory-design.md`
- Architect review of fact consolidation pipeline: memory `616f2f55` (895/10 issue)
- Routing-quality analysis context: `docs/designs/007-routing-quality-analysis.md`
- Eval-from-live-failures process: `docs/context/eval-from-live-failures.md`

## Out of Scope (Explicitly)

- Container scope changes (`container_ref` derivation, virtual-thread model).
- Cross-container memory portability.
- Multi-user/multi-actor scope work.
- Embedding model changes.
- New prompt variants.
- Anything in `roadmap/Later` and `roadmap/Ideas`.
