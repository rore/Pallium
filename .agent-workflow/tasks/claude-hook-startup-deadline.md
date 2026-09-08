<!-- agent-workflow:start -->
**Outcome:** Claude UserPromptSubmit no longer discards Pallium output when normal cold or contended Python startup consumes part of the host hook window.

**Target:** Pallium Claude Code integration.

**Scope:** Claude hook timeout registration and reconciliation, focused regression coverage, and Relay roadmap evidence.

**Constraints:** Normal hook work remains bounded to its existing seven-second safe budget; fail-open behavior, Relay ACK ordering, public APIs, and other hook timeouts remain unchanged; tests add no wall-clock sleep.

**Completion criteria:** Existing installed UserPromptSubmit entries migrate from the unsafe eight-second host timeout to a 12-second outer window, leaving five seconds of total outer slack beyond the unchanged seven-second active-work budget; repeated setup stays idempotent and focused/full verification passes.

**Risk:** Elevated

**Complexity:** Simple

**Reason:** Redline classified the Claude integration and setup paths gray, with app/** watch; no boundary, API, schema, security, or persistence checkpoint applies. The change is one coherent setup contract correction.

**Discovery:** The installed global Claude settings point at current main, not a stale checkout. Claude starts its eight-second host timer before Python startup/imports, but user_prompt_submit starts its internal 8s budget with 1s reserve only after imports, so the intended reserve does not cover startup. The prior deadline suite asserts deadline-before-input but not process-startup margin. Setup also leaves an existing managed hook's timeout unchanged, so changing the default alone would not update local installs.

**Material assumptions:** Five seconds of total outer slack is sufficient for normal Python startup/import and host/transport overhead on supported platforms; evidence disproving this is a caller-surface timeout while active hook work remains within seven seconds, which would require measuring startup and revisiting the fixed outer window. Claude honors the registered numeric timeout per managed command; a host contract change would require setup compatibility work.

**Plan:** Keep the hook's existing active-work deadline. Increase only Claude UserPromptSubmit's outer host timeout to 12 seconds. Reconcile every exact managed command after normalizing path separators, updating only its timeout while preserving entry/hook fields, unrelated and malformed hooks, and any pre-existing exact duplicates; never add another managed entry when one exists. Add deterministic fast tests proving five seconds of total slack, migration, preservation, duplicate policy, and idempotence. Record the incident in the Relay wake roadmap. Target files: app/cli/setup_claude_code.py, tests/test_claude_code_integration.py, tests/test_hook_deadline_safety.py, roadmap/features/add-wake-first-relay-delivery.md. Stop if reconciliation would alter non-Pallium hooks or if tests show active work can exceed seven seconds.

**Verification plan:** When setup sees current eight-second Pallium UserPromptSubmit entries, including Windows separators and mixed/malformed neighbors, it shall update only exact managed entries to 12 seconds without adding one -> focused setup regression with repeated registration and duplicate policy. When the entrypoint advertises its current internal budget, the installed outer window shall preserve five seconds of total outer slack -> deterministic deadline contract test. Existing hook safety and Claude integration behavior remain intact -> affected test files, then full suite once before review.

**Plan review:** Clean-context review `/root/claude_deadline_plan_review`; approved after correcting slack wording and exact managed-command reconciliation coverage.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Plan review

- Initial review rejected guaranteed-margin wording and substring/shape-unsafe reconciliation.
- Revised plan uses a 12-second outer window with five seconds total slack beyond the unchanged seven-second active budget; exact normalized matching updates only managed timeout values and covers mixed, malformed, unrelated, duplicate, and repeated setup cases. Re-review approved with no blockers.

## Implementation

- Context/discovery complete. Clean-context plan review approved the revised 12-second outer-window and exact reconciliation plan.
- Regression-first implementation: both new tests failed before the fix (`8 - 7 == 1`, and existing timeouts remained 8/7), then passed after changing only setup registration/reconciliation. The hook runtime and seven-second active budget were not changed.
- RW-023 records the installed dogfood incident and correction.

## Evidence

- Installed `C:\Users\I347041\.claude\settings.json` uses the current checkout and an eight-second UserPromptSubmit timeout.
- Redline review `/root/claude_deadline_redline`: gray integration/setup paths, blue tests/docs, no boundary or mandatory checkpoint.

## Result review

- Pending.
