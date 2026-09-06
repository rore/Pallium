<!-- agent-workflow:start -->
**Outcome:** Restarting the installed Windows Pallium service leaves a healthy existing process untouched when the registered replacement cannot import, and reports success only after all required readiness signals pass.

**Target:** Pallium Windows service restart workflow.

**Scope:** `scripts/restart-service.ps1`, its real PowerShell caller-surface regressions, Windows operations guidance, the Relay RW-010 ledger, and this Work Record.

**Constraints:** Preserve the stale process-tree sweep and exclusion of client-owned `app.run mcp` bridges; support both observed Windows task shapes from `pallium service install` and the legacy helper; use the exact installed interpreter and an installed working directory only when one exists; allow valid dirty checkouts; no wall-clock waits in tests; no changes to Unix wrappers, service installation format, service runtime code, or public APIs.

**Completion criteria:** Import/preflight failure occurs before any stop or kill and exits nonzero with actionable diagnostics; successful restart polls `/health`, `/status`, and `/debug/queue/health` until health is `ok`, embeddings and ingestion are healthy, and queue HTTP succeeds; start failure or bounded readiness exhaustion exits nonzero without printing success; deterministic real-script tests prove each path.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Redline classifies the script/test/docs/roadmap/record paths blue and `.github/workflows/ci.yml` gray with no checkpoint, but engineering judgment raises risk because the wrapper force-kills a live service and a false success can strand all integrations. Moderate complexity comes from installed-task/VBS interpreter discovery, two supported Windows task shapes, and deterministic execution of the real PowerShell script.

**Discovery:** The wrapper originally stopped and swept the live process tree before validating disk code, then started the fire-and-forget scheduled task and printed success without probing. The task action supplies the authoritative VBS path; the VBS supplies the authoritative Python executable. The current local legacy task also supplies a repo working directory and Python launcher, while canonical `app/cli/service.py::_install_windows` deliberately omits `WorkingDirectory` and invokes `python -m app.run service run` from its VBS. The original slice rejected that canonical installation and the unchanged sweep omitted its `app.run service run` process signature. A blanket dirty-checkout rejection is broader than the failure and would block valid development restarts, so importability—not Git cleanliness—is the safety gate. The PR Windows smoke job names tests explicitly, so the new restart regression must be added to that list or it will not exercise native Windows on PRs. The deprecated `scripts/install-service.ps1` still writes a legacy `run(["all"])` launcher; compatibility is retained here without making it the canonical installer.

**Material assumptions:** The registered task action exposes one quoted VBS argument. An optional nonempty `WorkingDirectory` is authoritative and must exist; an absent value is valid and is omitted from preflight. Both observed VBS forms begin with an installed Python executable: canonical `<python> -m app.run service run` and legacy `<pythonw> <launcher.py>`. A successful import of `app.run` and `app.main` with that interpreter and optional working directory is sufficient pre-stop protection against partial code edits; any third installed shape returns the task to planning.

**Plan:** In `scripts/restart-service.ps1`, keep the small failure helper and VBS/Python resolver, make task `WorkingDirectory` optional while failing closed on a nonempty invalid value, and pass it to `Start-Process` only when present. Run `import app.run, app.main` before the first stop and do not inspect Git dirtiness. Add the exact canonical `app.run service run` survivor signature while preserving legacy cleanup and excluding `app.run mcp`. Keep the fixed 20-attempt readiness loop over the three documented endpoints: require `health.status == "ok"`, `status.embedding_provider_ok == true`, `status.ingestion.status == "ok"`, and queue HTTP 2xx; retry transient/malformed states, then fail with the last named check and `~/.pallium/logs/pallium.log`. Extend `tests/test_restart_service.py` to execute both canonical no-working-directory/module-VBS and legacy working-directory/launcher-VBS shapes, assert the exact preflight invocation, reject invalid nonempty working directories and unparseable interpreters before stop, and prove the canonical survivor is killed while an MCP bridge is untouched. Add only that test path to `.github/workflows/ci.yml`'s existing Windows smoke list. Update operations guidance and RW-010.

**Verification plan:** Canonical no-working-directory and legacy working-directory tasks shall both preflight through their installed interpreter → real PS1 harness asserts omitted versus exact `WorkingDirectory`; invalid or unparseable installation metadata and replacement import failure shall leave the live process untouched → real PS1 tests assert no stop/kill and nonzero diagnostics; a canonical `app.run service run` survivor shall be killed while `app.run mcp` is excluded → mocked CIM/taskkill caller test; start failure shall return nonzero; transient readiness shall probe all three endpoints and print success only after all contracts pass; any endpoint remaining unavailable or malformed shall exhaust deterministically and name the last check/log → Windows-only real-script tests with no-op mocked sleep and the fixed 20-attempt budget; the installed wrapper shall restart the real service and all three endpoints shall satisfy the same contracts → bounded Windows witness; workflow/redline/CI shall pass.

**Plan review:** Clean-context Luna review under `## Plan review`; its Linux-collection, deterministic-budget, and queue-HTTP predicate findings are incorporated.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready to implement
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

## Evidence

- Current `scripts/restart-service.ps1` stops before any code validation and prints success immediately after `Start-ScheduledTask`.
- Installed task action uses `wscript.exe`, a quoted `~/.pallium/service_launcher.vbs` argument, and `C:\Dev\rore\Pallium` as working directory; the VBS quotes the installed venv `pythonw.exe` and launcher path.
- `docs/context/operations.md` already requires `/health`, `/status`, `/debug/queue/health` plus embedding-provider and ingestion checks.
- Existing `test_windows_service_restart_preserves_codex_mcp_bridge` covers only process signature exclusion.
- `.github/workflows/ci.yml` runs an explicit Windows-sensitive test list and does not auto-collect new restart tests in the PR Windows job.
- `tests/test_restart_service.py` launches the actual wrapper under mocked Windows commands and HTTP responses; `Start-Sleep` only records calls, making 20-attempt failures deterministic.
- Focused verification: `python -m py_compile tests/test_restart_service.py`; pytest new module plus MCP-exclusion regression → 7 passed in 3.05s.

## Plan review

The first clean-context Luna review required an explicit non-Windows skip, a fixed deterministic retry budget with mocked sleep, and queue readiness defined as HTTP 2xx. Architect review after slice 1 then disproved the working-directory assumption against the canonical installer. A second clean-context review requires optional working-directory handling, exact canonical/legacy preflight assertions, and the missing canonical `app.run service run` sweep signature while preserving MCP exclusion. The revised Plan incorporates every finding; no further correctness or over-engineering blocker remains.

## Result review

Pending.
