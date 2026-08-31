<!-- agent-workflow:start -->
**Outcome:** A concrete Codex-first batch/wake design is available for one consolidated independent architecture review; production remains unchanged and blocked on review and runtime evidence.
**Target:** Pallium Relay milestone 1: existing Codex architect/developer sessions, with regular-turn fallback.
**Scope:** This Work Record; docs/designs/relay-batch-codex-wake.md; supersession notice in docs/plans/2026-08-26-wake-first-relay-delivery.md; roadmap feature alignment.
**Constraints:** Documentation only. No production, tests, fixtures, dependency, configuration, installer or running-service changes. Preserve the pre-existing uv.lock edit. Use claude-code:@claude_arch through Relay, not a substitute subagent; future implementation uses the existing Codex Relay developer. No live wake probes in this task.
**Completion criteria:** One authoritative design specifies atomic batches, ownership/admission, regular-turn fallback, backlog progress, MCP/skill UX and an observable E2E matrix; B1-B5 are explicitly adjudicated; external architect receives the versioned design and returns a consolidated verdict before implementation readiness is claimed.
**Risk:** Elevated
**Complexity:** Moderate
**Reason:** Pre-edit redline classified all four documentation paths BLUE with no boundary violations. Engineering judgment raises risk for a design governing execution triggers and durable delivery; runtime feasibility remains uncertain.
**Discovery:** Existing send caps payload at 1500 code points; current turn/formatter defaults are uncapped, despite stale 2400/3 constants. SQLite sends commit messages and deliveries together; hook ACK loops operate per delivery. Reply ID currently derives from delivery ID alone. The old wake plan allows timeout-to-fallback without proving non-admission. Six external review messages are in this task's Relay context; this is user-turn receipt, not no-ping wake evidence.
**Material assumptions:** A queued Codex turn can execute the same pre-model Relay hook as a normal turn; disproof keeps wake passive and returns the adapter to review. Full context admission and stale-publication fencing can be observed/reconciled; disproof forbids exact-once claims and automatic uncertain replay. The proposed byte/character/count bounds fit actual integration limits; disproof reduces advertised limits or rejects before acceptance, never truncates.
**Plan:** (1) Invoke agent-workflow, classify documentation scope and record it before edits. (2) Consolidate the contract and failures in the design. (3) Mark conflicting earlier planning rules superseded; link canonical design in roadmap. (4) Run diff, link, redline and workflow checks. (5) Commit the design-only task branch; request one independent Relay review from claude_arch by file/commit pointer. (6) Incorporate blocking findings in one bounded correction pass; any unresolved runtime question remains a named gate, not invented evidence. No guarded edits authorized.
**Verification plan:** When the design is read, every identified failure class shall map to an observable requirement and planned caller-surface test -> design matrix/self-review. When old planning is followed, its supersession banner shall point to the new contract -> link and stale-rule checks. When reviewed, the architect shall identify the exact revision and blockers -> Relay verdict recorded here. Changed paths shall remain docs/workflow only -> staged diff and redline check.
**Plan review:** Pending independent review by claude-code:@claude_arch; previous B1-B5 and proposed dispositions are recorded in design section 9. The prior review did not cover batching or the notification-only trigger.
**Approvals:** Not required for documentation at this risk level. User requested design and external review; this is not approval for future High-risk API/persistence implementation.
**Exceptions:** —
**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- 2026-08-31: Created task branch codex/relay-batch-wake-design from b58f693. Existing uv.lock edit is out of scope and remains unstaged.
- Pre-edit redline reporter: BLUE, all four planned paths blue; no boundary findings. Bundled redline skill is under .claude/skills/agent-workflow/agent-redline/ (the sibling path in assess-risk.md is stale).
- Design-only consolidation prepared for independent review. State is Blocked on independent design review and explicit runtime feasibility gates, not on missing permission to write documentation.

## Evidence

Inspected core/relay.py, storage/sqlite_relay.py (send, turn, reply, both ACKs and status expiry), storage/sqlite_schema.py, api/schemas.py, app/mcp/server.py, Codex hook/formatter, and recorded Phase 0 evidence. No runtime or implementation tests have been run for the proposed design. Fresh documentation-scope redline: BLUE/no boundaries; workflow checker with build/relay-batch-design-redline.json: clean (exit 0); new document links resolve; scoped git diff --check passes. These are structural checks, not architect approval or runtime evidence. apply_patch failed with Windows error 1327; the documented exact-file PowerShell fallback was used.

## Plan review

Awaiting the named external architect. Ask for a single complete review artifact plus a short Relay verdict/pointer while the current 1500-character cap prevents consolidated long replies. That is a temporary review-workflow workaround, not a required product UX.

## Recovery

Design revision 9543503 is committed and published on codex/relay-batch-wake-design. Review request relay-msg-dd80e21718f04f26a71abb32c4005f4e was sent to claude-code:@claude_arch on 2026-08-31; delivery is pending. Reviewer may write only docs/designs/relay-batch-codex-wake-review.md and reply with its pointer. Next: receive the verdict, inspect the complete artifact, adjudicate blockers, and update this record before implementation readiness is claimed. No production changes or tests ran. Future production work needs its own risk-classified record and approvals. Existing uv.lock remains untouched.
