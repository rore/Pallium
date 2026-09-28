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
**Plan review:** Agent technical review: /root/relay_redaction_incident/redaction_plan_review, reviewed 7de393ea; approve with drive-prefix word boundary and rejection of // URI prefix. See Plan review below.
**Approvals:** Approved by user 2026-09-28: "This is a night job so you have blanket approval for what it needs". Task owner delegates technical review; exact authorization forwarded by root, request_source_item_id e05b03f1-f97d-482b-ba9b-7ea0be68b403.
**Exceptions:** —
**State:** Blocked
<!-- agent-workflow:end -->

## Implementation
Read-only diagnosis complete. Managed worktree: C:/Users/I347041/.codex/worktrees/relay-redaction-paths/Pallium; branch feat/relay-redaction-paths. Shared development/installed and concurrent wake checkouts remain untouched. Human blanket approval and clean-context technical plan review received before application edits.

Implemented one match-aware predicate reused by assignment prose and Tier B. The initial boundary check caught low-entropy compact path segments falling back to aggregate entropy; the final drive branch classifies suspicious segments directly under caller minimum length. No dependencies, API/persistence changes, or integration edits. All patches used apply_patch successfully; no fallback writes.

## Evidence
Affected subsystem: `python -m pytest tests/test_redaction_tier_a_and_b.py tests/test_agent_relay_e2e.py -q -n 0`: 143 passed in 23.42s. Initial compact-segment failures were corrected and `--lf --lfnf=none -q -n 0`: 3 passed. Exact original source was replayed locally without printing its contents: 4453 input/output code points, identical output, idempotent. Selector chooses full lane. `git diff --check` passed. Import-linter: 8 contracts kept, 0 broken; machine-readable boundary report and fresh Redline verdict produced. Workflow runtime check: clean, exit 0.
Full suite at 9cd003bf stopped after 1 failed, 2027 passed, 2 skipped, 1 xfailed in 144.81s: `tests/test_agent_relay_hooks.py::test_legacy_pin_bootstraps_endpoint_alias_and_queued_delivery[claude-code]` returned None at line 1126. Exact recorded `--lf --lfnf=none -q -n 0` rerun: 1 passed in 0.79s. Root authorized one full rerun with two workers: 2 failed, 591 passed, 1 xfailed in 73.44s; same legacy hook failure plus `tests/test_codex_wake.py::test_codex_wake_evidence_is_bounded_and_definition_matched` returned False at line 135. Exact two-node serial rerun with in-memory os.replace exception logging: 2 passed in 1.05s, no logged file-operation exceptions. No more full reruns; bounded read-only subsystem diagnosis delegated to /root/relay_redaction_incident/full_suite_failure_diagnosis. Cause remains unconfirmed; readiness code does not depend on redaction. State remains Blocked pending whole-suite evidence; root owns acceptance.
Roadmap reconciliation: no matching canonical item applies; existing Relay scope remains accurate. Documentation now names the narrow structural-path retention contract. No feature-status changes.

## Result review
Agent technical review: /root/relay_redaction_incident/redaction_plan_review. Reviewed revision: 9cd003bf. Verification adequacy: implementation and focused HTTP evidence approved; required full-suite and workflow completion remain acceptance gates. The reviewer inspected the complete diff and found benign paths alone exempt, suspicious compact/entropy segments still masked, separate candidates and Tier A still active, and send/reply/read/ACK/idempotence/Unicode coverage adequate. No correctness/security findings. User delegates technical review under the recorded blanket approval; root owns final coordinated acceptance and rollout.

## Plan review
Agent technical review: /root/relay_redaction_incident/redaction_plan_review. Reviewed revision: 7de393ea, shared predicate, Relay write boundary, and existing redaction tests. Verdict: approve; require drive-prefix word boundary and reject // so URI suffixes cannot resemble drives. Segment checks honor existing FP guards, provider masking stays active, and any separate secret in the RHS still masks. HTTP send/reply/status/paging/turn coverage judged adequate.

## Sanitized reproduction
Input: `authorization: run checks from C:/Users/reader/.codex/worktrees/sample-project/workspace_run. Use python check.py --record build/check.json`
Before fix: `authorization: [REDACTED]`. After fix: input retained unchanged; exact private-source offline replay also retained unchanged and idempotently.

## Checkpoint: security-review
What is changing: distinguish drive-qualified structural paths from opaque high-entropy credential candidates.
Why: an innocent checkout directory removes a complete useful command paragraph.
Affected contract: shared secret masking before storage and display.
Compatibility risk: medium; false-positive handling must not suppress secret masking.
Verification: synthetic harmless/real-shaped/mixed content through shared unit and Relay HTTP lifecycle tests, plus independent plan/result review.
