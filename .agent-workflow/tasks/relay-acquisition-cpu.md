# Split Relay acquisition timing in the hosted reply-chain test

<!-- agent-workflow:start -->
**Outcome:** For a native Relay acquisition refusal in the selected hosted reply-chain test, show which measured layer consumed wall time and same-thread CPU.

**Target:** The existing GitHub Actions acquisition failure report for `tests/test_cross_container_relay_e2e.py::test_cross_container_reply_chain_and_bounded_backlog_continuation[semantic]`.

**Scope:** Extend `tests/codex_wake_setup.py` and its `tests/conftest.py` fixture binding. Add a focused recorder control in `tests/test_sqlite_write_retry.py` and use this Work Record.

**Constraints:** Limit split timing to the verified node in an already authorized Linux CI lane. Preserve native deadlines, original assertions, SQL execution and exception behavior, and the existing cap of four failure reports per fixture. No product code, GC instrumentation, additional node, workflow change, standalone Linux rerun, or environment change.

**Completion criteria:** On an eligible typed pre-yield refusal, the existing bounded report separates session connection and pool checkout from setup execute and the nested driver-call proxy, with paired wall and same-thread CPU for each observed span. It explicitly identifies missing or incomplete observations. Successes, semantic setup, unrelated engines and other nodes produce no split failure report. Instrumentation preserves one call and its original result or exception and is removed at fixture teardown.

**Requirement baseline:**
{"source":"roadmap/features/add-wake-first-relay-delivery.md","outcome":"For a native Relay acquisition refusal in the selected hosted reply-chain test, show which measured layer consumed wall time and same-thread CPU.","scope":"Extend `tests/codex_wake_setup.py` and its `tests/conftest.py` fixture binding. Add a focused recorder control in `tests/test_sqlite_write_retry.py` and use this Work Record.","constraints":"Limit split timing to the verified node in an already authorized Linux CI lane. Preserve native deadlines, original assertions, SQL execution and exception behavior, and the existing cap of four failure reports per fixture. No product code, GC instrumentation, additional node, workflow change, standalone Linux rerun, or environment change.","completion_criteria":"On an eligible typed pre-yield refusal, the existing bounded report separates session connection and pool checkout from setup execute and the nested driver-call proxy, with paired wall and same-thread CPU for each observed span. It explicitly identifies missing or incomplete observations. Successes, semantic setup, unrelated engines and other nodes produce no split failure report. Instrumentation preserves one call and its original result or exception and is removed at fixture teardown."}

**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:add-wake-first-relay-delivery"}],"pull_requests":[]}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** The recorder's paths are Redline blue. The combined #439 change includes the separately reviewed Hermes adapter and inherits its Elevated floor. The test-only wraps need review for correct timing boundaries, exact delegation and coexistence with the semantic-clock fixture.

**Discovery:** On [#439 Linux 3.12, attempt 2](https://github.com/rore/Pallium/actions/runs/45837429813/job/139980717771), the final claim in the reply chain used the native budget after the two semantic setup registrations. `setup_pragma` took 1,394 ms; acquisition and failed-entry cleanup measured 1,394.783 ms wall and 1,385.589 ms thread CPU, with no native SQLite error recorded. These totals do not isolate checkout, SQLAlchemy or the driver. The failing node, shared fixture, observer and acquisition helper are unchanged between `fb5f891a` and base `cfb5b5ae`.

**Material assumptions:** The fixture owns the Relay engine and its pool and dialect for the test. SQLAlchemy's normal driver path calls the dialect's `do_execute`; a bypass, unsupported binding, missing sample, overflow or incompatible clock leaves coverage incomplete. The native path is recognizable by the live `sqlite_queue.time` module; `relay_admission_clock` replaces it during semantic prerequisites. This observer measures bracket timing, not the physical cause of a stall.

**Plan:** Invoke Agent Workflow before any source edit. After independent plan review, keep the existing `observe_relay_acquisition_failures` entry point and report. Let `client` opt into split timing only for the exact node on GitHub Actions Linux. Install fixture-scoped wrappers that delegate to captured originals once, and record only while this fixture's native `_begin_relay_immediate` entry is active on the same thread. Time `Session.connection` for the bound Relay session and `Pool.connect` for its engine, then `Connection.execute` for the acquisition's explicit setup busy-timeout PRAGMA and the matching dialect `do_execute` inside that call. Filter any shared method by both the active acquisition and the exact fixture binding. Exclude timeout restores, raw connect-hook SQL from the setup bracket, and all work after the body is admitted. Keep a bounded list of paired spans; add only fixed labels, durations and completeness status to the existing refusal report. A single bounded fixture-arming marker may distinguish a non-reproduction from absent coverage. Release local capture on yield or unwind, and restore wrappers with the fixture's monkeypatch finalizer. Leave GC and any second node outside this first slice.

**Verification plan:**
- Correct brackets, pairing, and exclusion of setup restores and unrelated invocations -> focused recorder control in `tests/test_sqlite_write_retry.py`, using the real fixture-owned SQLite/SQLAlchemy call path.
- Original result and exception propagation, teardown, privacy, incomplete samples, and four-report cap -> focused control plus existing acquisition diagnostic controls in the same file.
- Exact node/CI gating and unchanged semantic setup -> focused gate control and the unchanged reply-chain assertions on the next authorized Linux lane. Use its existing job runtime metadata, mark any missing coverage, and stop after one legitimate run without a matching refusal. The manager will select the Linux composition after plan review; this checkpoint authorizes no execution.

**Plan review:** Agent technical review: the Pallium architect gave GO on plan blob `5f8b50b557a94c150ae5440d91cc805f84e8231a`, verified and relayed by the manager. A checkout that expires can skip setup entirely; classify only the bounded setup PRAGMA, never the first observed PRAGMA by position.

**Approvals:** Not required at this risk level. The manager authorized the reviewed test-only implementation and focused controls; full-suite execution and publication remain outside this assignment.

**State:** Ready for review
<!-- agent-workflow:end -->

## Review handoff

Base `cfb5b5ae876e96a3c9aada8b461e43af8a7f60fa`; branch
`test/relay-acquisition-cpu`. The plan review preceded source edits. It checked whether
the chosen wrappers can isolate the checkout and driver brackets without
altering SQLite dispatch, and whether an unmatched span stays visibly
incomplete. Preserve the original failure; do not use a passing control
or an unobserved lane as a diagnosis.

## Implementation

Limit edits to `tests/codex_wake_setup.py`, `tests/conftest.py`,
and focused controls in `tests/test_sqlite_write_retry.py`. Keep the
original four-report budget and leave a missing setup span visible when
checkout expires and only the timeout restoration runs.

The spans record paired wall and thread CPU durations, with child spans
linked to their enclosing calls. Missing spans, unpaired calls, missing
clock samples and overflow cannot produce a complete observation. Checks
also catch a retry whose final checkout had no setup call. The exact
Linux CI fixture adds a bounded JUnit `armed` property; the existing
failure report carries the split. It reports the dialect call as a
driver proxy, not native CPU attribution.

## Evidence

Windows CPython 3.13.14, SQLite 3.53.1, SQLAlchemy 2.0.51: the full
`tests/test_sqlite_write_retry.py` file and the exact reply-chain node
passed together, 84 tests. The new controls exercised real SQLAlchemy
connections and SQLite with ordered observers and simulated refusals.
They cover restoration-only and partial retry, original result/error,
scope, missing clock samples, overflow, privacy and the four-report cap.
The Windows reply-chain compatibility run did not activate Linux CI capture.

`focused.xml` SHA-256:
`b5dbef588af8ae7b1c8593a2a338dd56ba5f4c4c95f9ef069c8232c7cda0beba`.
Local workflow, import boundaries and diff check passed. The whole-change
selector requires the full lane, which this assignment did not authorize.

## Result review

Agent technical review: The independent architect accepted the exact
recorder and the direct fixture caller correction for normal CI in
[#439](https://github.com/rore/Pallium/pull/439).

Reviewed revision: base `cfb5b5ae`; recorder `d275c34a`, fixture
`f06b4a4a`, recorder controls `ee264960`, cleanup fixture `3b503209`.

Verification adequacy: The earlier 84 focused passes still apply.
The previously uncovered direct fixture caller now passes `request`;
all 14 cleanup cases passed with the original assertions. The manager
verified the reviewed blobs and no overlap with #439 before separate
test-only composition in its next ordinary CI. The Linux capture
and full qualification are pending. A green job without a matching
refusal establishes no slowdown diagnosis.

### Direct fixture caller correction

Independent review found that `tests/test_client_fixture.py` calls
`conftest.client.__wrapped__` directly. The new `request` fixture
parameter is injected for ordinary pytest callers but must be passed
explicitly here. A repository-wide search found no other direct caller
of this fixture. The manager authorized this test-only scope addition:
pass the existing pytest request through, retain all cleanup assertions,
and rerun only the 14 cleanup parameterizations. The other three
tested files stay byte-identical.

All 14 cleanup cases passed on Windows CPython 3.13.14.
`tests/test_client_fixture.py` Git blob `3b50320953971aae723db2063b7263400704a8b5`.
Private `direct-fixture/result.xml` SHA-256:
`c6766f63218c421fdab82936f06e2662149d81c6376a43d242fed2568a3f93df`.
The three original source/test blob IDs still match the 84-pass evidence;
that run was not repeated. The amended uncommitted diff is back with the
manager for review. Full qualification remains pending.
