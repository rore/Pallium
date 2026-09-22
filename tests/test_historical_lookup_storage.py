"""Historical-lookup reuse funnel — storage + loader (PR-a).

Covers the write-only event table, the append-only label table, their indexes,
the two writer round-trips, and the ``load_events_from_storage`` loader
(eligible-session reconstruction against the pinned predicate, consensus rung
join, and empty-safety). No LLM / app wiring — pure storage + loader.
"""
from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import pytest

from sqlalchemy import text

from core.errors import HistoryDiagnosticConflictError, HistoryDiagnosticCorruptError
from core.models import new_id, utc_now
from evals.historical_lookup_measurement import (
    compute_reuse_rollup,
    count_unattributed_lookups,
    load_events_from_storage,
)
from storage.sqlite import SQLiteStorageProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _storage(tmp_path) -> tuple[SQLiteStorageProvider, str]:
    db_file = tmp_path / "hist.db"
    storage = SQLiteStorageProvider(f"sqlite:///{db_file}")
    return storage, str(db_file)


def _insert_source_item(
    storage: SQLiteStorageProvider,
    *,
    source_id: str,
    role: str | None,
    artifact_kind: str | None,
    container_ref: str,
    thread_ref: str | None,
    created_at: str,
    completed: bool = True,
    forgotten: bool = False,
) -> None:
    with storage._engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO source_items "
                "(id, source_type, source_id, content_type, content, role, "
                " artifact_kind, container_ref, thread_ref, visibility, "
                " processing_status, processing_attempts, processing_completed_at, "
                " forgotten_at, created_at) "
                "VALUES (:id, 'chat_message', :source_id, 'text/plain', 'x', :role, "
                " :artifact_kind, :container_ref, :thread_ref, 'private', "
                " 'completed', 0, :completed, :forgotten, :created_at)"
            ),
            {
                "id": new_id(),
                "source_id": source_id,
                "role": role,
                "artifact_kind": artifact_kind,
                "container_ref": container_ref,
                "thread_ref": thread_ref,
                "completed": created_at if completed else None,
                "forgotten": created_at if forgotten else None,
                "created_at": created_at,
            },
        )


def _seed_substantive_session(
    storage: SQLiteStorageProvider, *, container_ref: str, thread_ref: str, base: str
) -> None:
    """One user turn + one assistant-work turn = a substantive session."""
    _insert_source_item(
        storage, source_id=f"{thread_ref}-u", role="user", artifact_kind="message",
        container_ref=container_ref, thread_ref=thread_ref, created_at=f"{base} 00:00:01.000000",
    )
    _insert_source_item(
        storage, source_id=f"{thread_ref}-a", role="assistant", artifact_kind="assistant_output",
        container_ref=container_ref, thread_ref=thread_ref, created_at=f"{base} 00:00:02.000000",
    )


def _write_lookup(
    storage, *, container_ref, session_id, event_id=None,
    request_source_item_id: str | None = None,
) -> str:
    event_id = event_id or new_id()
    storage.write_historical_lookup_event_row({
        "id": event_id,
        "created_at": utc_now(),
        "event_type": "lookup",
        "session_id": session_id,
        "container_ref": container_ref,
        "actor_ref": None,
        "trigger_origin": "agent_pull",
        "parent_lookup_id": None,
        "exposed_json": json.dumps([{"source_item_id": "s1", "raw_rank": 1, "score": 0.5}]),
        "visibility": "private",
        "request_source_item_id": request_source_item_id,
    })
    return event_id


def _write_label(storage, *, lookup_event_id, rung, rater_seed="seed-0") -> None:
    storage.write_historical_lookup_label_row({
        "id": new_id(),
        "lookup_event_id": lookup_event_id,
        "rater_seed": rater_seed,
        "rung": rung,
        "rationale": "test",
        "created_at": utc_now(),
    })


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class TestSchema:
    def test_both_tables_created(self, tmp_path) -> None:
        storage, _ = _storage(tmp_path)
        with storage._engine.connect() as conn:
            names = {
                r[0] for r in conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                )
            }
        assert "historical_lookup_reuse_event" in names
        assert "historical_lookup_reuse_label" in names

    def test_indexes_created(self, tmp_path) -> None:
        storage, _ = _storage(tmp_path)
        with storage._engine.connect() as conn:
            indexes = {
                r[0] for r in conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='index'")
                )
            }
        assert "idx_historical_lookup_event_container_session" in indexes
        assert "idx_historical_lookup_label_event" in indexes


    def test_existing_event_table_gets_nullable_request_link_column(self, tmp_path) -> None:
        db_file = tmp_path / "legacy-hist.db"
        with sqlite3.connect(db_file) as conn:
            conn.execute(
                """
                CREATE TABLE historical_lookup_reuse_event (
                    id VARCHAR PRIMARY KEY,
                    created_at DATETIME NOT NULL,
                    event_type VARCHAR NOT NULL,
                    session_id VARCHAR,
                    container_ref VARCHAR,
                    actor_ref VARCHAR,
                    trigger_origin VARCHAR,
                    parent_lookup_id VARCHAR,
                    exposed_json TEXT NOT NULL DEFAULT '[]',
                    visibility VARCHAR,
                    source_session_ref VARCHAR,
                    query_text TEXT
                )
                """
            )

        storage = SQLiteStorageProvider(f"sqlite:///{db_file}")
        with storage._engine.connect() as conn:
            columns = {
                row[1]
                for row in conn.execute(
                    text("PRAGMA table_info(historical_lookup_reuse_event)")
                )
            }
        assert "request_source_item_id" in columns

        event_id = _write_lookup(
            storage,
            container_ref="c:legacy",
            session_id="t:legacy",
            request_source_item_id="请求:legacy",
        )
        with storage._engine.connect() as conn:
            value = conn.execute(
                text(
                    "SELECT request_source_item_id "
                    "FROM historical_lookup_reuse_event WHERE id = :id"
                ),
                {"id": event_id},
            ).scalar_one()
        assert value == "请求:legacy"


# ---------------------------------------------------------------------------
# Writer round-trips
# ---------------------------------------------------------------------------


class TestWriters:
    def test_event_row_round_trip(self, tmp_path) -> None:
        storage, _ = _storage(tmp_path)
        event_id = _write_lookup(
            storage, container_ref="c:1", session_id="t:1",
            request_source_item_id="request-1",
        )
        with storage._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT event_type, session_id, container_ref, trigger_origin, "
                    "parent_lookup_id, exposed_json, request_source_item_id FROM historical_lookup_reuse_event "
                    "WHERE id = :id"
                ),
                {"id": event_id},
            ).one()
        assert row[0] == "lookup"
        assert row[1] == "t:1"
        assert row[2] == "c:1"
        assert row[3] == "agent_pull"
        assert row[4] is None
        assert json.loads(row[5])[0]["source_item_id"] == "s1"
        assert row[6] == "request-1"

    def test_expansion_row_carries_parent(self, tmp_path) -> None:
        storage, _ = _storage(tmp_path)
        parent = _write_lookup(storage, container_ref="c:1", session_id="t:1")
        exp_id = new_id()
        storage.write_historical_lookup_event_row({
            "id": exp_id,
            "created_at": utc_now(),
            "event_type": "expansion",
            "session_id": "t:1",
            "container_ref": "c:1",
            "actor_ref": None,
            "trigger_origin": None,
            "parent_lookup_id": parent,
            "exposed_json": json.dumps([{"source_item_id": "n1", "raw_rank": None, "score": None}]),
            "visibility": "private",
        })
        with storage._engine.connect() as conn:
            row = conn.execute(
                text("SELECT event_type, parent_lookup_id FROM historical_lookup_reuse_event WHERE id = :id"),
                {"id": exp_id},
            ).one()
        assert row[0] == "expansion"
        assert row[1] == parent

    def test_label_row_round_trip_append_only(self, tmp_path) -> None:
        storage, _ = _storage(tmp_path)
        event_id = _write_lookup(storage, container_ref="c:1", session_id="t:1")
        # Two raters label the SAME event → two rows (append-only, kappa-ready).
        _write_label(storage, lookup_event_id=event_id, rung="incorporation", rater_seed="seed-0")
        _write_label(storage, lookup_event_id=event_id, rung="influence", rater_seed="seed-1")
        with storage._engine.connect() as conn:
            count = conn.execute(
                text("SELECT COUNT(*) FROM historical_lookup_reuse_label WHERE lookup_event_id = :id"),
                {"id": event_id},
            ).scalar()
        assert count == 2


# ---------------------------------------------------------------------------
# Loader — eligible reconstruction (pinned predicate) + consensus rung
# ---------------------------------------------------------------------------


class TestLoader:
    def test_substantive_session_eligible_and_event_loaded(self, tmp_path) -> None:
        storage, db_file = _storage(tmp_path)
        _seed_substantive_session(storage, container_ref="c:1", thread_ref="t:1", base="2026-08-01")
        event_id = _write_lookup(storage, container_ref="c:1", session_id="t:1")
        _write_label(storage, lookup_event_id=event_id, rung="incorporation")

        eligible, events = load_events_from_storage(
            db_file, container_ref="c:1", eligibility_n=0
        )
        assert "t:1" in eligible
        assert len(events) == 1
        assert events[0]["session_id"] == "t:1"
        assert events[0]["rung"] == "incorporation"

        rollup = compute_reuse_rollup(eligible, events, eligibility_n=0, window={})
        assert rollup["rungs"]["incorporation"]["numerator"] == 1

    def test_non_substantive_session_not_eligible(self, tmp_path) -> None:
        storage, db_file = _storage(tmp_path)
        # Only a user turn — no assistant-work turn → not substantive.
        _insert_source_item(
            storage, source_id="u-only", role="user", artifact_kind="message",
            container_ref="c:1", thread_ref="t:only-user", created_at="2026-08-01 00:00:01.000000",
        )
        eligible, _ = load_events_from_storage(db_file, container_ref="c:1", eligibility_n=0)
        assert "t:only-user" not in eligible

    def test_null_role_does_not_classify(self, tmp_path) -> None:
        storage, db_file = _storage(tmp_path)
        # NULL role rows must not count as user or assistant-work.
        _insert_source_item(
            storage, source_id="n1", role=None, artifact_kind=None,
            container_ref="c:1", thread_ref="t:null", created_at="2026-08-01 00:00:01.000000",
        )
        _insert_source_item(
            storage, source_id="n2", role=None, artifact_kind="assistant_output",
            container_ref="c:1", thread_ref="t:null", created_at="2026-08-01 00:00:02.000000",
        )
        eligible, _ = load_events_from_storage(db_file, container_ref="c:1", eligibility_n=0)
        assert "t:null" not in eligible

    def test_eligibility_n_threshold_enforced(self, tmp_path) -> None:
        storage, db_file = _storage(tmp_path)
        # Substantive session starting at 00:00:10 with only 1 prior-indexed turn
        # before it → not eligible under eligibility_n=5.
        _insert_source_item(
            storage, source_id="prior", role="user", artifact_kind="message",
            container_ref="c:1", thread_ref="t:prior", created_at="2026-08-01 00:00:01.000000",
        )
        _seed_substantive_session(storage, container_ref="c:1", thread_ref="t:late", base="2026-08-02")
        eligible, _ = load_events_from_storage(db_file, container_ref="c:1", eligibility_n=5)
        assert "t:late" not in eligible

    def test_forgotten_turns_excluded_from_eligibility(self, tmp_path) -> None:
        storage, db_file = _storage(tmp_path)
        # Assistant-work turn is forgotten → session loses its work turn.
        _insert_source_item(
            storage, source_id="u", role="user", artifact_kind="message",
            container_ref="c:1", thread_ref="t:forg", created_at="2026-08-01 00:00:01.000000",
        )
        _insert_source_item(
            storage, source_id="a", role="assistant", artifact_kind="assistant_output",
            container_ref="c:1", thread_ref="t:forg", created_at="2026-08-01 00:00:02.000000",
            forgotten=True,
        )
        eligible, _ = load_events_from_storage(db_file, container_ref="c:1", eligibility_n=0)
        assert "t:forg" not in eligible

    def test_consensus_rung_majority(self, tmp_path) -> None:
        storage, db_file = _storage(tmp_path)
        _seed_substantive_session(storage, container_ref="c:1", thread_ref="t:1", base="2026-08-01")
        event_id = _write_lookup(storage, container_ref="c:1", session_id="t:1")
        _write_label(storage, lookup_event_id=event_id, rung="influence", rater_seed="s0")
        _write_label(storage, lookup_event_id=event_id, rung="influence", rater_seed="s1")
        _write_label(storage, lookup_event_id=event_id, rung="incorporation", rater_seed="s2")
        _, events = load_events_from_storage(db_file, container_ref="c:1", eligibility_n=0)
        assert events[0]["rung"] == "influence"

    def test_consensus_rung_tie_drops_to_conservative(self, tmp_path) -> None:
        storage, db_file = _storage(tmp_path)
        _seed_substantive_session(storage, container_ref="c:1", thread_ref="t:1", base="2026-08-01")
        event_id = _write_lookup(storage, container_ref="c:1", session_id="t:1")
        # 1 influence vs 1 downstream → tie → most conservative (influence).
        _write_label(storage, lookup_event_id=event_id, rung="downstream", rater_seed="s0")
        _write_label(storage, lookup_event_id=event_id, rung="influence", rater_seed="s1")
        _, events = load_events_from_storage(db_file, container_ref="c:1", eligibility_n=0)
        assert events[0]["rung"] == "influence"

    def test_event_without_labels_has_null_rung(self, tmp_path) -> None:
        storage, db_file = _storage(tmp_path)
        _seed_substantive_session(storage, container_ref="c:1", thread_ref="t:1", base="2026-08-01")
        _write_lookup(storage, container_ref="c:1", session_id="t:1")
        _, events = load_events_from_storage(db_file, container_ref="c:1", eligibility_n=0)
        assert events[0]["rung"] is None
        rollup = compute_reuse_rollup(["t:1"], events, eligibility_n=0, window={})
        # Null-rung events are skipped by the rollup.
        assert rollup["rungs"]["incorporation"]["numerator"] == 0

    def test_event_for_ineligible_session_dropped(self, tmp_path) -> None:
        storage, db_file = _storage(tmp_path)
        # A lookup event whose session was never substantive → not loaded.
        _write_lookup(storage, container_ref="c:1", session_id="t:ghost")
        _eligible, events = load_events_from_storage(db_file, container_ref="c:1", eligibility_n=0)
        assert events == []


# ---------------------------------------------------------------------------
# Loader — empty safety
# ---------------------------------------------------------------------------


class TestLoaderEmptySafe:
    def test_none_db_returns_empty(self) -> None:
        assert load_events_from_storage(None) == ([], [])

    def test_missing_file_returns_empty(self, tmp_path) -> None:
        assert load_events_from_storage(tmp_path / "nope.db", container_ref="c:1") == ([], [])

    def test_fresh_schema_no_rows_returns_empty(self, tmp_path) -> None:
        _, db_file = _storage(tmp_path)
        eligible, events = load_events_from_storage(db_file, container_ref="c:1", eligibility_n=0)
        assert eligible == []
        assert events == []


# ---------------------------------------------------------------------------
# Attribution: migration + unattributed data-quality count
# ---------------------------------------------------------------------------


def test_source_session_ref_migration_on_pre_column_db(tmp_path) -> None:
    """A DB whose event table predates source_session_ref gets the column added
    by schema init — proving the orchestrator actually calls the column-ensure
    (create_all alone never alters an existing table)."""
    import sqlite3
    db_file = tmp_path / "old.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute(
        "CREATE TABLE historical_lookup_reuse_event ("
        " id VARCHAR PRIMARY KEY, created_at DATETIME NOT NULL, event_type VARCHAR NOT NULL,"
        " session_id VARCHAR, container_ref VARCHAR, actor_ref VARCHAR, trigger_origin VARCHAR,"
        " parent_lookup_id VARCHAR, exposed_json TEXT NOT NULL DEFAULT '[]', visibility VARCHAR)"
    )
    conn.commit()
    cols_before = {r[1] for r in conn.execute("PRAGMA table_info(historical_lookup_reuse_event)")}
    conn.close()
    assert "source_session_ref" not in cols_before

    # Instantiating the provider runs _initialize_schema → the column-ensure.
    SQLiteStorageProvider(f"sqlite:///{db_file}")

    conn = sqlite3.connect(str(db_file))
    cols_after = {r[1] for r in conn.execute("PRAGMA table_info(historical_lookup_reuse_event)")}
    conn.close()
    assert "source_session_ref" in cols_after
    assert "query_text" in cols_after  # both attribution/eval columns migrated in


def test_unattributed_lookups_counted_and_excluded_from_kpi(tmp_path) -> None:
    """A lookup with no requesting session (session_id NULL) is excluded from the
    reuse KPI but surfaced in the data-quality count — no silent NULL."""
    storage, db_file = _storage(tmp_path)
    _seed_substantive_session(storage, container_ref="c:1", thread_ref="t:1", base="2026-08-18")
    _write_lookup(storage, container_ref="c:1", session_id="t:1")
    _write_lookup(storage, container_ref="c:1", session_id=None)

    assert count_unattributed_lookups(db_file, container_ref="c:1") == 1

    eligible, events = load_events_from_storage(db_file, container_ref="c:1", eligibility_n=0)
    assert "t:1" in eligible
    assert all(e["session_id"] is not None for e in events)  # NULL-session lookup not in KPI events

    rollup = compute_reuse_rollup(
        eligible, events, eligibility_n=0, window={}, unattributed_lookups=1
    )
    assert rollup["data_quality"]["unattributed_lookup_events"] == 1

# ---------------------------------------------------------------------------
# Session-history diagnostic store (red contract)
# ---------------------------------------------------------------------------


def _diagnostic_row(*, diagnostic_id="diag-1", key="retry-1", fingerprint="fp-1", snapshot=None):
    return {
        "id": diagnostic_id,
        "created_at": datetime(2026, 9, 22, 10, tzinfo=timezone.utc),
        "container_ref": "container:canonical",
        "active_session_ref": "session:active",
        "visibility": "private",
        "idempotency_key": key,
        "request_fingerprint": fingerprint,
        "saved_filters_json": json.dumps({"actor_ref": "actor:1", "thread_ref": "thread:1"}, sort_keys=True),
        "schema_version": 1,
        "snapshot_json": json.dumps(snapshot if snapshot is not None else {"status": "ok", "results": []}, sort_keys=True),
    }


class TestHistoryDiagnosticStore:
    def test_dedicated_table_and_scoped_unique_key_are_created(self, tmp_path) -> None:
        storage, _ = _storage(tmp_path)
        with storage._engine.connect() as conn:
            assert conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='history_diagnostic'")
            ).scalar_one() == "history_diagnostic"
            columns = {row[1] for row in conn.execute(text("PRAGMA table_info(history_diagnostic)"))}
            assert {
                "id", "created_at", "container_ref", "active_session_ref", "visibility",
                "idempotency_key", "request_fingerprint", "saved_filters_json",
                "schema_version", "snapshot_json",
            } <= columns
            indexes = {row[1] for row in conn.execute(text("PRAGMA index_list(history_diagnostic)"))}
            assert any("idempot" in index for index in indexes)

    def test_legacy_initialization_is_idempotent_and_preserves_existing_rows(self, tmp_path) -> None:
        db_file = tmp_path / "legacy-diagnostic.db"
        with sqlite3.connect(db_file) as conn:
            conn.execute("CREATE TABLE marker (id TEXT PRIMARY KEY, value TEXT NOT NULL)")
            conn.execute("INSERT INTO marker VALUES ('m1', 'keep')")
        first = SQLiteStorageProvider(f"sqlite:///{db_file}")
        second = SQLiteStorageProvider(f"sqlite:///{db_file}")
        with second._engine.connect() as conn:
            assert conn.execute(text("SELECT value FROM marker WHERE id='m1'")).scalar_one() == "keep"
            assert conn.execute(text("SELECT COUNT(*) FROM history_diagnostic")).scalar_one() == 0

    def test_create_round_trip_keeps_requester_filters_version_and_private_snapshot(self, tmp_path) -> None:
        storage, _ = _storage(tmp_path)
        row = _diagnostic_row(snapshot={"stages": [{"channel": "lexical", "rank": 1}]})
        stored = storage.create_history_diagnostic(row)
        assert stored["id"] == row["id"]
        loaded = storage.get_history_diagnostic(
            row["id"], container_ref=row["container_ref"],
            active_session_ref=row["active_session_ref"], visibility=row["visibility"],
        )
        assert loaded["idempotency_key"] == "retry-1"
        assert loaded["request_fingerprint"] == "fp-1"
        assert json.loads(loaded["saved_filters_json"])["actor_ref"] == "actor:1"
        assert loaded["schema_version"] == 1
        assert json.loads(loaded["snapshot_json"])["stages"][0]["channel"] == "lexical"

    def test_identical_retry_returns_same_row_but_changed_fingerprint_conflicts(self, tmp_path) -> None:
        storage, _ = _storage(tmp_path)
        row = _diagnostic_row()
        assert storage.create_history_diagnostic(row)["id"] == "diag-1"
        assert storage.create_history_diagnostic(row)["id"] == "diag-1"
        with pytest.raises(HistoryDiagnosticConflictError):
            storage.create_history_diagnostic({**row, "id": "diag-2", "request_fingerprint": "fp-other"})

    def test_idempotency_is_scoped_to_requester_tuple(self, tmp_path) -> None:
        storage, _ = _storage(tmp_path)
        row = _diagnostic_row()
        storage.create_history_diagnostic(row)
        other = {**row, "id": "diag-2", "container_ref": "container:other"}
        assert storage.create_history_diagnostic(other)["id"] == "diag-2"

    def test_retrieval_requires_exact_requester_tuple(self, tmp_path) -> None:
        storage, _ = _storage(tmp_path)
        row = _diagnostic_row()
        storage.create_history_diagnostic(row)
        assert storage.get_history_diagnostic(
            row["id"], container_ref="container:other",
            active_session_ref=row["active_session_ref"], visibility=row["visibility"],
        ) is None

    @pytest.mark.parametrize(
        "mutation",
        [
            lambda conn, row: conn.execute(
                text("UPDATE history_diagnostic SET snapshot_json=:snapshot WHERE id=:id"),
                {"id": row["id"], "snapshot": "{"},
            ),
            lambda conn, row: conn.execute(
                text("UPDATE history_diagnostic SET snapshot_json=:snapshot WHERE id=:id"),
                {"id": row["id"], "snapshot": json.dumps({"payload": "x" * 70000})},
            ),
            lambda conn, row: conn.execute(
                text("UPDATE history_diagnostic SET schema_version=99 WHERE id=:id"),
                {"id": row["id"]},
            ),
        ],
        ids=["malformed-json", "oversized-json", "unknown-version"],
    )
    def test_retrieval_rejects_corrupt_snapshots(self, tmp_path, mutation) -> None:
        storage, _ = _storage(tmp_path)
        row = _diagnostic_row()
        storage.create_history_diagnostic(row)
        with storage._engine.begin() as conn:
            mutation(conn, row)
        with pytest.raises(HistoryDiagnosticCorruptError):
            storage.get_history_diagnostic(
                row["id"], container_ref=row["container_ref"],
                active_session_ref=row["active_session_ref"], visibility=row["visibility"],
            )

    def test_failed_or_oversized_create_does_not_leave_a_row(self, tmp_path) -> None:
        storage, _ = _storage(tmp_path)
        row = _diagnostic_row(snapshot={"payload": "x" * 70000})
        with pytest.raises(HistoryDiagnosticCorruptError):
            storage.create_history_diagnostic(row)
        with storage._engine.connect() as conn:
            assert conn.execute(text("SELECT COUNT(*) FROM history_diagnostic")).scalar_one() == 0

    def test_concurrent_identical_creates_converge(self, tmp_path) -> None:
        storage, _ = _storage(tmp_path)
        row = _diagnostic_row()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(storage.create_history_diagnostic, (row, row)))
        assert [result["id"] for result in results] == ["diag-1", "diag-1"]

    def test_concurrent_conflicting_creates_have_one_success(self, tmp_path) -> None:
        storage, _ = _storage(tmp_path)
        row = _diagnostic_row()
        conflicting = {**row, "id": "diag-2", "request_fingerprint": "fp-other"}
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(storage.create_history_diagnostic, candidate) for candidate in (row, conflicting)]
            outcomes = []
            for future in futures:
                try:
                    outcomes.append(("ok", future.result()))
                except HistoryDiagnosticConflictError:
                    outcomes.append(("conflict", None))
        assert [kind for kind, _ in outcomes].count("ok") == 1
        assert [kind for kind, _ in outcomes].count("conflict") == 1


def test_history_diagnostic_lookup_by_request_is_exact_and_validated(tmp_path):
    storage, _ = _storage(tmp_path)
    row = _diagnostic_row(key="preflight")
    storage.create_history_diagnostic(row)
    found = storage.get_history_diagnostic_by_request(
        container_ref=row["container_ref"],
        active_session_ref=row["active_session_ref"],
        visibility=row["visibility"],
        idempotency_key="preflight",
    )
    assert found["id"] == row["id"]
    assert storage.get_history_diagnostic_by_request(
        container_ref=row["container_ref"],
        active_session_ref="wrong",
        visibility=row["visibility"],
        idempotency_key="preflight",
    ) is None