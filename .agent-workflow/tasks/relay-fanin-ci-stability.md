<!-- agent-workflow:start -->
**Outcome:** Concurrent Relay fan-in CI coverage honors the existing retryable storage-busy contract without losing or duplicating deliveries.

**Target:** Pallium Relay SQLite concurrency regression.

**Scope:** `tests/test_sqlite_relay_isolation.py` and this Work Record.

**Constraints:** Production code, retry budgets, API behavior, and persistence remain unchanged. Retries reuse the exact idempotent send input and keep the default suite fast.

**Completion criteria:** When four concurrent storage writers encounter transient `ImmediateTransactionBusyError`, the test retries within a fixed bound and still observes exactly eight unique delivered and acknowledged messages.

**Risk:** Routine

**Complexity:** Simple

**Reason:** Redline classified both intended files BLUE with no boundary risk, watch path, or checkpoint.

**Approach:** Catch only the documented transient storage-busy exception around each direct test send, retry the unchanged message ID within the existing caller attempt bound, and preserve the full delivery/ACK lifecycle assertions.

**Verification:** Run the exact fan-in test repeatedly, the full SQLite Relay isolation file, workflow/redline checks, and the authoritative Linux Python 3.12 CI job.

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- GitHub Actions run 34613328416 failed only `test (3.12)` after 4,148 passes; the fan-in test surfaced `ImmediateTransactionBusyError` from one of four direct storage writers. Python 3.13 and both Windows full jobs passed.
- The existing storage/API contract intentionally maps exhausted bounded lock acquisition to retryable `relay_busy`; MCP idempotent sends retry up to 12 attempts within 25 seconds. The direct-storage test bypassed that layer and assumed no transient busy result.
- Pre-edit exact-test stress: 30 consecutive local passes, confirming load-sensitive rather than deterministic data loss.
- Implemented a test-only bounded retry around the unchanged idempotent direct-storage send, catching only `ImmediateTransactionBusyError`. Added assertions for all eight expected claimed message IDs and persisted `delivered` state after every ACK.
- After one machine-local `apply_patch` failure (`CreateProcessWithLogonW` 1327), used deterministic replacement limited to `tests/test_sqlite_relay_isolation.py`, per local instructions.

## Evidence

- Failed-job rerun `test (3.12)` passed on GitHub Actions run 34613328416.
- `python -m pytest tests/test_sqlite_relay_isolation.py -q -n 0`: 20 passed in 7.67s after final assertions.
- First full local run exposed one unrelated Codex hook timing failure; repository-prescribed `python -m pytest --lf --lfnf=none -q -n 0` passed, followed by 20/20 isolated repetitions of that node.
- Authoritative full rerun `python -m pytest tests/ -x -q`: 4,861 passed, 33 skipped, 2 xfailed in 202.59s.
- `git diff --check` passed.

## Result review

Clean-context smart review `/root/relay_fanin_fix_review` returned PASS. It confirmed test-only retry matches the deliberate pre-transaction `relay_busy` contract, remains bounded, retries identical idempotent inputs, and needs no extra sleep or helper. Its two nonblocking assertion suggestions were added; re-review returned PASS with no remaining findings.