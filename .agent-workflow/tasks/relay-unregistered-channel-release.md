# Release canceled unregistered source channels

<!-- agent-workflow:start -->
**Outcome:** A canceled first Codex Relay request cannot indefinitely occupy the native admission slot without registration.

**Target:** Retained Codex MCP worker lifecycle.

**Scope:** app/mcp/codex_desktop_bridge.py, one read-only trusted-bootstrap comparison in app/codex_bridge_pipe.py, existing worker/native caller tests, a focused isolated Windows pipe lifecycle regression, related operations evidence and the parent recovery record.

**Constraints:** Preserve queued fresh requests, authenticated admitted custody, unresolved-I/O retention, exact identity and continuity checks, finite modes, deadlines, and no replay or takeover. No service protocol, API, persistence, shared helper, dependency, protected behavior-contract or live environment change.

**Completion criteria:** After cancellation during first readiness with no replacement caller, a resolved unregistered channel is disposed and another source can obtain readiness without manually stopping the worker. A fresh queued request, including one arriving during disposal, survives and supplies only its own metadata. Already-admitted cancellation retains existing behavior; unresolved disposal forbids replacement. Focused caller and actual isolated Windows pipe journeys, affected/full validation, independent smart review and exact-head PR gates pass. Installed outage attribution and parent recovery acceptance remain separate.

**Requirement baseline:**
{"source":"parent:relay-recovery-closure;user:so take ownership of this and fix;pre-edit-plan-revision:trusted-bootstrap-cleanup-fence","outcome":"A canceled first Codex Relay request cannot indefinitely occupy the native admission slot without registration.","scope":"app/mcp/codex_desktop_bridge.py, one read-only trusted-bootstrap comparison in app/codex_bridge_pipe.py, existing worker/native caller tests, a focused isolated Windows pipe lifecycle regression, related operations evidence and the parent recovery record.","constraints":"Preserve queued fresh requests, authenticated admitted custody, unresolved-I/O retention, exact identity and continuity checks, finite modes, deadlines, and no replay or takeover. No service protocol, API, persistence, shared helper, dependency, protected behavior-contract or live environment change.","completion_criteria":"After cancellation during first readiness with no replacement caller, a resolved unregistered channel is disposed and another source can obtain readiness without manually stopping the worker. A fresh queued request, including one arriving during disposal, survives and supplies only its own metadata. Already-admitted cancellation retains existing behavior; unresolved disposal forbids replacement. Focused caller and actual isolated Windows pipe journeys, affected/full validation, independent smart review and exact-head PR gates pass. Installed outage attribution and parent recovery acceptance remain separate."}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Policy-gray/watch private worker lifecycle. This retires only a never-registered resolved channel, without adding authority or weakening any admission fence. Disposal and queued-call races require independent review. Parent relay-recovery-closure remains High/Large; reassess before implementation if review finds an authority change.

**Discovery:** InventoryWorker skips a first future canceled during client.ready(), then waits indefinitely with registered=False and the client still open. RetainedService.ready grants an infinite source read deadline on its sole serial pipe. The existing canceled-request test immediately sends another request and does not assert idle release. Root reproduced the idle leak with actual worker plus simulated Native, then with actual RetainedService and NativeInventoryClient Win32 readiness: registration absent, worker/source channel alive, another connection startup-unavailable; explicit shutdown released the slot. The scratch service was stopped and removed. These are isolated lifecycle findings, not installed Desktop or historical causal evidence.

**Material assumptions:** The existing _finish disposal fence conclusively distinguishes resolved cleanup from uncertainty; if it cannot, stop and retain ownership rather than replace a channel. Queued fresh callers remain valid while the canceled initial client retires; their metadata must never be drained as stopped solely by that retirement. Review or real-pipe evidence disproving these assumptions returns the plan to review. Native Windows fixtures may disclose simulated Desktop descriptors/catalogs; kernel pipe behavior must be real and installed acceptance must not be inferred.

**Plan:** Invoke /agent-workflow and classify before production/test edits (completed). Obtain clean-context smart review of this revised allowlist and risk. Target files: app/mcp/codex_desktop_bridge.py, app/codex_bridge_pipe.py, tests/test_codex_worker_reconnect.py, tests/test_codex_bridge_pipe.py, tests/test_codex_retained_native_reconnect.py, docs/context/operations.md and the two Work Records. Keep initial actual-request waiting and finite-mode startup unchanged. Move retained client creation/readiness into the request loop only when a live actual request has no client. Track whether a ready channel has never attempted registration; do not mistake legacy fake clients without continuity support for unused channels. Skip canceled requests while preserving any already queued live request on that existing ready channel. Retire a never-used channel only at the existing unregistered 0.1-second queue.Empty seam, using _finish; stop without replacement on uncertainty. Resolved disposal clears only the client, not the worker or request queue, and retains the retired client as a trusted identity witness. A fresh caller arriving during retirement survives. Permit constructor-only startup-unavailable acquisition attempts for at most one second after resolved retirement, checking stop/cancellation, unchanged runtime capability and trusted bootstrap before every attempt; after construction require the same manifest and recheck the trusted bootstrap before readiness. No retry of ready, register or tool calls; no extension of the existing caller deadline; ordinary first acquisition remains one attempt. Add NativeInventoryClient.bootstrap_unchanged() using its existing secure private-file read and exact manifest comparison, allowing read/parse errors to propagate. Do not refactor other callers or use previous_manifest (its admitted-reconnect semantics reject the same epoch). Leave admitted cancellation, reconnect windows, busy handling and service-side checks unchanged. First add a failing Windows regression and bounded caller cases, then the minimum source patch. A cheap bounded implementer may edit only the named source/tests; root owns records, risk, source acceptance and smart review. Stop on broader helper/protocol/authority change or protected requirement edit. Run focused, affected, whole-change selected/full validation, independent result review and PR CI. No installation or restart; manager owns the later combined release.

**Verification plan:**
When first readiness finishes after cancellation, the unused resolved channel shall release and a second source shall obtain readiness without worker shutdown -> genuine isolated Windows service/source pipe journey with actual InventoryWorker and NativeInventoryClient, finite waits and cleanup.
When a fresh request is queued before or during retirement, it shall survive and register only its own metadata -> existing real MCP caller fixtures plus gated disposal/ready cases.
When cancellation precedes native creation or occurs after admission, no unused channel shall open and existing admitted custody behavior shall remain -> existing and new bounded caller controls.
When disposal is unresolved or raises, no replacement channel shall be created -> existing _finish fence and explicit negative caller cases.
When startup/ready fails or finite inventory mode is used, existing bounded behavior shall remain -> existing lifecycle regression files and readiness controls.
When a post-retirement constructor finds asynchronous EOF still pending, only same-service acquisition may wait within one second; cancellation, stop, changed/lost capability, changed/missing/invalid/inaccessible trusted bootstrap and other error categories shall stop without admission -> gated worker caller cases and native bootstrap helper cases after resolved disposal, ordinary startup one-attempt control and actual Windows source journeys.
When the reviewed change is ready for release, its full observable contract and whole-change gates shall pass -> selected affected checks, full serial non-slow suite, focused slow Windows kernel test, import/Redline/workflow, smart result review and exact-head CI.

**Plan review:** Agent technical review: /root/wake_output_plan_review, independent non-implementer gpt-6.1-sol/high, approved adbcc474cf7274df434d1d86d9868e54d7845832 on 2026-10-07. Reviewed exact clean checkout, full child record, worker and native identity/disposal paths; independently confirmed Elevated/Moderate and verification adequacy. The asynchronous EOF race raised on 6b522387 was corrected before edits. Result review must verify cancellation-aware acquisition-window bounds and unresolved mismatch cleanup. No blocker remains before the named edits; this is not result or installed acceptance.

**Approvals:** Existing user reliability implementation/PR authority covers this narrow component. No new authority or live operation is inferred; required separate human plan approval will be requested if risk is raised to High.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Recovery state

Owner relaydev; branch feat/relay-unregistered-channel-release, base
989f2c267e6f1cd261bad6a6e0a78537d32199ab. Reused the clean managed recovery
checkout; prior feat/relay-recovery-closure and db3e8fb9 evidence are preserved.
This is one narrow repair component, not a new owner or replacement for the
parent .agent-workflow/tasks/relay-recovery-closure.md. No production/test edit
has begun at plan approval; next action is bounded implementation and regression coverage.

## Implementation

Approved target files are the two native worker/client sources, the three named
existing caller/native test files, operations evidence, and the two Work Records.
Bounded cheap workers will handle source/caller tests and the isolated separate-
process Windows release regression in disjoint files. Root owns records,
scope, integration, validation scheduling and independent result acceptance.
No live service, host, configuration, databases or Relay custody are changed.

Pre-fix caller cases (queued during disposal false/true) failed at the expected
missing idle disposal, 2 failed in 3.45 seconds. The separate-source actual
Windows regression at aa096be8 with test blob
ffce2866268e0d276be0313e983e944fc58ba9be failed in 3.38 seconds: real initial
readiness succeeded, cancellation completed, and the second OS source's real
NativeInventoryClient readiness returned startup-unavailable while the first
worker remained alive with its resolved channel open. The assertion observed
the caller surface rather than only an internal cleanup flag. Fixture cleanup
stopped both source and service and verified no random scratch subtree remained.
The native helper pre-fix check failed at its absent method after actual source
EOF, in 1.11 seconds. Production sources were untouched for these runs.
Commands use the isolated checkout and shared interpreter with -B, serial -n 0;
the separate-source node additionally selects -m slow. These are isolated Win32
lifecycle findings, not installed or historical causality.

The actual separate-source release regression passed after the initial patch,
one passed in 2.63 seconds at native test blob
7fb4cea8e79e027fe4349b518be89d6db6dd9507, with no registration/custody and verified
teardown. Three bounded caller cases passed in 2.07 seconds and the actual
disposed-client bootstrap check passed in 1.46 seconds. These do not discharge
the subsequent new acquisition guards. Root's provisional review corrected an
invalid completion callback and prevented cancellation from replacing the trusted
retired identity. Independent source review then found a capability change during
replacement readiness; the retired capability must remain fenced through the
existing pre-registration capture/check. Gated changed/removed-capability cases
and the remaining negative matrix are being verified before whole-change freeze.
Ordinary startup and admitted recovery are not redesigned.

Independent review also required terminal fencing of a rejected retired identity:
otherwise register() could restart the same worker and discard its witness.
This is limited to the new cleanup lineage's capability/bootstrap/manifest,
non-startup constructor and confirmed/unknown trust failures during replacement
readiness. Known readiness stop/deadline/transport availability and generic
non-ready results retain fresh-caller behavior; readiness is never replayed.
Timeout and cancellation remain eligible for a fresh actual request. The caller
subsystem run before the readiness-category delta passed 302 cases in 138.65
seconds without concurrent source changes. Final changed-node controls, native
subsystem and full final-revision validation remain gates; that interim run is
not claimed as final whole-change evidence.

The affected native subsystem passed 265 cases in 112.42 seconds, serial with
`-m slow`, across tests/test_codex_bridge_pipe.py,
tests/test_codex_retained_native_reconnect.py and
tests/test_codex_retained_contention.py. Frozen worker blob
fc7f5e863c6dc09f7edeb75f3b8d44008d5ca20e, native helper blob
0555068e29169eccb43fb41c516f70d058690260 and native regression blob
7fb4cea8e79e027fe4349b518be89d6db6dd9507 matched before and after the run;
no source edits or regression scratch remained. At that revision the focused
worker controls passed 27 cases in 7.54 seconds and the slow bootstrap helper
passed separately in 0.63 seconds. These are isolated Windows and simulated
caller results, not installed-host acceptance.

Interim review required a terminal fence for idle capability mismatch after
a canceled replacement, separation of ordinary stop from trust failures, and
real FastMCP cancellation/release/fresh-call coverage plus an already-admitted
cancellation control. The shared simulated-native fixture must enable native
availability explicitly so Linux does not pass negative cases through its OS
gate. Existing native results cover unchanged exercised branches, not these
remaining guards. Whole-change selection includes all eight dirty files and
requires the full lane. Those source/test corrections are resolved in the final
focused evidence below; the full suite will run only after final source freeze
and accounting for origin/main e9eb3956.

Independent source technical review by /root/wake_output_plan_review
(gpt-6.1-sol/high) approved frozen worker blob
422502954c021660121b49be1292aab606c17f1c and native blob
0555068e29169eccb43fb41c516f70d058690260 at HEAD
aa096be8ab178038cc4f6b7bb33a7b27f8861cd9 plus the named dirty sources.
Reviewed revision: those exact blobs, compared with approved plan adbcc474.
Verification adequacy: source-only approval; caller E2E, final whole-change
validation, result review and CI remain required. No source blocker remains.
The idle terminal fence is restricted to a retired lineage; observing ordinary
stop does not itself reject identity. Unknown trust failures cannot reset that
lineage, and known readiness availability failures retain fresh-caller behavior.
The source and native helper are frozen while caller tests are completed.

The real MCP cancellation check must send notifications/cancelled with the
observed tools/call request ID. Installed SDK inspection showed that canceling
only the client's asyncio task closes its response stream without notifying
the server. No SDK or protocol changes are required; using that client-only
shortcut would not qualify the server cancellation boundary.

Final focused caller validation passed 32 cases in 8.42 seconds, using the
shared interpreter with `-B -m pytest`, exact worker nodes, `-q -n 0`.
The 18 selected nodes include the existing readiness/acquisition/error matrix,
test_cancelled_replacement_ready_keeps_retired_capability_fence_at_idle,
test_mcp_cancellation_releases_unused_channel_for_fresh_request (queued before
cleanup, queued during cleanup, rejected retired bootstrap), and
test_mcp_cancellation_after_retained_admission_does_not_replay. Genuine MCP
notifications/cancelled reached the server with the observed outgoing request
ID; the SDK returned its cancellation error. No canceled tool operation ran.
Fresh callers provided only their own thread/turn metadata. Rejected native
identity did not block ordinary Relay reads or permit another native admission.
The admitted control preserved its checked live channel and continuity, without
replay, before final disposal. All captured worker threads were stopped.
The separate slow bootstrap helper passed in 0.68 seconds.

Frozen worker test blob: 7375eec32113970b3375d25b43e16b0d5e37ea31.
Frozen pipe test blob: 0b7343a607bba96dce08983b5dabdd88f51a391f.
The final source blobs remain 422502954c021660121b49be1292aab606c17f1c
and 0555068e29169eccb43fb41c516f70d058690260. The earlier native 265-case
run used fc7f5e86, not the final worker: it is reused only for unchanged
exercised paths; final focused controls cover the later guard changes and the
upcoming full serial suite will verify the final revision. No installed result
or historical explanation is inferred.

Explicit base update: committed component 6582ee37edbfe767b1862324ce5c670ece4f9b0f
is preserved by local branch feat/relay-unregistered-channel-release-pre-rebase.
Rebased the four task commits onto main
e9eb3956ce4990f9dc15d0a24520f40d67246883, yielding
ee5e8d911e0486ed3dfac4b88c5d54d3225fee15. Main's intervening change is limited
to independently owned OpenCode paths. All five production/test blob hashes
above matched after rebase; the reviewed and pre-fix revisions remain reachable.
No parallel work or live checkout was changed. The post-rebase whole-change
selector reports the full lane for exactly the eight approved task files.

## Pre-edit review correction

The first plan was not approved. Local handle closure does not prove that the
service has processed EOF, so immediate disposal could fail a fresh queued call.
The correction preserves that call on the ready channel, retires only after an
idle queue wait, and fences a one-second constructor-only acquisition window
to the retired trusted identity. The technical allowlist and pre-implementation
baseline now explicitly include the minimal native read-only comparison;
product outcome, authority, protocol and completion criteria are unchanged.
The original record remains available at 6b522387. Parent risk stays High/Large.
Current main advanced independently to e9eb3956ce4990f9dc15d0a24520f40d67246883;
account for that base before PR/CI rather than silently switching mid-task.
Skill feedback trigger 2 dropped: this was a source-specific plan race caught by
normal independent review, not an upstream workflow instruction defect.

## Isolated discovery evidence

The retained ignored harness is build/native_ready_cancel_diagnostic.py in the
separate relay-wake-output-failure checkout at 4698ba52. Root ran
`python -B -m build.native_ready_cancel_diagnostic` there, exit zero, tool
wrapper 3.67 seconds. Actual Windows readiness completed before a test gate;
canceling the worker request and releasing that gate left the channel open
without registration after 250 ms. A second actual client connection was busy
(typed startup-unavailable); after explicit worker shutdown it reached ready.
The test-only private random scratch service was stopped, its thread and
uncertainty state checked, and its validated repo/tmp subtree removed. No live
bootstrap, Desktop endpoint, Relay payload, installed configuration or service
was touched; -B suppressed imported bytecode writes. The competing connection
was in the same process; regression qualification must additionally exercise a
separate source child. This establishes a reproducible lifecycle gap, not the
cause of the historical post-restart absence of enrollment.
