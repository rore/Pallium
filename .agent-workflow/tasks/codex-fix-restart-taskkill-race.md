<!-- agent-workflow:start -->
**Outcome:** The required Windows restart wrapper completes cleanup when `taskkill /T` partially succeeds during a child-exit race, but still refuses to start a second service while the installed port remains occupied.

**Target:** Windows service restart process-tree cleanup, deterministic real-script regressions, Relay bug roadmap, and this Work Record.

**Scope:** `scripts/restart-service.ps1`, `tests/test_restart_service.py`, `roadmap/features/add-wake-first-relay-delivery.md`, and this Work Record.

**Constraints:** Preserve preflight-before-stop, exact installed home/port resolution, MCP bridge exclusion, task action compatibility, all three readiness checks, bounded timing, and existing process signatures. Do not hide a surviving listener, weaken fail-before-start safety, add a dependency, or add real sleeps to tests.

**Completion criteria:** A partial/nonzero `taskkill /T` caused by a racing child cannot abort the remaining exact cleanup passes; all taskkill sites share the same behavior; after the existing deterministic settle interval, any remaining listener on the installed port fails before `Start-ScheduledTask`; a one-time taskkill error with no survivor restarts successfully; a persistent listener never starts a duplicate; existing RW-010/RW-016 service, port, preflight, PID/log, Unicode, and readiness regressions pass; clean-context review, workflow/redline, PR CI, installed wrapper restart, and endpoint health pass.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Only blue script/test/roadmap/workflow paths change, but the wrapper kills process trees and controls availability of the installed local service; a wrong error policy can either strand the service or start a duplicate.

**Discovery:** Installed dogfood after PR #114 stopped the task and listener, then `taskkill /F /T /PID 18496` removed the stale root but emitted an error for a racing child. `$ErrorActionPreference = "Stop"` converted it into a terminating error before signature sweeps and restart. The child `pythonw.exe -m app.run serve` survived under the gone root and respawned the HTTP server, leaving health green but the wrapper incomplete and PID metadata stale. Every taskkill call currently inherits the same abort behavior and the script does not verify the port is free after cleanup.

**Material assumptions:** A nonzero tree-kill result can be ignored only provisionally because later exact signature sweeps plus a post-settle port check prove the observable shutdown condition; disprove if another required non-port process can survive without a matching signature, then add only its existing lifecycle signal. The existing two-second production settle is adequate for the final port check; disprove through installed restart and keep the same bounded loop rather than adding an unbounded wait.

**Plan:** Introduce one tiny best-effort process-tree helper around native `taskkill` and route all three existing call sites through it so a child-exit race cannot skip later cleanup. Keep the existing settle sleep, then query the exact installed port; if a listener remains, report its PID and stop before scheduled-task start. Extend the real PowerShell harness so the first tree kill can throw once and a separate case can retain the listener; assert successful restart in the first case and fail-before-start in the second. Update the Relay roadmap with the dogfood incident and qualification status. Stop and return to planning if tolerating taskkill errors can bypass the final observable port gate or if a supported restart mode has no listener.

**Verification plan:** First native tree-kill throws after partial success -> real-script harness continues signatures, performs post-settle port check, starts the task, and passes health/status/queue readiness; installed port remains occupied after all sweeps -> wrapper returns nonzero with actionable PID, never calls `Start-ScheduledTask`, and never prints success; existing preflight/metadata/port/PID/Unicode/legacy/transient/terminal tests -> unchanged; installed witness -> exact merged-main wrapper completes, PID/port metadata refresh, `/health` is ok, `/status` has healthy embedding and ingestion, and `/debug/queue/health` is 2xx; gates -> focused suite, exact Windows smoke, workflow/redline, clean-context result review, PR CI, and merge.

**Plan review:** Approved by clean-context Luna reviewer `/root/rw018_plan_review` on 2026-09-06. It confirmed the taskkill child-exit race and approved centralized best-effort kills plus an array-safe post-settle port gate. It required warning on both thrown/nonzero native results and regressions for one-time failure recovery and persistent-listener refusal.

**Approvals:** Approved by user 2026-09-06: "you don't need to ask every time, you have a constant approval to get what you're working on to a done state"

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Routed every native tree kill through one helper that reports thrown or nonzero partial failure and continues the existing exact cleanup sweeps.
- Added a null- and array-safe post-settle port gate before scheduled-task start, plus explicit successful exit 0 so a tolerated native exit code cannot leak.
- Extended the real PowerShell harness with a one-time taskkill exception and two persistent listener PIDs; no production wait or dependency was added.

## Evidence

- Dogfood incident: wrapper aborted on a partial `taskkill /T` native error before its signature sweeps; exact old root/listener PIDs then disappeared while orphan `pythonw.exe -m app.run serve` survived and respawned the service.
- Focused real-script restart suite: 22 passed in 7.82s. Full Windows smoke plus service CLI floor: 326 passed, 6 skipped in 15.40s.
- Corrected wrapper replayed the exact live orphan shape and exited 0; installed PID refreshed from stale 18496 to 9680, port remained 19836, launcher was UTF-16 exact-home, `/health` was ok, embedding and ingestion were healthy, and queue health returned 200.
- Relay message `relay-msg-732471bf...` sent after restart auto-delivered once to `codex:@relaydev` in about nine seconds with durable expiry omitted.

## Plan review

- Pending.

## Result review

Clean-context Luna review approved the centralized kill handling, array-safe pre-start port gate, explicit success exit, MCP exclusion, deterministic regressions, roadmap state, and installed evidence with no actionable blocker.