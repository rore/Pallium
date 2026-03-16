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
from evals.continuity_common import CONTINUITY_FAILURE_FAMILIES, failure_family_counts

DEFAULT_SCENARIO_FILE = Path("evals/low_value_churn/scenarios.json")
DEFAULT_OUTPUT_DIR = Path("evals/low_value_churn/output")
SUMMARY_MEMORY_TYPES = ["thread_summary", "discussion_summary"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the low-value and rebuild-churn benchmark.")
    parser.add_argument("--scenario-file", type=Path, default=DEFAULT_SCENARIO_FILE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-name", default=None)
    args = parser.parse_args()

    run_dir = run_low_value_churn_benchmark(
        scenario_file=args.scenario_file,
        output_root=args.output_dir,
        config=AppConfig.from_env(),
        run_name=args.run_name,
    )
    print(run_dir)
    return 0


def run_low_value_churn_benchmark(
    *,
    scenario_file: Path,
    output_root: Path,
    config: AppConfig,
    run_name: str | None = None,
) -> Path:
    scenarios = json.loads(scenario_file.read_text(encoding="utf-8"))
    run_id = run_name or _build_run_id()
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    results_path = run_dir / "results.jsonl"

    results: list[dict[str, Any]] = []
    with results_path.open("w", encoding="utf-8") as handle:
        for scenario in scenarios:
            result = _run_scenario(scenario=scenario, config=config)
            results.append(result)
            handle.write(json.dumps(result) + "\n")

    summary = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scenario_file": str(scenario_file),
        "results_file": results_path.name,
        "scenarios_total": len(results),
        "policy_successes": sum(1 for row in results if row["policy_success"]),
        "low_value_promotion_successes": sum(1 for row in results if not row["low_value_promotion_failures"]),
        "thread_rebuild_churn_successes": sum(1 for row in results if "thread_rebuild_churn_failure" not in row["failure_families"]),
        "failure_family_counts": failure_family_counts(results),
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (run_dir / "report.md").write_text(_build_report(summary=summary, results=results), encoding="utf-8")
    return run_dir


def _run_scenario(*, scenario: dict[str, Any], config: AppConfig) -> dict[str, Any]:
    with TemporaryDirectory() as temp_dir:
        database_url = f"sqlite:///{Path(temp_dir) / 'low-value-churn.db'}"
        scenario_config = replace(config, sqlite_url=database_url, default_use_case="agent_conversation_memory")
        with TestClient(create_app(scenario_config)) as client:
            source_item_ids: list[str] = []
            for event in scenario.get("events", []):
                response = client.post("/items", json=_with_default_visibility(event))
                response.raise_for_status()
                source_item_ids.append(response.json()["source_item_id"])
            client.app.state.pallium_service.drain_processing_queue(worker_id="low-value-churn-runner")

            processing_rows = []
            for source_item_id in source_item_ids:
                processing_response = client.get(f"/items/{source_item_id}/processing")
                processing_response.raise_for_status()
                processing_rows.append(processing_response.json())

            storage = client.app.state.pallium_service._storage
            summary_memory = storage.list_memory_objects(memory_types=SUMMARY_MEMORY_TYPES)
            active_summary_memory = [item for item in summary_memory if item.lifecycle == "active"]
            superseded_summary_memory = [item for item in summary_memory if item.lifecycle == "superseded"]

            engine = getattr(storage, "_engine", None)
            if engine is not None:
                engine.dispose()

    by_source_id = {
        row["source_item_id"]: row
        for row in processing_rows
    }
    low_value_source_ids = set(scenario.get("low_value_source_item_ids", []))
    source_id_by_input = {
        event["source_id"]: source_item_id
        for event, source_item_id in zip(scenario.get("events", []), source_item_ids, strict=False)
    }
    tracked_low_value_ids = {source_id_by_input[source_id] for source_id in low_value_source_ids if source_id in source_id_by_input}

    low_value_promotion_failures = [
        source_item_id
        for source_item_id in tracked_low_value_ids
        if by_source_id[source_item_id]["memory_object_types"]
    ]
    low_value_rebuild_failures = [
        source_item_id
        for source_item_id in tracked_low_value_ids
        if by_source_id[source_item_id]["thread_rebuild_requested"]
    ]

    failure_families: list[str] = []
    if low_value_promotion_failures or low_value_rebuild_failures:
        failure_families.append("low_value_promotion_failure")

    active_summary_limit = int(scenario.get("expected_active_summary_max", len(active_summary_memory)))
    superseded_summary_limit = int(scenario.get("expected_superseded_summary_max", len(superseded_summary_memory)))
    summary_churn_details = {
        "active_summary_count": len(active_summary_memory),
        "superseded_summary_count": len(superseded_summary_memory),
        "active_summary_types": [item.type for item in active_summary_memory],
        "superseded_summary_types": [item.type for item in superseded_summary_memory],
    }
    if len(active_summary_memory) > active_summary_limit or len(superseded_summary_memory) > superseded_summary_limit:
        failure_families.append("thread_rebuild_churn_failure")

    return {
        "scenario_id": scenario["scenario_id"],
        "description": scenario["description"],
        "processing_rows": processing_rows,
        "low_value_source_item_ids": sorted(tracked_low_value_ids),
        "low_value_promotion_failures": low_value_promotion_failures,
        "low_value_rebuild_failures": low_value_rebuild_failures,
        "summary_churn": summary_churn_details,
        "failure_families": [name for name in CONTINUITY_FAILURE_FAMILIES if name in set(failure_families)],
        "policy_success": not failure_families,
    }


def _with_default_visibility(payload: dict[str, Any]) -> dict[str, Any]:
    updated = dict(payload)
    updated.setdefault("visibility_context", {"kind": "public", "id": None})
    return updated


def _build_report(*, summary: dict[str, Any], results: list[dict[str, Any]]) -> str:
    lines = [
        "# Low-Value And Churn Benchmark Report",
        "",
        f"Run ID: `{summary['run_id']}`",
        "",
        f"- scenarios: {summary['scenarios_total']}",
        f"- policy successes: {summary['policy_successes']} / {summary['scenarios_total']}",
        f"- low-value promotion successes: {summary['low_value_promotion_successes']} / {summary['scenarios_total']}",
        f"- thread-rebuild churn successes: {summary['thread_rebuild_churn_successes']} / {summary['scenarios_total']}",
        "",
        "## Failure Families",
        "",
    ]
    for name, count in summary["failure_family_counts"].items():
        lines.append(f"- `{name}`: {count}")
    lines.extend(["", "## Scenario Results", ""])
    for row in results:
        lines.append(
            f"- `{row['scenario_id']}`: failures {row['failure_families'] or 'none'}, "
            f"low-value promotion {row['low_value_promotion_failures'] or 'none'}, "
            f"low-value rebuild {row['low_value_rebuild_failures'] or 'none'}, "
            f"summary churn {row['summary_churn']}"
        )
    return "\n".join(lines) + "\n"


def _build_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"low-value-churn-benchmark__{timestamp}"


if __name__ == "__main__":
    raise SystemExit(main())


