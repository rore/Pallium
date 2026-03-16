from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import AppConfig
from evals.benchmark_architecture import BenchmarkLane, build_aggregate_summary
from evals.continuity_common import (
    CONTINUITY_FAILURE_FAMILIES,
    dominant_bottleneck_implication,
    dominant_tuning_bottleneck,
    failure_family_counts,
)
from evals.low_value_churn_benchmark import run_low_value_churn_benchmark
from evals.memory_routing_benchmark import run_memory_routing_benchmark
from evals.public_corpus_benchmark import run_public_corpus_benchmark
from evals.work_resumption_benchmark import run_work_resumption_benchmark
from providers.llm.base import LLMProvider

DEFAULT_OUTPUT_DIR = Path("evals/developer_work_confidence/output")
DEFAULT_WORK_SCENARIO_FILE = Path("evals/work_resumption/scenarios.json")
DEFAULT_MEMORY_ROUTING_SCENARIO_FILE = Path("evals/memory_routing/scenarios.json")
DEFAULT_WILDCHAT_MANIFEST = Path("evals/public_corpus/wildchat_review_manifest.json")
DEFAULT_WILDBENCH_MANIFEST = Path("evals/public_corpus/wildbench_developer_continuation_manifest.json")
DEFAULT_LOW_VALUE_CHURN_SCENARIO_FILE = Path("evals/low_value_churn/scenarios.json")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the combined developer-work confidence suite.")
    parser.add_argument("--work-scenario-file", type=Path, default=DEFAULT_WORK_SCENARIO_FILE)
    parser.add_argument("--memory-routing-scenario-file", type=Path, default=DEFAULT_MEMORY_ROUTING_SCENARIO_FILE)
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
        memory_routing_scenario_file=args.memory_routing_scenario_file,
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
    memory_routing_scenario_file: Path = DEFAULT_MEMORY_ROUTING_SCENARIO_FILE,
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
    memory_routing_answer_provider: LLMProvider | None = None,
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
    memory_routing_run_dir = run_memory_routing_benchmark(
        scenario_file=memory_routing_scenario_file,
        output_root=run_dir / "memory_routing",
        config=config,
        run_name="memory-routing",
        answer_provider=memory_routing_answer_provider,
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
    memory_routing_summary = _read_json(memory_routing_run_dir / "summary.json")
    memory_routing_results = _read_jsonl(memory_routing_run_dir / "results.jsonl")
    wildchat_summary = _read_json(wildchat_run_dir / "summary.json")
    wildchat_results = _read_jsonl(wildchat_run_dir / "results.jsonl")
    wildbench_summary = _read_json(wildbench_run_dir / "summary.json")
    wildbench_results = _read_jsonl(wildbench_run_dir / "results.jsonl")
    low_value_churn_summary = _read_json(low_value_churn_run_dir / "summary.json")
    low_value_churn_results = _read_jsonl(low_value_churn_run_dir / "results.jsonl")

    all_results = [
        *work_results,
        *memory_routing_results,
        *wildchat_results,
        *wildbench_results,
        *low_value_churn_results,
    ]
    aggregate_failure_counts = _aggregate_failure_counts(results=all_results)
    dominant_bottleneck = dominant_tuning_bottleneck(aggregate_failure_counts)
    benchmark = build_aggregate_summary(results=all_results)

    components = {
        "work_resumption": _component_summary(work_run_dir, work_summary, work_results, success_key="failure_families"),
        "memory_routing": _component_summary(memory_routing_run_dir, memory_routing_summary, memory_routing_results, success_key="policy_success"),
        "wildchat_reviewed": _component_summary(wildchat_run_dir, wildchat_summary, wildchat_results, success_key="policy_success"),
        "wildbench_developer": _component_summary(wildbench_run_dir, wildbench_summary, wildbench_results, success_key="policy_success"),
        "low_value_churn": _component_summary(low_value_churn_run_dir, low_value_churn_summary, low_value_churn_results, success_key="policy_success"),
    }

    aggregate = {
        "scenarios_total": len(all_results),
        "value_scenarios": sum(1 for row in all_results if row.get("should_memory_help") or row.get("expected_value")),
        "non_value_scenarios": sum(1 for row in all_results if row.get("should_memory_help") is False or row.get("expected_value") is False),
        "policy_successes": sum(component["policy_successes"] for component in components.values()),
        "failure_family_counts": aggregate_failure_counts,
        "dominant_tuning_bottleneck": dominant_bottleneck,
        "dominant_bottleneck_implication": dominant_bottleneck_implication(dominant_bottleneck),
        "benchmark": benchmark,
        "hard_gate_status": benchmark["hard_gate_summary"],
        "tier_aggregates": benchmark["tier_aggregates"],
        "lane_aggregates": benchmark["lane_aggregates"],
        "dominant_benchmark_lane": benchmark["dominant_lane"],
    }
    aggregate["policy_success_rate"] = round(
        aggregate["policy_successes"] / aggregate["scenarios_total"],
        4,
    ) if aggregate["scenarios_total"] else 0.0

    contract_green = benchmark["lane_aggregates"][BenchmarkLane.CONTRACT.value]["failures"] == 0
    trace_green = benchmark["lane_aggregates"][BenchmarkLane.TRACE.value]["failures"] == 0
    operational_drift_present = benchmark["lane_aggregates"][BenchmarkLane.OPERATIONAL.value]["failures"] > 0
    realism_pressure_present = benchmark["lane_aggregates"][BenchmarkLane.REALISM.value]["failures"] > 0

    gates = {
        "contract_hard_gate_green": contract_green,
        "trace_hard_gate_green": trace_green,
        "hard_gate_passed": benchmark["hard_gate_summary"]["all_green"],
        "zero_privacy_leaks": aggregate_failure_counts["privacy_leak_failure"] == 0,
        "zero_wrong_memory_failures": aggregate_failure_counts["wrong_memory_selection_failure"] == 0,
        "zero_stale_memory_failures": aggregate_failure_counts["stale_memory_failure"] == 0,
        "zero_no_value_overreach_failures": aggregate_failure_counts["no_value_overreach_failure"] == 0,
        "zero_low_value_promotion_failures": aggregate_failure_counts["low_value_promotion_failure"] == 0,
        "zero_thread_rebuild_churn_failures": aggregate_failure_counts["thread_rebuild_churn_failure"] == 0,
        "work_suite_green": components["work_resumption"]["policy_successes"] == components["work_resumption"]["scenarios_total"],
        "memory_routing_suite_green": components["memory_routing"]["policy_successes"] == components["memory_routing"]["scenarios_total"],
        "wildchat_suite_green": components["wildchat_reviewed"]["policy_successes"] == components["wildchat_reviewed"]["scenarios_total"],
        "wildbench_suite_green": components["wildbench_developer"]["policy_successes"] == components["wildbench_developer"]["scenarios_total"],
        "low_value_churn_suite_green": components["low_value_churn"]["policy_successes"] == components["low_value_churn"]["scenarios_total"],
        "realism_pressure_present": realism_pressure_present,
        "operational_drift_present": operational_drift_present,
        "replay_assets_present": benchmark["replay_summary"]["has_replay_assets"],
        "confidence_gate_passed": benchmark["hard_gate_summary"]["all_green"],
    }

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


def _component_summary(
    run_dir: Path,
    summary: dict[str, Any],
    results: list[dict[str, Any]],
    *,
    success_key: str,
) -> dict[str, Any]:
    if success_key == "failure_families":
        policy_successes = sum(1 for row in results if not row.get("failure_families"))
    else:
        policy_successes = sum(1 for row in results if row.get(success_key))
    return {
        "run_dir": str(run_dir),
        "suite_id": str(summary.get("benchmark", {}).get("suite_id") or (results[0].get("suite_id") if results else "unknown")),
        "dataset_tier": str(summary.get("benchmark", {}).get("dataset_tier") or (results[0].get("dataset_tier") if results else "unknown")),
        "primary_lane": str(summary.get("benchmark", {}).get("primary_lane") or (results[0].get("primary_lane") if results else "unknown")),
        "scenarios_total": len(results),
        "value_scenarios": sum(1 for row in results if row.get("should_memory_help") or row.get("expected_value")),
        "non_value_scenarios": sum(1 for row in results if row.get("should_memory_help") is False or row.get("expected_value") is False),
        "policy_successes": policy_successes,
        "failure_family_counts": failure_family_counts(results),
        "summary_file": str(run_dir / "summary.json"),
        "results_file": str(run_dir / "results.jsonl"),
        "dominant_tuning_bottleneck": summary.get("dominant_tuning_bottleneck"),
        "benchmark": summary.get("benchmark", {}),
    }


def _aggregate_failure_counts(*, results: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    counts.update(failure for row in results for failure in row.get("failure_families", []))
    return {name: int(counts.get(name, 0)) for name in CONTINUITY_FAILURE_FAMILIES}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _build_report(summary: dict[str, Any]) -> str:
    aggregate = summary["aggregate"]
    gates = summary["gates"]
    benchmark = aggregate["benchmark"]
    contract_lane = benchmark["lane_aggregates"][BenchmarkLane.CONTRACT.value]
    trace_lane = benchmark["lane_aggregates"][BenchmarkLane.TRACE.value]
    realism_lane = benchmark["lane_aggregates"][BenchmarkLane.REALISM.value]
    operational_lane = benchmark["lane_aggregates"][BenchmarkLane.OPERATIONAL.value]
    operational_summary = benchmark["operational_summary"]
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
        f"- dominant benchmark lane: {aggregate['dominant_benchmark_lane'] or 'none'}",
        f"- dominant tuning bottleneck: {aggregate['dominant_tuning_bottleneck'] or 'none'}",
        "",
        "## Hard-Gate Foundation",
        "",
        f"- `contract`: {contract_lane['successes']} / {contract_lane['scenarios_total']} ({'PASS' if gates['contract_hard_gate_green'] else 'FAIL'})",
        f"- `trace`: {trace_lane['successes']} / {trace_lane['scenarios_total']} ({'PASS' if gates['trace_hard_gate_green'] else 'FAIL'})",
        f"- failing hard-gate lanes: {benchmark['hard_gate_summary']['failing_lanes'] or 'none'}",
        f"- `hard_gate_passed`: {'PASS' if gates['hard_gate_passed'] else 'FAIL'}",
        f"- `confidence_gate_passed`: {'PASS' if gates['confidence_gate_passed'] else 'FAIL'}",
    ]
    if aggregate["dominant_bottleneck_implication"]:
        lines.extend(["", f"Current implication: {aggregate['dominant_bottleneck_implication']}"])

    lines.extend([
        "",
        "## Realism And Replay Pressure",
        "",
        f"- `realism`: {realism_lane['successes']} / {realism_lane['scenarios_total']}",
        f"- `realism_pressure_present`: {'YES' if gates['realism_pressure_present'] else 'NO'}",
        f"- confidence tier scenarios: {benchmark['tier_aggregates']['confidence']['scenarios_total']}",
        f"- replay tier scenarios: {benchmark['tier_aggregates']['replay']['scenarios_total']}",
        f"- replay assets present: {'YES' if gates['replay_assets_present'] else 'NO'}",
    ])

    lines.extend([
        "",
        "## Operational Drift",
        "",
        f"- `operational`: {operational_lane['successes']} / {operational_lane['scenarios_total']}",
        f"- `operational_drift_present`: {'YES' if gates['operational_drift_present'] else 'NO'}",
        f"- injected block distribution: {operational_summary['injected_block_count_distribution'] or 'none'}",
        f"- no-value overreach: {operational_summary['no_value_overreach_failures']} / {operational_summary['no_value_scenarios']}",
        f"- stale-memory failures: {operational_summary['stale_memory_failures']}",
        f"- wrong-memory failures: {operational_summary['wrong_memory_selection_failures']}",
        f"- low-value promotion failures: {operational_summary['low_value_promotion_failures']}",
        f"- thread-rebuild churn failures: {operational_summary['thread_rebuild_churn_failures']}",
    ])

    lines.extend(["", "## Failure Families", ""])
    for name, count in aggregate["failure_family_counts"].items():
        lines.append(f"- `{name}`: {count}")

    lines.extend(["", "## Components", ""])
    for name, component in summary["components"].items():
        lines.append(
            f"- `{name}`: tier `{component['dataset_tier']}`, primary lane `{component['primary_lane']}`, "
            f"policy {component['policy_successes']} / {component['scenarios_total']}, lane rollups {component['benchmark'].get('lane_aggregates', {})}"
        )
    return "\n".join(lines) + "\n"


def _build_run_id(config: AppConfig) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    provider = (config.llm_provider_for_default_use_case or "provider").replace("_", "-")
    model = (config.llm_model_for_default_use_case or "model").replace("/", "-").replace(".", "-")
    return f"developer-work-confidence__{provider}__{model}__{timestamp}"


if __name__ == "__main__":
    raise SystemExit(main())