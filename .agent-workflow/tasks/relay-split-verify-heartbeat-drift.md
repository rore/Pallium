<!-- agent-workflow:start -->
**Outcome:** The Relay split-migration startup verify no longer aborts when a mutable heartbeat column (`last_seen_at`) has drifted between the main and relay databases during normal operation.

**Risk:** Routine

**Complexity:** Simple

**Reason:** Clean-context redline (2026-09-02): `storage/sqlite.py` is gray (unlisted) under the `storage/**` watch glob; no red zone, no checkpoint (persistence-review fires only on `sqlite_schema.py`/`sqlite_codec.py`). Change wraps one existing loop in `if require_exact:` — no new logic, no schema/API surface.

**Plan:** In `storage/sqlite.py::_verify_relay_ids`, gate the column-by-column equality loop (lines 211-217) behind `require_exact`. The one-time copy path (`require_exact=True`, called right after `_copy_relay_rows`) still verifies full column equality — columns must match because we just copied them. The resumed startup path (`require_exact=False`) verifies only id-subset parity (existing check at line 209); it must NOT compare mutable columns because `last_seen_at` is written only to the relay DB after the split, so it legitimately diverges from the frozen main-DB copy on every session touch. Add a regression test in `tests/test_sqlite_relay_isolation.py`: split, advance the relay session's `last_seen_at`, reopen the provider, assert startup succeeds.

**Verification plan:** New regression test passes. Existing split-migration tests (`test_populated_legacy_relay_rows_migrate_exactly_once`, `test_split_marker_detects_missing_target_row`, `test_split_rejects_competing_legacy_writer_within_bound`) stay green. Full `tests/test_sqlite_relay_isolation.py` green. Then restart the installed service and confirm it binds (this drift is what was aborting startup on the live box).

**State:** Ready for review
<!-- Ready to implement | Blocked | Ready for review -->
<!-- agent-workflow:end -->

## Implementation

- 2026-09-02: Root cause of live-service startup abort (`RuntimeError: Relay split migration found conflicting relay_sessions row ...`). `_verify_relay_ids` compared every column on both the copy and resumed paths. `last_seen_at` advances only in the relay DB post-split (all relay writes go through `_begin_relay_immediate`), so the main-DB copy freezes at its last pre-split value and diverges on every heartbeat. The every-startup re-verify treated that expected drift as corruption. Fix scopes the full-column diff to the copy path only.
- 2026-09-02: Implemented. `storage/sqlite.py::_verify_relay_ids` — column-equality loop now guarded by `if not require_exact: continue`. Regression test `test_split_resume_tolerates_heartbeat_drift` added to `tests/test_sqlite_relay_isolation.py` (split, bump relay `last_seen_at`, reopen, assert no raise). Tests: `tests/test_sqlite_relay_isolation.py` 10 passed. Service restarted via `scripts/restart-service.ps1`; `/health` 200, `/status` 200 (`relay_migration_ready: true`), `/debug/queue/health` 200 — startup no longer aborts.
