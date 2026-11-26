# Refuse Relay writer admission when SQLite setup uses up its deadline

<!-- agent-workflow:start -->
**Outcome:** Do not ask SQLite to begin a Relay write after setup has already used the acquisition allowance.

**Target:** `storage/sqlite_queue.py::_begin_immediate_for`, at the boundary between `setup_pragma` and `BEGIN IMMEDIATE`.

**Scope:** One deadline check after the setup PRAGMA, plus simulated-clock boundary tests and an HTTP regression with real SQLite.

**Constraints:** Keep the acquisition budget, busy response, `Retry-After`, native busy-timeout policy, rollback for a genuinely late BEGIN, and transaction cleanup unchanged. No live fault injection, installed operation, or claim to fix the underlying setup stall.

**Completion criteria:** If the deadline is reached during the setup PRAGMA, return `setup_deadline` with setup timing and never issue BEGIN or run the write body. Before that deadline, ordinary admission still works. A BEGIN that runs past the deadline still rolls back as `late_begin`. The HTTP 503 leaves no registration and one later normal request succeeds.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"Do not ask SQLite to begin a Relay write after setup has already used the acquisition allowance.","scope":"One deadline check after the setup PRAGMA, plus simulated-clock boundary tests and an HTTP regression with real SQLite.","constraints":"Keep the acquisition budget, busy response, `Retry-After`, native busy-timeout policy, rollback for a genuinely late BEGIN, and transaction cleanup unchanged. No live fault injection, installed operation, or claim to fix the underlying setup stall.","completion_criteria":"If the deadline is reached during the setup PRAGMA, return `setup_deadline` with setup timing and never issue BEGIN or run the write body. Before that deadline, ordinary admission still works. A BEGIN that runs past the deadline still rolls back as `late_begin`. The HTTP 503 leaves no registration and one later normal request succeeds."}

**Risk:** Elevated

**Complexity:** Simple

**Reason:** A narrow change to transaction timing and diagnostics, in a shared persistence helper. No schema or custody mutation change.

**Discovery:** On current main, a disposable HTTP/SQLite witness advanced the acquisition clock immediately after the real setup PRAGMA. The request still issued BEGIN and ROLLBACK, then returned 503 `relay_busy` with `Retry-After: 1`. No session was registered and the next normal turn returned 200. Hosted CI independently recorded slow setup followed by `late_begin`; the witness does not reproduce that physical delay.

**Material assumptions:** `acquisition_deadline` is supplied only for the bounded Relay path; callers without a deadline remain unchanged. The check is a boundary guard, not an interruption of a native call already in progress.

**Plan:** Invoke Agent Workflow and classify before editing. After independent plan review, add a regression using real SQLAlchemy cursor observations through `/relay/turn`. Prove it fails before implementing the guard. Check the existing monotonic deadline immediately after `setup_pragma`; use the existing `setup_deadline` refusal and cleanup path. Keep the post-BEGIN rollback.

**Verification plan:**
- Before, equal, and after the deadline → controlled clock at the PRAGMA completion boundary, with SQL statement and phase assertions.
- Refusal and recovery → isolated `/relay/turn` with real SQLite, no BEGIN or persisted registration on refusal, unchanged status and retry header, and successful subsequent registration.
- True late BEGIN and no-deadline callers → existing controls; no changes to their assertions.

**Plan review:** Agent technical review: independent Pallium architect GO at base `3e69d4ca`, with direct assertions for busy-timeout reset and session close on refusal.

**Approvals:** Not required at this risk level. Standing bug-fix authority does not authorize rollout or publication of private evidence.

**State:** Blocked
<!-- agent-workflow:end -->

The offline boundary matrix found unnecessary BEGIN/ROLLBACK both at
and after the setup deadline. Just before the deadline committed;
when BEGIN itself crossed the deadline it rolled back. All refusals
left no registration, restored the timeout, and allowed a later turn.
This does not identify the physical cause of the hosted or installed stalls.

## Implementation

The regression failed on the unmodified writer: both expired HTTP
cases issued BEGIN and ROLLBACK; all three expired direct cases
reported `late_begin`. The just-before and genuinely late BEGIN
controls passed. Add the check at the setup-to-BEGIN boundary.

The two-line guard now uses `setup_deadline` and the existing cleanup
path. The genuinely late BEGIN still rolls back. Both affected files
passed together: 154 tests. The whole-change selector requires one full
non-slow run, now started in the isolated worktree with the previously
qualified Windows test runtime. No publication or installed change.

The selected full run stopped at 1,807 passes. An unchanged Claude
test got `PermissionError` reading its child-process ready file, before
hook publication or HTTP recovery. The exact node passed alone.
The full result remains failed. Use ordinary hosted checks on the
reviewed candidate; no repeat of the passing focused run.

## Result review

Agent technical review: independent Pallium architect GO for the source
change and focused evidence, with full qualification explicitly open.
Reviewed revision: base `3e69d4ca`; storage blob `cb5603c6`, HTTP test
blob `10f6bfc0`, direct test blob `9d11568a`.
Verification adequacy: five intended baseline failures and 154 focused
passes cover the exact deadline, before/after, genuine late BEGIN,
timeout reset, single close, writer lock release, and unchanged HTTP
refusal and recovery. The local Windows full run failed before the
unchanged Claude test reached its HTTP subject. Its isolated pass does
not replace that result.
