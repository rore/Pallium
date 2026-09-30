<!-- agent-workflow:start -->
**Outcome:** A failed private Codex inventory response identifies the rejected validation predicate through a fixed, sanitized service-log stage.

**Target:** Windows Codex inventory observer in `app/codex_bridge_pipe.py`.

**Scope:** Extend the existing validation failure-stage allowlist and set a bounded substage at the existing `_observe` predicates; add private caller tests in `tests/test_codex_bridge_pipe.py`.

**Constraints:** Preserve all response acceptance rules, native-failed caller result, custody fencing, proof, authority, retry and cleanup. Never log native response content, keys, names, schema, endpoint, environment, or exception text. No live registration or service operation.

**Completion criteria:** Each synthetic rejected predicate yields a distinct fixed allowlisted stage and unchanged failure/fence through the private caller; a valid response still registers; no native content appears in diagnostics.

**Requirement baseline:**
{"source":"delegated-user-approved-task","outcome":"A failed private Codex inventory response identifies the rejected validation predicate through a fixed, sanitized service-log stage.","scope":"Extend the existing validation failure-stage allowlist and set a bounded substage at the existing `_observe` predicates; add private caller tests in `tests/test_codex_bridge_pipe.py`.","constraints":"Preserve all response acceptance rules, native-failed caller result, custody fencing, proof, authority, retry and cleanup. Never log native response content, keys, names, schema, endpoint, environment, or exception text. No live registration or service operation.","completion_criteria":"Each synthetic rejected predicate yields a distinct fixed allowlisted stage and unchanged failure/fence through the private caller; a valid response still registers; no native content appears in diagnostics."}

**Risk:** Elevated

**Complexity:** Simple

**Reason:** `app/codex_bridge_pipe.py` is a Redline watch-zone runtime surface. Validation diagnostics touch a security boundary but preserve its acceptance rules; one coherent code-and-test change.

**Discovery:** Matching live failure was `before-validate/invalid-response`. `_observe` currently combines envelope and tool predicates under one stage; `_record_failure` accepts only fixed stage/category allowlists and logs epoch/revision. Existing FakeDesktop tests exercise the private caller but mirror the validator, so they do not prove the real Desktop schema.

**Material assumptions:** Existing fixed-stage logging reaches the service log (confirmed for the incident). If caller tests expose a change in validation or failure handling, stop and revise the plan. If the actual response is needed to classify further, stop; never log it.

**Plan:** Keep the existing logger format and failure category. Add fixed validation substage names to `_INVENTORY_FAILURE_STAGES`; set one before each envelope/tool predicate in `_observe`, preserving predicate order and expressions. First add private-caller red tests with synthetic distinct failures and valid response; then minimal production change. Use existing `inventory_running`/`inventory_failure_records` fixtures. No new storage, API, or diagnostic framework. Stop if a stage is not uniquely attributable or content could leak.

**Verification plan:** When each synthetic response violates one predicate, private `register()` shall return the same native-failed unavailable result, fence custody, and log one fixed stage with the matching epoch/revision → parameterized private-caller test. When a valid response arrives, registration shall still succeed without a failure log → positive control. When native data is present, no logged field or proof shall include it → privacy assertions. Run focused, affected, then selector-required full suite once.

**Plan review:** Agent technical review: `/root/service_handoff_security`, 2026-09-30. Accepted Elevated/Simple plan with no blocking finding; requires isolated atomic predicates, valid positive and after-phase witness, fixed log identity, unchanged caller/fence/proof, and no sensitive content.

**Approvals:** Not required at this risk level; standing user implementation approval applies.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

2026-09-30: Entered Agent Workflow, confirmed whole-change application scope is non-exempt, reused a clean managed checkout, refreshed `origin/main`, and created `fix/codex-inventory-validation-code`. Classified Elevated/Simple before code edits. Independent security plan review accepted the narrow two-file change.

2026-09-30: Added 14 synthetic private-caller rejection cases, a valid-response control, and an after-phase expectation. All 14 rejected cases failed red on the old generic stage, with the unchanged public failure. Split the existing validation conditions into ordered atomic checks with fixed stages; focused before/after/positive run is green (40 passed). Affected file: 218 passed, one pre-validation transport failure in the existing `result` case; exact `--lf` rerun passed. Selector-required full non-slow run stopped at an unrelated Claude pending-close assertion after 1500 passes; exact `--lf` rerun passed. Neither failure's root cause is claimed fixed. Independent result review and fresh CI remain.

2026-09-30: Source/test diff passed independent result review and was committed at `1d710db7`. Automatic approval review rejected pushing the new branch to the verified public `rore/Pallium` origin because it did not find trusted authorization for publishing this exact code payload. No alternate push or PR path was attempted. Publication and CI are blocked pending explicit user approval for that destination and payload; local work is preserved.

## Evidence

Incident stage/category is fixed and sanitized: `before-validate/invalid-response`; no raw response was read.

Red: 14 caller cases failed on stage-only mismatch. Green: `test_codex_bridge_pipe.py -m slow -k 'validation_diagnostic or transfer_stage_diagnostics_from_private_caller or confirmed_source_process_exit_retains_same_connection' -n 0`: 40 passed, 179 deselected.

Affected: `test_codex_bridge_pipe.py -m slow -n 0`: 218 passed, 1 failed at existing `test_inventory_transfer_stage_diagnostics_from_private_caller[result]`; log stage was `before-write`/`transport-failed`, earlier than injected `before-result`. Exact `--lf --lfnf=none -m slow -n 0`: 1 passed. This is a non-reproduced failure, not a fixed root cause.

Selector `scripts/test-plan.py --base origin/main`: full. `pytest tests/ -x -q`: 1 failed at `test_claude_wake_registration.py::test_prompt_cleanup_retries_real_wake_and_relay_transition`, 1500 passed, 2 skipped, 1 xfailed; pending close remained after the second hook turn. Exact `--lf --lfnf=none -n 0`: 1 passed. Cause unproven; no full rerun was spent.

Agent Workflow local check: clean after correcting baseline field traceability. Publication attempt: auto-review rejection on `git push -u origin fix/codex-inventory-validation-code`, despite read-only confirmation that origin is the public `https://github.com/rore/Pallium.git`. The stated remaining concern is publication authorization for this source payload.

## Result review

Agent technical review: `/root/service_handoff_security`, 2026-09-30. Accepted the two-file source/test diff with no actionable code or privacy finding. The 14 fixed stages retain the original short-circuit order and `_record_failure` still emits only allowlisted stage/category and epoch/revision. Reviewer confirmed positive and after-phase coverage. Reviewed revision: implementation commit `1d710db7`; no production change followed review. Verification adequacy: focused native caller coverage passed; affected and selected full runs had separately recorded non-reproduced failures, so fresh current-head CI remains required before `Ready for review`.

## Recovery

Branch `fix/codex-inventory-validation-code` in the existing managed checkout. Preserve local implementation commit `1d710db7` and this Work Record. First resolve the explicit public-repository publication authorization rejection; then push this exact branch, open a PR, inspect current-head CI and review threads. Do not repeat local full validation absent a new finding.
