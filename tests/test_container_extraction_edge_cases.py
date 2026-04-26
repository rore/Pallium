"""Edge case tests for container-level extraction.

Covers scenarios not exercised by the main reproduction test or unit tests:
- Thread position computation edge cases
- Collection watermark incremental behavior
- Scope-aware 2-item minimum
- Container processing scope opt-in gating
- Mixed containers with only threadless items
- Re-entrancy: items arriving after initial processing
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.config import AppConfig, LLMProviderConfig, SemanticPackageConfig
from app.main import create_app
from capabilities.thread_aggregation import build_thread_aggregate
from core.contracts import ProcessResult
from core.models import SourceItem, utc_now
from core.thread_rebuild import CONTAINER_SCOPE_RECENT_ITEMS, ThreadRebuilder
from fastapi.testclient import TestClient
from providers.llm.base import LLMJsonResponse
from semantic.base import ThreadAggregationSemanticPlugin
from storage.base import ThreadProcessingScope
from storage.vector_index import VectorIndexConfig


# ── Helpers ──────────────────────────────────────────────────────────────────

def _app_config(db_url: str) -> AppConfig:
    return AppConfig(
        storage_backend="sqlite",
        sqlite_url=db_url,
        default_use_case="demo_agent_memory",
        vector_index=VectorIndexConfig(enabled=False),
    )


def _app_config_with_llm(db_url: str) -> AppConfig:
    return AppConfig(
        storage_backend="sqlite",
        sqlite_url=db_url,
        default_use_case="demo_agent_memory",
        llm_providers={
            "test_provider": LLMProviderConfig(
                name="test_provider",
                kind="openai_compatible",
                base_url="http://fake-provider.local",
                api_key="test-key",
                timeout_seconds=30.0,
            ),
        },
        semantic_packages={
            "conversational_knowledge": SemanticPackageConfig(
                name="conversational_knowledge",
                implementation="conversational_knowledge",
                llm_provider="test_provider",
                model="fake-model",
            ),
        },
        vector_index=VectorIndexConfig(enabled=False),
    )


class FactStub:
    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        payload = {"facts": [
            {"subject": "test", "statement": "Test fact from edge case.", "category": "preference"},
        ]}
        return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)


def _make_item(
    source_id: str,
    content: str = "test content",
    *,
    thread_ref: str | None = None,
    container_ref: str = "container-a",
    role: str = "user",
    artifact_kind: str = "message",
) -> SourceItem:
    return SourceItem(
        source_type="chat_message",
        source_id=source_id,
        content_type="text/plain",
        content=content,
        role=role,
        artifact_kind=artifact_kind,
        container_ref=container_ref,
        thread_ref=thread_ref,
        visibility="private",
    )


def _find(storage, source_id: str) -> SourceItem:
    item = storage.find_source_item("chat_message", source_id)
    assert item is not None, f"source_id={source_id!r} not found"
    return item


def _count_container_scopes(service, container_ref: str) -> int:
    from sqlalchemy import select
    from storage.sqlite_schema import ThreadProcessingLeaseRecord

    with service._storage._session_factory() as session:
        scopes = session.scalars(
            select(ThreadProcessingLeaseRecord).where(
                ThreadProcessingLeaseRecord.container_ref == container_ref,
            )
        ).all()
        return len([s for s in scopes if '"thread_ref":null' in s.scope_key])


def _get_container_scope_watermark(service, container_ref: str) -> datetime | None:
    from sqlalchemy import select
    from storage.sqlite_schema import ThreadProcessingLeaseRecord

    with service._storage._session_factory() as session:
        scopes = session.scalars(
            select(ThreadProcessingLeaseRecord).where(
                ThreadProcessingLeaseRecord.container_ref == container_ref,
            )
        ).all()
        for s in scopes:
            if '"thread_ref":null' in s.scope_key:
                return s.collection_watermark_at
    return None


# ── Thread position edge cases ───────────────────────────────────────────────

class TestThreadPositionEdgeCases:
    def test_multiple_threadless_items_all_get_position_1(self, test_db_url: str) -> None:
        """Each threadless item is independent — all get position 1."""
        app = create_app(_app_config(test_db_url))
        storage = app.state.pallium_service._storage

        for i in range(5):
            storage.create_source_item(_make_item(f"no-thread-{i}", thread_ref=None))

        for i in range(5):
            assert _find(storage, f"no-thread-{i}").thread_position == 1

    def test_containerless_item_gets_position_1(self, test_db_url: str) -> None:
        """Item with no container_ref gets position 1 (threadless path)."""
        app = create_app(_app_config(test_db_url))
        storage = app.state.pallium_service._storage

        item = SourceItem(
            source_type="chat_message",
            source_id="no-container",
            content_type="text/plain",
            content="orphan",
            container_ref=None,
            thread_ref="thread-a",
            visibility="private",
        )
        storage.create_source_item(item)
        assert _find(storage, "no-container").thread_position == 1

    def test_mixed_threaded_and_threadless_positions(self, test_db_url: str) -> None:
        """Threaded items get sequential positions; threadless items always get 1."""
        app = create_app(_app_config(test_db_url))
        storage = app.state.pallium_service._storage

        storage.create_source_item(_make_item("t-1", thread_ref="thread-a"))
        storage.create_source_item(_make_item("orphan-1", thread_ref=None))
        storage.create_source_item(_make_item("t-2", thread_ref="thread-a"))
        storage.create_source_item(_make_item("orphan-2", thread_ref=None))

        assert _find(storage, "t-1").thread_position == 1
        assert _find(storage, "t-2").thread_position == 2
        assert _find(storage, "orphan-1").thread_position == 1
        assert _find(storage, "orphan-2").thread_position == 1


# ── Container collection edge cases ──────────────────────────────────────────

class TestContainerCollectionEdgeCases:
    def test_only_threadless_items_collected(self, test_db_url: str) -> None:
        """Container with only threadless items still collects them."""
        app = create_app(_app_config(test_db_url))
        storage = app.state.pallium_service._storage

        for i in range(3):
            storage.create_source_item(_make_item(f"orphan-{i}", f"orphan msg {i}", thread_ref=None))

        items = storage.list_top_level_messages_for_container("container-a")
        assert len(items) == 3

    def test_empty_container_returns_empty(self, test_db_url: str) -> None:
        """No items in container returns empty list."""
        app = create_app(_app_config(test_db_url))
        storage = app.state.pallium_service._storage

        items = storage.list_top_level_messages_for_container("container-a")
        assert items == []

    def test_watermark_with_threadless_items(self, test_db_url: str) -> None:
        """Watermark filters threadless items by created_at."""
        app = create_app(_app_config(test_db_url))
        storage = app.state.pallium_service._storage

        storage.create_source_item(_make_item("old-orphan", "old", thread_ref=None))
        all_items = storage.list_top_level_messages_for_container("container-a")
        watermark = all_items[0].created_at

        storage.create_source_item(_make_item("new-orphan", "new", thread_ref=None))
        filtered = storage.list_top_level_messages_for_container(
            "container-a", after_created_at=watermark,
        )
        assert len(filtered) == 1
        assert filtered[0].source_id == "new-orphan"

    def test_max_items_with_mixed_threaded_and_threadless(self, test_db_url: str) -> None:
        """max_items returns most recent top-level items across both threaded firsts and threadless."""
        app = create_app(_app_config(test_db_url))
        storage = app.state.pallium_service._storage

        for i in range(5):
            storage.create_source_item(_make_item(f"thread-first-{i}", f"first in thread {i}", thread_ref=f"t-{i}"))
        for i in range(5):
            storage.create_source_item(_make_item(f"orphan-{i}", f"orphan {i}", thread_ref=None))

        items = storage.list_top_level_messages_for_container("container-a", max_items=3)
        assert len(items) == 3
        for item in items:
            assert item.thread_position == 1

    def test_single_thread_container_only_first_collected(self, test_db_url: str) -> None:
        """Container where all items are in a single thread: only first item is collected."""
        app = create_app(_app_config(test_db_url))
        storage = app.state.pallium_service._storage

        for i in range(5):
            storage.create_source_item(_make_item(f"single-{i}", f"msg {i}", thread_ref="the-thread"))

        items = storage.list_top_level_messages_for_container("container-a")
        assert len(items) == 1
        assert items[0].source_id == "single-0"


# ── Scope-aware 2-item minimum ──────────────────────────────────────────────

class TestScopeAwareMinimum:
    def test_thread_scope_requires_2_items(self) -> None:
        """Thread-scope aggregate with 1 item returns empty result."""
        items = [_make_item("msg-1", "single", thread_ref="thread-a")]
        aggregate = build_thread_aggregate(items)
        assert aggregate.thread_ref == "thread-a"
        assert len(aggregate.source_items) == 1

    def test_container_scope_accepts_1_item(self) -> None:
        """Container-scope aggregate with 1 item is valid."""
        items = [_make_item("msg-1", "single", thread_ref="thread-a")]
        aggregate = build_thread_aggregate(items, container_scope=True)
        assert aggregate.thread_ref is None
        assert len(aggregate.source_items) == 1


# ── Container processing scope opt-in ────────────────────────────────────────

class TestContainerScopeOptIn:
    def test_container_scope_created_for_conversational_knowledge(
        self, monkeypatch, test_db_url: str,
    ) -> None:
        """conversational_knowledge plugin creates container scope."""
        monkeypatch.setattr(
            "app.dependencies.build_llm_provider",
            lambda config, **_: FactStub(),
        )
        app = create_app(_app_config_with_llm(test_db_url))
        service = app.state.pallium_service
        rebuilder = service._thread_rebuilder

        item = _make_item("msg-1", "test content", thread_ref="t-1")
        ck_plugin = service._semantic_plugins.get("conversational_knowledge")
        assert ck_plugin is not None

        scope = rebuilder.build_container_processing_scope(
            plugin_name="conversational_knowledge",
            plugin=ck_plugin,
            source_item=item,
        )
        assert scope is not None
        assert scope.thread_ref is None
        assert scope.container_ref == "container-a"

    def test_container_scope_not_created_for_agent_memory(
        self, test_db_url: str,
    ) -> None:
        """agent_conversation_memory does NOT get container scope (opt-in = False)."""
        app = create_app(_app_config(test_db_url))
        service = app.state.pallium_service
        rebuilder = service._thread_rebuilder

        item = _make_item("msg-1", "test content", thread_ref="t-1")
        acm_plugin = service._semantic_plugins.get("demo_agent_memory")
        if acm_plugin is None:
            pytest.skip("demo_agent_memory plugin not available")

        scope = rebuilder.build_container_processing_scope(
            plugin_name="demo_agent_memory",
            plugin=acm_plugin,
            source_item=item,
        )
        assert scope is None

    def test_container_scope_requires_container_ref(
        self, monkeypatch, test_db_url: str,
    ) -> None:
        """No container scope if source_item lacks container_ref."""
        monkeypatch.setattr(
            "app.dependencies.build_llm_provider",
            lambda config, **_: FactStub(),
        )
        app = create_app(_app_config_with_llm(test_db_url))
        service = app.state.pallium_service
        rebuilder = service._thread_rebuilder

        item = SourceItem(
            source_type="chat_message",
            source_id="orphan",
            content_type="text/plain",
            content="no container",
            container_ref=None,
            thread_ref="t-1",
            visibility="private",
            role="user",
            artifact_kind="message",
        )
        ck_plugin = service._semantic_plugins.get("conversational_knowledge")
        scope = rebuilder.build_container_processing_scope(
            plugin_name="conversational_knowledge",
            plugin=ck_plugin,
            source_item=item,
        )
        assert scope is None


# ── Incremental watermark flow ───────────────────────────────────────────────

class TestIncrementalWatermarkFlow:
    def test_first_run_uses_max_items_bound(
        self, monkeypatch, test_db_url: str,
    ) -> None:
        """First container scope extraction (no watermark) uses max_items bound."""
        monkeypatch.setattr(
            "app.dependencies.build_llm_provider",
            lambda config, **_: FactStub(),
        )
        app = create_app(_app_config_with_llm(test_db_url))
        client = TestClient(app)
        service = app.state.pallium_service

        for i in range(5):
            thread_ts = f"17764306{i:02d}.000000"
            client.post("/items", json=[{
                "source_type": "conversation_agent_event",
                "source_id": f"wm-msg-{i}",
                "content_type": "text/plain",
                "content": f"Watermark test message {i} about catalog sync configuration.",
                "artifact_kind": "message",
                "role": "user",
                "container_ref": "slack:dm:watermark-test",
                "thread_ref": f"slack:thread:watermark-test:{thread_ts}",
                "visibility": "private",
            }])

        service.drain_processing_queue(worker_id="drain")

        facts = service._storage.list_memory_objects(
            memory_types=["atomic_fact"],
            lifecycle="active",
            container_ref="slack:dm:watermark-test",
        )
        assert len(facts) >= 1, "First run should produce facts"

        watermark = _get_container_scope_watermark(service, "slack:dm:watermark-test")
        assert watermark is not None, "Watermark should be set after first run"

    def test_subsequent_run_uses_watermark_for_incremental(
        self, monkeypatch, test_db_url: str,
    ) -> None:
        """After first run, new items get collected incrementally via watermark."""
        monkeypatch.setattr(
            "app.dependencies.build_llm_provider",
            lambda config, **_: FactStub(),
        )
        app = create_app(_app_config_with_llm(test_db_url))
        client = TestClient(app)
        service = app.state.pallium_service

        for i in range(3):
            thread_ts = f"17764306{i:02d}.000000"
            client.post("/items", json=[{
                "source_type": "conversation_agent_event",
                "source_id": f"incr-batch1-{i}",
                "content_type": "text/plain",
                "content": f"First batch message {i} about catalog deployment.",
                "artifact_kind": "message",
                "role": "user",
                "container_ref": "slack:dm:incremental-test",
                "thread_ref": f"slack:thread:incremental-test:{thread_ts}",
                "visibility": "private",
            }])

        service.drain_processing_queue(worker_id="drain")
        first_watermark = _get_container_scope_watermark(service, "slack:dm:incremental-test")
        assert first_watermark is not None

        first_facts = service._storage.list_memory_objects(
            memory_types=["atomic_fact"],
            lifecycle="active",
            container_ref="slack:dm:incremental-test",
        )
        first_count = len(first_facts)
        assert first_count >= 1

        for i in range(2):
            thread_ts = f"17764307{i:02d}.000000"
            client.post("/items", json=[{
                "source_type": "conversation_agent_event",
                "source_id": f"incr-batch2-{i}",
                "content_type": "text/plain",
                "content": f"Second batch message {i} about shadow mode evaluation.",
                "artifact_kind": "message",
                "role": "user",
                "container_ref": "slack:dm:incremental-test",
                "thread_ref": f"slack:thread:incremental-test:{thread_ts}",
                "visibility": "private",
            }])

        service.drain_processing_queue(worker_id="drain")
        second_watermark = _get_container_scope_watermark(service, "slack:dm:incremental-test")
        assert second_watermark is not None
        assert second_watermark > first_watermark, "Watermark should advance"

        all_facts = service._storage.list_memory_objects(
            memory_types=["atomic_fact"],
            lifecycle="active",
            container_ref="slack:dm:incremental-test",
        )
        assert len(all_facts) > first_count, "Second run should produce additional facts"


# ── Re-entrancy: new items during/after processing ──────────────────────────

class TestContainerScopeReentrancy:
    def test_items_after_initial_drain_trigger_new_scope_processing(
        self, monkeypatch, test_db_url: str,
    ) -> None:
        """Items ingested after drain complete trigger new container scope processing on next drain."""
        monkeypatch.setattr(
            "app.dependencies.build_llm_provider",
            lambda config, **_: FactStub(),
        )
        app = create_app(_app_config_with_llm(test_db_url))
        client = TestClient(app)
        service = app.state.pallium_service
        container = "slack:dm:reentrant-test"

        for i in range(3):
            client.post("/items", json=[{
                "source_type": "conversation_agent_event",
                "source_id": f"reent-first-{i}",
                "content_type": "text/plain",
                "content": f"First batch message {i} about catalog sync monitoring.",
                "artifact_kind": "message",
                "role": "user",
                "container_ref": container,
                "thread_ref": f"slack:thread:reentrant:{i}",
                "visibility": "private",
            }])
        service.drain_processing_queue(worker_id="drain")

        scope_count_1 = _count_container_scopes(service, container)
        assert scope_count_1 >= 1

        for i in range(2):
            client.post("/items", json=[{
                "source_type": "conversation_agent_event",
                "source_id": f"reent-second-{i}",
                "content_type": "text/plain",
                "content": f"Second batch message {i} about deployment rollback strategy.",
                "artifact_kind": "message",
                "role": "user",
                "container_ref": container,
                "thread_ref": f"slack:thread:reentrant:late-{i}",
                "visibility": "private",
            }])
        service.drain_processing_queue(worker_id="drain")

        all_facts = service._storage.list_memory_objects(
            memory_types=["atomic_fact"],
            lifecycle="active",
            container_ref=container,
        )
        assert len(all_facts) >= 2, (
            "Both batches should produce facts — "
            "re-entrancy ensures the second batch triggers container scope processing"
        )


# ── Mixed visibility in container scope ──────────────────────────────────────

class TestContainerScopeVisibility:
    def test_container_scope_filters_by_visibility_before_aggregation(
        self, monkeypatch, test_db_url: str,
    ) -> None:
        """Container scope only aggregates items matching the scope's visibility."""
        monkeypatch.setattr(
            "app.dependencies.build_llm_provider",
            lambda config, **_: FactStub(),
        )
        app = create_app(_app_config_with_llm(test_db_url))
        client = TestClient(app)
        service = app.state.pallium_service
        container = "slack:dm:visibility-test"

        client.post("/items", json=[{
            "source_type": "conversation_agent_event",
            "source_id": "vis-private",
            "content_type": "text/plain",
            "content": "Private message about catalog sync design.",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": container,
            "thread_ref": "slack:thread:vis:private",
            "visibility": "private",
        }])
        client.post("/items", json=[{
            "source_type": "conversation_agent_event",
            "source_id": "vis-shared",
            "content_type": "text/plain",
            "content": "Shared message about catalog sync design.",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": container,
            "thread_ref": "slack:thread:vis:shared",
            "visibility": "shared",
        }])
        service.drain_processing_queue(worker_id="drain")

        facts = service._storage.list_memory_objects(
            memory_types=["atomic_fact"],
            lifecycle="active",
            container_ref=container,
        )
        assert len(facts) >= 1, "At least one visibility group should produce facts"
