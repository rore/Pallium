from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import AppConfig, ObservabilityConfig
from app.main import create_app
from core.models import EvidenceReference, InjectableBlock, QueryResultItem
from core.service import PalliumService
from retrieval.lexical import LexicalRetrievalProvider
from semantic.demo_agent_memory import DemoAgentMemoryPlugin
from storage.sqlite import SQLiteStorageProvider
from storage.vector_index import VectorIndexConfig


def _build_service(
    test_db_url: str,
    *,
    storage: SQLiteStorageProvider | None = None,
) -> PalliumService:
    storage = storage or SQLiteStorageProvider(test_db_url)
    retrieval = LexicalRetrievalProvider(storage)
    plugins = {"demo_agent_memory": DemoAgentMemoryPlugin()}
    return PalliumService(
        storage=storage,
        retrieval=retrieval,
        semantic_plugins=plugins,
        default_use_case="demo_agent_memory",
    )


def _make_client(test_db_url: str, *, audit_log_enabled: bool = False) -> TestClient:
    app = create_app(AppConfig(
        storage_backend="sqlite",
        sqlite_url=test_db_url,
        default_use_case="demo_agent_memory",
        vector_index=VectorIndexConfig(enabled=False),
        observability=ObservabilityConfig(query_audit_log=audit_log_enabled),
    ))
    return TestClient(app)


def _item_and_query_payload(**overrides) -> dict:
    base = {
        "source_type": "chat_message",
        "source_id": "test:msg:1",
        "content_type": "text/plain",
        "content": "What database should I use for the project?",
        "container_ref": "test:channel:1",
        "thread_ref": "test:thread:1",
        "actor_ref": "test:user:1",
        "visibility": "private",
        "query_limit": 5,
    }
    base.update(overrides)
    return base


# ── Test 1: schema creates audit table ──────────────────────────────────

def test_schema_creates_audit_table(test_db_url: str) -> None:
    storage = SQLiteStorageProvider(test_db_url)
    with storage._engine.begin() as connection:
        rows = connection.execute(text("PRAGMA table_info(query_audit_log)")).fetchall()
    column_names = {row[1] for row in rows}
    assert "id" in column_names
    assert "created_at" in column_names
    assert "source_item_id" in column_names
    assert "query_text" in column_names
    assert "should_inject" in column_names
    assert "injected_blocks_json" in column_names


# ── Test 2: write and read back a row ────────────────────────────────────

def test_write_audit_row_basic(test_db_url: str) -> None:
    from datetime import datetime, timezone

    storage = SQLiteStorageProvider(test_db_url)
    row = {
        "id": "audit-001",
        "created_at": datetime.now(timezone.utc),
        "source_item_id": "si-001",
        "source_id": "chat:msg:1",
        "thread_ref": "thread:1",
        "container_ref": "container:1",
        "actor_ref": "user:1",
        "visibility": "private",
        "query_text": "What database?",
        "should_inject": 1,
        "decision_reason": "carry_forward_available",
        "injected_blocks_json": "[]",
    }
    storage.write_query_audit_row(row)

    with storage._engine.begin() as connection:
        result = connection.execute(
            text("SELECT * FROM query_audit_log WHERE id = :id"),
            {"id": "audit-001"},
        ).fetchone()

    assert result is not None
    # Access by index: id is column 0
    assert result[0] == "audit-001"
    # source_item_id is column 2
    assert result[2] == "si-001"


# ── Test 3: nullable fields ─────────────────────────────────────────────

def test_write_audit_row_nullable_fields(test_db_url: str) -> None:
    from datetime import datetime, timezone

    storage = SQLiteStorageProvider(test_db_url)
    row = {
        "id": "audit-002",
        "created_at": datetime.now(timezone.utc),
        "source_item_id": "si-002",
        "source_id": "chat:msg:2",
        "thread_ref": None,
        "container_ref": None,
        "actor_ref": None,
        "visibility": None,
        "query_text": "Hello",
        "should_inject": 0,
        "decision_reason": "no_relevant_memory",
        "injected_blocks_json": "[]",
    }
    storage.write_query_audit_row(row)

    with storage._engine.begin() as connection:
        result = connection.execute(
            text("SELECT * FROM query_audit_log WHERE id = :id"),
            {"id": "audit-002"},
        ).fetchone()

    assert result is not None


# ── Test 4: service write_query_audit ────────────────────────────────────

def test_service_write_query_audit(test_db_url: str) -> None:
    service = _build_service(test_db_url)
    service.write_query_audit(
        source_item_id="si-100",
        source_id="chat:msg:100",
        thread_ref="thread:100",
        container_ref="container:100",
        actor_ref="user:100",
        visibility="private",
        query_text="test query",
        should_inject=False,
        decision_reason="no_relevant_memory",
        injectable_blocks=[],
        results=[],
    )

    with service._storage._engine.begin() as connection:
        rows = connection.execute(
            text("SELECT * FROM query_audit_log")
        ).fetchall()

    assert len(rows) == 1
    row = rows[0]
    # source_item_id is column 2
    assert row[2] == "si-100"


# ── Test 5: enriches blocks with result data ─────────────────────────────

def test_service_write_query_audit_enriches_blocks(test_db_url: str) -> None:
    service = _build_service(test_db_url)

    block = InjectableBlock(
        result_id="memory_object:mo-1",
        block_type="structured_recall",
        title="Database choice: PostgreSQL",
        text="We decided on PostgreSQL.",
        evidence=[],
        memory_type="decision",
    )
    result_item = QueryResultItem(
        result_id="memory_object:mo-1",
        result_kind="memory_object",
        score=0.87,
        evidence=[],
        memory_object_id="mo-1",
        retrieval_source="both",
    )

    service.write_query_audit(
        source_item_id="si-200",
        source_id="chat:msg:200",
        thread_ref="thread:200",
        container_ref="container:200",
        actor_ref="user:200",
        visibility="private",
        query_text="which database?",
        should_inject=True,
        decision_reason="carry_forward_available",
        injectable_blocks=[block],
        results=[result_item],
    )

    with service._storage._engine.begin() as connection:
        rows = connection.execute(
            text("SELECT injected_blocks_json FROM query_audit_log")
        ).fetchall()

    assert len(rows) == 1
    blocks_data = json.loads(rows[0][0])
    assert len(blocks_data) == 1
    entry = blocks_data[0]
    assert entry["result_id"] == "memory_object:mo-1"
    assert entry["memory_type"] == "decision"
    assert entry["block_type"] == "structured_recall"
    assert entry["score"] == 0.87
    assert entry["retrieval_source"] == "both"
    assert entry["memory_object_id"] == "mo-1"
    assert entry["title_preview"] == "Database choice: PostgreSQL"


# ── Test 6: empty blocks ────────────────────────────────────────────────

def test_service_write_query_audit_empty_blocks(test_db_url: str) -> None:
    service = _build_service(test_db_url)

    service.write_query_audit(
        source_item_id="si-300",
        source_id="chat:msg:300",
        thread_ref=None,
        container_ref=None,
        actor_ref=None,
        visibility=None,
        query_text="hello",
        should_inject=False,
        decision_reason="no_relevant_memory",
        injectable_blocks=[],
        results=[],
    )

    with service._storage._engine.begin() as connection:
        rows = connection.execute(
            text("SELECT injected_blocks_json FROM query_audit_log")
        ).fetchall()

    assert len(rows) == 1
    assert rows[0][0] == "[]"


# ── Test 7: item-and-query writes audit when enabled ─────────────────────

def test_item_and_query_writes_audit_when_enabled(test_db_url: str) -> None:
    client = _make_client(test_db_url, audit_log_enabled=True)
    response = client.post("/item-and-query", json=_item_and_query_payload())
    assert response.status_code == 200

    storage = client.app.state.pallium_service._storage
    with storage._engine.begin() as connection:
        rows = connection.execute(
            text("SELECT * FROM query_audit_log")
        ).fetchall()

    assert len(rows) == 1


# ── Test 8: item-and-query skips audit when disabled ─────────────────────

def test_item_and_query_skips_audit_when_disabled(test_db_url: str) -> None:
    client = _make_client(test_db_url, audit_log_enabled=False)
    response = client.post("/item-and-query", json=_item_and_query_payload())
    assert response.status_code == 200

    storage = client.app.state.pallium_service._storage
    with storage._engine.begin() as connection:
        rows = connection.execute(
            text("SELECT * FROM query_audit_log")
        ).fetchall()

    assert len(rows) == 0


# ── Test 9: audit write failure does not break query ─────────────────────

def test_audit_write_failure_does_not_break_query(test_db_url: str, monkeypatch) -> None:
    client = _make_client(test_db_url, audit_log_enabled=True)
    storage = client.app.state.pallium_service._storage

    def _raise(*args, **kwargs):
        raise RuntimeError("simulated audit write failure")

    monkeypatch.setattr(storage, "write_query_audit_row", _raise)

    response = client.post("/item-and-query", json=_item_and_query_payload())
    assert response.status_code == 200


# ── Test 10: config default is False ─────────────────────────────────────

def test_config_query_audit_log_default_false() -> None:
    config = ObservabilityConfig()
    assert config.query_audit_log is False


# ── Test 11: config from env var ─────────────────────────────────────────

def test_config_query_audit_log_from_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PALLIUM_OBSERVABILITY_QUERY_AUDIT_LOG", "true")
    # Ensure no config file is read
    monkeypatch.setenv("PALLIUM_CONFIG_FILE", str(tmp_path / "nonexistent.toml"))
    monkeypatch.setenv("PALLIUM_ENV_FILE", str(tmp_path / "nonexistent.env"))
    config = AppConfig.from_env()
    assert config.observability.query_audit_log is True
