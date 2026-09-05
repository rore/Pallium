<!-- agent-workflow:start -->
**Outcome:** A Relay delivery whose hook turn crashes after claiming is automatically re-woken after lease recovery and delivered exactly once without a manual agent turn.

**Target:** Pallium Agent Relay wake and recovery lifecycle.

**Scope:** Exact-session expired-claim recovery and wake scheduling in the shared Relay persistence/service path and existing Codex/Claude runtime adapters; actual HTTP/hook E2E; Relay roadmap/docs.

**Constraints:** Preserve the 60-second claim lease and runtime-owned identity; no model polling, hook/MCP mixing, duplicate or empty wakes, platform-specific core behavior, new dependency, or wall-clock sleep in normal tests. Reuse existing wake coalescing/reconciliation and retain durable natural-turn fallback when launch fails.

**Completion criteria:** When a hook claims an eligible delivery and terminates before context emission/ACK, lease expiry shall automatically schedule its exact session again and the real hook surface shall deliver and ACK that ID once; duplicate recovery signals, concurrent new sends, scope mismatch, restart, launch failure, and terminal empty state shall preserve pending work without duplicate action or wake loops.

**Risk:** High

**Complexity:** Moderate

**Reason:** Preliminary High because this changes persisted claim/exact-once recovery and exact-session wake admission; redline classification and focused discovery must confirm the exact surfaces before planning. Moderate spans storage/service scheduling, two runtime adapters, and real lifecycle E2E.

**Discovery:** Pending focused code/test/roadmap trace; implementation is blocked until current lease recovery ownership and all callers are mapped.

**Material assumptions:** Existing persisted delivery and session state contains enough runtime-owned identity to rearm after lease expiry; discovery must identify the authoritative event and fails back to planning if recovery needs new identity or polling infrastructure.

**Plan:** Blocked pending discovery, clean-context redline classification, and clean-context plan review. The first implementation step after approval will be the smallest shared recovery trigger that reuses existing runtime wake dispatch.

**Verification plan:** When an admitted hook crashes after claim, deterministic time/control shall cross lease expiry and observable wake/hook surfaces shall show one rearm, one delivery/ACK, and empty terminal state; failure, duplicate, restart, concurrent-arrival, Unicode/max-boundary, and cross-scope cases shall be driven through real HTTP/hooks without wall-clock sleep.

**Plan review:** Pending clean-context review after discovery.

**Approvals:** Approved by user 2026-09-05: "you don't need to ask every time, you have a constant approval to get what you're working on to a done state"

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- 2026-09-05: Established RW-008 from merged/installed RW-007. No production code inspected or edited; discovery, redline classification, and plan review remain.

## Evidence

- Canonical roadmap row RW-008 records crash-after-claim lease recovery without unattended re-wake as the next open correctness bug.