from __future__ import annotations

import argparse
import json
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
from evals.continuity_common import default_injection_expectations, evaluate_query_contract, query_family_from_intent
from evals.recurring_question_benchmark import _compare_answers, _generate_answer, _score_answer
from providers.llm.base import LLMProvider

DEFAULT_SCENARIO_FILE = Path("evals/memory_routing/scenarios.json")
DEFAULT_OUTPUT_DIR = Path("evals/memory_routing/output")
HIGHER_LEVEL_LAYERS = {"pattern_memory", "continuity_memory", "task_checkpoint"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the routed memory-policy benchmark.")
    parser.add_argument("--scenario-file", type=Path, default=DEFAULT_SCENARIO_FILE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-name", default=None)
    args = parser.parse_args()

    run_dir = run_memory_routing_benchmark(
        scenario_file=args.scenario_file,
        output_root=args.output_dir,
        config=AppConfig.from_env(),
        run_name=args.run_name,
    )
    print(run_dir)
    return 0


def run_memory_routing_benchmark(
    *,
    scenario_file: Path,
    output_root: Path,
    config: AppConfig,
    run_name: str | None = None,
    answer_provider: LLMProvider | None = None,
) -> Path:
    scenarios = _load_scenarios(scenario_file)
    default_package = config.package_config(config.default_use_case)
    if answer_provider is None:
        if not default_package.llm_provider or not default_package.model:
            raise ValueError(f"Default use case '{config.default_use_case}' is missing LLM package config")
        provider = build_llm_provider(config, provider_name=default_package.llm_provider, model=default_package.model)
    else:
        provider = answer_provider

    run_id = run_name or _build_run_id(config)
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    results_path = run_dir / "results.jsonl"

    results: list[dict[str, Any]] = []
    with results_path.open("w", encoding="utf-8") as results_file:
        for scenario in scenarios:
            result = annotate_result(
                _run_scenario(scenario=scenario, config=config, answer_provider=provider),
                suite_id="memory_routing",
            )
            results.append(result)
            results_file.write(json.dumps(result) + "\n")

    summary = _build_summary(results=results, scenario_file=scenario_file, config=config, run_id=run_id, results_file=results_path.name)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (run_dir / "report.md").write_text(_build_report(summary=summary, results=results), encoding="utf-8")
    return run_dir


def _run_scenario(
    *,
    scenario: dict[str, Any],
    config: AppConfig,
    answer_provider: LLMProvider,
) -> dict[str, Any]:
    consolidation_strategy = scenario.get("consolidation_strategy")
    runtime_context = _scenario_runtime_context(scenario)
    query_request = dict(scenario["current_query"])
    query_request.setdefault("runtime_context", runtime_context)
    with TemporaryDirectory() as temp_dir:
        database_url = f"sqlite:///{Path(temp_dir) / 'memory-routing.db'}"
        vector_index_config = replace(config.vector_index, index_path=str(Path(temp_dir) / "vector.index"))
        scenario_config = replace(config, sqlite_url=database_url, default_use_case="agent_conversation_memory", vector_index=vector_index_config)
        with TestClient(create_app(scenario_config)) as client:
            for event in scenario.get("prior_events", []):
                response = client.post("/items", json=_with_default_visibility(event))
                response.raise_for_status()
            client.app.state.pallium_service.drain_processing_queue(worker_id="memory-routing-runner")

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
            memory_payload = query_response.json()
            engine = getattr(client.app.state.pallium_service._storage, "_engine", None)
            if engine is not None:
                engine.dispose()

    baseline_answer = _generate_answer(
        answer_provider=answer_provider,
        target_question=scenario["target_question"],
        current_thread_context=scenario.get("current_thread_context", []),
        memory_backed_results=[],
        branch="baseline",
    )
    memory_answer = _generate_answer(
        answer_provider=answer_provider,
        target_question=scenario["target_question"],
        current_thread_context=scenario.get("current_thread_context", []),
        memory_backed_results=memory_payload["results"],
        branch="memory_backed",
    )

    routing = ((memory_payload.get("trace") or {}).get("routing") or {})
    top_result = memory_payload["results"][0] if memory_payload["results"] else None
    top_layer = _result_layer(top_result)
    top_memory_type = top_result.get("type") if top_result else None
    available_layers = sorted({_result_layer(item) for item in memory_payload["results"]})
    available_memory_types = sorted({item.get("type") for item in memory_payload["results"] if item.get("type")})
    expected_top_layers = scenario.get("acceptable_top_layers") or [scenario["expected_top_layer"]]
    expected_memory_types = scenario.get("expected_memory_types", [])
    expected_higher_level_memory_types = scenario.get("expected_higher_level_memory_types", [])
    returned_memory_types = sorted(
        {item.get("type") for item in memory_payload["results"] if item.get("result_kind") == "memory_hit" and item.get("type")}
    )
    higher_level_memory_types = sorted(item for item in returned_memory_types if item in {"pattern_memory", "continuity_memory", "task_checkpoint"})

    query_family = routing.get("query_family") or query_family_from_intent(
        routing.get("query_intent"),
        runtime_context=runtime_context,
        should_memory_help=bool(scenario.get("expected_value")),
    )
    expected_query_family = scenario.get("expected_query_family") or query_family_from_intent(
        scenario.get("expected_intent"),
        runtime_context=runtime_context,
        should_memory_help=bool(scenario.get("expected_value")),
    )
    query_family_match = query_family == expected_query_family
    intent_match = routing.get("query_intent") == scenario["expected_intent"]
    top_layer_match = top_layer in expected_top_layers
    expected_top_memory_types = scenario.get("expected_top_memory_types") or []
    top_memory_type_match = not expected_top_memory_types or top_memory_type in expected_top_memory_types
    expected_memory_types_found = all(item in returned_memory_types for item in expected_memory_types)
    expected_higher_level_memory_types_found = all(item in higher_level_memory_types for item in expected_higher_level_memory_types)

    baseline_rubric = _score_answer(
        answer_payload=baseline_answer,
        target_question=scenario["target_question"],
        expected_answer_signals=scenario.get("expected_answer_signals", []),
        scenario_kind=scenario["scenario_kind"],
    )
    memory_rubric = _score_answer(
        answer_payload=memory_answer,
        target_question=scenario["target_question"],
        expected_answer_signals=scenario.get("expected_answer_signals", []),
        scenario_kind=scenario["scenario_kind"],
    )
    comparison = _compare_answers(
        expected_value=bool(scenario.get("expected_value")),
        expected_memory_types_found=expected_memory_types_found,
        expected_higher_level_memory_types_found=expected_higher_level_memory_types_found,
        baseline_rubric=baseline_rubric,
        memory_rubric=memory_rubric,
        baseline_answer=baseline_answer,
        memory_answer=memory_answer,
        expected_failures_without_memory=scenario.get("expected_failures_without_memory", []),
    )

    injection_expectations = default_injection_expectations(
        should_memory_help=bool(scenario.get("expected_value")),
        runtime_context=runtime_context,
        expected_primary_layer=scenario.get("expected_top_layer"),
        expected_memory_types=expected_memory_types,
        acceptable_fallback_layers=list(scenario.get("acceptable_top_layers") or []),
        forbidden_layers=[],
        expected_should_inject=scenario.get("expected_should_inject"),
        expected_decision_reason=scenario.get("expected_decision_reason"),
        acceptable_decision_reasons=list(scenario.get("acceptable_decision_reasons") or []),
        expected_primary_block_types=list(scenario.get("expected_primary_injected_block_types") or []),
        acceptable_fallback_block_types=list(scenario.get("acceptable_fallback_block_types") or []),
        forbidden_block_types=list(scenario.get("forbidden_block_types") or []),
        acceptable_injected_block_count=scenario.get("acceptable_injected_block_count"),
        expected_cap_behavior=scenario.get("expected_cap_behavior"),
    )
    query_contract = evaluate_query_contract(
        query_payload=query_contract_payload,
        debug_payload=memory_payload,
        **injection_expectations,
    )

    forbidden_terms_found = _find_forbidden_terms(
        forbidden_terms=scenario.get("forbidden_terms", []),
        retrieval_results=memory_payload["results"],
        answer_payload=memory_answer,
    )
    false_merge_occurred = bool(forbidden_terms_found)
    higher_level_overuse = top_layer in HIGHER_LEVEL_LAYERS and scenario["expected_top_layer"] not in HIGHER_LEVEL_LAYERS
    answer_success = _answer_success(expected_value=bool(scenario.get("expected_value")), winner=comparison["winner"])
    policy_success = all(
        [
            intent_match,
            query_family_match,
            top_layer_match,
            top_memory_type_match,
            not false_merge_occurred,
            not higher_level_overuse,
            answer_success,
            query_contract["injection_contract"]["contract_success"],
        ]
    )

    return {
        "scenario_id": scenario["scenario_id"],
        "scenario_kind": scenario["scenario_kind"],
        "description": scenario["description"],
        "consolidation_strategy": consolidation_strategy,
        "runtime_context": runtime_context,
        "expected_value": bool(scenario.get("expected_value")),
        "expected_intent": scenario["expected_intent"],
        "expected_query_family": expected_query_family,
        "query_family": query_family,
        "query_family_match": query_family_match,
        "expected_top_layer": scenario["expected_top_layer"],
        "acceptable_top_layers": expected_top_layers,
        "expected_top_memory_types": expected_top_memory_types,
        "expected_memory_types": expected_memory_types,
        "expected_higher_level_memory_types": expected_higher_level_memory_types,
        "routing_intent": routing.get("query_intent"),
        "routing_preferred_layers": routing.get("preferred_layers", []),
        "intent_match": intent_match,
        "top_layer": top_layer,
        "top_memory_type": top_memory_type,
        "top_layer_match": top_layer_match,
        "top_memory_type_match": top_memory_type_match,
        "available_layers": available_layers,
        "available_memory_types": available_memory_types,
        "returned_memory_types": returned_memory_types,
        "higher_level_memory_types": higher_level_memory_types,
        "expected_memory_types_found": expected_memory_types_found,
        "expected_higher_level_memory_types_found": expected_higher_level_memory_types_found,
        "higher_level_overuse": higher_level_overuse,
        "forbidden_terms_found": forbidden_terms_found,
        "false_merge_occurred": false_merge_occurred,
        "answer_success": answer_success,
        "policy_success": policy_success,
        "winner": comparison["winner"],
        "why": comparison["why"],
        "query_trace": memory_payload.get("trace"),
        "memory_backed_retrieval": memory_payload["results"],
        "thin_agent_query_response": query_contract_payload,
        "query_contract_consistent": query_contract["query_contract_consistent"],
        "query_contract_mismatch_fields": query_contract["query_contract_mismatch_fields"],
        "should_inject": query_contract["should_inject"],
        "decision_reason": query_contract["decision_reason"],
        "injectable_blocks": query_contract["injectable_blocks"],
        "injection_contract": query_contract["injection_contract"],
        "baseline_answer": baseline_answer,
        "memory_backed_answer": memory_answer,
        "rubric": {
            "baseline": baseline_rubric,
            "memory_backed": memory_rubric,
            "comparison": comparison,
        },
        "consolidation_run": _serialize_consolidation_result(consolidation_result),
    }

def _scenario_runtime_context(scenario: dict[str, Any]) -> dict[str, Any]:
    explicit_runtime_context = scenario.get("runtime_context") or (scenario.get("current_query") or {}).get("runtime_context")
    if isinstance(explicit_runtime_context, dict):
        return dict(explicit_runtime_context)
    if not bool(scenario.get("expected_value")):
        return {
            "turn_kind": "same_thread_continuation",
            "session_has_sufficient_local_context": True,
        }
    if scenario.get("expected_intent") in {"answer_continuity", "work_resumption"}:
        return {
            "turn_kind": "resumed_session",
            "session_has_sufficient_local_context": False,
        }
    return {
        "turn_kind": "new_thread",
        "session_has_sufficient_local_context": False,
    }



def _with_default_visibility(payload: dict[str, Any]) -> dict[str, Any]:
    updated = dict(payload)
    updated.setdefault("visibility_context", {"kind": "public", "id": None})
    return updated


def _result_layer(item: dict[str, Any] | None) -> str:
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


def _find_forbidden_terms(*, forbidden_terms: list[str], retrieval_results: list[dict[str, Any]], answer_payload: dict[str, Any]) -> list[str]:
    if not forbidden_terms:
        return []
    combined = json.dumps(retrieval_results).lower() + "\n" + json.dumps(answer_payload).lower()
    return [term for term in forbidden_terms if term.lower() in combined]


def _answer_success(*, expected_value: bool, winner: str) -> bool:
    if expected_value:
        return winner == "memory_backed"
    return winner != "memory_backed"


def _build_summary(*, results: list[dict[str, Any]], scenario_file: Path, config: AppConfig, run_id: str, results_file: str) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scenario_file": str(scenario_file),
        "results_file": results_file,
        "provider": config.llm_provider_for_default_use_case,
        "model": config.llm_model_for_default_use_case,
        "prompt_variant": config.llm_prompt_variant_for_default_use_case,
        "scenarios_total": len(results),
        "value_scenarios": sum(1 for row in results if row["expected_value"]),
        "non_value_scenarios": sum(1 for row in results if not row["expected_value"]),
        "intent_matches": sum(1 for row in results if row["intent_match"]),
        "query_family_matches": sum(1 for row in results if row["query_family_match"]),
        "top_layer_matches": sum(1 for row in results if row["top_layer_match"]),
        "answer_successes": sum(1 for row in results if row["answer_success"]),
        "query_contract_consistency_successes": sum(1 for row in results if row["query_contract_consistent"]),
        "injection_contract_successes": sum(1 for row in results if row["injection_contract"]["contract_success"]),
        "policy_successes": sum(1 for row in results if row["policy_success"]),
        "memory_backed_wins": sum(1 for row in results if row["winner"] == "memory_backed"),
        "false_merge_failures": sum(1 for row in results if row["false_merge_occurred"]),
        "higher_level_overuse_failures": sum(1 for row in results if row["higher_level_overuse"]),
        "by_intent": [],
    }
    by_intent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in results:
        by_intent[row["expected_intent"]].append(row)
    for intent in sorted(by_intent):
        rows = by_intent[intent]
        summary["by_intent"].append(
            {
                "intent": intent,
                "scenarios_total": len(rows),
                "intent_matches": sum(1 for row in rows if row["intent_match"]),
                "query_family_matches": sum(1 for row in rows if row["query_family_match"]),
                "top_layer_matches": sum(1 for row in rows if row["top_layer_match"]),
                "answer_successes": sum(1 for row in rows if row["answer_success"]),
                "injection_contract_successes": sum(1 for row in rows if row["injection_contract"]["contract_success"]),
                "policy_successes": sum(1 for row in rows if row["policy_success"]),
                "false_merge_failures": sum(1 for row in rows if row["false_merge_occurred"]),
            }
        )
    summary["benchmark"] = build_suite_summary(suite_id="memory_routing", results=results)
    return summary
def _build_report(*, summary: dict[str, Any], results: list[dict[str, Any]]) -> str:
    lines = [
        "# Memory Routing Benchmark Report",
        "",
        f"Run ID: `{summary['run_id']}`",
        "",
        "## Aggregate",
        "",
        f"- scenarios: {summary['scenarios_total']}",
        f"- intent matches: {summary['intent_matches']} / {summary['scenarios_total']}",
        f"- query-family matches: {summary['query_family_matches']} / {summary['scenarios_total']}",
        f"- top-layer matches: {summary['top_layer_matches']} / {summary['scenarios_total']}",
        f"- answer successes: {summary['answer_successes']} / {summary['scenarios_total']}",
        f"- query-contract consistency: {summary['query_contract_consistency_successes']} / {summary['scenarios_total']}",
        f"- injection-contract successes: {summary['injection_contract_successes']} / {summary['scenarios_total']}",
        f"- policy successes: {summary['policy_successes']} / {summary['scenarios_total']}",
        f"- false-merge failures: {summary['false_merge_failures']}",
        f"- higher-level-overuse failures: {summary['higher_level_overuse_failures']}",
        "",
        "## By Intent",
        "",
    ]
    for item in summary["by_intent"]:
        lines.append(
            f"- `{item['intent']}`: policy {item['policy_successes']} / {item['scenarios_total']}, "
            f"intent {item['intent_matches']} / {item['scenarios_total']}, "
            f"family {item['query_family_matches']} / {item['scenarios_total']}, "
            f"top-layer {item['top_layer_matches']} / {item['scenarios_total']}"
        )
    failed = [row for row in results if not row["policy_success"]]
    lines.extend(["", "## Failures", ""])
    if not failed:
        lines.append("- none")
    else:
        for row in failed:
            reasons = []
            if not row["intent_match"]:
                reasons.append(f"intent expected `{row['expected_intent']}` got `{row['routing_intent']}`")
            if not row["query_family_match"]:
                reasons.append(f"query family expected `{row['expected_query_family']}` got `{row['query_family']}`")
            if not row["top_layer_match"]:
                reasons.append(f"top layer expected `{row['acceptable_top_layers']}` got `{row['top_layer']}`")
            if not row["answer_success"]:
                reasons.append(f"winner was `{row['winner']}`")
            if row["false_merge_occurred"]:
                reasons.append(f"forbidden terms {row['forbidden_terms_found']}")
            if row["higher_level_overuse"]:
                reasons.append("higher-level overuse")
            if not row["injection_contract"]["contract_success"]:
                reasons.append(f"injection contract {row['injection_contract']}")
            lines.append(f"- `{row['scenario_id']}`: {'; '.join(reasons)}")
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
    return json.loads(path.read_text(encoding="utf-8"))


def _build_run_id(config: AppConfig) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    provider = (config.llm_provider_for_default_use_case or "provider").replace("_", "-")
    model = (config.llm_model_for_default_use_case or "model").replace("/", "-").replace(".", "-")
    return f"memory-routing-benchmark__{provider}__{model}__{timestamp}"


if __name__ == "__main__":
    raise SystemExit(main())
