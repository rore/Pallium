<!-- agent-workflow:start -->
**Outcome:** Relay messages sent without an explicit expiry remain deliverable until terminal handling, including across busy targets, dormant sessions, backlog turns, and service restarts.

**Target:** Pallium Relay HTTP, MCP forwarding, core expiry semantics, SQLite persistence, dashboard accounting, public documentation, and caller-surface E2E.

**Scope:** `core/relay.py`, `api/schemas.py`, `storage/sqlite_relay.py`, `tests/test_agent_relay_e2e.py`, `tests/test_dashboard.py` if dashboard behavior needs a regression, existing MCP forwarding tests only if their current omission assertion is insufficient, `docs/agent-relay.md`, `roadmap/features/add-wake-first-relay-delivery.md`, and this Work Record.

**Constraints:** Preserve explicit expiry bounds of 60 seconds through 7 days, legacy rows and their stored 24-hour expiries, exact-scope isolation, receipt/lease/idempotency contracts, Unicode, delivery redaction, and existing SQLite indexes. Omitted expiry must be exposed honestly as `expires_at: null`. No schema migration, dependency, real sleep, or slow default test. Use the existing MCP omission forwarding path and the smallest persistence representation that keeps every current expiry predicate correct.

**Completion criteria:** Newly omitted-expiry sends and atomic replies are durable and expose `expires_at: null`; an omitted-expiry idempotent retry succeeds while omitted-versus-explicit reuse conflicts; a durable message remains pending and claimable after deterministic time beyond seven days, dormant/busy delay, service-app restart, and bounded backlog turns; explicit minimum/maximum expiry and over-bound rejection remain unchanged; ACK and atomic reply work after delayed durable claim; dashboard pending/expired counts handle durable messages correctly; focused E2E, workflow, redline, API review, PR CI, and result review pass without adding wall-clock delay.

**Risk:** High

**Complexity:** Moderate

**Reason:** Pre-edit redline classifies `api/schemas.py` as a red public-contract surface requiring `api-review`; core/storage are watch and tests/docs are blue, with no boundary violation. The change spans API, core, persistence representation, idempotency, dashboard accounting, and restart lifecycle.

**Discovery:** HTTP request schemas currently replace omission with 86,400 seconds; core applies and validates that default; SQLite persists a non-null timestamp and all eligibility/expiry indexes assume it. MCP already forwards omission as `None`. A nullable SQLite column would require a table rebuild and coordinated null-safe changes to every expiry predicate. A migration-free UTC year-9999 sentinel round-trips through the existing SQLite DateTime column and remains eligible under current indexed comparisons; the public serializer can map only that internal value to `null`. Existing explicit rows remain unchanged. Existing E2E helpers cover exact scope, idempotency, backlog, explicit bounds, dormant sessions, Unicode, leases, and dashboard metrics; controllable-clock/reopen patterns avoid sleeps.

**Material assumptions:** SQLite and SQLAlchemy preserve the exact year-9999 UTC sentinel used for new durable rows; disproved by focused round-trip or CI failure, which returns persistence design to planning. No supported explicit expiry can equal the sentinel; enforced by the existing seven-day maximum. Current query predicates uniformly treat the sentinel as future; disproved by a caller that compares expiry outside the inspected storage/dashboard paths, which requires adding that path to scope before implementation. Public clients accept nullable `expires_at`; disproved by repository contract fixtures or API review, which returns schema design to planning.

**Plan:** Keep the existing non-null SQLite column and indexed expiry predicates. Change request/core defaults to `None`; validate only supplied durations. In `storage/sqlite_relay.py`, map omission to one internal UTC year-9999 sentinel, centralize only the minimum encode/match/render logic needed by send, reply, idempotency, delivery, and status views, and mark the deliberate sentinel ceiling with a `ponytail:` comment. Map the sentinel to `expires_at: null` at the API-facing storage views; preserve explicit timestamp behavior and legacy rows. Reuse existing MCP omission forwarding rather than changing MCP code. Add a compact caller-surface E2E that proves omitted send/reply, idempotency conflict, deterministic >7-day delay, persisted app restart, dormant/backlog delivery, and terminal ACK/reply; extend the existing dashboard test only if it does not already exercise the new default. Update the public Relay document and canonical roadmap state. Stop and return to planning if sentinel round-trip, public contract review, or an uninspected expiry predicate invalidates an assumption.

**Verification plan:** Omitted HTTP send/reply → caller-surface E2E asserts `expires_at: null`, delayed delivery, ACK/reply, and terminal status; MCP omission → existing real tool test plus HTTP E2E prove `None` is omitted then interpreted durably; idempotency → same omitted request is idempotent and omitted-versus-explicit conflicts; persistence → deterministic clock beyond seven days plus app close/reopen retains pending delivery and fresh claim; lifecycle → dormant target and backlog continuation remain claimable without sleeps; explicit expiry → existing min/max/over-max and deterministic expiry regressions remain green; dashboard → pending includes durable while expired metrics exclude it; compatibility → focused exact-scope, receipt/lease, Unicode, redaction, and reply tests; gates → workflow, redline, API-review label, diff check, PR CI, clean-context result review.

**Plan review:** Pending clean-context agent review; implementation blocked until findings are resolved.

**Approvals:** Approved by user 2026-09-06: "you have approval for all prs you manage"

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- Discovery and pre-edit redline classification are complete. No code edit has started; implementation is blocked on the required clean-context High-risk plan review.
- `apply_patch` was used for the initial Work Record; no machine fallback was needed.

## Evidence

- Current implementation defaults: `core/relay.py::RELAY_DEFAULT_EXPIRY_SECONDS`, `RelaySendRequest`, and `RelayReplyRequest` use 86,400 seconds.
- MCP forwarding already preserves omission as `expires_in_seconds=None` in `tests/test_mcp_server.py::test_relay_send_uses_exact_scope_and_preserves_unicode`.
- In-memory SQLAlchemy/SQLite probe round-tripped `9999-12-31T23:59:59.999999+00:00` through the existing non-null DateTime column and selected it with `expires_at > now`.

## Plan review

Pending.

## Result review

Pending.
