# Work Record — add-historical-lookup-reuse-funnel

Task branch: `feat/add-historical-lookup-reuse-funnel`
Roadmap item: `roadmap/features/add-historical-lookup-reuse-funnel.md`

<!-- agent-workflow:start -->
**Outcome:**
On a fresh local Pallium install, real agent usage produces the Phase-1 reuse KPI. Every `pallium_search_history` call persists a lookup event (unconditionally, not gated on `audit_log_enabled`) carrying a newly-minted `lookup_event_id` + exposed source ids + raw ranks (+ best-effort score) + session/agent/container identity; every `pallium_expand_source` persists an expansion event carrying `parent_lookup_id`. `load_events_from_storage` reconstructs eligible sessions + loads events so `python -m evals.historical_lookup_measurement --db <db>` returns a non-empty, empty-data-safe rollup (reuse-per-100-eligible, rungs 1–2, Wilson intervals, supporting rates). A retrospective sampled judge assigns rung labels + the user-directed-vs-agent-decided split + inter-rater κ. The funnel is armed by default on install and `pallium service status` reports whether it is armed.

**Target:**
Pallium repo. Guarded: `storage/` (new event table + writer), `core/query.py`/`core/service.py` (unconditional lookup + expansion persistence hooks; surface `lookup_event_id` for the source_only path), `api/` (source_only response contract — RED api-review), `app/cli/` (install config seeding + status health check), `app/config.py`. Non-guarded: `evals/historical_lookup_measurement.py` (loader), a judge harness under `evals/`, `pallium.example.toml`, runbook doc, `tests/`.

**Scope:**
As in the feature file, delivered as **2 PRs**. PR-a (guarded core): new `historical_lookup_reuse_event` side table + writer; unconditional lookup-event persistence + minted `lookup_event_id` in the `source_only` branch; expansion-event persistence carrying `parent_lookup_id`; `load_events_from_storage` (eligible-session reconstruction + event load) feeding `compute_reuse_rollup`; tests incl. reconciling the existing `lookup_event_id` contract test. PR-b (enablement + judge): retrospective sampled judge harness that assigns rung labels; arm-by-default on install + `pallium service status` health check; runbook + visibility-violation reporting in the rollup output.
MAY NOT touch: retrieval *behavior* (scoring / `source_only` candidate semantics) beyond adding persistence hooks; agent guidance/skills (separate feature `add-agent-historical-lookup-exposure`); dashboard surfacing (separate feature).

**Constraints:**
Lookup-event persistence is UNCONDITIONAL (not gated on `audit_log_enabled`). The existing normal-`/query` audit behavior (audit-gated `lookup_event_id` == audit row id, null when disabled — `tests/test_lookup_event_id_e2e.py`) MUST remain intact for the non-source_only path; only the `source_only` path gains an unconditional minted id. Rollup stays empty-data-safe. No regression to existing retrieval or metrics. Visibility/redaction/forgotten invariants hold for persisted event data (forgotten sources excluded from exposure + eligibility; no cross-container leak). New table follows the write-only side-table pattern (`SubtaskSelectorShadowRecord`) via ORM `create_all` + `_ensure_*` index migration — no migration framework. No internal/external product names in committed artifacts.

**Completion criteria:**
Feature "Done When" 1–6: (1) fresh install persists lookup + expansion events with required fields, audit-independent; (2) `python -m evals.historical_lookup_measurement --db <db>` returns non-empty rollup with Wilson intervals + supporting rates, still empty-safe; (3) judge harness emits rung-1/2 labels + user-directed-vs-agent split + κ; (4) visibility-violation report emits 0 violations with attempted-disallowed-access counts; (5) `pallium service status` reports funnel-armed state; (6) runbook documents enable/use/read-KPI. Plus `python -m pytest tests/ -q` green (modulo known-benign `test_config.py::test_prompt_variants_legacy_fallback_unaffected`).

**Risk:** High

**Complexity:** Large

**Reason:**
Red persistence surface (new `storage/` table) + `core/service.py` (architecture-review RED, orchestrator wiring) + a `source_only` **response-contract change** in `api/` (api-review RED: `lookup_event_id` becomes unconditional for that path). High because persistence + contract surfaces. Large: spans storage + core + api + cli + evals + judge harness as independently-verifiable outcomes across 2 PRs.

**Discovery:**
Recorded under `## Discovery` (seam map, 6 sections). Five contract gotchas confirmed: (1) no distinct `lookup_event_id` exists — it is the `query_audit_log` row id, null when audit off; a NEW id + table is required. (2) `source_only` generates no event id and writes nothing of its own. (3) `parent_lookup_id` is only echoed, never persisted. (4) the rollup's `historical_lookup_reuse_event(session_id, rung)` table does not exist. (5) the LLM cache key (`providers/llm/cached.py:106-116`) has NO seed slot → "≥3 seeds" collapses unless the seed ordinal is folded into the prompt. Fusion score is debug-only (trace, `include_trace=True`); persist `raw_rank`+`source_id`+item score always, fusion score best-effort/null.

**Material assumptions:**
- A1: `compute_reuse_rollup` consumes events as `{session_id, rung}` with rungs `incorporation`/`influence`/`downstream`; denominator = eligible sessions; empty-safe when 0. CONFIRMED (`evals/historical_lookup_measurement.py:117-201`). The persisted schema conforms to this.
- A2: `storage/` uses declarative ORM + `create_all` + hand-rolled `_ensure_*` index migrations, no framework; `SubtaskSelectorShadowRecord` is the write-only side-table template. CONFIRMED (`storage/sqlite_schema.py:253-306,756-780`).
- A3: the `source_only` persist hook lives in `PalliumService.query` (`core/service.py:659-703`) without changing retrieval behavior; expansion hook in `get_source_context` (`:1413-1541`). CONFIRMED. Disproof: persistence would require reshaping the query flow → re-plan/re-classify.
- A4: rung labels are assigned retrospectively by the judge (PR-b) and written back onto event rows; PR-a persists rung=null and the loader/rollup are empty-safe until labels land. Disproof: rollup requires rung at write time → add a labels side-table instead.

**Plan:**
See `## Plan`. PR-a: storage table+writer → unconditional lookup persistence + minted id in source_only branch → expansion parentage persistence → response contract surfaces id for source_only (reconcile e2e contract test) → `load_events_from_storage` (eligible reconstruction + event load) → tests. PR-b: retrospective judge (seed folded into prompt) writing rung labels → arm-by-default + status health check → runbook + visibility-violation reporting. Stop condition: if the source_only contract change forces a change to the normal `/query` audit behavior, stop and re-review.

**Verification plan:**
See `## Verification plan` — each completion criterion → method. Unit: new schema test, storage writer test, loader eligible-reconstruction + empty-safe test. E2E: ingest→`search_history` (audit OFF) → lookup event persisted with minted id → `expand_source` → expansion event with `parent_lookup_id` → loader returns eligible + (rung-seeded) events → `compute_reuse_rollup` non-empty; empty-data-safe path. Invariants: forgotten-source excluded, cross-container non-leak (0 violations + attempted-access count). Contract: updated `test_lookup_event_id_e2e.py` (normal path unchanged; source_only unconditional). Manual: `pallium service status` funnel-armed. Judge: dry-run over a small window emits rung labels + κ with distinct per-seed cache keys.

**Plan review:**
Clean-context technical review requested (High risk) IN ADDITION to the recorded human approval — see `## Plan review`. Reference recorded there before State → Ready to implement.

**Approvals:**
Approved by user 2026-08-14: "ok, so continue on all the features design, including the tool registration feature, then go into a nightly developemrn process. you have my ok for high risk changes"

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Discovery

Full seam map from the read-only discovery agent (citations are `path:line`). Key sections:

**Rollup contract** — `evals/historical_lookup_measurement.py`: `load_events_from_storage(db_path, *, container_ref, since, until, eligibility_n=50) -> (eligible_session_ids: list[str], reuse_events: list[dict])`, stub returns `([], [])` (:209-247). `compute_reuse_rollup(eligible_sessions, reuse_events, *, eligibility_n, window)` (:117-201) consumes events `{session_id, rung}`; rungs `incorporation`/`influence`/`downstream` (:49-79); dedup per session per rung; denominator = eligible sessions; empty-safe (:181-192). `__main__` argparse `--db/--container-ref/--since/--until/--eligibility-n/--output/--dry-run/--quiet` (:255-337).

**Storage** — ORM on `declarative_base()` in `storage/sqlite_schema.py`; `Base.metadata.create_all` in `_initialize_schema` (:756-780); additive changes via `_ensure_*` + `_*_MIGRATIONS` dicts. Follow `SubtaskSelectorShadowRecord` (:253-306) — write-only side table, correlated at eval time via `(thread_ref, container_ref, created_at)` join to `source_items` (index `idx_source_items_thread_lookup` :596-599). `MetricRecord`/`MetricsStore` (`storage/metrics.py:61-227`) = the record+store pattern. `QueryAuditLogRecord` (:180-205) written by `write_query_audit_row` (`storage/sqlite.py:1246-1248`), row built in `core/service.py:write_query_audit` (:1143-1287, returns row id as `lookup_event_id`), gated by `observability.query_audit_log` (default False). New writer mirrors `write_query_audit_row`/`write_subtask_selector_shadow_row` + base method.

**Lookup + expansion** — `core/query.py` `source_only` branch (:126-162): restricts to `target_kind="source_item"`, stamps 1-based `raw_rank` (`core/models.py:255-257`), `should_inject=False`, `decision_reason="source_only_search"`; NO event id minted; fusion score only in trace when `include_trace=True` (`core/models.py:308-331`). `core/service.py`: `query(..., source_only)` wrapper (:659-703) = lookup persist seam; `get_source_context(..., parent_lookup_id)` (:1413-1541) echoes `parent_lookup_id` at :1541, persistence deferred = expansion persist seam. `app/mcp/server.py` `pallium_search_history` (:56-96) / `pallium_expand_source` (:176-213); `app/mcp/client.py` hardcodes `source_only=True` + `trigger_origin="agent_pull"` (:55-60).

**Local enablement** — `query_audit_log: bool = False` (`app/config.py:80`). `_seed_config` (`app/cli/service.py:54-96`) keeps only `keep_prefixes` (llm_providers, two semantic_packages) → strips `[observability]`. `pallium service status` = `_cmd_status` (:454-502); `pallium setup claude-code` `_verify_service` (`app/cli/setup_claude_code.py:210-214`), default port 19836. `pallium.example.toml:13-14` `[observability]` has only `integration_debug=false`.

**Judge reuse** — `evals/anchor_probe/subagent_audit.py:182-280` (`audit_rule` sample+shuffle by seed, blinded A/B `_build_user_prompt`, `provider.generate_json`, de-blind, rate accumulation). `evals/eval_common.py` wires `CachedLLMProvider` (:628-637), flags `--cache-dir/--no-eval-cache`. Cache key `providers/llm/cached.py:106-116` = `sha256(model_tag\x00system\x00user\x00schema)[:24]`, NO seed slot → fold seed ordinal into the user prompt.

**Tests** — `tests/test_historical_lookup_measurement.py` (rollup math, empty-safe, loader-stub), `tests/test_lookup_event_id_e2e.py` (contract: audit-on non-null==row, audit-off null, trigger-origin, bypass guard), `tests/test_source_context.py`, `tests/test_search_history_tool.py`, metrics/schema test templates, fixture `tests/conftest.py:13-38` (`test_db_url`, `client`, `drain_queue`; storage via `client.app.state.pallium_service._storage`).

## Plan

**PR-a — funnel persistence + loader + rollup (guarded/High):**
1. **Storage.** Add `HistoricalLookupReuseEventRecord` ORM model (`storage/sqlite_schema.py`) after `SubtaskSelectorShadowRecord`: `id` (PK = `lookup_event_id`), `created_at`, `event_type` ("lookup"|"expansion"), `session_id` (=thread_ref), `container_ref`, `actor_ref`, `agent_ref`, `trigger_origin`, `parent_lookup_id` (nullable), `exposed_json` (Text: `[{source_id, raw_rank, score}]`), `rung` (nullable, judge-assigned), `visibility`. Add `_HISTORICAL_LOOKUP_INDEX_MIGRATIONS` + `_ensure_historical_lookup_indexes` (index on `container_ref, session_id, created_at`) called in `_initialize_schema`. Add `write_historical_lookup_event_row(row: dict)` on `SqliteStorageProvider` + `StorageProvider` base.
2. **Lookup persistence (unconditional).** In `PalliumService.query` source_only branch (`core/service.py:659-703`): mint `lookup_event_id = new_id()`; build `exposed` from `result.results` (`source_id`, `raw_rank`, item score if present); persist a "lookup" row via the new writer — NOT gated on `audit_log_enabled`; attach the minted id to the returned result so the response can surface it. Normal-path `query` untouched.
3. **Expansion parentage.** In `get_source_context` (`:1413-1541`): persist an "expansion" row (own minted id, `parent_lookup_id` = incoming, `exposed` = the returned neighbor ids) unconditionally.
4. **Response contract.** Ensure the `source_only` `/query` response returns the minted `lookup_event_id` unconditionally (api/routes.py — RED api-review). Keep the normal `/query` path's audit-gated id behavior exactly as-is. Reconcile `tests/test_lookup_event_id_e2e.py`: add source_only-unconditional assertions; keep normal-path audit-off→null assertions.
5. **Loader.** Implement `load_events_from_storage`: reconstruct eligible sessions (group `source_items` by `thread_ref` within `container_ref`; substantive = ≥1 user turn + ≥1 assistant work turn; container held ≥ `eligibility_n` prior indexed turns at session start via `(container_ref, created_at)` join); load persisted events (rung-labeled) → return `(eligible_session_ids, [{session_id, rung}])`. Empty-safe.
6. **Tests** (PR-a): schema test; writer round-trip; loader eligible-reconstruction + empty-safe; e2e ingest→search_history (audit OFF)→lookup persisted w/ minted id→expand→expansion row w/ parent_lookup_id→loader→`compute_reuse_rollup` non-empty (rung-seeded); forgotten-source excluded + cross-container non-leak.

**PR-b — enablement + judge + runbook:**
7. **Retrospective judge harness** under `evals/` (reuse `anchor_probe` protocol + `eval_common` providers): sample lookups + eligible sessions from a window; per lookup label genuine-opportunity, rung-1 verified incorporation + evidence span, rung-2 judged influence, user-directed-vs-agent-decided (subsequent-turn `(thread_ref, container_ref, created_at)` join); blinded A/B; **≥3 seeds with the seed ordinal folded into the user prompt** (defeats the seedless cache key); consensus; Cohen's κ on a double-rated subsample; Wilson intervals; empty/abandoned handling. Writes rung labels back onto the event rows.
8. **Arm by default.** Persistence is already unconditional (step 2), so events record regardless of audit. Additionally arm the funnel out of the box: seed the funnel flag (add to `pallium.example.toml` and keep/seed it in `_seed_config` rather than stripping) and add a "funnel armed?" report to `pallium service status` + `setup_claude_code` verify.
9. **Runbook + reporting.** `docs/` runbook (enable/use/read-KPI on a local service); wire visibility-violation reporting (0 violations WITH attempted-disallowed-access counts/types) into the rollup output.

## Verification plan

- **C1 (persist, audit-independent):** e2e test with `ObservabilityConfig(query_audit_log=False)` asserts a `historical_lookup_reuse_event` "lookup" row exists after `search_history`, and an "expansion" row with `parent_lookup_id` after `expand_source`. Manual: fresh-install smoke.
- **C2 (non-empty + empty-safe rollup):** unit test seeds events+eligible sessions → `compute_reuse_rollup` non-empty with Wilson intervals + supporting rates; separate test with zero events → empty-safe (no crash, `n/a` notes). `python -m evals.historical_lookup_measurement --db <tmp>` smoke.
- **C3 (judge):** dry-run judge over a tiny fixture window emits rung-1/2 labels + user-directed-vs-agent split + κ; assert ≥3 seeds produce distinct cache keys (seed-in-prompt).
- **C4 (visibility):** invariant test — forgotten source excluded from exposure + eligibility; cross-container query yields 0 leaked events + an attempted-disallowed-access count.
- **C5 (health check):** `pallium service status` output includes funnel-armed state (unit/CLI test).
- **C6 (runbook):** doc present + referenced; reporting format emitted by the rollup.
- **Regression:** `python -m pytest tests/ -q` green (modulo known-benign `test_config.py::test_prompt_variants_legacy_fallback_unaffected`); existing `test_lookup_event_id_e2e.py` normal-path assertions still pass.

## Plan review

Requested a clean-context technical review (High risk) — reference to be recorded here on completion. Human approval is already recorded in the marker block (Approvals). Review focus: the `source_only` `lookup_event_id` contract change (must not disturb normal-`/query` audit behavior), empty-data safety of the loader, visibility/forgotten invariants on persisted events, and the rung-labels-written-back model (A4).

## Implementation

Not started. State `Blocked` (in planning) until the clean-context plan review returns and State flips to `Ready to implement`. Standing High-risk approval recorded. Next agent: read `## Plan` + `## Plan review`; do not edit code until State is `Ready to implement`.
