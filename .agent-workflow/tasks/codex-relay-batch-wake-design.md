<!-- agent-workflow:start -->
**Outcome:** Codex-first batch/wake design reviewed by the named external architect; agreed corrections applied at user request. Design discussion is closed; production remains unchanged and blocked on runtime evidence G1-G3.
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
**Plan review:** Independent review by claude-code:claude_arch complete on rev 9543503 (2026-08-31) in Minimap Spec Session relay-batch-codex-wake-5f4497cb. Verdict APPROVE-WITH-REVISIONS: 4 design blockers (D1-D4, cmt_000003-000006), 3 runtime evidence gates (G1-G3, cmt_000007-000009), 5 nonblocking (N1-N5, cmt_000010-000014); global conclusion cmt_000002. D1-D4 must be resolved in the doc; G1-G3 require live runtime proof before enabling wake, not doc edits. Previous B1-B5 dispositions in design section 9. Review authorized no implementation or live probes; implementation stays Blocked.
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

Review completed in Minimap Spec Session relay-batch-codex-wake-5f4497cb. Architect accepted suggestions 1/2/4/5 and requested one D3 clarification; sug_000006 makes changed-content retry rejection explicit without adding content to request-key uniqueness. User requested closure; sug_000001-000006 applied. D1-D4 and N2-N5 are captured in the design; N1 is explicitly bounded/deferred, not claimed as conversation termination. G1-G3 discussion closes by transfer to named, unproven evidence gates in design section 5 and slice A. No further general review requested.

## Recovery

Design review base 9543503 is published on codex/relay-batch-wake-design. The user-authorized closure applies six Minimap suggestions and aligns status; these local closure edits are not yet committed/pushed. Final architect review arrived through Relay message relay-reply-1fe1a69927295e4c8af69a045cd5e2eb9160728c52e1b5a18e1453657f023bf4. Next: bounded slice-A runtime qualification under a separate risk-classified Work Record and required approvals; no implementation readiness or runtime success is claimed. State remains Blocked for those gates, not for another design review. Existing uv.lock remains untouched.
