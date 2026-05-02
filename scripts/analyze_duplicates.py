"""One-off script to measure semantic duplicates in the live Pallium DB.

Usage:
    python scripts/analyze_duplicates.py [--threshold 0.92] [--db PATH]

Reads the vector index + SQLite DB, groups active memories by (container_ref, type),
and reports pairs above the cosine similarity threshold.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np


def main():
    parser = argparse.ArgumentParser(description="Analyze semantic duplicates in Pallium DB")
    parser.add_argument("--threshold", type=float, default=0.92, help="Cosine similarity threshold (default: 0.92)")
    parser.add_argument("--db", type=str, default=None, help="Path to pallium.db (default: ~/.pallium/data/pallium.db)")
    parser.add_argument("--top", type=int, default=20, help="Show top N duplicate pairs (default: 20)")
    args = parser.parse_args()

    data_dir = Path(args.db).parent if args.db else Path.home() / ".pallium" / "data"
    db_path = Path(args.db) if args.db else data_dir / "pallium.db"
    index_path = data_dir / "vector_index"
    idmap_path = data_dir / "vector_index.idmap.json"

    if not db_path.exists():
        print(f"ERROR: DB not found at {db_path}")
        sys.exit(1)
    if not index_path.exists():
        print(f"ERROR: Vector index not found at {index_path}")
        sys.exit(1)

    # Load idmap
    idmap = json.loads(idmap_path.read_text(encoding="utf-8"))
    id_to_key: dict[str, int] = idmap["id_to_key"]
    key_to_id: dict[int, str] = {int(k): v for v, k in id_to_key.items()}

    # Load usearch index
    from usearch.index import Index
    index = Index(ndim=384, metric="cos", dtype="f32")
    index.load(str(index_path))
    print(f"Loaded vector index: {index.size} vectors")

    # Load memory metadata from SQLite
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Get active memory objects
    cur = conn.execute("""
        SELECT id, type, container_ref, lifecycle, payload_json, created_at
        FROM memory_objects
        WHERE lifecycle = 'active'
    """)
    memories = {row["id"]: dict(row) for row in cur.fetchall()}
    print(f"Active memories: {len(memories)}")

    # Get vector index entries that point to memory objects
    # Only use CONTENT embeddings, not shared context embeddings
    CONTENT_VIEWS = {
        "memory_object.fact_embedding",
        "memory_object.fact_summary_embedding",
    }
    CONTEXT_VIEWS = {
        "memory_object.thread_summary_context.embedding",
        "memory_object.investigation_context.embedding",
        "memory_object.task_checkpoint_context.embedding",
        "memory_object.interest_context.embedding",
        "memory_object.constraint_memory_context.embedding",
        "memory_object.decision_context.embedding",
    }
    cur = conn.execute("""
        SELECT id, target_id, text_view_name
        FROM index_entries
        WHERE index_type = 'vector' AND target_kind = 'memory_object'
    """)
    entry_to_memory: dict[str, str] = {}
    context_only_memories: set[str] = set()
    all_memory_entries: dict[str, list[tuple[str, str]]] = {}  # memory_id -> [(entry_id, view_name)]
    for row in cur.fetchall():
        entry_id, target_id, view_name = row["id"], row["target_id"], row["text_view_name"]
        all_memory_entries.setdefault(target_id, []).append((entry_id, view_name or ""))

    # For each memory, prefer content views; fall back to context views if no content view exists
    for memory_id, entries_list in all_memory_entries.items():
        content_entries = [(eid, vn) for eid, vn in entries_list if vn in CONTENT_VIEWS]
        if content_entries:
            for eid, _ in content_entries:
                entry_to_memory[eid] = memory_id
        else:
            # Context-only: use all entries but mark for reporting
            context_only_memories.add(memory_id)
            for eid, _ in entries_list:
                entry_to_memory[eid] = memory_id

    conn.close()
    print(f"Vector entries for comparison: {len(entry_to_memory)} (content-only where available)")
    print(f"Memories with only context embeddings: {len(context_only_memories)}")

    # Build groups: (container_ref, type) -> { memory_id: [usearch_keys] }
    groups: dict[tuple[str, str], dict[str, list[int]]] = {}
    skipped = 0
    for entry_id, memory_id in entry_to_memory.items():
        if memory_id not in memories:
            skipped += 1
            continue
        if entry_id not in id_to_key:
            skipped += 1
            continue
        mem = memories[memory_id]
        group_key = (mem["container_ref"] or "", mem["type"])
        usearch_key = id_to_key[entry_id]
        groups.setdefault(group_key, {}).setdefault(memory_id, []).append(usearch_key)

    total_memories_in_groups = sum(len(mems) for mems in groups.values())
    print(f"Groups (container+type): {len(groups)}, memories in groups: {total_memories_in_groups}, skipped entries: {skipped}")
    print(f"Threshold: {args.threshold}")
    print()

    # For each group, compare distinct memories using max similarity across their embeddings
    all_duplicates: list[tuple[float, str, str, str, str, str]] = []

    for (container, mem_type), mem_keys in sorted(groups.items(), key=lambda x: -len(x[1])):
        mem_ids = list(mem_keys.keys())
        if len(mem_ids) < 2:
            continue

        # For each memory, compute centroid vector (average of its embeddings)
        # This is simpler and good enough — if two memories are semantically similar,
        # their centroids will be similar too
        centroids = np.zeros((len(mem_ids), 384), dtype=np.float32)
        for i, mid in enumerate(mem_ids):
            keys = mem_keys[mid]
            vecs = np.zeros((len(keys), 384), dtype=np.float32)
            for j, key in enumerate(keys):
                vecs[j] = index[key]
            centroids[i] = vecs.mean(axis=0)

        # Normalize
        norms = np.linalg.norm(centroids, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        centroids_normed = centroids / norms

        # Pairwise cosine similarity
        sim_matrix = centroids_normed @ centroids_normed.T

        # Find pairs above threshold (distinct memories only)
        for i in range(len(mem_ids)):
            for j in range(i + 1, len(mem_ids)):
                sim = float(sim_matrix[i, j])
                if sim >= args.threshold:
                    all_duplicates.append((sim, container, mem_type, mem_ids[i], mem_ids[j], ""))

    # Sort by similarity descending
    all_duplicates.sort(key=lambda x: -x[0])

    print(f"=== DUPLICATE PAIRS (similarity >= {args.threshold}) ===")
    print(f"Total: {len(all_duplicates)}")
    print()

    if not all_duplicates:
        print("No duplicates found. Your memory is clean!")
        return

    # Stats
    type_counts: dict[str, int] = {}
    for _, _, mem_type, _, _, _ in all_duplicates:
        type_counts[mem_type] = type_counts.get(mem_type, 0) + 1

    print("By type:")
    for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {t}: {c} pairs")
    print()

    # Show top N
    print(f"--- Top {min(args.top, len(all_duplicates))} pairs ---")
    conn = sqlite3.connect(str(db_path))
    for i, (sim, container, mem_type, id_a, id_b, _) in enumerate(all_duplicates[:args.top]):
        # Get summaries from payload
        row_a = conn.execute("SELECT payload_json, created_at FROM memory_objects WHERE id = ?", (id_a,)).fetchone()
        row_b = conn.execute("SELECT payload_json, created_at FROM memory_objects WHERE id = ?", (id_b,)).fetchone()
        payload_a = json.loads(row_a[0]) if row_a else {}
        payload_b = json.loads(row_b[0]) if row_b else {}
        summary_a = (payload_a.get("summary") or payload_a.get("decision") or payload_a.get("statement") or payload_a.get("fact") or payload_a.get("interest") or str(payload_a))[:120]
        summary_b = (payload_b.get("summary") or payload_b.get("decision") or payload_b.get("statement") or payload_b.get("fact") or payload_b.get("interest") or str(payload_b))[:120]
        created_a = row_a[1] if row_a else "?"
        created_b = row_b[1] if row_b else "?"

        print(f"\n#{i+1} similarity={sim:.4f} type={mem_type}")
        print(f"  A [{created_a}]: {summary_a}")
        print(f"  B [{created_b}]: {summary_b}")

    conn.close()

    # Summary
    total_active = len(memories)
    unique_ids_in_dupes = set()
    for _, _, _, id_a, id_b, _ in all_duplicates:
        unique_ids_in_dupes.add(id_a)
        unique_ids_in_dupes.add(id_b)
    print(f"\n=== SUMMARY ===")
    print(f"Active memories: {total_active}")
    print(f"Duplicate pairs: {len(all_duplicates)}")
    print(f"Memories involved in duplicates: {len(unique_ids_in_dupes)} ({100*len(unique_ids_in_dupes)/total_active:.1f}%)")
    print(f"Potential supersessions (keep older, mark newer): {len(all_duplicates)}")


if __name__ == "__main__":
    main()
