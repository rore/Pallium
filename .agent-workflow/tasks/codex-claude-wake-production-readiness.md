<!-- agent-workflow:start -->
**Outcome:**
Claude Relay `idle_wake` is production-ready on Windows at the qualified Codex hook-delivery reliability bar: exact-session native acceptance is verified, send remains responsive, failures are observable and loss-safe, crash/restart recovery is qualified, and a no-ping live round trip succeeds.

**Target:**
Pallium Claude Code Relay wake adapter.

**Scope:**
Claude wake scheduling, native Windows/POSIX transport protocol, exact-session registry handoff, hook-time Relay delivery/recovery, credential-free outcome logging, focused caller-surface/E2E tests, integration documentation, and the canonical wake roadmap. Primary paths: `app/claude_wake.py`, `app/claude_wake_transport.py`, `core/claude_wake.py`, `integrations/claude-code/hooks/*`, `api/routes.py`, and related tests.

**Constraints:**
Preserve persist-first delivery, fail-closed scope/session identity, one-shot verified-idle admission, bounded I/O, durable natural-turn fallback, and secret/message-content redaction. Use no wall-clock lease sleeps. Keep cold resume, busy-turn queueing, macOS/Linux qualification, Channels, turn-end notifications, and OpenCode out of this milestone. Use Relay for agent coordination; delegate implementation primarily to the Claude developer and independent validation to the Claude architect. Minimize expensive-model work. Preserve unrelated `uv.lock` and `.agent-workflow/.hooks.log` changes.

**Completion criteria:**
1. When Claude accepts, holds, denies, truncates, malforms, disconnects, or times out a native peer message, Pallium shall return the correct bounded outcome using the exact session identity, with deterministic Windows and POSIX caller-surface coverage.
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
Current `main` already persists before wake, validates pending delivery and scope, atomically consumes a one-shot idle grant, claims only at admitted hook execution, and covers deterministic D1→D2→D3 lifecycle behavior. Remaining verified gaps: the transport reports clean write as success without reading `peer_message_status`; its frame omits `session_id`; the probe runs inline with a two-second bound; wake outcomes lack structured logs; and automatic unattended recovery after crash-between-claim-and-emission is unqualified. Codex UTF-8, MCP scope guidance, multipart guidance, Windows cancellation, and the prior hook lifecycle defects are already fixed and must not be reimplemented.

**Material assumptions:**
- Claude's native endpoint returns a bounded `peer_message_status` that distinguishes accepted from held/denied. Disproof: fresh-session wire evidence returns no status or a different frame; action: stop protocol edits and update the plan from captured non-secret evidence.
- The native endpoint requires or safely accepts `session_id` in the peer frame. Disproof: live receiver rejects the field or documented/wire behavior proves socket identity is the complete contract; action: retain the existing signature and record why.
- A background probe can preserve one-shot registry semantics without introducing a second coordinator. Disproof: a deterministic concurrency test shows an idle grant can be lost or duplicated; action: keep the probe inline temporarily and solve only the demonstrated serialization boundary.
- Automatic crash-after-claim recovery can reuse existing lease eligibility and wake scheduling. Disproof: no supported event observes lease expiry without polling or broad persistence work; action: retain natural-turn recovery, mark unattended recovery unqualified, and return that expansion to planning.

**Plan:**
1. Claude architect delegates a clean-context redline and plan review against this Work Record and relevant sources; resolve findings before code.
2. Claude developer captures/validates the current native status-frame contract and implements the smallest protocol-correct transport change, including exact session identity only if verified. Stop on contradictory live evidence.
3. Claude developer moves only the bounded probe off the public send path and adds one existing-style structured outcome log, preserving registry atomicity and adding deterministic concurrency/error regressions.
4. Trace stale registration, service restart, transport failure, and crash-after-claim paths end to end. Reuse existing lease/wake machinery for the smallest recovery fix; do not add a general coordinator unless the assumption fails and the Work Record is replanned.
5. Run deterministic caller-surface and lifecycle tests, then update stable integrations, restart only with `scripts/restart-service.ps1`, verify all three health surfaces, and perform the fresh-session Windows no-ping matrix.
6. Claude architect independently validates in Claude Code. Codex architect reviews the complete diff, resolves all PR threads, and merges only after green gates.

**Verification plan:**
- Native accepted/held/denied/malformed/disconnect/timeout outcomes and exact identity → transport tests using real framing surfaces and deterministic fakes; no sleeps.
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

- 2026-09-02: Mission persisted before code. No runtime edits started. Waiting for clean-context risk/plan review; then implementation is delegated primarily to the Claude developer through Relay.

## Evidence

- Mission memory: `19f07003-979f-4e39-a9ed-50dac8f0fa80`.
- Roadmap priority: `roadmap/features/add-wake-first-relay-delivery.md`, Claude live Windows qualification first.

## Plan review

Pending.

## Result review

Pending.
