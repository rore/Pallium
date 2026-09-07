<!-- agent-workflow:start -->
**Outcome:** The dual-package rapid-fire test stops its workers reliably on contended Windows CI without weakening its concurrency assertions.

**Target:** Pallium test suite.

**Scope:** `tests/test_thread_summary_accumulation.py` and this Work Record.

**Constraints:** Production behavior and coverage remain unchanged; the shutdown wait stays bounded.

**Completion criteria:** When SQLite holds a worker claim for its configured busy timeout, the test allows that bounded operation to finish and still fails if either worker does not terminate.

**Risk:** Routine

**Complexity:** Simple

**Reason:** Redline classified both paths blue; this is one test-only timeout correction with no product or CI configuration change.

**Approach:** Align the test's bounded worker-join budget with SQLite's 15-second busy timeout, using one shared deadline so two workers cannot double the maximum wait.

**Verification:** Run the failing test repeatedly and serially, the full test module, agent-workflow/redline checks, and PR CI; review the final diff independently before merge.

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Discovery: Windows CI failed because `join(timeout=5)` is shorter than SQLite's configured 15-second busy timeout; workers only observe the stop event between claims.
- Implemented: replaced the two independent 5-second joins with one shared 20-second deadline, preserving immediate return and a bounded hang assertion.

## Evidence

- Revision b0863fcf: focused test passed 5 repeated runs, then passed again at the committed revision; all 4 module scenarios passed serially in 8.21s; redline and agent-workflow gates are clean.
