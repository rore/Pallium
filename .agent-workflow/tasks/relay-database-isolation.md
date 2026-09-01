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

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Confirmed the root cause with disposable-file probes: SQLite WAL permits one writer per file; a competing main-DB writer delayed or exhausted Relay, while the same Relay operation on a separate file completed in 5–8 ms.
- Added an optional isolated Relay engine/session factory with a derived sibling file, one shared engine-hook lifecycle (WAL, incremental auto-vacuum, busy timeout), Relay-only schema initialization, bounded Relay transactions, and dual-engine reclaim/close behavior.
- Added stopped-service, source/target-marker migration with exact legacy-row verification and fail-closed reopening on target mismatch or missing migrated rows. Legacy rows remain rollback evidence.
- Added paired snapshot creation, manifest publication, restore, prune, supervisor compatibility, legacy single-snapshot upgrade handling, status/dashboard signals, docs, and exact default runtime-file ignores.
- Routed Relay API, MCP, dashboard, and E2E probes through the isolated store without changing their public contracts. Existing indexes were retained because query-plan evidence used the claim index; no speculative index was added.
- `apply_patch` failed with the documented Windows process-launch limitation, so edits used deterministic replacements limited to named files.

## Evidence

- Focused operational suite: 192 passed, 1 skipped (`test_sqlite_relay_isolation`, Relay HTTP/MCP/hooks, snapshots, health).
- Default CI lane with an empty machine-local config: 4,093 passed, 12 skipped, 2 expected failures in 122.74 s.
- Concurrent coverage includes eight-sender fan-in with unique deliveries, HTTP Relay writes while the main DB holds `BEGIN IMMEDIATE`, bounded competing legacy-writer rejection, exact populated migration including claimed state, idempotent reopen, and fail-closed missing-target-row detection.
- Lifecycle coverage verifies both files use WAL, `auto_vacuum=INCREMENTAL`, and busy timeouts; paired snapshots publish a manifest last, restore only complete pairs, prune by generation, and reject partial post-split live state.
- Workflow checker: clean. Binding redline report: `SCHEMA_CHANGE`, no boundary/API/security violations; persistence-review checkpoint remains for the PR.
- PR #90 first CI run exposed environment-dependent snapshot-worker configuration on Linux/Python 3.12 and 3.13. Both worker tests now pass explicit temporary main/Relay URLs; the focused correction passes 2/2 locally.
- The repository-root test-created split pair was repaired only after verifying all three legacy Relay tables contained zero rows. The actual installed service has not been migrated on this branch.

## Result review

A bounded clean-context result review reported two P1 concerns. The snapshot concern was rejected after tracing the precondition: paired restore runs only when both live files are absent, so a crash after the first rename leaves exactly one file and the next startup fails closed; it cannot leave two mixed live generations. Existing partial-live coverage asserts this contract.

The old-binary concern is a real operational boundary but not a supported concurrent mode. Migration holds the source writer lock and is supported only after the previous process tree is stopped; starting an old binary afterward would bypass semantics that old code cannot know. Database triggers were considered but not adopted because permanently mutating rollback-evidence tables would create a broader rollback/data-recovery hazard. Operations docs now explicitly prohibit restarting an old binary after split and require stopping and reconciling if it writes. No remaining code blocker was found within the supported upgrade contract.

## Remaining release steps

- Push the local branch and open a PR after remote-write approval.
- Satisfy the persistence-review checkpoint and resolve CI/review findings.
- After merge, update the stable local checkout, run `scripts/restart-service.ps1`, verify `/health`, `/status`, and `/debug/queue/health`, confirm the migration marker/file pair, then run a live concurrent Relay/ingestion smoke test and reinstall integrations only if their installed files changed.