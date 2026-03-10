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
    args = parser.parse_args()

    run_dir = run_agent_conversation_scenarios(
        scenario_file=args.scenario_file,
        output_root=args.output_dir,
        config=AppConfig.from_env(),
        run_name=args.run_name,
    )
    print(run_dir)
    return 0


def run_agent_conversation_scenarios(
    *,
    scenario_file: Path,
    output_root: Path,
    config: AppConfig,
    run_name: str | None = None,
) -> Path:
    scenarios = _load_scenarios(scenario_file)
    run_id = run_name or _build_run_id()
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    results_path = run_dir / "results.jsonl"

    summary = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scenario_file": str(scenario_file),
        "results_file": results_path.name,
        "scenarios_total": len(scenarios),
        "value_scenarios": 0,
        "non_value_scenarios": 0,
        "memory_expected_and_found": 0,
        "low_value_without_memory": 0,
    }

    with results_path.open("w", encoding="utf-8") as results_file:
        for scenario in scenarios:
            result = _run_scenario(scenario=scenario, config=config)
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


def _run_scenario(*, scenario: dict[str, Any], config: AppConfig) -> dict[str, Any]:
    with TemporaryDirectory() as temp_dir:
        database_url = f"sqlite:///{Path(temp_dir) / 'scenario.db'}"
        scenario_config = replace(
            config,
            sqlite_url=database_url,
            default_use_case="agent_conversation_memory",
        )
        with TestClient(create_app(scenario_config)) as client:
            for event in scenario.get("prior_events", []):
                response = client.post("/items", json=event)
                response.raise_for_status()

            query_response = client.post("/query", json=scenario["current_query"])
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
    }


def _load_scenarios(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"agent-conversation-test-bed__{timestamp}"


if __name__ == "__main__":
    raise SystemExit(main())
