<!-- agent-workflow:start -->
**Outcome:**
Relay writes remain responsive under concurrent multi-agent traffic and memory ingestion, without weakening SQLite durability or lifecycle handling.

**Target:**
Pallium SQLite storage, Relay persistence, service lifecycle, migration, health, backup/maintenance behavior, and E2E coverage.

**Scope:**
Read-only contention investigation first. If evidence supports isolation: shared SQLite lifecycle/configuration code, Relay database routing and migration, operational status/maintenance behavior, indexes, concurrency stress tests, documentation, and roadmap alignment.

**Constraints:**
Preserve existing Relay data and API/MCP behavior; use one shared implementation for WAL, timeout, schema lifecycle, backup/maintenance conventions; no second service; no unbounded retry loops; stop if isolation is not supported by evidence or the migration cannot be made safely.

**Completion criteria:**
Evidence identifies the lock source and validates or rejects database isolation; if implemented, ingestion cannot block Relay writes, existing Relay rows migrate exactly once, both databases receive equivalent SQLite lifecycle handling, required Relay indexes are justified, concurrent-agent stress and lifecycle E2E pass, CI/review are clean, and local integrations/service are updated.

**Risk:**
High

**Complexity:**
Moderate

**Reason:**
This changes a red-zone persistence and migration surface. Complexity is moderate because it spans storage initialization, operational lifecycle, compatibility migration, and concurrency verification within one service.

**Discovery:**
GO decision supported by independent code audit and disposable-file measurement. SQLite WAL still permits only one writer per file; all Relay lifecycle operations use _begin_immediate, while ingestion queue claims and large process-result commits share the same writer. Shared-file probes with a ~450 ms competing writer delayed Relay to ~0.48–0.54 s and a longer lock exhausted retries; the same Relay operations on a separate file completed in 5–8 ms while the ingestion lock remained held. Relay has no foreign keys, transactions, or lifecycle dependencies outside relay_sessions, relay_messages, and relay_deliveries. Existing discovery, claim, message, and expiry indexes match measured query plans; speculative alias/order indexes are not justified at bounded session cardinality. Operational coupling requiring changes: schema initialization, config/process construction, dashboard access, file-size health, snapshots/restore/prune, WAL/checkpoint/free-page maintenance, and idempotent legacy-row migration. Redline classified this High risk (SCHEMA_CHANGE + CONFIG_CHANGE) with persistence and architecture review required; no boundary violation was found.
**Material assumptions:**
1. Relay has no required atomic invariant with memory/ingestion tables. Confirmed by schema and caller inventory; reassess if implementation discovers an indirect dependency.
2. A second SQLite file can reuse the same lifecycle implementation. Supported by parameterizing the existing engine hooks, schema lock, immediate-transaction helper, planner optimization, reclaim, and snapshot functions; stop if implementation requires duplicated lifecycle code.
3. Existing Relay rows can be migrated idempotently without loss. The plan requires an initialization-time, file-locked, atomic import with a durable source marker and full ID verification; stop if the probe cannot demonstrate interrupted/resumed safety.
4. Relay transactions remain short enough that a bounded Relay-specific acquisition budget absorbs multi-agent fan-in. Disproof: stress tests show failures or excessive tail latency after isolation; action: measure the lock holder and revise before merge, not add unbounded retries.
**Plan:**
1. Preserve the public StorageProvider/RelayService contract. Extend SQLiteStorageProvider with an optional Relay URL/session factory; direct one-file construction remains available for compatibility tests, while application configuration derives a sibling pallium-relay.db unless explicitly configured.
2. Reuse one implementation for both files: introduce one shared engine/lifecycle primitive for connection PRAGMAs (auto_vacuum=INCREMENTAL, WAL, default busy timeout), schema file locking, planner optimization, immediate transaction acquisition, reclaim/checkpoint, and snapshot primitives. Feed it explicit role-specific schema plans: main keeps its current schema/migrations/FTS/backfills; Relay creates only the three Relay tables, Relay indexes, and migration metadata. A schema-shape test rejects accidental memory tables in the Relay file.
3. Route every method in SQLiteRelayMixin and dashboard Relay summary through the Relay session factory. Give the isolated, short Relay transactions a bounded acquisition budget; preserve sanitized relay_busy as the exhaustion contract and existing MCP bounded retry behavior.
4. Migration is permitted only while the previous service process tree is fully stopped; scripts/restart-service.ps1 and documented Unix stop/start are the supported upgrade paths. Under both source and target migration locks, atomically import legacy Relay rows into the new file, preserve all IDs/state/timestamps/tokens/relationships, and verify every legacy ID. After target commit, write a split-activated marker with canonical target identity into the main DB. Reruns before that marker are idempotent; interrupted transactions roll back. Once marked, a missing/mismatched Relay file or any legacy ID absent from the target fails startup rather than silently remigrating stale data. Legacy rows remain untouched as rollback evidence, but rollback after new Relay writes is explicitly not automatic. Add a competing-old-writer rejection/precondition E2E.
5. Generalize snapshot/restore/prune and shutdown orchestration around a two-file generation: write both temporary backups, validate both, atomically publish both names, then publish a manifest/commit marker last. Restore only the newest complete validated generation; never combine generations. If live state is partial after split, fail closed. Preserve compatibility with a legacy main-only snapshot only when the main DB has no split marker, then migrate it under the stopped-service rule. Generalize free-page reclaim/checkpoint and planner optimization over both engines. Report both database sizes and migration readiness in status/dashboard without changing Relay API/MCP payloads.
6. Configuration accepts plain file-backed SQLite URLs. An omitted Relay URL derives a sibling pallium-relay.db; canonical path equality is rejected. sqlite:///:memory: remains an explicit shared compatibility mode for direct unit tests only, while isolation tests use two temporary files. Unsupported/non-file URLs fail with a clear error. Keep the current Relay indexes unless query-plan tests disprove adequacy; add no speculative alias/order index and no Relay retention semantics.
7. Add bounded stress and lifecycle coverage, update operations/design/roadmap, obtain clean-context result review, run full CI, merge only with resolved findings, then restore local main, reinstall integrations, restart with scripts/restart-service.ps1, and verify health plus a live Relay round trip.

Key conventions and target surfaces: storage/sqlite.py, storage/sqlite_queue.py, storage/sqlite_relay.py, storage/sqlite_schema.py, app/config.py, app/dependencies.py, app/snapshot.py, app/supervisor.py, app/main.py, app/dashboard.py, focused tests, docs/context/operations.md, and roadmap. No API schema change, new service, new dependency, suppression, or cross-layer import is permitted.
**Verification plan:**
When ingestion holds the primary writer, Relay shall send/claim/reply/ACK/status on the isolated file without relay_busy or corruption → deterministic cross-file contention E2E.
When many agents write concurrently, Relay shall preserve exactly-once IDs/state transitions with bounded latency and no uncaught lock errors → bounded fan-in/fan-out stress test including duplicate send, stale receipt, lease expiry, and atomic reply.
When upgrading an empty, populated, interrupted, already-migrated, or actively-written legacy installation, every legacy Relay ID/state shall appear exactly once; upgrade shall require a stopped old service and fail closed on source mismatch, partial live pair, or post-marker incompleteness → migration lifecycle, competing-old-writer, and restart E2E.
When either database opens, it shall receive the same WAL, auto-vacuum, default busy-timeout, schema-lock, planner, reclaim, and integrity behavior → parameterized lifecycle tests for both roles.
When snapshots/restores/pruning/shutdown run, both databases shall be published and restored only as one complete validated generation; partial live/published pairs shall fail closed → failure-injection paired snapshot, manifest, restore, and supervisor tests.
When status/dashboard is read, it shall report both file sizes and Relay migration readiness without direct main-database Relay queries → API/dashboard E2E.
When existing callers use Relay or ingestion through HTTP/MCP/hooks, their observable contracts shall remain unchanged → existing focused Relay, MCP, hook, ingestion, Windows smoke, full CI, and live round trip.
**Plan review:**
Approved by clean-context persistence/architecture re-review; no blocking findings. See Plan review below.

**Approvals:**
Approved by user 2026-09-01: "so i'm leaving you with a night job: db performance improvement. do some investigation first to see that separating into a different db is the answer here. if so, let's do it. cover all operational things - we are handling the current db with some caution, wal etc. . both dbs should be handled the same way and not split code. also, for relay, make sure the dbn is optimized, we understand write stress pattern, we have indexes as needed, make sure write will not fail with multiple agents. be budget aware, work incrementally, use cheap agents when possible. don't do into infinite loops - if this doesn't consolidate don't waste money, be focused and if you see this doesn't come to an end, stop"

**Exceptions:**
—

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- Paired snapshot implementation and focused tests completed in the scoped files. `apply_patch` hit the documented Windows 1327 process limitation; a deterministic single-file replacement was used and reported.

- Discovery proved isolation removes the observed writer-lock failure. Redline and two clean-context plan reviews completed; the corrected High-risk plan is approved and ready for implementation. apply_patch later failed with the documented Windows 1327 issue, so Work Record updates used a verified deterministic single-file replacement.

## Evidence

- Implemented paired snapshot generations in `app/snapshot.py`: main and relay backups are independently validated, both names are published before a manifest commit marker, restore requires a newest complete validated pair, and pruning removes pair members as a unit. String-path callers remain the explicit legacy compatibility path.
- Added paired restore, incomplete-generation rejection, and unit-pruning tests in `tests/test_snapshot.py`. Existing focused suite passed 47 tests before the concurrent `app/main.py` worktree change introduced a syntax error; the new tests exposed and fixed duplicate stale definitions during implementation.
- Supervisor and periodic worker now select the sibling relay DB when present and route restore/create/prune through the same snapshot functions.

## Result review

- Pending.

## Plan review

Clean-context persistence/architecture review supported database isolation but blocked the first plan on four gaps: an old service could write after copy; the shared schema seam lacked role-specific plans; independent snapshots could mix generations; and in-memory/aliased/non-file URL behavior was undefined. The revised plan requires a quiesced old service and fail-closed split marker, explicit role schemas over one lifecycle primitive, manifest-published two-file snapshot generations, and strict URL/fallback validation. A fresh final re-review approved the corrected plan with no blocking findings. No production code had been edited at approval.