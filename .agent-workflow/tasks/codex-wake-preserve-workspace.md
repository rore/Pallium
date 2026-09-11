# Preserve Codex task workspace during Relay wake

<!-- agent-workflow:start -->
**Outcome:**
Codex Relay wake resumes the addressed task in its runtime-recorded workspace and never changes task scope merely because the Pallium service runs from another checkout.

**Target:**
Pallium Codex Relay wake adapter.

**Scope:**
`app/codex_wake.py`, focused caller-surface coverage in `tests/test_codex_wake.py`, concise Codex integration documentation if needed, and this Work Record.

**Constraints:**
Preserve exact-session routing, pending-until-hook-admission, single-flight deduplication, active-writer queue behavior, hidden process launch, and fail-closed sender scope. Do not add cross-scope fallback, write Codex state, add dependencies, or inherit the service cwd when runtime workspace resolution fails.

**Completion criteria:**
1. When a persisted delivery wakes an idle Codex task, the resume process uses the exact existing absolute workspace recorded for that task, not the service cwd.
2. When Codex state is missing, changing, malformed, relative, or names a missing directory, wake does not run `exec resume` from an unrelated directory and instead uses the already-qualified native exact-thread queue fallback.
3. When the addressed task is busy, the distinct-turn queue path retains the same validated workspace and existing delivery/admission semantics.
4. The HTTP send-to-wake lifecycle and focused edge cases pass, followed by the repository regression suite and deployed Windows service health checks.

**Risk:**
Elevated

**Complexity:**
Moderate

**Reason:**
Redline classifies `app/codex_wake.py` as gray/watch runtime code, mapping to Elevated risk; tests and the Work Record are blue. Complexity is Moderate because the fix must preserve cold wake, busy queue, missing-state fallback, and installed-service behavior.

**Discovery:**
`app/codex_wake.py::_launch` invokes `codex exec ... resume` and its queue fallback without `cwd`, so both inherit the installed service checkout. The incident log shows Codex applied that inherited cwd before the hook derived Pallium scope. Codex's runtime-owned `state_5.sqlite` already stores exact `threads(id, cwd)` records; a read-only query for the affected task reflects its current workspace. The existing Phase 0 decision proves `codex queue --thread` is the native exact-session path for loaded idle and busy tasks and persists safely for later resume. Official OpenAI documentation search did not document these internal CLI/state details. PR #161 preserves legitimate Relay scope transitions but does not prevent this host-created transition.

**Material assumptions:**
- Codex's `threads.cwd` is the runtime's current task workspace at wake dispatch. A caller-surface mismatch with the runtime record disproves this; if disproved, drop cold `exec resume` and retain queue-only fallback until a supported workspace API exists.
- Passing the validated runtime cwd to `subprocess.run` prevents the CLI from inheriting the service checkout. A regression showing another cwd reaches the launch call disproves this and returns the task to planning.
- The private Codex state schema may evolve. Missing database/table/row, SQLite errors, relative paths, and missing directories must all fail safely to queue without blocking the persisted delivery.

**Plan:**
1. Reuse stdlib `sqlite3` in `app/codex_wake.py` to read only the exact task row from Codex's local state database and accept only an absolute existing directory.
2. Pass that workspace as `cwd` to the current resume and active-writer queue subprocesses. If no workspace is safely available, skip resume and use the existing native exact-thread queue path directly; never fall back to the service cwd.
3. Add focused resolver/launch edge cases plus an HTTP send-to-wake caller-surface regression that proves the service cwd cannot enter the subprocess call while delivery remains pending until the hook path.
4. Run focused tests, affected Relay/Codex suites, workflow/redline checks, then the full suite once. Obtain independent smart result review before PR merge.
5. Merge only with green CI and resolved review threads. Fast-forward the stable installed checkout and applicable development checkout state to current `origin/main`, restart only with `Pallium-installed\scripts\restart-service.ps1`, and verify `/health`, `/status`, and `/debug/queue/health`.

**Verification plan:**
- Idle exact-task wake uses runtime-recorded cwd → focused launch test and caller-surface HTTP lifecycle test.
- Missing/malformed/changing state never inherits service cwd → parameterized resolver/fallback edge tests.
- Busy delivery remains a distinct queued turn with unchanged admission semantics → existing busy queue lifecycle tests plus cwd assertion.
- Final code satisfies repository governance and regressions → redline/workflow checks, full `tests/` suite, green PR CI, independent review.
- Installed service runs merged code healthily → exact commit comparison, wrapper restart, and all three required health endpoints.

**Plan review:**
Pending clean-context review under `## Plan review`.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

<!-- Ready to implement | Blocked | Ready for review -->
**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- Established isolated branch `feat/codex-wake-preserve-workspace` from `origin/main` at `cad04e01`; no implementation files edited.
- Discovery confirmed the sender-scope 404 is downstream of wake-inherited service cwd and that PR #161 does not cover this exact host-context root cause.

## Plan review

Pending.

## Evidence

Pending.

## Result review

Pending.
