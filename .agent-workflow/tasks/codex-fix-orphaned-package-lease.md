<!-- agent-workflow:start -->
**Outcome:** Expired package-processing leases at the retry ceiling settle terminally instead of leaving ingestion permanently pending.

**Target:** Pallium ingestion queue.

**Scope:** Package-task lease reconciliation in `storage/sqlite_queue.py`, existing queue-health reason reporting, focused lifecycle and HTTP health tests, and repair of the one verified local orphan after deployment.

**Constraints:** No schema or public response-shape change; preserve retry ceilings, atomic claims, completed package results, and existing worker behavior for recoverable leases.

**Completion criteria:** When a package worker dies on its final attempt and its lease expires, a later processor pass shall mark that package terminal failed and settle its parent source when all packages are terminal. Before reconciliation, queue health shall classify the parent as unclaimable rather than reporting zero causes. The verified local orphan shall no longer remain pending after the fixed service runs.

**Risk:** Elevated

**Complexity:** Simple

**Reason:** Redline reports `storage/sqlite_queue.py` as gray plus the `storage/**` watch, with no boundary violation or checkpoint. The change is one coherent queue-lifecycle correction with focused tests.

**Discovery:** Live item `3704ed46-880d-4a3f-885f-d3f70dbcf529` has a pending parent, an expired `agent_conversation_memory` package lease at attempts=3, and another terminal package. Package claims exclude expired processing rows at the retry ceiling; legacy source claims exclude any package marked pending/processing. Queue health examines only parent fields, so it misses this orphan. Existing terminal synchronization and `unclaimable_pending_counts` contracts can be reused without schema/API changes.

**Material assumptions:** Reconciliation can run atomically at the start of package claiming using the existing SQLite immediate transaction and `_sync_source_item_if_all_packages_terminal`; disproved if that helper cannot safely run in the same transaction, in which case return to planning. `unclaimable_pending_counts` accepts a new reason value without schema changes; disproved by schema validation or contract tests, in which case stop rather than touch API schemas without reclassification.

**Plan:** First add a regression lifecycle test reproducing a processor crash after the final claim and confirm it fails. In `storage/sqlite_queue.py`, atomically convert expired `processing` package rows with attempts >= max into terminal `failed`, clear their leases, preserve/add an exhaustion error, and synchronize affected parents before selecting the next package task. Extend existing queue-health classification to report this package-state orphan through `unclaimable_pending_counts`. Add HTTP-observable coverage for the health reason and lifecycle recovery. Stop if schema/API files or a new persistence structure become necessary. Key conventions: reuse `_begin_immediate`, `_sync_source_item_if_all_packages_terminal`, and existing reason/count response shapes. Target files: `storage/sqlite_queue.py`, focused tests only.

**Verification plan:** Final-attempt expired package lease settles package and parent terminally without an extra provider attempt → focused package lifecycle regression test. Recoverable expired leases below the ceiling remain reclaimable → focused existing/new regression test. Queue health identifies the orphan before reconciliation through the existing HTTP response → `/debug/queue/health` test. Existing atomic/concurrent package claims remain correct → multi-package and concurrent-claim test slices. Live orphan leaves pending after service restart → local health endpoint plus read-only row verification.

**Plan review:** Pending clean-context review.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Blocked
<!-- Ready to implement | Blocked | Ready for review -->
<!-- agent-workflow:end -->

## Implementation

Discovery and Elevated pre-edit redline classification completed. No code edited. Awaiting the required clean-context plan review.

## Evidence

Pending.

## Plan review

Pending.

## Result review

Pending.
