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
from app.main import create_app
from evals.benchmark_architecture import annotate_result, build_suite_summary
from evals.continuity_common import (
    CONTINUITY_FAILURE_FAMILIES,
    block_type_for_result,
    evaluate_query_contract,
    failure_family_counts,
    query_family_from_intent,
    result_layer,
)
from evals.external_memory_pressure_builder import (
    DEFAULT_REVIEW_MANIFEST,
    DEFAULT_TRANSFORMED_FIXTURE,
    build_reviewed_external_pressure_episodes,
    load_review_manifest,
    load_transformed_episodes,
)

DEFAULT_OUTPUT_DIR = Path("evals/external_memory_pressure/output")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the standalone external-memory pressure benchmark.")
    parser.add_argument("--transformed-fixture", type=Path, default=DEFAULT_TRANSFORMED_FIXTURE)
    parser.add_argument("--reviewed-manifest", type=Path, default=DEFAULT_REVIEW_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-name", default=None)
    parser.add_argument("--consolidation-strategy", default=None)
    args = parser.parse_args()
    run_dir = run_external_memory_pressure_benchmark(
        transformed_fixture=args.transformed_fixture,
        reviewed_manifest=args.reviewed_manifest,
        output_root=args.output_dir,
        config=AppConfig.from_env(),
        run_name=args.run_name,
        default_consolidation_strategy=args.consolidation_strategy,
    )
    print(run_dir)
    return 0


def run_external_memory_pressure_benchmark(
    *,
    transformed_fixture: Path,
    reviewed_manifest: Path,
    output_root: Path,
    config: AppConfig,
    run_name: str | None = None,
    default_consolidation_strategy: str | None = None,
) -> Path:
    fixture_rows = load_transformed_episodes(transformed_fixture)
    manifest = load_review_manifest(reviewed_manifest)
    episodes = build_reviewed_external_pressure_episodes(episodes=fixture_rows, manifest=manifest)

    run_id = run_name or _build_run_id()
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
                    default_consolidation_strategy=default_consolidation_strategy,
                ),
                suite_id="external_memory_pressure",
                dataset_tier=episode.get("dataset_tier"),
            )
            results.append(result)
            handle.write(json.dumps(result) + "\n")

    promotion_candidates = _promotion_candidates(results)
    summary = _build_summary(
        results=results,
        transformed_fixture=transformed_fixture,
        reviewed_manifest=reviewed_manifest,
        manifest=manifest,
        run_id=run_id,
        results_file=results_path.name,
        promotion_candidates=promotion_candidates,
    )
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (run_dir / "report.md").write_text(_build_report(summary=summary, results=results), encoding="utf-8")
    with (run_dir / "promotion_candidates.jsonl").open("w", encoding="utf-8") as handle:
        for row in promotion_candidates:
            handle.write(json.dumps(row) + "\n")
    return run_dir


def _run_episode(
    *,
    episode: dict[str, Any],
    config: AppConfig,
    default_consolidation_strategy: str | None,
) -> dict[str, Any]:
    runtime_context = dict(episode.get("runtime_context") or {})
    query_request = dict(episode["current_query"])
    query_request.setdefault("runtime_context", runtime_context)
    consolidation_strategy = episode.get("consolidation_strategy") or default_consolidation_strategy

    with TemporaryDirectory() as temp_dir:
        database_url = f"sqlite:///{Path(temp_dir) / 'external-memory-pressure.db'}"
        vector_index_config = replace(config.vector_index, index_path=str(Path(temp_dir) / "vector.index"))
        scenario_config = replace(config, sqlite_url=database_url, default_use_case="agent_conversation_memory", vector_index=vector_index_config)
        with TestClient(create_app(scenario_config)) as client:
            for event in episode.get("prior_events", []):
                response = client.post("/items", json=[_with_default_visibility(event)])
                response.raise_for_status()
            client.app.state.pallium_service.drain_processing_queue(worker_id="external-memory-pressure-runner")
            if consolidation_strategy:
                client.app.state.pallium_service.run_consolidation_pass(
                    use_case="agent_conversation_memory",
                    strategy_name=consolidation_strategy,
                )
            query_response = client.post("/query", json=_with_default_visibility(query_request))
            query_response.raise_for_status()
            query_contract_payload = query_response.json()
            debug_response = client.post("/query/debug", json=_with_default_visibility(query_request))
            debug_response.raise_for_status()
            debug_payload = debug_response.json()
            engine = getattr(client.app.state.pallium_service._storage, "_engine", None)
            if engine is not None:
                engine.dispose()

    routing = ((debug_payload.get("trace") or {}).get("routing") or {})
    top_result = debug_payload["results"][0] if debug_payload.get("results") else None
    top_layer = result_layer(top_result)
    returned_memory_types = sorted(
        {item.get("type") for item in debug_payload.get("results", []) if item.get("result_kind") == "memory_hit" and item.get("type")}
    )
    query_family = routing.get("query_family") or query_family_from_intent(
        routing.get("query_intent"),
        runtime_context=runtime_context,
        should_memory_help=bool(episode.get("should_memory_help")),
    )
    expected_layers = list(
        episode.get("acceptable_layers")
        or ([episode.get("expected_primary_layer")] if episode.get("expected_primary_layer") else [])
    )
    expected_memory_types = list(episode.get("expected_memory_types") or [])

    query_contract = evaluate_query_contract(
        query_payload=query_contract_payload,
        debug_payload=debug_payload,
        expected_should_inject=bool(episode.get("expected_should_inject", episode.get("should_memory_help"))),
        expected_decision_reason=episode.get("expected_decision_reason"),
        acceptable_decision_reasons=list(episode.get("acceptable_decision_reasons") or []),
        expected_primary_block_types=list(
            episode.get("expected_primary_block_types")
            or ([block_type_for_result(top_result)] if top_result else [])
        ),
        acceptable_fallback_block_types=list(episode.get("acceptable_fallback_block_types") or []),
        forbidden_block_types=list(episode.get("forbidden_block_types") or []),
        acceptable_injected_block_count=episode.get("acceptable_injected_block_count"),
        expected_cap_behavior=episode.get("expected_cap_behavior"),
    )

    rendered = json.dumps(
        {
            "results": debug_payload.get("results", []),
            "injectable_blocks": debug_payload.get("injectable_blocks", []),
        }
    ).lower()
    required_signals = list(episode.get("required_signals") or [])
    forbidden_signals = list(episode.get("forbidden_signals") or [])
    required_hits = [signal for signal in required_signals if str(signal).lower() in rendered]
    forbidden_hits = [signal for signal in forbidden_signals if str(signal).lower() in rendered]

    should_memory_help = bool(episode.get("should_memory_help"))
    should_abstain = bool(episode.get("should_abstain", not should_memory_help))
    if should_abstain:
        policy_success = (not debug_payload.get("should_inject")) and not forbidden_hits
    else:
        policy_success = (
            (not expected_layers or top_layer in expected_layers)
            and all(item in returned_memory_types for item in expected_memory_types)
            and len(required_hits) == len(required_signals)
            and not forbidden_hits
            and bool(query_contract["injection_contract"]["contract_success"])
        )

    failure_families: list[str] = []
    if not policy_success and episode.get("expected_failure_target"):
        failure_families.append(str(episode["expected_failure_target"]))

    return {
        "episode_id": episode["episode_id"],
        "source_benchmark_family": episode.get("source_benchmark_family", "longmemeval"),
        "pressure_family": episode.get("pressure_family"),
        "description": episode.get("description"),
        "should_memory_help": should_memory_help,
        "should_abstain": should_abstain,
        "query_family": query_family,
        "routing_intent": routing.get("query_intent"),
        "top_layer": top_layer,
        "returned_memory_types": returned_memory_types,
        "required_signals": required_signals,
        "required_signal_hits": required_hits,
        "forbidden_signal_hits": forbidden_hits,
        "query_contract_consistent": bool(query_contract["query_contract_consistent"]),
        "query_contract_mismatch_fields": list(query_contract["query_contract_mismatch_fields"]),
        "injection_contract": query_contract["injection_contract"],
        "should_inject": bool(debug_payload.get("should_inject")),
        "decision_reason": debug_payload.get("decision_reason"),
        "failure_families": [name for name in CONTINUITY_FAILURE_FAMILIES if name in set(failure_families)],
        "policy_success": policy_success,
        "expected_failure_target": episode.get("expected_failure_target"),
        "suggested_native_lane": episode.get("suggested_native_lane"),
        "promotable": bool(episode.get("promotable", False)),
    }


def _promotion_candidates(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in results:
        if row.get("policy_success") or not row.get("promotable"):
            continue
        if row.get("forbidden_signal_hits"):
            reason = "forbidden_signal_present"
        elif row.get("required_signals") and len(row.get("required_signal_hits", [])) != len(row.get("required_signals", [])):
            reason = "required_signal_missing"
        elif not row.get("injection_contract", {}).get("contract_success"):
            reason = "query_contract_miss"
        else:
            reason = "layer_or_memory_type_miss"
        rows.append(
            {
                "episode_id": row["episode_id"],
                "source_benchmark_family": row.get("source_benchmark_family"),
                "pressure_family": row.get("pressure_family"),
                "mapped_failure_family": row.get("expected_failure_target"),
                "reason": reason,
                "suggested_native_lane": row.get("suggested_native_lane"),
                "promotable": True,
            }
        )
    return rows


def _build_summary(
    *,
    results: list[dict[str, Any]],
    transformed_fixture: Path,
    reviewed_manifest: Path,
    manifest: dict[str, Any],
    run_id: str,
    results_file: str,
    promotion_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    pressure_family_counts: dict[str, int] = defaultdict(int)
    source_family_counts: dict[str, int] = defaultdict(int)
    for row in results:
        pressure_family_counts[str(row.get("pressure_family"))] += 1
        source_family_counts[str(row.get("source_benchmark_family"))] += 1
    summary = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "transformed_fixture": str(transformed_fixture),
        "reviewed_manifest": str(reviewed_manifest),
        "manifest_name": manifest.get("name"),
        "episodes_total": len(results),
        "policy_successes": sum(1 for row in results if row["policy_success"]),
        "failure_family_counts": failure_family_counts(results),
        "pressure_family_counts": dict(pressure_family_counts),
        "source_benchmark_family_counts": dict(source_family_counts),
        "promotion_candidates_total": len(promotion_candidates),
        "results_file": results_file,
    }
    summary["benchmark"] = build_suite_summary(suite_id="external_memory_pressure", results=results)
    return summary


def _build_report(*, summary: dict[str, Any], results: list[dict[str, Any]]) -> str:
    lines = [
        "# External Memory Pressure Report",
        "",
        f"Run ID: `{summary['run_id']}`",
        "",
        f"- episodes: {summary['episodes_total']}",
        f"- policy successes: {summary['policy_successes']} / {summary['episodes_total']}",
        f"- promotion candidates: {summary['promotion_candidates_total']}",
        "",
        "## Pressure Families",
        "",
    ]
    for name, count in sorted(summary["pressure_family_counts"].items()):
        lines.append(f"- `{name}`: {count}")
    lines.extend(["", "## Failure Families", ""])
    for name, count in summary["failure_family_counts"].items():
        lines.append(f"- `{name}`: {count}")
    lines.extend(["", "## Episode Results", ""])
    for row in results:
        lines.append(
            f"- `{row['episode_id']}`: policy_success={row['policy_success']}, pressure_family={row['pressure_family']}, failures={row['failure_families'] or 'none'}"
        )
    return "\n".join(lines) + "\n"


def _with_default_visibility(payload: dict[str, Any]) -> dict[str, Any]:
    updated = dict(payload)
    updated.setdefault("container_visibility", "public")
    return updated


def _build_run_id() -> str:
    return f"external-memory-pressure__{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"


if __name__ == "__main__":
    raise SystemExit(main())
