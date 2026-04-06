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

from capabilities.consolidation import ConsolidationGroup, ConsolidationPolicy
from capabilities.thread_aggregation import ThreadAggregate
from core.contracts import ProcessResult
from core.indexing import VECTOR_INDEX_TYPE, build_index_entry
from core.models import MemoryObject, Relation, SourceItem, new_id, utc_now
from core.type_registry import TypeRegistration, TypeRegistry
from providers.llm.base import LLMProvider, LLMJsonResponse
from semantic.base import ConsolidationSemanticPlugin, ThreadAggregationSemanticPlugin
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

FACT_EXTRACTION_MAX_ITEMS_PER_CHUNK = 10   # max source items per LLM call
FACT_EXTRACTION_MAX_CHARS_PER_CHUNK = 6000  # max chars of thread text per LLM call

# ── Fact summary (consolidation output) constants ────────────────────────

FACT_SUMMARY_SCHEMA_ID = "conversational_knowledge.fact_summary"
FACT_SUMMARY_SCHEMA_VERSION = "v1"
FACT_SUMMARY_TYPE = "fact_summary"

FACT_CONSOLIDATION_PROMPT_SCHEMA_ID = "fact_consolidation"
FACT_CONSOLIDATION_PROMPT_SCHEMA_VERSION = "v1"

FACT_SUMMARY_LEXICAL_TEXT_VIEW = "memory_object.fact_summary_statement"
FACT_SUMMARY_VECTOR_TEXT_VIEW = "memory_object.fact_summary_embedding"

FACT_CONSOLIDATION_SYSTEM_PROMPT = (
    "Consolidate the atomic facts below into one summary for the given subject and category. "
    "Also detect CONTRADICTIONS among the input facts.\n\n"
    "CONTRADICTION: Two facts contradict ONLY if they assign incompatible values to the SAME "
    "single-valued property. Examples:\n"
    "- 'born in London' vs 'born in Berlin' — same property (birthplace), incompatible → CONTRADICTION\n"
    "- 'citizen of France' vs 'citizen of India' — same property (citizenship), incompatible → CONTRADICTION\n"
    "- 'married to X' vs 'married to Y' — same property (spouse), incompatible → CONTRADICTION\n\n"
    "NOT a contradiction (do NOT supersede):\n"
    "- Different properties: 'died in X' and 'authored Y' — different predicates, both survive\n"
    "- Multi-valued predicates: 'authored book A' and 'authored book B' — a person can author many books\n"
    "- Separate events: 'went camping in July' and 'went camping in October' — two distinct events\n"
    "- Paraphrases: 'has kids' and 'has children' — same fact, merge in summary but do NOT supersede\n"
    "- Elaborations: 'is an artist' and 'creates paintings' — related but not contradictory\n\n"
    "When in doubt, do NOT supersede. Only flag clear single-valued property conflicts.\n"
    "When facts contradict, the NEWER one (later timestamp) supersedes the older. "
    "Add the older fact's index to superseded_indices.\n\n"
    "Return JSON:\n"
    "{\"summary\": \"consolidated summary text\", "
    "\"superseded_indices\": [indices of contradicted facts only], "
    "\"reasoning\": \"brief explanation\"}\n\n"
    "Summary format: a single sentence starting with \"{subject}'s {category}:\" "
    "followed by a comma-separated enumeration. "
    "Preserve all proper nouns, dates, numbers. Do not infer facts not in the input. "
    "Write in the same language as the input facts."
)

FACT_CONSOLIDATION_SCHEMA_DESCRIPTION = json.dumps(
    {
        "summary": "consolidated fact summary as enumerated list",
        "superseded_indices": [0],
        "reasoning": "brief explanation of contradictions found, or empty string",
    },
    indent=2,
)

# ── Extraction prompt ────────────────────────────────────────────────────

FACT_EXTRACTION_SYSTEM_PROMPT = (
    "Extract specific, atomic facts from the conversation below. "
    "Each fact should answer a possible future question about these people, places, events, or preferences. "
    "Extract: names, dates, numbers, places, activities, preferences, relationships, events, stated plans, "
    "emotional reactions to significant events, what was discussed or learned, recommendations between people. "
    "Skip: greetings, filler, generic encouragement, meta-conversation, trivial restatements. "
    "If the same fact is mentioned multiple times, extract it once in its most specific form. "
    "Resolve relative dates using the session date. \"Last Tuesday\" with session date 2024-03-15 → \"approximately 2024-03-12\". "
    "\n\n"
    "SPECIFICITY: Preserve proper nouns (country names, book titles, pet names), qualifying details "
    "('abstract art' not 'art', 'single parent' not 'parent'), activity specifics "
    "('roasted marshmallows and hiked' not 'went camping'), and what was discussed/learned at events. "
    "Extract aside mentions in multi-topic turns. Never produce a vague version alongside a specific one. "
    "\n"
    "Good: {\"subject\": \"Jordan\", \"statement\": \"Jordan completed a half-marathon in Denver on approximately 2024-03-12\", \"category\": \"event\"}\n"
    "Bad: {\"subject\": \"Jordan\", \"statement\": \"Jordan likes running\", \"category\": \"personal\"} — too vague.\n"
    "\n"
    "Return JSON with key 'facts' containing up to 20 items. "
    "Each: subject (string), statement (string), category (personal | event | preference | relationship | activity). "
    "Prioritize facts with names, dates, numbers, or specific details. "
    "If no extractable facts, return {\"facts\": []}. "
    "\n"
    "LANGUAGE: Examples above are in English for illustration only. "
    "Write statements in the same language as the conversation. Do not translate."
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


class ConversationalKnowledgePlugin(ThreadAggregationSemanticPlugin, ConsolidationSemanticPlugin):
    """Extracts atomic facts from conversation threads and consolidates them cross-thread."""

    name = "conversational_knowledge"

    def __init__(self, provider: LLMProvider, *, prompt_variant: str = "fact_extraction_v1", providers_by_role: dict[str, LLMProvider] | None = None) -> None:
        self._provider = provider
        self._prompt_variant = prompt_variant
        self._providers_by_role = providers_by_role or {}

    def _provider_for_role(self, role: str) -> LLMProvider:
        return self._providers_by_role.get(role, self._provider)

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

    # ── Consolidation interface ──────────────────────────────────────────

    @property
    def consolidation_policy(self) -> ConsolidationPolicy | None:
        return ConsolidationPolicy(
            enabled_strategies=("fact_consolidation",),
            default_strategy="fact_consolidation",
            max_candidates_per_run=200,
            max_group_size=50,
            same_container_required=True,
            time_window_hours=8760,
            lexical_overlap_threshold=0,
        )

    def supports_consolidation(self, memory_object: MemoryObject) -> bool:
        return memory_object.type == FACT_TYPE

    def build_consolidated_memory(self, group: ConsolidationGroup) -> ProcessResult:
        return _build_fact_summary(
            provider=self._provider_for_role("fact_consolidation"),
            group=group,
            prompt_variant=self._prompt_variant,
        )

    # ── Per-item processing ──────────────────────────────────────────────

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

        Splits source items into chunks bounded by item count and char budget.
        Each chunk gets one LLM call. Results are merged and deduped.
        """
        if len(aggregate.source_items) < 2:
            return ProcessResult(memory_objects=[], relations=[], index_entries=[])

        chunk_texts = _build_chunk_texts(aggregate.source_items)
        if not chunk_texts:
            return ProcessResult(memory_objects=[], relations=[], index_entries=[])

        raw_facts: list[dict] = []
        for chunk_text in chunk_texts:
            raw_facts.extend(self._extract_facts(chunk_text))

        raw_facts = _dedup_extracted_facts(raw_facts)
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
                        "thread_ref": aggregate.thread_ref,
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
            response = self._provider_for_role("fact_extraction").generate_json(
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
        """Register atomic_fact and fact_summary types with the core type registry."""
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
        registry.register(
            TypeRegistration(
                type_name="fact_summary",
                layer_name="fact_summary",
                weight_by_intent={
                    "recall": 150,
                    "structured_recall": 170,
                    "work_resumption": 60,
                    "evidence_trace": 120,
                },
                default_weight=100,
                block_title="Fact Summary",
                block_text_field="summary",
                high_value=True,
            )
        )

    def source_item_embedding_text(self, source_item: SourceItem) -> str | None:
        return None

    def reconcile_process_result(
        self,
        result: ProcessResult,
        *,
        storage: Any,
        container_ref: str,
        visibility: str,
    ) -> ProcessResult:
        """Remove facts that duplicate active cross-thread facts in the same container."""
        if not result.memory_objects:
            return result

        current_thread_ref = None
        for mo in result.memory_objects:
            if mo.type == FACT_TYPE and mo.payload.get("thread_ref"):
                current_thread_ref = mo.payload["thread_ref"]
                break
        if current_thread_ref is None:
            return result

        existing_facts = storage.list_memory_objects(
            memory_types=[FACT_TYPE], lifecycle="active",
        )
        # NOTE: This loads all active facts across all containers, then post-filters.
        # O(all facts) per thread rebuild. Acceptable at current scale (~200 facts).
        # When list_memory_objects supports container_ref filtering, scope this query.

        existing_keys: set[tuple[str, str]] = set()
        for ef in existing_facts:
            if ef.container_ref != container_ref:
                continue
            if ef.payload.get("thread_ref") == current_thread_ref:
                continue  # same thread — will be superseded, don't suppress
            subj = normalize_for_index(str(ef.payload.get("subject", "")))
            stmt = normalize_for_index(str(ef.payload.get("statement", "")))
            existing_keys.add((subj, stmt))

        if not existing_keys:
            return result

        keep_ids: set[str] = set()
        filtered_memory_objects: list[MemoryObject] = []
        for mo in result.memory_objects:
            if mo.type != FACT_TYPE:
                keep_ids.add(mo.id)
                filtered_memory_objects.append(mo)
                continue
            key = (
                normalize_for_index(str(mo.payload.get("subject", ""))),
                normalize_for_index(str(mo.payload.get("statement", ""))),
            )
            if key in existing_keys:
                logger.debug("Dedup: skipping cross-thread duplicate fact: %s", mo.payload.get("statement", "")[:80])
                continue
            keep_ids.add(mo.id)
            filtered_memory_objects.append(mo)

        if len(filtered_memory_objects) == len(result.memory_objects):
            return result

        return ProcessResult(
            memory_objects=filtered_memory_objects,
            relations=[r for r in result.relations if r.from_id in keep_ids],
            index_entries=[e for e in result.index_entries if e.target_id in keep_ids],
        )


def _is_eligible_for_fact_extraction(source_item: SourceItem) -> bool:
    """Check if a source item is eligible for fact extraction."""
    if not source_item.container_ref or not source_item.thread_ref:
        return False
    role = (source_item.role or "").lower()
    artifact_kind = (source_item.artifact_kind or "").lower() or None
    return (artifact_kind, role) in ELIGIBLE_ARTIFACT_ROLES


def _build_chunk_texts(source_items: list[SourceItem]) -> list[str]:
    """Split source items into chunk texts for extraction.

    Each chunk is bounded by both item count (FACT_EXTRACTION_MAX_ITEMS_PER_CHUNK)
    and character budget (FACT_EXTRACTION_MAX_CHARS_PER_CHUNK). No item is ever
    truncated — if a single item exceeds the char budget, it gets its own chunk.
    """
    session_date = _extract_session_date(source_items)
    date_header = f"Session date: {session_date}\n" if session_date else ""

    chunks: list[str] = []
    current_lines: list[str] = []
    current_chars = len(date_header)
    current_count = 0

    for item in source_items:
        role = item.role or "unknown"
        content = item.content or ""
        line = f"[{role}]: {content}"
        line_chars = len(line) + 1  # +1 for newline

        # Start a new chunk if adding this item would exceed either limit
        # (but always allow at least one item per chunk)
        if current_count > 0 and (
            current_count >= FACT_EXTRACTION_MAX_ITEMS_PER_CHUNK
            or current_chars + line_chars > FACT_EXTRACTION_MAX_CHARS_PER_CHUNK
        ):
            chunks.append(date_header + "\n".join(current_lines))
            current_lines = []
            current_chars = len(date_header)
            current_count = 0

        current_lines.append(line)
        current_chars += line_chars
        current_count += 1

    if current_lines:
        chunks.append(date_header + "\n".join(current_lines))

    return chunks


def _dedup_extracted_facts(facts: list[dict]) -> list[dict]:
    """Remove duplicate facts from merged multi-chunk extraction."""
    seen: set[tuple[str, str]] = set()
    result: list[dict] = []
    for fact in facts:
        key = (
            normalize_for_index(str(fact.get("subject", ""))),
            normalize_for_index(str(fact.get("statement", ""))),
        )
        if key not in seen:
            seen.add(key)
            result.append(fact)
    return result


def _extract_session_date(source_items: list[SourceItem]) -> str | None:
    """Extract the session date (YYYY-MM-DD) from the earliest occurred_at."""
    dates = [item.occurred_at for item in source_items if item.occurred_at is not None]
    if not dates:
        return None
    return min(dates).strftime("%Y-%m-%d")


# ── Fact consolidation ───────────────────────────────────────────────────


def _build_fact_summary(
    *,
    provider: LLMProvider,
    group: ConsolidationGroup,
    prompt_variant: str,
) -> ProcessResult:
    """Synthesize a group of atomic_facts into one fact_summary via LLM.

    Also detects contradictions: the LLM returns superseded_indices identifying
    which input facts are contradicted by newer ones. The corresponding candidate
    IDs are stored in the fact_summary payload for the runner to act on.
    """
    fact_lines: list[str] = []
    candidate_ids_by_index: list[str] = []
    for i, candidate in enumerate(group.candidates):
        statement = str(candidate.memory_object.payload.get("statement", "")).strip()
        if not statement:
            continue
        ts = candidate.latest_occurred_at.strftime("%Y-%m-%dT%H:%M:%S") if candidate.latest_occurred_at else "unknown"
        fact_lines.append(f"[{i}] ({ts}) {statement}")
        candidate_ids_by_index.append(candidate.memory_object.id)

    if not fact_lines:
        return ProcessResult(memory_objects=[], relations=[], index_entries=[])

    subject = str(group.merge_rationale.get("subject", "")).strip()
    category = str(group.merge_rationale.get("category", "")).strip()

    user_prompt = (
        f"Subject: {subject}\n"
        f"Category: {category}\n"
        f"Facts ({len(fact_lines)}):\n" + "\n".join(fact_lines)
    )

    response = provider.generate_json(
        system_prompt=FACT_CONSOLIDATION_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        schema_description=FACT_CONSOLIDATION_SCHEMA_DESCRIPTION,
    )

    parsed_summary = response.parsed_json.get("summary")
    if not isinstance(parsed_summary, str) or not parsed_summary.strip():
        raise ValueError("fact consolidation must return a non-empty summary string")

    summary = parsed_summary.strip()

    # Map superseded_indices from the LLM response to candidate memory IDs
    raw_indices = response.parsed_json.get("superseded_indices", [])
    superseded_candidate_ids: list[str] = []
    if isinstance(raw_indices, list):
        for idx in raw_indices:
            if isinstance(idx, int) and 0 <= idx < len(candidate_ids_by_index):
                cid = candidate_ids_by_index[idx]
                if cid not in superseded_candidate_ids:
                    superseded_candidate_ids.append(cid)

    reasoning = str(response.parsed_json.get("reasoning", "")).strip()
    memory_id = new_id()

    consolidation_provenance = {
        "memory_kind": "fact_summary",
        "strategy_name": group.strategy_name,
        "strategy_version": group.strategy_version,
        "prompt_schema_id": FACT_CONSOLIDATION_PROMPT_SCHEMA_ID,
        "prompt_schema_version": FACT_CONSOLIDATION_PROMPT_SCHEMA_VERSION,
        "prompt_variant": prompt_variant,
    }

    memory_object = MemoryObject(
        id=memory_id,
        type=FACT_SUMMARY_TYPE,
        schema_id=FACT_SUMMARY_SCHEMA_ID,
        schema_version=FACT_SUMMARY_SCHEMA_VERSION,
        payload={
            "subject": subject,
            "category": category,
            "summary": summary,
            "fact_count": len(fact_lines),
            "supporting_memory_ids": list(group.candidate_ids),
            "superseded_candidate_ids": superseded_candidate_ids,
            "contradiction_reasoning": reasoning,
            "latest_occurred_at": group.latest_occurred_at.isoformat(),
            "container_ref": group.container_ref,
            "group_key": group.group_key,
            "consolidation_provenance": consolidation_provenance,
        },
        visibility=group.visibility,
        container_ref=group.container_ref,
        freshness_at=group.latest_occurred_at,
    )

    index_entries = [
        build_index_entry(
            target_kind="memory_object",
            target_id=memory_id,
            index_type="lexical",
            text_view=normalize_for_index(summary),
            text_view_name=FACT_SUMMARY_LEXICAL_TEXT_VIEW,
        ),
    ]

    embedding_text = f"{subject}: {summary}" if subject else summary
    index_entries.append(
        build_index_entry(
            target_kind="memory_object",
            target_id=memory_id,
            index_type=VECTOR_INDEX_TYPE,
            text_view=embedding_text,
            text_view_name=FACT_SUMMARY_VECTOR_TEXT_VIEW,
            provider_name=VECTOR_EMBEDDING_PROVIDER_NAME,
            provider_version=VECTOR_EMBEDDING_PROVIDER_VERSION,
        )
    )

    return ProcessResult(
        memory_objects=[memory_object],
        relations=[],
        index_entries=index_entries,
    )
