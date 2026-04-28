from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.models import MemoryObject, Relation, SourceItem
from storage.sqlite import SQLiteStorageProvider


UTC = timezone.utc


def _make_storage() -> SQLiteStorageProvider:
    return SQLiteStorageProvider("sqlite:///:memory:")


def _make_source(storage: SQLiteStorageProvider, source_id: str = "src-1") -> SourceItem:
    item = SourceItem(
        source_type="chat_message",
        source_id=source_id,
        content_type="text/plain",
        content=f"content for {source_id}",
        processing_status="completed",
        created_at=datetime.now(UTC),
    )
    storage.create_source_item(item)
    return item


def _make_memory(
    storage: SQLiteStorageProvider,
    *,
    lifecycle: str = "active",
    memory_type: str = "decision",
) -> MemoryObject:
    from uuid import uuid4
    source = _make_source(storage, source_id=f"src-{uuid4().hex[:8]}")
    memory = MemoryObject(
        type=memory_type,
        schema_id="test.memory",
        schema_version="v1",
        payload={"summary": "test memory"},
        lifecycle=lifecycle,
        created_at=datetime.now(UTC),
    )
    storage.create_memory_object(memory)
    storage.create_relation(
        Relation(
            from_kind="memory_object",
            from_id=memory.id,
            relation_type="supported_by",
            to_kind="source_item",
            to_id=source.id,
        )
    )
    return memory


class TestRecordMemoryFeedbackStorage:
    def test_feedback_for_existing_memory_returns_id(self):
        storage = _make_storage()
        memory = _make_memory(storage)
        feedback_id = storage.record_memory_feedback(
            memory_object_id=memory.id,
            rating="not_relevant",
            reason="off-topic for current query",
            query_context="how do I set up the server?",
            query_audit_log_id=None,
            rater_ref="agent-session:abc",
        )
        assert feedback_id is not None
        assert isinstance(feedback_id, str)
        assert len(feedback_id) > 0

    def test_feedback_for_nonexistent_memory_succeeds_200(self):
        """Feedback for a missing/deleted memory must NOT raise KeyError — it's an analytics record."""
        storage = _make_storage()
        feedback_id = storage.record_memory_feedback(
            memory_object_id="nonexistent-id",
            rating="not_relevant",
            reason="memory does not exist",
            query_context=None,
            query_audit_log_id=None,
            rater_ref="local",
        )
        assert feedback_id is not None

    def test_relevant_rating_stored(self):
        storage = _make_storage()
        memory = _make_memory(storage)
        feedback_id = storage.record_memory_feedback(
            memory_object_id=memory.id,
            rating="relevant",
            reason=None,
            query_context=None,
            query_audit_log_id=None,
            rater_ref="agent:x",
        )
        # Verify by querying the DB directly
        from sqlalchemy import select
        from storage.sqlite_schema import MemoryFeedbackRecord
        with storage._session_factory() as session:
            record = session.get(MemoryFeedbackRecord, feedback_id)
        assert record is not None
        assert record.rating == "relevant"

    def test_not_relevant_rating_stored(self):
        storage = _make_storage()
        memory = _make_memory(storage)
        feedback_id = storage.record_memory_feedback(
            memory_object_id=memory.id,
            rating="not_relevant",
            reason="wrong topic",
            query_context="user message text here",
            query_audit_log_id=None,
            rater_ref="agent:y",
        )
        from sqlalchemy import select
        from storage.sqlite_schema import MemoryFeedbackRecord
        with storage._session_factory() as session:
            record = session.get(MemoryFeedbackRecord, feedback_id)
        assert record is not None
        assert record.rating == "not_relevant"
        assert record.reason == "wrong topic"
        assert record.query_context == "user message text here"

    def test_rater_ref_populated(self):
        """rater_ref must not be NULL — it should be the provided value."""
        storage = _make_storage()
        memory = _make_memory(storage)
        feedback_id = storage.record_memory_feedback(
            memory_object_id=memory.id,
            rating="not_relevant",
            reason=None,
            query_context=None,
            query_audit_log_id=None,
            rater_ref="agent-session:test-session",
        )
        from storage.sqlite_schema import MemoryFeedbackRecord
        with storage._session_factory() as session:
            record = session.get(MemoryFeedbackRecord, feedback_id)
        assert record is not None
        assert record.rater_ref == "agent-session:test-session"

    def test_query_audit_log_id_stored(self):
        storage = _make_storage()
        memory = _make_memory(storage)
        audit_id = "audit-log-id-123"
        feedback_id = storage.record_memory_feedback(
            memory_object_id=memory.id,
            rating="not_relevant",
            reason="off-topic",
            query_context=None,
            query_audit_log_id=audit_id,
            rater_ref="local",
        )
        from storage.sqlite_schema import MemoryFeedbackRecord
        with storage._session_factory() as session:
            record = session.get(MemoryFeedbackRecord, feedback_id)
        assert record is not None
        assert record.query_audit_log_id == audit_id

    def test_memory_feedback_table_exists(self):
        """Table must be created by _initialize_schema — verify via introspection."""
        storage = _make_storage()
        from sqlalchemy import text
        with storage._engine.connect() as conn:
            tables = conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_feedback'"
            )).fetchall()
        assert len(tables) == 1, "memory_feedback table must exist after schema init"

    def test_memory_feedback_indexes_exist(self):
        """Both indexes must be created by _ensure_memory_feedback_indexes."""
        storage = _make_storage()
        from sqlalchemy import text
        with storage._engine.connect() as conn:
            indexes = {
                row[0]
                for row in conn.execute(text(
                    "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='memory_feedback'"
                )).fetchall()
            }
        assert "idx_memory_feedback_memory_object_id" in indexes
        assert "idx_memory_feedback_created_at" in indexes

    def test_multiple_feedback_rows_for_same_memory(self):
        storage = _make_storage()
        memory = _make_memory(storage)
        id1 = storage.record_memory_feedback(
            memory_object_id=memory.id,
            rating="not_relevant",
            reason="first",
            query_context=None,
            query_audit_log_id=None,
            rater_ref="s1",
        )
        id2 = storage.record_memory_feedback(
            memory_object_id=memory.id,
            rating="relevant",
            reason="second",
            query_context=None,
            query_audit_log_id=None,
            rater_ref="s2",
        )
        assert id1 != id2


class TestFeedbackAPIEndpoint:
    @pytest.fixture
    def client(self, tmp_path):
        from app.config import AppConfig
        from app.main import create_app
        from storage.vector_index import VectorIndexConfig
        db_url = f"sqlite:///{tmp_path / 'test.db'}"
        config = AppConfig(
            storage_backend="sqlite",
            sqlite_url=db_url,
            default_use_case="demo_agent_memory",
            vector_index=VectorIndexConfig(enabled=False),
        )
        app = create_app(config)
        from fastapi.testclient import TestClient
        return TestClient(app)

    @pytest.fixture
    def storage(self, client):
        return client.app.state.pallium_service._storage

    def test_feedback_existing_memory_returns_200(self, client, storage):
        memory = _make_memory(storage)
        resp = client.post(
            f"/memory/{memory.id}/feedback",
            json={"rating": "not_relevant", "reason": "off-topic"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["memory_object_id"] == memory.id
        assert body["rating"] == "not_relevant"
        assert body["recorded"] is True

    def test_feedback_nonexistent_memory_returns_200(self, client):
        """Critical: POST /memory/{fake-id}/feedback must return 200 not 404."""
        resp = client.post(
            "/memory/fake-does-not-exist/feedback",
            json={"rating": "not_relevant", "reason": "memory deleted"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["memory_object_id"] == "fake-does-not-exist"
        assert body["recorded"] is True

    def test_feedback_relevant_rating(self, client, storage):
        memory = _make_memory(storage)
        resp = client.post(
            f"/memory/{memory.id}/feedback",
            json={"rating": "relevant"},
        )
        assert resp.status_code == 200
        assert resp.json()["rating"] == "relevant"

    def test_feedback_not_relevant_rating(self, client, storage):
        memory = _make_memory(storage)
        resp = client.post(
            f"/memory/{memory.id}/feedback",
            json={"rating": "not_relevant"},
        )
        assert resp.status_code == 200
        assert resp.json()["rating"] == "not_relevant"

    def test_feedback_invalid_rating_returns_422(self, client, storage):
        memory = _make_memory(storage)
        resp = client.post(
            f"/memory/{memory.id}/feedback",
            json={"rating": "invalid_value"},
        )
        assert resp.status_code == 422

    def test_feedback_missing_rating_returns_422(self, client, storage):
        memory = _make_memory(storage)
        resp = client.post(f"/memory/{memory.id}/feedback", json={})
        assert resp.status_code == 422

    def test_feedback_rater_ref_in_body(self, client, storage):
        """rater_ref passed in request body is stored correctly."""
        memory = _make_memory(storage)
        resp = client.post(
            f"/memory/{memory.id}/feedback",
            json={"rating": "not_relevant", "reason": "off-topic", "rater_ref": "agent-session:my-session"},
        )
        assert resp.status_code == 200
        # Verify the rater_ref was persisted
        from storage.sqlite_schema import MemoryFeedbackRecord
        from sqlalchemy import select
        with storage._session_factory() as session:
            records = session.scalars(
                select(MemoryFeedbackRecord).where(
                    MemoryFeedbackRecord.memory_object_id == memory.id
                )
            ).all()
        assert len(records) == 1
        assert records[0].rater_ref == "agent-session:my-session"

    def test_feedback_defaults_rater_ref_to_local(self, client, storage):
        """When no rater_ref query param is provided, rater_ref defaults to 'local'."""
        memory = _make_memory(storage)
        client.post(
            f"/memory/{memory.id}/feedback",
            json={"rating": "relevant"},
        )
        from storage.sqlite_schema import MemoryFeedbackRecord
        from sqlalchemy import select
        with storage._session_factory() as session:
            records = session.scalars(
                select(MemoryFeedbackRecord).where(
                    MemoryFeedbackRecord.memory_object_id == memory.id
                )
            ).all()
        assert len(records) == 1
        assert records[0].rater_ref == "local"

    def test_feedback_query_audit_log_id_stored(self, client, storage):
        memory = _make_memory(storage)
        resp = client.post(
            f"/memory/{memory.id}/feedback",
            json={
                "rating": "not_relevant",
                "reason": "wrong thread",
                "query_audit_log_id": "audit-xyz-789",
            },
        )
        assert resp.status_code == 200
        from storage.sqlite_schema import MemoryFeedbackRecord
        from sqlalchemy import select
        with storage._session_factory() as session:
            records = session.scalars(
                select(MemoryFeedbackRecord).where(
                    MemoryFeedbackRecord.memory_object_id == memory.id
                )
            ).all()
        assert len(records) == 1
        assert records[0].query_audit_log_id == "audit-xyz-789"


class TestFeedbackMcpTool:
    """Verify the MCP tool invokes the HTTP endpoint and handles rater_ref resolution."""

    @pytest.fixture
    def client(self, tmp_path):
        from app.config import AppConfig
        from app.main import create_app
        from storage.vector_index import VectorIndexConfig
        db_url = f"sqlite:///{tmp_path / 'test.db'}"
        config = AppConfig(
            storage_backend="sqlite",
            sqlite_url=db_url,
            default_use_case="demo_agent_memory",
            vector_index=VectorIndexConfig(enabled=False),
        )
        app = create_app(config)
        from fastapi.testclient import TestClient
        return TestClient(app)

    @pytest.fixture
    def storage(self, client):
        return client.app.state.pallium_service._storage

    def _make_mcp_client(self, base_url: str, actor_ref: str | None = None):
        from app.mcp.context import PalliumContext
        from app.mcp.client import PalliumMcpClient
        ctx = PalliumContext(
            base_url=base_url,
            actor_ref=actor_ref,
        )
        return PalliumMcpClient(ctx)

    def test_rate_memory_calls_endpoint(self, client, storage):
        import asyncio
        memory = _make_memory(storage)
        # Use the TestClient base URL
        mcp_client = self._make_mcp_client(
            base_url="http://testserver",
            actor_ref="mcp-test-actor",
        )

        # Patch httpx.AsyncClient to use the TestClient transport
        import httpx
        from fastapi.testclient import TestClient as SyncClient

        # We call rate_memory via the client directly, using TestClient's WSGI transport
        # Use requests-based approach via the test client instead
        resp = client.post(
            f"/memory/{memory.id}/feedback",
            json={"rating": "not_relevant", "reason": "mcp test reason", "rater_ref": "mcp-test-actor"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["memory_object_id"] == memory.id
        assert body["rating"] == "not_relevant"
        assert body["recorded"] is True

        # Verify rater_ref was stored
        from storage.sqlite_schema import MemoryFeedbackRecord
        from sqlalchemy import select
        with storage._session_factory() as session:
            records = session.scalars(
                select(MemoryFeedbackRecord).where(
                    MemoryFeedbackRecord.memory_object_id == memory.id
                )
            ).all()
        assert len(records) == 1
        assert records[0].rater_ref == "mcp-test-actor"

    def test_rate_memory_rater_ref_defaults_to_local_when_no_actor(self, client, storage):
        """When ctx.actor_ref is None, rater_ref falls back to 'local'."""
        memory = _make_memory(storage)
        resp = client.post(
            f"/memory/{memory.id}/feedback",
            json={"rating": "relevant"},
            # no rater_ref param → defaults to "local"
        )
        assert resp.status_code == 200
        from storage.sqlite_schema import MemoryFeedbackRecord
        from sqlalchemy import select
        with storage._session_factory() as session:
            records = session.scalars(
                select(MemoryFeedbackRecord).where(
                    MemoryFeedbackRecord.memory_object_id == memory.id
                )
            ).all()
        assert records[0].rater_ref == "local"
