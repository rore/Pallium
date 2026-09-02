<!-- agent-workflow:start -->
**Outcome:** The Relay split-migration startup verify no longer aborts when a mutable heartbeat column (`last_seen_at`) has drifted between the main and relay databases during normal operation.

**Target:** `storage/sqlite.py::_verify_relay_ids` — the row-parity check run during the Relay DB split migration on startup.

**Scope:** One guard in `_verify_relay_ids` plus one regression test in `tests/test_sqlite_relay_isolation.py`. No schema, API, or contract change.

**Constraints:** The one-time copy path must still verify full column equality (integrity of the copy). Only the resumed-startup path relaxes to id-subset parity. No change to migration ordering, locking, or marker logic.

**Completion criteria:** (1) Service startup no longer aborts when `last_seen_at` differs between the main and relay copies of a relay row. (2) The one-time copy path still raises on any real column mismatch. (3) A regression test reproduces the drift and asserts startup succeeds. (4) Existing split-migration tests stay green.

**Risk:** Elevated

**Complexity:** Simple

**Reason:** CI redline floors the `storage/**` gray zone at Elevated (conservative default for a persistence-layer file). No red zone, no checkpoint (persistence-review fires only on `sqlite_schema.py`/`sqlite_codec.py`). The change itself is one guard wrapping an existing loop — no new logic, no schema/API surface.

**Discovery:** `_verify_relay_ids` (storage/sqlite.py:203-217) is called twice from `_migrate_legacy_relay`: once with `require_exact=True` right after `_copy_relay_rows` (one-time copy), once with `require_exact=False` on every subsequent startup (marker present, resumed path). It always ran a full column-by-column equality check. `last_seen_at` is written only to the relay DB after the split (all relay writes go through `_begin_relay_immediate`, storage/sqlite_relay.py), so the relay-DB copy advances while the main-DB copy stays frozen at its last pre-split value. The resumed-path re-verify then treated that expected drift as corruption and aborted service startup. Confirmed on the live box: the conflicting row `relay-session-a2f0777f...` was byte-identical in both DBs except `last_seen_at`.

**Material assumptions:**
- The main-DB copy of relay rows is never read for serving after the split (relay reads/writes all route to the relay engine), so relaxing column equality on the resumed path loses no correctness. Disproof: a serving path reads relay rows from `self._engine`. Action: re-tighten and reconcile the main copy instead. (Verified: `sqlite_relay.py` routes all relay ops through `_begin_relay_immediate`/`_relay_session_factory`.)

**Plan:** In `_verify_relay_ids`, gate the column-by-column equality loop behind `require_exact`. The one-time copy path (`require_exact=True`) still verifies full column equality — columns must match because we just copied them. The resumed startup path (`require_exact=False`) verifies only id-subset parity (the existing set-subset check); it must NOT compare mutable columns because `last_seen_at` legitimately diverges. Add a regression test: split, advance the relay session's `last_seen_at`, reopen the provider, assert startup succeeds.

**Verification plan:** New regression test passes. Existing split-migration tests (`test_populated_legacy_relay_rows_migrate_exactly_once`, `test_split_marker_detects_missing_target_row`, `test_split_rejects_competing_legacy_writer_within_bound`) stay green. Full `tests/test_sqlite_relay_isolation.py` green. Then restart the installed service and confirm it binds.

**Plan review:** CI redline (2026-09-02) classified `storage/sqlite.py` gray under the `storage/**` watch glob, no boundary violation, no checkpoint triggered. Elevated is the gray-zone floor; this doubles as the single Elevated architecture review — the change adds no cross-layer dependency and touches no contract/security/persistence-DDL surface.

**Approvals:** Not required at this risk level (Elevated).

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- 2026-09-02: Root cause of live-service startup abort (`RuntimeError: Relay split migration found conflicting relay_sessions row ...`). `_verify_relay_ids` compared every column on both the copy and resumed paths. `last_seen_at` advances only in the relay DB post-split, so the main-DB copy freezes at its last pre-split value and diverges on every heartbeat. The every-startup re-verify treated that expected drift as corruption. Fix scopes the full-column diff to the copy path only.
- 2026-09-02: Implemented. `storage/sqlite.py::_verify_relay_ids` — column-equality loop now guarded by `if not require_exact: continue`. Regression test `test_split_resume_tolerates_heartbeat_drift` added to `tests/test_sqlite_relay_isolation.py` (split, bump relay `last_seen_at`, reopen, assert no raise). Tests: `tests/test_sqlite_relay_isolation.py` 10 passed. Service restarted via `scripts/restart-service.ps1`; `/health` 200, `/status` 200 (`relay_migration_ready: true`), `/debug/queue/health` 200 — startup no longer aborts.
