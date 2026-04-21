"""Conversational knowledge package — extracts atomic facts from conversation threads.

This package is lightweight per-item (no LLM calls) and expensive per-thread
(one LLM call to extract all facts from the thread). It uses the thread rebuild
mechanism to trigger extraction when new messages arrive.

Produces `atomic_fact` memory objects indexed for both lexical and vector retrieval.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from capabilities.consolidation import ConsolidationGroup, ConsolidationPolicy
from capabilities.thread_aggregation import ThreadAggregate
from core.contracts import ProcessResult
from core.indexing import VECTOR_INDEX_TYPE, build_index_entry
from core.text import SENTENCE_PATTERN
from core.models import (
    MemoryEnvelope,
    MemoryEnvelopeDerivation,
    MemoryEnvelopeScope,
    MemoryObject,
    MemorySubjectAnchor,
    Relation,
    SourceItem,
    new_id,
    utc_now,
)
from core.type_registry import TypeRegistration, TypeRegistry
from providers.llm.base import LLMProvider, LLMJsonResponse
from semantic.base import ConsolidationSemanticPlugin, ThreadAggregationSemanticPlugin
from semantic.common import clean_markdown_artifacts, content_tokens, fact_statement_is_quality_viable, normalize_for_index


logger = logging.getLogger(__name__)

FACT_SCHEMA_ID = "conversational_knowledge.atomic_fact"
FACT_SCHEMA_VERSION = "v1"
FACT_TYPE = "atomic_fact"

FACT_PROMPT_SCHEMA_ID = "fact_extraction"
FACT_PROMPT_SCHEMA_VERSION = "v2"

VECTOR_EMBEDDING_PROVIDER_NAME = "embedding"
VECTOR_EMBEDDING_PROVIDER_VERSION = "v1"

FACT_LEXICAL_TEXT_VIEW = "memory_object.fact_statement"
FACT_VECTOR_TEXT_VIEW = "memory_object.fact_embedding"

# Envelope schema constants (shared across fact types in this package)
FACT_ENVELOPE_SCHEMA_ID = "core.memory_envelope"
FACT_ENVELOPE_SCHEMA_VERSION = "v1"

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
    "Record what participants stated, not what is objectively true — if a statement contradicts common knowledge or a prior fact, still extract it. "
    "Each fact should answer a possible future question about these people, places, events, or preferences. "
    "Each statement must be self-contained and explicitly name its subject; do not return subjectless predicate fragments. "
    "Extract: names, dates, numbers, places, activities, preferences, relationships, events, stated plans, "
    "emotional reactions to significant events, what was discussed or learned, recommendations between people. "
    "Skip: greetings, filler, generic encouragement, meta-conversation, trivial restatements, "
    "hypothetical or conditional future states, current runtime/deployment/debug status, "
    "one-off failures, monitoring chatter, and generic platform behavior instructions. "
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


def _clean_fact_text(text: str | None) -> str:
    return str(clean_markdown_artifacts(text) or "").strip()


def _fact_subject_is_present(subject: str) -> bool:
    return bool(normalize_for_index(subject))


def _statement_mentions_subject(subject: str, statement: str) -> bool:
    subject_tokens = set(normalize_for_index(subject).split())
    statement_tokens = set(normalize_for_index(statement).split())
    return bool(subject_tokens) and subject_tokens <= statement_tokens


def _iter_source_sentences(source_items: list[SourceItem]) -> list[str]:
    sentences: list[str] = []
    for source_item in source_items:
        for line in str(source_item.content or "").splitlines():
            stripped_line = line.strip()
            if not stripped_line:
                continue
            parts = [part.strip() for part in SENTENCE_PATTERN.split(stripped_line) if part.strip()]
            if not parts:
                parts = [stripped_line]
            sentences.extend(parts)
    return sentences


def _best_grounded_fact_sentence(statement: str, source_items: list[SourceItem]) -> str | None:
    normalized_statement = normalize_for_index(statement)
    if not normalized_statement:
        return None
    best_sentence: str | None = None
    for sentence in _iter_source_sentences(source_items):
        cleaned_sentence = _clean_fact_text(sentence)
        if not cleaned_sentence:
            continue
        if normalized_statement not in normalize_for_index(cleaned_sentence):
            continue
        if best_sentence is None or len(cleaned_sentence) < len(best_sentence):
            best_sentence = cleaned_sentence
    return best_sentence


def _canonicalize_fact_statement(subject: str, statement: str, source_items: list[SourceItem]) -> str:
    cleaned_subject = _clean_fact_text(subject)
    cleaned_statement = _clean_fact_text(statement)
    if not cleaned_statement:
        return ""
    grounded_sentence = _best_grounded_fact_sentence(cleaned_statement, source_items)
    if grounded_sentence:
        if cleaned_subject and _statement_mentions_subject(cleaned_subject, grounded_sentence):
            return grounded_sentence
        if not cleaned_subject and grounded_sentence != cleaned_statement:
            return grounded_sentence
    if cleaned_subject and not _statement_mentions_subject(cleaned_subject, cleaned_statement):
        return f"{cleaned_subject}: {cleaned_statement}"
    return cleaned_statement


def _is_question_like_fact(statement: str) -> bool:
    return statement.rstrip().endswith("?")


def _is_subject_prefixed_vague_fact(subject: str, statement: str) -> bool:
    prefix = f"{subject}:"
    if not subject or not statement.startswith(prefix):
        return False
    remainder = statement[len(prefix):].strip()
    if not remainder:
        return True
    return len(content_tokens(remainder)) < 2 and not any(char.isdigit() for char in remainder)


def _is_durable_fact_statement(subject: str, statement: str) -> bool:
    return not _is_question_like_fact(statement) and not _is_subject_prefixed_vague_fact(subject, statement)


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
        return frozenset({FACT_TYPE})

    @property
    def rebuild_supersedes_prior(self) -> bool:
        return False

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

    FACT_SUMMARY_FREEZE_WORD_LIMIT = 150

    def supports_consolidation(self, memory_object: MemoryObject) -> bool:
        if memory_object.type == FACT_TYPE:
            return True
        if memory_object.type == FACT_SUMMARY_TYPE:
            summary_text = str(memory_object.payload.get("summary", ""))
            return len(summary_text.split()) < self.FACT_SUMMARY_FREEZE_WORD_LIMIT
        return False

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
        """Extract atomic facts incrementally from new thread messages.

        On first extraction (no existing facts), processes the full thread.
        On subsequent calls, only processes source items newer than the
        extraction watermark stored in existing facts.
        """
        if len(aggregate.source_items) < 2:
            return ProcessResult(memory_objects=[], relations=[], index_entries=[])

        # Determine which items are new since the last extraction
        existing_facts = conclusions  # filtered to FACT_TYPE by thread_conclusion_types
        watermark = _resolve_extraction_watermark(existing_facts)

        if watermark is not None:
            new_items = [
                item for item in aggregate.source_items
                if item.created_at > watermark
            ]
        else:
            # First extraction or backward compat — process full thread
            new_items = list(aggregate.source_items)

        if not new_items:
            return ProcessResult(memory_objects=[], relations=[], index_entries=[])

        chunk_texts = _build_chunk_texts(new_items)
        if not chunk_texts:
            return ProcessResult(memory_objects=[], relations=[], index_entries=[])

        existing_facts_context = _build_existing_facts_context(existing_facts)

        raw_facts: list[dict] = []
        for chunk_text in chunk_texts:
            raw_facts.extend(
                self._extract_facts(chunk_text, existing_facts=existing_facts_context)
            )

        raw_facts = _dedup_extracted_facts(raw_facts, existing_facts=existing_facts_context)
        if not raw_facts:
            return ProcessResult(memory_objects=[], relations=[], index_entries=[])

        now = utc_now()
        latest_occurred_at = max(
            (item.occurred_at for item in aggregate.source_items if item.occurred_at),
            default=now,
        )
        container_ref = aggregate.container_ref
        visibility = aggregate.visibility

        # Watermark: max created_at among the new items we just processed
        new_watermark = max(item.created_at for item in new_items).isoformat()

        memory_objects: list[MemoryObject] = []
        relations: list[Relation] = []
        index_entries = []

        for fact in raw_facts:
            subject = _clean_fact_text(str(fact.get("subject") or ""))
            raw_statement = _clean_fact_text(str(fact.get("statement", "")))
            if not fact_statement_is_quality_viable(raw_statement):
                continue
            statement = _canonicalize_fact_statement(
                subject,
                raw_statement,
                aggregate.source_items,
            )
            category = _clean_fact_text(str(fact.get("category", ""))).lower()
            if not _fact_subject_is_present(subject):
                continue
            if not fact_statement_is_quality_viable(statement):
                continue
            if not _is_durable_fact_statement(subject, statement):
                continue

            memory_id = new_id()
            envelope = MemoryEnvelope(
                schema_id=FACT_ENVELOPE_SCHEMA_ID,
                schema_version=FACT_ENVELOPE_SCHEMA_VERSION,
                kind="finding",
                scope=MemoryEnvelopeScope(
                    container_ref=container_ref,
                    thread_ref=aggregate.thread_ref,
                ),
                derivation=MemoryEnvelopeDerivation(
                    producer_kind="item_extraction",
                    producer_schema_id=FACT_SCHEMA_ID,
                    producer_schema_version=FACT_SCHEMA_VERSION,
                ),
                subjects=[MemorySubjectAnchor(kind="surface", value=subject)] if subject else [],
                confidence="medium",
            )
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
                        "container_ref": container_ref,
                        "extraction_watermark": new_watermark,
                    },
                    visibility=visibility or "private",
                    container_ref=container_ref,
                    freshness_at=latest_occurred_at,
                    envelope=envelope,
                )
            )

            # Evidence: supported_by ALL thread source items (not just new — preserves retention safety)
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

    def _extract_facts(self, thread_text: str, *, existing_facts: list[dict] | None = None) -> list[dict[str, Any]]:
        """Call the LLM to extract facts from thread text.

        When existing_facts is provided, prepends them to the user prompt so
        the LLM avoids re-extracting already-known facts.
        """
        user_prompt = thread_text
        if existing_facts:
            existing_lines = "\n".join(
                f"- {f.get('subject', '')}: {f.get('statement', '')}"
                for f in existing_facts
            )
            user_prompt = (
                f"Previously extracted facts (do NOT re-extract these):\n"
                f"{existing_lines}\n\n"
                f"New conversation messages to extract facts from:\n"
                f"{thread_text}"
            )

        try:
            response = self._provider_for_role("fact_extraction").generate_json(
                system_prompt=FACT_EXTRACTION_SYSTEM_PROMPT,
                user_prompt=user_prompt,
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
        """Post-extraction hook. Cross-thread dedup removed — consolidation handles it."""
        return result


def _is_eligible_for_fact_extraction(source_item: SourceItem) -> bool:
    """Check if a source item is eligible for fact extraction."""
    if not source_item.container_ref or not source_item.thread_ref:
        return False
    role = (source_item.role or "").lower()
    artifact_kind = (source_item.artifact_kind or "").lower() or None
    return (artifact_kind, role) in ELIGIBLE_ARTIFACT_ROLES


def _resolve_extraction_watermark(existing_facts: list[MemoryObject]) -> datetime | None:
    """Read extraction_watermark from existing facts and return the max timestamp.

    Returns None if no facts exist or any fact lacks the watermark field,
    which triggers full extraction (backward compatibility).

    Known v1 limitation: if all facts for a thread are superseded by
    consolidation (fact_summary), the next rebuild finds no active facts
    and falls back to full re-extraction. This is self-correcting but
    wastes one LLM call per consolidation cycle.
    """
    if not existing_facts:
        return None
    timestamps: list[datetime] = []
    for fact in existing_facts:
        watermark_str = fact.payload.get("extraction_watermark")
        if watermark_str is None:
            # Any fact missing the field → full extraction for backward compat
            return None
        try:
            timestamps.append(datetime.fromisoformat(watermark_str))
        except (ValueError, TypeError):
            logger.warning("Malformed extraction_watermark '%s'; falling back to full extraction", watermark_str)
            return None
    return max(timestamps)


def _build_existing_facts_context(existing_facts: list[MemoryObject]) -> list[dict]:
    """Convert existing MemoryObject facts to dicts for prompt context and dedup."""
    result: list[dict] = []
    for fact in existing_facts:
        result.append({
            "subject": str(fact.payload.get("subject", "")).strip(),
            "statement": str(fact.payload.get("statement", "")).strip(),
            "category": str(fact.payload.get("category", "")).strip(),
        })
    return result


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


def _dedup_extracted_facts(facts: list[dict], existing_facts: list[dict] | None = None) -> list[dict]:
    """Remove duplicate facts from merged multi-chunk extraction.

    When existing_facts is provided, pre-seeds the seen set so new facts
    that duplicate existing ones are filtered out.
    """
    seen: set[tuple[str, str]] = set()
    if existing_facts:
        for fact in existing_facts:
            key = (
                normalize_for_index(str(fact.get("subject", ""))),
                normalize_for_index(str(fact.get("statement", ""))),
            )
            seen.add(key)
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
    existing_summary_lines: list[str] = []
    candidate_ids_by_index: list[str] = []
    all_candidate_ids: list[str] = []

    for candidate in group.candidates:
        mo = candidate.memory_object
        all_candidate_ids.append(mo.id)

        # fact_summary candidates represent accumulated knowledge from prior consolidation
        if mo.type == "fact_summary":
            summary_text = str(mo.payload.get("summary", "")).strip()
            if summary_text:
                existing_summary_lines.append(f"(existing summary) {summary_text}")
            continue

        # atomic_fact candidates are individual facts
        statement = str(mo.payload.get("statement", "")).strip()
        if not statement:
            continue
        prompt_index = len(candidate_ids_by_index)
        ts = candidate.latest_occurred_at.strftime("%Y-%m-%dT%H:%M:%S") if candidate.latest_occurred_at else "unknown"
        fact_lines.append(f"[{prompt_index}] ({ts}) {statement}")
        candidate_ids_by_index.append(mo.id)

    if not fact_lines and not existing_summary_lines:
        return ProcessResult(memory_objects=[], relations=[], index_entries=[])

    subject = str(group.merge_rationale.get("subject", "")).strip()
    category = str(group.merge_rationale.get("category", "")).strip()

    prompt_parts = [f"Subject: {subject}", f"Category: {category}"]
    if existing_summary_lines:
        prompt_parts.append("Previous summary:\n" + "\n".join(existing_summary_lines))
    if fact_lines:
        prompt_parts.append(f"Facts ({len(fact_lines)}):\n" + "\n".join(fact_lines))
    user_prompt = "\n".join(prompt_parts)

    response = provider.generate_json(
        system_prompt=FACT_CONSOLIDATION_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        schema_description=FACT_CONSOLIDATION_SCHEMA_DESCRIPTION,
    )

    parsed_summary = response.parsed_json.get("summary")
    if not isinstance(parsed_summary, str) or not parsed_summary.strip():
        raise ValueError("fact consolidation must return a non-empty summary string")

    summary = parsed_summary.strip()

    # LLM may still report specific contradictions for reasoning, but ALL inputs get superseded.
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

    summary_envelope = MemoryEnvelope(
        schema_id=FACT_ENVELOPE_SCHEMA_ID,
        schema_version=FACT_ENVELOPE_SCHEMA_VERSION,
        kind="finding",
        scope=MemoryEnvelopeScope(
            container_ref=group.container_ref,
            thread_ref=None,
        ),
        derivation=MemoryEnvelopeDerivation(
            producer_kind="consolidation",
            producer_schema_id=FACT_SUMMARY_SCHEMA_ID,
            producer_schema_version=FACT_SUMMARY_SCHEMA_VERSION,
        ),
        subjects=[MemorySubjectAnchor(kind="surface", value=subject)] if subject else [],
        confidence="medium",
    )

    memory_object = MemoryObject(
        id=memory_id,
        type=FACT_SUMMARY_TYPE,
        schema_id=FACT_SUMMARY_SCHEMA_ID,
        schema_version=FACT_SUMMARY_SCHEMA_VERSION,
        payload={
            "subject": subject,
            "category": category,
            "summary": summary,
            "fact_count": len(fact_lines) + len(existing_summary_lines),
            "supporting_memory_ids": all_candidate_ids,
            "contradiction_reasoning": reasoning,
            "latest_occurred_at": group.latest_occurred_at.isoformat(),
            "container_ref": group.container_ref,
            "group_key": group.group_key,
            "consolidation_provenance": consolidation_provenance,
        },
        visibility=group.visibility,
        container_ref=group.container_ref,
        freshness_at=group.latest_occurred_at,
        envelope=summary_envelope,
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
