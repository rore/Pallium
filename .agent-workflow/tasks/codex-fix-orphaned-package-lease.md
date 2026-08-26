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

**Plan review:** Approved; see `## Plan review`.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready to implement
<!-- Ready to implement | Blocked | Ready for review -->
<!-- agent-workflow:end -->

## Implementation

Discovery, Elevated pre-edit redline classification, and the required clean-context plan review are complete. The plan is approved; no code has been edited.

## Evidence

Pending.

## Plan review

Approved by clean-context agent review on 2026-08-26. No blocking findings.

Implementation conditions:

- Reconcile only `processing` package rows whose lease is non-null and expired at the claim timestamp and whose attempts are at or above the supplied ceiling. Keep below-ceiling expired rows reclaimable and active leases untouched.
- Perform reconciliation, distinct-parent synchronization, and the subsequent global package selection inside the same existing `_begin_immediate` transaction. The processor always enters through `claim_next_package_task` before the item-scoped loop, so duplicating reconciliation in `claim_next_package_task_for_item` is unnecessary unless implementation discovery finds another production caller.
- Clear claim/lease/backoff fields, set a completion timestamp, and preserve an existing package error or supply a stable exhaustion error. Repeated processor passes must be idempotent and must not consume another provider attempt.
- Queue health must count each affected pending parent once from package state and use the existing open-string reason/count response shape; no schema or public shape change is needed.
- Focused coverage must include the exact ceiling boundary, below-ceiling reclaim, active versus expired lease, mixed terminal packages with parent settlement, idempotent repeated passes, and concurrent global claims. Deployment repair must use `scripts/restart-service.ps1`, then verify `/health`, `/status`, `/debug/queue/health`, and the orphan row through a read-only query.

## Result review
Pending.
