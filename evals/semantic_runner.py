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
from app.dependencies import build_semantic_plugins
from core.contracts import build_source_item
from core.models import SourceItem
from semantic.llm_agent_memory import LLMAgentMemoryPlugin, get_prompt_variant_text
from semantic.prompt_variant_metrics import prompt_text_metrics
from semantic.prompt_roles import get_prompt_role_contract


DEFAULT_INPUT_FILE = Path("evals/semantic/input/items.jsonl")
DEFAULT_OUTPUT_DIR = Path("evals/semantic/output")
SANITIZE_PATTERN = re.compile(r"[^a-z0-9]+")
TRACKED_TYPED_KINDS = ("decision", "investigation_outcome")
TRACKED_SIGNAL_FIELDS = (
    "is_low_value_meta",
    "constraint_text",
    "next_step_text",
    "blocker_text",
    "progress_text",
    "key_finding_text",
    "subject_hints",
    "constraint_candidates",
)
WRITE_EXTRACTION_PROMPT_ROLE = get_prompt_role_contract("write_extraction")


@dataclass(frozen=True)
class EvalTask:
    input_index: int
    input_key: str
    prompt_order: int
    prompt_variant: str
    source_item: SourceItem


@dataclass(frozen=True)
class EvalResult:
    task: EvalTask
    payload: dict[str, Any]
    promoted_type: str | None


def main() -> int:
    parser = argparse.ArgumentParser(description="Run LLM semantic evaluation over input fixtures.")
    parser.add_argument("--input-file", type=Path, default=DEFAULT_INPUT_FILE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--use-case", default="llm_agent_memory")
    parser.add_argument("--suite-name", default="semantic-eval")
    parser.add_argument("--run-name", default=None)
    parser.add_argument("--prompt-variants", default=None)
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument("--split-output", action="store_true")
    args = parser.parse_args()

    config = AppConfig.from_env()
    plugins = build_semantic_plugins(config)
    plugin = plugins.get(args.use_case)
    if not isinstance(plugin, LLMAgentMemoryPlugin):
        raise ValueError(f"Use case '{args.use_case}' is not an LLM-backed semantic plugin")

    prompt_variants = [item.strip() for item in args.prompt_variants.split(",") if item.strip()] if args.prompt_variants else [plugin.prompt_variant]
    run_dir = run_semantic_eval(
        input_file=args.input_file,
        output_root=args.output_dir,
        plugin=plugin,
        config=config,
        suite_name=args.suite_name,
        run_name=args.run_name,
        prompt_variants=prompt_variants,
        max_concurrency=args.max_concurrency,
        split_output=args.split_output,
    )
    print(run_dir)
    return 0


def run_semantic_eval(
    *,
    input_file: Path,
    output_root: Path,
    plugin: LLMAgentMemoryPlugin,
    config: AppConfig,
    suite_name: str = "semantic-eval",
    run_name: str | None = None,
    prompt_variants: list[str] | None = None,
    max_concurrency: int = 1,
    split_output: bool = False,
) -> Path:
    if not input_file.exists():
        raise FileNotFoundError(f"Input file does not exist: {input_file}")
    if max_concurrency < 1:
        raise ValueError("max_concurrency must be at least 1")

    resolved_variants = prompt_variants or [plugin.prompt_variant]
    package_config = config.semantic_packages.get(plugin.name)
    provider_config = config.llm_providers.get(package_config.llm_provider) if package_config and package_config.llm_provider else None
    run_id = run_name or _build_run_id(
        suite_name=suite_name,
        provider=provider_config.kind if provider_config else None,
        model=package_config.model if package_config else None,
    )
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    results_path = run_dir / "results.jsonl"

    records = list(_load_input_records(input_file))
    tasks = _build_tasks(records=records, prompt_variants=resolved_variants)
    results = _execute_tasks(tasks=tasks, plugin=plugin, max_concurrency=max_concurrency)

    summary = {
        "suite_name": suite_name,
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provider": provider_config.kind if provider_config else None,
        "model": package_config.model if package_config else None,
        "base_url": provider_config.base_url if provider_config else None,
        "use_case": plugin.name,
        "input_file": str(input_file),
        "prompt_variants": resolved_variants,
        "prompt_role": WRITE_EXTRACTION_PROMPT_ROLE.role,
        "prompt_schema_id": WRITE_EXTRACTION_PROMPT_ROLE.schema_id,
        "prompt_schema_version": WRITE_EXTRACTION_PROMPT_ROLE.schema_version,
        "prompt_text_metrics": {variant: prompt_text_metrics(get_prompt_variant_text(variant)) for variant in resolved_variants},
        "max_concurrency": max_concurrency,
        "results_file": results_path.name,
        "split_output": split_output,
        "items_total": len(tasks),
        "items_succeeded": 0,
        "items_failed": 0,
        "promoted_counts": {"decision": 0, "investigation_outcome": 0, "discussion_summary": 0},
        "split_outputs": [],
        "per_variant": {},
    }

    for variant in resolved_variants:
        summary["per_variant"][variant] = _empty_variant_summary(
            items_total=len(records),
            prompt_text_metrics=prompt_text_metrics(get_prompt_variant_text(variant)),
        )

    with results_path.open("w", encoding="utf-8") as results_file:
        for result in results:
            task = result.task
            payload = result.payload
            variant_summary = summary["per_variant"][task.prompt_variant]
            expected_kind = _expected_kind(task.source_item)
            expected_signal_truths = _expected_signal_truths(task.source_item)

            if payload["status"] == "ok":
                summary["items_succeeded"] += 1
                variant_summary["items_succeeded"] += 1
                if result.promoted_type in summary["promoted_counts"]:
                    summary["promoted_counts"][result.promoted_type] += 1
                if result.promoted_type in variant_summary["promoted_counts"]:
                    variant_summary["promoted_counts"][result.promoted_type] += 1
                _update_expected_metrics(variant_summary, expected_kind=expected_kind, predicted_type=result.promoted_type)
                _update_signal_metrics(
                    variant_summary,
                    expected_signal_truths=expected_signal_truths,
                    normalized_extraction=payload.get("normalized_extraction") or {},
                )
            else:
                summary["items_failed"] += 1
                variant_summary["items_failed"] += 1

            results_file.write(json.dumps(payload) + "\n")

            if split_output:
                output_name = f"{task.input_key}__{_slugify(task.prompt_variant)}.result.json"
                output_path = run_dir / output_name
                output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                summary["split_outputs"].append(output_name)

    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return run_dir


def _build_tasks(*, records: list[dict[str, Any]], prompt_variants: list[str]) -> list[EvalTask]:
    tasks: list[EvalTask] = []
    for index, payload in enumerate(records, start=1):
        source_item = build_source_item(
            source_type=payload["source_type"],
            source_id=payload["source_id"],
            content_type=payload["content_type"],
            content=payload["content"],
            metadata=payload.get("metadata"),
            occurred_at=_parse_datetime(payload.get("occurred_at")),
            actor_ref=payload.get("actor_ref"),
            role=payload.get("role"),
            container_ref=payload.get("container_ref"),
            thread_ref=payload.get("thread_ref"),
            session_ref=payload.get("session_ref"),
            source_ref=payload.get("source_ref"),
            artifact_kind=payload.get("artifact_kind"),
        )
        input_key = _build_input_key(index=index, source_id=source_item.source_id)
        for prompt_order, variant in enumerate(prompt_variants):
            tasks.append(
                EvalTask(
                    input_index=index,
                    input_key=input_key,
                    prompt_order=prompt_order,
                    prompt_variant=variant,
                    source_item=source_item,
                )
            )
    return tasks


def _execute_tasks(*, tasks: list[EvalTask], plugin: LLMAgentMemoryPlugin, max_concurrency: int) -> list[EvalResult]:
    if max_concurrency == 1:
        return [_evaluate_task(task, plugin) for task in tasks]

    results: list[EvalResult] = []
    with ThreadPoolExecutor(max_workers=max_concurrency) as executor:
        futures = [executor.submit(_evaluate_task, task, plugin) for task in tasks]
        for future in as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda item: (item.task.input_index, item.task.prompt_order))
    return results


def _evaluate_task(task: EvalTask, plugin: LLMAgentMemoryPlugin) -> EvalResult:
    variant_plugin = plugin.with_prompt_variant(task.prompt_variant)
    payload: dict[str, Any] = {
        "input_index": task.input_index,
        "input_key": task.input_key,
        "prompt_variant": task.prompt_variant,
        "status": "ok",
        "source_item": _serialize(task.source_item),
    }

    try:
        trace = variant_plugin.analyze_item(task.source_item)
        payload["request"] = _serialize(trace.request)
        payload["llm_response"] = {
            "raw_text": trace.response.raw_text,
            "parsed_json": trace.response.parsed_json,
        }
        payload["normalized_extraction"] = _serialize(trace.extraction)
        payload["artifacts"] = _serialize(trace.process_result)
        promoted_type = trace.process_result.memory_objects[0].type if trace.process_result.memory_objects else None
        return EvalResult(task=task, payload=payload, promoted_type=promoted_type)
    except Exception as exc:
        payload["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        payload["status"] = "error"
        return EvalResult(task=task, payload=payload, promoted_type=None)


def _load_input_records(input_file: Path) -> Iterable[dict[str, Any]]:
    for line in input_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        yield json.loads(stripped)


def _build_run_id(*, suite_name: str, provider: str | None, model: str | None) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    parts = [suite_name, provider or "unknown-provider", model or "unknown-model", timestamp]
    return "__".join(_slugify(part) for part in parts)


def _build_input_key(*, index: int, source_id: str) -> str:
    return f"{index:03d}-{_slugify(source_id)}"


def _expected_kind(source_item: Any) -> str | None:
    metadata = getattr(source_item, "metadata", None) or {}
    expected_kind = metadata.get("expected_kind")
    if not isinstance(expected_kind, str):
        return None
    normalized = expected_kind.strip()
    return normalized or None


def _expected_signal_truths(source_item: Any) -> dict[str, bool]:
    metadata = getattr(source_item, "metadata", None) or {}
    raw = metadata.get("expected_signal_truths")
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, bool] = {}
    for key, value in raw.items():
        if isinstance(key, str) and isinstance(value, bool) and key in TRACKED_SIGNAL_FIELDS:
            normalized[key] = value
    return normalized


def _empty_variant_summary(*, items_total: int, prompt_text_metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "prompt_role": WRITE_EXTRACTION_PROMPT_ROLE.role,
        "prompt_schema_id": WRITE_EXTRACTION_PROMPT_ROLE.schema_id,
        "prompt_schema_version": WRITE_EXTRACTION_PROMPT_ROLE.schema_version,
        "prompt_text_metrics": prompt_text_metrics,
        "items_total": items_total,
        "items_succeeded": 0,
        "items_failed": 0,
        "overall_correct": 0,
        "signal_cases_total": 0,
        "signal_cases_correct": 0,
        "promoted_counts": {"decision": 0, "investigation_outcome": 0, "discussion_summary": 0},
        "expected_counts": {"decision": 0, "investigation_outcome": 0, "discussion_summary": 0},
        "type_metrics": {
            kind: {"expected": 0, "predicted": 0, "correct": 0, "false_positive": 0, "false_negative": 0}
            for kind in TRACKED_TYPED_KINDS
        },
        "signal_metrics": {
            field: {"expected_true": 0, "expected_false": 0, "correct": 0, "false_positive": 0, "false_negative": 0}
            for field in TRACKED_SIGNAL_FIELDS
        },
    }


def _update_expected_metrics(variant_summary: dict[str, Any], *, expected_kind: str | None, predicted_type: str | None) -> None:
    if expected_kind is not None and expected_kind in variant_summary["expected_counts"]:
        variant_summary["expected_counts"][expected_kind] += 1

    for kind in TRACKED_TYPED_KINDS:
        expected = expected_kind == kind
        predicted = predicted_type == kind
        if expected:
            variant_summary["type_metrics"][kind]["expected"] += 1
        if predicted:
            variant_summary["type_metrics"][kind]["predicted"] += 1
        if expected and predicted:
            variant_summary["type_metrics"][kind]["correct"] += 1
        elif not expected and predicted:
            variant_summary["type_metrics"][kind]["false_positive"] += 1
        elif expected and not predicted:
            variant_summary["type_metrics"][kind]["false_negative"] += 1

    if expected_kind is None:
        return
    if predicted_type == expected_kind:
        variant_summary["overall_correct"] += 1


def _update_signal_metrics(
    variant_summary: dict[str, Any],
    *,
    expected_signal_truths: dict[str, bool],
    normalized_extraction: dict[str, Any],
) -> None:
    if not expected_signal_truths:
        return

    variant_summary["signal_cases_total"] += 1
    case_correct = True
    for signal_name, expected_present in expected_signal_truths.items():
        entry = variant_summary["signal_metrics"][signal_name]
        if expected_present:
            entry["expected_true"] += 1
        else:
            entry["expected_false"] += 1
        actual_present = _signal_present(normalized_extraction.get(signal_name))
        if actual_present == expected_present:
            entry["correct"] += 1
            continue
        case_correct = False
        if actual_present and not expected_present:
            entry["false_positive"] += 1
        else:
            entry["false_negative"] += 1

    if case_correct:
        variant_summary["signal_cases_correct"] += 1


def _signal_present(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict)):
        return bool(value)
    return True


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


def _parse_datetime(value: Any):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("occurred_at must be an ISO datetime string")
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


if __name__ == "__main__":
    raise SystemExit(main())
