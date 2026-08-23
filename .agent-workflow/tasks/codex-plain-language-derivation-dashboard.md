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
- Implementation: replaced jargon-first headings and key/value dumps with calculated human conclusions, explicit unjudged-state wording, and collapsed technical details. The repository patch helper failed once with Windows error 1385; exact replacements were then limited to the recorded dashboard and test files.

## Evidence

Pending.

## Result review

Pending.
