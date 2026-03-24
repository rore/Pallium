"""
Replay promotion script.

Converts live runner scenario result JSONs into benchmark-ready scenario skeleton files
consumable by the existing agent_conversation_runner.py via --scenario-file.

Usage:
    python -m tools.replay_promotion.promote_to_replay --source path/to/scenario_id.json
    python -m tools.replay_promotion.promote_to_replay --run-dir path/to/run/ [--scenario-id ID]
    python -m tools.replay_promotion.promote_to_replay --source ... --output evals/agent_conversation/scenarios_replay.json
    python -m tools.replay_promotion.promote_to_replay --source ... --expected-value true
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REQUIRED_SCENARIO_FIELDS = {
    "scenario_id",
    "scenario_kind",
    "description",
    "prior_events",
    "current_query",
    "expected_value",
    "expected_memory_types",
}

_DEFAULT_OUTPUT = Path("evals/agent_conversation/scenarios_replay.json")


def _validate_scenario(scenario: dict[str, Any]) -> list[str]:
    return [f for f in _REQUIRED_SCENARIO_FIELDS if f not in scenario]


def _compact_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _build_scenario_from_result(
    result: dict[str, Any],
    *,
    expected_value: bool | str | None,
) -> dict[str, Any]:
    source_id = result.get("scenario_id", "unknown")
    ts = _compact_timestamp()
    scenario_id = f"replay_{source_id}_{ts}"

    description = result.get("description") or source_id
    description = f"[REPLAY] {description}"

    prior_events: list[dict[str, Any]] = list(result.get("ingested_items") or [])

    query_request = result.get("followup_query_request") or {}
    current_query: dict[str, Any] = {
        "text": query_request.get("text") or result.get("followup_message") or "",
        "limit": query_request.get("limit", 6),
    }
    if query_request.get("container_ref"):
        current_query["container_ref"] = query_request["container_ref"]
    if query_request.get("visibility"):
        current_query["visibility"] = query_request["visibility"]

    if expected_value is None:
        ev = "__FILL_IN__"
    elif isinstance(expected_value, str):
        ev = expected_value.lower() == "true"
    else:
        ev = bool(expected_value)

    return {
        "scenario_id": scenario_id,
        "scenario_kind": "replay_capture",
        "description": description,
        "prior_events": prior_events,
        "current_thread_context": [],
        "current_query": current_query,
        "expected_value": ev,
        "expected_memory_types": [],
    }


def _build_sidecar(result: dict[str, Any], *, scenario_id: str) -> dict[str, Any]:
    eval_ = result.get("followup_evaluation") or {}
    return {
        "scenario_id": scenario_id,
        "source_scenario_id": result.get("scenario_id"),
        "source_description": result.get("description"),
        "source_classification": result.get("classification"),
        "source_selected_layer": eval_.get("selected_layer"),
        "source_should_inject": eval_.get("should_inject"),
        "source_decision_reason": eval_.get("decision_reason"),
        "promoted_at": datetime.now(timezone.utc).isoformat(),
        "review_status": "pending",
    }


def _load_result_file(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object in {path}, got {type(data).__name__}")
    return data


def _merge_into_output(
    output_path: Path,
    new_scenarios: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    existing: list[dict[str, Any]] = []
    if output_path.exists():
        raw = json.loads(output_path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            existing = raw

    existing_ids = {s.get("scenario_id") for s in existing}
    appended = 0
    for scenario in new_scenarios:
        if scenario.get("scenario_id") not in existing_ids:
            existing.append(scenario)
            existing_ids.add(scenario.get("scenario_id"))
            appended += 1

    return existing, appended


def _promote_single(
    source_path: Path,
    *,
    output_path: Path,
    expected_value: str | None,
) -> int:
    result = _load_result_file(source_path)
    scenario = _build_scenario_from_result(result, expected_value=expected_value)

    missing = _validate_scenario(scenario)
    if missing:
        print(f"ERROR: promoted scenario is missing required fields: {missing}", file=sys.stderr)
        return 1

    sidecar = _build_sidecar(result, scenario_id=scenario["scenario_id"])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    merged, appended = _merge_into_output(output_path, [scenario])
    output_path.write_text(json.dumps(merged, indent=2), encoding="utf-8")

    sidecar_path = output_path.parent / f"{scenario['scenario_id']}_source.json"
    sidecar_path.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")

    print(f"Promoted 1 scenario ({appended} new) → {output_path}")
    print(f"Sidecar → {sidecar_path}")
    return 0


def _promote_run_dir(
    run_dir: Path,
    *,
    scenario_id_filter: str | None,
    output_path: Path,
    expected_value: str | None,
) -> int:
    result_paths = sorted(run_dir.glob("*.json"))
    result_paths = [p for p in result_paths if not p.name.endswith("__error.json") and p.name != "summary.json"]
    if scenario_id_filter:
        result_paths = [p for p in result_paths if p.stem == scenario_id_filter]

    if not result_paths:
        print("ERROR: no matching result files found", file=sys.stderr)
        return 1

    scenarios: list[dict[str, Any]] = []
    sidecars: list[tuple[str, dict[str, Any]]] = []
    for path in result_paths:
        try:
            result = _load_result_file(path)
        except (ValueError, json.JSONDecodeError) as exc:
            print(f"SKIP {path.name}: {exc}", file=sys.stderr)
            continue
        scenario = _build_scenario_from_result(result, expected_value=expected_value)
        missing = _validate_scenario(scenario)
        if missing:
            print(f"SKIP {path.name}: missing required fields {missing}", file=sys.stderr)
            continue
        scenarios.append(scenario)
        sidecars.append((scenario["scenario_id"], _build_sidecar(result, scenario_id=scenario["scenario_id"])))

    if not scenarios:
        print("ERROR: no valid scenarios to promote", file=sys.stderr)
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    merged, appended = _merge_into_output(output_path, scenarios)
    output_path.write_text(json.dumps(merged, indent=2), encoding="utf-8")

    for sid, sidecar in sidecars:
        sidecar_path = output_path.parent / f"{sid}_source.json"
        sidecar_path.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")

    print(f"Promoted {len(scenarios)} scenarios ({appended} new) → {output_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Promote live runner scenario results to benchmark-ready replay scenarios."
    )
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--source", type=Path, help="Path to a single per-scenario result JSON")
    source_group.add_argument("--run-dir", type=Path, help="Directory containing per-scenario result JSONs from a live run")
    parser.add_argument("--scenario-id", help="Filter to a specific scenario ID (batch mode only)")
    parser.add_argument("--expected-value", choices=["true", "false"], help="Pre-fill expected_value (human confirms)")
    parser.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT, help=f"Output file (default: {_DEFAULT_OUTPUT})")
    args = parser.parse_args(argv)

    if args.source:
        return _promote_single(
            args.source,
            output_path=args.output,
            expected_value=args.expected_value,
        )
    return _promote_run_dir(
        args.run_dir,
        scenario_id_filter=args.scenario_id,
        output_path=args.output,
        expected_value=args.expected_value,
    )


if __name__ == "__main__":
    sys.exit(main())
