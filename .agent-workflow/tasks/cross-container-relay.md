<!-- agent-workflow:start -->
**Outcome:** Relay users can target one known endpoint or actor-global name across containers, with safe name takeover and no regular-send broadcast.

**Target:** Pallium Relay.

**Scope:** Relay endpoint/message/delivery persistence and migration; selector, naming, claim/reply/ACK/status, and wake routing; HTTP/MCP response contracts and agent instructions; focused caller-surface E2E, migration, wake, and regression tests; Relay docs after installed witnesses pass.

**Constraints:** Keep actor_ref as the trust boundary; keep container_ref as location/provenance; reuse RelaySessionRecord.id and the existing delivery engine; keep recipient listing container-local; preserve receipts, leases, idempotency, pending deliveries, and memory/history isolation; never silently resolve legacy ambiguity or alias collisions; reject bare-runtime sends without rows or wake; no broadcast API, coordination scopes, global discovery, or unrelated refactor.

**Completion criteria:** Exact endpoint IDs and actor-global names route one message across containers; name conflicts require explicit replace_existing takeover and transfer only the name; claims, replies, ACK/status, wake/recovery, lifecycle, migration, legacy ambiguity, actor isolation, validation boundaries, concurrency, and restart behavior pass through public HTTP/MCP/hook surfaces; existing Relay regressions pass; installed supported-runtime dogfood succeeds before public docs claim the feature.

**Risk:** High

**Complexity:** Large

**Reason:** Redline reports SCHEMA_CHANGE + API_CHANGE on persistence and public Relay contracts. High because endpoint identity, actor isolation, alias ownership, and queued delivery routing change; Large because persistence, HTTP/MCP, wake adapters, integrations, migration, and independent E2E outcomes are involved.

**Discovery:** Current code keys sessions and all send/claim/reply/status/ACK/wake paths through container_ref plus runtime/native session. RelaySessionRecord.id already provides a durable canonical ID but is not exposed. Messages lack sender endpoint ID; deliveries lack recipient endpoint ID/location. Bare runtime selectors broadcast. Alias uniqueness and resolution are container/runtime scoped. The split Relay DB migration copies ORM rows once and needs additive source/target column handling. Claude architecture review found endpoint-ID-first ordering mandatory to avoid reply failures, ambiguous legacy 500s, and inbox adoption. Redline requires persistence-review and api-review; no forbidden import is planned. Roadmap prerequisites RW-012–014 are fixed.

**Material assumptions:**
- RelaySessionRecord.id can be exposed as the canonical exact address without a second identity layer. Disproved by a lifecycle or integration path that cannot retain it; if disproved, return to planning before schema edits.
- BEGIN IMMEDIATE is the only alias mutation path, so actor-global uniqueness can be enforced transactionally while legacy duplicate aliases remain representable until explicit takeover; the old narrower constraint may remain redundant. Disproved by another write path or reviewer evidence that a database constraint is required; then return to planning for an alias registry/table or table rebuild.
- A session appearing at a new container/runtime/native location without presenting an existing endpoint ID is a new endpoint; v1 does not infer relocation. Disproved by an existing integration contract requiring identity-preserving moves; then expand and re-review the plan.
- Nullable endpoint columns plus actor/local legacy fallback can preserve pre-migration orphan rows, while every new message/delivery stores endpoint IDs. Disproved if migration tests show misrouting or loss; then stop and choose an explicit synthetic/orphan representation.

**Plan:**
1. Add nullable sender_endpoint_id to Relay messages and recipient_endpoint_id plus recipient_container_ref to deliveries; expose RelaySessionRecord.id as endpoint_id. Add idempotent additive-column/index migration and backfill in both same-DB and split-DB initialization before changing routing. New writes always populate IDs.
2. Extend selector validation with canonical relay-session-* exact IDs and @global-name, retain runtime:session_ref and runtime:@name as compatibility forms with explicit ambiguity/runtime-mismatch errors, and reject bare runtimes before persistence. Keep list discovery container-local but return canonical selectors.
3. Re-key targeted send, turn/claim, reply, status, receipt/token ACK, pending lookup, idempotency, expiry, and recovery authorization to actor plus canonical endpoint IDs. Preserve a narrowly scoped same-container fallback only for legacy rows whose endpoint columns could not be backfilled.
4. Make aliases actor-global in the serialized storage transaction. Normal conflicts change nothing; replace_existing clears all prior owners and assigns one owner atomically. Alias transfer never moves existing deliveries. Legacy duplicate aliases remain unusable until explicit takeover.
5. Route immediate and recovered wake attempts from the recipient endpoint/location stored or joined by endpoint ID, not the sender request scope. Keep existing runtime adapters and next-turn fallback.
6. Update HTTP/MCP response models, recipient rendering, tool descriptions, and Claude Code/Codex/OpenCode instructions for endpoint IDs, global names, conflict → ask user → approved takeover, direct takeover instructions, and no broadcast.
7. Extend public-surface E2E first around cross-container exact/alias journeys and failure-with-zero-side-effect cases, then migration, duplicate identity/name, concurrency, lifecycle, wake/restart, Unicode/length, actor isolation, and existing regression coverage. Update README/Relay docs only after installed witnesses pass.
Key conventions: no new delivery engine or dependency; API remains thin over core; storage does not import app/capabilities; endpoint-first migration precedes removal of container routing gates. Target files: storage/sqlite_schema.py, storage/sqlite.py, storage/sqlite_relay.py, core/relay.py, api/schemas.py, app/dependencies.py, app/mcp/server.py, relevant integration instruction sources, focused Relay tests, and post-witness docs. Stop on a forbidden import, unverifiable migration, actor-isolation regression, or need for a second routing abstraction.

**Verification plan:**
- When two same-actor endpoints occupy different containers, exact ID and global-name sends shall produce one delivery and support receive → ACK/reply → status → focused HTTP and MCP E2E.
- When a bare runtime, ambiguous legacy selector, occupied name without takeover, or cross-actor operation is attempted, no message/delivery/name/wake state shall change → negative E2E plus public read-path assertions.
- When takeover is approved or concurrent, exactly one global owner shall receive new sends while prior queued/claimed deliveries remain at their endpoint → naming concurrency/lifecycle E2E.
- When an old database starts, endpoint columns shall be added/backfilled exactly once and legacy duplicates/orphans shall remain deterministic across restart and split migration → file-backed migration E2E.
- When a cross-container delivery is persisted or recovered, wake shall use the recipient location and fallback shall retain the message without misrouting → wake adapter/recovery E2E.
- When empty/max/over-max, normalization, Unicode, expiry, lease, retry, duplicate ID, close/reactivate, and restart boundaries occur, the observable contract shall hold → focused boundary matrix in existing Relay E2E modules.
- When the final diff is ready, import boundaries, workflow predicates, targeted Relay suites, full test suite, and installed cross-runtime dogfood shall pass → redline/workflow scripts, pytest, service wrapper health checks, and installed witnesses.

**Plan review:** Pending clean-context architecture review.

**Approvals:** Pending post-review user approval.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Checkpoint: persistence-review + api-review

What is changing: Migrate Relay from container-scoped resolution to actor-scoped canonical endpoint addressing and expose exact/alias-only targeting through HTTP and MCP.

Why: Known endpoints must communicate across containers without weakening actor isolation or introducing broadcast.

Affected contract / model / boundary: Relay session/message/delivery identity, alias uniqueness, selector compatibility, receipt/ACK/reply/status authorization, and destination wake location.

Compatibility / migration risk: High — existing rows may contain duplicate native identities and aliases legal under the old scope; queued and claimed deliveries must retain exactly-once behavior.

Verification plan: Public HTTP, MCP, and hook E2E across containers; migration/restart tests; duplicate native-ID and alias-transfer races; actor isolation; bare-runtime rejection without side effects; destination-aware wake/fallback; existing delivery-engine regressions.

## Implementation

- Established isolated branch `feat/cross-container-relay` from `origin/main` at `88ed0e64`.
- Discovery and pre-edit redline classification completed. No production code has been edited.
- Intended production files are limited to the schema/migration/store/service/API/MCP/wake/instruction surfaces named in Plan; tests and post-witness docs may change within Scope.

## Evidence

- Pre-edit inventory: current Relay code and tests plus roadmap feature.
- Redline: MIXED SCHEMA_CHANGE + API_CHANGE; persistence-review and api-review; no boundary violation.

## Plan review

Pending clean-context strong-model review.

## Result review

Pending.
