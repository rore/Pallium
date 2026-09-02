<!-- agent-workflow:start -->
**Outcome:**
Claude Relay `idle_wake` is production-ready on Windows at the qualified Codex hook-delivery reliability bar: exact-session native acceptance is verified, send remains responsive, failures are observable and loss-safe, crash/restart recovery is qualified, and a no-ping live round trip succeeds.

**Target:**
Pallium Claude Code Relay wake adapter.

**Scope:**
Claude wake scheduling, native Windows/POSIX transport protocol, exact-session registry handoff, hook-time Relay delivery/recovery, credential-free outcome logging, focused caller-surface/E2E tests, integration documentation, and the canonical wake roadmap. Primary paths: `app/claude_wake.py`, `app/claude_wake_transport.py`, `core/claude_wake.py`, `integrations/claude-code/hooks/*`, `api/routes.py`, and related tests.

**Constraints:**
Preserve persist-first delivery, fail-closed scope/session identity, one-shot verified-idle admission, bounded I/O, durable natural-turn fallback, and secret/message-content redaction. Use no wall-clock lease sleeps. Keep cold resume, busy-turn queueing, macOS/Linux qualification, Channels, turn-end notifications, and OpenCode out of this milestone. Use Relay for agent coordination; delegate implementation primarily to `codex:@relaydev` and Claude protocol/runtime validation to `claude-code:@claude_arch`, which may use its own Claude developer internally. A stale recipient registration is not proof an agent exists. Minimize expensive-model work. Preserve unrelated `uv.lock` and `.agent-workflow/.hooks.log` changes.

**Completion criteria:**
1. When Claude native activation is attempted, Pallium shall report only the bounded local transport outcome; model-visible admission shall be established by the existing hook/Relay delivered state. The exact session shall remain bound by the registered socket/pipe plus token, with deterministic accepted-write, disconnect, timeout, partial-write, malformed-input, and Unicode coverage.
2. When Relay sends to a registered Claude session, the public send path shall not wait for the native transport timeout, and duplicate/concurrent sends shall trigger at most one scope-bound idle wake.
3. Every wake attempt shall emit one credential-free structured outcome with session/delivery correlation, latency, and a bounded failure category.
4. When registration is stale, the service restarts, transport fails after idle consumption, or a hook crashes after claim, the delivery shall remain recoverable and shall eventually produce at most one rearmed wake, one context injection, and one ACK; busy deliveries remain pending until a verified idle boundary.
5. A fresh installed Windows Claude session shall complete SessionStart → busy deferral → Stop idle grant → exact native wake → attributed hook delivery → atomic Relay reply without a manual ping, including duplicate, restart, and forced-failure probes.
6. Required focused/full gates, service health probes, installed-state verification, Claude architect acceptance, Codex architect review, and PR review threads shall be clean before merge.

**Risk:**
High

**Complexity:**
Moderate

**Reason:**
The change touches a security-sensitive exact-session transport, concurrent admission state, and loss/recovery semantics across service, hooks, and runtime boundaries. Multiple independently verifiable outcomes require live Claude Code evidence.

**Discovery:**
Current `main` already persists before wake, validates pending delivery and scope, atomically consumes a one-shot idle grant, claims only at admitted hook execution, and covers deterministic D1→D2→D3 lifecycle behavior. Installed Claude Code 2.1.250 evidence shows `peer_message_status` is an out-of-band control frame sent to the incoming frame's `origin.from`; the current one-way Pallium sender has no return inbox, so a clean write is trigger evidence only and hook/Relay delivery remains the admission proof. Claude's own authenticated `type:user` debug recipe omits `session_id`, matching successful live dogfood; exact targeting is the registered socket/pipe plus token and scope-bound registry entry. Remaining verified gaps: the probe runs inline with a two-second bound, wake outcomes lack structured logs, local transport result naming overstates success, and automatic unattended recovery after crash-between-claim-and-emission is unqualified. Codex UTF-8, MCP scope guidance, multipart guidance, Windows cancellation, and the prior hook lifecycle defects are already fixed and must not be reimplemented.

**Material assumptions:**
- A local bounded transport outcome plus hook/Relay delivered state is sufficient to separate trigger from admission without a Pallium reply inbox. Disproof: Claude architect evidence shows a production-required status cannot be inferred from hook admission; action: return to planning for a bounded authenticated `origin.from` listener rather than reading the write connection.
- The registered socket/pipe, token, runtime/session registry key, and caller scope are the exact-session identity contract for ordinary user frames; no `session_id` field is required. Disproof: Claude architect live evidence shows cross-session ambiguity or receiver rejection without that field; action: widen the transport signature only then.
- A background probe can preserve one-shot registry semantics without introducing a second coordinator. Disproof: a deterministic concurrency test shows an idle grant can be lost or duplicated; action: keep the probe inline temporarily and solve only the demonstrated serialization boundary.
- Automatic crash-after-claim recovery can reuse existing lease eligibility and wake scheduling. Disproof: no supported event observes lease expiry without polling or broad persistence work; action: retain natural-turn recovery, mark unattended recovery unqualified, and return that expansion to planning.

**Plan:**
1. Claude architect performs or delegates a clean-context redline and plan review against this Work Record and relevant sources; resolve findings before code.
2. Claude architect validates the out-of-band status and socket/token exact-identity contract from Claude Code evidence. `codex:@relaydev` makes transport outcomes truthful without adding a speculative reply listener or `session_id`; stop and replan on contradictory live evidence.
3. `codex:@relaydev` moves only the bounded probe off the public send path and adds one existing-style structured outcome log, preserving registry atomicity and adding deterministic concurrency/error regressions.
4. `codex:@relaydev` traces stale registration, service restart, transport failure, and crash-after-claim paths end to end. Reuse existing lease/wake machinery for the smallest recovery fix; do not add a general coordinator unless the assumption fails and the Work Record is replanned.
5. Run deterministic caller-surface and lifecycle tests, then update stable integrations, restart only with `scripts/restart-service.ps1`, verify all three health surfaces, and perform the fresh-session Windows no-ping matrix.
6. Claude architect independently validates in Claude Code. Codex architect reviews the complete diff, resolves all PR threads, and merges only after green gates.

**Verification plan:**
- Native local-write/disconnect/timeout/partial/malformed/Unicode outcomes and exact socket/token identity → transport tests with deterministic fakes; hook/Relay caller-surface E2E proves admission separately; no sleeps.
- Responsive send plus one wake under duplicate/concurrent sends → real router callback and registry concurrency tests with bounded events.
- Safe observability → captured-log assertions proving correlation fields and absence of token/payload content.
- Stale/restart/failure/crash recovery → persisted Relay hook/API E2E with deterministic clock/lease control and public delivery-state assertions.
- Fresh installed Windows journey → Claude architect dogfood transcript plus Relay status evidence, including reply, duplicate, restart, and forced failure.
- Repository acceptance → focused suites, full required CI, `agent-workflow`/redline, `git diff --check`, supported service restart, `/health`, `/status`, `/debug/queue/health`, installed integration checks, and resolved PR review threads.

**Plan review:**
Pending clean-context Claude architect/delegated reviewer assessment; implementation is blocked until recorded below.

**Approvals:**
Approved by user 2026-09-02: "ok. so that's the current mission. persist this plan so we don't loose it. use the claude dev for most of the developemtn work. remember budget considerations. use the claude architect when you need to validate and run verifications in claude code. the architect can also use a claude dev it has"

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- 2026-09-02: Mission persisted before code. No runtime edits started. User corrected delegation: `codex:@relaydev` is the primary implementation developer; `claude-code:@claude_arch` owns Claude-side validation and may use its own Claude developer. A stale `@paldev` address-book entry was mistakenly treated as an available agent; its pending assignment was superseded and must not be used.
- 2026-09-02: Installed Claude 2.1.250 protocol evidence corrected the initial design before code: `peer_message_status` is sent out-of-band to `origin.from`, not returned on the write connection, and the built-in authenticated user-frame recipe omits `session_id`. The plan now treats native write as trigger evidence and hook/Relay state as admission evidence; no speculative listener or identity field is authorized.

## Evidence

- Mission memory: `d7537934-fd56-4830-8834-7bab372124d8` (supersedes the incorrect developer assignment).
- Roadmap priority: `roadmap/features/add-wake-first-relay-delivery.md`, Claude live Windows qualification first.

## Plan review

Pending.

## Result review

Pending.
