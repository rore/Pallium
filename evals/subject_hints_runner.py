# evals/subject_hints_runner.py
from __future__ import annotations

import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import AppConfig
from app.dependencies import build_semantic_plugins
from core.contracts import build_source_item
from core.models import MemorySubjectAnchor
from semantic.agent_conversation_memory_anchors import _anchor_display_value
from semantic.llm_agent_memory import LLMAgentMemoryPlugin

DEFAULT_INPUT_FILE = Path("evals/semantic/input/subject_hints_items.jsonl")
DEFAULT_OUTPUT_DIR = Path("evals/subject_hints/output")
SANITIZE_PATTERN = re.compile(r"[^a-z0-9]+")


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def _normalize_hint(kind: str, value: str) -> tuple[str, str]:
    """Return (kind, display_value) normalized for comparison.

    Uses _anchor_display_value semantics: lowercase via normalize_for_index,
    leading/trailing noise tokens stripped, singular map applied.
    """
    return kind.strip().lower(), _anchor_display_value(value)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score_item(
    extracted: list[MemorySubjectAnchor],
    expected: list[dict[str, str]],
    forbidden: list[dict[str, str]],
) -> tuple[set[tuple[str, str]], set[tuple[str, str]], set[tuple[str, str]]]:
    """Return (hits, misses, spurious) as normalized (kind, value) sets.

    hits     = required ∩ extracted   (correctly extracted)
    misses   = required − extracted   (under-extraction)
    spurious = extracted ∩ forbidden  (over-extraction)
    """
    extracted_norm = {_normalize_hint(h.kind, h.value) for h in extracted}
    required_norm = {_normalize_hint(e["kind"], e["value"]) for e in expected}
    forbidden_norm = {_normalize_hint(f["kind"], f["value"]) for f in forbidden}
    hits = required_norm & extracted_norm
    misses = required_norm - extracted_norm
    spurious = extracted_norm & forbidden_norm
    return hits, misses, spurious


def _aggregate_variant(item_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll up per-item scores into a per-variant summary."""
    total_required = 0
    total_hits = 0
    total_spurious = 0
    perfect = 0
    for r in item_results:
        total_hits += r["hits_count"]
        total_required += r["required_count"]
        total_spurious += r["spurious_count"]
        if r["hits_count"] == r["required_count"] and r["spurious_count"] == 0:
            perfect += 1
    return {
        "recall": total_hits / total_required if total_required > 0 else 0.0,
        "spurious_count": total_spurious,
        "perfect_items": perfect,
        "items_total": len(item_results),
        "total_hits": total_hits,
        "total_required": total_required,
    }


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def _evaluate_one(
    *,
    source_item: Any,
    variant: str,
    plugin: LLMAgentMemoryPlugin,
) -> dict[str, Any]:
    variant_plugin = plugin.with_prompt_variant(variant)
    expected = list(source_item.metadata.get("expected_subject_hints") or [])
    forbidden = list(source_item.metadata.get("forbidden_subject_hints") or [])
    payload: dict[str, Any] = {
        "source_id": source_item.source_id,
        "prompt_variant": variant,
        "status": "ok",
        "expected_subject_hints": expected,
        "forbidden_subject_hints": forbidden,
    }
    try:
        trace = variant_plugin.analyze_item(source_item)
        extracted: list[MemorySubjectAnchor] = list(trace.extraction.subject_hints or [])
        hits, misses, spurious = _score_item(extracted, expected, forbidden)
        payload["extracted_subject_hints"] = [{"kind": h.kind, "value": h.value} for h in extracted]
        payload["hits"] = [list(h) for h in hits]
        payload["misses"] = [list(m) for m in misses]
        payload["spurious"] = [list(s) for s in spurious]
        payload["hits_count"] = len(hits)
        payload["misses_count"] = len(misses)
        payload["required_count"] = len(expected)
        payload["spurious_count"] = len(spurious)
    except Exception as exc:
        payload["status"] = "error"
        payload["error"] = {"type": type(exc).__name__, "message": str(exc)}
        payload["hits_count"] = 0
        payload["misses_count"] = 0
        payload["required_count"] = len(expected)
        payload["spurious_count"] = 0
    return payload


def _run(
    *,
    input_file: Path,
    output_root: Path,
    plugin: LLMAgentMemoryPlugin,
    prompt_variants: list[str],
    workers: int,
    run_name: str | None,
) -> Path:
    if not input_file.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")

    # Validate all variant names before any LLM calls.
    for variant in prompt_variants:
        plugin.with_prompt_variant(variant)  # raises ValueError for unknown names

    raw_records = [
        json.loads(line)
        for line in input_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    items = [
        build_source_item(
            source_type=r["source_type"],
            source_id=r["source_id"],
            content_type=r["content_type"],
            content=r["content"],
            metadata=r.get("metadata"),
            occurred_at=_parse_dt(r.get("occurred_at")),
            role=r.get("role"),
            container_ref=r.get("container_ref"),
            thread_ref=r.get("thread_ref"),
        )
        for r in raw_records
    ]

    run_id = run_name or _build_run_id()
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    tasks = [(item, variant) for item in items for variant in prompt_variants]

    if workers == 1:
        results = [_evaluate_one(source_item=item, variant=v, plugin=plugin) for item, v in tasks]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_evaluate_one, source_item=item, variant=v, plugin=plugin) for item, v in tasks]
            results = [f.result() for f in as_completed(futures)]

    results.sort(key=lambda r: (r["source_id"], prompt_variants.index(r["prompt_variant"])))

    (run_dir / "results.jsonl").write_text(
        "\n".join(json.dumps(r) for r in results) + "\n",
        encoding="utf-8",
    )

    per_variant: dict[str, list[dict[str, Any]]] = {v: [] for v in prompt_variants}
    for r in results:
        if r["status"] == "ok":
            per_variant[r["prompt_variant"]].append(r)

    summaries = {v: _aggregate_variant(per_variant[v]) for v in prompt_variants}

    summary = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input_file": str(input_file),
        "prompt_variants": prompt_variants,
        "per_variant": summaries,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    # Print console summary — one row per variant.
    print(f"\n{'variant':<55} {'recall':>6} {'spurious':>9} {'perfect':>8}")
    print("-" * 80)
    for variant in prompt_variants:
        s = summaries[variant]
        print(f"{variant:<55} {s['recall']:>6.2f} {s['spurious_count']:>9} {s['perfect_items']:>8}/{s['items_total']}")
    print(f"\nFull results: {run_dir / 'results.jsonl'}")

    return run_dir


def _build_run_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"subject-hints__{ts}"


def _parse_dt(value: Any):
    if value is None:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _slugify(value: str) -> str:
    return SANITIZE_PATTERN.sub("-", value.strip().lower()).strip("-") or "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description="Score subject_hint extraction against a ground-truth fixture.")
    parser.add_argument("--prompt-variants", default=None, help="Comma-separated variant names. Defaults to the plugin default.")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--cache-dir", default=None, help="LLM response cache directory.")
    parser.add_argument("--run-name", default=None)
    parser.add_argument("--input-file", type=Path, default=DEFAULT_INPUT_FILE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    config = AppConfig.from_env()
    if args.cache_dir:
        import os
        os.environ.setdefault("PALLIUM_LLM_CACHE_DIR", args.cache_dir)

    plugins = build_semantic_plugins(config)
    plugin = plugins.get("llm_agent_memory")
    if not isinstance(plugin, LLMAgentMemoryPlugin):
        raise ValueError("llm_agent_memory plugin not found or wrong type")

    prompt_variants = (
        [v.strip() for v in args.prompt_variants.split(",") if v.strip()]
        if args.prompt_variants
        else [plugin.prompt_variant]
    )

    _run(
        input_file=args.input_file,
        output_root=args.output_dir,
        plugin=plugin,
        prompt_variants=prompt_variants,
        workers=args.workers,
        run_name=args.run_name,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
