# Preserve Codex task workspace during Relay wake

<!-- agent-workflow:start -->
**Outcome:**
Codex Relay wake never changes an addressed task's workspace or scope merely because the Pallium service runs from another checkout.

**Target:**
Pallium Codex Relay wake adapter.

**Scope:**
`app/codex_wake.py`, focused caller-surface coverage in `tests/test_codex_wake.py`, current qualification in `docs/codex-integration.md`, `docs/agent-relay.md`, and `docs/context/state.md`; the Codex restart contract fixture in `tests/relay/wake/fixtures/codex/06_restart_recovery.json`; wake roadmap status and incident evidence in `roadmap/features/add-wake-first-relay-delivery.md`; and this Work Record.

**Constraints:**
Preserve exact-session routing, pending-until-hook-admission, single-flight deduplication, hidden process launch, and fail-closed sender scope. Do not add cross-scope fallback, read or write private Codex state, add dependencies, launch a Codex subprocess from the service cwd, or claim native unloaded-task persistence without executable evidence. Windows neutral paths must reject UNC/device/remote-drive and service-checkout redirects; POSIX paths must be absolute existing directories, with mount locality explicitly unclaimed.

**Completion criteria:**
1. Every wake uses the already-qualified native exact-thread queue from a vetted neutral Codex directory, never `codex exec resume` from the service checkout.
2. Loaded idle and busy tasks retain prompt wake plus the existing pending-until-hook-admission semantics.
3. Unloaded-task correctness relies only on Pallium persistence: the Relay delivery remains pending and a later supported hook turn retrieves it. Current docs, state, fixture, and roadmap claim neither unattended cold resume nor native unloaded-queue persistence.
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
- `codex queue --thread` remains the supported runtime-owned mechanism for an exact loaded task. Unloaded-task correctness depends only on Pallium's pending delivery and later hook retrieval; native queue persistence is not assumed.
- The resolved user Codex home (`Path.home() / ".codex"`) is suitable only as a process launch directory and is not task workspace state. Missing, non-directory, relative, Windows UNC/device/remote-drive, service-checkout redirect, and resolution-error paths fail closed. POSIX mount locality is not claimed because stdlib cannot prove it portably.
- Removing unattended cold `exec resume` is an intentional qualification correction, not a silent compatibility promise. A future supported runtime workspace API is required before restoring cold resume.

**Plan:**
1. Delete the private cold `exec resume` path and launch only `codex queue --thread` from a small stdlib-validated local Codex-home directory; fail closed before spawning if that directory is unavailable or unsafe.
2. Add focused neutral-directory/queue edge cases, including a redirected service-checkout path, plus an HTTP send-to-wake caller-surface regression that proves the service cwd cannot enter the subprocess call while delivery remains pending until the hook path.
3. Correct every current source of truth—including state and the Codex restart fixture—from loaded-plus-unloaded native wake to loaded-task wake plus Pallium-persisted unloaded-task next-turn delivery, and record the generalized inherited-cwd incident in the wake roadmap.
4. Run focused tests, affected Relay/Codex suites, workflow/redline checks, then the full suite once. Obtain independent smart result review before PR merge.
5. Merge only with green CI and resolved review threads. Fast-forward the stable installed checkout and applicable development checkout state to current `origin/main`, restart only with `Pallium-installed\scripts\restart-service.ps1`, and verify `/health`, `/status`, and `/debug/queue/health`.

**Verification plan:**
- Loaded exact-task wake uses one native queue command from the vetted neutral directory → focused launch test and caller-surface HTTP lifecycle test.
- Unsafe, missing, or service-checkout-redirected neutral directory never reaches a subprocess → parameterized fail-closed tests.
- Busy delivery remains a distinct queued turn with unchanged admission semantics; unloaded correctness relies only on pending Relay persistence and later real-hook retrieval → existing lifecycle tests, corrected restart fixture, and source-of-truth scan.
- Final code satisfies repository governance and regressions → redline/workflow checks, full `tests/` suite, green PR CI, independent review.
- Installed service runs merged code healthily → exact commit comparison, wrapper restart, and all three required health endpoints.

**Plan review:**
The repeat clean-context plan review accepted the expanded correction: reject service-checkout redirects, narrow POSIX claims, and rely only on Pallium persistence for unloaded tasks.

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
- Approved implementation files: `app/codex_wake.py`, `tests/test_codex_wake.py`, `docs/codex-integration.md`, `docs/agent-relay.md`, `docs/context/state.md`, `tests/relay/wake/fixtures/codex/06_restart_recovery.json`, `roadmap/features/add-wake-first-relay-delivery.md`, and this Work Record. No other paths are approved.
- Implemented the accepted queue-only adapter: one exact-thread native queue write from a validated resolved local Codex home, with no cold resume or private state access. Loaded/unloaded qualification is explicit in both current docs and the roadmap; RW-024 records the inherited-cwd failure and RW-025 tracks the observed expired-reply fallback.
- A low-cost delegated mechanical pass edited only the approved code/test files. Its first result had a malformed command list and stale outcome assertions; review corrected those plus unsafe-path validation order and caller-surface cwd assertions before acceptance.
- `apply_patch` failed with the machine's known Windows 1327 error. Both the delegate and primary agent used narrowly scoped elevated PowerShell/.NET deterministic replacements limited to approved files.
- Focused edit-loop verification is green: `tests/test_codex_wake.py` reports 49 passed, including explicit cwd, Unicode, unsafe/missing/error path, pending-before-hook, exact hook delivery, and single-flight coverage.
- Independent result review blocked merge on two substantive gaps: redirected `.codex` could still resolve to the service checkout, and live docs/fixture overclaimed native unloaded-task persistence. Scope expanded to the state doc and Codex restart fixture; verification must be rerun after the reviewed correction.
- Skill feedback Trigger 1 dropped: the repeated `apply_patch` 1327 workaround is a documented machine-local runtime failure outside agent-workflow ownership.

## Plan review

- Initial review: blocked. Private `state_5.sqlite.threads.cwd` is not a supported or reliably fresh workspace authority, and the proposed missing-state fallback still inherited the service cwd.
- Revision: removed private-state access and cold `exec resume`; uses only native exact-thread queue from a vetted neutral directory and explicitly narrows unloaded-task qualification.
- Clean-context re-review: **ACCEPT**. The reviewer confirmed the revised plan removes the only replacement-task path that inherited service cwd, preserves exact loaded-task wake and durable unloaded-task delivery, and requires explicit fail-closed cwd plus HTTP→scheduler→hook coverage.
- Repeat clean-context plan re-review after result-review scope expansion: **ACCEPT**. The reviewer found the expanded sources, narrowed unloaded/POSIX claims, redirected-service-cwd guard, risk classification, coverage, and sequential PR/deployment gates sound.

## Evidence

Verified implementation revision `6de3f5a9`:

- Focused Codex wake caller-surface suite: 49 passed.
- Repository last-failure rerun after syncing locked optional extras: 106 passed, 4,986 deselected.
- Full repository suite: 4,842 passed, 33 skipped, 2 expected failures.
- Import boundaries: 8 contracts kept, 0 broken.
- Redline: GRAY/watch only for `app/codex_wake.py`; blue tests/docs/roadmap, no boundary violations, no checkpoints, size ok.
- Agent-workflow local gate: clean, exit 0.
- The first last-failure collection lacked locked MCP/vector extras; `uv sync --frozen --all-extras` corrected the environment and the rerun passed. The first redline attempt lacked its configured generated boundary artifact; `scripts/run-import-linter.py` generated it and the rerun passed.

## Result review

- Initial independent review: **BLOCKED**. Reject service-checkout redirects, narrow POSIX locality claims, remove unsupported native unloaded-task persistence claims from all sources of truth, and rerun verification. PR/CI and installed-service gates remain sequential acceptance work after the corrected result review.
