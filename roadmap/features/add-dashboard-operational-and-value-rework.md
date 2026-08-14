---
id: add-dashboard-operational-and-value-rework
title: Dashboard rework — operational view + "how memory helps" view
status: queued
priority: high
commitment: committed
milestone: pallium-vnext-p1
---

## Summary

Rework the local Pallium dashboard from a single long scroll into a **two-view**
experience: an **Operational** view (is Pallium healthy and working — metrics, issues,
memory browser) and a **"How memory helps"** view (is Pallium *effective* — the reuse
funnel KPI and the derivation/representation evals surfaced for a human). The rework
starts with a **UX design pass** (what the user wants to see, what matters, and why)
before any layout code, and is built by **running the dashboard live and iterating on it
visually** until it reads well.

## Why

The dashboard today is one 2,032-line `app/dashboard.html` (vanilla HTML/CSS/JS, served
from disk per request — edit-and-refresh, no build step) that surfaces only operational
metrics: overview counts, storage/queue/extraction health, query activity + skip
reasons, memory browser, query-debug. vNext added the metrics that answer the question
the user actually cares about — *is this memory system helping?* — but those live only in
eval outputs (reuse-funnel KPI is currently a stub pending the funnel feature;
RAW/DERIVED/HYBRID and derivation-fidelity are offline JSON reports under
`.local/research/`). Mixing "is it up?" with "is it helping?" on one scroll buries the
value story. Separating concerns into two views lets an operator triage health fast and
lets the user read effectiveness deliberately — and gives the new metrics a home.

## In Scope

1. **UX design pass FIRST (planning deliverable, before layout code).** A short design
   doc that answers: what goes in each view and why; the priority order of panels; what
   the "how memory helps" view must show to answer *is memory effective?* at a glance
   (headline KPI + supporting rates + the honest caveats); what stays operational; how
   the memory browser fits; and what to do about metrics that are not live yet
   (empty/"run this eval" states vs. hiding). Produced and recorded in the Work Record
   before building.
2. **Two-view shell.** Introduce a tab/view switch in `app/dashboard.html` (net-new — no
   tab container exists today) separating **Operational** from **How memory helps**,
   without a framework/build step (keep vanilla HTML/CSS/JS, single-file or a
   deliberately-split file — decided in the design). Preserve deep-linkable state if
   cheap.
3. **Operational view.** Re-home the existing working panels: overview cards, system
   health (storage/queue/extraction), query activity + skip-reason trend, and the memory
   browser + query-debug. No backend change — these are already backed by
   `/dashboard/api/*`, `/status`, `/debug/queue/health`, `/query/debug`. Consider
   surfacing operational metrics currently only in evals (e.g. injection block-count
   distribution is already live; no-value/stale/wrong-selection rates are eval-only —
   decide per the design whether any are worth a live panel).
4. **"How memory helps" view.** Surface the effectiveness metrics:
   - Reuse-funnel KPI (reuse-per-100-eligible, three rungs, supporting rates) once the
     funnel feature lands its loader — read via a new read-only endpoint or the rollup
     output; **empty-data-safe** with a clear "no measurement window yet" state.
   - RAW/DERIVED/HYBRID and derivation-fidelity summaries — read the offline JSON reports
     (`.local/research/raw_derived_hybrid_report.json`,
     `.local/research/derivation_fidelity_report.json`) with a "last generated at / run
     this eval to refresh" affordance (these are manual CLI runs, not scheduled), or a
     small endpoint that serves the latest report file. Missing file → friendly empty
     state, not an error.
   - Honest framing: label what is measured vs. shadow/offline, and never imply live
     when the data is a stale report.
5. **Live iteration + screenshots.** Run the dashboard locally (`python -m app.run
   --host 127.0.0.1 --port 8000` → `http://localhost:8000/dashboard`) and iterate on the
   real rendered UI (Playwright/browser) until both views read clearly — captured as
   before/after evidence in the Work Record.
6. **Tests updated.** Keep/adjust `tests/test_dashboard.py` (it asserts literal endpoint
   strings like `/dashboard/api/memories`, `/dashboard/api/metrics/totals` are present in
   the HTML) and add coverage for any new endpoint that serves report files or the KPI.

## Out of Scope

- Introducing a JS framework, bundler, or build step (explicit non-goal — keep vanilla,
  edit-and-refresh). If the single file must be split, that is a deliberate structural
  choice recorded in the design, not a framework adoption.
- Computing new metrics: this feature *surfaces* the funnel KPI and the eval reports; it
  does not implement the funnel loader (that is `add-historical-lookup-reuse-funnel`) or
  change the evals. If the KPI endpoint depends on the funnel feature, this view ships
  its empty state first and lights up when the funnel lands.
- Scheduling eval runs / turning offline reports into live pipelines.
- Auth, multi-user, or remote-hosting concerns (local single-user dashboard).

## Done When

1. A recorded UX-design pass defines both views (what/why/priority) and the empty-data
   strategy for not-yet-live metrics — done before layout code.
2. The dashboard presents two clearly-separated views (Operational | How memory helps)
   with no framework/build step introduced; the operational view preserves all current
   working panels + the memory browser; existing dashboard APIs still work.
3. The "how memory helps" view surfaces the reuse-funnel KPI (empty-data-safe) and the
   RAW/DERIVED/HYBRID + derivation-fidelity reports (friendly empty/"stale report"
   states), with honest measured-vs-shadow framing.
4. The dashboard was iterated live (browser) with before/after screenshots in the Work
   Record; both views read clearly.
5. `tests/test_dashboard.py` passes (updated for any moved/added wiring), and any new
   report/KPI endpoint has coverage.

## Notes

Ordered **after** the funnel feature (so the KPI has a data source to light up) and its
exposure sibling, **before** the perf/e2e validation gate. Depends for its headline KPI
on `add-historical-lookup-reuse-funnel`; the eval-report panels depend only on the
already-merged `evals/raw_derived_hybrid/` + `evals/derivation_fidelity/` report files.

**Structural facts the plan must respect** (from investigation): single file
`app/dashboard.html` (2,032 lines), all CSS/JS inline; HTML read from disk per request
(edits live on refresh, no restart); fixed route `/dashboard` via `mount_dashboard()` in
`app/dashboard.py` wired at `app/main.py:424`; every `/dashboard/api/*` route 501s
without the SQLite backend; live metrics come from the `MetricRecord` table via
`MetricsStore` (`storage/metrics.py`) aggregated on read; no tab structure exists today
(only two collapsible sections); `tests/test_dashboard.py` asserts literal endpoint
strings in the HTML.

**Risk: guarded → likely Elevated.** Touches `app/dashboard.py` + `app/dashboard.html`
(guarded `app/` but a self-contained dashboard surface, not `core/`/`api/routes.py`
RED), possibly a small read-only report/KPI endpoint (new route — API-review consider if
it lands in `api/routes.py`; prefer a `/dashboard/api/*` route to stay on the dashboard
surface), and `tests/`. No persistence change, no retrieval-behavior change. A
change-classification at Work-Record time confirms; a read-only report-file endpoint on
the dashboard router stays Elevated.
