"""Tests for the conversational_knowledge fact extraction package."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from core.contracts import ProcessResult
from core.models import SourceItem, MemoryObject, new_id, utc_now
from core.models import MemoryEnvelope, MemoryEnvelopeScope, MemoryEnvelopeDerivation, MemorySubjectAnchor
from core.service import PalliumService
from core.type_registry import TypeRegistry
from providers.llm.base import LLMProvider, LLMJsonResponse
from retrieval.lexical import LexicalRetrievalProvider
from semantic.base import SemanticPlugin
from semantic.conversational_knowledge import (
    ConversationalKnowledgePlugin,
    FACT_TYPE,
    FACT_SUMMARY_TYPE,
    FACT_SCHEMA_ID,
    FACT_SCHEMA_VERSION,
    FACT_SUMMARY_SCHEMA_ID,
    FACT_SUMMARY_SCHEMA_VERSION,
    FACT_ENVELOPE_SCHEMA_ID,
    FACT_ENVELOPE_SCHEMA_VERSION,
    _is_eligible_for_fact_extraction,
)
from semantic.demo_agent_memory import DemoAgentMemoryPlugin
from storage.sqlite import SQLiteStorageProvider


# ── Stub LLM provider ────────────────────────────────────────────────────

class StubFactExtractionProvider(LLMProvider):
    """LLM provider that returns canned fact extraction responses."""

    provider_name = "stub_fact"

    def __init__(self, facts: list[dict] | None = None, consolidation_summary: str | None = None, superseded_indices: list[int] | None = None):
        self._facts = facts or []
        self._consolidation_summary = consolidation_summary or "Alice: cat owner (3 cats); painting enthusiast"
        self._superseded_indices = superseded_indices or []

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        if "consolidat" in system_prompt.lower() or "consolidat" in schema_description.lower():
            result = {
                "summary": self._consolidation_summary,
                "superseded_indices": self._superseded_indices,
                "reasoning": "stub contradiction detection",
            }
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


# ── Tests: _build_chunk_texts session date injection ─────────────────────

def test_build_chunk_texts_includes_session_date():
    """Chunk texts should include the session date from earliest occurred_at."""
    from datetime import datetime, timezone
    from semantic.conversational_knowledge import _build_chunk_texts
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
    chunks = _build_chunk_texts(items)
    assert len(chunks) == 1
    text = chunks[0]
    assert "Session date: 2023-08-28" in text
    assert text.index("Session date:") < text.index("[user]:")


def test_build_chunk_texts_no_occurred_at_omits_date():
    """When no occurred_at is available, omit the session date line."""
    from semantic.conversational_knowledge import _build_chunk_texts
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
    chunks = _build_chunk_texts(items)
    assert len(chunks) == 1
    assert "Session date:" not in chunks[0]


def test_build_chunk_texts_splits_by_item_count():
    """Chunks should split when item count exceeds the max."""
    from semantic.conversational_knowledge import _build_chunk_texts, FACT_EXTRACTION_MAX_ITEMS_PER_CHUNK
    items = [
        SourceItem(
            source_type="chat", source_id=f"item{i}",
            content_type="text/plain", content=f"Short fact {i}.",
            role="user", artifact_kind="message",
            container_ref="c1", thread_ref="t1",
        )
        for i in range(20)
    ]
    chunks = _build_chunk_texts(items)
    assert len(chunks) == 2
    # Each chunk should have exactly 10 items
    for chunk in chunks:
        lines = [l for l in chunk.split("\n") if l.startswith("[")]
        assert len(lines) == FACT_EXTRACTION_MAX_ITEMS_PER_CHUNK


def test_build_chunk_texts_splits_by_char_budget():
    """Chunks should split when char budget is exceeded."""
    from semantic.conversational_knowledge import _build_chunk_texts, FACT_EXTRACTION_MAX_CHARS_PER_CHUNK
    # 5 items at 2000 chars each — should need multiple chunks
    items = [
        SourceItem(
            source_type="chat", source_id=f"long{i}",
            content_type="text/plain", content="x" * 2000,
            role="user", artifact_kind="message",
            container_ref="c1", thread_ref="t1",
        )
        for i in range(5)
    ]
    chunks = _build_chunk_texts(items)
    assert len(chunks) >= 2
    # No item should be truncated — each chunk should contain full content
    for chunk in chunks:
        assert "..." not in chunk


def test_build_chunk_texts_single_large_item():
    """A single item exceeding the char budget gets its own chunk."""
    from semantic.conversational_knowledge import _build_chunk_texts, FACT_EXTRACTION_MAX_CHARS_PER_CHUNK
    items = [
        SourceItem(
            source_type="chat", source_id="huge",
            content_type="text/plain", content="y" * 8000,
            role="user", artifact_kind="message",
            container_ref="c1", thread_ref="t1",
        ),
        SourceItem(
            source_type="chat", source_id="small",
            content_type="text/plain", content="Hello",
            role="assistant", artifact_kind="message",
            container_ref="c1", thread_ref="t1",
        ),
    ]
    chunks = _build_chunk_texts(items)
    assert len(chunks) == 2
    assert "y" * 8000 in chunks[0]  # full content preserved
    assert "Hello" in chunks[1]


def test_build_chunk_texts_preserves_order():
    """Items within chunks must maintain original conversation order."""
    from semantic.conversational_knowledge import _build_chunk_texts
    items = [
        SourceItem(
            source_type="chat", source_id=f"ord{i}",
            content_type="text/plain", content=f"Message {i}",
            role="user" if i % 2 == 0 else "assistant",
            artifact_kind="message",
            container_ref="c1", thread_ref="t1",
        )
        for i in range(15)
    ]
    chunks = _build_chunk_texts(items)
    # Reconstruct all lines across chunks
    all_lines = []
    for chunk in chunks:
        all_lines.extend(l for l in chunk.split("\n") if l.startswith("["))
    numbers = [int(l.split("Message ")[1]) for l in all_lines]
    assert numbers == list(range(15))


def test_build_chunk_texts_small_thread_single_chunk():
    """A small thread should produce exactly one chunk."""
    from semantic.conversational_knowledge import _build_chunk_texts
    items = [
        SourceItem(
            source_type="chat", source_id=f"sm{i}",
            content_type="text/plain", content=f"Short {i}",
            role="user", artifact_kind="message",
            container_ref="c1", thread_ref="t1",
        )
        for i in range(3)
    ]
    chunks = _build_chunk_texts(items)
    assert len(chunks) == 1


def test_dedup_extracted_facts():
    """Dedup should remove exact statement duplicates across chunks."""
    from semantic.conversational_knowledge import _dedup_extracted_facts
    facts = [
        {"subject": "Alice", "statement": "Alice has 3 cats", "category": "personal"},
        {"subject": "Bob", "statement": "Bob lives in NYC", "category": "personal"},
        {"subject": "Alice", "statement": "Alice has 3 cats", "category": "personal"},  # exact dup
    ]
    result = _dedup_extracted_facts(facts)
    assert len(result) == 2
    assert result[0]["subject"] == "Alice"
    assert result[1]["subject"] == "Bob"


def test_build_thread_summary_skips_markdown_fragment_fact() -> None:
    from capabilities.thread_aggregation import ThreadAggregate

    facts = [
        {"subject": "", "statement": "| Can do |", "category": "activity"},
        {"subject": "Alice", "statement": "Alice has 3 cats", "category": "personal"},
    ]
    plugin = ConversationalKnowledgePlugin(provider=StubFactExtractionProvider(facts=facts))
    items = [
        SourceItem(
            source_type="chat", source_id="frag-1",
            content_type="text/plain", content="Capability table discussed.",
            role="user", artifact_kind="message",
            container_ref="c1", thread_ref="t1",
            visibility="public", occurred_at=utc_now(),
        ),
        SourceItem(
            source_type="chat", source_id="frag-2",
            content_type="text/plain", content="Alice has 3 cats.",
            role="assistant", artifact_kind="assistant_output",
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

    assert [memory.payload["statement"] for memory in result.memory_objects] == ["Alice has 3 cats"]


def test_build_thread_summary_skips_markdown_list_fact_in_non_english_text() -> None:
    from capabilities.thread_aggregation import ThreadAggregate

    facts = [
        {
            "subject": "מחזור חיי סשן",
            "statement": "- צריך סשן חדש כדי לקלוט שרת MCP שנוסף באמצע הסשן",
            "category": "activity",
        },
        {"subject": "Alice", "statement": "Alice has 3 cats", "category": "personal"},
    ]
    plugin = ConversationalKnowledgePlugin(provider=StubFactExtractionProvider(facts=facts))
    items = [
        SourceItem(
            source_type="chat", source_id="modal-1",
            content_type="text/plain", content="התנהגות הסשן נדונה.",
            role="user", artifact_kind="message",
            container_ref="c1", thread_ref="t1",
            visibility="public", occurred_at=utc_now(),
        ),
        SourceItem(
            source_type="chat", source_id="modal-2",
            content_type="text/plain", content="Alice has 3 cats.",
            role="assistant", artifact_kind="assistant_output",
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

    assert [memory.payload["statement"] for memory in result.memory_objects] == ["Alice has 3 cats"]


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


def test_reconcile_is_noop():
    """reconcile_process_result is a no-op — consolidation handles cross-thread dedup."""
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
    result = ProcessResult(memory_objects=[dup_fact], relations=[], index_entries=[])

    plugin = ConversationalKnowledgePlugin(provider=StubFactExtractionProvider())
    reconciled = plugin.reconcile_process_result(result, storage=storage, container_ref="c1", visibility="public")

    # All facts pass through — dedup is handled by consolidation, not reconcile
    assert len(reconciled.memory_objects) == 1
    assert reconciled.memory_objects[0].id == dup_fact.id


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

    # Only 1 fact — below MIN_GROUP_SIZE=2
    candidates = [
        _make_fact_candidate(subject="Bob", category="personal", container_ref="c1", thread_ref="t1"),
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

    # 2 facts from 2 threads — meets MIN_GROUP_SIZE=2 and MIN_DISTINCT_THREADS=2
    candidates = [
        _make_fact_candidate(subject="Bob", category="personal", container_ref="c1", thread_ref="t1"),
        _make_fact_candidate(subject="Bob", category="personal", container_ref="c1", thread_ref="t2"),
    ]
    groups = strategy.group_candidates(strategy.select_candidates(candidates, policy), policy)
    assert len(groups) == 1


def test_fact_consolidation_strategy_selects_facts_and_summaries():
    """Strategy selects atomic_fact and fact_summary, filters out other types."""
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
    fact_summary = ConsolidationCandidate(
        memory_object=MemoryObject(
            id=new_id(), type="fact_summary",
            schema_id="conversational_knowledge.fact_summary", schema_version="v1",
            payload={"subject": "Alice", "category": "personal", "summary": "Alice's facts"},
            lifecycle="active", visibility="public", container_ref="c1",
        ),
        evidence=(), text_view="Alice's facts",
        tokens=frozenset(["alice", "facts"]),
        container_ref="c1", thread_ref=None,
        latest_occurred_at=ts, visibility="public",
    )
    fact = _make_fact_candidate(subject="Alice", category="personal", container_ref="c1", thread_ref="t1")

    selected = strategy.select_candidates([thread_summary, fact_summary, fact], policy)
    assert len(selected) == 2
    selected_types = {c.memory_object.type for c in selected}
    assert selected_types == {"atomic_fact", "fact_summary"}


def test_thread_summary_anchored_strategy_accepts_same_thread_atomic_fact_support():
    from capabilities.consolidation import ThreadSummaryAnchoredStrategy, ConsolidationCandidate, ConsolidationPolicy

    strategy = ThreadSummaryAnchoredStrategy()
    policy = ConsolidationPolicy(max_candidates_per_run=50)
    ts = datetime(2024, 1, 1, tzinfo=timezone.utc)

    thread_summary = ConsolidationCandidate(
        memory_object=MemoryObject(
            id=new_id(), type="thread_summary",
            schema_id="test", schema_version="v1",
            payload={
                "summary": "Batch publishing decision recorded for process status summaries.",
                "conclusions": [{"type": "atomic_fact", "text": "Process status summaries go out in 30-minute batches."}],
            },
            lifecycle="active", visibility="public", container_ref="c1",
        ),
        evidence=(),
        text_view="batch publishing decision recorded",
        tokens=frozenset(["batch", "publishing", "decision", "recorded"]),
        container_ref="c1",
        thread_ref="t1",
        latest_occurred_at=ts,
        visibility="public",
    )
    atomic_fact = ConsolidationCandidate(
        memory_object=MemoryObject(
            id=new_id(), type="atomic_fact",
            schema_id="test.atomic_fact", schema_version="v1",
            payload={
                "subject": "summary publishing policy",
                "statement": "30-minute batches reduce downstream noise",
                "category": "decision",
                "thread_ref": "t1",
            },
            lifecycle="active", visibility="public", container_ref="c1",
        ),
        evidence=(),
        text_view="30-minute batches reduce downstream noise",
        tokens=frozenset(["30-minute", "batches", "reduce", "downstream", "noise"]),
        container_ref="c1",
        thread_ref="t1",
        latest_occurred_at=ts,
        visibility="public",
    )

    selected = strategy.select_candidates([thread_summary, atomic_fact], policy)
    groups = strategy.group_candidates(selected, policy)

    assert len(groups) == 1
    grouped_types = {candidate.memory_object.type for candidate in groups[0].candidates}
    assert grouped_types == {"thread_summary", "atomic_fact"}


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
    assert mo.payload["contradiction_reasoning"] == "stub contradiction detection"
    assert mo.visibility == "public"
    assert mo.container_ref == "c1"

    # 2 index entries: lexical + vector
    assert len(result.index_entries) == 2
    types = {e.index_type for e in result.index_entries}
    assert "lexical" in types

    # Relations are empty — the runner adds them
    assert result.relations == []


def test_build_consolidated_memory_records_all_supporting_ids():
    """fact_summary payload includes all input candidate IDs as supporting_memory_ids."""
    from capabilities.consolidation import ConsolidationGroup
    plugin = ConversationalKnowledgePlugin(
        provider=StubFactExtractionProvider(
            consolidation_summary="Alice's personal: citizen of India",
        ),
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
    mo = result.memory_objects[0]
    expected_ids = [c.memory_object.id for c in candidates]
    assert mo.payload["supporting_memory_ids"] == expected_ids


def test_consolidation_runner_supersedes_all_input_facts(test_db_url):
    """Runner supersedes ALL input atomic_facts after consolidation — fact_summary replaces them."""

    plugin = ConversationalKnowledgePlugin(
        provider=StubFactExtractionProvider(
            consolidation_summary="Alice's personal: citizen of India",
        ),
    )
    storage = SQLiteStorageProvider(test_db_url)
    service = PalliumService(
        storage=storage,
        retrieval=LexicalRetrievalProvider(storage),
        semantic_plugins={"conversational_knowledge": plugin},
        default_use_case="conversational_knowledge",
    )

    # Create 3 atomic_fact memory objects across different threads
    for i in range(3):
        mo = MemoryObject(
            id=new_id(),
            type="atomic_fact",
            schema_id="conversational_knowledge.atomic_fact",
            schema_version="v1",
            payload={"subject": "Alice", "statement": f"Alice fact {i}", "category": "personal", "thread_ref": f"t{i}"},
            lifecycle="active",
            visibility="public",
            container_ref="c1",
        )
        storage.create_memory_object(mo)

    # Run consolidation
    result = service.run_consolidation_pass(use_case="conversational_knowledge")

    assert result is not None
    assert len(result.groups) == 1

    # ALL atomic_facts should be superseded (fact_summary replaces them)
    all_facts = storage.list_memory_objects(memory_types=["atomic_fact"])
    active = [f for f in all_facts if f.lifecycle == "active"]
    superseded = [f for f in all_facts if f.lifecycle == "superseded"]
    assert len(superseded) == 3
    assert len(active) == 0

    # A fact_summary should be created
    summaries = storage.list_memory_objects(memory_types=["fact_summary"], lifecycle="active")
    assert len(summaries) == 1
    assert summaries[0].payload["summary"] == "Alice's personal: citizen of India"


def test_consolidation_returns_none_when_no_groups_formed(test_db_url):
    """run_consolidation_pass returns None when candidates exist but form no groups.

    This prevents infinite loops in callers that loop until None.
    Each fact has a unique subject, so no groups can be formed.
    """
    plugin = ConversationalKnowledgePlugin(
        provider=StubFactExtractionProvider(
            consolidation_summary="unused",
        ),
    )
    storage = SQLiteStorageProvider(test_db_url)
    service = PalliumService(
        storage=storage,
        retrieval=LexicalRetrievalProvider(storage),
        semantic_plugins={"conversational_knowledge": plugin},
        default_use_case="conversational_knowledge",
    )

    # Create 3 atomic_facts with DIFFERENT subjects — no groups possible.
    for i, (subject, statement) in enumerate([
        ("Alice", "Alice lives in Berlin"),
        ("Bob", "Bob works at CERN"),
        ("Carol", "Carol plays piano"),
    ]):
        mo = MemoryObject(
            id=f"no-group-fact-{i}",
            type="atomic_fact",
            schema_id="conversational_knowledge.atomic_fact",
            schema_version="v1",
            payload={"subject": subject, "statement": statement, "category": "personal", "thread_ref": f"t{i}"},
            lifecycle="active",
            visibility="public",
            container_ref="c1",
        )
        storage.create_memory_object(mo)

    result = service.run_consolidation_pass(use_case="conversational_knowledge")
    assert result is None, "Should return None when no groups can be formed (prevents infinite loops)"


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


# ── Tests: end-to-end fact lifecycle (ingest → extract → consolidation) ──


def test_e2e_cross_thread_facts_consolidated_automatically(test_db_url):
    """Full lifecycle: ingest messages across 2 threads about the same subject.
    After processing, targeted consolidation should fire automatically,
    producing a fact_summary and superseding all input atomic_facts.
    """
    from datetime import timedelta

    # Stub that extracts 2 facts per thread about "Alice"
    thread_facts = {
        "t1": [
            {"subject": "Alice", "statement": "Alice lives in Berlin", "category": "personal"},
            {"subject": "Alice", "statement": "Alice likes painting", "category": "preference"},
        ],
        "t2": [
            {"subject": "Alice", "statement": "Alice lives in Paris", "category": "personal"},
            {"subject": "Alice", "statement": "Alice has a cat", "category": "personal"},
        ],
    }

    class ThreadAwareFactProvider(LLMProvider):
        """Returns different facts depending on which thread text is being processed,
        and returns a consolidation summary when consolidation prompt is detected."""
        provider_name = "thread_fact_stub"

        def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
            if "consolidat" in system_prompt.lower():
                result = {
                    "summary": "Alice's personal: lives in Paris, has a cat",
                    "superseded_indices": [],
                    "reasoning": "Alice lives in Berlin contradicted by Alice lives in Paris (newer)",
                }
            elif "t2" in user_prompt:
                result = {"facts": thread_facts["t2"]}
            else:
                result = {"facts": thread_facts["t1"]}
            return LLMJsonResponse(raw_text=json.dumps(result), parsed_json=result)

    provider = ThreadAwareFactProvider()
    storage = SQLiteStorageProvider(test_db_url)
    service = PalliumService(
        storage=storage,
        retrieval=LexicalRetrievalProvider(storage),
        semantic_plugins={"conversational_knowledge": ConversationalKnowledgePlugin(provider=provider)},
        default_use_case="conversational_knowledge",
    )

    # Ingest messages in two threads about Alice
    base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i, (thread, content) in enumerate([
        ("t1", "Alice told me she lives in Berlin and likes painting"),
        ("t1", "She showed me her artwork"),
        ("t2", "Alice said she moved to Paris and got a cat"),
        ("t2", "She loves her new apartment"),
    ]):
        item = SourceItem(
            id=new_id(),
            source_type="chat_message",
            source_id=f"msg-{i}",
            content_type="text/plain",
            content=content,
            container_ref="c1",
            thread_ref=thread,
            role="user",
            artifact_kind="message",
            visibility="public",
            occurred_at=base_time + timedelta(hours=i),
        )
        service.ingest_item(
            source_type=item.source_type,
            source_id=item.source_id,
            content_type=item.content_type,
            content=item.content,
            metadata=None,
            use_case=None,
            container_ref=item.container_ref,
            thread_ref=item.thread_ref,
            role=item.role,
            artifact_kind=item.artifact_kind,
            visibility=item.visibility,
            occurred_at=item.occurred_at,
        )

    # Process all items + thread rebuilds (this triggers extraction + consolidation)
    service.drain_processing_queue(worker_id="test-worker")

    # Verify: fact_summary should exist for "alice" in "personal" category
    summaries = storage.list_memory_objects(
        memory_types=["fact_summary"],
        lifecycle="active",
        container_ref="c1",
    )
    personal_summaries = [s for s in summaries if s.payload.get("subject", "").lower() == "alice" and s.payload.get("category", "").lower() == "personal"]
    assert len(personal_summaries) == 1, f"Expected 1 fact_summary for Alice/personal, got {len(personal_summaries)}"
    assert "paris" in personal_summaries[0].payload["summary"].lower()

    # Verify: input atomic_facts about Alice/personal should be superseded
    all_facts = storage.list_memory_objects(memory_types=["atomic_fact"])
    alice_personal_facts = [
        f for f in all_facts
        if f.payload.get("subject", "").lower() == "alice"
        and f.payload.get("category", "").lower() == "personal"
    ]
    active_alice_personal = [f for f in alice_personal_facts if f.lifecycle == "active"]
    superseded_alice_personal = [f for f in alice_personal_facts if f.lifecycle == "superseded"]
    assert len(active_alice_personal) == 0, f"Expected 0 active Alice/personal facts, got {len(active_alice_personal)}"
    assert len(superseded_alice_personal) >= 2, f"Expected >=2 superseded Alice/personal facts, got {len(superseded_alice_personal)}"


def test_e2e_reconsolidation_updates_existing_summary(test_db_url):
    """Re-consolidation: when new facts arrive for a subject that already has a fact_summary,
    the existing summary is included as input and the output supersedes both the old summary
    and the new atomic_facts.
    """
    from datetime import timedelta

    consolidation_call_count = 0

    class ReconsolidationProvider(LLMProvider):
        """Returns different facts per thread and tracks consolidation calls.
        First consolidation: summary from t1+t2 facts.
        Second consolidation: updated summary incorporating t3 facts + prior summary.
        """
        provider_name = "reconsolidation_stub"

        def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
            nonlocal consolidation_call_count
            if "consolidat" in system_prompt.lower():
                consolidation_call_count += 1
                if "previous summary" in user_prompt.lower():
                    # Re-consolidation: sees existing summary + new facts
                    result = {
                        "summary": "Alice's personal: lives in Tokyo (moved from Paris), has a cat, speaks Japanese",
                        "superseded_indices": [],
                        "reasoning": "Updated: Alice moved from Paris to Tokyo",
                    }
                else:
                    # First consolidation: t1+t2 facts
                    result = {
                        "summary": "Alice's personal: lives in Paris, has a cat",
                        "superseded_indices": [],
                        "reasoning": "Initial consolidation",
                    }
            elif "t3" in user_prompt:
                result = {"facts": [
                    {"subject": "Alice", "statement": "Alice moved to Tokyo", "category": "personal"},
                    {"subject": "Alice", "statement": "Alice speaks Japanese", "category": "personal"},
                ]}
            elif "t2" in user_prompt:
                result = {"facts": [
                    {"subject": "Alice", "statement": "Alice lives in Paris", "category": "personal"},
                    {"subject": "Alice", "statement": "Alice has a cat", "category": "personal"},
                ]}
            else:
                result = {"facts": [
                    {"subject": "Alice", "statement": "Alice lives in Berlin", "category": "personal"},
                ]}
            return LLMJsonResponse(raw_text=json.dumps(result), parsed_json=result)

    provider = ReconsolidationProvider()
    storage = SQLiteStorageProvider(test_db_url)
    service = PalliumService(
        storage=storage,
        retrieval=LexicalRetrievalProvider(storage),
        semantic_plugins={"conversational_knowledge": ConversationalKnowledgePlugin(provider=provider)},
        default_use_case="conversational_knowledge",
    )

    base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)

    # Phase 1: Ingest threads t1 and t2, triggering first consolidation
    for i, (thread, content) in enumerate([
        ("t1", "Alice told me she lives in Berlin"),
        ("t1", "We talked about her life there"),
        ("t2", "Alice said she moved to Paris and got a cat"),
        ("t2", "She loves the city"),
    ]):
        service.ingest_item(
            source_type="chat_message", source_id=f"msg-{i}",
            content_type="text/plain", content=content,
            metadata=None, use_case=None,
            container_ref="c1", thread_ref=thread,
            role="user", artifact_kind="message",
            visibility="public", occurred_at=base_time + timedelta(hours=i),
        )
    service.drain_processing_queue(worker_id="test")

    # After phase 1: should have 1 active fact_summary, all atomic_facts superseded
    summaries_v1 = storage.list_memory_objects(memory_types=["fact_summary"], lifecycle="active", container_ref="c1")
    personal_v1 = [s for s in summaries_v1 if s.payload.get("category", "").lower() == "personal"]
    assert len(personal_v1) == 1, f"Phase 1: expected 1 fact_summary, got {len(personal_v1)}"
    summary_v1_id = personal_v1[0].id
    assert "paris" in personal_v1[0].payload["summary"].lower()

    # Phase 2: Ingest thread t3 with new facts about Alice
    for i, (thread, content) in enumerate([
        ("t3", "Alice told me she moved to Tokyo and is learning Japanese"),
        ("t3", "She's really enjoying the new city"),
    ], start=10):
        service.ingest_item(
            source_type="chat_message", source_id=f"msg-{i}",
            content_type="text/plain", content=content,
            metadata=None, use_case=None,
            container_ref="c1", thread_ref=thread,
            role="user", artifact_kind="message",
            visibility="public", occurred_at=base_time + timedelta(hours=i),
        )
    service.drain_processing_queue(worker_id="test")

    # After phase 2: should have a NEW fact_summary (v2), old one superseded
    summaries_v2 = storage.list_memory_objects(memory_types=["fact_summary"], lifecycle="active", container_ref="c1")
    personal_v2 = [s for s in summaries_v2 if s.payload.get("category", "").lower() == "personal"]
    assert len(personal_v2) == 1, f"Phase 2: expected 1 active fact_summary, got {len(personal_v2)}"
    assert personal_v2[0].id != summary_v1_id, "New summary should have a different ID from v1"
    assert "tokyo" in personal_v2[0].payload["summary"].lower(), "Updated summary should mention Tokyo"

    # Old summary should be superseded
    old_summary = storage.get_memory_object(summary_v1_id)
    assert old_summary.lifecycle == "superseded", f"Old summary should be superseded, got {old_summary.lifecycle}"

    # New atomic_facts from t3 should also be superseded
    all_facts = storage.list_memory_objects(memory_types=["atomic_fact"], lifecycle="active", container_ref="c1")
    active_alice_personal = [
        f for f in all_facts
        if f.payload.get("subject", "").lower() == "alice"
        and f.payload.get("category", "").lower() == "personal"
    ]
    assert len(active_alice_personal) == 0, f"All Alice/personal atomic_facts should be superseded, got {len(active_alice_personal)} active"

    # Consolidation should have been called at least twice (once per phase)
    assert consolidation_call_count >= 2, f"Expected >=2 consolidation calls, got {consolidation_call_count}"

    # The re-consolidation call should have received the previous summary as input
    # (verified by the "previous summary" check in the provider returning "Tokyo")


# ── Tests: MemoryEnvelope population ────────────────────────────────────


def test_atomic_fact_envelope_has_subject_anchor():
    """atomic_fact objects should carry a MemoryEnvelope with the subject as a surface anchor."""
    from capabilities.thread_aggregation import ThreadAggregate
    facts = [
        {"subject": "Alice", "statement": "Alice has 3 cats", "category": "personal"},
    ]
    plugin = ConversationalKnowledgePlugin(
        provider=StubFactExtractionProvider(facts=facts),
    )
    items = [
        SourceItem(
            source_type="chat", source_id="env-1",
            content_type="text/plain", content="Alice mentioned she has 3 cats.",
            role="user", artifact_kind="message",
            container_ref="c1", thread_ref="t1",
            visibility="public", occurred_at=utc_now(),
        ),
        SourceItem(
            source_type="chat", source_id="env-2",
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

    assert len(result.memory_objects) == 1
    mo = result.memory_objects[0]
    assert mo.envelope is not None

    env = mo.envelope
    assert env.kind == "finding"
    assert env.confidence == "medium"
    assert env.schema_id == FACT_ENVELOPE_SCHEMA_ID
    assert env.schema_version == FACT_ENVELOPE_SCHEMA_VERSION

    # Scope
    assert env.scope.container_ref == "c1"
    assert env.scope.thread_ref == "t1"

    # Derivation
    assert env.derivation.producer_kind == "item_extraction"
    assert env.derivation.producer_schema_id == FACT_SCHEMA_ID
    assert env.derivation.producer_schema_version == FACT_SCHEMA_VERSION

    # Subject anchor
    assert len(env.subjects) == 1
    assert env.subjects[0].kind == "surface"
    assert env.subjects[0].value == "Alice"


def test_atomic_fact_envelope_empty_subject():
    """atomic_fact with empty subject should have envelope with empty subjects list."""
    from capabilities.thread_aggregation import ThreadAggregate
    facts = [
        {"subject": "", "statement": "The weather was nice", "category": "event"},
    ]
    plugin = ConversationalKnowledgePlugin(
        provider=StubFactExtractionProvider(facts=facts),
    )
    items = [
        SourceItem(
            source_type="chat", source_id="env-es1",
            content_type="text/plain", content="The weather was nice",
            role="user", artifact_kind="message",
            container_ref="c1", thread_ref="t1",
            visibility="public", occurred_at=utc_now(),
        ),
        SourceItem(
            source_type="chat", source_id="env-es2",
            content_type="text/plain", content="Indeed!",
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

    assert len(result.memory_objects) == 1
    mo = result.memory_objects[0]
    assert mo.envelope is not None
    assert mo.envelope.subjects == []
    assert mo.envelope.kind == "finding"
    assert mo.envelope.confidence == "medium"


def test_atomic_fact_envelope_multiple_facts_different_subjects():
    """Each atomic_fact gets its own envelope with its own subject anchor."""
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
            source_type="chat", source_id="env-m1",
            content_type="text/plain", content="Alice has 3 cats, Bob works at the library.",
            role="user", artifact_kind="message",
            container_ref="c1", thread_ref="t1",
            visibility="public", occurred_at=utc_now(),
        ),
        SourceItem(
            source_type="chat", source_id="env-m2",
            content_type="text/plain", content="Interesting!",
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

    assert len(result.memory_objects) == 2

    alice_mo = result.memory_objects[0]
    assert alice_mo.envelope is not None
    assert len(alice_mo.envelope.subjects) == 1
    assert alice_mo.envelope.subjects[0].value == "Alice"

    bob_mo = result.memory_objects[1]
    assert bob_mo.envelope is not None
    assert len(bob_mo.envelope.subjects) == 1
    assert bob_mo.envelope.subjects[0].value == "Bob"


def test_fact_summary_envelope_has_subject_anchor():
    """fact_summary objects should carry a MemoryEnvelope with the subject as a surface anchor."""
    from capabilities.consolidation import ConsolidationGroup
    canned_summary = "Alice's personal: cat owner (3 cats); painting enthusiast"
    plugin = ConversationalKnowledgePlugin(
        provider=StubFactExtractionProvider(consolidation_summary=canned_summary),
    )
    candidates = tuple([
        _make_fact_candidate(subject="Alice", category="personal", container_ref="c1", thread_ref="t1"),
        _make_fact_candidate(subject="Alice", category="personal", container_ref="c1", thread_ref="t2"),
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
    assert mo.envelope is not None

    env = mo.envelope
    assert env.kind == "finding"
    assert env.confidence == "medium"
    assert env.schema_id == FACT_ENVELOPE_SCHEMA_ID
    assert env.schema_version == FACT_ENVELOPE_SCHEMA_VERSION

    # Scope — cross-thread, so thread_ref should be None
    assert env.scope.container_ref == "c1"
    assert env.scope.thread_ref is None

    # Derivation
    assert env.derivation.producer_kind == "consolidation"
    assert env.derivation.producer_schema_id == FACT_SUMMARY_SCHEMA_ID
    assert env.derivation.producer_schema_version == FACT_SUMMARY_SCHEMA_VERSION

    # Subject anchor
    assert len(env.subjects) == 1
    assert env.subjects[0].kind == "surface"
    assert env.subjects[0].value == "Alice"


def test_fact_summary_envelope_empty_subject():
    """fact_summary with empty subject should have envelope with empty subjects list."""
    from capabilities.consolidation import ConsolidationGroup
    canned_summary = "General facts about the project"
    plugin = ConversationalKnowledgePlugin(
        provider=StubFactExtractionProvider(consolidation_summary=canned_summary),
    )
    candidates = tuple([
        _make_fact_candidate(subject="", category="general", container_ref="c1", thread_ref="t1"),
        _make_fact_candidate(subject="", category="general", container_ref="c1", thread_ref="t2"),
    ])
    group = ConsolidationGroup(
        strategy_name="fact_consolidation",
        strategy_version="v1",
        group_key="fact_consolidation:public:c1::general",
        candidates=candidates,
        container_ref="c1",
        thread_ref=None,
        latest_occurred_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        visibility="public",
        merge_rationale={"subject": "", "category": "general"},
    )

    result = plugin.build_consolidated_memory(group)

    assert len(result.memory_objects) == 1
    mo = result.memory_objects[0]
    assert mo.envelope is not None
    assert mo.envelope.subjects == []
    assert mo.envelope.kind == "finding"
    assert mo.envelope.confidence == "medium"


def test_fact_envelope_survives_sqlite_roundtrip(test_db_url):
    """Envelope on atomic_fact must survive serialization/deserialization in SQLite.

    Regression: a mismatched schema_id caused envelope_json to silently
    deserialize as None, making facts enter routing as unanchored_legacy.
    """
    storage = SQLiteStorageProvider(test_db_url)

    mo = MemoryObject(
        type=FACT_TYPE,
        schema_id=FACT_SCHEMA_ID,
        schema_version=FACT_SCHEMA_VERSION,
        payload={"subject": "Alice", "statement": "Alice has cats", "category": "personal"},
        visibility="public",
        container_ref="c1",
        freshness_at=utc_now(),
        envelope=MemoryEnvelope(
            schema_id=FACT_ENVELOPE_SCHEMA_ID,
            schema_version=FACT_ENVELOPE_SCHEMA_VERSION,
            kind="finding",
            scope=MemoryEnvelopeScope(container_ref="c1", thread_ref="t1"),
            derivation=MemoryEnvelopeDerivation(
                producer_kind="item_extraction",
                producer_schema_id=FACT_SCHEMA_ID,
                producer_schema_version=FACT_SCHEMA_VERSION,
            ),
            subjects=[MemorySubjectAnchor(kind="surface", value="Alice")],
            confidence="medium",
        ),
    )

    storage.create_memory_object(mo)
    loaded = storage.get_memory_object(mo.id)

    assert loaded.envelope is not None, (
        "Envelope lost on round-trip — check schema_id matches "
        "MEMORY_ENVELOPE_SCHEMA_ID in storage/sqlite_codec.py"
    )
    assert loaded.envelope.kind == "finding"
    assert loaded.envelope.confidence == "medium"
    assert loaded.envelope.scope.container_ref == "c1"
    assert loaded.envelope.scope.thread_ref == "t1"
    assert len(loaded.envelope.subjects) == 1
    assert loaded.envelope.subjects[0].kind == "surface"
    assert loaded.envelope.subjects[0].value == "Alice"
