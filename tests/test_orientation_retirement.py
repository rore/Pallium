"""Retirement-regression tests for the orientation_recency layer.

The session-start `orientation_recency` injection was removed in
`fix/retire-orientation-recency`. These tests pin the retirement at
runtime:

- R1a: ``GET /memory-objects/recent`` returns 404 (route deleted).
- R1b: A session-start-equivalent ``POST /query`` does not produce any
  ``decision_reason='orientation_recency'`` row in ``query_audit_log``.
- R2:  The per-message retrieval path still surfaces a topical
  ``task_checkpoint`` when the user types something that lexically
  matches a stored checkpoint.
"""
from __future__ import annotations

from fastapi.testclient import TestClient


CONTAINER = "test:container:retirement"
RETRIEVAL_FALLBACK_QUERY = "recent decisions, progress, and open tasks"


def _audited_demo_client(tmp_path, db_name: str) -> TestClient:
    """Build a TestClient (demo_agent_memory) with query_audit_log enabled.

    Used by R1b to verify that a session-start-equivalent /query call
    produces no orientation_recency audit row. Mirrors the pattern that
    lived in tests/test_orientation_recency.py (now deleted).
    """
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


def _all_audit_rows(client: TestClient):
    from sqlalchemy import select

    from storage.sqlite_schema import QueryAuditLogRecord

    storage = client.app.state.pallium_service._storage
    with storage._session_factory() as session:
        return list(session.scalars(select(QueryAuditLogRecord)).all())


# ─── R1a — route is gone ────────────────────────────────────────────────


def test_recent_memory_objects_route_is_gone(client: TestClient) -> None:
    """Retirement guard: the GET /memory-objects/recent route was deleted in
    fix/retire-orientation-recency."""
    response = client.get(
        "/memory-objects/recent",
        params=[("container_ref", CONTAINER), ("types", "task_checkpoint")],
    )
    assert response.status_code == 404


# ─── R1b — no orientation_recency audit row on session-start /query ─────


def test_no_orientation_recency_audit_row_on_query(tmp_path) -> None:
    """Retirement guard: a session-start-equivalent /query call must not
    produce any decision_reason='orientation_recency' or
    injection_method='orientation_recency' row in query_audit_log."""
    audited = _audited_demo_client(tmp_path, "retirement_r1b.db")

    response = audited.post(
        "/query",
        json={
            "text": RETRIEVAL_FALLBACK_QUERY,
            "container_ref": CONTAINER,
            "actor_ref": "alice",
            "visibility": "private",
            "limit": 5,
        },
    )
    assert response.status_code == 200

    rows = _all_audit_rows(audited)
    assert all(row.decision_reason != "orientation_recency" for row in rows)
    assert all(row.injection_method != "orientation_recency" for row in rows)


# ─── R2 — per-message retrieval still surfaces a topical task_checkpoint ─


def test_per_message_retrieval_surfaces_task_checkpoint(monkeypatch, test_db_url: str) -> None:
    """Regression: removing orientation_recency must not break the per-message
    retrieval path's ability to surface a task_checkpoint when the user types
    something topical.

    Uses the agent_conversation_memory pipeline (the only package that produces
    injectable_blocks) with a stored task_checkpoint built from the standard
    resumption-work fixture, then issues a work_resumption-shaped /query and
    asserts a task_checkpoint block surfaces.
    """
    from tests.agent_conversation_replay_helpers import _agent_conversation_client
    from tests.agent_conversation_memory_routing_helpers import _ingest_resumption_work

    client = _agent_conversation_client(monkeypatch, test_db_url)
    _ingest_resumption_work(client, thread_ref="chat:library-help:thread-retirement-r2")

    response = client.post(
        "/query",
        json={
            "text": (
                "What blocker did we hit, what progress was preserved, and "
                "what should we do next on the catalog sync retry?"
            ),
            "limit": 6,
            "container_ref": "chat:library-help",
            "runtime_context": {
                "turn_kind": "resumed_session",
                "session_has_sufficient_local_context": False,
            },
        },
    )
    assert response.status_code == 200

    body = response.json()
    blocks = body.get("injectable_blocks") or []
    assert any(
        block.get("memory_type") == "task_checkpoint" for block in blocks
    ), (
        "Expected a task_checkpoint to surface in injectable_blocks for a "
        f"work_resumption-shaped /query; got {blocks!r}"
    )
