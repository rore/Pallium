<!-- agent-workflow:start -->
**Outcome:** Relay callers receive a safe, deterministic transport/timeout diagnostic when the API is unreachable, including when the underlying exception has an empty string, while retry behavior and payload privacy remain unchanged.

**Target:** Pallium Relay MCP client and its caller-facing tests; optionally the local supervisor logging path only if a small, directly reusable crash-cause capture exists.

**Scope:** Inspect and minimally update `app/mcp/client.py` Relay GET/POST error normalization and the focused caller-surface tests. Investigate API child-process crash observability in existing supervisor/logging code; split it into a separate task if it requires new lifecycle or logging architecture. No service restart or local installation changes in this task.

**Constraints:** Preserve retry count, backoff, timeout budgets, structured `transport_unavailable` semantics, redaction, and no endpoint/payload/credential leakage. Do not change Relay routing, authorization, persistence, hooks, wake behavior, or API contracts unless discovery proves the client fix cannot satisfy the reported symptom. Do not modify production state or interrupt parallel dict-dev2 work.

**Completion criteria:** Empty transport exceptions produce a stable non-empty diagnostic with operation context and a bounded safe cause classification; non-empty exceptions remain redacted; GET and POST retry paths behave consistently; focused tests cover connection refusal, timeout, empty exception text, redaction, and retry exhaustion; any supervisor investigation is either implemented with a minimal verified reuse or explicitly split out with evidence and reason.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Redline classifies `app/mcp/client.py` as GRAY/watch and the focused tests as BLUE; the runtime surface defines cross-integration error behavior and must preserve retry, redaction, and transport-unavailable contracts. Supervisor crash capture is uncertain and may require separate lifecycle scope.

**Discovery:** Exact incident evidence: API exited at `2026-09-12T14:18:20.728Z`; Uvicorn became ready at `14:18:58.838Z`; Relay receive returned `All connection attempts failed`; a send retry ran about `25.1s` and returned an empty error. Current main `app/mcp/client.py` already returns structured `transport_unavailable` from `_post`, but `_get_or_error` and `_post_or_error` use `redact_sensitive(str(exc))`, allowing an empty string. The root-cause slice is therefore shared error normalization across Relay GET/POST retry paths, not a retry-budget change. Supervisor crash-cause capture remains unconfirmed and must stay read-only until its smallest existing hook is identified.

**Material assumptions:** The client exception type/message is the only cause data available at the caller boundary; disproved by a reproducible richer exception or supervisor log path, which should be preserved safely. Existing retry timing is intentional; disproved by focused tests showing budget regression, which requires re-planning rather than extending retries. A stable classification such as connection/timeout is sufficient without exposing endpoint details; disproved by an existing caller contract requiring a more specific safe code, which requires plan review.

**Plan:** 1. Invoke agent-workflow and record this task before production edits (completed). 2. Trace all callers of `_get_or_error`, `_post_or_error`, `_post`, and the redaction helper; inspect existing tests and supervisor startup/crash logging read-only. 3. Obtain clean-context plan review before code edits. 4. Implement the smallest shared safe formatter or normalization change, reusing existing error types/helpers; keep retry loops and budgets byte-for-byte behaviorally equivalent. 5. Add focused caller-surface tests for GET/POST, empty and non-empty exceptions, timeout/connection classes, redaction, and exhausted retries. 6. If supervisor capture is unrelated or larger than a narrow existing logging hook, record the evidence and split it out rather than expanding scope. 7. Run focused tests, affected subsystem tests, workflow/redline checks, and smart result review. Stop and re-plan for API/schema, persistence, authorization, hook, wake, or service-management changes.

**Verification plan:** GET and POST exhausted transport paths return the same stable non-empty safe diagnostic and preserve structured error fields -> focused MCP client tests. Exception text is redacted and endpoint/payload/credential values never appear -> sentinel-secret redaction tests. Retry count, timeout, and backoff remain unchanged -> existing retry tests plus focused regression. Any supervisor logging change captures child exit cause without secrets or restart-behavior changes; otherwise the investigation is explicitly split out -> targeted supervisor test or Work Record evidence. Repository readiness is clean -> focused tests, affected Relay/MCP tests, `C:\Dev\rore\Pallium\.venv\Scripts\python.exe scripts/agent-workflow-check.py --repo-root . --slug relay-transport-error-diagnostics`, and fresh redline report.

**Plan review:** Required clean-context review before implementation; this Work Record is the review target. Final implementation also requires smart result review because transport diagnostics are an integration contract.

**Approvals:** Approved by user 2026-09-12: "Approve"

**Exceptions:** —

<!-- Ready to implement | Blocked | Ready for review -->
**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- Work Record only. No production files, service state, installed integrations, or parallel task state changed.

## Evidence

- Branch/worktree created from current `main` at `df407c27`.
- Initial incident evidence and current client behavior are recorded in Discovery above; supervisor capture remains an explicit investigation boundary.

## Result review

- Pending clean-context plan review and subsequent implementation/result review.
