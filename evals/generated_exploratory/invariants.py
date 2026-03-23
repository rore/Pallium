"""
Invariant checks for automated exploratory QA.

Each invariant is a function that inspects a query result and its debug trace
to check a hard correctness or quality property. Invariants do not require
hand-authored expected outcomes — they check universal rules that every
scenario must obey.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Greeting / phatic patterns that should never appear in injectable blocks.
_GREETING_PATTERNS = re.compile(
    r"^(hi|hello|hey|good morning|good afternoon|good evening|howdy|greetings)"
    r"[\s!.,?]*$",
    re.IGNORECASE,
)
_GREETING_CONTENT_MAX_WORDS = 8

# Minimum meaningful content words shared between query and injectable block
# to consider them topically related (for INV-03).
_TOPIC_OVERLAP_MIN_TOKENS = 1

# Common stopwords excluded from topic overlap computation.
_STOPWORDS = frozenset({
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
})

# Recall signal phrases — queries containing these are backward-looking.
# Multi-word phrases use substring matching (low false-positive risk).
_RECALL_PHRASE_SIGNALS = [
    "didn't we", "did we", "didn't you", "did you",
    "we discussed", "we talked about", "we decided",
    "remember when", "last time", "previously",
    "what was", "what were", "what did",
]
# Single-word signals need word-boundary matching to avoid false positives
# (e.g., "before" in "before we proceed" is forward-looking).
_RECALL_WORD_SIGNALS = [
    re.compile(rf"\b{word}\b", re.IGNORECASE)
    for word in ["recall", "earlier"]
]


@dataclass(frozen=True)
class InvariantResult:
    """Result of checking a single invariant against a scenario outcome."""

    invariant_id: str
    passed: bool
    severity: str = "hard"
    details: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


def _content_tokens(text: str) -> set[str]:
    """Extract lowercase content words, excluding stopwords."""
    words = set(re.findall(r"[a-z0-9]+", text.lower()))
    return words - _STOPWORDS


# ---------------------------------------------------------------------------
# INV-01: no_cross_container_leak
# ---------------------------------------------------------------------------

def check_no_cross_container_leak(
    scenario: dict[str, Any],
    query_payload: dict[str, Any],
    debug_payload: dict[str, Any],
) -> InvariantResult:
    """No non-public results should come from a container other than the queried one.

    Public items are visible to all containers per core/filters.py, so only
    non-public results from a different container constitute a leak.
    """
    query_container = _query_container_ref(scenario, debug_payload)
    if not query_container:
        return InvariantResult(
            invariant_id="INV-01",
            passed=True,
            details="No container_ref on query — invariant not applicable",
        )

    leaked = []
    for result in debug_payload.get("results", []):
        # Public results are visible to all containers — not a leak.
        if result.get("container_visibility") == "public":
            continue
        result_container = result.get("container_ref")
        if result_container and result_container != query_container:
            leaked.append({
                "result_id": result.get("result_id"),
                "result_container": result_container,
                "result_visibility": result.get("container_visibility"),
            })

    if leaked:
        return InvariantResult(
            invariant_id="INV-01",
            passed=False,
            details=(
                f"Cross-container leak: {len(leaked)} non-public result(s) from "
                f"wrong container. Query container: {query_container}"
            ),
            evidence={"query_container": query_container, "leaked_results": leaked},
        )
    return InvariantResult(invariant_id="INV-01", passed=True)


# ---------------------------------------------------------------------------
# INV-02: no_wrong_role_memory
# ---------------------------------------------------------------------------

# Memory types that should only be created from user-originated content.
# Interest represents user-expressed preferences ("Chroma sounds interesting").
# If an assistant elaborates on a topic, that should not create an interest
# memory attributed to the user. See agent_conversation_memory_memory.py.
_USER_ONLY_MEMORY_TYPES = frozenset({"interest", "constraint_memory"})


def check_no_wrong_role_memory(
    scenario: dict[str, Any],
    query_payload: dict[str, Any],
    debug_payload: dict[str, Any],
) -> InvariantResult:
    """User-only memory types must not have assistant-only evidence."""
    violations = []
    for result in debug_payload.get("results", []):
        if result.get("result_kind") != "memory_hit":
            continue
        memory_type = result.get("type")
        if memory_type not in _USER_ONLY_MEMORY_TYPES:
            continue
        evidence_roles = {ev.get("role") for ev in result.get("evidence", [])}
        if evidence_roles and evidence_roles <= {"assistant"}:
            violations.append({
                "result_id": result.get("result_id"),
                "memory_type": memory_type,
                "evidence_roles": sorted(evidence_roles),
            })

    if violations:
        return InvariantResult(
            invariant_id="INV-02",
            passed=False,
            details=(
                f"Wrong-role memory: {len(violations)} {_USER_ONLY_MEMORY_TYPES} "
                f"memory hit(s) backed only by assistant evidence"
            ),
            evidence={"violations": violations},
        )
    return InvariantResult(invariant_id="INV-02", passed=True)


# ---------------------------------------------------------------------------
# INV-03: no_off_topic_injection
# ---------------------------------------------------------------------------

def check_no_off_topic_injection(
    scenario: dict[str, Any],
    query_payload: dict[str, Any],
    debug_payload: dict[str, Any],
) -> InvariantResult:
    """Injectable blocks must share content-word overlap with the query."""
    query_text = _query_text(scenario, debug_payload)
    query_tokens = _content_tokens(query_text)
    if not query_tokens:
        return InvariantResult(
            invariant_id="INV-03",
            passed=True,
            details="Query has no content tokens — invariant not applicable",
        )

    blocks = query_payload.get("injectable_blocks", [])
    if not blocks:
        return InvariantResult(invariant_id="INV-03", passed=True)

    off_topic = []
    for block in blocks:
        block_tokens = _content_tokens(block.get("text", ""))
        overlap = query_tokens & block_tokens
        if len(overlap) < _TOPIC_OVERLAP_MIN_TOKENS:
            off_topic.append({
                "result_id": block.get("result_id"),
                "block_preview": (block.get("text") or "")[:120],
                "overlap_tokens": sorted(overlap),
            })

    if off_topic:
        return InvariantResult(
            invariant_id="INV-03",
            passed=False,
            details=(
                f"Off-topic injection: {len(off_topic)} injectable block(s) "
                f"share no content words with the query"
            ),
            evidence={"query_tokens": sorted(query_tokens), "off_topic_blocks": off_topic},
        )
    return InvariantResult(invariant_id="INV-03", passed=True)


# ---------------------------------------------------------------------------
# INV-04: no_visibility_violation
# ---------------------------------------------------------------------------

def check_no_visibility_violation(
    scenario: dict[str, Any],
    query_payload: dict[str, Any],
    debug_payload: dict[str, Any],
) -> InvariantResult:
    """Results must respect the visibility scope of the query.

    Production visibility rule (core/filters.py): public items are visible to
    all containers regardless of the query's visibility. Non-public items must
    match the query's container_ref. This invariant checks the container-scoping
    rule: non-public results must come from the queried container.
    """
    query_container = _query_container_ref(scenario, debug_payload)
    if not query_container:
        return InvariantResult(
            invariant_id="INV-04",
            passed=True,
            details="No container_ref on query — invariant not applicable",
        )

    violations = []
    for result in debug_payload.get("results", []):
        result_vis = result.get("container_visibility")
        # Public results are visible to all — this matches core/filters.py.
        if result_vis == "public":
            continue
        result_container = result.get("container_ref")
        if result_container and result_container != query_container:
            violations.append({
                "result_id": result.get("result_id"),
                "result_container": result_container,
                "result_visibility": result_vis,
            })

    if violations:
        return InvariantResult(
            invariant_id="INV-04",
            passed=False,
            details=(
                f"Visibility violation: {len(violations)} non-public result(s) from "
                f"wrong container. Query container: {query_container}"
            ),
            evidence={"query_container": query_container, "violations": violations},
        )
    return InvariantResult(invariant_id="INV-04", passed=True)


# ---------------------------------------------------------------------------
# INV-05: recall_not_routed_as_noise
# ---------------------------------------------------------------------------

def check_recall_not_routed_as_noise(
    scenario: dict[str, Any],
    query_payload: dict[str, Any],
    debug_payload: dict[str, Any],
) -> InvariantResult:
    """Backward-looking recall queries must not be classified as low-value."""
    query_text = _query_text(scenario, debug_payload).lower()
    is_recall = (
        any(signal in query_text for signal in _RECALL_PHRASE_SIGNALS)
        or any(pat.search(query_text) for pat in _RECALL_WORD_SIGNALS)
    )
    if not is_recall:
        return InvariantResult(
            invariant_id="INV-05",
            passed=True,
            details="Query does not contain recall signals — invariant not applicable",
        )

    routing = _routing_trace(debug_payload)
    low_value = _nested_get(routing, "query_signal_envelope", "low_value")
    if low_value is True:
        return InvariantResult(
            invariant_id="INV-05",
            passed=False,
            details=(
                f"Recall query classified as low_value. "
                f"Query: {query_text[:100]!r}"
            ),
            evidence={
                "query_text": query_text[:200],
                "signal_envelope": routing.get("query_signal_envelope"),
            },
        )
    return InvariantResult(invariant_id="INV-05", passed=True)


# ---------------------------------------------------------------------------
# INV-06: no_greeting_in_blocks
# ---------------------------------------------------------------------------

def check_no_greeting_in_blocks(
    scenario: dict[str, Any],
    query_payload: dict[str, Any],
    debug_payload: dict[str, Any],
) -> InvariantResult:
    """Injectable blocks must not contain trivially phatic/greeting content."""
    blocks = query_payload.get("injectable_blocks", [])
    if not blocks:
        return InvariantResult(invariant_id="INV-06", passed=True)

    greeting_blocks = []
    for block in blocks:
        text = (block.get("text") or "").strip()
        words = text.split()
        if len(words) <= _GREETING_CONTENT_MAX_WORDS and _GREETING_PATTERNS.match(text):
            greeting_blocks.append({
                "result_id": block.get("result_id"),
                "text": text,
            })

    if greeting_blocks:
        return InvariantResult(
            invariant_id="INV-06",
            passed=False,
            details=f"Greeting in injectable blocks: {len(greeting_blocks)} block(s)",
            evidence={"greeting_blocks": greeting_blocks},
        )
    return InvariantResult(invariant_id="INV-06", passed=True)


# ---------------------------------------------------------------------------
# INV-07: query_contract_consistency
# ---------------------------------------------------------------------------

def check_query_contract_consistency(
    scenario: dict[str, Any],
    query_payload: dict[str, Any],
    debug_payload: dict[str, Any],
) -> InvariantResult:
    """/query and /query/debug must return consistent injection decisions.

    The caller (invariant_runner) must call both endpoints separately and pass
    query_payload from POST /query and debug_payload from POST /query/debug.
    """
    q_inject = query_payload.get("should_inject")
    d_inject = debug_payload.get("should_inject")
    q_reason = query_payload.get("decision_reason")
    d_reason = debug_payload.get("decision_reason")
    q_block_count = len(query_payload.get("injectable_blocks", []))
    d_block_count = len(debug_payload.get("injectable_blocks", []))

    mismatches = []
    if q_inject != d_inject:
        mismatches.append(f"should_inject: query={q_inject} vs debug={d_inject}")
    if q_reason != d_reason:
        mismatches.append(f"decision_reason: query={q_reason!r} vs debug={d_reason!r}")
    if q_block_count != d_block_count:
        mismatches.append(f"block_count: query={q_block_count} vs debug={d_block_count}")

    if mismatches:
        return InvariantResult(
            invariant_id="INV-07",
            passed=False,
            details=f"Query contract inconsistency: {'; '.join(mismatches)}",
            evidence={
                "query_should_inject": q_inject,
                "debug_should_inject": d_inject,
                "query_decision_reason": q_reason,
                "debug_decision_reason": d_reason,
                "query_block_count": q_block_count,
                "debug_block_count": d_block_count,
            },
        )
    return InvariantResult(invariant_id="INV-07", passed=True)


# ---------------------------------------------------------------------------
# INV-08: noise_no_injection
# ---------------------------------------------------------------------------

def check_noise_no_injection(
    scenario: dict[str, Any],
    query_payload: dict[str, Any],
    debug_payload: dict[str, Any],
) -> InvariantResult:
    """When signal envelope says low_value, should_inject must be false."""
    routing = _routing_trace(debug_payload)
    low_value = _nested_get(routing, "query_signal_envelope", "low_value")
    if low_value is not True:
        return InvariantResult(
            invariant_id="INV-08",
            passed=True,
            details="Query not classified as low_value — invariant not applicable",
        )

    should_inject = debug_payload.get("should_inject")
    blocks = debug_payload.get("injectable_blocks", [])
    if should_inject is True or blocks:
        return InvariantResult(
            invariant_id="INV-08",
            passed=False,
            details=(
                f"Low-value query has injection: should_inject={should_inject}, "
                f"block_count={len(blocks)}"
            ),
            evidence={
                "should_inject": should_inject,
                "block_count": len(blocks),
                "signal_envelope": routing.get("query_signal_envelope"),
            },
        )
    return InvariantResult(invariant_id="INV-08", passed=True)


# ---------------------------------------------------------------------------
# INV-09: no_superseded_in_results
# ---------------------------------------------------------------------------

def check_no_superseded_in_results(
    scenario: dict[str, Any],
    query_payload: dict[str, Any],
    debug_payload: dict[str, Any],
) -> InvariantResult:
    """Active retrieval must not return superseded memory objects."""
    superseded = []
    for result in debug_payload.get("results", []):
        if result.get("result_kind") != "memory_hit":
            continue
        payload = result.get("payload") or {}
        lifecycle = payload.get("lifecycle_status") or payload.get("lifecycle")
        if lifecycle == "superseded":
            superseded.append({
                "result_id": result.get("result_id"),
                "memory_type": result.get("type"),
            })

    if superseded:
        return InvariantResult(
            invariant_id="INV-09",
            passed=False,
            details=f"Superseded memory in results: {len(superseded)} hit(s)",
            evidence={"superseded_results": superseded},
        )
    return InvariantResult(invariant_id="INV-09", passed=True)


# ---------------------------------------------------------------------------
# INV-10: idf_discrimination
# ---------------------------------------------------------------------------

def check_idf_discrimination(
    scenario: dict[str, Any],
    query_payload: dict[str, Any],
    debug_payload: dict[str, Any],
) -> InvariantResult:
    """When scenario specifies expected ranking, rare-term memory ranks higher.

    This invariant is only applicable when the scenario metadata includes
    ``idf_expected_top_result_id`` — a result_id that should appear in the
    top N results because it contains rare discriminating terms.
    """
    meta = scenario.get("_generation_metadata") or {}
    expected_top_id = meta.get("idf_expected_top_result_id")
    top_n = meta.get("idf_expected_top_n", 3)
    if not expected_top_id:
        return InvariantResult(
            invariant_id="INV-10",
            passed=True,
            details="No idf_expected_top_result_id — invariant not applicable",
        )

    results = debug_payload.get("results", [])
    top_ids = [r.get("result_id") for r in results[:top_n]]
    if expected_top_id in top_ids:
        return InvariantResult(invariant_id="INV-10", passed=True)

    return InvariantResult(
        invariant_id="INV-10",
        passed=False,
        details=(
            f"IDF discrimination failure: expected {expected_top_id!r} in top {top_n}, "
            f"got {top_ids}"
        ),
        evidence={
            "expected_top_result_id": expected_top_id,
            "top_n": top_n,
            "actual_top_ids": top_ids,
        },
    )


# ---------------------------------------------------------------------------
# INV-11: no_personal_memory_in_shared_container
# ---------------------------------------------------------------------------

# Memory types that are inherently personal and should only exist in private
# containers. In shared containers (limited/public) they fall through to
# discussion_summary. See add-actor-scoped-memory-and-container-visibility-rules.
_PERSONAL_MEMORY_TYPES = frozenset({"interest", "constraint_memory"})


def check_no_personal_memory_in_shared_container(
    scenario: dict[str, Any],
    query_payload: dict[str, Any],
    debug_payload: dict[str, Any],
) -> InvariantResult:
    """Personal memory types must not exist in shared (limited/public) containers.

    Interest and constraint_memory are inherently personal. In shared containers
    they should fall through to discussion_summary at write time. If they appear
    in results from a shared-container query, it means the write-time guard failed.
    """
    query_vis = _query_visibility(scenario, debug_payload)
    if query_vis == "private" or query_vis is None:
        return InvariantResult(
            invariant_id="INV-11",
            passed=True,
            details="Private or unknown visibility — invariant not applicable",
        )

    violations = []
    for result in debug_payload.get("results", []):
        if result.get("result_kind") != "memory_hit":
            continue
        memory_type = result.get("type")
        if memory_type in _PERSONAL_MEMORY_TYPES:
            violations.append({
                "result_id": result.get("result_id"),
                "memory_type": memory_type,
                "container_visibility": result.get("container_visibility"),
            })

    if violations:
        return InvariantResult(
            invariant_id="INV-11",
            passed=False,
            details=(
                f"Personal memory in shared container: {len(violations)} "
                f"{_PERSONAL_MEMORY_TYPES} hit(s) in {query_vis} context"
            ),
            evidence={"query_visibility": query_vis, "violations": violations},
        )
    return InvariantResult(invariant_id="INV-11", passed=True)


# ---------------------------------------------------------------------------
# INV-12: no_cross_actor_leak
# ---------------------------------------------------------------------------

def check_no_cross_actor_leak(
    scenario: dict[str, Any],
    query_payload: dict[str, Any],
    debug_payload: dict[str, Any],
) -> InvariantResult:
    """When a query specifies actor_ref, no results with a different actor_ref should appear.

    Actor scoping rules: memories with actor_ref=null are shared and visible to all.
    Memories with actor_ref=X are personal to X and should only appear when the
    querying actor is X. This invariant checks that no result has a non-null actor_ref
    that differs from the query's actor_ref.

    Only applicable when the query supplies actor_ref.
    """
    query_actor = _query_actor_ref(scenario, debug_payload)
    if not query_actor:
        return InvariantResult(
            invariant_id="INV-12",
            passed=True,
            details="No actor_ref on query — invariant not applicable",
        )

    leaked = []
    for result in debug_payload.get("results", []):
        result_actor = result.get("actor_ref")
        # Shared memories (actor_ref=null) are visible to all — not a leak.
        if result_actor is None:
            continue
        if result_actor != query_actor:
            leaked.append({
                "result_id": result.get("result_id"),
                "result_actor_ref": result_actor,
                "memory_type": result.get("type"),
            })

    if leaked:
        return InvariantResult(
            invariant_id="INV-12",
            passed=False,
            details=(
                f"Cross-actor leak: {len(leaked)} result(s) with actor_ref != "
                f"query actor {query_actor!r}"
            ),
            evidence={"query_actor": query_actor, "leaked_results": leaked},
        )
    return InvariantResult(invariant_id="INV-12", passed=True)


# ---------------------------------------------------------------------------
# INV-13: thread_level_memory_always_shared
# ---------------------------------------------------------------------------

# Thread-level memory types must always have actor_ref=null regardless of
# container type. Thread summaries are about the conversation, not an individual.
# See docs/context/architecture.md line 234.
_THREAD_LEVEL_MEMORY_TYPES = frozenset({"thread_summary", "task_checkpoint"})


def check_thread_level_memory_always_shared(
    scenario: dict[str, Any],
    query_payload: dict[str, Any],
    debug_payload: dict[str, Any],
) -> InvariantResult:
    """Thread-level memories must have actor_ref=null (shared).

    Architecture rule: thread_summary and task_checkpoint always have
    actor_ref=null regardless of container type. A thread-level memory
    with a non-null actor_ref indicates a write-path bug.
    """
    violations = []
    for result in debug_payload.get("results", []):
        if result.get("result_kind") != "memory_hit":
            continue
        memory_type = result.get("type")
        if memory_type not in _THREAD_LEVEL_MEMORY_TYPES:
            continue
        actor_ref = result.get("actor_ref")
        if actor_ref is not None:
            violations.append({
                "result_id": result.get("result_id"),
                "memory_type": memory_type,
                "actor_ref": actor_ref,
            })

    if violations:
        return InvariantResult(
            invariant_id="INV-13",
            passed=False,
            details=(
                f"Thread-level memory with actor_ref set: {len(violations)} "
                f"hit(s) should have actor_ref=null"
            ),
            evidence={"violations": violations},
        )
    return InvariantResult(invariant_id="INV-13", passed=True)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

ALL_INVARIANTS = {
    "INV-01": check_no_cross_container_leak,
    "INV-02": check_no_wrong_role_memory,
    "INV-03": check_no_off_topic_injection,
    "INV-04": check_no_visibility_violation,
    "INV-05": check_recall_not_routed_as_noise,
    "INV-06": check_no_greeting_in_blocks,
    "INV-07": check_query_contract_consistency,
    "INV-08": check_noise_no_injection,
    "INV-09": check_no_superseded_in_results,
    "INV-10": check_idf_discrimination,
    "INV-11": check_no_personal_memory_in_shared_container,
    "INV-12": check_no_cross_actor_leak,
    "INV-13": check_thread_level_memory_always_shared,
}


def run_invariants(
    scenario: dict[str, Any],
    query_payload: dict[str, Any],
    debug_payload: dict[str, Any],
    *,
    invariant_ids: list[str] | None = None,
) -> list[InvariantResult]:
    """Run selected (or all) invariants and return results."""
    ids = invariant_ids or list(ALL_INVARIANTS)
    results: list[InvariantResult] = []
    for inv_id in ids:
        check_fn = ALL_INVARIANTS.get(inv_id)
        if check_fn is None:
            results.append(InvariantResult(
                invariant_id=inv_id,
                passed=False,
                severity="error",
                details=f"Unknown invariant: {inv_id!r}",
            ))
            continue
        results.append(check_fn(scenario, query_payload, debug_payload))
    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _query_text(scenario: dict[str, Any], debug_payload: dict[str, Any]) -> str:
    """Extract query text from scenario or debug trace."""
    trace = debug_payload.get("trace") or {}
    if trace.get("query_text"):
        return trace["query_text"]
    # Fall back to scenario current_query or last query step.
    cq = scenario.get("current_query") or {}
    if cq.get("text"):
        return cq["text"]
    for step in reversed(scenario.get("steps") or []):
        if step.get("action") == "query":
            return (step.get("query") or {}).get("text", "")
    return ""


def _query_container_ref(scenario: dict[str, Any], debug_payload: dict[str, Any]) -> str | None:
    """Extract container_ref from scenario query."""
    cq = scenario.get("current_query") or {}
    if cq.get("container_ref"):
        return cq["container_ref"]
    for step in reversed(scenario.get("steps") or []):
        if step.get("action") == "query":
            return (step.get("query") or {}).get("container_ref")
    return None


def _routing_trace(debug_payload: dict[str, Any]) -> dict[str, Any]:
    """Extract routing sub-trace from debug payload."""
    return (debug_payload.get("trace") or {}).get("routing") or {}


def _nested_get(d: dict[str, Any], *keys: str) -> Any:
    """Safely traverse nested dicts."""
    for key in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(key)  # type: ignore[assignment]
    return d


def _query_visibility(scenario: dict[str, Any], debug_payload: dict[str, Any]) -> str | None:
    """Extract container_visibility from scenario query."""
    cq = scenario.get("current_query") or {}
    if cq.get("container_visibility"):
        return cq["container_visibility"]
    for step in reversed(scenario.get("steps") or []):
        if step.get("action") == "query":
            return (step.get("query") or {}).get("container_visibility")
    return None


def _query_actor_ref(scenario: dict[str, Any], debug_payload: dict[str, Any]) -> str | None:
    """Extract actor_ref from scenario query."""
    cq = scenario.get("current_query") or {}
    if cq.get("actor_ref"):
        return cq["actor_ref"]
    for step in reversed(scenario.get("steps") or []):
        if step.get("action") == "query":
            return (step.get("query") or {}).get("actor_ref")
    return None
