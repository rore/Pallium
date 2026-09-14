<!-- agent-workflow:start -->
**Outcome:** Running Codex setup from another live Pallium checkout cannot silently replace an existing working hook installation and force unexpected hook reapproval.

**Target:** Pallium.

**Scope:** Codex integration setup preflight, focused setup/readiness tests, integration/operations documentation, and roadmap alignment. Live delivery witnesses remain read-only acceptance evidence, not implementation scope.

**Constraints:** Do not mutate the earlier 24-delivery split-endpoint incident; do not expose claim tokens or private payloads; keep public Relay contracts and persistence schema unchanged; use the stable installed checkout for live integrations.

**Completion criteria:** A synthetic reproduction fails before and passes after the smallest root-cause fix; local Codex hooks point to and execute from the stable installation; focused and full verification pass; CI, review, merge, installation sync, service health, and architect notification complete.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** `app/cli/setup_codex.py` is gray/watch under agent-redline and changes installation behavior across live checkouts. No red contract, schema, security, runtime-config policy path, or boundary change is intended.

**Discovery:** The three named deliveries were pending with attempts=0 while Codex hooks pointed at the development checkout. Both old executable/script paths existed, so this was not path-not-found; changing absolute hook commands invalidated Codex-owned approval/reload. `hooks.json` was repointed to `Pallium-installed` at 2026-09-14T13:07:59Z, after which the deliveries were claimed and delivered at 13:08:42Z and 13:10:27Z. Current readiness is verified and this task's hook injects successfully. Code inspection confirms setup intentionally replaces recognized hooks across checkout paths and marks changed definitions `review_required`; accepted wake reservations deliberately remain until a hook turn because Codex queue submission is not idempotent. Existing tests prove deliberate cross-checkout convergence but do not distinguish it from accidental replacement of a still-live installation.

**Material assumptions:** A different recognized Pallium checkout with live hook commands represents an existing installation and must not be replaced without explicit operator intent; a missing old executable/script disproves the live-install case and should remain automatically repairable. Codex queue acceptance is not payload admission, so accepted reservations remain single-shot and are not retried blindly.

**Plan:** In `app/cli/setup_codex.py`, reuse one exact direct-Python command parser for ownership and reconciliation. Before any config/readiness write, inspect every recognized hook across all events. Resolve bare executables with `shutil.which`; inspect absolute executables and scripts with native path semantics; confirmed missing executable or script is repairable, while permission/inspection uncertainty blocks safely. Any live recognized hook from a different checkout, including partial or mixed current/foreign installs, returns a bounded nonzero error without changing config, hooks, Relay profile, AGENTS, skill tree, or readiness unless `--replace-existing-checkout` is explicitly supplied. Preserve same-checkout idempotence, automatic repair of confirmed broken old sources, explicit uninstall, and deliberate cross-checkout reconciliation behind the flag. Extend `tests/test_codex_integration.py` with synthetic public CLI lifecycle and bounded parser/preflight matrices covering partial/mixed hooks, missing script/executable, bare Python, and spaces/Unicode. Align `docs/codex-integration.md`, `docs/context/operations.md`, and roadmap. Do not change activation retry semantics or public HTTP/MCP/persistence contracts. Stop and re-plan if exact ownership cannot be determined safely.

**Verification plan:** When setup is accidentally run from another live checkout, existing hooks/MCP/readiness remain byte-for-byte unchanged and setup fails with explicit migration guidance -> synthetic CLI lifecycle test. When migration is explicitly authorized or the old source is missing, setup converges to one current hook set and readiness changes only when definitions change -> focused lifecycle tests. Hook execution after deliberate migration verifies the new definition -> real hook entrypoint test. Run `tests/test_codex_integration.py`, affected Relay/wake/readiness tests, workflow/redline checks, full suite, CI, installed checkout sync, supported service restart, and all three health endpoints.

**Plan review:** Clean-context review `/root/relay_hook_plan_review`; initial REQUEST_CHANGES addressed, re-review APPROVE.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Established task context and isolated branch before code inspection. Workflow applicability requires the normal Work Record path.
- Preserved the live incident read-only. The three original deliveries self-recovered only after hooks returned to `Pallium-installed`; a newer witness to this already-running task remains pending because it was sent after the current hook boundary and will be checked on the next natural turn.
- `apply_patch` failed with Windows process error 1327; subsequent Work Record edits use the repository-approved deterministic replacement fallback.
- Clean-context plan re-review approved the narrowed setup guard; State advanced to Ready to implement.
- Implemented pre-write detection of recognized hooks owned by another live checkout, safe missing/uncertain path handling, and explicit `--replace-existing-checkout` migration.
- Added synthetic CLI lifecycle and partial/mixed/broken/bare-Python/Unicode edge coverage; aligned Codex, operations, and Relay roadmap documentation.
- Focused Codex integration file passed: 49 tests. One existing Windows temp-directory rename flaked once, then passed alone and on full-file rerun.
- Affected suites passed: Codex integration 49, Codex wake 70, integration readiness 2, Relay hooks 54.
- Import-boundary report and agent-workflow/redline gate passed with GRAY/Elevated, no boundary violation or checkpoint.
- Full repository suite passed after result-review correction: 4989 passed, 34 skipped, 2 xfailed in 217.61s. State remains Ready for review after approval.

## Evidence

- Architect incident report delivered through Relay on 2026-09-14.
- Local incident timeline: hooks corrected at 13:07:59Z; named deliveries claimed/delivered at 13:08:42Z and 13:10:27Z.
- Verification commands and counts are recorded under Implementation; fresh redline verdict is `build/redline-verdict.json`.

## Result review

- Clean-context reviewer `/root/relay_hook_result_review` found one P2: unresolved bare executable lookup was treated as confirmed missing and could fail open. Fixed by preserving `unknown`; the public CLI regression proves return 2 and byte-for-byte unchanged state, while a confirmed missing script remains repairable. Focused Codex integration tests passed 49/49. Re-review: APPROVE — NO FINDINGS, MERGEABLE_FOR_PR.


## Plan review

Clean-context reviewer /root/relay_hook_plan_review classified the intended paths GRAY/Elevated, Moderate, with no boundary/API/schema/security/runtime-config flag or required redline checkpoint. It requested explicit partial/mixed/uncertain ownership behavior and a narrower installation-protection outcome; both are incorporated above. Re-review approved the revised plan with no remaining findings.



