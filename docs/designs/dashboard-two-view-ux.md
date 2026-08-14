# Dashboard rework — two-view UX design

Status: design (precedes implementation of `add-dashboard-operational-and-value-rework`).
Reviewable artifact — the operator should confirm/adjust "what I want to see and why" here before/while the layout lands.

## The problem this solves

The dashboard today is one long scroll that answers only *"is Pallium up and processing?"* — overview counts, storage/queue/extraction health, query activity, skip reasons, the memory browser, query-debug. vNext added the signal that answers the question the operator actually cares about — *"is this memory system **helping**?"* — but that signal lives in eval outputs and a new `/status` field, not on the dashboard. Mixing "is it up?" with "is it helping?" on one scroll buries the value story and makes health-triage slower.

**Split into two views, each answering one question:**

| View | Question it answers | Who reads it, when |
|---|---|---|
| **Operational** | Is Pallium healthy and working right now? | triage / day-to-day; glance and move on |
| **How memory helps** | Is Pallium actually effective — does memory get reused, is derived memory worth it? | deliberate reading; "is this paying off?" |

The switch is a top-level tab (CSS `display` toggle; both views stay in the DOM so the 10s auto-refresh never breaks). Operational is the default view (health-first).

## View A — Operational (what's here + priority)

All backed by existing endpoints (`/status`, `/debug/queue/health`, `/query/debug`, `/dashboard/api/*`) — **no backend change**, this is a re-home. Priority top→bottom = "what breaks triage if I can't see it":

1. **Header + health badge + uptime** — is it up, how long, auto-refresh countdown. (Also surface the funnel-armed pill here — one glance says "measurement is on".)
2. **System Health** — Storage (SQLite + vector index size), Ingestion Queue (pending/done/failed/skipped), Extraction Health (recent failures). This is the "something's wrong" row; keep it high.
3. **Overview cards** — Memory Objects (active/total), Source Items, Queries (+ inject rate), Failed extractions, with sparklines.
4. **Query Activity + Skip Reasons** — injections/skips/flags/feedback tiles + hourly bars; skip-reason trend table. (Operational lens on *why* memory isn't injecting.)
5. **Memory Browser** (collapsible) — search/filter/sort memories, expand for content + feedback + evidence. The "what does it actually know / why did it surface this" tool.
6. **Query Debug** (collapsible) — ad-hoc INJECT/SKIP + retrieval-trace inspection.

Rationale: an operator triaging "is it broken?" reads 1–2 and stops; 3–4 are trend context; 5–6 are investigation tools, so they stay collapsible at the bottom.

## View B — How memory helps (the effectiveness story)

The headline answers *"do agents reuse prior work, and is it landing?"*; supporting panels give the rates behind it; a shadow section reports the derivation research honestly. **Honest framing is a hard rule**: every panel is labelled *live* / *retrospective (needs the judge)* / *shadow (offline eval)* so nothing reads as live when it's a stale report.

1. **Reuse funnel — headline (LIVE).** From `/status.historical_lookup_funnel`: **armed** (yes/no) + **events_recorded** (lookups captured so far). This is live the moment the service runs the funnel code.
   - Empty state when `events_recorded == 0`: *"Funnel armed, no lookups yet — agents haven't pulled history. Deploy the historical-lookup guidance (`pallium setup claude-code`) so agents pull, then events appear here."* (This is the honest "why is it zero" nudge, not a broken panel.)
2. **Reuse KPI — rungs (RETROSPECTIVE).** reuse-per-100-eligible for rung-1 (verified incorporation) + rung-2 (judged influence), with Wilson intervals + the supporting rates (opportunity→lookup, lookup→useful). Sourced from the **last-written rollup/report**, not computed on-request. Labelled *"needs the retrospective judge — run `python -m evals.historical_lookup_measurement` / the judge to populate; last generated <mtime>."* Empty state until a judge run exists.
3. **Derivation research — shadow (OFFLINE).** Compact summaries of the two merged offline evals, read from their last-written JSON reports:
   - **RAW / DERIVED / HYBRID** — candidate recovery + representation quality + cost-at-equal-budget headline.
   - **Derivation fidelity** — coverage + fidelity (misleading/unsupported rate).
   Each labelled *shadow / offline*, with *"last generated <mtime> — run the eval to refresh"* and a friendly "not generated yet" empty state when the file/dir is absent.

Deliberately **not** here (deferred): promoting eval-only operational rates (no-value overreach, stale-memory, wrong-selection, thread-rebuild churn) into live panels — those require eval compute in the request path, so they stay in eval outputs; if surfaced later they get the same "run this eval" treatment, never a fake-live number.

## Data sources & the empty/stale strategy

| Panel | Source | Freshness | Empty/stale treatment |
|---|---|---|---|
| Funnel armed + events_recorded | `/status.historical_lookup_funnel` | live | "armed, 0 lookups yet" nudge |
| Reuse KPI (rungs, rates) | last-written rollup/report file | retrospective | "run the judge; last gen <mtime>" |
| RAW/DERIVED/HYBRID | `.local/research/raw_derived_hybrid_report.json` | offline | "not generated yet / last gen <mtime>" |
| Derivation fidelity | `.local/research/derivation_fidelity_report.json` | offline | same |

Rules:
- The new dashboard endpoint **serves last-written report files only** — it never runs the rollup/loader on-request (that would scan `source_items` unbounded on a 10s-cadence sync handler).
- Report paths are **hardcoded** on the server (a fixed `report` key → constant `Path`); no user-supplied filename. Missing `.local/research/` dir or file → **200 with an empty state**, never 404/500.
- Report paths are **cwd-relative** (`.local/research/…`), so "populated" depends on the server's working dir matching the eval's — call this out in the panel's help text.
- Never render a stale report as if it were live: always show the `last_modified` timestamp and the *shadow/offline* label.

## Constraints honored

Vanilla HTML/CSS/JS, no framework/bundler/build step; single `app/dashboard.html`, JS stays inline (a split would break the HTML-substring tests and needs a build to be worthwhile). Two views via CSS `display` toggle, all elements in the DOM. New endpoint is read-only, on the dashboard router (`/dashboard/api/*`), off the RED `api/routes.py` surface. Every `/dashboard/api/*` still 501s without SQLite.

## Success = the operator can, in two glances

1. **Operational tab:** "healthy, queue clear, memory growing" — or spot the red immediately.
2. **How-memory-helps tab:** "the funnel is armed, N lookups captured, rung-1/2 reuse is X per 100 eligible (or: not measured yet — here's what to run), and the derivation shadow says derived memory is/ isn't earning its place."
