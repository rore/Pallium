<!-- agent-workflow:start -->
**Outcome:** A delayed Codex queue wake cannot make an agent treat an already-delivered Relay message as new work.

**Target:** Codex Relay wake prompt and its caller-surface regression coverage.

**Scope:** Add a backward-compatible `already_delivered` discriminator to both ACK paths and the existing HTTP response schema; teach the attributed wake prompt to stop before payload work when ACK reports it; assert the rule in the actual `codex queue --message` vector. No database schema, lease, scheduler, or new tool call.

**Constraints:** Preserve claim-before-wake, direct payload visibility, wake-first behavior, natural-turn fallback, and fail-closed stale receipt rejection. Do not add polling, renewal, cancellation, or a new tool call.

**Completion criteria:** A first valid ACK returns `already_delivered=false`; an idempotent same-receipt ACK returns `already_delivered=true`; stale-generation receipts remain 409; queued wake instructions require ACK/reply before work and stop on either the discriminator or receipt conflict; HTTP/MCP and queue subprocess regressions assert the observable contracts.

**Risk:** High

**Complexity:** Simple

**Reason:** `api/schemas.py` is a red HTTP-contract surface and the storage ACK result changes additively. High risk is required for the API/persistence contract; complexity stays Simple because the discriminator is computed atomically in the existing ACK transaction.

**Discovery:** Live merged-main smoke exposed delayed queue prompts for three deliveries after their leases were reclaimed by the normal hook. The hook safely delivered all three, while two old queued receipts returned 409 `receipt does not match delivered claim`. Existing `tests/test_relay_mcp_lifecycle.py` already proves stale receipts fail closed; the missing contract is telling the awakened model that this 409 means the queued copy is stale and must not be acted upon.

**Material assumptions:** An additive boolean response field is backward compatible for existing HTTP/MCP clients; disproved by schema/client regressions, which blocks merge. Agents follow the existing “acknowledge before other work” ordering and the new discriminator stop rule; disproved by a prompt regression, which blocks merge. Eliminating duplicate queued turns requires queue cancellation/lease renewal and is intentionally outside this safety fix.

**Plan:** In the two existing transactional ACK methods, return `already_delivered=true` only from the same-token/same-receipt idempotent branch and `false` on the state transition; add the field to the shared response schema with a default for compatibility. Amend the direct wake prompt to stop before payload work on `already_delivered=true` or receipt conflict, assert the queue argv contract, and cover first/idempotent/stale behavior through HTTP and MCP tests.

**Verification plan:** first ACK → HTTP/MCP tests assert `already_delivered=false`; same-receipt retry → HTTP/MCP tests assert `already_delivered=true`; stale-generation receipt → existing E2E asserts 409; delayed queue safety → subprocess argv test asserts the stop-before-work instruction; unchanged wake behavior → focused wake suite; packaging → workflow/redline and PR CI.

**Plan review:** Clean-context review found the prompt-only design unsafe because same-receipt idempotent ACK was indistinguishable from a first ACK. Revised atomic-discriminator plan approved by `/root/stale_wake_plan_review`; no remaining critical blockers.

**Approvals:** Approved by user 2026-09-01: "also if you find bugs, fix them!" — standing explicit authorization to fix Relay bugs discovered during live use.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- 2026-09-01: Reproduced the delayed-queue/stale-receipt path on merged main; all deliveries were already safely delivered, so the fix is limited to preventing duplicate action and confusing retries.
