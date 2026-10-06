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

**Material assumptions:** Disproved: current service-epoch authority does not permit a resident child to refresh enrollment using historical caller metadata after restart. Return to planning; require the exact human admission-lifetime decision below before that implementation. Dedicated test-session faults can be isolated by temporary instrumentation that preserves all nonmatching hook behavior, consumes one bounded exact-delivery fault and restores verified installed bytes; the concrete harness still requires review and isolation tests before installation. Manager confirmed no overlapping production, roadmap or service work.

**Plan:** First invoke the /agent-workflow skill to create the Work Record and classify risk before any code edit. Discovery first: reconcile manager and current main/installation, inspect existing worker custody and all callers, determine safe installed fault qualification and historical backlog causes. Write the narrow implementation plan and obtain a clean-context smart technical review before source edits. Delegate bounded read-only diagnosis to cheaper agents; retain custody/security decisions and combined installed acceptance. Reuse PR286/288 evidence and existing fixtures. Implement only demonstrated root-cause fixes, run focused and selected whole-change validation, obtain smart independent result review, resolve PR findings, merge under standing user authority, sync/restart/verify installed service, qualify exact native journeys and deliver evidence to manager. Stop implementation on a failed safety assumption, not on merely passing simulated tests.

**Verification plan:** Exact pending delivery IDs link native attempt/retry, actual hook claim/emission/ACK and payload-specific recipient response for each failure journey. Simulated and installed evidence remain separate. Preserve active-lease and committed-ACK controls, exact identity changes and stale-worker denial with caller-surface tests. Investigate historical messages read-only before remediation. Use scripts/test-plan.py on whole change, one required full non-slow suite, workflow/Redline/import checks, smart reviews and green PR CI. Verify stable commit equality, /health, /status, /debug/queue/health and embedding_provider_ok after installed wrapper restart.

**Plan review:** Agent technical review: /root/closure_plan_review (gpt-6.1-sol/high), revision 7277445737efb58a0afd3c6195adfb8058aacb4a on 525df5bb. Blocked saved-caller automatic re-enrollment: approved admission authority ends at the service epoch, and source-process continuity does not create a fresh host request. Existing MCP children also do not hot-reload a worker fix after service restart. Accepted preparing bounded native qualification with a concrete reviewed exact-session/delivery one-shot hook shim, no config changes, no fabricated native response, preserved nonmatching hooks, backup/atomic restore/hash verification. No implementation or installed qualification performed.

**Approvals:** Approved by user 2026-10-06: "so can you complete the cycle so we don't leave open ends?". Standing authority: "you can push pr and merge if all is ok" and "i approve what is needed". Scope-limited approval, not permission to weaken fencing or interfere with active recipients.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

2026-10-06: Normal workflow applies: intended app/native-hook/persistence paths are outside the documentation-only allowlist. Complete clean isolated checkout scope plus intended paths selects no exemption. Classified High/Large from the existing policy before any source change. Managed checkout: C:/Users/I347041/.codex/worktrees/relay-recovery-closure/Pallium; branch feat/relay-recovery-closure. State is returned to planning pending discovery and technical review, not awaiting another human approval. Root untracked .codex-remote-attachments/ is preserved.

Canonical roadmap: roadmap/features/add-wake-first-relay-delivery.md. Prior evidence remains in .agent-workflow/tasks/relay-recovery-round.md and PR286/288. Manager coordination message relay-msg-577e17962853494fb0eab430ca683cb9 saved; receipt and ownership confirmation pending.

## Evidence

No new installed qualification or source verification claimed yet.

Read-only discovery: /root/closure_custody_discovery and /root/closure_fault_discovery (gpt-6-luna/medium), independently assessed by /root/closure_plan_review. Packaged SPEC was unavailable; reviewer read the available operating-mode and required checkpoint references rather than inventing one.

Native Dictation rollout reference: resumed session 01a0e2fc-c5b9-7c81-bce3-1c8c2ae35a1d. At 13:32:21.921 UTC the model received relay-delivery-4d0d946f75b54c7dacb058862e80d61e; live read-only SQLite records claimed_at 13:32:21.370893, delivered_at 13:32:21.638918 and attempts=1. Next relay-delivery-6e630c129fa647c4afe0ad09de0920c7 remains attempts=0. This corrects the prior assumption of a missed original hook on that turn, not the unexplained earlier idle interval. No payload bodies or claim tokens were printed from SQLite. No backlog mutations, recipient activation or service restart occurred.

## Admission decision required

Current: service restart discards registration; a fresh actual authenticated MCP request must re-enroll it.

Proposed: a previously admitted, still-live MCP child may recreate registration in a new service epoch using its captured actual caller pair, without another host request. This extends authorization lifetime from the service epoch to that admitted child's lifetime; all source/Desktop/capability identity, native schema, unresolved-I/O, shutdown and durable wake fences must remain enforced. It does not permit replay of Relay operations or owner submissions, a new child, changed capability or arbitrary historical session takeover.

Standing implementation/PR permission does not substitute for this exact changed admission requirement. No admission source edits will occur before the human decision. A safe host/MCP reload plan is also required before installed worker qualification; do not interrupt active user chats.

## Recovery handoff

Owner: relaydev. Branch feat/relay-recovery-closure; last source base 525df5bb, initial record commit 72774457. Retain this managed worktree for the concrete reviewed fault harness and admission decision; do not install from it. Next action: obtain the exact admission-lifetime decision, then write the narrow approved implementation/harness plan, review it and run isolation tests before any installed instrumentation. Prior PR286/288 evidence is reusable; no source change or new PR is claimed. Root and stable installation remain unchanged.

Skill feedback trigger 3 dropped: the restart limitation belongs to this product's approved native admission contract, not an Agent Workflow upstream defect.

## Result review

Planning review found a real admission decision, not a failing source implementation. Overall reliability remains open; no release or acceptance completion is claimed.
