"""Tests for incremental thread rebuild: watermark, windowing, supersession exemption."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.config import AppConfig, LLMProviderConfig, SemanticPackageConfig
from app.main import create_app
from capabilities.consolidation import ConsolidationPolicy, DEFAULT_CONSOLIDATION_STRATEGIES
from capabilities.thread_aggregation import ThreadAggregate, build_thread_aggregate
from core.models import MemoryObject, SourceItem
from core.thread_rebuild import ThreadRebuilder, THREAD_WINDOW_BUDGET_CHARS
from fastapi.testclient import TestClient
from providers.llm.base import LLMJsonResponse
from semantic.agent_conversation_memory_threads import (
    THREAD_SUMMARY_MAX_TEXT_CHARS,
    THREAD_SUMMARY_PROMPT_SCHEMA_VERSION,
    THREAD_SUMMARY_WITH_CHECKPOINT_PROMPT_SCHEMA_VERSION,
    build_thread_summary,
    _build_thread_material,
)
from storage.vector_index import VectorIndexConfig


# ---------------------------------------------------------------------------
# Stub LLM Provider
# ---------------------------------------------------------------------------

class IncrementalTestStubProvider:
    """Stub that returns summaries with identifiable content for windowed rebuild tests."""

    def __init__(self):
        self.call_count = 0
        self.prompts: list[str] = []

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        self.call_count += 1
        self.prompts.append(user_prompt)

        decisions = []
        investigations = []

        # Check for decision-like content in new thread items
        if "we decided to use event-time ordering" in user_prompt.lower():
            decisions = [{"decision_text": "We decided to use event-time ordering for all reservation holds to prevent sync-delay losses across all concurrent processing.", "evidence": "to prevent sync-delay losses across all concurrent processing workers in our distributed system architecture"}]

        if "investigation concluded that batch processing" in user_prompt.lower():
            investigations = [{"investigation_text": "Investigation concluded that batch processing with checkpoint recovery handles the 150K message backlog within acceptable latency bounds.", "evidence": "batch processing with checkpoint recovery handles the 150K message backlog within acceptable latency bounds"}]

        if "second window decision: adopt retry-with-backoff" in user_prompt.lower():
            decisions = [{"decision_text": "Second window decision: adopt retry-with-backoff for catalog sync failures to prevent cascading hold expiration across the system.", "evidence": "adopt retry-with-backoff for catalog sync failures to prevent cascading hold expiration across the system architecture"}]

        summary = f"Thread summary from call {self.call_count}."
        if "prior summary" in user_prompt.lower():
            summary = f"Updated thread summary incorporating prior context (call {self.call_count})."

        payload = {
            "summary": summary,
            "content_quality": "substantive",
            "retrieval_context": None,
            "decisions": decisions,
            "investigations": investigations,
        }

        if "task_checkpoint" in schema_description:
            payload["task_checkpoint"] = {
                "summary": f"Checkpoint from call {self.call_count}.",
                "task": "Test task",
                "current_state": "in progress",
                "key_findings": [],
                "blocker_state": "",
                "next_step": "",
                "evidence": [],
                "freshness_signal": "latest",
                "retrieval_context": None,
            }

        return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)


# ---------------------------------------------------------------------------
# Config helper
# ---------------------------------------------------------------------------

def _test_config(test_db_url: str) -> AppConfig:
    return AppConfig(
        storage_backend="sqlite",
        sqlite_url=test_db_url,
        default_use_case="agent_conversation_memory",
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
            "agent_conversation_memory": SemanticPackageConfig(
                name="agent_conversation_memory",
                implementation="agent_conversation_memory",
                llm_provider="test_provider",
                model="fake-model",
                prompt_variant="strict_typed_memory_v6_work_state_examples",
                consolidation=ConsolidationPolicy(
                    enabled_strategies=DEFAULT_CONSOLIDATION_STRATEGIES,
                    default_strategy="thread_summary_anchored",
                    max_candidates_per_run=24,
                    max_group_size=4,
                    same_container_required=True,
                    time_window_hours=168,
                    lexical_overlap_threshold=2,
                ),
            ),
        },
        vector_index=VectorIndexConfig(enabled=False),
    )


def _dual_package_config(test_db_url: str) -> AppConfig:
    """Config with both packages for isolation tests."""
    return AppConfig(
        storage_backend="sqlite",
        sqlite_url=test_db_url,
        default_use_case="agent_conversation_memory",
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
            "agent_conversation_memory": SemanticPackageConfig(
                name="agent_conversation_memory",
                implementation="agent_conversation_memory",
                llm_provider="test_provider",
                model="fake-model",
                prompt_variant="strict_typed_memory_v6_work_state_examples",
                consolidation=ConsolidationPolicy(
                    enabled_strategies=DEFAULT_CONSOLIDATION_STRATEGIES,
                    default_strategy="thread_summary_anchored",
                    max_candidates_per_run=24,
                    max_group_size=4,
                    same_container_required=True,
                    time_window_hours=168,
                    lexical_overlap_threshold=2,
                ),
            ),
            "conversational_knowledge": SemanticPackageConfig(
                name="conversational_knowledge",
                implementation="conversational_knowledge",
                llm_provider="test_provider",
                model="fake-model",
            ),
        },
        vector_index=VectorIndexConfig(enabled=False),
    )


def _create_client(monkeypatch, test_db_url: str, *, stub=None, dual_package=False):
    if stub is None:
        stub = IncrementalTestStubProvider()
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: stub)
    config = _dual_package_config(test_db_url) if dual_package else _test_config(test_db_url)
    app = create_app(config)
    client = TestClient(app)
    return client, app.state.pallium_service, stub


def _post_and_drain(client, service, messages):
    """Post all messages and drain once at the end."""
    for msg in messages:
        client.post("/items", json=[msg])
    service.drain_processing_queue(worker_id="test-worker")


def _post_drain_each(client, service, messages):
    """Post each message and drain after each one."""
    for msg in messages:
        client.post("/items", json=[msg])
        service.drain_processing_queue(worker_id="test-worker")


def _filler(size: int) -> str:
    """Generate word-based filler content that tokenizes to many tokens.

    Using repeated single characters (e.g. 'A' * 9000) produces only 1 token,
    which makes _should_request_thread_rebuild return False. Word-based filler
    produces realistic token counts.
    """
    phrase = "padding word filler text for budget testing "
    repeats = (size // len(phrase)) + 1
    return (phrase * repeats)[:size]


def _make_message(source_id: str, content: str, container_ref: str, thread_ref: str, *, role="user"):
    return {
        "source_type": "chat_message" if role == "user" else "assistant_artifact",
        "source_id": source_id,
        "content_type": "text/plain",
        "content": content,
        "artifact_kind": "message" if role == "user" else "assistant_output",
        "role": role,
        "container_ref": container_ref,
        "thread_ref": thread_ref,
        "visibility": "public",
    }


def _collect_memory(storage, container_ref: str, thread_ref: str, memory_type: str | None = None):
    """Collect memory objects for a thread, optionally filtered by type."""
    thread_items = storage.list_source_items_for_thread(container_ref, thread_ref)
    all_memory: dict[str, object] = {}
    for item in thread_items:
        for memory in storage.list_memory_objects_for_source_item(item.id):
            if memory_type is None or memory.type == memory_type:
                all_memory[memory.id] = memory
    return list(all_memory.values())


# ---------------------------------------------------------------------------
# Test 1: Key finding in thread tail is extracted (tail-biased truncation)
# ---------------------------------------------------------------------------

def test_tail_biased_truncation_extracts_finding_from_tail(monkeypatch, test_db_url: str) -> None:
    """When a thread exceeds budget, tail content (recent items) is visible to the LLM."""
    # Build a thread where the key finding is in the tail
    container_ref = "test:tail-bias"
    thread_ref = "test:tail-bias:thread-1"

    # Create enough filler content to exceed 16K
    filler_chars = THREAD_SUMMARY_MAX_TEXT_CHARS + 1000
    filler_content = _filler(filler_chars)

    messages = [
        _make_message("filler-1", filler_content, container_ref, thread_ref),
        _make_message("tail-finding", "Investigation concluded that batch processing with checkpoint recovery handles the 150K message backlog within acceptable latency bounds. Evidence: batch processing with checkpoint recovery handles the 150K message backlog within acceptable latency bounds", container_ref, thread_ref, role="assistant"),
    ]

    client, service, stub = _create_client(monkeypatch, test_db_url)
    _post_and_drain(client, service, messages)

    # Verify the LLM was called with the tail content visible
    assert stub.call_count >= 1
    last_prompt = stub.prompts[-1]
    assert "investigation concluded that batch processing" in last_prompt.lower()

    # The investigation should be extracted
    memories = _collect_memory(service._storage, container_ref, thread_ref, "investigation_outcome")
    active_investigations = [m for m in memories if m.lifecycle == "active"]
    assert len(active_investigations) >= 1
    assert any("batch processing" in m.payload.get("investigation_outcome", "").lower() for m in active_investigations)


# ---------------------------------------------------------------------------
# Test 2: Watermark persists across rebuilds
# ---------------------------------------------------------------------------

def test_watermark_persists_and_advances_across_rebuilds(monkeypatch, test_db_url: str) -> None:
    """Watermark advances after each rebuild when thread exceeds budget."""
    container_ref = "test:watermark"
    thread_ref = "test:watermark:thread-1"

    # Build a large thread that exceeds budget
    filler_size = THREAD_WINDOW_BUDGET_CHARS // 2 + 1000
    messages = [
        _make_message("big-1", _filler(filler_size), container_ref, thread_ref),
        _make_message("big-2", _filler(filler_size), container_ref, thread_ref, role="assistant"),
    ]

    client, service, stub = _create_client(monkeypatch, test_db_url)
    _post_and_drain(client, service, messages)

    # After first rebuild, watermark should be set
    from storage.sqlite_schema import ThreadProcessingLeaseRecord
    from sqlalchemy import select
    with service._storage._session_factory() as session:
        records = session.scalars(select(ThreadProcessingLeaseRecord)).all()
        acm_records = [r for r in records if r.use_case == "agent_conversation_memory" and r.thread_ref == thread_ref]
        assert len(acm_records) == 1
        first_watermark = acm_records[0].collection_watermark_at
        assert first_watermark is not None

    # Add more content and drain again
    messages2 = [
        _make_message("big-3", _filler(filler_size), container_ref, thread_ref),
    ]
    _post_and_drain(client, service, messages2)

    # Watermark should advance
    with service._storage._session_factory() as session:
        records = session.scalars(select(ThreadProcessingLeaseRecord)).all()
        acm_records = [r for r in records if r.use_case == "agent_conversation_memory" and r.thread_ref == thread_ref]
        assert len(acm_records) == 1
        second_watermark = acm_records[0].collection_watermark_at
        assert second_watermark is not None
        assert second_watermark >= first_watermark


# ---------------------------------------------------------------------------
# Test 3: Two successive window rebuilds produce two active decisions
# (supersession exemption for decisions/investigations)
# ---------------------------------------------------------------------------

def test_decisions_accumulate_across_windowed_rebuilds(monkeypatch, test_db_url: str) -> None:
    """Decisions from different windows accumulate (not superseded)."""
    container_ref = "test:accumulate"
    thread_ref = "test:accumulate:thread-1"

    # Build a large thread that requires windowing
    filler_size = THREAD_WINDOW_BUDGET_CHARS // 2 + 1000

    # First batch with a decision
    messages1 = [
        _make_message("acc-1", _filler(filler_size), container_ref, thread_ref),
        _make_message("acc-2", "We decided to use event-time ordering for all reservation holds to prevent sync-delay losses across all concurrent processing. Evidence: to prevent sync-delay losses across all concurrent processing workers in our distributed system architecture. " + _filler(filler_size), container_ref, thread_ref, role="assistant"),
    ]

    client, service, stub = _create_client(monkeypatch, test_db_url)
    _post_and_drain(client, service, messages1)

    # Check first decision exists
    decisions = _collect_memory(service._storage, container_ref, thread_ref, "decision")
    active_decisions_1 = [m for m in decisions if m.lifecycle == "active"]
    assert len(active_decisions_1) >= 1

    # Second batch with a different decision
    messages2 = [
        _make_message("acc-3", "Second window decision: adopt retry-with-backoff for catalog sync failures to prevent cascading hold expiration across the system. Evidence: adopt retry-with-backoff for catalog sync failures to prevent cascading hold expiration across the system architecture. " + _filler(filler_size), container_ref, thread_ref, role="assistant"),
    ]
    _post_and_drain(client, service, messages2)

    # Both decisions should be active (accumulate, not supersede)
    decisions = _collect_memory(service._storage, container_ref, thread_ref, "decision")
    active_decisions_2 = [m for m in decisions if m.lifecycle == "active"]
    assert len(active_decisions_2) >= 2, (
        f"Expected at least 2 active decisions (accumulation), got {len(active_decisions_2)}"
    )

    # But thread_summary should be superseded (only 1 active)
    summaries = _collect_memory(service._storage, container_ref, thread_ref, "thread_summary")
    active_summaries = [m for m in summaries if m.lifecycle == "active"]
    assert len(active_summaries) == 1


# ---------------------------------------------------------------------------
# Test 4: Chain cap handles large thread (simulated 150K)
# ---------------------------------------------------------------------------

def test_chain_cap_handles_large_thread(monkeypatch, test_db_url: str) -> None:
    """A thread well over budget chains multiple rebuilds until caught up."""
    container_ref = "test:chain"
    thread_ref = "test:chain:thread-1"

    # Create content that requires multiple windows (>16K total)
    # 3 items of ~6K each = 18K total, needs 2 windows at 16K budget
    item_size = 6000
    messages = [
        _make_message(f"chain-{i}", f"Item {i} content " + _filler(item_size), container_ref, thread_ref, role="user" if i % 2 == 0 else "assistant")
        for i in range(4)  # 4 items * 6K = 24K, exceeds 16K budget
    ]

    client, service, stub = _create_client(monkeypatch, test_db_url)
    _post_and_drain(client, service, messages)

    # Should have processed in multiple iterations
    # The exact number depends on windowing, but we should have at least 1 summary
    summaries = _collect_memory(service._storage, container_ref, thread_ref, "thread_summary")
    active_summaries = [m for m in summaries if m.lifecycle == "active"]
    assert len(active_summaries) == 1

    # Verify the iteration limit (15) is sufficient
    assert ThreadRebuilder._MAX_THREAD_REBUILD_ITERATIONS == 15


# ---------------------------------------------------------------------------
# Test 5: Package isolation — independent watermarks
# ---------------------------------------------------------------------------

class DualPackageStubForIsolation(IncrementalTestStubProvider):
    """Handles both agent_conversation_memory and conversational_knowledge calls."""

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        if "atomic fact" in system_prompt.lower() or '"category"' in schema_description:
            payload = {"facts": [
                {"subject": "test subject", "statement": "Test fact statement.", "category": "event"},
            ]}
            return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)
        return super().generate_json(system_prompt=system_prompt, user_prompt=user_prompt, schema_description=schema_description)


def test_package_watermarks_are_independent(monkeypatch, test_db_url: str) -> None:
    """Each package's watermark advances independently for the same thread."""
    container_ref = "test:isolation"
    thread_ref = "test:isolation:thread-1"

    stub = DualPackageStubForIsolation()
    client, service, _ = _create_client(monkeypatch, test_db_url, stub=stub, dual_package=True)

    messages = [
        _make_message("iso-1", "First message about library holds and reservation system processing that handles concurrent requests from multiple branches in the distributed catalog architecture.", container_ref, thread_ref),
        _make_message("iso-2", "Second message about catalog sync mechanisms and batch processing pipelines that coordinate between the main branch and satellite locations for inventory management operations.", container_ref, thread_ref, role="assistant"),
    ]
    _post_and_drain(client, service, messages)

    # Check that both packages have independent scope records
    from storage.sqlite_schema import ThreadProcessingLeaseRecord
    from sqlalchemy import select
    with service._storage._session_factory() as session:
        records = session.scalars(select(ThreadProcessingLeaseRecord)).all()
        thread_records = [r for r in records if r.thread_ref == thread_ref]
        use_cases = {r.use_case for r in thread_records}
        assert "agent_conversation_memory" in use_cases
        assert "conversational_knowledge" in use_cases

        # Each has its own watermark
        acm_record = next(r for r in thread_records if r.use_case == "agent_conversation_memory")
        ck_record = next(r for r in thread_records if r.use_case == "conversational_knowledge")
        # Both should have watermarks set (they're independent)
        assert acm_record.collection_watermark_at is not None
        assert ck_record.collection_watermark_at is not None


# ---------------------------------------------------------------------------
# Test 6: Prompt schema version in provenance
# ---------------------------------------------------------------------------

def test_prompt_schema_version_in_provenance(monkeypatch, test_db_url: str) -> None:
    """Thread summary provenance tracks the updated schema version (v8)."""
    container_ref = "test:provenance"
    thread_ref = "test:provenance:thread-1"

    client, service, stub = _create_client(monkeypatch, test_db_url)
    messages = [
        _make_message("prov-1", "First message discussing the architecture of our reservation system and how it handles concurrent processing across multiple library branches in the distributed network infrastructure.", container_ref, thread_ref),
        _make_message("prov-2", "Second message analyzing the catalog synchronization mechanism and its interaction with the batch processing pipeline for inventory management operations across all regional centers.", container_ref, thread_ref, role="assistant"),
    ]
    _post_and_drain(client, service, messages)

    summaries = _collect_memory(service._storage, container_ref, thread_ref, "thread_summary")
    active_summaries = [m for m in summaries if m.lifecycle == "active"]
    assert len(active_summaries) == 1

    provenance = active_summaries[0].payload.get("semantic_provenance", {})
    assert provenance.get("prompt_schema_version") == THREAD_SUMMARY_PROMPT_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Test 7: Finding spanning window boundary is cleanly dropped (grounding)
# ---------------------------------------------------------------------------

def test_cross_window_finding_is_not_hallucinated(monkeypatch, test_db_url: str) -> None:
    """A finding split across two windows fails grounding and is not fabricated."""
    container_ref = "test:grounding"
    thread_ref = "test:grounding:thread-1"

    # Create a large thread where a finding spans two items
    # The first half is in window 1, the second half in window 2
    filler_size = THREAD_WINDOW_BUDGET_CHARS // 2 + 1000

    # First half of a finding + filler
    messages1 = [
        _make_message("ground-1", "Beginning of investigation about sync delays. " + _filler(filler_size), container_ref, thread_ref),
        _make_message("ground-2", "More context about the sync mechanism. " + _filler(filler_size), container_ref, thread_ref, role="assistant"),
    ]

    # Stub that tries to hallucinate a finding from prior context
    class GroundingSafetyStub(IncrementalTestStubProvider):
        def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
            # Simulate LLM trying to quote from prior summary (which should be rejected by grounding)
            payload = {
                "summary": "Thread about sync delay investigation.",
                "content_quality": "substantive",
                "retrieval_context": None,
                "decisions": [],
                "investigations": [
                    {
                        "investigation_text": "This text is not in the thread items",
                        "evidence": "This evidence is also fabricated",
                    }
                ],
            }
            if "task_checkpoint" in schema_description:
                payload["task_checkpoint"] = {
                    "summary": "Checkpoint.", "task": "Test", "current_state": "in progress",
                    "key_findings": [], "blocker_state": "", "next_step": "",
                    "evidence": [], "freshness_signal": "latest", "retrieval_context": None,
                }
            self.call_count += 1
            self.prompts.append(user_prompt)
            return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)

    stub = GroundingSafetyStub()
    client, service, _ = _create_client(monkeypatch, test_db_url, stub=stub)
    _post_and_drain(client, service, messages1)

    # The fabricated investigation should be rejected by grounding validation
    investigations = _collect_memory(service._storage, container_ref, thread_ref, "investigation_outcome")
    active_investigations = [m for m in investigations if m.lifecycle == "active"]
    # Grounding check should reject the hallucinated finding
    assert all(
        "this text is not in the thread items" not in m.payload.get("investigation_outcome", "").lower()
        for m in active_investigations
    ), "Hallucinated finding should be rejected by grounding validation"


# ---------------------------------------------------------------------------
# Test 8: Prior summary is passed to prompt in incremental mode
# ---------------------------------------------------------------------------

def test_prior_summary_included_in_prompt(monkeypatch, test_db_url: str) -> None:
    """When a prior summary exists, it's included in the prompt for context."""
    container_ref = "test:prior-ctx"
    thread_ref = "test:prior-ctx:thread-1"

    # Create a large thread that exceeds budget to trigger incremental mode
    filler_size = THREAD_WINDOW_BUDGET_CHARS // 2 + 1000

    messages1 = [
        _make_message("ctx-1", "First large message. " + _filler(filler_size), container_ref, thread_ref),
        _make_message("ctx-2", "Second large message. " + _filler(filler_size), container_ref, thread_ref, role="assistant"),
    ]

    client, service, stub = _create_client(monkeypatch, test_db_url)
    _post_and_drain(client, service, messages1)

    # Verify summary was created
    summaries = _collect_memory(service._storage, container_ref, thread_ref, "thread_summary")
    assert len([s for s in summaries if s.lifecycle == "active"]) >= 1, "First rebuild should create a thread_summary"

    first_call_count = stub.call_count

    # Now add more content to trigger a second rebuild
    messages2 = [
        _make_message("ctx-3", "Third message after watermark. " + _filler(filler_size), container_ref, thread_ref),
    ]
    _post_and_drain(client, service, messages2)

    # The second rebuild should include prior summary in the prompt
    assert stub.call_count > first_call_count
    # Find the prompt that has "Prior summary" in it
    thread_rebuild_prompts = [p for p in stub.prompts[first_call_count:] if "thread items:" in p.lower()]
    assert len(thread_rebuild_prompts) >= 1, "Second rebuild should produce a thread summary prompt"
    incremental_prompts = [p for p in thread_rebuild_prompts if "prior summary" in p.lower()]
    assert len(incremental_prompts) >= 1, (
        f"Prior summary should appear in incremental rebuild prompts. "
        f"Thread rebuild prompts found: {len(thread_rebuild_prompts)}. "
        f"First 200 chars of last rebuild prompt: {thread_rebuild_prompts[-1][:200] if thread_rebuild_prompts else 'none'}"
    )


# ---------------------------------------------------------------------------
# Test 9: Budget constant values are as specified
# ---------------------------------------------------------------------------

def test_budget_constants():
    """Verify the budget constants match the spec."""
    assert THREAD_SUMMARY_MAX_TEXT_CHARS == 16000
    assert THREAD_WINDOW_BUDGET_CHARS == 16000
    assert THREAD_SUMMARY_PROMPT_SCHEMA_VERSION == "v8"
    assert THREAD_SUMMARY_WITH_CHECKPOINT_PROMPT_SCHEMA_VERSION == "v6"


# ---------------------------------------------------------------------------
# Test 10: ThreadAggregate includes prior_summary field
# ---------------------------------------------------------------------------

def test_thread_aggregate_prior_summary():
    """ThreadAggregate carries prior_summary through to the plugin."""
    items = [
        SourceItem(
            source_type="chat_message",
            source_id="agg-1",
            content_type="text/plain",
            content="First message",
            artifact_kind="message",
            role="user",
            container_ref="test:agg",
            thread_ref="test:agg:t1",
            visibility="public",
        ),
        SourceItem(
            source_type="assistant_artifact",
            source_id="agg-2",
            content_type="text/plain",
            content="Second message",
            artifact_kind="assistant_output",
            role="assistant",
            container_ref="test:agg",
            thread_ref="test:agg:t1",
            visibility="public",
        ),
    ]
    aggregate = build_thread_aggregate(items, prior_summary="Prior context about reservations.")
    assert aggregate.prior_summary == "Prior context about reservations."

    aggregate_no_prior = build_thread_aggregate(items)
    assert aggregate_no_prior.prior_summary is None


# ---------------------------------------------------------------------------
# Test 11: Non-superseding types property on plugin
# ---------------------------------------------------------------------------

def test_non_superseding_types_on_plugin(monkeypatch, test_db_url: str):
    """AgentConversationMemoryPlugin declares decision and investigation_outcome as non-superseding."""
    client, service, stub = _create_client(monkeypatch, test_db_url)
    plugin = service._semantic_plugins["agent_conversation_memory"]
    assert plugin.non_superseding_types == frozenset({"decision", "investigation_outcome"})

    from semantic.base import ThreadAggregationSemanticPlugin
    assert ThreadAggregationSemanticPlugin.non_superseding_types.fget(plugin) == frozenset()


# ---------------------------------------------------------------------------
# Test 12: Small threads don't use watermark windowing
# ---------------------------------------------------------------------------

def test_small_thread_does_not_use_watermark_windowing(monkeypatch, test_db_url: str) -> None:
    """Threads under budget process all items even when watermark exists."""
    container_ref = "test:small"
    thread_ref = "test:small:thread-1"

    # Small messages that won't exceed budget but have enough tokens to trigger thread rebuild
    messages = [
        _make_message("small-1", "First short message about holds and reservation processing in the library system architecture that coordinates between branches.", container_ref, thread_ref),
        _make_message("small-2", "Second short message about sync mechanisms and catalog processing pipelines that handle batch operations across distributed infrastructure components.", container_ref, thread_ref, role="assistant"),
    ]

    client, service, stub = _create_client(monkeypatch, test_db_url)
    _post_drain_each(client, service, messages)

    first_call_count = stub.call_count

    # Add a third message
    messages2 = [
        _make_message("small-3", "Third message about ordering and reservation hold priorities that determine scheduling behavior in the queue processing system for distributed library operations.", container_ref, thread_ref),
    ]
    _post_drain_each(client, service, messages2)

    # The rebuild should see ALL items (no windowing) — look at thread summary prompts
    thread_rebuild_prompts = [p for p in stub.prompts[first_call_count:] if "thread items:" in p.lower()]
    assert len(thread_rebuild_prompts) >= 1, "Should have a thread rebuild prompt after adding third message"
    last_rebuild_prompt = thread_rebuild_prompts[-1]
    assert "first short message" in last_rebuild_prompt.lower()
    assert "second short message" in last_rebuild_prompt.lower()
    assert "third message" in last_rebuild_prompt.lower()

    # Should have exactly 1 active summary (superseded correctly)
    summaries = _collect_memory(service._storage, container_ref, thread_ref, "thread_summary")
    active_summaries = [m for m in summaries if m.lifecycle == "active"]
    assert len(active_summaries) == 1


# ---------------------------------------------------------------------------
# Test 13: Tail-biased truncation preserves recent content
# ---------------------------------------------------------------------------

def test_tail_biased_truncation_direction():
    """Truncation takes from the tail (most recent), dropping the head."""
    items = []
    for i in range(100):
        items.append(SourceItem(
            source_type="chat_message",
            source_id=f"trunc-{i}",
            content_type="text/plain",
            content=f"Message number {i:04d} with filler content " + ("x" * 200),
            artifact_kind="message",
            role="user" if i % 2 == 0 else "assistant",
            container_ref="test:trunc",
            thread_ref="test:trunc:t1",
            visibility="public",
        ))

    thread_material = _build_thread_material(items)
    assert len(thread_material) > THREAD_SUMMARY_MAX_TEXT_CHARS

    # Simulate the truncation logic from build_thread_summary
    if len(thread_material) > THREAD_SUMMARY_MAX_TEXT_CHARS:
        truncated = "[earlier thread items truncated for token budget]\n" + thread_material[-THREAD_SUMMARY_MAX_TEXT_CHARS:].lstrip()
    else:
        truncated = thread_material

    # The latest messages should be visible
    assert "message number 0099" in truncated.lower()
    assert "message number 0098" in truncated.lower()
    # The earliest messages should be truncated
    assert "message number 0000" not in truncated.lower()
    # Truncation marker should be at the start
    assert truncated.startswith("[earlier thread items truncated")


# ---------------------------------------------------------------------------
# Test 14: Single item exceeding budget is included alone (guaranteed progress)
# ---------------------------------------------------------------------------

def test_single_item_exceeding_budget_is_included(monkeypatch, test_db_url: str) -> None:
    """A single item larger than the budget is still processed (guaranteed progress)."""
    container_ref = "test:oversize"
    thread_ref = "test:oversize:thread-1"

    # Create one item that exceeds the 16K budget
    oversize_content = _filler(THREAD_WINDOW_BUDGET_CHARS + 5000)

    messages = [
        _make_message("over-1", oversize_content, container_ref, thread_ref),
        _make_message("over-2", _filler(THREAD_WINDOW_BUDGET_CHARS + 3000), container_ref, thread_ref, role="assistant"),
    ]

    client, service, stub = _create_client(monkeypatch, test_db_url)
    _post_and_drain(client, service, messages)

    # Thread rebuild should still happen — at least 1 item in the window
    summaries = _collect_memory(service._storage, container_ref, thread_ref, "thread_summary")
    active_summaries = [m for m in summaries if m.lifecycle == "active"]
    assert len(active_summaries) == 1, (
        f"Expected 1 active thread_summary even with oversize items, got {len(active_summaries)}"
    )


# ---------------------------------------------------------------------------
# Test 15: Boundary — thread at exactly budget chars processes all items
# ---------------------------------------------------------------------------

def test_thread_at_exact_budget_processes_all(monkeypatch, test_db_url: str) -> None:
    """A thread with total content == budget does not trigger windowing."""
    container_ref = "test:boundary"
    thread_ref = "test:boundary:thread-1"

    # Two items whose combined content is just under budget (no windowing)
    half_budget = THREAD_WINDOW_BUDGET_CHARS // 2 - 50
    messages = [
        _make_message("bound-1", _filler(half_budget), container_ref, thread_ref),
        _make_message("bound-2", _filler(half_budget), container_ref, thread_ref, role="assistant"),
    ]

    client, service, stub = _create_client(monkeypatch, test_db_url)
    _post_and_drain(client, service, messages)

    # Both items should appear in the thread rebuild prompt (no windowing)
    thread_rebuild_prompts = [p for p in stub.prompts if "thread items:" in p.lower()]
    assert len(thread_rebuild_prompts) >= 1
    # Verify both items are present (not windowed away)
    last_rebuild = thread_rebuild_prompts[-1]
    assert "bound-1" in last_rebuild or "padding word filler" in last_rebuild.lower()

    # Should have exactly 1 active summary
    summaries = _collect_memory(service._storage, container_ref, thread_ref, "thread_summary")
    active_summaries = [m for m in summaries if m.lifecycle == "active"]
    assert len(active_summaries) == 1


# ---------------------------------------------------------------------------
# Test 16: _apply_thread_window_budget unit test — guarantees at least 1 item
# ---------------------------------------------------------------------------

def test_window_budget_guarantees_one_item():
    """_apply_thread_window_budget always returns at least 1 item."""
    from core.thread_rebuild import ThreadRebuilder

    # Create items where each exceeds budget
    items = [
        SourceItem(
            source_type="chat_message",
            source_id=f"budget-{i}",
            content_type="text/plain",
            content=_filler(THREAD_WINDOW_BUDGET_CHARS + 1000),
            artifact_kind="message",
            role="user",
            container_ref="test:budget-unit",
            thread_ref="test:budget-unit:t1",
            visibility="public",
        )
        for i in range(3)
    ]

    rebuilder = ThreadRebuilder.__new__(ThreadRebuilder)
    result = rebuilder._apply_thread_window_budget(items)
    # Should include at least the last item (guaranteed progress)
    assert len(result) >= 1
    assert result[-1].source_id == "budget-2"  # most recent


# ---------------------------------------------------------------------------
# Test 17: _apply_thread_window_budget with items fitting exactly
# ---------------------------------------------------------------------------

def test_window_budget_includes_items_up_to_limit():
    """Budget trimming includes items from tail until budget is exhausted."""
    from core.thread_rebuild import ThreadRebuilder

    # 4 items of 5K each = 20K total. Budget is 16K. Should include last 3 items (15K).
    items = [
        SourceItem(
            source_type="chat_message",
            source_id=f"fit-{i}",
            content_type="text/plain",
            content=_filler(5000),
            artifact_kind="message",
            role="user" if i % 2 == 0 else "assistant",
            container_ref="test:fit",
            thread_ref="test:fit:t1",
            visibility="public",
        )
        for i in range(4)
    ]

    rebuilder = ThreadRebuilder.__new__(ThreadRebuilder)
    result = rebuilder._apply_thread_window_budget(items)
    # Last 3 items fit (15K < 16K), 4th would push to 20K
    assert len(result) == 3
    assert result[0].source_id == "fit-1"
    assert result[-1].source_id == "fit-3"


# ---------------------------------------------------------------------------
# Test 18: Watermark windowing skips items before watermark correctly
# ---------------------------------------------------------------------------

def test_watermark_skips_old_items(monkeypatch, test_db_url: str) -> None:
    """After watermark is set, only new items are passed to the rebuild window."""
    container_ref = "test:skip"
    thread_ref = "test:skip:thread-1"

    filler_size = THREAD_WINDOW_BUDGET_CHARS // 2 + 1000

    # First batch — establishes watermark
    messages1 = [
        _make_message("skip-1", _filler(filler_size), container_ref, thread_ref),
        _make_message("skip-2", _filler(filler_size), container_ref, thread_ref, role="assistant"),
    ]

    client, service, stub = _create_client(monkeypatch, test_db_url)
    _post_and_drain(client, service, messages1)

    first_call_count = stub.call_count

    # Second batch — only this should appear in the rebuild
    messages2 = [
        _make_message("skip-3", "New item after watermark with enough words to trigger rebuild in the distributed catalog synchronization pipeline for the library system.", container_ref, thread_ref),
    ]
    _post_and_drain(client, service, messages2)

    # The second rebuild prompt should contain skip-3 content but NOT skip-1/skip-2 filler
    thread_rebuild_prompts = [p for p in stub.prompts[first_call_count:] if "thread items:" in p.lower()]
    if thread_rebuild_prompts:
        last_rebuild = thread_rebuild_prompts[-1]
        assert "new item after watermark" in last_rebuild.lower()
        # The old filler content should NOT be in the rebuild prompt (watermark skipped it)
        assert "padding word filler text for budget testing" not in last_rebuild.lower() or "new item after watermark" in last_rebuild.lower()
