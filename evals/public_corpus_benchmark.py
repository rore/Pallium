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
from evals.public_corpus_builder import DEFAULT_REVIEW_MANIFEST, build_reviewed_episodes, load_review_manifest, load_wildchat_conversations
from evals.recurring_question_benchmark import _compare_answers, _generate_answer, _score_answer
from providers.llm.base import LLMProvider

DEFAULT_OUTPUT_DIR = Path("evals/public_corpus/output")
HIGHER_LEVEL_LAYERS = {"pattern_memory", "continuity_memory"}
FAILURE_FAMILIES = (
    "retrieval_recall_failure",
    "routing_layer_choice_failure",
    "result_packaging_evidence_failure",
    "overreach_no_value_failure",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the reviewed public-corpus benchmark over a local WildChat export.")
    parser.add_argument("--corpus-file", type=Path, required=True)
    parser.add_argument("--reviewed-manifest", type=Path, default=DEFAULT_REVIEW_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-name", default=None)
    parser.add_argument("--consolidation-strategy", default="thread_summary_anchored")
    args = parser.parse_args()

    run_dir = run_public_corpus_benchmark(
        corpus_file=args.corpus_file,
        reviewed_manifest=args.reviewed_manifest,
        output_root=args.output_dir,
        config=AppConfig.from_env(),
        run_name=args.run_name,
        default_consolidation_strategy=args.consolidation_strategy,
    )
    print(run_dir)
    return 0


def run_public_corpus_benchmark(
    *,
    corpus_file: Path,
    reviewed_manifest: Path,
    output_root: Path,
    config: AppConfig,
    run_name: str | None = None,
    answer_provider: LLMProvider | None = None,
    default_consolidation_strategy: str | None = "thread_summary_anchored",
) -> Path:
    manifest = load_review_manifest(reviewed_manifest)
    conversations = load_wildchat_conversations(corpus_file)
    episodes = build_reviewed_episodes(conversations=conversations, manifest=manifest)

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
    with results_path.open("w", encoding="utf-8") as handle:
        for episode in episodes:
            result = _run_episode(
                episode=episode,
                config=config,
                answer_provider=provider,
                default_consolidation_strategy=default_consolidation_strategy,
            )
            results.append(result)
            handle.write(json.dumps(result) + "\n")

    summary = _build_summary(
        results=results,
        manifest=manifest,
        corpus_file=corpus_file,
        reviewed_manifest=reviewed_manifest,
        config=config,
        run_id=run_id,
        results_file=results_path.name,
    )
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (run_dir / "report.md").write_text(_build_report(summary=summary, results=results), encoding="utf-8")
    return run_dir


def _run_episode(
    *,
    episode: dict[str, Any],
    config: AppConfig,
    answer_provider: LLMProvider,
    default_consolidation_strategy: str | None,
) -> dict[str, Any]:
    consolidation_strategy = episode.get("consolidation_strategy") or default_consolidation_strategy
    with TemporaryDirectory() as temp_dir:
        database_url = f"sqlite:///{Path(temp_dir) / 'public-corpus.db'}"
        scenario_config = replace(config, sqlite_url=database_url, default_use_case="agent_conversation_memory")
        with TestClient(create_app(scenario_config)) as client:
            for event in episode.get("prior_events", []):
                response = client.post("/items", json=event)
                response.raise_for_status()

            consolidation_result = None
            if consolidation_strategy:
                consolidation_result = client.app.state.pallium_service.run_consolidation_pass(
                    use_case="agent_conversation_memory",
                    strategy_name=consolidation_strategy,
                )

            query_response = client.post("/query/debug", json=episode["current_query"])
            query_response.raise_for_status()
            memory_payload = query_response.json()
            engine = getattr(client.app.state.pallium_service._storage, "_engine", None)
            if engine is not None:
                engine.dispose()

    baseline_answer = _generate_answer(
        answer_provider=answer_provider,
        target_question=episode["target_question"],
        current_thread_context=episode.get("current_thread_context", []),
        memory_backed_results=[],
        branch="baseline",
    )
    memory_answer = _generate_answer(
        answer_provider=answer_provider,
        target_question=episode["target_question"],
        current_thread_context=episode.get("current_thread_context", []),
        memory_backed_results=memory_payload["results"],
        branch="memory_backed",
    )

    memory_hits = [item for item in memory_payload["results"] if item.get("result_kind") == "memory_hit"]
    returned_memory_types = sorted({item.get("type") for item in memory_hits if item.get("type")})
    higher_level_memory_types = sorted(item for item in returned_memory_types if item in HIGHER_LEVEL_LAYERS)
    routing = ((memory_payload.get("trace") or {}).get("routing") or {})
    top_result = memory_payload["results"][0] if memory_payload["results"] else None
    top_layer = _result_layer(top_result)
    available_layers = sorted({_result_layer(item) for item in memory_payload["results"]})

    expected_winning_layer = episode.get("expected_winning_layer")
    acceptable_winning_layers = episode.get("acceptable_winning_layers") or ([expected_winning_layer] if expected_winning_layer else [])
    expected_memory_types = episode.get("expected_memory_types", [])
    expected_higher_level_memory_types = episode.get("expected_higher_level_memory_types", [])
    expected_memory_types_found = all(item in returned_memory_types for item in expected_memory_types)
    expected_higher_level_memory_types_found = all(item in higher_level_memory_types for item in expected_higher_level_memory_types)
    expected_layer_found = (expected_winning_layer in available_layers) if expected_winning_layer else False
    top_layer_match = top_layer in acceptable_winning_layers if acceptable_winning_layers else True

    baseline_rubric = _score_answer(
        answer_payload=baseline_answer,
        target_question=episode["target_question"],
        expected_answer_signals=episode.get("expected_answer_signals", []),
        scenario_kind=episode["episode_type"],
    )
    memory_rubric = _score_answer(
        answer_payload=memory_answer,
        target_question=episode["target_question"],
        expected_answer_signals=episode.get("expected_answer_signals", []),
        scenario_kind=episode["episode_type"],
    )
    comparison = _compare_answers(
        expected_value=bool(episode.get("should_memory_help")),
        expected_memory_types_found=expected_memory_types_found,
        expected_higher_level_memory_types_found=expected_higher_level_memory_types_found,
        baseline_rubric=baseline_rubric,
        memory_rubric=memory_rubric,
        baseline_answer=baseline_answer,
        memory_answer=memory_answer,
        expected_failures_without_memory=episode.get("expected_answer_signals", []),
    )
    winner = comparison["winner"]
    evidence_used = memory_answer.get("evidence_used", [])
    evidence_used_present = bool(evidence_used)
    forbidden_terms_found = _find_forbidden_terms(
        forbidden_terms=episode.get("forbidden_terms", []),
        retrieval_results=memory_payload["results"],
        answer_payload=memory_answer,
    )

    failure_family = _classify_failure_family(
        should_memory_help=bool(episode.get("should_memory_help")),
        winner=winner,
        expected_layer_found=expected_layer_found,
        expected_memory_types_found=expected_memory_types_found,
        expected_higher_level_memory_types_found=expected_higher_level_memory_types_found,
        top_layer_match=top_layer_match,
        evidence_used_present=evidence_used_present,
        forbidden_terms_found=forbidden_terms_found,
    )
    policy_success = failure_family is None

    return {
        "episode_id": episode["episode_id"],
        "episode_type": episode["episode_type"],
        "description": episode["description"],
        "corpus_name": episode["corpus_name"],
        "source_conversation_ids": episode["source_conversation_ids"],
        "target_conversation_id": episode["target_conversation_id"],
        "should_memory_help": bool(episode.get("should_memory_help")),
        "expected_winning_layer": expected_winning_layer,
        "acceptable_winning_layers": acceptable_winning_layers,
        "expected_memory_types": expected_memory_types,
        "expected_higher_level_memory_types": expected_higher_level_memory_types,
        "consolidation_strategy": consolidation_strategy,
        "routing_intent": routing.get("query_intent"),
        "routing_preferred_layers": routing.get("preferred_layers", []),
        "top_layer": top_layer,
        "available_layers": available_layers,
        "returned_memory_types": returned_memory_types,
        "higher_level_memory_types": higher_level_memory_types,
        "expected_layer_found": expected_layer_found,
        "expected_memory_types_found": expected_memory_types_found,
        "expected_higher_level_memory_types_found": expected_higher_level_memory_types_found,
        "top_layer_match": top_layer_match,
        "evidence_used_present": evidence_used_present,
        "forbidden_terms_found": forbidden_terms_found,
        "failure_family": failure_family,
        "policy_success": policy_success,
        "query_trace": memory_payload.get("trace"),
        "memory_backed_retrieval": memory_payload["results"],
        "baseline_answer": baseline_answer,
        "memory_backed_answer": memory_answer,
        "winner": winner,
        "why": comparison["why"],
        "rubric": {
            "baseline": baseline_rubric,
            "memory_backed": memory_rubric,
            "comparison": comparison,
        },
        "consolidation_run": _serialize_consolidation_result(consolidation_result),
    }


def _classify_failure_family(
    *,
    should_memory_help: bool,
    winner: str,
    expected_layer_found: bool,
    expected_memory_types_found: bool,
    expected_higher_level_memory_types_found: bool,
    top_layer_match: bool,
    evidence_used_present: bool,
    forbidden_terms_found: list[str],
) -> str | None:
    if forbidden_terms_found:
        return "overreach_no_value_failure"
    if not should_memory_help:
        return None if winner != "memory_backed" else "overreach_no_value_failure"
    if not expected_layer_found and not expected_memory_types_found and not expected_higher_level_memory_types_found:
        return "retrieval_recall_failure"
    if not top_layer_match:
        return "routing_layer_choice_failure"
    if winner != "memory_backed" or not evidence_used_present:
        return "result_packaging_evidence_failure"
    return None


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


def _find_forbidden_terms(*, forbidden_terms: list[str], retrieval_results: list[dict[str, Any]], answer_payload: dict[str, Any]) -> list[str]:
    if not forbidden_terms:
        return []
    combined = json.dumps(retrieval_results).lower() + "\n" + json.dumps(answer_payload).lower()
    return [term for term in forbidden_terms if term.lower() in combined]


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


def _build_summary(
    *,
    results: list[dict[str, Any]],
    manifest: dict[str, Any],
    corpus_file: Path,
    reviewed_manifest: Path,
    config: AppConfig,
    run_id: str,
    results_file: str,
) -> dict[str, Any]:
    failure_counter = Counter(row["failure_family"] for row in results if row["failure_family"])
    by_episode_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in results:
        by_episode_type[row["episode_type"]].append(row)

    summary: dict[str, Any] = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "corpus_file": str(corpus_file),
        "reviewed_manifest": str(reviewed_manifest),
        "results_file": results_file,
        "provider": config.llm_provider_for_default_use_case,
        "model": config.llm_model_for_default_use_case,
        "prompt_variant": config.llm_prompt_variant_for_default_use_case,
        "corpus_name": manifest.get("corpus_name", "wildchat"),
        "episodes_total": len(results),
        "should_memory_help_total": sum(1 for row in results if row["should_memory_help"]),
        "no_value_guard_total": sum(1 for row in results if not row["should_memory_help"]),
        "memory_backed_wins": sum(1 for row in results if row["winner"] == "memory_backed"),
        "policy_successes": sum(1 for row in results if row["policy_success"]),
        "failure_families": {name: int(failure_counter.get(name, 0)) for name in FAILURE_FAMILIES},
        "by_episode_type": [],
    }
    for episode_type in sorted(by_episode_type):
        rows = by_episode_type[episode_type]
        summary["by_episode_type"].append(
            {
                "episode_type": episode_type,
                "episodes_total": len(rows),
                "policy_successes": sum(1 for row in rows if row["policy_success"]),
                "memory_backed_wins": sum(1 for row in rows if row["winner"] == "memory_backed"),
                "failure_families": {
                    name: sum(1 for row in rows if row["failure_family"] == name)
                    for name in FAILURE_FAMILIES
                },
            }
        )
    return summary


def _build_report(*, summary: dict[str, Any], results: list[dict[str, Any]]) -> str:
    lines = [
        "# Public Corpus Benchmark Report",
        "",
        f"Run ID: `{summary['run_id']}`",
        "",
        "## Aggregate",
        "",
        f"- episodes: {summary['episodes_total']}",
        f"- should-memory-help: {summary['should_memory_help_total']}",
        f"- no-value-guards: {summary['no_value_guard_total']}",
        f"- memory-backed wins: {summary['memory_backed_wins']}",
        f"- policy successes: {summary['policy_successes']} / {summary['episodes_total']}",
        "",
        "## Failure Families",
        "",
    ]
    for name, count in summary["failure_families"].items():
        lines.append(f"- `{name}`: {count}")
    lines.extend(["", "## Episode Results", ""])
    for row in results:
        status = "PASS" if row["policy_success"] else f"FAIL ({row['failure_family']})"
        lines.append(
            f"- `{row['episode_id']}` [{status}]: winner `{row['winner']}`, "
            f"expected layer `{row['expected_winning_layer']}`, top layer `{row['top_layer']}`"
        )
    return "\n".join(lines) + "\n"


def _build_run_id(config: AppConfig) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    provider = (config.llm_provider_for_default_use_case or "provider").replace("_", "-")
    model = (config.llm_model_for_default_use_case or "model").replace("/", "-").replace(".", "-")
    return f"public-corpus-benchmark__{provider}__{model}__{timestamp}"


if __name__ == "__main__":
    raise SystemExit(main())
