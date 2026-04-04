from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from fastapi.testclient import TestClient

from app.config import AppConfig
from app.dependencies import build_llm_provider
from app.main import create_app
from evals.benchmark_architecture import annotate_result, build_suite_summary
from evals.continuity_common import (
    CONTINUITY_FAILURE_FAMILIES,
    PARAPHRASE_OR_INDIRECT_QUERY_LABELS,
    default_injection_expectations,
    dominant_bottleneck_implication,
    dominant_tuning_bottleneck,
    evaluate_query_contract,
    failure_family_counts,
    query_family_from_intent,
    result_layer,
)
from semantic.agent_conversation_memory_routing import is_query_topic_signal_empty
from providers.llm.base import LLMProvider


DEFAULT_SCENARIO_FILE = Path("evals/work_resumption/scenarios.json")
DEFAULT_OUTPUT_DIR = Path("evals/work_resumption/output")
CONTINUATION_SCHEMA = json.dumps(
    {
        "answer": "string",
        "task_orientation": "string",
        "reused_findings": ["string"],
        "blocker_state": "string",
        "preserved_progress": "string",
        "next_step": "string",
        "evidence_used": ["string"],
        "freshness_notes": "string",
    },
    indent=2,
)
DIMENSION_ORDER = (
    "task_orientation",
    "key_findings",
    "blocker_state",
    "preserved_progress",
    "next_step_guidance",
    "evidence",
    "freshness",
)
TASK_STATE_DIMENSIONS = {"blocker_state", "preserved_progress", "next_step_guidance", "freshness"}
LEGACY_DIMENSION_NAMES = {
    "task_orientation": "task_orientation",
    "prior_findings_reused": "key_findings",
    "key_findings": "key_findings",
    "blocker_state": "blocker_state",
    "preserved_progress": "preserved_progress",
    "next_step_guidance": "next_step_guidance",
    "evidence_preserved": "evidence",
    "evidence": "evidence",
    "freshness_preserved": "freshness",
    "freshness": "freshness",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the developer-work continuity benchmark.")
    parser.add_argument("--scenario-file", type=Path, default=DEFAULT_SCENARIO_FILE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-name", default=None)
    parser.add_argument("--consolidation-strategy", default=None)
    args = parser.parse_args()

    run_dir = run_work_resumption_benchmark(
        scenario_file=args.scenario_file,
        output_root=args.output_dir,
        config=AppConfig.from_env(),
        run_name=args.run_name,
        consolidation_strategy=args.consolidation_strategy,
    )
    print(run_dir)
    return 0


def run_work_resumption_benchmark(
    *,
    scenario_file: Path,
    output_root: Path,
    config: AppConfig,
    run_name: str | None = None,
    answer_provider: LLMProvider | None = None,
    consolidation_strategy: str | None = None,
) -> Path:
    scenarios = _load_scenarios(scenario_file)
    default_package = config.package_config(config.default_use_case)
    if answer_provider is None:
        if not default_package.llm_provider or not default_package.model:
            raise ValueError(f"Default use case '{config.default_use_case}' is missing LLM package config")
        provider = build_llm_provider(config, provider_name=default_package.llm_provider, model=default_package.model)
    else:
        provider = answer_provider

    effective_consolidation_strategy = consolidation_strategy
    if effective_consolidation_strategy is None:
        consolidation_policy = default_package.consolidation
        effective_consolidation_strategy = consolidation_policy.default_strategy if consolidation_policy is not None else None

    run_id = run_name or _build_run_id(config, effective_consolidation_strategy)
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    results_path = run_dir / "results.jsonl"

    results: list[dict[str, Any]] = []
    with results_path.open("w", encoding="utf-8") as results_file:
        for scenario in scenarios:
            result = annotate_result(
                _run_scenario(
                    scenario=scenario,
                    config=config,
                    answer_provider=provider,
                    consolidation_strategy=effective_consolidation_strategy,
                ),
                suite_id="work_resumption",
            )
            results.append(result)
            results_file.write(json.dumps(result) + "\n")

    summary = _build_summary(
        results=results,
        scenario_file=scenario_file,
        config=config,
        run_id=run_id,
        results_file=results_path.name,
        consolidation_strategy=effective_consolidation_strategy,
    )
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (run_dir / "report.md").write_text(_build_report(summary=summary, results=results), encoding="utf-8")
    return run_dir


def _run_scenario(
    *,
    scenario: dict[str, Any],
    config: AppConfig,
    answer_provider: LLMProvider,
    consolidation_strategy: str | None,
) -> dict[str, Any]:
    query_request = _scenario_query_request(scenario)
    with TemporaryDirectory() as temp_dir:
        database_url = f"sqlite:///{Path(temp_dir) / 'work-resumption.db'}"
        vector_index_config = replace(config.vector_index, index_path=str(Path(temp_dir) / "vector.index"))
        scenario_config = replace(
            config,
            sqlite_url=database_url,
            default_use_case="agent_conversation_memory",
            vector_index=vector_index_config,
        )
        with TestClient(create_app(scenario_config)) as client:
            for event in scenario.get("prior_events", []):
                response = client.post("/items", json=[_with_default_visibility(event)])
                response.raise_for_status()
            client.app.state.pallium_service.drain_processing_queue(worker_id="work-resumption-runner")

            consolidation_result = None
            if consolidation_strategy:
                consolidation_result = client.app.state.pallium_service.run_consolidation_pass(
                    use_case="agent_conversation_memory",
                    strategy_name=consolidation_strategy,
                )

            query_contract_response = client.post("/query", json=_with_default_visibility(query_request))
            query_contract_response.raise_for_status()
            query_contract_payload = query_contract_response.json()

            query_response = client.post("/query/debug", json=_with_default_visibility(query_request))
            query_response.raise_for_status()
            query_payload = query_response.json()
            engine = getattr(client.app.state.pallium_service._storage, "_engine", None)
            if engine is not None:
                engine.dispose()
    baseline_continuation = _generate_continuation(
        answer_provider=answer_provider,
        scenario_id=scenario["scenario_id"],
        target_question=scenario["target_question"],
        current_thread_context=scenario.get("current_thread_context", []),
        memory_backed_results=[],
        branch="baseline",
    )
    memory_backed_continuation = _generate_continuation(
        answer_provider=answer_provider,
        scenario_id=scenario["scenario_id"],
        target_question=scenario["target_question"],
        current_thread_context=scenario.get("current_thread_context", []),
        memory_backed_results=query_payload["results"],
        branch="memory_backed",
    )

    routing = ((query_payload.get("trace") or {}).get("routing") or {})
    routing_intent = routing.get("query_intent")
    query_family = routing.get("query_family") or query_family_from_intent(
        routing_intent,
        runtime_context=scenario.get("runtime_context"),
        should_memory_help=bool(scenario.get("should_memory_help")),
    )
    intent_match = routing_intent == scenario.get("expected_intent") if scenario.get("expected_intent") else True
    query_family_match = query_family == scenario.get("expected_query_family") if scenario.get("expected_query_family") else True

    memory_hits = [item for item in query_payload["results"] if item.get("result_kind") == "memory_hit"]
    source_hits = [item for item in query_payload["results"] if item.get("result_kind") == "source_hit"]
    returned_memory_types = sorted({item.get("type") for item in memory_hits if item.get("type")})
    carried_conclusion_types = _carried_conclusion_types(memory_hits)
    expected_memory_types = scenario.get("expected_memory_types", [])
    expected_memory_types_found = all(
        item in returned_memory_types or item in carried_conclusion_types
        for item in expected_memory_types
    )
    top_result = query_payload["results"][0] if query_payload["results"] else None
    top_layer = result_layer(top_result)
    available_layers = sorted({result_layer(item) for item in query_payload["results"]})
    expected_primary_layer = scenario.get("expected_primary_layer")
    expected_layer_in_results = (expected_primary_layer in available_layers) if expected_primary_layer else False
    raw_query_tokens = tuple(((query_payload.get("trace") or {}).get("query_tokens")) or [])
    query_topic_tokens_empty = is_query_topic_signal_empty(raw_query_tokens)
    acceptable_layers = list(scenario.get("acceptable_layers", []))
    top_layer_match = not acceptable_layers or top_layer in acceptable_layers
    primary_layer_match = expected_primary_layer is None or top_layer == expected_primary_layer
    forbidden_layers = list(scenario.get("forbidden_layers", []))
    forbidden_layers_hit = [layer for layer in forbidden_layers if layer == top_layer]

    query_contract = evaluate_query_contract(
        query_payload=query_contract_payload,
        debug_payload=query_payload,
        expected_should_inject=bool(scenario.get("expected_should_inject")),
        expected_decision_reason=scenario.get("expected_decision_reason"),
        acceptable_decision_reasons=scenario.get("acceptable_decision_reasons", []),
        expected_primary_block_types=list(scenario.get("expected_primary_block_types") or scenario.get("expected_primary_injected_block_types") or []),
        acceptable_fallback_block_types=scenario.get("acceptable_fallback_block_types", []),
        forbidden_block_types=scenario.get("forbidden_block_types", []),
        acceptable_injected_block_count=scenario.get("acceptable_injected_block_count"),
        expected_cap_behavior=scenario.get("expected_cap_behavior"),
    )

    baseline_rubric = _score_continuation(
        continuation=baseline_continuation,
        expected_dimensions=scenario.get("expected_dimensions", {}),
        must_preserve=scenario.get("must_preserve", []),
        forbidden_terms=scenario.get("forbidden_terms", []),
    )
    memory_rubric = _score_continuation(
        continuation=memory_backed_continuation,
        expected_dimensions=scenario.get("expected_dimensions", {}),
        must_preserve=scenario.get("must_preserve", []),
        forbidden_terms=scenario.get("forbidden_terms", []),
    )
    comparison = _compare_continuations(
        should_memory_help=bool(scenario.get("should_memory_help")),
        baseline_rubric=baseline_rubric,
        memory_rubric=memory_rubric,
    )

    retrieval_text = _retrieval_text(query_payload["results"])
    gap_breakdown = _dimension_gap_breakdown(
        scenario=scenario,
        memory_rubric=memory_rubric,
        retrieval_text=retrieval_text,
        routing_failed=(not intent_match) or (not top_layer_match) or bool(forbidden_layers_hit),
    )
    guard_matches = _guard_term_matches(
        guard_terms=scenario.get("guard_terms", {}),
        top_result=top_result,
        continuation=memory_backed_continuation,
    )
    failure_families = _classify_failure_families(
        scenario=scenario,
        comparison=comparison,
        memory_rubric=memory_rubric,
        expected_memory_types_found=expected_memory_types_found,
        intent_match=intent_match,
        query_family_match=query_family_match,
        top_layer_match=top_layer_match,
        forbidden_layers_hit=forbidden_layers_hit,
        gap_breakdown=gap_breakdown,
        guard_matches=guard_matches,
        injection_contract=query_contract["injection_contract"],
    )
    missing_dimensions_after_memory = _missing_dimensions(memory_rubric)
    forbidden_terms_found = sorted({term for matches in guard_matches.values() for term in matches})
    no_value_guard_success = (not bool(scenario.get("should_memory_help"))) and "no_value_overreach_failure" not in failure_families
    stale_guard_success = (
        "stale_state" not in scenario.get("must_not_introduce", [])
        or "stale_memory_failure" not in failure_families
    )
    wrong_memory_guard_success = (
        "wrong_thread_state" not in scenario.get("must_not_introduce", [])
        or "wrong_memory_selection_failure" not in failure_families
    )
    thin_agent_boundary_success = "thin_agent_boundary_failure" not in failure_families

    labels = {
        "scenario_family": scenario["scenario_family"],
        "query_family": scenario.get("expected_query_family"),
        "query_wording_label": scenario.get("query_wording_label"),
        "should_memory_help": bool(scenario.get("should_memory_help")),
        "expected_intent": scenario.get("expected_intent"),
        "expected_primary_layer": expected_primary_layer,
        "acceptable_fallback_layers": list(scenario.get("acceptable_fallback_layers", [])),
        "forbidden_layers": forbidden_layers,
        "expected_should_inject": bool(scenario.get("expected_should_inject")),
        "expected_decision_reason": scenario.get("expected_decision_reason"),
        "expected_primary_injected_block_types": list(scenario.get("expected_primary_block_types") or scenario.get("expected_primary_injected_block_types") or []),
        "acceptable_fallback_block_types": list(scenario.get("acceptable_fallback_block_types", [])),
        "forbidden_block_types": list(scenario.get("forbidden_block_types", [])),
        "must_preserve": list(scenario.get("must_preserve", [])),
        "must_not_introduce": list(scenario.get("must_not_introduce", [])),
    }

    return {
        "scenario_id": scenario["scenario_id"],
        "scenario_family": scenario["scenario_family"],
        "scenario_kind": scenario["scenario_family"],
        "description": scenario["description"],
        "labels": labels,
        "should_memory_help": bool(scenario.get("should_memory_help")),
        "expected_value": bool(scenario.get("should_memory_help")),
        "expected_non_value_reason": scenario.get("expected_non_value_reason"),
        "runtime_context": scenario.get("runtime_context"),
        "expected_query_family": scenario.get("expected_query_family"),
        "query_family": query_family,
        "query_family_match": query_family_match,
        "query_wording_label": scenario.get("query_wording_label"),
        "expected_intent": scenario.get("expected_intent"),
        "routing_intent": routing_intent,
        "intent_match": intent_match,
        "expected_primary_layer": expected_primary_layer,
        "expected_top_layer": expected_primary_layer,
        "acceptable_fallback_layers": list(scenario.get("acceptable_fallback_layers", [])),
        "acceptable_layers": acceptable_layers,
        "acceptable_top_layers": acceptable_layers,
        "forbidden_layers": forbidden_layers,
        "forbidden_layers_hit": forbidden_layers_hit,
        "top_layer": top_layer,
        "top_layer_match": top_layer_match,
        "primary_layer_match": primary_layer_match,
        "expected_memory_types": expected_memory_types,
        "expected_memory_types_found": expected_memory_types_found,
        "returned_memory_types": returned_memory_types,
        "memory_hit_count": len(memory_hits),
        "source_hit_count": len(source_hits),
        "memory_backed_retrieval": query_payload["results"],
        "query_trace": query_payload.get("trace"),
        "routing_preferred_layers": routing.get("preferred_layers", []),
        "thin_agent_query_response": query_contract_payload,
        "query_contract_consistent": query_contract["query_contract_consistent"],
        "query_contract_mismatch_fields": query_contract["query_contract_mismatch_fields"],
        "expected_should_inject": bool(scenario.get("expected_should_inject")),
        "expected_decision_reason": scenario.get("expected_decision_reason"),
        "should_inject": query_contract["should_inject"],
        "decision_reason": query_contract["decision_reason"],
        "injectable_blocks": query_contract["injectable_blocks"],
        "injection_contract": query_contract["injection_contract"],
        "baseline_continuation": baseline_continuation,
        "memory_backed_continuation": memory_backed_continuation,
        "rubric": {
            "baseline": baseline_rubric,
            "memory_backed": memory_rubric,
            "comparison": comparison,
        },
        "winner": comparison["winner"],
        "why": comparison["why"],
        "missing_dimensions_after_memory": missing_dimensions_after_memory,
        "dimension_gap_breakdown": gap_breakdown,
        "failure_families": failure_families,
        "gap_signals": failure_families,
        "guard_matches": guard_matches,
        "forbidden_terms_found": forbidden_terms_found,
        "non_value_guard_success": no_value_guard_success,
        "stale_guard_success": stale_guard_success,
        "wrong_memory_guard_success": wrong_memory_guard_success,
        "thin_agent_boundary_success": thin_agent_boundary_success,
        "consolidation_strategy": consolidation_strategy,
        "consolidation_run": _serialize_consolidation_result(consolidation_result),
        "expected_layer_in_results": expected_layer_in_results,
        "query_topic_tokens_empty": query_topic_tokens_empty,
    }
def _generate_continuation(
    *,
    answer_provider: LLMProvider,
    scenario_id: str,
    target_question: str,
    current_thread_context: list[dict[str, Any]],
    memory_backed_results: list[dict[str, Any]],
    branch: str,
) -> dict[str, Any]:
    system_prompt = (
        "You produce continuation guidance for an agent resuming work. "
        "Use only the supplied context. Return exactly one JSON object and no extra prose. "
        "Keep fields empty when the context does not support them."
    )
    user_prompt = (
        f"Scenario ID: {scenario_id}\n"
        f"Branch: {branch}\n"
        f"Target question: {target_question}\n\n"
        f"Current thread context:\n{_format_current_thread_context(current_thread_context)}\n\n"
        f"Retrieved prior memory and evidence:\n{_format_retrieval_results(memory_backed_results)}\n\n"
        "Return JSON with:\n"
        "- answer: concise continuation guidance for the agent\n"
        "- task_orientation: the current task or workstream to stay oriented on\n"
        "- reused_findings: short list of prior findings that matter now\n"
        "- blocker_state: blocker or failure state that should carry forward\n"
        "- preserved_progress: partial progress already completed and worth preserving\n"
        "- next_step: the best next step supported by the supplied context\n"
        "- evidence_used: short list of prior memory or source evidence actually used\n"
        "- freshness_notes: what current or freshest prior state matters now\n"
        "If the current-thread context is already sufficient, do not force older memory into the answer."
    )
    response = answer_provider.generate_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        schema_description=CONTINUATION_SCHEMA,
    )
    parsed = response.parsed_json
    reused_findings = parsed.get("reused_findings") or []
    evidence_used = parsed.get("evidence_used") or []
    if not isinstance(reused_findings, list):
        reused_findings = []
    if not isinstance(evidence_used, list):
        evidence_used = []
    return {
        "answer": _normalize_string(parsed.get("answer")),
        "task_orientation": _normalize_string(parsed.get("task_orientation")),
        "reused_findings": [_normalize_string(item) for item in reused_findings if _normalize_string(item)],
        "blocker_state": _normalize_string(parsed.get("blocker_state")),
        "preserved_progress": _normalize_string(parsed.get("preserved_progress")),
        "next_step": _normalize_string(parsed.get("next_step")),
        "evidence_used": [_normalize_string(item) for item in evidence_used if _normalize_string(item)],
        "freshness_notes": _normalize_string(parsed.get("freshness_notes")),
        "raw_text": response.raw_text,
    }

def _normalize_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _score_continuation(
    *,
    continuation: dict[str, Any],
    expected_dimensions: dict[str, list[str]],
    must_preserve: list[str],
    forbidden_terms: list[str],
) -> dict[str, Any]:
    dimensions: dict[str, Any] = {}
    normalized_must_preserve = set(must_preserve)
    for dimension in DIMENSION_ORDER:
        expected_signals = list(expected_dimensions.get(dimension, []))
        applicable = dimension in normalized_must_preserve or bool(expected_signals)
        haystack = _dimension_text(dimension, continuation)
        matches = [signal for signal in expected_signals if _signal_matches(signal, haystack)]
        missing = [signal for signal in expected_signals if signal not in matches]
        if not applicable:
            score = None
        elif expected_signals:
            score = _score_signal_coverage(matches, expected_signals)
        elif dimension == "evidence":
            score = 2 if continuation["evidence_used"] else 0
        elif dimension == "freshness":
            score = 2 if continuation["freshness_notes"] else 0
        else:
            score = 2 if haystack.strip() else 0
        dimensions[dimension] = {
            "applicable": applicable,
            "expected_signals": expected_signals,
            "matches": matches,
            "missing": missing,
            "score": score,
        }

    combined = _combined_continuation_text(continuation)
    overreach_terms = [term for term in forbidden_terms if term.lower() in combined]
    applicable_dimensions = [item for item in dimensions.values() if item["applicable"]]
    total = sum(int(item["score"] or 0) for item in applicable_dimensions)
    evidence_grounding = 2 if continuation["evidence_used"] else 0
    return {
        "dimensions": dimensions,
        "applicable_dimensions": len(applicable_dimensions),
        "fully_covered_dimensions": sum(1 for item in applicable_dimensions if int(item["score"] or 0) == 2),
        "partially_covered_dimensions": sum(1 for item in applicable_dimensions if int(item["score"] or 0) == 1),
        "total": total,
        "evidence_grounding": evidence_grounding,
        "overreach": bool(overreach_terms),
        "overreach_terms": overreach_terms,
    }


def _dimension_text(dimension: str, continuation: dict[str, Any]) -> str:
    if dimension == "task_orientation":
        return f"{continuation['answer']}\n{continuation['task_orientation']}"
    if dimension == "key_findings":
        return f"{continuation['answer']}\n{' '.join(continuation['reused_findings'])}"
    if dimension == "blocker_state":
        return f"{continuation['answer']}\n{continuation['blocker_state']}"
    if dimension == "preserved_progress":
        return f"{continuation['answer']}\n{continuation['preserved_progress']}"
    if dimension == "next_step_guidance":
        return f"{continuation['answer']}\n{continuation['next_step']}"
    if dimension == "evidence":
        return f"{continuation['answer']}\n{' '.join(continuation['evidence_used'])}"
    return f"{continuation['answer']}\n{continuation['freshness_notes']}\n{continuation['blocker_state']}\n{continuation['next_step']}"


def _carried_conclusion_types(memory_hits: list[dict[str, Any]]) -> set[str]:
    """Extract types carried as conclusions inside thread_summary/continuity_memory.

    Thread summaries carry decision and investigation_outcome conclusions in their
    payload.  A thread_summary containing a carried decision is a valid way to
    surface that decision — the eval should not penalize it for not returning the
    raw atomic type.
    """
    types: set[str] = set()
    for hit in memory_hits:
        payload = hit.get("payload") or {}
        for conclusion in payload.get("conclusions", []):
            if isinstance(conclusion, dict) and conclusion.get("type"):
                types.add(conclusion["type"])
        if payload.get("carry_forward_answer") and payload.get("continuity_question"):
            types.add("continuity_memory")
    return types


_SIGNAL_STOPWORDS = frozenset({"the", "a", "an", "is", "was", "are", "were", "be", "been", "being", "to", "of", "in", "for", "on", "with", "at", "by", "from", "and", "or", "not", "that", "this", "it", "its"})
_SIGNAL_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def _signal_matches(signal: str, haystack: str) -> bool:
    """Check if a signal phrase matches in the haystack using word overlap.

    Exact substring match first (fast path). Falls back to checking that all
    content words from the signal appear in the haystack, allowing the LLM to
    paraphrase word order while preserving key terms.
    """
    signal_lower = signal.lower()
    haystack_lower = haystack.lower()
    if signal_lower in haystack_lower:
        return True
    signal_words = set(_SIGNAL_TOKEN_PATTERN.findall(signal_lower)) - _SIGNAL_STOPWORDS
    if not signal_words:
        return False
    haystack_words = set(_SIGNAL_TOKEN_PATTERN.findall(haystack_lower))
    return signal_words.issubset(haystack_words)


def _score_signal_coverage(matches: list[str], expected_signals: list[str]) -> int:
    if not expected_signals:
        return 0
    if len(matches) == len(expected_signals):
        return 2
    if matches:
        return 1
    return 0


def _compare_continuations(
    *,
    should_memory_help: bool,
    baseline_rubric: dict[str, Any],
    memory_rubric: dict[str, Any],
) -> dict[str, Any]:
    baseline_total = int(baseline_rubric["total"])
    memory_total = int(memory_rubric["total"])
    improved_dimensions = [
        dimension
        for dimension in DIMENSION_ORDER
        if baseline_rubric["dimensions"][dimension]["applicable"]
        and int(memory_rubric["dimensions"][dimension]["score"] or 0)
        > int(baseline_rubric["dimensions"][dimension]["score"] or 0)
    ]

    if not should_memory_help:
        if memory_rubric["overreach"]:
            why = "Current-thread context was already sufficient, and the memory-backed branch overreached by replaying unnecessary prior detail."
        else:
            why = "Current-thread context was already sufficient, so extra memory is not counted as a benchmark win."
        return {
            "winner": "baseline",
            "why": why,
            "improved_dimensions": improved_dimensions,
        }

    if memory_total > baseline_total and improved_dimensions:
        return {
            "winner": "memory_backed",
            "why": "Memory-backed continuation preserved more of the prior developer-work state than baseline.",
            "improved_dimensions": improved_dimensions,
        }
    if memory_total == baseline_total:
        return {
            "winner": "tie",
            "why": "Both branches preserved a comparable amount of continuity signal.",
            "improved_dimensions": improved_dimensions,
        }
    return {
        "winner": "baseline",
        "why": "Baseline remained stronger because the retrieved continuity context did not carry enough forward.",
        "improved_dimensions": improved_dimensions,
    }


def _missing_dimensions(rubric: dict[str, Any]) -> list[str]:
    return [
        dimension
        for dimension in DIMENSION_ORDER
        if rubric["dimensions"][dimension]["applicable"] and int(rubric["dimensions"][dimension]["score"] or 0) < 2
    ]


def _dimension_gap_breakdown(
    *,
    scenario: dict[str, Any],
    memory_rubric: dict[str, Any],
    retrieval_text: str,
    routing_failed: bool,
) -> dict[str, list[str]]:
    retrieval_gaps: list[str] = []
    compact_task_state_gaps: list[str] = []
    packaging_gaps: list[str] = []

    for dimension in _missing_dimensions(memory_rubric):
        expected_signals = scenario.get("retrieval_signals", {}).get(dimension) or scenario.get("expected_dimensions", {}).get(dimension, [])
        if expected_signals and not any(signal.lower() in retrieval_text for signal in expected_signals):
            retrieval_gaps.append(dimension)
            continue
        if not routing_failed and scenario.get("expected_primary_layer") == "task_checkpoint" and dimension in TASK_STATE_DIMENSIONS:
            compact_task_state_gaps.append(dimension)
            continue
        packaging_gaps.append(dimension)

    return {
        "missing": _missing_dimensions(memory_rubric),
        "retrieval_recall": retrieval_gaps,
        "compact_task_state": compact_task_state_gaps,
        "result_packaging_evidence": packaging_gaps,
    }


def _guard_term_matches(
    *,
    guard_terms: dict[str, list[str]],
    top_result: dict[str, Any] | None,
    continuation: dict[str, Any],
) -> dict[str, list[str]]:
    combined = json.dumps(top_result or {}, sort_keys=True).lower() + "\n" + _combined_continuation_text(continuation)
    return {
        guard: [term for term in terms if term.lower() in combined]
        for guard, terms in guard_terms.items()
    }


def _classify_failure_families(
    *,
    scenario: dict[str, Any],
    comparison: dict[str, Any],
    memory_rubric: dict[str, Any],
    expected_memory_types_found: bool,
    intent_match: bool,
    query_family_match: bool,
    top_layer_match: bool,
    forbidden_layers_hit: list[str],
    gap_breakdown: dict[str, list[str]],
    guard_matches: dict[str, list[str]],
    injection_contract: dict[str, Any],
) -> list[str]:
    failures: list[str] = []

    if guard_matches.get("stale_state"):
        failures.append("stale_memory_failure")
    if guard_matches.get("wrong_thread_state"):
        failures.append("wrong_memory_selection_failure")
    if guard_matches.get("privacy_leak"):
        failures.append("privacy_leak_failure")

    if not injection_contract["should_inject_match"] or not injection_contract["decision_reason_match"]:
        failures.append("injection_decision_failure")
    if (
        not injection_contract["block_types_match"]
        or not injection_contract["block_count_ok"]
        or not injection_contract["cap_behavior_ok"]
        or injection_contract["forbidden_block_types_hit"]
    ):
        failures.append("injectability_packaging_failure")
    if injection_contract["semantic_compensation_needed"]:
        failures.append("thin_agent_boundary_failure")

    if not bool(scenario.get("should_memory_help")):
        if (
            comparison["winner"] == "memory_backed"
            or memory_rubric["overreach"]
            or forbidden_layers_hit
            or any(guard_matches.values())
            or injection_contract["should_inject_actual"]
            or injection_contract["injected_block_count"] > 0
        ):
            failures.append("no_value_overreach_failure")
        if scenario.get("query_wording_label") in PARAPHRASE_OR_INDIRECT_QUERY_LABELS and failures:
            failures.append("paraphrase_or_indirect_query_failure")
        return _ordered_failure_families(failures)

    if gap_breakdown["retrieval_recall"] or not expected_memory_types_found:
        failures.append("retrieval_recall_failure")
    if not intent_match or not query_family_match or not top_layer_match or forbidden_layers_hit:
        failures.append("routing_layer_choice_failure")
    if gap_breakdown["compact_task_state"]:
        failures.append("compact_task_state_failure")

    evidence_required = "evidence" in scenario.get("must_preserve", [])
    evidence_score = int(memory_rubric["dimensions"]["evidence"]["score"] or 0) if memory_rubric["dimensions"]["evidence"]["applicable"] else 0
    packaging_failure = bool(gap_breakdown["result_packaging_evidence"]) or (evidence_required and evidence_score < 2) or comparison["winner"] != "memory_backed"
    if packaging_failure and "retrieval_recall_failure" not in failures and "routing_layer_choice_failure" not in failures and "compact_task_state_failure" not in failures:
        failures.append("result_packaging_evidence_failure")

    if scenario.get("query_wording_label") in PARAPHRASE_OR_INDIRECT_QUERY_LABELS and (
        not intent_match
        or not query_family_match
        or not top_layer_match
        or comparison["winner"] != "memory_backed"
        or "injection_decision_failure" in failures
        or "injectability_packaging_failure" in failures
    ):
        failures.append("paraphrase_or_indirect_query_failure")

    return _ordered_failure_families(failures)
def _ordered_failure_families(families: list[str]) -> list[str]:
    unique = set(families)
    return [name for name in CONTINUITY_FAILURE_FAMILIES if name in unique]


def _scenario_query_request(scenario: dict[str, Any]) -> dict[str, Any]:
    request = dict(scenario["current_query"])
    request.setdefault("runtime_context", dict(scenario.get("runtime_context") or {}))
    if not request["runtime_context"]:
        request.pop("runtime_context")
    return request



def _with_default_visibility(payload: dict[str, Any]) -> dict[str, Any]:
    updated = dict(payload)
    updated.setdefault("visibility", "public")
    return updated

def _retrieval_text(results: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for item in results:
        if item.get("result_kind") == "memory_hit":
            payload = item.get("payload") or {}
            parts.append(json.dumps(payload))
        else:
            parts.append(str(item.get("excerpt", "")))
    return "\n".join(parts).lower()


def _format_current_thread_context(context: list[dict[str, Any]]) -> str:
    if not context:
        return "- none"
    lines = []
    for item in context:
        lines.append(
            f"- {item.get('role', 'unknown')}/{item.get('artifact_kind', 'unknown')}: {str(item.get('content', '')).strip()}"
        )
    return "\n".join(lines)


def _format_retrieval_results(results: list[dict[str, Any]]) -> str:
    if not results:
        return "- none"
    lines: list[str] = []
    for item in results[:6]:
        if item.get("result_kind") == "memory_hit":
            payload = item.get("payload") or {}
            if item.get("type") == "task_checkpoint":
                findings = payload.get("key_findings") or []
                evidence = payload.get("evidence") or []
                checkpoint_parts: list[str] = []
                if payload.get("task"):
                    checkpoint_parts.append(f"Task: {payload['task']}")
                if payload.get("current_state"):
                    checkpoint_parts.append(f"Current state: {payload['current_state']}")
                if payload.get("blocker_state"):
                    checkpoint_parts.append(f"Blocker: {payload['blocker_state']}")
                if payload.get("next_step"):
                    checkpoint_parts.append(f"Next step: {payload['next_step']}")
                if findings:
                    checkpoint_parts.append(f"Findings: {'; '.join(str(v) for v in findings[:2])}")
                if evidence:
                    checkpoint_parts.append(f"Evidence: {'; '.join(str(v) for v in evidence[:2])}")
                if payload.get("freshness_signal"):
                    checkpoint_parts.append(f"Freshness: {payload['freshness_signal']}")
                summary = " | ".join(checkpoint_parts)
            else:
                summary = (
                    payload.get("carry_forward_answer")
                    or payload.get("decision")
                    or payload.get("investigation_outcome")
                    or payload.get("summary")
                    or json.dumps(payload)
                )
            lines.append(f"- memory/{item.get('type')}: {summary}")
        else:
            lines.append(f"- source/{item.get('source_type')}:{item.get('source_id')}: {item.get('excerpt')}")
    return "\n".join(lines)


def _combined_continuation_text(continuation: dict[str, Any]) -> str:
    return "\n".join(
        [
            continuation["answer"],
            continuation["task_orientation"],
            " ".join(continuation["reused_findings"]),
            continuation["blocker_state"],
            continuation["preserved_progress"],
            continuation["next_step"],
            " ".join(continuation["evidence_used"]),
            continuation["freshness_notes"],
        ]
    ).lower()


def _build_summary(
    *,
    results: list[dict[str, Any]],
    scenario_file: Path,
    config: AppConfig,
    run_id: str,
    results_file: str,
    consolidation_strategy: str | None,
) -> dict[str, Any]:
    family_counts = failure_family_counts(results)
    dominant_bottleneck = dominant_tuning_bottleneck(family_counts)

    dimension_summary = []
    for dimension in DIMENSION_ORDER:
        applicable_rows = [
            row
            for row in results
            if row["rubric"]["memory_backed"]["dimensions"][dimension]["applicable"]
        ]
        dimension_summary.append(
            {
                "dimension": dimension,
                "applicable_scenarios": len(applicable_rows),
                "memory_backed_complete": sum(
                    1
                    for row in applicable_rows
                    if int(row["rubric"]["memory_backed"]["dimensions"][dimension]["score"] or 0) == 2
                ),
                "memory_backed_better_than_baseline": sum(
                    1
                    for row in applicable_rows
                    if int(row["rubric"]["memory_backed"]["dimensions"][dimension]["score"] or 0)
                    > int(row["rubric"]["baseline"]["dimensions"][dimension]["score"] or 0)
                ),
            }
        )

    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in results:
        by_family[row["scenario_family"]].append(row)

    summary = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scenario_file": str(scenario_file),
        "results_file": results_file,
        "provider": config.llm_provider_for_default_use_case,
        "model": config.llm_model_for_default_use_case,
        "prompt_variant": config.llm_prompt_variant_for_default_use_case,
        "consolidation_strategy": consolidation_strategy,
        "scenarios_total": len(results),
        "value_scenarios": sum(1 for row in results if row["should_memory_help"]),
        "non_value_scenarios": sum(1 for row in results if not row["should_memory_help"]),
        "memory_backed_wins": sum(1 for row in results if row["winner"] == "memory_backed"),
        "intent_matches": sum(1 for row in results if row["intent_match"]),
        "query_family_matches": sum(1 for row in results if row["query_family_match"]),
        "primary_layer_matches": sum(1 for row in results if row["primary_layer_match"]),
        "acceptable_layer_matches": sum(1 for row in results if row["top_layer_match"]),
        "query_contract_consistency_successes": sum(1 for row in results if row["query_contract_consistent"]),
        "should_inject_matches": sum(1 for row in results if row["injection_contract"]["should_inject_match"]),
        "decision_reason_matches": sum(1 for row in results if row["injection_contract"]["decision_reason_match"]),
        "injection_contract_successes": sum(1 for row in results if row["injection_contract"]["contract_success"]),
        "thin_agent_boundary_successes": sum(1 for row in results if row["thin_agent_boundary_success"]),
        "non_value_guard_successes": sum(1 for row in results if row["non_value_guard_success"]),
        "stale_guard_successes": sum(1 for row in results if row["stale_guard_success"]),
        "wrong_memory_guard_successes": sum(1 for row in results if row["wrong_memory_guard_success"]),
        "privacy_guard_successes": sum(
            1
            for row in results
            if "privacy_leak" in row["labels"]["must_not_introduce"] and "privacy_leak_failure" not in row["failure_families"]
        ),
        "scenario_families": sorted(by_family),
        "scoring_dimensions": list(DIMENSION_ORDER),
        "failure_family_counts": family_counts,
        "gap_signal_counts": family_counts,
        "dominant_tuning_bottleneck": dominant_bottleneck,
        "biggest_gap": dominant_bottleneck,
        "dominant_bottleneck_implication": dominant_bottleneck_implication(dominant_bottleneck),
        "biggest_gap_implication": dominant_bottleneck_implication(dominant_bottleneck),
        "dimension_summary": dimension_summary,
        "by_family": [
            {
                "scenario_family": family,
                "scenarios_total": len(rows),
                "memory_backed_wins": sum(1 for row in rows if row["winner"] == "memory_backed"),
                "intent_matches": sum(1 for row in rows if row["intent_match"]),
                "query_family_matches": sum(1 for row in rows if row["query_family_match"]),
                "primary_layer_matches": sum(1 for row in rows if row["primary_layer_match"]),
                "acceptable_layer_matches": sum(1 for row in rows if row["top_layer_match"]),
                "injection_contract_successes": sum(1 for row in rows if row["injection_contract"]["contract_success"]),
                "thin_agent_boundary_successes": sum(1 for row in rows if row["thin_agent_boundary_success"]),
                "failure_family_counts": failure_family_counts(rows),
            }
            for family, rows in sorted(by_family.items())
        ],
    }



    summary["benchmark"] = build_suite_summary(suite_id="work_resumption", results=results)
    return summary
def _build_report(*, summary: dict[str, Any], results: list[dict[str, Any]]) -> str:
    lines = [
        "# Developer-Work Continuity Benchmark Report",
        "",
        f"Run ID: `{summary['run_id']}`",
        "",
        "## Scenario Families In Suite",
        "",
    ]
    for family in summary["scenario_families"]:
        lines.append(f"- `{family}`")

    lines.extend(
        [
            "",
            "## Scoring Dimensions",
            "",
        ]
    )
    for dimension in summary["scoring_dimensions"]:
        lines.append(f"- `{dimension}`")

    lines.extend(
        [
            "",
            "## Aggregate",
            "",
            f"- scenarios: {summary['scenarios_total']}",
            f"- value scenarios: {summary['value_scenarios']}",
            f"- non-value scenarios: {summary['non_value_scenarios']}",
            f"- memory-backed wins: {summary['memory_backed_wins']} / {summary['value_scenarios']}",
            f"- intent matches: {summary['intent_matches']} / {summary['scenarios_total']}",
            f"- query-family matches: {summary['query_family_matches']} / {summary['scenarios_total']}",
            f"- primary-layer matches: {summary['primary_layer_matches']} / {summary['scenarios_total']}",
            f"- acceptable-layer matches: {summary['acceptable_layer_matches']} / {summary['scenarios_total']}",
            f"- query-contract consistency: {summary['query_contract_consistency_successes']} / {summary['scenarios_total']}",
            f"- should-inject matches: {summary['should_inject_matches']} / {summary['scenarios_total']}",
            f"- decision-reason matches: {summary['decision_reason_matches']} / {summary['scenarios_total']}",
            f"- injection-contract successes: {summary['injection_contract_successes']} / {summary['scenarios_total']}",
            f"- thin-agent boundary successes: {summary['thin_agent_boundary_successes']} / {summary['scenarios_total']}",
            f"- non-value guard successes: {summary['non_value_guard_successes']} / {summary['non_value_scenarios']}",
            f"- stale guard successes: {summary['stale_guard_successes']} / {summary['scenarios_total']}",
            f"- wrong-memory guard successes: {summary['wrong_memory_guard_successes']} / {summary['scenarios_total']}",
            f"- privacy guard successes: {summary['privacy_guard_successes']}",
            f"- dominant tuning bottleneck: {summary['dominant_tuning_bottleneck'] or 'none'}",
        ]
    )
    if summary["dominant_bottleneck_implication"]:
        lines.append(f"- current implication: {summary['dominant_bottleneck_implication']}")

    lines.extend(["", "## Failure Families", ""])
    for name, count in summary["failure_family_counts"].items():
        lines.append(f"- `{name}`: {count}")

    lines.extend(["", "## Scenario Results", ""])
    for row in results:
        lines.append(
            f"- `{row['scenario_id']}`: family `{row.get('query_family')}`, wording `{row.get('query_wording_label')}`, "
            f"winner `{row['winner']}`, intent `{row['routing_intent']}`, top layer `{row['top_layer']}`, "
            f"should_inject `{row['should_inject']}`, decision `{row['decision_reason']}`, "
            f"injected `{row['injection_contract']['injected_block_types'] or 'none'}`, "
            f"failures {row['failure_families'] or 'none'}"
        )
    return "\n".join(lines) + "\n"
def _serialize_consolidation_result(result: Any) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "package_name": result.package_name,
        "strategy_name": result.strategy_name,
        "strategy_version": result.strategy_version,
        "candidate_count": result.candidate_count,
        "selected_candidate_ids": list(result.selected_candidate_ids),
        "groups": [
            {
                "strategy_name": group.strategy_name,
                "strategy_version": group.strategy_version,
                "group_key": group.group_key,
                "selected_candidate_ids": list(group.selected_candidate_ids),
                "selected_source_item_ids": list(group.selected_source_item_ids),
                "candidate_thread_refs": list(group.candidate_thread_refs),
                "created_memory_ids": list(group.created_memory_ids),
                "created_memory_types": list(group.created_memory_types),
                "superseded_memory_ids": list(group.superseded_memory_ids),
                "merge_rationale": group.merge_rationale,
            }
            for group in result.groups
        ],
    }


def _load_scenarios(path: Path) -> list[dict[str, Any]]:
    raw_scenarios = json.loads(path.read_text(encoding="utf-8"))
    return [_normalize_scenario(item) for item in raw_scenarios]


def _normalize_scenario(raw: dict[str, Any]) -> dict[str, Any]:
    expected_dimensions = _normalize_dimension_signals(raw.get("expected_dimensions", {}))
    retrieval_signals = _normalize_dimension_signals(raw.get("retrieval_signals", {}))
    should_memory_help = bool(raw.get("should_memory_help", raw.get("expected_value")))
    expected_primary_layer = raw.get("expected_primary_layer", raw.get("expected_top_layer"))
    acceptable_fallback_layers = list(raw.get("acceptable_fallback_layers") or [])
    if not acceptable_fallback_layers and raw.get("acceptable_top_layers"):
        acceptable_fallback_layers = [
            item
            for item in raw.get("acceptable_top_layers", [])
            if item != expected_primary_layer
        ]
    acceptable_layers: list[str] = []
    if expected_primary_layer:
        acceptable_layers.append(expected_primary_layer)
    for layer in acceptable_fallback_layers:
        if layer not in acceptable_layers:
            acceptable_layers.append(layer)

    guard_terms = {
        key: [str(item).strip() for item in values if str(item).strip()]
        for key, values in (raw.get("guard_terms", {}) or {}).items()
    }
    forbidden_terms = [str(item).strip() for item in raw.get("forbidden_terms", []) if str(item).strip()]
    for values in guard_terms.values():
        for term in values:
            if term not in forbidden_terms:
                forbidden_terms.append(term)

    must_preserve = list(raw.get("must_preserve") or [])
    if not must_preserve:
        must_preserve = [dimension for dimension in DIMENSION_ORDER if expected_dimensions.get(dimension)]

    runtime_context = _default_runtime_context(raw, should_memory_help=should_memory_help)
    expected_intent = raw.get("expected_intent")
    expected_query_family = raw.get("expected_query_family") or query_family_from_intent(
        expected_intent,
        runtime_context=runtime_context,
        should_memory_help=should_memory_help,
    )
    injection_expectations = default_injection_expectations(
        should_memory_help=should_memory_help,
        runtime_context=runtime_context,
        expected_primary_layer=expected_primary_layer,
        expected_memory_types=list(raw.get("expected_memory_types") or []),
        acceptable_fallback_layers=acceptable_fallback_layers,
        forbidden_layers=list(raw.get("forbidden_layers") or []),
        expected_should_inject=raw.get("expected_should_inject"),
        expected_decision_reason=raw.get("expected_decision_reason"),
        acceptable_decision_reasons=list(raw.get("acceptable_decision_reasons") or []),
        expected_primary_block_types=list(raw.get("expected_primary_injected_block_types") or []),
        acceptable_fallback_block_types=list(raw.get("acceptable_fallback_block_types") or []),
        forbidden_block_types=list(raw.get("forbidden_block_types") or []),
        acceptable_injected_block_count=raw.get("acceptable_injected_block_count"),
        expected_cap_behavior=raw.get("expected_cap_behavior"),
    )

    scenario = dict(raw)
    scenario.update(
        {
            "should_memory_help": should_memory_help,
            "expected_value": should_memory_help,
            "runtime_context": runtime_context,
            "expected_query_family": expected_query_family,
            "query_wording_label": raw.get("query_wording_label") or _default_query_wording_label(raw),
            "expected_primary_layer": expected_primary_layer,
            "expected_top_layer": expected_primary_layer,
            "acceptable_fallback_layers": acceptable_fallback_layers,
            "acceptable_layers": acceptable_layers,
            "acceptable_top_layers": acceptable_layers,
            "expected_dimensions": expected_dimensions,
            "retrieval_signals": retrieval_signals,
            "must_preserve": must_preserve,
            "must_not_introduce": list(raw.get("must_not_introduce", [])),
            "forbidden_layers": list(raw.get("forbidden_layers", [])),
            "guard_terms": guard_terms,
            "forbidden_terms": forbidden_terms,
            **injection_expectations,
        }
    )
    return scenario


def _default_runtime_context(raw: dict[str, Any], *, should_memory_help: bool) -> dict[str, Any]:
    explicit_runtime_context = raw.get("runtime_context") or (raw.get("current_query") or {}).get("runtime_context")
    if isinstance(explicit_runtime_context, dict):
        return dict(explicit_runtime_context)
    scenario_id = str(raw.get("scenario_id") or "")
    description = str(raw.get("description") or "").lower()
    if not should_memory_help and (
        "same-thread" in scenario_id
        or "same thread" in description
        or "current thread already" in str(raw.get("expected_non_value_reason") or "").lower()
    ):
        return {
            "turn_kind": "same_thread_continuation",
            "session_has_sufficient_local_context": True,
        }
    if raw.get("expected_intent") in {"recall", "evidence_trace", "structured_recall"}:
        return {
            "turn_kind": "new_thread",
            "session_has_sufficient_local_context": False,
        }
    return {
        "turn_kind": "resumed_session",
        "session_has_sufficient_local_context": False,
    }


def _default_query_wording_label(raw: dict[str, Any]) -> str:
    lowered = " ".join(
        [
            str(raw.get("description") or "").lower(),
            str(raw.get("target_question") or "").lower(),
            str((raw.get("current_query") or {}).get("text") or "").lower(),
        ]
    )
    if "indirect" in lowered:
        return "indirect"
    if "paraphrase" in lowered or "general lesson" in lowered or "what state were we in" in lowered or "what finding should orient us" in lowered:
        return "paraphrase"
    return "literal"
def _normalize_dimension_signals(raw_dimensions: dict[str, Any]) -> dict[str, list[str]]:
    normalized: dict[str, list[str]] = {dimension: [] for dimension in DIMENSION_ORDER}
    for key, value in raw_dimensions.items():
        dimension = LEGACY_DIMENSION_NAMES.get(key)
        if dimension is None:
            continue
        if isinstance(value, list):
            normalized[dimension] = [str(item).strip() for item in value if str(item).strip()]
        elif value not in (None, ""):
            normalized[dimension] = [str(value).strip()]
    return normalized


def _build_run_id(config: AppConfig, consolidation_strategy: str | None) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    provider = (config.llm_provider_for_default_use_case or "provider").replace("_", "-")
    model = (config.llm_model_for_default_use_case or "model").replace("/", "-").replace(".", "-")
    strategy_suffix = f"__{consolidation_strategy}" if consolidation_strategy else ""
    return f"work-resumption-benchmark__{provider}__{model}{strategy_suffix}__{timestamp}"


if __name__ == "__main__":
    raise SystemExit(main())
