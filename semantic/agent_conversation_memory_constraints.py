from __future__ import annotations

from typing import Iterable

from core.models import MemoryEnvelopeConfidence, MemorySubjectAnchor, SourceItem
from semantic.common import normalize_for_index

SUBJECT_HINT_METADATA_KEY = "pallium_subject_hints"

CONSTRAINT_MEMORY_TYPE = "constraint_memory"

CONSTRAINT_MEMORY_SCHEMA_ID = "agent_conversation_memory.constraint_memory"

CONSTRAINT_MEMORY_SCHEMA_VERSION = "v1"

CONSTRAINT_ALLOWED_ANCHOR_KINDS = {"workstream", "component", "surface"}

CONSTRAINT_TOOL_MARKERS = (
    "browser",
    "jira",
    "slack",
    "auth",
    "authenticate",
    "authentication",
    "login",
    "tracker",
    "portal",
    "workspace",
    "local repo",
    "local repos",
)

CONSTRAINT_MARKERS = (
    "blocked from",
    "use only",
    "instead of",
    "ask you directly",
    "ask the user directly",
    "do not",
    "don't",
    "forbid",
    "forbids",
    "prohibit",
    "prohibits",
)


def _serialize_subject_anchors(subjects: Iterable[MemorySubjectAnchor]) -> list[dict[str, str]]:
    return [{"kind": subject.kind, "value": subject.value} for subject in subjects]

def _serialize_subject_anchor(subject: MemorySubjectAnchor) -> dict[str, str]:
    return {"kind": subject.kind, "value": subject.value}

def _deserialize_subject_anchor(payload: object) -> MemorySubjectAnchor | None:
    if not isinstance(payload, dict):
        return None
    kind = str(payload.get("kind") or "").strip().lower()
    value = str(payload.get("value") or "").strip()
    if kind not in CONSTRAINT_ALLOWED_ANCHOR_KINDS or not value:
        return None
    return MemorySubjectAnchor(kind=kind, value=value)

def _anchor_display_value(value: str) -> str:
    normalized = normalize_for_index(value).split()
    if not normalized:
        return ""
    leading_noise_tokens = {
        "a",
        "an",
        "and",
        "attempt",
        "authenticate",
        "by",
        "can",
        "cannot",
        "connect",
        "don",
        "for",
        "from",
        "in",
        "into",
        "log",
        "login",
        "no",
        "not",
        "of",
        "on",
        "only",
        "open",
        "opening",
        "or",
        "point",
        "sign",
        "t",
        "the",
        "to",
        "try",
        "trying",
        "use",
        "using",
        "with",
    }
    trailing_noise_tokens = {"again", "here", "manually", "please", "there"}
    while normalized and (normalized[0] in leading_noise_tokens or (len(normalized[0]) == 1 and not normalized[0].isdigit())):
        normalized = normalized[1:]
    while normalized and normalized[-1] in trailing_noise_tokens:
        normalized = normalized[:-1]
    singular_map = {"mirrors": "mirror", "snapshots": "snapshot", "exports": "export"}
    normalized = [singular_map.get(token, token) for token in normalized]
    return " ".join(normalized)

def _anchor_key(subject: MemorySubjectAnchor) -> str:
    return f"{subject.kind}:{_anchor_display_value(subject.value)}"

def _merge_subject_anchors(*groups: Iterable[MemorySubjectAnchor]) -> list[MemorySubjectAnchor]:
    merged: list[MemorySubjectAnchor] = []
    seen: set[tuple[str, str]] = set()
    for group in groups:
        for subject in group:
            value = str(subject.value or "").strip()
            if not value:
                continue
            key = (subject.kind, value.lower())
            if key in seen:
                continue
            seen.add(key)
            merged.append(MemorySubjectAnchor(kind=subject.kind, value=value))
    return merged

def _subject_anchors_from_metadata(metadata: dict[str, object] | None) -> list[MemorySubjectAnchor]:
    if not isinstance(metadata, dict):
        return []
    raw_subjects = metadata.get(SUBJECT_HINT_METADATA_KEY)
    if not isinstance(raw_subjects, list):
        return []
    anchors: list[MemorySubjectAnchor] = []
    for raw_subject in raw_subjects:
        if not isinstance(raw_subject, dict):
            continue
        kind = str(raw_subject.get("kind") or "").strip().lower()
        value = str(raw_subject.get("value") or "").strip()
        if kind not in {"workstream", "component", "surface"} or not value:
            continue
        anchors.append(MemorySubjectAnchor(kind=kind, value=value))
    return _merge_subject_anchors(anchors)

def _subject_anchors_from_source_items(source_items: Iterable[SourceItem]) -> list[MemorySubjectAnchor]:
    return _merge_subject_anchors(*(_subject_anchors_from_metadata(source_item.metadata) for source_item in source_items))

def _subject_anchors_from_memory_objects(memory_objects) -> list[MemorySubjectAnchor]:
    return _merge_subject_anchors(*(memory_object.envelope.subjects for memory_object in memory_objects if memory_object.envelope is not None))
