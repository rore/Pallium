"""Tests for the conversational_knowledge fact extraction package."""
from __future__ import annotations

import json
from datetime import datetime, timezone

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
    FACT_SUMMARY_TYPE,
    _is_eligible_for_fact_extraction,
)
from semantic.demo_agent_memory import DemoAgentMemoryPlugin
from storage.sqlite import SQLiteStorageProvider


# ── Stub LLM provider ────────────────────────────────────────────────────

class StubFactExtractionProvider(LLMProvider):
    """LLM provider that returns canned fact extraction responses."""

    provider_name = "stub_fact"

    def __init__(self, facts: list[dict] | None = None, consolidation_summary: str | None = None):
        self._facts = facts or []
        self._consolidation_summary = consolidation_summary or "Alice: cat owner (3 cats); painting enthusiast"

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        if "consolidat" in system_prompt.lower() or "consolidat" in schema_description.lower():
            result = {"summary": self._consolidation_summary}
        else:
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


# ── Tests: thread_ref in payload and reconcile_process_result ─────────────

def test_build_thread_summary_includes_thread_ref_in_payload():
    """Fact payloads should include thread_ref for cross-thread dedup."""
    from capabilities.thread_aggregation import ThreadAggregate
    facts = [{"subject": "Alice", "statement": "Alice has 3 cats", "category": "personal"}]
    plugin = ConversationalKnowledgePlugin(provider=StubFactExtractionProvider(facts=facts))
    items = [
        SourceItem(
            source_type="chat", source_id="tr1",
            content_type="text/plain", content="Alice has 3 cats",
            role="user", artifact_kind="message",
            container_ref="c1", thread_ref="t1",
            visibility="public", occurred_at=utc_now(),
        ),
        SourceItem(
            source_type="chat", source_id="tr2",
            content_type="text/plain", content="Nice!",
            role="assistant", artifact_kind="message",
            container_ref="c1", thread_ref="t1",
            visibility="public", occurred_at=utc_now(),
        ),
    ]
    aggregate = ThreadAggregate(
        container_ref="c1", thread_ref="t1",
        source_items=items, source_item_ids=[i.id for i in items],
        latest_occurred_at=utc_now(), aggregate_text="", visibility="public",
    )
    result = plugin.build_thread_summary(aggregate, conclusions=[])
    assert result.memory_objects[0].payload["thread_ref"] == "t1"


def test_reconcile_removes_cross_thread_duplicates():
    """reconcile_process_result should remove facts that duplicate cross-thread facts."""
    from core.models import Relation
    from core.indexing import build_index_entry

    storage = SQLiteStorageProvider("sqlite:///:memory:")
    existing_fact = MemoryObject(
        id=new_id(), type="atomic_fact",
        schema_id="conversational_knowledge.atomic_fact",
        schema_version="v1",
        payload={"subject": "Alice", "statement": "Alice has 3 cats", "category": "personal", "thread_ref": "t-other"},
        lifecycle="active", visibility="public", container_ref="c1",
    )
    storage.create_memory_object(existing_fact)

    dup_fact = MemoryObject(
        id=new_id(), type="atomic_fact",
        schema_id="conversational_knowledge.atomic_fact",
        schema_version="v1",
        payload={"subject": "Alice", "statement": "Alice has 3 cats", "category": "personal", "thread_ref": "t1"},
        lifecycle="active", visibility="public", container_ref="c1",
    )
    unique_fact = MemoryObject(
        id=new_id(), type="atomic_fact",
        schema_id="conversational_knowledge.atomic_fact",
        schema_version="v1",
        payload={"subject": "Alice", "statement": "Alice likes painting", "category": "preference", "thread_ref": "t1"},
        lifecycle="active", visibility="public", container_ref="c1",
    )
    result = ProcessResult(
        memory_objects=[dup_fact, unique_fact],
        relations=[
            Relation(from_kind="memory_object", from_id=dup_fact.id, relation_type="supported_by", to_kind="source_item", to_id="s1"),
            Relation(from_kind="memory_object", from_id=unique_fact.id, relation_type="supported_by", to_kind="source_item", to_id="s1"),
        ],
        index_entries=[
            build_index_entry(target_kind="memory_object", target_id=dup_fact.id, index_type="lexical", text_view="Alice has 3 cats", text_view_name="test"),
            build_index_entry(target_kind="memory_object", target_id=unique_fact.id, index_type="lexical", text_view="Alice likes painting", text_view_name="test"),
        ],
    )

    plugin = ConversationalKnowledgePlugin(provider=StubFactExtractionProvider())
    reconciled = plugin.reconcile_process_result(result, storage=storage, container_ref="c1", visibility="public")

    assert len(reconciled.memory_objects) == 1
    assert reconciled.memory_objects[0].payload["statement"] == "Alice likes painting"
    assert all(r.from_id != dup_fact.id for r in reconciled.relations)
    assert all(e.target_id != dup_fact.id for e in reconciled.index_entries)


def test_reconcile_keeps_same_thread_facts():
    """reconcile should NOT filter facts that duplicate same-thread facts (those get superseded)."""
    storage = SQLiteStorageProvider("sqlite:///:memory:")
    existing_fact = MemoryObject(
        id=new_id(), type="atomic_fact",
        schema_id="conversational_knowledge.atomic_fact",
        schema_version="v1",
        payload={"subject": "Alice", "statement": "Alice has 3 cats", "category": "personal", "thread_ref": "t1"},
        lifecycle="active", visibility="public", container_ref="c1",
    )
    storage.create_memory_object(existing_fact)

    new_fact = MemoryObject(
        id=new_id(), type="atomic_fact",
        schema_id="conversational_knowledge.atomic_fact",
        schema_version="v1",
        payload={"subject": "Alice", "statement": "Alice has 3 cats", "category": "personal", "thread_ref": "t1"},
        lifecycle="active", visibility="public", container_ref="c1",
    )
    result = ProcessResult(memory_objects=[new_fact], relations=[], index_entries=[])

    plugin = ConversationalKnowledgePlugin(provider=StubFactExtractionProvider())
    reconciled = plugin.reconcile_process_result(result, storage=storage, container_ref="c1", visibility="public")

    assert len(reconciled.memory_objects) == 1


# ── Tests: consolidation — strategy grouping ────────────────────────────

def _make_fact_candidate(*, subject: str, category: str, container_ref: str, thread_ref: str, visibility: str = "public"):
    """Helper to build a ConsolidationCandidate for an atomic_fact."""
    from capabilities.consolidation import ConsolidationCandidate
    ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    mo = MemoryObject(
        id=new_id(), type="atomic_fact",
        schema_id="conversational_knowledge.atomic_fact", schema_version="v1",
        payload={"subject": subject, "statement": f"{subject} fact in {thread_ref}", "category": category, "thread_ref": thread_ref},
        lifecycle="active", visibility=visibility, container_ref=container_ref,
    )
    return ConsolidationCandidate(
        memory_object=mo,
        evidence=(),
        text_view=f"{subject} fact in {thread_ref}",
        tokens=frozenset(f"{subject} fact in {thread_ref}".lower().split()),
        container_ref=container_ref,
        thread_ref=thread_ref,
        latest_occurred_at=ts,
        visibility=visibility,
    )


def test_fact_consolidation_strategy_groups_by_subject_category():
    """Groups atomic facts by (container_ref, subject, category)."""
    from capabilities.consolidation import FactConsolidationStrategy, ConsolidationPolicy
    strategy = FactConsolidationStrategy()
    policy = ConsolidationPolicy(max_candidates_per_run=200)

    candidates = [
        _make_fact_candidate(subject="Alice", category="personal", container_ref="c1", thread_ref="t1"),
        _make_fact_candidate(subject="Alice", category="personal", container_ref="c1", thread_ref="t2"),
        _make_fact_candidate(subject="Alice", category="personal", container_ref="c1", thread_ref="t3"),
        _make_fact_candidate(subject="Alice", category="activity", container_ref="c1", thread_ref="t1"),
        _make_fact_candidate(subject="Alice", category="activity", container_ref="c1", thread_ref="t2"),
        _make_fact_candidate(subject="Alice", category="activity", container_ref="c1", thread_ref="t3"),
    ]
    selected = strategy.select_candidates(candidates, policy)
    groups = strategy.group_candidates(selected, policy)

    assert len(groups) == 2
    group_keys = {g.merge_rationale["category"].lower() for g in groups}
    assert group_keys == {"personal", "activity"}
    for g in groups:
        assert len(g.candidates) == 3
        assert g.thread_ref is None  # cross-thread


def test_fact_consolidation_strategy_skips_small_groups():
    """Groups below MIN_GROUP_SIZE or MIN_DISTINCT_THREADS are excluded."""
    from capabilities.consolidation import FactConsolidationStrategy, ConsolidationPolicy
    strategy = FactConsolidationStrategy()
    policy = ConsolidationPolicy(max_candidates_per_run=200)

    # Only 2 facts — below MIN_GROUP_SIZE=3
    candidates = [
        _make_fact_candidate(subject="Bob", category="personal", container_ref="c1", thread_ref="t1"),
        _make_fact_candidate(subject="Bob", category="personal", container_ref="c1", thread_ref="t2"),
    ]
    groups = strategy.group_candidates(strategy.select_candidates(candidates, policy), policy)
    assert len(groups) == 0

    # 3 facts but all same thread — below MIN_DISTINCT_THREADS=2
    candidates = [
        _make_fact_candidate(subject="Bob", category="personal", container_ref="c1", thread_ref="t1"),
        _make_fact_candidate(subject="Bob", category="personal", container_ref="c1", thread_ref="t1"),
        _make_fact_candidate(subject="Bob", category="personal", container_ref="c1", thread_ref="t1"),
    ]
    groups = strategy.group_candidates(strategy.select_candidates(candidates, policy), policy)
    assert len(groups) == 0


def test_fact_consolidation_strategy_selects_only_atomic_facts():
    """Strategy filters out non-atomic_fact candidates."""
    from capabilities.consolidation import FactConsolidationStrategy, ConsolidationPolicy, ConsolidationCandidate
    strategy = FactConsolidationStrategy()
    policy = ConsolidationPolicy(max_candidates_per_run=200)

    ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    thread_summary = ConsolidationCandidate(
        memory_object=MemoryObject(
            id=new_id(), type="thread_summary",
            schema_id="test", schema_version="v1",
            payload={"summary": "test summary"},
            lifecycle="active", visibility="public", container_ref="c1",
        ),
        evidence=(), text_view="test summary",
        tokens=frozenset(["test", "summary"]),
        container_ref="c1", thread_ref="t1",
        latest_occurred_at=ts, visibility="public",
    )
    fact = _make_fact_candidate(subject="Alice", category="personal", container_ref="c1", thread_ref="t1")

    selected = strategy.select_candidates([thread_summary, fact], policy)
    assert len(selected) == 1
    assert selected[0].memory_object.type == "atomic_fact"


# ── Tests: consolidation — plugin interface ─────────────────────────────

def test_consolidation_policy_present():
    plugin = ConversationalKnowledgePlugin(provider=StubFactExtractionProvider())
    policy = plugin.consolidation_policy
    assert policy is not None
    assert "fact_consolidation" in policy.enabled_strategies
    assert policy.default_strategy == "fact_consolidation"


def test_supports_consolidation_atomic_fact():
    plugin = ConversationalKnowledgePlugin(provider=StubFactExtractionProvider())
    fact = MemoryObject(
        id=new_id(), type="atomic_fact",
        schema_id="test", schema_version="v1",
        payload={"statement": "test"}, lifecycle="active",
    )
    assert plugin.supports_consolidation(fact) is True


def test_supports_consolidation_rejects_other_types():
    plugin = ConversationalKnowledgePlugin(provider=StubFactExtractionProvider())
    summary = MemoryObject(
        id=new_id(), type="thread_summary",
        schema_id="test", schema_version="v1",
        payload={"summary": "test"}, lifecycle="active",
    )
    assert plugin.supports_consolidation(summary) is False


# ── Tests: consolidation — build_consolidated_memory ────────────────────

def test_build_consolidated_memory_produces_fact_summary():
    """LLM synthesis creates a fact_summary with correct payload and indexes."""
    from capabilities.consolidation import ConsolidationGroup
    canned_summary = "Alice's personal: cat owner (3 cats); painting enthusiast"
    plugin = ConversationalKnowledgePlugin(
        provider=StubFactExtractionProvider(consolidation_summary=canned_summary),
    )
    candidates = tuple([
        _make_fact_candidate(subject="Alice", category="personal", container_ref="c1", thread_ref="t1"),
        _make_fact_candidate(subject="Alice", category="personal", container_ref="c1", thread_ref="t2"),
        _make_fact_candidate(subject="Alice", category="personal", container_ref="c1", thread_ref="t3"),
    ])
    group = ConsolidationGroup(
        strategy_name="fact_consolidation",
        strategy_version="v1",
        group_key="fact_consolidation:public:c1:alice:personal",
        candidates=candidates,
        container_ref="c1",
        thread_ref=None,
        latest_occurred_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        visibility="public",
        merge_rationale={"subject": "Alice", "category": "personal"},
    )

    result = plugin.build_consolidated_memory(group)

    assert len(result.memory_objects) == 1
    mo = result.memory_objects[0]
    assert mo.type == FACT_SUMMARY_TYPE
    assert mo.schema_id == "conversational_knowledge.fact_summary"
    assert mo.payload["subject"] == "Alice"
    assert mo.payload["category"] == "personal"
    assert mo.payload["summary"] == canned_summary
    assert mo.payload["fact_count"] == 3
    assert mo.payload["group_key"] == "fact_consolidation:public:c1:alice:personal"
    assert mo.payload["consolidation_provenance"]["strategy_name"] == "fact_consolidation"
    assert mo.payload["consolidation_provenance"]["prompt_variant"] == "fact_extraction_v1"
    assert mo.visibility == "public"
    assert mo.container_ref == "c1"

    # 2 index entries: lexical + vector
    assert len(result.index_entries) == 2
    types = {e.index_type for e in result.index_entries}
    assert "lexical" in types

    # Relations are empty — the runner adds them
    assert result.relations == []


# ── Tests: consolidation — type registration ────────────────────────────

def test_register_routing_types_includes_fact_summary():
    plugin = ConversationalKnowledgePlugin(provider=StubFactExtractionProvider())
    registry = TypeRegistry()
    plugin.register_routing_types(registry)
    assert "fact_summary" in registry
    reg = registry.get("fact_summary")
    assert reg.block_title == "Fact Summary"
    assert reg.block_text_field == "summary"
    assert reg.high_value is True


# ── Tests: consolidation — _derive_text_view ────────────────────────────

def test_derive_text_view_atomic_fact():
    from capabilities.consolidation import _derive_text_view
    mo = MemoryObject(
        id=new_id(), type="atomic_fact",
        schema_id="test", schema_version="v1",
        payload={"statement": "Alice has 3 cats"},
        lifecycle="active",
    )
    assert _derive_text_view(mo) == "Alice has 3 cats"


def test_derive_text_view_atomic_fact_empty():
    from capabilities.consolidation import _derive_text_view
    mo = MemoryObject(
        id=new_id(), type="atomic_fact",
        schema_id="test", schema_version="v1",
        payload={},
        lifecycle="active",
    )
    assert _derive_text_view(mo) == ""
