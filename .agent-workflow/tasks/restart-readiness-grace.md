<!-- agent-workflow:start -->
**Outcome:**
The installed Windows restart wrapper keeps waiting through legitimate slow cold starts that finish just beyond the old two-minute ceiling, while still failing in finite time with the last failed readiness check.

**Target:**
The Windows installed-service restart readiness policy.

**Scope:**
`scripts/restart-service.ps1`; focused wrapper coverage in `tests/test_restart_service.py`; operator guidance in `docs/context/operations.md`; `RW-020` in `roadmap/features/add-wake-first-relay-delivery.md`; this Work Record.

**Constraints:**
Preserve the strict `/health`, `/status`, and `/debug/queue/health` readiness contracts, monotonic remaining-time probe caps, installed-task validation, process-tree cleanup, and explicit caller-supplied budgets. Add no dependency, new readiness phase, service/API change, production-length test wait, or change to unrelated `scripts/validate_relay_cutover_copies.py`.

**Completion criteria:**
(1) The wrapper's default cold-start budget is three minutes, giving the measured just-after-120-second recovery class one bounded minute of headroom. (2) Explicit `-ReadinessTimeoutSeconds` values retain their exact finite deadline and failure diagnostics. (3) Success still requires all three readiness contracts within the active budget. (4) Deterministic wrapper tests, the full suite, and an installed wrapper run pass; direct post-run probes confirm all three endpoints on port 19836.

**Risk:**
Elevated

**Complexity:**
Simple

**Reason:**
Redline classifies the intended wrapper, tests, docs, roadmap, and Work Record as blue with no watch path, boundary violation, or checkpoint. Engineering risk remains Elevated because this wrapper force-stops and restarts the installed service, and a false success or premature failure affects local availability. Complexity is Simple: one existing default, one caller-surface test pin, and aligned operator/roadmap text.

**Discovery:**
PR #124 replaced retry counting with one correct monotonic 120-second budget, isolated diagnostic capacity, and removed the queue-health full-history scan. Its material assumption that 120 seconds covered cold starts was later disproved: an exact-main installed restart ended on a timed-out final `/health` probe amid transient Windows accept errors, while `/health`, `/status`, and `/debug/queue/health` were all healthy moments later. The current loop already preserves strict endpoint checks, caps each probe by remaining time, reports the last failure, and honors injected budgets. No evidence points to another endpoint, cleanup, or service defect. Session History could not be queried because this turn has no injected container/thread scope; the repository's reopened RW-020 record is the durable evidence.

**Material assumptions:**
A three-minute default is enough for the observed just-after-two-minute recovery class and is a reasonable bounded operator wait. The installed witness must disprove any current service defect; if it still exhausts three minutes, stop and diagnose rather than increasing the bound again. If a service/API change becomes necessary, stop and reclassify.

**Plan:**
(1) Keep the existing single-budget design and change only its default from 120 to 180 seconds; do not add a grace phase or second timeout. (2) Pin the production default in the existing real-PowerShell test surface while retaining the existing explicit tiny-budget exhaustion, transient, and three-contract coverage. (3) State the three-minute bounded default in operations guidance. (4) Run the focused wrapper tests and workflow/diff checks, then use only `scripts/restart-service.ps1` for an installed restart and directly verify `/health`, `/status`, and `/debug/queue/health` on port 19836. Mark RW-020 complete only if that witness passes. (5) Run the full suite, obtain clean-context result review, and complete PR review/merge.

**Verification plan:**
Default policy -> a focused source-contract test pins the public PowerShell parameter default at 180 seconds without sleeping. Explicit deadlines and failure truth -> existing real-PowerShell terminal scenarios keep tiny injected budgets and assert nonzero exit, exact configured budget, last check, and no success output. Readiness completeness -> existing transient lifecycle test requires health, status, and queue-health success before exit 0. Installed behavior -> the repository wrapper must exit 0 against the registered task, followed by direct healthy responses from all three required endpoints on port 19836. Release -> workflow/redline and whitespace checks, full pytest, clean-context result review, green CI, no unresolved PR threads.

**Plan review:**
2026-09-08 clean-context review by /root/review_relay_first_run_plan: APPROVE after correcting Complexity from Moderate to Simple. The single-budget 120-to-180-second approach, existing-surface test, and installed witness are minimal and adequate; Elevated Risk remains justified by the destructive restart witness.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- 2026-09-08: Created the Work Record before code changes. Independent classification initially returned Elevated/Moderate despite an all-blue redline result because the installed restart wrapper controls service availability; clean-context review corrected Complexity to Simple while retaining Elevated Risk.
- 2026-09-08: Chose the smallest existing mechanism: increase the single bounded default instead of adding a separate grace phase, new configuration, or service change.
- 2026-09-08: Changed the wrapper default from 120 to 180 seconds, pinned it in the existing Windows test surface, and documented the three-minute operator bound. All 25 wrapper tests passed.
- 2026-09-08: The no-argument installed wrapper restarted the registered service in about 68 seconds. Direct port-19836 verification returned health `status=ok`, vectors ready, embeddings ready, ingestion `status=ok`, and queue-health HTTP 200. The current service did not naturally trigger a vector rebuild, so the roadmap records no new rebuild-duration claim.

## Evidence

- Default-policy regression: `.venv\Scripts\python.exe -m pytest tests\test_restart_service.py::test_default_readiness_budget_allows_three_minute_cold_start -q -n 0` → 1 passed.
- Complete wrapper file: `.venv\Scripts\python.exe -m pytest tests\test_restart_service.py -q -n 0` → 25 passed in 19.15 seconds, including explicit tiny-budget exhaustion and all three readiness contracts.
- Installed witness: `scripts/restart-service.ps1` with no timeout override exited 0 in about 68 seconds. Direct port-19836 probes returned `/health` status ok with vector/embedding readiness, `/status` embedding provider true and ingestion ok, and `/debug/queue/health` HTTP 200. The current service did not naturally trigger a vector rebuild.
- Full repository gate: `.venv\Scripts\python.exe -m pytest tests\ -x -q` → 4659 passed, 32 skipped, 2 xfailed, with four pre-existing Pydantic warnings in 184.82 seconds.
- `.venv\Scripts\python.exe scripts\agent-workflow-check.py --repo-root . --slug restart-readiness-grace` → clean; `git diff --check` → clean.
- `apply_patch` had already failed in this user task with Windows CreateProcess error 1327; per repository instructions, these edits used deterministic replacements limited to the five scoped files.
- Skill-feedback check: all triggers No.

## Result review

2026-09-08 clean-context review by /root/review_relay_first_run_result: APPROVE. The production change is only the 120-to-180-second default with the original UTF-8 BOM preserved; explicit deadlines, diagnostics, all three readiness contracts, tests, and honestly scoped roadmap evidence are adequate.