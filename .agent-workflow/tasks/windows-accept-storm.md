# Bound Windows accept-error logging during API recovery

<!-- agent-workflow:start -->
**Outcome:** Repeated Windows peer-abort completions do not flood synchronous API logs or prevent the listener from serving a later valid request.

**Target:** Pallium's Windows API listener.

**Scope:** `app/asyncio_windows_accept.py`, `tests/test_asyncio_windows_accept.py`, and this Work Record. Continue read-only attribution of the service outage separately from the mitigation.

**Constraints:** Preserve peer cleanup, immediate accept rearm, listener ownership, and fatal or unexpected error visibility. No live fault injection, timeout increases, Relay custody changes, dependency changes, or installed operations. Do not claim the trigger of the historical outage without matching evidence.

**Completion criteria:** An isolated WinError 64 completion burst demonstrates log amplification before the change and bounded diagnostics after it. An actual Windows loopback HTTP request succeeds after the burst; failed peers close and fatal errors remain visible.

**Requirement baseline:**
{"source":"Task-owner service stability investigation and fix request","outcome":"Repeated Windows peer-abort completions do not flood synchronous API logs or prevent the listener from serving a later valid request.","scope":"`app/asyncio_windows_accept.py`, `tests/test_asyncio_windows_accept.py`, and this Work Record. Continue read-only attribution of the service outage separately from the mitigation.","constraints":"Preserve peer cleanup, immediate accept rearm, listener ownership, and fatal or unexpected error visibility. No live fault injection, timeout increases, Relay custody changes, dependency changes, or installed operations. Do not claim the trigger of the historical outage without matching evidence.","completion_criteria":"An isolated WinError 64 completion burst demonstrates log amplification before the change and bounded diagnostics after it. An actual Windows loopback HTTP request succeeds after the burst; failed peers close and fatal errors remain visible."}

**Relationships:**
{"schema_version":1,"sources":null,"pull_requests":[]}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** The gray, watch-listed Windows event-loop adapter affects listener availability, even though the change is limited to diagnostics on a known transient completion.

**Discovery:** Windows can report repeated WinError 64 accept completions. The listener already closes failed peers and rearms, but it reports each exception synchronously before rearming. The isolated regression establishes log amplification, not the cause of an outage.

**Material assumptions:** WinError 64 from a completed accept is the narrow observed class; the change will not classify a transport/setup/reschedule exception as a peer abort. The observed log burst is a concrete load amplifier, not proof of what triggered the historical incident. If the isolated test does not reach that path, stop before changing product code.

**Plan:** Invoke the `/agent-workflow` skill to create the Work Record and classify risk, before any code edit. Use the existing real Windows accept-completion fixture on loopback to reproduce a short deterministic burst and subsequent HTTP success. Keep the first diagnostic with its original error and bound repeats per listener with a monotonic window; retain a count in the next diagnostic. Do not rate-limit actual accepts or other failures. Reuse the existing listener and cleanup seams.

**Verification plan:**
Burst logging → focused RED and GREEN through the actual Windows Proactor accept path, with fixed completions, bounded output, and a deterministic window boundary check.
Peer lifetime and health → later real HTTP succeeds, all failed peers close, and existing fatal, teardown, idempotence, and cancellation checks pass.
Scope and delivery → full-change selector, Redline, Workflow, independent review, required whole-change validation, and separate installed verification if authorized. Do not run a broad competing test load during live diagnosis.

**Plan review:** Agent technical review: accepted by the independent architecture reviewer on base `e1e5c4f3`. Limit only WinError 64 from pending result retrieval after fatal/closed checks. Use a fixed per-listener monotonic window, unchanged by success, with exact boundary and suppressed-count reporting. Verify rearm, two listeners and fresh lifetimes, and unchanged reporting for scheduling, setup, other completion errors and fatal cases. The review does not establish the outage's cause.

**Approvals:** Not required at this risk level. No live action is authorized by this record.

**State:** Blocked
<!-- agent-workflow:end -->

## Evidence

The bounded witness used a real Windows Proactor listener on an ephemeral
loopback port with 12 synthetic WinError 64 accept completions. All 12 failed
peers closed and a later HTTP request returned 200. The only failing
assertion was the diagnostic bound: the current code invoked the synchronous
exception handler 12 times, not once. This reproduces amplification, not
the original service outage. The independent reviewer accepted the
targeted plan before production edits.

## Implementation

Limit only reports for WinError 64 while retrieving the pending accept
result. The first report keeps the exception and socket; a fixed ten-second
window per listener suppresses repeats and counts them on the next report.
Success does not reset the window. Peer cleanup, immediate rearm, other
diagnostics, and fatal shutdown behavior remain unchanged.

## Verification

The retained native loopback regression failed on the baseline at 12 reports
instead of one. All peer cleanup and HTTP success assertions preceding it
passed. With the mitigation, the Windows accept file passed all 28 tests.
The final added post-success assertion passed on a targeted rerun. The
whole-change selector reports FULL. Whitespace check passed.
Redline returned GRAY with no violation or checkpoint; Agent Workflow was
clean. The prior import boundary report was reused after checking that the
only graph-source import change is a standard-library clock excluded from
the configured internal graph.

The first isolated invocation
stopped before pytest because the preflight used the wrong import name
for xdist. With the import corrected, the local run stopped after 3,558
passes on two unchanged failures: a Claude fixture's intent-file write
and Hermes setup turning a typed pre-attempt deadline into a missing
session. Preserve the failed run. Neither test exercises native Windows
accept completion; Windows smoke runs the changed accept file.
No rerun, live fault injection, rollout, or installed behavior claim.

## Result review

Agent technical review: independent architecture reviewer accepted the
targeted source and coverage review.
Reviewed revision: the exact frozen app/test patch above on `e1e5c4f3`.
Verification adequacy: accepted the finite Windows loopback burst, fixed
window, listener isolation, and unchanged fatal/setup/reschedule behavior.
The reviewer checked authored coverage and reported focused evidence, not
raw execution receipts. The manager rechecked the patch and both file
digests. Whole-change validation and incident trigger attribution stay open.

## Publication gate

App and test blobs match the reviewed patch exactly (`dc7021a3` and
`18a31c5c`). Main at `a5ab4d3b` has no overlap with either path or the
checked shared test and governance configuration. The task owner authorized
a separate PR and its first normal hosted checks. No local rerun. The failed
local run remains evidence; the merge gate is blocked pending hosted
disposition. Supervisor readiness, process-tree cleanup and deployment are
out of scope.
