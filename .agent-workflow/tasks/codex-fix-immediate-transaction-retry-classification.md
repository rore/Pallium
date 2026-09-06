<!-- agent-workflow:start -->
**Outcome:** Rare `BEGIN IMMEDIATE` retry exhaustion is treated as transient by the ingestion worker, so it backs off and retries instead of terminating.

**Target:** Pallium shared transient-error classification and async worker caller surface.

**Scope:** `core/errors.py`, `tests/test_async_worker.py`, this Work Record, and a concise incident note in `roadmap/ideas/idea-operational-scale-hardening.md`.

**Constraints:** Preserve the bounded immediate-transaction retry/503 contract, existing SQLite message classification, worker maximum-consecutive-error behavior, and all non-SQLite error handling. No retry-budget increase, dependency, or wall-clock test.

**Completion criteria:** `ImmediateTransactionBusyError` is classified transient; the real worker loop retries that exact exception and completes the pending item; raw and SQLAlchemy SQLite classifications and non-transient rejection remain covered; focused/full relevant tests, workflow, redline, and PR CI pass.

**Risk:** Elevated

**Complexity:** Simple

**Reason:** Pre-edit redline classifies `core/errors.py` gray/watch and both test/roadmap paths blue, with no boundary or checkpoint. The shared classifier has broad callers, so caller-surface regression is required despite the one-line implementation.

**Discovery:** PR #110 Windows smoke intermittently failed `test_begin_immediate_under_wal` with `ImmediateTransactionBusyError`; the immediate rerun passed. `SQLiteQueueMixin` deliberately converts exhausted transient SQLite locks to this stable custom exception. `app.worker.run_worker` retries only errors accepted by `is_transient_error`, which currently accepts raw/SQLAlchemy `sqlite3.OperationalError` but rejects the custom wrapper, so production ingestion can exit on a retryable lock.

**Material assumptions:** The custom exception always represents exhausted acquisition of a transient SQLite write lock; disproved by any non-lock use site, which would require a narrower exception or classifier. Existing outer worker backoff is the intended recovery path; disproved by a caller that must fail immediately, which would return this task to planning.

**Plan:** Add one explicit `ImmediateTransactionBusyError` acceptance at the shared classifier. Reuse the existing real `run_worker` recovery test by making its first two failures the exact custom exception, while retaining existing raw/SQLAlchemy and terminal-error coverage. Record the observed CI incident and fix in the operational-hardening roadmap note. Do not change retry durations or storage transactions.

**Verification plan:** Classifier contract → focused predicate tests; worker recovery lifecycle → existing real worker test proves two exact custom failures, deterministic 1s/2s injected backoff, third-call success, completed processing state, and transient log; regression surface → `tests/test_async_worker.py`, `tests/test_snapshot.py::test_begin_immediate_under_wal`, `tests/test_sqlite_write_retry.py`, workflow/redline/diff checks, then PR CI.

**Plan review:** Clean-context Luna review under `## Plan review`; approved the root-cause location and existing worker caller-surface regression.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- Discovery, pre-edit redline classification, and Elevated clean-context plan review complete. Implementation is ready; no code edit has started.

## Evidence

- Failed Windows CI run 34016782311 job 101441823518: one `ImmediateTransactionBusyError('database is locked (immediate transaction retry exhausted)')`; retry passed in job 101442373283.
- Production trace: `storage/sqlite_queue.py::_begin_immediate_for` raises the custom exception; `app/worker.py::run_worker` delegates retryability to `core.errors.is_transient_error`; the classifier currently rejects the wrapper because it is a `RuntimeError`.

## Plan review

Pending.

## Result review

Pending.