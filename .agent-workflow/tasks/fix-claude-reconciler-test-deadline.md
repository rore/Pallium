<!-- agent-workflow:start -->
**Outcome:**
Claude wake retry durability CI verifies eventual retry without imposing a one-second filesystem-throughput deadline.

**Target:**
Pallium Claude wake durability verification.

**Scope:**
`tests/test_claude_wake_durability.py`, `roadmap/features/add-wake-first-relay-delivery.md`, and this Work Record.

**Constraints:**
Production wake scheduling, indefinite retry semantics, and observable state assertions remain unchanged; successful tests must not become slower.

**Completion criteria:**
When the native transport returns retryable three times, the reconciler shall continue until the fourth acceptance under loaded CI, while any future timeout reports observed attempts.

**Risk:** Routine

**Complexity:** Simple

**Reason:**
All intended paths are agent-redline blue-zone test, roadmap, or Work Record files.

**Approach:**
Raise only the asynchronous test's failure ceiling from one to five seconds and include the observed retry states in an assertion failure; record the CI incident in the existing Relay wake ledger.

**Verification:**
Repeat the exact reconciler test serially and under default xdist, then run the Claude wake durability suite and PR/main CI.

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- GitHub run 34095951883 failed only Linux 3.13 at the one-second event-wait ceiling after 1,320 passing tests; the exact test also reproduced locally in serial mode while passing under xdist.
- Changed only that event wait from a one-second to a five-second failure ceiling and added observed retry states to assertion output; production code and successful-test timing are unchanged.
- Recorded the generalized CI incident as Relay wake ledger item RW-021.

## Evidence

- GitHub Actions job 101659545855: 1 failed, 1,320 passed, 14 skipped, 1 xfailed; failing assertion was the one-second event wait.
- Exact serial regression: 1 passed in 0.95s; event returned before its five-second ceiling.
- Repeat serial witness: 10/10 passed; each completed in 0.76-0.91s.
- Full `tests/test_claude_wake_durability.py`: 41 passed in 6.13s under default xdist.

## Result review

- Self-review: the diff changes no production path, keeps the required four-attempt assertion, adds no sleep, and narrows the timing accommodation to the one test that performs four filesystem-backed retry cycles.
