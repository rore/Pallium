# Idempotent SQLite startup pragmas

<!-- agent-workflow:start -->
**Outcome:** Concurrent fresh startup of separate main and Relay SQLite databases completes without a transient `database is locked` failure.

**Target:** Pallium SQLite storage startup.

**Scope:** `storage/sqlite.py` and `tests/test_sqlite_relay_isolation.py` only.

**Constraints:** Preserve `auto_vacuum=INCREMENTAL`, `journal_mode=WAL`, the existing 15-second SQLite busy-wait budget per operation, schema/pair locks, database schemas, and public APIs. Do not add application-level retries, dependencies, install/restart, or merge.

**Completion criteria:** When two processes initialize the same fresh separate database pair, both complete successfully and both database files retain incremental auto-vacuum and WAL mode; the existing concurrency E2E passes repeatedly.

**Risk:** Elevated

**Complexity:** Simple

**Reason:** Pre-edit redline reports no red zone, boundary violation, or checkpoint, but `storage/sqlite.py` is a watched persistence runtime path. Engineering judgment raises risk because the change affects concurrent database bootstrap behavior; no schema or stored-data contract changes.

**Discovery:** The same Python 3.13 Linux CI node failed on main run 34386599635 and PR #162: startup overrides the connection's configured 15-second busy handler with `busy_timeout=0`, then immediately executes write-capable persistent PRAGMAs. A disposable reproduction held a brief exclusive lock on an initialized main database and produced the exact immediate failure at `PRAGMA auto_vacuum=INCREMENTAL`. SQLite documents that WAL cleanup and other brief lock transitions can return `SQLITE_BUSY`, so merely querying current PRAGMA values with a zero timeout would move rather than remove the race. No existing branch or PR fixes this.

**Material assumptions:** The connection hook's existing `busy_timeout=15000` remains active during bootstrap when the local zero-timeout override is removed; disprove by inspecting the pragma on the bootstrap connection, in which case stop. Waiting through a brief competing lock is preferable to an immediate startup failure and remains bounded by 15 seconds; disprove with a deterministic transient-lock E2E, in which case stop. Persistent modes remain incremental auto-vacuum and WAL after concurrent startup; disprove with direct SQLite assertions, in which case revert and reassess.

**Plan:** In `_initialize_sqlite_pragmas`, delete only the code that saves, forces, and restores `busy_timeout`; retain the existing locks, AUTOCOMMIT connection, and persistent PRAGMA writes so SQLite's configured 15-second busy handler covers transient startup contention. Add one deterministic E2E that holds an exclusive SQLite lock briefly while constructing a provider, then asserts startup succeeds and both database files retain incremental auto-vacuum and WAL. Extend the existing concurrent fresh-pair E2E with the same direct mode assertions. Run the exact E2Es repeatedly, the affected test file, the full suite once, workflow/redline gates, and smart result review. Stop on any mode regression, unbounded wait, or new lock failure.

**Verification plan:** While another connection holds then releases a brief exclusive lock, provider construction shall wait and succeed -> new deterministic transient-lock E2E. When two spawned providers initialize one fresh separate pair, both shall return `ok` and exit zero -> repeat `test_concurrent_fresh_separate_pair_startup_is_serialized` sequentially. Both files shall retain incremental auto-vacuum and WAL mode -> direct assertions after each concurrency path. Existing repository behavior shall remain intact -> affected file and full suite once.

**Plan review:** First clean-context smart review rejected the conditional-read approach because reads can also return `SQLITE_BUSY` during WAL cleanup and the existing E2E did not force the race. Revised deletion-first plan approved by a fresh GPT-6 Astra high-reasoning review with no blocking findings. Reviewer confirmed that removing the override fixes the shared initializer while preserving PRAGMA order, locks, and SQLite's bounded native contention handling; requested deterministic synchronization and cleanup in the regression.

**Approvals:** Not required at this risk level.

**Exceptions:** -

<!-- Ready to implement | Blocked | Ready for review -->
**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- Confirmed repeated CI failure and completed pre-edit redline classification. A disposable exclusive-lock reproduction failed immediately at the same PRAGMA, validating the first reviewer's concern; the conditional-read plan was rejected and replaced with the smaller native busy-handler fix. No production or test code changes yet.

## Evidence

- Main CI run 34386599635 and PR #162 both failed at `PRAGMA auto_vacuum=INCREMENTAL` in the same Python 3.13 concurrency E2E.
- SQLite PRAGMA documentation: https://www.sqlite.org/pragma.html#pragma_auto_vacuum and https://www.sqlite.org/pragma.html#pragma_journal_mode
- SQLite WAL concurrency documentation: https://www.sqlite.org/wal.html#sometimes_queries_return_sqlite_busy_in_wal_mode

## Result review

- Pending.