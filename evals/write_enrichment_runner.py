from __future__ import annotations

import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app.config import AppConfig
from app.dependencies import build_llm_provider
from core.models import MemoryObject
from providers.llm.base import LLMProvider
from semantic.agent_conversation_memory_enrichment import (
    DEFAULT_WRITE_ENRICHMENT_PROMPT_VARIANT,
    analyze_write_enrichment,
    get_write_enrichment_prompt_text,
)
from semantic.prompt_variant_metrics import prompt_text_metrics
from semantic.prompt_roles import get_prompt_role_contract


DEFAULT_INPUT_FILE = Path("evals/write_enrichment/input/scenarios.jsonl")
DEFAULT_OUTPUT_DIR = Path("evals/write_enrichment/output")
SANITIZE_PATTERN = re.compile(r"[^a-z0-9]+")
WRITE_ENRICHMENT_PROMPT_ROLE = get_prompt_role_contract("write_enrichment")


@dataclass(frozen=True)
class EnrichmentEvalTask:
    scenario_index: int
    scenario_id: str
    prompt_order: int
    prompt_variant: str
    memory_object: MemoryObject
    support_lines: tuple[str, ...]
    expected_action: str
    required_terms: tuple[str, ...]
    forbidden_terms: tuple[str, ...]


@dataclass(frozen=True)
class EnrichmentEvalResult:
    task: EnrichmentEvalTask
    payload: dict[str, Any]
    action: str | None
    retrieval_context: str | None


def main() -> int:
    parser = argparse.ArgumentParser(description="Run write-enrichment prompt evaluation over input fixtures.")
    parser.add_argument("--input-file", type=Path, default=DEFAULT_INPUT_FILE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--suite-name", default="write-enrichment-eval")
    parser.add_argument("--run-name", default=None)
    parser.add_argument("--prompt-variants", default=None)
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument("--split-output", action="store_true")
    args = parser.parse_args()

    config = AppConfig.from_env()
    package = config.package_config("llm_agent_memory")
    if not package.llm_provider or not package.model:
        raise ValueError("llm_agent_memory is not configured with a real provider/model")
    provider = build_llm_provider(config, provider_name=package.llm_provider, model=package.model)
    prompt_variants = [item.strip() for item in args.prompt_variants.split(",") if item.strip()] if args.prompt_variants else [DEFAULT_WRITE_ENRICHMENT_PROMPT_VARIANT]
    run_dir = run_write_enrichment_eval(
        input_file=args.input_file,
        output_root=args.output_dir,
        provider=provider,
        config=config,
        suite_name=args.suite_name,
        run_name=args.run_name,
        prompt_variants=prompt_variants,
        max_concurrency=args.max_concurrency,
        split_output=args.split_output,
    )
    print(run_dir)
    return 0


def run_write_enrichment_eval(
    *,
    input_file: Path,
    output_root: Path,
    provider: LLMProvider,
    config: AppConfig,
    suite_name: str = "write-enrichment-eval",
    run_name: str | None = None,
    prompt_variants: list[str] | None = None,
    max_concurrency: int = 1,
    split_output: bool = False,
) -> Path:
    if not input_file.exists():
        raise FileNotFoundError(f"Input file does not exist: {input_file}")
    if max_concurrency < 1:
        raise ValueError("max_concurrency must be at least 1")

    package = config.package_config("llm_agent_memory")
    provider_config = config.provider_config(package.llm_provider) if package.llm_provider else None
    resolved_variants = prompt_variants or [DEFAULT_WRITE_ENRICHMENT_PROMPT_VARIANT]
    run_id = run_name or _build_run_id(
        suite_name=suite_name,
        provider=provider_config.kind if provider_config else None,
        model=package.model,
    )
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    results_path = run_dir / "results.jsonl"

    records = list(_load_input_records(input_file))
    tasks = _build_tasks(records=records, prompt_variants=resolved_variants)
    results = _execute_tasks(tasks=tasks, provider=provider, max_concurrency=max_concurrency)

    summary = {
        "suite_name": suite_name,
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provider": provider_config.kind if provider_config else None,
        "model": package.model,
        "base_url": provider_config.base_url if provider_config else None,
        "input_file": str(input_file),
        "prompt_variants": resolved_variants,
        "prompt_role": WRITE_ENRICHMENT_PROMPT_ROLE.role,
        "prompt_schema_id": WRITE_ENRICHMENT_PROMPT_ROLE.schema_id,
        "prompt_schema_version": WRITE_ENRICHMENT_PROMPT_ROLE.schema_version,
        "prompt_text_metrics": {variant: prompt_text_metrics(get_write_enrichment_prompt_text(variant)) for variant in resolved_variants},
        "max_concurrency": max_concurrency,
        "results_file": results_path.name,
        "split_output": split_output,
        "scenarios_total": len(tasks),
        "scenarios_succeeded": 0,
        "scenarios_failed": 0,
        "split_outputs": [],
        "per_variant": {},
    }

    for variant in resolved_variants:
        summary["per_variant"][variant] = _empty_variant_summary(
            scenarios_total=len(records),
            prompt_text_metrics=prompt_text_metrics(get_write_enrichment_prompt_text(variant)),
        )

    with results_path.open("w", encoding="utf-8") as results_file:
        for result in results:
            task = result.task
            payload = result.payload
            variant_summary = summary["per_variant"][task.prompt_variant]
            if payload["status"] == "ok":
                summary["scenarios_succeeded"] += 1
                variant_summary["scenarios_succeeded"] += 1
                _update_variant_summary(
                    variant_summary,
                    expected_action=task.expected_action,
                    actual_action=result.action or "NO_OP",
                    retrieval_context=result.retrieval_context,
                    required_terms=task.required_terms,
                    forbidden_terms=task.forbidden_terms,
                )
            else:
                summary["scenarios_failed"] += 1
                variant_summary["scenarios_failed"] += 1

            results_file.write(json.dumps(payload) + "\n")
            if split_output:
                output_name = f"{task.scenario_id}__{_slugify(task.prompt_variant)}.result.json"
                output_path = run_dir / output_name
                output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                summary["split_outputs"].append(output_name)

    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return run_dir


def _build_tasks(*, records: list[dict[str, Any]], prompt_variants: list[str]) -> list[EnrichmentEvalTask]:
    tasks: list[EnrichmentEvalTask] = []
    for index, record in enumerate(records, start=1):
        memory_object = MemoryObject(
            type=str(record["memory_type"]),
            schema_id=str(record.get("schema_id") or f"semantic.{record['memory_type']}"),
            schema_version=str(record.get("schema_version") or "v1"),
            payload=dict(record.get("payload") or {}),
        )
        scenario_id = str(record.get("scenario_id") or f"scenario-{index:03d}")
        expected_action = str(record.get("expected_action") or "NO_OP").upper()
        support_lines = tuple(str(item) for item in (record.get("support_lines") or []))
        required_terms = tuple(str(item).lower() for item in (record.get("required_terms") or []))
        forbidden_terms = tuple(str(item).lower() for item in (record.get("forbidden_terms") or []))
        for prompt_order, variant in enumerate(prompt_variants):
            tasks.append(
                EnrichmentEvalTask(
                    scenario_index=index,
                    scenario_id=scenario_id,
                    prompt_order=prompt_order,
                    prompt_variant=variant,
                    memory_object=memory_object,
                    support_lines=support_lines,
                    expected_action=expected_action,
                    required_terms=required_terms,
                    forbidden_terms=forbidden_terms,
                )
            )
    return tasks


def _execute_tasks(*, tasks: list[EnrichmentEvalTask], provider: LLMProvider, max_concurrency: int) -> list[EnrichmentEvalResult]:
    if max_concurrency == 1:
        return [_evaluate_task(task, provider) for task in tasks]

    results: list[EnrichmentEvalResult] = []
    with ThreadPoolExecutor(max_workers=max_concurrency) as executor:
        futures = [executor.submit(_evaluate_task, task, provider) for task in tasks]
        for future in as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda item: (item.task.scenario_index, item.task.prompt_order))
    return results


def _evaluate_task(task: EnrichmentEvalTask, provider: LLMProvider) -> EnrichmentEvalResult:
    payload: dict[str, Any] = {
        "scenario_id": task.scenario_id,
        "prompt_variant": task.prompt_variant,
        "status": "ok",
        "memory_object": _serialize(task.memory_object),
        "support_lines": list(task.support_lines),
        "expected_action": task.expected_action,
    }
    try:
        trace = analyze_write_enrichment(
            provider=provider,
            memory_object=task.memory_object,
            support_lines=task.support_lines,
            prompt_variant=task.prompt_variant,
        )
        payload["request"] = _serialize(trace.request)
        payload["llm_response"] = {
            "raw_text": trace.response.raw_text,
            "parsed_json": trace.response.parsed_json,
        }
        payload["action"] = trace.action
        payload["retrieval_context"] = trace.retrieval_context
        return EnrichmentEvalResult(
            task=task,
            payload=payload,
            action=trace.action,
            retrieval_context=trace.retrieval_context,
        )
    except Exception as exc:
        payload["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        payload["status"] = "error"
        return EnrichmentEvalResult(task=task, payload=payload, action=None, retrieval_context=None)


def _load_input_records(input_file: Path) -> Iterable[dict[str, Any]]:
    for line in input_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        yield json.loads(stripped)


def _empty_variant_summary(*, scenarios_total: int, prompt_text_metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "prompt_role": WRITE_ENRICHMENT_PROMPT_ROLE.role,
        "prompt_schema_id": WRITE_ENRICHMENT_PROMPT_ROLE.schema_id,
        "prompt_schema_version": WRITE_ENRICHMENT_PROMPT_ROLE.schema_version,
        "prompt_text_metrics": prompt_text_metrics,
        "scenarios_total": scenarios_total,
        "scenarios_succeeded": 0,
        "scenarios_failed": 0,
        "action_correct": 0,
        "scenario_successes": 0,
        "required_term_hits": 0,
        "required_term_misses": 0,
        "forbidden_term_violations": 0,
    }


def _update_variant_summary(
    variant_summary: dict[str, Any],
    *,
    expected_action: str,
    actual_action: str,
    retrieval_context: str | None,
    required_terms: tuple[str, ...],
    forbidden_terms: tuple[str, ...],
) -> None:
    if actual_action == expected_action:
        variant_summary["action_correct"] += 1

    normalized_context = str(retrieval_context or "").lower()
    required_ok = True
    for term in required_terms:
        if term in normalized_context:
            variant_summary["required_term_hits"] += 1
        else:
            variant_summary["required_term_misses"] += 1
            required_ok = False

    forbidden_ok = True
    for term in forbidden_terms:
        if term and term in normalized_context:
            variant_summary["forbidden_term_violations"] += 1
            forbidden_ok = False

    if actual_action == expected_action and required_ok and forbidden_ok:
        variant_summary["scenario_successes"] += 1


def _build_run_id(*, suite_name: str, provider: str | None, model: str | None) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    parts = [suite_name, provider or "unknown-provider", model or "unknown-model", timestamp]
    return "__".join(_slugify(part) for part in parts)


def _slugify(value: str) -> str:
    normalized = SANITIZE_PATTERN.sub("-", value.strip().lower()).strip("-")
    return normalized or "unknown"


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _serialize(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


if __name__ == "__main__":
    raise SystemExit(main())
