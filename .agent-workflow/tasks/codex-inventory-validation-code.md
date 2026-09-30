<!-- agent-workflow:start -->
**Outcome:** A failed private Codex inventory response identifies the rejected validation predicate through a fixed, sanitized service-log stage.

**Target:** Windows Codex inventory observer in `app/codex_bridge_pipe.py`.

**Scope:** Extend the existing validation failure-stage allowlist and set a bounded substage at the existing `_observe` predicates; add private caller tests in `tests/test_codex_bridge_pipe.py`.

**Constraints:** Preserve all response acceptance rules, native-failed caller result, custody fencing, proof, authority, retry and cleanup. Never log native response content, keys, names, schema, endpoint, environment, or exception text. No live registration or service operation.

**Completion criteria:** Each synthetic rejected predicate yields a distinct fixed allowlisted stage and unchanged failure/fence through the private caller; a valid response still registers; no native content appears in diagnostics.

**Requirement baseline:**
{"source":"delegated-user-approved-task","outcome":"A failed private Codex inventory response identifies the rejected validation predicate through a fixed, sanitized service-log stage.","scope":"Existing logger and _observe validation, with caller tests only.","constraints":"No validation, public result, custody, proof, authority, retry, cleanup, or live-state change; no native content logging.","completion_criteria":"One ensuing trial identifies the exact failed predicate; synthetic caller failures and positive control verify unchanged behavior and privacy."}

**Risk:** Elevated

**Complexity:** Simple

**Reason:** `app/codex_bridge_pipe.py` is a Redline watch-zone runtime surface. Validation diagnostics touch a security boundary but preserve its acceptance rules; one coherent code-and-test change.

**Discovery:** Matching live failure was `before-validate/invalid-response`. `_observe` currently combines envelope and tool predicates under one stage; `_record_failure` accepts only fixed stage/category allowlists and logs epoch/revision. Existing FakeDesktop tests exercise the private caller but mirror the validator, so they do not prove the real Desktop schema.

**Material assumptions:** Existing fixed-stage logging reaches the service log (confirmed for the incident). If caller tests expose a change in validation or failure handling, stop and revise the plan. If the actual response is needed to classify further, stop; never log it.

**Plan:** Keep the existing logger format and failure category. Add fixed validation substage names to `_INVENTORY_FAILURE_STAGES`; set one before each envelope/tool predicate in `_observe`, preserving predicate order and expressions. First add private-caller red tests with synthetic distinct failures and valid response; then minimal production change. Use existing `inventory_running`/`inventory_failure_records` fixtures. No new storage, API, or diagnostic framework. Stop if a stage is not uniquely attributable or content could leak.

**Verification plan:** When each synthetic response violates one predicate, private `register()` shall return the same native-failed unavailable result, fence custody, and log one fixed stage with the matching epoch/revision → parameterized private-caller test. When a valid response arrives, registration shall still succeed without a failure log → positive control. When native data is present, no logged field or proof shall include it → privacy assertions. Run focused, affected, then selector-required full suite once.

**Plan review:** Pending clean-context technical review by existing service-handoff security reviewer.

**Approvals:** Not required at this risk level; standing user implementation approval applies.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

2026-09-30: Entered Agent Workflow, confirmed whole-change application scope is non-exempt, reused a clean managed checkout, refreshed `origin/main`, and created `fix/codex-inventory-validation-code`. Classified Elevated/Simple before code edits. Awaiting independent plan review.

## Evidence

Incident stage/category is fixed and sanitized: `before-validate/invalid-response`; no raw response was read.

## Result review

Pending.
