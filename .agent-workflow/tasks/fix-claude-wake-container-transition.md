<!-- agent-workflow:start -->
**Outcome:** When a live Claude session changes repositories, Pallium retires both the old Relay endpoint and the old wake registration instead of repeatedly waking an unclaimable delivery.

**Target:** Pallium Claude Code integration.

**Scope:** Claude UserPromptSubmit container-transition cleanup, focused hook lifecycle tests, and matching integration documentation if behavior is undocumented.

**Constraints:** Keep Relay actor-free, preserve endpoint isolation across containers, do not move or rewrite pending deliveries, and do not change the public HTTP/MCP schema.

**Completion criteria:** A hook-level repository-switch journey proves the exact old wake registration and old Relay session are retired while the new container remains registered; pending cleanup clears only after both exact closes succeed and safely retries partial failure.

**Risk:** Elevated

**Complexity:** Simple

**Reason:** Agent-redline classified the integration hook path gray with no boundary findings or checkpoint flags. The diff is small, but wake lifecycle behavior affects delivery reliability.

**Discovery:** Current main records prior containers in `pending_relay_closes` and closes `/relay/sessions/close`, but never calls the existing durable `close_claude_wake` for those same containers. Live evidence shows one Claude session registered under both its old path-derived and new Git-derived container, sharing one pipe, with the old registration stuck in `wake_inflight` and repeatedly triggered. Wake close is already exact-scope, write-ahead, and idempotent.

**Material assumptions:** `close_claude_wake(session_id, old_container)` is the canonical durable cleanup and is safe when the registration is already absent; disproved by its current tests or registry contract, in which case return to planning. Relay close is idempotent while its row exists, allowing a partial wake failure to retry; a genuinely absent old Relay row may retain harmless pending bookkeeping but cannot recreate a retired wake registration.

**Plan:** Reuse the existing `pending_relay_closes` loop in `integrations/claude-code/hooks/user_prompt_submit.py`: import `close_claude_wake`, attempt the exact old wake close and existing Relay-session close independently, and mark that old container complete only when both report success. Add a hook-driven transition test using real durable wake state and real Relay API/storage reads. Add a partial-failure retry test where wake-intent publication fails after Relay close succeeds, then a later turn succeeds through the idempotent Relay close and retires the stale wake. Reuse existing tests for ambiguous wake-close HTTP recovery and missing registration idempotence. Stop if this requires changing endpoint identity, moving deliveries, or altering core wake-registry semantics.

**Verification plan:** When a Claude hook switches containers, it shall retire the exact old wake registration and old Relay session while preserving the new registration → hook-driven test through real wake registry plus Relay HTTP/storage reads. When wake-intent publication fails after Relay close succeeds, pending cleanup shall survive and a later turn shall finish both idempotent closes → partial-failure retry test. When old Relay close fails or is absent, pending bookkeeping shall remain while successful wake retirement prevents repeated wake delivery → focused failure assertion. Existing persistent wake-close recovery, Claude wake, and structural hook suites shall remain green → targeted pytest. Final diff shall pass agent-workflow and redline checks plus CI.

**Plan review:** Approved by clean-context Astra reviewer `/root/review_wake_fix_plan` after two revisions; no remaining blocking findings. See `## Plan review`.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Reused the existing pending-close loop to retire the exact stale Claude wake registration and Relay endpoint independently, clearing transition bookkeeping only after both succeed. Added one hook-driven retry lifecycle test over real wake HTTP and Relay HTTP/storage paths.

## Plan review

Initial clean-context review (`/root/review_wake_fix_plan`) verdict: revise. Blocking findings were (1) the old Relay row may be absent even though a wake registration exists, so requiring both closes to succeed would retain pending state forever, and (2) verification needed real durable wake plus Relay read paths and partial-success coverage. The reviewer approved hook ownership because only the hook knows a container transition occurred; the registry must continue permitting identical native session IDs in different containers.

Second review found that ignoring a false wake-close result can lose cleanup when intent publication itself fails. The plan now retains pending state unless both exact closes succeed; repeated Relay close is idempotent while its row exists.

Final clean-context review approved the revised plan with no remaining blockers.

## Evidence

- Revision `5a9de9af`: expanded Claude/Relay integration suite → 197 passed, 3 skipped; full repository suite in the complete development environment → 4660 passed, 32 skipped, 2 expected failures.
- Import-boundary adapter and agent-redline report → no boundary violations; detected risk Elevated.
- Agent Workflow local gate → clean.
- `apply_patch` was unavailable due the documented Windows sandbox launch failure; the test-only correction used a deterministic replacement limited to the named file.

## Result review

Clean-context Astra review requested changes for an unstubbed wake HTTP dependency in an existing retry test and a real user-profile session-state write in the new test. Both were fixed and regression-tested. Re-review approved `5a9de9af` with no remaining actionable findings.