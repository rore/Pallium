from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from fastapi.testclient import TestClient

from app.config import AppConfig
from app.dependencies import build_llm_provider
from app.main import create_app
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
    },
    indent=2,
)
DIMENSION_ORDER = (
    "task_orientation",
    "prior_findings_reused",
    "blocker_state",
    "preserved_progress",
    "next_step_guidance",
)
DEFAULT_DIMENSION_GAP_TARGET = "result_packaging_or_evidence"
GAP_IMPLICATIONS = {
    "compact_task_state_memory": "The current benchmark points to compact task-state memory as the next slice for carrying forward progress, blocker state, and the next step without depending on transcript replay.",
    "selected_work_artifact_support": "The current benchmark points to selected work-artifact support as the next slice when tool/auth failure state and partial progress need more deliberate promotion than generic source replay.",
    "routing_or_layer_choice": "The current benchmark points to routing and layer choice as the next slice to tighten before broadening memory representation again.",
    "result_packaging_or_evidence": "The current benchmark points to result packaging and evidence handling as the next slice to improve in continuation guidance for the downstream agent.",
    "retrieval_recall": "The current benchmark points to retrieval recall as the next slice to improve before adding more memory structure.",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the work-resumption continuity benchmark.")
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

    run_id = run_name or _build_run_id(config, consolidation_strategy)
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    results_path = run_dir / "results.jsonl"

    results: list[dict[str, Any]] = []
    with results_path.open("w", encoding="utf-8") as results_file:
        for scenario in scenarios:
            result = _run_scenario(
                scenario=scenario,
                config=config,
                answer_provider=provider,
                consolidation_strategy=consolidation_strategy,
            )
            results.append(result)
            results_file.write(json.dumps(result) + "\n")

    summary = _build_summary(
        results=results,
        scenario_file=scenario_file,
        config=config,
        run_id=run_id,
        results_file=results_path.name,
        consolidation_strategy=consolidation_strategy,
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
    with TemporaryDirectory() as temp_dir:
        database_url = f"sqlite:///{Path(temp_dir) / 'work-resumption.db'}"
        scenario_config = replace(
            config,
            sqlite_url=database_url,
            default_use_case="agent_conversation_memory",
        )
        with TestClient(create_app(scenario_config)) as client:
            for event in scenario.get("prior_events", []):
                response = client.post("/items", json=event)
                response.raise_for_status()

            consolidation_result = None
            if consolidation_strategy:
                consolidation_result = client.app.state.pallium_service.run_consolidation_pass(
                    use_case="agent_conversation_memory",
                    strategy_name=consolidation_strategy,
                )

            query_response = client.post("/query/debug", json=scenario["current_query"])
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

    memory_hits = [item for item in query_payload["results"] if item.get("result_kind") == "memory_hit"]
    source_hits = [item for item in query_payload["results"] if item.get("result_kind") == "source_hit"]
    returned_memory_types = sorted({item.get("type") for item in memory_hits if item.get("type")})
    expected_memory_types = scenario.get("expected_memory_types", [])
    expected_memory_types_found = all(item in returned_memory_types for item in expected_memory_types)
    top_result = query_payload["results"][0] if query_payload["results"] else None
    top_layer = _result_layer(top_result)
    expected_top_layers = list(scenario.get("acceptable_top_layers") or [])
    if not expected_top_layers and scenario.get("expected_top_layer"):
        expected_top_layers = [scenario["expected_top_layer"]]
    top_layer_match = not expected_top_layers or top_layer in expected_top_layers

    baseline_rubric = _score_continuation(
        continuation=baseline_continuation,
        expected_dimensions=scenario.get("expected_dimensions", {}),
        forbidden_terms=scenario.get("forbidden_terms", []),
    )
    memory_rubric = _score_continuation(
        continuation=memory_backed_continuation,
        expected_dimensions=scenario.get("expected_dimensions", {}),
        forbidden_terms=scenario.get("forbidden_terms", []),
    )
    comparison = _compare_continuations(
        expected_value=bool(scenario.get("expected_value")),
        baseline_rubric=baseline_rubric,
        memory_rubric=memory_rubric,
        expected_memory_types_found=expected_memory_types_found,
        top_layer_match=top_layer_match,
    )
    gap_signal_counts = _infer_gap_signal_counts(
        scenario=scenario,
        expected_value=bool(scenario.get("expected_value")),
        memory_rubric=memory_rubric,
        query_payload=query_payload,
        top_layer_match=top_layer_match,
    )

    return {
        "scenario_id": scenario["scenario_id"],
        "scenario_family": scenario["scenario_family"],
        "scenario_kind": scenario["scenario_family"],
        "description": scenario["description"],
        "expected_value": bool(scenario.get("expected_value")),
        "expected_non_value_reason": scenario.get("expected_non_value_reason"),
        "expected_memory_types": expected_memory_types,
        "expected_memory_types_found": expected_memory_types_found,
        "expected_top_layers": expected_top_layers,
        "top_layer": top_layer,
        "top_layer_match": top_layer_match,
        "returned_memory_types": returned_memory_types,
        "memory_hit_count": len(memory_hits),
        "source_hit_count": len(source_hits),
        "memory_backed_retrieval": query_payload["results"],
        "query_trace": query_payload.get("trace"),
        "routing_intent": ((query_payload.get("trace") or {}).get("routing") or {}).get("query_intent"),
        "routing_preferred_layers": ((query_payload.get("trace") or {}).get("routing") or {}).get("preferred_layers", []),
        "baseline_continuation": baseline_continuation,
        "memory_backed_continuation": memory_backed_continuation,
        "rubric": {
            "baseline": baseline_rubric,
            "memory_backed": memory_rubric,
            "comparison": comparison,
        },
        "winner": comparison["winner"],
        "why": comparison["why"],
        "missing_dimensions_after_memory": _missing_dimensions(memory_rubric),
        "gap_signals": sorted(gap_signal_counts),
        "gap_signal_counts": dict(gap_signal_counts),
        "non_value_guard_success": (not bool(scenario.get("expected_value"))) and not memory_rubric["overreach"],
        "consolidation_strategy": consolidation_strategy,
        "consolidation_run": _serialize_consolidation_result(consolidation_result),
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
    forbidden_terms: list[str],
) -> dict[str, Any]:
    dimensions: dict[str, Any] = {}
    for dimension in DIMENSION_ORDER:
        expected_signals = expected_dimensions.get(dimension, [])
        applicable = bool(expected_signals)
        haystack = _dimension_text(dimension, continuation)
        matches = [signal for signal in expected_signals if signal.lower() in haystack.lower()]
        missing = [signal for signal in expected_signals if signal not in matches]
        dimensions[dimension] = {
            "applicable": applicable,
            "expected_signals": expected_signals,
            "matches": matches,
            "missing": missing,
            "score": _score_signal_coverage(matches, expected_signals) if applicable else None,
        }

    combined = _combined_continuation_text(continuation)
    overreach_terms = [term for term in forbidden_terms if term.lower() in combined]
    applicable_dimensions = [item for item in dimensions.values() if item["applicable"]]
    total = sum(int(item["score"]) for item in applicable_dimensions)
    evidence_grounding = 2 if continuation["evidence_used"] else 0
    return {
        "dimensions": dimensions,
        "applicable_dimensions": len(applicable_dimensions),
        "fully_covered_dimensions": sum(1 for item in applicable_dimensions if int(item["score"]) == 2),
        "partially_covered_dimensions": sum(1 for item in applicable_dimensions if int(item["score"]) == 1),
        "total": total,
        "evidence_grounding": evidence_grounding,
        "overreach": bool(overreach_terms),
        "overreach_terms": overreach_terms,
    }


def _dimension_text(dimension: str, continuation: dict[str, Any]) -> str:
    if dimension == "task_orientation":
        return f"{continuation['answer']}\n{continuation['task_orientation']}"
    if dimension == "prior_findings_reused":
        return f"{continuation['answer']}\n{' '.join(continuation['reused_findings'])}"
    if dimension == "blocker_state":
        return f"{continuation['answer']}\n{continuation['blocker_state']}"
    if dimension == "preserved_progress":
        return f"{continuation['answer']}\n{continuation['preserved_progress']}"
    return f"{continuation['answer']}\n{continuation['next_step']}"


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
    expected_value: bool,
    baseline_rubric: dict[str, Any],
    memory_rubric: dict[str, Any],
    expected_memory_types_found: bool,
    top_layer_match: bool,
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

    if not expected_value:
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
        why = "Memory-backed continuation preserved more of the prior work state than baseline."
        if not expected_memory_types_found and not top_layer_match:
            why = "Memory-backed continuation improved, but routing still relied on a weaker layer than expected."
        return {
            "winner": "memory_backed",
            "why": why,
            "improved_dimensions": improved_dimensions,
        }
    if memory_total == baseline_total:
        return {
            "winner": "tie",
            "why": "Both branches preserved a comparable amount of work continuity.",
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


def _infer_gap_signal_counts(
    *,
    scenario: dict[str, Any],
    expected_value: bool,
    memory_rubric: dict[str, Any],
    query_payload: dict[str, Any],
    top_layer_match: bool,
) -> Counter[str]:
    counts: Counter[str] = Counter()
    if not expected_value:
        if memory_rubric["overreach"]:
            counts["overreach_in_no_value_case"] += 1
        return counts

    retrieval_text = _retrieval_text(query_payload["results"])
    retrieval_signals = scenario.get("retrieval_signals", {})
    dimension_gap_targets = scenario.get("dimension_gap_targets", {})
    for dimension in _missing_dimensions(memory_rubric):
        expected_signals = retrieval_signals.get(dimension) or scenario.get("expected_dimensions", {}).get(dimension, [])
        if expected_signals and not any(signal.lower() in retrieval_text for signal in expected_signals):
            counts["retrieval_recall"] += 1
            continue
        if not top_layer_match:
            counts["routing_or_layer_choice"] += 1
            continue
        targets = dimension_gap_targets.get(dimension) or [DEFAULT_DIMENSION_GAP_TARGET]
        for target in targets:
            counts[target] += 1
    return counts


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
        ]
    ).lower()


def _result_layer(item: dict[str, Any] | None) -> str:
    if item is None:
        return "none"
    if item.get("result_kind") == "source_hit":
        return "source_evidence"
    if item.get("type") == "pattern_memory":
        return "pattern_memory"
    if item.get("type") == "continuity_memory":
        return "continuity_memory"
    return "lower_level_memory"


def _build_summary(
    *,
    results: list[dict[str, Any]],
    scenario_file: Path,
    config: AppConfig,
    run_id: str,
    results_file: str,
    consolidation_strategy: str | None,
) -> dict[str, Any]:
    gap_counts: Counter[str] = Counter()
    for row in results:
        gap_counts.update(row.get("gap_signal_counts", {}))

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

    biggest_gap = _biggest_gap(gap_counts)
    return {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scenario_file": str(scenario_file),
        "results_file": results_file,
        "provider": config.llm_provider_for_default_use_case,
        "model": config.llm_model_for_default_use_case,
        "prompt_variant": config.llm_prompt_variant_for_default_use_case,
        "consolidation_strategy": consolidation_strategy,
        "scenarios_total": len(results),
        "value_scenarios": sum(1 for row in results if row["expected_value"]),
        "non_value_scenarios": sum(1 for row in results if not row["expected_value"]),
        "memory_backed_wins": sum(1 for row in results if row["winner"] == "memory_backed"),
        "top_layer_matches": sum(1 for row in results if row["top_layer_match"]),
        "non_value_guard_successes": sum(1 for row in results if row["non_value_guard_success"]),
        "overreach_failures": gap_counts.get("overreach_in_no_value_case", 0),
        "scenario_families": sorted(by_family),
        "scoring_dimensions": list(DIMENSION_ORDER),
        "gap_signal_counts": dict(gap_counts),
        "biggest_gap": biggest_gap,
        "biggest_gap_implication": _gap_implication(biggest_gap),
        "dimension_summary": dimension_summary,
        "by_family": [
            {
                "scenario_family": family,
                "scenarios_total": len(rows),
                "memory_backed_wins": sum(1 for row in rows if row["winner"] == "memory_backed"),
                "top_layer_matches": sum(1 for row in rows if row["top_layer_match"]),
            }
            for family, rows in sorted(by_family.items())
        ],
    }


def _biggest_gap(gap_counts: Counter[str]) -> str | list[str] | None:
    filtered = {key: value for key, value in gap_counts.items() if key != "overreach_in_no_value_case" and value > 0}
    if not filtered:
        return None
    highest = max(filtered.values())
    winners = sorted(key for key, value in filtered.items() if value == highest)
    if len(winners) == 1:
        return winners[0]
    return winners


def _gap_implication(biggest_gap: str | list[str] | None) -> str | None:
    if biggest_gap is None:
        return None
    if isinstance(biggest_gap, list):
        return "Multiple gap signals tied for the highest score, so the next slice should stay benchmark-guided rather than assuming one missing capability."
    return GAP_IMPLICATIONS.get(biggest_gap)


def _build_report(*, summary: dict[str, Any], results: list[dict[str, Any]]) -> str:
    lines = [
        "# Work Resumption Benchmark Report",
        "",
        f"Run ID: `{summary['run_id']}`",
        "",
        "## Scenario Families Added",
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
            f"- top-layer matches: {summary['top_layer_matches']} / {summary['scenarios_total']}",
            f"- non-value guard successes: {summary['non_value_guard_successes']} / {summary['non_value_scenarios']}",
            f"- highest-scoring gap signal: {summary['biggest_gap'] or 'none'}",
        ]
    )
    if summary["biggest_gap_implication"]:
        lines.append(f"- current implication: {summary['biggest_gap_implication']}")

    lines.append("- note: the gap rollup is hypothesis-driven because scenario-authored `dimension_gap_targets` contribute to it.")
    lines.extend(["", "## Gap Signals", ""])
    if not summary["gap_signal_counts"]:
        lines.append("- none")
    else:
        for gap, count in sorted(summary["gap_signal_counts"].items()):
            lines.append(f"- `{gap}`: {count}")

    lines.extend(["", "## Scenario Results", ""])
    for row in results:
        lines.append(
            f"- `{row['scenario_id']}`: winner `{row['winner']}`, top layer `{row['top_layer']}`, "
            f"missing after memory {row['missing_dimensions_after_memory'] or 'none'}, gap signals {row['gap_signals'] or 'none'}"
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
    return json.loads(path.read_text(encoding="utf-8"))


def _build_run_id(config: AppConfig, consolidation_strategy: str | None) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    provider = (config.llm_provider_for_default_use_case or "provider").replace("_", "-")
    model = (config.llm_model_for_default_use_case or "model").replace("/", "-").replace(".", "-")
    strategy_suffix = f"__{consolidation_strategy}" if consolidation_strategy else ""
    return f"work-resumption-benchmark__{provider}__{model}{strategy_suffix}__{timestamp}"


if __name__ == "__main__":
    raise SystemExit(main())

