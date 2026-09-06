<!-- agent-workflow:start -->
**Outcome:** Restarting the installed Windows Pallium service leaves a healthy existing process untouched when the registered replacement cannot import, and reports success only after all required readiness signals pass.

**Target:** Pallium Windows service restart workflow.

**Scope:** `scripts/restart-service.ps1`, its real PowerShell caller-surface regressions, Windows operations guidance, the Relay RW-010 ledger, and this Work Record.

**Constraints:** Preserve the stale process-tree sweep and exclusion of client-owned `app.run mcp` bridges; support both observed Windows task shapes from `pallium service install` and the legacy helper, including their configured ports; use the exact installed interpreter and an installed working directory only when one exists; allow valid dirty checkouts; no wall-clock waits in tests; no changes to Unix wrappers, service installation format, service runtime code, or public APIs.

**Completion criteria:** Import/preflight failure occurs before any stop or kill and exits nonzero with actionable diagnostics; successful restart polls `/health`, `/status`, and `/debug/queue/health` until health is `ok`, embeddings and ingestion are healthy, and queue HTTP succeeds; start failure or bounded readiness exhaustion exits nonzero without printing success; deterministic real-script tests prove each path.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Redline classifies the script/test/docs/roadmap/record paths blue and `.github/workflows/ci.yml` gray with no checkpoint, but engineering judgment raises risk because the wrapper force-kills a live service and a false success can strand all integrations. Moderate complexity comes from installed-task/VBS interpreter discovery, two supported Windows task shapes, and deterministic execution of the real PowerShell script.

**Discovery:** The wrapper originally stopped and swept the live process tree before validating disk code, then started the fire-and-forget scheduled task and printed success without probing. The task action supplies the authoritative VBS path; the VBS supplies the authoritative Python executable. The current local legacy task also supplies a repo working directory and Python launcher, while canonical `app/cli/service.py::_install_windows` deliberately omits `WorkingDirectory` and invokes `python -m app.run service run` from its VBS. The original slice rejected that canonical installation, omitted its `app.run service run` process signature, and hardcoded port 19836 although both installers accept a custom port. A blanket dirty-checkout rejection is broader than the failure and would block valid development restarts, so importability—not Git cleanliness—is the safety gate. The PR Windows smoke job names tests explicitly, so the new restart regression must be added to that list or it will not exercise native Windows on PRs. The deprecated `scripts/install-service.ps1` still writes a legacy `run(["all"])` launcher; compatibility is retained here without making it the canonical installer. Canonical Windows custom-home propagation is separately broken in the installer and remains outside this restart-only change.

**Material assumptions:** The registered task action exposes one quoted VBS argument. An optional nonempty `WorkingDirectory` is authoritative and must exist; an absent value is valid and is omitted from preflight. Both observed VBS forms begin with an installed Python executable: canonical `<python> -m app.run service run --port N` and legacy `<pythonw> <launcher.py>` whose launcher contains `--port N`. A successful import of `app.run` and `app.main` with that interpreter and optional working directory is sufficient pre-stop protection against partial code edits; any third installed shape returns the task to planning.

**Plan:** In `scripts/restart-service.ps1`, keep the small failure helper and VBS/Python resolver, make task `WorkingDirectory` optional while failing closed on a nonempty invalid value, and pass it to `Start-Process` only when present. Run `import app.run, app.main` before the first stop and do not inspect Git dirtiness. Resolve the configured port from the canonical VBS command or legacy Python launcher and use it consistently for kill, PID, readiness, and success output. Sweep canonical `app.run service run` survivors only when their command line carries the exact resolved `--port` value, while preserving legacy cleanup and excluding `app.run mcp`. Keep the fixed 20-attempt readiness loop over the three documented endpoints: require `health.status == "ok"`, `status.embedding_provider_ok == true`, `status.ingestion.status == "ok"`, and queue HTTP 2xx; retry transient/malformed states, then fail with the last named check and `~/.pallium/logs/pallium.log`. Extend `tests/test_restart_service.py` to execute both canonical no-working-directory/module-VBS and legacy working-directory/launcher-VBS shapes at nondefault ports, assert the exact preflight invocation and addressed port, reject invalid nonempty working directories, unparseable interpreters, and missing/invalid ports before stop, prove the matching canonical survivor is killed while a different-port service and MCP bridge are untouched, and keep the Unicode path case. Add the test path to Windows smoke and keep operations/roadmap aligned.

**Verification plan:** Canonical no-working-directory and legacy working-directory tasks at nondefault ports shall both preflight through their installed interpreter and address the installed port → real PS1 harness asserts omitted versus exact `WorkingDirectory` plus kill/probe port; invalid or unparseable installation metadata, port, and replacement import failure shall leave the live process untouched → real PS1 tests assert no stop/kill and nonzero diagnostics; a canonical `app.run service run` survivor on the installed port shall be killed while a different-port service and `app.run mcp` are excluded → mocked CIM/taskkill caller test; start failure shall return nonzero; transient readiness shall probe all three endpoints and print success only after all contracts pass; any endpoint remaining unavailable or malformed shall exhaust deterministically and name the last check/log → Windows-only real-script tests with no-op mocked sleep and the fixed 20-attempt budget; the installed wrapper shall restart the real service and all three endpoints shall satisfy the same contracts → bounded Windows witness; workflow/redline/CI shall pass.

**Plan review:** Clean-context Luna review under `## Plan review`; its Linux-collection, deterministic-budget, and queue-HTTP predicate findings are incorporated.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Established RW-010 from the canonical Relay ledger and preserved the developer's read-only lifecycle trace.
- Pre-edit redline classified the operational paths blue and the Windows smoke workflow gray with no checkpoint; operational process-kill risk keeps the task Elevated.
- Rejected a blanket dirty-checkout gate in favor of validating the exact installed interpreter and code import before stop.
- Slice 1 changes only scripts/restart-service.ps1 and this Implementation log; tests, docs, workflow, and roadmap remain for later slices.
- apply_patch failed with local Windows error 1327; used deterministic exact-block replacement for the two named files.
- The first installed-preflight check exposed a VBScript quote-count mistake in the Python regex; corrected it to the observed triple-open/double-close launcher syntax before commit.
- Implemented installed task/VBS/Python/working-directory validation and import preflight before the unchanged kill sweep, wrapped scheduled-task start failure, and added the fixed 20-attempt readiness gate.
- Verification: PowerShell parser clean; exact installed pythonw import preflight passed; existing MCP-exclusion pytest passed (1 test); git diff --check clean.
- Slice 2 changes only tests/test_restart_service.py plus this Work Record's Implementation and Evidence prose.
- apply_patch again failed with local Windows error 1327; used deterministic writes limited to the new test and this Work Record.
- The first two focused runs were 1 passed/5 failed while refining PowerShell script-scope exit handling; the final harness invokes the real script with the call operator and explicitly exits with `$LASTEXITCODE`, preserving mocks and caller-visible failure.
- Added one Windows-only real-script harness covering preflight/no-stop, start failure, staged readiness success, and exact 20-attempt exhaustion for health, status, and queue.
- Slice 2 verification: test module compiled; six new scenarios plus the existing MCP-exclusion regression passed (7 passed in 3.05s); git diff --check clean. Ruff was unavailable in the venv, so no dependency was installed.
- Slice 3 is limited to the wrapper, its existing real-script harness, and this Work Record's Implementation/Evidence; canonical empty-working-directory compatibility supersedes the legacy-only assumption.
- apply_patch failed with local Windows error 1327; used deterministic exact replacements limited to the three assigned files.
- Made task WorkingDirectory optional for canonical installs while still rejecting an invalid nonempty value; preflight splatting passes the exact legacy directory only when present.
- Added the canonical app.run service run sweep signature and extended the real-script harness for canonical omission, legacy exact directory, invalid directory, unparseable VBS, service survivor kill, and MCP preservation.
- Slice 3 verification: PowerShell parser and installed legacy import preflight passed; compatibility/readiness suite plus existing MCP-exclusion regression passed (11 passed in 5.26s); git diff --check clean.
- Slice 4 is limited to the wrapper, its existing real-script harness, and this Work Record's Implementation/Evidence; docs, workflow, and roadmap are unchanged.
- Resolved the installed port before any stop from canonical VBS `--port N` or the VBS-referenced legacy launcher, rejected missing/nonnumeric/out-of-range values, and reused the validated port for listener cleanup, readiness, and success output.
- apply_patch failed with local Windows error 1327; the Git patch fallback did not parse, so deterministic marker/exact replacements were used only for the three assigned files.
- Slice 4 verification: PowerShell parser and test-module compile passed; custom-port, boundary, failure-safety, readiness, and MCP-exclusion regressions passed (17 passed in 8.26s); git diff --check clean.
- Added a valid Hebrew-and-spaces WorkingDirectory caller-surface case; the wrapper passes the exact Unicode path to Start-Process.
- Added the restart test module to the PR Windows smoke job, documented the preflight/readiness contract, aligned RW-010 for installed verification, and recorded the separate RW-016 custom-home/Unicode installer defect.
- Architect attempts to apply the port and Unicode edits directly were guarded by exact replacements and refused when relaydev began the same shared-worktree edits concurrently; no developer work was overwritten.
- Ran the installed legacy-task wrapper from a clean worktree. It resolved port 19836, stopped the full service tree, restarted through Task Scheduler, waited through cold start, exited 0, and printed the derived dashboard URL.
- Slice 5 is limited to the wrapper, its existing real-script harness, and this Work Record's Implementation/Evidence.
- Removed canonical `app.run service run` from the broad command-line sweep and filtered its candidates by the exact resolved `--port` token with a whitespace/end boundary; legacy service signatures and MCP exclusion remain unchanged.
- apply_patch failed with local Windows error 1327; used deterministic exact replacements limited to the three assigned files.
- Slice 5 verification: PowerShell parser and test-module compile passed; focused restart plus MCP-exclusion regressions passed (18 passed in 9.22s); workflow and diff checks clean.

## Evidence

- The initial `scripts/restart-service.ps1` stopped before code validation and printed success immediately after `Start-ScheduledTask`; the branch now preflights before stop and gates success on all required endpoints.
- Installed task action uses `wscript.exe`, a quoted `~/.pallium/service_launcher.vbs` argument, and `C:\Dev\rore\Pallium` as working directory; the VBS quotes the installed venv `pythonw.exe` and launcher path.
- `docs/context/operations.md` already requires `/health`, `/status`, `/debug/queue/health` plus embedding-provider and ingestion checks.
- Existing `test_windows_service_restart_preserves_codex_mcp_bridge` covers only process signature exclusion.
- `.github/workflows/ci.yml` runs an explicit Windows-sensitive test list and does not auto-collect new restart tests in the PR Windows job.
- `tests/test_restart_service.py` launches the actual wrapper under mocked Windows commands and HTTP responses; `Start-Sleep` only records calls, making 20-attempt failures deterministic.
- Focused verification: `python -m py_compile tests/test_restart_service.py`; pytest new module plus MCP-exclusion regression → 7 passed in 3.05s.
- Revised caller-surface evidence proves canonical empty WorkingDirectory is omitted, legacy WorkingDirectory is passed exactly, invalid/unparseable metadata cannot stop the service, PID 4242 matching app.run service run is killed, and synthetic MCP PID 9999 is untouched.
- Revised focused verification: test module compiled; PowerShell parser clean; installed legacy import-only preflight passed; 11 focused tests passed in 5.26s.
- Port evidence: canonical VBS uses 21987 and legacy launcher metadata uses 21988; both drive `Get-NetTCPConnection`, all three readiness URIs, and the printed dashboard URL.
- Missing, nonnumeric, zero, and 65536 ports fail before stop or process cleanup; boundary ports 1 and 65535 complete successfully.
- Final focused verification before documentation alignment: PowerShell parser clean; test module compiled; 18 focused tests passed in 6.52s; git diff --check clean.
- Clean-context result review approved canonical/legacy shape handling, optional and Unicode working directories, port parsing/boundaries, preflight ordering, survivor cleanup with MCP exclusion, readiness/error behavior, and non-Windows collection. Its sole blocker was adding the new test to Windows smoke; that workflow entry is now present.
- Installed witness after the clean review: wrapper exit 0; `/health.status=ok`; `/status.embedding_provider_ok=true`; `/status.ingestion.status=ok`; `/debug/queue/health` HTTP 200.
- Exact-port survivor evidence uses resolved port 2198: matching canonical PID 4242 is killed, same-signature PID 4343 on valid prefix port 21987 is preserved, and synthetic MCP PID 9999 remains untouched.
- Final exact-port verification: PowerShell parser clean; test module compiled; 18 focused tests passed in 9.22s; git diff --check clean.

## Plan review

The first clean-context Luna review required an explicit non-Windows skip, a fixed deterministic retry budget with mocked sleep, and queue readiness defined as HTTP 2xx. Architect review after slice 1 then disproved the working-directory assumption against the canonical installer. The second clean-context review required optional working-directory handling, exact canonical/legacy preflight assertions, and the missing canonical `app.run service run` sweep signature while preserving MCP exclusion. A final bounded installer audit found the hardcoded-port bug; configured-port derivation and coverage are now included. Canonical Windows custom-home propagation is recorded as a separate installer defect because repairing install metadata would violate this task's restart-only scope. No further restart-wrapper correctness or over-engineering blocker remains.

## Result review

CodeRabbit found two valid post-review blockers: stale roadmap ordering and a broad canonical `app.run service run` sweep that could kill another local service on a different port. The roadmap now points directly to RW-016, and canonical cleanup requires the exact resolved `--port` token. The real-script regression kills the matching PID while preserving a prefix/different-port service and MCP bridge. PowerShell parsing, 44 focused tests, workflow, and diff checks pass; final clean-context review found no code blocker and required only these state/order corrections. Ready for renewed PR review and CI.
