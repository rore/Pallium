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

**Plan review:** Review of 6b522387436db13d862427221c50aa599af359b6 by /root/wake_output_plan_review required correction for asynchronous server EOF. The reviewer supports the revised mechanism and Elevated/Moderate classification, but approval of this revised immutable record is still pending. No production/test edits have begun.

**Approvals:** Existing user reliability implementation/PR authority covers this narrow component. No new authority or live operation is inferred; required separate human plan approval will be requested if risk is raised to High.

**Exceptions:** —

**State:** Blocked or returned to planning
<!-- agent-workflow:end -->

## Recovery state

Owner relaydev; branch feat/relay-unregistered-channel-release, base
989f2c267e6f1cd261bad6a6e0a78537d32199ab. Reused the clean managed recovery
checkout; prior feat/relay-recovery-closure and db3e8fb9 evidence are preserved.
This is one narrow repair component, not a new owner or replacement for the
parent .agent-workflow/tasks/relay-recovery-closure.md. No production/test edit
has begun; first next action is independent review of the corrected plan.

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
