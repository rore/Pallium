<!-- agent-workflow:start -->
**Outcome:** Restarting the installed Windows Pallium service leaves a healthy existing process untouched when the registered replacement cannot import, and reports success only after all required readiness signals pass.

**Target:** Pallium Windows service restart workflow.

**Scope:** `scripts/restart-service.ps1`, its real PowerShell caller-surface regressions, Windows operations guidance, the Relay RW-010 ledger, and this Work Record.

**Constraints:** Preserve the full stale process-tree sweep and exclusion of client-owned `app.run mcp` bridges; use the exact installed task interpreter and working directory; allow valid dirty checkouts; no wall-clock waits in tests; no changes to Unix wrappers, service installation format, service runtime code, or public APIs.

**Completion criteria:** Import/preflight failure occurs before any stop or kill and exits nonzero with actionable diagnostics; successful restart polls `/health`, `/status`, and `/debug/queue/health` until health is `ok`, embeddings and ingestion are healthy, and queue HTTP succeeds; start failure or bounded readiness exhaustion exits nonzero without printing success; deterministic real-script tests prove each path.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Redline classifies the script/test/docs/roadmap/record paths blue and `.github/workflows/ci.yml` gray with no checkpoint, but engineering judgment raises risk because the wrapper force-kills a live service and a false success can strand all integrations. Moderate complexity comes from installed-task/VBS interpreter discovery plus deterministic cross-platform execution of the real PowerShell script.

**Discovery:** The wrapper currently stops and sweeps the live process tree before validating disk code, then starts the fire-and-forget scheduled task and prints success without probing. The task action supplies the authoritative working directory and VBS path; the VBS supplies the authoritative Python executable. A blanket dirty-checkout rejection is broader than the failure and would block valid development restarts, so importability—not Git cleanliness—is the safety gate. Existing tests only assert that MCP bridges are excluded. The PR Windows smoke job names tests explicitly, so the new restart regression must be added to that list or it will not exercise native Windows on PRs. `install-service.ps1` still writes a legacy `run([\"all\"])` launcher despite operations guidance requiring `service run`; that separate installer drift is not needed to close RW-010.

**Material assumptions:** The registered task action exposes one VBS argument and working directory, and the VBS retains the installed `WshShell.Run \"\"\"<python>\"\" \"\"<launcher>\"\"\"` shape. Disproof: installed or CI fixtures use another action/launcher shape. Action if disproved: stop and either add a backward-compatible resolver grounded in observed installed shapes or move installer metadata alignment into scope with a revised plan. A successful import of `app.run` and `app.main` with the installed interpreter is sufficient pre-stop protection against partial code edits; a live witness that passes import but fails deterministically before scheduled-task admission returns the task to planning.

**Plan:** In `scripts/restart-service.ps1`, add one small failure helper, resolve and validate the installed task action/VBS/Python/working directory, and run `import app.run, app.main` through `Start-Process` before the first stop. Do not inspect Git dirtiness. Preserve the existing kill sweep unchanged. Wrap scheduled-task start with actionable failure. Replace unconditional success with a bounded probe loop over the three documented endpoints: require `health.status == \"ok\"`, `status.embedding_provider_ok == true`, `status.ingestion.status == \"ok\"`, and successful queue response; retry transient/malformed states, then fail with the last named check and `~/.pallium/logs/pallium.log`. Add `tests/test_restart_service.py` that executes the real PS1 beneath mocked Windows commands and time, covering preflight failure/no stop, start failure, transient recovery/all three probes, and each terminal readiness failure; add only that test path to `.github/workflows/ci.yml`'s existing Windows smoke list. Update operations guidance and RW-010. Stop if real PowerShell command shadowing cannot exercise the script in CI without sleeps, or installed task/VBS shape differs from the recorded assumption.

**Verification plan:** When replacement imports fail, the live process shall remain untouched → real PS1 subprocess test asserts no stop/kill and nonzero diagnostics; when start fails, the wrapper shall return nonzero → mocked scheduled-task caller test; when readiness is transient, the wrapper shall probe all three endpoints and print success only after all contracts pass → ordered real-script test; when any endpoint remains unavailable or malformed, the wrapper shall exhaust deterministically and name the last check/log → parameterized real-script tests with mocked sleep; when merged locally, the installed wrapper shall restart the real service and all three endpoints shall satisfy the same contracts → bounded Windows witness; workflow/redline/CI shall pass.

**Plan review:** Pending clean-context review under `## Plan review`.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Blocked or returned to planning
<!-- agent-workflow:end -->

## Implementation

- Established RW-010 from the canonical Relay ledger and preserved the developer's read-only lifecycle trace.
- Pre-edit redline classified the operational paths blue and the Windows smoke workflow gray with no checkpoint; operational process-kill risk keeps the task Elevated.
- Rejected a blanket dirty-checkout gate in favor of validating the exact installed interpreter and code import before stop.

## Evidence

- Current `scripts/restart-service.ps1` stops before any code validation and prints success immediately after `Start-ScheduledTask`.
- Installed task action uses `wscript.exe`, a quoted `~/.pallium/service_launcher.vbs` argument, and `C:\Dev\rore\Pallium` as working directory; the VBS quotes the installed venv `pythonw.exe` and launcher path.
- `docs/context/operations.md` already requires `/health`, `/status`, `/debug/queue/health` plus embedding-provider and ingestion checks.
- Existing `test_windows_service_restart_preserves_codex_mcp_bridge` covers only process signature exclusion.
- `.github/workflows/ci.yml` runs an explicit Windows-sensitive test list and does not auto-collect new restart tests in the PR Windows job.

## Plan review

Pending.

## Result review

Pending.
