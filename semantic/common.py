from __future__ import annotations

import re
from dataclasses import dataclass

from core.contracts import ProcessResult
from core.indexing import build_index_entry
from core.models import Annotation, MemoryObject, Relation, SourceItem


SENTENCE_PATTERN = re.compile(r"(?<=[.!?])\s+")
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
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
DECISION_EVIDENCE_PATTERNS = (
    re.compile(r"^\s*decision:\s*", re.IGNORECASE),
    re.compile(r"^\s*we decided(?: to)?\s+", re.IGNORECASE),
    re.compile(r"^\s*we chose\s+", re.IGNORECASE),
    re.compile(r"^\s*chosen approach[:\s]+", re.IGNORECASE),
    re.compile(r"^\s*we will use\s+", re.IGNORECASE),
)
INVESTIGATION_EVIDENCE_PATTERNS = (
    re.compile(r"^\s*root cause[:\s]+", re.IGNORECASE),
    re.compile(r"^\s*investigation found(?: that)?\s+", re.IGNORECASE),
    re.compile(r"^\s*investigation concluded(?: that)?\s+", re.IGNORECASE),
    re.compile(r"^\s*analysis found(?: that)?\s+", re.IGNORECASE),
    re.compile(r"^\s*findings?[:\s]+", re.IGNORECASE),
    re.compile(r"^\s*outcome[:\s]+", re.IGNORECASE),
    re.compile(r"^\s*we found that\s+", re.IGNORECASE),
    re.compile(r"^\s*verdict[:\s]+", re.IGNORECASE),
    re.compile(r"^\s*here's the verdict[:\s]+", re.IGNORECASE),
    re.compile(r"^\s*the verdict is\s+", re.IGNORECASE),
    re.compile(r"^\s*conclusion[:\s]+", re.IGNORECASE),
    re.compile(r"^\s*the conclusion is\s+", re.IGNORECASE),
)

WEAK_INVESTIGATION_EVIDENCE_PATTERN = re.compile(
    r"\b(may|might|could|should|watch|monitor|recommend(?:ed|s)?|proposal|prefer(?:s|red)?|need(?:ed|s)?|next step|risk)\b",
    re.IGNORECASE,
)
GROUNDED_INVESTIGATION_MARKER_PATTERN = re.compile(
    r"\b(verdict|conclusion|root cause|caused by|due to|because)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SemanticExtraction:
    summary: str
    candidate_type: str | None = None
    decision_text: str | None = None
    decision_evidence_text: str | None = None
    investigation_text: str | None = None
    investigation_evidence_text: str | None = None
    rationale_text: str | None = None
    matched_phrase: str | None = None


def summarize_content(content: str) -> str:
    text = content.strip()
    if not text:
        return ""
    sentences = [item.strip() for item in SENTENCE_PATTERN.split(text) if item.strip()]
    if sentences:
        return sentences[0]
    return text[:200].strip()


def normalize_for_index(text: str) -> str:
    return " ".join(TOKEN_PATTERN.findall(text.lower()))


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


def has_explicit_decision_evidence(text: str | None) -> bool:
    if not text:
        return False
    return any(pattern.search(text) for pattern in DECISION_EVIDENCE_PATTERNS)


def has_explicit_investigation_evidence(text: str | None) -> bool:
    if not text:
        return False
    return any(pattern.search(text) for pattern in INVESTIGATION_EVIDENCE_PATTERNS)


def has_grounded_investigation_evidence(source_item: SourceItem, text: str | None) -> bool:
    if has_explicit_investigation_evidence(text):
        return True
    if not text:
        return False
    normalized = text.strip()
    if not normalized:
        return False
    lowered = normalized.lower()
    if lowered not in source_item.content.lower():
        return False
    if WEAK_INVESTIGATION_EVIDENCE_PATTERN.search(normalized):
        return False
    if has_explicit_decision_evidence(normalized):
        return False
    return bool(GROUNDED_INVESTIGATION_MARKER_PATTERN.search(normalized))


def _memory_text_view_name(memory_type: str) -> str:
    if memory_type == "decision":
        return "memory_object.decision_context"
    if memory_type == "investigation_outcome":
        return "memory_object.investigation_context"
    return "memory_object.summary"


def build_process_result(
    source_item: SourceItem,
    extraction: SemanticExtraction,
    schema_prefix: str,
    semantic_metadata: dict[str, str] | None = None,
) -> ProcessResult:
    summary_payload = {"text": extraction.summary}
    if semantic_metadata:
        summary_payload["semantic_provenance"] = semantic_metadata

    annotations = [
        Annotation(
            source_item_id=source_item.id,
            type="summary",
            schema_id="core.summary",
            schema_version="v1",
            payload=summary_payload,
        )
    ]

    if (
        extraction.candidate_type == "decision"
        and extraction.decision_text
        and extraction.decision_evidence_text
        and has_explicit_decision_evidence(extraction.decision_evidence_text)
    ):
        candidate_payload = {
            "candidate_type": "decision",
            "decision_text": extraction.decision_text,
            "decision_evidence_text": extraction.decision_evidence_text,
            "rationale_text": extraction.rationale_text,
        }
        if semantic_metadata:
            candidate_payload["semantic_provenance"] = semantic_metadata
        if extraction.matched_phrase:
            candidate_payload["matched_phrase"] = extraction.matched_phrase
        annotations.append(
            Annotation(
                source_item_id=source_item.id,
                type="typed_candidate",
                schema_id=f"{schema_prefix}.typed_candidate",
                schema_version="v1",
                payload=candidate_payload,
            )
        )
        memory_object = MemoryObject(
            type="decision",
            schema_id=f"{schema_prefix}.decision",
            schema_version="v1",
            payload={
                "decision": extraction.decision_text,
                "decision_evidence_text": extraction.decision_evidence_text,
                "rationale": extraction.rationale_text,
                "source_type": source_item.source_type,
                "source_id": source_item.source_id,
                **({"semantic_provenance": semantic_metadata} if semantic_metadata else {}),
            },
            visibility_context=source_item.visibility_context,
        )
        index_source = " ".join(
            part
            for part in (
                extraction.summary,
                extraction.decision_text or "",
                extraction.decision_evidence_text or "",
                extraction.rationale_text or "",
            )
            if part
        )
    elif (
        extraction.candidate_type == "investigation_outcome"
        and extraction.investigation_text
        and extraction.investigation_evidence_text
        and has_grounded_investigation_evidence(source_item, extraction.investigation_evidence_text)
    ):
        candidate_payload = {
            "candidate_type": "investigation_outcome",
            "investigation_text": extraction.investigation_text,
            "investigation_evidence_text": extraction.investigation_evidence_text,
            "rationale_text": extraction.rationale_text,
        }
        if semantic_metadata:
            candidate_payload["semantic_provenance"] = semantic_metadata
        if extraction.matched_phrase:
            candidate_payload["matched_phrase"] = extraction.matched_phrase
        annotations.append(
            Annotation(
                source_item_id=source_item.id,
                type="typed_candidate",
                schema_id=f"{schema_prefix}.typed_candidate",
                schema_version="v1",
                payload=candidate_payload,
            )
        )
        memory_object = MemoryObject(
            type="investigation_outcome",
            schema_id=f"{schema_prefix}.investigation_outcome",
            schema_version="v1",
            payload={
                "investigation_outcome": extraction.investigation_text,
                "investigation_evidence_text": extraction.investigation_evidence_text,
                "rationale": extraction.rationale_text,
                "source_type": source_item.source_type,
                "source_id": source_item.source_id,
                **({"semantic_provenance": semantic_metadata} if semantic_metadata else {}),
            },
            visibility_context=source_item.visibility_context,
        )
        index_source = " ".join(
            part
            for part in (
                extraction.summary,
                extraction.investigation_text or "",
                extraction.investigation_evidence_text or "",
                extraction.rationale_text or "",
            )
            if part
        )
    else:
        memory_object = MemoryObject(
            type="discussion_summary",
            schema_id=f"{schema_prefix}.discussion_summary",
            schema_version="v1",
            payload={
                "summary": extraction.summary,
                "source_type": source_item.source_type,
                "source_id": source_item.source_id,
                **({"semantic_provenance": semantic_metadata} if semantic_metadata else {}),
            },
            visibility_context=source_item.visibility_context,
        )
        index_source = extraction.summary

    relation = Relation(
        from_kind="memory_object",
        from_id=memory_object.id,
        relation_type="supported_by",
        to_kind="source_item",
        to_id=source_item.id,
    )
    index_entry = build_index_entry(
        target_kind="memory_object",
        target_id=memory_object.id,
        index_type="lexical",
        text_view=normalize_for_index(index_source),
        text_view_name=_memory_text_view_name(memory_object.type),
    )
    return ProcessResult(
        annotations=annotations,
        memory_objects=[memory_object],
        relations=[relation],
        index_entries=[index_entry],
    )