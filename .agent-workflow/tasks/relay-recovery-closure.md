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

**Plan review:** Agent technical review: /root/closure_plan_review (gpt-6.1-sol/high). Initial 72774457 review correctly blocked admission-lifetime expansion. After the exact human approval, resumed review of 320cc9d5 approved same-live-child continuity, opt-in legacy compatibility, comparisons before catalog/caller updates, conclusive disposal, startup-only retries capped at 12 attempts/five minutes, and preserved cancellation/fences. A concrete native fault harness still needs independent review and isolation tests before installation; source changes do not hot-reload existing MCP children.

**Approvals:** Approved by user 2026-10-06: "yes, of course, that's the desired state" after the exact question allowing the same still-live previously authenticated MCP child to reconnect automatically after service restart, preserving identity checks and no resends. Prior scope approval: "so can you complete the cycle so we don't leave open ends?". Standing authority: "you can push pr and merge if all is ok" and "i approve what is needed". This authorizes the stated child-lifetime admission only, not new-child takeover, changed host identity, unresolved-I/O replay or active-chat interruption.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

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

2026-10-06: Normal workflow applies: intended app/native-hook/persistence paths are outside the documentation-only allowlist. Complete clean isolated checkout scope plus intended paths selects no exemption. Classified High/Large from the existing policy before any source change. Managed checkout: C:/Users/I347041/.codex/worktrees/relay-recovery-closure/Pallium; branch feat/relay-recovery-closure. State is returned to planning pending discovery and technical review, not awaiting another human approval. Root untracked .codex-remote-attachments/ is preserved.

Canonical roadmap: roadmap/features/add-wake-first-relay-delivery.md. Prior evidence remains in .agent-workflow/tasks/relay-recovery-round.md and PR286/288. Manager coordination message relay-msg-577e17962853494fb0eab430ca683cb9 saved; receipt and ownership confirmation pending.

## Evidence

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

Owner: relaydev. Branch feat/relay-recovery-closure; source base 525df5bb, initial record 72774457 and approved plan 320cc9d5. Retain this managed worktree for the reviewed reconnect implementation and fault harness; do not install from it. Next: focused regressions, smart result/harness review, whole-change checks and PR. Prior PR286/288 evidence is reusable; no new installed acceptance is claimed. Root and stable installation remain unchanged.

Skill feedback trigger 3 dropped: the restart limitation belongs to this product's approved native admission contract, not an Agent Workflow upstream defect.

## Result review

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
