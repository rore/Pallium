from __future__ import annotations

from core.models import InjectableBlock, QueryFilters, QueryResultItem, QueryRuntimeContext
from semantic.common import normalize_for_index
from semantic.agent_conversation_memory_constraints import (
    CONSTRAINT_MEMORY_TYPE,
)
from semantic.agent_conversation_memory_threads import (
    _is_low_value_meta_text,
)
from semantic.agent_conversation_memory_routing_constants import (
    INJECTION_RETRIEVAL_RELEVANCE_FLOOR,
    ROUTING_SUPPORT_THRESHOLD,
    WORK_RESUMPTION_SIGNAL_PRIORITY,
    _candidate_container_refs,
    _candidate_thread_refs,
    _routing_result_id,
)
from semantic.agent_conversation_memory_routing_scoring import (
    _is_current_query_echo,
    _summary_low_value_reason,
)


def _select_final_candidates(
    *,
    intent: str,
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
    if intent in {"broad_recall", "answer_continuity"}:
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

def _select_compatible_recall_candidates(
    *,
    ranked_candidates: list[dict[str, object]],
    requested_limit: int,
    query_shape_tags: list[str],
    packaging_summary: dict[str, object],
    selected_lane: str | None = None,
) -> tuple[list[dict[str, object]], dict[str, object] | None]:
    # Filter out suppressed candidates
    compatible_candidates = [c for c in ranked_candidates if not c.get("suppression_reason_code")]
    if not compatible_candidates:
        return [], packaging_summary or None

    primary_candidate = compatible_candidates[0]

    selected_candidates = [primary_candidate]
    used_result_ids = {_routing_result_id(primary_candidate["item"])}
    primary_retrieval_score = int(primary_candidate.get("retrieval_score") or 0)
    retrieval_score_floor = primary_retrieval_score * 0.5

    remaining_candidates = [
        candidate
        for candidate in compatible_candidates
        if _routing_result_id(candidate["item"]) not in used_result_ids
    ]
    structured_remaining = [
        candidate
        for candidate in remaining_candidates
        if getattr(candidate["item"], "result_kind", None) == "memory_hit"
    ]
    source_remaining = [
        candidate
        for candidate in remaining_candidates
        if getattr(candidate["item"], "result_kind", None) != "memory_hit"
    ]
    for candidate_group in (structured_remaining, source_remaining):
        for candidate in candidate_group:
            candidate_result_id = _routing_result_id(candidate["item"])
            if candidate_result_id in used_result_ids:
                continue
            if len(selected_candidates) >= requested_limit:
                break
            candidate_retrieval_score = int(candidate.get("retrieval_score") or 0)
            if primary_retrieval_score > 0 and candidate_retrieval_score < retrieval_score_floor:
                continue
            selected_candidates.append(candidate)
            used_result_ids.add(candidate_result_id)
        if len(selected_candidates) >= requested_limit:
            break

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
    if primary_thread_refs and candidate_thread_refs and primary_thread_refs.intersection(candidate_thread_refs):
        return True

    primary_container_refs = set(_candidate_container_refs(primary_item))
    candidate_container_refs = set(_candidate_container_refs(candidate_item))
    if query_filters is not None and query_filters.container_ref:
        return query_filters.container_ref in primary_container_refs and query_filters.container_ref in candidate_container_refs
    if primary_container_refs and candidate_container_refs:
        return bool(primary_container_refs.intersection(candidate_container_refs))
    return True


def _any_candidate_passes_retrieval_relevance_floor(
    candidates: list[dict[str, object]],
    *,
    floor: int,
) -> tuple[bool, str]:
    """Check if any candidate has sufficient lexical retrieval quality.

    Returns (passes, reason) where reason describes why the check passed
    or failed.  Used to suppress injection when the query has near-zero
    content overlap with all retrieved candidates.

    The floor only activates when composite retrieval is in play
    (retrieval_source is set).  In lexical-only mode the score IS the
    IDF quality signal, not a rank-derived RRF score, so the existing
    scoring pipeline is sufficient.
    """
    has_composite_candidate = False
    for c in candidates:
        item: QueryResultItem = c["item"]
        if item.retrieval_source is None:
            # Lexical-only retrieval: floor not applied
            return True, "lexical_only_retrieval"
        has_composite_candidate = True
        if item.retrieval_source == "vector":
            continue  # No lexical match at all
        if item.lexical_score is not None:
            if item.lexical_score >= floor:
                return True, "lexical_score_above_floor"
            continue
        # "both"/"lexical" without lexical_score — defensive pass
        return True, "lexical_score_missing_defensive_pass"
    if not has_composite_candidate:
        return True, "no_composite_candidates"
    return False, "no_candidate_above_floor"


def _build_injectable_blocks(
    final_candidates: list[dict[str, object]],
    *,
    ranked_candidates: list[dict[str, object]],
    intent: str,
    query_text: str,
    query_filters: QueryFilters | None,
    runtime_context: QueryRuntimeContext | None,
) -> tuple[list[InjectableBlock], dict[str, object]]:
    same_thread_context = _evaluate_same_thread_local_context(
        ranked_candidates,
        intent=intent,
        query_text=query_text,
        query_filters=query_filters,
        runtime_context=runtime_context,
    )
    if same_thread_context["suppress_injection"]:
        return [], {
            "should_inject": False,
            "decision_reason": "same_thread_context_sufficient",
            "returned_block_ids": [],
            "eligible_result_ids": [],
            "dropped_by_cap_result_ids": [],
            "cap": 3,
            "same_thread_context_evaluation": same_thread_context,
        }
    if not final_candidates:
        return [], {
            "should_inject": False,
            "decision_reason": "no_relevant_memory",
            "returned_block_ids": [],
            "eligible_result_ids": [],
            "dropped_by_cap_result_ids": [],
            "cap": 3,
            "same_thread_context_evaluation": same_thread_context,
        }

    passes_floor, floor_reason = _any_candidate_passes_retrieval_relevance_floor(
        final_candidates, floor=INJECTION_RETRIEVAL_RELEVANCE_FLOOR,
    )
    if not passes_floor:
        return [], {
            "should_inject": False,
            "decision_reason": "low_retrieval_relevance",
            "retrieval_relevance_floor_reason": floor_reason,
            "returned_block_ids": [],
            "eligible_result_ids": [],
            "dropped_by_cap_result_ids": [],
            "cap": 3,
            "same_thread_context_evaluation": same_thread_context,
        }

    primary_non_discussion_eligible = [
        candidate
        for candidate in final_candidates
        if _candidate_is_injection_eligible(
            candidate,
            intent=intent,
            query_text=query_text,
            allow_discussion_fallback=False,
            allow_source_companion=False,
        )
    ]
    primary_eligible_candidates = [
        candidate
        for candidate in final_candidates
        if _candidate_is_injection_eligible(
            candidate,
            intent=intent,
            query_text=query_text,
            allow_discussion_fallback=not primary_non_discussion_eligible,
            allow_source_companion=False,
        )
    ]
    if not primary_eligible_candidates:
        decision_reason = "only_low_value_candidates" if any(_candidate_is_low_value(candidate) for candidate in final_candidates) else "no_relevant_memory"
        return [], {
            "should_inject": False,
            "decision_reason": decision_reason,
            "returned_block_ids": [],
            "eligible_result_ids": [],
            "dropped_by_cap_result_ids": [],
            "cap": 3,
            "same_thread_context_evaluation": same_thread_context,
        }

    selected_candidates = list(primary_eligible_candidates[:3])
    if intent == "work_resumption" and len(selected_candidates) < 3:
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
            )
            and candidate["item"].result_kind == "source_hit"
            and _routing_result_id(candidate["item"]) not in used_result_ids
        ]
        for candidate in companion_candidates:
            if len(selected_candidates) >= 3:
                break
            selected_candidates.append(candidate)
            used_result_ids.add(_routing_result_id(candidate["item"]))

    blocks = [_build_injectable_block_from_candidate(candidate, intent=intent) for candidate in selected_candidates]
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
            )
            and candidate["item"].result_kind == "source_hit"
            and _routing_result_id(candidate["item"]) not in {_routing_result_id(item["item"]) for item in eligible_candidates}
        )
    eligible_ids = [_routing_result_id(candidate["item"]) for candidate in eligible_candidates]
    dropped_ids = [result_id for result_id in eligible_ids if result_id not in returned_ids]
    return blocks, {
        "should_inject": bool(blocks),
        "decision_reason": "carry_forward_available" if blocks else "no_relevant_memory",
        "returned_block_ids": returned_ids,
        "eligible_result_ids": eligible_ids,
        "dropped_by_cap_result_ids": dropped_ids,
        "cap": 3,
        "same_thread_context_evaluation": same_thread_context,
    }

def _build_injectable_block_from_candidate(candidate: dict[str, object], *, intent: str) -> InjectableBlock:
    item = candidate["item"]
    assert isinstance(item, QueryResultItem)
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
        )
    if item.type == "task_checkpoint":
        return InjectableBlock(
            result_id=str(item.result_id),
            block_type="memory",
            title="Task Checkpoint",
            text=_task_checkpoint_injection_text(payload),
            evidence=item.evidence,
            memory_type=item.type,
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
        )
    if item.type == "continuity_memory":
        return InjectableBlock(
            result_id=str(item.result_id),
            block_type="memory",
            title="Carry Forward",
            text=str(payload.get("carry_forward_answer") or payload.get("summary") or "").strip(),
            evidence=item.evidence,
            memory_type=item.type,
        )
    if item.type == "pattern_memory":
        return InjectableBlock(
            result_id=str(item.result_id),
            block_type="memory",
            title="Pattern Memory",
            text=str(payload.get("summary") or "").strip(),
            evidence=item.evidence,
            memory_type=item.type,
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
        )
    if item.type in {"thread_summary", "discussion_summary"}:
        summary_text = str(payload.get("summary") or "").strip()
        return InjectableBlock(
            result_id=str(item.result_id),
            block_type="memory",
            title="Thread Summary" if item.type == "thread_summary" else "Discussion Summary",
            text=summary_text,
            evidence=item.evidence,
            memory_type=item.type,
        )
    return InjectableBlock(
        result_id=str(item.result_id),
        block_type="memory",
        title=item.type or "Memory",
        text=str(payload.get("summary") or "").strip(),
        evidence=item.evidence,
        memory_type=item.type,
    )

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
        if _candidate_could_supply_external_carry_forward(candidate, intent=intent, query_text=query_text):
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

def _candidate_could_supply_external_carry_forward(candidate: dict[str, object], *, intent: str, query_text: str) -> bool:
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
        )
    return _candidate_is_injection_eligible(
        candidate,
        intent=intent,
        query_text=query_text,
        allow_discussion_fallback=True,
        allow_source_companion=False,
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
    overlap_tokens = list(candidate.get("content_overlap_tokens") or [])

    if item.result_kind == "source_hit":
        excerpt = str(item.excerpt or "")
        if normalize_for_index(excerpt) == normalize_for_index(query_text):
            return False, "current_query_same_thread_source"
        if _is_current_query_echo(item, query_text=query_text, query_filters=query_filters):
            return False, "query_like_same_thread_source"
        if work_usefulness >= 18:
            return True, ""
        if support_grade in {"supported", "strong"} and len(overlap_tokens) >= 2:
            if item.role == "assistant" or intent in {"precise_fact", "evidence_trace", "investigative_conclusion"}:
                return True, ""
        return False, "weak_same_thread_source"

    if item.type in {"task_checkpoint", "decision", "investigation_outcome", CONSTRAINT_MEMORY_TYPE}:
        if support_grade in {"supported", "strong"}:
            return True, ""
        return False, "weak_same_thread_structured_state"

    if item.type in {"thread_summary", "discussion_summary"}:
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
        if support_grade in {"supported", "strong"} and (support_score >= ROUTING_SUPPORT_THRESHOLD["supported"] or len(overlap_tokens) >= 2):
            return True, ""
        return False, "weak_same_thread_summary"

    return False, "non_local_state_candidate"

def _candidate_is_injection_eligible(
    candidate: dict[str, object],
    *,
    intent: str,
    query_text: str,
    allow_discussion_fallback: bool,
    allow_source_companion: bool,
) -> bool:
    item = candidate["item"]
    assert isinstance(item, QueryResultItem)
    if _candidate_is_low_value(candidate):
        return False
    if candidate.get("suppression_reason_code"):
        return False
    if item.result_kind == "source_hit":
        if normalize_for_index(str(item.excerpt or "")) == normalize_for_index(query_text):
            return False
        if _source_candidate_is_primary_injection_eligible(candidate, intent, query_text=query_text):
            return True
        return allow_source_companion and _source_candidate_is_companion_injection_eligible(intent)
    if item.type in {"decision", "investigation_outcome", "task_checkpoint", "continuity_memory", "pattern_memory", "interest", "thread_summary", CONSTRAINT_MEMORY_TYPE}:
        return True
    if item.type == "discussion_summary":
        return allow_discussion_fallback
    return False

def _candidate_is_low_value(candidate: dict[str, object]) -> bool:
    item = candidate["item"]
    assert isinstance(item, QueryResultItem)
    if item.result_kind == "source_hit":
        excerpt = str(item.excerpt or "")
        return _is_low_value_meta_text(excerpt)
    if item.type in {"discussion_summary", "thread_summary"}:
        payload = item.payload or {}
        return _is_low_value_meta_text(str(payload.get("summary") or ""))
    return False

def _source_candidate_is_primary_injection_eligible(candidate: dict[str, object], intent: str, *, query_text: str) -> bool:
    if intent == "evidence_trace":
        item = candidate["item"]
        assert isinstance(item, QueryResultItem)
        excerpt = str(item.excerpt or "")
        if _source_excerpt_disclaims_exact_evidence(excerpt):
            return False
        return True
    if intent == "investigative_conclusion":
        return True
    return intent == "precise_fact" and _source_candidate_has_quote_grade_support(candidate, query_text=query_text)

def _source_candidate_is_companion_injection_eligible(intent: str) -> bool:
    return intent == "work_resumption"

def _source_candidate_has_quote_grade_support(candidate: dict[str, object], *, query_text: str) -> bool:
    if not _query_requests_quote_grade_source(query_text):
        return False
    overlap_tokens = {str(token) for token in candidate.get("content_overlap_tokens") or []}
    proof_overlap = overlap_tokens.intersection({"exact", "line", "log", "proof", "quote"})
    item = candidate["item"]
    assert isinstance(item, QueryResultItem)
    excerpt = str(item.excerpt or "")
    excerpt_lower = excerpt.lower()
    if any(hedge in excerpt_lower for hedge in ("probably", "maybe", "somewhere", "did not keep", "don't have", "not sure")):
        return False
    proof_like_excerpt = any(
        cue in excerpt_lower
        for cue in ("investigation found", "exact log line", "smoking gun", "showed", "proved", "backed")
    )
    quoted_evidence = (excerpt.count("'") >= 2 or excerpt.count('"') >= 2) and bool(proof_overlap)
    support_grade = str(candidate.get("support_grade") or "weak")
    return (support_grade in {"supported", "strong"} and proof_like_excerpt) or quoted_evidence


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


def _query_requests_quote_grade_source(query_text: str) -> bool:
    lowered = query_text.lower()
    if any(
        cue in lowered
        for cue in (
            "exact line",
            "exact log line",
            "proof line",
            "smoking gun",
            "exact wording",
            "exact text",
            "quote the",
            "quote that",
        )
    ):
        return True
    if ("which line" in lowered or "what line" in lowered) and any(
        cue in lowered for cue in ("prove", "proved", "proof", "backed", "support", "supported", "log")
    ):
        return True
    return False

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
