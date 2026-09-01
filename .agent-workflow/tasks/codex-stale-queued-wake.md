<!-- agent-workflow:start -->
**Outcome:** A delayed Codex queue wake cannot make an agent treat an already-delivered Relay message as new work.

**Target:** Codex Relay wake prompt and its caller-surface regression coverage.

**Scope:** Add an explicit stale-receipt stop rule to the existing attributed wake prompt and assert it is present in the actual `codex queue --message` vector. Reuse the existing receipt mismatch contract; no service, storage, API, lease, or schema change.

**Constraints:** Preserve claim-before-wake, direct payload visibility, wake-first behavior, natural-turn fallback, and fail-closed stale receipt rejection. Do not add polling, renewal, cancellation, or a new tool call.

**Completion criteria:** When an old queued prompt runs after the same delivery was reclaimed and delivered, its instructions require ACK/reply before work and explicitly require stopping on receipt mismatch/already-delivered state; the queue subprocess regression asserts the observable prompt contract; existing stale-receipt MCP E2E and focused wake tests pass.

**Risk:** Elevated

**Complexity:** Simple

**Reason:** `app/codex_wake.py` is a watch/gray integration surface. The fix is one prompt-contract clarification plus regression coverage and does not alter delivery state.

**Discovery:** Live merged-main smoke exposed delayed queue prompts for three deliveries after their leases were reclaimed by the normal hook. The hook safely delivered all three, while two old queued receipts returned 409 `receipt does not match delivered claim`. Existing `tests/test_relay_mcp_lifecycle.py` already proves stale receipts fail closed; the missing contract is telling the awakened model that this 409 means the queued copy is stale and must not be acted upon.

**Material assumptions:** Agents follow the existing “acknowledge before other work” ordering; disproved by a prompt regression, which blocks merge. Receipt mismatch remains fail-closed; disproved by the existing MCP E2E failing, which blocks merge. Eliminating duplicate queued turns requires queue cancellation/lease renewal and is intentionally outside this safety fix.

**Plan:** Amend the shared direct wake prompt with one explicit stale-copy stop instruction, add an assertion at the `codex queue --message` caller surface, run focused wake plus stale-receipt lifecycle E2E, and merge only after review/CI.

**Verification plan:** The queue subprocess test inspects the emitted message and asserts the stop rule; focused wake tests preserve loaded/unloaded behavior; `test_mcp_ack_stale_receipt_returns_409` proves the state boundary remains fail-closed; workflow/redline and PR CI verify packaging.

**Plan review:** Clean-context review required before guarded edit.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- 2026-09-01: Reproduced the delayed-queue/stale-receipt path on merged main; all deliveries were already safely delivered, so the fix is limited to preventing duplicate action and confusing retries.
