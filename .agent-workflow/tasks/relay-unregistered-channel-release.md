# Release canceled unregistered source channels

<!-- agent-workflow:start -->
**Outcome:** A canceled first Codex Relay request cannot indefinitely occupy the native admission slot without registration.

**Target:** Retained Codex MCP worker lifecycle.

**Scope:** app/mcp/codex_desktop_bridge.py, existing worker caller tests, a focused isolated Windows pipe lifecycle regression, related operations evidence and the parent recovery record.

**Constraints:** Preserve queued fresh requests, authenticated admitted custody, unresolved-I/O retention, exact identity and continuity checks, finite modes, deadlines, and no replay or takeover. No service protocol, API, persistence, shared helper, dependency, protected behavior-contract or live environment change.

**Completion criteria:** After cancellation during first readiness with no replacement caller, a resolved unregistered channel is disposed and another source can obtain readiness without manually stopping the worker. A fresh queued request, including one arriving during disposal, survives and supplies only its own metadata. Already-admitted cancellation retains existing behavior; unresolved disposal forbids replacement. Focused caller and actual isolated Windows pipe journeys, affected/full validation, independent smart review and exact-head PR gates pass. Installed outage attribution and parent recovery acceptance remain separate.

**Requirement baseline:**
{"source":"parent:relay-recovery-closure;user:so take ownership of this and fix","outcome":"A canceled first Codex Relay request cannot indefinitely occupy the native admission slot without registration.","scope":"app/mcp/codex_desktop_bridge.py, existing worker caller tests, a focused isolated Windows pipe lifecycle regression, related operations evidence and the parent recovery record.","constraints":"Preserve queued fresh requests, authenticated admitted custody, unresolved-I/O retention, exact identity and continuity checks, finite modes, deadlines, and no replay or takeover. No service protocol, API, persistence, shared helper, dependency, protected behavior-contract or live environment change.","completion_criteria":"After cancellation during first readiness with no replacement caller, a resolved unregistered channel is disposed and another source can obtain readiness without manually stopping the worker. A fresh queued request, including one arriving during disposal, survives and supplies only its own metadata. Already-admitted cancellation retains existing behavior; unresolved disposal forbids replacement. Focused caller and actual isolated Windows pipe journeys, affected/full validation, independent smart review and exact-head PR gates pass. Installed outage attribution and parent recovery acceptance remain separate."}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Policy-gray/watch private worker lifecycle. This retires only a never-registered resolved channel, without adding authority or weakening any admission fence. Disposal and queued-call races require independent review. Parent relay-recovery-closure remains High/Large; reassess before implementation if review finds an authority change.

**Discovery:** InventoryWorker skips a first future canceled during client.ready(), then waits indefinitely with registered=False and the client still open. RetainedService.ready grants an infinite source read deadline on its sole serial pipe. The existing canceled-request test immediately sends another request and does not assert idle release. Root reproduced the idle leak with actual worker plus simulated Native, then with actual RetainedService and NativeInventoryClient Win32 readiness: registration absent, worker/source channel alive, another connection startup-unavailable; explicit shutdown released the slot. The scratch service was stopped and removed. These are isolated lifecycle findings, not installed Desktop or historical causal evidence.

**Material assumptions:** The existing _finish disposal fence conclusively distinguishes resolved cleanup from uncertainty; if it cannot, stop and retain ownership rather than replace a channel. Queued fresh callers remain valid while the canceled initial client retires; their metadata must never be drained as stopped solely by that retirement. Review or real-pipe evidence disproving these assumptions returns the plan to review. Native Windows fixtures may disclose simulated Desktop descriptors/catalogs; kernel pipe behavior must be real and installed acceptance must not be inferred.

**Plan:** Invoke /agent-workflow and classify before production/test edits (completed). Obtain clean-context smart plan/risk review. Keep initial actual-request waiting and finite-mode startup unchanged. Move retained client creation/readiness into the request loop, only for a live actual request when no client exists. Immediately after readiness, if that request is canceled and registration has never succeeded, call existing _finish; retain the client and stop on unresolved disposal, otherwise clear only the resolved client and continue the same request queue. Do not close the worker or drain a live queued request as part of resolved retirement. A subsequent queued request creates its own fresh channel; no canceled metadata or native operation is replayed. Leave already-admitted paths, reconnect windows, busy handling and all service-side checks unchanged. First add a failing actual Windows pipe regression and bounded caller-surface cases, then the minimum source patch. A cheap bounded implementer may edit only the named source/tests; root owns records, risk, source acceptance and smart review. Stop if a helper/protocol/authority change or protected requirement edit is needed. Run focused, affected, whole-change selected/full validation, independent result review and PR CI. No installation or restart occurs; the manager owns the later combined release.

**Verification plan:**
When first readiness finishes after cancellation, the unused resolved channel shall release and a second source shall obtain readiness without worker shutdown -> genuine isolated Windows service/source pipe journey with actual InventoryWorker and NativeInventoryClient, finite waits and cleanup.
When a fresh request is queued before or during retirement, it shall survive and register only its own metadata -> existing real MCP caller fixtures plus gated disposal/ready cases.
When cancellation precedes native creation or occurs after admission, no unused channel shall open and existing admitted custody behavior shall remain -> existing and new bounded caller controls.
When disposal is unresolved or raises, no replacement channel shall be created -> existing _finish fence and explicit negative caller cases.
When startup/ready fails or finite inventory mode is used, existing bounded behavior shall remain -> existing lifecycle regression files and readiness controls.
When the reviewed change is ready for release, its full observable contract and whole-change gates shall pass -> selected affected checks, full serial non-slow suite, focused slow Windows kernel test, import/Redline/workflow, smart result review and exact-head CI.

**Plan review:** Pending independent smart technical and risk review of this record before production/test edits.

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
has begun; first next action is independent plan review.

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
