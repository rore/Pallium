"""Conversational knowledge package — extracts atomic facts from conversation threads.

This package is lightweight per-item (no LLM calls) and expensive per-thread
(one LLM call to extract all facts from the thread). It uses the thread rebuild
mechanism to trigger extraction when new messages arrive.

Produces `atomic_fact` memory objects indexed for both lexical and vector retrieval.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from capabilities.thread_aggregation import ThreadAggregate
from core.contracts import ProcessResult
from core.indexing import VECTOR_INDEX_TYPE, build_index_entry
from core.models import MemoryObject, MemoryObject, Relation, SourceItem, new_id, utc_now
from core.type_registry import TypeRegistration, TypeRegistry
from providers.llm.base import LLMProvider, LLMJsonResponse
from semantic.base import ThreadAggregationSemanticPlugin
from semantic.common import normalize_for_index


logger = logging.getLogger(__name__)

# ── Schema constants ──────────────────────────────────────────────────────

FACT_SCHEMA_ID = "conversational_knowledge.atomic_fact"
FACT_SCHEMA_VERSION = "v1"
FACT_TYPE = "atomic_fact"

FACT_PROMPT_SCHEMA_ID = "fact_extraction"
FACT_PROMPT_SCHEMA_VERSION = "v1"

VECTOR_EMBEDDING_PROVIDER_NAME = "embedding"
VECTOR_EMBEDDING_PROVIDER_VERSION = "v1"

FACT_LEXICAL_TEXT_VIEW = "memory_object.fact_statement"
FACT_VECTOR_TEXT_VIEW = "memory_object.fact_embedding"

# Eligible source artifacts for fact extraction
ELIGIBLE_ARTIFACT_ROLES = {
    ("message", "user"),
    ("message", "assistant"),
    (None, "user"),
    (None, "assistant"),
    ("assistant_output", "assistant"),
}

FACT_EXTRACTION_MAX_THREAD_CHARS = 6000

FACT_EXTRACTION_SYSTEM_PROMPT = (
    "Extract specific, atomic facts from the conversation below. "
    "Each fact should be independently useful for answering a future question. "
    "Extract: names, dates, numbers, places, activities, preferences, relationships, events, stated plans. "
    "Skip: greetings, filler, emotional reactions, generic encouragement, meta-conversation. "
    "Preserve the original language — do not translate. "
    "Include who the fact is about (subject) and when it happened if mentioned. "
    "Return a JSON object with a single key 'facts' containing an array. "
    "Each fact has: subject (string), statement (string), category (one of: personal, event, preference, relationship, activity). "
    "If there are no extractable facts, return {\"facts\": []}."
)

FACT_EXTRACTION_SCHEMA_DESCRIPTION = json.dumps(
    {
        "facts": [
            {
                "subject": "who or what this fact is about",
                "statement": "the atomic fact, self-contained",
                "category": "personal | event | preference | relationship | activity",
            }
        ]
    },
    indent=2,
)


class ConversationalKnowledgePlugin(ThreadAggregationSemanticPlugin):
    """Extracts atomic facts from conversation threads."""

    name = "conversational_knowledge"

    def __init__(self, provider: LLMProvider, *, prompt_variant: str = "fact_extraction_v1") -> None:
        self._provider = provider
        self._prompt_variant = prompt_variant

    @property
    def requires_visibility_context(self) -> bool:
        return True

    @property
    def parallel_processing(self) -> bool:
        return True

    @property
    def thread_summary_schema_id(self) -> str:
        return FACT_SCHEMA_ID

    @property
    def thread_conclusion_types(self) -> frozenset[str]:
        return frozenset()

    def process_item(self, source_item: SourceItem) -> ProcessResult:
        """Lightweight per-item check. No LLM calls, no memory objects.

        Returns thread_rebuild_requested=True for eligible items so the
        thread-level handler runs when all items are collected.
        """
        if not _is_eligible_for_fact_extraction(source_item):
            return ProcessResult(
                memory_objects=[], relations=[], index_entries=[],
                thread_rebuild_requested=False,
            )
        return ProcessResult(
            memory_objects=[], relations=[], index_entries=[],
            thread_rebuild_requested=True,
        )

    def supports_thread_aggregation(self, source_item: SourceItem) -> bool:
        return _is_eligible_for_fact_extraction(source_item)

    def build_thread_summary(
        self,
        aggregate: ThreadAggregate,
        conclusions: list[MemoryObject],
    ) -> ProcessResult:
        """Extract atomic facts from the full thread.

        Makes one LLM call to extract all facts. Returns atomic_fact memory
        objects with lexical and vector index entries.
        """
        if len(aggregate.source_items) < 2:
            return ProcessResult(memory_objects=[], relations=[], index_entries=[])

        thread_text = _build_thread_text(aggregate)
        if not thread_text.strip():
            return ProcessResult(memory_objects=[], relations=[], index_entries=[])

        raw_facts = self._extract_facts(thread_text)
        if not raw_facts:
            return ProcessResult(memory_objects=[], relations=[], index_entries=[])

        now = utc_now()
        latest_occurred_at = max(
            (item.occurred_at for item in aggregate.source_items if item.occurred_at),
            default=now,
        )
        container_ref = aggregate.container_ref
        visibility = aggregate.visibility

        memory_objects: list[MemoryObject] = []
        relations: list[Relation] = []
        index_entries = []

        for fact in raw_facts:
            subject = str(fact.get("subject", "")).strip()
            statement = str(fact.get("statement", "")).strip()
            category = str(fact.get("category", "")).strip()
            if not statement:
                continue

            memory_id = new_id()
            memory_objects.append(
                MemoryObject(
                    id=memory_id,
                    type=FACT_TYPE,
                    schema_id=FACT_SCHEMA_ID,
                    schema_version=FACT_SCHEMA_VERSION,
                    payload={
                        "subject": subject,
                        "statement": statement,
                        "category": category,
                    },
                    visibility=visibility or "private",
                    container_ref=container_ref,
                    freshness_at=latest_occurred_at,
                )
            )

            # Evidence: supported_by all thread source items
            for item in aggregate.source_items:
                relations.append(
                    Relation(
                        from_kind="memory_object",
                        from_id=memory_id,
                        relation_type="supported_by",
                        to_kind="source_item",
                        to_id=item.id,
                    )
                )

            # Lexical index: the statement text
            index_entries.append(
                build_index_entry(
                    target_kind="memory_object",
                    target_id=memory_id,
                    index_type="lexical",
                    text_view=normalize_for_index(statement),
                    text_view_name=FACT_LEXICAL_TEXT_VIEW,
                )
            )

            # Vector index: "{subject}: {statement}"
            embedding_text = f"{subject}: {statement}" if subject else statement
            index_entries.append(
                build_index_entry(
                    target_kind="memory_object",
                    target_id=memory_id,
                    index_type=VECTOR_INDEX_TYPE,
                    text_view=embedding_text,
                    text_view_name=FACT_VECTOR_TEXT_VIEW,
                    provider_name=VECTOR_EMBEDDING_PROVIDER_NAME,
                    provider_version=VECTOR_EMBEDDING_PROVIDER_VERSION,
                )
            )

        return ProcessResult(
            memory_objects=memory_objects,
            relations=relations,
            index_entries=index_entries,
        )

    def _extract_facts(self, thread_text: str) -> list[dict[str, Any]]:
        """Call the LLM to extract facts from thread text."""
        try:
            response = self._provider.generate_json(
                system_prompt=FACT_EXTRACTION_SYSTEM_PROMPT,
                user_prompt=thread_text,
                schema_description=FACT_EXTRACTION_SCHEMA_DESCRIPTION,
            )
            parsed = response.parsed_json
        except Exception:
            logger.warning("Fact extraction LLM call failed", exc_info=True)
            raise

        facts = parsed.get("facts", [])
        if not isinstance(facts, list):
            return []
        return [f for f in facts if isinstance(f, dict) and f.get("statement")]

    def register_routing_types(self, registry: TypeRegistry) -> None:
        """Register atomic_fact type with the core type registry."""
        registry.register(
            TypeRegistration(
                type_name="atomic_fact",
                layer_name="atomic_fact",
                weight_by_intent={
                    "recall": 120,
                    "structured_recall": 140,
                    "work_resumption": 60,
                    "evidence_trace": 100,
                },
                default_weight=80,
                block_title="Known Fact",
                block_text_field="statement",
                high_value=False,
            )
        )

    def source_item_embedding_text(self, source_item: SourceItem) -> str | None:
        return None


def _is_eligible_for_fact_extraction(source_item: SourceItem) -> bool:
    """Check if a source item is eligible for fact extraction."""
    if not source_item.container_ref or not source_item.thread_ref:
        return False
    role = (source_item.role or "").lower()
    artifact_kind = (source_item.artifact_kind or "").lower() or None
    return (artifact_kind, role) in ELIGIBLE_ARTIFACT_ROLES


def _build_thread_text(aggregate: ThreadAggregate) -> str:
    """Build a text representation of the thread for fact extraction."""
    parts: list[str] = []
    for item in aggregate.source_items:
        role = item.role or "unknown"
        content = item.content or ""
        if len(content) > FACT_EXTRACTION_MAX_THREAD_CHARS // max(len(aggregate.source_items), 1):
            content = content[:FACT_EXTRACTION_MAX_THREAD_CHARS // max(len(aggregate.source_items), 1)] + "..."
        parts.append(f"[{role}]: {content}")
    return "\n".join(parts)
