"""Unit tests for W3 explicit memory-write storage methods.

Covers the four storage-layer methods that back the W3 MCP tools:
- mark_memory_origin
- link_supersession
- soft_delete_memory
- correct_memory_payload

Tests each method's contract in isolation:
- Happy path (values written correctly, returned as expected)
- Error paths (missing memory_object → KeyError; wrong state →
  SupersessionConflictError)
- Idempotence (soft_delete on already-forgotten memory is a no-op)
- Invariant 1 compliance (no ranking / accessibility state updates
  triggered by write alone — verified by spot-checking that no other
  fields are touched)

Concurrency-safety (writes serialized via _with_retry) is not tested
here directly; that's covered by the surrounding integration tests
where two write calls execute in parallel. This file focuses on the
per-call contract.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from core.errors import SupersessionConflictError
from core.models import MemoryObject
from storage.sqlite import SQLiteStorageProvider


@pytest.fixture
def store(tmp_path):
    return SQLiteStorageProvider(f"sqlite:///{tmp_path / 'w3.db'}")


def _make_memory(memory_id: str, payload: dict | None = None) -> MemoryObject:
    """Minimal MemoryObject that create_memory_object accepts."""
    return MemoryObject(
        id=memory_id,
        type="decision",
        schema_id="test-schema",
        schema_version="1",
        payload=payload or {"statement": f"test {memory_id}"},
        lifecycle="active",
        visibility="private",
        container_ref="git:test",
        actor_ref=None,
        freshness_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        created_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )


class TestMarkMemoryOrigin:
    def test_sets_origin_and_provenance(self, store):
        store.create_memory_object(_make_memory("m1"))
        store.mark_memory_origin(
            "m1",
            origin="agent_explicit",
            origin_session_id="sess-1",
            origin_agent_id="agent-1",
        )
        row = store.get_memory_object("m1")
        # get_memory_object roundtrips through MemoryObject; peek at raw row for W3 columns.
        with store._engine.connect() as conn:
            from sqlalchemy import text as _text
            r = conn.execute(_text(
                "SELECT origin, origin_session_id, origin_agent_id "
                "FROM memory_objects WHERE id='m1'"
            )).one()
        assert r.origin == "agent_explicit"
        assert r.origin_session_id == "sess-1"
        assert r.origin_agent_id == "agent-1"

    def test_rejects_unknown_origin_enum(self, store):
        store.create_memory_object(_make_memory("m1"))
        with pytest.raises(ValueError, match="origin must be one of"):
            store.mark_memory_origin("m1", origin="bogus")

    def test_missing_memory_raises_keyerror(self, store):
        with pytest.raises(KeyError, match="does-not-exist"):
            store.mark_memory_origin("does-not-exist", origin="agent_explicit")

    def test_idempotent_same_values(self, store):
        store.create_memory_object(_make_memory("m1"))
        store.mark_memory_origin("m1", origin="agent_explicit")
        store.mark_memory_origin("m1", origin="agent_explicit")  # no error
        with store._engine.connect() as conn:
            from sqlalchemy import text as _text
            origin = conn.execute(_text(
                "SELECT origin FROM memory_objects WHERE id='m1'"
            )).scalar()
        assert origin == "agent_explicit"

    def test_partial_update_leaves_untouched_fields_alone(self, store):
        """If only origin is passed, don't clobber existing session/agent ids."""
        store.create_memory_object(_make_memory("m1"))
        store.mark_memory_origin(
            "m1",
            origin="agent_explicit",
            origin_session_id="sess-1",
            origin_agent_id="agent-1",
        )
        # Second call with only origin — provenance columns must survive.
        store.mark_memory_origin("m1", origin="user_requested")
        with store._engine.connect() as conn:
            from sqlalchemy import text as _text
            r = conn.execute(_text(
                "SELECT origin, origin_session_id, origin_agent_id "
                "FROM memory_objects WHERE id='m1'"
            )).one()
        assert r.origin == "user_requested"
        assert r.origin_session_id == "sess-1"  # preserved
        assert r.origin_agent_id == "agent-1"  # preserved


class TestLinkSupersession:
    def test_marks_old_superseded_and_records_pointer(self, store):
        store.create_memory_object(_make_memory("old"))
        store.create_memory_object(_make_memory("new"))
        store.link_supersession("old", "new", correction_reason="better fact found")

        with store._engine.connect() as conn:
            from sqlalchemy import text as _text
            r_old = conn.execute(_text(
                "SELECT lifecycle, superseded_by_id, correction_reason "
                "FROM memory_objects WHERE id='old'"
            )).one()
            r_new = conn.execute(_text(
                "SELECT lifecycle, superseded_by_id FROM memory_objects WHERE id='new'"
            )).one()

        assert r_old.lifecycle == "superseded"
        assert r_old.superseded_by_id == "new"
        assert r_old.correction_reason == "better fact found"
        # Invariant: new memory is untouched by the supersession.
        assert r_new.lifecycle == "active"
        assert r_new.superseded_by_id is None

    def test_conflict_if_old_already_superseded(self, store):
        store.create_memory_object(_make_memory("a"))
        store.create_memory_object(_make_memory("b"))
        store.create_memory_object(_make_memory("c"))
        store.link_supersession("a", "b")
        with pytest.raises(SupersessionConflictError, match="not active"):
            store.link_supersession("a", "c")

    def test_conflict_if_old_lifecycle_not_active(self, store):
        store.create_memory_object(_make_memory("a"))
        store.create_memory_object(_make_memory("b"))
        # Force a to a non-active lifecycle without going through the W3 path.
        store.update_memory_object_lifecycle("a", "archived")
        with pytest.raises(SupersessionConflictError):
            store.link_supersession("a", "b")

    def test_missing_old_raises_keyerror(self, store):
        store.create_memory_object(_make_memory("new"))
        with pytest.raises(KeyError, match="ghost"):
            store.link_supersession("ghost", "new")

    def test_missing_new_raises_keyerror(self, store):
        store.create_memory_object(_make_memory("old"))
        with pytest.raises(KeyError, match="ghost"):
            store.link_supersession("old", "ghost")

    def test_correction_reason_optional(self, store):
        store.create_memory_object(_make_memory("old"))
        store.create_memory_object(_make_memory("new"))
        store.link_supersession("old", "new")
        with store._engine.connect() as conn:
            from sqlalchemy import text as _text
            reason = conn.execute(_text(
                "SELECT correction_reason FROM memory_objects WHERE id='old'"
            )).scalar()
        assert reason is None


class TestSoftDeleteMemory:
    def test_marks_soft_deleted_with_reason(self, store):
        store.create_memory_object(_make_memory("m1"))
        result = store.soft_delete_memory("m1", reason="no longer useful")
        assert result is True

        with store._engine.connect() as conn:
            from sqlalchemy import text as _text
            r = conn.execute(_text(
                "SELECT is_soft_deleted, soft_delete_reason, soft_deleted_at "
                "FROM memory_objects WHERE id='m1'"
            )).one()
        assert r.is_soft_deleted == 1
        assert r.soft_delete_reason == "no longer useful"
        assert r.soft_deleted_at is not None

    def test_idempotent_on_already_deleted(self, store):
        store.create_memory_object(_make_memory("m1"))
        assert store.soft_delete_memory("m1", reason="first") is True
        # Second call: returns False, does not overwrite reason.
        assert store.soft_delete_memory("m1", reason="second") is False

        with store._engine.connect() as conn:
            from sqlalchemy import text as _text
            reason = conn.execute(_text(
                "SELECT soft_delete_reason FROM memory_objects WHERE id='m1'"
            )).scalar()
        assert reason == "first", "second call must not overwrite the original reason"

    def test_missing_memory_raises_keyerror(self, store):
        with pytest.raises(KeyError, match="ghost"):
            store.soft_delete_memory("ghost", reason="test")

    def test_soft_delete_does_not_change_lifecycle(self, store):
        """Tombstone is orthogonal to lifecycle. A soft-deleted memory may
        still be 'active' or 'superseded'; the retrieval filter checks both.
        """
        store.create_memory_object(_make_memory("m1"))
        store.soft_delete_memory("m1", reason="test")
        row = store.get_memory_object("m1")
        assert row.lifecycle == "active", \
            "soft-delete must not change lifecycle"


class TestCorrectMemoryPayload:
    def test_updates_payload_and_records_reason(self, store):
        store.create_memory_object(_make_memory("m1", {"statement": "wrong"}))
        store.correct_memory_payload(
            "m1",
            new_payload={"statement": "right"},
            correction_reason="test found the correct value",
        )

        with store._engine.connect() as conn:
            from sqlalchemy import text as _text
            r = conn.execute(_text(
                "SELECT payload_json, correction_reason, lifecycle, superseded_by_id "
                "FROM memory_objects WHERE id='m1'"
            )).one()
        assert json.loads(r.payload_json) == {"statement": "right"}
        assert r.correction_reason == "test found the correct value"
        # Invariant: correction is in-place, lifecycle unchanged.
        assert r.lifecycle == "active"
        assert r.superseded_by_id is None

    def test_conflict_if_memory_superseded(self, store):
        store.create_memory_object(_make_memory("old"))
        store.create_memory_object(_make_memory("new"))
        store.link_supersession("old", "new")
        with pytest.raises(SupersessionConflictError, match="non-active"):
            store.correct_memory_payload(
                "old",
                new_payload={"statement": "attempt"},
                correction_reason="won't apply",
            )

    def test_missing_memory_raises_keyerror(self, store):
        with pytest.raises(KeyError, match="ghost"):
            store.correct_memory_payload(
                "ghost",
                new_payload={"statement": "x"},
                correction_reason="test",
            )


class TestInvariant1Compliance:
    """Spot checks: none of the W3 write methods touch fields that
    influence retrieval ranking. Only the columns each method is
    documented to write should change.
    """

    def _snapshot(self, store, memory_id: str) -> dict:
        with store._engine.connect() as conn:
            from sqlalchemy import text as _text
            r = conn.execute(_text(
                "SELECT freshness_at, subject, visibility, container_ref, "
                "actor_ref, envelope_json "
                "FROM memory_objects WHERE id = :i"
            ), {"i": memory_id}).one()
        return dict(r._mapping)

    def test_mark_origin_does_not_touch_ranking_fields(self, store):
        store.create_memory_object(_make_memory("m1"))
        before = self._snapshot(store, "m1")
        store.mark_memory_origin("m1", origin="agent_explicit")
        after = self._snapshot(store, "m1")
        assert before == after

    def test_link_supersession_does_not_touch_new_memorys_ranking(self, store):
        store.create_memory_object(_make_memory("old"))
        store.create_memory_object(_make_memory("new"))
        before = self._snapshot(store, "new")
        store.link_supersession("old", "new")
        after = self._snapshot(store, "new")
        assert before == after

    def test_soft_delete_does_not_touch_ranking_fields(self, store):
        store.create_memory_object(_make_memory("m1"))
        before = self._snapshot(store, "m1")
        store.soft_delete_memory("m1", reason="test")
        after = self._snapshot(store, "m1")
        assert before == after

    def test_correct_payload_does_not_touch_ranking_fields(self, store):
        store.create_memory_object(_make_memory("m1"))
        before = self._snapshot(store, "m1")
        store.correct_memory_payload(
            "m1", new_payload={"statement": "fixed"}, correction_reason="test"
        )
        after = self._snapshot(store, "m1")
        assert before == after


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
