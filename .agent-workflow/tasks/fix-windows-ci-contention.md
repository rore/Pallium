<!-- agent-workflow:start -->
**Outcome:**
Windows CI no longer flakes when two ingestion workers claim distinct queued items or when the one-shot OpenCode caller-surface harness finishes its assertions.

**Target:**
Pallium SQLite queue claim acquisition and the structural-work-ref OpenCode E2E harness.

**Scope:**
`storage/sqlite_queue.py`, `tests/test_sqlite_write_retry.py`, `tests/test_queue_concurrent_claim.py`, `tests/test_structural_work_refs_e2e.py`, this Work Record, and the Relay wake defect ledger if qualification changes.

**Constraints:**
Keep Relay's separately configured short transaction budget unchanged; preserve exactly-once queue claims; do not add wall-clock sleeps to the normal suite; do not weaken or skip caller-surface E2E.

**Completion criteria:**
Two concurrent ordinary queue claimers can acquire distinct eligible items without exhausting the lock budget; a one-shot Node harness exits immediately after emitting its result; focused tests pass repeatedly on Windows; PR CI is green.

**Risk:**
Elevated

**Complexity:**
Moderate

**Reason:**
`storage/sqlite_queue.py` is a gray persistence-layer path under agent-redline. Two independent but small Windows reliability failures require product and E2E-harness changes.

**Discovery:**
Run 34083835988 failed `test_concurrent_claim_next_source_item_two_items_two_winners`: one worker exhausted three 100 ms immediate-lock attempts. Run 34083904007 failed when a one-shot Node process importing the long-lived OpenCode plugin remained alive past the harness's 20 s timeout. The next main run passed both, confirming nondeterministic scheduling/lifecycle flakes rather than commit-specific regressions.

**Material assumptions:**
- Ordinary ingestion claims may wait longer than Relay transactions; disproved if callers require Relay-like subsecond failure, in which case separate the budgets instead of widening the shared ordinary constant.
- The OpenCode timeout occurs after useful work or from handles appropriate to a long-lived plugin; disproved if instrumentation shows the hook call itself exceeds the deadline, in which case optimize the production path rather than only terminating the harness.

**Plan:**
1. Raise only the ordinary immediate-transaction acquisition window to tolerate Windows scheduling while retaining bounded failure and leaving Relay's 100 ms override untouched.
2. Add deterministic retry-policy coverage plus the existing real two-worker claim regression; no sleep-based long test.
3. End the one-shot OpenCode Node snippets explicitly after writing their JSON result; keep the real plugin calls and assertions unchanged.
4. Run focused tests repeatedly, full affected suites, workflow/redline checks, independent review, then PR CI and review-thread closure.

**Verification plan:**
- When ordinary claim acquisition sees transient lock contention, it shall retry within the widened bounded window without replaying transaction work → deterministic `TestImmediateTransactionRetry` assertions.
- When two workers race for two items, both shall claim distinct items exactly once → `test_concurrent_claim_next_source_item_two_items_two_winners`, repeated locally.
- When the OpenCode caller-surface harness finishes, its Node process shall exit without waiting for long-lived plugin handles → all `test_structural_work_refs_e2e.py` cases, repeated locally.
- When the branch is proposed, all platforms shall remain compatible → full focused suites, agent-workflow/redline checks, and GitHub PR CI.

**Plan review:**
Pending clean-context review via `codex:@relaydev`.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Blocked
<!-- Ready to implement | Blocked | Ready for review -->
<!-- agent-workflow:end -->

## Implementation

- Discovery and Elevated/Moderate classification complete; implementation awaits clean-context plan review.

## Evidence

- GitHub Actions runs 34083835988 and 34083904007.

## Result review

- Pending.
