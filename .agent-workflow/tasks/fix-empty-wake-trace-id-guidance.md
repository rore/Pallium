<!-- agent-workflow:start -->
**Outcome:** Exact empty-wake instructions that supply a `relay-delivery-*` identifier cause the agent to pass that exact identifier as `message_id` to Relay trace, and the evaluation record reports the original valid fixture honestly.

**Target:** Pallium.

**Scope:** The three always-loaded guidance owners, their focused guidance/integration assertions, the prior optimization Work Record and roadmap outcome, and this Work Record.

**Constraints:** No Relay runtime, hook, installer, skill, tool-schema, service, or configuration change. Preserve all other compact-guidance safeguards and owner parity. Do not rerun unaffected smoke cases or claim Claude/OpenCode behavior evidence.

**Completion criteria:** The three owners explicitly map an exact supplied `relay-delivery-*` identifier into Relay trace's `message_id` argument; focused tests and owner-parity/budget checks pass; the original and relabeled case-4 fixtures and outcomes are documented without classifying the original as invalid; the affected original-prompt candidate decision passes under the existing Codex Luna-low smoke setup; independent review and CI pass.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Clean-context redline classified the integration guidance owners as gray and tests/records/roadmap as blue, with no boundary or checkpoint trigger. Moderate because the correction spans three generated owners, tests, prior evidence, one bounded model rerun, and review/PR closure.

**Discovery:** The original case-4 prompt said `Relay wake for relay-delivery-empty-example ... Inspect this exact delivery by message_id.` Relay trace accepts an exact delivery ID as the value of its `message_id` argument. Both original baseline and candidate responses failed to trace it. The fixture was then relabeled `Relay wake for message_id=relay-delivery-empty-example ...`; both relabeled runs passed and the original pair was incorrectly excluded as an ambiguous/invalid fixture. PR #202 merged before the delayed architect delivery exposed this error. Current guidance says only `trace only that delivery`, which did not teach the required argument mapping.

**Material assumptions:** The preserved original baseline case-4 result is valid reusable evidence; disproof would require a mismatch in prompt, model, catalog, stubs, or cap, in which case rerun both arms once. Adding one explicit argument-mapping clause is sufficient; disproof is failure of the original-prompt candidate rerun, which returns the task to planning without broader infrastructure work.

**Plan:** 1. Record and review this Work Record before code edits. 2. Add the smallest cross-owner clause: for an exact empty wake, pass the supplied exact delivery identifier as Relay trace's `message_id`; keep all other guidance unchanged. 3. Update only focused assertions and correct the prior Work Record/roadmap evidence: original pair valid and failed, relabeled pair passed but is not the primary oracle. 4. Reuse the preserved original baseline result and run only one fresh candidate decision on the exact original prompt with the same Codex Luna-low fixture/catalog/stubs/caps, preserving the response separately. Stop and return to planning if it fails. 5. Run focused tests, owner parity/budget/control checks, workflow/redline checks, independent result review, CI, resolve review threads, and merge. Key convention: one identical marker block across all three owners; no new helper or framework. Target files are exactly those named in Scope.

**Verification plan:** Exact delivery-ID mapping appears identically in all owners and emitted variants → focused guidance budget and integration tests plus byte-normalized parity check. Existing safeguards and budgets remain within their adjusted exact ceilings → the same focused tests. Original case-4 behavior improves without replacing the fixture → preserved baseline failure compared with one fresh candidate run on the exact original prompt, independently graded. Evidence is honest and scoped → clean-context/result review plus Work Record/roadmap diff inspection. Repository remains healthy → workflow/redline checks and PR CI.

**Plan review:** Pending clean-context review.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- 2026-09-15: Created from `origin/main` commit `f22c7574` in isolated branch `feat/fix-empty-wake-trace-id-guidance`. Applicability is non-exempt because integration and Work Record paths are in scope. Clean-context redline returned GRAY: integration owners gray, tests/records/roadmap blue, no boundary or checkpoint trigger. Agent-workflow feedback trigger 2 was dropped because the defect is owned by Pallium integration guidance, not upstream agent-workflow.

## Plan review

- Pending.

## Evidence

- Exact original setup preserved in the root task transcript and archived baseline/candidate JSONL: `Relay wake for relay-delivery-empty-example. If no Relay message block accompanies this turn, do not conclude the inbox is empty and do not receive or resend. Inspect this exact delivery by message_id.`
- Exact relabeling performed later: replace `Relay wake for relay-delivery-empty-example` with `Relay wake for message_id=relay-delivery-empty-example`; no other case-4 text changed.

## Result review

- Pending.
