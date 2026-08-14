"""vNext P0 lookup_event_id contract tests.

Asserts the observable API contract for the lookup_event_id field added by the
add-historical-lookup-funnel-telemetry slice (design 015, Phase 0):

A. E2E audit ENABLED: /item-and-query and /query return a non-null
   lookup_event_id that equals the persisted query_audit_log row id.
B. E2E audit DISABLED (default): same endpoints return lookup_event_id=null.
C. E2E debug: lookup_event_id equals the persisted audit row id, or null when
   no row was written. /query/debug writes no row; /item-and-query/debug does
   when audit logging is enabled.
D. Unit: _validate_trigger_origin accepts "agent_pull" and "mcp_pull", rejects
   unknowns with HTTP 400, returns None for None input.
E. Guard: "agent_pull" and "mcp_pull" are NOT in _TRIGGER_BYPASS_ORIGINS (they
   take the normal routing path, not the abstention-bypass path).
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text

from api.routes import _VALID_TRIGGER_ORIGINS, _validate_trigger_origin
from app.config import AppConfig, ObservabilityConfig
from app.main import create_app
from semantic.agent_conversation_memory_routing_selection import _TRIGGER_BYPASS_ORIGINS
from storage.vector_index import VectorIndexConfig
from tests.config_helpers import DEMO_SEMANTIC_PACKAGES


# ---------------------------------------------------------------------------
# Helpers (mirrors pattern in tests/test_query_audit_log.py)
# ---------------------------------------------------------------------------

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
        "source_id": "test:msg:lookup-1",
        "content_type": "text/plain",
        "content": "What framework should the project use?",
        "container_ref": "test:container:lookup",
        "thread_ref": "test:thread:lookup",
        "actor_ref": "test:actor:lookup",
        "visibility": "private",
        "query_limit": 5,
    }
    base.update(overrides)
    return base


def _query_payload(**overrides) -> dict:
    base = {
        "text": "What framework should the project use?",
        "container_ref": "test:container:lookup",
        "thread_ref": "test:thread:lookup",
        "visibility": "private",
    }
    base.update(overrides)
    return base


def _audit_row_count(client: TestClient) -> int:
    storage = client.app.state.pallium_service._storage
    with storage._engine.connect() as conn:
        return conn.execute(text("SELECT COUNT(*) FROM query_audit_log")).scalar()


def _audit_row_id_by_event_id(client: TestClient, event_id: str) -> str | None:
    storage = client.app.state.pallium_service._storage
    with storage._engine.connect() as conn:
        return conn.execute(
            text("SELECT id FROM query_audit_log WHERE id = :eid"),
            {"eid": event_id},
        ).scalar()


def _historical_event_row(client: TestClient, event_id: str) -> tuple | None:
    """Return (event_type, session_id) for a historical_lookup_reuse_event row."""
    storage = client.app.state.pallium_service._storage
    with storage._engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT event_type, session_id FROM historical_lookup_reuse_event "
                "WHERE id = :eid"
            ),
            {"eid": event_id},
        ).one_or_none()


# ---------------------------------------------------------------------------
# A. E2E — audit ENABLED: non-null id matching the persisted row
# ---------------------------------------------------------------------------

class TestLookupEventIdAuditEnabled:
    """When audit logging is on, both /query and /item-and-query must surface
    a non-null lookup_event_id equal to the query_audit_log row id."""

    def test_item_and_query_returns_non_null_lookup_event_id(self, test_db_url):
        client = _make_client(test_db_url, audit_log_enabled=True)
        resp = client.post("/item-and-query", json=_item_and_query_payload())
        assert resp.status_code == 200
        assert resp.json()["lookup_event_id"] is not None, (
            "audit enabled: lookup_event_id must be a non-null string on /item-and-query"
        )

    def test_item_and_query_lookup_event_id_matches_persisted_row(self, test_db_url):
        client = _make_client(test_db_url, audit_log_enabled=True)
        resp = client.post("/item-and-query", json=_item_and_query_payload())
        assert resp.status_code == 200
        event_id = resp.json()["lookup_event_id"]
        assert event_id is not None
        persisted = _audit_row_id_by_event_id(client, event_id)
        assert persisted == event_id, (
            f"lookup_event_id {event_id!r} must equal the persisted query_audit_log id"
        )

    def test_query_returns_non_null_lookup_event_id(self, test_db_url):
        client = _make_client(test_db_url, audit_log_enabled=True)
        resp = client.post("/query", json=_query_payload())
        assert resp.status_code == 200
        assert resp.json()["lookup_event_id"] is not None, (
            "audit enabled: lookup_event_id must be a non-null string on /query"
        )

    def test_query_lookup_event_id_matches_persisted_row(self, test_db_url):
        client = _make_client(test_db_url, audit_log_enabled=True)
        resp = client.post("/query", json=_query_payload())
        assert resp.status_code == 200
        event_id = resp.json()["lookup_event_id"]
        assert event_id is not None
        persisted = _audit_row_id_by_event_id(client, event_id)
        assert persisted == event_id, (
            f"/query lookup_event_id {event_id!r} must equal the persisted row id"
        )

    def test_distinct_calls_produce_distinct_lookup_event_ids(self, test_db_url):
        """Each call must produce a distinct id; ids are not shared across requests."""
        client = _make_client(test_db_url, audit_log_enabled=True)
        ids = set()
        for i in range(3):
            resp = client.post("/item-and-query", json=_item_and_query_payload(
                source_id=f"test:msg:lookup-{i}",
            ))
            assert resp.status_code == 200
            event_id = resp.json()["lookup_event_id"]
            assert event_id is not None
            ids.add(event_id)
        assert len(ids) == 3, "each call must produce a unique lookup_event_id"


# ---------------------------------------------------------------------------
# B. E2E — audit DISABLED (default): lookup_event_id is null
# ---------------------------------------------------------------------------

class TestLookupEventIdAuditDisabled:
    """When audit logging is off (the default), both endpoints return null."""

    def test_item_and_query_returns_null_lookup_event_id(self, test_db_url):
        client = _make_client(test_db_url, audit_log_enabled=False)
        resp = client.post("/item-and-query", json=_item_and_query_payload())
        assert resp.status_code == 200
        assert resp.json()["lookup_event_id"] is None

    def test_query_returns_null_lookup_event_id(self, test_db_url):
        client = _make_client(test_db_url, audit_log_enabled=False)
        resp = client.post("/query", json=_query_payload())
        assert resp.status_code == 200
        assert resp.json()["lookup_event_id"] is None


# ---------------------------------------------------------------------------
# C. E2E — debug endpoints follow the uniform rule: lookup_event_id equals the
# persisted audit row id, or null when no row was written. /query/debug writes
# no row (null); /item-and-query/debug persists a row when audit is enabled.
# ---------------------------------------------------------------------------

class TestLookupEventIdDebugEndpoints:
    """Uniform rule: id == persisted audit row, else null. /query/debug persists
    no row; /item-and-query/debug persists one when audit logging is enabled."""

    def test_query_debug_lookup_event_id_is_null_audit_enabled(self, test_db_url):
        client = _make_client(test_db_url, audit_log_enabled=True)
        resp = client.post("/query/debug", json=_query_payload())
        assert resp.status_code == 200
        assert resp.json()["lookup_event_id"] is None

    def test_query_debug_no_audit_row_written(self, test_db_url):
        """/query/debug must not write any query_audit_log row."""
        client = _make_client(test_db_url, audit_log_enabled=True)
        client.post("/query/debug", json=_query_payload())
        assert _audit_row_count(client) == 0, (
            "/query/debug must not write a query_audit_log row"
        )

    def test_item_and_query_debug_returns_non_null_lookup_event_id_audit_enabled(self, test_db_url):
        """/item-and-query/debug persists an audit row, so it surfaces the id —
        and the id must equal the persisted query_audit_log row id."""
        client = _make_client(test_db_url, audit_log_enabled=True)
        resp = client.post("/item-and-query/debug", json=_item_and_query_payload())
        assert resp.status_code == 200
        event_id = resp.json()["lookup_event_id"]
        assert event_id is not None
        persisted = _audit_row_id_by_event_id(client, event_id)
        assert persisted == event_id, (
            f"/item-and-query/debug lookup_event_id {event_id!r} must equal the persisted row id"
        )

    def test_item_and_query_debug_writes_audit_row(self, test_db_url):
        """/item-and-query/debug writes exactly one query_audit_log row when enabled."""
        client = _make_client(test_db_url, audit_log_enabled=True)
        client.post("/item-and-query/debug", json=_item_and_query_payload())
        assert _audit_row_count(client) == 1, (
            "/item-and-query/debug should write one query_audit_log row when audit is enabled"
        )

    def test_item_and_query_debug_null_when_audit_disabled(self, test_db_url):
        """With audit off, /item-and-query/debug writes no row → null id."""
        client = _make_client(test_db_url, audit_log_enabled=False)
        resp = client.post("/item-and-query/debug", json=_item_and_query_payload())
        assert resp.status_code == 200
        assert resp.json()["lookup_event_id"] is None


# ---------------------------------------------------------------------------
# C2. E2E — source_only path: the historical reuse funnel mints a lookup_event_id
# UNCONDITIONALLY (not gated on audit) and it takes precedence over the audit id.
# ---------------------------------------------------------------------------

class TestSourceOnlyLookupEventId:
    """source_only /query surfaces a minted historical lookup_event_id that is
    persisted independently of query-audit logging and wins over the audit id."""

    def test_source_only_audit_off_returns_minted_id_and_persists_event(self, test_db_url):
        # Audit OFF (default): normal /query returns null, but a source_only
        # search must still return a non-null minted id with a persisted event.
        client = _make_client(test_db_url, audit_log_enabled=False)
        resp = client.post("/query", json=_query_payload(source_only=True))
        assert resp.status_code == 200
        event_id = resp.json()["lookup_event_id"]
        assert event_id is not None, (
            "source_only search must mint a lookup_event_id even with audit off"
        )
        # No audit row was written (audit disabled), but a lookup event exists.
        assert _audit_row_count(client) == 0
        row = _historical_event_row(client, event_id)
        assert row is not None and row[0] == "lookup", (
            "a historical_lookup_reuse_event 'lookup' row must be persisted"
        )
        assert row[1] == "test:thread:lookup"  # session_id == thread_ref

    def test_source_only_audit_on_response_id_is_minted_not_audit(self, test_db_url):
        # Audit ON: an audit row is still written, but the source_only response
        # id must be the minted historical id — NOT the audit row id.
        client = _make_client(test_db_url, audit_log_enabled=True)
        resp = client.post("/query", json=_query_payload(source_only=True))
        assert resp.status_code == 200
        event_id = resp.json()["lookup_event_id"]
        assert event_id is not None
        # The returned id is the minted historical id (present in the event
        # table) and is NOT a query_audit_log row id.
        row = _historical_event_row(client, event_id)
        assert row is not None and row[0] == "lookup"
        assert _audit_row_id_by_event_id(client, event_id) is None, (
            "source_only response id must be the minted historical id, not the audit row id"
        )
        # An audit row was nonetheless written for the query (audit is on).
        assert _audit_row_count(client) == 1


# ---------------------------------------------------------------------------
# D. Unit — _validate_trigger_origin: agent_pull / mcp_pull accepted
# ---------------------------------------------------------------------------

class TestValidateTriggerOriginNewValues:
    def test_agent_pull_accepted(self):
        assert _validate_trigger_origin("agent_pull") == "agent_pull"

    def test_mcp_pull_accepted(self):
        assert _validate_trigger_origin("mcp_pull") == "mcp_pull"

    def test_none_returns_none(self):
        assert _validate_trigger_origin(None) is None

    def test_unknown_origin_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_trigger_origin("bogus_origin")
        assert exc_info.value.status_code == 400

    def test_agent_pull_in_valid_set(self):
        assert "agent_pull" in _VALID_TRIGGER_ORIGINS

    def test_mcp_pull_in_valid_set(self):
        assert "mcp_pull" in _VALID_TRIGGER_ORIGINS


# ---------------------------------------------------------------------------
# E. Guard — agent_pull / mcp_pull not in the abstention bypass set
# ---------------------------------------------------------------------------

class TestBypassSetGuard:
    """agent_pull and mcp_pull must take the normal routing path.
    Adding them to _TRIGGER_BYPASS_ORIGINS would incorrectly let
    demoted-type candidates through for every agent-issued pull."""

    def test_agent_pull_not_in_bypass_origins(self):
        assert "agent_pull" not in _TRIGGER_BYPASS_ORIGINS, (
            "agent_pull must NOT be in the abstention bypass set; "
            "it takes the normal routing path"
        )

    def test_mcp_pull_not_in_bypass_origins(self):
        assert "mcp_pull" not in _TRIGGER_BYPASS_ORIGINS, (
            "mcp_pull must NOT be in the abstention bypass set; "
            "it takes the normal routing path"
        )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
