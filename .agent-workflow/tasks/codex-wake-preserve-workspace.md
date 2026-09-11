# Preserve Codex task workspace during Relay wake

<!-- agent-workflow:start -->
**Outcome:**
Codex Relay wake never changes an addressed task's workspace or scope merely because the Pallium service runs from another checkout.

**Target:**
Pallium Codex Relay wake adapter.

**Scope:**
`app/codex_wake.py`, focused caller-surface coverage in `tests/test_codex_wake.py`, current qualification in `docs/codex-integration.md` and `docs/agent-relay.md`, wake roadmap status and incident evidence in `roadmap/features/add-wake-first-relay-delivery.md`, and this Work Record.

**Constraints:**
Preserve exact-session routing, pending-until-hook-admission, single-flight deduplication, hidden process launch, and fail-closed sender scope. Do not add cross-scope fallback, read or write private Codex state, add dependencies, or launch a Codex subprocess from the service cwd.

**Completion criteria:**
1. Every wake uses the already-qualified native exact-thread queue from a vetted neutral Codex directory, never `codex exec resume` from the service checkout.
2. Loaded idle and busy tasks retain prompt wake plus the existing pending-until-hook-admission semantics.
3. Unloaded tasks retain the durable exact-thread queued message for their next supported resume; current docs and roadmap no longer claim unattended cold resume.
4. The HTTP send-to-wake lifecycle and focused edge cases pass, followed by the repository regression suite and deployed Windows service health checks.

**Risk:**
Elevated

**Complexity:**
Moderate

**Reason:**
Redline classifies `app/codex_wake.py` as gray/watch runtime code, mapping to Elevated risk; tests, docs, roadmap, and the Work Record are blue. Complexity is Moderate because the fix changes Codex wake qualification while preserving loaded-task wake, durable unloaded-task delivery, admission semantics, and installed-service behavior.

**Discovery:**
`app/codex_wake.py::_launch` invokes `codex exec ... resume` and its queue fallback without `cwd`, so both inherit the installed service checkout. The incident log shows Codex applied that inherited cwd before the hook derived Pallium scope. The initial proposal to read `state_5.sqlite.threads.cwd` was rejected in clean-context review because that private value may be stale after handoff and is not a supported workspace authority. The existing Phase 0 evidence proves `codex queue --thread` is the native exact-session path for loaded idle and busy tasks and persists safely for later resume. Official OpenAI documentation search did not establish a supported cold-resume workspace API. PR #161 preserves legitimate Relay scope transitions but does not prevent this host-created transition.

**Material assumptions:**
- `codex queue --thread` remains the supported runtime-owned mechanism for an exact loaded task and persists the message for an unloaded task's next supported resume. A caller-surface regression that loses the message or targets another task disproves this and returns the task to planning.
- The resolved user Codex home (`Path.home() / ".codex"`) is an existing local directory suitable only as a process launch directory; it is not used as task workspace state. A missing, non-directory, relative, device, or network path must fail closed without spawning.
- Removing unattended cold `exec resume` is an intentional qualification correction, not a silent compatibility promise. A future supported runtime workspace API is required before restoring cold resume.

**Plan:**
1. Delete the private cold `exec resume` path and launch only `codex queue --thread` from a small stdlib-validated local Codex-home directory; fail closed before spawning if that directory is unavailable or unsafe.
2. Add focused neutral-directory/queue edge cases plus an HTTP send-to-wake caller-surface regression that proves the service cwd cannot enter the subprocess call while delivery remains pending until the hook path.
3. Correct current Codex integration and Relay qualification from loaded-plus-unloaded wake to loaded-task wake plus durable unloaded-task next-resume delivery, and record the generalized inherited-cwd incident in the wake roadmap.
4. Run focused tests, affected Relay/Codex suites, workflow/redline checks, then the full suite once. Obtain independent smart result review before PR merge.
5. Merge only with green CI and resolved review threads. Fast-forward the stable installed checkout and applicable development checkout state to current `origin/main`, restart only with `Pallium-installed\scripts\restart-service.ps1`, and verify `/health`, `/status`, and `/debug/queue/health`.

**Verification plan:**
- Loaded exact-task wake uses one native queue command from the vetted neutral directory → focused launch test and caller-surface HTTP lifecycle test.
- Unsafe or missing neutral directory never inherits service cwd → parameterized fail-closed tests.
- Busy delivery remains a distinct queued turn with unchanged admission semantics; unloaded delivery remains durable without a false cold-resume claim → existing lifecycle tests plus command/cwd and documentation assertions.
- Final code satisfies repository governance and regressions → redline/workflow checks, full `tests/` suite, green PR CI, independent review.
- Installed service runs merged code healthily → exact commit comparison, wrapper restart, and all three required health endpoints.

**Plan review:**
Initial clean-context re-review accepted the queue-only plan: exact-thread queue from a validated neutral Codex home, fail-closed path handling, explicit unloaded-task qualification, and caller-surface coverage.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

<!-- Ready to implement | Blocked | Ready for review -->
**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- Established isolated branch `feat/codex-wake-preserve-workspace` from `origin/main` at `cad04e01`; no implementation files edited.
- Discovery confirmed the sender-scope 404 is downstream of wake-inherited service cwd and that PR #161 does not cover this exact host-context root cause.
- Rebased the isolated plan branch onto `origin/main` at `18c43f0d` after PR #165 merged.
- Approved implementation files: `app/codex_wake.py`, `tests/test_codex_wake.py`, `docs/codex-integration.md`, `docs/agent-relay.md`, `roadmap/features/add-wake-first-relay-delivery.md`, and this Work Record. No other paths are approved.
- Implemented the accepted queue-only adapter: one exact-thread native queue write from a validated resolved local Codex home, with no cold resume or private state access. Loaded/unloaded qualification is explicit in both current docs and the roadmap; RW-024 records the inherited-cwd failure and RW-025 tracks the observed expired-reply fallback.
- A low-cost delegated mechanical pass edited only the approved code/test files. Its first result had a malformed command list and stale outcome assertions; review corrected those plus unsafe-path validation order and caller-surface cwd assertions before acceptance.
- `apply_patch` failed with the machine's known Windows 1327 error. Both the delegate and primary agent used narrowly scoped elevated PowerShell/.NET deterministic replacements limited to approved files.
- Focused edit-loop verification is green: `tests/test_codex_wake.py` reports 49 passed, including explicit cwd, Unicode, unsafe/missing/error path, pending-before-hook, exact hook delivery, and single-flight coverage.

## Plan review

- Initial review: blocked. Private `state_5.sqlite.threads.cwd` is not a supported or reliably fresh workspace authority, and the proposed missing-state fallback still inherited the service cwd.
- Revision: removed private-state access and cold `exec resume`; uses only native exact-thread queue from a vetted neutral directory and explicitly narrows unloaded-task qualification.
- Clean-context re-review: **ACCEPT**. The reviewer confirmed the revised plan removes the only replacement-task path that inherited service cwd, preserves exact loaded-task wake and durable unloaded-task delivery, and requires explicit fail-closed cwd plus HTTP→scheduler→hook coverage.

## Evidence

Pending.

## Result review

Pending.
