<!-- agent-workflow:start -->
**Outcome:** Relay callers receive a safe, deterministic transport/timeout diagnostic when the API is unreachable, including when the underlying exception has an empty string, while retry behavior and payload privacy remain unchanged.

**Target:** Pallium Relay MCP client transport diagnostics and caller-facing tests.

**Scope:** Minimally update `app/mcp/client.py` Relay-only GET and retry-enabled POST error normalization plus focused MCP caller-surface tests. Preserve existing non-Relay memory/source-write behavior in `_post_or_error`. API child-process crash-cause logging is a separate investigation; no supervisor, service restart, or local installation change belongs in this task.

**Constraints:** Preserve retry count, backoff, timeout budgets, HTTP-status handling, cancellation propagation, structured transport semantics, and no endpoint/path/payload/credential leakage. Diagnostics are fixed allowlisted strings derived only from HTTP method and exception category; never include `str(exc)`, request URLs, dynamic paths, payload data, or arbitrary class names. Connection failures are distinct from read/write/pool timeouts. A POST timeout after connection may be ambiguous and must not be advertised as safely retryable. Do not change Relay routing, authorization, persistence, hooks, wake behavior, or API contracts unless discovery proves the client fix cannot satisfy the reported symptom. Do not modify production state or interrupt parallel dict-dev2 work.

**Completion criteria:** Relay connection failures produce stable non-empty `transport_unavailable` diagnostics; read/write/pool timeouts produce a distinct fixed `transport_timeout` diagnostic. GET may state retryability while ambiguous POST completion does not. No exception text or request data is serialized. Attempt-count exhaustion, deadline exhaustion, single-attempt receive, timeout categories, HTTP errors, cancellation, and MCP ToolError serialization retain their existing control flow. Non-Relay `_post_or_error` callers remain behaviorally unchanged.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Redline classifies `app/mcp/client.py` as GRAY/watch and the focused tests as BLUE; the runtime surface defines cross-integration error behavior and must preserve retry, redaction, and transport-unavailable contracts. Supervisor crash capture is uncertain and may require separate lifecycle scope.

**Discovery:** Exact incident evidence: API exited at `2026-09-12T14:18:20.728Z`; Uvicorn became ready at `14:18:58.838Z`; Relay receive returned `All connection attempts failed`; a send retry ran about `25.1s` and returned an empty error. Current main `app/mcp/client.py` already returns structured `transport_unavailable` from `_post`, but `_get_or_error` and `_post_or_error` use `redact_sensitive(str(exc))`, allowing an empty string. The root-cause slice is therefore shared error normalization across Relay GET/POST retry paths, not a retry-budget change. Supervisor already redirects child stdout/stderr and logs PID/label/exit code, but this incident retained no cause adjacent to the exit. That is a separate evidence/observability task, not part of client normalization.

**Material assumptions:** `httpx` exception categories provide enough fixed classification without their messages; if tests show a category cannot distinguish ambiguous POST completion, fail closed as non-retryable. `_get_or_error` is Relay-only, while `_post_or_error` must gate new normalization to `retry_relay_busy=True`; discovery of another caller needing the new contract returns to planning. Existing retry timing is intentional; any budget change requires re-planning.

**Plan:** 1. Invoke agent-workflow, record the task, and classify redline risk before production edits (completed). 2. Trace callers of `_get_or_error`, `_post_or_error`, `_post`, and existing retry tests (completed); keep supervisor crash-cause work separate. 3. Obtain clean-context plan review before code edits. 4. Add one fixed allowlist formatter keyed only by `GET|POST` and `connection|timeout`, used by Relay GET and retry-enabled Relay POST paths. Connect failures remain retryable; GET timeouts may be retried; POST read/write/pool timeout output is explicitly ambiguous/non-retryable. Preserve non-Relay calls, retries, deadlines, HTTP errors, and cancellation. 5. Extend existing focused tests for attempt and deadline exhaustion, single-attempt receive, empty/non-empty exception messages, connect/read/write/pool timeouts, no secret/URL/path/payload leakage, unchanged HTTP errors, cancellation, and MCP-visible serialization. 6. Run focused and affected MCP/Relay tests, workflow/redline checks, and smart result review. Stop and re-plan for retry-budget, API/schema, persistence, authorization, hook, wake, supervisor, or service-management changes.

**Verification plan:**
- Fixed category output and privacy -> existing MCP client tests extended for empty/non-empty connect exceptions and connect/read/write/pool timeouts on GET/POST, asserting no exception message, URL, path, payload, credential, or arbitrary class name.
- Retry and ambiguity semantics -> focused tests for attempt exhaustion, deadline exhaustion, single-attempt receive, unchanged count/backoff/budget, GET retryability, and POST timeout non-retryability.
- Compatibility -> focused tests proving retry-disabled memory/source writes keep existing behavior, HTTP errors are unchanged, and cancellation propagates.
- Caller surface -> MCP tool tests asserting bounded ToolError JSON preserves fixed `error`, `error_kind`, `retryable`, and `action` fields.
- Repository readiness -> focused/affected Relay-MCP tests, workflow check, fresh redline report, and smart result review.

**Plan review:** Clean-context smart review on `da5cacc8` withheld for fixed allowlisted categories, timeout ambiguity, non-Relay caller compatibility, complete retry/cancellation/MCP coverage, and removal of supervisor work. This revision incorporates every correction; re-review is pending. Final implementation requires smart result review.

**Approvals:** Approved by user 2026-09-12: "Approve"

**Exceptions:** —

<!-- Ready to implement | Blocked | Ready for review -->
**State:** Blocked or returned to planning
<!-- agent-workflow:end -->

## Implementation

- Work Record only. No production files, service state, installed integrations, or parallel task state changed.

## Evidence

- Branch/worktree created from current `main` at `df407c27`.
- Initial incident evidence and current client behavior are recorded in Discovery. Read-only supervisor inspection confirmed crash-cause retention is a separate task.
- Clean-context plan review withheld on five bounded contract gaps; all are incorporated in the revised plan, with no production edit.

## Result review

- Pending clean-context plan review and subsequent implementation/result review.
