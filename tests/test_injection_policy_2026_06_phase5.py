"""Phase 5a tests — memory_usage_audit schema, service, and endpoints.

See: docs/specs/2026-06-27-injection-policy-abstention.md (Phase 5).

Phase 5a ships the Pallium-side surface:
- Schema (table + indexes, additive, fresh + existing DBs converge)
- Storage methods (write/list/update)
- Service-level integration (write rows alongside query_audit_log)
- GET/POST endpoints

Phase 5b (NOT in this commit) will add the integration-side populator
hook that observes the agent's next turns and POSTs to update rows.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from api.routes import create_router
from core.models import InjectableBlock
from core.service import PalliumService
from retrieval.lexical import LexicalRetrievalProvider
from semantic.demo_agent_memory import DemoAgentMemoryPlugin
from storage.sqlite import SQLiteStorageProvider


@pytest.fixture
def service_and_client(tmp_path):
    """Build a real PalliumService (demo plugin) plus an HTTP test client."""
    db_url = f"sqlite:///{tmp_path / 'pallium.db'}"
    storage = SQLiteStorageProvider(db_url)
    retrieval = LexicalRetrievalProvider(storage)
    plugins = {"demo_agent_memory": DemoAgentMemoryPlugin()}
    service = PalliumService(
        storage=storage,
        retrieval=retrieval,
        semantic_plugins=plugins,
        default_use_case="demo_agent_memory",
    )
    app = FastAPI()
    app.include_router(create_router(service, audit_log_enabled=True))
    client = TestClient(app)
    return service, client, tmp_path


def _write_query_with_blocks(
    service,
    *,
    audit_id: str | None = None,
    container_ref: str = "git:test",
    thread_ref: str | None = "thread-1",
    trigger_origin: str | None = None,
    blocks: list[dict] | None = None,
):
    """Write one audit row + its usage-audit rows by calling
    service.write_query_audit directly. Returns audit_id."""
    blocks = blocks or [
        {
            "memory_object_id": "m-decision-1",
            "memory_type": "decision",
            "block_type": "memory",
            "title_preview": "x",
            "score": 22,
            "retrieval_source": "vector",
        },
    ]
    # Build InjectableBlock proxies from the simple dicts so the audit
    # code path works the same as real production calls.
    inj = []
    for b in blocks:
        inj.append(InjectableBlock(
            result_id=f"memory_object:{b['memory_object_id']}",
            memory_object_id=b["memory_object_id"],
            block_type=b.get("block_type", "memory"),
            title="t",
            text="text",
            evidence=[],
            memory_type=b.get("memory_type"),
        ))
    service.write_query_audit(
        source_item_id=audit_id or f"si-{uuid.uuid4().hex[:8]}",
        source_id="src-1",
        thread_ref=thread_ref,
        container_ref=container_ref,
        actor_ref="user-1",
        visibility="private",
        query_text="test query",
        should_inject=True,
        decision_reason="carry_forward_available",
        injectable_blocks=inj,
        results=[],
        ranked_candidates=None,
        injection_method=None,
        trigger_origin=trigger_origin,
    )


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_schema_creates_memory_usage_audit_table(service_and_client):
    service, _client, db_path = service_and_client
    with service._storage._engine.begin() as connection:
        rows = connection.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='memory_usage_audit'"
        )).fetchall()
    assert len(rows) == 1


def test_schema_creates_indexes(service_and_client):
    service, _client, _db_path = service_and_client
    with service._storage._engine.begin() as connection:
        rows = connection.execute(text(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND tbl_name='memory_usage_audit'"
        )).fetchall()
    index_names = {r[0] for r in rows}
    assert "idx_memory_usage_audit_query_audit_log_id" in index_names
    assert "idx_memory_usage_audit_memory_object_id" in index_names
    assert "idx_memory_usage_audit_type_trigger" in index_names
    assert "idx_memory_usage_audit_pending" in index_names


# ---------------------------------------------------------------------------
# Service-level write
# ---------------------------------------------------------------------------


def test_write_query_audit_also_writes_usage_audit_rows(service_and_client):
    service, _client, _db_path = service_and_client
    _write_query_with_blocks(
        service,
        container_ref="git:repo",
        thread_ref="thread-x",
        trigger_origin=None,
        blocks=[
            {"memory_object_id": "m1", "memory_type": "decision",
             "block_type": "memory", "title_preview": "x", "score": 20,
             "retrieval_source": "vector"},
            {"memory_object_id": "m2", "memory_type": "constraint_memory",
             "block_type": "memory", "title_preview": "y", "score": 21,
             "retrieval_source": "vector"},
        ],
    )
    # Find the audit row id and confirm two usage-audit rows exist
    with service._storage._engine.begin() as connection:
        audit_id = connection.execute(text(
            "SELECT id FROM query_audit_log LIMIT 1"
        )).fetchone()[0]
        rows = connection.execute(text(
            "SELECT memory_object_id, memory_type, container_ref, "
            "       thread_ref, trigger_origin, referenced_in_next_turn, "
            "       reference_kind, populated_at "
            "FROM memory_usage_audit "
            "WHERE query_audit_log_id = :id "
            "ORDER BY memory_object_id"
        ), {"id": audit_id}).fetchall()
    assert len(rows) == 2
    # Denorms copied
    assert rows[0][1] == "decision"
    assert rows[0][2] == "git:repo"
    assert rows[0][3] == "thread-x"
    assert rows[0][4] is None  # trigger_origin
    # Populator hasn't run yet — NULLs
    assert rows[0][5] is None  # referenced_in_next_turn
    assert rows[0][6] is None  # reference_kind
    assert rows[0][7] is None  # populated_at


def test_write_query_audit_with_zero_injected_blocks_writes_zero_rows(
    service_and_client,
):
    service, _client, _db_path = service_and_client
    # Direct storage call — no injectable_blocks.
    service.write_query_audit(
        source_item_id="si-empty",
        source_id="src-empty",
        thread_ref="t",
        container_ref="c",
        actor_ref="user",
        visibility="private",
        query_text="empty",
        should_inject=False,
        decision_reason="no_relevant_memory",
        injectable_blocks=[],
        results=[],
        ranked_candidates=None,
        injection_method=None,
        trigger_origin=None,
    )
    with service._storage._engine.begin() as connection:
        n_audit = connection.execute(text(
            "SELECT COUNT(*) FROM query_audit_log"
        )).fetchone()[0]
        n_usage = connection.execute(text(
            "SELECT COUNT(*) FROM memory_usage_audit"
        )).fetchone()[0]
    assert n_audit == 1  # the audit row still gets written
    assert n_usage == 0  # but no per-block usage rows


def test_write_query_audit_denormalizes_trigger_origin(service_and_client):
    service, _client, _db_path = service_and_client
    _write_query_with_blocks(
        service,
        trigger_origin="post_tool_failure",
        blocks=[{"memory_object_id": "m1", "memory_type": "investigation_outcome",
                 "block_type": "memory", "title_preview": "x", "score": 14,
                 "retrieval_source": "vector"}],
    )
    with service._storage._engine.begin() as connection:
        trigger_origin = connection.execute(text(
            "SELECT trigger_origin FROM memory_usage_audit LIMIT 1"
        )).fetchone()[0]
    assert trigger_origin == "post_tool_failure"


# ---------------------------------------------------------------------------
# Storage methods
# ---------------------------------------------------------------------------


def test_list_memory_usage_audit_rows_returns_oldest_first(service_and_client):
    service, _client, _db_path = service_and_client
    _write_query_with_blocks(
        service,
        blocks=[
            {"memory_object_id": "m_a", "memory_type": "decision",
             "block_type": "memory", "title_preview": "x", "score": 20,
             "retrieval_source": "vector"},
            {"memory_object_id": "m_b", "memory_type": "decision",
             "block_type": "memory", "title_preview": "y", "score": 21,
             "retrieval_source": "vector"},
        ],
    )
    with service._storage._engine.begin() as connection:
        audit_id = connection.execute(text(
            "SELECT id FROM query_audit_log LIMIT 1"
        )).fetchone()[0]
    rows = service.list_memory_usage_audit(audit_id)
    assert len(rows) == 2
    # All rows for the same query → created_at ties; assert ids are
    # stable (sorted by storage natural order).
    mem_ids = sorted(r["memory_object_id"] for r in rows)
    assert mem_ids == ["m_a", "m_b"]


def test_list_memory_usage_audit_rows_empty_for_unknown_query(service_and_client):
    service, _client, _db_path = service_and_client
    assert service.list_memory_usage_audit("no-such-id") == []


def test_update_memory_usage_audit_row_happy_path(service_and_client):
    service, _client, _db_path = service_and_client
    _write_query_with_blocks(service, blocks=[
        {"memory_object_id": "m1", "memory_type": "decision",
         "block_type": "memory", "title_preview": "x", "score": 20,
         "retrieval_source": "vector"},
    ])
    rows = service.list_memory_usage_audit(_first_audit_id(service))
    row_id = rows[0]["id"]
    updated = service.update_memory_usage_audit(
        audit_row_id=row_id,
        referenced_in_next_turn=True,
        reference_kind="verbatim_snippet",
        observation_window_turns=2,
    )
    assert updated is True
    rows = service.list_memory_usage_audit(_first_audit_id(service))
    assert rows[0]["referenced_in_next_turn"] is True
    assert rows[0]["reference_kind"] == "verbatim_snippet"
    assert rows[0]["observation_window_turns"] == 2
    assert rows[0]["populated_at"] is not None


def test_update_memory_usage_audit_row_is_idempotent(service_and_client):
    service, _client, _db_path = service_and_client
    _write_query_with_blocks(service, blocks=[
        {"memory_object_id": "m1", "memory_type": "decision",
         "block_type": "memory", "title_preview": "x", "score": 20,
         "retrieval_source": "vector"},
    ])
    rows = service.list_memory_usage_audit(_first_audit_id(service))
    row_id = rows[0]["id"]
    first = service.update_memory_usage_audit(
        audit_row_id=row_id,
        referenced_in_next_turn=False,
        reference_kind=None,
        observation_window_turns=1,
    )
    second = service.update_memory_usage_audit(
        audit_row_id=row_id,
        referenced_in_next_turn=True,
        reference_kind="verbatim_snippet",
        observation_window_turns=2,
    )
    assert first is True
    assert second is False  # already populated → no-op


def test_update_memory_usage_audit_row_unknown_returns_false(service_and_client):
    service, _client, _db_path = service_and_client
    assert service.update_memory_usage_audit(
        audit_row_id="no-such-row",
        referenced_in_next_turn=True,
        reference_kind="verbatim_snippet",
        observation_window_turns=1,
    ) is False


def _first_audit_id(service) -> str:
    with service._storage._engine.begin() as connection:
        return connection.execute(text(
            "SELECT id FROM query_audit_log LIMIT 1"
        )).fetchone()[0]


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


def test_get_memory_usage_audit_returns_rows(service_and_client):
    service, client, _db_path = service_and_client
    _write_query_with_blocks(service, blocks=[
        {"memory_object_id": "m1", "memory_type": "decision",
         "block_type": "memory", "title_preview": "x", "score": 20,
         "retrieval_source": "vector"},
    ])
    audit_id = _first_audit_id(service)
    resp = client.get(
        "/memory-usage-audit",
        params={"query_audit_log_id": audit_id},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["rows"]) == 1
    assert body["rows"][0]["memory_object_id"] == "m1"
    assert body["rows"][0]["referenced_in_next_turn"] is None


def test_post_memory_usage_audit_updates_row(service_and_client):
    service, client, _db_path = service_and_client
    _write_query_with_blocks(service, blocks=[
        {"memory_object_id": "m1", "memory_type": "decision",
         "block_type": "memory", "title_preview": "x", "score": 20,
         "retrieval_source": "vector"},
    ])
    audit_id = _first_audit_id(service)
    list_resp = client.get(
        "/memory-usage-audit", params={"query_audit_log_id": audit_id}
    )
    row_id = list_resp.json()["rows"][0]["id"]
    resp = client.post(
        f"/memory-usage-audit/{row_id}",
        json={
            "referenced_in_next_turn": True,
            "reference_kind": "verbatim_snippet",
            "observation_window_turns": 1,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["updated"] is True


def test_post_memory_usage_audit_idempotent_second_call_is_noop(service_and_client):
    service, client, _db_path = service_and_client
    _write_query_with_blocks(service, blocks=[
        {"memory_object_id": "m1", "memory_type": "decision",
         "block_type": "memory", "title_preview": "x", "score": 20,
         "retrieval_source": "vector"},
    ])
    audit_id = _first_audit_id(service)
    row_id = client.get(
        "/memory-usage-audit", params={"query_audit_log_id": audit_id}
    ).json()["rows"][0]["id"]
    first = client.post(
        f"/memory-usage-audit/{row_id}",
        json={"referenced_in_next_turn": False, "reference_kind": None,
              "observation_window_turns": 1},
    )
    second = client.post(
        f"/memory-usage-audit/{row_id}",
        json={"referenced_in_next_turn": True, "reference_kind": "verbatim_snippet",
              "observation_window_turns": 2},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["updated"] is True
    assert second.json()["updated"] is False  # idempotent


def test_post_memory_usage_audit_requires_kind_when_referenced(service_and_client):
    service, client, _db_path = service_and_client
    _write_query_with_blocks(service, blocks=[
        {"memory_object_id": "m1", "memory_type": "decision",
         "block_type": "memory", "title_preview": "x", "score": 20,
         "retrieval_source": "vector"},
    ])
    audit_id = _first_audit_id(service)
    row_id = client.get(
        "/memory-usage-audit", params={"query_audit_log_id": audit_id}
    ).json()["rows"][0]["id"]
    resp = client.post(
        f"/memory-usage-audit/{row_id}",
        json={"referenced_in_next_turn": True, "reference_kind": None,
              "observation_window_turns": 1},
    )
    assert resp.status_code == 400
    assert "reference_kind" in resp.json()["detail"]


def test_post_memory_usage_audit_rejects_unknown_kind(service_and_client):
    service, client, _db_path = service_and_client
    _write_query_with_blocks(service, blocks=[
        {"memory_object_id": "m1", "memory_type": "decision",
         "block_type": "memory", "title_preview": "x", "score": 20,
         "retrieval_source": "vector"},
    ])
    audit_id = _first_audit_id(service)
    row_id = client.get(
        "/memory-usage-audit", params={"query_audit_log_id": audit_id}
    ).json()["rows"][0]["id"]
    resp = client.post(
        f"/memory-usage-audit/{row_id}",
        json={"referenced_in_next_turn": True, "reference_kind": "bogus",
              "observation_window_turns": 1},
    )
    assert resp.status_code == 400


def test_post_memory_usage_audit_unknown_row_returns_updated_false(service_and_client):
    _service, client, _db_path = service_and_client
    resp = client.post(
        "/memory-usage-audit/no-such-id",
        json={"referenced_in_next_turn": False, "reference_kind": None,
              "observation_window_turns": 1},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Phase 5b — GET ?thread_ref=... discovery mode
# ---------------------------------------------------------------------------


def test_get_by_thread_returns_only_pending_rows(service_and_client):
    """GET with thread_ref returns rows where populated_at IS NULL."""
    service, client, _db_path = service_and_client
    # Inject one block on thread-A and another on thread-B.
    _write_query_with_blocks(service, thread_ref="thread-A", blocks=[
        {"memory_object_id": "m1", "memory_type": "decision",
         "block_type": "memory", "title_preview": "x", "score": 20,
         "retrieval_source": "vector"},
    ])
    _write_query_with_blocks(service, thread_ref="thread-A", blocks=[
        {"memory_object_id": "m2", "memory_type": "decision",
         "block_type": "memory", "title_preview": "y", "score": 21,
         "retrieval_source": "vector"},
    ])
    _write_query_with_blocks(service, thread_ref="thread-B", blocks=[
        {"memory_object_id": "m3", "memory_type": "decision",
         "block_type": "memory", "title_preview": "z", "score": 22,
         "retrieval_source": "vector"},
    ])
    resp = client.get("/memory-usage-audit", params={"thread_ref": "thread-A"})
    assert resp.status_code == 200
    rows = resp.json()["rows"]
    # Thread-A only — m1 and m2, not m3.
    mids = sorted(r["memory_object_id"] for r in rows)
    assert mids == ["m1", "m2"]
    # All are pending.
    assert all(r["populated_at"] is None for r in rows)
    assert all(r["referenced_in_next_turn"] is None for r in rows)


def test_get_by_thread_excludes_populated_rows(service_and_client):
    service, client, _db_path = service_and_client
    _write_query_with_blocks(service, thread_ref="thread-X", blocks=[
        {"memory_object_id": "m_kept", "memory_type": "decision",
         "block_type": "memory", "title_preview": "x", "score": 20,
         "retrieval_source": "vector"},
        {"memory_object_id": "m_done", "memory_type": "decision",
         "block_type": "memory", "title_preview": "y", "score": 21,
         "retrieval_source": "vector"},
    ])
    # Populate one of the rows
    audit_id = _first_audit_id(service)
    rows = client.get(
        "/memory-usage-audit", params={"query_audit_log_id": audit_id}
    ).json()["rows"]
    done_row = next(r for r in rows if r["memory_object_id"] == "m_done")
    client.post(
        f"/memory-usage-audit/{done_row['id']}",
        json={"referenced_in_next_turn": True,
              "reference_kind": "verbatim_snippet",
              "observation_window_turns": 1},
    )
    # Now the by-thread call should only return the still-pending one.
    pending = client.get(
        "/memory-usage-audit", params={"thread_ref": "thread-X"}
    ).json()["rows"]
    assert len(pending) == 1
    assert pending[0]["memory_object_id"] == "m_kept"


def test_get_by_thread_honors_limit(service_and_client):
    service, client, _db_path = service_and_client
    # Five pending rows on the same thread.
    for i in range(5):
        _write_query_with_blocks(service, thread_ref="thread-N", blocks=[
            {"memory_object_id": f"m{i}", "memory_type": "decision",
             "block_type": "memory", "title_preview": "x", "score": 20,
             "retrieval_source": "vector"},
        ])
    resp = client.get(
        "/memory-usage-audit",
        params={"thread_ref": "thread-N", "limit": 2},
    )
    assert resp.status_code == 200
    assert len(resp.json()["rows"]) == 2


def test_get_rejects_both_query_audit_id_and_thread_ref(service_and_client):
    _service, client, _ = service_and_client
    resp = client.get(
        "/memory-usage-audit",
        params={"query_audit_log_id": "q1", "thread_ref": "t1"},
    )
    assert resp.status_code == 400
    assert "exactly one" in resp.json()["detail"].lower()


def test_get_rejects_neither_param(service_and_client):
    _service, client, _ = service_and_client
    resp = client.get("/memory-usage-audit")
    assert resp.status_code == 400
    assert "exactly one" in resp.json()["detail"].lower()


def test_get_by_thread_no_rows_returns_empty(service_and_client):
    _service, client, _ = service_and_client
    resp = client.get(
        "/memory-usage-audit", params={"thread_ref": "no-such-thread"}
    )
    assert resp.status_code == 200
    assert resp.json()["rows"] == []


def test_get_by_thread_limit_capped_at_100(service_and_client):
    """Request limit > 100 should be rejected by fastapi validation."""
    _service, client, _ = service_and_client
    resp = client.get(
        "/memory-usage-audit",
        params={"thread_ref": "t", "limit": 500},
    )
    assert resp.status_code == 422  # fastapi validation error
