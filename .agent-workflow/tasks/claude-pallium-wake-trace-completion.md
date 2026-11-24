# Observe refused optional Relay trace writes

<!-- agent-workflow:start -->
**Outcome:**
When the existing RelayTraceWriter worker calls a trace writer that explicitly returns False (refused optional diagnostic write), the service emits one safe, bounded warning, distinct from queue rejection and from writer exceptions. Today such refusals leave no log line, so lost trace facts (for example a Claude wake "completed" event) are undiagnosable.

**Target:**
Pallium service process: `app/relay_trace.py` (RelayTraceWriter) and its tests.

**Scope:**
`app/relay_trace.py` RelayTraceWriter worker result handling; tests in `tests/test_relay_trace_worker.py` and `tests/test_relay_delivery_trace.py`; this Work Record.

**Constraints:**
No change to trace admission, the correctness-writer gate, `_begin_low_priority_relay_write`, storage validation, delivery custody, wake eligibility or emitters. No retries, debug counters, typed reasons or thread dumps. Warning text carries no identifiers, payload, event fields or exception strings. Writers returning None or True stay silent. Existing queue-rejection and write-failure warnings keep their text and bounds. No live service restart, settings change or message resend.

**Completion criteria:**
1. A writer that returns False produces exactly one warning `relay_trace_write outcome=refused` per RelayTraceWriter instance, however many refusals follow.
2. True/None results produce no new warning; exceptions keep producing only `relay trace write failed`.
3. End to end through the existing busy-gate seam (correctness writer lock held), a Claude-shaped completed trace event enqueued through RelayTraceWriter to `RelayService.record_trace_event` yields the refusal warning, opens no database session, records no row, and leaves the delivery's claim/ACK custody unchanged; after release the same writer records the next event.
4. Warning text contains no attempt, delivery, endpoint or session identifiers.

**Requirement baseline:**
{"source": "work-record-initial", "outcome": "When the existing RelayTraceWriter worker calls a trace writer that explicitly returns False (refused optional diagnostic write), the service emits one safe, bounded warning, distinct from queue rejection and from writer exceptions. Today such refusals leave no log line, so lost trace facts (for example a Claude wake \"completed\" event) are undiagnosable.", "scope": "`app/relay_trace.py` RelayTraceWriter worker result handling; tests in `tests/test_relay_trace_worker.py` and `tests/test_relay_delivery_trace.py`; this Work Record.", "constraints": "No change to trace admission, the correctness-writer gate, `_begin_low_priority_relay_write`, storage validation, delivery custody, wake eligibility or emitters. No retries, debug counters, typed reasons or thread dumps. Warning text carries no identifiers, payload, event fields or exception strings. Writers returning None or True stay silent. Existing queue-rejection and write-failure warnings keep their text and bounds. No live service restart, settings change or message resend.", "completion_criteria": "1. A writer that returns False produces exactly one warning `relay_trace_write outcome=refused` per RelayTraceWriter instance, however many refusals follow.\n2. True/None results produce no new warning; exceptions keep producing only `relay trace write failed`.\n3. End to end through the existing busy-gate seam (correctness writer lock held), a Claude-shaped completed trace event enqueued through RelayTraceWriter to `RelayService.record_trace_event` yields the refusal warning, opens no database session, records no row, and leaves the delivery's claim/ACK custody unchanged; after release the same writer records the next event.\n4. Warning text contains no attempt, delivery, endpoint or session identifiers."}

**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:add-wake-first-relay-delivery"}],"pull_requests":[]}

**Risk:**
Elevated

**Complexity:**
Simple

**Reason:**
`app/relay_trace.py` is an unclassified watch path (runtime/process layer), so Redline floors Risk at Elevated. One coherent change in one class plus tests, so Simple.

**Discovery:**
- `app/claude_wake.py` emits "completed" in `run()`'s finally. In a reproduction, service logs showed a Claude wake attempt finishing with outcome `accepted` while its trace kept only the "prepared" event.
- `storage/sqlite_relay.py::relay_record_trace_event` returns False on busy/validation/missing; `storage/sqlite_queue.py::_begin_low_priority_relay_write` refuses while `_relay_writer_lock` is held (busy_timeout 25ms otherwise); `core/relay.py::RelayService.record_trace_event` converts any exception to False.
- `app/relay_trace.py::RelayTraceWriter._run` logs only exceptions, so a False result is silent. Enqueue rejections are reported once per reason per writer.
- Existing contract: `tests/test_relay_delivery_trace.py::test_busy_correctness_gate_refuses_optional_trace_before_database_admission` requires the optional write to be refused before DB admission while the gate is held. That stays unchanged.
- False conflates validation, missing and busy, so no typed reason is claimed.

**Material assumptions:**
- Every production writer passed to RelayTraceWriter returns bool and returns False only on refusal. Disproved if a writer returns False on success; then restrict the warning to the record_trace_event writer. Checked: `app/main.py` and `app/dependencies.py` pass only `relay_service.record_trace_event`.
- Logging once per writer instance is enough as a stall signal for operators. Disproved if repeated or periodic reporting is required; then return to planning.

**Plan:**
1. Write a characterization test through the busy-gate seam (completion criterion 3) and run it on unmodified code: it must fail only because no refusal warning is emitted.
2. Write a unit test in `tests/test_relay_trace_worker.py` for criteria 1, 2 and 4.
3. Change `RelayTraceWriter._run` into an instance method that inspects the writer's result; on `result is False`, emit `relay_trace_write outcome=refused` once per instance under the existing lock, using the existing reported-set pattern with a key distinct from enqueue reasons.
4. Run the focused tests, then the affected trace subsystem files.
Stop conditions: any needed change to storage, gate or emitters; any test requiring weakened existing assertions.

**Verification plan:**
- Criteria 1, 2 and 4 → unit test `tests/test_relay_trace_worker.py::test_trace_refused_write_warns_once_without_identifiers` (False three times gives one warning; True/None/falsy give none; exception keeps the existing text; no identifiers).
- Criterion 3 → busy-gate test `tests/test_relay_delivery_trace.py::test_busy_gate_refused_wake_completion_is_observable_without_custody_change`, failing on base and passing after the fix.
- Regression → `tests/test_relay_trace_worker.py`, `tests/test_relay_delivery_trace.py`, `tests/test_app_trace_lifecycle.py` with `-n 0`. The full non-slow suite runs once before the PR; see Correction.

**Plan review:**
Agent technical review: see ## Plan review.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

<!-- Ready to implement | Blocked | Ready for review -->
**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Branch `claude-pallium/wake-trace-completion` from `a5cb7acd`.
- Characterization: added both tests before any product edit; both failed on base only for the missing refusal warning.
- Implement: `RelayTraceWriter._run` is now an instance method; on an explicit False it sets `write_refused` in the existing reported set under `self._lock`, releases the lock, then logs `relay_trace_write outcome=refused` once inside its own try/except. Exception path unchanged.

## Plan review

Agent technical review: clean-context read-only non-implementer agent; approve-with-changes.
1. Do not log while holding the lock; reuse `_reported_rejections` with a distinct key. Applied.
2. Keep `result is False` and comment why. Applied.
3. Keep `_run`'s exception catch and wrap the warning in its own try/except. Applied.
4. Close and cancel paths need no change. Accepted.
5. Confirm module imports exist (`claude_wake`, `ActivationAttemptResult`, `logging`). Verified: already imported.
6. Prove the busy-gate test fails on base. Done before the product edit; see Evidence.

## Evidence

- Base (no product edit), `-n 0`: `test_busy_gate_refused_wake_completion_is_observable_without_custody_change[semantic]` failed `assert 0 == 1` on the refusal count; `test_trace_refused_write_warns_once_without_identifiers` failed with `['relay trace write failed'] == ['relay_trace_write outcome=refused', 'relay trace write failed']`.
- After the fix, `-n 0`: `tests/test_relay_trace_worker.py tests/test_relay_delivery_trace.py tests/test_app_trace_lifecycle.py` gave 92 passed. This includes the unchanged contract `test_busy_correctness_gate_refuses_optional_trace_before_database_admission`.
- The full non-slow suite ran separately; see Correction.

## Result review

Final confirmation after the test-only correction:
Agent technical review: clean-context read-only non-implementer agent; approve, no material findings.
Reviewed revision: f45ceff8 (base a5cb7acd). Blobs: `app/relay_trace.py` da6290e4 and `tests/test_relay_delivery_trace.py` 9df0fd87, both unchanged since the first review; `tests/test_relay_trace_worker.py` 2f251de0.
Verification adequacy: adequate. The reviewer ran `tests/test_relay_trace_worker.py -n 0`: 14 passed. Full-suite evidence is in Correction.

First review, before the correction:
Agent technical review: clean-context read-only non-implementer agent; approve, no material findings.
Reviewed revision: base `a5cb7acd` plus uncommitted diff of `app/relay_trace.py`, `tests/test_relay_delivery_trace.py` and `tests/test_relay_trace_worker.py` (`git diff | sha1sum` = `29dbfabca27537217b763d7783323158a37677ab`).
Verification adequacy: adequate. The reviewer independently ran both focused files with `-n 0`: 69 passed.

Local `agent-workflow-check`: all Work Record predicates pass. The only remaining blockers are `risk.redline_findings_available` and `behavior_contracts.redline_evidence_complete`, which need the Redline verdict artifact produced in CI.

## Correction: full-suite test failure

- Full non-slow run on the reviewed revision: exit 2, 7415 passed / 1 failed / 16 skipped / 2 xfailed. That result stays failed. The receipt is kept locally in an ignored build directory. Sole failure: `tests/test_relay_trace_worker.py::test_trace_refused_write_warns_once_without_identifiers`. Under INFO logging, `caplog.records` contained the writer's normal INFO `relay_trace_lifecycle outcome=ready` record; `close` can add an INFO record too. Test defect only; product logic unaffected.
- Test-only correction: the test now forces `caplog.set_level(logging.INFO, logger="app.relay_trace")`, so lifecycle INFO records are always captured. It asserts at least one INFO record exists. At both assertion points it compares only `app.relay_trace` records at WARNING or above. The exact warning sequence, explicit-False-only cases and no-identifier oracle are unchanged. No product change.
- Targeted run, serial: `tests/test_relay_trace_worker.py -q -n 0` gave 14 passed.
- Changed test file blob: `git hash-object tests/test_relay_trace_worker.py` = `2f251de0a0a6a73848d1f984380ed685495ea268`; `git diff -- tests/test_relay_trace_worker.py | sha1sum` = `d341bf1302e75745ecac0954851acb7c576b6cf4`; `app/relay_trace.py` is unchanged from the reviewed revision.
- The full suite was not rerun. The correction is test-only, the unchanged busy-gate E2E test passed in the full run, and the corrected worker file passed with INFO capture forced. Hosted PR checks run the suite again.
