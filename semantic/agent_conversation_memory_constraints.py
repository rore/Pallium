from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import replace
from datetime import datetime, timezone
from typing import Iterable, Sequence

from core.contracts import ProcessResult
from core.indexing import build_index_entry
from core.models import MemoryEnvelopeConfidence, MemoryObject, MemorySubjectAnchor, QueryResultItem, QueryRuntimeContext, SourceItem
from semantic.common import ConstraintCandidate, normalize_for_index

SUBJECT_HINT_METADATA_KEY = "pallium_subject_hints"

CONSTRAINT_MEMORY_TYPE = "constraint_memory"

CONSTRAINT_MEMORY_SCHEMA_ID = "agent_conversation_memory.constraint_memory"

CONSTRAINT_MEMORY_SCHEMA_VERSION = "v1"

CONSTRAINT_ALLOWED_ANCHOR_KINDS = {"workstream", "component", "surface"}

CONSTRAINT_ACTION_CLASSES = {"use_surface", "use_source", "perform_step"}

CONSTRAINT_POLARITIES = {"prohibit", "prefer", "require"}

CONSTRAINT_CONFIDENCES = {"high", "medium", "low", "unknown"}

CONSTRAINT_HARD_POLARITIES = {"prohibit", "require"}

CONSTRAINT_STATUSES = {"active", "superseded"}

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

STRUCTURED_CONFLICT_MEMORY_TYPES = {"task_checkpoint", "thread_summary", "discussion_summary"}

OPERATIONAL_GUIDANCE_MARKERS = (
    "next step",
    "should ",
    "need to ",
    "must ",
    "attempt ",
    "retry ",
    "resume ",
    "rerun ",
    "refresh ",
    "connect ",
    "authenticate",
    "sign in",
    "log in",
    "login",
    "open ",
    "use ",
)

CONSTRAINT_POLICY_STOPWORDS = {
    "and",
    "avoid",
    "blocked",
    "constraint",
    "constraints",
    "do",
    "dont",
    "forbid",
    "for",
    "forbidden",
    "forbids",
    "from",
    "never",
    "not",
    "only",
    "operator",
    "or",
    "please",
    "remember",
    "using",
    "without",
}

CONSTRAINT_POLICY_ACTION_TOKENS = {
    "attempt",
    "attempted",
    "attempting",
    "attempts",
    "auth",
    "authenticate",
    "authentication",
    "connect",
    "connected",
    "connecting",
    "fetch",
    "fetched",
    "fetching",
    "log",
    "login",
    "manual",
    "manually",
    "open",
    "refresh",
    "refreshed",
    "refreshing",
    "rerun",
    "resume",
    "restore",
    "restored",
    "retry",
    "sign",
    "signin",
    "use",
    "using",
}

CONSTRAINT_POLICY_LOW_SIGNAL_TOKENS = {
    "local",
    "note",
    "noted",
    "operator",
    "state",
}

CONSTRAINT_FOCUS_TOOL_TOKENS = {
    "auth",
    "authenticate",
    "authentication",
    "browser",
    "jira",
    "login",
    "portal",
    "repo",
    "repos",
    "slack",
    "tracker",
    "workspace",
}

CONSTRAINT_ONLY_RESIDUAL_TOKENS = {
    "and",
    "constraint",
    "constraints",
    "current",
    "note",
    "noted",
    "reminder",
    "remember",
    "state",
}

CONSTRAINT_SURFACE_ANCHOR_PATTERN = re.compile(r"\b(?P<value>(?:[a-z0-9]+(?:[- ][a-z0-9]+){0,3})\s+(?:portal|browser|console|dashboard|ui|endpoint|surface))\b", re.IGNORECASE)

CONSTRAINT_SOURCE_ANCHOR_PATTERN = re.compile(r"\b(?P<value>(?:[a-z0-9]+(?:[- ][a-z0-9]+){0,3})\s+(?:mirror|mirrors|snapshot|snapshots|export|exports))\b", re.IGNORECASE)

CONSTRAINT_STEP_ANCHOR_PATTERN = re.compile(r"\b(?P<value>(?:manual\s+)?(?:retry|rerun|reset|refresh|reconnect|connect))\b", re.IGNORECASE)

CONSTRAINT_PREFER_MARKERS = ("use only", "only use", "prefer", "preferred", "rather than", "instead of")

CONSTRAINT_REQUIRE_MARKERS = ("must use", "required", "require", "must", "needs to use")

CONSTRAINT_PROHIBIT_MARKERS = ("do not", "don't", "dont", "cannot", "can't", "avoid", "forbid", "forbidden", "prohibit")

CONSTRAINT_GUIDANCE_POSITIVE_MARKERS = ("use ", "open ", "attempt ", "try ", "trying ", "connect ", "sign in", "log in", "authenticate", "retry", "rerun", "refresh", "reset", "reconnect")

TASK_CHECKPOINT_TEXT_VIEW = "memory_object.task_checkpoint_context"

THREAD_SUMMARY_TEXT_VIEW = "memory_object.thread_summary_context"

ROUTING_META_QUERY_TOKENS = {
    "a",
    "about",
    "already",
    "an",
    "before",
    "did",
    "do",
    "exact",
    "have",
    "i",
    "need",
    "previously",
    "show",
    "source",
    "support",
    "supported",
    "the",
    "this",
    "trace",
    "we",
    "what",
    "which",
    "again",
    "can",
    "had",
    "have",
    "here",
    "in",
    "is",
    "lately",
    "latest",
    "me",
    "sir",
    "that",
    "there",
    "you",
}


def _parse_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    parsed: list[str] = []
    for item in value:
        text = str(item or '').strip()
        if text and text not in parsed:
            parsed.append(text)
    return parsed


def _join_unique_text_parts(parts: list[str]) -> str:
    seen: set[str] = set()
    ordered: list[str] = []
    for part in parts:
        normalized = str(part or '').strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(normalized)
    return ' '.join(ordered)


def _routing_result_id(item: QueryResultItem) -> str:
    return str(item.result_id)


def _routing_query_tokens(text: str) -> tuple[str, ...]:
    return tuple(token for token in normalize_for_index(str(text or '')).split() if token)


def _routing_item_text(item: QueryResultItem) -> str:
    if item.result_kind == 'source_hit':
        return str(item.excerpt or '')
    payload = item.payload or {}
    parts: list[str] = []
    for key in (
        'decision',
        'investigation_outcome',
        'summary',
        'rationale',
        'continuity_question',
        'carry_forward_answer',
        'task',
        'current_state',
        'blocker_state',
        'next_step',
        'freshness_signal',
        'constraint_text',
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value)
    for key in ('key_findings', 'evidence'):
        parts.extend(_parse_string_list(payload.get(key)))
    conclusions = payload.get('conclusions', [])
    if isinstance(conclusions, list):
        for conclusion in conclusions:
            if isinstance(conclusion, dict):
                text = str(conclusion.get('text') or '').strip()
                if text:
                    parts.append(text)
    selected = payload.get('selected_work_artifacts', [])
    if isinstance(selected, list):
        for artifact in selected:
            if isinstance(artifact, dict):
                text = str(artifact.get('text') or '').strip()
                if text:
                    parts.append(text)
    return _join_unique_text_parts(parts)


def _routing_item_tokens(item: QueryResultItem) -> tuple[str, ...]:
    return _routing_query_tokens(_routing_item_text(item))


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

def _constraint_supersession_identity(primary_scope_anchor: MemorySubjectAnchor, target_anchor: MemorySubjectAnchor, action_class: str) -> str:
    return "|".join((_anchor_key(primary_scope_anchor), _anchor_key(target_anchor), action_class))

def _constraint_compatibility_domain(primary_scope_anchor: MemorySubjectAnchor, action_class: str) -> str:
    return "|".join((_anchor_key(primary_scope_anchor), action_class))

def _constraint_strength_for_polarity(polarity: str) -> str:
    return "hard" if polarity in CONSTRAINT_HARD_POLARITIES else "soft"

def _constraint_confidence_from_candidate(candidate: ConstraintCandidate) -> MemoryEnvelopeConfidence:
    confidence = str(candidate.confidence or "unknown").strip().lower()
    return confidence if confidence in CONSTRAINT_CONFIDENCES else "unknown"

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

def _subject_anchors_from_memory_objects(memory_objects: Iterable[MemoryObject]) -> list[MemorySubjectAnchor]:
    return _merge_subject_anchors(*(memory_object.envelope.subjects for memory_object in memory_objects if memory_object.envelope is not None))

def _constraint_summary_text(candidate: ConstraintCandidate) -> str:
    if candidate.polarity == "prohibit":
        return f"Constraint: do not use {candidate.target_anchor.value}."
    if candidate.polarity == "require":
        return f"Constraint: require {candidate.target_anchor.value} for {candidate.primary_scope_anchor.value}."
    return f"Constraint: prefer {candidate.target_anchor.value} for {candidate.primary_scope_anchor.value}."

def _structured_constraint_profile_from_item(item: QueryResultItem) -> dict[str, object] | None:
    if item.result_kind != "memory_hit" or item.type not in STRUCTURED_CONFLICT_MEMORY_TYPES:
        return None
    payload = item.payload or {}
    return _structured_constraint_profile_from_payload(
        memory_type=str(item.type or ""),
        payload=payload,
        result_id=_routing_result_id(item),
        freshness_at=item.freshness_at,
    )

def _structured_payload_constraint_fragments(memory_type: str, payload: dict[str, object]) -> list[str]:
    fragments: list[str] = []
    if memory_type == "task_checkpoint":
        fragments.extend(
            str(payload.get(key) or "")
            for key in ("summary", "current_state", "blocker_state")
        )
        fragments.extend(str(value or "") for value in _parse_string_list(payload.get("key_findings")))
        fragments.extend(str(value or "") for value in _parse_string_list(payload.get("evidence")))
    elif memory_type in {"thread_summary", "discussion_summary"}:
        fragments.append(str(payload.get("summary") or ""))
    return fragments

def _structured_payload_guidance_fragments(memory_type: str, payload: dict[str, object]) -> list[str]:
    fragments: list[str] = []
    if memory_type == "task_checkpoint":
        next_step = str(payload.get("next_step") or "").strip()
        if next_step:
            fragments.append(next_step)
        for key in ("summary", "current_state", "blocker_state"):
            value = str(payload.get(key) or "").strip()
            if value and _text_contains_operational_guidance(value):
                fragments.append(value)
    elif memory_type in {"thread_summary", "discussion_summary"}:
        summary = str(payload.get("summary") or "").strip()
        if summary and _text_contains_operational_guidance(summary):
            fragments.append(summary)
    return fragments

def _text_contains_operational_guidance(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    lowered = normalized.lower()
    non_constraint = _strip_constraint_snippets(normalized).strip()
    target = non_constraint.lower() if re.search(r"\w", non_constraint) else lowered
    return any(marker in target for marker in OPERATIONAL_GUIDANCE_MARKERS)

def _constraint_policy_tokens(text: str) -> set[str]:
    return {
        token
        for token in _routing_query_tokens(text)
        if (
            len(token) > 2
            and token not in CONSTRAINT_POLICY_STOPWORDS
            and token not in ROUTING_META_QUERY_TOKENS
        )
    }

def _constraint_focus_tokens(tokens: Iterable[str]) -> set[str]:
    return {
        token
        for token in tokens
        if token not in CONSTRAINT_POLICY_ACTION_TOKENS and token not in CONSTRAINT_POLICY_LOW_SIGNAL_TOKENS
    }

def _exclusive_constraint_tokens(text: str) -> set[str]:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return set()
    clauses: list[str] = []
    for pattern in (
        r"use only (?P<clause>.+?)(?: instead of| rather than|$)",
        r"only use (?P<clause>.+?)(?: instead of| rather than|$)",
    ):
        for match in re.finditer(pattern, normalized):
            clause = str(match.group("clause") or "").strip(" .,;:")
            if clause:
                clauses.append(clause)
    if not clauses:
        return set()
    return _constraint_focus_tokens(_constraint_policy_tokens(" ".join(clauses)))

def _prohibited_constraint_focus_tokens(text: str) -> set[str]:
    focus_tokens: set[str] = set()
    for snippet in _extract_constraint_snippets(text):
        lowered = snippet.lower()
        if "use only" in lowered or "only use" in lowered:
            continue
        tokens = _constraint_policy_tokens(snippet)
        tool_tokens = tokens.intersection(CONSTRAINT_FOCUS_TOOL_TOKENS)
        if tool_tokens:
            focus_tokens.update(tool_tokens)
    return focus_tokens

def _candidate_has_self_conflicting_guidance(candidate: dict[str, object]) -> bool:
    item = candidate["item"]
    assert isinstance(item, QueryResultItem)
    profile = _structured_constraint_profile_from_item(item)
    if profile is None:
        return False
    return _structured_item_conflicts_with_constraint(item, profile)

def _structured_item_conflicts_with_constraint(item: QueryResultItem, constraint_profile: dict[str, object]) -> bool:
    payload = item.payload or {}
    return any(
        _structured_text_conflicts_with_constraint(fragment, constraint_profile)
        for fragment in _structured_payload_guidance_fragments(str(item.type or ""), payload)
    )

def _candidate_conflicts_with_constraint(item: QueryResultItem, constraint_profile: dict[str, object]) -> bool:
    if item.result_kind == "source_hit":
        return _structured_text_conflicts_with_constraint(str(item.excerpt or ""), constraint_profile)
    return _structured_item_conflicts_with_constraint(item, constraint_profile)

def _constraint_profile_sort_key(profile: dict[str, object]) -> tuple[datetime, int, int]:
    freshness_at = profile.get("freshness_at")
    if not isinstance(freshness_at, datetime):
        freshness_at = datetime.min.replace(tzinfo=timezone.utc)
    source_priority = 1 if profile.get("profile_source") == "local_typed" else 0
    text_length = len(str(profile.get("constraint_text") or ""))
    return freshness_at, source_priority, text_length

def _constraint_anchor_matches(pattern: re.Pattern[str], text: str, *, kind: str = "surface") -> list[MemorySubjectAnchor]:
    matches: list[MemorySubjectAnchor] = []
    seen: set[tuple[str, str]] = set()
    for match in pattern.finditer(text):
        value = str(match.group("value") or "").strip(" .,:;-")
        display_value = _anchor_display_value(value)
        if not display_value:
            continue
        key = (kind, display_value)
        if key in seen:
            continue
        seen.add(key)
        matches.append(MemorySubjectAnchor(kind=kind, value=display_value))
    return matches

def _constraint_action_target_pairs(text: str) -> list[tuple[str, MemorySubjectAnchor]]:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return []
    pairs: list[tuple[str, MemorySubjectAnchor]] = []
    seen: set[tuple[str, str]] = set()
    for action_class, pattern in (
        ("use_source", CONSTRAINT_SOURCE_ANCHOR_PATTERN),
        ("use_surface", CONSTRAINT_SURFACE_ANCHOR_PATTERN),
        ("perform_step", CONSTRAINT_STEP_ANCHOR_PATTERN),
    ):
        for anchor in _constraint_anchor_matches(pattern, normalized):
            key = (action_class, _anchor_key(anchor))
            if key in seen:
                continue
            seen.add(key)
            pairs.append((action_class, anchor))
    return pairs

def _constraint_primary_scope_anchor(
    fallback_subjects: Iterable[MemorySubjectAnchor],
    target_anchor: MemorySubjectAnchor,
) -> MemorySubjectAnchor | None:
    target_key = _anchor_key(target_anchor)
    distinct_scope_anchors: list[MemorySubjectAnchor] = []
    seen_scope_keys: set[str] = set()
    for subject in fallback_subjects:
        subject_key = _anchor_key(subject)
        if subject_key == target_key or subject_key in seen_scope_keys:
            continue
        seen_scope_keys.add(subject_key)
        distinct_scope_anchors.append(MemorySubjectAnchor(kind=subject.kind, value=subject.value))
    if len(distinct_scope_anchors) == 1:
        return distinct_scope_anchors[0]
    if len(distinct_scope_anchors) > 1:
        return None
    return MemorySubjectAnchor(kind=target_anchor.kind, value=target_anchor.value)

def _constraint_entry_has_distinct_scope(entry: dict[str, object]) -> bool:
    primary_scope_anchor = entry.get("primary_scope_anchor")
    target_anchor = entry.get("target_anchor")
    if not isinstance(primary_scope_anchor, MemorySubjectAnchor) or not isinstance(target_anchor, MemorySubjectAnchor):
        return False
    return _anchor_key(primary_scope_anchor) != _anchor_key(target_anchor)

def _constraint_fallback_subjects_from_item(item: QueryResultItem) -> list[MemorySubjectAnchor]:
    if item.envelope is None:
        return []
    return [MemorySubjectAnchor(kind=subject.kind, value=subject.value) for subject in item.envelope.subjects]

def _constraint_fallback_subjects_from_memory_object(memory_object: MemoryObject) -> list[MemorySubjectAnchor]:
    if memory_object.envelope is None:
        return []
    return [MemorySubjectAnchor(kind=subject.kind, value=subject.value) for subject in memory_object.envelope.subjects]

def _constraint_polarity_from_text(text: str) -> str | None:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return None
    if any(marker in lowered for marker in CONSTRAINT_PROHIBIT_MARKERS):
        return "prohibit"
    if any(marker in lowered for marker in CONSTRAINT_REQUIRE_MARKERS):
        return "require"
    if any(marker in lowered for marker in CONSTRAINT_PREFER_MARKERS):
        return "prefer"
    return None

def _normalized_constraint_rule_entries(
    text: str,
    *,
    fallback_subjects: Iterable[MemorySubjectAnchor] = (),
) -> list[dict[str, object]]:
    polarity = _constraint_polarity_from_text(text)
    if polarity not in CONSTRAINT_POLARITIES:
        return []
    entries: list[dict[str, object]] = []
    seen: set[str] = set()
    for action_class, target_anchor in _constraint_action_target_pairs(text):
        primary_scope_anchor = _constraint_primary_scope_anchor(fallback_subjects, target_anchor)
        if primary_scope_anchor is None:
            continue
        precise_key = _constraint_supersession_identity(primary_scope_anchor, target_anchor, action_class)
        if precise_key in seen:
            continue
        seen.add(precise_key)
        entries.append(
            {
                "primary_scope_anchor": primary_scope_anchor,
                "target_anchor": target_anchor,
                "action_class": action_class,
                "polarity": polarity,
                "strength": _constraint_strength_for_polarity(polarity),
                "supersession_identity": precise_key,
                "compatibility_domain": _constraint_compatibility_domain(primary_scope_anchor, action_class),
                "precise_coverage_key": precise_key,
                "target_key": _anchor_key(target_anchor),
            }
        )
    return entries

def _normalized_guidance_entries(
    text: str,
    *,
    fallback_subjects: Iterable[MemorySubjectAnchor] = (),
) -> list[dict[str, object]]:
    lowered = str(text or "").strip().lower()
    if not lowered or not any(marker in lowered for marker in CONSTRAINT_GUIDANCE_POSITIVE_MARKERS):
        return []
    entries: list[dict[str, object]] = []
    seen: set[str] = set()
    for action_class, target_anchor in _constraint_action_target_pairs(lowered):
        primary_scope_anchor = _constraint_primary_scope_anchor(fallback_subjects, target_anchor)
        if primary_scope_anchor is None:
            continue
        precise_key = _constraint_supersession_identity(primary_scope_anchor, target_anchor, action_class)
        if precise_key in seen:
            continue
        seen.add(precise_key)
        entries.append(
            {
                "primary_scope_anchor": primary_scope_anchor,
                "target_anchor": target_anchor,
                "action_class": action_class,
                "compatibility_domain": _constraint_compatibility_domain(primary_scope_anchor, action_class),
                "target_key": _anchor_key(target_anchor),
            }
        )
    return entries

def _typed_constraint_profile_from_payload(
    *,
    payload: dict[str, object],
    result_id: str,
    freshness_at: datetime | None,
    profile_source: str = "durable_typed",
    memory_type: str = CONSTRAINT_MEMORY_TYPE,
) -> dict[str, object] | None:
    primary_scope_anchor = _deserialize_subject_anchor(payload.get("primary_scope_anchor"))
    target_anchor = _deserialize_subject_anchor(payload.get("target_anchor"))
    action_class = str(payload.get("action_class") or "").strip().lower()
    polarity = str(payload.get("polarity") or "").strip().lower()
    status = str(payload.get("status") or "active").strip().lower()
    confidence = str(payload.get("confidence") or "unknown").strip().lower() or "unknown"
    constraint_text = str(payload.get("constraint_text") or payload.get("summary") or "").strip()
    if primary_scope_anchor is None or target_anchor is None:
        return None
    if action_class not in CONSTRAINT_ACTION_CLASSES or polarity not in CONSTRAINT_POLARITIES:
        return None
    if status not in CONSTRAINT_STATUSES or status != "active":
        return None
    if confidence not in CONSTRAINT_CONFIDENCES:
        confidence = "unknown"
    if not constraint_text:
        return None
    precise_key = _constraint_supersession_identity(primary_scope_anchor, target_anchor, action_class)
    return {
        "result_id": result_id,
        "memory_type": memory_type,
        "constraint_text": constraint_text,
        "primary_scope_anchor": primary_scope_anchor,
        "target_anchor": target_anchor,
        "action_class": action_class,
        "polarity": polarity,
        "strength": str(payload.get("strength") or _constraint_strength_for_polarity(polarity)),
        "freshness_at": freshness_at,
        "profile_source": profile_source,
        "confidence": confidence,
        "supersession_identity": precise_key,
        "compatibility_domain": _constraint_compatibility_domain(primary_scope_anchor, action_class),
        "precise_coverage_key": precise_key,
        "target_key": _anchor_key(target_anchor),
        "anchor_result_id": result_id,
    }

def _typed_constraint_profile_from_item(item: QueryResultItem) -> dict[str, object] | None:
    if item.result_kind != "memory_hit" or item.type != CONSTRAINT_MEMORY_TYPE or not isinstance(item.payload, dict):
        return None
    return _typed_constraint_profile_from_payload(
        payload=item.payload,
        result_id=_routing_result_id(item),
        freshness_at=item.freshness_at,
    )

def _matching_constraint_scope_anchors_from_candidate(
    candidate: dict[str, object],
    *,
    matching_pairs: set[tuple[str, str]],
) -> list[MemorySubjectAnchor]:
    item = candidate["item"]
    assert isinstance(item, QueryResultItem)
    matched_scope_anchors: list[MemorySubjectAnchor] = []

    typed_profile = _typed_constraint_profile_from_item(item)
    if typed_profile is not None:
        pair = (str(typed_profile.get("action_class") or ""), str(typed_profile.get("target_key") or ""))
        if pair in matching_pairs and isinstance(typed_profile.get("primary_scope_anchor"), MemorySubjectAnchor):
            primary_scope_anchor = typed_profile["primary_scope_anchor"]
            target_anchor = typed_profile.get("target_anchor")
            if isinstance(target_anchor, MemorySubjectAnchor) and _anchor_key(primary_scope_anchor) != _anchor_key(target_anchor):
                matched_scope_anchors.append(primary_scope_anchor)

    fallback_subjects = _constraint_fallback_subjects_from_item(item)
    if fallback_subjects:
        legacy_profile = _structured_constraint_profile_from_item(item)
        if legacy_profile is not None:
            constraint_text = str(legacy_profile.get("constraint_text") or "")
            for entry in _normalized_constraint_rule_entries(constraint_text, fallback_subjects=fallback_subjects):
                pair = (str(entry.get("action_class") or ""), str(entry.get("target_key") or ""))
                if pair in matching_pairs and _constraint_entry_has_distinct_scope(entry):
                    primary_scope_anchor = entry.get("primary_scope_anchor")
                    if isinstance(primary_scope_anchor, MemorySubjectAnchor):
                        matched_scope_anchors.append(primary_scope_anchor)

    guidance_entries, _guidance_unknown = _candidate_guidance_entries(candidate)
    for entry in guidance_entries:
        pair = (str(entry.get("action_class") or ""), str(entry.get("target_key") or ""))
        if pair in matching_pairs and _constraint_entry_has_distinct_scope(entry):
            primary_scope_anchor = entry.get("primary_scope_anchor")
            if isinstance(primary_scope_anchor, MemorySubjectAnchor):
                matched_scope_anchors.append(primary_scope_anchor)
    return _merge_subject_anchors(matched_scope_anchors)

def _local_query_constraint_fallback_subjects(
    query_text: str,
    ranked_candidates: Sequence[dict[str, object]],
) -> list[MemorySubjectAnchor]:
    matching_pairs = {
        (action_class, _anchor_key(target_anchor))
        for action_class, target_anchor in _constraint_action_target_pairs(query_text)
    }
    if not matching_pairs:
        return []
    return _merge_subject_anchors(
        *(
            _matching_constraint_scope_anchors_from_candidate(candidate, matching_pairs=matching_pairs)
            for candidate in ranked_candidates
        )
    )

def _build_local_query_constraint_profile(
    query_text: str,
    runtime_context: QueryRuntimeContext | None,
    ranked_candidates: Sequence[dict[str, object]],
) -> dict[str, object] | None:
    if runtime_context is None or runtime_context.turn_kind not in {"same_thread", "same_thread_continuation"}:
        return None
    fallback_subjects = _local_query_constraint_fallback_subjects(query_text, ranked_candidates)
    if not fallback_subjects:
        return None
    entries = [
        entry
        for entry in _normalized_constraint_rule_entries(query_text, fallback_subjects=fallback_subjects)
        if _constraint_entry_has_distinct_scope(entry)
    ]
    if not entries:
        return None
    entry = dict(entries[0])
    entry.update(
        {
            "result_id": "query_text:local_constraint",
            "memory_type": CONSTRAINT_MEMORY_TYPE,
            "constraint_text": query_text.strip(),
            "freshness_at": datetime.max.replace(tzinfo=timezone.utc),
            "profile_source": "local_typed",
            "confidence": "unknown",
            "anchor_result_id": None,
        }
    )
    return entry

def _apply_exact_constraint_supersession(profiles: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    chosen: dict[str, dict[str, object]] = {}
    shadowed: list[dict[str, object]] = []
    for profile in sorted(profiles, key=_constraint_profile_sort_key, reverse=True):
        key = str(profile.get("supersession_identity") or "")
        if not key:
            continue
        if key in chosen:
            shadowed.append(profile)
            continue
        chosen[key] = profile
    return list(chosen.values()), shadowed

def _reduce_constraint_domain_policies(profiles: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for profile in profiles:
        grouped.setdefault(str(profile.get("compatibility_domain") or ""), []).append(profile)
    policies: list[dict[str, object]] = []
    shadowed: list[dict[str, object]] = []
    for domain_key, domain_profiles in grouped.items():
        sorted_profiles = sorted(domain_profiles, key=_constraint_profile_sort_key, reverse=True)
        prohibit_rules = [profile for profile in sorted_profiles if profile.get("polarity") == "prohibit"]
        require_rules = [profile for profile in sorted_profiles if profile.get("polarity") == "require"]
        prefer_rules = [profile for profile in sorted_profiles if profile.get("polarity") == "prefer"]
        authoritative_require = require_rules[0] if require_rules else None
        authoritative_prefer = prefer_rules[0] if not authoritative_require and prefer_rules else None
        shadowed.extend(require_rules[1:] if len(require_rules) > 1 else [])
        shadowed.extend(prefer_rules[1:] if len(prefer_rules) > 1 else [])
        if authoritative_require is not None:
            conflicting_prohibits = [
                profile
                for profile in prohibit_rules
                if profile.get("target_key") == authoritative_require.get("target_key")
            ]
            if conflicting_prohibits:
                newest_prohibit = max(conflicting_prohibits, key=_constraint_profile_sort_key)
                if _constraint_profile_sort_key(newest_prohibit) > _constraint_profile_sort_key(authoritative_require):
                    shadowed.append(authoritative_require)
                    authoritative_require = None
                else:
                    for profile in conflicting_prohibits:
                        shadowed.append(profile)
                    prohibit_rules = [profile for profile in prohibit_rules if profile not in conflicting_prohibits]
        if authoritative_prefer is not None:
            conflicting_prefer_prohibits = [
                profile
                for profile in prohibit_rules
                if profile.get("target_key") == authoritative_prefer.get("target_key")
            ]
            if conflicting_prefer_prohibits:
                shadowed.append(authoritative_prefer)
                authoritative_prefer = None
        authoritative_rule = authoritative_require or authoritative_prefer
        policies.append(
            {
                "domain_key": domain_key,
                "prohibit_rules": prohibit_rules,
                "authoritative_rule": authoritative_rule,
            }
        )
    return policies, shadowed

def _serialize_constraint_rule_profile(profile: dict[str, object]) -> dict[str, object]:
    return {
        "result_id": str(profile.get("result_id") or ""),
        "memory_type": str(profile.get("memory_type") or ""),
        "profile_source": str(profile.get("profile_source") or ""),
        "constraint_text": str(profile.get("constraint_text") or ""),
        "primary_scope_anchor": _serialize_subject_anchor(profile["primary_scope_anchor"]),
        "target_anchor": _serialize_subject_anchor(profile["target_anchor"]),
        "action_class": str(profile.get("action_class") or ""),
        "polarity": str(profile.get("polarity") or ""),
        "compatibility_domain": str(profile.get("compatibility_domain") or ""),
        "precise_coverage_key": str(profile.get("precise_coverage_key") or ""),
        "supersession_identity": str(profile.get("supersession_identity") or ""),
    }

def _serialize_constraint_domain_policy(policy: dict[str, object]) -> dict[str, object]:
    authoritative_rule = policy.get("authoritative_rule")
    return {
        "domain_key": str(policy.get("domain_key") or ""),
        "prohibit_rules": [_serialize_constraint_rule_profile(profile) for profile in policy.get("prohibit_rules", [])],
        "authoritative_rule": _serialize_constraint_rule_profile(authoritative_rule) if isinstance(authoritative_rule, dict) else None,
    }


def _constraint_profile_trace_result_id(profile: dict[str, object]) -> str:
    return str(profile.get("anchor_result_id") or profile.get("result_id") or "")


def _serialize_active_constraint_profile(profile: dict[str, object]) -> dict[str, object]:
    return {
        "result_id": _constraint_profile_trace_result_id(profile),
        "memory_type": str(profile.get("memory_type") or ""),
        "constraint_text": str(profile.get("constraint_text") or ""),
        "protected_tokens": list(profile.get("protected_tokens") or []),
        "focus_tokens": list(profile.get("focus_tokens") or []),
        "exclusive_tokens": list(profile.get("exclusive_tokens") or []),
    }


def _select_active_constraint_profile(
    profiles: Iterable[dict[str, object]],
    *,
    local_constraint_profile: dict[str, object] | None = None,
) -> dict[str, object] | None:
    if local_constraint_profile is not None:
        return local_constraint_profile
    available_profiles = [profile for profile in profiles if isinstance(profile, dict)]
    if not available_profiles:
        return None
    return max(available_profiles, key=_constraint_profile_sort_key)

def _candidate_guidance_entries(candidate: dict[str, object]) -> tuple[list[dict[str, object]], bool]:
    item = candidate["item"]
    assert isinstance(item, QueryResultItem)
    if item.result_kind == "memory_hit" and item.type == CONSTRAINT_MEMORY_TYPE:
        return [], False
    fallback_subjects = item.envelope.subjects if item.envelope is not None else []
    fragments: list[str]
    if item.result_kind == "source_hit":
        fragments = [str(item.excerpt or "")]
    else:
        fragments = _structured_payload_guidance_fragments(str(item.type or ""), item.payload or {})
    entries: list[dict[str, object]] = []
    unknown = False
    for fragment in fragments:
        normalized = str(fragment or "").strip()
        if not normalized or not _text_contains_operational_guidance(normalized):
            continue
        if _fragment_is_constraint_only(normalized):
            continue
        stripped = _strip_constraint_snippets(normalized).strip()
        candidate_text = stripped if re.search(r"\w", stripped) else normalized
        normalized_entries = _normalized_guidance_entries(candidate_text, fallback_subjects=fallback_subjects)
        if normalized_entries:
            entries.extend(normalized_entries)
        else:
            unknown = True
    return entries, unknown

def _evaluate_guidance_entries_against_domain_policies(
    guidance_entries: list[dict[str, object]],
    domain_policies: list[dict[str, object]],
) -> tuple[str, dict[str, object] | None]:
    outcome = "compatible"
    winning_rule: dict[str, object] | None = None
    for entry in guidance_entries:
        for policy in domain_policies:
            if entry.get("compatibility_domain") != policy.get("domain_key"):
                continue
            prohibit_rules = list(policy.get("prohibit_rules") or [])
            if any(rule.get("target_key") == entry.get("target_key") for rule in prohibit_rules):
                return "incompatible", next(rule for rule in prohibit_rules if rule.get("target_key") == entry.get("target_key"))
            authoritative_rule = policy.get("authoritative_rule")
            if not isinstance(authoritative_rule, dict):
                continue
            if authoritative_rule.get("target_key") == entry.get("target_key"):
                winning_rule = authoritative_rule
                continue
            if authoritative_rule.get("polarity") == "require":
                return "incompatible", authoritative_rule
            if authoritative_rule.get("polarity") == "prefer":
                outcome = "competing_preference"
                winning_rule = authoritative_rule
    return outcome, winning_rule

def _build_constraint_state(
    unsuppressed_candidates: list[dict[str, object]],
    *,
    local_constraint_profile: dict[str, object] | None,
) -> dict[str, object]:
    typed_profiles: list[dict[str, object]] = []
    typed_anchor_candidates: dict[str, dict[str, object]] = {}
    legacy_profiles: list[dict[str, object]] = []
    legacy_anchor_candidates: dict[str, dict[str, object]] = {}
    for candidate in unsuppressed_candidates:
        item = candidate["item"]
        assert isinstance(item, QueryResultItem)
        typed_profile = _typed_constraint_profile_from_item(item)
        if typed_profile is not None:
            typed_profiles.append(typed_profile)
            typed_anchor_candidates[str(typed_profile["result_id"])] = candidate
            continue
        legacy_profile = _structured_constraint_profile_from_item(item)
        if legacy_profile is not None:
            legacy_profile = {
                **legacy_profile,
                "fallback_subjects": _constraint_fallback_subjects_from_item(item),
            }
            legacy_profiles.append(legacy_profile)
            legacy_anchor_candidates[str(legacy_profile.get("result_id") or "")] = candidate
    if local_constraint_profile is not None:
        typed_profiles.append(local_constraint_profile)

    active_typed_profiles, superseded_typed_profiles = _apply_exact_constraint_supersession(typed_profiles)
    typed_domain_policies, domain_shadowed_typed_profiles = _reduce_constraint_domain_policies(active_typed_profiles)
    typed_coverage_keys = {str(profile.get("precise_coverage_key") or "") for profile in active_typed_profiles}

    normalized_legacy_profiles: list[dict[str, object]] = []
    opaque_legacy_profiles: list[dict[str, object]] = []
    for legacy_profile in legacy_profiles:
        constraint_text = str(legacy_profile.get("constraint_text") or "")
        fallback_subjects = list(legacy_profile.get("fallback_subjects") or [])
        entries = [
            entry
            for entry in _normalized_constraint_rule_entries(constraint_text, fallback_subjects=fallback_subjects)
            if _constraint_entry_has_distinct_scope(entry)
        ]
        if not entries:
            opaque_legacy_profiles.append(legacy_profile)
            continue
        for entry in entries:
            precise_key = str(entry.get("precise_coverage_key") or "")
            if precise_key in typed_coverage_keys:
                continue
            normalized_legacy_profiles.append(
                {
                    **entry,
                    "result_id": f"{legacy_profile['result_id']}::{precise_key}",
                    "anchor_result_id": str(legacy_profile.get("result_id") or ""),
                    "memory_type": str(legacy_profile.get("memory_type") or ""),
                    "constraint_text": constraint_text,
                    "freshness_at": legacy_profile.get("freshness_at"),
                    "profile_source": "legacy_fallback",
                    "confidence": "unknown",
                }
            )

    retained_legacy_profiles, shadowed_legacy_profiles = _apply_exact_constraint_supersession(normalized_legacy_profiles)
    legacy_domain_policies, domain_shadowed_legacy_profiles = _reduce_constraint_domain_policies(retained_legacy_profiles)
    opaque_legacy_profiles = sorted(opaque_legacy_profiles, key=_constraint_profile_sort_key, reverse=True)
    active_constraint_profile = _select_active_constraint_profile(
        [*active_typed_profiles, *retained_legacy_profiles, *opaque_legacy_profiles],
        local_constraint_profile=local_constraint_profile,
    )

    constraint_anchor: dict[str, object] | None = None
    for profile in sorted(active_typed_profiles, key=_constraint_profile_sort_key, reverse=True):
        anchor_candidate = typed_anchor_candidates.get(str(profile.get("anchor_result_id") or profile.get("result_id") or ""))
        if anchor_candidate is not None:
            constraint_anchor = anchor_candidate
            break
    if constraint_anchor is None:
        for profile in sorted(retained_legacy_profiles, key=_constraint_profile_sort_key, reverse=True):
            anchor_candidate = legacy_anchor_candidates.get(str(profile.get("anchor_result_id") or ""))
            if anchor_candidate is not None:
                constraint_anchor = anchor_candidate
                break
    if constraint_anchor is None and opaque_legacy_profiles:
        freshest_legacy_profile = max(opaque_legacy_profiles, key=_constraint_profile_sort_key)
        constraint_anchor = legacy_anchor_candidates.get(str(freshest_legacy_profile.get("result_id") or ""))

    return {
        "active_typed_profiles": active_typed_profiles,
        "typed_domain_policies": typed_domain_policies,
        "retained_legacy_profiles": retained_legacy_profiles,
        "legacy_domain_policies": legacy_domain_policies,
        "opaque_legacy_profiles": opaque_legacy_profiles,
        "active_constraint_profile": active_constraint_profile,
        "constraint_anchor": constraint_anchor,
        "shadowed_typed_profiles": [*superseded_typed_profiles, *domain_shadowed_typed_profiles],
        "shadowed_legacy_profiles": [*shadowed_legacy_profiles, *domain_shadowed_legacy_profiles],
    }

def _candidate_aligns_with_constraint_profile(candidate: dict[str, object], constraint_profile: dict[str, object] | None) -> bool:
    if constraint_profile is None:
        return False
    item = candidate["item"]
    assert isinstance(item, QueryResultItem)
    candidate_tokens = set(_routing_item_tokens(item))
    if not candidate_tokens:
        return False
    focus_tokens = set(constraint_profile.get("focus_tokens") or [])
    protected_tokens = set(constraint_profile.get("protected_tokens") or [])
    target_tokens = focus_tokens or protected_tokens
    return bool(target_tokens.intersection(candidate_tokens))

def _candidate_aligns_with_constraint_state(candidate: dict[str, object], constraint_state: dict[str, object] | None) -> bool:
    if not constraint_state:
        return False
    item = candidate["item"]
    assert isinstance(item, QueryResultItem)
    if item.result_kind == "memory_hit" and item.type == CONSTRAINT_MEMORY_TYPE:
        return True
    guidance_entries, _unknown = _candidate_guidance_entries(candidate)
    if guidance_entries:
        all_policies = [*constraint_state.get("typed_domain_policies", []), *constraint_state.get("legacy_domain_policies", [])]
        outcome, _rule = _evaluate_guidance_entries_against_domain_policies(guidance_entries, all_policies)
        return outcome in {"compatible", "competing_preference"}
    for legacy_profile in constraint_state.get("opaque_legacy_profiles", []):
        if _candidate_aligns_with_constraint_profile(candidate, legacy_profile):
            return True
    return False

def _apply_structured_constraint_compatibility(
    *,
    ranked_candidates: list[dict[str, object]],
    packaging_summary: dict[str, object],
    local_constraint_profile: dict[str, object] | None = None,
) -> tuple[list[dict[str, object]], dict[str, object], dict[str, object] | None, dict[str, object] | None]:
    unsuppressed_candidates = [candidate for candidate in ranked_candidates if not candidate.get("suppression_reason_code")]
    if not unsuppressed_candidates:
        return [], packaging_summary, None, None

    constraint_state = _build_constraint_state(
        unsuppressed_candidates,
        local_constraint_profile=local_constraint_profile,
    )
    compatible_candidates: list[dict[str, object]] = []
    incompatible_candidates: list[dict[str, str]] = []
    all_domain_policies = [*constraint_state["typed_domain_policies"], *constraint_state["legacy_domain_policies"]]

    for candidate in unsuppressed_candidates:
        item = candidate["item"]
        assert isinstance(item, QueryResultItem)
        guidance_entries, guidance_unknown = _candidate_guidance_entries(candidate)
        candidate["constraint_compatibility"] = "compatible"
        conflict_reason: tuple[str, str] | None = None
        packaging_adjustment = int(candidate.get("packaging_adjustment") or 0)

        if guidance_entries:
            compatibility_outcome, governing_rule = _evaluate_guidance_entries_against_domain_policies(guidance_entries, all_domain_policies)
            candidate["constraint_compatibility"] = compatibility_outcome
            if compatibility_outcome == "incompatible":
                conflict_reason = (
                    "conflicts_with_active_constraint",
                    "Candidate guidance was excluded because it conflicts with the active carried constraint.",
                )
            elif compatibility_outcome == "competing_preference":
                packaging_adjustment -= 140
                candidate["packaging_reasons"] = list(OrderedDict.fromkeys([*candidate["packaging_reasons"], "demoted_by_active_preference"]))
                candidate["constraint_governing_rule"] = str((governing_rule or {}).get("result_id") or "")
        elif guidance_unknown:
            candidate["constraint_compatibility"] = "unknown"

        if conflict_reason is None:
            for legacy_profile in constraint_state["opaque_legacy_profiles"]:
                if _candidate_conflicts_with_constraint(item, legacy_profile):
                    candidate["constraint_compatibility"] = "incompatible"
                    conflict_reason = (
                        "conflicts_with_active_constraint",
                        "Candidate guidance was excluded because it conflicts with the retained legacy carried constraint.",
                    )
                    break

        if conflict_reason is not None:
            reason_code, reason_text = conflict_reason
            candidate["suppression_reason_code"] = reason_code
            candidate["suppression_reason"] = reason_text
            candidate["packaging_reasons"] = list(OrderedDict.fromkeys([*candidate["packaging_reasons"], reason_code]))
            incompatible_candidates.append({
                "result_id": _routing_result_id(item),
                "reason_code": reason_code,
            })
            continue

        if packaging_adjustment:
            candidate["packaging_adjustment"] = packaging_adjustment
        compatible_candidates.append(candidate)

    compatible_candidates = sorted(
        compatible_candidates,
        key=lambda candidate: (int(candidate["routing_score"]) + int(candidate.get("packaging_adjustment") or 0), int(candidate["lexical_score"])),
        reverse=True,
    )

    if constraint_state["active_typed_profiles"]:
        packaging_summary["active_typed_constraints"] = [
            _serialize_constraint_rule_profile(profile)
            for profile in constraint_state["active_typed_profiles"]
        ]
    if constraint_state["typed_domain_policies"]:
        packaging_summary["typed_domain_policies"] = [
            _serialize_constraint_domain_policy(policy)
            for policy in constraint_state["typed_domain_policies"]
        ]
    if constraint_state["retained_legacy_profiles"]:
        packaging_summary["retained_legacy_fallback_profiles"] = [
            _serialize_constraint_rule_profile(profile)
            for profile in constraint_state["retained_legacy_profiles"]
        ]
    if constraint_state["opaque_legacy_profiles"]:
        packaging_summary["retained_opaque_legacy_fallback_profiles"] = [
            {
                "result_id": str(profile.get("result_id") or ""),
                "memory_type": str(profile.get("memory_type") or ""),
                "constraint_text": str(profile.get("constraint_text") or ""),
            }
            for profile in constraint_state["opaque_legacy_profiles"]
        ]
    if constraint_state["shadowed_typed_profiles"]:
        packaging_summary["shadowed_typed_constraints"] = [
            _serialize_constraint_rule_profile(profile)
            for profile in constraint_state["shadowed_typed_profiles"]
        ]
    if constraint_state["shadowed_legacy_profiles"]:
        packaging_summary["shadowed_legacy_fallback_profiles"] = [
            _serialize_constraint_rule_profile(profile)
            for profile in constraint_state["shadowed_legacy_profiles"]
            if isinstance(profile.get("primary_scope_anchor"), MemorySubjectAnchor)
        ]
    active_constraint_profile = constraint_state.get("active_constraint_profile")
    if isinstance(active_constraint_profile, dict):
        packaging_summary["active_constraint_profile"] = _serialize_active_constraint_profile(active_constraint_profile)
        if local_constraint_profile is not None and _constraint_profile_trace_result_id(active_constraint_profile) == _constraint_profile_trace_result_id(local_constraint_profile):
            packaging_summary["active_constraint_profile_source"] = "local_query_constraint"
    constraint_anchor = constraint_state["constraint_anchor"]
    if constraint_anchor is not None:
        packaging_summary["constraint_anchor_result_id"] = _routing_result_id(constraint_anchor["item"])
    if incompatible_candidates:
        packaging_summary["incompatible_structured_candidates"] = incompatible_candidates
    if constraint_state["active_typed_profiles"] or constraint_state["retained_legacy_profiles"] or constraint_state["opaque_legacy_profiles"]:
        return compatible_candidates, packaging_summary, constraint_anchor, constraint_state
    return compatible_candidates, packaging_summary, constraint_anchor, None

def _list_active_constraint_state(
    storage,
    *,
    container_ref: str,
    visibility_context,
) -> dict[str, object]:
    typed_profiles: list[dict[str, object]] = []
    legacy_profiles: list[dict[str, object]] = []
    for memory_object in storage.list_memory_objects(
        memory_types=[CONSTRAINT_MEMORY_TYPE, *STRUCTURED_CONFLICT_MEMORY_TYPES],
        lifecycle="active",
    ):
        payload = memory_object.payload or {}
        payload_container_ref = str(payload.get("container_ref") or payload.get("scope_container_ref") or "")
        if payload_container_ref and payload_container_ref != container_ref:
            continue
        if memory_object.visibility_context != visibility_context:
            continue
        if memory_object.type == CONSTRAINT_MEMORY_TYPE:
            typed_profile = _typed_constraint_profile_from_payload(
                payload=payload,
                result_id=f"memory_object:{memory_object.id}",
                freshness_at=memory_object.freshness_at,
            )
            if typed_profile is not None:
                typed_profiles.append(typed_profile)
            continue
        legacy_profile = _structured_constraint_profile_from_payload(
            memory_type=memory_object.type,
            payload=payload,
            result_id=f"memory_object:{memory_object.id}",
            freshness_at=memory_object.freshness_at,
        )
        if legacy_profile is None:
            continue
        legacy_profiles.append(
            {
                **legacy_profile,
                "fallback_subjects": _constraint_fallback_subjects_from_memory_object(memory_object),
            }
        )

    active_typed_profiles, superseded_typed_profiles = _apply_exact_constraint_supersession(typed_profiles)
    typed_domain_policies, domain_shadowed_typed_profiles = _reduce_constraint_domain_policies(active_typed_profiles)
    typed_coverage_keys = {str(profile.get("precise_coverage_key") or "") for profile in active_typed_profiles}

    normalized_legacy_profiles: list[dict[str, object]] = []
    opaque_legacy_profiles: list[dict[str, object]] = []
    for legacy_profile in legacy_profiles:
        fallback_subjects = list(legacy_profile.get("fallback_subjects") or [])
        entries = [
            entry
            for entry in _normalized_constraint_rule_entries(
                str(legacy_profile.get("constraint_text") or ""),
                fallback_subjects=fallback_subjects,
            )
            if _constraint_entry_has_distinct_scope(entry)
        ]
        if not entries:
            opaque_legacy_profiles.append(legacy_profile)
            continue
        for entry in entries:
            precise_key = str(entry.get("precise_coverage_key") or "")
            if precise_key in typed_coverage_keys:
                continue
            normalized_legacy_profiles.append(
                {
                    **entry,
                    "result_id": f"{legacy_profile['result_id']}::{precise_key}",
                    "anchor_result_id": str(legacy_profile.get("result_id") or ""),
                    "memory_type": str(legacy_profile.get("memory_type") or ""),
                    "constraint_text": str(legacy_profile.get("constraint_text") or ""),
                    "freshness_at": legacy_profile.get("freshness_at"),
                    "profile_source": "legacy_fallback",
                    "confidence": "unknown",
                }
            )
    retained_legacy_profiles, shadowed_legacy_profiles = _apply_exact_constraint_supersession(normalized_legacy_profiles)
    legacy_domain_policies, domain_shadowed_legacy_profiles = _reduce_constraint_domain_policies(retained_legacy_profiles)
    opaque_legacy_profiles = sorted(opaque_legacy_profiles, key=_constraint_profile_sort_key, reverse=True)
    active_constraint_profile = _select_active_constraint_profile(
        [*active_typed_profiles, *retained_legacy_profiles, *opaque_legacy_profiles]
    )
    return {
        "active_typed_profiles": active_typed_profiles,
        "typed_domain_policies": typed_domain_policies,
        "retained_legacy_profiles": retained_legacy_profiles,
        "legacy_domain_policies": legacy_domain_policies,
        "opaque_legacy_profiles": opaque_legacy_profiles,
        "active_constraint_profile": active_constraint_profile,
        "shadowed_typed_profiles": [*superseded_typed_profiles, *domain_shadowed_typed_profiles],
        "shadowed_legacy_profiles": [*shadowed_legacy_profiles, *domain_shadowed_legacy_profiles],
        "has_any": bool(active_typed_profiles or retained_legacy_profiles or opaque_legacy_profiles),
    }

def _structured_constraint_profile_from_payload(
    *,
    memory_type: str,
    payload: dict[str, object],
    result_id: str,
    freshness_at: datetime | None = None,
) -> dict[str, object] | None:
    constraint_text = _preferred_constraint_text(*_structured_payload_constraint_fragments(memory_type, payload))
    if not constraint_text:
        return None
    protected_tokens = set(_constraint_policy_tokens(constraint_text))
    if protected_tokens.intersection({"issue", "jira", "log", "login", "portal", "sign", "slack", "tracker"}):
        protected_tokens.update({"auth", "authenticate", "authentication", "retry"})
    focus_tokens = _prohibited_constraint_focus_tokens(constraint_text) or _constraint_focus_tokens(protected_tokens)
    exclusive_tokens = _exclusive_constraint_tokens(constraint_text)
    protected_tokens = sorted(protected_tokens)
    focus_tokens = sorted(focus_tokens)
    exclusive_tokens = sorted(exclusive_tokens)
    if not protected_tokens:
        return None
    return {
        "result_id": result_id,
        "memory_type": memory_type,
        "constraint_text": constraint_text,
        "protected_tokens": protected_tokens,
        "focus_tokens": focus_tokens,
        "exclusive_tokens": exclusive_tokens,
        "freshness_at": freshness_at,
    }

def _structured_payload_conflicts_with_constraint(memory_type: str, payload: dict[str, object], constraint_profile: dict[str, object]) -> bool:
    return any(
        _structured_text_conflicts_with_constraint(fragment, constraint_profile)
        for fragment in _structured_payload_guidance_fragments(memory_type, payload)
    )

def _reconcile_memory_object_against_active_constraints(
    memory_object: MemoryObject,
    *,
    constraint_state: dict[str, object],
) -> MemoryObject:
    if memory_object.type not in STRUCTURED_CONFLICT_MEMORY_TYPES or not constraint_state.get("has_any"):
        return memory_object
    payload = dict(memory_object.payload or {})
    candidate = {"item": QueryResultItem(result_kind="memory_hit", memory_object_id=memory_object.id, type=memory_object.type, payload=payload, freshness_at=memory_object.freshness_at, evidence=[], score=0)}
    all_domain_policies = [*constraint_state.get("typed_domain_policies", []), *constraint_state.get("legacy_domain_policies", [])]
    guidance_entries, _guidance_unknown = _candidate_guidance_entries(candidate)
    active_constraint = None
    if guidance_entries:
        compatibility_outcome, active_constraint = _evaluate_guidance_entries_against_domain_policies(guidance_entries, all_domain_policies)
        if compatibility_outcome != "incompatible":
            active_constraint = None
    if active_constraint is None:
        for legacy_profile in constraint_state.get("opaque_legacy_profiles", []):
            if _structured_payload_conflicts_with_constraint(memory_object.type, payload, legacy_profile):
                active_constraint = legacy_profile
                break
    if active_constraint is None:
        return memory_object

    constraint_text = str(active_constraint.get("constraint_text") or "").strip()
    updated_payload = dict(payload)
    if memory_object.type == "task_checkpoint":
        updated_payload["summary"] = _strip_conflicting_guidance_text(str(payload.get("summary") or ""), active_constraint)
        updated_payload["current_state"] = _strip_conflicting_guidance_text(str(payload.get("current_state") or ""), active_constraint)
        blocker_state = _strip_conflicting_guidance_text(str(payload.get("blocker_state") or ""), active_constraint)
        updated_payload["blocker_state"] = _join_unique_text_parts([constraint_text, blocker_state]) if constraint_text else blocker_state
        updated_payload["next_step"] = _strip_conflicting_guidance_text(str(payload.get("next_step") or ""), active_constraint)
        updated_payload["key_findings"] = [
            text
            for text in _parse_string_list(payload.get("key_findings"))
            if not _structured_text_conflicts_with_constraint(text, active_constraint)
        ]
        evidence_lines = [
            text
            for text in _parse_string_list(payload.get("evidence"))
            if not _structured_text_conflicts_with_constraint(text, active_constraint)
        ]
        if constraint_text and not any(constraint_text.lower() in text.lower() for text in evidence_lines):
            evidence_lines.insert(0, f"Constraint: {constraint_text}")
        updated_payload["evidence"] = evidence_lines
    else:
        summary = _strip_conflicting_guidance_text(str(payload.get("summary") or ""), active_constraint)
        updated_payload["summary"] = _join_unique_text_parts([constraint_text, summary]) if constraint_text else summary
        if memory_object.type == "thread_summary":
            updated_payload["selected_work_artifacts"] = [
                artifact
                for artifact in payload.get("selected_work_artifacts", [])
                if isinstance(artifact, dict)
                and not _structured_text_conflicts_with_constraint(str(artifact.get("text") or ""), active_constraint)
            ]
            updated_payload["conclusions"] = [
                conclusion
                for conclusion in payload.get("conclusions", [])
                if isinstance(conclusion, dict)
                and not _structured_text_conflicts_with_constraint(str(conclusion.get("text") or ""), active_constraint)
            ]
    semantic_provenance = dict(updated_payload.get("semantic_provenance") or {})
    semantic_provenance["constraint_reconciliation"] = {
        "active_constraint_result_id": _constraint_profile_trace_result_id(active_constraint),
        "constraint_text": constraint_text,
    }
    updated_payload["semantic_provenance"] = semantic_provenance
    return replace(memory_object, payload=updated_payload)

def _strip_conflicting_guidance_text(text: str, constraint_profile: dict[str, object]) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    parts = [part.strip(" -") for part in re.split(r"(?<=[.!?;])\s+|\n+", normalized) if part.strip(" -")]
    if not parts:
        return ""
    kept_parts: list[str] = []
    for part in parts:
        if not _structured_text_conflicts_with_constraint(part, constraint_profile):
            kept_parts.append(part)
            continue
        preferred_constraint = _preferred_constraint_text(part)
        if preferred_constraint:
            kept_parts.append(preferred_constraint)
    return _join_unique_text_parts(kept_parts)

def _structured_text_conflicts_with_constraint(text: str, constraint_profile: dict[str, object]) -> bool:
    normalized = str(text or "").strip()
    if not normalized or not _text_contains_operational_guidance(normalized):
        return False
    if _fragment_is_constraint_only(normalized):
        return False
    stripped = _strip_constraint_snippets(normalized).strip()
    candidate_text = stripped if re.search(r"\w", stripped) else normalized
    if candidate_text != normalized and not _text_contains_operational_guidance(candidate_text):
        return False
    if isinstance(constraint_profile.get("primary_scope_anchor"), MemorySubjectAnchor):
        guidance_entries = _normalized_guidance_entries(candidate_text)
        if not guidance_entries:
            return False
        policy = {
            "domain_key": str(constraint_profile.get("compatibility_domain") or ""),
            "prohibit_rules": [constraint_profile] if constraint_profile.get("polarity") == "prohibit" else [],
            "authoritative_rule": constraint_profile if constraint_profile.get("polarity") in {"require", "prefer"} else None,
        }
        outcome, _governing_rule = _evaluate_guidance_entries_against_domain_policies(guidance_entries, [policy])
        return outcome == "incompatible"
    protected_tokens = set(constraint_profile.get("protected_tokens") or [])
    if not protected_tokens:
        return False
    candidate_tokens = _constraint_policy_tokens(candidate_text)
    if not candidate_tokens:
        return False
    focus_tokens = set(constraint_profile.get("focus_tokens") or [])
    focus_basis = focus_tokens or {
        token for token in protected_tokens if token not in CONSTRAINT_POLICY_LOW_SIGNAL_TOKENS
    }
    focus_overlap = candidate_tokens.intersection(focus_basis)
    exclusive_tokens = set(constraint_profile.get("exclusive_tokens") or [])
    if len(focus_overlap) >= 2:
        if exclusive_tokens:
            forbidden_focus_overlap = focus_overlap.difference(exclusive_tokens)
            lowered_candidate = candidate_text.lower()
            if candidate_tokens.intersection(exclusive_tokens) and not forbidden_focus_overlap and re.search(r"\buse\b", lowered_candidate):
                return False
            residual_tokens = candidate_tokens.difference(
                exclusive_tokens,
                CONSTRAINT_POLICY_ACTION_TOKENS,
                CONSTRAINT_POLICY_LOW_SIGNAL_TOKENS,
                ROUTING_META_QUERY_TOKENS,
                {"next", "step", "instead", "rather", "than"},
            )
            if candidate_tokens.intersection(exclusive_tokens) and not forbidden_focus_overlap and not residual_tokens:
                return False
        return True
    if focus_overlap and len(focus_basis) <= 2:
        return True
    action_overlap = candidate_tokens.intersection(protected_tokens).intersection(CONSTRAINT_POLICY_ACTION_TOKENS)
    return bool(focus_basis) and len(action_overlap) >= 2

def _rebuild_reconciled_memory_index_entry(memory_object: MemoryObject):
    payload = memory_object.payload or {}
    if memory_object.type != "task_checkpoint":
        return build_index_entry(
            target_kind="memory_object",
            target_id=memory_object.id,
            index_type="lexical",
            text_view=normalize_for_index(str(payload.get("summary") or "")),
            text_view_name=TASK_CHECKPOINT_TEXT_VIEW if memory_object.type == "task_checkpoint" else THREAD_SUMMARY_TEXT_VIEW,
        )
    index_source = " ".join(
        [
            str(payload.get("summary") or ""),
            str(payload.get("task") or ""),
            str(payload.get("current_state") or ""),
            str(payload.get("blocker_state") or ""),
            str(payload.get("next_step") or ""),
            str(payload.get("freshness_signal") or ""),
            *[str(value or "") for value in _parse_string_list(payload.get("key_findings"))],
            *[str(value or "") for value in _parse_string_list(payload.get("evidence"))],
            *[str(item.get("text") or "") for item in payload.get("conclusions", []) if isinstance(item, dict)],
            *[str(item.get("text") or "") for item in payload.get("selected_work_artifacts", []) if isinstance(item, dict)],
        ]
    )
    return build_index_entry(
        target_kind="memory_object",
        target_id=memory_object.id,
        index_type="lexical",
        text_view=normalize_for_index(index_source),
        text_view_name=TASK_CHECKPOINT_TEXT_VIEW,
    )

def _preferred_constraint_text(*fragments: str) -> str:
    candidates: list[str] = []
    for fragment in fragments:
        candidates.extend(_extract_constraint_snippets(fragment))
    if not candidates:
        return ""
    unique_candidates = list(OrderedDict.fromkeys(candidate.strip() for candidate in candidates if candidate.strip()))
    ordered_candidates = sorted(
        unique_candidates,
        key=lambda candidate: (
            "do not" not in candidate.lower() and "don't" not in candidate.lower(),
            "use only" not in candidate.lower() and "instead of" not in candidate.lower(),
            "avoid" not in candidate.lower() and "without" not in candidate.lower(),
            -len(candidate),
        ),
    )
    return _join_unique_text_parts(ordered_candidates)

def _extract_constraint_snippets(text: str) -> list[str]:
    normalized = str(text or "").strip()
    if not normalized:
        return []
    snippets: list[str] = []
    for fragment in re.split(r"(?<=[.!?])\s+|\n+", normalized):
        fragment_lowered = fragment.lower()
        fragment_has_tool_marker = any(marker in fragment_lowered for marker in CONSTRAINT_TOOL_MARKERS)
        for clause in re.split(r"(?<=[,;])\s+|\s+\b(?:and|but|while)\b\s+", fragment):
            candidate = clause.strip(" -,:;")
            lowered = candidate.lower()
            if not candidate:
                continue
            has_tool_marker = any(marker in lowered for marker in CONSTRAINT_TOOL_MARKERS)
            explicit_local_constraint = any(marker in lowered for marker in ("cannot use", "can't use", "cannot open", "can't open", "cannot connect", "can't connect"))
            has_constraint_marker = any(marker in lowered for marker in (*CONSTRAINT_MARKERS, "avoid", "without")) or explicit_local_constraint
            if has_constraint_marker and (has_tool_marker or fragment_has_tool_marker):
                snippets.append(candidate.rstrip("."))
    return list(OrderedDict.fromkeys(snippets))

def _fragment_is_constraint_only(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    lowered = normalized.lower()
    strong_positive_markers = (
        "next step",
        "should ",
        "need to ",
        "must ",
        "attempt ",
        "retry ",
        "resume ",
        "rerun ",
        "refresh ",
        "connect ",
        "authenticate",
        "sign in",
        "log in manually",
        "login manually",
    )
    has_tool_marker = any(marker in lowered for marker in CONSTRAINT_TOOL_MARKERS)
    has_constraint_language = any(marker in lowered for marker in (*CONSTRAINT_MARKERS, "avoid", "without", "no-login", "no browser", "no-browser"))
    if not has_tool_marker or not has_constraint_language:
        return False
    if any(marker in lowered for marker in strong_positive_markers):
        return False
    residual = normalize_for_index(_strip_constraint_snippets(normalized))
    if not residual:
        return True
    residual_tokens = [
        token
        for token in residual.split()
        if token not in CONSTRAINT_ONLY_RESIDUAL_TOKENS and token not in CONSTRAINT_POLICY_STOPWORDS
    ]
    return not residual_tokens or not any(marker in residual for marker in strong_positive_markers)

def _strip_constraint_snippets(text: str) -> str:
    stripped = str(text or "")
    for snippet in _extract_constraint_snippets(stripped):
        stripped = re.sub(re.escape(snippet), " ", stripped, flags=re.IGNORECASE)
    return stripped


def reconcile_process_result_against_active_constraints(
    result: ProcessResult,
    *,
    storage,
    container_ref: str | None,
    visibility_context,
) -> ProcessResult:
    if not container_ref or visibility_context is None or not result.memory_objects:
        return result
    active_constraints = _list_active_constraint_state(
        storage,
        container_ref=container_ref,
        visibility_context=visibility_context,
    )
    if not active_constraints.get('has_any'):
        return result

    reconciled_memory_objects: list[MemoryObject] = []
    changed_ids: set[str] = set()
    for memory_object in result.memory_objects:
        reconciled = _reconcile_memory_object_against_active_constraints(
            memory_object,
            constraint_state=active_constraints,
        )
        reconciled_memory_objects.append(reconciled)
        if reconciled is not memory_object:
            changed_ids.add(reconciled.id)

    if not changed_ids:
        return result

    rebuilt_index_entries = {
        memory_object.id: _rebuild_reconciled_memory_index_entry(memory_object)
        for memory_object in reconciled_memory_objects
        if memory_object.id in changed_ids
    }
    updated_index_entries = [
        rebuilt_index_entries.get(index_entry.target_id, index_entry)
        if index_entry.target_kind == 'memory_object'
        else index_entry
        for index_entry in result.index_entries
    ]
    return replace(
        result,
        memory_objects=reconciled_memory_objects,
        index_entries=updated_index_entries,
    )
