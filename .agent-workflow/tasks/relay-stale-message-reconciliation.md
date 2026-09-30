<!-- agent-workflow:start -->
**Outcome:** A reviewed minimal plan explains how agents reconcile delayed Relay messages with current work without discarding useful results or reopening completed actions.

**Target:** Pallium Relay message presentation and agent coordination guidance.

**Scope:** Diagnose existing hook/MCP envelopes, bundled Relay guidance, collection-coordination boundaries, and assignment reconciliation; produce a caller-visible contract, red test cases, and review plan. Production implementation is outside this offer.

**Constraints:** Preserve claims, ACK, TTL, routing, and budgets. Never infer supersession from age alone or suppress all late messages. Preserve useful late results and blockers. No new ledger, protocol, schema, task-specific heuristic, or live service operation without demonstrated need and separate authorization.

**Completion criteria:** The plan distinguishes valid delayed delivery, duplicate processing, and superseded work; maps each proposed rule to existing evidence and a caller-surface red case; identifies behavioral limits and the approval needed before implementation.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"A reviewed minimal plan explains how agents reconcile delayed Relay messages with current work without discarding useful results or reopening completed actions.","scope":"Diagnose existing hook/MCP envelopes, bundled Relay guidance, collection-coordination boundaries, and assignment reconciliation; produce a caller-visible contract, red test cases, and review plan. Production implementation is outside this offer.","constraints":"Preserve claims, ACK, TTL, routing, and budgets. Never infer supersession from age alone or suppress all late messages. Preserve useful late results and blockers. No new ledger, protocol, schema, task-specific heuristic, or live service operation without demonstrated need and separate authorization.","completion_criteria":"The plan distinguishes valid delayed delivery, duplicate processing, and superseded work; maps each proposed rule to existing evidence and a caller-surface red case; identifies behavioral limits and the approval needed before implementation."}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Cross-integration message interpretation and agent action semantics need independent review. Prospective hook/skill paths are gray; any API or lifecycle change requires reclassification before implementation.

**Discovery:** Pending source and incident inspection.

**Material assumptions:** Exact incident evidence will come from the manager. Delivery timestamps and transport state alone cannot establish whether work is complete or superseded.

**Plan:** Invoke Agent Workflow, establish this record, inspect shared presentation and current guidance, compare exact incident evidence, then propose the smallest existing-surface change and explicit red cases for independent and manager review.

**Verification plan:** When a delayed unique result arrives after a completed action, the plan must preserve the result while requiring current-state reconciliation before another action → anonymized incident sequence and caller-surface red case. When age is the only stale signal, the plan must not authorize dropping it → counterexample review. Root review precedes TDD authorization.

**Plan review:** Pending independent review of the concrete proposal.

**Approvals:** This offer authorizes diagnosis and planning only; manager review and TDD authorization remain required before production work.

**Exceptions:** —

**State:** Blocked or returned to planning
<!-- agent-workflow:end -->

## Implementation

2026-09-30: Accepted the bounded planning offer. Reused the clean completed PR #236 worktree on `feat/relay-stale-message-reconciliation`, based on current main `dfcd35abc5690cfb88f91bf7a7646cc3b6871c1f`. Applicability selects the normal workflow: Work Records and prospective hook/agent-instruction changes are not documentation-only exempt. No production edit or service operation has occurred.
