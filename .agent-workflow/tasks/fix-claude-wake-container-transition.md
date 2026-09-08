<!-- agent-workflow:start -->
**Outcome:** When a live Claude session changes repositories, Pallium retires both the old Relay endpoint and the old wake registration instead of repeatedly waking an unclaimable delivery.

**Target:** Pallium Claude Code integration.

**Scope:** Claude UserPromptSubmit container-transition cleanup, focused hook lifecycle tests, and matching integration documentation if behavior is undocumented.

**Constraints:** Keep Relay actor-free, preserve endpoint isolation across containers, do not move or rewrite pending deliveries, and do not change the public HTTP/MCP schema.

**Completion criteria:** A hook-level repository-switch journey proves the old Relay session and exact old wake registration are closed once, retry safely after transient failure, and leave the new container registered and usable.

**Risk:** Elevated

**Complexity:** Simple

**Reason:** Agent-redline classified the integration hook path gray with no boundary findings or checkpoint flags. The diff is small, but wake lifecycle behavior affects delivery reliability.

**Discovery:** Current main records prior containers in `pending_relay_closes` and closes `/relay/sessions/close`, but never calls the existing durable `close_claude_wake` for those same containers. Live evidence shows one Claude session registered under both its old path-derived and new Git-derived container, sharing one pipe, with the old registration stuck in `wake_inflight` and repeatedly triggered. Wake close is already exact-scope, write-ahead, and idempotent.

**Material assumptions:** `close_claude_wake(session_id, old_container)` is the canonical durable cleanup and is safe when the registration is already absent; disproved by its current tests or registry contract, in which case return to planning. Pending close state may clear only after both Relay and wake close report success; if focused tests show an unrecoverable partial-success loop, return to planning.

**Plan:** Reuse the existing `pending_relay_closes` loop in `integrations/claude-code/hooks/user_prompt_submit.py`: import `close_claude_wake`, close the exact old wake scope alongside the old Relay session, and mark that old container complete only when both operations succeed. Extend the existing hook lifecycle test to cover success and retry/partial-failure without new helpers or APIs. Update docs only if the lifecycle promise is currently stated incompletely. Stop if this requires changing endpoint identity, moving deliveries, or altering core wake-registry semantics.

**Verification plan:** When a Claude hook observes an old pending container, it shall close both exact old registrations and clear pending state only after both succeed → focused hook test. When either close fails, the hook shall retain the old container for retry without touching the new registration → focused failure test. Existing Claude wake and structural hook suites shall remain green → targeted pytest. Final diff shall pass agent-workflow and redline checks plus CI.

**Plan review:** Pending clean-context review.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- Discovery and elevated gray-zone classification completed. No code edits started; clean-context plan review is pending.

## Plan review

Pending.

## Evidence

Pending.

## Result review

Pending.
