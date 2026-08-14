# Work Record — add-vnext-performance-and-e2e-validation

Task branch: `feat/add-vnext-performance-and-e2e-validation`
Roadmap item: `roadmap/features/add-vnext-performance-and-e2e-validation.md`

<!-- agent-workflow:start -->
**Outcome:**
The cumulative vNext work (P0 raw-history governance + measurement contract, the P1 historical-lookup vertical — `source_only` search, `pallium_search_history`, source-context expansion — the reuse-funnel population, and the dashboard rework) is confirmed to have **not regressed performance** (code paths + DB) and is proven correct **end to end**. Deliverables: (a) a bounded perf-timing harness over the exact vNext-touched hot paths with a baseline + regression thresholds; (b) a DB perf check that confirms the hot-path queries are indexed/in-budget and names any N+1; (c) a committed e2e suite for the historical-lookup + measurement vertical (extending the existing e2e to close its gaps) with visibility/redaction/forgotten invariants held; (d) a reproducible perf/e2e report + documented re-run command; (e) a **live production-service smoke** (port 19836) that confirms the funnel armed and a real `POST /query`(source_only)→`GET /source/{id}/context` chain persists events — run against a **disposable DB copy** so it never pollutes the real KPI.

**Target:**
Pallium repo. New/edited files live in `evals/` and `tests/` (blue, non-guarded) plus a docs report and a runnable smoke script under `scripts/` or `evals/`. **Read-only** against guarded code (`core/`, `storage/`, `retrieval/`, `api/`) — this feature *measures and flags*; it does not modify product behavior. Live smoke targets the installed service on `:19836`.

**Scope:**
Delivered as **1 PR**. (1) **Perf harness** (new, bounded, in `evals/`): times the vNext hot paths — lexical+vector fusion query, ingest/processing, `source_only` search (`core/query.py:126-162`), source-context expansion (`core/service.py:1456-1609` + `storage/sqlite.py:262-320`), the `matches_filters` forgotten-source gate (`core/filters.py:67-76`), and the reuse-funnel event write (`core/service.py:710-745`). Drives traffic via `app.agent_simulation`/TestClient over a realistically-sized local DB; reports per-path latency vs a captured baseline with a regression threshold. (2) **DB perf check**: confirms the indexes backing the hot paths (`idx_source_items_thread_lookup` for neighbor windows; the reuse-event/label indexes) and explicitly measures/flags the two known N+1 shapes — double `get_source_item` per candidate (`storage/sqlite_search.py:74-108`) and the loader's per-exposed-id visibility scan (`evals/historical_lookup_measurement.py:586-589`). (3) **Committed e2e**: EXTEND `tests/test_historical_lookup_funnel_e2e.py` to close its three gaps — chain depth >2 (expand's returned id as a further `parent_lookup_id`), assert `/status.events_recorded` increments, and keep the adversarial cross-container + forgotten-source 0-leak invariants; add any missing redaction assertion. (4) **Report + re-run command**: a perf/e2e report (`docs/` or `evals/`-adjacent) stating baseline/current/delta/pass-fail per path + e2e invariant results, with a documented command. (5) **Live-service smoke** (new runnable script): drives `POST /query`(source_only, `trigger_origin=agent_pull`)→`GET /source/{id}/context`(with `parent_lookup_id`) against `:19836`, asserts `/status.historical_lookup_funnel.armed` and that a lookup+expansion event persist and `events_recorded` increments — against a **disposable DB copy / scratch-tagged container** so the real KPI is untouched; documented for post-deploy/restart use.
MAY NOT touch: product behavior in `core/`/`storage/`/`retrieval/`/`api/` (measure-only; any regression fix is a SEPARATE WR/PR with its own risk — per ticket Out-of-Scope); scheduling eval runs; auth/multi-user/remote; the RED contract surface (`api/routes.py`, `api/schemas.py`, `core/service.py`).

**Constraints:**
Measure-and-flag ONLY — no product code changes (a warranted index/memoization fix is deferred to its own WR). Long-running perf/e2e test files MUST carry `pytestmark = pytest.mark.slow` (repo default `addopts = -m 'not slow' -n 4`; slow tests excluded from the default run — `docs/testing-conventions.md`). Reuse existing harnesses (`app.agent_simulation`, `TestClient` fixtures in `tests/conftest.py`, the existing funnel e2e) rather than building a general perf framework (ticket Out-of-Scope). The live smoke MUST NOT pollute the real measurement DB/KPI: `/status.events_recorded` is an **unscoped global `COUNT(*)`** (`app/main.py:419-423`), so the smoke runs against a **disposable copy** of the DB (or a clearly scratch-tagged container) and is explicit about that. No user-supplied SQL/path injection in any harness. No internal/external product names in committed artifacts. Tests run via the real cpython interpreter + `PYTHONPATH=".local/test-env/site-packages;."` (this box blocks venv python stubs).

**Completion criteria:**
Feature "Done When" 1–5: (1) perf report over the vNext paths shows no material regression vs baseline, or flags each regression with cause + recommended fix; (2) hot-path DB queries confirmed indexed/in-budget on a realistic local DB, any N+1/missing index identified; (3) committed e2e covering the historical-lookup + measurement vertical passes incl. visibility/redaction/forgotten invariants (0 leaks under adversarial cases); (4) a documented command re-runs perf + e2e reproducibly; (5) the live service (:19836) validated end to end after a deploy/restart — `/status` funnel armed + a search→expand chain persists events, verified WITHOUT polluting the real KPI, with a documented re-run command. Plus `python -m pytest tests/ -q` green (modulo known-benign `test_config.py::test_prompt_variants_legacy_fallback_unaffected`).

**Risk:** Elevated

**Complexity:** Large

**Reason:**
All new/edited artifacts are in `evals/`+`tests/`+`docs/`+`scripts/` (blue, non-guarded); DB timing and hot-path reads are read-only; NO product behavior change and NO RED contract surface touched — so not High. But it drives the real service, touches the live production instance for the smoke, and asserts cumulative correctness across the whole vNext vertical → above Routine. Elevated. Large: five independently-verifiable deliverables (perf harness, DB check, e2e extension, report, live smoke) across multiple subsystems + a live-service loop.

**Discovery:**
See `## Discovery`. Grounded by a read-only discovery pass (file:line verified). Key facts: (a) a committed e2e ALREADY exists — `tests/test_historical_lookup_funnel_e2e.py` — covering ingest→search_history→expand→events→rollup + cross-container + forgotten invariants; the gaps are chain-depth>2, `/status.events_recorded` assertion, and a live-HTTP smoke. (b) The repo does NOT time latency/DB anywhere on the hot paths (`docs/context/validation.md:147-148`); corpus benchmarks time only phases via `time.monotonic()` — so the perf harness is genuinely new but must stay bounded. (c) Hot paths pinned: `matches_filters` gate `core/filters.py:67-76` (per-candidate `get_source_item`, before the `filters is None` short-circuit); `source_only` `core/query.py:126-162`; neighbor windows `storage/sqlite.py:262-320` (backed by `idx_source_items_thread_lookup`); event write `core/service.py:710-745`/`:1586-1607`. (d) Two N+1 shapes located: double `get_source_item` per candidate (`storage/sqlite_search.py:74-108`) and loader per-exposed-id scan (`evals/historical_lookup_measurement.py:586-589`). (e) Live endpoints: MCP `pallium_search_history`→`POST /query`(source_only, agent_pull) (`app/mcp/client.py:39-70`); `pallium_expand_source`→`GET /source/{id}/context` (`app/mcp/client.py:152-168`); `/status.historical_lookup_funnel` built at `app/main.py:413-440`, `events_recorded` = unscoped global `COUNT(*)` (`:419-423`). (f) TestClient via `create_app(AppConfig(...))`, fixtures in `tests/conftest.py`; funnel e2e builds its own visibility-enforcing client. (g) Live restart: `scripts/restart-service.ps1`.

**Material assumptions:**
- A1: The committed e2e can be EXTENDED in place (`tests/test_historical_lookup_funnel_e2e.py`) to close the three gaps rather than writing a parallel suite. Disproof: the existing test's fixture/client shape can't express chain-depth>2 or a `/status` assertion cleanly → add a sibling test module in the same style, note it. (Fits the validation.md anti-pattern: don't build a new slice before checking the existing one.)
- A2: A bounded perf harness can get useful, repeatable per-path timings from an in-process `TestClient` + a realistically-sized seeded DB WITHOUT a separate baseline branch — baseline = a captured snapshot committed alongside (or generated by a documented `--baseline` run), compared with a percentage regression threshold. Disproof: in-process timing is too noisy to be meaningful (variance > threshold) → report wall-clock ranges + the N+1 *counts* (deterministic) as the primary signal and latency as advisory, and say so. **Query-count / round-trip counts are the deterministic backbone; latency is advisory.**
- A3: The live :19836 smoke can run fully against a **disposable copy** of the production DB (copy the sqlite file, point a scratch server or the smoke's own client at it) so `events_recorded` increments are observed without touching the real KPI. Disproof: can't cleanly redirect the installed task's DB without disrupting it → run the smoke against a second short-lived server process on a scratch port bound to the copied DB, and separately do a READ-ONLY `/status.armed` check against the real :19836. Either way the real KPI COUNT is never incremented by the smoke.
- A4: No product-code change is needed to measure. Disproof: a hot path lacks any timing seam and can only be measured by editing product code → prefer external timing (wrap the TestClient call / count queries via a SQLAlchemy event listener), do NOT edit product code; if truly impossible, STOP and record a scope question (a product edit would raise risk).

**Plan:**
See `## Plan`. Sequence: e2e extension FIRST (closes correctness gaps, cheap, reuses existing) → perf harness (query-count backbone + advisory latency) → DB check (indexes + N+1 counts, folds into perf harness output) → live-service smoke (disposable DB) → report + re-run command. Stop conditions: (A2) if latency too noisy → lead with deterministic query counts; (A4) if measurement would require a product edit → stop, record scope question, do not edit guarded code.

**Verification plan:**
See `## Verification plan`. Each Done-When → concrete check: e2e green (incl. adversarial 0-leak) via pytest; perf harness emits per-path timings + N+1 counts + baseline delta; DB check names indexes/N+1; live smoke shows armed + events persisted on the copy + real KPI untouched; documented commands reproduce; full `pytest tests/ -q` green modulo the known-benign config test.

**Plan review:**
Clean-context agent review REQUIRED (Elevated) — recorded in `## Plan review` before State → Ready to implement. Focus: (1) is measure-only genuinely achievable without editing guarded code (external timing/query-count seams), or does any hot path force a product edit (→ raise risk)?; (2) is extending the existing e2e the right call vs a new module?; (3) is the disposable-DB-copy approach for the live smoke actually leak-proof for the unscoped global `events_recorded` COUNT?; (4) is the perf-baseline approach (captured snapshot + threshold, query-counts as deterministic backbone) sound given known in-process timing noise?

**Approvals:**
Not required at this risk level (Elevated). Standing overnight package mandate covers proceeding.

**Exceptions:**
—

**State:** Ready to implement
<!-- agent-workflow:end -->

## Discovery

Read-only discovery pass (file:line verified). Full detail folded into the marker-block **Discovery** field; the load-bearing facts:

- **Existing e2e already covers most of the vertical:** `tests/test_historical_lookup_funnel_e2e.py` — `test_full_funnel_chain_audit_off` (ingest → `POST /query` source_only → persisted `lookup` row → `GET /source/{id}/context` w/ `parent_lookup_id` → `expansion` row → seed labels → `load_events_from_storage` → `compute_reuse_rollup` non-empty) + adversarial cross-container non-leak + forgotten-source exclusion. Builds a visibility-enforcing client (`agent_conversation_memory`, audit OFF). **Gaps to close:** chain depth >2 (expand's own returned id fed as a further `parent_lookup_id`); assert `/status.events_recorded` increments; explicit redaction assertion.
- **No hot-path latency/DB timing exists** (`docs/context/validation.md:147-148`). Corpus benchmarks time phases only (`time.monotonic()`), per-query `latency_ms` is LLM-resolver-only. Perf harness = new, bounded, `evals/`.
- **Hot paths:** gate `core/filters.py:67-76`; `source_only` `core/query.py:126-162`; neighbor windows `storage/sqlite.py:262-320` (idx `idx_source_items_thread_lookup` = `(container_ref, thread_ref, created_at, id)`, `storage/sqlite_schema.py:662-664`); event write `core/service.py:710-745` (lookup) + `:1586-1607` (expansion); loader `evals/historical_lookup_measurement.py:423-483` (own `sqlite3.connect`).
- **N+1 shapes:** double `get_source_item` per candidate (`storage/sqlite_search.py:74` matches_filters + `:101-108` visibility) ; vector path second fetch `retrieval/vector.py:209`; loader per-exposed-id `evals/historical_lookup_measurement.py:586-589`.
- **Live endpoints:** search_history → `POST /query` `{source_only:true, trigger_origin:"agent_pull", ...}` (`app/mcp/client.py:39-70`); expand_source → `GET /source/{id}/context` (`app/mcp/client.py:152-168`, route `api/routes.py:673-727`); `/status.historical_lookup_funnel` `app/main.py:413-440`; `events_recorded` = unscoped global `COUNT(*)` `app/main.py:419-423` → live smoke MUST use a disposable DB copy.
- **Commands:** tests via real cpython + `PYTHONPATH=".local/test-env/site-packages;."`; slow tests need `pytestmark = pytest.mark.slow` (`docs/testing-conventions.md`); dev server `python -m app.run serve --port 8000`; live restart `scripts/restart-service.ps1`.

## Plan

Single PR on `feat/add-vnext-performance-and-e2e-validation`.

1. **E2E extension (correctness first, cheap).** Extend `tests/test_historical_lookup_funnel_e2e.py` (or a sibling module if the fixture can't express it — A1): (a) chain depth >2 — feed the `expansion` event's own id as `parent_lookup_id` to a further expand and assert the chain persists; (b) assert `/status.historical_lookup_funnel.events_recorded` increments across the chain; (c) an explicit redaction assertion on the exposed set; keep the cross-container + forgotten 0-leak invariants. `pytestmark = pytest.mark.slow` if it drives the full pipeline.
2. **Perf harness (new, bounded, `evals/`).** A runnable module that seeds a realistically-sized local sqlite DB, then drives each vNext hot path via TestClient/`app.agent_simulation` and records: **(deterministic backbone)** DB round-trip counts per path via a SQLAlchemy `after_cursor_execute` event listener (this catches the N+1s directly and is noise-free); **(advisory)** wall-clock latency per path (median/p95 over N reps). Compare against a committed baseline snapshot with a percentage regression threshold; a `--baseline` mode regenerates it. NO product-code edits — all timing/counting is external (event listener + wrapping the call).
3. **DB perf check (folds into #2 output).** Assert the hot-path indexes exist and are used (confirm `idx_source_items_thread_lookup` backs the neighbor window; reuse-event/label indexes back the loader). Surface the two known N+1 shapes as explicit counts in the harness output (double `get_source_item` per candidate; loader per-exposed-id). Report — do not fix (fix = separate WR).
4. **Live-service smoke (new script, disposable DB).** A runnable script (`scripts/` or `evals/`): copy the live sqlite DB to a scratch path, start a short-lived server on a scratch port bound to the copy (or redirect the smoke client), drive `POST /query`(source_only, agent_pull) → `GET /source/{id}/context`(parent_lookup_id), assert a lookup+expansion event persisted in the copy and `events_recorded` incremented there; separately do a READ-ONLY `/status.armed` check against the real :19836. Real KPI COUNT never incremented. Document as the post-deploy/restart confirmation.
5. **Report + re-run command.** A perf/e2e report (baseline/current/delta/pass-fail per path + e2e invariant results + N+1 counts) and documented commands to reproduce all of the above.

## Verification plan

- **C1 (perf):** harness runs, emits per-path latency + baseline delta + pass/fail at threshold; any regression flagged with cause + recommended fix. Query-count backbone is deterministic.
- **C2 (DB):** harness names the indexes backing each hot path and the N+1 counts; no missing index on the measured paths, or it's flagged.
- **C3 (e2e):** extended `test_historical_lookup_funnel_e2e.py` green incl. chain>2, `/status.events_recorded` increment, redaction, and cross-container + forgotten 0-leak.
- **C4 (reproducible):** documented commands re-run perf + e2e; report regenerates.
- **C5 (live):** live smoke shows funnel armed + events persisted on the disposable copy + real :19836 KPI untouched (read-only armed check only against real).
- **Regression:** `python -m pytest tests/ -q` green (modulo known-benign config test).

## Plan review

_Pending clean-context review (Elevated) — see marker-block Plan review field for the review questions._

## Implementation

_Not started._
