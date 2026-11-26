# Coalesce successful slow OpenCode wake warnings

<!-- agent-workflow:start -->
**Outcome:** Bound successful slow OpenCode wake warnings while retaining the count and peak elapsed time.

**Target:** The `opencode_wake` success warning in `_relay_sync_call` on `origin/main`.

**Scope:** The successful `opencode_wake` warning in `_relay_sync_call`, the existing real-route writer diagnostics tests in `tests/test_relay_writer_diagnostics_e2e.py`, and this Work Record.

**Constraints:** No change to HTTP behavior, busy or 503 records, writer phase or completion evidence, other operations, timeouts, cache, or polling. No timer, sink filter, shared limiter, live execution, rollout, or duplicate local broad validation. Draft publication starts hosted validation only.

**Completion criteria:** The first successful wake at or above 100 ms reports immediately. Subsequent reports reserve at most one slot per ten monotonic seconds per router and report the batch count and peak elapsed time. Concurrent completions account for each qualifying observation once without holding the lock during logging. Busy replies and other operation warnings are unchanged.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"Bound successful slow OpenCode wake warnings while retaining the count and peak elapsed time.","scope":"The successful `opencode_wake` warning in `_relay_sync_call`, the existing real-route writer diagnostics tests in `tests/test_relay_writer_diagnostics_e2e.py`, and this Work Record.","constraints":"No change to HTTP behavior, busy or 503 records, writer phase or completion evidence, other operations, timeouts, cache, or polling. No timer, sink filter, shared limiter, live execution, rollout, publication, or duplicate broad validation.","completion_criteria":"The first successful wake at or above 100 ms reports immediately. Subsequent reports reserve at most one slot per ten monotonic seconds per router and report the batch count and peak elapsed time. Concurrent completions account for each qualifying observation once without holding the lock during logging. Busy replies and other operation warnings are unchanged."}

**Behavior changes:**
[{"target":"task-context.constraints","classification":"equivalent","before":"No change to HTTP behavior, busy or 503 records, writer phase or completion evidence, other operations, timeouts, cache, or polling. No timer, sink filter, shared limiter, live execution, rollout, publication, or duplicate broad validation.","after":"No change to HTTP behavior, busy or 503 records, writer phase or completion evidence, other operations, timeouts, cache, or polling. No timer, sink filter, shared limiter, live execution, rollout, or duplicate local broad validation. Draft publication starts hosted validation only.","reason":"Advance from closed offline implementation to draft review without changing the patch or authorizing merge or installed changes."}]

**Risk:** High

**Complexity:** Simple

**Reason:** `api/routes.py` is a red zone requiring API review even for a logging-only change.

**Discovery:** Successful slow completions write a synchronous warning after return from the operation. Busy, failed, and writer diagnostic paths are separate.

**Material assumptions:** The report batch belongs to one router. An unreported final batch is not flushed at shutdown.

**Plan:** Reuse the independently reviewed route and test bytes. Run normal hosted checks on a separate draft; keep the test-only History correction in its own PR. No rollout from this draft.

**Verification plan:**
- Initial report, threshold, exact time boundary, count and peak reset → existing HTTP writer diagnostic controls.
- Overlapping completions and held sink → one slot, full accounting, and progress without holding the counter lock during logging.
- Busy, 503, and other slow warnings → unchanged route controls.
- Whole-change qualification → retain prior Windows results and use normal hosted CI on the exact draft.

**Plan review:** Agent technical review: independent clean-context GO on plan `a305b2c5f561f3fadb3b87d9273e294ea6e8f739`. API review remains distinct.

**Approvals:** The task owner reaffirmed the existing bug-fix approval and directed release work to proceed without another human review. The plan approval evidence is retained privately. This records the owner's disposition, not a human technical verdict.

**Exceptions:**
- rule: approval.high_risk_approval_recorded
  reason: The owner reaffirmed existing approval and directed work to proceed without another approval or review round. Do not publish private chat to meet the public quote format.
  scope: PR #432 only, with the reviewed route and test blobs below; the exception covers the public verbatim-record format, not actual approval or technical review.
  approver: Repository task owner
  expiry: 2026-12-03
  compensating_validation: Retain the exact approval privately. Preserve independent plan, result, and API-contract review and exact-blob verification.

**State:** Ready for review
<!-- agent-workflow:end -->

## Verification

- The new HTTP test failed on base: a second completion inside the window logged rather than joining the batch. The prior candidate passed 81 focused tests. Two affected HTTP cases passed after restoring the triggering completion's `duration_ms` field.
- The exact route and writer tests, with the separate History test correction, passed a locked Windows full run: 9,305 passed, 48 skipped, two xfailed. Two earlier failed full runs are retained. The passing integrated run does not make either failure a pass, and this draft does not include the History correction.
- Only the successful slow-wake warning changes. No stall cause or measured latency improvement is claimed.

## Result review

Agent technical review: independent result GO on the exact revised route and writer-test blobs.
Reviewed revision: `api/routes.py` blob `5ffb2bd4c190592da3e284fd12573a5b10295cbe`; writer-test blob `04e635c6e70e9e29595fffd11b5697fc2d1d65e5`.
Verification adequacy: reviewed focused RED/GREEN and warning-field correction, then matched the blobs to the locked full-run composition. [Application CI](https://github.com/rore/Pallium/actions/runs/45784836069/attempts/2) passed on the single failed-jobs retry; [attempt 1](https://github.com/rore/Pallium/actions/runs/45784836069/attempts/1) remains failed on a Relay expiry prerequisite.

Independent API-contract review confirmed unchanged HTTP responses, retry
behavior, busy diagnostics, and other warnings at `d6c5d034`. The task
owner declined a separate human result review for this release candidate.
