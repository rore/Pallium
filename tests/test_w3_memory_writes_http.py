"""W3 HTTP integration tests — the five explicit memory-write endpoints.

Covers:
- POST /memory/remember
- POST /memory/{id}/correct
- POST /memory/supersede
- POST /memory/{id}/forget
- POST /memory/record-outcome

Verifies:
- Happy path returns 200 with the expected response body.
- 400 on invalid enum / type / outcome.
- 404 on unknown memory_object_id.
- 409 on supersede/correct against already-superseded memory.
- Idempotence: forget-twice yields forgotten=False on the second call.
- Round-trip through the persistence layer: rows land in memory_objects
  with the correct W3 columns.

Concurrency (write serialization via _with_retry) is exercised by the
storage-layer tests in test_w3_memory_writes_storage.py; here we
confirm the HTTP surface presents the right semantics to callers.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.models import MemoryObject
from storage.sqlite import SQLiteStorageProvider


@pytest.fixture
def client(tmp_path):
    from app.config import AppConfig
    from app.main import create_app
    from storage.vector_index import VectorIndexConfig
    from tests.config_helpers import DEMO_SEMANTIC_PACKAGES

    db_url = f"sqlite:///{tmp_path / 'w3-http.db'}"
    config = AppConfig(
        storage_backend="sqlite",
        sqlite_url=db_url,
        default_use_case="demo_agent_memory",
        semantic_packages=DEMO_SEMANTIC_PACKAGES,
        vector_index=VectorIndexConfig(enabled=False),
    )
    app = create_app(config)
    from fastapi.testclient import TestClient
    return TestClient(app)


@pytest.fixture
def storage(client):
    return client.app.state.pallium_service._storage


def _seed_memory(storage, memory_id: str = "seed-1", mtype: str = "decision") -> MemoryObject:
    memory = MemoryObject(
        id=memory_id,
        type=mtype,
        schema_id=f"{mtype}.test.v1",
        schema_version="1",
        payload={"statement": f"seed {memory_id}"},
        lifecycle="active",
        visibility="private",
        container_ref="git:test",
        freshness_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        created_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    storage.create_memory_object(memory)
    return memory


class TestRememberEndpoint:
    def test_happy_path(self, client, storage):
        resp = client.post(
            "/memory/remember",
            json={
                "text": "Decision: prefer approach A over B because of latency.",
                "type": "decision",
                "confidence": 0.9,
                "container_ref": "git:test",
                "origin_session_id": "sess-1",
                "origin_agent_id": "agent-x",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["origin"] == "agent_explicit"
        assert "memory_object_id" in body

        # Round-trip: origin actually recorded in DB.
        from sqlalchemy import text as _text
        with storage._engine.connect() as conn:
            row = conn.execute(_text(
                "SELECT origin, origin_session_id, origin_agent_id, type "
                "FROM memory_objects WHERE id=:i"
            ), {"i": body["memory_object_id"]}).one()
        assert row.origin == "agent_explicit"
        assert row.origin_session_id == "sess-1"
        assert row.origin_agent_id == "agent-x"
        assert row.type == "decision"

    def test_invalid_type_returns_400(self, client):
        resp = client.post(
            "/memory/remember",
            json={"text": "bogus", "type": "not_a_real_type"},
        )
        assert resp.status_code == 400
        assert "must be one of" in resp.json()["detail"]

    def test_empty_text_returns_422(self, client):
        # Pydantic min_length=1 rejects at the boundary.
        resp = client.post("/memory/remember", json={"text": "", "type": "decision"})
        assert resp.status_code == 422

    def test_oversize_text_returns_422(self, client):
        big = "x" * 10_001  # exceeds _MAX_MEMORY_TEXT_CHARS
        resp = client.post("/memory/remember", json={"text": big, "type": "decision"})
        assert resp.status_code == 422

    def test_negative_confidence_returns_422(self, client):
        resp = client.post(
            "/memory/remember",
            json={"text": "x", "type": "decision", "confidence": -0.1},
        )
        assert resp.status_code == 422


class TestCorrectEndpoint:
    def test_happy_path(self, client, storage):
        memory = _seed_memory(storage)
        resp = client.post(
            f"/memory/{memory.id}/correct",
            json={"corrected_text": "corrected text", "reason": "test found the actual value"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["memory_object_id"] == memory.id
        assert body["corrected"] is True

        from sqlalchemy import text as _text
        with storage._engine.connect() as conn:
            row = conn.execute(_text(
                "SELECT correction_reason, lifecycle, superseded_by_id "
                "FROM memory_objects WHERE id=:i"
            ), {"i": memory.id}).one()
        assert row.correction_reason == "test found the actual value"
        assert row.lifecycle == "active"
        assert row.superseded_by_id is None

    def test_unknown_memory_returns_404(self, client):
        resp = client.post(
            "/memory/nonexistent/correct",
            json={"corrected_text": "x", "reason": "test"},
        )
        assert resp.status_code == 404

    def test_correct_on_superseded_returns_409(self, client, storage):
        old = _seed_memory(storage, memory_id="conflict-old")
        # Supersede first via the service directly.
        client.post(
            "/memory/supersede",
            json={"new_text": "replacement", "supersedes_id": old.id},
        )
        # Now try to correct the old memory — must be 409.
        resp = client.post(
            f"/memory/{old.id}/correct",
            json={"corrected_text": "attempt", "reason": "should fail"},
        )
        assert resp.status_code == 409


class TestSupersedeEndpoint:
    def test_happy_path(self, client, storage):
        old = _seed_memory(storage, memory_id="ss-old")
        resp = client.post(
            "/memory/supersede",
            json={
                "new_text": "new fact replaces old",
                "supersedes_id": old.id,
                "reason": "found a better formulation",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["old_memory_object_id"] == old.id
        assert body["superseded"] is True
        new_id = body["new_memory_object_id"]

        from sqlalchemy import text as _text
        with storage._engine.connect() as conn:
            r_old = conn.execute(_text(
                "SELECT lifecycle, superseded_by_id, correction_reason "
                "FROM memory_objects WHERE id=:i"
            ), {"i": old.id}).one()
            r_new = conn.execute(_text(
                "SELECT lifecycle, origin FROM memory_objects WHERE id=:i"
            ), {"i": new_id}).one()

        assert r_old.lifecycle == "superseded"
        assert r_old.superseded_by_id == new_id
        assert r_old.correction_reason == "found a better formulation"
        assert r_new.lifecycle == "active"
        assert r_new.origin == "agent_explicit"

    def test_supersede_missing_old_returns_404(self, client):
        resp = client.post(
            "/memory/supersede",
            json={"new_text": "x", "supersedes_id": "nonexistent"},
        )
        assert resp.status_code == 404

    def test_double_supersede_returns_409(self, client, storage):
        old = _seed_memory(storage, memory_id="dbl-old")
        assert client.post(
            "/memory/supersede",
            json={"new_text": "first", "supersedes_id": old.id},
        ).status_code == 200
        resp = client.post(
            "/memory/supersede",
            json={"new_text": "second", "supersedes_id": old.id},
        )
        assert resp.status_code == 409


class TestForgetEndpoint:
    def test_happy_path(self, client, storage):
        memory = _seed_memory(storage, memory_id="forget-me")
        resp = client.post(
            f"/memory/{memory.id}/forget",
            json={"reason": "no longer relevant"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["memory_object_id"] == memory.id
        assert body["forgotten"] is True

        from sqlalchemy import text as _text
        with storage._engine.connect() as conn:
            r = conn.execute(_text(
                "SELECT is_soft_deleted, soft_delete_reason "
                "FROM memory_objects WHERE id=:i"
            ), {"i": memory.id}).one()
        assert r.is_soft_deleted == 1
        assert r.soft_delete_reason == "no longer relevant"

    def test_double_forget_is_idempotent(self, client, storage):
        memory = _seed_memory(storage, memory_id="dbl-forget")
        first = client.post(
            f"/memory/{memory.id}/forget",
            json={"reason": "first"},
        )
        assert first.json()["forgotten"] is True
        # Second call: still 200, but forgotten=False (idempotent, does not overwrite).
        second = client.post(
            f"/memory/{memory.id}/forget",
            json={"reason": "second"},
        )
        assert second.status_code == 200
        assert second.json()["forgotten"] is False

        from sqlalchemy import text as _text
        with storage._engine.connect() as conn:
            reason = conn.execute(_text(
                "SELECT soft_delete_reason FROM memory_objects WHERE id=:i"
            ), {"i": memory.id}).scalar()
        assert reason == "first", "idempotent forget must not overwrite reason"

    def test_unknown_memory_returns_404(self, client):
        resp = client.post(
            "/memory/nonexistent/forget",
            json={"reason": "test"},
        )
        assert resp.status_code == 404


class TestRecordOutcomeEndpoint:
    def test_happy_path(self, client, storage):
        proc = _seed_memory(storage, memory_id="proc-1", mtype="operational_fact")
        resp = client.post(
            "/memory/record-outcome",
            json={
                "procedure_id": proc.id,
                "outcome": "success",
                "note": "worked on first try",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["procedure_id"] == proc.id
        assert body["outcome"] == "success"
        assert body["recorded"] is True

    def test_invalid_outcome_returns_422(self, client, storage):
        proc = _seed_memory(storage, memory_id="proc-2", mtype="operational_fact")
        resp = client.post(
            "/memory/record-outcome",
            json={"procedure_id": proc.id, "outcome": "maybe"},
        )
        assert resp.status_code == 422  # pydantic Literal validation

    def test_unknown_procedure_returns_404(self, client):
        resp = client.post(
            "/memory/record-outcome",
            json={"procedure_id": "nonexistent", "outcome": "success"},
        )
        assert resp.status_code == 404


class TestConcurrencySafeSemanticsViaHTTP:
    """Concurrency is enforced at the storage layer via _with_retry + SQLite
    IMMEDIATE transactions. Here we sanity-check that two supersede attempts
    against the same old memory reach a consistent state (first wins, second
    409).
    """

    def test_first_supersede_wins_second_409(self, client, storage):
        old = _seed_memory(storage, memory_id="race-old")
        # Simulate two agents by calling twice in sequence — the second one
        # sees the state written by the first and returns 409.
        r1 = client.post(
            "/memory/supersede",
            json={"new_text": "first attempt", "supersedes_id": old.id},
        )
        r2 = client.post(
            "/memory/supersede",
            json={"new_text": "second attempt", "supersedes_id": old.id},
        )
        assert r1.status_code == 200
        assert r2.status_code == 409

        # Only one supersession chain exists.
        from sqlalchemy import text as _text
        with storage._engine.connect() as conn:
            row = conn.execute(_text(
                "SELECT COUNT(*) FROM memory_objects WHERE superseded_by_id IS NOT NULL"
            )).scalar()
        assert row == 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
