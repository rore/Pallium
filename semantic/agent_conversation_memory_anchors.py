from __future__ import annotations

from typing import Iterable

from core.models import MemoryObject, MemorySubjectAnchor, QueryResultItem, SourceItem
from semantic.common import normalize_for_index

ALLOWED_SUBJECT_ANCHOR_KINDS = ("workstream", "component", "surface")

ANCHOR_KIND_PRECEDENCE = ("workstream", "component", "surface")

SUBJECT_HINT_METADATA_KEY = "pallium_subject_hints"


def _serialize_subject_anchors(subjects: Iterable[MemorySubjectAnchor]) -> list[dict[str, str]]:
    return [{"kind": subject.kind, "value": subject.value} for subject in subjects]


def _serialize_subject_anchor(subject: MemorySubjectAnchor) -> dict[str, str]:
    return {"kind": subject.kind, "value": subject.value}


def _deserialize_subject_anchor(payload: object) -> MemorySubjectAnchor | None:
    if not isinstance(payload, dict):
        return None
    kind = str(payload.get("kind") or "").strip().lower()
    value = str(payload.get("value") or "").strip()
    if kind not in ALLOWED_SUBJECT_ANCHOR_KINDS or not value:
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
        if kind not in ALLOWED_SUBJECT_ANCHOR_KINDS or not value:
            continue
        anchors.append(MemorySubjectAnchor(kind=kind, value=value))
    return _merge_subject_anchors(anchors)


def _subject_anchors_from_source_items(source_items: Iterable[SourceItem]) -> list[MemorySubjectAnchor]:
    return _merge_subject_anchors(*(_subject_anchors_from_metadata(source_item.metadata) for source_item in source_items))


def _subject_anchors_from_memory_objects(memory_objects: Iterable[MemoryObject]) -> list[MemorySubjectAnchor]:
    return _merge_subject_anchors(*(memory_object.envelope.subjects for memory_object in memory_objects if memory_object.envelope is not None))


def _normalized_subject_anchor(subject: MemorySubjectAnchor) -> MemorySubjectAnchor | None:
    value = _anchor_display_value(subject.value)
    if not value or subject.kind not in ALLOWED_SUBJECT_ANCHOR_KINDS:
        return None
    return MemorySubjectAnchor(kind=subject.kind, value=value)


def _item_subjects_by_kind(item: QueryResultItem) -> dict[str, list[MemorySubjectAnchor]]:
    subjects_by_kind: dict[str, list[MemorySubjectAnchor]] = {kind: [] for kind in ALLOWED_SUBJECT_ANCHOR_KINDS}
    if item.envelope is None:
        return subjects_by_kind
    for subject in item.envelope.subjects:
        normalized = _normalized_subject_anchor(subject)
        if normalized is None:
            continue
        subjects_by_kind[normalized.kind].append(normalized)
    return subjects_by_kind


def _infer_selected_query_anchor(
    query_tokens: tuple[str, ...],
    candidates: list[QueryResultItem],
) -> dict[str, object]:
    query_token_set = set(query_tokens)
    best_anchor: MemorySubjectAnchor | None = None
    best_kind: str | None = None
    status = "none"
    ambiguous_kind: str | None = None
    for kind in ANCHOR_KIND_PRECEDENCE:
        anchors_by_key: dict[str, tuple[MemorySubjectAnchor, tuple[str, ...]]] = {}
        single_token_counts: dict[str, int] = {}
        for item in candidates:
            if item.result_kind != "memory_hit":
                continue
            for subject in _item_subjects_by_kind(item).get(kind, []):
                normalized_key = _anchor_key(subject)
                if normalized_key in anchors_by_key:
                    continue
                token_tuple = tuple(token for token in normalize_for_index(subject.value).split() if token)
                if not token_tuple:
                    continue
                anchors_by_key[normalized_key] = (subject, token_tuple)
                if len(token_tuple) == 1:
                    single_token = token_tuple[0]
                    single_token_counts[single_token] = single_token_counts.get(single_token, 0) + 1
        matches: list[tuple[int, int, MemorySubjectAnchor]] = []
        for subject, token_tuple in anchors_by_key.values():
            if len(token_tuple) > 1:
                if all(token in query_token_set for token in token_tuple):
                    matches.append((2, len(token_tuple), subject))
                continue
            token = token_tuple[0]
            if token in query_token_set and single_token_counts.get(token, 0) == 1:
                matches.append((1, 1, subject))
        if not matches:
            continue
        matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
        top_strength = matches[0][:2]
        top_matches = [match for match in matches if match[:2] == top_strength]
        if len(top_matches) == 1:
            best_anchor = top_matches[0][2]
            best_kind = kind
            status = "clear"
            break
        status = "ambiguous"
        ambiguous_kind = kind
        break
    return {
        "status": status,
        "selected_anchor": best_anchor,
        "selected_anchor_kind": best_kind if status == "clear" else ambiguous_kind,
    }


def _classify_memory_candidate_anchor_state(
    item: QueryResultItem,
    selected_anchor: MemorySubjectAnchor | None,
) -> str:
    if item.result_kind != "memory_hit":
        raise ValueError("Anchor state classification only applies to memory-hit candidates.")
    if selected_anchor is None:
        raise ValueError("Selected query anchor is required for anchor-state classification.")
    if item.envelope is None or not item.envelope.subjects:
        return "unanchored_legacy"
    subjects_by_kind = _item_subjects_by_kind(item)
    same_kind_subjects = subjects_by_kind.get(selected_anchor.kind, [])
    if not same_kind_subjects:
        return "anchored_insufficient"
    selected_key = _anchor_key(selected_anchor)
    if any(_anchor_key(subject) == selected_key for subject in same_kind_subjects):
        return "anchored_aligned"
    return "anchored_conflicting"