# Allow equal clock ticks in the shared Relay capacity test

Source: [#396](https://github.com/rore/Pallium/pull/396). Base:
`e73531d8057a16ae7dbfd6df5bf2b0c57e1e3d99` ([#441](https://github.com/rore/Pallium/pull/441)).

<!-- agent-workflow:start -->
**Outcome:** The shared capacity test accepts equal clock ticks while still requiring a confirmed ACK before releasing held polls.
**Target:** `test_shared_wake_admission_preserves_ack_under_poll_and_projection`.
**Scope:** One timestamp comparison in `tests/test_relay_capacity_isolation.py` and this Work Record.
**Constraints:** Preserve every other assertion and all fixture and runtime behavior. No other draft hunks, local full run, or service operations. The manager owns ordinary PR publication and hosted validation.
**Completion criteria:** Equal ticks pass the comparison; reversed timestamps still fail. All six affected cases retain the real ACK confirmation, completion-event, release-event and durable-state checks.
**Requirement baseline:**
{"source":"roadmap/features/add-wake-first-relay-delivery.md","outcome":"The shared capacity test accepts equal clock ticks while still requiring a confirmed ACK before releasing held polls.","scope":"One timestamp comparison in `tests/test_relay_capacity_isolation.py` and this Work Record.","constraints":"Preserve every other assertion and all fixture and runtime behavior. No other draft hunks, local full run, publication, or service operations.","completion_criteria":"Equal ticks pass the comparison; reversed timestamps still fail. All six affected cases retain the real ACK confirmation, completion-event, release-event and durable-state checks."}
**Behavior changes:**
[{"target":"task-context.constraints","classification":"equivalent","before":"Preserve every other assertion and all fixture and runtime behavior. No other draft hunks, local full run, publication, or service operations.","after":"Preserve every other assertion and all fixture and runtime behavior. No other draft hunks, local full run, or service operations. The manager owns ordinary PR publication and hosted validation.","reason":"Move the independently reviewed and tested comparison from local handoff to ordinary hosted validation without changing the task outcome or caller behavior."}]
**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:add-wake-first-relay-delivery"}],"pull_requests":[]}
**Risk:** Routine
**Complexity:** Simple
**Reason:** Redline blue paths only. This test is outside the protected behavior-contract paths.
**Approach:** Port only the independently reviewed `ack_worker_entered <= polls_released` comparison from #396. The real ACK return and `ack_finished` are asserted with `release` still unset; the clock comparison checks that the samples do not run backward.
**Verification:** Run all six parameterizations of the exact shared capacity test. Inspect the one-line diff and run the whole-change selector and local Redline and Agent Workflow checks. The manager owns ordinary hosted validation.
**State:** Ready for review
<!-- agent-workflow:end -->

## Evidence reuse

#396's prior independent review accepted the causal ACK ordering change.
Its full manual qualification still failed. Only the comparison is
carried forward; no prior full run qualifies the merged #441 composition.

## Implementation and verification

The test diff changes only `<` to `<=`. Test Git blob:
`5959b6a9fcac58cd0232615dc4d1d5091132fd3b`.
On isolated Windows CPython 3.13.14, all six parameterizations of
`test_shared_wake_admission_preserves_ack_under_poll_and_projection`
passed. The exact ACK, release, claim and durable-state assertions remain.
Private JUnit report SHA-256:
`145b124378b1a33fe61eba5fe251a2a010d5e84ee5a01bfa7378ced73d4e2307`.
Diff, import boundaries, Redline and local Agent Workflow checks passed.
The selector requires the full lane. The assignment leaves that lane
to ordinary hosted CI selected by the manager.

## Handoff

The manager verified the exact one-line diff on `e73531d8` and its
unchanged causal and durable-state checks. Reuse #396's independent
review for that identical comparison. The six focused passes support
ordinary hosted validation; full qualification remains pending. The
draft #396 branch and its failed evidence are retained.
