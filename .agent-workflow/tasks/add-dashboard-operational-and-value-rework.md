# Work Record — add-dashboard-operational-and-value-rework

Task branch: `feat/add-dashboard-operational-and-value-rework`
Roadmap item: `roadmap/features/add-dashboard-operational-and-value-rework.md`

<!-- agent-workflow:start -->
**Outcome:**
The local Pallium dashboard is reworked from one long scroll into two clearly-separated views: an **Operational** view (is Pallium healthy/working — metrics, issues, memory browser, query-debug) and a **"How memory helps"** view (is it effective — the reuse-funnel KPI + derivation/representation eval summaries surfaced for a human). A recorded **UX-design pass precedes layout code** (what goes where + why + priority + empty-data strategy). The dashboard is iterated live in a browser until both views read clearly. No framework/build step introduced; existing dashboard APIs still work.

**Target:**
Pallium repo. Guarded: `app/dashboard.py` + `app/dashboard.html` (self-contained dashboard surface, guarded `app/` but not `core/`/`api/routes.py` RED); possibly a small read-only `/dashboard/api/*` endpoint for the funnel KPI / eval reports. Non-guarded: `tests/`, a UX-design doc under `docs/`.

**Scope:**
Delivered as **1 PR**. (0) UX-design doc (planning deliverable) defining both views, panel priority, and the empty/stale-data strategy. (1) A two-view shell in `app/dashboard.html` (net-new tab switch; vanilla HTML/CSS/JS, no framework/bundler). (2) Operational view = re-home the existing working panels (overview, system health, query activity + skip reasons, memory browser, query-debug) — backed by existing `/dashboard/api/*`, `/status`, `/debug/queue/health`, `/query/debug`; no backend change. (3) "How memory helps" view = surface the reuse-funnel signal (`/status.historical_lookup_funnel` {armed, events_recorded} is live NOW; plus the rollup KPI and the offline eval JSON reports `raw_derived_hybrid` / `derivation_fidelity`) with honest measured-vs-shadow framing and friendly empty/"run this eval"/"stale report" states; a small read-only endpoint may serve the report files / rollup. (4) Live browser iteration with before/after screenshots. (5) Tests updated (`tests/test_dashboard.py` asserts literal endpoint strings) + coverage for any new endpoint.
MAY NOT touch: computing new metrics (funnel loader/evals are merged features); scheduling eval runs; auth/multi-user/remote; `core/`/`api/routes.py` behavior.

**Constraints:**
No JS framework, bundler, or build step (keep vanilla, edit-and-refresh). If the single 2,032-line `app/dashboard.html` must be split, that is a deliberate recorded choice, not framework adoption. Preserve all current operational panels + the existing `/dashboard/api/*` contract; keep the literal endpoint strings `tests/test_dashboard.py` asserts (or update the tests). Every `/dashboard/api/*` route 501s without SQLite — keep that. "How memory helps" data that isn't live must show a friendly empty/stale state, never imply live when it's a stale offline report. No internal/external product names. Any new endpoint is read-only and lives on the dashboard router (`/dashboard/api/*`), not `api/routes.py` (avoid the RED api surface).

**Completion criteria:**
Feature "Done When" 1–5: (1) recorded UX-design pass (what/why/priority + empty-data strategy) BEFORE layout code; (2) two separated views, no framework/build, operational view preserves all current panels + APIs work; (3) "how memory helps" view surfaces the funnel signal (empty-safe) + the eval reports (friendly stale/empty states) with honest framing; (4) iterated live with before/after screenshots in the WR; (5) `tests/test_dashboard.py` passes (updated for moved/added wiring) + any new endpoint has coverage. Plus `python -m pytest tests/ -q` green (modulo known-benign `test_config.py::test_prompt_variants_legacy_fallback_unaffected`).

**Risk:** Elevated

**Complexity:** Large

**Reason:**
Guarded (`app/dashboard.py` + `app/dashboard.html`, possibly a small read-only dashboard-router endpoint) but no RED: not `core/`/`api/routes.py`, no persistence, no retrieval behavior. Elevated. Large: a substantial UI rework of a 2,032-line file into two views + a new data surface + live-iteration loop + tests — multiple independently-verifiable outcomes.

**Discovery:**
Grounded on the earlier read-only dashboard investigation (recorded under `## Discovery`), refreshed for the now-merged funnel. Key: single `app/dashboard.html` (2,032 lines, all inline CSS/JS), served from disk per request (edit-and-refresh, no restart/build); route `/dashboard` via `mount_dashboard()` (`app/dashboard.py`) wired at `app/main.py:424`; data from `/dashboard/api/*` (`MetricsStore` + direct record selects) + `/status` + `/debug/queue/health` + `/query/debug` + `/memory/{id}/expand`; NO tab structure today (only two collapsible sections); `tests/test_dashboard.py` asserts literal endpoint strings (`/dashboard/api/memories`, `/dashboard/api/metrics/totals`). NEW since investigation: `/status` now returns `historical_lookup_funnel {armed, events_recorded}` (live), and the merged evals write JSON reports to `.local/research/{raw_derived_hybrid,derivation_fidelity}_report.json`. So the "how memory helps" view has real (if partly manual-run) data sources — not empty.

**Material assumptions:**
- A1: The 2-view shell can be built in-place in `app/dashboard.html` with vanilla JS (a tab switch over existing sections) without a framework/build. Disproof: the file is unmaintainable to extend in place → a deliberate split (recorded), still no framework.
- A2: "How memory helps" live data = `/status.historical_lookup_funnel` (already served) + a NEW read-only `/dashboard/api/*` endpoint that runs/serves the rollup and reads the offline eval JSON reports. Disproof: running the rollup on-request is too heavy for a dashboard call → serve last-written report files + the `/status` funnel counts only, with a "run the eval" affordance.
- A3: `tests/test_dashboard.py` string-presence assertions can be preserved or updated without breaking behavior. Disproof: moving panels drops asserted strings → update the tests in the same PR.

**Plan:**
See `## Plan`. UX-design doc FIRST (recorded, surfaced for user review) → two-view shell → operational view (re-home) → how-it-helps view (funnel /status live + rollup/report reader endpoint, empty-safe) → live browser iteration (screenshots) → tests. Stop condition: if the how-it-helps view needs a non-trivial compute endpoint (heavy rollup on-request), fall back to serving last-written reports + /status counts (A2 disproof) and note it.

**Verification plan:**
See `## Verification plan` — UX doc present; two views render (browser); operational panels + APIs intact; how-it-helps shows funnel signal + reports with empty/stale states; `tests/test_dashboard.py` green + new-endpoint coverage; live before/after screenshots.

**Plan review:**
Clean-context agent review REQUIRED (Elevated) — recorded in `## Plan review` before State → Ready to implement. Focus: is a small read-only dashboard-router endpoint the right seam for the funnel KPI / eval reports (vs heavy on-request compute); does the split stay framework-free; are the `test_dashboard.py` string assertions handled.

**Approvals:**
Not required at this risk level (Elevated). Standing overnight package mandate covers proceeding. NOTE: the user explicitly wants to review the UX design ("what I want to see there and why") — the UX-design doc is produced as a reviewable artifact and surfaced, but implementation proceeds under the mandate (the user can adjust the design on review).

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Discovery

From the earlier read-only dashboard investigation (still accurate for structure), refreshed for the merged funnel:

- **One file:** `app/dashboard.html` (2,032 lines), inline `<style>` (dark theme, CSS vars) + inline vanilla JS (hand-rolled SVG sparklines/bars). No framework/bundler/`package.json`.
- **Serving:** `app/dashboard.py` `mount_dashboard(app)` — `GET /dashboard` reads the HTML from disk per request (`:33-36`); edits are live on refresh, no restart/build. Wired at `app/main.py:424`.
- **Sections today (single scroll, no tabs):** header/health, Overview cards, System Health (storage/queue/extraction), Query Activity + Skip Reasons trend, Memory Browser (collapsible), Query Debug (collapsible).
- **Data:** `/dashboard/api/{containers,actors,activity,memories,memories/{id}/feedback,flags,metrics/query,metrics/aggregate,metrics/totals,feedback/stats}` (backed by `MetricsStore` `storage/metrics.py` + direct `MemoryObjectRecord`/feedback/flag selects); plus `/status`, `/debug/queue/health`, `POST /query/debug`, `/memory/{id}/expand`. Every `/dashboard/api/*` route 501s without SQLite.
- **Tests:** `tests/test_dashboard.py` (388 lines) — JSON-API tests + literal-string presence assertions (`/dashboard/api/memories` at :152, `/dashboard/api/metrics/totals` at :162). `tests/test_metrics_api.py`. No browser/DOM tests.
- **"How memory helps" data availability (post-funnel-merge):** `/status.historical_lookup_funnel` {armed, events_recorded} — LIVE. Reuse KPI — `python -m evals.historical_lookup_measurement --db <db>` (rollup; needs judge labels for non-zero rungs). RAW/DERIVED/HYBRID + derivation-fidelity — offline JSON reports under `.local/research/*.json` (manual CLI runs, not scheduled). No live endpoint reads the reports today.

## Plan

Single PR on `feat/add-dashboard-operational-and-value-rework`.

0. **UX-design doc (planning deliverable, FIRST).** `docs/design/` (or `docs/`) short doc: the two views, what goes in each and WHY, panel priority order, what the "how memory helps" view must show to answer *is memory effective?* at a glance (headline: reuse funnel armed + events_recorded + rung KPI when available; supporting: injection rate, block-count, skip reasons; honest caveats), what stays operational, how the memory browser fits, and the empty/"run this eval"/"stale report" strategy for not-yet-live metrics. Recorded in the WR and surfaced for the user to review/adjust.
1. **Two-view shell.** Add a vanilla tab/view switch in `app/dashboard.html` (net-new; no framework). Operational | How memory helps. Preserve deep-link/hash state if cheap. If a file split is warranted, record the rationale (still no framework).
2. **Operational view.** Re-home existing panels (overview, system health, query activity + skip reasons, memory browser, query-debug). No backend change; keep the asserted endpoint strings.
3. **"How memory helps" view.** (a) Funnel signal from `/status.historical_lookup_funnel` (live) — armed state + events_recorded, with a "0 events yet — agents haven't pulled" empty state. (b) Reuse KPI + RAW/DERIVED/HYBRID + derivation-fidelity via a NEW read-only `/dashboard/api/*` endpoint that serves the last-written eval JSON reports (and, if cheap/bounded, the rollup) — friendly "run this eval to populate / last generated at" states; 404/missing file → empty state, not error. Honest measured-vs-shadow labels.
4. **Live iteration.** Run `python -m app.run --host 127.0.0.1 --port 8000` → `http://localhost:8000/dashboard`; iterate both views in a browser (Playwright) until they read clearly; before/after screenshots into the WR. (Iterate against the DEV instance on :8000, NOT the production service on :19836.)
5. **Tests.** Update `tests/test_dashboard.py` for moved/added wiring (keep or update the literal-string assertions); add coverage for the new report/KPI endpoint (empty-file → empty state; served report shape).

## Verification plan

- **C1 (UX doc):** the design doc exists, defines both views + priority + empty-data strategy, recorded in the WR before layout code.
- **C2 (two views, no framework):** browser shows two separated views; grep confirms no bundler/framework added; operational view has all prior panels; existing `/dashboard/api/*` respond.
- **C3 (how-it-helps):** funnel signal renders from `/status` (armed + events_recorded incl. the 0-events empty state); eval reports render via the new endpoint with friendly empty/stale states; honest framing present.
- **C4 (live iteration):** before/after screenshots in the WR; both views read clearly.
- **C5 (tests):** `tests/test_dashboard.py` green (updated); new endpoint covered (empty + populated).
- **Regression:** `python -m pytest tests/ -q` green (modulo known-benign config test).

## Plan review

Clean-context review requested (Elevated) — reference recorded here on completion.

## Implementation

Not started. State `Blocked` (in planning) until the clean-context review returns and State flips to `Ready to implement`.
