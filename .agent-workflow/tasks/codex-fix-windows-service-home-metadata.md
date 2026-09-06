<!-- agent-workflow:start -->
**Outcome:** A canonical Windows Pallium service always starts, stops, restarts, logs, and diagnoses against the exact home selected at install time, including paths with spaces and non-ASCII characters.

**Target:** Windows service launcher metadata, the required restart wrapper, deterministic service caller-surface tests, the Relay roadmap, and this Work Record.

**Scope:** `app/cli/service.py`, `scripts/restart-service.ps1`, `tests/test_service.py`, `tests/test_restart_service.py`, `roadmap/features/add-wake-first-relay-delivery.md`, and this Work Record.

**Constraints:** Preserve the canonical scheduled-task and legacy launcher shapes, installed port discovery, preflight-before-stop safety, process-tree cleanup, all three readiness checks, default-home behavior, and Linux systemd behavior. Use Windows-native Unicode script encoding, add no dependency, perform no real service install in the normal test suite, and add no wall-clock sleep.

**Completion criteria:** `pallium service install --home <custom>` writes a Unicode-safe Windows launcher whose `service run` command carries the exact resolved home; default, custom, spaces, and Unicode homes and interpreter paths round-trip through the caller surface; restart resolves canonical PID/log paths from installed metadata while legacy default-home tasks remain compatible; malformed metadata still fails before stopping; focused Windows/service tests, workflow/redline checks, clean-context result review, PR CI, installed service restart, and health/status/queue verification pass; roadmap RW-016 is marked complete only after evidence.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** `app/cli/service.py` is a guarded runtime/watch path and the change affects Windows service startup and restart operations. Scripts, tests, roadmap, and workflow metadata are blue; no red API, persistence, security, runtime-config, or architecture checkpoint is triggered.

**Discovery:** `_cmd_install` resolves and applies the selected home, but `_install_windows` emits `python -m app.run service run --port N` without `--home`, so a later scheduled-task process falls back to its default environment. The same function writes the VBS launcher as ASCII. `scripts/restart-service.ps1` already reads the scheduled-task action and launcher but hardcodes default-home log and PID paths. The Linux unit already carries `Environment=PALLIUM_HOME=<home>` and needs no change.

**Material assumptions:** Windows Script Host accepts Python's BOM-marked UTF-16 launcher output; disprove with focused Windows execution or CI and return encoding choice to planning. Canonical launchers persist one exact quoted `--home` value; disprove if Windows command-line parsing changes it, then return quoting to planning. Windows paths cannot contain a literal quote, so standard command-line quoting round-trips valid interpreter and home paths; disprove with a valid Windows counterexample and add only the necessary escaping.

**Plan:** Add the quoted exact home to the shared canonical Windows VBS command and write that file as UTF-16. In the restart wrapper, parse canonical service home from its exact launcher argument before diagnostics and use it for log/PID files, require it before stopping a canonical service, and retain the default-home fallback only for the legacy `service_launcher.vbs` shape. Extend the existing real PowerShell harness to expose PID/log reads and add a compact CLI/install lifecycle test that decodes the generated launcher and drives its `service run` arguments far enough to prove exact-home state paths. Preserve existing port regex behavior and Linux installer output. Update the roadmap after verification. Stop and return to planning if Windows Script Host encoding, canonical placement, or legacy compatibility fails.

**Verification plan:** Windows install caller surface with default/custom/space/Unicode home and Unicode interpreter -> generated UTF-16 launcher decodes, contains exact quoted `--home`, registered task points to it, and no slow health wait occurs; launcher command -> parsed `service run` arguments write PID/port/log state under the selected home rather than default; restart real-script harness -> custom/space/Unicode canonical task uses installed-home PID/log paths, legacy task still uses default home, invalid metadata stops nothing, exact installed port and readiness contracts remain; Linux -> existing unit text remains byte-for-byte behaviorally unchanged; gates -> focused pytest, workflow/redline, diff check, clean-context result review, PR CI, then installed wrapper restart and `/health`, `/status`, `/debug/queue/health` verification.

**Plan review:** Approved by clean-context Luna reviewer `/root/rw016_plan_review` on 2026-09-06. It confirmed the omission, ASCII encoding, and hardcoded restart paths as the three root causes; recommended quoted exact `--home`, UTF-16 with BOM, canonical installed-home derivation with legacy fallback, and deterministic caller-surface tests. No red checkpoint applies.

**Approvals:** Approved by user 2026-09-06: "you have approval for all prs you manage"

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Added exact quoted `--home` to the canonical Windows launcher and changed its VBS encoding from ASCII to BOM-marked UTF-16.
- Restart now reads canonical home metadata for diagnostics and PID cleanup, preserves literal percent signs, rejects missing canonical home before stop, and retains the recognized legacy default-home path.
- Added CLI install/run lifecycle coverage plus real-PowerShell restart coverage. `apply_patch` later failed with the documented Windows error 1327, so test and documentation updates used narrow deterministic replacements limited to the named files.

## Evidence

- Focused `tests/test_service.py tests/test_restart_service.py`: 52 passed in 7.06s; no real sleeps.
- Exact CI Windows smoke selection: 291 passed, 6 skipped in 14.18s.
- Python compilation and `git diff --check` pass; workflow/redline gate is clean with detected and declared Elevated risk and no review checkpoint.
- Local `cscript.exe` executed a BOM-marked UTF-16 VBS and exited 0. Installed-service reinstall, wrapper restart, endpoint qualification, PR CI, and merge remain pending.

## Plan review

Clean-context read-only review completed before implementation; no blocker remains.

## Result review

Clean-context Luna review found one safety blocker: canonical metadata without `--home` could fall back to the default and stop the wrong service. The implementation now rejects that shape before `Stop-ScheduledTask` and a real-script regression proves no stop/process kill. Roadmap and Work Record state were aligned. The clean-context re-review approved the amended implementation with no remaining correctness blocker; installed qualification remains pending.
