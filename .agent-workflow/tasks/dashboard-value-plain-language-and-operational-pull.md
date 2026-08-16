# dashboard-value-plain-language-and-operational-pull

Two-part dashboard pass: (1) make the "How memory helps" value tab speak plain human language
(strip rung-1/rung-2, κ, CALIBRATED/UNCALIBRATED, raw eval commands, endpoint paths) while keeping
it honest; (2) surface the newly-activated agent-pull / historical-lookup path as an OPERATIONAL
signal on the Operational tab, so new capabilities are visibly operational there.

<!-- agent-workflow:start -->
**Outcome:**
The "How memory helps" tab reads in language a non-expert understands — it explains what the numbers
mean (did agents reuse past work, and did it actually help) without internal jargon, and still shows
honestly when a measure isn't yet confidently calibrated. The Operational tab gains a "Historical
Lookups" signal (armed + lookups recorded) so the activated pull path is visible as operational
health, establishing the pattern for surfacing future new capabilities. Display-only; no API/metric
schema change, no production behaviour change.

**Target:**
Pallium — `app/dashboard.html` (copy in the value tab; a new operational section; the `renderFunnel`
and `renderReuseCalibration` JS renderers). Both files are redline BLUE.

**Scope:**
- `app/dashboard.html` value tab: rewrite jargon in the Reuse KPI section title/scope-tag, its
  empty-state, the `renderReuseCalibration` JS strings (rung-1/rung-2, judge-vs-gold κ,
  CALIBRATED/UNCALIBRATED, the `python -m evals...` command), and the `/status.historical_lookup_funnel`
  endpoint leak — into plain language, honest about uncalibrated state.
- `app/dashboard.html` operational tab: add a compact "Historical Lookups" section (armed + lookups
  recorded), wired from the already-loaded `/status.historical_lookup_funnel` via `renderFunnel`.
- NO change to `app/dashboard.py`, endpoints, report schema, or metric semantics.

**Constraints:**
- Honesty preserved: still communicate when a measure is not yet calibrated/confident, just without
  jargon. Do not overclaim.
- Display-only: no data-source, endpoint, or schema changes; the `judge_vs_gold` fields consumed by
  the JS stay the same.
- Do not touch the live service (port 19836).
- No internal/product/company names introduced.

**Completion criteria:**
The value tab has no leaked internal terms (rung-1/rung-2, κ, CALIBRATED, raw eval commands,
`/status...` paths) — verified by grep — and reads plainly while staying honest; the operational tab
shows a Historical Lookups signal reflecting `events_recorded`; the dashboard still loads and renders
(smoke check); no JS references dangle (new element ids are populated by a renderer).

**Risk:** Routine

**Complexity:** Moderate

**Reason:** `app/dashboard.html` is redline BLUE (with a watch on `app/**`); display-only, no runtime
or data surface → Routine. Copy rewrite spanning HTML + two JS renderers plus a new operational
section with wiring → Moderate, so expanded shape.

**Discovery:**
Value-tab jargon is concentrated in `dashboard.html` `renderReuseCalibration` (~2194-2227) and the
Reuse-KPI HTML (~905-919); endpoint leak at ~889. The funnel is already loaded from
`/status.historical_lookup_funnel` and rendered by `renderFunnel` (~1540-1563) into the header pill +
value-tab headline; the Operational Overview (`metrics-row`, fixed 4-col grid ~583-629) does NOT show
the pull path. A 5th grid tile would orphan on a second row, so the pull signal goes in its own
compact section after Overview, populated by extending `renderFunnel` (no new fetch). The pull path
was just activated live (events_recorded 0→1 via a real `pallium_search_history` call), so the
signal will show a non-zero value.

**Material assumptions:**
- ASSUMPTION: the value-tab numbers are display-only over existing report/status fields, so copy edits
  don't change behaviour. DISPROVED BY: a renderer reading a field the rewrite removes. ACTION: keep
  all field reads (`judge_vs_gold.kappa/threshold/calibrated/n`); change only display strings.
- ASSUMPTION: `renderFunnel` runs on every refresh with `/status` funnel data. DISPROVED BY: new
  operational ids never populate. ACTION: verify the ids are set inside `renderFunnel` and it is
  called from the status refresh path.

**Plan:**
1. Value tab: rewrite the Reuse-KPI section title/scope-tag, empty-state, and `renderReuseCalibration`
   strings into plain language — "how often agents reused past work", "reused directly (copied a
   specific detail)" for rung-1, "shaped the approach" for rung-2, "how well our automatic check
   agrees with human review" for κ, "checked / not yet checked against human review" for
   CALIBRATED/UNCALIBRATED; drop the raw eval command and the `/status...` path from user-facing copy.
2. Operational tab: add a compact "Historical Lookups" section (armed + lookups recorded + a plain
   sub) after Overview; extend `renderFunnel` to populate the two new element ids.
3. Smoke: load the dashboard HTML against a stub/live `/status` and confirm render + no dangling ids;
   grep the file for the removed jargon tokens.

**Verification plan:**
- No jargon leak → grep `app/dashboard.html` for rung-1|rung-2|κ|CALIBRATED|reuse_judge_calibration|/status.historical, confirm none remain in user-facing copy.
- Operational signal wired → the new element ids are assigned inside `renderFunnel`; a stub-status smoke render shows the lookups count.
- Honesty preserved → the uncalibrated path still renders an explicit not-yet-confident message in plain words.
- No behaviour change → `app/dashboard.py` untouched; JS still reads the same `judge_vs_gold` fields.
- CI: agent-workflow, redline (BLUE), test lanes.

**Plan review:** Self (Routine).

**Approvals:** Not required at this risk level (Routine).

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

_(pending)_
