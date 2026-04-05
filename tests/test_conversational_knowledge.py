"""Tests for the conversational_knowledge fact extraction package."""
from __future__ import annotations

import json

import pytest

from core.contracts import ProcessResult
from core.models import SourceItem, MemoryObject, new_id, utc_now
from core.service import PalliumService
from core.type_registry import TypeRegistry
from providers.llm.base import LLMProvider, LLMJsonResponse
from retrieval.lexical import LexicalRetrievalProvider
from semantic.base import SemanticPlugin
from semantic.conversational_knowledge import (
    ConversationalKnowledgePlugin,
    FACT_TYPE,
    _is_eligible_for_fact_extraction,
)
from semantic.demo_agent_memory import DemoAgentMemoryPlugin
from storage.sqlite import SQLiteStorageProvider


# ── Stub LLM provider ────────────────────────────────────────────────────

class StubFactExtractionProvider(LLMProvider):
    """LLM provider that returns canned fact extraction responses."""

    provider_name = "stub_fact"

    def __init__(self, facts: list[dict] | None = None):
        self._facts = facts or []

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        result = {"facts": self._facts}
        raw = json.dumps(result)
        return LLMJsonResponse(raw_text=raw, parsed_json=result)


# ── Helpers ───────────────────────────────────────────────────────────────

@pytest.fixture
def test_db_url(tmp_path):
    return f"sqlite:///{tmp_path / 'test.db'}"


def _build_service(
    db_url: str,
    *,
    fact_provider: LLMProvider | None = None,
    include_demo: bool = True,
) -> PalliumService:
    storage = SQLiteStorageProvider(db_url)
    plugins: dict[str, SemanticPlugin] = {}
    if include_demo:
        plugins["demo_agent_memory"] = DemoAgentMemoryPlugin()
    if fact_provider is not None:
        plugins["conversational_knowledge"] = ConversationalKnowledgePlugin(
            provider=fact_provider,
        )
    default_use_case = "demo_agent_memory" if include_demo else list(plugins.keys())[0]
    return PalliumService(
        storage=storage,
        retrieval=LexicalRetrievalProvider(storage),
        semantic_plugins=plugins,
        default_use_case=default_use_case,
    )


# ── Tests: eligibility ───────────────────────────────────────────────────

def test_eligible_user_message():
    item = SourceItem(
        source_type="chat", source_id="1",
        content_type="text/plain", content="Hello",
        role="user", artifact_kind="message",
        container_ref="c1", thread_ref="t1",
    )
    assert _is_eligible_for_fact_extraction(item) is True


def test_eligible_assistant_output():
    item = SourceItem(
        source_type="chat", source_id="2",
        content_type="text/plain", content="Sure",
        role="assistant", artifact_kind="assistant_output",
        container_ref="c1", thread_ref="t1",
    )
    assert _is_eligible_for_fact_extraction(item) is True


def test_ineligible_no_thread():
    item = SourceItem(
        source_type="chat", source_id="3",
        content_type="text/plain", content="Hello",
        role="user", artifact_kind="message",
        container_ref="c1",
    )
    assert _is_eligible_for_fact_extraction(item) is False


def test_ineligible_tool_output():
    item = SourceItem(
        source_type="chat", source_id="4",
        content_type="text/plain", content="tool result",
        role="assistant", artifact_kind="tool_use_summary",
        container_ref="c1", thread_ref="t1",
    )
    assert _is_eligible_for_fact_extraction(item) is False


# ── Tests: process_item (lightweight) ─────────────────────────────────────

def test_process_item_eligible_requests_thread_rebuild():
    plugin = ConversationalKnowledgePlugin(
        provider=StubFactExtractionProvider(),
    )
    item = SourceItem(
        source_type="chat", source_id="5",
        content_type="text/plain", content="I have 3 cats",
        role="user", artifact_kind="message",
        container_ref="c1", thread_ref="t1",
    )
    result = plugin.process_item(item)
    assert result.thread_rebuild_requested is True
    assert len(result.memory_objects) == 0


def test_process_item_ineligible_no_rebuild():
    plugin = ConversationalKnowledgePlugin(
        provider=StubFactExtractionProvider(),
    )
    item = SourceItem(
        source_type="chat", source_id="6",
        content_type="text/plain", content="tool output",
        role="assistant", artifact_kind="tool_use_summary",
        container_ref="c1", thread_ref="t1",
    )
    result = plugin.process_item(item)
    assert result.thread_rebuild_requested is False
    assert len(result.memory_objects) == 0


# ── Tests: build_thread_summary (fact extraction) ─────────────────────────

def test_build_thread_summary_extracts_facts():
    from capabilities.thread_aggregation import ThreadAggregate
    facts = [
        {"subject": "Alice", "statement": "Alice has 3 cats", "category": "personal"},
        {"subject": "Bob", "statement": "Bob works at the library", "category": "activity"},
    ]
    plugin = ConversationalKnowledgePlugin(
        provider=StubFactExtractionProvider(facts=facts),
    )
    items = [
        SourceItem(
            source_type="chat", source_id="msg-1",
            content_type="text/plain", content="Alice mentioned she has 3 cats.",
            role="user", artifact_kind="message",
            container_ref="c1", thread_ref="t1",
            visibility="public", occurred_at=utc_now(),
        ),
        SourceItem(
            source_type="chat", source_id="msg-2",
            content_type="text/plain", content="Bob said he works at the library.",
            role="assistant", artifact_kind="assistant_output",
            container_ref="c1", thread_ref="t1",
            visibility="public", occurred_at=utc_now(),
        ),
    ]
    aggregate = ThreadAggregate(
        container_ref="c1",
        thread_ref="t1",
        source_items=items,
        source_item_ids=[i.id for i in items],
        latest_occurred_at=utc_now(),
        aggregate_text="[user]: Alice has 3 cats.\n[assistant]: Bob works at the library.",
        visibility="public",
    )

    result = plugin.build_thread_summary(aggregate, conclusions=[])

    assert len(result.memory_objects) == 2
    assert result.memory_objects[0].type == FACT_TYPE
    assert result.memory_objects[0].payload["subject"] == "Alice"
    assert result.memory_objects[0].payload["statement"] == "Alice has 3 cats"
    assert result.memory_objects[1].payload["subject"] == "Bob"

    # Each fact should have evidence to both source items
    assert len(result.relations) == 4  # 2 facts × 2 source items
    assert all(r.relation_type == "supported_by" for r in result.relations)

    # Each fact should have lexical and vector index entries
    assert len(result.index_entries) == 4  # 2 facts × (lexical + vector)


def test_build_thread_summary_empty_thread():
    from capabilities.thread_aggregation import ThreadAggregate
    plugin = ConversationalKnowledgePlugin(
        provider=StubFactExtractionProvider(facts=[]),
    )
    items = [
        SourceItem(
            source_type="chat", source_id="msg-only",
            content_type="text/plain", content="Hi",
            role="user", artifact_kind="message",
            container_ref="c1", thread_ref="t1",
            visibility="public",
        ),
    ]
    aggregate = ThreadAggregate(
        container_ref="c1", thread_ref="t1",
        source_items=items, source_item_ids=[i.id for i in items],
        latest_occurred_at=None, aggregate_text="",
    )

    result = plugin.build_thread_summary(aggregate, conclusions=[])
    assert len(result.memory_objects) == 0


# ── Tests: type registration ──────────────────────────────────────────────

def test_register_routing_types():
    plugin = ConversationalKnowledgePlugin(
        provider=StubFactExtractionProvider(),
    )
    registry = TypeRegistry()
    plugin.register_routing_types(registry)
    assert "atomic_fact" in registry
    reg = registry.get("atomic_fact")
    assert reg.block_title == "Known Fact"
    assert reg.high_value is False


# ── Tests: parallel_processing flag ───────────────────────────────────────

def test_parallel_processing_flag():
    plugin = ConversationalKnowledgePlugin(
        provider=StubFactExtractionProvider(),
    )
    assert plugin.parallel_processing is True


# ── Tests: multi-package integration ──────────────────────────────────────

def test_multi_package_ingest_creates_fact_package_records(test_db_url):
    """When conversational_knowledge is registered, ingest should create records for both packages."""
    service = _build_service(
        test_db_url,
        fact_provider=StubFactExtractionProvider(),
    )
    result = service.ingest_item(
        source_type="chat", source_id="multi-1",
        content_type="text/plain", content="Alice has 3 cats",
        metadata=None, use_case=None,
        artifact_kind="message", role="user",
        container_ref="c1", thread_ref="t1",
        visibility="public",
    )

    storage = service._storage
    from sqlalchemy import select
    from storage.sqlite_schema import PackageProcessingStatusRecord
    with storage._session_factory() as session:
        records = session.scalars(
            select(PackageProcessingStatusRecord).where(
                PackageProcessingStatusRecord.source_item_id == result.source_item_id,
            )
        ).all()
    package_names = {r.package_name for r in records}
    assert "demo_agent_memory" in package_names
    assert "conversational_knowledge" in package_names


# ── Tests: _build_thread_text session date injection ─────────────────────

def test_build_thread_text_includes_session_date():
    """Thread text should include the session date from earliest occurred_at."""
    from datetime import datetime, timezone
    from capabilities.thread_aggregation import ThreadAggregate
    from semantic.conversational_knowledge import _build_thread_text
    ts = datetime(2023, 8, 28, 14, 30, 0, tzinfo=timezone.utc)
    items = [
        SourceItem(
            source_type="chat", source_id="d1",
            content_type="text/plain", content="I went camping yesterday",
            role="user", artifact_kind="message",
            container_ref="c1", thread_ref="t1",
            occurred_at=ts,
        ),
        SourceItem(
            source_type="chat", source_id="d2",
            content_type="text/plain", content="That sounds fun!",
            role="assistant", artifact_kind="message",
            container_ref="c1", thread_ref="t1",
            occurred_at=datetime(2023, 8, 28, 14, 31, 0, tzinfo=timezone.utc),
        ),
    ]
    aggregate = ThreadAggregate(
        container_ref="c1", thread_ref="t1",
        source_items=items, source_item_ids=[i.id for i in items],
        latest_occurred_at=items[-1].occurred_at,
        aggregate_text="", visibility="public",
    )
    text = _build_thread_text(aggregate)
    assert "Session date: 2023-08-28" in text
    assert text.index("Session date:") < text.index("[user]:")


def test_build_thread_text_no_occurred_at_omits_date():
    """When no occurred_at is available, omit the session date line."""
    from capabilities.thread_aggregation import ThreadAggregate
    from semantic.conversational_knowledge import _build_thread_text
    items = [
        SourceItem(
            source_type="chat", source_id="d3",
            content_type="text/plain", content="Hello",
            role="user", artifact_kind="message",
            container_ref="c1", thread_ref="t1",
        ),
        SourceItem(
            source_type="chat", source_id="d4",
            content_type="text/plain", content="Hi",
            role="assistant", artifact_kind="message",
            container_ref="c1", thread_ref="t1",
        ),
    ]
    aggregate = ThreadAggregate(
        container_ref="c1", thread_ref="t1",
        source_items=items, source_item_ids=[i.id for i in items],
        latest_occurred_at=None, aggregate_text="", visibility="public",
    )
    text = _build_thread_text(aggregate)
    assert "Session date:" not in text
