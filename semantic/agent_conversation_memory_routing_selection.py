from __future__ import annotations

from dataclasses import replace
from core.models import InjectableBlock, QueryFilters, QueryResultItem, QueryRuntimeContext
from semantic.common import content_tokens, normalize_for_index
from semantic.agent_conversation_memory_constraints import (
    CONSTRAINT_MEMORY_TYPE,
)
from semantic.agent_conversation_memory_threads import (
    _is_low_value_meta_text,
)
from semantic.agent_conversation_memory_routing_constants import (
    ROUTING_LOWER_LEVEL_EXACT_TYPES,
    ROUTING_SUPPORT_THRESHOLD,
    WORK_RESUMPTION_SIGNAL_PRIORITY,
    normalize_lexical_score,
    _candidate_container_refs,
    _candidate_thread_refs,
    _candidate_work_refs,
    _routing_result_id,
)
from semantic.agent_conversation_memory_routing_injection import (
    should_allow_injection,
    candidate_injection_eligible,
    _VERBOSE as _INJECTION_VERBOSE,
    _verbose as _injection_verbose,
)
from semantic.agent_conversation_memory_routing_scoring import (
    _is_current_query_echo,
    _summary_low_value_reason,
)


def _select_final_candidates(
    *,
    intent: str,
    recall_mode: str = "default",
    ranked_candidates: list[dict[str, object]],
    requested_limit: int,
    query_filters: QueryFilters | None,
    query_shape_tags: list[str],
    runtime_context: QueryRuntimeContext | None,
    packaging_summary: dict[str, object] | None,
    selected_lane: str | None = None,
) -> tuple[list[dict[str, object]], dict[str, object] | None]:
    summary = dict(packaging_summary or {})
    if not ranked_candidates:
        return ranked_candidates[:requested_limit], summary or None
    if intent in {"recall"}:
        return _select_compatible_recall_candidates(
            ranked_candidates=ranked_candidates,
            requested_limit=requested_limit,
            query_shape_tags=query_shape_tags,
            packaging_summary=summary,
            selected_lane=selected_lane,
        )
    if intent != "work_resumption":
        return ranked_candidates[:requested_limit], summary or None

    # Filter out suppressed candidates
    unsuppressed = [c for c in ranked_candidates if not c.get("suppression_reason_code")]
    if not unsuppressed:
        return [], summary or None
    top_candidate = unsuppressed[0]
    summary["top_result_layer"] = top_candidate["layer"]
    if top_candidate["layer"] != "task_checkpoint" or requested_limit <= 1:
        demoted_checkpoint = next((candidate for candidate in ranked_candidates if candidate["layer"] == "task_checkpoint"), None)
        if demoted_checkpoint is not None and demoted_checkpoint is not top_candidate:
            summary["demoted_task_checkpoint"] = {
                "result_id": _routing_result_id(demoted_checkpoint["item"]),
                "packaging_reasons": list(demoted_checkpoint["packaging_reasons"]),
            }
        return ranked_candidates[:requested_limit], summary

    selected_candidates = [top_candidate]
    used_result_ids = {_routing_result_id(top_candidate["item"])}
    adjacent_evidence: list[dict[str, str]] = []
    for signal_type in WORK_RESUMPTION_SIGNAL_PRIORITY:
        if len(selected_candidates) >= requested_limit:
            break
        for candidate in ranked_candidates[1:]:
            candidate_result_id = _routing_result_id(candidate["item"])
            if candidate_result_id in used_result_ids:
                continue
            if candidate["layer"] != "source_evidence":
                continue
            if signal_type not in candidate["work_signal_types"]:
                continue
            if not _candidate_locality_compatible_for_packaging(top_candidate["item"], candidate["item"], query_filters):
                continue
            selected_candidates.append(candidate)
            used_result_ids.add(candidate_result_id)
            adjacent_evidence.append({"signal_type": signal_type, "result_id": candidate_result_id})
            break

    if adjacent_evidence:
        summary["mode"] = "task_checkpoint_plus_adjacent_evidence"
        summary["adjacent_evidence"] = adjacent_evidence
    else:
        summary["mode"] = "task_checkpoint_only"

    # Fill any remaining slots with the next-best non-suppressed candidates.
    # The signal-based source_evidence pass may not exhaust the requested limit
    # (e.g. when few source_evidence items carry a matching signal type).  Lower-
    # level memory (decision, investigation_outcome) is useful supporting context
    # and should fill those slots rather than leaving them empty.
    # Apply the same locality guard as the adjacent-evidence pass above so that
    # only same-thread / same-container derived memory is included.
    if len(selected_candidates) < requested_limit:
        CHECKPOINT_FILL_ALLOWED_LAYERS = {"decision", "investigation_outcome", "lower_level_memory"}
        for candidate in ranked_candidates[1:]:
            if len(selected_candidates) >= requested_limit:
                break
            candidate_result_id = _routing_result_id(candidate["item"])
            if candidate_result_id in used_result_ids:
                continue
            if candidate.get("suppression_reason_code"):
                continue
            if candidate["layer"] not in CHECKPOINT_FILL_ALLOWED_LAYERS:
                continue
            if not _candidate_locality_compatible_for_packaging(top_candidate["item"], candidate["item"], query_filters):
                continue
            selected_candidates.append(candidate)
            used_result_ids.add(candidate_result_id)

    return selected_candidates, summary

MIN_SOURCE_HIT_SLOTS = 3
_ACTIVE_TASK_CHECKPOINT_WORK_SIGNALS = frozenset({"blocker", "next_step"})


def _select_compatible_recall_candidates(
    *,
    ranked_candidates: list[dict[str, object]],
    requested_limit: int,
    query_shape_tags: list[str],
    packaging_summary: dict[str, object],
    selected_lane: str | None = None,
) -> tuple[list[dict[str, object]], dict[str, object] | None]:
    compatible_candidates = [c for c in ranked_candidates if not c.get("suppression_reason_code")]
    if not compatible_candidates:
        return [], packaging_summary or None

    primary_candidate = compatible_candidates[0]
    selected_candidates = [primary_candidate]
    used_result_ids = {_routing_result_id(primary_candidate["item"])}
    primary_retrieval_score = int(primary_candidate.get("retrieval_score") or 0)
    retrieval_score_floor = primary_retrieval_score * 0.5

    remaining_candidates = [
        c for c in compatible_candidates
        if _routing_result_id(c["item"]) not in used_result_ids
    ]
    structured_remaining = [
        c for c in remaining_candidates
        if getattr(c["item"], "result_kind", None) == "memory_hit"
    ]
    source_remaining = [
        c for c in remaining_candidates
        if getattr(c["item"], "result_kind", None) != "memory_hit"
    ]

    # Pre-filter sources by score floor
    eligible_source = [
        c for c in source_remaining
        if primary_retrieval_score == 0 or int(c.get("retrieval_score") or 0) >= retrieval_score_floor
    ]

    # Reserve slots for source_hits when eligible sources exist
    reserved = min(MIN_SOURCE_HIT_SLOTS, len(eligible_source), max(0, requested_limit - len(selected_candidates)))
    structured_cap = requested_limit - reserved

    # Fill structured slots up to cap
    for candidate in structured_remaining:
        if len(selected_candidates) >= structured_cap:
            break
        rid = _routing_result_id(candidate["item"])
        if rid in used_result_ids:
            continue
        if primary_retrieval_score > 0 and int(candidate.get("retrieval_score") or 0) < retrieval_score_floor:
            continue
        selected_candidates.append(candidate)
        used_result_ids.add(rid)

    # Fill remaining slots with eligible sources
    for candidate in eligible_source:
        if len(selected_candidates) >= requested_limit:
            break
        rid = _routing_result_id(candidate["item"])
        if rid in used_result_ids:
            continue
        selected_candidates.append(candidate)
        used_result_ids.add(rid)

    return selected_candidates, packaging_summary or None

def _candidate_locality_compatible_for_packaging(
    primary_item: QueryResultItem,
    candidate_item: QueryResultItem,
    query_filters: QueryFilters | None,
) -> bool:
    primary_thread_refs = set(_candidate_thread_refs(primary_item))
    candidate_thread_refs = set(_candidate_thread_refs(candidate_item))
    if query_filters is not None and query_filters.thread_ref:
        return query_filters.thread_ref in primary_thread_refs and query_filters.thread_ref in candidate_thread_refs

    # Work_ref overlap allows cross-thread packaging — items about the same
    # work item can be bundled even if they come from different threads.
    primary_work_refs = set(_candidate_work_refs(primary_item))
    candidate_work_refs = set(_candidate_work_refs(candidate_item))
    if primary_work_refs and candidate_work_refs and primary_work_refs.intersection(candidate_work_refs):
        return True

    # When both items have thread context, require thread overlap.
    # Different threads in the same container are different conversations —
    # a source evidence item from thread B should not be packaged alongside
    # a task_checkpoint from thread A even if they share a container.
    if primary_thread_refs and candidate_thread_refs:
        return bool(primary_thread_refs.intersection(candidate_thread_refs))

    # Fall back to container overlap only when one or both items lack thread
    # context (e.g., consolidation-produced memory that spans threads).
    primary_container_refs = set(_candidate_container_refs(primary_item))
    candidate_container_refs = set(_candidate_container_refs(candidate_item))
    if query_filters is not None and query_filters.container_ref:
        return query_filters.container_ref in primary_container_refs and query_filters.container_ref in candidate_container_refs
    if primary_container_refs and candidate_container_refs:
        return bool(primary_container_refs.intersection(candidate_container_refs))
    return True


def _make_injection_result(
    blocks: list[InjectableBlock],
    *,
    should_inject: bool,
    decision_reason: str,
    returned_block_ids: list[str],
    eligible_result_ids: list[str],
    dropped_by_cap_result_ids: list[str],
    same_thread_context: dict[str, object],
    injection_method: str | None = None,
    dedup_applied: bool = False,
    dedup_removed_count: int = 0,
    dedup_removed_result_ids: list[str] | None = None,
    dedup_kept_map: dict | None = None,
    expansion_applied: bool = False,
    expansion_added_count: int = 0,
    best_lexical: float | None = None,
    best_vector: int | None = None,
    cap_config: dict[str, object] | None = None,
) -> tuple[list[InjectableBlock], dict[str, object]]:
    """Build the standard injection result tuple returned by _build_injectable_blocks."""
    result: dict[str, object] = {
        "should_inject": should_inject,
        "decision_reason": decision_reason,
        "returned_block_ids": returned_block_ids,
        "eligible_result_ids": eligible_result_ids,
        "dropped_by_cap_result_ids": dropped_by_cap_result_ids,
        "cap": INJECTION_HARD_CEILING,
        "dedup_applied": dedup_applied,
        "dedup_removed_count": dedup_removed_count,
        "dedup_removed_result_ids": dedup_removed_result_ids or [],
        "dedup_kept_map": dedup_kept_map or {},
        "expansion_applied": expansion_applied,
        "expansion_added_count": expansion_added_count,
        "same_thread_context_evaluation": same_thread_context,
    }
    if injection_method is not None:
        result["injection_method"] = injection_method
    if best_lexical is not None:
        result["best_lexical"] = best_lexical
    if best_vector is not None:
        result["best_vector"] = best_vector
    if cap_config is not None:
        result["cap_config"] = cap_config
    return blocks, result


def _resolve_gate_blocked_injection(
    final_candidates: list[dict[str, object]],
    ranked_candidates: list[dict[str, object]],
    *,
    intent: str,
    recall_mode: str,
    query_text: str,
    evidence_request: bool,
    same_thread_context: dict[str, object],
) -> tuple[list[InjectableBlock], dict[str, object]] | None:
    """Try override strategies in priority order when the confidence gate blocked injection.

    Returns a result tuple if any override applies, or None to fall through to the
    low_injection_confidence return.
    """
    # Strategy 1: Constraint supplement — recent constraints are cross-cutting and
    # deserve injection even when topical confidence is low.
    constraint_supplements = _find_constraint_supplements(
        ranked_candidates,
        already_selected_ids=set(),
    )
    if constraint_supplements:
        blocks = [_build_injectable_block_from_candidate(c, intent=intent) for c in constraint_supplements]
        returned_ids = [b.result_id for b in blocks]
        if _INJECTION_VERBOSE:
            _injection_verbose(
                f"INJECTION query={query_text[:80]!r} intent={intent} | DECISION: "
                f"should_inject=True reason=constraint_supplement (gate blocked but recent constraint retrieved)"
            )
        return _make_injection_result(
            blocks,
            should_inject=True,
            decision_reason="constraint_supplement",
            injection_method="simplified",
            returned_block_ids=returned_ids,
            eligible_result_ids=returned_ids,
            dropped_by_cap_result_ids=[],
            same_thread_context=same_thread_context,
        )

    # Strategy 2: Carry-forward low confidence override
    carry_forward_override = _carry_forward_low_confidence_override_candidates(
        final_candidates,
        intent=intent,
        recall_mode=recall_mode,
    )
    if carry_forward_override:
        blocks = [_build_injectable_block_from_candidate(c, intent=intent) for c in carry_forward_override]
        returned_ids = [b.result_id for b in blocks]
        eligible_ids = [_routing_result_id(c["item"]) for c in carry_forward_override]
        if _INJECTION_VERBOSE:
            _injection_verbose(
                f"INJECTION query={query_text[:80]!r} intent={intent} | DECISION: "
                "should_inject=True reason=carry_forward_available "
                "(carry-forward low-confidence override)"
            )
        return _make_injection_result(
            blocks,
            should_inject=True,
            decision_reason="carry_forward_available",
            injection_method="carry_forward_low_confidence_override",
            returned_block_ids=returned_ids,
            eligible_result_ids=eligible_ids,
            dropped_by_cap_result_ids=[],
            same_thread_context=same_thread_context,
        )

    # Strategy 3: Supported exact low confidence override
    exact_memory_override = _supported_exact_low_confidence_override_candidates(
        final_candidates,
        intent=intent,
        recall_mode=recall_mode,
        evidence_request=evidence_request,
    )
    if exact_memory_override:
        blocks = [_build_injectable_block_from_candidate(c, intent=intent) for c in exact_memory_override]
        returned_ids = [b.result_id for b in blocks]
        eligible_ids = [_routing_result_id(c["item"]) for c in exact_memory_override]
        if _INJECTION_VERBOSE:
            _injection_verbose(
                f"INJECTION query={query_text[:80]!r} intent={intent} | DECISION: "
                "should_inject=True reason=carry_forward_available "
                "(supported exact-memory override after low-confidence gate)"
            )
        return _make_injection_result(
            blocks,
            should_inject=True,
            decision_reason="carry_forward_available",
            injection_method="supported_exact_low_confidence_override",
            returned_block_ids=returned_ids,
            eligible_result_ids=eligible_ids,
            dropped_by_cap_result_ids=[],
            same_thread_context=same_thread_context,
        )

    # Strategy 4: Source evidence provenance override
    source_evidence_override = _source_evidence_provenance_override_candidates(
        final_candidates,
        intent=intent,
        evidence_request=evidence_request,
        query_text=query_text,
    )
    if source_evidence_override:
        blocks = [_build_injectable_block_from_candidate(c, intent=intent) for c in source_evidence_override]
        returned_ids = [b.result_id for b in blocks]
        eligible_ids = [_routing_result_id(c["item"]) for c in source_evidence_override]
        if _INJECTION_VERBOSE:
            _injection_verbose(
                f"INJECTION query={query_text[:80]!r} intent={intent} | DECISION: "
                "should_inject=True reason=carry_forward_available "
                "(source_evidence provenance override after low-confidence gate)"
            )
        return _make_injection_result(
            blocks,
            should_inject=True,
            decision_reason="carry_forward_available",
            injection_method="source_evidence_provenance_override",
            returned_block_ids=returned_ids,
            eligible_result_ids=eligible_ids,
            dropped_by_cap_result_ids=[],
            same_thread_context=same_thread_context,
        )

    # Strategy 5: Fact summary low confidence override
    fact_summary_override = _fact_summary_low_confidence_override_candidates(
        final_candidates,
        intent=intent,
        query_text=query_text,
    )
    if fact_summary_override:
        selected_override: list[dict[str, object]] = []
        for candidate in fact_summary_override:
            if not _can_select_candidate_under_fact_summary_limit(candidate, selected_override):
                continue
            selected_override.append(candidate)
        if selected_override:
            blocks = [_build_injectable_block_from_candidate(c, intent=intent) for c in selected_override]
            returned_ids = [b.result_id for b in blocks]
            eligible_ids = [_routing_result_id(c["item"]) for c in fact_summary_override]
            dropped_ids = [rid for rid in eligible_ids if rid not in returned_ids]
            if _INJECTION_VERBOSE:
                _injection_verbose(
                    f"INJECTION query={query_text[:80]!r} intent={intent} | DECISION: "
                    "should_inject=True reason=carry_forward_available "
                    "(fact_summary low-confidence override)"
                )
            return _make_injection_result(
                blocks,
                should_inject=True,
                decision_reason="carry_forward_available",
                injection_method="fact_summary_low_confidence_override",
                returned_block_ids=returned_ids,
                eligible_result_ids=eligible_ids,
                dropped_by_cap_result_ids=dropped_ids,
                same_thread_context=same_thread_context,
            )

    # No override strategy applied
    return None


def _select_candidates_with_floor_and_expansion(
    deduped_candidates: list[dict[str, object]],
) -> tuple[list[dict[str, object]], int]:
    """Selects candidates up to floor, then expands if they score well.
    Returns (selected_candidates, expansion_added_count)."""
    floor = min(INJECTION_MIN_FLOOR, len(deduped_candidates))
    selected: list[dict[str, object]] = []
    for candidate in deduped_candidates:
        if len(selected) >= floor:
            break
        if not _can_select_candidate_under_fact_summary_limit(candidate, selected):
            continue
        selected.append(candidate)

    expansion_added = 0
    if deduped_candidates and selected:
        top_score = int(deduped_candidates[0].get("routing_score") or 0)
        if top_score > 0 and len(deduped_candidates) > len(selected):
            expansion_floor_score = top_score * INJECTION_EXPANSION_RATIO
            for candidate in deduped_candidates:
                if candidate in selected:
                    continue
                if len(selected) >= INJECTION_HARD_CEILING:
                    break
                if not _can_select_candidate_under_fact_summary_limit(candidate, selected):
                    continue
                if int(candidate.get("routing_score") or 0) >= expansion_floor_score:
                    selected.append(candidate)
                    expansion_added += 1

    return selected, expansion_added


def _fill_companion_candidates(
    selected_candidates: list[dict[str, object]],
    final_candidates: list[dict[str, object]],
    *,
    intent: str,
    query_text: str,
    evidence_request: bool,
) -> None:
    """Appends work_resumption companion source_hit candidates to the selection list.
    Appends candidates in place."""
    if intent != "work_resumption":
        return
    used_result_ids = {_routing_result_id(candidate["item"]) for candidate in selected_candidates}
    companion_candidates = [
        candidate
        for candidate in final_candidates
        if _candidate_is_injection_eligible(
            candidate,
            intent=intent,
            query_text=query_text,
            allow_discussion_fallback=False,
            allow_source_companion=True,
            evidence_request=evidence_request,
        )
        and candidate["item"].result_kind == "source_hit"
        and _routing_result_id(candidate["item"]) not in used_result_ids
    ]
    for candidate in companion_candidates:
        if len(selected_candidates) >= INJECTION_HARD_CEILING:
            break
        if not _can_select_candidate_under_fact_summary_limit(candidate, selected_candidates):
            continue
        selected_candidates.append(candidate)
        used_result_ids.add(_routing_result_id(candidate["item"]))


def _append_constraint_supplements(
    selected_candidates: list[dict[str, object]],
    ranked_candidates: list[dict[str, object]],
) -> None:
    """Appends constraint supplement candidates to selection if room permits."""
    if len(selected_candidates) >= INJECTION_HARD_CEILING:
        return
    _selected_ids = {_routing_result_id(c["item"]) for c in selected_candidates}
    constraint_supplements = _find_constraint_supplements(
        ranked_candidates,
        already_selected_ids=_selected_ids,
        max_count=min(_CONSTRAINT_SUPPLEMENT_CAP, INJECTION_HARD_CEILING - len(selected_candidates)),
    )
    for cs in constraint_supplements:
        if _is_duplicate_of_selected(cs, selected_candidates):
            continue
        if not _can_select_candidate_under_fact_summary_limit(cs, selected_candidates):
            continue
        selected_candidates.append(cs)


def _resolve_source_evidence_override(
    final_candidates: list[dict[str, object]],
    *,
    intent: str,
    evidence_request: bool,
    query_text: str,
    same_thread_context: dict[str, object],
) -> tuple[list[InjectableBlock], dict[str, object]] | None:
    """Returns a result tuple if source_evidence provenance override applies, else None."""
    source_evidence_override = _source_evidence_provenance_override_candidates(
        final_candidates,
        intent=intent,
        evidence_request=evidence_request,
        query_text=query_text,
    )
    if not source_evidence_override:
        return None
    blocks = [_build_injectable_block_from_candidate(c, intent=intent) for c in source_evidence_override]
    returned_ids = [b.result_id for b in blocks]
    eligible_ids = [_routing_result_id(c["item"]) for c in source_evidence_override]
    if _INJECTION_VERBOSE:
        _injection_verbose(
            f"INJECTION query={query_text[:80]!r} intent={intent} | DECISION: "
            "should_inject=True reason=carry_forward_available "
            "(source_evidence provenance override)"
        )
    return _make_injection_result(
        blocks,
        should_inject=True,
        decision_reason="carry_forward_available",
        injection_method="source_evidence_provenance_override",
        returned_block_ids=returned_ids,
        eligible_result_ids=eligible_ids,
        dropped_by_cap_result_ids=[],
        same_thread_context=same_thread_context,
    )


def _compute_eligible_and_dropped_ids(
    blocks: list[InjectableBlock],
    primary_eligible_candidates: list[dict[str, object]],
    final_candidates: list[dict[str, object]],
    *,
    intent: str,
    query_text: str,
    evidence_request: bool,
) -> tuple[list[str], list[str]]:
    """Computes eligible_ids and dropped_ids.
    Returns (eligible_ids, dropped_ids)."""
    returned_ids = [block.result_id for block in blocks]
    eligible_candidates = list(primary_eligible_candidates)
    if intent == "work_resumption":
        eligible_candidates.extend(
            candidate
            for candidate in final_candidates
            if _candidate_is_injection_eligible(
                candidate,
                intent=intent,
                query_text=query_text,
                allow_discussion_fallback=False,
                allow_source_companion=True,
                evidence_request=evidence_request,
            )
            and candidate["item"].result_kind == "source_hit"
            and _routing_result_id(candidate["item"]) not in {_routing_result_id(item["item"]) for item in eligible_candidates}
        )
    eligible_ids = [_routing_result_id(candidate["item"]) for candidate in eligible_candidates]
    dropped_ids = [result_id for result_id in eligible_ids if result_id not in returned_ids]
    return eligible_ids, dropped_ids


def _build_injectable_blocks(
    final_candidates: list[dict[str, object]],
    *,
    ranked_candidates: list[dict[str, object]],
    intent: str,
    recall_mode: str = "default",
    query_text: str,
    query_filters: QueryFilters | None,
    runtime_context: QueryRuntimeContext | None,
    evidence_request: bool = False,
) -> tuple[list[InjectableBlock], dict[str, object]]:
    same_thread_context = _evaluate_same_thread_local_context(
        ranked_candidates,
        intent=intent,
        query_text=query_text,
        query_filters=query_filters,
        runtime_context=runtime_context,
        evidence_request=evidence_request,
    )
    if same_thread_context["suppress_injection"]:
        return _make_injection_result(
            [],
            should_inject=False,
            decision_reason="same_thread_context_sufficient",
            returned_block_ids=[],
            eligible_result_ids=[],
            dropped_by_cap_result_ids=[],
            same_thread_context=same_thread_context,
        )
    if not final_candidates:
        return _make_injection_result(
            [],
            should_inject=False,
            decision_reason="no_relevant_memory",
            returned_block_ids=[],
            eligible_result_ids=[],
            dropped_by_cap_result_ids=[],
            same_thread_context=same_thread_context,
        )

    if not should_allow_injection(final_candidates, query_text=query_text, intent=intent):
        resolved = _resolve_gate_blocked_injection(
            final_candidates,
            ranked_candidates,
            intent=intent,
            recall_mode=recall_mode,
            query_text=query_text,
            evidence_request=evidence_request,
            same_thread_context=same_thread_context,
        )
        if resolved is not None:
            return resolved
        return _make_injection_result(
            [],
            should_inject=False,
            decision_reason="low_injection_confidence",
            injection_method="simplified",
            best_lexical=max((normalize_lexical_score(c.get("lexical_score")) for c in final_candidates), default=0),
            best_vector=max((int(c.get("vector_score", 0) or 0) for c in final_candidates), default=0),
            returned_block_ids=[],
            eligible_result_ids=[],
            dropped_by_cap_result_ids=[],
            same_thread_context=same_thread_context,
        )

    primary_non_discussion_eligible = [
        candidate
        for candidate in final_candidates
        if _candidate_is_injection_eligible(
            candidate,
            intent=intent,
            query_text=query_text,
            allow_discussion_fallback=False,
            allow_source_companion=False,
            evidence_request=evidence_request,
        )
    ]
    source_evidence_resolved = _resolve_source_evidence_override(
        final_candidates,
        intent=intent,
        evidence_request=evidence_request,
        query_text=query_text,
        same_thread_context=same_thread_context,
    )
    if source_evidence_resolved is not None:
        return source_evidence_resolved
    primary_eligible_candidates = [
        candidate
        for candidate in final_candidates
        if _candidate_is_injection_eligible(
            candidate,
            intent=intent,
            query_text=query_text,
            allow_discussion_fallback=not primary_non_discussion_eligible,
            allow_source_companion=False,
            evidence_request=evidence_request,
        )
    ]
    if not primary_eligible_candidates:
        decision_reason = "only_low_value_candidates" if any(_candidate_is_low_value(candidate) for candidate in final_candidates) else "no_relevant_memory"
        if _INJECTION_VERBOSE:
            _injection_verbose(
                f"INJECTION query={query_text[:80]!r} intent={intent} | DECISION: should_inject=False "
                f"reason={decision_reason} (gate=ALLOW but no eligible candidates after type/intent filter)"
            )
        return _make_injection_result(
            [],
            should_inject=False,
            decision_reason=decision_reason,
            returned_block_ids=[],
            eligible_result_ids=[],
            dropped_by_cap_result_ids=[],
            same_thread_context=same_thread_context,
        )

    # --- Dedup + dynamic cap (replaces static [:3] cap) ---
    deduped_candidates, dedup_removed = _dedup_eligible_candidates(
        primary_eligible_candidates,
        recall_mode=recall_mode,
    )
    dedup_removed_ids = [_routing_result_id(c["item"]) for c in dedup_removed]

    dedup_kept_map: dict[str, str] = {}
    for removed_candidate in dedup_removed:
        removed_id = _routing_result_id(removed_candidate["item"])
        for kept in deduped_candidates:
            if _is_content_duplicate(removed_candidate, kept):
                dedup_kept_map[removed_id] = _routing_result_id(kept["item"])
                break

    selected_candidates, expansion_added = _select_candidates_with_floor_and_expansion(deduped_candidates)

    # Companion fill (work_resumption only): fill to ceiling with dedup check
    _fill_companion_candidates(
        selected_candidates,
        final_candidates,
        intent=intent,
        query_text=query_text,
        evidence_request=evidence_request,
    )

    # Constraint supplement: add recent constraint if room permits, with dedup check
    _append_constraint_supplements(selected_candidates, ranked_candidates)

    blocks = [_build_injectable_block_from_candidate(candidate, intent=intent) for candidate in selected_candidates]
    eligible_ids, dropped_ids = _compute_eligible_and_dropped_ids(
        blocks,
        primary_eligible_candidates,
        final_candidates,
        intent=intent,
        query_text=query_text,
        evidence_request=evidence_request,
    )
    returned_ids = [block.result_id for block in blocks]
    if _INJECTION_VERBOSE:
        block_summaries = []
        for b in blocks:
            block_summaries.append(f"{b.result_id[:30]} type={b.block_type}")
        _injection_verbose(
            f"INJECTION query={query_text[:80]!r} intent={intent} | DECISION: "
            f"should_inject={bool(blocks)} reason={'carry_forward_available' if blocks else 'no_relevant_memory'} "
            f"blocks={len(blocks)} [{'; '.join(block_summaries) if block_summaries else 'none'}]"
        )
    return _make_injection_result(
        blocks,
        should_inject=bool(blocks),
        decision_reason="carry_forward_available" if blocks else "no_relevant_memory",
        injection_method="simplified",
        returned_block_ids=returned_ids,
        eligible_result_ids=eligible_ids,
        dropped_by_cap_result_ids=dropped_ids,
        same_thread_context=same_thread_context,
        cap_config={
            "floor": INJECTION_MIN_FLOOR,
            "expansion_ratio": INJECTION_EXPANSION_RATIO,
            "ceiling": INJECTION_HARD_CEILING,
        },
        dedup_applied=bool(dedup_removed),
        dedup_removed_count=len(dedup_removed),
        dedup_removed_result_ids=dedup_removed_ids,
        dedup_kept_map=dedup_kept_map,
        expansion_applied=expansion_added > 0,
        expansion_added_count=expansion_added,
    )

_SOURCE_EXPANDED_THRESHOLD = 1000
_NOTE_INJECTION_TRUNCATION = 500  # chars — notes longer than this get snippet + source pointer

_SOURCE_EXPANDED_TYPES = frozenset({
    "investigation_outcome",
    "decision",
    "task_checkpoint",
})


def _source_expanded_available(item: QueryResultItem) -> bool:
    return (
        item.type in _SOURCE_EXPANDED_TYPES
        and item.envelope is not None
        and item.envelope.source_content_length > _SOURCE_EXPANDED_THRESHOLD
    )


def _build_raw_injectable_block(candidate: dict[str, object], *, intent: str) -> InjectableBlock:
    item = candidate["item"]
    assert isinstance(item, QueryResultItem)
    mo_id = item.memory_object_id  # None for source hits
    if item.result_kind == "source_hit":
        return InjectableBlock(
            result_id=str(item.result_id),
            block_type="source_evidence",
            title="Supporting Evidence",
            text=str(item.excerpt or "").strip(),
            memory_type=None,
            evidence=item.evidence,
        )

    payload = item.payload or {}
    if item.type == "decision":
        text = str(payload.get("decision") or "").strip()
        rationale = str(payload.get("rationale") or "").strip()
        body = f"Decision: {text}"
        if rationale:
            body += f" Rationale: {rationale}"
        return InjectableBlock(
            result_id=str(item.result_id),
            block_type="memory",
            title="Prior Decision",
            text=body,
            evidence=item.evidence,
            memory_type=item.type,
            memory_object_id=mo_id,
        )
    if item.type == "investigation_outcome":
        text = str(payload.get("investigation_outcome") or "").strip()
        rationale = str(payload.get("rationale") or "").strip()
        body = f"Investigation outcome: {text}"
        if rationale:
            body += f" Rationale: {rationale}"
        return InjectableBlock(
            result_id=str(item.result_id),
            block_type="memory",
            title="Prior Investigation",
            text=body,
            evidence=item.evidence,
            memory_type=item.type,
            memory_object_id=mo_id,
        )
    if item.type == "task_checkpoint":
        return InjectableBlock(
            result_id=str(item.result_id),
            block_type="memory",
            title="Task Checkpoint",
            text=_task_checkpoint_injection_text(payload),
            evidence=item.evidence,
            memory_type=item.type,
            memory_object_id=mo_id,
        )
    if item.type == CONSTRAINT_MEMORY_TYPE:
        constraint_text = str(payload.get("constraint_text") or payload.get("summary") or "").strip()
        summary_text = str(payload.get("summary") or "").strip()
        constraint_line = f"Constraint: {constraint_text}" if constraint_text else ""
        summary_line = ""
        if summary_text and normalize_for_index(summary_text) != normalize_for_index(constraint_line):
            summary_line = summary_text
        return InjectableBlock(
            result_id=str(item.result_id),
            block_type="memory",
            title="Active Constraint",
            text=_join_unique_text_parts([constraint_line, summary_line]),
            evidence=item.evidence,
            memory_type=item.type,
            memory_object_id=mo_id,
        )
    if item.type == "continuity_memory":
        return InjectableBlock(
            result_id=str(item.result_id),
            block_type="memory",
            title="Carry Forward",
            text=str(payload.get("carry_forward_answer") or payload.get("summary") or "").strip(),
            evidence=item.evidence,
            memory_type=item.type,
            memory_object_id=mo_id,
        )
    if item.type == "pattern_memory":
        return InjectableBlock(
            result_id=str(item.result_id),
            block_type="memory",
            title="Pattern Memory",
            text=str(payload.get("summary") or "").strip(),
            evidence=item.evidence,
            memory_type=item.type,
            memory_object_id=mo_id,
        )
    if item.type == "interest":
        interest_text = str(payload.get("interest_text") or payload.get("summary") or "").strip()
        return InjectableBlock(
            result_id=str(item.result_id),
            block_type="memory",
            title="Interest",
            text=interest_text,
            evidence=item.evidence,
            memory_type=item.type,
            memory_object_id=mo_id,
        )
    if item.type == "atomic_fact":
        return InjectableBlock(
            result_id=str(item.result_id),
            block_type="memory",
            title="Known Fact",
            text=str(payload.get("statement") or "").strip(),
            evidence=item.evidence,
            memory_type=item.type,
            memory_object_id=mo_id,
        )
    if item.type == FACT_SUMMARY_TYPE:
        return InjectableBlock(
            result_id=str(item.result_id),
            block_type="memory",
            title="Fact Summary",
            text=str(payload.get("summary") or "").strip(),
            evidence=item.evidence,
            memory_type=item.type,
            memory_object_id=mo_id,
        )
    if item.type in {"thread_summary"}:
        summary_text = str(payload.get("summary") or "").strip()
        return InjectableBlock(
            result_id=str(item.result_id),
            block_type="memory",
            title="Thread Summary",
            text=summary_text,
            evidence=item.evidence,
            memory_type=item.type,
            memory_object_id=mo_id,
        )
    if item.type == "note":
        content = str(payload.get("content") or "").strip()
        title = payload.get("title") or ""
        block_title = f"Note: {title}" if title else "Note"
        truncated = len(content) > _NOTE_INJECTION_TRUNCATION

        if truncated:
            snippet = content[:_NOTE_INJECTION_TRUNCATION].rsplit(" ", 1)[0] + "..."
            text = snippet
        else:
            text = content

        return InjectableBlock(
            result_id=str(item.result_id),
            block_type="memory",
            title=block_title,
            text=text,
            evidence=item.evidence,
            memory_type=item.type,
            memory_object_id=mo_id,
            source_expanded_available=truncated,
        )
    return InjectableBlock(
        result_id=str(item.result_id),
        block_type="memory",
        title=item.type or "Memory",
        text=str(payload.get("summary") or "").strip(),
        evidence=item.evidence,
        memory_type=item.type,
        memory_object_id=mo_id,
    )


def _build_injectable_block_from_candidate(candidate: dict[str, object], *, intent: str) -> InjectableBlock:
    block = _build_raw_injectable_block(candidate, intent=intent)
    if block.block_type == "memory":
        item = candidate["item"]
        assert isinstance(item, QueryResultItem)
        if _source_expanded_available(item):
            block = replace(block, source_expanded_available=True)
    return block


def _task_checkpoint_injection_text(payload: dict[str, object]) -> str:
    summary = str(payload.get("summary") or "").strip()
    current_state = str(payload.get("current_state") or "").strip()
    blocker = str(payload.get("blocker_state") or "").strip()
    next_step = str(payload.get("next_step") or "").strip()
    parts: list[str] = []
    # When an active blocker is present, lead with it so the blocking issue is
    # immediately visible — it is the most actionable signal for resumption.
    if blocker:
        parts.append(f"Blocker: {blocker}")
    if current_state and normalize_for_index(current_state) not in normalize_for_index(blocker):
        parts.append(f"Current state: {current_state}")
    elif not blocker and summary:
        parts.append(summary)
    if next_step:
        parts.append(f"Next step: {next_step}")
    # Always include summary when it carries task identity not already present.
    # This matters for blocker-only checkpoints where current_state is absent:
    # without summary the injected text is just "Blocker: ..." with no task context.
    if summary and not current_state:
        parts.append(summary)
    return _join_unique_text_parts(parts)


def _join_unique_text_parts(parts: list[str]) -> str:
    ordered_parts: list[str] = []
    seen: set[str] = set()
    for part in parts:
        normalized = str(part or "").strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered_parts.append(normalized)
    return " ".join(ordered_parts)

def _evaluate_same_thread_local_context(
    ranked_candidates: list[dict[str, object]],
    *,
    intent: str,
    query_text: str,
    query_filters: QueryFilters | None,
    runtime_context: QueryRuntimeContext | None,
    evidence_request: bool = False,
) -> dict[str, object]:
    if not (
        runtime_context is not None
        and runtime_context.turn_kind in {"same_thread", "same_thread_continuation"}
        and runtime_context.session_has_sufficient_local_context is True
    ):
        return {"evaluated": False, "suppress_injection": False}
    if query_filters is None or not query_filters.thread_ref:
        return {
            "evaluated": True,
            "suppress_injection": True,
            "reason_code": "runtime_same_thread_context_only",
            "qualifying_result_ids": [],
            "external_carry_forward_result_ids": [],
            "rejected_candidates": [],
        }

    qualifying_result_ids: list[str] = []
    external_carry_forward_result_ids: list[str] = []
    rejected_candidates: list[dict[str, str]] = []
    for candidate in ranked_candidates:
        result_id = _routing_result_id(candidate["item"])
        if bool(candidate.get("same_thread")):
            qualifies, reason_code = _candidate_qualifies_as_same_thread_local_state(
                candidate,
                intent=intent,
                query_text=query_text,
                query_filters=query_filters,
            )
            if qualifies:
                qualifying_result_ids.append(result_id)
                continue
            rejected_candidates.append({"result_id": result_id, "reason_code": reason_code})
            continue
        if _candidate_could_supply_external_carry_forward(candidate, intent=intent, query_text=query_text, evidence_request=evidence_request):
            external_carry_forward_result_ids.append(result_id)

    if qualifying_result_ids:
        reason_code = "relevant_same_thread_local_state"
        suppress_injection = True
    elif not external_carry_forward_result_ids:
        reason_code = "no_external_carry_forward_available"
        suppress_injection = True
    else:
        reason_code = "insufficient_same_thread_local_state"
        suppress_injection = False

    return {
        "evaluated": True,
        "suppress_injection": suppress_injection,
        "reason_code": reason_code,
        "qualifying_result_ids": qualifying_result_ids,
        "external_carry_forward_result_ids": external_carry_forward_result_ids[:6],
        "rejected_candidates": rejected_candidates[:6],
    }

def _candidate_could_supply_external_carry_forward(candidate: dict[str, object], *, intent: str, query_text: str, evidence_request: bool = False) -> bool:
    if _candidate_is_low_value(candidate):
        return False
    item = candidate["item"]
    assert isinstance(item, QueryResultItem)
    if item.result_kind == "source_hit":
        return _candidate_is_injection_eligible(
            candidate,
            intent=intent,
            query_text=query_text,
            allow_discussion_fallback=False,
            allow_source_companion=False,
            evidence_request=evidence_request,
        )
    return _candidate_is_injection_eligible(
        candidate,
        intent=intent,
        query_text=query_text,
        allow_discussion_fallback=True,
        allow_source_companion=False,
        evidence_request=evidence_request,
    )

def _candidate_qualifies_as_same_thread_local_state(
    candidate: dict[str, object],
    *,
    intent: str,
    query_text: str,
    query_filters: QueryFilters | None,
) -> tuple[bool, str]:
    item = candidate["item"]
    assert isinstance(item, QueryResultItem)
    suppression_reason = str(candidate.get("suppression_reason_code") or "")
    if suppression_reason:
        return False, suppression_reason
    if _candidate_is_low_value(candidate):
        return False, "low_value_same_thread_context"

    support_grade = str(candidate.get("support_grade") or "weak")
    support_score = int(candidate.get("support_score") or 0)
    work_usefulness = int(candidate.get("work_usefulness_score") or 0)

    if item.result_kind == "source_hit":
        excerpt = str(item.excerpt or "")
        if normalize_for_index(excerpt) == normalize_for_index(query_text):
            return False, "current_query_same_thread_source"
        if _is_current_query_echo(item, query_text=query_text, query_filters=query_filters):
            return False, "query_like_same_thread_source"
        if work_usefulness >= 18:
            return True, ""
        return False, "weak_same_thread_source"

    if item.type in {"task_checkpoint", "decision", "investigation_outcome", CONSTRAINT_MEMORY_TYPE}:
        if support_grade in {"supported", "strong"}:
            return True, ""
        return False, "weak_same_thread_structured_state"

    if item.type in {"thread_summary"}:
        payload = item.payload or {}
        summary_text = str(payload.get("summary") or "").strip()
        summary_rejection = _summary_low_value_reason(
            item.type,
            payload,
            summary_text=summary_text,
            query_text=query_text,
        )
        if summary_rejection is not None:
            return False, summary_rejection[0]
        if payload.get("selected_work_artifacts") or payload.get("conclusions"):
            return True, ""
        if payload.get("content_quality") == "substantive":
            return True, ""
        if support_grade in {"supported", "strong"} and support_score >= ROUTING_SUPPORT_THRESHOLD["supported"]:
            return True, ""
        return False, "weak_same_thread_summary"

    return False, "non_local_state_candidate"


def _candidate_content_surface(item: QueryResultItem) -> str:
    """Extract the candidate's content surface for overlap checking.

    Lightweight extractor covering the key payload fields across all memory
    types.  Does NOT duplicate the full block-builder formatting — only needs
    enough text to check whether query content words appear in the candidate.
    """
    if item.result_kind == "source_hit":
        return str(item.excerpt or "")
    payload = item.payload or {}
    return " ".join(filter(None, [
        str(payload.get("decision") or ""),
        str(payload.get("investigation_outcome") or ""),
        str(payload.get("summary") or ""),
        str(payload.get("carry_forward_answer") or ""),
        str(payload.get("constraint_text") or ""),
        str(payload.get("interest_text") or ""),
        str(payload.get("task") or ""),
        str(payload.get("current_state") or ""),
        str(payload.get("blocker_state") or ""),
        str(payload.get("next_step") or ""),
        str(payload.get("rationale") or ""),
        str(payload.get("statement") or ""),
    ])).strip()


def _scripts_differ(tokens_a: set[str], tokens_b: set[str]) -> bool:
    """True when two token sets use entirely different Unicode scripts.

    When scripts differ, content-overlap is not meaningful — defer to
    vector similarity as the relevance signal.
    """
    if tokens_a & tokens_b:
        return False  # shared tokens → scripts overlap
    def _is_latin(t: str) -> bool:
        return len(t) > 0 and t[0].isascii() and t[0].isalpha()
    latin_a = any(_is_latin(t) for t in tokens_a)
    latin_b = any(_is_latin(t) for t in tokens_b)
    nonlatin_a = any(not t[0].isascii() for t in tokens_a if t and t[0].isalpha())
    nonlatin_b = any(not t[0].isascii() for t in tokens_b if t and t[0].isalpha())
    return (latin_a and not nonlatin_a and nonlatin_b and not latin_b) or \
           (nonlatin_a and not latin_a and latin_b and not nonlatin_b)


def _candidate_has_content_overlap(
    item: QueryResultItem,
    query_text: str,
    *,
    query_ct: set[str] | None = None,
) -> bool:
    """Check whether a candidate shares at least 1 content word with the query.

    Uses stopword-filtered tokenization so that function words like "to", "at",
    "the" don't create false overlap.  When neither side has content tokens
    (e.g., ultra-short query), returns True to avoid over-filtering.
    """
    if query_ct is None:
        query_ct = content_tokens(query_text)
    if not query_ct:
        return True  # can't assess — don't filter
    candidate_text = _candidate_content_surface(item)
    if not candidate_text:
        return False
    candidate_ct = content_tokens(candidate_text)
    if _scripts_differ(query_ct, candidate_ct):
        return True  # cross-language — defer to vector similarity
    return bool(query_ct & candidate_ct)


FACT_SUMMARY_TYPE = "fact_summary"
_SHARED_FACT_SUMMARY_VISIBILITIES = frozenset({"container", "public"})
_SAME_TYPE_DEDUP_CANONICAL_TYPES = frozenset({"decision", "investigation_outcome"})


def _candidate_canonical_key(item: QueryResultItem) -> str:
    payload = item.payload or {}
    raw_key = str(payload.get("canonical_key") or "").strip()
    if not raw_key:
        return ""
    return normalize_for_index(raw_key)


def _fact_summary_is_injection_eligible(
    candidate: dict[str, object],
    *,
    intent: str,
) -> bool:
    if intent != "recall":
        return False
    item = candidate["item"]
    assert isinstance(item, QueryResultItem)
    if item.visibility in _SHARED_FACT_SUMMARY_VISIBILITIES:
        return str(candidate.get("anchor_prefilter_status") or "") == "aligned"
    return True


def _fact_summary_low_confidence_override_candidates(
    candidates: list[dict[str, object]],
    *,
    intent: str,
    query_text: str,
) -> list[dict[str, object]]:
    """Allow isolated fact_summary recall to bypass the generic confidence gate."""
    if intent != "recall" or not candidates:
        return []
    items = [candidate["item"] for candidate in candidates]
    if not all(isinstance(item, QueryResultItem) and item.type == FACT_SUMMARY_TYPE for item in items):
        return []

    query_ct = content_tokens(query_text)
    override_candidates: list[dict[str, object]] = []
    for candidate in candidates:
        item = candidate["item"]
        assert isinstance(item, QueryResultItem)
        if candidate.get("suppression_reason_code"):
            continue
        if _candidate_is_low_value(candidate):
            continue
        if len(query_ct) > 2 and not _candidate_has_content_overlap(item, query_text, query_ct=query_ct):
            continue
        if not _fact_summary_is_injection_eligible(candidate, intent=intent):
            continue
        if float(candidate.get("retrieval_score", 0) or 0) <= 0:
            continue
        override_candidates.append(candidate)
    return override_candidates


def _carry_forward_low_confidence_override_candidates(
    candidates: list[dict[str, object]],
    *,
    intent: str,
    recall_mode: str,
) -> list[dict[str, object]]:
    if intent != "recall" or recall_mode != "continuity_preference":
        return []

    continuity_candidates: list[dict[str, object]] = []
    fallback_candidates: list[dict[str, object]] = []
    for candidate in candidates:
        item = candidate["item"]
        assert isinstance(item, QueryResultItem)
        if item.result_kind != "memory_hit":
            continue
        if candidate.get("suppression_reason_code"):
            continue
        if _candidate_is_low_value(candidate):
            continue
        if float(candidate.get("retrieval_score", 0) or 0) <= 0:
            continue
        if item.type == "continuity_memory":
            continuity_candidates.append(candidate)
        elif item.type == "decision":
            fallback_candidates.append(candidate)

    if continuity_candidates:
        return continuity_candidates[:1]
    return fallback_candidates[:1]


def _candidate_lexical_rank(candidate: dict[str, object]) -> int:
    value = candidate.get("lexical_rank")
    try:
        if value is None:
            raise TypeError
        return int(value)
    except (TypeError, ValueError):
        return 1_000_000


def _supported_exact_low_confidence_override_candidates(
    candidates: list[dict[str, object]],
    *,
    intent: str,
    recall_mode: str,
    evidence_request: bool,
) -> list[dict[str, object]]:
    if intent != "recall" or recall_mode == "continuity_preference" or not candidates:
        return []
    if evidence_request:
        return []

    best_lexical_rank = min((_candidate_lexical_rank(candidate) for candidate in candidates), default=1_000_000)
    override_candidates: list[dict[str, object]] = []
    for candidate in candidates:
        item = candidate["item"]
        assert isinstance(item, QueryResultItem)
        if item.result_kind != "memory_hit":
            continue
        if item.type not in ROUTING_LOWER_LEVEL_EXACT_TYPES:
            continue
        if candidate.get("suppression_reason_code"):
            continue
        if _candidate_is_low_value(candidate):
            continue
        if float(candidate.get("retrieval_score", 0) or 0) <= 0:
            continue
        if _candidate_lexical_rank(candidate) > best_lexical_rank + 1:
            continue
        if not candidate_injection_eligible(candidate):
            continue
        override_candidates.append(candidate)

    override_candidates.sort(
        key=lambda candidate: (
            -int(candidate.get("routing_score") or 0),
            _candidate_lexical_rank(candidate),
        )
    )
    return override_candidates[:1]


def _candidate_is_injection_eligible(
    candidate: dict[str, object],
    *,
    intent: str,
    query_text: str,
    allow_discussion_fallback: bool,
    allow_source_companion: bool,
    evidence_request: bool = False,
) -> bool:
    # Per-candidate lexical grounding check (from simplified injection module)
    if not candidate_injection_eligible(candidate):
        return False
    item = candidate["item"]
    assert isinstance(item, QueryResultItem)
    if _candidate_is_low_value(candidate):
        return False
    if candidate.get("suppression_reason_code"):
        return False
    # Content-overlap grounding: require at least 1 shared content word
    # between the query and the candidate's content surface.
    # Skip for work_resumption — directional context is useful even without
    # lexical confirmation (per injection precision principle in decisions.md).
    # For fresh-thread recall, short topical queries like "weather today"
    # still need overlap; otherwise tiny lexical noise can inject unrelated
    # lower-level memories.
    if intent != "work_resumption":
        query_ct = content_tokens(query_text)
        has_active_task_checkpoint_signals = (
            item.type == "task_checkpoint"
            and bool(set(candidate.get("work_signal_types") or ()) & _ACTIVE_TASK_CHECKPOINT_WORK_SIGNALS)
        )
        if (
            query_ct
            and not has_active_task_checkpoint_signals
            and not _candidate_has_content_overlap(item, query_text, query_ct=query_ct)
        ):
            return False
    if item.result_kind == "source_hit":
        if normalize_for_index(str(item.excerpt or "")) == normalize_for_index(query_text):
            return False
        if _source_candidate_is_primary_injection_eligible(candidate, intent, evidence_request=evidence_request):
            return True
        return allow_source_companion and _source_candidate_is_companion_injection_eligible(intent)
    if item.type == FACT_SUMMARY_TYPE:
        return _fact_summary_is_injection_eligible(candidate, intent=intent)
    if item.type == "atomic_fact":
        return False
    if item.type in {"decision", "investigation_outcome", "task_checkpoint", "continuity_memory", "pattern_memory", "interest", "thread_summary", CONSTRAINT_MEMORY_TYPE}:
        return True
    return False

def _candidate_is_low_value(candidate: dict[str, object]) -> bool:
    item = candidate["item"]
    assert isinstance(item, QueryResultItem)
    if item.result_kind == "source_hit":
        excerpt = str(item.excerpt or "")
        return _is_low_value_meta_text(excerpt)
    if item.type in {"thread_summary"}:
        payload = item.payload or {}
        return _is_low_value_meta_text(str(payload.get("summary") or ""))
    return False

def _source_candidate_is_primary_injection_eligible(candidate: dict[str, object], intent: str, *, evidence_request: bool) -> bool:
    if intent == "evidence_trace":
        item = candidate["item"]
        assert isinstance(item, QueryResultItem)
        excerpt = str(item.excerpt or "")
        if _source_excerpt_disclaims_exact_evidence(excerpt):
            return False
        return True
    if intent == "structured_recall":
        return True
    if intent == "recall" and evidence_request:
        item = candidate["item"]
        assert isinstance(item, QueryResultItem)
        excerpt = str(item.excerpt or "")
        if _source_excerpt_disclaims_exact_evidence(excerpt):
            return False
        return True
    return False

def _source_candidate_is_companion_injection_eligible(intent: str) -> bool:
    return intent == "work_resumption"


def _source_evidence_provenance_override_candidates(
    candidates: list[dict[str, object]],
    *,
    intent: str,
    evidence_request: bool,
    query_text: str,
) -> list[dict[str, object]]:
    if intent == "work_resumption" or not evidence_request:
        return []

    query_ct = content_tokens(query_text)
    override_candidates: list[dict[str, object]] = []
    for candidate in candidates:
        item = candidate["item"]
        assert isinstance(item, QueryResultItem)
        if item.result_kind != "source_hit":
            continue
        if candidate.get("suppression_reason_code"):
            continue
        if _candidate_is_low_value(candidate):
            continue
        if normalize_for_index(str(item.excerpt or "")) == normalize_for_index(query_text):
            continue
        if _source_excerpt_disclaims_exact_evidence(str(item.excerpt or "")):
            continue
        if len(query_ct) > 2 and not _candidate_has_content_overlap(item, query_text, query_ct=query_ct):
            continue
        if float(candidate.get("retrieval_score", 0) or 0) <= 0:
            continue
        override_candidates.append(candidate)
    return override_candidates[:INJECTION_HARD_CEILING]


def _source_excerpt_disclaims_exact_evidence(excerpt: str) -> bool:
    """Return True when the source explicitly states that exact evidence was not retained.

    This is an interim guardrail for evidence_trace suppression.  It catches
    sources that directly disclaim having the evidence ("did not keep the exact
    line", "not preserved", etc.) rather than sources that simply lack strong
    proof.  Keep this list narrow — "probably" alone is NOT sufficient.
    """
    lowered = excerpt.lower()
    return any(phrase in lowered for phrase in (
        "did not keep",
        "didn't keep",
        "don't have the exact",
        "do not have the exact",
        "didn't have the exact",
        "couldn't find the exact",
        "could not find the exact",
        "can't find the exact",
        "cannot find the exact",
        "no exact record",
        "not preserved",
        "wasn't preserved",
        "was not preserved",
    ))


def _annotate_excluded_candidates(
    *,
    ranked_candidates: list[dict[str, object]],
    final_candidates: list[dict[str, object]],
    requested_limit: int,
    routing_focus: dict[str, object],
    packaging_summary: dict[str, object] | None,
) -> None:
    selected_result_ids = {_routing_result_id(candidate["item"]) for candidate in final_candidates}
    packaging_mode = str((packaging_summary or {}).get("mode") or "")
    for candidate in ranked_candidates:
        result_id = _routing_result_id(candidate["item"])
        if result_id in selected_result_ids:
            candidate["excluded_reason_code"] = None
            candidate["excluded_reason"] = None
            continue
        if candidate.get("suppression_reason_code"):
            candidate["excluded_reason_code"] = candidate.get("suppression_reason_code")
            candidate["excluded_reason"] = candidate.get("suppression_reason")
        elif (
            packaging_mode == "task_checkpoint_plus_adjacent_evidence"
            and int(candidate.get("routing_rank", 0)) <= requested_limit
        ):
            candidate["excluded_reason_code"] = "displaced_by_adjacent_evidence_packaging"
            candidate["excluded_reason"] = "Checkpoint packaging preferred adjacent source evidence for resumed-work coverage."
        elif bool(routing_focus.get("applied")) and str(candidate.get("layer")) == str(routing_focus.get("primary_layer")):
            candidate["excluded_reason_code"] = "fallback_layer_deprioritized"
            candidate["excluded_reason"] = str(routing_focus.get("reason"))
        else:
            candidate["excluded_reason_code"] = "lower_routing_score_than_selected_limit"
            candidate["excluded_reason"] = "Candidate remained below the final routed cutoff."


# ---------------------------------------------------------------------------
# Constraint supplement
# ---------------------------------------------------------------------------

_CONSTRAINT_FRESHNESS_WINDOW_DAYS = 14
_CONSTRAINT_SUPPLEMENT_CAP = 1


def _find_constraint_supplements(
    ranked_candidates: list[dict[str, object]],
    *,
    already_selected_ids: set[str],
    max_count: int = _CONSTRAINT_SUPPLEMENT_CAP,
) -> list[dict[str, object]]:
    """Find recent constraint_memory candidates that were retrieved but not selected.

    Constraints are cross-cutting — they apply by context, not topic. When the
    normal injection pipeline doesn't select them (e.g., low lexical/vector scores),
    this supplement adds the most recent retrieved constraints if:
    - They were actually retrieved (vector/lexical similarity confirmed some relevance)
    - They are recent (within freshness window)
    - They are not suppressed
    - There is room in the injection cap

    Returns at most max_count candidates, most recent first.
    """
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=_CONSTRAINT_FRESHNESS_WINDOW_DAYS)

    constraint_candidates = []
    for candidate in ranked_candidates:
        item = candidate.get("item")
        if item is None:
            continue
        if getattr(item, "type", None) != CONSTRAINT_MEMORY_TYPE:
            continue
        if _routing_result_id(item) in already_selected_ids:
            continue
        if candidate.get("suppression_reason_code"):
            continue
        freshness = getattr(item, "freshness_at", None)
        if freshness is not None and freshness < cutoff:
            continue
        constraint_candidates.append(candidate)

    # Sort by freshness (most recent first)
    constraint_candidates.sort(
        key=lambda c: getattr(c.get("item"), "freshness_at", None) or now,
        reverse=True,
    )
    return constraint_candidates[:max_count]


# ---------------------------------------------------------------------------
# Injection dedup + dynamic cap
# ---------------------------------------------------------------------------

INJECTION_MIN_FLOOR = 3
INJECTION_EXPANSION_RATIO = 0.4
INJECTION_HARD_CEILING = 5
DEDUP_EVIDENCE_TEXT_THRESHOLD = 0.75
DEDUP_TEXT_ONLY_THRESHOLD = 0.7
DEDUP_MIN_TOKENS = 2


def _prefer_duplicate_by_nonfact_mode(
    item_a: QueryResultItem,
    item_b: QueryResultItem,
    candidate_a: dict[str, object],
    candidate_b: dict[str, object],
    recall_mode: str,
) -> dict[str, object] | None:
    """Apply recall_mode-specific duplicate preference rules (non-default modes).

    Returns the preferred candidate or None if the mode produces no preference.
    """
    if recall_mode == "sharp_fact_preference":
        if item_a.type in ROUTING_LOWER_LEVEL_EXACT_TYPES and item_b.type in {"continuity_memory", "atomic_fact", "thread_summary"}:
            return candidate_a
        if item_b.type in ROUTING_LOWER_LEVEL_EXACT_TYPES and item_a.type in {"continuity_memory", "atomic_fact", "thread_summary"}:
            return candidate_b
    elif recall_mode == "continuity_preference":
        if item_a.type == "continuity_memory" and item_b.type in {"decision", "investigation_outcome", "atomic_fact", "thread_summary"}:
            return candidate_a
        if item_b.type == "continuity_memory" and item_a.type in {"decision", "investigation_outcome", "atomic_fact", "thread_summary"}:
            return candidate_b
    elif recall_mode == "investigation_preference":
        if item_a.type == "investigation_outcome" and item_b.type == "decision":
            return candidate_a
        if item_b.type == "investigation_outcome" and item_a.type == "decision":
            return candidate_b
    return None


def _prefer_duplicate_by_default_mode(
    item_a: QueryResultItem,
    item_b: QueryResultItem,
    candidate_a: dict[str, object],
    candidate_b: dict[str, object],
) -> dict[str, object] | None:
    """Apply recall_mode == "default" duplicate preference rules.

    Returns the preferred candidate or None if no rule matches.
    """
    if item_a.type == "continuity_memory" and item_b.type == "thread_summary":
        return candidate_a
    if item_b.type == "continuity_memory" and item_a.type == "thread_summary":
        return candidate_b

    continuity_candidate: dict[str, object] | None = None
    exact_candidate: dict[str, object] | None = None
    if item_a.type == "continuity_memory" and item_b.type in ROUTING_LOWER_LEVEL_EXACT_TYPES:
        continuity_candidate = candidate_a
        exact_candidate = candidate_b
    elif item_b.type == "continuity_memory" and item_a.type in ROUTING_LOWER_LEVEL_EXACT_TYPES:
        continuity_candidate = candidate_b
        exact_candidate = candidate_a
    if continuity_candidate is not None and exact_candidate is not None:
        continuity_rank = _candidate_lexical_rank(continuity_candidate)
        exact_rank = _candidate_lexical_rank(exact_candidate)
        if exact_rank >= 5 and continuity_rank + 2 <= exact_rank:
            return continuity_candidate

    return None


def _prefer_duplicate_candidate(
    candidate_a: dict[str, object],
    candidate_b: dict[str, object],
    *,
    recall_mode: str = "default",
) -> dict[str, object]:
    """Choose which duplicate candidate to retain.

    First-rollout rule: a synthesized fact_summary must not displace a sharper
    lower-level memory when both carry the same content.
    """
    item_a = candidate_a["item"]
    item_b = candidate_b["item"]
    assert isinstance(item_a, QueryResultItem)
    assert isinstance(item_b, QueryResultItem)

    mode_result = _prefer_duplicate_by_nonfact_mode(item_a, item_b, candidate_a, candidate_b, recall_mode)
    if mode_result is not None:
        return mode_result

    # Universal fact_summary rule
    if item_a.type == FACT_SUMMARY_TYPE and item_b.type != FACT_SUMMARY_TYPE:
        return candidate_b
    if item_b.type == FACT_SUMMARY_TYPE and item_a.type != FACT_SUMMARY_TYPE:
        return candidate_a

    # Default mode specific rules
    if recall_mode == "default":
        default_result = _prefer_duplicate_by_default_mode(item_a, item_b, candidate_a, candidate_b)
        if default_result is not None:
            return default_result

    score_a = int(candidate_a.get("routing_score") or 0)
    score_b = int(candidate_b.get("routing_score") or 0)
    if score_a != score_b:
        return candidate_a if score_a > score_b else candidate_b

    tokens_a = content_tokens(_candidate_content_surface(item_a))
    tokens_b = content_tokens(_candidate_content_surface(item_b))
    if len(tokens_a) != len(tokens_b):
        return candidate_a if len(tokens_a) > len(tokens_b) else candidate_b

    return candidate_a


def _can_select_candidate_under_fact_summary_limit(
    candidate: dict[str, object],
    selected: list[dict[str, object]],
) -> bool:
    item = candidate["item"]
    assert isinstance(item, QueryResultItem)
    if item.type != FACT_SUMMARY_TYPE:
        return True
    return not any(
        isinstance(kept.get("item"), QueryResultItem)
        and kept["item"].type == FACT_SUMMARY_TYPE
        for kept in selected
    )


def _candidate_evidence_ids(candidate: dict[str, object]) -> set[str]:
    """Extract source_item_ids from a candidate's evidence references."""
    item = candidate["item"]
    assert isinstance(item, QueryResultItem)
    evidence = getattr(item, "evidence", None) or []
    return {e.source_item_id for e in evidence if hasattr(e, "source_item_id")}


def _is_content_duplicate(
    candidate_a: dict[str, object],
    candidate_b: dict[str, object],
) -> bool:
    """Two-gate duplicate check: evidence+text or text-only.

    Returns True when two candidates carry semantically duplicate content.
    Applies between memory_hit candidates of different types and, narrowly,
    between same-type decision/investigation memories that share the same
    canonical key.
    Source hits are never deduped (they are raw evidence, not derived memory).
    Same-type memories are otherwise never deduped (two decisions from the same
    thread are likely about different things even if they share vocabulary).
    Evidence overlap alone is not sufficient (thread-level extractions share
    all source items) — it must be combined with text overlap.
    """
    item_a = candidate_a["item"]
    item_b = candidate_b["item"]
    assert isinstance(item_a, QueryResultItem)
    assert isinstance(item_b, QueryResultItem)

    # Only dedup between memory_hit candidates of different types
    if item_a.result_kind != "memory_hit" or item_b.result_kind != "memory_hit":
        return False
    same_type_canonical_duplicate = False
    if item_a.type == item_b.type:
        if item_a.type not in _SAME_TYPE_DEDUP_CANONICAL_TYPES:
            return False
        canonical_key_a = _candidate_canonical_key(item_a)
        canonical_key_b = _candidate_canonical_key(item_b)
        if canonical_key_a != canonical_key_b:
            return False
        if not canonical_key_a:
            return False
        same_type_canonical_duplicate = True

    evidence_a = _candidate_evidence_ids(candidate_a)
    evidence_b = _candidate_evidence_ids(candidate_b)
    if same_type_canonical_duplicate and evidence_a and evidence_b and evidence_a & evidence_b:
        return True

    text_a = _candidate_content_surface(item_a)
    text_b = _candidate_content_surface(item_b)
    tokens_a = content_tokens(text_a)
    tokens_b = content_tokens(text_b)

    # Overlap coefficient: |intersection| / min(|A|, |B|)
    min_size = min(len(tokens_a), len(tokens_b))
    if min_size == 0:
        return False
    overlap = len(tokens_a & tokens_b) / min_size

    # Gate 1: evidence overlap + loose text threshold
    if evidence_a and evidence_b and evidence_a & evidence_b:
        if overlap >= DEDUP_EVIDENCE_TEXT_THRESHOLD:
            return True

    # Gate 2: text-only with strict threshold (needs minimum tokens)
    if min_size >= DEDUP_MIN_TOKENS and overlap >= DEDUP_TEXT_ONLY_THRESHOLD:
        return True

    return False


def _dedup_eligible_candidates(
    candidates: list[dict[str, object]],
    *,
    recall_mode: str = "default",
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Greedy dedup sweep: retain candidates in routing_score order, skip duplicates.

    Returns (retained, removed) where removed candidates are those that
    duplicate an already-retained candidate.
    """
    if len(candidates) <= 1:
        return list(candidates), []

    retained: list[dict[str, object]] = []
    removed: list[dict[str, object]] = []
    for candidate in candidates:
        duplicate_index: int | None = None
        for index, kept in enumerate(retained):
            if _is_content_duplicate(candidate, kept):
                duplicate_index = index
                break
        if duplicate_index is not None:
            kept = retained[duplicate_index]
            preferred = _prefer_duplicate_candidate(candidate, kept, recall_mode=recall_mode)
            if preferred is kept:
                removed.append(candidate)
            else:
                removed.append(kept)
                retained[duplicate_index] = candidate
        else:
            retained.append(candidate)
    return retained, removed


def _is_duplicate_of_selected(
    candidate: dict[str, object],
    selected: list[dict[str, object]],
) -> bool:
    """Check if a candidate duplicates any already-selected candidate."""
    for kept in selected:
        if _is_content_duplicate(candidate, kept):
            return True
    return False
