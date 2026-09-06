<!-- agent-workflow:start -->
**Outcome:** Relay messages sent without an explicit expiry remain deliverable until terminal handling, including across busy targets, dormant sessions, backlog turns, and service restarts.

**Target:** Pallium Relay HTTP, MCP forwarding, core expiry semantics, SQLite persistence, dashboard accounting, public documentation, and caller-surface E2E.

**Scope:** `core/relay.py`, `api/schemas.py`, `storage/sqlite_relay.py`, `tests/test_agent_relay_e2e.py`, `tests/test_dashboard.py` if dashboard behavior needs a regression, existing MCP forwarding tests only if their current omission assertion is insufficient, `docs/agent-relay.md`, `roadmap/features/add-wake-first-relay-delivery.md`, and this Work Record.

**Constraints:** Preserve explicit expiry bounds of 60 seconds through 7 days, legacy rows and their stored 24-hour expiries, exact-scope isolation, receipt/lease/idempotency contracts, Unicode, delivery redaction, and existing SQLite indexes. Omitted expiry must be exposed honestly as `expires_at: null`. No schema migration, dependency, real sleep, or slow default test. Use the existing MCP omission forwarding path and the smallest persistence representation that keeps every current expiry predicate correct.

**Completion criteria:** Newly omitted-expiry and explicit-JSON-null sends and atomic replies are durable and expose `expires_at: null`; omitted/null idempotent retries succeed while durable-versus-explicit reuse conflicts for both send and derived reply; legacy concrete-expiry rows remain compatible; a durable message remains pending and claimable after deterministic time beyond seven days, dormant/busy delay, a real file-backed SQLite app close/reopen, and bounded backlog turns; explicit minimum/maximum expiry and over-bound rejection remain unchanged; ACK and atomic reply work after delayed durable claim; dashboard pending/expired counts handle durable messages correctly; focused E2E, workflow, redline, API review, PR CI, and result review pass without adding wall-clock delay.

**Risk:** High

**Complexity:** Moderate

**Reason:** Pre-edit redline classifies `api/schemas.py` as a red public-contract surface requiring `api-review`; core/storage are watch and tests/docs are blue, with no boundary violation. The change spans API, core, persistence representation, idempotency, dashboard accounting, and restart lifecycle.

**Discovery:** HTTP request schemas currently replace omission with 86,400 seconds; core applies and validates that default; SQLite persists a non-null timestamp and all eligibility/expiry indexes assume it. MCP already forwards omission as `None`. A nullable SQLite column would require a table rebuild and coordinated null-safe changes to every expiry predicate. A migration-free UTC year-9999 sentinel round-trips through the existing SQLite DateTime column and remains eligible under current indexed comparisons; the public serializer can map only that internal value to `null`. Existing explicit rows remain unchanged. Existing E2E helpers cover exact scope, idempotency, backlog, explicit bounds, dormant sessions, Unicode, leases, and dashboard metrics; controllable-clock/reopen patterns avoid sleeps.

**Material assumptions:** SQLite and SQLAlchemy preserve the exact year-9999 UTC sentinel used for new durable rows; disproved by focused round-trip or CI failure, which returns persistence design to planning. No supported explicit expiry can equal the sentinel; enforced by the existing seven-day maximum. Current query predicates uniformly treat the sentinel as future; disproved by a caller that compares expiry outside the inspected storage/dashboard paths, which requires adding that path to scope before implementation. Public clients accept nullable `expires_at`; disproved by repository contract fixtures or API review, which returns schema design to planning.

**Plan:** Keep the existing non-null SQLite column and indexed expiry predicates. Change request fields to `int | None`, response fields to `datetime | None`, core defaults to `None`, and validate only supplied durations. In `storage/sqlite_relay.py`, map omission/JSON null to one internal UTC year-9999 sentinel; centralize the minimum encode, durable-match, and public-render logic used by send, atomic reply, both idempotency paths, delivery views, and status views; mark the deliberate sentinel ceiling with a `ponytail:` comment. Audit every Relay/dashboard expiry predicate before editing and preserve explicit timestamp behavior and legacy rows. Reuse existing MCP omission forwarding rather than changing MCP code. Add a compact caller-surface E2E that proves omitted/null send/reply, both idempotency conflicts, deterministic >7-day delay, real file-backed app close/reopen with sentinel UTC round-trip, dormant/backlog delivery, and terminal ACK/reply; extend the existing dashboard test only if it does not already exercise the new default. Update the public Relay document and canonical roadmap state. Stop and return to planning if sentinel round-trip, public contract review, or an uninspected expiry predicate invalidates an assumption.

**Verification plan:** Omitted and explicit-null HTTP send/reply → caller-surface E2E asserts `expires_at: null`, schema validation, delayed delivery, ACK/reply, and terminal status; MCP omission → existing real tool test plus HTTP E2E prove `None` is omitted then interpreted durably; idempotency → same durable send and derived reply are idempotent while durable-versus-explicit reuse conflicts, with legacy explicit rows unchanged; persistence → deterministic clock beyond seven days plus real file-backed SQLite app close/reopen proves exact sentinel round-trip, UTC normalization, pending retention, and fresh claim; lifecycle → dormant target and backlog continuation remain claimable without sleeps; explicit expiry → existing min/max/over-max and deterministic expiry regressions remain green; predicate audit/dashboard → every `expires_at` comparison is sentinel-safe, pending includes durable, and expired metrics exclude it; compatibility → focused exact-scope, receipt/lease, Unicode, redaction, and reply tests; gates → workflow, redline, API-review label, diff check, PR CI, clean-context result review.

**Plan review:** Clean-context Luna review under `## Plan review`; approved after five acceptance gaps were incorporated.

**Approvals:** Approved by user 2026-09-06: "you have approval for all prs you manage"

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Discovery, pre-edit redline classification, High-risk human approval, and clean-context plan review are complete. The reviewed implementation is ready; no code edit has started.
- `apply_patch` created the initial Work Record. A later update hit Windows sandbox error 1327, so the required narrow deterministic replacement fallback was used for this file only.
- Implemented the reviewed migration-free sentinel at the shared storage boundary, nullable HTTP contract fields, optional core validation, and public null rendering without changing schema or expiry predicates.
- Added the real file-backed restart/dormancy/backlog/send-reply idempotency E2E, strengthened dashboard durable/explicit assertions, and kept MCP response-budget coverage above its truncation boundary with an explicit expiry.

## Evidence

- Current implementation defaults: `core/relay.py::RELAY_DEFAULT_EXPIRY_SECONDS`, `RelaySendRequest`, and `RelayReplyRequest` use 86,400 seconds.
- MCP forwarding already preserves omission as `expires_in_seconds=None` in `tests/test_mcp_server.py::test_relay_send_uses_exact_scope_and_preserves_unicode`.
- In-memory SQLAlchemy/SQLite probe round-tripped `9999-12-31T23:59:59.999999+00:00` through the existing non-null DateTime column and selected it with `expires_at > now`.
- Revision `2fa3969d`: 383 Relay, wake, MCP, isolation, and dashboard tests passed in 27.50s; four existing Pydantic forward-reference warnings. The narrower 170-test surface passed in 16.22s and the new two-test slice in 4.66s. Workflow and diff checks are clean; no wall-clock sleep was added.

## Plan review

Clean-context Luna review found no fundamental blocker in the migration-free sentinel design. It required explicit nullable request/response types, shared send/reply sentinel and idempotency logic, a real file-backed close/reopen assertion, explicit JSON-null coverage, and an exhaustive expiry-predicate audit. All five are now explicit completion, plan, and verification requirements. The reviewer re-read the amended record and approved implementation with no remaining blocker.

## Result review

Pending.
