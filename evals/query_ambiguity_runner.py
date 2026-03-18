from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import AppConfig
from app.dependencies import build_llm_provider
from providers.llm.base import LLMProvider
from semantic.agent_conversation_memory_resolver import (
    ResolverPacket,
    ResolverResult,
    build_resolver_packet,
    resolve_query_ambiguity,
)
from semantic.agent_conversation_memory_resolver_prompts import (
    QAR_VARIANTS,
    list_qar_variants,
)


def run_qar_benchmark(
    *,
    scenario_file: Path,
    output_root: Path,
    config: AppConfig,
    run_name: str | None = None,
    provider: LLMProvider | None = None,
) -> Path:
    default_package = config.package_config(config.default_use_case)
    if provider is None:
        if not default_package.llm_provider or not default_package.model:
            raise ValueError(f"Default use case '{config.default_use_case}' is missing LLM config")
        provider = build_llm_provider(config, provider_name=default_package.llm_provider, model=default_package.model)

    scenarios = _load_scenarios(scenario_file)
    variants = list_qar_variants()
    run_id = run_name or _build_run_id(config)
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    all_results: list[dict[str, Any]] = []
    for scenario in scenarios:
        for variant in variants:
            result = _run_one(scenario=scenario, variant=variant, provider=provider)
            all_results.append(result)

    results_file = run_dir / "results.jsonl"
    results_file.write_text(
        "\n".join(json.dumps(r, default=str) for r in all_results) + "\n",
        encoding="utf-8",
    )

    summary = _build_summary(
        results=all_results,
        variants=variants,
        config=config,
        scenario_count=len(scenarios),
    )
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    report = _build_report(summary, all_results)
    (run_dir / "report.md").write_text(report, encoding="utf-8")

    return run_dir


def _load_scenarios(path: Path) -> list[dict[str, Any]]:
    scenarios = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        scenarios.append(json.loads(stripped))
    return scenarios


def _run_one(
    *,
    scenario: dict[str, Any],
    variant: str,
    provider: LLMProvider,
) -> dict[str, Any]:
    packet = build_resolver_packet(
        query_text=scenario["query_text"],
        turn_kind=scenario.get("turn_kind"),
        ambiguity_pair_type=scenario["ambiguity_pair_type"],
        option_a=scenario["option_a"],
        option_b=scenario["option_b"],
        candidates=scenario.get("candidates", []),
    )

    result = resolve_query_ambiguity(
        provider=provider,
        model=None,
        prompt_variant=variant,
        resolver_packet=packet,
        timeout_ms=800,
    )

    expected_action = scenario.get("expected_action", "SELECT")
    expected_option = scenario.get("expected_option_id")

    schema_valid = (
        result.action in {"SELECT", "FALLBACK"}
        and (result.selected_option_id in {"A", "B", None})
        and result.confidence in {"high", "medium", "low"}
    )

    if expected_action == "FALLBACK":
        option_correct = result.action == "FALLBACK"
        fallback_disciplined = result.action == "FALLBACK"
    elif expected_action == "SELECT":
        option_correct = result.action == "SELECT" and result.selected_option_id == expected_option
        fallback_disciplined = result.action != "FALLBACK"  # should not fall back on clear scenarios
    else:
        option_correct = False
        fallback_disciplined = True

    return {
        "scenario_id": scenario["scenario_id"],
        "scenario_kind": scenario.get("scenario_kind", ""),
        "prompt_variant": variant,
        "query_text": scenario["query_text"],
        "ambiguity_pair_type": scenario["ambiguity_pair_type"],
        "expected_action": expected_action,
        "expected_option_id": expected_option,
        "action": result.action,
        "selected_option_id": result.selected_option_id,
        "confidence": result.confidence,
        "reason_codes": list(result.reason_codes),
        "latency_ms": round(result.latency_ms, 1),
        "schema_valid": schema_valid,
        "option_correct": option_correct,
        "fallback_disciplined": fallback_disciplined,
        "scenario_success": schema_valid and option_correct and fallback_disciplined,
    }


def _build_summary(
    *,
    results: list[dict[str, Any]],
    variants: list[str],
    config: AppConfig,
    scenario_count: int,
) -> dict[str, Any]:
    per_variant: dict[str, dict[str, Any]] = {}
    for variant in variants:
        vr = [r for r in results if r["prompt_variant"] == variant]
        schema_valid_count = sum(1 for r in vr if r["schema_valid"])
        option_correct_count = sum(1 for r in vr if r["option_correct"])
        fallback_disciplined_count = sum(1 for r in vr if r["fallback_disciplined"])
        success_count = sum(1 for r in vr if r["scenario_success"])
        latencies = [r["latency_ms"] for r in vr if r["latency_ms"] > 0]
        prompt_text = QAR_VARIANTS.get(variant, "")

        per_variant[variant] = {
            "total": len(vr),
            "schema_valid": schema_valid_count,
            "option_correct": option_correct_count,
            "fallback_disciplined": fallback_disciplined_count,
            "success": success_count,
            "success_rate": round(success_count / len(vr), 3) if vr else 0.0,
            "mean_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0.0,
            "max_latency_ms": round(max(latencies), 1) if latencies else 0.0,
            "prompt_chars": len(prompt_text),
            "prompt_words": len(prompt_text.split()),
        }

    # Find winner: highest success rate, then smallest prompt
    ranked = sorted(
        per_variant.items(),
        key=lambda kv: (-kv[1]["success_rate"], kv[1]["prompt_chars"]),
    )
    winner = ranked[0][0] if ranked else variants[0]

    return {
        "suite": "query_ambiguity_resolution",
        "scenarios_total": scenario_count,
        "variants_total": len(variants),
        "results_total": len(results),
        "provider": config.llm_provider_for_default_use_case,
        "model": config.llm_model_for_default_use_case,
        "per_variant": per_variant,
        "winner": winner,
        "winner_success_rate": per_variant[winner]["success_rate"],
    }


def _build_report(summary: dict[str, Any], results: list[dict[str, Any]]) -> str:
    lines = [
        "# Query Ambiguity Resolution — Prompt Variant Bakeoff",
        "",
        f"Provider: {summary['provider']}",
        f"Model: {summary['model']}",
        f"Scenarios: {summary['scenarios_total']}",
        f"Variants: {summary['variants_total']}",
        "",
        "## Per-Variant Results",
        "",
        "| Variant | Success | Schema | Option | Fallback | Rate | Mean ms | Prompt chars |",
        "|---------|---------|--------|--------|----------|------|---------|-------------|",
    ]
    for variant, stats in summary["per_variant"].items():
        lines.append(
            f"| {variant} | {stats['success']}/{stats['total']} | {stats['schema_valid']} | "
            f"{stats['option_correct']} | {stats['fallback_disciplined']} | "
            f"{stats['success_rate']:.1%} | {stats['mean_latency_ms']:.0f} | {stats['prompt_chars']} |"
        )
    lines.extend([
        "",
        f"## Winner: `{summary['winner']}` ({summary['winner_success_rate']:.1%})",
        "",
        "## Scenario Detail",
        "",
    ])
    for r in results:
        status = "PASS" if r["scenario_success"] else "FAIL"
        lines.append(
            f"- [{status}] {r['scenario_id']} / {r['prompt_variant']}: "
            f"{r['action']}({r['selected_option_id']}) conf={r['confidence']} "
            f"expected={r['expected_action']}({r['expected_option_id']}) "
            f"latency={r['latency_ms']:.0f}ms"
        )
    lines.append("")
    return "\n".join(lines)


def _build_run_id(config: AppConfig) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    provider = (config.llm_provider_for_default_use_case or "provider").replace("_", "-")
    model = (config.llm_model_for_default_use_case or "model").replace("/", "-").replace(".", "-")
    return f"qar-benchmark__{provider}__{model}__{timestamp}"


if __name__ == "__main__":
    import sys

    scenario_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("evals/query_ambiguity/input/scenarios.jsonl")
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("evals/query_ambiguity/output")

    app_config = AppConfig.from_env()
    run_dir = run_qar_benchmark(
        scenario_file=scenario_path,
        output_root=output_path,
        config=app_config,
    )
    print(f"Results: {run_dir}")

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    print(f"Winner: {summary['winner']} ({summary['winner_success_rate']:.1%})")
    for variant, stats in summary["per_variant"].items():
        print(f"  {variant}: {stats['success']}/{stats['total']} ({stats['success_rate']:.1%}) mean={stats['mean_latency_ms']:.0f}ms")
