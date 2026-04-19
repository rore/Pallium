from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.models import MemoryFlag, MemoryObject, Relation, SourceItem
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


class TestStoreMemoryFlag:
    def test_flag_stored_and_retrievable(self):
        storage = _make_storage()
        memory = _make_memory(storage)
        flag = MemoryFlag(
            memory_object_id=memory.id,
            reason="outdated",
            source_ref="agent-session:abc",
        )
        storage.store_memory_flag(flag)
        flags = storage.list_memory_flags(memory.id)
        assert len(flags) == 1
        assert flags[0].reason == "outdated"
        assert flags[0].source_ref == "agent-session:abc"
        assert flags[0].memory_object_id == memory.id

    def test_flag_unknown_memory_raises_key_error(self):
        storage = _make_storage()
        flag = MemoryFlag(
            memory_object_id="nonexistent-id",
            reason="bad",
            source_ref="session:x",
        )
        with pytest.raises(KeyError):
            storage.store_memory_flag(flag)

    def test_multiple_flags_stored(self):
        storage = _make_storage()
        memory = _make_memory(storage)
        for i in range(3):
            storage.store_memory_flag(MemoryFlag(
                memory_object_id=memory.id,
                reason=f"reason-{i}",
                source_ref=f"session:{i}",
            ))
        flags = storage.list_memory_flags(memory.id)
        assert len(flags) == 3

    def test_list_flags_empty_for_unflagged_memory(self):
        storage = _make_storage()
        memory = _make_memory(storage)
        flags = storage.list_memory_flags(memory.id)
        assert flags == []


class TestCountUniqueFlags:
    def test_dedup_same_source_ref(self):
        storage = _make_storage()
        memory = _make_memory(storage)
        for _ in range(3):
            storage.store_memory_flag(MemoryFlag(
                memory_object_id=memory.id,
                reason="bad",
                source_ref="same-session",
            ))
        assert storage.count_unique_flag_sources(memory.id, 30) == 1

    def test_unique_sources_counted(self):
        storage = _make_storage()
        memory = _make_memory(storage)
        storage.store_memory_flag(MemoryFlag(
            memory_object_id=memory.id,
            reason="bad",
            source_ref="session-a",
        ))
        storage.store_memory_flag(MemoryFlag(
            memory_object_id=memory.id,
            reason="also bad",
            source_ref="session-b",
        ))
        assert storage.count_unique_flag_sources(memory.id, 30) == 2

    def test_window_excludes_old_flags(self):
        storage = _make_storage()
        memory = _make_memory(storage)
        old_flag = MemoryFlag(
            memory_object_id=memory.id,
            reason="old",
            source_ref="session-old",
            flagged_at=datetime.now(UTC) - timedelta(days=31),
        )
        storage.store_memory_flag(old_flag)
        new_flag = MemoryFlag(
            memory_object_id=memory.id,
            reason="new",
            source_ref="session-new",
        )
        storage.store_memory_flag(new_flag)
        assert storage.count_unique_flag_sources(memory.id, 30) == 1
        assert storage.count_total_flags(memory.id) == 2

    def test_zero_for_unflagged_memory(self):
        storage = _make_storage()
        memory = _make_memory(storage)
        assert storage.count_unique_flag_sources(memory.id, 30) == 0
        assert storage.count_total_flags(memory.id) == 0


class TestFlagMemoryObjectService:
    """Tests for PalliumService.flag_memory_object via direct storage + service logic."""

    def _make_service(self):
        from unittest.mock import MagicMock
        from core.service import PalliumService
        storage = _make_storage()
        service = PalliumService(
            storage=storage,
            retrieval=MagicMock(),
            semantic_plugins={},
            default_use_case="test",
        )
        return service, storage

    def test_flag_below_threshold_no_suppression(self):
        service, storage = self._make_service()
        memory = _make_memory(storage)
        result = service.flag_memory_object(
            memory.id, "bad", "session-a", immediate=False,
        )
        assert result.suppressed is False
        assert result.flag_count == 1
        assert result.unique_sources == 1
        refreshed = storage.get_memory_object(memory.id)
        assert refreshed.lifecycle == "active"

    def test_threshold_reached_suppresses(self):
        service, storage = self._make_service()
        memory = _make_memory(storage)
        service.flag_memory_object(memory.id, "bad", "session-a")
        result = service.flag_memory_object(memory.id, "also bad", "session-b")
        assert result.suppressed is True
        assert result.unique_sources == 2
        refreshed = storage.get_memory_object(memory.id)
        assert refreshed.lifecycle == "suppressed"

    def test_same_session_dedup_no_suppression(self):
        service, storage = self._make_service()
        memory = _make_memory(storage)
        service.flag_memory_object(memory.id, "bad turn 1", "same-session")
        result = service.flag_memory_object(memory.id, "bad turn 2", "same-session")
        assert result.suppressed is False
        assert result.flag_count == 2
        assert result.unique_sources == 1

    def test_immediate_suppresses_with_one_flag(self):
        service, storage = self._make_service()
        memory = _make_memory(storage)
        result = service.flag_memory_object(
            memory.id, "garbage fragment", "triage:2026-04-17", immediate=True,
        )
        assert result.suppressed is True
        assert result.flag_count == 1
        refreshed = storage.get_memory_object(memory.id)
        assert refreshed.lifecycle == "suppressed"

    def test_flag_already_suppressed_is_idempotent(self):
        service, storage = self._make_service()
        memory = _make_memory(storage)
        service.flag_memory_object(memory.id, "first", "triage:1", immediate=True)
        result = service.flag_memory_object(memory.id, "second", "session-x")
        assert result.suppressed is True
        assert result.flag_count == 2

    def test_flag_superseded_memory_records_but_no_lifecycle_change(self):
        service, storage = self._make_service()
        memory = _make_memory(storage, lifecycle="superseded")
        result = service.flag_memory_object(memory.id, "outdated", "session-a")
        assert result.suppressed is False
        assert result.flag_count == 1
        refreshed = storage.get_memory_object(memory.id)
        assert refreshed.lifecycle == "superseded"

    def test_flag_unknown_memory_raises_key_error(self):
        service, _storage = self._make_service()
        with pytest.raises(KeyError):
            service.flag_memory_object("nonexistent", "bad", "session-a")

    def test_window_prevents_old_flag_from_counting(self):
        service, storage = self._make_service()
        memory = _make_memory(storage)
        old_flag = MemoryFlag(
            memory_object_id=memory.id,
            reason="old flag",
            source_ref="session-old",
            flagged_at=datetime.now(UTC) - timedelta(days=31),
        )
        storage.store_memory_flag(old_flag)
        result = service.flag_memory_object(memory.id, "new flag", "session-new")
        assert result.suppressed is False
        assert result.flag_count == 2
        assert result.unique_sources == 1


class TestFlagAPIEndpoint:
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

    def test_flag_endpoint_returns_200(self, client, storage):
        memory = _make_memory(storage)
        resp = client.post(
            f"/memory/{memory.id}/flag",
            json={"reason": "outdated", "source_ref": "session:a"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["memory_object_id"] == memory.id
        assert body["flag_count"] == 1
        assert body["suppressed"] is False

    def test_flag_endpoint_404_unknown_memory(self, client):
        resp = client.post(
            "/memory/nonexistent-id/flag",
            json={"reason": "bad", "source_ref": "session:a"},
        )
        assert resp.status_code == 404

    def test_flag_endpoint_422_missing_fields(self, client, storage):
        memory = _make_memory(storage)
        resp = client.post(f"/memory/{memory.id}/flag", json={})
        assert resp.status_code == 422

    def test_flag_endpoint_suppresses_after_threshold(self, client, storage):
        memory = _make_memory(storage)
        client.post(
            f"/memory/{memory.id}/flag",
            json={"reason": "bad", "source_ref": "session:a"},
        )
        resp = client.post(
            f"/memory/{memory.id}/flag",
            json={"reason": "still bad", "source_ref": "session:b"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["suppressed"] is True

    def test_flag_endpoint_immediate_mode(self, client, storage):
        memory = _make_memory(storage)
        resp = client.post(
            f"/memory/{memory.id}/flag",
            json={"reason": "garbage", "source_ref": "triage:1", "immediate": True},
        )
        assert resp.status_code == 200
        assert resp.json()["suppressed"] is True

    def test_suppressed_memory_excluded_from_query(self, client, storage):
        memory = _make_memory(storage)
        client.post(
            f"/memory/{memory.id}/flag",
            json={"reason": "garbage", "source_ref": "triage:1", "immediate": True},
        )
        objects = storage.list_memory_objects(lifecycle="active")
        memory_ids = {m.id for m in objects}
        assert memory.id not in memory_ids


class TestRetentionWithSuppressed:
    def test_suppressed_memory_cleaned_by_retention(self):
        from core.contracts import MemoryRetentionPolicy
        from core.retention import SUPERSEDED_MEMORY_TTL
        storage = _make_storage()
        memory = _make_memory(storage, lifecycle="active")
        storage.update_memory_object_lifecycle(memory.id, "suppressed")
        storage.store_memory_flag(MemoryFlag(
            memory_object_id=memory.id,
            reason="bad",
            source_ref="session:a",
        ))
        old_time = datetime.now(UTC) - SUPERSEDED_MEMORY_TTL - timedelta(hours=1)
        storage.refresh_memory_object_freshness(memory.id)
        from sqlalchemy import text as sql_text
        with storage._session_factory.begin() as session:
            session.execute(
                sql_text("UPDATE memory_objects SET freshness_at = :ts WHERE id = :mid"),
                {"ts": old_time, "mid": memory.id},
            )

        policy = MemoryRetentionPolicy(
            durable_types=frozenset({"decision"}),
            working_types=frozenset(),
            orphan_delete_types=frozenset(),
        )
        stats = storage.run_retention_pass(
            now=datetime.now(UTC),
            retention_policy=policy,
            batch_size=100,
        )
        assert stats.deleted_memory_objects >= 1
        with pytest.raises(KeyError):
            storage.get_memory_object(memory.id)
        assert storage.list_memory_flags(memory.id) == []

    def test_flag_cascade_on_memory_deletion(self):
        from core.contracts import MemoryRetentionPolicy
        from core.retention import SUPERSEDED_MEMORY_TTL
        storage = _make_storage()
        memory = _make_memory(storage, lifecycle="active")
        storage.update_memory_object_lifecycle(memory.id, "superseded")
        for i in range(3):
            storage.store_memory_flag(MemoryFlag(
                memory_object_id=memory.id,
                reason=f"reason-{i}",
                source_ref=f"session:{i}",
            ))
        assert len(storage.list_memory_flags(memory.id)) == 3
        old_time = datetime.now(UTC) - SUPERSEDED_MEMORY_TTL - timedelta(hours=1)
        storage.refresh_memory_object_freshness(memory.id)
        from sqlalchemy import text as sql_text
        with storage._session_factory.begin() as session:
            session.execute(
                sql_text("UPDATE memory_objects SET freshness_at = :ts WHERE id = :mid"),
                {"ts": old_time, "mid": memory.id},
            )
        policy = MemoryRetentionPolicy(
            durable_types=frozenset(),
            working_types=frozenset(),
            orphan_delete_types=frozenset(),
        )
        storage.run_retention_pass(
            now=datetime.now(UTC),
            retention_policy=policy,
            batch_size=100,
        )
        assert storage.list_memory_flags(memory.id) == []


class TestFlagE2EFlow:
    """End-to-end: ingest → query (memory injected) → flag → query again (memory gone)."""

    def _make_client(self, monkeypatch, test_db_url: str):
        from tests.agent_conversation_replay_helpers import _agent_conversation_client
        return _agent_conversation_client(monkeypatch, test_db_url)

    def test_flagged_memory_stops_being_injected(self, monkeypatch, tmp_path):
        test_db_url = f"sqlite:///{tmp_path / 'e2e_flag.db'}"
        client = self._make_client(monkeypatch, test_db_url)

        client.post("/items", json=[{
            "source_type": "assistant_artifact",
            "source_id": "e2e-bad-decision-1",
            "content_type": "text/plain",
            "content": "Decision: use PostgreSQL for the catalog service instead of MongoDB.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": "chat:e2e",
            "thread_ref": "chat:e2e:thread-1",
        }])

        query_payload = {
            "text": "what did we decide about the catalog database?",
            "limit": 5,
            "container_ref": "chat:e2e",
            "runtime_context": {
                "turn_kind": "resumed_session",
                "session_has_sufficient_local_context": False,
            },
        }
        resp1 = client.post("/query/debug", json=query_payload)
        assert resp1.status_code == 200
        payload1 = resp1.json()
        assert payload1["results"], "expected at least one result before flagging"
        injected_ids_before = {
            b["memory_object_id"]
            for b in payload1.get("injectable_blocks", [])
            if b.get("memory_object_id")
        }
        result_memory_ids = {
            r["memory_object_id"]
            for r in payload1["results"]
            if r.get("memory_object_id")
        }
        target_ids = injected_ids_before or result_memory_ids
        assert target_ids, "expected at least one memory object in results"

        for memory_id in target_ids:
            flag_resp = client.post(
                f"/memory/{memory_id}/flag",
                json={
                    "reason": "wrong database recommendation — we decided on CockroachDB, not PostgreSQL",
                    "source_ref": "triage-review:e2e-test",
                    "immediate": True,
                },
            )
            assert flag_resp.status_code == 200
            assert flag_resp.json()["suppressed"] is True

        resp2 = client.post("/query/debug", json=query_payload)
        assert resp2.status_code == 200
        payload2 = resp2.json()
        suppressed_ids_in_results = {
            r["memory_object_id"]
            for r in payload2["results"]
            if r.get("memory_object_id") and r["memory_object_id"] in target_ids
        }
        assert suppressed_ids_in_results == set(), (
            f"suppressed memories still appearing in results: {suppressed_ids_in_results}"
        )
        injected_ids_after = {
            b["memory_object_id"]
            for b in payload2.get("injectable_blocks", [])
            if b.get("memory_object_id") and b["memory_object_id"] in target_ids
        }
        assert injected_ids_after == set(), (
            f"suppressed memories still in injectable_blocks: {injected_ids_after}"
        )

    def test_threshold_flag_flow_across_sessions(self, monkeypatch, tmp_path):
        """Two independent sessions flag the same memory → suppressed on second flag."""
        test_db_url = f"sqlite:///{tmp_path / 'e2e_threshold.db'}"
        client = self._make_client(monkeypatch, test_db_url)

        client.post("/items", json=[{
            "source_type": "assistant_artifact",
            "source_id": "e2e-stale-decision-1",
            "content_type": "text/plain",
            "content": "Decision: deploy the catalog service to staging on Friday.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": "chat:e2e2",
            "thread_ref": "chat:e2e2:thread-1",
        }])

        query_payload = {
            "text": "what did we decide about catalog deployment?",
            "limit": 5,
            "container_ref": "chat:e2e2",
            "runtime_context": {
                "turn_kind": "resumed_session",
                "session_has_sufficient_local_context": False,
            },
        }
        resp = client.post("/query/debug", json=query_payload)
        memory_ids = {
            r["memory_object_id"]
            for r in resp.json()["results"]
            if r.get("memory_object_id")
        }
        assert memory_ids, "expected at least one memory"
        target_id = next(iter(memory_ids))

        flag1 = client.post(f"/memory/{target_id}/flag", json={
            "reason": "outdated — deployment moved to Monday",
            "source_ref": "agent-session:monday-session",
        })
        assert flag1.status_code == 200
        assert flag1.json()["suppressed"] is False

        resp_mid = client.post("/query/debug", json=query_payload)
        mid_memory_ids = {
            r["memory_object_id"]
            for r in resp_mid.json()["results"]
            if r.get("memory_object_id")
        }
        assert target_id in mid_memory_ids, "memory should still appear after 1 flag"

        flag2 = client.post(f"/memory/{target_id}/flag", json={
            "reason": "still outdated — confirmed deployment was Monday",
            "source_ref": "agent-session:tuesday-session",
        })
        assert flag2.status_code == 200
        assert flag2.json()["suppressed"] is True

        resp_after = client.post("/query/debug", json=query_payload)
        after_memory_ids = {
            r["memory_object_id"]
            for r in resp_after.json()["results"]
            if r.get("memory_object_id")
        }
        assert target_id not in after_memory_ids, "memory should be gone after 2 flags from different sessions"
