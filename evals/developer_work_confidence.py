from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import AppConfig
from evals.continuity_common import (
    CONTINUITY_FAILURE_FAMILIES,
    dominant_bottleneck_implication,
    dominant_tuning_bottleneck,
    failure_family_counts,
)
from evals.low_value_churn_benchmark import run_low_value_churn_benchmark
from evals.public_corpus_benchmark import run_public_corpus_benchmark
from evals.work_resumption_benchmark import run_work_resumption_benchmark
from providers.llm.base import LLMProvider

DEFAULT_OUTPUT_DIR = Path("evals/developer_work_confidence/output")
DEFAULT_WORK_SCENARIO_FILE = Path("evals/work_resumption/scenarios.json")
DEFAULT_WILDCHAT_MANIFEST = Path("evals/public_corpus/wildchat_review_manifest.json")
DEFAULT_WILDBENCH_MANIFEST = Path("evals/public_corpus/wildbench_developer_continuation_manifest.json")
DEFAULT_LOW_VALUE_CHURN_SCENARIO_FILE = Path("evals/low_value_churn/scenarios.json")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the combined developer-work confidence suite.")
    parser.add_argument("--work-scenario-file", type=Path, default=DEFAULT_WORK_SCENARIO_FILE)
    parser.add_argument("--wildchat-corpus-file", type=Path, required=True)
    parser.add_argument("--wildchat-manifest", type=Path, default=DEFAULT_WILDCHAT_MANIFEST)
    parser.add_argument("--wildbench-corpus-file", type=Path, required=True)
    parser.add_argument("--wildbench-manifest", type=Path, default=DEFAULT_WILDBENCH_MANIFEST)
    parser.add_argument("--low-value-churn-scenario-file", type=Path, default=DEFAULT_LOW_VALUE_CHURN_SCENARIO_FILE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-name", default=None)
    parser.add_argument("--consolidation-strategy", default="thread_summary_anchored")
    args = parser.parse_args()

    run_dir = run_developer_work_confidence_suite(
        work_scenario_file=args.work_scenario_file,
        wildchat_corpus_file=args.wildchat_corpus_file,
        wildchat_manifest=args.wildchat_manifest,
        wildbench_corpus_file=args.wildbench_corpus_file,
        wildbench_manifest=args.wildbench_manifest,
        low_value_churn_scenario_file=args.low_value_churn_scenario_file,
        output_root=args.output_dir,
        config=AppConfig.from_env(),
        run_name=args.run_name,
        consolidation_strategy=args.consolidation_strategy,
    )
    print(run_dir)
    return 0


def run_developer_work_confidence_suite(
    *,
    work_scenario_file: Path,
    wildchat_corpus_file: Path,
    wildchat_manifest: Path,
    wildbench_corpus_file: Path,
    wildbench_manifest: Path,
    low_value_churn_scenario_file: Path = DEFAULT_LOW_VALUE_CHURN_SCENARIO_FILE,
    output_root: Path,
    config: AppConfig,
    run_name: str | None = None,
    consolidation_strategy: str | None = "thread_summary_anchored",
    work_answer_provider: LLMProvider | None = None,
    public_corpus_answer_provider: LLMProvider | None = None,
) -> Path:
    run_id = run_name or _build_run_id(config)
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    work_run_dir = run_work_resumption_benchmark(
        scenario_file=work_scenario_file,
        output_root=run_dir / "work_resumption",
        config=config,
        run_name="work-resumption",
        answer_provider=work_answer_provider,
        consolidation_strategy=consolidation_strategy,
    )
    wildchat_run_dir = run_public_corpus_benchmark(
        corpus_file=wildchat_corpus_file,
        reviewed_manifest=wildchat_manifest,
        output_root=run_dir / "wildchat",
        config=config,
        run_name="wildchat-reviewed",
        answer_provider=public_corpus_answer_provider,
        default_consolidation_strategy=consolidation_strategy,
    )
    wildbench_run_dir = run_public_corpus_benchmark(
        corpus_file=wildbench_corpus_file,
        reviewed_manifest=wildbench_manifest,
        output_root=run_dir / "wildbench",
        config=config,
        run_name="wildbench-developer",
        answer_provider=public_corpus_answer_provider,
        default_consolidation_strategy=consolidation_strategy,
    )
    low_value_churn_run_dir = run_low_value_churn_benchmark(
        scenario_file=low_value_churn_scenario_file,
        output_root=run_dir / "low_value_churn",
        config=config,
        run_name="low-value-churn",
    )

    work_summary = _read_json(work_run_dir / "summary.json")
    work_results = _read_jsonl(work_run_dir / "results.jsonl")
    wildchat_summary = _read_json(wildchat_run_dir / "summary.json")
    wildchat_results = _read_jsonl(wildchat_run_dir / "results.jsonl")
    wildbench_summary = _read_json(wildbench_run_dir / "summary.json")
    wildbench_results = _read_jsonl(wildbench_run_dir / "results.jsonl")
    low_value_churn_summary = _read_json(low_value_churn_run_dir / "summary.json")
    low_value_churn_results = _read_jsonl(low_value_churn_run_dir / "results.jsonl")

    aggregate_failure_counts = _aggregate_failure_counts(
        work_results=work_results,
        wildchat_results=wildchat_results,
        wildbench_results=wildbench_results,
        low_value_churn_results=low_value_churn_results,
    )
    dominant_bottleneck = dominant_tuning_bottleneck(aggregate_failure_counts)

    components = {
        "work_resumption": _work_component_summary(work_run_dir, work_summary, work_results),
        "wildchat_reviewed": _public_component_summary(wildchat_run_dir, wildchat_summary, wildchat_results),
        "wildbench_developer": _public_component_summary(wildbench_run_dir, wildbench_summary, wildbench_results),
        "low_value_churn": _generic_component_summary(low_value_churn_run_dir, low_value_churn_summary, low_value_churn_results),
    }

    aggregate = {
        "scenarios_total": len(work_results) + len(wildchat_results) + len(wildbench_results) + len(low_value_churn_results),
        "value_scenarios": sum(1 for row in work_results if row.get("should_memory_help"))
        + sum(1 for row in wildchat_results if row.get("should_memory_help"))
        + sum(1 for row in wildbench_results if row.get("should_memory_help")),
        "non_value_scenarios": sum(1 for row in work_results if not row.get("should_memory_help"))
        + sum(1 for row in wildchat_results if not row.get("should_memory_help"))
        + sum(1 for row in wildbench_results if not row.get("should_memory_help"))
        + len(low_value_churn_results),
        "policy_successes": sum(component["policy_successes"] for component in components.values()),
        "failure_family_counts": aggregate_failure_counts,
        "dominant_tuning_bottleneck": dominant_bottleneck,
        "dominant_bottleneck_implication": dominant_bottleneck_implication(dominant_bottleneck),
    }
    aggregate["policy_success_rate"] = round(
        aggregate["policy_successes"] / aggregate["scenarios_total"],
        4,
    ) if aggregate["scenarios_total"] else 0.0

    gates = {
        "zero_privacy_leaks": aggregate_failure_counts["privacy_leak_failure"] == 0,
        "zero_wrong_memory_failures": aggregate_failure_counts["wrong_memory_selection_failure"] == 0,
        "zero_stale_memory_failures": aggregate_failure_counts["stale_memory_failure"] == 0,
        "zero_no_value_overreach_failures": aggregate_failure_counts["no_value_overreach_failure"] == 0,
        "zero_low_value_promotion_failures": aggregate_failure_counts["low_value_promotion_failure"] == 0,
        "zero_thread_rebuild_churn_failures": aggregate_failure_counts["thread_rebuild_churn_failure"] == 0,
        "work_suite_green": components["work_resumption"]["policy_successes"] == components["work_resumption"]["scenarios_total"],
        "wildchat_suite_green": components["wildchat_reviewed"]["policy_successes"] == components["wildchat_reviewed"]["scenarios_total"],
        "wildbench_suite_green": components["wildbench_developer"]["policy_successes"] == components["wildbench_developer"]["scenarios_total"],
        "low_value_churn_suite_green": components["low_value_churn"]["policy_successes"] == components["low_value_churn"]["scenarios_total"],
    }
    gates["confidence_gate_passed"] = all(gates.values())

    summary = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "components": components,
        "aggregate": aggregate,
        "gates": gates,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (run_dir / "report.md").write_text(_build_report(summary), encoding="utf-8")
    return run_dir


def _work_component_summary(run_dir: Path, summary: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "run_dir": str(run_dir),
        "scenarios_total": len(results),
        "value_scenarios": sum(1 for row in results if row.get("should_memory_help")),
        "non_value_scenarios": sum(1 for row in results if not row.get("should_memory_help")),
        "policy_successes": sum(1 for row in results if not row.get("failure_families")),
        "failure_family_counts": failure_family_counts(results),
        "summary_file": str(run_dir / "summary.json"),
        "results_file": str(run_dir / "results.jsonl"),
        "dominant_tuning_bottleneck": summary.get("dominant_tuning_bottleneck"),
    }


def _public_component_summary(run_dir: Path, summary: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
    failure_counts = {name: int(summary.get("failure_families", {}).get(name, 0)) for name in CONTINUITY_FAILURE_FAMILIES}
    return {
        "run_dir": str(run_dir),
        "scenarios_total": len(results),
        "value_scenarios": sum(1 for row in results if row.get("should_memory_help")),
        "non_value_scenarios": sum(1 for row in results if not row.get("should_memory_help")),
        "policy_successes": sum(1 for row in results if row.get("policy_success")),
        "failure_family_counts": failure_counts,
        "summary_file": str(run_dir / "summary.json"),
        "results_file": str(run_dir / "results.jsonl"),
    }


def _generic_component_summary(run_dir: Path, summary: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "run_dir": str(run_dir),
        "scenarios_total": len(results),
        "value_scenarios": 0,
        "non_value_scenarios": len(results),
        "policy_successes": int(summary.get("policy_successes", 0)),
        "failure_family_counts": {name: int(summary.get("failure_family_counts", {}).get(name, 0)) for name in CONTINUITY_FAILURE_FAMILIES},
        "summary_file": str(run_dir / "summary.json"),
        "results_file": str(run_dir / "results.jsonl"),
    }


def _aggregate_failure_counts(
    *,
    work_results: list[dict[str, Any]],
    wildchat_results: list[dict[str, Any]],
    wildbench_results: list[dict[str, Any]],
    low_value_churn_results: list[dict[str, Any]],
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    counts.update(failure for row in work_results for failure in row.get("failure_families", []))
    counts.update(failure for row in wildchat_results for failure in row.get("failure_families", []))
    counts.update(failure for row in wildbench_results for failure in row.get("failure_families", []))
    counts.update(failure for row in low_value_churn_results for failure in row.get("failure_families", []))
    return {name: int(counts.get(name, 0)) for name in CONTINUITY_FAILURE_FAMILIES}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _build_report(summary: dict[str, Any]) -> str:
    aggregate = summary["aggregate"]
    gates = summary["gates"]
    lines = [
        "# Developer-Work Confidence Report",
        "",
        f"Run ID: `{summary['run_id']}`",
        "",
        "## Aggregate",
        "",
        f"- scenarios: {aggregate['scenarios_total']}",
        f"- value scenarios: {aggregate['value_scenarios']}",
        f"- non-value scenarios: {aggregate['non_value_scenarios']}",
        f"- policy successes: {aggregate['policy_successes']} / {aggregate['scenarios_total']}",
        f"- policy success rate: {aggregate['policy_success_rate']}",
        f"- dominant tuning bottleneck: {aggregate['dominant_tuning_bottleneck'] or 'none'}",
        "",
        "## Confidence Gate",
        "",
    ]
    for gate_name, passed in gates.items():
        lines.append(f"- `{gate_name}`: {'PASS' if passed else 'FAIL'}")
    if aggregate["dominant_bottleneck_implication"]:
        lines.extend(["", f"Current implication: {aggregate['dominant_bottleneck_implication']}"])

    lines.extend(["", "## Failure Families", ""])
    for name, count in aggregate["failure_family_counts"].items():
        lines.append(f"- `{name}`: {count}")

    lines.extend(["", "## Components", ""])
    for name, component in summary["components"].items():
        lines.append(
            f"- `{name}`: {component['policy_successes']} / {component['scenarios_total']} policy successes, "
            f"failures {component['failure_family_counts']}"
        )
    return "\n".join(lines) + "\n"


def _build_run_id(config: AppConfig) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    provider = (config.llm_provider_for_default_use_case or "provider").replace("_", "-")
    model = (config.llm_model_for_default_use_case or "model").replace("/", "-").replace(".", "-")
    return f"developer-work-confidence__{provider}__{model}__{timestamp}"


if __name__ == "__main__":
    raise SystemExit(main())
