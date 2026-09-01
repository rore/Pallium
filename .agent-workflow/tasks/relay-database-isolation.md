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
Observed production evidence: SQLite WAL is enabled, but the database still has one writer across all tables. Shared `_begin_immediate` uses 100 ms acquisition attempts and live logs show `/items` failing while processor commits hold the writer. Investigation is in progress to measure transaction shape, schema/index coverage, and operational coupling before selecting a design.

**Material assumptions:**
1. Relay has no required atomic invariant with memory/ingestion tables. Disproof: a cross-capability transaction or foreign key is found; action: stop the split and redesign.
2. A second SQLite file can reuse the same lifecycle implementation. Disproof: schema/backup/retention code is inseparable without duplication; action: stop and prefer transaction hardening.
3. Existing Relay rows can be migrated idempotently without loss. Disproof: migration cannot distinguish completion or safely resume; action: block implementation.

**Plan:**
1. Prove the contention mechanism, inventory cross-table dependencies, benchmark isolated versus shared files, inspect indexes and operational lifecycle.
2. Obtain clean-context persistence/redline and architecture review of the evidence-backed plan.
3. Only if supported, introduce the smallest shared database-lifecycle seam and route Relay to its own file with idempotent compatibility migration.
4. Add bounded concurrency, migration, restart, backup/maintenance, and API/MCP/hook E2E coverage; update operational docs and roadmap.
5. Review, run CI, merge only when findings are resolved, then restore local main and refresh integrations/service.

**Verification plan:**
Run deterministic shared-vs-isolated writer contention probes; schema/index query-plan checks; migration empty/populated/interrupted/idempotent tests; WAL/pragma/maintenance tests for both files; concurrent send/claim/reply/ACK/status plus ingestion stress; existing Relay and ingestion E2E; Windows smoke; agent-workflow/redline; clean-context result review; live local service health and Relay round trip.

**Plan review:**
Pending clean-context review after discovery.

**Approvals:**
Approved by user 2026-09-01: "so i'm leaving you with a night job: db performance improvement. do some investigation first to see that separating into a different db is the answer here. if so, let's do it. cover all operational things - we are handling the current db with some caution, wal etc. . both dbs should be handled the same way and not split code. also, for relay, make sure the dbn is optimized, we understand write stress pattern, we have indexes as needed, make sure write will not fail with multiple agents. be budget aware, work incrementally, use cheap agents when possible. don't do into infinite loops - if this doesn't consolidate don't waste money, be focused and if you see this doesn't come to an end, stop"

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- Discovery started; no production code has been edited. The stop gate is evidence that isolation is unnecessary or unsafe.

## Evidence

- Pending.

## Result review

- Pending.
