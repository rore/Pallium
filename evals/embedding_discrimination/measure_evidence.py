"""Measure whether appending source evidence to embedding text improves discrimination.

Compares two versions of embedding text for a sample of memory objects:
- Version 1: current text (with type prefix)
- Version 2: current text + truncated source evidence (~500 chars)

Reports similarity distributions and clustering analysis.

Usage:
    python -m evals.embedding_discrimination [--db PATH] [--sample-size N]
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

import numpy as np


def load_memory_sample(db_path: str, sample_size: int = 50) -> list[dict]:
    """Load memory objects with their evidence text from the database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT mo.id, mo.type, mo.thread_ref, mo.container_ref,
               ie.text_view as current_embedding_text
        FROM memory_objects mo
        JOIN index_entries ie ON ie.target_id = mo.id
        WHERE ie.index_type = 'vector'
          AND ie.target_kind = 'memory_object'
          AND mo.lifecycle = 'active'
        ORDER BY mo.freshness_at DESC
        LIMIT ?
    """, (sample_size * 2,)).fetchall()  # over-fetch since some may lack evidence

    memories = []
    for row in rows:
        if len(memories) >= sample_size:
            break

        evidence_rows = conn.execute("""
            SELECT si.content
            FROM relations r
            JOIN source_items si ON si.id = r.to_id
            WHERE r.from_id = ? AND r.relation_type = 'supported_by' AND r.to_kind = 'source_item'
            ORDER BY si.id
            LIMIT 3
        """, (row["id"],)).fetchall()

        if not evidence_rows:
            continue

        evidence_text = " ".join(e["content"][:500] for e in evidence_rows[:3])

        memories.append({
            "id": row["id"],
            "type": row["type"],
            "thread_ref": row["thread_ref"],
            "container_ref": row["container_ref"],
            "current_embedding_text": row["current_embedding_text"],
            "evidence_text": evidence_text[:500],
        })

    conn.close()
    return memories


def build_embedding_versions(memories: list[dict]) -> tuple[list[str], list[str]]:
    """Build V1 (current) and V2 (current + evidence) texts."""
    v1_texts = []
    v2_texts = []

    for mem in memories:
        v1 = mem["current_embedding_text"]
        v1_texts.append(v1)

        evidence = mem["evidence_text"].strip()
        if evidence:
            v2 = f"{v1} Evidence: {evidence}"
        else:
            v2 = v1
        v2_texts.append(v2)

    return v1_texts, v2_texts


def compute_similarity_matrix(vectors: list[list[float]]) -> np.ndarray:
    """Compute pairwise cosine similarity matrix (vectors assumed L2-normalized)."""
    arr = np.array(vectors)
    return arr @ arr.T


def analyze_clustering(memories: list[dict], sim_matrix: np.ndarray, label: str) -> dict:
    """Analyze similarity distribution overall and by grouping."""
    n = len(memories)
    upper_indices = np.triu_indices(n, k=1)
    all_sims = sim_matrix[upper_indices]

    stats: dict = {
        "label": label,
        "mean": float(np.mean(all_sims)),
        "std": float(np.std(all_sims)),
        "min": float(np.min(all_sims)),
        "max": float(np.max(all_sims)),
        "median": float(np.median(all_sims)),
    }

    types = [m["type"] for m in memories]
    same_type_sims = []
    diff_type_sims = []
    for i, j in zip(*upper_indices):
        if types[i] == types[j]:
            same_type_sims.append(sim_matrix[i, j])
        else:
            diff_type_sims.append(sim_matrix[i, j])

    if same_type_sims:
        stats["same_type_mean"] = float(np.mean(same_type_sims))
        stats["same_type_std"] = float(np.std(same_type_sims))
    if diff_type_sims:
        stats["diff_type_mean"] = float(np.mean(diff_type_sims))
        stats["diff_type_std"] = float(np.std(diff_type_sims))

    threads = [m["thread_ref"] for m in memories]
    same_thread_sims = []
    diff_thread_sims = []
    for i, j in zip(*upper_indices):
        if threads[i] and threads[j] and threads[i] == threads[j]:
            same_thread_sims.append(sim_matrix[i, j])
        elif threads[i] != threads[j]:
            diff_thread_sims.append(sim_matrix[i, j])

    if same_thread_sims:
        stats["same_thread_mean"] = float(np.mean(same_thread_sims))
        stats["same_thread_std"] = float(np.std(same_thread_sims))
    if diff_thread_sims:
        stats["diff_thread_mean"] = float(np.mean(diff_thread_sims))
        stats["diff_thread_std"] = float(np.std(diff_thread_sims))

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Embedding discrimination: source evidence measurement")
    parser.add_argument("--db", default=None)
    parser.add_argument("--sample-size", type=int, default=50)
    args = parser.parse_args()

    if args.db:
        db_path = args.db
    else:
        db_path = os.path.expanduser("~/.pallium/data/pallium.db")

    if not Path(db_path).exists():
        print(f"DB not found: {db_path}", file=sys.stderr)
        return 1

    print(f"Loading {args.sample_size} memories from: {db_path}")
    memories = load_memory_sample(db_path, args.sample_size)
    print(f"Loaded {len(memories)} memories with evidence")

    if len(memories) < 5:
        print("Not enough memories to analyze", file=sys.stderr)
        return 1

    v1_texts, v2_texts = build_embedding_versions(memories)

    from app.config import AppConfig
    from app.dependencies import build_embedding_provider

    config = AppConfig.from_env()
    vector_config = config.vector_index
    provider = build_embedding_provider(config, provider_name=vector_config.embedding_provider)
    print(f"Using model: {provider.model_name()} ({provider.dimensions()} dims)")

    print("Embedding V1 (current text with prefix)...")
    v1_vectors = provider.embed(v1_texts, mode="passage")
    print("Embedding V2 (current text + source evidence)...")
    v2_vectors = provider.embed(v2_texts, mode="passage")

    v1_sim = compute_similarity_matrix(v1_vectors)
    v2_sim = compute_similarity_matrix(v2_vectors)

    v1_stats = analyze_clustering(memories, v1_sim, "V1: type prefix only")
    v2_stats = analyze_clustering(memories, v2_sim, "V2: type prefix + evidence")

    print("\n" + "=" * 70)
    print("SIMILARITY DISTRIBUTION COMPARISON")
    print("=" * 70)

    for stats in [v1_stats, v2_stats]:
        print(f"\n--- {stats['label']} ---")
        print(f"  Overall: mean={stats['mean']:.4f} std={stats['std']:.4f} "
              f"min={stats['min']:.4f} max={stats['max']:.4f} median={stats['median']:.4f}")
        if "same_type_mean" in stats:
            print(f"  Same-type:    mean={stats['same_type_mean']:.4f} std={stats['same_type_std']:.4f}")
        if "diff_type_mean" in stats:
            print(f"  Diff-type:    mean={stats['diff_type_mean']:.4f} std={stats['diff_type_std']:.4f}")
        if "same_thread_mean" in stats:
            print(f"  Same-thread:  mean={stats['same_thread_mean']:.4f} std={stats['same_thread_std']:.4f}")
        if "diff_thread_mean" in stats:
            print(f"  Diff-thread:  mean={stats['diff_thread_mean']:.4f} std={stats['diff_thread_std']:.4f}")

    print("\n" + "=" * 70)
    print("ANALYSIS")
    print("=" * 70)

    spread_improved = v2_stats["std"] > v1_stats["std"]
    thread_clustering_increased = (
        v2_stats.get("same_thread_mean", 0) - v2_stats.get("diff_thread_mean", 0)
        > v1_stats.get("same_thread_mean", 0) - v1_stats.get("diff_thread_mean", 0)
    )
    type_separation_improved = (
        v2_stats.get("same_type_mean", 0) - v2_stats.get("diff_type_mean", 0)
        < v1_stats.get("same_type_mean", 0) - v1_stats.get("diff_type_mean", 0)
    )

    print(f"  Spread (std) improved: {spread_improved} "
          f"(V1={v1_stats['std']:.4f} -> V2={v2_stats['std']:.4f})")
    print(f"  Same-thread clustering increased (bad): {thread_clustering_increased}")
    print(f"  Type separation improved (good): {type_separation_improved}")

    if spread_improved and not thread_clustering_increased:
        print("\n  RECOMMENDATION: A2 HELPS — source evidence improves spread without excessive thread clustering")
    elif thread_clustering_increased:
        print("\n  RECOMMENDATION: A2 HURTS — source evidence causes same-thread clustering")
    else:
        print("\n  RECOMMENDATION: INCONCLUSIVE — no meaningful improvement from source evidence")

    return 0
