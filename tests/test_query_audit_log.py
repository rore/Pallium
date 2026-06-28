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
from tests.config_helpers import DEMO_SEMANTIC_PACKAGES


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
        semantic_packages=DEMO_SEMANTIC_PACKAGES,
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


# ── Test 12: candidate_scores_json is None when no snapshot passed ──────

def test_candidate_scores_json_none_when_no_snapshot(test_db_url: str) -> None:
    service = _build_service(test_db_url)
    service.write_query_audit(
        source_item_id="si-400",
        source_id="chat:msg:400",
        thread_ref="thread:400",
        container_ref="container:400",
        actor_ref="user:400",
        visibility="private",
        query_text="test query no candidates",
        should_inject=False,
        decision_reason="no_relevant_memory",
        injectable_blocks=[],
        results=[],
    )

    with service._storage._engine.begin() as connection:
        rows = connection.execute(
            text("SELECT candidate_scores_json FROM query_audit_log WHERE source_item_id = 'si-400'")
        ).fetchall()

    assert len(rows) == 1
    assert rows[0][0] is None


# ── Test 13: candidate_scores_json populated with correct structure ─────

def test_candidate_scores_json_populated(test_db_url: str) -> None:
    service = _build_service(test_db_url)

    block = InjectableBlock(
        result_id="memory_object:mo-10",
        block_type="structured_recall",
        title="Some memory",
        text="Memory text",
        evidence=[],
        memory_type="decision",
        memory_object_id="mo-10",
    )
    item1 = QueryResultItem(
        result_id="memory_object:mo-10",
        result_kind="memory_hit",
        score=0.9,
        evidence=[],
        memory_object_id="mo-10",
        type="decision",
        retrieval_source="both",
    )
    item2 = QueryResultItem(
        result_id="memory_object:mo-11",
        result_kind="memory_hit",
        score=0.5,
        evidence=[],
        memory_object_id="mo-11",
        type="atomic_fact",
    )

    ranked_candidates = [
        {
            "item": item1,
            "routing_score": 0.95,
            "lexical_score": 0.8,
            "vector_score": 12,
            "routing_rank": 1,
            "layer": "core",
            "support_grade": "strong",
            "suppression_reason_code": None,
        },
        {
            "item": item2,
            "routing_score": 0.4,
            "lexical_score": 0.3,
            "vector_score": 5,
            "routing_rank": 2,
            "layer": "supporting",
            "support_grade": "weak",
            "suppression_reason_code": "low_relevance",
        },
    ]

    service.write_query_audit(
        source_item_id="si-500",
        source_id="chat:msg:500",
        thread_ref="thread:500",
        container_ref="container:500",
        actor_ref="user:500",
        visibility="private",
        query_text="test query with candidates",
        should_inject=True,
        decision_reason="carry_forward_available",
        injectable_blocks=[block],
        results=[item1, item2],
        ranked_candidates=ranked_candidates,
    )

    with service._storage._engine.begin() as connection:
        rows = connection.execute(
            text("SELECT candidate_scores_json FROM query_audit_log WHERE source_item_id = 'si-500'")
        ).fetchall()

    assert len(rows) == 1
    scores = json.loads(rows[0][0])
    assert len(scores) == 2

    # First candidate
    assert scores[0]["memory_object_id"] == "mo-10"
    assert scores[0]["memory_type"] == "decision"
    assert scores[0]["routing_score"] == 0.95
    assert scores[0]["lexical_score"] == 0.8
    assert scores[0]["vector_score"] == 12
    assert scores[0]["routing_rank"] == 1
    assert scores[0]["layer"] == "core"
    assert scores[0]["support_grade"] == "strong"
    assert scores[0]["suppression_reason_code"] is None
    assert scores[0]["injected"] is True
    # Phase 0.5: result `score` (policy gate) + retrieval_source
    assert scores[0]["score"] == 0.9
    assert scores[0]["retrieval_source"] == "both"

    # Second candidate (not injected)
    assert scores[1]["memory_object_id"] == "mo-11"
    assert scores[1]["memory_type"] == "atomic_fact"
    assert scores[1]["routing_score"] == 0.4
    assert scores[1]["injected"] is False
    assert scores[1]["suppression_reason_code"] == "low_relevance"
    # Phase 0.5: retrieval_source defaults to None when unset
    assert scores[1]["score"] == 0.5
    assert scores[1]["retrieval_source"] is None


# ── Test 14: serialization failure does not break audit write ───────────

def test_candidate_scores_serialization_failure(test_db_url: str) -> None:
    service = _build_service(test_db_url)

    # Create a candidate with an item that has a non-serializable field
    item = QueryResultItem(
        result_id="memory_object:mo-bad",
        result_kind="memory_hit",
        score=0.5,
        evidence=[],
        memory_object_id="mo-bad",
        type="decision",
    )

    # Use a non-JSON-serializable value in the candidate dict to trigger failure
    class Unserializable:
        def __repr__(self):
            return "<Unserializable>"

    ranked_candidates = [
        {
            "item": item,
            "routing_score": Unserializable(),  # json.dumps will fail on this
            "lexical_score": 0.3,
            "vector_score": 5,
            "routing_rank": 1,
            "layer": "core",
            "support_grade": "strong",
            "suppression_reason_code": None,
        },
    ]

    # Should not raise
    service.write_query_audit(
        source_item_id="si-600",
        source_id="chat:msg:600",
        thread_ref="thread:600",
        container_ref="container:600",
        actor_ref="user:600",
        visibility="private",
        query_text="test query with bad candidate",
        should_inject=False,
        decision_reason="no_relevant_memory",
        injectable_blocks=[],
        results=[],
        ranked_candidates=ranked_candidates,
    )

    with service._storage._engine.begin() as connection:
        rows = connection.execute(
            text("SELECT candidate_scores_json FROM query_audit_log WHERE source_item_id = 'si-600'")
        ).fetchall()

    assert len(rows) == 1
    # Serialization failed, so it should be None
    assert rows[0][0] is None


# ── Test 15: schema migration adds candidate_scores_json column ─────────

def test_schema_has_candidate_scores_json_column(test_db_url: str) -> None:
    storage = SQLiteStorageProvider(test_db_url)
    with storage._engine.begin() as connection:
        rows = connection.execute(text("PRAGMA table_info(query_audit_log)")).fetchall()
    column_names = {row[1] for row in rows}
    assert "candidate_scores_json" in column_names


# ── Test 16: injection_method persists end-to-end ───────────────────────

def test_injection_method_persisted(test_db_url: str) -> None:
    service = _build_service(test_db_url)
    service.write_query_audit(
        source_item_id="si-700",
        source_id="chat:msg:700",
        thread_ref="thread:700",
        container_ref="container:700",
        actor_ref="user:700",
        visibility="private",
        query_text="test injection_method round-trip",
        should_inject=True,
        decision_reason="carry_forward_available",
        injectable_blocks=[],
        results=[],
        injection_method="simplified",
    )

    with service._storage._engine.begin() as connection:
        result = connection.execute(
            text("SELECT injection_method FROM query_audit_log WHERE source_item_id = :sid"),
            {"sid": "si-700"},
        ).mappings().fetchone()

    assert result is not None
    assert result["injection_method"] == "simplified"


# ── Test 17: injection_method NULL when not provided ────────────────────

def test_injection_method_null_when_omitted(test_db_url: str) -> None:
    service = _build_service(test_db_url)
    service.write_query_audit(
        source_item_id="si-701",
        source_id="chat:msg:701",
        thread_ref=None,
        container_ref=None,
        actor_ref=None,
        visibility=None,
        query_text="omitted injection_method",
        should_inject=False,
        decision_reason="no_relevant_memory",
        injectable_blocks=[],
        results=[],
    )

    with service._storage._engine.begin() as connection:
        result = connection.execute(
            text("SELECT injection_method FROM query_audit_log WHERE source_item_id = :sid"),
            {"sid": "si-701"},
        ).mappings().fetchone()

    assert result is not None
    assert result["injection_method"] is None


# ── Test 18: schema has injection_method column ─────────────────────────

def test_schema_has_injection_method_column(test_db_url: str) -> None:
    storage = SQLiteStorageProvider(test_db_url)
    with storage._engine.begin() as connection:
        rows = connection.execute(text("PRAGMA table_info(query_audit_log)")).fetchall()
    column_names = {row[1] for row in rows}
    assert "injection_method" in column_names


# ── Test 19: PackageQueryOutcome → QueryResult → audit chain ────────────

def test_injection_method_propagates_through_outcome_to_audit(test_db_url: str) -> None:
    """End-to-end contract: PackageQueryOutcome.injection_method must flow through
    QueryResult rebuild (core/query.py) and _maybe_write_query_audit (api/routes.py)
    into the persisted row. Catches typos like injection_summary.get("injection_methdo")."""
    from types import SimpleNamespace
    from api.routes import _maybe_write_query_audit
    from core.contracts import PackageQueryOutcome, QueryResult

    service = _build_service(test_db_url)
    outcome = PackageQueryOutcome(results=[], injection_method="simplified")
    # Mirror core/query.py rebuild (lines 163-172): PackageQueryOutcome → QueryResult
    query_result = QueryResult(
        results=outcome.results,
        trace=None,
        should_inject=outcome.should_inject,
        decision_reason=outcome.decision_reason,
        injectable_blocks=outcome.injectable_blocks,
        injection_method=outcome.injection_method,
    )
    request = SimpleNamespace(source_id="chat:msg:800", thread_ref=None,
        container_ref=None, query_actor_ref=None, visibility_kind=lambda: None)
    ingest_result = SimpleNamespace(source_item_id="si-800")
    _maybe_write_query_audit(service, True, ingest_result, request, "q", query_result)

    with service._storage._engine.begin() as connection:
        row = connection.execute(
            text("SELECT injection_method FROM query_audit_log WHERE source_item_id = :sid"),
            {"sid": "si-800"},
        ).mappings().fetchone()
    assert row is not None and row["injection_method"] == "simplified"


# ── Test 20: migrations are idempotent on re-init ───────────────────────

def test_query_audit_log_migrations_idempotent(test_db_url: str) -> None:
    SQLiteStorageProvider(test_db_url)
    # Re-init should not raise even though columns already exist
    storage = SQLiteStorageProvider(test_db_url)
    with storage._engine.begin() as connection:
        rows = connection.execute(text("PRAGMA table_info(query_audit_log)")).fetchall()
    column_names = {row[1] for row in rows}
    assert "injection_method" in column_names
    assert "candidate_scores_json" in column_names
