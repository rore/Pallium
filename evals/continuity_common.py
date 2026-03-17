from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any, Iterable

CONTINUITY_FAILURE_FAMILIES = (
    "retrieval_recall_failure",
    "routing_layer_choice_failure",
    "result_packaging_evidence_failure",
    "compact_task_state_failure",
    "injectability_packaging_failure",
    "injection_decision_failure",
    "low_value_promotion_failure",
    "thread_rebuild_churn_failure",
    "thin_agent_boundary_failure",
    "paraphrase_or_indirect_query_failure",
    "no_value_overreach_failure",
    "stale_memory_failure",
    "wrong_memory_selection_failure",
    "privacy_leak_failure",
    "temporal_reasoning_failure",
    "update_conflict_handling_failure",
    "unsupported_memory_overreach",
)

HIGHER_LEVEL_LAYERS = {"pattern_memory", "continuity_memory", "task_checkpoint"}
PARAPHRASE_OR_INDIRECT_QUERY_LABELS = {"paraphrase", "indirect", "noisy_indirect"}
QUERY_FAMILY_VOCABULARY = (
    "answer_continuity",
    "broad_recurring_recall",
    "evidence_trace",
    "investigative_conclusion",
    "new_thread_continuation",
    "precise_fact",
    "resumed_session_continuation",
    "same_thread_no_value_continuation",
    "work_resumption",
)

FAILURE_FAMILY_TO_BOTTLENECK = {
    "retrieval_recall_failure": "retrieval_recall",
    "routing_layer_choice_failure": "routing",
    "paraphrase_or_indirect_query_failure": "paraphrase_routing",
    "result_packaging_evidence_failure": "evidence_packaging",
    "compact_task_state_failure": "task_state_packaging",
    "injectability_packaging_failure": "packaging",
    "thin_agent_boundary_failure": "packaging",
    "injection_decision_failure": "injection_decision",
    "low_value_promotion_failure": "ingest_noise_churn",
    "thread_rebuild_churn_failure": "ingest_noise_churn",
    "temporal_reasoning_failure": "temporal_reasoning",
    "update_conflict_handling_failure": "update_conflict_handling",
    "unsupported_memory_overreach": "unsupported_memory",
}

BOTTLENECK_IMPLICATIONS = {
    "retrieval_recall": "The current suite points to retrieval recall as the next tuning target before broader retrieval expansion.",
    "routing": "The current suite points to routing and layer choice as the next tuning target.",
    "paraphrase_routing": "The current suite points to paraphrase and indirect-query routing robustness as the next tuning target.",
    "evidence_packaging": "The current suite points to result and evidence packaging as the next tuning target.",
    "task_state_packaging": "The current suite points to compact task-state packaging as the next tuning target.",
    "packaging": "The current suite points to injectability packaging and thin-agent-ready output as the next tuning target.",
    "injection_decision": "The current suite points to injection-decision quality as the next tuning target.",
    "ingest_noise_churn": "The current suite points to ingest-time noise suppression and rebuild-churn control as the next tuning target.",
    "temporal_reasoning": "The current suite points to temporal reasoning under carried memory as the next tuning target.",
    "update_conflict_handling": "The current suite points to stale-versus-updated memory resolution as the next tuning target.",
    "unsupported_memory": "The current suite points to abstention and unsupported-memory boundaries as the next tuning target.",
}


def result_layer(item: dict[str, Any] | None) -> str:
    if item is None:
        return "none"
    if item.get("result_kind") == "source_hit":
        return "source_evidence"
    if item.get("type") == "pattern_memory":
        return "pattern_memory"
    if item.get("type") == "continuity_memory":
        return "continuity_memory"
    if item.get("type") == "task_checkpoint":
        return "task_checkpoint"
    return "lower_level_memory"


def failure_family_counts(rows: Iterable[dict[str, Any]], key: str = "failure_families") -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        counts.update(row.get(key, []))
    return {name: int(counts.get(name, 0)) for name in CONTINUITY_FAILURE_FAMILIES}


def query_family_from_intent(
    intent: str | None,
    *,
    runtime_context: dict[str, Any] | None = None,
    should_memory_help: bool | None = None,
) -> str | None:
    if intent is None:
        return None
    runtime_context = runtime_context or {}
    turn_kind = runtime_context.get("turn_kind")
    session_has_sufficient_local_context = runtime_context.get("session_has_sufficient_local_context")
    if turn_kind == "same_thread_continuation" and session_has_sufficient_local_context is True and should_memory_help is False:
        return "same_thread_no_value_continuation"
    if intent == "answer_continuity":
        if turn_kind == "resumed_session":
            return "resumed_session_continuation"
        if turn_kind in {"new_thread", "new_session"}:
            return "new_thread_continuation"
        return "answer_continuity"
    if intent == "broad_recall":
        return "broad_recurring_recall"
    if intent == "investigative_conclusion":
        return "investigative_conclusion"
    if intent == "work_resumption":
        if turn_kind == "resumed_session":
            return "resumed_session_continuation"
        if turn_kind in {"new_thread", "new_session"}:
            return "new_thread_continuation"
        return "work_resumption"
    return intent


def block_type_for_result(item: dict[str, Any] | None) -> str | None:
    if not item:
        return None
    if item.get("result_kind") == "source_hit":
        return "source_evidence"
    return item.get("type")


def block_type_for_injectable_block(block: dict[str, Any]) -> str | None:
    if block.get("block_type") == "source_evidence":
        return "source_evidence"
    return block.get("memory_type")


def compare_query_contract_payloads(query_payload: dict[str, Any], debug_payload: dict[str, Any]) -> dict[str, Any]:
    normalized_query_blocks = [
        _normalize_injectable_block_for_contract(block)
        for block in list(query_payload.get("injectable_blocks", []) or [])
    ]
    normalized_debug_blocks = [
        _normalize_injectable_block_for_contract(block)
        for block in list(debug_payload.get("injectable_blocks", []) or [])
    ]

    mismatch_fields: list[str] = []
    should_inject_match = bool(query_payload.get("should_inject")) == bool(debug_payload.get("should_inject"))
    if not should_inject_match:
        mismatch_fields.append("should_inject")

    decision_reason_match = str(query_payload.get("decision_reason") or "") == str(debug_payload.get("decision_reason") or "")
    if not decision_reason_match:
        mismatch_fields.append("decision_reason")

    mismatch_fields.extend(_injectable_block_mismatch_fields(normalized_query_blocks, normalized_debug_blocks))

    return {
        "consistent": not mismatch_fields,
        "should_inject_match": should_inject_match,
        "decision_reason_match": decision_reason_match,
        "injectable_blocks_match": normalized_query_blocks == normalized_debug_blocks,
        "mismatch_fields": mismatch_fields,
        "query_injectable_blocks": normalized_query_blocks,
        "debug_injectable_blocks": normalized_debug_blocks,
    }


def query_contract_payloads_consistent(query_payload: dict[str, Any], debug_payload: dict[str, Any]) -> bool:
    return bool(compare_query_contract_payloads(query_payload, debug_payload)["consistent"])


def evaluate_query_contract(
    *,
    query_payload: dict[str, Any],
    debug_payload: dict[str, Any],
    expected_should_inject: bool,
    expected_decision_reason: str | None = None,
    acceptable_decision_reasons: list[str] | None = None,
    expected_primary_block_types: list[str] | None = None,
    acceptable_fallback_block_types: list[str] | None = None,
    forbidden_block_types: list[str] | None = None,
    acceptable_injected_block_count: dict[str, int] | int | None = None,
    expected_cap_behavior: str | None = None,
) -> dict[str, Any]:
    consistency = compare_query_contract_payloads(query_payload, debug_payload)
    injection_contract = score_injection_contract(
        query_payload,
        expected_should_inject=expected_should_inject,
        expected_decision_reason=expected_decision_reason,
        acceptable_decision_reasons=acceptable_decision_reasons,
        expected_primary_block_types=expected_primary_block_types,
        acceptable_fallback_block_types=acceptable_fallback_block_types,
        forbidden_block_types=forbidden_block_types,
        acceptable_injected_block_count=acceptable_injected_block_count,
        expected_cap_behavior=expected_cap_behavior,
    )
    return {
        'query_contract_consistent': bool(consistency['consistent']),
        'query_contract_mismatch_fields': list(consistency['mismatch_fields']),
        'should_inject': bool(query_payload.get('should_inject')),
        'decision_reason': query_payload.get('decision_reason'),
        'injectable_blocks': list(query_payload.get('injectable_blocks', [])),
        'injection_contract': injection_contract,
    }


def _injectable_block_mismatch_fields(
    query_blocks: list[dict[str, Any]],
    debug_blocks: list[dict[str, Any]],
) -> list[str]:
    mismatch_fields: list[str] = []
    if len(query_blocks) != len(debug_blocks):
        mismatch_fields.append("injectable_blocks.length")

    for index, (query_block, debug_block) in enumerate(zip(query_blocks, debug_blocks)):
        for field in ("result_id", "block_type", "memory_type", "title", "text", "evidence"):
            if query_block.get(field) != debug_block.get(field):
                mismatch_fields.append(f"injectable_blocks[{index}].{field}")
    return mismatch_fields


def _normalize_injectable_block_for_contract(block: dict[str, Any]) -> dict[str, Any]:
    return {
        "result_id": _normalize_contract_scalar(block.get("result_id")),
        "block_type": _normalize_contract_scalar(block.get("block_type")),
        "memory_type": _normalize_contract_scalar(block.get("memory_type")),
        "title": str(block.get("title") or ""),
        "text": str(block.get("text") or ""),
        "evidence": [
            _normalize_evidence_reference_for_contract(item)
            for item in list(block.get("evidence", []) or [])
        ],
    }


def _normalize_evidence_reference_for_contract(item: dict[str, Any]) -> dict[str, Any]:
    visibility_context = item.get("visibility_context") if isinstance(item, dict) else None
    return {
        "source_item_id": _normalize_contract_scalar(item.get("source_item_id") if isinstance(item, dict) else None),
        "source_type": _normalize_contract_scalar(item.get("source_type") if isinstance(item, dict) else None),
        "source_id": _normalize_contract_scalar(item.get("source_id") if isinstance(item, dict) else None),
        "occurred_at": _normalize_contract_scalar(item.get("occurred_at") if isinstance(item, dict) else None),
        "actor_ref": _normalize_contract_scalar(item.get("actor_ref") if isinstance(item, dict) else None),
        "role": _normalize_contract_scalar(item.get("role") if isinstance(item, dict) else None),
        "container_ref": _normalize_contract_scalar(item.get("container_ref") if isinstance(item, dict) else None),
        "thread_ref": _normalize_contract_scalar(item.get("thread_ref") if isinstance(item, dict) else None),
        "session_ref": _normalize_contract_scalar(item.get("session_ref") if isinstance(item, dict) else None),
        "source_ref": _normalize_contract_scalar(item.get("source_ref") if isinstance(item, dict) else None),
        "artifact_kind": _normalize_contract_scalar(item.get("artifact_kind") if isinstance(item, dict) else None),
        "visibility_context": _normalize_visibility_context_for_contract(visibility_context),
    }


def _normalize_visibility_context_for_contract(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        "kind": _normalize_contract_scalar(value.get("kind")),
        "id": _normalize_contract_scalar(value.get("id")),
    }


def _normalize_contract_scalar(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def score_injection_contract(
    query_payload: dict[str, Any],
    *,
    expected_should_inject: bool,
    expected_decision_reason: str | None = None,
    acceptable_decision_reasons: list[str] | None = None,
    expected_primary_block_types: list[str] | None = None,
    acceptable_fallback_block_types: list[str] | None = None,
    forbidden_block_types: list[str] | None = None,
    acceptable_injected_block_count: dict[str, int] | int | None = None,
    expected_cap_behavior: str | None = None,
) -> dict[str, Any]:
    acceptable_decision_reasons = list(acceptable_decision_reasons or [])
    expected_primary_block_types = list(expected_primary_block_types or [])
    acceptable_fallback_block_types = list(acceptable_fallback_block_types or [])
    forbidden_block_types = list(forbidden_block_types or [])
    injected_blocks = list(query_payload.get("injectable_blocks", []))
    injected_block_types = [
        block_type
        for block_type in (block_type_for_injectable_block(block) for block in injected_blocks)
        if block_type
    ]
    should_inject_actual = bool(query_payload.get("should_inject"))
    decision_reason_actual = str(query_payload.get("decision_reason") or "")
    should_inject_match = should_inject_actual is expected_should_inject

    accepted_reasons = [expected_decision_reason] if expected_decision_reason else []
    accepted_reasons.extend(reason for reason in acceptable_decision_reasons if reason not in accepted_reasons)
    decision_reason_match = True if not accepted_reasons else decision_reason_actual in accepted_reasons

    count_expectation = _normalize_count_expectation(acceptable_injected_block_count)
    injected_block_count = len(injected_blocks)
    block_count_ok = (
        count_expectation is None
        or (count_expectation["min"] <= injected_block_count <= count_expectation["max"])
    )

    forbidden_block_types_hit = [block_type for block_type in injected_block_types if block_type in forbidden_block_types]
    primary_block_types_hit = [block_type for block_type in injected_block_types if block_type in expected_primary_block_types]
    fallback_block_types_hit = [block_type for block_type in injected_block_types if block_type in acceptable_fallback_block_types]
    block_types_match = True
    if expected_should_inject:
        expected_allowed = expected_primary_block_types or acceptable_fallback_block_types
        if expected_allowed:
            block_types_match = bool(primary_block_types_hit or fallback_block_types_hit)
        else:
            block_types_match = bool(injected_blocks)
    else:
        block_types_match = not injected_blocks

    routing = ((query_payload.get("trace") or {}).get("routing") or {})
    injection_summary = routing.get("injection_decision") or {}
    eligible_result_ids = list(injection_summary.get("eligible_result_ids", []))
    returned_block_ids = list(injection_summary.get("returned_block_ids", []))
    dropped_by_cap_result_ids = list(injection_summary.get("dropped_by_cap_result_ids", []))
    cap_value = int(injection_summary.get("cap", 3) or 3)
    cap_obeyed = injected_block_count <= cap_value
    cap_behavior_ok = True
    if expected_cap_behavior == "drop_extra_candidates":
        cap_behavior_ok = bool(dropped_by_cap_result_ids)
    elif expected_cap_behavior == "within_cap":
        cap_behavior_ok = not dropped_by_cap_result_ids

    compatible_result_ids = _compatible_result_ids(
        query_payload.get("results", []),
        expected_primary_block_types=expected_primary_block_types,
        acceptable_fallback_block_types=acceptable_fallback_block_types,
    )
    semantic_compensation_needed, semantic_compensation_reason = _semantic_compensation_needed(
        expected_should_inject=expected_should_inject,
        should_inject_match=should_inject_match,
        decision_reason_match=decision_reason_match,
        block_types_match=block_types_match,
        forbidden_block_types_hit=forbidden_block_types_hit,
        block_count_ok=block_count_ok,
        cap_behavior_ok=cap_behavior_ok,
        compatible_result_ids=compatible_result_ids,
        injected_blocks=injected_blocks,
        decision_reason_actual=decision_reason_actual,
    )

    contract_success = all(
        [
            should_inject_match,
            decision_reason_match,
            block_types_match,
            block_count_ok,
            cap_obeyed,
            cap_behavior_ok,
            not forbidden_block_types_hit,
            not semantic_compensation_needed,
        ]
    )

    return {
        "contract_success": contract_success,
        "should_inject_expected": expected_should_inject,
        "should_inject_actual": should_inject_actual,
        "should_inject_match": should_inject_match,
        "decision_reason_expected": expected_decision_reason,
        "acceptable_decision_reasons": accepted_reasons,
        "decision_reason_actual": decision_reason_actual,
        "decision_reason_match": decision_reason_match,
        "expected_primary_block_types": expected_primary_block_types,
        "acceptable_fallback_block_types": acceptable_fallback_block_types,
        "forbidden_block_types": forbidden_block_types,
        "injected_block_types": injected_block_types,
        "primary_block_types_hit": primary_block_types_hit,
        "fallback_block_types_hit": fallback_block_types_hit,
        "forbidden_block_types_hit": forbidden_block_types_hit,
        "block_types_match": block_types_match,
        "injected_block_count": injected_block_count,
        "acceptable_injected_block_count": count_expectation,
        "block_count_ok": block_count_ok,
        "cap": cap_value,
        "cap_obeyed": cap_obeyed,
        "expected_cap_behavior": expected_cap_behavior,
        "cap_behavior_ok": cap_behavior_ok,
        "eligible_result_ids": eligible_result_ids,
        "returned_block_ids": returned_block_ids,
        "dropped_by_cap_result_ids": dropped_by_cap_result_ids,
        "compatible_result_ids": compatible_result_ids,
        "semantic_compensation_needed": semantic_compensation_needed,
        "semantic_compensation_reason": semantic_compensation_reason,
    }



def default_injection_expectations(
    *,
    should_memory_help: bool,
    runtime_context: dict[str, Any] | None,
    expected_primary_layer: str | None,
    expected_memory_types: list[str] | None,
    acceptable_fallback_layers: list[str] | None,
    forbidden_layers: list[str] | None,
    expected_should_inject: bool | None = None,
    expected_decision_reason: str | None = None,
    acceptable_decision_reasons: list[str] | None = None,
    expected_primary_block_types: list[str] | None = None,
    acceptable_fallback_block_types: list[str] | None = None,
    forbidden_block_types: list[str] | None = None,
    acceptable_injected_block_count: dict[str, int] | int | None = None,
    expected_cap_behavior: str | None = None,
) -> dict[str, Any]:
    runtime_context = runtime_context or {}
    resolved_should_inject = expected_should_inject
    if resolved_should_inject is None:
        resolved_should_inject = should_memory_help
        if (
            runtime_context.get("turn_kind") == "same_thread_continuation"
            and runtime_context.get("session_has_sufficient_local_context") is True
        ):
            resolved_should_inject = False
    resolved_decision_reason = expected_decision_reason
    if resolved_decision_reason is None:
        if resolved_should_inject:
            resolved_decision_reason = "carry_forward_available"
        elif (
            runtime_context.get("turn_kind") == "same_thread_continuation"
            and runtime_context.get("session_has_sufficient_local_context") is True
        ):
            resolved_decision_reason = "same_thread_context_sufficient"
        else:
            resolved_decision_reason = "no_relevant_memory"
    resolved_primary_block_types = list(expected_primary_block_types or [])
    if not resolved_primary_block_types and resolved_should_inject:
        resolved_primary_block_types = default_primary_block_types(
            expected_primary_layer=expected_primary_layer,
            expected_memory_types=expected_memory_types,
        )
    resolved_fallback_block_types = list(acceptable_fallback_block_types or [])
    if not resolved_fallback_block_types:
        resolved_fallback_block_types = fallback_block_types_from_layers(acceptable_fallback_layers or [])
    resolved_forbidden_block_types = list(forbidden_block_types or [])
    if not resolved_forbidden_block_types:
        resolved_forbidden_block_types = fallback_block_types_from_layers(forbidden_layers or [])
    resolved_block_count = acceptable_injected_block_count
    if resolved_block_count is None:
        resolved_block_count = {"min": 1, "max": 3} if resolved_should_inject else 0
    return {
        "expected_should_inject": bool(resolved_should_inject),
        "expected_decision_reason": resolved_decision_reason,
        "acceptable_decision_reasons": list(acceptable_decision_reasons or []),
        "expected_primary_block_types": resolved_primary_block_types,
        "acceptable_fallback_block_types": resolved_fallback_block_types,
        "forbidden_block_types": resolved_forbidden_block_types,
        "acceptable_injected_block_count": resolved_block_count,
        "expected_cap_behavior": expected_cap_behavior,
    }


def default_primary_block_types(
    *,
    expected_primary_layer: str | None,
    expected_memory_types: list[str] | None,
) -> list[str]:
    expected_memory_types = list(expected_memory_types or [])
    if expected_primary_layer == "source_evidence":
        return ["source_evidence"]
    if expected_primary_layer in HIGHER_LEVEL_LAYERS:
        return [expected_primary_layer]
    if expected_primary_layer == "lower_level_memory":
        return [memory_type for memory_type in expected_memory_types if memory_type not in HIGHER_LEVEL_LAYERS]
    return [expected_primary_layer] if expected_primary_layer and expected_primary_layer != "none" else []


def fallback_block_types_from_layers(layers: list[str]) -> list[str]:
    block_types: list[str] = []
    for layer in layers:
        if layer == "source_evidence":
            block_types.append("source_evidence")
        elif layer in HIGHER_LEVEL_LAYERS or layer in {"decision", "investigation_outcome", "thread_summary", "discussion_summary"}:
            block_types.append(layer)
    return block_types

def _normalize_count_expectation(expectation: dict[str, int] | int | None) -> dict[str, int] | None:
    if expectation is None:
        return None
    if isinstance(expectation, int):
        return {"min": expectation, "max": expectation}
    minimum = int(expectation.get("min", 0))
    maximum = int(expectation.get("max", minimum))
    return {"min": minimum, "max": maximum}


def _compatible_result_ids(
    results: list[dict[str, Any]],
    *,
    expected_primary_block_types: list[str],
    acceptable_fallback_block_types: list[str],
) -> list[str]:
    supported_block_types = set(expected_primary_block_types) | set(acceptable_fallback_block_types)
    if not supported_block_types:
        return []
    compatible: list[str] = []
    for item in results:
        result_id = item.get("result_id")
        block_type = block_type_for_result(item)
        if result_id and block_type in supported_block_types and result_id not in compatible:
            compatible.append(str(result_id))
    return compatible


def _semantic_compensation_needed(
    *,
    expected_should_inject: bool,
    should_inject_match: bool,
    decision_reason_match: bool,
    block_types_match: bool,
    forbidden_block_types_hit: list[str],
    block_count_ok: bool,
    cap_behavior_ok: bool,
    compatible_result_ids: list[str],
    injected_blocks: list[dict[str, Any]],
    decision_reason_actual: str,
) -> tuple[bool, str | None]:
    if expected_should_inject:
        if not should_inject_match and compatible_result_ids:
            return True, "compatible_memory_existed_but_pallium_suppressed_injection"
        if should_inject_match and not injected_blocks and compatible_result_ids:
            return True, "compatible_memory_existed_but_no_injectable_blocks_were_returned"
        if not block_types_match and compatible_result_ids:
            return True, "compatible_memory_existed_but_wrong_block_types_were_injected"
    else:
        if injected_blocks:
            return True, "downstream_would_need_to_drop_unwanted_injected_blocks"
        if not should_inject_match and decision_reason_actual:
            return True, "downstream_would_need_to_ignore_unwanted_injection_decision"
    if forbidden_block_types_hit:
        return True, "downstream_would_need_to_filter_forbidden_block_types"
    if not block_count_ok or not cap_behavior_ok:
        return True, "downstream_would_need_to_clean_up_packaging_or_cap_behavior"
    if not decision_reason_match:
        return True, "downstream_would_need_to_compensate_for_wrong_decision_reason"
    return False, None


def dominant_tuning_bottleneck(counts: dict[str, int]) -> str | list[str] | None:
    bottleneck_counts: Counter[str] = Counter()
    for family, count in counts.items():
        bottleneck = FAILURE_FAMILY_TO_BOTTLENECK.get(family)
        if bottleneck and count > 0:
            bottleneck_counts[bottleneck] += count
    if not bottleneck_counts:
        return None
    highest = max(bottleneck_counts.values())
    winners = sorted(name for name, count in bottleneck_counts.items() if count == highest)
    if len(winners) == 1:
        return winners[0]
    return winners


def dominant_bottleneck_implication(bottleneck: str | list[str] | None) -> str | None:
    if bottleneck is None:
        return None
    if isinstance(bottleneck, list):
        return "Multiple tuning bottlenecks tied in the current suite, so the next change should stay benchmark-guided rather than assuming one dominant gap."
    return BOTTLENECK_IMPLICATIONS.get(bottleneck)
