"""Unified suppression pass with composable rules.

Rules are evaluated in priority order. First match wins.
Each rule is independently testable and intent-gatable.
Applies both a boolean flag AND a modest score penalty (-50) as defense-in-depth.
"""
from __future__ import annotations

from dataclasses import dataclass
from semantic.common import normalize_for_index
from semantic.agent_conversation_memory_threads import _is_low_value_meta_text

SUPPRESSION_SCORE_PENALTY = 50  # modest penalty as defense-in-depth

RECALL_INTENTS = frozenset({
    "recall", "structured_recall",
    # Legacy names during migration:
    "broad_recall", "answer_continuity", "precise_fact", "investigative_conclusion",
})

WEAK_SUMMARY_QUALITIES = frozenset({"query_only", "weak", "unresolved"})
SUMMARY_TYPES = frozenset({"thread_summary", "discussion_summary"})


@dataclass(frozen=True)
class SuppressionRule:
    """One suppression check. Rules are evaluated in priority order."""
    name: str
    reason_code: str
    intents: frozenset[str] | None  # None = applies to all intents


def _check_echo(candidate: dict, *, query_text: str, **kw) -> bool:
    """Check if candidate is the current query echoing back as a source hit."""
    item = candidate.get("item")
    if item is None or getattr(item, "result_kind", None) != "source_hit":
        return False
    role = getattr(item, "role", None)
    if role not in ("user", "", None):
        return False
    if not candidate.get("same_thread", False):
        return False
    excerpt = str(getattr(item, "excerpt", "") or "")
    normalized_excerpt = normalize_for_index(excerpt)
    normalized_query = normalize_for_index(query_text)
    if not normalized_query:
        return False
    return normalized_excerpt == normalized_query


def _check_meta_text(candidate: dict, **kw) -> bool:
    """Check if candidate is orchestration boilerplate."""
    item = candidate.get("item")
    if item is None or getattr(item, "result_kind", None) != "source_hit":
        return False
    excerpt = str(getattr(item, "excerpt", "") or "")
    return _is_low_value_meta_text(excerpt)


def _check_weak_summary(candidate: dict, **kw) -> bool:
    """Check if candidate is a structurally weak summary."""
    item = candidate.get("item")
    if item is None:
        return False
    item_type = getattr(item, "type", None)
    if item_type not in SUMMARY_TYPES:
        return False
    payload = getattr(item, "payload", None) or {}
    content_quality = payload.get("content_quality")
    return content_quality in WEAK_SUMMARY_QUALITIES


# Default rules — priority order (echo > meta-text > weak summary)
DEFAULT_RULES: list[SuppressionRule] = [
    SuppressionRule(name="echo", reason_code="current_query_source_echo", intents=None),
    SuppressionRule(name="meta_text", reason_code="low_value_meta_text", intents=None),
    SuppressionRule(name="weak_summary", reason_code="weak_summary", intents=RECALL_INTENTS),
]

_CHECK_FNS: dict[str, callable] = {
    "echo": _check_echo,
    "meta_text": _check_meta_text,
    "weak_summary": _check_weak_summary,
}


def apply_suppression(
    candidate: dict,
    *,
    intent: str,
    query_text: str,
    rules: list[SuppressionRule] | None = None,
) -> tuple[bool, str | None]:
    """Evaluate suppression rules in priority order. First match wins.

    If suppressed, also applies a modest score penalty to base_routing_score
    as defense-in-depth.

    Returns (suppressed, reason_code).
    """
    _rules = rules if rules is not None else DEFAULT_RULES
    for rule in _rules:
        if rule.intents is not None and intent not in rule.intents:
            continue
        check_fn = _CHECK_FNS.get(rule.name)
        if check_fn is None:
            continue
        if check_fn(candidate, query_text=query_text):
            candidate["suppressed"] = True
            candidate["suppression_reason_code"] = rule.reason_code
            # Defense-in-depth: modest score penalty
            if "base_routing_score" in candidate:
                candidate["base_routing_score"] = int(candidate["base_routing_score"]) - SUPPRESSION_SCORE_PENALTY
            return True, rule.reason_code
    return False, None
