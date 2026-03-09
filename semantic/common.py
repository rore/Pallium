from __future__ import annotations

import re
from dataclasses import dataclass

from core.contracts import ProcessResult
from core.models import Annotation, IndexEntry, MemoryObject, Relation, SourceItem


SENTENCE_PATTERN = re.compile(r"(?<=[.!?])\s+")
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
DECISION_PATTERNS = (
    re.compile(r"\bdecision:\s*(?P<body>.+)", re.IGNORECASE),
    re.compile(r"\bwe decided(?: to)?\s+(?P<body>.+)", re.IGNORECASE),
    re.compile(r"\bwe chose\s+(?P<body>.+)", re.IGNORECASE),
    re.compile(r"\bchosen approach[:\s]+(?P<body>.+)", re.IGNORECASE),
    re.compile(r"\bwe will use\s+(?P<body>.+)", re.IGNORECASE),
)
RATIONALE_SPLITTERS = (
    " because ",
    " to avoid ",
    " to prevent ",
    " so that ",
)


@dataclass(frozen=True)
class SemanticExtraction:
    summary: str
    candidate_type: str | None = None
    decision_text: str | None = None
    decision_evidence_text: str | None = None
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



def deterministic_extraction(content: str) -> SemanticExtraction:
    summary = summarize_content(content)
    candidate = extract_decision_candidate(content)
    if candidate is None:
        return SemanticExtraction(summary=summary)
    return SemanticExtraction(
        summary=summary,
        candidate_type="decision",
        decision_text=candidate["decision_text"],
        decision_evidence_text=candidate["decision_evidence_text"],
        rationale_text=candidate["rationale_text"],
        matched_phrase=candidate["matched_phrase"],
    )



def build_process_result(
    source_item: SourceItem,
    extraction: SemanticExtraction,
    schema_prefix: str,
) -> ProcessResult:
    annotations = [
        Annotation(
            source_item_id=source_item.id,
            type="summary",
            schema_id="core.summary",
            schema_version="v1",
            payload={"text": extraction.summary},
        )
    ]

    if extraction.candidate_type == "decision" and extraction.decision_text and extraction.decision_evidence_text:
        candidate_payload = {
            "candidate_type": "decision",
            "decision_text": extraction.decision_text,
            "decision_evidence_text": extraction.decision_evidence_text,
            "rationale_text": extraction.rationale_text,
        }
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
            },
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
    else:
        memory_object = MemoryObject(
            type="discussion_summary",
            schema_id=f"{schema_prefix}.discussion_summary",
            schema_version="v1",
            payload={
                "summary": extraction.summary,
                "source_type": source_item.source_type,
                "source_id": source_item.source_id,
            },
        )
        index_source = extraction.summary

    relation = Relation(
        from_kind="memory_object",
        from_id=memory_object.id,
        relation_type="supported_by",
        to_kind="source_item",
        to_id=source_item.id,
    )
    index_entry = IndexEntry(
        target_kind="memory_object",
        target_id=memory_object.id,
        index_type="lexical",
        text_view=normalize_for_index(index_source),
    )
    return ProcessResult(
        annotations=annotations,
        memory_objects=[memory_object],
        relations=[relation],
        index_entries=[index_entry],
    )
