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

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Discovery, Elevated pre-edit redline classification, and the required clean-context plan review are complete. The plan is approved; no code has been edited.

Implementation: added the failing final-attempt lease regression first, then added atomic package-claim reconciliation and existing-contract health classification in storage/sqlite_queue.py. Focused lifecycle tests cover the ceiling, below-ceiling reclaim, active leases, idempotence, mixed-package parent settlement, and HTTP health before/after recovery. apply_patch failed with Windows error 1385, so edits used the permitted deterministic named-file fallback.

## Evidence

Revision bfd6d15: the four focused regressions first reproduced two expected failures, then passed after the fix. After CodeRabbit identified the item-scoped claim edge, the same reconciliation was added inside `claim_next_package_task_for_item`'s existing transaction with a regression asserting settlement through the service read path. The multi-package processing, concurrent claim, and observability slices pass 42 tests with three pre-existing Pydantic warnings; diff hygiene and the agent-workflow checker pass. After restart through `scripts/restart-service.ps1`, independent live verification found `/health` ok with vector and embedding ready, `/status.ingestion.status` ok, no unclaimable queue reasons, and source `3704ed46-880d-4a3f-885f-d3f70dbcf529` terminal failed with claims cleared, completion timestamp set, and the historic 404 error preserved.

## Plan review

Approved by clean-context agent review on 2026-08-26. No blocking findings.

Implementation conditions:

- Reconcile only `processing` package rows whose lease is non-null and expired at the claim timestamp and whose attempts are at or above the supplied ceiling. Keep below-ceiling expired rows reclaimable and active leases untouched.
- Perform reconciliation, distinct-parent synchronization, and the subsequent global package selection inside the same existing `_begin_immediate` transaction. The processor always enters through `claim_next_package_task` before the item-scoped loop, so duplicating reconciliation in `claim_next_package_task_for_item` is unnecessary unless implementation discovery finds another production caller.
- Clear claim/lease/backoff fields, set a completion timestamp, and preserve an existing package error or supply a stable exhaustion error. Repeated processor passes must be idempotent and must not consume another provider attempt.
- Queue health must count each affected pending parent once from package state and use the existing open-string reason/count response shape; no schema or public shape change is needed.
- Focused coverage must include the exact ceiling boundary, below-ceiling reclaim, active versus expired lease, mixed terminal packages with parent settlement, idempotent repeated passes, and concurrent global claims. Deployment repair must use `scripts/restart-service.ps1`, then verify `/health`, `/status`, `/debug/queue/health`, and the orphan row through a read-only query.

## Result review

**Verdict: Approved.** CodeRabbit correctly identified that an exhausted lease can arise between the global claim and the later item-scoped claim, invalidating the plan-review assumption that global entry alone was sufficient. The resolution reuses the same helper inside the item-scoped method's existing immediate transaction; it adds no abstraction or contract change. The new service-read-path regression and the full 42-test focused lifecycle, observability, and concurrency suite pass, as do diff hygiene and the workflow checker. Live repair evidence remains valid. No unresolved assumptions, scope expansion, roadmap/docs drift, or risk reclassification.

## Skill feedback (unsent)

**Trigger fired:** 3 — a skill instruction produced an invalid artifact.

**What the skill said (or failed to say):** The expanded Work Record template places a state-values guidance comment immediately after the State value. File: templates/work-record-expanded.md, State field.

**What happened:** A record copied from that template failed workrecord.state_valid; the parser included the following HTML comment in the State value. Removing the comment made the checker pass.

**Suggested fix:** Move the guidance comment outside the marker block or make State parsing stop at HTML comments/end marker, with a checker test using the generated template unchanged.

**Work Record:** consumer commit 614390c, .agent-workflow/tasks/codex-fix-orphaned-package-lease.md. External issue creation was not authorized by the execution environment.
