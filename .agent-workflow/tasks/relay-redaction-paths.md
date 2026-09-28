<!-- agent-workflow:start -->
**Outcome:** Preserve harmless drive-qualified checkout paths in Relay prose while continuing to mask credential values.
**Target:** Pallium shared redaction and Relay HTTP caller surface.
**Scope:** redaction/__init__.py; tests/test_redaction_tier_a_and_b.py; tests/test_agent_relay_e2e.py; docs/agent-relay.md; this Work Record.
**Constraints:** No private incident commands, provider calls, original-message resends, credential-value inspection, scope guesses, installation, merge, or changes to concurrent wake work. Keep redaction leaf-only and preserve direct assignment and provider-token masking.
**Completion criteria:** Generic checkout-command prose survives send/reply/read unchanged; direct assignments and real-shaped synthetic secrets in mixed prose remain masked; focused, selector-required, workflow, and independent-review checks pass.
**Requirement baseline:** {"source":"delegated-task","outcome":"Preserve harmless drive-qualified checkout paths in Relay prose while continuing to mask credential values.","scope":"redaction/__init__.py; tests/test_redaction_tier_a_and_b.py; tests/test_agent_relay_e2e.py; docs/agent-relay.md; this Work Record.","constraints":"No private incident commands, provider calls, original-message resends, credential-value inspection, scope guesses, installation, merge, or changes to concurrent wake work. Keep redaction leaf-only and preserve direct assignment and provider-token masking.","completion_criteria":"Generic checkout-command prose survives send/reply/read unchanged; direct assignments and real-shaped synthetic secrets in mixed prose remain masked; focused, selector-required, workflow, and independent-review checks pass."}
**Risk:** High
**Complexity:** Simple
**Reason:** redaction/__init__.py is gray by path policy, but credential masking is a security boundary. High by judgment; no dependency boundary changes.
**Discovery:** No matching roadmap/Work Record incident. Relay core/relay.py::_stored_payload redacts before persistence; redacted is stored != raw. Offline exact-source replay identified one YAML assignment match: authorization cue, span [1354,2278), 924 chars/90 words, no newline; one entropy candidate at [1440,1504), 64 chars, is a drive-qualified absolute checkout directory path. No raw command or value was printed. Installed filter source equals main. Existing assignment-prose remediation is recorded in codex-claude-wake-production-readiness; this incident is distinct.
**Material assumptions:** Exact source replay and sanitized reproduction establish structural-path false positive. If proposed discrimination permits direct secret assignments or unqualified base64-like secrets, stop and revise the plan; never exempt merely slash-containing candidates.
**Plan:** Add one shared match-aware predicate using the existing probable-token predicate. Exempt a candidate only if immediately preceded by an ASCII drive-letter colon, begins with slash, has multiple path segments, and none of its individual segments satisfies either existing assignment discriminator: entropy at the 12-character floor or compact >=12-character alphanumeric shape. Reuse at assignment-prose and Tier B callers; retain Tier A and compact-token rules. Add generic unit boundaries and HTTP send/reply/read lifecycle regression for harmless, secret, and mixed content, Unicode, idempotence, and continuation. Explicit negatives: real-shaped secret path segment, drive-prefixed compact secret, arbitrary URI, bare base64, secret beside benign path. Document narrow retention contract. Stop on new API/persistence or broader exemptions. No dependencies or integration copies.
**Verification plan:** When harmless drive-qualified directory prose is sent/replied, Relay shall retain it across status/paging/turn readback -> HTTP E2E. When direct assignments, unqualified secret-shaped tokens, provider tokens, or mixed real-secret prose occur, redaction shall mask them -> boundary tests plus HTTP E2E. When matching twice, output shall be idempotent -> focused tests. Whole change -> test-plan selector, full non-slow once, workflow check, diff check, independent result review.
**Plan review:** Pending clean-context agent technical review.
**Approvals:** Approved by user 2026-09-28: "This is a night job so you have blanket approval for what it needs". Task owner delegates technical review; exact authorization forwarded by root, request_source_item_id e05b03f1-f97d-482b-ba9b-7ea0be68b403.
**Exceptions:** —
**State:** Blocked
<!-- agent-workflow:end -->

## Implementation
Read-only diagnosis complete. Managed worktree: C:/Users/I347041/.codex/worktrees/relay-redaction-paths/Pallium; branch feat/relay-redaction-paths. Shared development/installed and concurrent wake checkouts remain untouched. Application edits await clean-context plan review; human blanket approval received from root.

## Sanitized reproduction
Input: `authorization: run checks from C:/Users/reader/.codex/worktrees/sample-project/workspace_run. Use python check.py --record build/check.json`
Current output: `authorization: [REDACTED]`

## Checkpoint: security-review
What is changing: distinguish drive-qualified structural paths from opaque high-entropy credential candidates.
Why: an innocent checkout directory removes a complete useful command paragraph.
Affected contract: shared secret masking before storage and display.
Compatibility risk: medium; false-positive handling must not suppress secret masking.
Verification: synthetic harmless/real-shaped/mixed content through shared unit and Relay HTTP lifecycle tests, plus independent plan/result review.
