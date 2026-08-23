# Reliable reuse calibration

Branch: `codex/reliable-reuse-calibration`

<!-- agent-workflow:start -->
**Outcome:**
Pallium's reuse checker reliably supplies verifiable shared evidence, and the dashboard reflects the newest complete calibration attempt rather than an older passing report.

**Target:**
Pallium repository.

**Scope:**
Reuse-judge prompt/output handling, calibration report publication, focused evaluator/dashboard tests, the calibration roadmap card, and this Work Record.

**Constraints:**
Do not weaken evidence-span validation, tune the maintained reference fixture, change production retrieval/ranking, expose private history, or describe reference-set stability as proof that Pallium helped real work. A failed completed calibration must remain visible as failed.

**Completion criteria:**
The deterministic suite rejects unsupported evidence and accepts valid shared evidence; a cache-disabled two-group reference run has no missing/failed events and all three agreement gates meet κ≥0.70; the canonical dashboard report is replaced by that newest run whether it passes or fails; the live dashboard shows the same verdict after the VBS-backed service restarts.

**Risk:**
Routine

**Complexity:**
Moderate

**Reason:**
Redline classified all intended eval, test, roadmap, and optional dashboard paths blue with no boundary or checkpoint findings. Complexity is moderate because prompt behavior, report publication, multi-seed external evaluation, and live dashboard agreement must all align.

**Discovery:**
The canonical dashboard report is the older 15:34 passing run (κ=0.75, N=12). A newer 16:53 post-enforcement run failed: 16/72 calls violated evidence-span validation, so the roadmap correctly reopened calibration while the dashboard remained stale. The validator itself is intentionally fail-closed.

**Material assumptions:**
The configured HAI judge can execute the synthetic 12-case reference run without sending private user history; disprove by provider/config failure or by discovering non-synthetic inputs, then stop before any external call. Prompt-only repair is sufficient; disprove if deterministic replay shows the shared span is absent or the parser/runner causes the failures, then revise the plan before editing additional surfaces.

**Plan:**
Inspect every failed synthetic case and the judge prompt/runner path; make the smallest prompt or output-contract repair that tells the existing judge how to quote a short exact span present on both sides; add deterministic regression coverage for the failure class and canonical pass/fail publication; run focused tests; run the full cache-disabled two-group calibration to the canonical path; update roadmap evidence and verify the restarted live dashboard. Stop if success would require weakening validation or editing the reference fixture.

**Verification plan:**
Focused historical-lookup judge and calibration tests; dashboard report endpoint/rendering tests if publication wiring changes; agent-workflow/redline checks; the real two-group 72-call synthetic calibration with zero failures/missing events and κ≥0.70 for group A, group B, and mutual agreement; canonical report metadata and live dashboard verdict after VBS-backed restart.

**Plan review:**
Clean-context review required by Moderate complexity; pending after discovery.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- Context/risk: current dashboard/report drift confirmed from aggregate local metadata. Clean-context redline review classified the intended scope blue with no checkpoint; `app/dashboard.py` is watch-only if touched. The referenced repository-local agent-redline skill file was absent, so classification used the checked-in policy and reporter.

## Evidence

Pending.

## Result review

Pending.
