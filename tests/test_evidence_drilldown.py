"""Tests for the evidence drill-down feature (memory_object_id + GET /memory/{id}/evidence).

Covers:
- Service method: container validation, visibility filtering, missing objects
- HTTP endpoint: happy path, wrong container (404), non-existent (404)
- Injectable block: memory_object_id propagation
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app
from core.models import MemoryObject, Relation, SourceItem
from storage.vector_index import VectorIndexConfig


def _config(db_url: str) -> AppConfig:
    return AppConfig(
        storage_backend="sqlite",
        sqlite_url=db_url,
        default_use_case="demo_agent_memory",
        vector_index=VectorIndexConfig(enabled=False),
    )


def _make_source_item(
    source_id: str, container_ref: str, content: str = "test content",
    visibility: str = "private", actor_ref: str | None = None,
) -> SourceItem:
    return SourceItem(
        source_type="chat_message",
        source_id=source_id,
        content_type="text/plain",
        content=content,
        role="user",
        container_ref=container_ref,
        visibility=visibility,
        actor_ref=actor_ref,
        processing_status="completed",
    )


def _make_memory_object(
    container_ref: str, payload: dict | None = None, visibility: str = "private",
) -> MemoryObject:
    return MemoryObject(
        type="decision",
        schema_id="test",
        schema_version="1",
        payload=payload or {"decision": "test decision"},
        container_ref=container_ref,
        visibility=visibility,
    )


# ---------------------------------------------------------------------------
# Service method tests
# ---------------------------------------------------------------------------

class TestGetMemoryEvidence:
    def test_returns_evidence_for_matching_container(self, test_db_url: str) -> None:
        app = create_app(_config(test_db_url))
        service = app.state.pallium_service
        storage = service._storage

        si = _make_source_item("ev-src-1", "container-a", content="the original conversation")
        storage.create_source_item(si)
        mo = _make_memory_object("container-a")
        storage.create_memory_object(mo)
        storage.create_relation(Relation(
            from_kind="memory_object", from_id=mo.id,
            relation_type="supported_by",
            to_kind="source_item", to_id=si.id,
        ))

        items = service.get_memory_evidence(mo.id, container_ref="container-a")
        assert len(items) == 1
        assert items[0].content == "the original conversation"

    def test_rejects_wrong_container(self, test_db_url: str) -> None:
        app = create_app(_config(test_db_url))
        service = app.state.pallium_service
        storage = service._storage

        mo = _make_memory_object("container-a")
        storage.create_memory_object(mo)

        with pytest.raises(KeyError):
            service.get_memory_evidence(mo.id, container_ref="container-b")

    def test_rejects_nonexistent_memory_object(self, test_db_url: str) -> None:
        app = create_app(_config(test_db_url))
        service = app.state.pallium_service

        with pytest.raises(KeyError):
            service.get_memory_evidence("nonexistent-id", container_ref="container-a")

    def test_no_container_ref_uses_memory_object_container(self, test_db_url: str) -> None:
        """When container_ref is omitted, evidence is returned using the
        memory object's own container_ref for visibility filtering."""
        app = create_app(_config(test_db_url))
        service = app.state.pallium_service
        storage = service._storage

        si = _make_source_item("ev-no-cref", "container-a", content="accessible without container")
        storage.create_source_item(si)
        mo = _make_memory_object("container-a")
        storage.create_memory_object(mo)
        storage.create_relation(Relation(
            from_kind="memory_object", from_id=mo.id,
            relation_type="supported_by",
            to_kind="source_item", to_id=si.id,
        ))

        items = service.get_memory_evidence(mo.id)
        assert len(items) == 1
        assert items[0].content == "accessible without container"

    def test_filters_private_cross_container_evidence(self, test_db_url: str) -> None:
        """A memory object in container-a links to a private source item in container-b.
        The private item should be filtered out by visibility rules."""
        app = create_app(_config(test_db_url))
        service = app.state.pallium_service
        storage = service._storage

        # Source item belongs to a different container and is private
        si_private = _make_source_item(
            "ev-cross-priv", "container-b", content="private from B",
            visibility="private",
        )
        # Source item is public (shared, no actor) — should pass
        si_public = _make_source_item(
            "ev-cross-pub", "container-b", content="public shared",
            visibility="public", actor_ref=None,
        )
        # Source item is in the same container — should pass
        si_same = _make_source_item(
            "ev-same", "container-a", content="same container",
        )
        storage.create_source_item(si_private)
        storage.create_source_item(si_public)
        storage.create_source_item(si_same)

        mo = _make_memory_object("container-a")
        storage.create_memory_object(mo)
        for si in [si_private, si_public, si_same]:
            storage.create_relation(Relation(
                from_kind="memory_object", from_id=mo.id,
                relation_type="supported_by",
                to_kind="source_item", to_id=si.id,
            ))

        items = service.get_memory_evidence(mo.id, container_ref="container-a")
        contents = {item.content for item in items}
        assert "same container" in contents
        assert "public shared" in contents
        assert "private from B" not in contents

    def test_returns_multiple_evidence_items(self, test_db_url: str) -> None:
        app = create_app(_config(test_db_url))
        service = app.state.pallium_service
        storage = service._storage

        items = []
        for i in range(3):
            si = _make_source_item(f"multi-{i}", "container-a", content=f"message {i}")
            storage.create_source_item(si)
            items.append(si)

        mo = _make_memory_object("container-a")
        storage.create_memory_object(mo)
        for si in items:
            storage.create_relation(Relation(
                from_kind="memory_object", from_id=mo.id,
                relation_type="supported_by",
                to_kind="source_item", to_id=si.id,
            ))

        result = service.get_memory_evidence(mo.id, container_ref="container-a")
        assert len(result) == 3


# ---------------------------------------------------------------------------
# HTTP endpoint tests
# ---------------------------------------------------------------------------

class TestMemoryEvidenceEndpoint:
    def test_happy_path(self, test_db_url: str) -> None:
        app = create_app(_config(test_db_url))
        storage = app.state.pallium_service._storage

        si = _make_source_item("ep-src-1", "container-a", content="original text")
        storage.create_source_item(si)
        mo = _make_memory_object("container-a")
        storage.create_memory_object(mo)
        storage.create_relation(Relation(
            from_kind="memory_object", from_id=mo.id,
            relation_type="supported_by",
            to_kind="source_item", to_id=si.id,
        ))

        with TestClient(app) as client:
            response = client.get(f"/memory/{mo.id}/evidence", params={"container_ref": "container-a"})

        assert response.status_code == 200
        body = response.json()
        assert body["memory_object_id"] == mo.id
        assert len(body["items"]) == 1
        assert body["items"][0]["content"] == "original text"
        assert body["items"][0]["source_item_id"] == si.id

    def test_wrong_container_returns_404(self, test_db_url: str) -> None:
        app = create_app(_config(test_db_url))
        storage = app.state.pallium_service._storage

        mo = _make_memory_object("container-a")
        storage.create_memory_object(mo)

        with TestClient(app) as client:
            response = client.get(f"/memory/{mo.id}/evidence", params={"container_ref": "container-b"})

        assert response.status_code == 404

    def test_nonexistent_memory_object_returns_404(self, test_db_url: str) -> None:
        app = create_app(_config(test_db_url))

        with TestClient(app) as client:
            response = client.get("/memory/nonexistent-id/evidence", params={"container_ref": "container-a"})

        assert response.status_code == 404

    def test_no_container_ref_returns_evidence(self, test_db_url: str) -> None:
        """Endpoint returns evidence when container_ref is omitted, using
        the memory object's own container for visibility."""
        app = create_app(_config(test_db_url))
        storage = app.state.pallium_service._storage

        si = _make_source_item("ep-no-cref", "container-a", content="no scope needed")
        storage.create_source_item(si)
        mo = _make_memory_object("container-a")
        storage.create_memory_object(mo)
        storage.create_relation(Relation(
            from_kind="memory_object", from_id=mo.id,
            relation_type="supported_by",
            to_kind="source_item", to_id=si.id,
        ))

        with TestClient(app) as client:
            response = client.get(f"/memory/{mo.id}/evidence")

        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["content"] == "no scope needed"

    def test_visibility_filtering_in_response(self, test_db_url: str) -> None:
        app = create_app(_config(test_db_url))
        storage = app.state.pallium_service._storage

        si_visible = _make_source_item("ep-vis", "container-a", content="visible")
        si_hidden = _make_source_item("ep-hid", "container-b", content="hidden", visibility="private")
        storage.create_source_item(si_visible)
        storage.create_source_item(si_hidden)

        mo = _make_memory_object("container-a")
        storage.create_memory_object(mo)
        for si in [si_visible, si_hidden]:
            storage.create_relation(Relation(
                from_kind="memory_object", from_id=mo.id,
                relation_type="supported_by",
                to_kind="source_item", to_id=si.id,
            ))

        with TestClient(app) as client:
            response = client.get(f"/memory/{mo.id}/evidence", params={"container_ref": "container-a"})

        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["content"] == "visible"


# ---------------------------------------------------------------------------
# Injectable block memory_object_id propagation
# ---------------------------------------------------------------------------

class TestInjectableBlockMemoryObjectId:
    def test_memory_hit_block_has_memory_object_id(self) -> None:
        from core.models import EvidenceReference, QueryResultItem
        from semantic.agent_conversation_memory_routing_selection import (
            _build_injectable_block_from_candidate,
        )

        item = QueryResultItem(
            result_kind="memory_hit",
            memory_object_id="mo-test-123",
            type="decision",
            payload={"decision": "use redis", "rationale": "fast"},
            score=100,
            evidence=[],
        )
        candidate = {"item": item, "support": 80, "same_thread": False}
        block = _build_injectable_block_from_candidate(candidate, intent="recall")

        assert block.memory_object_id == "mo-test-123"
        assert "use redis" in block.text

    def test_source_hit_block_has_no_memory_object_id(self) -> None:
        from core.models import QueryResultItem
        from semantic.agent_conversation_memory_routing_selection import (
            _build_injectable_block_from_candidate,
        )

        item = QueryResultItem(
            result_kind="source_hit",
            source_item_id="si-test-456",
            source_type="chat",
            source_id="s-1",
            excerpt="some source text",
            score=50,
            evidence=[],
        )
        candidate = {"item": item, "support": 50, "same_thread": False}
        block = _build_injectable_block_from_candidate(candidate, intent="recall")

        assert block.memory_object_id is None

    def test_all_memory_types_propagate_id(self) -> None:
        from core.models import QueryResultItem
        from semantic.agent_conversation_memory_routing_selection import (
            _build_injectable_block_from_candidate,
        )

        types_and_payloads = [
            ("decision", {"decision": "x", "rationale": "y"}),
            ("investigation_outcome", {"investigation_outcome": "x"}),
            ("task_checkpoint", {"summary": "x", "task": "t", "current_state": "s"}),
            ("continuity_memory", {"summary": "x"}),
            ("pattern_memory", {"summary": "x"}),
            ("interest", {"interest_text": "x"}),
            ("atomic_fact", {"statement": "x"}),
            ("fact_summary", {"summary": "x"}),
            ("thread_summary", {"summary": "x"}),
            ("turn_summary", {"summary": "x"}),
        ]
        for mem_type, payload in types_and_payloads:
            item = QueryResultItem(
                result_kind="memory_hit",
                memory_object_id=f"mo-{mem_type}",
                type=mem_type,
                payload=payload,
                score=100,
                evidence=[],
            )
            candidate = {"item": item, "support": 80, "same_thread": False}
            block = _build_injectable_block_from_candidate(candidate, intent="recall")
            assert block.memory_object_id == f"mo-{mem_type}", f"Failed for type {mem_type}"

    def test_fact_summary_block_uses_explicit_title_and_summary_text(self) -> None:
        from core.models import QueryResultItem
        from semantic.agent_conversation_memory_routing_selection import (
            _build_injectable_block_from_candidate,
        )

        item = QueryResultItem(
            result_kind="memory_hit",
            memory_object_id="mo-fact-summary",
            type="fact_summary",
            payload={
                "subject": "Alice",
                "category": "travel",
                "summary": "Alice's travel: planning trips to Rome and Madrid this summer.",
            },
            score=100,
            evidence=[],
        )
        candidate = {"item": item, "support": 80, "same_thread": False}
        block = _build_injectable_block_from_candidate(candidate, intent="recall")

        assert block.title == "Fact Summary"
        assert block.text == "Alice's travel: planning trips to Rome and Madrid this summer."
        assert block.memory_object_id == "mo-fact-summary"
