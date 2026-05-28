"""Tests for orientation-recency endpoint (mitigation A).

Covers:
- Storage layer: list_recent_memory_objects
- Service layer: get_recent_orientation_blocks
- Route layer: GET /memory-objects/recent + audit log row
- End-to-end: route response shape matches format_injection contract
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from core.models import MemoryObject


CONTAINER = "test:container:orientation"


def _checkpoint(
    *,
    container_ref: str = CONTAINER,
    task: str = "Investigate retrieval",
    summary: str = "Working on retrieval quality",
    blocker: str = "",
    next_step: str = "Run pytest",
    findings: list[str] | None = None,
    freshness_at: datetime | None = None,
    visibility: str = "private",
    lifecycle: str = "active",
) -> MemoryObject:
    return MemoryObject(
        type="task_checkpoint",
        schema_id="test.task_checkpoint",
        schema_version="v1",
        payload={
            "task": task,
            "summary": summary,
            "blocker_state": blocker,
            "current_state": "",
            "next_step": next_step,
            "key_findings": findings or [],
            "evidence": [],
            "freshness_signal": "synthetic",
        },
        visibility=visibility,
        container_ref=container_ref,
        lifecycle=lifecycle,
        freshness_at=freshness_at or datetime.now(timezone.utc),
    )


def _trace(
    *,
    container_ref: str = CONTAINER,
    subject: str = "indexing",
    outcome: str = "verified",
    files: list[str] | None = None,
    freshness_at: datetime | None = None,
) -> MemoryObject:
    return MemoryObject(
        type="task_trace",
        schema_id="test.task_trace",
        schema_version="v1",
        payload={
            "investigation_subject": subject,
            "outcome": outcome,
            "exploratory_files": files or [],
            "files_modified": [],
            "commands_succeeded": [],
            "commands_failed": [],
        },
        visibility="private",
        container_ref=container_ref,
        freshness_at=freshness_at or datetime.now(timezone.utc),
    )


# ─── Storage layer ──────────────────────────────────────────────────────


def test_storage_list_recent_filters_by_type_and_container(client: TestClient) -> None:
    storage = client.app.state.pallium_service._storage
    storage.create_memory_object(_checkpoint(task="A"))
    storage.create_memory_object(_checkpoint(container_ref="other:container", task="B"))
    storage.create_memory_object(_trace(subject="X"))

    rows = storage.list_recent_memory_objects(
        container_ref=CONTAINER,
        memory_types=["task_checkpoint"],
        since=datetime.now(timezone.utc) - timedelta(days=14),
        limit=5,
    )
    assert len(rows) == 1
    assert rows[0].payload["task"] == "A"


def test_storage_list_recent_orders_by_freshness_desc(client: TestClient) -> None:
    storage = client.app.state.pallium_service._storage
    older = _checkpoint(task="older", freshness_at=datetime.now(timezone.utc) - timedelta(days=3))
    newer = _checkpoint(task="newer", freshness_at=datetime.now(timezone.utc) - timedelta(hours=1))
    storage.create_memory_object(older)
    storage.create_memory_object(newer)

    rows = storage.list_recent_memory_objects(
        container_ref=CONTAINER,
        memory_types=["task_checkpoint"],
        since=datetime.now(timezone.utc) - timedelta(days=14),
        limit=5,
    )
    assert [r.payload["task"] for r in rows] == ["newer", "older"]


def test_storage_list_recent_respects_since_cutoff(client: TestClient) -> None:
    storage = client.app.state.pallium_service._storage
    stale = _checkpoint(task="stale", freshness_at=datetime.now(timezone.utc) - timedelta(days=30))
    fresh = _checkpoint(task="fresh", freshness_at=datetime.now(timezone.utc) - timedelta(days=2))
    storage.create_memory_object(stale)
    storage.create_memory_object(fresh)

    rows = storage.list_recent_memory_objects(
        container_ref=CONTAINER,
        memory_types=["task_checkpoint"],
        since=datetime.now(timezone.utc) - timedelta(days=14),
        limit=5,
    )
    tasks = [r.payload["task"] for r in rows]
    assert "fresh" in tasks
    assert "stale" not in tasks


def test_storage_list_recent_excludes_suppressed(client: TestClient) -> None:
    storage = client.app.state.pallium_service._storage
    active = _checkpoint(task="active")
    suppressed = _checkpoint(task="suppressed", lifecycle="suppressed")
    storage.create_memory_object(active)
    storage.create_memory_object(suppressed)

    rows = storage.list_recent_memory_objects(
        container_ref=CONTAINER,
        memory_types=["task_checkpoint"],
        since=datetime.now(timezone.utc) - timedelta(days=14),
        limit=5,
    )
    tasks = [r.payload["task"] for r in rows]
    assert tasks == ["active"]


def test_storage_list_recent_supports_multi_type(client: TestClient) -> None:
    storage = client.app.state.pallium_service._storage
    storage.create_memory_object(_checkpoint(task="cp"))
    storage.create_memory_object(_trace(subject="trace_subject"))

    rows = storage.list_recent_memory_objects(
        container_ref=CONTAINER,
        memory_types=["task_checkpoint", "task_trace"],
        since=datetime.now(timezone.utc) - timedelta(days=14),
        limit=5,
    )
    types = sorted(r.type for r in rows)
    assert types == ["task_checkpoint", "task_trace"]


def test_storage_list_recent_empty_types_returns_empty(client: TestClient) -> None:
    storage = client.app.state.pallium_service._storage
    rows = storage.list_recent_memory_objects(
        container_ref=CONTAINER,
        memory_types=[],
        since=datetime.now(timezone.utc) - timedelta(days=14),
        limit=5,
    )
    assert rows == []


# ─── Service layer ──────────────────────────────────────────────────────


def test_service_orientation_blocks_for_task_checkpoint(client: TestClient) -> None:
    service = client.app.state.pallium_service
    cp = _checkpoint(task="Resume retrieval work", findings=["found A", "found B"])
    service._storage.create_memory_object(cp)

    blocks = service.get_recent_orientation_blocks(
        container_ref=CONTAINER,
        memory_types=["task_checkpoint"],
        since_days=14,
        limit=1,
    )
    assert len(blocks) == 1
    block = blocks[0]
    assert block["memory_type"] == "task_checkpoint"
    assert block["title"] == "Task Checkpoint — Resume retrieval work"
    assert "Working on retrieval quality" in block["text"] or "Run pytest" in block["text"]
    assert block["memory_object_id"] == cp.id
    assert block["block_type"] == "memory"
    assert block["expand_available"] is False


def test_service_orientation_blocks_for_task_trace(client: TestClient) -> None:
    service = client.app.state.pallium_service
    trace = _trace(subject="retrieval", outcome="confirmed", files=["a.py", "b.py"])
    service._storage.create_memory_object(trace)

    blocks = service.get_recent_orientation_blocks(
        container_ref=CONTAINER,
        memory_types=["task_trace"],
        since_days=14,
        limit=1,
    )
    assert len(blocks) == 1
    block = blocks[0]
    assert block["memory_type"] == "task_trace"
    assert block["title"] == "Task Trace"
    assert "retrieval" in block["text"]
    assert "confirmed" in block["text"]


def test_service_orientation_returns_empty_when_no_match(client: TestClient) -> None:
    service = client.app.state.pallium_service
    blocks = service.get_recent_orientation_blocks(
        container_ref=CONTAINER,
        memory_types=["task_checkpoint", "task_trace"],
        since_days=14,
        limit=1,
    )
    assert blocks == []


# ─── Route layer ────────────────────────────────────────────────────────


def test_route_recent_returns_block_when_checkpoint_exists(client: TestClient) -> None:
    storage = client.app.state.pallium_service._storage
    storage.create_memory_object(_checkpoint(task="ship A"))

    response = client.get(
        "/memory-objects/recent",
        params=[
            ("container_ref", CONTAINER),
            ("types", "task_checkpoint"),
            ("limit", 1),
            ("since_days", 14),
        ],
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["blocks"]) == 1
    assert body["blocks"][0]["memory_type"] == "task_checkpoint"
    assert "ship A" in body["blocks"][0]["title"]


def test_route_recent_returns_empty_when_no_match(client: TestClient) -> None:
    response = client.get(
        "/memory-objects/recent",
        params=[
            ("container_ref", CONTAINER),
            ("types", "task_checkpoint"),
            ("types", "task_trace"),
            ("limit", 1),
            ("since_days", 14),
        ],
    )
    assert response.status_code == 200
    assert response.json()["blocks"] == []


def test_route_recent_validates_limit_bounds(client: TestClient) -> None:
    response = client.get(
        "/memory-objects/recent",
        params=[("container_ref", CONTAINER), ("types", "task_checkpoint"), ("limit", 99)],
    )
    assert response.status_code == 400


def test_route_recent_validates_since_days_bounds(client: TestClient) -> None:
    response = client.get(
        "/memory-objects/recent",
        params=[("container_ref", CONTAINER), ("types", "task_checkpoint"), ("since_days", 0)],
    )
    assert response.status_code == 400


def test_route_recent_rejects_non_private_visibility(client: TestClient) -> None:
    response = client.get(
        "/memory-objects/recent",
        params=[
            ("container_ref", CONTAINER),
            ("types", "task_checkpoint"),
            ("visibility", "public"),
        ],
    )
    assert response.status_code == 400


def test_route_recent_response_shape_matches_format_injection_contract(
    client: TestClient,
) -> None:
    """The four fields format_injection reads must be present."""
    storage = client.app.state.pallium_service._storage
    storage.create_memory_object(_checkpoint(task="format-test"))

    response = client.get(
        "/memory-objects/recent",
        params=[("container_ref", CONTAINER), ("types", "task_checkpoint")],
    )
    body = response.json()
    block = body["blocks"][0]
    for required_key in ("title", "memory_object_id", "text", "expand_available"):
        assert required_key in block, f"format_injection requires '{required_key}'"


# ─── Audit logging ──────────────────────────────────────────────────────


def test_route_recent_writes_audit_row_when_audit_enabled(tmp_path) -> None:
    from app.config import AppConfig, ObservabilityConfig
    from app.main import create_app
    from storage.vector_index import VectorIndexConfig
    from tests.config_helpers import DEMO_SEMANTIC_PACKAGES

    db_path = tmp_path / "audit.db"
    app = create_app(
        AppConfig(
            storage_backend="sqlite",
            sqlite_url=f"sqlite:///{db_path}",
            default_use_case="demo_agent_memory",
            semantic_packages=DEMO_SEMANTIC_PACKAGES,
            vector_index=VectorIndexConfig(enabled=False),
            observability=ObservabilityConfig(query_audit_log=True),
        )
    )
    audited_client = TestClient(app)
    storage = audited_client.app.state.pallium_service._storage
    storage.create_memory_object(_checkpoint(task="audit-target"))

    response = audited_client.get(
        "/memory-objects/recent",
        params=[("container_ref", CONTAINER), ("types", "task_checkpoint"), ("actor_ref", "alice")],
    )
    assert response.status_code == 200

    from sqlalchemy import select

    from storage.sqlite_schema import QueryAuditLogRecord

    with storage._session_factory() as session:
        rows = session.scalars(select(QueryAuditLogRecord)).all()
        orientation_rows = [r for r in rows if r.injection_method == "orientation_recency"]

    assert len(orientation_rows) == 1
    row = orientation_rows[0]
    assert row.container_ref == CONTAINER
    assert row.actor_ref == "alice"
    assert row.should_inject == 1
    assert row.decision_reason == "orientation_recency"
    assert row.source_item_id == "orientation_recency"
    assert row.source_id == "orientation_recency"
    blocks = json.loads(row.injected_blocks_json)
    assert len(blocks) == 1
    assert blocks[0]["memory_type"] == "task_checkpoint"


def test_route_recent_audit_row_records_zero_inject_when_empty(tmp_path) -> None:
    from app.config import AppConfig, ObservabilityConfig
    from app.main import create_app
    from storage.vector_index import VectorIndexConfig
    from tests.config_helpers import DEMO_SEMANTIC_PACKAGES

    db_path = tmp_path / "audit_empty.db"
    app = create_app(
        AppConfig(
            storage_backend="sqlite",
            sqlite_url=f"sqlite:///{db_path}",
            default_use_case="demo_agent_memory",
            semantic_packages=DEMO_SEMANTIC_PACKAGES,
            vector_index=VectorIndexConfig(enabled=False),
            observability=ObservabilityConfig(query_audit_log=True),
        )
    )
    audited_client = TestClient(app)
    storage = audited_client.app.state.pallium_service._storage

    response = audited_client.get(
        "/memory-objects/recent",
        params=[("container_ref", CONTAINER), ("types", "task_checkpoint")],
    )
    assert response.status_code == 200

    from sqlalchemy import select

    from storage.sqlite_schema import QueryAuditLogRecord

    with storage._session_factory() as session:
        rows = session.scalars(select(QueryAuditLogRecord)).all()
        orientation_rows = [r for r in rows if r.injection_method == "orientation_recency"]
    assert len(orientation_rows) == 1
    assert orientation_rows[0].should_inject == 0


# ─── Drift guard: orientation block matches routing-side builder ────────


def test_orientation_task_checkpoint_text_matches_routing_builder() -> None:
    """If routing's text-builder changes, this test will break — drift detector."""
    from core.service import _orientation_task_checkpoint_text
    from semantic.agent_conversation_memory_routing_selection import (
        _task_checkpoint_injection_text,
    )

    payload = {
        "summary": "Working through extraction gap",
        "current_state": "BM25 floor lifted",
        "blocker_state": "Awaiting consolidation tests",
        "next_step": "Run regression suite",
        "key_findings": ["A", "B", "C", "D"],
    }
    assert _orientation_task_checkpoint_text(payload) == _task_checkpoint_injection_text(payload)


def test_orientation_task_trace_text_matches_routing_builder() -> None:
    """Drift detector: orientation block text must match routing-side task_trace builder."""
    from core.service import _orientation_task_trace_text
    from semantic.agent_conversation_memory_routing_selection import _build_raw_injectable_block
    from core.models import QueryResultItem

    payload = {
        "investigation_subject": "indexing",
        "outcome": "verified",
        "exploratory_files": ["a.py", "b.py", "c.py", "d.py", "e.py", "f.py"],
        "files_modified": ["m1.py", "m2.py", "m3.py", "m4.py"],
        "commands_succeeded": ["pytest tests/some_long_test_module_name_that_exceeds_sixty_characters.py"],
        "commands_failed": ["mypy core/"],
    }
    item = QueryResultItem(
        result_id="rid",
        result_kind="memory",
        type="task_trace",
        memory_object_id="moid",
        score=0.0,
        excerpt=None,
        evidence=[],
        payload=payload,
    )
    routing_block = _build_raw_injectable_block({"item": item}, intent="orientation")
    orientation_text = _orientation_task_trace_text(payload)
    assert orientation_text == routing_block.text
    assert routing_block.title == "Task Trace"


# ─── Audit candidate snapshot (Goal B) ──────────────────────────────────


def _audited_client(tmp_path, db_name: str) -> TestClient:
    """Build a TestClient with query_audit_log enabled, isolated SQLite DB."""
    from app.config import AppConfig, ObservabilityConfig
    from app.main import create_app
    from storage.vector_index import VectorIndexConfig
    from tests.config_helpers import DEMO_SEMANTIC_PACKAGES

    db_path = tmp_path / db_name
    app = create_app(
        AppConfig(
            storage_backend="sqlite",
            sqlite_url=f"sqlite:///{db_path}",
            default_use_case="demo_agent_memory",
            semantic_packages=DEMO_SEMANTIC_PACKAGES,
            vector_index=VectorIndexConfig(enabled=False),
            observability=ObservabilityConfig(query_audit_log=True),
        )
    )
    return TestClient(app)


def _orientation_audit_rows(client: TestClient):
    from sqlalchemy import select

    from storage.sqlite_schema import QueryAuditLogRecord

    storage = client.app.state.pallium_service._storage
    with storage._session_factory() as session:
        rows = session.scalars(select(QueryAuditLogRecord)).all()
        return [r for r in rows if r.injection_method == "orientation_recency"]


def test_orientation_recency_audit_records_candidates(tmp_path) -> None:
    """One typed memory available → audit row carries one candidate snapshot entry."""
    audited = _audited_client(tmp_path, "audit_b1.db")
    storage = audited.app.state.pallium_service._storage
    cp = _checkpoint(task="capture me")
    storage.create_memory_object(cp)

    response = audited.get(
        "/memory-objects/recent",
        params=[("container_ref", CONTAINER), ("types", "task_checkpoint")],
    )
    assert response.status_code == 200

    rows = _orientation_audit_rows(audited)
    assert len(rows) == 1
    row = rows[0]
    assert row.candidate_scores_json is not None
    snapshot = json.loads(row.candidate_scores_json)
    assert isinstance(snapshot, list)
    assert len(snapshot) == 1
    entry = snapshot[0]
    assert entry["memory_object_id"] == cp.id
    assert entry["memory_type"] == "task_checkpoint"
    assert entry["routing_rank"] == 1
    assert entry["layer"] == "orientation_recency"
    assert entry["injected"] is True
    for nullable_field in (
        "routing_score",
        "lexical_score",
        "vector_score",
        "support_grade",
        "suppression_reason_code",
        "excluded_reason_code",
        "post_routing_drop_reason",
    ):
        assert entry[nullable_field] is None


def test_orientation_recency_audit_with_no_results(tmp_path) -> None:
    """No matching memories → candidate_scores_json is the JSON literal "[]" (not None)."""
    audited = _audited_client(tmp_path, "audit_b2.db")

    response = audited.get(
        "/memory-objects/recent",
        params=[("container_ref", CONTAINER), ("types", "task_checkpoint")],
    )
    assert response.status_code == 200

    rows = _orientation_audit_rows(audited)
    assert len(rows) == 1
    row = rows[0]
    # Architect-approved: write "[]" (empty JSON array), not NULL.
    # Disambiguates "no candidates considered" from rows that predate this
    # instrumentation (those carry NULL).
    assert row.candidate_scores_json == "[]"
    assert json.loads(row.candidate_scores_json) == []


def test_orientation_recency_audit_with_multiple_records(tmp_path) -> None:
    """Three matching memories, limit=2 → snapshot has 2 entries with ranks 1 and 2."""
    audited = _audited_client(tmp_path, "audit_b3.db")
    storage = audited.app.state.pallium_service._storage
    older = _checkpoint(
        task="oldest",
        freshness_at=datetime.now(timezone.utc) - timedelta(days=3),
    )
    middle = _checkpoint(
        task="middle",
        freshness_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    newest = _checkpoint(
        task="newest",
        freshness_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    for cp in (older, middle, newest):
        storage.create_memory_object(cp)

    response = audited.get(
        "/memory-objects/recent",
        params=[
            ("container_ref", CONTAINER),
            ("types", "task_checkpoint"),
            ("limit", 2),
        ],
    )
    assert response.status_code == 200

    rows = _orientation_audit_rows(audited)
    assert len(rows) == 1
    snapshot = json.loads(rows[0].candidate_scores_json)
    assert len(snapshot) == 2
    assert snapshot[0]["memory_object_id"] == newest.id
    assert snapshot[0]["routing_rank"] == 1
    assert snapshot[0]["injected"] is True
    assert snapshot[1]["memory_object_id"] == middle.id
    assert snapshot[1]["routing_rank"] == 2
    assert snapshot[1]["injected"] is True


def test_orientation_recency_audit_legacy_null_handling(tmp_path) -> None:
    """A row with candidate_scores_json=NULL (predates instrumentation) reads back fine."""
    import uuid as _uuid
    from datetime import datetime as _datetime, timezone as _timezone

    from sqlalchemy import select

    from storage.sqlite_schema import QueryAuditLogRecord

    audited = _audited_client(tmp_path, "audit_b4.db")
    storage = audited.app.state.pallium_service._storage

    # Manually insert a legacy-shaped row with NULL candidate_scores_json.
    legacy_id = str(_uuid.uuid4())
    with storage._session_factory() as session:
        session.add(
            QueryAuditLogRecord(
                id=legacy_id,
                created_at=_datetime.now(_timezone.utc),
                source_item_id="orientation_recency",
                source_id="orientation_recency",
                thread_ref=None,
                container_ref=CONTAINER,
                actor_ref=None,
                visibility="private",
                query_text="[orientation_recency types=task_checkpoint]",
                should_inject=0,
                decision_reason="orientation_recency",
                injected_blocks_json="[]",
                candidate_scores_json=None,
                injection_method="orientation_recency",
            )
        )
        session.commit()

    # Read back: must not raise and the legacy row must be visible with NULL preserved.
    with storage._session_factory() as session:
        legacy = session.get(QueryAuditLogRecord, legacy_id)
    assert legacy is not None
    assert legacy.candidate_scores_json is None
    assert legacy.decision_reason == "orientation_recency"
