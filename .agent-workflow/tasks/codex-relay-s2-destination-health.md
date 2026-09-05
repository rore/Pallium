<!-- agent-workflow:start -->
**Outcome:** Relay keeps recoverable in-flight deliveries pending while exposing a separate self-healing destination-health signal that can fail new sends fast.

**Target:** Pallium Agent Relay.

**Scope:** Relay delivery/session persistence, wake-result classification, sender-visible status surfaces, affected wake adapters, contract documentation, and caller-surface E2E tests.

**Constraints:** Destination health must never terminalize an existing delivery; passive fallback, exact-session isolation, restart durability, cross-platform behavior, and fast deterministic tests remain intact.

**Completion criteria:** Caller-surface E2E proves recoverable wake failure leaves the delivery pending, advisory unreachable rejects only new sends, exact registration self-heals, and only separate proven-terminal delivery evidence can mark a delivery failed.

**Risk:** High

**Complexity:** Moderate

**Reason:** The repository workflow checker detects High risk because the final intended scope changes the public Relay API response surface; no boundary violation or schema migration is currently implied. Moderate complexity spans persistence, wake adapters, public status, and E2E.

**Discovery:** `relay_send()` resolves only internal session state `active` and creates delivery state `pending`; ACK/expiry are the only terminal transitions. Claude transport maps POSIX `FileNotFoundError` and Windows `ERROR_FILE_NOT_FOUND` to `terminal`, then `ClaudeWakeRegistry.probe()` evicts the wake registration while the Relay delivery remains pending. Wake outcomes are only logged; `app/dependencies.py::_relay_wake_dispatch()` does not pass Relay persistence into the scheduler; Relay status exposes no destination health. `relay_turn(register_session=True)` already restores session state to `active`. Claude validation identified two distinct stores: `ClaudeWakeRegistry._Registration.state` controls probe eligibility, while `RelaySessionRecord.state` controls new-send admission. Both need an advisory `unreachable` transition; delivery state remains independent and unchanged.

**Material assumptions:** Reusing internal `RelaySessionRecord.state="unreachable"` is sufficient because `closed` takes precedence and does not need concurrent health; the durable Claude wake registry separately retains credentials in non-probed `_Registration.state="unreachable"`. Disprove if a supported lifecycle requires closed+unreachable observability, then return to planning. `last_seen_at` can serve as an optimistic Relay registration epoch because both `relay_turn(register_session=True)` and successful exact wake registration update it; feedback applies only while Relay state is active and `last_seen_at < attempt_started_at`; equality fails closed, and unrelated newer turns conservatively invalidate the result. Disprove with an ordering case that passes after re-registration, then add an explicit persisted epoch. Native missing-endpoint signals are advisory destination evidence, not terminal delivery evidence; if Windows/POSIX classification is unreliable, keep retryable and do not mark either store unreachable. No current signal proves a delivery terminal, so do not add delivery `failed`.

**Plan:** 1. Record three independent transition tables in the existing wake design. Delivery remains `pending|claimed|delivered|expired` and is never touched by health. Durable Claude registry capability is `idle|wake_inflight|busy|unreachable`: qualified missing changes `wake_inflight→unreachable`, retains socket/token, and `recovery_candidates()` excludes it; retryable/ambiguous rearms `idle`; exact `register()` clears it to probe-eligible. Relay destination health is internal session state `active|unreachable`, with `closed` taking precedence. 2. Add one exact-scope Relay storage/core health operation with an `attempt_started_at` compare-and-set guard (`state == active` and `last_seen_at < attempt_started_at`). Unreachable senders may send and rename because health describes inbound wake; exact/alias recipients resolved solely to unreachable fail synchronously; runtime fan-out still reaches active sessions. Successful `relay_turn` sets active and advances `last_seen_at`; after `ClaudeWakeRegistry.register()` succeeds, `/internal/claude-wake/register` does the same through the scoped Relay operation. Do not add a table, dependency, or delivery `failed`. 3. Rename native transport outcome `terminal` to destination `unreachable`; change `ClaudeWakeRegistry.probe()` from eviction to retained non-probed `unreachable`; wire `app/dependencies.py` and the existing scheduler callback to persist Relay health. Existing delivery remains pending. 4. Surface `destination_health` separately on session views and each delivery status; closed destinations report no advisory health, and delivery vocabulary is unchanged. 5. Add fast deterministic caller-surface E2E for recoverable failure, Windows/POSIX absent endpoint, both-store transitions, no reconciler probing while unreachable, composition wiring, new-send fail-fast, existing-delivery preservation, stale-result-after-register CAS including equal timestamps, close/register races, unreachable sender/alias behavior, exact registration self-heal of both stores, restart durability, scope isolation, idempotence, and absence of delivery `failed`. Target files: `storage/sqlite_relay.py`, `core/relay.py`, `core/claude_wake.py`, `app/claude_wake.py`, `app/claude_wake_transport.py`, `app/dependencies.py`, `api/routes.py`, `api/schemas.py`, existing Relay/Claude E2E tests, and wake contract docs. Key conventions: persist before wake callback, exact scope, fail closed, deterministic clocks/events, no wall sleeps, no new dependency/schema abstraction. Stop and return to planning if the timestamp CAS assumption fails.

**Verification plan:** Retryable/ambiguous wake → delivery remains pending, Relay health stays active, registry rearms idle → HTTP composition E2E. Qualified missing endpoint → delivery remains pending, Relay and registry become unreachable, reconciler does not probe, and new exact/alias send fails synchronously → Windows/POSIX classifier plus HTTP/reconciler E2E. Exact Relay turn or successful internal Claude wake register → Relay active, registry probe-eligible, advanced epoch, pending delivery receivable once; stale older result and close cannot overwrite → deterministic ordering/race E2E. Unreachable sender may send/rename while runtime fan-out excludes it as recipient → selector E2E. Cross-scope feedback cannot alter either store → isolation E2E. HTTP/MCP status exposes `destination_health` separately without adding delivery state → schema/client tests. Run focused suites, workflow checker, redline/API review, `git diff --check`, then one installed Claude witness.

**Plan review:** Clean-context agent `s2_plan_review` approved the corrected concurrency/wiring plan. Claude architect `claude-code:@claude_arch` then approved the finalized three-state-machine plan with no blockers, including the strict timestamp CAS ceiling and required ordering E2E.

**Approvals:** Pending explicit human approval after Claude-specific plan validation.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- Established task context before code discovery; no product code changed.
- Repository checker raised Risk from Elevated to High because the planned diff includes the public API response surface; implementation remains blocked on Claude validation and explicit human approval.

## Plan review

- Initial clean-context review (agent `s2_plan_review`) found omitted `app/dependencies.py` wiring, stale asynchronous outcome risk after re-registration, undefined closed/sender/alias semantics, and underspecified per-delivery status. First re-review required equality to fail closed and explicit internal Claude registration→Relay wiring. The corrected plan now uses strict `last_seen_at < attempt_started_at`, treats unrelated newer activity as conservative invalidation, and wires successful exact wake registration to the scoped Relay health operation. Final focused re-review approved these corrections, conditional only on the pending one-shot Claude capability retry decision.

- Claude architect validation chose a retained, non-probed registry-side `unreachable` state, plus separate Relay destination `unreachable`; it rejected both one-second re-probing and capability eviction. The plan now changes the probe eviction branch, excludes unreachable registrations from reconciliation, self-heals both stores on exact registration, and leaves delivery state unchanged.
- Final Claude read-only confirmation approved the updated Work Record with no blockers and retained the installed-Claude witness as a post-test release gate, not merge authority.

## Evidence

- Pending.

## Result review

- Pending.
