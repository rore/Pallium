from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import AppConfig
from evals.public_corpus_benchmark import run_public_corpus_benchmark
from evals.public_corpus_builder import (
    DEFAULT_REVIEW_MANIFEST,
    build_reviewed_episodes,
    extract_review_conversation_ids,
    iter_wildchat_conversations,
    load_review_manifest,
    load_wildchat_conversations,
)

HF_DATASET_REPO_ID = "allenai/WildChat-4.8M"
DEFAULT_LOCAL_ROOT = Path(r"C:\data\wildchat\WildChat-4.8M")
SNAPSHOT_DIRNAME = "snapshot"
DERIVED_DIRNAME = "derived"
REVIEW_SETS_DIRNAME = "review_sets"
CANDIDATE_INDEX_FILENAME = "conversation_index.sqlite"
CANDIDATE_OUTPUT_FILENAME = "review_candidates.jsonl"
VALIDATION_FILENAME = "validation_summary.json"
DOWNLOAD_ALLOW_PATTERNS = ["*.parquet", "*.json", "*.md", "*.txt"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage the local full-corpus WildChat workflow for Pallium public-corpus evals.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    download_parser = subparsers.add_parser("download", help="Download the full WildChat snapshot outside the repo.")
    _add_root_arg(download_parser)

    validate_parser = subparsers.add_parser("validate", help="Validate the local WildChat snapshot layout and summarize it.")
    _add_root_arg(validate_parser)

    index_parser = subparsers.add_parser("build-candidate-index", help="Build a local SQLite index of filtered WildChat conversations.")
    _add_root_arg(index_parser)
    index_parser.add_argument("--rebuild", action="store_true")

    candidates_parser = subparsers.add_parser("emit-candidates", help="Write reviewed-slice candidate episodes from the local candidate index.")
    _add_root_arg(candidates_parser)
    candidates_parser.add_argument("--rebuild-index", action="store_true")
    candidates_parser.add_argument("--output-file", type=Path, default=None)

    materialize_parser = subparsers.add_parser("materialize-review-set", help="Extract only the conversations referenced by a reviewed manifest.")
    _add_root_arg(materialize_parser)
    materialize_parser.add_argument("--reviewed-manifest", type=Path, default=DEFAULT_REVIEW_MANIFEST)
    materialize_parser.add_argument("--output-name", default=None)

    benchmark_parser = subparsers.add_parser("benchmark", help="Run the public-corpus benchmark from a local materialized review set.")
    _add_root_arg(benchmark_parser)
    benchmark_parser.add_argument("--reviewed-manifest", type=Path, default=DEFAULT_REVIEW_MANIFEST)
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
    if args.command == "build-candidate-index":
        summary = build_candidate_index(root=root, rebuild=args.rebuild)
        print(json.dumps(summary, indent=2))
        return 0
    if args.command == "emit-candidates":
        output_path = emit_review_candidates(root=root, rebuild_index=args.rebuild_index, output_file=args.output_file)
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
        raise RuntimeError("Downloading WildChat requires the optional 'huggingface_hub' package.") from exc

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
        "candidate_index": derived_dir / CANDIDATE_INDEX_FILENAME,
        "candidate_output": derived_dir / CANDIDATE_OUTPUT_FILENAME,
        "validation_summary": derived_dir / VALIDATION_FILENAME,
    }


def validate_local_corpus(root: Path) -> dict[str, Any]:
    layout = ensure_local_layout(root)
    parquet_files = sorted(layout["snapshot_dir"].rglob("*.parquet"))
    jsonl_files = sorted(list(layout["snapshot_dir"].rglob("*.jsonl")) + list(layout["snapshot_dir"].rglob("*.ndjson")))
    corpus_files = parquet_files or jsonl_files
    total_bytes = sum(item.stat().st_size for item in corpus_files)
    total_rows = _sum_parquet_rows(parquet_files)
    summary = {
        "dataset_repo": HF_DATASET_REPO_ID,
        "root": str(layout["root"]),
        "snapshot_dir": str(layout["snapshot_dir"]),
        "derived_dir": str(layout["derived_dir"]),
        "review_sets_dir": str(layout["review_sets_dir"]),
        "runs_dir": str(layout["runs_dir"]),
        "candidate_index": str(layout["candidate_index"]),
        "candidate_output": str(layout["candidate_output"]),
        "parquet_file_count": len(parquet_files),
        "jsonl_file_count": len(jsonl_files),
        "snapshot_size_bytes": total_bytes,
        "snapshot_size_gb": round(total_bytes / (1024 ** 3), 2),
        "parquet_row_count": total_rows,
    }
    layout["validation_summary"].write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def build_candidate_index(*, root: Path, rebuild: bool) -> dict[str, Any]:
    layout = ensure_local_layout(root)
    index_path = layout["candidate_index"]
    if rebuild and index_path.exists():
        index_path.unlink()

    connection = sqlite3.connect(index_path)
    try:
        _initialize_candidate_index(connection)
        if _candidate_index_has_rows(connection):
            return _candidate_index_summary(root=root, connection=connection, index_path=index_path)

        count = 0
        rows: list[tuple[str, str | None, str, int, int | None, str | None, int | None, str | None]] = []
        for conversation in iter_wildchat_conversations(layout["snapshot_dir"]):
            count += 1
            within_turn_index = _last_user_turn_index(conversation["turns"])
            first_turn_index = _first_user_turn_index(conversation["turns"])
            rows.append(
                (
                    conversation["conversation_id"],
                    conversation.get("user_key"),
                    conversation["sort_key"],
                    len(conversation["turns"]),
                    within_turn_index,
                    _turn_text(conversation["turns"], within_turn_index),
                    first_turn_index,
                    _turn_text(conversation["turns"], first_turn_index),
                )
            )
            if len(rows) >= 512:
                _flush_candidate_index_rows(connection, rows)
                rows.clear()
        if rows:
            _flush_candidate_index_rows(connection, rows)
        return _candidate_index_summary(root=root, connection=connection, index_path=index_path, conversation_count=count)
    finally:
        connection.close()


def emit_review_candidates(*, root: Path, rebuild_index: bool, output_file: Path | None) -> Path:
    layout = ensure_local_layout(root)
    build_candidate_index(root=root, rebuild=rebuild_index)
    output_path = output_file or layout["candidate_output"]
    output_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(layout["candidate_index"])
    try:
        with output_path.open("w", encoding="utf-8") as handle:
            for row in connection.execute(
                """
                SELECT conversation_id, within_query_turn_index, within_query_text, user_key, turn_count
                FROM conversations
                WHERE within_query_turn_index IS NOT NULL AND within_query_turn_index >= 2
                ORDER BY sort_key, conversation_id
                """
            ):
                conversation_id, query_turn_index, query_text, user_key, turn_count = row
                handle.write(
                    json.dumps(
                        {
                            "episode_id": f"{conversation_id}::within::{query_turn_index}",
                            "episode_type": "within_conversation_later_turn_recall",
                            "conversation_id": conversation_id,
                            "query_turn_index": query_turn_index,
                            "current_context_turn_indices": [query_turn_index],
                            "query_text": query_text,
                            "user_key": user_key,
                            "turn_count": turn_count,
                            "language": "english",
                        }
                    )
                    + "\n"
                )
            for row in connection.execute(
                """
                WITH ordered AS (
                    SELECT
                        conversation_id,
                        user_key,
                        sort_key,
                        LEAD(conversation_id) OVER (PARTITION BY user_key ORDER BY sort_key, conversation_id) AS target_conversation_id,
                        LEAD(first_user_turn_index) OVER (PARTITION BY user_key ORDER BY sort_key, conversation_id) AS target_query_turn_index,
                        LEAD(first_user_query_text) OVER (PARTITION BY user_key ORDER BY sort_key, conversation_id) AS target_query_text
                    FROM conversations
                    WHERE user_key IS NOT NULL
                )
                SELECT conversation_id, target_conversation_id, target_query_turn_index, target_query_text, user_key
                FROM ordered
                WHERE target_conversation_id IS NOT NULL AND target_query_turn_index IS NOT NULL
                ORDER BY user_key, sort_key, conversation_id
                """
            ):
                source_conversation_id, target_conversation_id, target_query_turn_index, target_query_text, user_key = row
                handle.write(
                    json.dumps(
                        {
                            "episode_id": f"{source_conversation_id}::{target_conversation_id}::carry-forward",
                            "episode_type": "later_session_carry_forward",
                            "source_conversation_ids": [source_conversation_id],
                            "target_conversation_id": target_conversation_id,
                            "target_query_turn_index": target_query_turn_index,
                            "current_context_turn_indices": [target_query_turn_index],
                            "query_text": target_query_text,
                            "user_key": user_key,
                        }
                    )
                    + "\n"
                )
    finally:
        connection.close()
    return output_path


def materialize_review_set(*, root: Path, reviewed_manifest: Path, output_name: str | None) -> Path:
    layout = ensure_local_layout(root)
    manifest = load_review_manifest(reviewed_manifest)
    conversation_ids = extract_review_conversation_ids(manifest)
    review_dir = layout["review_sets_dir"] / (output_name or reviewed_manifest.stem)
    review_dir.mkdir(parents=True, exist_ok=True)

    conversations = load_wildchat_conversations(layout["snapshot_dir"], conversation_ids=conversation_ids)
    found_ids = {item["conversation_id"] for item in conversations}
    missing_ids = sorted(conversation_ids - found_ids)
    if missing_ids:
        raise ValueError(f"Reviewed manifest references missing conversations: {missing_ids}")

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


def _flush_candidate_index_rows(
    connection: sqlite3.Connection,
    rows: list[tuple[str, str | None, str, int, int | None, str | None, int | None, str | None]],
) -> None:
    connection.executemany(
        """
        INSERT OR REPLACE INTO conversations (
            conversation_id,
            user_key,
            sort_key,
            turn_count,
            within_query_turn_index,
            within_query_text,
            first_user_turn_index,
            first_user_query_text
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    connection.commit()


def _initialize_candidate_index(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            conversation_id TEXT PRIMARY KEY,
            user_key TEXT,
            sort_key TEXT NOT NULL,
            turn_count INTEGER NOT NULL,
            within_query_turn_index INTEGER,
            within_query_text TEXT,
            first_user_turn_index INTEGER,
            first_user_query_text TEXT
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_conversations_user_sort ON conversations (user_key, sort_key, conversation_id)")
    connection.commit()


def _candidate_index_has_rows(connection: sqlite3.Connection) -> bool:
    row = connection.execute("SELECT COUNT(*) FROM conversations").fetchone()
    return bool(row and row[0])


def _candidate_index_summary(
    *,
    root: Path,
    connection: sqlite3.Connection,
    index_path: Path,
    conversation_count: int | None = None,
) -> dict[str, Any]:
    total_conversations = conversation_count
    if total_conversations is None:
        row = connection.execute("SELECT COUNT(*) FROM conversations").fetchone()
        total_conversations = int(row[0]) if row else 0
    users = connection.execute("SELECT COUNT(DISTINCT user_key) FROM conversations WHERE user_key IS NOT NULL").fetchone()
    within = connection.execute("SELECT COUNT(*) FROM conversations WHERE within_query_turn_index IS NOT NULL AND within_query_turn_index >= 2").fetchone()
    return {
        "root": str(root),
        "candidate_index": str(index_path),
        "conversation_count": total_conversations,
        "distinct_user_keys": int(users[0]) if users else 0,
        "within_conversation_candidates": int(within[0]) if within else 0,
    }


def _sum_parquet_rows(parquet_files: list[Path]) -> int:
    if not parquet_files:
        return 0
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError("Validating WildChat parquet snapshots requires the optional 'pyarrow' package.") from exc
    total = 0
    for parquet_file in parquet_files:
        total += int(pq.ParquetFile(parquet_file).metadata.num_rows)
    return total


def _first_user_turn_index(turns: list[dict[str, Any]]) -> int | None:
    for turn in turns:
        if turn["role"] == "user":
            return int(turn["turn_index"])
    return None


def _last_user_turn_index(turns: list[dict[str, Any]]) -> int | None:
    for turn in reversed(turns):
        if turn["role"] == "user":
            return int(turn["turn_index"])
    return None


def _turn_text(turns: list[dict[str, Any]], turn_index: int | None) -> str | None:
    if turn_index is None:
        return None
    for turn in turns:
        if int(turn["turn_index"]) == turn_index:
            return str(turn["content"])
    return None


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


if __name__ == "__main__":
    raise SystemExit(main())
