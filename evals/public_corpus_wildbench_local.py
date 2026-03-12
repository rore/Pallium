from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import AppConfig
from evals.public_corpus_benchmark import run_public_corpus_benchmark
from evals.public_corpus_builder import (
    DEFAULT_WILDBENCH_REVIEW_MANIFEST,
    build_candidate_episodes,
    build_reviewed_episodes,
    extract_review_conversation_ids,
    load_public_corpus_conversations,
    load_review_manifest,
)

HF_DATASET_REPO_ID = "allenai/WildBench"
DEFAULT_LOCAL_ROOT = Path(r"C:\data\wildbench\WildBench")
SNAPSHOT_DIRNAME = "snapshot"
DERIVED_DIRNAME = "derived"
REVIEW_SETS_DIRNAME = "review_sets"
CANDIDATE_OUTPUT_FILENAME = "review_candidates.jsonl"
VALIDATION_FILENAME = "validation_summary.json"
DOWNLOAD_ALLOW_PATTERNS = ["*.parquet", "*.json", "*.jsonl", "*.md", "*.txt"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage the local WildBench workflow for Pallium public-corpus evals.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    download_parser = subparsers.add_parser("download", help="Download the WildBench snapshot outside the repo.")
    _add_root_arg(download_parser)

    validate_parser = subparsers.add_parser("validate", help="Validate the local WildBench snapshot layout and summarize it.")
    _add_root_arg(validate_parser)

    candidates_parser = subparsers.add_parser("emit-candidates", help="Write reviewed-slice candidate episodes from the local snapshot.")
    _add_root_arg(candidates_parser)
    candidates_parser.add_argument("--output-file", type=Path, default=None)

    materialize_parser = subparsers.add_parser("materialize-review-set", help="Extract only the sessions referenced by a reviewed manifest.")
    _add_root_arg(materialize_parser)
    materialize_parser.add_argument("--reviewed-manifest", type=Path, default=DEFAULT_WILDBENCH_REVIEW_MANIFEST)
    materialize_parser.add_argument("--output-name", default=None)

    benchmark_parser = subparsers.add_parser("benchmark", help="Run the public-corpus benchmark from a local materialized review set.")
    _add_root_arg(benchmark_parser)
    benchmark_parser.add_argument("--reviewed-manifest", type=Path, default=DEFAULT_WILDBENCH_REVIEW_MANIFEST)
    benchmark_parser.add_argument("--output-name", default=None)
    benchmark_parser.add_argument("--run-name", default=None)
    benchmark_parser.add_argument("--consolidation-strategy", default="thread_summary_anchored")

    args = parser.parse_args()
    root = args.root.resolve()

    if args.command == "download":
        snapshot_dir = download_snapshot(root)
        print(snapshot_dir)
        return 0
    if args.command == "validate":
        summary = validate_local_corpus(root)
        print(json.dumps(summary, indent=2))
        return 0
    if args.command == "emit-candidates":
        output_path = emit_review_candidates(root=root, output_file=args.output_file)
        print(output_path)
        return 0
    if args.command == "materialize-review-set":
        review_dir = materialize_review_set(root=root, reviewed_manifest=args.reviewed_manifest, output_name=args.output_name)
        print(review_dir)
        return 0
    if args.command == "benchmark":
        run_dir = benchmark_review_set(
            root=root,
            reviewed_manifest=args.reviewed_manifest,
            output_name=args.output_name,
            run_name=args.run_name,
            default_consolidation_strategy=args.consolidation_strategy,
        )
        print(run_dir)
        return 0
    raise ValueError(f"Unsupported command: {args.command}")


def _add_root_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", type=Path, default=DEFAULT_LOCAL_ROOT)


def download_snapshot(root: Path) -> Path:
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError("Downloading WildBench requires the optional 'huggingface_hub' package.") from exc

    layout = ensure_local_layout(root)
    snapshot_download(
        repo_id=HF_DATASET_REPO_ID,
        repo_type="dataset",
        local_dir=layout["snapshot_dir"],
        allow_patterns=DOWNLOAD_ALLOW_PATTERNS,
    )
    return layout["snapshot_dir"]


def ensure_local_layout(root: Path) -> dict[str, Path]:
    snapshot_dir = root / SNAPSHOT_DIRNAME
    derived_dir = root / DERIVED_DIRNAME
    review_sets_dir = derived_dir / REVIEW_SETS_DIRNAME
    runs_dir = root / "runs"
    for directory in (root, snapshot_dir, derived_dir, review_sets_dir, runs_dir):
        directory.mkdir(parents=True, exist_ok=True)
    return {
        "root": root,
        "snapshot_dir": snapshot_dir,
        "derived_dir": derived_dir,
        "review_sets_dir": review_sets_dir,
        "runs_dir": runs_dir,
        "candidate_output": derived_dir / CANDIDATE_OUTPUT_FILENAME,
        "validation_summary": derived_dir / VALIDATION_FILENAME,
    }


def validate_local_corpus(root: Path) -> dict[str, Any]:
    layout = ensure_local_layout(root)
    parquet_files = sorted(layout["snapshot_dir"].rglob("*.parquet"))
    jsonl_files = sorted(list(layout["snapshot_dir"].rglob("*.jsonl")) + list(layout["snapshot_dir"].rglob("*.ndjson")))
    json_files = sorted(layout["snapshot_dir"].rglob("*.json"))
    corpus_files = parquet_files or jsonl_files or json_files
    total_bytes = sum(item.stat().st_size for item in corpus_files)
    total_rows = _sum_parquet_rows(parquet_files)
    summary = {
        "dataset_repo": HF_DATASET_REPO_ID,
        "root": str(layout["root"]),
        "snapshot_dir": str(layout["snapshot_dir"]),
        "derived_dir": str(layout["derived_dir"]),
        "review_sets_dir": str(layout["review_sets_dir"]),
        "runs_dir": str(layout["runs_dir"]),
        "candidate_output": str(layout["candidate_output"]),
        "parquet_file_count": len(parquet_files),
        "jsonl_file_count": len(jsonl_files),
        "json_file_count": len(json_files),
        "snapshot_size_bytes": total_bytes,
        "snapshot_size_mb": round(total_bytes / (1024 ** 2), 2),
        "parquet_row_count": total_rows,
    }
    layout["validation_summary"].write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def emit_review_candidates(*, root: Path, output_file: Path | None) -> Path:
    layout = ensure_local_layout(root)
    conversations = load_public_corpus_conversations(layout["snapshot_dir"], corpus_name="wildbench")
    candidates = build_candidate_episodes(conversations)

    output_path = output_file or layout["candidate_output"]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for item in candidates:
            handle.write(json.dumps(item) + "\n")
    return output_path


def materialize_review_set(*, root: Path, reviewed_manifest: Path, output_name: str | None) -> Path:
    layout = ensure_local_layout(root)
    manifest = load_review_manifest(reviewed_manifest)
    conversation_ids = extract_review_conversation_ids(manifest)
    review_dir = layout["review_sets_dir"] / (output_name or reviewed_manifest.stem)
    review_dir.mkdir(parents=True, exist_ok=True)

    conversations = load_public_corpus_conversations(layout["snapshot_dir"], corpus_name="wildbench", conversation_ids=conversation_ids)
    found_ids = {item["conversation_id"] for item in conversations}
    missing_ids = sorted(conversation_ids - found_ids)
    if missing_ids:
        raise ValueError(f"Reviewed manifest references missing sessions: {missing_ids}")

    corpus_path = review_dir / "conversations.json"
    corpus_path.write_text(json.dumps(conversations, indent=2, default=_json_default), encoding="utf-8")

    episodes = build_reviewed_episodes(conversations=conversations, manifest=manifest)
    reviewed_path = review_dir / "reviewed_episodes.json"
    reviewed_path.write_text(json.dumps(episodes, indent=2), encoding="utf-8")

    summary = {
        "dataset_repo": HF_DATASET_REPO_ID,
        "reviewed_manifest": str(reviewed_manifest),
        "corpus_path": str(corpus_path),
        "reviewed_episodes_path": str(reviewed_path),
        "conversation_count": len(conversations),
        "conversation_ids": sorted(found_ids),
        "reviewed_episode_count": len(episodes),
    }
    (review_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return review_dir


def benchmark_review_set(
    *,
    root: Path,
    reviewed_manifest: Path,
    output_name: str | None,
    run_name: str | None,
    default_consolidation_strategy: str,
) -> Path:
    review_dir = materialize_review_set(root=root, reviewed_manifest=reviewed_manifest, output_name=output_name)
    corpus_path = review_dir / "conversations.json"
    output_root = ensure_local_layout(root)["runs_dir"]
    return run_public_corpus_benchmark(
        corpus_file=corpus_path,
        reviewed_manifest=reviewed_manifest,
        output_root=output_root,
        config=AppConfig.from_env(),
        run_name=run_name,
        default_consolidation_strategy=default_consolidation_strategy,
    )


def _sum_parquet_rows(parquet_files: list[Path]) -> int:
    if not parquet_files:
        return 0
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError("Validating WildBench parquet snapshots requires the optional 'pyarrow' package.") from exc
    total = 0
    for parquet_file in parquet_files:
        total += int(pq.ParquetFile(parquet_file).metadata.num_rows)
    return total


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


if __name__ == "__main__":
    raise SystemExit(main())
