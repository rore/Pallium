<!-- agent-workflow:start -->
**Outcome:** Relay keeps recoverable in-flight deliveries pending while exposing a separate self-healing destination-health signal that can fail new sends fast.

**Target:** Pallium Agent Relay.

**Scope:** Relay delivery/session persistence, wake-result classification, sender-visible status surfaces, affected wake adapters, contract documentation, and caller-surface E2E tests.

**Constraints:** Destination health must never terminalize an existing delivery; passive fallback, exact-session isolation, restart durability, cross-platform behavior, and fast deterministic tests remain intact.

**Completion criteria:** Caller-surface E2E proves recoverable wake failure leaves the delivery pending, advisory unreachable rejects only new sends, exact registration self-heals, and only separate proven-terminal delivery evidence can mark a delivery failed.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Redline found API red-zone review if response schemas/routes change, plus watched core/storage behavior; no boundary violation or schema migration is currently implied. Moderate complexity spans persistence, wake adapters, public status, and E2E.

**Discovery:** `relay_send()` resolves only internal session state `active` and creates delivery state `pending`; ACK/expiry are the only terminal transitions. Claude transport maps POSIX `FileNotFoundError` and Windows `ERROR_FILE_NOT_FOUND` to `terminal`, then `ClaudeWakeRegistry.probe()` evicts the wake registration while the Relay delivery remains pending. Wake outcomes are only logged; `app/dependencies.py::_relay_wake_dispatch()` does not pass Relay persistence into the scheduler; Relay status exposes no destination health. `relay_turn(register_session=True)` already restores session state to `active`. The existing string session-state column can represent advisory `unreachable` without a schema migration. Clean review found that asynchronous wake feedback needs compare-and-set protection against a later registration.

**Material assumptions:** Reusing internal `RelaySessionRecord.state="unreachable"` is sufficient because `closed` takes precedence and does not need concurrent health; disprove if a supported lifecycle requires closed+unreachable observability, then return to planning. `last_seen_at` can serve as an optimistic registration epoch because both `relay_turn(register_session=True)` and successful exact wake registration will update it; an unreachable result applies only while state is active and `last_seen_at <= attempt_started_at`. Disprove with a same-process ordering case that can pass this guard after re-registration, then add an explicit persisted epoch. Native missing-endpoint signals are advisory destination evidence, not terminal delivery evidence; if Windows/POSIX classification is unreliable, keep retryable and do not mark unreachable. No current signal proves a delivery terminal, so do not add delivery `failed`.

**Plan:** 1. Record independent transition tables in the existing wake design: delivery remains `pending|claimed|delivered|expired`; advisory destination is `active|unreachable`; health never mutates delivery. 2. Reuse internal `RelaySessionRecord.state` for `unreachable`; add one exact-scope storage/core health operation with an `attempt_started_at` compare-and-set guard (`state == active` and `last_seen_at <= attempt_started_at`). `closed` wins; unreachable senders may send and rename because health describes inbound wake; exact/alias recipients that resolve only to unreachable fail synchronously; runtime fan-out still reaches active sessions. Successful `relay_turn` or exact wake registration sets active and advances `last_seen_at`. Do not add a table, dependency, or delivery `failed`. 3. Rename native transport outcome `terminal` to destination `unreachable`; wire `app/dependencies.py` and the existing scheduler callback to persist it. Preserve the in-flight delivery. Pending Claude validation decides whether the stale wake capability becomes non-probed until exact register, is removed, or uses bounded retry; unbounded one-second probing is forbidden. 4. Surface `destination_health` separately on session views and each delivery status; closed destinations report no advisory health, and delivery vocabulary is unchanged. 5. Add fast deterministic caller-surface E2E for recoverable failure, Windows/POSIX absent endpoint, composition wiring, new-send fail-fast, existing-delivery preservation, stale-result-after-register CAS, close/register races, unreachable sender/alias behavior, exact registration self-heal, restart durability, scope isolation, idempotence, and absence of delivery `failed`. Target files: `storage/sqlite_relay.py`, `core/relay.py`, `core/claude_wake.py`, `app/claude_wake.py`, `app/claude_wake_transport.py`, `app/dependencies.py`, `api/routes.py`, `api/schemas.py`, existing Relay/Claude E2E tests, and wake contract docs. Key conventions: persist before wake callback, exact scope, fail closed, deterministic clocks/events, no wall sleeps, no new dependency/schema abstraction. Stop and return to planning if Claude validation rejects the capability retry/re-registration transition or if the timestamp CAS assumption fails.

**Verification plan:** Retryable/ambiguous wake → existing delivery remains pending and destination stays active through HTTP composition E2E. Qualified missing endpoint → existing delivery remains pending, destination becomes unreachable, and new exact/alias send fails synchronously through Windows/POSIX classifier plus HTTP E2E. Exact register after failure → active health, advanced epoch, pending delivery receivable once; stale older result and close cannot be overwritten → deterministic ordering/race E2E. Unreachable sender may send/rename while runtime fan-out excludes it as a recipient → selector E2E. Cross-scope feedback cannot alter health → isolation E2E. HTTP/MCP status exposes `destination_health` separately without adding delivery state → schema/client tests. Run focused suites, workflow checker, redline/API review, `git diff --check`, then one installed Claude witness.

**Plan review:** Initial clean-context review rejected the draft; findings and remediation are recorded under Plan review. Corrected plan pending focused re-review and one-shot Claude-specific validation.

**Approvals:** Not required at this risk level unless redline raises the task to High.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- Established task context before code discovery; no product code changed.

## Plan review

- Initial clean-context review (agent `s2_plan_review`) found omitted `app/dependencies.py` wiring, stale asynchronous outcome risk after re-registration, undefined closed/sender/alias semantics, and underspecified per-delivery status. The corrected plan adds composition wiring, a no-schema `last_seen_at` compare-and-set guard, explicit transition precedence, and race/status E2E. Re-review pending.

## Evidence

- Pending.

## Result review

- Pending.
