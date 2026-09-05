<!-- agent-workflow:start -->
**Outcome:** Relay keeps recoverable in-flight deliveries pending while exposing a separate self-healing destination-health signal that can fail new sends fast.

**Target:** Pallium Agent Relay.

**Scope:** Relay delivery/session persistence, wake-result classification, sender-visible status surfaces, affected wake adapters, contract documentation, and caller-surface E2E tests.

**Constraints:** Destination health must never terminalize an existing delivery; passive fallback, exact-session isolation, restart durability, cross-platform behavior, and fast deterministic tests remain intact.

**Completion criteria:** Caller-surface E2E proves recoverable wake failure leaves the delivery pending, advisory unreachable rejects only new sends, exact registration self-heals, and only separate proven-terminal delivery evidence can mark a delivery failed.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Redline found API red-zone review if response schemas/routes change, plus watched core/storage behavior; no boundary violation or schema migration is currently implied. Moderate complexity spans persistence, wake adapters, public status, and E2E.

**Discovery:** `relay_send()` resolves only internal session state `active` and creates delivery state `pending`; ACK/expiry are the only terminal transitions. Claude transport currently maps POSIX `FileNotFoundError` and Windows `ERROR_FILE_NOT_FOUND` to `terminal`, after which `ClaudeWakeRegistry.probe()` evicts the wake registration while the Relay delivery remains pending. Wake outcomes are only logged; Relay status exposes no destination health. `relay_turn(register_session=True)` already restores session state to `active`. The existing string session-state column can represent advisory `unreachable` without a schema migration, but API response changes require api-review.

**Material assumptions:** Reusing internal `RelaySessionRecord.state="unreachable"` is sufficient because closed destinations do not need a concurrent health value; disprove if a supported lifecycle requires closed+unreachable observability, then return to planning. Native missing-endpoint signals are advisory destination evidence, not terminal delivery evidence; if Windows/POSIX classification cannot be made reliable, leave the outcome retryable and do not mark unreachable. No current signal proves a delivery terminal, so this slice must not add delivery `failed` merely for completeness.

**Plan:** 1. Record the independent delivery/destination transition tables in the existing wake design: delivery remains `pending|claimed|delivered|expired`; advisory destination is `active|unreachable`, and no health transition mutates a delivery. 2. Reuse the existing Relay session-state column for internal `unreachable`; add one exact-scope storage/core operation to set health, keep `relay_turn(register_session=True)` as the self-healing `active` transition, and reject only new exact/alias sends resolved solely to an unreachable session. Do not add a table, dependency, or delivery `failed` state. 3. Rename native transport classification from delivery-sounding `terminal` to destination `unreachable`; feed that normalized outcome through the existing wake callback into Relay health without exposing secrets or model-supplied identity. Preserve the in-flight delivery. Stop and return to planning if Claude review says a removed endpoint requires a different bounded retry/re-registration contract. 4. Surface destination health separately from delivery state in sender status/session views and sanitized logs; retain existing lifecycle fields. 5. Add fast deterministic caller-surface E2E for recoverable failure, Windows/POSIX absent endpoint, new-send fail-fast, existing-delivery preservation, exact registration self-heal, restart durability, scope isolation, idempotence, and proof that no adapter outcome can create delivery `failed`. Target files: `storage/sqlite_relay.py`, `core/relay.py`, `core/claude_wake.py`, `app/claude_wake.py`, `app/claude_wake_transport.py`, `api/routes.py`, `api/schemas.py`, existing Relay/Claude E2E tests, and wake contract docs. Key conventions: persist before wake callback, exact container/actor/runtime/session scope, fail closed, deterministic clocks/events, no wall-clock sleeps, no new dependency or schema abstraction.

**Verification plan:** When a retryable/ambiguous wake fails, the existing delivery shall remain pending and destination health shall stay active → HTTP caller-surface E2E. When a qualified missing endpoint is observed, the existing delivery shall remain pending while destination health becomes unreachable and a new exact/alias send fails synchronously → Windows/POSIX classifier tests plus HTTP E2E. When the exact session registers again, destination health shall become active and the pending delivery shall remain receivable exactly once → restart/re-registration HTTP+hook E2E. Cross-scope registration or wake feedback shall not read or alter health → isolation E2E. Relay/MCP status shall expose destination health separately without changing delivery state vocabulary → schema/client contract tests. Focused suites, workflow checker, redline/API review, `git diff --check`, and installed Claude witness only after deterministic tests pass.

**Plan review:** Pending clean-context workflow review and one-shot Claude-specific validation.

**Approvals:** Not required at this risk level unless redline raises the task to High.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- Established task context before code discovery; no product code changed.

## Evidence

- Pending.

## Result review

- Pending.
