# Plain-language derivation dashboard

Branch: `codex/plain-language-derivation-dashboard`

<!-- agent-workflow:start -->
**Outcome:**
The derivation-research dashboard tells a non-technical user what the latest experiment found, what it does not yet prove, and how much data was examined.

**Target:**
Pallium repository.

**Scope:**
Derivation-research labels and rendering in `app/dashboard.html`, focused dashboard HTML tests, and this Work Record.

**Constraints:**
Do not change report schemas, evaluator behavior, service APIs, or invent confidence from unjudged data. Preserve the technical report timestamp and equal-budget/offline caveats.

**Completion criteria:**
When either report is present, the dashboard shall show a plain-language conclusion with percentages/counts and explicitly say when quality was not judged; technical terms remain secondary. Missing-report guidance remains understandable.

**Risk:** Routine

**Complexity:** Simple

**Reason:**
All intended files are blue-zone dashboard UI, tests, and workflow metadata; no boundary, API, persistence, security, or runtime-config surface changes.

**Approach:**
Reuse the existing client-side report renderers: replace jargon-first headings and raw key/value dumps with short human summaries, percentage formatting, and a compact technical-details block. Add HTML contract assertions for the explanations and unjudged state.

**Verification:**
Focused dashboard tests, a deterministic JavaScript renderer check against present/missing/judged/unjudged reports, full relevant regression, and live dashboard verification after the VBS-backed service restart.

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Discovery: the reports are already loaded correctly. The UI currently exposes raw labels (`raw_only`, `item coverage`) and decimals, and reports `objects judged` even when every fidelity result is null. The smallest root fix is confined to the two existing JavaScript renderers and their visible headings.
- Implementation: replaced jargon-first headings and key/value dumps with calculated human conclusions, explicit unjudged-state wording, and collapsed technical details. The helpfulness panel now distinguishes "the measurement works" from "memory helped," and expanded technical details retain their state across refreshes. The repository patch helper failed with Windows error 1385; exact replacements were then limited to the recorded dashboard and test files.

## Evidence

- `node tests\dashboard_plain_language_renderer.mjs app\dashboard.html`: passed; executes the shipped renderers for every helpfulness-calibration state, refresh-preserved technical details, original-history win, compact-memory win, tie, unknown lookup count, missing reports, empty coverage, and mixed judged/unjudged results.
- `.venv\Scripts\python.exe -m pytest tests\test_dashboard.py -q`: 28 passed; 4 pre-existing Pydantic warnings.
- VBS-backed service restarted successfully. `/health`: status ok, vector index ready, embedding provider ok. `/dashboard`: HTTP 200 with all three plain-language headings. Both experiment reports are available; current data is 28 lookups, 44% item coverage, and 62% conversation coverage.
- In-app browser pixel inspection was unavailable because its Windows Node sandbox hit `CreateProcessWithLogonW failed: 1385`; live HTTP and executable rendering of the actual shipped JavaScript provide the fallback verification.

## Result review

Independent reviewer first found three misleading/untested states: a downstream-safety overclaim, nullable judge values counted as false, and static-only HTML assertions. After those were fixed, the reviewer found two more partial-report cases: an unconditional winner claim and missing lookup counts rendered as zero. The final reviews approved the corrected diff, the plain-language helpfulness distinction, and refresh-preserved technical details with executable coverage for all identified states. PR review then suggested skipping the renderer check when Node is unavailable and removing one brittle source-text assertion; both were addressed and revalidated.
