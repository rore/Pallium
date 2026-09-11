<!-- agent-workflow:start -->
**Outcome:** Codex setup converges to one stable Pallium integration across checkout moves without recurring duplicate hooks or unnecessary trust churn.

**Target:** Pallium Codex integration installer.

**Scope:** `app/cli/setup_codex.py`, focused Codex integration tests, integration/operations documentation, and verification of the user-local migration to `Pallium-installed`.

**Constraints:** Preserve unrelated hooks and wrapper fields/order; never read, synthesize, delete, or bypass Codex-owned `hooks.state` trust hashes; keep absolute-path setup compatibility and uninstall behavior.

**Completion criteria:** Cross-checkout setup removes stale Pallium registrations, leaves exactly one current hook per event, preserves peer hooks, is idempotent on repeat setup, documents the new migration behavior, and the local Codex MCP/hooks resolve only to `Pallium-installed`.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** `app/cli/setup_codex.py` is a gray/watch runtime-installation surface. The change is behaviorally narrow but affects shared setup/uninstall semantics and Codex hook trust continuity across checkout migrations.

**Discovery:** Local evidence showed three `Pallium-installed` hooks plus three stale development-checkout hooks, while the MCP server still used the development checkout. The documented old-checkout uninstall followed by stable-checkout setup repaired local state. Code inspection found `_unregister_hooks()` matches only the current absolute `_hooks_dir()`, so setup from another checkout cannot remove stale registrations. Existing tests cover same-checkout stale quoting and preservation of Codex-owned TOML trust state, but not cross-checkout cleanup, mixed wrappers, or position-preserving repeat setup. A clean-context redline audit found no boundary risk or required checkpoint and recommended Elevated/Moderate by engineering judgment.

**Material assumptions:** Pallium-managed Codex hooks can be identified narrowly by the known script names under `/integrations/codex/hooks/`; a third-party command using that exact directory suffix and filename would disprove this and require a stronger ownership marker. Preserving an already-current hook in place avoids trust churn; if Codex keys trust differently than the visible config location/event/index and definition hash suggest, rely only on semantic idempotence and retain the explicit approval prompt.

**Plan:** First, invoke agent-workflow and classify risk before code edits (completed). Parse only the complete supported direct-Python command shape and recognize exact known scripts under `/integrations/codex/hooks/`; reject shell composition, extra arguments, suffix lookalikes, and commands that merely mention a hook path. Reconcile each event hook-by-hook so the first exact current definition plus effective matcher stays in place, stale/duplicate Pallium hooks are removed even inside mixed wrappers, peer fields/order are preserved, and a required wrapper is appended only when no exact current registration remains. Keep uninstall as generic removal of all recognized Pallium hooks across checkout paths. Add focused ownership/matcher/mixed-wrapper tests plus a public install -> cross-checkout migrate -> repeat install -> third-checkout uninstall -> repeat uninstall lifecycle test that reads JSON/TOML and preserves Codex-owned trust state. Update Codex-specific docs while retaining old-checkout uninstall requirements for Claude and explicit restart/review guidance for changed commands. Stop and re-plan if ownership cannot be identified without matching arbitrary third-party commands or if the change requires modifying Codex trust state.

**Verification plan:** When setup moves between checkouts, exactly one current hook per event remains and peers are unchanged -> focused cross-checkout tests. When setup repeats from the same checkout, hook JSON ordering/content remains stable -> idempotence test. When uninstall runs from a different checkout, all recognized Pallium hooks are removed while mixed-wrapper peers remain -> focused uninstall tests. Codex-owned trust state remains untouched -> existing/extended install test. All affected integration behavior remains green -> `python -m pytest tests/test_codex_integration.py -q -n 0`, workflow/redline checks, then full repository suite before PR.

**Plan review:** Clean-context review `/root/codex_hook_plan_review`; initial REQUEST_CHANGES addressed in the revised plan and recorded below.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Established isolated branch `fix/codex-hook-install-idempotence` from `origin/main` at `61452da7`.
- Repaired the user-local configuration through the documented old-checkout uninstall and stable-checkout setup sequence; backup: `C:\Users\I347041\AppData\Local\Temp\pallium-codex-config-20260911-161216`.
- Verified local hooks now contain one Pallium command per event and the MCP command/PYTHONPATH point only to `C:\Dev\rore\Pallium-installed`.
- Implemented exact direct-Python Pallium hook ownership detection, cross-checkout reconciliation, mixed-wrapper peer preservation, and generic cross-checkout uninstall.
- Preserved an exact current hook in place and skipped rewriting `hooks.json` when setup is semantically unchanged; setup now reports changed versus unchanged approval state.
- Added caller-facing setup lifecycle and parser/matcher/mixed-wrapper regression coverage; corrected two implementation gaps exposed by the delegated test pass.
- Updated Codex migration documentation while retaining Claude Code's path-specific uninstall requirement.
- `apply_patch` failed once with the known Windows sandbox error 1327; all subsequent edits used deterministic replacements limited to the named files.
- Addressed final-review blockers with shell-aware exact two-token parsing, safe quoting for generated special-character paths, preservation of untouched empty peer wrappers, and the reviewer's three false-positive probes.
- Addressed the second review with Windows quoting for apostrophes and explicit CR/LF rejection; the lifecycle fixture now uses a checkout path containing both & and an apostrophe.

## Evidence

- Pre-edit clean-context audit `/root/codex_hook_installer_audit`: gray/watch installer surface, no boundary risk, Elevated/Moderate recommended; root cause is current-checkout-only removal.
- Focused regression suite after implementation: `32 passed` in `tests/test_codex_integration.py`; includes real `app.run` setup dispatch lifecycle.
- Full repository suite: `4846 passed, 33 skipped, 2 xfailed in 186.31s`, exit 0.
- Python compilation and `git diff --check`: passed.
- Import-boundary report, redline verdict, and agent-workflow gate: clean; detected/declared Elevated, no boundary violations or checkpoints.
- `ruff` was unavailable in the development environment; modified Python sections were manually formatted and syntax/test verified.
- Final reviewer `/root/codex_hook_plan_review` returned REQUEST_CHANGES: permissive path parsing could delete unrelated extra-argument commands, generated `R&D` paths escaped reconciliation, and untouched empty peer wrappers were dropped. Returned to implementation; prior full-suite result remains evidence for the earlier revision only.
- Corrected revision: focused suite `32 passed`; full suite `4846 passed, 33 skipped, 2 xfailed in 186.25s`, exit 0. Reviewer-provided false-positive commands and `R&D`/empty-wrapper cases are covered.
- Second result review confirmed the earlier blockers fixed and requested two edge corrections: quote apostrophes in generated Windows paths and reject CR/LF command separators. Returned to implementation; the latest full-suite evidence applies to the prior revision.
- Final corrected revision: focused Codex integration suite 32 passed in 3.58s; full repository suite 4846 passed, 33 skipped, 2 xfailed in 207.27s; Python compilation and git diff --check passed.

## Plan review

Clean-context reviewer `/root/codex_hook_plan_review` requested four corrections: require the complete direct-Python command shape rather than substring ownership; include effective wrapper matcher in exact-current identity; add public lifecycle coverage instead of helper-only tests; and relax migration documentation only for Codex because Claude removal remains path-specific. The plan now includes all four. No boundary or policy checkpoint is required.

## Result review

Clean-context reviewer /root/codex_hook_plan_review returned MERGEABLE_FOR_PR on the final diff after confirming the apostrophe quoting and CR/LF rejection corrections. No roadmap status changed; this is a narrow installer correctness fix and the integration/operations docs are aligned.
