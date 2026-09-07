<!-- agent-workflow:start -->
**Outcome:** The dual-package rapid-fire test stops its workers reliably on contended Windows CI without weakening its concurrency assertions.

**Target:** Pallium test suite.

**Scope:** `tests/test_thread_summary_accumulation.py` and this Work Record.

**Constraints:** Production behavior and coverage remain unchanged; the shutdown wait stays bounded.

**Completion criteria:** When SQLite contention keeps an in-flight worker busy beyond five seconds, the test allows the configured 15-second connection timeout and still fails after one shared 20-second deadline if either worker does not terminate.

**Risk:** Routine

**Complexity:** Simple

**Reason:** Redline classified both paths blue; this is one test-only timeout correction with no product or CI configuration change.

**Approach:** Allow one shared 20-second worker-join deadline, just above SQLite's 15-second connection timeout, so two workers cannot double the maximum wait.

**Verification:** Run the failing test repeatedly and serially, the full test module, agent-workflow/redline checks, and PR CI; review the final diff independently before merge.

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Discovery: Windows CI failed because workers can remain inside source-item or rebuild processing while SQLite operations observe the 15-second connection timeout; workers only observe the stop event between calls.
- Implemented: replaced the two independent 5-second joins with one shared 20-second deadline, preserving immediate return and a bounded hang assertion.

## Evidence

- Revision b0863fcf: focused test passed 5 repeated runs, then passed again at the committed revision; all 4 module scenarios passed serially in 8.21s; redline and agent-workflow gates are clean.
- Result review: independent review approved the bounded shared deadline after correcting claim-specific timeout wording; no behavioral findings remain.
