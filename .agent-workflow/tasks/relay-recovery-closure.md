# Relay recovery closure

<!-- agent-workflow:start -->
**Outcome:** Relay recovery gaps remaining after PR286/288 are explained and fixed, with installed native-host acceptance instead of simulated transport alone.

**Target:** Pallium Relay.

**Scope:** Existing native custody, wake recovery and hook delivery paths; historical zero-claim backlog diagnosis; bounded dedicated-session fault qualification; related tests, operations documentation and canonical roadmap.

**Constraints:** Preserve active-claim exclusion, committed-ACK terminality, authenticated custody, exact scope/endpoint/generation fencing, bounded retries and protected behavior contracts. Do not interrupt active user chats, delete or falsely ACK backlog, use manual recipient turns/receive as automatic recovery proof, or install from a development worktree. No speculative transport redesign or new dependencies.

**Completion criteria:** Installed dedicated native-host journeys recover the same original and later delivery after claim-response loss, failed ACK and lease expiry, including scope move; committed ACK response loss never repeats delivered payload. Lost-notification and restart recovery need no fresh sender call or manual recipient action. Historical backlog causes are established and remedied or an exact external limitation is reported without claiming closure. Required reviews, whole-change validation, PR CI/review, merge, both stable-main syncs and installed health checks pass; manager receives the final bounded evidence and worktree is retired safely.

**Requirement baseline:**
{"source":"user:db619a2b-6d86-4ebc-b5c5-b9a8453116d8","outcome":"Relay recovery gaps remaining after PR286/288 are explained and fixed, with installed native-host acceptance instead of simulated transport alone.","scope":"Existing native custody, wake recovery and hook delivery paths; historical zero-claim backlog diagnosis; bounded dedicated-session fault qualification; related tests, operations documentation and canonical roadmap.","constraints":"Preserve active-claim exclusion, committed-ACK terminality, authenticated custody, exact scope/endpoint/generation fencing, bounded retries and protected behavior contracts. Do not interrupt active user chats, delete or falsely ACK backlog, use manual recipient turns/receive as automatic recovery proof, or install from a development worktree. No speculative transport redesign or new dependencies.","completion_criteria":"Installed dedicated native-host journeys recover the same original and later delivery after claim-response loss, failed ACK and lease expiry, including scope move; committed ACK response loss never repeats delivered payload. Lost-notification and restart recovery need no fresh sender call or manual recipient action. Historical backlog causes are established and remedied or an exact external limitation is reported without claiming closure. Required reviews, whole-change validation, PR CI/review, merge, both stable-main syncs and installed health checks pass; manager receives the final bounded evidence and worktree is retired safely."}

**Risk:** High

**Complexity:** Large

**Reason:** Native custody is a security-sensitive process boundary and recovery may touch persisted Relay lifecycle. Multiple installed failure boundaries require distinct evidence.

**Discovery:** Prior PR286 and PR288 are merged; both stable clones last verified at 525df5bb. Existing caller-surface tests cover claim/ACK faults, scope move and restart but simulate Desktop. Installed 6b49ff75 proved a missed-hook retry and backlog receipt after restart, explicitly requiring a fresh sender Relay read to restore custody. Historical 30 pending deliveries all had attempts=0: 22 current Dictation manager, eight older recipients. The seven pre-current-turn deliveries arrived during its prior active 12:21-12:54 UTC turn. Native rollout plus live SQLite prove the real 13:32:21 hook claimed and ACKed an earlier 1,125-character message; its 2,400-character output cap prevented claiming the next 1,101-character message plus headers. Thus that turn did not miss the hook; the idle 12:54-13:32 interval remains unexplained. The worker and approved design deliberately require a fresh actual MCP request to re-enroll after service restart; no supported child-lifetime grant exists. No safe existing per-session native fault switch exists; additive project hooks would race the global hook. A temporary exact-session/delivery-gated hook shim is feasible with reviewed isolation and restoration.

**Material assumptions:** The original service-epoch authority did not permit saved-caller re-enrollment; the user explicitly approved same-live-child admission on 2026-10-06 after that boundary was explained. The resumed smart plan review approved the narrow continuity checks below. Dedicated test-session faults require reviewed instrumentation preserving all nonmatching hook behavior, consuming one bounded exact-message fault and restoring verified installed bytes. Manager confirmed no overlapping production, roadmap or service work. An existing MCP child does not reload updated Python source on service restart.

**Plan:** First invoke the /agent-workflow skill to create the Work Record and classify risk before any code edit. Discovery first: reconcile manager and current main/installation, inspect existing worker custody and all callers, determine safe installed fault qualification and historical backlog causes. Write the narrow implementation plan and obtain a clean-context smart technical review before source edits. Delegate bounded read-only diagnosis to cheaper agents; retain custody/security decisions and combined installed acceptance. Reuse PR286/288 evidence and existing fixtures. Implement only demonstrated root-cause fixes, run focused and selected whole-change validation, obtain smart independent result review, resolve PR findings, merge under standing user authority, sync/restart/verify installed service, qualify exact native journeys and deliver evidence to manager. Stop implementation on a failed safety assumption, not on merely passing simulated tests.

**Verification plan:** Same-child reconnect and unchanged security/legacy behavior → test_codex_worker_reconnect.py, test_codex_retained_continuity.py, genuine Windows cross-epoch channel test and existing retained/native/MCP suites. Fault recovery → dedicated installed-host exact delivery traces, actual hook emission/ACK and payload-specific recipient responses, separately from simulated test_codex_wake_retry_edges.py. Historical backlog → read-only exact delivery traces and native rollout metadata, with unrecoverable gaps left explicit. Release readiness → whole-change scripts/test-plan.py, full non-slow suite, workflow/Redline/import checks, smart result review and PR CI. Installed sync → stable commit equality and wrapper restart followed by /health, /status, /debug/queue/health and embedding_provider_ok.

**Plan review:** Agent technical review: /root/ci_fixture_plan_review (gpt-6.1-sol/high), approved the unchanged-scope test-only correction at 29a27485 before source edits; details and preserved requirements are in the CI diagnostic fixture correction plan below. Earlier reviews remain valid for unchanged released source: /root/closure_plan_review at 320cc9d5 approved the human-authorized same-live-child continuity, and at 9ea12eba approved existing-busy contention with no replay or custody changes. Source changes do not hot-reload existing MCP children.

**Approvals:** Approved by user 2026-10-06: "yes, of course, that's the desired state" after the exact question allowing the same still-live previously authenticated MCP child to reconnect automatically after service restart, preserving identity checks and no resends. Prior scope approval: "so can you complete the cycle so we don't leave open ends?". Standing authority: "you can push pr and merge if all is ok" and "i approve what is needed". This authorizes the stated child-lifetime admission only, not new-child takeover, changed host identity, unresolved-I/O replay or active-chat interruption.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

### CI diagnostic fixture correction plan, 2026-10-07

Invoke /agent-workflow before edits (completed). Resume this record and retain
High/Large and the unchanged requirement baseline. Intended files are this
record, tests/test_codex_relay_fault_harness.py, tests/test_agent_relay_hooks.py,
and, only if needed to preserve deterministic body-deadline coverage,
tests/test_hook_deadline_safety.py. All are policy-blue; no production, protected
behavior contract, CI, configuration, API or installed-hook changes are planned.
PR297's independently owned OpenCode guard stays separate and held while CI is red.

PR297 attempt1 failed the unchanged observer concurrent-admission ledger read:
zero relay_response rows. A controlled delayed existing writer reproduces this
for both hooks; after append completion each ledger contains exactly one response.
The observer deliberately returns after at most 50 ms of daemon logging, whereas
the fixture reads immediately. Preserve that production bound and fail-open
behavior. Add one test-only completion-event reader around the existing append
helper; all observer assertions needing complete evidence wait for completion
with a finite test deadline. Keep failed/blocked logging tests independent. Add
a controlled delayed-writer regression proving unchanged turn results, one-shot
admission, reference restoration before append and eventual complete evidence.

Attempt2 instead failed the unchanged real HTTP fragmented-response case:
one attempted fragment versus three, with hook timeout at 2272 ms and a block
decision. Later trace/state assertions did not execute in that failing run.
The server calls the real TestClient endpoint before sending bytes and attempts
three fragments across 2.2 seconds, longer than the hook's 2.0-second budget.
Exact serial rerun passed once; endpoint delay versus runner scheduling is not
attributed by the original log. Correct only unsupported server-completion
assumptions after client cancellation. Retain the existing hook deadline,
elapsed bounds, exact delivery attempts/state/trace and no-emission assertions;
also preserve explicit nonvacuous slow-body deadline coverage using the existing
deadline fixture. Do not merely drop the fragment check, raise production
timeouts, skip a test, fake a successful response or treat a serial pass as cause.

Verification: deterministic failing-before/fixed-after observer read; exact
affected tests serially, then affected files; whole-change test selector and
one full non-slow lane, unchanged behavioral contracts and workflow checks.
Clean-context smart plan/result reviews precede implementation/release. Reuse
standing approved diagnostic/test scope; any changed product requirement or
new boundary returns to planning. No service restart, live fault, consumer
configuration change or receipt fallback occurs during this test-only work.
Before merge reconcile the original and retry CI failures and preserve their
logs. After green reviewed merge, coordinate both stable syncs, consumer-owned
hot-reload acceptance, and the required safe-window installed wrapper restart
with health checks. Installed recovery qualification remains separately open.

Implementation update, 2026-10-07: tests/test_codex_relay_fault_harness.py now
wraps the real observer append with a test completion event and waits before
successful-ledger assertions. A controlled writer opens the evidence file and
pauses; both concurrent calls preserve their original response objects, one
fault admission is consumed, undo restores all references and returns within
the bound, and an immediate read is empty until the writer is released. The
test then waits for append completion and requires one response event plus a
captured terminal event. Failed/blocked logger coverage and the production
50 ms wait remain unchanged. Verification: the exact prior and new concurrency
nodes passed, 4 passed in 5.37s; the complete
tests/test_codex_relay_fault_harness.py file passed, 90 passed in 10.30s.

Current isolated base: f31ac14186943cdc60ce10dbb37e26c42a3496bc on
feat/relay-recovery-closure. Agent technical plan review:
/root/ci_fixture_plan_review (gpt-6.1-sol/high), approved narrowly at
29a27485a0a62382b28370652a869abe7f21b859. No requirement change or new
authority is introduced; the existing approved diagnostic/test scope applies.
Use a finite completion Event around the real append for every observer reader
requiring complete evidence; retain independent blocked/failed logger checks.
The controlled delayed writer must prove bounded undo and restored references
before release, then exactly one response and complete terminal evidence.
Remove only unsupported canceled-client server-write completion assumptions;
retain every hook elapsed/state/trace/no-emission assertion. Extend the existing
response fixture with controlled partial-byte progress followed by an incomplete
blocked body, asserting progress before return, unfinished reader, unchanged
1.5-second outer join and unavailable result. Release and join in finally.
This deterministic model complements, not replaces, real HTTP coverage.
No test source changed before review. Native ownership/recovery acceptance
and earlier unexplained incidents remain open outside this resumed CI slice.

Root acceptance checkpoint: the completed source diff was independently approved
by /root/ci_fixture_plan_review with no correctness, coverage or overengineering
finding. Frozen test blobs are ec6838b48467fe0ed76da1d02e89b0265f21b5ee
(observer), 2c188d04e574a31a3f881d55e5613eb21bb6c05a (real HTTP), and
10ad8d270a9bcc46d44a0763b6c5b010f7d28c7b (deadline). The observer file passed
90 cases in 10.30 s; both deadline files passed 126 cases in 29.94 s with
confirmed exit zero. A temporary in-memory one-second extension of the outer
fence was rejected by the strengthened partial-body regression. Two earlier
worker file runs omitted completion metadata and are not accepted as evidence.
Root started the one required full non-slow serial lane at 65c74b37 with exactly
these dirty test blobs; session 83768 is running. No production source, protected
contract, service, hook configuration or consumer settings changed. Full-suite
result, final adequacy review, separate human result review and PR CI remain
gates. PR297 stays separately owned and unmerged pending this correction.

Separate human result review received on 2026-10-07: the user selected
"Approve result after all gates pass" for request
call_8e4f89bb47254a48be1569627dff647a. The presented result states that observer
tests await the real ledger writer, HTTP tests preserve deadline/delivery-state/
no-emission checks without requiring server writes after cancellation, partial
body deadline coverage is strengthened, no production/settings change occurs,
smart source review and 216 affected tests passed, and full validation is still
running. Merge is conditional on full validation, final review and green CI.
The broader installed Relay recovery acceptance explicitly remains open.

### Passive exact-session diagnostic plan, 2026-10-07

First invoke /agent-workflow and classify risk before code edits (completed).
Resume this record, not a new workstream. Intended paths are
scripts/qualify_codex_relay_faults.py, tests/test_codex_relay_fault_harness.py,
docs/context/operations.md, this record and the canonical roadmap. Normal applicability applies; all these
paths are blue, but the umbrella stays High/Large because instrumentation runs
at an installed claim/emission boundary. Original requirements remain unchanged.
Manager's substantive delivery relay-delivery-0abc65b6472c46c08892daa49cdb7127
continues the existing user-authorized investigation, not new takeover authority.

Existing-safe-diagnostic limit is now concrete: read-only indexed host-log queries
restricted to 08:36-08:39 UTC examined 287 Pallium/MCP rows with fixed diagnostic
patterns and found no first-hook transport category. The single hook-runtime
warning is an after-agent legacy-hook warning at 08:37:13.735055400, not evidence
of SessionStart failure. No raw log bodies, payloads or tokens were printed.
SessionStart has no claim-to-emission event recording; the existing wake recorder
requires exact configured-script identity. Do not forge UPS events for SessionStart.

Smallest proposed change: add a passive opt-in observe mode to the reviewed
qualification helper, reusing its exact session/message manifest, finite expiry,
private case directory, two named hook targets, atomic one-shot reservation,
unchanged configuration and checked finally-safe restore. No new public API,
production hook behavior, dependency, registry, source grant or fault is added.
Only the first eligible exact-session relay_turn reserves observation; nonmatching,
expired, malformed and already-used cases call the original unchanged. Record
whether the expected message was actually observed; never label unrelated context
as a payload emission. The private manifest supplies planned message identity;
delivery identity is recorded only when observed in the real response.

Observe actual relay_turn and its POST /relay/turn callback, actual common
session-state write result, module.format_relay (the hooks use imported aliases),
module.emit_context/common.emit_utf8 and module.acknowledge_relay. Save/restore
every patched reference and preserve original arguments, object identity,
exceptions, stdout bytes, requests and ACK membership. Record only fixed stage,
hook kind, result class/target-presence, bounded elapsed time, timestamp and
validated actual delivery ID. Never record args, raw results, text, paths,
exception messages, claim tokens or private capabilities. No receive/resend.

Buffer at most 64 fixed-schema events / 16 KiB in RAM. No diagnostic filesystem
I/O in claim/render/emit/ACK stages. After restoring wrappers in finally, perform
one best-effort private-ledger append on a daemon thread with at most 50 ms wait;
failure, blocked storage or incomplete evidence never changes processing and
must not be treated as proof. Reuse existing case files and fail-open behavior;
do not introduce a background service or durable delivery ledger. Review may
choose a smaller safe bound or an existing equivalent facility.

Verification before live use: actual backed-up SessionStart and UserPromptSubmit
through HTTP/hook caller-surface fixtures, original stdout/HTTP operations equal
with and without observer; claim response unavailable, malformed/post-response
state write rejection, render skip, actual write/flush failure, failed ACK and
success each produce correct stage metadata. Prove no payload/token leakage,
exact-session/message targeting, expiry and already-used exclusion, concurrent
one-shot admission, bounded/blocked/failed logging and complete restoration on
normal exit, SystemExit and exceptions. Preserve all existing fault modes.
Run exact file first, affected files, whole-change selected checks/full lane,
independent smart result review and normal PR/CI/deployment before installed use.
Then coordinate shared service operations and one fresh dedicated native-host
observational case. No fault is armed now. Success is not historical attribution;
native ownership and restart qualification remain separate open requirements.

Agent technical plan review: /root/deployment_evidence_review
(gpt-6.1-sol/high), at f6d0074c, approved this narrow observer with required
conditions: atomic reservation before original relay_turn; no observed target
means no claim/ownership/emission proof; transactional setup and finally teardown,
same original exceptions/objects with no replay; actual imported aliases and
write/flush versus ACK distinguished; bounded snapshot only after restoration,
incomplete writes never evidence of completeness. Add explicit partial-setup,
teardown, overflow and unrelated fallback-output coverage. Existing standing
human reliability/instrumentation approval covers these unchanged boundaries;
this review does not claim historical causality or installed acceptance.
Delegate helper-only implementation and test-only verification separately to
the cheaper agents; root owns this record, integrated review and shared live ops.

Implementation checkpoint: helper-only and test-only work is complete in the
isolated checkout. Root's review corrected premature logging inside ACK, wrong
output-alias forwarding, target binding and setup/teardown fail-open handling.
Independent source review found an unfenced daemon logger exception; its exact
fix is conditionally approved at helper blob
8dded7ffa65c765a34afeec035e71f62df25c543. Test blob
03c2ee34aeda478c7f20c71b04c6f01968e1c327 passed 84 focused cases without warnings;
the affected observer/recovery/deadline suites passed 132 cases in 28.75s.
Real HTTP/SQLite and hook paths are covered; native transport is still simulated.
The whole-change selector requires the full non-slow lane, now running. Final
independent evidence review, separate human result review and PR CI remain gates.
No observer is installed or armed; no service or ownership operation occurred.

Final evidence review requested the planned teardown-failure check. The test-only
delta preserves result/exception identity, forbids replay and diagnostic output,
and requires an incomplete terminal observation on rejected restoration. Four
new cases passed; all 88 focused cases passed in 10.21s at test blob
6890d79f2978726dd0ab7be7e04b18c563e5ef12. An identical shadowed test definition
was removed. The helper remains unchanged at 8dded7ffa65c765a34afeec035e71f62df25c543.
The first full run at 5ac63de7 stopped: 2,307 passed, two skipped, one expected
failure and one failure in the unchanged legacy-pin Codex hook test (263.54s).
Its exact serial last-failure rerun passed in 1.86s. No deadline or assertion is
weakened; rerun the full lane with two workers on the final frozen change.
Import boundaries passed (eight kept, zero broken). Fresh Redline is Blue;
workflow has no blocking findings and retains the known 9dfe4839 commit-order
advisory, which concerns the earlier documentation reconciliation.
Documentation alignment: the existing operator guide listed only fault modes.
Document passive observation, admission-before-claim and incomplete evidence
semantics in that same guide. This stays inside the original related operations
documentation scope; no source, risk, authorization or acceptance boundary changes.
The two-worker full run also stopped: 2,152 passed, two skipped, one expected
failure and one failure in the unchanged moved/restarted ACK-response-loss
recovery case (457.64s). Its later delivery was claimed but its second hook
emitted only scope; the exact serial last-failure rerun passed in 1.98s.
HTTP 200 does not explain the missing payload, so timing/I/O sensitivity versus
test-state leakage remains under read-only investigation, not a proven cause.
Run the complete suite serially without weakening deadlines or assertions.
These failed runs are not passing validation or installed incident attribution.

The complete serial lane passed: `python -m pytest tests/ -x -q -n 0`
reported 6,316 passed, 34 skipped, 479 deselected and two expected failures in
1,534.43s. It started at 616af2a5; only record-only d6787df2 was committed during
the run. Helper/test blobs above remained frozen. Both parallel failures stay
unexplained: three legacy HTTP calls share a 0.75-second budget, while the later
claimed delivery could lose emission at state-write, response validation or
formatting. No exact failing stage was captured. Serial success does not resolve
those causes; any CI recurrence requires investigation, not isolated-rerun closure.
Ready for review applies only to this bounded observer release, not the original
umbrella completion criteria. No observer, fault or service operation is armed.
Skill feedback trigger 1 dropped: these application-test failures are not an
Agent Workflow instruction or implementation failure.

Manager reply relay-reply-d4ef666f95cb93deb63e1a615f58b9201eb843f5124916555e41c2b26a42bab9
reported the exact existing-diagnostic limit and passive implementation scope.
Its trace confirms hook ACK at 09:23:02.762694 UTC, attempts=1 and no reported gap;
this establishes receipt at that boundary, not manager acceptance or completion.
Manager progress message relay-msg-aaeeec489615487f9722c028a6500dc3 was also
hook-ACKed at 09:51:43.074505 UTC, attempts=1 with no reported trace gap;
this is receipt evidence only.

Post-release contention follow-up at 385a8a94: worker caller-surface regression
failed only its positive busy-preservation case (11 negative cases passed).
The genuine authenticated Windows source-pipe regression failed before source
edits: registration did not return within two seconds while dispatch held the
lock through two real kernel exchanges. It then lost the source and dispatch
failed peer-mismatch at owner-result. Desktop descriptor/catalog/results are
explicit fixtures, not the installed Desktop. Root applied nonblocking retained
maintenance/admission and reused the existing checked-service recovery result
to preserve only exact busy on unchanged admitted proof and resolved I/O.
No stream lock, identity check, durable fence or retry budget was weakened.
Initial focused worker/continuity/existing recovery run: 97 passed in 12.62s.
The whole-change selector requires full validation; fixed native and independent
smart result review are still in progress. Trigger3 dropped: the concurrency
fault belongs to Pallium, not Agent Workflow. Manager continuation notice
relay-msg-cc2a12bfbcfb4f8099757a384ad9a533 was saved; app-side manager response
restated the remaining acceptance gaps, without claiming overall closure.

PR291 Python 3.12 CI exposed a raw-HTTP fixture caller that asserted one-shot
success despite the route's structured retryable SQLite `relay_busy` response;
the exact node passed locally once. This follow-up is limited to
`tests/test_codex_retained_wake.py` and this record: retry the same message body
only for that exact response within fixed bounds, preserving the existing
concurrency, owner, recovery and restart assertions. No production or protected
behavior-contract change is planned.

Implemented the fixture's direct HTTP retry for one matching 503 only, bounded
by two attempts and a two-second retry-initiation budget; malformed responses,
other errors and out-of-budget Retry-After values stop. Existing worker and
outer-thread joins remain unchanged. Added real-route busy-once, exhaustion,
nonbusy, malformed-response and retry-after-budget checks.

2026-10-06: Normal workflow applies: intended app/native-hook/persistence paths are outside the documentation-only allowlist. Complete clean isolated checkout scope plus intended paths selects no exemption. Classified High/Large from the existing policy before any source change. Managed checkout: C:/Users/I347041/.codex/worktrees/relay-recovery-closure/Pallium; branch feat/relay-recovery-closure. State is returned to planning pending discovery and technical review, not awaiting another human approval. Root untracked .codex-remote-attachments/ is preserved.

Canonical roadmap: roadmap/features/add-wake-first-relay-delivery.md. Prior evidence remains in .agent-workflow/tasks/relay-recovery-round.md and PR286/288. Manager coordination message relay-msg-577e17962853494fb0eab430ca683cb9 saved; receipt and ownership confirmation pending.

## Evidence

### Fresh Minimap first-emission incident, 2026-10-07

Manager's substantive hook delivery relay-delivery-42c826b64469415fac9ba4f152d4821b
(message relay-msg-d6a06ec903664aebbebef6c750d12d4a) requested correlation
within this existing investigation. The incident is message
relay-msg-68d089abf546483a9914cfb13f005999 / delivery
relay-delivery-37b44d69123f47248934afc17f8907ae, recipient thread
01a0d7cf-2c64-7bb2-a87c-724dd1c405a2, provider-returned endpoint
relay-session-0936354f39ce4b61a967de3cd6c8cb7c and container
git:github.com/rore/minimap. Root exhausted both trace pages: first activation
prepared 08:36:21.693881 UTC, completed 08:36:26.745396 uncertain /
native_unavailable / submission_attempted / native_retry_safe=false.
The installed service's exact-delivery diagnostic at 08:36:25.781 UTC reports
timeout at owner-result, generation 6672. This establishes the native failure
boundary, not the later first-hook emission failure or source ownership.

First recipient turn 01a11581-c4a5-7d12-bc32-204c4792c664 started
08:36:28.485 UTC and ended 08:37:13.737. Its model explicitly reported claimed
without payload or ACK and made only a trace read, not receive/ACK/resend.
Read-only /root/contention_native_regression checked the 25 persisted rollout
records in that exact interval: no hook start/response/stdout/stderr, emission
or ACK-error metadata is retained. The file is
C:/Users/I347041/.codex/sessions/2026/09/25/rollout-2026-09-25T12-04-34-01a0d7cf-2c64-7bb2-a87c-724dd1c405a2.jsonl.
First emission and ACK cause remain unresolved; absence of retained diagnostics
does not establish whether stdout was written, rejected or never produced.

Second activation prepared 08:37:55.164188 UTC, with no completed event in the
bounded trace. The second recipient turn 01a11583-2ee0-7e31-af78-0e72816360f1
began 08:38:01. An authorized app fallback for the same assignment arrived in
that turn; the model recognized the late Relay payload and deduplicated it.
Snapshot attempts=2: claim 08:38:03.412662, ACK 08:38:03.796175 UTC.
Existing local hook telemetry independently records hook_started
08:38:02.340411, response 08:38:03.742811 (1119ms), payload_emitted
08:38:03.780806 and delivery_acked 08:38:03.892583 UTC. There are no matching
first-turn entries. This proves second-hook receipt, not autonomous recovery
without fallback, nor the first fault's cause. Trace completeness remains
best_effort despite no reported gap, pruning or truncation.

Original hooks/configuration hashes remain unchanged and host timeouts remain
eight seconds. No fault, service restart, recipient interruption, receive,
resend, ACK mutation or native-owner takeover was performed for this diagnosis.
Next bounded diagnostic: capture SessionStart's normal claim-response,
validation/state-write, rendering, emission and ACK outcomes through the existing
safe hook diagnostic path in a dedicated session. Preserve process/host timing
and exact delivery correlation without payload, tokens or private capabilities.
Any diagnostic code change needs its own narrow plan/review under this record;
do not replay the now-terminal incident or conflate native ownership with first
emission. Evidence-only bookkeeping stays blue, High/Large umbrella unchanged;
original criteria and roadmap queued state remain unchanged.

### PR291 release and installed qualification preparation, 2026-10-07

PR291 merged at 17f9304b0ee68081d7801075e507d97ac4909fe9 on
2026-10-07T07:58:38Z, from reviewed head
fdef3f0026d5efd2831f2a2097f849296a0d79f8. Fresh Python 3.12/3.13,
Windows smoke, CI result, Redline and Agent Workflow checks passed.
There were no unresolved inline findings. Separate human result approval was
verified directly in manager turn 01a1155c-e376-7791-8029-c20b76e5182e,
user message 01a1155c-f377-7483-9e50-66bed8ca6f8e ("approved"), then recorded
before merge at https://github.com/rore/Pallium/pull/291#issuecomment-6033607770.
The later UI approval names PR290 and is not substituted for this evidence.

Both stable main clones resolve to 17f9304b. The installed clone is clean;
the shared development clone preserves unrelated .codex-remote-attachments/.
The supported installed scripts/restart-service.ps1 completed successfully.
Independent /health, /status and /debug/queue/health checks passed:
embedding_provider_ok=true, ingestion.status=ok, recent_failures=0,
unclaimable=0. Actual global hooks.json and both installed hook hashes remain
unchanged. Health and deployment are not installed recovery acceptance.

Preparation used existing Pallium enrollment test thread
01a0e7dc-795e-7bf1-bf83-7d3dabe78903. Its 08:05 UTC pallium_status call
was an operator setup error: this plain tool does not enroll native custody.
The corrected single pallium_relay_trace read at 08:18 UTC succeeded for
terminal relay-delivery-c1de768876a64ce58392372bea16ed15, but no admission
diagnostic was visible and no new initial-registration log appeared.
The fresh process pair remains pinned: launcher 66028 created
2026-10-07T08:04:45.8739930Z; child 57916 created
2026-10-07T08:04:45.9550200Z. Process birth and successful reads do not prove
this child owns custody. A pre-08:03 registration log proves some admission,
not the current owner's identity or continued occupancy. Read-only source
inspection found no supported public owner-attribution or targeted handoff.
Do not infer a product failure, busy rejection or current owner from this gap.

Installed same-child restart qualification is blocked on verifiable source
admission/ownership. Manager records also contain no trusted current-owner
evidence. No case04 directory, fault wrappers or qualification messages were
created; the 15-minute window never started. All provisioning quiet requests
were explicitly released. No unknown process was stopped, no private
capability/handle inspected, no manual recipient turn/receive used and no
fresh sender read counted as automatic recovery. Six prior no-restart witnesses
remain valid; unattended restart, scope move, pre-hook notification loss and
eight historical zero-claim causal gaps remain open.

Evidence-only continuation invokes agent-workflow before edits. Exactly this
record and the canonical roadmap are blue; normal workflow applies because
Work Records are not exempt. Existing High/Large classification and original
requirement baseline remain unchanged. No new product promise or source edit.

Evidence-only verification: fresh whole-change selection chose the governance
lane; tests/test_test_plan.py, tests/test_ci_workflow.py and
tests/test_agent_workflow_ci.py passed 31 cases in 44.96s with --noconftest
-q -n 0. Fresh exact-diff Redline and Agent Workflow checks passed, as did
git diff --check. Independent read-only /root/deployment_evidence_review
(gpt-6.1-sol/high) found no actionable issue in the two-file delta against
17f9304b: original criteria are preserved, release and acceptance are distinct,
and unknown ownership is not asserted as a reproduced product defect.

Continuation check, 2026-10-06 18:13-18:20 UTC: both stable main clones remain
at 8c4f38a0; installed hooks and actual global hooks.json match their recorded
restored hashes. Health/embedding/ingestion and the live queue read remain ready.
Restart case03 is now expired with attempts=0 and an incomplete retained trace;
it remains a failed qualification, never a recovery witness. Manager notice
relay-msg-6a0280409dd54d14b7f9c8dd9033be42 was claimed and ACKed at
18:13:41.850723 UTC (attempts=1, no trace gap). This proves transport receipt of
the PR291/CI/open-acceptance update, not completion of the remaining work.

### PR291 retained-wake HTTP retry

Final local whole-change validation at 563b0f3f (same frozen test and production
blobs as the running working-tree start): `python -m pytest tests/ -x -q`
passed 6,269 cases, with 34 skips and two expected failures in 333.58s. Fresh
selection requires the full lane; import boundaries, Redline, workflow and
diff checks passed. Ready for review applies to the bounded PR291 release,
not the unresolved umbrella installed-acceptance criteria. Fresh CI and the
separate human PR291 result approval remain release gates.

Before helper correction, the deterministic actual-route busy-once node failed
on the expected `503 {code: relay_busy, retryable: true}`. After correction,
`tests/test_codex_retained_wake.py -k test_http_`: 8 passed, 147 deselected;
the full retained-wake file: 155 passed in 45.17s. The existing same-ID API
idempotency node passed (1 passed in 0.78s). The regression retains one delivery,
one native owner and the uncertain reservation fence; exhaustion creates no
delivery or owner. Test blob: `8cdfcbe66a622fcca305db76b1ee0aaa7673679e`.

### Installed release and acceptance, 2026-10-06

PR290 merged at 8c4f38a0d964f097d432b74b62517b5632fd0a0c after the
separate human result approval and green CI37499119320. Both stable main
clones are synchronized to that revision. The installed wrapper restart and
/health, /status and /debug/queue/health passed; embedding_provider_ok=true.
CodeRabbit's quota skip is not an additional technical review.

Six installed, automatically awakened deliveries passed with actual hooks and
payload-specific model replies: lost claim response original/backlog
6b283df7fe2c4c2e9eb2f8421257e9cd / b22ef53b6ebb48e19d7a904907ab8646;
ACK precommit original/backlog 378d00d65eba4c30bb1284a872487409 /
86be9c103ccc40468d7b043e95849f96; committed ACK response loss original/backlog
f46ffebbe433496b994f7708dfaf7f9c / fcb38eb6e2ae40568522f65503410f24.
All identifiers above have the relay-delivery- prefix. Claim-loss and ACK
precommit originals reached attempts=2; committed ACK stayed attempts=1 after
its old lease. No manual recipient turn, receive or resend counted as recovery.
These are NO-RESTART cases. Exact private one-shot evidence/backups remain under
C:/Users/I347041/.pallium/qualification/relay-recovery-closure-20261006.
All temporary installed hooks were restored and installed Git status is clean.

Restart case03, relay-delivery-68e3088a5d894c4ca8cc2f23f8e8d7c9, never claimed
before its qualification window: attempts=0, so no restart acceptance is
claimed. Initial native-unavailable became peer-mismatch at reopen. Smart
review identified a concrete concurrency hazard: service maintenance and
registration wait for the same custody lock that dispatch holds over multiple
separately budgeted three-second exchanges; the registering client has one
three-second total deadline. A timeout can dispose the source and clear saved
custody. The 17:23 overlap supports this lead but does not establish historical
causality. Return to planning: reproduce lock starvation and obtain a smart
review of bounded admission before any new source edit. Preserve the lock's
Desktop stream serialization and every identity/replay fence. Installed
restart, scope-move, pre-hook lost-notification and eight old attempts=0
deliveries remain unresolved. Operator-only UTC comparison mistakes were
corrected; they are not product bugs. Manager was notified through app fallback
because the native qualification deliberately excluded fresh sender MCP calls.

No new installed qualification is claimed. Source verification below does not
establish installed recipient consumption.

Full non-slow suite on source revision 940ebe6e: 6,239 passed, 34 skipped and two
expected failures in 412.79 seconds. Subsequent a9c38940 adds only a slow native
test (1 passed); the isolated ACK-evidence/private-control harness review delta
requires focused final verification and is not silently attributed to that run.
Import boundaries passed. Whole-change selector requires the full lane.

Agent technical result review: /root/closure_plan_review (gpt-6.1-sol/high).
Reviewed production revision: 940ebe6e, native blob
17b86575939be2bade67647d8ada7f91a0dabc2f and worker blob
761f6c519b13173d2f123d05dd0fc97864db6843; additional genuine Windows channel
coverage a9c38940. Verification adequacy: sufficient focused and native-channel
evidence for the source fix, with no remaining blocking production finding.
Installed Desktop receipt/restart/fault qualification remains unproven and does
not follow from either simulated MCP tests or kernel pipe coverage. The test
Desktop descriptor/catalog is a fixture, not the installed host.

Reviewer-confirmed lifecycle fixes preserve idle capability revocation, exclude
cancelled first registrations, recover a service-exit/request race without
replaying the original future/operation, and make unresolved cleanup denial
monotonic. Legacy adapters without continuity remain usable via fresh calls but
never acquire automatic recovery authority. MCP protocol cancellation did not
cancel its running server handler in the fixture; cancelled worker-Future
exclusion is tested directly rather than asserting unsupported MCP semantics.

Reconnect regression failed before the worker change through an actual FastMCP
request: one source client remained after the service epoch changed. New native
continuity tests passed 54 cases; existing retained-wake cases passed 147. Native
finite-mode slow suite passed 259 of 261 initially; both transport/timing failures
passed the exact-node rerun (2 passed). A finite capability-presence regression
failed during worker editing and is being fixed without changing the contract.
Smart result review is in progress; no release readiness inferred from these runs.

Admission approval notification relay-msg-24815cb3943d46a9ac291b8c160e4ec4 /
relay-delivery-84f633d5d1ea454dab7d1cb4bfcac556 was ACKed at
15:55:42.227466 UTC. This is hook receipt, not proof of manager action.

Read-only discovery: /root/closure_custody_discovery and /root/closure_fault_discovery (gpt-6-luna/medium), independently assessed by /root/closure_plan_review. Packaged SPEC was unavailable; reviewer read the available operating-mode and required checkpoint references rather than inventing one.

Native Dictation rollout reference: resumed session 01a0e2fc-c5b9-7c81-bce3-1c8c2ae35a1d. At 13:32:21.921 UTC the model received relay-delivery-4d0d946f75b54c7dacb058862e80d61e; live read-only SQLite records claimed_at 13:32:21.370893, delivered_at 13:32:21.638918 and attempts=1. Next relay-delivery-6e630c129fa647c4afe0ad09de0920c7 remains attempts=0. This corrects the prior assumption of a missed original hook on that turn, not the unexplained earlier idle interval. No payload bodies or claim tokens were printed from SQLite. No backlog mutations, recipient activation or service restart occurred.

## Admission decision required

Current: service restart discards registration; a fresh actual authenticated MCP request must re-enroll it.

Proposed: a previously admitted, still-live MCP child may recreate registration in a new service epoch using its captured actual caller pair, without another host request. This extends authorization lifetime from the service epoch to that admitted child's lifetime; all source/Desktop/capability identity, native schema, unresolved-I/O, shutdown and durable wake fences must remain enforced. It does not permit replay of Relay operations or owner submissions, a new child, changed capability or arbitrary historical session takeover.

Standing implementation/PR permission did not substitute for this exact changed admission requirement. The decision below preceded admission source edits. A safe host/MCP reload plan is required before installed worker qualification; do not interrupt active user chats.

2026-10-06 human decision received: "yes, of course, that's the desired state". The admission decision is resolved; planning now defines the smallest implementation under the unchanged safety constraints. No Task Context or protected-contract requirement is weakened.

## Resumed implementation plan

### Post-release contention plan

CI follow-up at 5da9b377: PR291 Python3.12 failed the existing concurrent
HTTP-send fence test on two explicit retryable relay_busy503 responses. Windows
smoke passed; other CI is still running. This fixture bypasses the production
MCP busy retry and asserts every first raw HTTP response is200. The error is
bounded pre-transaction SQLite backpressure, not registration contention.
Target the single tests/test_codex_retained_wake.py fixture caller: bounded
attempt/time retry only exact503/code relay_busy/retryable true, identical body
and stable messageID. No retry after ambiguous failures. Keep native/worker and
outer thread deadlines and every one-owner/uncertain/recovery/restart assertion.
Add deterministic actual-HTTP busy-once→sameID/single delivery coverage plus
negative nonretryable/exhausted cases. Existing same-ID busy-send E2E is reusable.
Agent technical plan review: /root/closure_plan_review approved this test-only
correction under the existing caller contract. Scope stays High/Large; source
review remains valid. No production timeout, protected contract or requirement
change. Return to planning for this failing gate, not a speculative product fix.
Read-only diagnosis confirmed bounded SQLite pre-BEGIN acquisition, and the
independent smart plan review approved the exact correction. Resume implementation
in this single test file; preserve the original concurrent and native deadlines.

2026-10-06: Invoke agent-workflow before the follow-up source edit (completed).
High/Large remains unchanged. app/codex_bridge_pipe.py and
app/mcp/codex_desktop_bridge.py are policy-gray/watch but security-sensitive by
judgment; tests/docs/record are blue. No dependency boundary or public schema
change, and no protected behavior-contract edits. Standing user approval
"so take ownership of this and fix", "i approve what is needed" and
"always apporve such things" covers the same authorized reliability outcome.
The same-child admission authority approved for PR290 is not expanded.

Keep the custody lock around Desktop I/O. Retained maintenance skips a held
lock; retained registration rejects contention immediately using the existing
authenticated unavailable/busy response. It must not update any caller,
continuity or custody. The worker may keep only its already admitted channel
after that exact response, unchanged thread/capability, unchanged proof,
verified current service and resolved I/O. No resend, caller update or initial
admission follows busy. Cleanup and every other failure remain fenced.

Target files: the two production files above, existing worker/native regression
fixtures or focused test_codex_retained_contention.py, design/operations docs
and canonical roadmap. First add a failing genuine Win32 contention regression;
then the minimum source fix. Required coverage includes bounded busy response,
preserved old channel/provenance, later fresh successful caller update,
first-enrollment rejection, cancellation/shutdown/unresolved I/O,
changed identity/capability and malformed responses. Reuse existing dispatch
generation and active-claim fence coverage without weakening it. Run focused,
affected, whole-change selected/full checks, smart result review and new PR.
Installed host recovery still needs separate qualification after stable merge.

Agent technical plan review: /root/closure_plan_review (gpt-6.1-sol/high),
read-only at 9ea12eba and merged production8c4f38a0, approved this narrow
existing-busy design subject to failing-before/fixed-after real Windows pipe
coverage. No unlocked native I/O or broad retry expansion was approved.

First invoke /agent-workflow to resume this Work Record and classify risk before code edits (completed; High/Large unchanged, normal workflow applies).

Target source files: app/mcp/codex_desktop_bridge.py (single retained worker lifecycle) and app/codex_bridge_pipe.py (private continuity handshake). Target regression files: existing retained lifecycle/native fixtures plus a focused reconnect test file; docs/designs/codex-mcp-desktop-bridge.md, docs/context/operations.md and the canonical roadmap document must reconcile the newly approved product-mode lifetime, leaving finite experimental modes unchanged. No public MCP/HTTP schema, persistence schema, scheduler or dependency changes.

New retained clients opt into a private register response containing only a validated SHA-256 continuity fingerprint of the original source and existing Desktop identity/ancestor tuple. This is an equality constraint, not an authentication credential. Legacy clients and finite modes keep their exact original wire fields. Each new epoch repeats all existing actual source/Desktop/capability/catalog checks and compares the fingerprint before retaining custody. No executable paths, native capabilities or proof fields enter public MCP output/logs.

Resumed Agent technical plan review: /root/closure_plan_review approved at 320cc9d5 under the exact human decision, requiring opt-in wire compatibility, continuity comparison on both fresh and already-open custody paths, conclusive disposal, startup-only typed retries, cancellation/competing source controls and a five-minute/12-attempt reconnect window with capped backoff. No application operation or caller future is replayed. This review supersedes the earlier freshness-only block; all other safety findings remain binding. No protected behavior contract changes are planned.

The same sole worker retains only successfully observed actual caller provenance, the original capability string and fingerprint in RAM. On a bounded idle poll it checks the old service's real process lifetime, source identity and secure bootstrap. Only conclusive resolved old-channel disposal allows reconnection. Existing unresolved-I/O retention, explicit stop, malformed trust, capability or source/Desktop changes deny retry. Retry startup outages with capped backoff and no busy loop; do not acquire any slot before the first actual runtime request. Never replay a Relay operation, pending future or owner action. Fresh actual calls remain supported and update provenance normally.

Dedicated installed fault qualification uses a separately reviewed temporary exact-session/message one-shot wrapper around real installed hooks, unchanged configuration/commands, bounded expiry, atomic consumption, nonmatching byte-behavior preservation and finally restoration/hash verification. It discards real committed responses rather than fabricating success. Real native-host and simulation results remain separate. Installed child reload is a distinct qualification dependency, not something a service restart proves.

Manager notification relay-msg-2c33245d0a5e4e778c162f7d4946050f / relay-delivery-bbc99d3d8dde447b975081cefee39a19 was ACKed at 15:52:02.624520 UTC. Manager's model response explicitly restated the admission decision and confirmed isolated fault-test preparation can continue. Notification is receipt-confirmed, not merely queued.

## Recovery handoff

Owner: relaydev. Branch feat/relay-recovery-closure; last verified release
f062cc72, including merged PR294 and separately owned PR292. Retain this managed checkout for remaining installed
acceptance and evidence reconciliation; never install from it. Both stable main
clones and the installed service are synchronized to that release, with restored
hooks/configuration and passing health checks. PR294 review, separate human
result approval, CI and deployment are complete. The real unloaded-host passive
observer case below passed; it is not recovery acceptance. The umbrella is returned
to planning because supported evidence does not identify the current admitted
native source owner. First resolve verifiable dedicated-source
admission/ownership through trusted host evidence or an explicitly reviewed
supported diagnostic; never take over an unidentified child. Then run a fresh
bounded installed recovery case. No fault is armed and no quiet window remains.
Prior evidence is reusable, but six no-restart installed successes do not close
restart/scope-move/pre-hook loss or historical incidents.
Fresh Minimap incident above additionally needs first-hook claim-to-emission
diagnostics; its successful second claim/ACK after app fallback is not closure.

Skill feedback trigger 3 dropped: the restart limitation belongs to this product's approved native admission contract, not an Agent Workflow upstream defect.

## Result review

### PR294 release and installed passive observation, 2026-10-07

The user separately approved PR294's diagnostic result after green CI. The exact
approval is recorded before merge at
https://github.com/rore/Pallium/pull/294#issuecomment-6035903908.
PR294 merged at 0311aa61. The authoritative deployment and installed-case evidence
is https://github.com/rore/Pallium/pull/294#issuecomment-6036653957.
Both stable main clones subsequently reached f062cc72 before observation; no
deployment or restart occurred during the observation window.

The passive window began 10:54:38 UTC and was released at 10:59:48 UTC. The exact
delivery relay-delivery-6385945398ba41e59f6d9b964da73a4f was claimed and ACKed once.
The real SessionStart observer recorded response, state writes, formatting,
emission, confirmed ACK and reference restoration. The recipient's native final
response contained the exact payload-specific marker, without tool calls or a
manual turn. Both installed hook files were restored at 10:58:20.464145 UTC;
original hook/config hashes and ACLs were independently verified unchanged.
No fault remains armed. The manager handoff relay-msg-f610bf6561874b319ea189fdaca4f253
was ACKed at 10:59:53.132339 UTC; this confirms receipt, not manager action.

Agent technical review: /root/deployment_evidence_review (gpt-6.1-sol/high).
Reviewed revision: installed f062cc72, unchanged helper blob
8dded7ffa65c765a34afeec035e71f62df25c543, and the retained private observation ledger.
Verification adequacy: no findings; the twelve ordered real hook events,
payload-specific native final and verified restoration qualify one ordinary
no-fault unloaded-recipient observer case only. The new operator HTTP send does
not establish authenticated MCP transport or unattended restart recovery.
Installed restart, scope-move and pre-hook lost-notification recovery, historical
causality and both unexplained parallel failures remain open. A new supported
source-owner diagnostic needs its own bounded plan and required reviews; this
release approval does not authorize opaque capability inspection or takeover.

The two-file post-release evidence reconciliation was independently reviewed by
/root/deployment_evidence_review with no findings. It changes no source or
requirement baseline. The fresh whole-change selector chose the governance lane:
31 checks passed in 45.60s; fresh Redline is Blue and the workflow check is clean.

### Passive exact-session observer release

Agent technical review: /root/deployment_evidence_review (gpt-6.1-sol/high).
Reviewed revision: d6787df294487987a15dc9157a2f308f7df1fc74.

Helper blob: 8dded7ffa65c765a34afeec035e71f62df25c543. Test blob:
6890d79f2978726dd0ab7be7e04b18c563e5ef12.
Verification adequacy: approved the bounded observer source and evidence after
88 focused cases, the affected-suite evidence plus four teardown cases, and the
complete passing serial lane. Documentation deltas 616af2a5 and d6787df2 accurately
retain evidence limits and both failed parallel runs. No remaining technical
finding or unintended scope expansion; original High/Large risk remains.
Historical causality, native ownership and installed recovery criteria are not
satisfied. Required PR CI and separate human result review remain gates; earlier
PR290/291 approvals do not approve this result. No installed acceptance is inferred.

### PR291 CI caller correction

Agent technical review: /root/closure_plan_review (gpt-6.1-sol/high).
Reviewed test blob: 8cdfcbe66a622fcca305db76b1ee0aaa7673679e; unchanged production
review below remains valid. Verification adequacy: the deterministic pre-fix
503 failure, eight focused cases, 155 retained-wake cases and existing same-ID
HTTP retry case adequately cover the test-only delta. One retry follows only
the exact supported busy response with identical body/ID; original concurrent
callers, worker/thread joins and custody/recovery/restart assertions remain.
Two seconds bounds retry initiation, not completion of a blocking POST.
Fresh full local and CI validation remain gates; no installed acceptance or
separate human PR291 result approval is inferred from this agent review.

### Post-release contention result

Agent technical review: /root/closure_plan_review (gpt-6.1-sol/high).
Reviewed revision: c8700aef2bb435d71bda16b7ed503f840e7b0e8e.
Verification adequacy: approved the 19-line production fix with no correctness
or security blocker. Real Windows source/service channels and the disclosed
fixture Desktop prove prompt busy, preserved source/proof/caller, serialized
dispatch and later fresh caller update. Worker/provenance/identity negative
coverage passed. Fixed native contention plus existing reconnect: 2 passed in
5.90s. Full non-slow validation at c8700aef passed: 6,261 passed, 34 skipped and
two expected failures in 331.17s. Import boundaries and fresh whole-change
Redline/workflow checks passed. CI and separate human result review remain
gates. Installed restart, scope-move, pre-hook notification loss and exact
historical causal attribution remain open, not weakened completion criteria.
Manager continuation relay-delivery-ec7d77128e6e42608633bdfc83262c44 ACKed at
17:44:01.781607 UTC with attempts=1 and no trace gap; its model response restated
the remaining gaps. Hook ACK and that response establish this handoff's receipt,
not any additional feature acceptance.

### PR290 source and harness result

Agent technical review: /root/closure_plan_review (gpt-6.1-sol/high).

Reviewed revision: 940ebe6e production blobs 17b86575939be2bade67647d8ada7f91a0dabc2f
and 761f6c519b13173d2f123d05dd0fc97864db6843, plus a9c38940 native-channel coverage.

Verification adequacy: source fix approved with focused and real Windows pipe
checks; full non-slow baseline passed. Final private-control harness revision
a766ccf3 and its 41 cases (110 combined focused cases) are undergoing final review.
Final harness technical review approved a766ccf3, helper blob
af0537c169c3df9a91a2066b8049fc968fffa319, after the confirmed-ACK and private-control
changes. Live preflight requires a unique user/SYSTEM/admin-only private case
directory outside the installed checkout, recorded original/config hashes,
unchanged configured targets/helper and target ACLs, and verified restoration of
both original files. Retain each case's backups/evidence; do not reuse or delete
them merely to enable another mode. This approval is for bounded source release
and safe instrumentation, not installed receipt acceptance.

The affected existing MCP/retained/recovery suites passed 266 cases. No protected
behavior contract changed, no dependency added, and no public schema changed.

Human result review received on 2026-10-06: the user selected "Approve reviewed
result after green CI" in response to the exact PR290 result summary (same
previously authenticated still-live child reconnects, changed identities and
unresolved I/O denied, no calls/messages replayed, installed qualification not
yet complete). This is separate from plan approval. PR CI remains a release gate.
CodeRabbit reported its review quota exhausted, so its green status is not
claimed as an additional completed review; independent smart review above is
the technical result review.

Installed qualification will
follow the merged stable-checkout deployment using a fresh native MCP child;
neither the source review nor health checks close that acceptance step. The
umbrella roadmap remains queued and historical unexplained incidents remain open.

## Contention native regression

The focused Windows-only slow regression uses the actual retained service run
loop and authenticated source child over a Win32 pipe, plus the shared FakeDesktop
pipe with an explicitly disclosed fake app descriptor. It gates two real
Desktop exchanges at two seconds each (each below its three-second I/O budget;
combined dispatch lock hold above three seconds). A fresh same-child registration
must return unavailable/busy promptly, preserve the source channel and continuity,
leave the caller unchanged, and allow a later registration to update the caller.

Before the source fix, at HEAD
385a8a943f5eb7dd3fc757166d0dc11cdbe9b967, ran:
`C:\Dev\rore\Pallium\.venv\Scripts\python.exe -m pytest tests/test_codex_retained_contention.py -q -n 0 -m slow`
Result: failed in 4.63s because registration did not return within two seconds;
the source then timed out and dispatch logged peer-mismatch at owner-result. No
production files had been edited for that run.

After the fix, HEAD remained 385a8a943f5eb7dd3fc757166d0dc11cdbe9b967 with
working-tree source blobs app/codex_bridge_pipe.py
e8e7b4fb8cbf03fd4020524e1e6df862c3e1402c and
app/mcp/codex_desktop_bridge.py 77e79bd1c2e72c4fe436f68e7f55b8cfcdc82325.
Ran:
`C:\Dev\rore\Pallium\.venv\Scripts\python.exe -m pytest tests/test_codex_retained_contention.py tests/test_codex_retained_native_reconnect.py -q -n 0 -m slow`
Result: 2 passed in 5.90s. Test-source blobs were
tests/test_codex_retained_contention.py
55c3cdf098b4159a8c1e5d7131d38f076d5c5758 and
tests/test_codex_retained_native_reconnect.py
820f2baa2ecc7737e05a9af59722d4f73b119e37.
