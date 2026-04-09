"""Tests for incremental fact extraction in conversational_knowledge.

Covers watermark-based incremental extraction, dedup against existing facts,
supported_by relation scope, watermark propagation, backward compatibility,
and the rebuild_supersedes_prior=False behavior.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from capabilities.thread_aggregation import build_thread_aggregate, ThreadAggregate
from core.contracts import ProcessResult
from core.models import MemoryObject, SourceItem, new_id, utc_now
from providers.llm.base import LLMJsonResponse
from semantic.conversational_knowledge import (
    ConversationalKnowledgePlugin,
    FACT_TYPE,
    FACT_SCHEMA_ID,
    FACT_SCHEMA_VERSION,
    _resolve_extraction_watermark,
    _build_existing_facts_context,
    _dedup_extracted_facts,
)


# ── Helpers ─────────────────────────────────────────────────────────────────


class FactExtractionStub:
    """Stub LLM provider that tracks calls and returns configurable facts."""

    def __init__(self, facts: list[dict] | None = None):
        self.calls: list[str] = []
        self._facts = facts or [
            {"subject": "test", "statement": "Test fact from new items.", "category": "event"},
        ]

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        self.calls.append(user_prompt)
        payload = {"facts": list(self._facts)}
        return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)


def _make_source_item(
    content: str,
    *,
    role: str = "user",
    artifact_kind: str = "message",
    container_ref: str = "test-container",
    thread_ref: str = "test-thread",
    created_at: datetime | None = None,
    occurred_at: datetime | None = None,
    source_id: str | None = None,
    visibility: str = "public",
) -> SourceItem:
    now = created_at or utc_now()
    return SourceItem(
        source_type="chat_message",
        source_id=source_id or new_id(),
        content_type="text/plain",
        content=content,
        role=role,
        artifact_kind=artifact_kind,
        container_ref=container_ref,
        thread_ref=thread_ref,
        created_at=now,
        occurred_at=occurred_at or now,
        visibility=visibility,
    )


def _make_existing_fact(
    statement: str,
    *,
    subject: str = "test",
    category: str = "event",
    thread_ref: str = "test-thread",
    container_ref: str = "test-container",
    extraction_watermark: str | None = None,
    visibility: str = "public",
) -> MemoryObject:
    payload: dict = {
        "subject": subject,
        "statement": statement,
        "category": category,
        "thread_ref": thread_ref,
    }
    if extraction_watermark is not None:
        payload["extraction_watermark"] = extraction_watermark
    return MemoryObject(
        type=FACT_TYPE,
        schema_id=FACT_SCHEMA_ID,
        schema_version=FACT_SCHEMA_VERSION,
        payload=payload,
        visibility=visibility,
        container_ref=container_ref,
    )


def _make_plugin(stub: FactExtractionStub | None = None) -> tuple[ConversationalKnowledgePlugin, FactExtractionStub]:
    if stub is None:
        stub = FactExtractionStub()
    plugin = ConversationalKnowledgePlugin(provider=stub)
    return plugin, stub


# ── Unit tests: _resolve_extraction_watermark ───────────────────────────────


class TestResolveExtractionWatermark:
    def test_no_facts_returns_none(self):
        assert _resolve_extraction_watermark([]) is None

    def test_all_facts_with_watermark_returns_max(self):
        t1 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        facts = [
            _make_existing_fact("Fact A", extraction_watermark=t1.isoformat()),
            _make_existing_fact("Fact B", extraction_watermark=t2.isoformat()),
        ]
        result = _resolve_extraction_watermark(facts)
        assert result == t2

    def test_any_fact_missing_watermark_returns_none(self):
        """If even one fact lacks extraction_watermark, fall back to full extraction."""
        t1 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        facts = [
            _make_existing_fact("Fact A", extraction_watermark=t1.isoformat()),
            _make_existing_fact("Fact B"),  # no watermark
        ]
        result = _resolve_extraction_watermark(facts)
        assert result is None


# ── Unit tests: _dedup_extracted_facts ──────────────────────────────────────


class TestDedupExtractedFacts:
    def test_removes_duplicates_within_batch(self):
        facts = [
            {"subject": "Jordan", "statement": "Jordan ran a marathon", "category": "event"},
            {"subject": "Jordan", "statement": "Jordan ran a marathon", "category": "event"},
        ]
        result = _dedup_extracted_facts(facts)
        assert len(result) == 1

    def test_removes_duplicates_against_existing(self):
        existing = [
            {"subject": "Jordan", "statement": "Jordan ran a marathon", "category": "event"},
        ]
        new_facts = [
            {"subject": "Jordan", "statement": "Jordan ran a marathon", "category": "event"},
            {"subject": "Jordan", "statement": "Jordan likes coffee", "category": "preference"},
        ]
        result = _dedup_extracted_facts(new_facts, existing_facts=existing)
        assert len(result) == 1
        assert result[0]["statement"] == "Jordan likes coffee"

    def test_no_existing_facts_keeps_unique(self):
        facts = [
            {"subject": "A", "statement": "Fact A", "category": "event"},
            {"subject": "B", "statement": "Fact B", "category": "event"},
        ]
        result = _dedup_extracted_facts(facts, existing_facts=None)
        assert len(result) == 2


# ── Test 1: Incremental extraction skips old items ─────────────────────────


def test_incremental_extraction_skips_old_items():
    """Verify only new items (created_at > watermark) are sent to the LLM."""
    base_time = datetime(2026, 4, 1, 10, 0, 0, tzinfo=timezone.utc)
    watermark_time = base_time + timedelta(minutes=5)

    # Two old items (created_at <= watermark)
    old_item1 = _make_source_item("Old message one", created_at=base_time)
    old_item2 = _make_source_item(
        "Old message two",
        role="assistant",
        artifact_kind="assistant_output",
        created_at=watermark_time,
    )
    # Two new items (created_at > watermark)
    new_item1 = _make_source_item("New message one", created_at=watermark_time + timedelta(minutes=1))
    new_item2 = _make_source_item(
        "New message two",
        role="assistant",
        artifact_kind="assistant_output",
        created_at=watermark_time + timedelta(minutes=2),
    )

    all_items = [old_item1, old_item2, new_item1, new_item2]
    aggregate = build_thread_aggregate(all_items)

    existing_facts = [
        _make_existing_fact("Old fact.", extraction_watermark=watermark_time.isoformat()),
    ]

    plugin, stub = _make_plugin()
    result = plugin.build_thread_summary(aggregate, existing_facts)

    # LLM was called
    assert len(stub.calls) == 1
    # The prompt should contain new items but NOT old items
    prompt = stub.calls[0]
    assert "New message one" in prompt
    assert "New message two" in prompt
    assert "Old message one" not in prompt
    assert "Old message two" not in prompt
    # Should have produced memory objects
    assert len(result.memory_objects) > 0


# ── Test 2: No new items skips LLM ────────────────────────────────────────


def test_incremental_no_new_items_skips_llm():
    """Verify zero LLM calls when all items are covered by watermark."""
    base_time = datetime(2026, 4, 1, 10, 0, 0, tzinfo=timezone.utc)
    # Watermark covers all items
    watermark_time = base_time + timedelta(minutes=10)

    item1 = _make_source_item("Message one", created_at=base_time)
    item2 = _make_source_item(
        "Message two",
        role="assistant",
        artifact_kind="assistant_output",
        created_at=base_time + timedelta(minutes=5),
    )

    aggregate = build_thread_aggregate([item1, item2])
    existing_facts = [
        _make_existing_fact("Known fact.", extraction_watermark=watermark_time.isoformat()),
    ]

    plugin, stub = _make_plugin()
    result = plugin.build_thread_summary(aggregate, existing_facts)

    assert len(stub.calls) == 0
    assert len(result.memory_objects) == 0
    assert len(result.relations) == 0
    assert len(result.index_entries) == 0


# ── Test 3: Dedup against existing facts ──────────────────────────────────


def test_incremental_dedup_against_existing():
    """Verify new facts matching existing ones are dropped by dedup."""
    base_time = datetime(2026, 4, 1, 10, 0, 0, tzinfo=timezone.utc)
    watermark_time = base_time + timedelta(minutes=5)

    old_item = _make_source_item("Old message", created_at=base_time)
    new_item = _make_source_item("New message", created_at=watermark_time + timedelta(minutes=1))

    aggregate = build_thread_aggregate([old_item, new_item])

    # Existing fact with a specific statement
    existing_facts = [
        _make_existing_fact(
            "Item event time is used for reservation ordering.",
            subject="reservation ordering",
            extraction_watermark=watermark_time.isoformat(),
        ),
    ]

    # Stub returns the SAME fact that already exists, plus a new one
    stub = FactExtractionStub(facts=[
        {"subject": "reservation ordering", "statement": "Item event time is used for reservation ordering.", "category": "event"},
        {"subject": "catalog sync", "statement": "Catalog sync can cause delays.", "category": "event"},
    ])
    plugin, _ = _make_plugin(stub)
    result = plugin.build_thread_summary(aggregate, existing_facts)

    # Only the new (non-duplicate) fact should survive
    assert len(result.memory_objects) == 1
    assert result.memory_objects[0].payload["statement"] == "Catalog sync can cause delays."


# ── Test 4: supported_by links all thread items ───────────────────────────


def test_supported_by_links_all_thread_items():
    """Verify supported_by relations reference ALL source items (not just new)."""
    base_time = datetime(2026, 4, 1, 10, 0, 0, tzinfo=timezone.utc)
    watermark_time = base_time + timedelta(minutes=5)

    old_item = _make_source_item("Old message", created_at=base_time)
    new_item = _make_source_item("New message", created_at=watermark_time + timedelta(minutes=1))

    all_items = [old_item, new_item]
    aggregate = build_thread_aggregate(all_items)
    all_item_ids = {item.id for item in all_items}

    existing_facts = [
        _make_existing_fact("Prior fact.", extraction_watermark=watermark_time.isoformat()),
    ]

    plugin, stub = _make_plugin()
    result = plugin.build_thread_summary(aggregate, existing_facts)

    assert len(result.memory_objects) == 1
    # Each memory object should have supported_by relations for ALL items
    memory_id = result.memory_objects[0].id
    supported_by_relations = [
        r for r in result.relations
        if r.from_id == memory_id and r.relation_type == "supported_by"
    ]
    referenced_item_ids = {r.to_id for r in supported_by_relations}
    assert referenced_item_ids == all_item_ids, (
        f"Expected supported_by to reference all {len(all_item_ids)} items, "
        f"but got {len(referenced_item_ids)}"
    )


# ── Test 5: extraction_watermark in payload ───────────────────────────────


def test_extraction_watermark_in_payload():
    """Verify new facts contain extraction_watermark equal to max created_at of new items."""
    base_time = datetime(2026, 4, 1, 10, 0, 0, tzinfo=timezone.utc)
    watermark_time = base_time + timedelta(minutes=5)

    old_item = _make_source_item("Old message", created_at=base_time)
    new_item1 = _make_source_item("New message one", created_at=watermark_time + timedelta(minutes=1))
    new_item2 = _make_source_item(
        "New message two",
        role="assistant",
        artifact_kind="assistant_output",
        created_at=watermark_time + timedelta(minutes=3),
    )

    aggregate = build_thread_aggregate([old_item, new_item1, new_item2])

    existing_facts = [
        _make_existing_fact("Prior fact.", extraction_watermark=watermark_time.isoformat()),
    ]

    plugin, stub = _make_plugin()
    result = plugin.build_thread_summary(aggregate, existing_facts)

    assert len(result.memory_objects) > 0
    expected_watermark = (watermark_time + timedelta(minutes=3)).isoformat()
    for mo in result.memory_objects:
        assert mo.payload["extraction_watermark"] == expected_watermark, (
            f"Expected watermark {expected_watermark}, got {mo.payload['extraction_watermark']}"
        )


# ── Test 6: First extraction (no existing facts) → full extraction ────────


def test_first_extraction_full():
    """No existing facts → full extraction of all items."""
    base_time = datetime(2026, 4, 1, 10, 0, 0, tzinfo=timezone.utc)

    items = [
        _make_source_item("Message one", created_at=base_time),
        _make_source_item(
            "Message two",
            role="assistant",
            artifact_kind="assistant_output",
            created_at=base_time + timedelta(minutes=1),
        ),
        _make_source_item("Message three", created_at=base_time + timedelta(minutes=2)),
    ]

    aggregate = build_thread_aggregate(items)

    plugin, stub = _make_plugin()
    result = plugin.build_thread_summary(aggregate, conclusions=[])

    # LLM was called with all items
    assert len(stub.calls) == 1
    prompt = stub.calls[0]
    assert "Message one" in prompt
    assert "Message two" in prompt
    assert "Message three" in prompt

    # Facts were produced with watermark = max created_at
    assert len(result.memory_objects) > 0
    expected_watermark = (base_time + timedelta(minutes=2)).isoformat()
    for mo in result.memory_objects:
        assert mo.payload["extraction_watermark"] == expected_watermark


# ── Test 7: Pre-migration fallback ───────────────────────────────────────


def test_pre_migration_fallback():
    """Existing facts without extraction_watermark → full extraction of all items."""
    base_time = datetime(2026, 4, 1, 10, 0, 0, tzinfo=timezone.utc)

    items = [
        _make_source_item("Message one", created_at=base_time),
        _make_source_item(
            "Message two",
            role="assistant",
            artifact_kind="assistant_output",
            created_at=base_time + timedelta(minutes=1),
        ),
    ]

    aggregate = build_thread_aggregate(items)

    # Pre-migration facts: no extraction_watermark field
    existing_facts = [
        _make_existing_fact("Legacy fact A."),
        _make_existing_fact("Legacy fact B."),
    ]

    plugin, stub = _make_plugin()
    result = plugin.build_thread_summary(aggregate, existing_facts)

    # Should do full extraction (all items sent to LLM)
    assert len(stub.calls) == 1
    prompt = stub.calls[0]
    assert "Message one" in prompt
    assert "Message two" in prompt

    # New facts should have the watermark set
    assert len(result.memory_objects) > 0
    for mo in result.memory_objects:
        assert "extraction_watermark" in mo.payload


def test_pre_migration_fallback_mixed_watermarks():
    """If even ONE pre-migration fact lacks watermark, full extraction triggers."""
    base_time = datetime(2026, 4, 1, 10, 0, 0, tzinfo=timezone.utc)

    items = [
        _make_source_item("Message one", created_at=base_time),
        _make_source_item(
            "Message two",
            role="assistant",
            artifact_kind="assistant_output",
            created_at=base_time + timedelta(minutes=1),
        ),
    ]

    aggregate = build_thread_aggregate(items)

    existing_facts = [
        _make_existing_fact("New fact.", extraction_watermark=base_time.isoformat()),
        _make_existing_fact("Legacy fact."),  # no watermark
    ]

    plugin, stub = _make_plugin()
    result = plugin.build_thread_summary(aggregate, existing_facts)

    # Full extraction — both items sent
    assert len(stub.calls) == 1
    prompt = stub.calls[0]
    assert "Message one" in prompt
    assert "Message two" in prompt


# ── Test 8: rebuild_supersedes_prior=False → empty supersede plan ─────────


def test_rebuild_supersedes_prior_false_empty_supersede_plan():
    """ConversationalKnowledgePlugin.rebuild_supersedes_prior returns False,
    which means ThreadRebuilder produces an empty supersede_plan."""
    plugin = ConversationalKnowledgePlugin(provider=FactExtractionStub())
    assert plugin.rebuild_supersedes_prior is False

    # Simulate the logic from ThreadRebuilder._maybe_rebuild_thread_summary
    # When rebuild_supersedes_prior is False, the supersede_plan stays empty
    supersede_plan: dict[str, list[str]] = {}
    if getattr(plugin, 'rebuild_supersedes_prior', True):
        # This branch should NOT execute for conversational_knowledge
        supersede_plan["fake-id"] = ["old-id"]

    assert supersede_plan == {}, (
        "Expected empty supersede_plan when rebuild_supersedes_prior=False"
    )


# ── Test 9: agent_conversation_memory still gets full supersession ────────


def test_rebuild_supersedes_prior_default_true():
    """The base ThreadAggregationSemanticPlugin defaults to rebuild_supersedes_prior=True."""
    from semantic.agent_conversation_memory import AgentConversationMemoryPlugin
    from tests.test_thread_aggregation import ThreadAwareStubProvider

    plugin = AgentConversationMemoryPlugin(
        provider=ThreadAwareStubProvider(),
        prompt_variant="strict_typed_memory_v6_work_state_examples",
    )
    assert plugin.rebuild_supersedes_prior is True


# ── Test 10: E2E incremental thread lifecycle ─────────────────────────────


def test_e2e_incremental_thread_lifecycle(monkeypatch, test_db_url: str):
    """Integration test: ingest 2 msgs + process, ingest 2 more + process,
    verify only new items extracted on second pass."""
    from tests.test_thread_summary_accumulation import (
        DualPackageStubProvider,
        _dual_package_config,
        _collect_memory,
    )
    from app.main import create_app
    from fastapi.testclient import TestClient

    # Use a call-counting stub to track extraction calls
    extraction_call_prompts: list[str] = []

    class IncrementalTrackingStub(DualPackageStubProvider):
        def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
            # Detect fact extraction calls
            if "atomic fact" in system_prompt.lower() or '"category"' in schema_description:
                extraction_call_prompts.append(user_prompt)
                # Return different facts based on call number
                call_num = len(extraction_call_prompts)
                if call_num == 1:
                    payload = {"facts": [
                        {"subject": "reservation ordering", "statement": "Item event time is used for reservation ordering.", "category": "event"},
                    ]}
                else:
                    payload = {"facts": [
                        {"subject": "catalog sync", "statement": "Catalog sync delays can cause skipped holds.", "category": "event"},
                    ]}
                return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)
            return super().generate_json(system_prompt=system_prompt, user_prompt=user_prompt, schema_description=schema_description)

    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: IncrementalTrackingStub())
    config = _dual_package_config(test_db_url)
    app = create_app(config)
    client = TestClient(app)
    service = app.state.pallium_service

    thread_ref = "chat:test:thread-incremental-e2e"
    container_ref = "chat:test"

    # Phase 1: Ingest 2 messages and process
    for msg in [
        {
            "source_type": "chat_message",
            "source_id": "incr-e2e-1",
            "content_type": "text/plain",
            "content": "Why are some library holds disappearing after catalog sync delays?",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": container_ref,
            "thread_ref": thread_ref,
            "visibility": "public",
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "incr-e2e-2",
            "content_type": "text/plain",
            "content": "Decision: use item event time for reservation ordering to avoid skipped holds during sync delays.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": thread_ref,
            "visibility": "public",
        },
    ]:
        client.post("/items", json=[msg])
        service.drain_processing_queue(worker_id="drain-worker")

    facts_after_phase1 = _collect_memory(service._storage, container_ref, thread_ref, FACT_TYPE)
    active_facts_phase1 = [f for f in facts_after_phase1 if f.lifecycle == "active"]
    calls_after_phase1 = len(extraction_call_prompts)

    assert len(active_facts_phase1) >= 1, "Expected at least 1 active fact after phase 1"
    assert calls_after_phase1 >= 1, "Expected at least 1 LLM extraction call after phase 1"

    # Phase 1 call should have included both messages
    phase1_prompt = extraction_call_prompts[0]
    assert "library holds" in phase1_prompt.lower() or "catalog sync" in phase1_prompt.lower()

    # Phase 2: Ingest 2 more messages and process
    for msg in [
        {
            "source_type": "chat_message",
            "source_id": "incr-e2e-3",
            "content_type": "text/plain",
            "content": "Good, that should fix the holds. Will the sync delays also affect due-date calculations?",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": container_ref,
            "thread_ref": thread_ref,
            "visibility": "public",
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "incr-e2e-4",
            "content_type": "text/plain",
            "content": "Due-date calculations use a different timestamp path, so they are not affected by the ordering change.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": thread_ref,
            "visibility": "public",
        },
    ]:
        client.post("/items", json=[msg])
        service.drain_processing_queue(worker_id="drain-worker")

    facts_after_phase2 = _collect_memory(service._storage, container_ref, thread_ref, FACT_TYPE)
    active_facts_phase2 = [f for f in facts_after_phase2 if f.lifecycle == "active"]
    calls_after_phase2 = len(extraction_call_prompts)

    # More extraction calls happened in phase 2
    assert calls_after_phase2 > calls_after_phase1, (
        f"Expected additional LLM calls in phase 2, got {calls_after_phase2} total vs {calls_after_phase1} after phase 1"
    )

    # Phase 2 extraction should only contain the new messages, not the old ones
    phase2_prompts = extraction_call_prompts[calls_after_phase1:]
    assert any("fix the holds" in p.lower() or "due-date" in p.lower() for p in phase2_prompts), \
        "Expected at least one phase 2 prompt to contain new message content"
    for prompt in phase2_prompts:
        has_new_content = ("fix the holds" in prompt.lower() or "due-date" in prompt.lower())
        # Old messages should NOT be present (incremental extraction)
        has_old_content = ("library holds disappearing" in prompt.lower() or "use item event time" in prompt.lower())
        if has_new_content:
            assert not has_old_content, (
                "Phase 2 extraction prompt should not contain old messages "
                "(incremental extraction should skip already-extracted items)"
            )

    # Facts from both phases should be active (rebuild_supersedes_prior=False)
    assert len(active_facts_phase2) >= len(active_facts_phase1), (
        f"Expected facts to accumulate (rebuild_supersedes_prior=False), "
        f"got {len(active_facts_phase2)} after phase 2 vs {len(active_facts_phase1)} after phase 1"
    )


# ── Edge case: watermark boundary is strict greater-than ──────────────────


def test_watermark_comparison_is_strict_greater_than():
    """Items with created_at == watermark should NOT be re-extracted."""
    base_time = datetime(2026, 4, 1, 10, 0, 0, tzinfo=timezone.utc)
    watermark_time = base_time + timedelta(minutes=5)

    # Item at exactly the watermark time
    item_at_watermark = _make_source_item("Message at watermark", created_at=watermark_time)
    # Item before watermark
    old_item = _make_source_item("Old message", created_at=base_time)
    # Item after watermark
    new_item = _make_source_item(
        "New message after watermark",
        role="assistant",
        artifact_kind="assistant_output",
        created_at=watermark_time + timedelta(minutes=1),
    )

    aggregate = build_thread_aggregate([old_item, item_at_watermark, new_item])

    existing_facts = [
        _make_existing_fact("Known fact.", extraction_watermark=watermark_time.isoformat()),
    ]

    plugin, stub = _make_plugin()
    result = plugin.build_thread_summary(aggregate, existing_facts)

    assert len(stub.calls) == 1
    prompt = stub.calls[0]
    # Only the item AFTER the watermark should be in the prompt
    assert "New message after watermark" in prompt
    assert "Message at watermark" not in prompt
    assert "Old message" not in prompt


# ── Edge case: single item thread is skipped ─────────────────────────────


def test_single_item_thread_skipped():
    """Thread with fewer than 2 items should produce no output."""
    base_time = datetime(2026, 4, 1, 10, 0, 0, tzinfo=timezone.utc)
    item = _make_source_item("Only message", created_at=base_time)
    aggregate = build_thread_aggregate([item])

    plugin, stub = _make_plugin()
    result = plugin.build_thread_summary(aggregate, conclusions=[])

    assert len(stub.calls) == 0
    assert len(result.memory_objects) == 0


# ── Edge case: existing facts context passed to LLM ──────────────────────


def test_existing_facts_context_included_in_llm_prompt():
    """When there are existing facts, they should be included in the LLM prompt
    so the LLM knows not to re-extract them."""
    base_time = datetime(2026, 4, 1, 10, 0, 0, tzinfo=timezone.utc)
    watermark_time = base_time + timedelta(minutes=5)

    old_item = _make_source_item("Old message", created_at=base_time)
    new_item = _make_source_item("New message", created_at=watermark_time + timedelta(minutes=1))

    aggregate = build_thread_aggregate([old_item, new_item])

    existing_facts = [
        _make_existing_fact(
            "Reservation ordering uses item event time.",
            subject="reservation ordering",
            extraction_watermark=watermark_time.isoformat(),
        ),
    ]

    plugin, stub = _make_plugin()
    result = plugin.build_thread_summary(aggregate, existing_facts)

    assert len(stub.calls) == 1
    prompt = stub.calls[0]
    # The prompt should mention the existing fact for the LLM to avoid re-extraction
    assert "Previously extracted facts" in prompt
    assert "Reservation ordering uses item event time." in prompt


# ── Unit tests: _build_existing_facts_context ─────────────────────────────


class TestBuildExistingFactsContext:
    def test_converts_memory_objects_to_dicts(self):
        facts = [
            _make_existing_fact("Statement A.", subject="SubjectA", category="event"),
            _make_existing_fact("Statement B.", subject="SubjectB", category="preference"),
        ]
        context = _build_existing_facts_context(facts)
        assert len(context) == 2
        assert context[0] == {"subject": "SubjectA", "statement": "Statement A.", "category": "event"}
        assert context[1] == {"subject": "SubjectB", "statement": "Statement B.", "category": "preference"}

    def test_empty_list_returns_empty(self):
        assert _build_existing_facts_context([]) == []
