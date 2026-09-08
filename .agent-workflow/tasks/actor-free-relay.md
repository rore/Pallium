<!-- agent-workflow:start -->
**Outcome:** Relay routing, discovery, wake, and names are global to the local Pallium service and cannot be split by `actor_ref`; memory and Session History actor behavior is unchanged.

**Target:** Pallium.

**Scope:** Relay HTTP/MCP/core/storage contracts, Relay wake state, Relay dashboard views, Codex/Claude/OpenCode Relay integration payloads and guidance, Relay tests, operations/docs, and the canonical cross-repository Relay roadmap item.

**Constraints:** Keep `actor_ref` unchanged for memory and Session History. Preserve targeted-only sends, global-name takeover consent, endpoint identity, lifecycle, wake safety, and data. Ship no compatibility migration; convert only the installed local Relay database operationally after merge.

**Completion criteria:** Different actor strings cannot partition Relay sessions, messages, wake state, or names; `@name` is unique and reachable across all containers on the local service; regular sends remain targeted and name takeover remains opt-in; all Relay caller surfaces omit actor identity while memory/history still carry it; current-format startup rejects the retired actor-scoped Relay schema; full Relay lifecycle/E2E and focused regression suites pass; the installed database is backed up and converted once with row integrity verified, then the installed service/integrations pass health checks and a live cross-repository round trip.

**Risk:** High

**Complexity:** Moderate

**Reason:** Breaking Relay API/MCP and persistence key changes remove an existing claimed scope from routing. Redline requires API and persistence review; the installed SQLite database needs coordinated one-time conversion before new code starts.

**Discovery:** `actor_ref` currently flows through every Relay layer: HTTP/MCP schemas, `RelayService`, SQLite endpoint/message/alias ownership, Codex and Claude wake keys, hook ACKs, and dashboard filters. The same hook-derived value is separately used by memory/history and must remain there. Live local Relay state has 928 sessions, 1,142 messages/deliveries, and 18 name bindings across several accidental actor strings; only `claude-smoke-1` is duplicated, and `relaydev` is an unresolved binding. Names must be service-global, not container-scoped. The current schema validator can be changed to reject actor-bearing Relay tables without adding migration code.

**Material assumptions:** The Relay service is a trusted local single-user fabric; evidence of a supported shared/multi-user Relay deployment would stop implementation and require authenticated tenancy. The one-time local conversion may resolve the duplicated smoke-test name to its most recently seen endpoint and retain the unresolved `relaydev` reservation; a collision involving two current user-assigned names would stop conversion for explicit choice. Existing extra `actor_ref` JSON sent by already-running local clients may be ignored by Pydantic during the coordinated restart, but the published and newly loaded contracts will omit it; rejection of extra fields would require a separate compatibility decision.

**Plan:** 1. Replace Relay schema ownership with service-global sessions/messages and a single-column name key; update fail-fast current-format validation and indexes, with no migration path. 2. Delete actor validation/filtering/parameters from Relay core, storage, REST, MCP, callbacks, dashboard Relay queries, and wake registries/adapters while retaining container metadata for provenance and exact session identity. 3. Keep hook actor derivation solely for memory/history, but remove it from all Relay requests and wake credentials. 4. Align agent guidance, docs, and the canonical roadmap around service-global names, targeted-only sends, and takeover consent. 5. Replace actor-isolation coverage with service-global cross-container/name/takeover/wake/lifecycle E2E coverage and run focused then broad verification. 6. Obtain smart result review, push a PR, resolve review threads, and merge only when green. 7. From merged current main, back up and operationally convert the installed Relay DB, restart only through `scripts/restart-service.ps1`, verify DB integrity/health/integration paths, and run a live cross-repository round trip. Stop on unexpected alias collisions, row-count/integrity mismatch, boundary violation, or any memory/history actor regression. Key conventions: reuse existing endpoint IDs, transactions, claim receipts, wake registry persistence, and takeover flow; add no dependency or replacement identity layer. Target files/classes: `RelayService`; `SQLiteRelayMixin`; Relay records/schema validation; Relay API schemas/routes; MCP Relay context/client/tools; `ClaudeWakeRegistry` and Codex/Claude wake adapters; Relay-only dashboard endpoints; hook Relay payload builders; Relay E2E/integration tests; Relay guidance/docs/roadmap.

**Verification plan:** Actor variation cannot affect Relay and `@name` works across containers -> HTTP, MCP, hook, wake, and dashboard E2E assertions using differing actor values only on memory context. Targeted-only/name-takeover/lifecycle/expiry/claim/idempotence/concurrency/Unicode/error contracts remain intact -> focused Relay suites plus complete non-slow suite and import/redline/workflow checks. Memory/history actor scoping is unchanged -> focused actor-scoped-memory, visibility, history, and hook tests. Retired Relay schemas fail before mutation and fresh actor-free schemas initialize -> SQLite schema/isolation startup tests. Installed state is preserved and operational -> pre/post row and name audit, SQLite quick-check, required service health endpoints, installed integration path verification, and live cross-repository ACK.

**Plan review:** Pending clean-context review.

**Approvals:** Approved by user 2026-09-08: "yes, relay doesn't need the actor. it just created a whole lot of trouble" and "we need local migration if needed but since no one else is using pallium we don't need migrations code"

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

Discovery and redline classification complete on isolated branch `feat/actor-free-relay` from `origin/main` at `19f500ac`. No code edits have started. Redline found breaking API and schema changes with required `api-review` and `persistence-review`, no boundary violation. Awaiting clean-context plan review.

## Evidence

Pending implementation and verification.

## Result review

Pending.
