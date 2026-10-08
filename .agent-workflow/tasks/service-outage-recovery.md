# Service outage recovery

<!-- agent-workflow:start -->
**Outcome:** Explain the service outage and correct demonstrated supervision or launcher recovery defects without changing the user's live installation.

**Target:** Pallium local service supervision and Windows launcher generation.

**Scope:** Isolated investigation of AcceptEx error handling, API startup/restart budgets, supervisor terminal status and generated Windows launcher status propagation; minimal regression-backed corrections and focused caller-surface coverage; reviewed handoff to pallium manager.

**Constraints:** Pallium manager exclusively owns live restoration, health checks and installed operations. No installed edits, service operations, real database tests, configuration changes, native enrollment or parallel full qualification. Preserve the frozen Relay projection component and incident evidence. No speculative timeout-only patch, new dependency, weakened protected contract or inferred historical cause.

**Completion criteria:** Established source defects and unresolved incident causes are distinguished; each implemented correction has focused caller-surface lifecycle/failure coverage and independent smart plan/result review; coordinated whole-change validation, workflow/risk checks and PR/merge gates remain explicit; manager receives exact revision, evidence and any separately required live rollout scope.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"Explain the service outage and correct demonstrated supervision or launcher recovery defects without changing the user's live installation.","scope":"Isolated investigation of AcceptEx error handling, API startup/restart budgets, supervisor terminal status and generated Windows launcher status propagation; minimal regression-backed corrections and focused caller-surface coverage; reviewed handoff to pallium manager.","constraints":"Pallium manager exclusively owns live restoration, health checks and installed operations. No installed edits, service operations, real database tests, configuration changes, native enrollment or parallel full qualification. Preserve the frozen Relay projection component and incident evidence. No speculative timeout-only patch, new dependency, weakened protected contract or inferred historical cause.","completion_criteria":"Established source defects and unresolved incident causes are distinguished; each implemented correction has focused caller-surface lifecycle/failure coverage and independent smart plan/result review; coordinated whole-change validation, workflow/risk checks and PR/merge gates remain explicit; manager receives exact revision, evidence and any separately required live rollout scope."}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** app/supervisor.py, app/cli/service.py and app/asyncio_windows_accept.py are unclassified gray/watch runtime surfaces; launcher and recovery changes affect availability and child lifecycle. scripts/install-service.ps1 and existing tests/docs are blue. Risk will be reassessed against the exact selected fix and final diff.

**Discovery:** Start from verified installed/shared-main f31ac14186943cdc60ce10dbb37e26c42a3496bc in a new managed isolated checkout. origin/main is stale at5106866622deb9c011fd7538732d6b145a8ba147; no remote revision or service update is assumed. Runtime API restart exhaustion leaves exit_code initially0; both CLI and PowerShell-generated VBS launchers detach with wait=False, so scheduler sees launcher completion, not supervisor lifetime/status. Installed launcher's exact generation/provenance still needs reconciliation because the reported service_launcher.vbs differs from CLI run/pallium_launcher.vbs. Existing AcceptEx patch immediately reschedules transient failures; incident mechanism remains unproved. Manager reports independent restoration succeeded after one wrapper timed out, reproducing disagreement between wrapper and startup/recovery budgets.

**Material assumptions:** Source diagnosis and fake-process/private-home tests do not establish installed socket causality or scheduler acceptance. Same clean installed revision was restored by manager with no settings/code update. Tests require an explicitly coordinated bounded slot and fail-closed isolation; no test run begins during discovery.

**Plan:** First invoke the /agent-workflow skill to create the Work Record and classify risk before any code edit. Trace existing supervisor, CLI, PowerShell launcher and socket callers, distinguish fatal exhaustion from intentional stop and map all readiness budgets. Delegate bounded static tracing to a cheap non-writing agent. Select the smallest demonstrated correction, specify exact files and lifecycle/compatibility expectations, and obtain clean-context smart plan review before production edits. Preserve existing helpers, process-tree cleanup, hidden windows, identity/token fencing and bounded recovery. Stop on unproved assumptions or scope expansion. Only then implement in this checkout and run manager-allocated focused checks; retain exact commands, time intervals and logs. Independent smart result review and coordinated full/PR gates precede release; no installed action is authorized by this plan.

**Verification plan:** When recovery is fatally exhausted, the supervisor must expose failure rather than successful shutdown while intentional stop remains successful -> isolated fake-process caller regression through run_supervisor and CLI service/run dispatch. When a generated Windows launcher owns a service run, it must preserve hidden launch and propagate child terminal status rather than detach -> isolated generated-script/launcher execution checks with only private fixtures and mocked scheduler registration. When readiness budgets interact, the documented bounded lifecycle must agree with observed outcomes -> source-derived budget accounting and deterministic injected-clock caller checks, not an arbitrary timeout increase. Existing child cleanup, retry, token/foreign-process and transient/fatal listener behavior -> affected existing suites once a slot is allocated. Whole-change release -> selector/full lane, workflow/Redline/import checks and independent review; manager owns installed qualification and roadmap reconciliation.

**Plan review:** Pending discovery and exact correction selection; production edits are held until clean-context smart technical plan review.

**Approvals:** Existing human outage investigation/prevention request relayed by pallium manager authorizes isolated implementation only. No new installed launcher/config/restart scope is approved. Separate human plan/result gate will be required if reassessment raises Risk to High.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

2026-10-08: Accepted bounded ownership from pallium manager chat
01a0d7ce-83c6-77e2-90f7-d413894059e1. Manager owns restoration and reviews;
worker owns isolated investigation/fix, not production operation. Initial
State Blocked names the pending reviewed implementation plan, not a need
for another general task approval; read-only discovery continues.

Manager-reported outage evidence (not independently reread here): Oct8
08:09:39/49 UTC health probes failed amid WinError64 AcceptEx storm; API69796
killed, five replacement startups each hit30s deadline. Final startup52388
timed out08:12:52.484 and underlying API31024 logged startup complete
08:12:53.093, followed by supervisor cleanup08:13:11. Scheduled task appeared
Ready/LastTaskResult0. This establishes observation order, not socket root cause.

Manager-reported restore: ONE installed restart-service.ps1 wrapper exited1
at180s with last health503; later actual health/status/queue all200 at
08:45:13 UTC, status ingestionok/uptime32.8, vector and embedding ready,
17438 completed/no pending or failed ingestion. Replacement attempt2
timed out08:42:53; attempt3 started08:42:59/timed out08:43:30;
attempt4 started08:43:38/timed out08:44:09; attempt5 started08:44:20;
processors81236/cleaner77768 started08:44:42. Same installed f31ac141,
no update/settings change. Nine eligible pending/two uncertain Relay entries
are not payload receipt evidence. Worker performs no further live checks.

New checkout C:/Users/I347041/.codex/worktrees/service-outage-recovery/Pallium,
branch feat/service-outage-recovery, baseline f31ac14186943cdc60ce10dbb37e26c42a3496bc.
No source or test edit/run yet. Frozen projection branch and its evidence are
untouched. Manager owns any canonical roadmap association/status; no exact
new roadmap/work identity was supplied, so none is guessed or attached.
