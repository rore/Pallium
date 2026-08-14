"""Historical-lookup reuse funnel — storage + loader (PR-a).

Covers the write-only event table, the append-only label table, their indexes,
the two writer round-trips, and the ``load_events_from_storage`` loader
(eligible-session reconstruction against the pinned predicate, consensus rung
join, and empty-safety). No LLM / app wiring — pure storage + loader.
"""
from __future__ import annotations

import json

from sqlalchemy import text

from core.models import new_id, utc_now
from evals.historical_lookup_measurement import (
    compute_reuse_rollup,
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


def _write_lookup(storage, *, container_ref, session_id, event_id=None) -> str:
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


# ---------------------------------------------------------------------------
# Writer round-trips
# ---------------------------------------------------------------------------


class TestWriters:
    def test_event_row_round_trip(self, tmp_path) -> None:
        storage, _ = _storage(tmp_path)
        event_id = _write_lookup(storage, container_ref="c:1", session_id="t:1")
        with storage._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT event_type, session_id, container_ref, trigger_origin, "
                    "parent_lookup_id, exposed_json FROM historical_lookup_reuse_event "
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
