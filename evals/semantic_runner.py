from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app.config import AppConfig
from app.dependencies import build_semantic_plugins
from core.contracts import build_source_item
from semantic.llm_agent_memory import LLMAgentMemoryPlugin


DEFAULT_INPUT_FILE = Path("evals/semantic/input/items.jsonl")
DEFAULT_OUTPUT_DIR = Path("evals/semantic/output")
SANITIZE_PATTERN = re.compile(r"[^a-z0-9]+")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run LLM semantic evaluation over input fixtures.")
    parser.add_argument("--input-file", type=Path, default=DEFAULT_INPUT_FILE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--use-case", default="llm_agent_memory")
    parser.add_argument("--suite-name", default="semantic-eval")
    parser.add_argument("--run-name", default=None)
    parser.add_argument("--prompt-variants", default="baseline")
    parser.add_argument("--split-output", action="store_true")
    args = parser.parse_args()

    config = AppConfig.from_env()
    plugins = build_semantic_plugins(config)
    plugin = plugins.get(args.use_case)
    if not isinstance(plugin, LLMAgentMemoryPlugin):
        raise ValueError(f"Use case '{args.use_case}' is not an LLM-backed semantic plugin")

    prompt_variants = [item.strip() for item in args.prompt_variants.split(",") if item.strip()]
    run_dir = run_semantic_eval(
        input_file=args.input_file,
        output_root=args.output_dir,
        plugin=plugin,
        config=config,
        suite_name=args.suite_name,
        run_name=args.run_name,
        prompt_variants=prompt_variants,
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
    split_output: bool = False,
) -> Path:
    if not input_file.exists():
        raise FileNotFoundError(f"Input file does not exist: {input_file}")

    resolved_variants = prompt_variants or [plugin.prompt_variant]
    run_id = run_name or _build_run_id(
        suite_name=suite_name,
        provider=config.llm_provider,
        model=config.llm_model,
    )
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    results_path = run_dir / "results.jsonl"

    summary = {
        "suite_name": suite_name,
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provider": config.llm_provider,
        "model": config.llm_model,
        "base_url": config.llm_base_url,
        "use_case": plugin.name,
        "input_file": str(input_file),
        "prompt_variants": resolved_variants,
        "results_file": results_path.name,
        "split_output": split_output,
        "items_total": 0,
        "items_succeeded": 0,
        "items_failed": 0,
        "decision_promotions": 0,
        "discussion_summary_promotions": 0,
        "split_outputs": [],
        "per_variant": {},
    }

    records = list(_load_input_records(input_file))
    for variant in resolved_variants:
        summary["per_variant"][variant] = {
            "items_total": len(records),
            "items_succeeded": 0,
            "items_failed": 0,
            "decision_promotions": 0,
            "discussion_summary_promotions": 0,
            "expected_decision": 0,
            "expected_non_decision": 0,
            "correct": 0,
            "false_positive": 0,
            "false_negative": 0,
        }

    with results_path.open("w", encoding="utf-8") as results_file:
        for index, payload in enumerate(records, start=1):
            source_item = build_source_item(
                source_type=payload["source_type"],
                source_id=payload["source_id"],
                content_type=payload["content_type"],
                content=payload["content"],
                metadata=payload.get("metadata"),
            )
            input_key = _build_input_key(index=index, source_id=source_item.source_id)
            expected_kind = _expected_kind(source_item)

            for variant in resolved_variants:
                variant_plugin = plugin.with_prompt_variant(variant)
                output_payload: dict[str, Any] = {
                    "input_index": index,
                    "input_key": input_key,
                    "prompt_variant": variant,
                    "status": "ok",
                    "source_item": _serialize(source_item),
                }
                summary["items_total"] += 1
                variant_summary = summary["per_variant"][variant]
                if expected_kind == "decision":
                    variant_summary["expected_decision"] += 1
                elif expected_kind is not None:
                    variant_summary["expected_non_decision"] += 1

                try:
                    trace = variant_plugin.analyze_item(source_item)
                    output_payload["request"] = _serialize(trace.request)
                    output_payload["llm_response"] = {
                        "raw_text": trace.response.raw_text,
                        "parsed_json": trace.response.parsed_json,
                    }
                    output_payload["normalized_extraction"] = _serialize(trace.extraction)
                    output_payload["artifacts"] = _serialize(trace.process_result)
                    promoted_type = trace.process_result.memory_objects[0].type
                    if promoted_type == "decision":
                        summary["decision_promotions"] += 1
                        variant_summary["decision_promotions"] += 1
                    elif promoted_type == "discussion_summary":
                        summary["discussion_summary_promotions"] += 1
                        variant_summary["discussion_summary_promotions"] += 1
                    summary["items_succeeded"] += 1
                    variant_summary["items_succeeded"] += 1
                    _update_expected_metrics(variant_summary, expected_kind=expected_kind, predicted_type=promoted_type)
                except Exception as exc:
                    output_payload["status"] = "error"
                    output_payload["error"] = {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    }
                    summary["items_failed"] += 1
                    variant_summary["items_failed"] += 1

                results_file.write(json.dumps(output_payload) + "\n")

                if split_output:
                    output_name = f"{input_key}__{_slugify(variant)}.result.json"
                    output_path = run_dir / output_name
                    output_path.write_text(json.dumps(output_payload, indent=2), encoding="utf-8")
                    summary["split_outputs"].append(output_name)

    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return run_dir


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
    return expected_kind.strip() or None


def _update_expected_metrics(variant_summary: dict[str, Any], *, expected_kind: str | None, predicted_type: str) -> None:
    if expected_kind is None:
        return
    if expected_kind == "decision" and predicted_type == "decision":
        variant_summary["correct"] += 1
        return
    if expected_kind != "decision" and predicted_type != "decision":
        variant_summary["correct"] += 1
        return
    if expected_kind != "decision" and predicted_type == "decision":
        variant_summary["false_positive"] += 1
        return
    if expected_kind == "decision" and predicted_type != "decision":
        variant_summary["false_negative"] += 1


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
