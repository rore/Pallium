from __future__ import annotations

import argparse
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app


DEFAULT_SCENARIO_FILE = Path("evals/agent_conversation/scenarios.json")
DEFAULT_OUTPUT_DIR = Path("evals/agent_conversation/output")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run realistic agent conversation memory scenarios.")
    parser.add_argument("--scenario-file", type=Path, default=DEFAULT_SCENARIO_FILE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-name", default=None)
    parser.add_argument("--consolidation-strategy", default=None)
    args = parser.parse_args()

    run_dir = run_agent_conversation_scenarios(
        scenario_file=args.scenario_file,
        output_root=args.output_dir,
        config=AppConfig.from_env(),
        run_name=args.run_name,
        consolidation_strategy=args.consolidation_strategy,
    )
    print(run_dir)
    return 0


def run_agent_conversation_scenarios(
    *,
    scenario_file: Path,
    output_root: Path,
    config: AppConfig,
    run_name: str | None = None,
    consolidation_strategy: str | None = None,
) -> Path:
    scenarios = _load_scenarios(scenario_file)
    run_id = run_name or _build_run_id(consolidation_strategy)
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    results_path = run_dir / "results.jsonl"

    summary = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scenario_file": str(scenario_file),
        "results_file": results_path.name,
        "consolidation_strategy": consolidation_strategy,
        "scenarios_total": len(scenarios),
        "value_scenarios": 0,
        "non_value_scenarios": 0,
        "memory_expected_and_found": 0,
        "low_value_without_memory": 0,
    }

    with results_path.open("w", encoding="utf-8") as results_file:
        for scenario in scenarios:
            result = _run_scenario(scenario=scenario, config=config, consolidation_strategy=consolidation_strategy)
            if result["expected_value"]:
                summary["value_scenarios"] += 1
                if result["expected_memory_types_found"]:
                    summary["memory_expected_and_found"] += 1
            else:
                summary["non_value_scenarios"] += 1
                if result["memory_was_unnecessary"]:
                    summary["low_value_without_memory"] += 1

            results_file.write(json.dumps(result) + "\n")

    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return run_dir


def _run_scenario(*, scenario: dict[str, Any], config: AppConfig, consolidation_strategy: str | None) -> dict[str, Any]:
    with TemporaryDirectory() as temp_dir:
        database_url = f"sqlite:///{Path(temp_dir) / 'scenario.db'}"
        vector_index_config = replace(config.vector_index, index_path=str(Path(temp_dir) / "vector.index"))
        scenario_config = replace(
            config,
            sqlite_url=database_url,
            default_use_case="agent_conversation_memory",
            vector_index=vector_index_config,
        )
        with TestClient(create_app(scenario_config)) as client:
            for event in scenario.get("prior_events", []):
                response = client.post("/items", json=_with_default_visibility(event))
                response.raise_for_status()
            client.app.state.pallium_service.drain_processing_queue(worker_id="agent-conversation-runner")

            consolidation_result = None
            if consolidation_strategy:
                consolidation_result = client.app.state.pallium_service.run_consolidation_pass(
                    use_case="agent_conversation_memory",
                    strategy_name=consolidation_strategy,
                )

            query_response = client.post("/query", json=_with_default_visibility(scenario["current_query"]))
            query_response.raise_for_status()
            query_payload = query_response.json()
            engine = getattr(client.app.state.pallium_service._storage, "_engine", None)
            if engine is not None:
                engine.dispose()
    memory_hits = [item for item in query_payload["results"] if item["result_kind"] == "memory_hit"]
    source_hits = [item for item in query_payload["results"] if item["result_kind"] == "source_hit"]
    returned_memory_types = sorted({item["type"] for item in memory_hits if item.get("type")})
    expected_memory_types = scenario.get("expected_memory_types", [])
    expected_memory_types_found = all(item in returned_memory_types for item in expected_memory_types)
    expected_value = bool(scenario.get("expected_value"))

    return {
        "scenario_id": scenario["scenario_id"],
        "scenario_kind": scenario["scenario_kind"],
        "description": scenario["description"],
        "expected_value": expected_value,
        "expected_memory_types": expected_memory_types,
        "expected_non_value_reason": scenario.get("expected_non_value_reason"),
        "baseline_context": scenario.get("current_thread_context", []),
        "memory_backed_results": query_payload["results"],
        "returned_memory_types": returned_memory_types,
        "memory_hit_count": len(memory_hits),
        "source_hit_count": len(source_hits),
        "memory_added_signal": bool(memory_hits),
        "expected_memory_types_found": expected_memory_types_found,
        "memory_was_expected": expected_value and expected_memory_types_found,
        "memory_was_unnecessary": (not expected_value) and (not memory_hits),
        "consolidation_strategy": consolidation_strategy,
        "consolidation_run": _serialize_consolidation_result(consolidation_result),
    }


def _with_default_visibility(payload: dict[str, Any]) -> dict[str, Any]:
    updated = dict(payload)
    updated.setdefault("container_visibility", "public")
    return updated


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


def _load_scenarios(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_run_id(consolidation_strategy: str | None) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    strategy_suffix = f"__{consolidation_strategy}" if consolidation_strategy else ""
    return f"agent-conversation-test-bed{strategy_suffix}__{timestamp}"


if __name__ == "__main__":
    raise SystemExit(main())
