<!-- agent-workflow:start -->
**Outcome:** The supported Windows restart wrapper recognizes a healthy service when queue health takes longer than two seconds on a real database.

**Target:** Pallium.

**Scope:** `scripts/restart-service.ps1`, its focused executable tests, the Windows operations note, and RW-020 roadmap follow-up.

**Constraints:** Preserve the exact overall readiness deadline and all three required probes; do not weaken health criteria or change service/API behavior.

**Completion criteria:** A synthetic queue-health response slower than two seconds succeeds within the overall budget; terminal timeout still fails at the exact budget; focused/full tests, CI, review, merge, installed sync, supported restart, and health verification pass.

**Risk:** Elevated

**Complexity:** Simple

**Reason:** The Windows service lifecycle wrapper is an operational control path; the change only adjusts its per-probe timeout allocation.

**Discovery:** Two consecutive supported restarts exhausted 180 seconds at `/debug/queue/health`, while immediate 15-second follow-up probes showed health ok, ingestion ok, embedding provider ok, and queue health healthy. Three steady-state queue probes took 2906ms, 2349ms, and 2315ms. The wrapper caps every request at two seconds, so this endpoint can never pass on the current real database.

**Material assumptions:** Queue health may legitimately take several seconds because it is a live database query; a longer per-request allowance must remain bounded by the existing overall readiness deadline.

**Plan:** Reuse the existing deadline helper with an optional per-probe cap. Keep health and status at two seconds; allow only queue health up to ten seconds, always clipped to remaining readiness budget. Extend existing PowerShell E2E harness assertions for a >2-second successful queue response and exact terminal-budget failure. Add one concise operations note.

**Verification plan:** Delayed queue health completes in approximately three seconds and wrapper succeeds -> focused executable restart test. Queue health beyond the remaining overall deadline still produces the existing bounded failure -> terminal-budget test. Run `tests/test_restart_service.py`, full suite, workflow/redline checks, CI, installed sync, supported restart, and all three live endpoints.

**Plan review:** Clean-context review `/root/relay_hook_plan_review`: APPROVE. BLUE paths; Elevated/Simple justified by operational impact; no boundary/API/schema/security/runtime-config flags or redline checkpoint.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Work Record created before code edits from the live dogfood reproduction.
- Clean-context plan review approved the minimal per-probe cap, with explicit delayed-response, unchanged health/status cap, remaining-budget clipping, and RW-020 alignment checks.
- `apply_patch` failed with Windows process error 1327; repository-approved deterministic replacements were used for the scoped files.
- Implemented a ten-second queue-only cap clipped to the unchanged monotonic deadline; health/status retain the two-second default.
- Focused real-PowerShell restart suite passed: 31 tests. Full repository suite passed: 4990 passed, 34 skipped, 2 xfailed in 227.29s.

## Evidence

- Live measurements and wrapper output are recorded in Discovery.
- Import-boundary report and agent-workflow/redline gate passed with BLUE/Routine detected; the declared Elevated operational risk is conservative.

## Result review

- Clean-context reviewer `/root/relay_hook_result_review`: APPROVE — NO CODE FINDINGS, MERGEABLE_FOR_PR. It verified the unchanged overall deadline, two-second health/status caps, queue cap/clipping, and before/after delayed-response regression.
