<!-- agent-workflow:start -->
**Outcome:** When a live Claude session changes repositories, Pallium retires both the old Relay endpoint and the old wake registration instead of repeatedly waking an unclaimable delivery.

**Target:** Pallium Claude Code integration.

**Scope:** Claude UserPromptSubmit container-transition cleanup, focused hook lifecycle tests, and matching integration documentation if behavior is undocumented.

**Constraints:** Keep Relay actor-free, preserve endpoint isolation across containers, do not move or rewrite pending deliveries, and do not change the public HTTP/MCP schema.

**Completion criteria:** A hook-level repository-switch journey proves the exact old wake registration is durably retired while the new container remains registered; existing Relay-close bookkeeping still clears only on Relay-close success and retries on failure or absence.

**Risk:** Elevated

**Complexity:** Simple

**Reason:** Agent-redline classified the integration hook path gray with no boundary findings or checkpoint flags. The diff is small, but wake lifecycle behavior affects delivery reliability.

**Discovery:** Current main records prior containers in `pending_relay_closes` and closes `/relay/sessions/close`, but never calls the existing durable `close_claude_wake` for those same containers. Live evidence shows one Claude session registered under both its old path-derived and new Git-derived container, sharing one pipe, with the old registration stuck in `wake_inflight` and repeatedly triggered. Wake close is already exact-scope, write-ahead, and idempotent.

**Material assumptions:** `close_claude_wake(session_id, old_container)` is the canonical durable cleanup and is safe when the registration is already absent; disproved by its current tests or registry contract, in which case return to planning. Its write-ahead close intent remains authoritative after an ambiguous HTTP failure; existing durable-intent tests verify that contract.

**Plan:** Reuse the existing `pending_relay_closes` loop in `integrations/claude-code/hooks/user_prompt_submit.py`: import `close_claude_wake` and always publish the exact old wake-scope close before attempting the existing Relay-session close. Do not couple wake helper return status to pending bookkeeping: the helper writes a durable close intent before HTTP, while the pre-existing Relay result remains the only completion condition. Add a hook-driven transition test using real durable wake state and real Relay API/storage reads, plus a failure test proving an absent/failed Relay close retains pending state while the stale wake is still retired. Reuse existing tests for ambiguous wake-close HTTP recovery. Stop if this requires changing endpoint identity, moving deliveries, or altering core wake-registry semantics.

**Verification plan:** When a Claude hook switches containers, it shall retire the exact old wake registration and old Relay session while preserving the new registration → hook-driven test through real wake registry plus Relay HTTP/storage reads. When old Relay close fails or is absent, it shall retain pending Relay bookkeeping but still retire the old wake registration → focused failure test. When wake-close HTTP is ambiguous, the durable close intent shall recover after restart → existing persistent wake regression test. Existing Claude wake and structural hook suites shall remain green → targeted pytest. Final diff shall pass agent-workflow and redline checks plus CI.

**Plan review:** Initial clean-context Astra review requested revision for reachable missing-old-Relay and partial-success cases; revised plan awaits confirmation. See `## Plan review`.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- Discovery and elevated gray-zone classification completed. Initial plan review found that wake admission can precede Relay admission, so both-success bookkeeping would retry forever when the old Relay row is absent. Plan revised to decouple durable wake cleanup from unchanged Relay-close bookkeeping. No code edits started.

## Plan review

Initial clean-context review (`/root/review_wake_fix_plan`) verdict: revise. Blocking findings were (1) the old Relay row may be absent even though a wake registration exists, so requiring both closes to succeed would retain pending state forever, and (2) verification needed real durable wake plus Relay read paths and partial-success coverage. The reviewer approved hook ownership because only the hook knows a container transition occurred; the registry must continue permitting identical native session IDs in different containers.

## Evidence

Pending.

## Result review

Pending.