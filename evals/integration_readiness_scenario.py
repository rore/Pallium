from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import AppConfig
from evals.work_resumption_benchmark import run_work_resumption_benchmark
from providers.llm.base import LLMProvider

DEFAULT_SCENARIO_FILE = Path("evals/integration_readiness/scenarios.json")
DEFAULT_OUTPUT_DIR = Path("evals/integration_readiness/output")
BRUNO_COLLECTION_DIR = Path("bruno/integration-readiness")
ROLE_ORDER = ("positive_value", "no_value_control", "scope_guard")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the canonical integration-readiness milestone scenario.")
    parser.add_argument("--scenario-file", type=Path, default=DEFAULT_SCENARIO_FILE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-name", default=None)
    parser.add_argument("--consolidation-strategy", default=None)
    args = parser.parse_args()

    run_dir = run_integration_readiness_scenario(
        scenario_file=args.scenario_file,
        output_root=args.output_dir,
        config=AppConfig.from_env(),
        run_name=args.run_name,
        consolidation_strategy=args.consolidation_strategy,
    )
    print(run_dir)
    return 0


def run_integration_readiness_scenario(
    *,
    scenario_file: Path,
    output_root: Path,
    config: AppConfig,
    run_name: str | None = None,
    consolidation_strategy: str | None = None,
    answer_provider: LLMProvider | None = None,
) -> Path:
    scenarios = _load_scenarios(scenario_file)
    run_id = run_name or _build_run_id()
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    component_run_dir = run_work_resumption_benchmark(
        scenario_file=scenario_file,
        output_root=run_dir / "work_resumption_component",
        config=config,
        run_name="integration-readiness-work-resumption",
        answer_provider=answer_provider,
        consolidation_strategy=consolidation_strategy,
    )
    component_summary = _read_json(component_run_dir / "summary.json")
    component_results = _read_jsonl(component_run_dir / "results.jsonl")
    by_id = {row["scenario_id"]: row for row in component_results}

    role_results: dict[str, dict[str, Any]] = {}
    for scenario in scenarios:
        role = str(scenario["milestone_role"])
        result = by_id[scenario["scenario_id"]]
        policy_success = _component_policy_success(result)
        role_results[role] = {
            "scenario_id": scenario["scenario_id"],
            "description": scenario["description"],
            "policy_success": policy_success,
            "winner": result["winner"],
            "top_layer": result["top_layer"],
            "routing_intent": result["routing_intent"],
            "primary_layer_match": bool(result.get("primary_layer_match")),
            "top_layer_match": bool(result.get("top_layer_match")),
            "intent_match": bool(result.get("intent_match")),
            "failure_families": list(result.get("failure_families", [])),
            "must_preserve": list(scenario.get("must_preserve", [])),
            "must_not_introduce": list(scenario.get("must_not_introduce", [])),
            "trace_path": "work_resumption_component/integration-readiness-work-resumption/results.jsonl",
        }

    gates = {
        "positive_value_passed": _positive_value_gate(role_results.get("positive_value")),
        "no_value_control_passed": _no_value_control_gate(role_results.get("no_value_control")),
        "scope_guard_passed": _scope_guard_gate(role_results.get("scope_guard")),
    }
    gates["integration_readiness_passed"] = all(gates.values())

    summary = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scenario_count": len(scenarios),
        "component_run_dir": str(component_run_dir),
        "component_summary_file": str(component_run_dir / "summary.json"),
        "component_results_file": str(component_run_dir / "results.jsonl"),
        "bruno_collection_dir": str(BRUNO_COLLECTION_DIR),
        "component_policy_successes": sum(1 for row in role_results.values() if row["policy_success"]),
        "component_failure_families": component_summary.get("failure_family_counts", {}),
        "roles": {role: role_results[role] for role in ROLE_ORDER if role in role_results},
        "gates": gates,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (run_dir / "report.md").write_text(_build_report(summary), encoding="utf-8")
    return run_dir


def _positive_value_gate(result: dict[str, Any] | None) -> bool:
    if result is None:
        return False
    return bool(result["policy_success"] and result["winner"] == "memory_backed" and result["top_layer"] == "task_checkpoint")


def _no_value_control_gate(result: dict[str, Any] | None) -> bool:
    if result is None:
        return False
    return bool(result["policy_success"] and result["winner"] != "memory_backed")


def _scope_guard_gate(result: dict[str, Any] | None) -> bool:
    if result is None:
        return False
    failures = set(result.get("failure_families", []))
    return bool(result["policy_success"] and "privacy_leak_failure" not in failures and result["winner"] == "memory_backed")


def _component_policy_success(result: dict[str, Any]) -> bool:
    failures = list(result.get("failure_families", []))
    return bool(
        not failures
        and result.get("top_layer_match", False)
        and result.get("primary_layer_match", False)
        and result.get("expected_memory_types_found", True)
    )


def _load_scenarios(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError(f"integration readiness scenario file {path} must contain a non-empty JSON array")
    for scenario in payload:
        role = scenario.get("milestone_role")
        if role not in ROLE_ORDER:
            raise ValueError(f"scenario {scenario.get('scenario_id')} must declare one of {ROLE_ORDER}")
    return payload


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _build_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Integration-Readiness Report",
        "",
        f"Run ID: `{summary['run_id']}`",
        "",
        "## Gates",
        "",
    ]
    for gate_name, passed in summary["gates"].items():
        lines.append(f"- `{gate_name}`: {'PASS' if passed else 'FAIL'}")
    lines.extend([
        "",
        "## Scenarios",
        "",
    ])
    for role in ROLE_ORDER:
        result = summary["roles"].get(role)
        if result is None:
            continue
        lines.extend([
            f"### `{role}`",
            "",
            f"- scenario: `{result['scenario_id']}`",
            f"- winner: `{result['winner']}`",
            f"- top layer: `{result['top_layer']}`",
            f"- routing intent: `{result['routing_intent']}`",
            f"- policy success: {result['policy_success']}",
            f"- failure families: {result['failure_families']}",
            "",
        ])
    lines.extend([
        "## Manual Run",
        "",
        f"- Bruno collection: `{summary['bruno_collection_dir']}`",
        f"- Component results: `{summary['component_results_file']}`",
    ])
    return "\n".join(lines) + "\n"


def _build_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"integration-readiness__{timestamp}"


if __name__ == "__main__":
    raise SystemExit(main())
