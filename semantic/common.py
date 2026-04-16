from __future__ import annotations

import re
from dataclasses import dataclass, field

from core.contracts import ProcessResult
from core.indexing import VECTOR_INDEX_TYPE, build_index_entry
from core.models import MemoryObject, MemorySubjectAnchor, Relation, SourceItem
from core.text import (
    TOKEN_PATTERN,
    SENTENCE_PATTERN,
    normalize_for_index,
    strip_combining_marks as strip_diacritics,
    tokenize_text,
)
from semantic.agent_conversation_memory_embedding import VECTOR_EMBEDDING_PROVIDER_NAME, VECTOR_EMBEDDING_PROVIDER_VERSION, build_embedding_text


from core.retention import SEMANTIC_SIGNAL_METADATA_KEY  # noqa: F401 — re-export for backward compatibility


DECISION_PATTERNS = (
    re.compile(r"\bdecision:\s*(?P<body>.+)", re.IGNORECASE),
    re.compile(r"\bwe decided(?: to)?\s+(?P<body>.+)", re.IGNORECASE),
    re.compile(r"\bwe chose\s+(?P<body>.+)", re.IGNORECASE),
    re.compile(r"\bchosen approach[:\s]+(?P<body>.+)", re.IGNORECASE),
    re.compile(r"\bwe will use\s+(?P<body>.+)", re.IGNORECASE),
)
INVESTIGATION_PATTERNS = (
    re.compile(r"\broot cause[:\s]+(?P<body>.+)", re.IGNORECASE),
    re.compile(r"\binvestigation found(?: that)?\s+(?P<body>.+)", re.IGNORECASE),
    re.compile(r"\binvestigation concluded(?: that)?\s+(?P<body>.+)", re.IGNORECASE),
    re.compile(r"\banalysis found(?: that)?\s+(?P<body>.+)", re.IGNORECASE),
    re.compile(r"\bfindings?[:\s]+(?P<body>.+)", re.IGNORECASE),
    re.compile(r"\boutcome[:\s]+(?P<body>.+)", re.IGNORECASE),
    re.compile(r"\bwe found that\s+(?P<body>.+)", re.IGNORECASE),
    re.compile(r"\bverdict[:\s]+(?P<body>.+)", re.IGNORECASE),
    re.compile(r"\bhere's the verdict[:\s]+(?P<body>.+)", re.IGNORECASE),
    re.compile(r"\bthe verdict is\s+(?P<body>.+)", re.IGNORECASE),
    re.compile(r"\bconclusion[:\s]+(?P<body>.+)", re.IGNORECASE),
    re.compile(r"\bthe conclusion is\s+(?P<body>.+)", re.IGNORECASE),
)
RATIONALE_SPLITTERS = (
    " because ",
    " to avoid ",
    " to prevent ",
    " so that ",
)
INVESTIGATION_RATIONALE_SPLITTERS = (
    " caused by ",
    " due to ",
    " because ",
)
INVESTIGATION_SOURCE_TYPES = {"investigation_summary", "assistant_artifact", "tool_summary", "incident_note", "assistant_output"}
INVESTIGATION_ARTIFACT_KINDS = {"assistant_output", "tool_use_summary"}


@dataclass(frozen=True)
class SemanticExtraction:
    summary: str
    candidate_type: str | None = None
    decision_text: str | None = None
    decision_evidence_text: str | None = None
    investigation_text: str | None = None
    investigation_evidence_text: str | None = None
    rationale_text: str | None = None
    interest_text: str | None = None
    matched_phrase: str | None = None
    is_low_value_meta: bool = False
    constraint_text: str | None = None
    next_step_text: str | None = None
    blocker_text: str | None = None
    progress_text: str | None = None
    key_finding_text: str | None = None
    subject_hints: tuple[MemorySubjectAnchor, ...] = field(default_factory=tuple)
    work_refs: tuple[str, ...] = ()


def summarize_content(content: str) -> str:
    text = content.strip()
    if not text:
        return ""
    sentences = [item.strip() for item in SENTENCE_PATTERN.split(text) if item.strip()]
    if sentences:
        return sentences[0]
    return text[:200].strip()


# Common function words excluded from content-overlap checks. English + Hebrew.
# Lives with the tokenizer it serves — when additional languages are added,
# this set changes alongside the tokenizer and embedding model.
CONTENT_STOPWORDS: frozenset[str] = frozenset({
    # -- English --
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "must", "need",
    "i", "me", "my", "we", "us", "our", "you", "your", "he", "she",
    "it", "they", "them", "their", "its", "his", "her",
    "in", "on", "at", "to", "for", "of", "with", "by", "from", "up",
    "about", "into", "through", "during", "before", "after", "above",
    "below", "between", "out", "off", "over", "under",
    "and", "but", "or", "nor", "not", "so", "yet", "both", "either",
    "neither", "each", "every", "all", "any", "few", "more", "most",
    "other", "some", "such", "no", "only", "own", "same", "than", "too",
    "very", "just", "also", "now", "then", "here", "there", "when",
    "where", "why", "how", "what", "which", "who", "whom", "this",
    "that", "these", "those", "if", "as",
    # -- Hebrew --
    "של", "על", "את", "עם", "אל", "מן", "לא", "כי", "גם", "או",
    "אם", "הוא", "היא", "הם", "הן", "אני", "אנחנו", "אתה",
    "זה", "זו", "זאת", "אלה", "כל", "עוד", "רק", "כבר", "מאוד",
    "בין", "אבל", "אז", "כמו", "יותר", "פה", "שם",
})


def _is_low_information_content_token(token: str) -> bool:
    """Return True for tokens that are too weak to ground overlap checks.

    Keep this conservative: content_tokens powers multilingual overlap and
    duplicate checks, so only suppress fragments that are almost certainly
    punctuation fallout rather than meaningful content.
    """
    return token.isascii() and token.isalpha() and len(token) == 1


def content_tokens(text: str) -> set[str]:
    """Tokenize text and remove stopwords, returning content words only.

    Includes basic plural-stem variants (same rules as lexical retrieval)
    so that "batches" matches "batch" and vice versa.
    """
    raw = {
        token
        for token in set(normalize_for_index(text).split()) - CONTENT_STOPWORDS
        if not _is_low_information_content_token(token)
    }
    expanded: set[str] = set()
    for token in raw:
        expanded.add(token)
        if not token.isascii():
            continue
        # Plural stripping — mirrors retrieval/lexical.py _token_variants
        if len(token) > 4 and token.endswith("ies"):
            expanded.add(token[:-3] + "y")
        elif len(token) > 5 and token.endswith("es") and not token.endswith(("ses", "xes", "zes")):
            expanded.add(token[:-2])
        elif len(token) > 4 and token.endswith("s") and not token.endswith(("ss", "us", "is", "ses", "xes", "zes")):
            expanded.add(token[:-1])
    return expanded


def strip_terminal_punctuation(text: str) -> str:
    return text.strip().rstrip(" .!?;:")


def extract_decision_candidate(content: str) -> dict[str, str | None] | None:
    for pattern in DECISION_PATTERNS:
        match = pattern.search(content)
        if not match:
            continue
        body = strip_terminal_punctuation(match.group("body"))
        if not body:
            continue

        lowered = body.lower()
        decision_text = body
        rationale_text: str | None = None

        for splitter in RATIONALE_SPLITTERS:
            index = lowered.find(splitter)
            if index == -1:
                continue
            decision_text = strip_terminal_punctuation(body[:index])
            remainder = strip_terminal_punctuation(body[index + len(splitter) :])
            rationale_text = f"{splitter.strip()} {remainder}" if remainder else splitter.strip()
            break

        return {
            "decision_text": decision_text,
            "decision_evidence_text": strip_terminal_punctuation(match.group(0)),
            "rationale_text": rationale_text,
            "matched_phrase": match.group(0).split(match.group("body"))[0].strip(),
        }

    return None


def extract_investigation_candidate(source_item: SourceItem) -> dict[str, str | None] | None:
    source_type = source_item.source_type.lower()
    artifact_kind = (source_item.artifact_kind or "").lower()
    if source_type not in INVESTIGATION_SOURCE_TYPES and artifact_kind not in INVESTIGATION_ARTIFACT_KINDS:
        return None

    content = source_item.content
    for pattern in INVESTIGATION_PATTERNS:
        match = pattern.search(content)
        if not match:
            continue
        body = strip_terminal_punctuation(match.group("body"))
        if not body:
            continue

        lowered = body.lower()
        investigation_text = body
        rationale_text: str | None = None

        for splitter in INVESTIGATION_RATIONALE_SPLITTERS:
            index = lowered.find(splitter)
            if index == -1:
                continue
            investigation_text = strip_terminal_punctuation(body[:index])
            remainder = strip_terminal_punctuation(body[index + len(splitter) :])
            rationale_text = f"{splitter.strip()} {remainder}" if remainder else splitter.strip()
            break

        return {
            "investigation_text": investigation_text,
            "investigation_evidence_text": strip_terminal_punctuation(match.group(0)),
            "rationale_text": rationale_text,
            "matched_phrase": match.group(0).split(match.group("body"))[0].strip(),
        }

    return None


def deterministic_extraction(source_item: SourceItem) -> SemanticExtraction:
    summary = summarize_content(source_item.content)
    decision_candidate = extract_decision_candidate(source_item.content)
    if decision_candidate is not None:
        return SemanticExtraction(
            summary=summary,
            candidate_type="decision",
            decision_text=decision_candidate["decision_text"],
            decision_evidence_text=decision_candidate["decision_evidence_text"],
            rationale_text=decision_candidate["rationale_text"],
            matched_phrase=decision_candidate["matched_phrase"],
        )

    investigation_candidate = extract_investigation_candidate(source_item)
    if investigation_candidate is not None:
        return SemanticExtraction(
            summary=summary,
            candidate_type="investigation_outcome",
            investigation_text=investigation_candidate["investigation_text"],
            investigation_evidence_text=investigation_candidate["investigation_evidence_text"],
            rationale_text=investigation_candidate["rationale_text"],
            matched_phrase=investigation_candidate["matched_phrase"],
        )
    return SemanticExtraction(summary=summary)


def _normalize_for_containment(text: str) -> str:
    return " ".join(text.lower().split())


def has_grounded_decision_evidence(source_item: SourceItem, text: str | None) -> bool:
    """Check that decision evidence text is grounded in the source content.

    Language-agnostic: trusts the LLM's candidate_type classification and only
    verifies the extracted evidence is a substring of the source (anti-hallucination).
    """
    if not text:
        return False
    normalized = text.strip()
    if not normalized:
        return False
    return _normalize_for_containment(normalized) in _normalize_for_containment(source_item.content)


def has_grounded_investigation_evidence(source_item: SourceItem, text: str | None) -> bool:
    """Check that investigation evidence text is grounded in the source content.

    Language-agnostic: trusts the LLM's candidate_type classification and only
    verifies the extracted evidence is a substring of the source (anti-hallucination).
    """
    if not text:
        return False
    normalized = text.strip()
    if not normalized:
        return False
    return _normalize_for_containment(normalized) in _normalize_for_containment(source_item.content)


def _memory_text_view_name(memory_type: str) -> str:
    if memory_type == "decision":
        return "memory_object.decision_context"
    if memory_type == "investigation_outcome":
        return "memory_object.investigation_context"
    if memory_type == "interest":
        return "memory_object.interest_context"
    return "memory_object.summary"


def _resolve_actor_ref(source_item: SourceItem) -> str | None:
    """Determine actor_ref for a memory created from a source item.

    Private containers: propagate the speaker's actor_ref (personal memory).
    Shared containers (container/public): null (shared evidence).
    """
    if source_item.visibility == "private":
        return source_item.actor_ref
    return None


def build_process_result(
    source_item: SourceItem,
    extraction: SemanticExtraction,
    schema_prefix: str,
    semantic_metadata: dict[str, str] | None = None,
) -> ProcessResult:
    semantic_signals = _build_semantic_signal_payload(extraction, semantic_metadata=semantic_metadata)

    memory_objects: list[MemoryObject] = []
    relations: list[Relation] = []
    index_entries = []

    if (
        extraction.candidate_type == "decision"
        and extraction.decision_text
        and extraction.decision_evidence_text
        and has_grounded_decision_evidence(source_item, extraction.decision_evidence_text)
    ):
        canonical_key = normalize_for_index(extraction.decision_text)
        memory_objects.append(
            MemoryObject(
                type="decision",
                schema_id=f"{schema_prefix}.decision",
                schema_version="v1",
                payload={
                    "decision": extraction.decision_text,
                    "decision_evidence_text": extraction.decision_evidence_text,
                    "rationale": extraction.rationale_text,
                    "canonical_key": canonical_key,
                    "source_type": source_item.source_type,
                    "source_id": source_item.source_id,
                    **({"semantic_provenance": semantic_metadata} if semantic_metadata else {}),
                },
                visibility=source_item.visibility,
                container_ref=source_item.container_ref,
                actor_ref=_resolve_actor_ref(source_item),
            )
        )
        index_source = " ".join(
            part
            for part in (
                extraction.summary,
                extraction.decision_text or "",
                extraction.decision_evidence_text or "",
                extraction.rationale_text or "",
                canonical_key,
            )
            if part
        )
    elif (
        extraction.candidate_type == "investigation_outcome"
        and extraction.investigation_text
        and extraction.investigation_evidence_text
        and has_grounded_investigation_evidence(source_item, extraction.investigation_evidence_text)
    ):
        canonical_key = normalize_for_index(extraction.investigation_text)
        memory_objects.append(
            MemoryObject(
                type="investigation_outcome",
                schema_id=f"{schema_prefix}.investigation_outcome",
                schema_version="v1",
                payload={
                    "investigation_outcome": extraction.investigation_text,
                    "investigation_evidence_text": extraction.investigation_evidence_text,
                    "rationale": extraction.rationale_text,
                    "canonical_key": canonical_key,
                    "source_type": source_item.source_type,
                    "source_id": source_item.source_id,
                    **({"semantic_provenance": semantic_metadata} if semantic_metadata else {}),
                },
                visibility=source_item.visibility,
                container_ref=source_item.container_ref,
                actor_ref=_resolve_actor_ref(source_item),
            )
        )
        index_source = " ".join(
            part
            for part in (
                extraction.summary,
                extraction.investigation_text or "",
                extraction.investigation_evidence_text or "",
                extraction.rationale_text or "",
                extraction.key_finding_text or "",
                canonical_key,
            )
            if part
        )
    elif extraction.candidate_type == "interest" and extraction.interest_text and (
        not source_item.role or source_item.role.lower() == "user"
    ) and source_item.visibility not in ("container", "public"):
        memory_objects.append(
            MemoryObject(
                type="interest",
                schema_id=f"{schema_prefix}.interest",
                schema_version="v1",
                payload={
                    "interest_text": extraction.interest_text,
                    "summary": extraction.summary,
                    "source_type": source_item.source_type,
                    "source_id": source_item.source_id,
                    **({"semantic_provenance": semantic_metadata} if semantic_metadata else {}),
                },
                visibility=source_item.visibility,
                container_ref=source_item.container_ref,
                actor_ref=_resolve_actor_ref(source_item),
            )
        )
        index_source = " ".join(
            part
            for part in (
                extraction.summary,
                extraction.interest_text or "",
            )
            if part
        )
    elif _should_create_discussion_summary(source_item, extraction):
        memory_objects.append(
            MemoryObject(
                type="discussion_summary",
                schema_id=f"{schema_prefix}.discussion_summary",
                schema_version="v1",
                payload={
                    "summary": extraction.summary,
                    "source_type": source_item.source_type,
                    "source_id": source_item.source_id,
                    **({"semantic_provenance": semantic_metadata} if semantic_metadata else {}),
                },
                visibility=source_item.visibility,
                container_ref=source_item.container_ref,
                actor_ref=_resolve_actor_ref(source_item),
            )
        )
        index_source = " ".join(
            part
            for part in (
                extraction.summary,
                extraction.constraint_text or "",
                extraction.blocker_text or "",
                extraction.progress_text or "",
                extraction.next_step_text or "",
                extraction.key_finding_text or "",
            )
            if part
        )
    else:
        index_source = ""

    if memory_objects:
        memory_object = memory_objects[0]
        relations.append(
            Relation(
                from_kind="memory_object",
                from_id=memory_object.id,
                relation_type="supported_by",
                to_kind="source_item",
                to_id=source_item.id,
            )
        )
        index_entries.append(
            build_index_entry(
                target_kind="memory_object",
                target_id=memory_object.id,
                index_type="lexical",
                text_view=normalize_for_index(index_source),
                text_view_name=_memory_text_view_name(memory_object.type),
            )
        )
        embedding_text = build_embedding_text(memory_object)
        if embedding_text is not None:
            index_entries.append(
                build_index_entry(
                    target_kind="memory_object",
                    target_id=memory_object.id,
                    index_type=VECTOR_INDEX_TYPE,
                    text_view=embedding_text,
                    text_view_name=f"{_memory_text_view_name(memory_object.type)}.embedding",
                    provider_name=VECTOR_EMBEDDING_PROVIDER_NAME,
                    provider_version=VECTOR_EMBEDDING_PROVIDER_VERSION,
                )
            )

    thread_rebuild_requested = _should_request_thread_rebuild(source_item, extraction, memory_objects)
    metadata_updates: dict[str, dict[str, object]] = {}
    if semantic_signals:
        metadata_updates[source_item.id] = {SEMANTIC_SIGNAL_METADATA_KEY: semantic_signals}
    return ProcessResult(
        memory_objects=memory_objects,
        relations=relations,
        index_entries=index_entries,
        source_item_metadata_updates=metadata_updates,
        thread_rebuild_requested=thread_rebuild_requested,
    )


SELECTED_ASSISTANT_WORK_ARTIFACT_KINDS = {"tool_use_summary", "todo_snapshot"}


def _has_explicit_thread_signal(extraction: SemanticExtraction) -> bool:
    return any(
        getattr(extraction, field_name)
        for field_name in ("constraint_text", "blocker_text", "progress_text", "next_step_text", "key_finding_text")
    )


def _is_selected_assistant_work_artifact(source_item: SourceItem, extraction: SemanticExtraction) -> bool:
    return (
        not extraction.is_low_value_meta
        and (source_item.role or "").lower() == "assistant"
        and (source_item.artifact_kind or "").lower() in SELECTED_ASSISTANT_WORK_ARTIFACT_KINDS
    )


def _looks_like_low_value_meta_update(source_item: SourceItem, extraction: SemanticExtraction) -> bool:
    if extraction.is_low_value_meta:
        return True
    if _has_explicit_thread_signal(extraction):
        return False
    if (source_item.role or "").lower() != "assistant":
        return False
    normalized_text = normalize_for_index(" ".join(part for part in (source_item.content, extraction.summary) if part))
    if not normalized_text:
        return False
    if any(
        phrase in normalized_text
        for phrase in (
            "task complete",
            "nothing new to report",
            "no response requested",
            "no response needed",
            "no message needed",
        )
    ):
        return True
    return (
        ("local repos only" in normalized_text or "local cache only" in normalized_text)
        and (" auth " in f" {normalized_text} " or "authentication" in normalized_text)
    )

def _is_substantive_summary(source_item: SourceItem, extraction: SemanticExtraction) -> bool:
    if _looks_like_low_value_meta_update(source_item, extraction):
        return False
    if _has_explicit_thread_signal(extraction):
        return True
    summary_tokens = tokenize_text(extraction.summary)
    content_tokens_list = tokenize_text(source_item.content)
    if len(summary_tokens) >= 4:
        return True
    return len(content_tokens_list) >= 4


def _should_create_discussion_summary(source_item: SourceItem, extraction: SemanticExtraction) -> bool:
    if _looks_like_low_value_meta_update(source_item, extraction):
        return False
    if _is_selected_assistant_work_artifact(source_item, extraction):
        return True
    return _is_substantive_summary(source_item, extraction)


def _should_request_thread_rebuild(
    source_item: SourceItem,
    extraction: SemanticExtraction,
    memory_objects: list[MemoryObject],
) -> bool:
    if _looks_like_low_value_meta_update(source_item, extraction):
        return False
    has_supported_typed_memory = any(
        memory_object.type in {"decision", "investigation_outcome"}
        for memory_object in memory_objects
    )
    if has_supported_typed_memory:
        return True
    if _has_explicit_thread_signal(extraction):
        return True
    if _is_selected_assistant_work_artifact(source_item, extraction):
        return True
    if extraction.candidate_type in {"decision", "investigation_outcome"}:
        # Weak typed-looking candidates that fail evidence guards should not churn thread rebuilds.
        return False
    return _is_substantive_summary(source_item, extraction)


def _build_semantic_signal_payload(
    extraction: SemanticExtraction,
    *,
    semantic_metadata: dict[str, str] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {}
    if extraction.is_low_value_meta:
        payload["is_low_value_meta"] = True
    for field_name in ("constraint_text", "next_step_text", "blocker_text", "progress_text", "key_finding_text"):
        value = getattr(extraction, field_name)
        if value:
            payload[field_name] = value
    if payload and semantic_metadata:
        payload["semantic_provenance"] = semantic_metadata
    return payload
