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
from evals.benchmark_architecture import annotate_result, build_suite_summary
from evals.continuity_common import (
    CONTINUITY_FAILURE_FAMILIES,
    HIGHER_LEVEL_LAYERS,
    PARAPHRASE_OR_INDIRECT_QUERY_LABELS,
    default_injection_expectations,
    evaluate_query_contract,
    query_family_from_intent,
    result_layer,
)
from semantic.agent_conversation_memory_routing import is_query_topic_signal_empty
from evals.public_corpus_builder import (
    DEFAULT_REVIEW_MANIFEST,
    build_reviewed_episodes,
    load_public_corpus_conversations,
    load_review_manifest,
)
from evals.recurring_question_benchmark import _compare_answers, _generate_answer, _score_answer
from providers.llm.base import LLMProvider

DEFAULT_OUTPUT_DIR = Path("evals/public_corpus/output")
TASK_STATE_PRESERVE_MARKERS = {"blocker_state", "preserved_progress", "next_step_guidance", "freshness"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the reviewed public-corpus benchmark over a local public benchmark export.")
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
    corpus_name = str(manifest.get("corpus_name", "wildchat"))
    conversations = load_public_corpus_conversations(corpus_file, corpus_name=corpus_name)
    episodes = build_reviewed_episodes(conversations=conversations, manifest=manifest)

    default_package = config.package_config(config.default_use_case)
    if answer_provider is None:
        if not default_package.llm_provider or not default_package.model:
            raise ValueError(f"Default use case '{config.default_use_case}' is missing LLM package config")
        provider = build_llm_provider(config, provider_name=default_package.llm_provider, model=default_package.model)
    else:
        provider = answer_provider

    run_id = run_name or _build_run_id(config, corpus_name=corpus_name)
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    results_path = run_dir / "results.jsonl"

    results: list[dict[str, Any]] = []
    with results_path.open("w", encoding="utf-8") as handle:
        for episode in episodes:
            result = annotate_result(
                _run_episode(
                    episode=episode,
                    config=config,
                    answer_provider=provider,
                    default_consolidation_strategy=default_consolidation_strategy,
                ),
                suite_id="public_corpus",
                dataset_tier=episode.get("dataset_tier"),
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
    runtime_context = _episode_runtime_context(episode)
    query_request = dict(episode["current_query"])
    query_request.setdefault("runtime_context", runtime_context)
    with TemporaryDirectory() as temp_dir:
        database_url = f"sqlite:///{Path(temp_dir) / 'public-corpus.db'}"
        vector_index_config = replace(config.vector_index, index_path=str(Path(temp_dir) / "vector.index"))
        scenario_config = replace(config, sqlite_url=database_url, default_use_case="agent_conversation_memory", vector_index=vector_index_config)
        with TestClient(create_app(scenario_config)) as client:
            for event in episode.get("prior_events", []):
                response = client.post("/items", json=[_with_default_visibility(event)])
                response.raise_for_status()
            client.app.state.pallium_service.drain_processing_queue(worker_id="public-corpus-runner")

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
    routing_intent = routing.get("query_intent")
    query_family = routing.get("query_family") or query_family_from_intent(
        routing_intent,
        runtime_context=runtime_context,
        should_memory_help=bool(episode.get("should_memory_help")),
    )
    top_result = memory_payload["results"][0] if memory_payload["results"] else None
    top_layer = result_layer(top_result)
    available_layers = sorted({result_layer(item) for item in memory_payload["results"]})

    expected_intent = episode.get("expected_intent")
    intent_match = routing_intent == expected_intent if expected_intent else True
    expected_primary_layer = episode.get("expected_primary_layer") or episode.get("expected_winning_layer")
    acceptable_layers = list(episode.get("acceptable_layers") or [])
    if not acceptable_layers:
        acceptable_layers = list(episode.get("acceptable_winning_layers") or ([expected_primary_layer] if expected_primary_layer else []))
    acceptable_fallback_layers = list(episode.get("acceptable_fallback_layers") or [])
    if not acceptable_fallback_layers and acceptable_layers and expected_primary_layer:
        acceptable_fallback_layers = [layer for layer in acceptable_layers if layer != expected_primary_layer]
    forbidden_layers = list(episode.get("forbidden_layers") or [])
    forbidden_layers_hit = [layer for layer in forbidden_layers if layer == top_layer]

    expected_memory_types = episode.get("expected_memory_types", [])
    expected_higher_level_memory_types = episode.get("expected_higher_level_memory_types", [])
    expected_memory_types_found = all(item in returned_memory_types for item in expected_memory_types)
    expected_higher_level_memory_types_found = all(item in higher_level_memory_types for item in expected_higher_level_memory_types)
    expected_layer_in_results = (expected_primary_layer in available_layers) if expected_primary_layer else False
    raw_query_tokens = tuple(((memory_payload.get("trace") or {}).get("query_tokens")) or [])
    query_topic_tokens_empty = is_query_topic_signal_empty(raw_query_tokens)
    top_layer_match = top_layer in acceptable_layers if acceptable_layers else True
    query_family_match = query_family == episode.get("expected_query_family") if episode.get("expected_query_family") else True

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
    guard_matches = _guard_term_matches(
        guard_terms=episode.get("guard_terms", {}),
        top_result=top_result,
        answer_payload=memory_answer,
    )

    injection_expectations = default_injection_expectations(
        should_memory_help=bool(episode.get("should_memory_help")),
        runtime_context=runtime_context,
        expected_primary_layer=expected_primary_layer,
        expected_memory_types=expected_memory_types,
        acceptable_fallback_layers=acceptable_fallback_layers,
        forbidden_layers=forbidden_layers,
        expected_should_inject=episode.get("expected_should_inject"),
        expected_decision_reason=episode.get("expected_decision_reason"),
        acceptable_decision_reasons=list(episode.get("acceptable_decision_reasons") or []),
        expected_primary_block_types=list(episode.get("expected_primary_injected_block_types") or []),
        acceptable_fallback_block_types=list(episode.get("acceptable_fallback_block_types") or []),
        forbidden_block_types=list(episode.get("forbidden_block_types") or []),
        acceptable_injected_block_count=episode.get("acceptable_injected_block_count"),
        expected_cap_behavior=episode.get("expected_cap_behavior"),
    )
    query_contract = evaluate_query_contract(
        query_payload=query_contract_payload,
        debug_payload=memory_payload,
        **injection_expectations,
    )

    failure_families = _classify_failure_families(
        should_memory_help=bool(episode.get("should_memory_help")),
        winner=winner,
        expected_layer_in_results=expected_layer_in_results,
        expected_memory_types_found=expected_memory_types_found,
        expected_higher_level_memory_types_found=expected_higher_level_memory_types_found,
        higher_level_expectation_present=bool(expected_higher_level_memory_types),
        intent_match=intent_match,
        query_family_match=query_family_match,
        top_layer_match=top_layer_match,
        forbidden_layers_hit=forbidden_layers_hit,
        evidence_used_present=evidence_used_present,
        forbidden_terms_found=forbidden_terms_found,
        guard_matches=guard_matches,
        expected_primary_layer=expected_primary_layer,
        must_preserve=episode.get("must_preserve", []),
        query_wording_label=episode.get("query_wording_label") or _episode_query_wording_label(episode),
        injection_contract=query_contract["injection_contract"],
    )
    failure_family = failure_families[0] if failure_families else None
    policy_success = not failure_families
    no_value_guard_success = (not bool(episode.get("should_memory_help"))) and "no_value_overreach_failure" not in failure_families
    stale_guard_success = (
        "stale_state" not in episode.get("must_not_introduce", [])
        or "stale_memory_failure" not in failure_families
    )
    wrong_memory_guard_success = (
        "wrong_thread_state" not in episode.get("must_not_introduce", [])
        or "wrong_memory_selection_failure" not in failure_families
    )
    privacy_guard_success = (
        "privacy_leak" not in episode.get("must_not_introduce", [])
        or "privacy_leak_failure" not in failure_families
    )
    thin_agent_boundary_success = "thin_agent_boundary_failure" not in failure_families

    labels = {
        "scenario_family": episode.get("scenario_family", episode["episode_type"]),
        "query_family": episode.get("expected_query_family") or query_family_from_intent(expected_intent, runtime_context=runtime_context, should_memory_help=bool(episode.get("should_memory_help"))),
        "query_wording_label": episode.get("query_wording_label") or _episode_query_wording_label(episode),
        "should_memory_help": bool(episode.get("should_memory_help")),
        "expected_intent": expected_intent,
        "expected_primary_layer": expected_primary_layer,
        "acceptable_fallback_layers": acceptable_fallback_layers,
        "forbidden_layers": forbidden_layers,
        "must_preserve": list(episode.get("must_preserve", [])),
        "must_not_introduce": list(episode.get("must_not_introduce", [])),
        "expected_should_inject": injection_expectations["expected_should_inject"],
        "expected_decision_reason": injection_expectations["expected_decision_reason"],
        "expected_primary_injected_block_types": injection_expectations["expected_primary_block_types"],
        "acceptable_fallback_block_types": injection_expectations["acceptable_fallback_block_types"],
        "forbidden_block_types": injection_expectations["forbidden_block_types"],
    }

    return {
        "episode_id": episode["episode_id"],
        "episode_type": episode["episode_type"],
        "scenario_family": episode.get("scenario_family", episode["episode_type"]),
        "description": episode["description"],
        "labels": labels,
        "corpus_name": episode["corpus_name"],
        "source_conversation_ids": episode["source_conversation_ids"],
        "target_conversation_id": episode["target_conversation_id"],
        "source_primary_tag": episode.get("source_primary_tag"),
        "source_secondary_tags": episode.get("source_secondary_tags", []),
        "source_intent": episode.get("source_intent"),
        "source_checklist_count": len(episode.get("source_checklist", [])),
        "runtime_context": runtime_context,
        "should_memory_help": bool(episode.get("should_memory_help")),
        "expected_query_family": labels["query_family"],
        "query_family": query_family,
        "query_family_match": query_family_match,
        "query_wording_label": labels["query_wording_label"],
        "expected_intent": expected_intent,
        "routing_intent": routing_intent,
        "intent_match": intent_match,
        "expected_primary_layer": expected_primary_layer,
        "acceptable_fallback_layers": acceptable_fallback_layers,
        "acceptable_layers": acceptable_layers,
        "forbidden_layers": forbidden_layers,
        "forbidden_layers_hit": forbidden_layers_hit,
        "expected_winning_layer": episode.get("expected_winning_layer"),
        "acceptable_winning_layers": episode.get("acceptable_winning_layers", acceptable_layers),
        "expected_memory_types": expected_memory_types,
        "expected_higher_level_memory_types": expected_higher_level_memory_types,
        "consolidation_strategy": consolidation_strategy,
        "routing_preferred_layers": routing.get("preferred_layers", []),
        "top_layer": top_layer,
        "available_layers": available_layers,
        "returned_memory_types": returned_memory_types,
        "higher_level_memory_types": higher_level_memory_types,
        "expected_layer_in_results": expected_layer_in_results,
        "query_topic_tokens_empty": query_topic_tokens_empty,
        "expected_memory_types_found": expected_memory_types_found,
        "expected_higher_level_memory_types_found": expected_higher_level_memory_types_found,
        "top_layer_match": top_layer_match,
        "evidence_used_present": evidence_used_present,
        "guard_matches": guard_matches,
        "forbidden_terms_found": forbidden_terms_found,
        "failure_family": failure_family,
        "failure_families": failure_families,
        "policy_success": policy_success,
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
        "winner": winner,
        "why": comparison["why"],
        "rubric": {
            "baseline": baseline_rubric,
            "memory_backed": memory_rubric,
            "comparison": comparison,
        },
        "consolidation_run": _serialize_consolidation_result(consolidation_result),
        "reference_answer": episode.get("reference_answer"),
        "source_checklist": episode.get("source_checklist", []),
        "no_value_guard_success": no_value_guard_success,
        "stale_guard_success": stale_guard_success,
        "wrong_memory_guard_success": wrong_memory_guard_success,
        "privacy_guard_success": privacy_guard_success,
        "thin_agent_boundary_success": thin_agent_boundary_success,
    }

def _episode_runtime_context(episode: dict[str, Any]) -> dict[str, Any]:
    explicit_runtime_context = episode.get("runtime_context") or (episode.get("current_query") or {}).get("runtime_context")
    if isinstance(explicit_runtime_context, dict):
        return dict(explicit_runtime_context)
    if not bool(episode.get("should_memory_help")) and bool(episode.get("overreach_guard")):
        return {
            "turn_kind": "same_thread_continuation",
            "session_has_sufficient_local_context": True,
        }
    if episode.get("episode_type") == "within_conversation_later_turn_recall":
        return {
            "turn_kind": "same_thread_continuation",
            "session_has_sufficient_local_context": False,
        }
    return {
        "turn_kind": "resumed_session",
        "session_has_sufficient_local_context": False,
    }


def _episode_query_wording_label(episode: dict[str, Any]) -> str:
    lowered = " ".join(
        [
            str(episode.get("description") or "").lower(),
            str(episode.get("review_notes") or "").lower(),
            str(episode.get("target_question") or "").lower(),
            str(episode.get("query_text") or "").lower(),
        ]
    )
    if "indirect" in lowered or "messy" in lowered or "weaker" in lowered:
        return "indirect"
    if "paraphrase" in lowered or "big picture" in lowered or "old handoff" in lowered:
        return "paraphrase"
    return "literal"



def _with_default_visibility(payload: dict[str, Any]) -> dict[str, Any]:
    updated = dict(payload)
    updated.setdefault("container_visibility", "public")
    return updated


def _classify_failure_families(
    *,
    should_memory_help: bool,
    winner: str,
    expected_layer_in_results: bool,
    expected_memory_types_found: bool,
    expected_higher_level_memory_types_found: bool,
    higher_level_expectation_present: bool,
    intent_match: bool,
    query_family_match: bool,
    top_layer_match: bool,
    forbidden_layers_hit: list[str],
    evidence_used_present: bool,
    forbidden_terms_found: list[str],
    guard_matches: dict[str, list[str]],
    expected_primary_layer: str | None,
    must_preserve: list[str],
    query_wording_label: str,
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

    if not should_memory_help:
        if winner == "memory_backed" or forbidden_terms_found or forbidden_layers_hit or any(guard_matches.values()) or injection_contract["should_inject_actual"]:
            failures.append("no_value_overreach_failure")
        if query_wording_label in PARAPHRASE_OR_INDIRECT_QUERY_LABELS and failures:
            failures.append("paraphrase_or_indirect_query_failure")
        return _ordered_failure_families(failures)

    if not expected_layer_in_results and not expected_memory_types_found and (not higher_level_expectation_present or not expected_higher_level_memory_types_found):
        failures.append("retrieval_recall_failure")
    if not intent_match or not query_family_match or not top_layer_match or forbidden_layers_hit:
        failures.append("routing_layer_choice_failure")
    if (
        winner != "memory_backed" or not evidence_used_present
    ) and "retrieval_recall_failure" not in failures and "routing_layer_choice_failure" not in failures:
        if expected_primary_layer == "task_checkpoint" or any(marker in TASK_STATE_PRESERVE_MARKERS for marker in must_preserve):
            failures.append("compact_task_state_failure")
        else:
            failures.append("result_packaging_evidence_failure")
    if query_wording_label in PARAPHRASE_OR_INDIRECT_QUERY_LABELS and (
        not intent_match
        or not query_family_match
        or not top_layer_match
        or winner != "memory_backed"
        or "injection_decision_failure" in failures
        or "injectability_packaging_failure" in failures
    ):
        failures.append("paraphrase_or_indirect_query_failure")
    return _ordered_failure_families(failures)
def _ordered_failure_families(families: list[str]) -> list[str]:
    unique = set(families)
    return [name for name in CONTINUITY_FAILURE_FAMILIES if name in unique]


def _find_forbidden_terms(*, forbidden_terms: list[str], retrieval_results: list[dict[str, Any]], answer_payload: dict[str, Any]) -> list[str]:
    if not forbidden_terms:
        return []
    combined = json.dumps(retrieval_results).lower() + "\n" + json.dumps(answer_payload).lower()
    return [term for term in forbidden_terms if term.lower() in combined]


def _guard_term_matches(*, guard_terms: dict[str, list[str]], top_result: dict[str, Any] | None, answer_payload: dict[str, Any]) -> dict[str, list[str]]:
    combined = _guard_haystack_from_result(top_result) + "\n" + json.dumps(answer_payload, sort_keys=True).lower()
    return {
        guard: [term for term in terms if term.lower() in combined]
        for guard, terms in guard_terms.items()
    }


def _guard_haystack_from_result(item: dict[str, Any] | None) -> str:
    if not item:
        return ""
    if item.get("result_kind") == "source_hit":
        return json.dumps({
            "result_kind": item.get("result_kind"),
            "source_type": item.get("source_type"),
            "source_id": item.get("source_id"),
            "excerpt": item.get("excerpt"),
        }, sort_keys=True).lower()
    payload = item.get("payload") or {}
    surfaced_payload = {
        key: payload.get(key)
        for key in (
            "summary",
            "carry_forward_answer",
            "decision",
            "investigation_outcome",
            "task",
            "current_state",
            "blocker_state",
            "next_step",
            "freshness_signal",
        )
        if payload.get(key) not in (None, "", [])
    }
    return json.dumps({
        "result_kind": item.get("result_kind"),
        "type": item.get("type"),
        "payload": surfaced_payload,
    }, sort_keys=True).lower()


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
    failure_counter: Counter[str] = Counter()
    by_episode_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_primary_tag: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_scenario_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in results:
        failure_counter.update(row.get("failure_families", []))
        by_episode_type[row["episode_type"]].append(row)
        by_primary_tag[row.get("source_primary_tag") or "unlabeled"].append(row)
        by_scenario_family[row.get("scenario_family") or row["episode_type"]].append(row)

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
        "intent_matches": sum(1 for row in results if row["intent_match"]),
        "query_family_matches": sum(1 for row in results if row["query_family_match"]),
        "query_contract_consistency_successes": sum(1 for row in results if row["query_contract_consistent"]),
        "injection_contract_successes": sum(1 for row in results if row["injection_contract"]["contract_success"]),
        "thin_agent_boundary_successes": sum(1 for row in results if row["thin_agent_boundary_success"]),
        "non_value_guard_successes": sum(1 for row in results if row["no_value_guard_success"]),
        "stale_guard_successes": sum(1 for row in results if row["stale_guard_success"]),
        "wrong_memory_guard_successes": sum(1 for row in results if row["wrong_memory_guard_success"]),
        "privacy_guard_successes": sum(1 for row in results if row["privacy_guard_success"]),
        "failure_families": {name: int(failure_counter.get(name, 0)) for name in CONTINUITY_FAILURE_FAMILIES},
        "scenario_families": sorted(by_scenario_family),
        "by_episode_type": [],
        "by_primary_tag": [],
        "by_scenario_family": [],
    }
    for episode_type in sorted(by_episode_type):
        rows = by_episode_type[episode_type]
        summary["by_episode_type"].append(
            {
                "episode_type": episode_type,
                "episodes_total": len(rows),
                "policy_successes": sum(1 for row in rows if row["policy_success"]),
                "memory_backed_wins": sum(1 for row in rows if row["winner"] == "memory_backed"),
                "injection_contract_successes": sum(1 for row in rows if row["injection_contract"]["contract_success"]),
                "failure_families": {
                    name: sum(1 for row in rows if name in row.get("failure_families", []))
                    for name in CONTINUITY_FAILURE_FAMILIES
                },
            }
        )
    for primary_tag in sorted(by_primary_tag):
        rows = by_primary_tag[primary_tag]
        summary["by_primary_tag"].append(
            {
                "primary_tag": primary_tag,
                "episodes_total": len(rows),
                "policy_successes": sum(1 for row in rows if row["policy_success"]),
                "failure_families": {
                    name: sum(1 for row in rows if name in row.get("failure_families", []))
                    for name in CONTINUITY_FAILURE_FAMILIES
                },
            }
        )
    for family in sorted(by_scenario_family):
        rows = by_scenario_family[family]
        summary["by_scenario_family"].append(
            {
                "scenario_family": family,
                "episodes_total": len(rows),
                "policy_successes": sum(1 for row in rows if row["policy_success"]),
                "injection_contract_successes": sum(1 for row in rows if row["injection_contract"]["contract_success"]),
                "failure_families": {
                    name: sum(1 for row in rows if name in row.get("failure_families", []))
                    for name in CONTINUITY_FAILURE_FAMILIES
                },
            }
        )
    summary["benchmark"] = build_suite_summary(
        suite_id="public_corpus",
        results=results,
        dataset_tier=str(manifest.get("dataset_tier", "confidence")),
    )
    return summary


def _build_report(*, summary: dict[str, Any], results: list[dict[str, Any]]) -> str:
    lines = [
        "# Public Corpus Benchmark Report",
        "",
        f"Run ID: `{summary['run_id']}`",
        f"Corpus: `{summary['corpus_name']}`",
        "",
        "## Aggregate",
        "",
        f"- episodes: {summary['episodes_total']}",
        f"- should-memory-help: {summary['should_memory_help_total']}",
        f"- no-value-guards: {summary['no_value_guard_total']}",
        f"- memory-backed wins: {summary['memory_backed_wins']}",
        f"- policy successes: {summary['policy_successes']} / {summary['episodes_total']}",
        f"- intent matches: {summary['intent_matches']} / {summary['episodes_total']}",
        f"- query-family matches: {summary['query_family_matches']} / {summary['episodes_total']}",
        f"- query-contract consistency: {summary['query_contract_consistency_successes']} / {summary['episodes_total']}",
        f"- injection-contract successes: {summary['injection_contract_successes']} / {summary['episodes_total']}",
        f"- thin-agent boundary successes: {summary['thin_agent_boundary_successes']} / {summary['episodes_total']}",
        f"- no-value guard successes: {summary['non_value_guard_successes']} / {summary['no_value_guard_total']}",
        f"- stale guard successes: {summary['stale_guard_successes']} / {summary['episodes_total']}",
        f"- wrong-memory guard successes: {summary['wrong_memory_guard_successes']} / {summary['episodes_total']}",
        f"- privacy guard successes: {summary['privacy_guard_successes']} / {summary['episodes_total']}",
        "",
        "## Failure Families",
        "",
    ]
    for name, count in summary["failure_families"].items():
        lines.append(f"- `{name}`: {count}")
    lines.extend(["", "## By Scenario Family", ""])
    for row in summary.get("by_scenario_family", []):
        lines.append(f"- `{row['scenario_family']}`: {row['policy_successes']} / {row['episodes_total']} policy successes")
    lines.extend(["", "## Episode Results", ""])
    for row in results:
        status = "PASS" if row["policy_success"] else f"FAIL ({', '.join(row['failure_families'])})"
        lines.append(
            f"- `{row['episode_id']}` [{status}]: family `{row.get('query_family')}`, wording `{row.get('query_wording_label')}`, "
            f"winner `{row['winner']}`, intent `{row.get('routing_intent') or 'unknown'}`, expected layer `{row['expected_primary_layer']}`, "
            f"top layer `{row['top_layer']}`, injected `{row['injection_contract']['injected_block_types'] or 'none'}`, "
            f"tag `{row.get('source_primary_tag') or 'unlabeled'}`"
        )
    return "\n".join(lines) + "\n"
def _build_run_id(config: AppConfig, *, corpus_name: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    provider = (config.llm_provider_for_default_use_case or "provider").replace("_", "-")
    model = (config.llm_model_for_default_use_case or "model").replace("/", "-").replace(".", "-")
    return f"public-corpus-benchmark__{corpus_name}__{provider}__{model}__{timestamp}"


if __name__ == "__main__":
    raise SystemExit(main())
