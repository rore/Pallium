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

**Discovery:** Prior PR286 and PR288 are merged; both stable clones last verified at 525df5bb. Existing caller-surface tests cover claim/ACK faults, scope move and restart but simulate Desktop. Installed 6b49ff75 proved a missed-hook retry and backlog receipt after restart, explicitly requiring a fresh sender Relay read to restore custody. Historical 30 pending deliveries all had attempts=0: 22 current Dictation manager, eight older recipients; seven current-manager deliveries predate its active turn. No claim/ACK failure explains that zero-claim backlog. Live state and safe fault mechanisms remain to inspect.

**Material assumptions:** An existing authenticated resident native worker can recover service restart without weakening its runtime-owned identity checks; if false, return to planning and identify the supported limitation. Dedicated test-session faults can be isolated without modifying active sessions; if false, report the exact boundary instead of substituting simulated transport. Manager has no overlapping production work; verify before shared service operations.

**Plan:** First invoke the /agent-workflow skill to create the Work Record and classify risk before any code edit. Discovery first: reconcile manager and current main/installation, inspect existing worker custody and all callers, determine safe installed fault qualification and historical backlog causes. Write the narrow implementation plan and obtain a clean-context smart technical review before source edits. Delegate bounded read-only diagnosis to cheaper agents; retain custody/security decisions and combined installed acceptance. Reuse PR286/288 evidence and existing fixtures. Implement only demonstrated root-cause fixes, run focused and selected whole-change validation, obtain smart independent result review, resolve PR findings, merge under standing user authority, sync/restart/verify installed service, qualify exact native journeys and deliver evidence to manager. Stop implementation on a failed safety assumption, not on merely passing simulated tests.

**Verification plan:** Exact pending delivery IDs link native attempt/retry, actual hook claim/emission/ACK and payload-specific recipient response for each failure journey. Simulated and installed evidence remain separate. Preserve active-lease and committed-ACK controls, exact identity changes and stale-worker denial with caller-surface tests. Investigate historical messages read-only before remediation. Use scripts/test-plan.py on whole change, one required full non-slow suite, workflow/Redline/import checks, smart reviews and green PR CI. Verify stable commit equality, /health, /status, /debug/queue/health and embedding_provider_ok after installed wrapper restart.

**Plan review:** Pending discovery and clean-context technical review; no source edit authorized by this field yet.

**Approvals:** Approved by user 2026-10-06: "so can you complete the cycle so we don't leave open ends?". Standing authority: "you can push pr and merge if all is ok" and "i approve what is needed". Scope-limited approval, not permission to weaken fencing or interfere with active recipients.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

2026-10-06: Normal workflow applies: intended app/native-hook/persistence paths are outside the documentation-only allowlist. Complete clean isolated checkout scope plus intended paths selects no exemption. Classified High/Large from the existing policy before any source change. Managed checkout: C:/Users/I347041/.codex/worktrees/relay-recovery-closure/Pallium; branch feat/relay-recovery-closure. State is returned to planning pending discovery and technical review, not awaiting another human approval. Root untracked .codex-remote-attachments/ is preserved.

Canonical roadmap: roadmap/features/add-wake-first-relay-delivery.md. Prior evidence remains in .agent-workflow/tasks/relay-recovery-round.md and PR286/288. Manager coordination message relay-msg-577e17962853494fb0eab430ca683cb9 saved; receipt and ownership confirmation pending.

## Evidence

No new installed qualification or source verification claimed yet.

## Result review

Pending implementation and acceptance.
