"""Tests for type prefix in fact embedding text (vector discrimination)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from capabilities.consolidation import ConsolidationCandidate, ConsolidationGroup
from capabilities.thread_aggregation import ThreadAggregate
from core.contracts import ProcessResult
from core.indexing import VECTOR_INDEX_TYPE
from core.models import EvidenceReference, MemoryObject, SourceItem, new_id, utc_now
from providers.llm.base import LLMProvider, LLMJsonResponse
from semantic.conversational_knowledge import (
    ConversationalKnowledgePlugin,
    FACT_VECTOR_TEXT_VIEW,
    FACT_SUMMARY_VECTOR_TEXT_VIEW,
    _build_fact_summary,
)


# ── Stub LLM provider ────────────────────────────────────────────────────


class StubFactProvider(LLMProvider):
    """LLM provider that returns canned fact extraction responses."""

    provider_name = "stub_fact_embed"

    def __init__(self, facts: list[dict] | None = None, consolidation_summary: str = "consolidated"):
        self._facts = facts or []
        self._consolidation_summary = consolidation_summary

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        if "consolidat" in system_prompt.lower() or "consolidat" in schema_description.lower():
            result = {
                "summary": self._consolidation_summary,
                "superseded_indices": [],
                "reasoning": "stub",
            }
        else:
            result = {"facts": self._facts}
        raw = json.dumps(result)
        return LLMJsonResponse(raw_text=raw, parsed_json=result)


# ── Helpers ───────────────────────────────────────────────────────────────


def _make_aggregate(items: list[SourceItem]) -> ThreadAggregate:
    return ThreadAggregate(
        container_ref="c1",
        thread_ref="t1",
        source_items=items,
        source_item_ids=[i.id for i in items],
        latest_occurred_at=utc_now(),
        aggregate_text="[user]: test content",
        visibility="public",
    )


def _vector_entries(result: ProcessResult, text_view_name: str):
    """Filter index entries to vector entries with a specific text_view_name."""
    return [
        e for e in result.index_entries
        if e.index_type == VECTOR_INDEX_TYPE and e.text_view_name == text_view_name
    ]


# ── Tests: atomic_fact embedding prefix ──────────────────────────────────


class TestAtomicFactEmbeddingPrefix:
    def test_atomic_fact_prefix_with_subject(self):
        """atomic_fact vector index entry should start with [atomic_fact] prefix."""
        facts = [{"subject": "Alice", "statement": "Alice has 3 cats", "category": "personal"}]
        plugin = ConversationalKnowledgePlugin(provider=StubFactProvider(facts=facts))
        items = [
            SourceItem(
                source_type="chat", source_id="e1a",
                content_type="text/plain", content="Alice has 3 cats.",
                role="user", artifact_kind="message",
                container_ref="c1", thread_ref="t1",
                visibility="public", occurred_at=utc_now(),
            ),
            SourceItem(
                source_type="chat", source_id="e1b",
                content_type="text/plain", content="That's nice!",
                role="assistant", artifact_kind="assistant_output",
                container_ref="c1", thread_ref="t1",
                visibility="public", occurred_at=utc_now(),
            ),
        ]
        result = plugin.build_thread_summary(_make_aggregate(items), conclusions=[])

        vector_entries = _vector_entries(result, FACT_VECTOR_TEXT_VIEW)
        assert len(vector_entries) == 1
        assert vector_entries[0].text_view.startswith("[atomic_fact] ")

    def test_atomic_fact_prefix_preserves_subject_statement_format(self):
        """Subject: statement format should be preserved after the prefix."""
        facts = [{"subject": "Alice", "statement": "Alice has 3 cats", "category": "personal"}]
        plugin = ConversationalKnowledgePlugin(provider=StubFactProvider(facts=facts))
        items = [
            SourceItem(
                source_type="chat", source_id="e2a",
                content_type="text/plain", content="Alice has 3 cats",
                role="user", artifact_kind="message",
                container_ref="c1", thread_ref="t1",
                visibility="public", occurred_at=utc_now(),
            ),
            SourceItem(
                source_type="chat", source_id="e2b",
                content_type="text/plain", content="That's interesting!",
                role="assistant", artifact_kind="assistant_output",
                container_ref="c1", thread_ref="t1",
                visibility="public", occurred_at=utc_now(),
            ),
        ]
        result = plugin.build_thread_summary(_make_aggregate(items), conclusions=[])

        vector_entries = _vector_entries(result, FACT_VECTOR_TEXT_VIEW)
        assert len(vector_entries) == 1
        # Prefix + subject:statement format
        assert vector_entries[0].text_view == "[atomic_fact] Alice: Alice has 3 cats"

    def test_atomic_fact_prefix_multiple_facts(self):
        """Multiple facts should each get the prefix."""
        facts = [
            {"subject": "Alice", "statement": "Alice has 3 cats", "category": "personal"},
            {"subject": "Bob", "statement": "Bob works at the library", "category": "activity"},
        ]
        plugin = ConversationalKnowledgePlugin(provider=StubFactProvider(facts=facts))
        items = [
            SourceItem(
                source_type="chat", source_id="e3a",
                content_type="text/plain", content="Alice has 3 cats.",
                role="user", artifact_kind="message",
                container_ref="c1", thread_ref="t1",
                visibility="public", occurred_at=utc_now(),
            ),
            SourceItem(
                source_type="chat", source_id="e3b",
                content_type="text/plain", content="Bob works at the library.",
                role="assistant", artifact_kind="assistant_output",
                container_ref="c1", thread_ref="t1",
                visibility="public", occurred_at=utc_now(),
            ),
        ]
        result = plugin.build_thread_summary(_make_aggregate(items), conclusions=[])

        vector_entries = _vector_entries(result, FACT_VECTOR_TEXT_VIEW)
        assert len(vector_entries) == 2
        assert all(e.text_view.startswith("[atomic_fact] ") for e in vector_entries)


# ── Tests: fact_summary embedding prefix ─────────────────────────────────


class TestFactSummaryEmbeddingPrefix:
    def _make_consolidation_group(self, subject: str = "Alice") -> ConsolidationGroup:
        """Create a ConsolidationGroup with atomic_fact candidates."""
        now = utc_now()
        statement = f"{subject} has 3 cats" if subject else "team meets on Mondays"
        mo = MemoryObject(
            id=new_id(),
            type="atomic_fact",
            schema_id="fact.atomic_v1",
            schema_version="1",
            payload={"subject": subject, "statement": statement, "category": "personal"},
            visibility="public",
            container_ref="c1",
            freshness_at=now,
        )
        candidate = ConsolidationCandidate(
            memory_object=mo,
            evidence=(),
            text_view=statement,
            tokens=frozenset(statement.lower().split()),
            container_ref="c1",
            thread_ref="t1",
            latest_occurred_at=now,
            visibility="public",
        )
        return ConsolidationGroup(
            strategy_name="fact_consolidation",
            strategy_version="1",
            group_key=f"{subject}::personal",
            candidates=(candidate,),
            container_ref="c1",
            thread_ref="t1",
            latest_occurred_at=now,
            visibility="public",
            merge_rationale={"subject": subject, "category": "personal"},
        )

    def test_fact_summary_prefix_with_subject(self):
        """fact_summary vector index entry should start with [fact_summary] prefix."""
        provider = StubFactProvider(consolidation_summary="Alice has 3 cats and loves painting")
        group = self._make_consolidation_group(subject="Alice")

        result = _build_fact_summary(provider=provider, group=group, prompt_variant="default")

        vector_entries = _vector_entries(result, FACT_SUMMARY_VECTOR_TEXT_VIEW)
        assert len(vector_entries) == 1
        assert vector_entries[0].text_view.startswith("[fact_summary] ")

    def test_fact_summary_prefix_preserves_subject_summary_format(self):
        """Subject: summary format should be preserved after the prefix."""
        provider = StubFactProvider(consolidation_summary="likes painting")
        group = self._make_consolidation_group(subject="Alice")

        result = _build_fact_summary(provider=provider, group=group, prompt_variant="default")

        vector_entries = _vector_entries(result, FACT_SUMMARY_VECTOR_TEXT_VIEW)
        assert len(vector_entries) == 1
        assert vector_entries[0].text_view == "[fact_summary] Alice: likes painting"

    def test_fact_summary_prefix_empty_subject(self):
        """When subject is empty, only summary with prefix should appear."""
        provider = StubFactProvider(consolidation_summary="team meeting at 3pm every Monday")
        group = self._make_consolidation_group(subject="")

        result = _build_fact_summary(provider=provider, group=group, prompt_variant="default")

        vector_entries = _vector_entries(result, FACT_SUMMARY_VECTOR_TEXT_VIEW)
        assert len(vector_entries) == 1
        assert vector_entries[0].text_view == "[fact_summary] team meeting at 3pm every Monday"
