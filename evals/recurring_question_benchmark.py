from __future__ import annotations

import argparse
import json
import re
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


DEFAULT_SCENARIO_FILE = Path("evals/recurring_question/scenarios.json")
DEFAULT_OUTPUT_DIR = Path("evals/recurring_question/output")
ANSWER_SCHEMA = '{"answer":"string","evidence_used":["string"]}'
TARGET_KEYWORD_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "already",
    "answered",
    "do",
    "have",
    "how",
    "is",
    "it",
    "of",
    "or",
    "the",
    "this",
    "to",
    "we",
    "why",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the recurring-question value benchmark.")
    parser.add_argument("--scenario-file", type=Path, default=DEFAULT_SCENARIO_FILE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-name", default=None)
    parser.add_argument("--consolidation-strategy", default=None)
    args = parser.parse_args()

    run_dir = run_recurring_question_benchmark(
        scenario_file=args.scenario_file,
        output_root=args.output_dir,
        config=AppConfig.from_env(),
        run_name=args.run_name,
        consolidation_strategy=args.consolidation_strategy,
    )
    print(run_dir)
    return 0


def run_recurring_question_benchmark(
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

    summary = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scenario_file": str(scenario_file),
        "results_file": results_path.name,
        "provider": config.llm_provider_for_default_use_case,
        "model": config.llm_model_for_default_use_case,
        "prompt_variant": config.llm_prompt_variant_for_default_use_case,
        "consolidation_strategy": consolidation_strategy,
        "scenarios_total": len(scenarios),
        "value_scenarios": 0,
        "non_value_scenarios": 0,
        "memory_backed_wins": 0,
        "non_value_memory_not_winner": 0,
    }

    with results_path.open("w", encoding="utf-8") as results_file:
        for scenario in scenarios:
            result = _run_scenario(
                scenario=scenario,
                config=config,
                answer_provider=provider,
                consolidation_strategy=consolidation_strategy,
            )
            if result["expected_value"]:
                summary["value_scenarios"] += 1
                if result["winner"] == "memory_backed":
                    summary["memory_backed_wins"] += 1
            else:
                summary["non_value_scenarios"] += 1
                if result["winner"] != "memory_backed":
                    summary["non_value_memory_not_winner"] += 1
            results_file.write(json.dumps(result) + "\n")

    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return run_dir


def _run_scenario(
    *,
    scenario: dict[str, Any],
    config: AppConfig,
    answer_provider: LLMProvider,
    consolidation_strategy: str | None,
) -> dict[str, Any]:
    with TemporaryDirectory() as temp_dir:
        database_url = f"sqlite:///{Path(temp_dir) / 'recurring-question.db'}"
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

            query_response = client.post("/query", json=scenario["current_query"])
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

    memory_hits = [item for item in memory_payload["results"] if item["result_kind"] == "memory_hit"]
    returned_memory_types = sorted({item["type"] for item in memory_hits if item.get("type")})
    expected_memory_types = scenario.get("expected_memory_types", [])
    expected_memory_types_found = all(item in returned_memory_types for item in expected_memory_types)

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
        baseline_rubric=baseline_rubric,
        memory_rubric=memory_rubric,
        baseline_answer=baseline_answer,
        memory_answer=memory_answer,
        expected_failures_without_memory=scenario.get("expected_failures_without_memory", []),
    )

    return {
        "scenario_id": scenario["scenario_id"],
        "scenario_kind": scenario["scenario_kind"],
        "description": scenario["description"],
        "expected_value": bool(scenario.get("expected_value")),
        "expected_memory_types": expected_memory_types,
        "expected_memory_types_found": expected_memory_types_found,
        "expected_non_value_reason": scenario.get("expected_non_value_reason"),
        "baseline_context": scenario.get("current_thread_context", []),
        "memory_backed_retrieval": memory_payload["results"],
        "returned_memory_types": returned_memory_types,
        "consolidation_strategy": consolidation_strategy,
        "consolidation_run": _serialize_consolidation_result(consolidation_result),
        "baseline_answer": baseline_answer,
        "memory_backed_answer": memory_answer,
        "rubric": {
            "baseline": baseline_rubric,
            "memory_backed": memory_rubric,
            "comparison": comparison,
        },
        "winner": comparison["winner"],
        "why": comparison["why"],
    }


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
                "created_pattern_memory_ids": list(group.created_pattern_memory_ids),
                "superseded_pattern_memory_ids": list(group.superseded_pattern_memory_ids),
            }
            for group in result.groups
        ],
    }


def _generate_answer(
    *,
    answer_provider: LLMProvider,
    target_question: str,
    current_thread_context: list[dict[str, Any]],
    memory_backed_results: list[dict[str, Any]],
    branch: str,
) -> dict[str, Any]:
    system_prompt = (
        "You answer downstream support questions using only the supplied context. "
        "Return exactly one JSON object and no extra prose. Keep the answer concise, evidence-aware, and avoid speculation."
    )
    context_text = _format_current_thread_context(current_thread_context)
    memory_text = _format_memory_results(memory_backed_results)
    user_prompt = (
        f"Branch: {branch}\n"
        f"Target question: {target_question}\n\n"
        f"Current thread context:\n{context_text}\n\n"
        f"Prior memory results:\n{memory_text}\n\n"
        "Return JSON with:\n"
        "- answer: a concise answer to the target question using only the supplied context\n"
        "- evidence_used: a short list of prior conclusions or evidence actually used, or an empty list if none\n"
        "If the current-thread context is already sufficient, answer from it without inventing older memory."
    )
    response = answer_provider.generate_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        schema_description=ANSWER_SCHEMA,
    )
    parsed = response.parsed_json
    answer = str(parsed.get("answer", "")).strip()
    evidence_used = parsed.get("evidence_used") or []
    if not isinstance(evidence_used, list):
        evidence_used = []
    normalized_evidence = [str(item).strip() for item in evidence_used if str(item).strip()]
    return {
        "answer": answer,
        "evidence_used": normalized_evidence,
        "raw_text": response.raw_text,
    }


def _score_answer(
    *,
    answer_payload: dict[str, Any],
    target_question: str,
    expected_answer_signals: list[str],
    scenario_kind: str,
) -> dict[str, Any]:
    answer_text = str(answer_payload.get("answer", ""))
    evidence_text = " ".join(str(item) for item in answer_payload.get("evidence_used", []))
    signal_matches = _find_signal_matches(answer_text, evidence_text, expected_answer_signals)
    directness = _score_directness(answer_text, target_question)
    memory_carry_forward = _score_signal_coverage(signal_matches, expected_answer_signals)
    evidence_grounding = _score_evidence_grounding(answer_payload.get("evidence_used", []), signal_matches)
    noise = _score_noise(answer_text)
    consistency = _score_consistency(scenario_kind, signal_matches, expected_answer_signals)
    total = directness + memory_carry_forward + evidence_grounding + noise + consistency

    return {
        "directness": directness,
        "memory_carry_forward": memory_carry_forward,
        "evidence_grounding": evidence_grounding,
        "noise": noise,
        "consistency": consistency,
        "total": total,
        "signal_matches": signal_matches,
    }


def _compare_answers(
    *,
    expected_value: bool,
    expected_memory_types_found: bool,
    baseline_rubric: dict[str, Any],
    memory_rubric: dict[str, Any],
    baseline_answer: dict[str, Any],
    memory_answer: dict[str, Any],
    expected_failures_without_memory: list[str],
) -> dict[str, Any]:
    baseline_total = int(baseline_rubric["total"])
    memory_total = int(memory_rubric["total"])
    baseline_missing = [signal for signal in expected_failures_without_memory if signal.lower() not in _combined_text(baseline_answer)]
    memory_has_expected = [signal for signal in expected_failures_without_memory if signal.lower() in _combined_text(memory_answer)]

    memory_advantage = 0
    if memory_total > baseline_total:
        memory_advantage += 1
    if len(memory_rubric["signal_matches"]) > len(baseline_rubric["signal_matches"]):
        memory_advantage += 1
    if expected_value and expected_memory_types_found and memory_has_expected:
        memory_advantage += 1

    if expected_value and memory_advantage >= 2:
        winner = "memory_backed"
        delta = 2
        why = "Memory-backed answer carried forward the expected prior conclusion more clearly than baseline."
    elif not expected_value and memory_advantage == 0:
        winner = "baseline"
        delta = 2
        why = "Current-thread context was already sufficient, so memory-backed context did not materially improve the answer."
    elif memory_total == baseline_total:
        winner = "tie"
        delta = 1
        why = "Both branches were comparably strong for this scenario."
    elif memory_total > baseline_total:
        winner = "memory_backed"
        delta = 1
        why = "Memory-backed answer was somewhat stronger, but the improvement was limited."
    else:
        winner = "baseline"
        delta = 0
        why = "Baseline answer remained stronger for this scenario."

    return {
        "delta": delta,
        "winner": winner,
        "why": why,
        "baseline_notes": _build_notes(baseline_rubric, baseline_missing),
        "memory_backed_notes": _build_notes(memory_rubric, memory_has_expected),
    }


def _find_signal_matches(answer_text: str, evidence_text: str, expected_signals: list[str]) -> list[str]:
    combined = f"{answer_text}\n{evidence_text}".lower()
    return [signal for signal in expected_signals if signal.lower() in combined]


def _score_directness(answer_text: str, target_question: str) -> int:
    if not answer_text.strip():
        return 0
    keywords = _extract_keywords(target_question)
    if keywords and any(keyword in answer_text.lower() for keyword in keywords):
        return 2
    return 1


def _score_signal_coverage(matches: list[str], expected_signals: list[str]) -> int:
    if not expected_signals:
        return 1 if matches else 0
    if len(matches) == len(expected_signals):
        return 2
    if matches:
        return 1
    return 0


def _score_evidence_grounding(evidence_used: list[str], signal_matches: list[str]) -> int:
    if evidence_used and signal_matches:
        return 2
    if evidence_used:
        return 1
    return 0


def _score_noise(answer_text: str) -> int:
    words = len(answer_text.split())
    if words <= 60:
        return 2
    if words <= 120:
        return 1
    return 0


def _score_consistency(scenario_kind: str, matches: list[str], expected_signals: list[str]) -> int:
    if scenario_kind == "repeated_answer_value":
        return _score_signal_coverage(matches, expected_signals)
    return 1 if matches else 0


def _build_notes(rubric: dict[str, Any], signal_list: list[str]) -> str:
    matched = ", ".join(rubric.get("signal_matches", [])) or "none"
    extra = ", ".join(signal_list) or "none"
    return f"matched signals: {matched}; expected emphasis present/missing: {extra}"


def _extract_keywords(question: str) -> list[str]:
    tokens = [token.lower() for token in re.findall(r"[a-zA-Z]{4,}", question)]
    return [token for token in tokens if token not in TARGET_KEYWORD_STOPWORDS]


def _combined_text(answer_payload: dict[str, Any]) -> str:
    return f"{answer_payload.get('answer', '')}\n{' '.join(answer_payload.get('evidence_used', []))}".lower()


def _format_current_thread_context(context: list[dict[str, Any]]) -> str:
    if not context:
        return "- none"
    lines = []
    for item in context:
        role = item.get("role", "unknown")
        artifact_kind = item.get("artifact_kind", "unknown")
        content = str(item.get("content", "")).strip()
        lines.append(f"- {role}/{artifact_kind}: {content}")
    return "\n".join(lines)


def _format_memory_results(results: list[dict[str, Any]]) -> str:
    if not results:
        return "- none"
    lines: list[str] = []
    for item in results[:4]:
        if item.get("result_kind") == "memory_hit":
            payload = item.get("payload") or {}
            summary = payload.get("decision") or payload.get("investigation_outcome") or payload.get("summary") or json.dumps(payload)
            lines.append(f"- memory/{item.get('type')}: {summary}")
        else:
            lines.append(f"- source/{item.get('source_type')}:{item.get('source_id')}: {item.get('excerpt')}")
    return "\n".join(lines)


def _load_scenarios(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_run_id(config: AppConfig, consolidation_strategy: str | None) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    provider = (config.llm_provider_for_default_use_case or "provider").replace("_", "-")
    model = (config.llm_model_for_default_use_case or "model").replace("/", "-").replace(".", "-")
    strategy_suffix = f"__{consolidation_strategy}" if consolidation_strategy else ""
    return f"recurring-question-benchmark__{provider}__{model}{strategy_suffix}__{timestamp}"


if __name__ == "__main__":
    raise SystemExit(main())

