from __future__ import annotations

from core.models import QueryResultItem, QueryRuntimeContext
from semantic.agent_conversation_memory_routing_constants import (
    PolicySelectedContext,
    LaneEligibility,
    LaneNarrowingResult,
    QUERY_POLICY_FAMILY_ALLOWED_INTENTS,
    LATEST_STATUS_COLLAPSED_INTENTS,
    AMBIGUITY_MARGIN_LATEST_VS_RESUME,
    AMBIGUITY_MARGIN_CONSTRAINTS_VS_RECALL,
    LANE_INTENT_MAPPING,
    LANE_POLICY_FAMILY_MAPPING,
    _result_layer,
)
from semantic.agent_conversation_memory_routing_signals import (
    _work_state_evidence_gate_passes,
    _policy_candidate_support_estimate,
)


def _invoke_resolver_for_ambiguity(
    *,
    ambiguity_pair_type: str,
    query_text: str,
    candidates: list[QueryResultItem],
    runtime_context: QueryRuntimeContext | None,
    resolver_config: dict[str, object],
    option_a: dict[str, object],
    option_b: dict[str, object],
) -> bool:
    """Single entry point for all resolver-mediated ambiguity decisions.

    Returns True if option A was selected with valid confidence.
    """
    from semantic.agent_conversation_memory_resolver import (
        build_resolver_packet,
        resolve_query_ambiguity,
    )

    scored_cards = _build_resolver_candidate_cards(candidates, option_a, option_b)
    packet = build_resolver_packet(
        query_text=query_text,
        turn_kind=runtime_context.turn_kind if runtime_context else None,
        ambiguity_pair_type=ambiguity_pair_type,
        option_a=option_a,
        option_b=option_b,
        candidates=scored_cards,
    )
    result = resolve_query_ambiguity(
        provider=resolver_config["provider"],
        model=None,
        prompt_variant=None,  # resolver selects based on ambiguity_pair_type
        resolver_packet=packet,
        timeout_ms=int(resolver_config.get("resolver_timeout_ms", 800)),
    )
    return result.is_valid_selection and result.selected_option_id == "A"


def _build_resolver_candidate_cards(
    candidates: list[QueryResultItem],
    option_a: dict[str, object],
    option_b: dict[str, object],
) -> list[dict[str, object]]:
    """Build compact candidate cards for the resolver from routing candidates."""
    cards: list[dict[str, object]] = []
    for c in candidates[:10]:
        layer = "source_evidence" if c.result_kind == "source_hit" else c.type or "unknown"
        summary = ""
        if c.payload:
            summary = str(c.payload.get("summary", ""))[:200]
        elif c.result_kind == "source_hit":
            summary = str(c.source_type or "source")[:200]
        cards.append({
            "result_id": c.result_id or c.memory_object_id or "",
            "layer": layer,
            "memory_type": c.type or c.result_kind,
            "support_score": int(c.score or 0),
            "summary": summary,
        })
    return cards


def _determine_eligible_lanes(
    *,
    text: str,
    query_shape_tags: list[str],
    policy_evidence: dict[str, object],
    anchor_prefiltered_candidates: list[QueryResultItem],
    family_inference: dict[str, object],
    runtime_context: QueryRuntimeContext | None,
) -> LaneNarrowingResult:
    lanes: list[LaneEligibility] = []

    # --- work_resumption ---
    work_structural: list[str] = []
    work_shape: list[str] = []
    is_resumed_session = runtime_context is not None and runtime_context.turn_kind == "resumed_session"
    has_resume_state_tag = "resume_state" in query_shape_tags
    work_evidence_gate = _work_state_evidence_gate_passes(policy_evidence)
    if is_resumed_session:
        work_structural.append("resumed_session")
    if has_resume_state_tag:
        work_shape.append("resume_state_tag")
    if int(policy_evidence.get("task_checkpoint_best_work_usefulness", 0)) > 0:
        work_structural.append("checkpoint_usefulness_present")
    # Strong eligibility requires both a query-side signal AND candidate-side evidence.
    # resumed_session alone is only plausible — users ask broad recall questions in
    # resumed sessions. Evidence gate alone is also insufficient (see constraint test).
    if is_resumed_session and work_evidence_gate:
        work_structural.append("resumed_session_with_evidence")
        work_state = "strongly_eligible"
        work_reason = "Structural work signal: resumed session with checkpoint evidence"
    elif work_evidence_gate and has_resume_state_tag:
        work_structural.append("work_state_evidence_gate")
        work_state = "strongly_eligible"
        work_reason = "Structural work signal: evidence gate + resume_state tag"
    elif work_shape or work_structural:
        work_state = "plausible"
        all_hints = work_shape + [s for s in work_structural if s not in ("resumed_session_with_evidence", "work_state_evidence_gate")]
        work_reason = ("Structural and shape hints: " if work_structural else "Query-shape hint only: ") + ", ".join(all_hints)
    else:
        work_state = "excluded"
        work_reason = "No work resumption signals"
    lanes.append(LaneEligibility(
        lane="work_resumption", state=work_state,
        structural_signals=tuple(work_structural), shape_signals=tuple(work_shape),
        reason=work_reason,
    ))

    # --- evidence_trace ---
    evidence_structural: list[str] = []
    evidence_shape: list[str] = []
    has_source_hits = any(item.result_kind == "source_hit" for item in anchor_prefiltered_candidates)
    if "evidence_request" in query_shape_tags and has_source_hits:
        evidence_structural.append("evidence_request_with_source_hits")
    if has_source_hits and not evidence_structural:
        evidence_shape.append("source_hits_present")

    if evidence_structural:
        evidence_state = "strongly_eligible"
        evidence_reason = "Structural evidence signal: " + ", ".join(evidence_structural)
    elif evidence_shape:
        evidence_state = "plausible"
        evidence_reason = "Source hits present but no explicit evidence request"
    else:
        evidence_state = "excluded"
        evidence_reason = "No source evidence signals"
    lanes.append(LaneEligibility(
        lane="evidence_trace", state=evidence_state,
        structural_signals=tuple(evidence_structural), shape_signals=tuple(evidence_shape),
        reason=evidence_reason,
    ))

    # --- residual_recall ---
    strongly_eligible_lanes = [le for le in lanes if le.state == "strongly_eligible"]
    if strongly_eligible_lanes:
        residual_state = "excluded"
        residual_reason = "Excluded: other lane(s) strongly eligible"
    else:
        residual_state = "plausible"
        residual_reason = "No lane strongly eligible; fallthrough to existing pipeline"
    lanes.append(LaneEligibility(
        lane="residual_recall", state=residual_state,
        structural_signals=(), shape_signals=(), reason=residual_reason,
    ))

    # --- Decision logic ---
    strongly_count = len(strongly_eligible_lanes)

    if strongly_count == 1:
        winner = strongly_eligible_lanes[0]
        return LaneNarrowingResult(
            eligible_lanes=tuple(lanes),
            selected_lane=winner.lane,
            selection_mode="single_lane_bypass",
            lane_narrowing_used_intent=False,
            intent_effect="none",
            abstain_reason=None,
            mapped_intent=LANE_INTENT_MAPPING.get(winner.lane),
            mapped_policy_family=LANE_POLICY_FAMILY_MAPPING.get(winner.lane),
        )

    if strongly_count > 1:
        return LaneNarrowingResult(
            eligible_lanes=tuple(lanes),
            selected_lane=None,
            selection_mode="abstain",
            lane_narrowing_used_intent=False,
            intent_effect="none",
            abstain_reason="lane_ambiguity",
            mapped_intent=None,
            mapped_policy_family=None,
        )

    plausible_lanes = [le for le in lanes if le.state == "plausible"]
    if plausible_lanes:
        return LaneNarrowingResult(
            eligible_lanes=tuple(lanes),
            selected_lane=None,
            selection_mode="residual_fallthrough",
            lane_narrowing_used_intent=False,
            intent_effect="none",
            abstain_reason=None,
            mapped_intent=None,
            mapped_policy_family=None,
        )

    return LaneNarrowingResult(
        eligible_lanes=tuple(lanes),
        selected_lane=None,
        selection_mode="abstain",
        lane_narrowing_used_intent=False,
        intent_effect="none",
        abstain_reason="no_lane_eligible",
        mapped_intent=None,
        mapped_policy_family=None,
    )


def _classify_query_policy_family(
    text: str,
    *,
    query_shape_tags: list[str],
    runtime_context: QueryRuntimeContext | None,
    initial_intent: str | None = None,
) -> str:
    if "resume_state" in query_shape_tags:
        return "resume_work"
    if runtime_context is not None and runtime_context.turn_kind == "resumed_session" and initial_intent == "work_resumption":
        return "resume_work"
    return "recall_fact"


def _build_ambiguity_options(
    policy_family: str,
    *,
    text: str,
    policy_evidence: dict[str, object],
    family_inference: dict[str, object],
    runtime_context: QueryRuntimeContext | None,
    query_shape_tags: list[str],
) -> tuple[PolicySelectedContext, list[dict[str, object]]]:
    if policy_family == "noise":
        return PolicySelectedContext(
            query_policy_family="noise",
            allowed_query_intents=frozenset(),
        ), []

    if policy_family == "latest_status":
        if _work_state_evidence_gate_passes(policy_evidence):
            return _build_latest_vs_resume_pair(
                policy_evidence=policy_evidence,
                runtime_context=runtime_context,
                query_shape_tags=query_shape_tags,
            )
        return PolicySelectedContext(
            query_policy_family="latest_status",
            allowed_query_intents=LATEST_STATUS_COLLAPSED_INTENTS,
        ), []

    if policy_family == "resume_work":
        return PolicySelectedContext(
            query_policy_family="resume_work",
            allowed_query_intents=QUERY_POLICY_FAMILY_ALLOWED_INTENTS["resume_work"],
        ), []

    # recall_fact — default
    return PolicySelectedContext(
        query_policy_family="recall_fact",
        allowed_query_intents=QUERY_POLICY_FAMILY_ALLOWED_INTENTS["recall_fact"],
    ), []


def _build_latest_vs_resume_pair(
    *,
    policy_evidence: dict[str, object],
    runtime_context: QueryRuntimeContext | None,
    query_shape_tags: list[str],
) -> tuple[PolicySelectedContext, list[dict[str, object]]]:
    resume_work_score = 0
    if runtime_context is not None and runtime_context.turn_kind == "resumed_session":
        resume_work_score += 12
    if "resume_state" in query_shape_tags:
        resume_work_score += 18
    resume_work_score += min(int(policy_evidence["task_checkpoint_best_work_usefulness"]), 40)
    resume_work_score += min(int(policy_evidence["source_evidence_best_work_usefulness"]), 16)

    latest_status_score = 0
    latest_status_score += 18  # latest_status wording is always present when this pair is eligible
    if "history_lookup" in query_shape_tags:
        latest_status_score += 14
    if bool(policy_evidence["cross_thread_continuity_survives"]):
        latest_status_score += 12
    latest_status_score += min(int(policy_evidence["structured_best_support"]), 24)

    # Determine option A
    if resume_work_score > latest_status_score:
        option_a_family = "resume_work"
    elif resume_work_score == latest_status_score:
        option_a_family = "resume_work" if (runtime_context is not None and runtime_context.turn_kind == "resumed_session") else "latest_status"
    else:
        option_a_family = "latest_status"
    option_b_family = "latest_status" if option_a_family == "resume_work" else "resume_work"

    options = [
        {
            "option_id": "A",
            "query_policy_family": option_a_family,
            "allowed_query_intents": list({"work_resumption"} if option_a_family == "resume_work" else {"recall"}),
            "score": resume_work_score if option_a_family == "resume_work" else latest_status_score,
        },
        {
            "option_id": "B",
            "query_policy_family": option_b_family,
            "allowed_query_intents": list({"work_resumption"} if option_b_family == "resume_work" else {"recall"}),
            "score": resume_work_score if option_b_family == "resume_work" else latest_status_score,
        },
    ]

    # Phase 3: always use option A (deterministic). Phase 4 will add resolver here.
    selected_family = option_a_family
    allowed_intents = frozenset({"work_resumption"}) if selected_family == "resume_work" else frozenset({"recall"})

    return PolicySelectedContext(
        query_policy_family=selected_family,
        allowed_query_intents=allowed_intents,
        option_a_family=option_a_family,
        option_b_family=option_b_family,
        deterministic_option="A",
        ambiguity_pair_type="latest_status_vs_resume_work",
    ), options



def _maybe_invoke_resolver(
    *,
    policy_ctx: PolicySelectedContext,
    policy_options: list[dict[str, object]],
    anchor_prefiltered_candidates: list[QueryResultItem],
    query_text: str,
    runtime_context: QueryRuntimeContext | None,
    resolver_config: dict[str, object] | None,
) -> PolicySelectedContext:
    if resolver_config is None:
        return policy_ctx
    if not resolver_config.get("resolver_enabled", True):
        return policy_ctx
    if policy_ctx.ambiguity_pair_type is None:
        return policy_ctx
    if len(policy_options) != 2:
        return policy_ctx

    # Check score delta against ambiguity margin
    score_a = int(policy_options[0].get("score", 0))
    score_b = int(policy_options[1].get("score", 0))
    delta = abs(score_a - score_b)
    margin = AMBIGUITY_MARGIN_LATEST_VS_RESUME if policy_ctx.ambiguity_pair_type == "latest_status_vs_resume_work" else AMBIGUITY_MARGIN_CONSTRAINTS_VS_RECALL
    if delta > margin:
        return policy_ctx

    from semantic.agent_conversation_memory_resolver import (
        build_resolver_packet,
        resolve_query_ambiguity,
    )

    provider = resolver_config.get("provider")
    if provider is None:
        return policy_ctx

    packet = build_resolver_packet(
        query_text=query_text,
        turn_kind=runtime_context.turn_kind if runtime_context else None,
        ambiguity_pair_type=policy_ctx.ambiguity_pair_type,
        option_a=policy_options[0],
        option_b=policy_options[1],
        candidates=[
            {
                "result_id": getattr(item, "memory_object_id", None) or getattr(item, "source_item_id", None) or "",
                "layer": _result_layer(item),
                "memory_type": item.type if item.result_kind == "memory_hit" else "source_hit",
                "support_score": _policy_candidate_support_estimate(item, _result_layer(item)),
                "summary": str((item.payload or {}).get("summary", item.excerpt or ""))[:200],
            }
            for item in anchor_prefiltered_candidates[:10]
        ],
    )

    timeout_ms = int(resolver_config.get("resolver_timeout_ms", 800))
    prompt_variant = str(resolver_config.get("prompt_variant", "qar_v1_compact_contract"))

    result = resolve_query_ambiguity(
        provider=provider,
        model=None,
        prompt_variant=prompt_variant,
        resolver_packet=packet,
        timeout_ms=timeout_ms,
    )

    # Apply resolver result
    if result.is_valid_selection and result.selected_option_id in {"A", "B"}:
        selected_idx = 0 if result.selected_option_id == "A" else 1
        selected_option = policy_options[selected_idx]
        selected_family = str(selected_option.get("query_policy_family", policy_ctx.query_policy_family))
        allowed = QUERY_POLICY_FAMILY_ALLOWED_INTENTS.get(selected_family)
        if allowed is None:
            allowed = policy_ctx.allowed_query_intents
        return PolicySelectedContext(
            query_policy_family=selected_family,
            allowed_query_intents=allowed,
            resolver_invoked=True,
            resolver_action=result.action,
            resolver_confidence=result.confidence,
            resolver_reason_codes=result.reason_codes,
            option_a_family=policy_ctx.option_a_family,
            option_b_family=policy_ctx.option_b_family,
            deterministic_option=policy_ctx.deterministic_option,
            ambiguity_pair_type=policy_ctx.ambiguity_pair_type,
        )

    # Fallback: keep deterministic option A
    return PolicySelectedContext(
        query_policy_family=policy_ctx.query_policy_family,
        allowed_query_intents=policy_ctx.allowed_query_intents,
        resolver_invoked=True,
        resolver_action="FALLBACK",
        resolver_confidence=result.confidence,
        resolver_reason_codes=result.reason_codes,
        option_a_family=policy_ctx.option_a_family,
        option_b_family=policy_ctx.option_b_family,
        deterministic_option=policy_ctx.deterministic_option,
        ambiguity_pair_type=policy_ctx.ambiguity_pair_type,
    )


def _apply_policy_intent_restriction(
    family_inference: dict[str, object],
    policy_ctx: PolicySelectedContext,
) -> str:
    selected = str(family_inference["selected_family"])
    allowed = policy_ctx.allowed_query_intents
    if allowed is None:
        return selected
    if selected in allowed:
        return selected
    # Override to the highest-scoring allowed intent
    family_scores = family_inference.get("family_scores")
    best_intent = None
    best_score = -1
    for intent in allowed:
        if isinstance(family_scores, dict):
            score_data = family_scores.get(intent)
            score = int(score_data.get("total", 0)) if isinstance(score_data, dict) else 0
        else:
            score = 0
        if score > best_score:
            best_score = score
            best_intent = intent
    return best_intent if best_intent else (next(iter(allowed)) if allowed else selected)
