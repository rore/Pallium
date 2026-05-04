"""Build corpus for extraction alternatives eval.

Pulls source items from production DB with known outcomes:
- Items that produced investigation_outcomes (with feedback ratings)
- Items that produced constraint_memories (with feedback ratings)
- Items that produced NO typed memory (negative examples for triage)
- Thread context for thread-level extraction test

Usage:
    python -m evals.build_extraction_alternatives_corpus
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path.home() / ".pallium" / "data" / "pallium.db"
OUTPUT = Path(__file__).parent / "extraction_alternatives_corpus.jsonl"
THREAD_CONTEXT_OUTPUT = Path(__file__).parent / "extraction_alternatives_thread_context.jsonl"


def build_corpus():
    sys.stdout.reconfigure(encoding="utf-8")
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    corpus = []

    # Part A: Source items that produced investigation_outcomes (with feedback)
    cur.execute("""
        SELECT DISTINCT si.id, si.content, si.role, si.source_type, si.source_id,
               si.artifact_kind, si.thread_ref, si.container_ref, si.visibility,
               si.metadata_json, si.created_at
        FROM memory_objects mo
        JOIN source_items si ON si.source_id = json_extract(mo.payload_json, '$.source_id')
            AND si.source_type = json_extract(mo.payload_json, '$.source_type')
        WHERE mo.type = 'investigation_outcome'
          AND json_extract(mo.payload_json, '$.source_type') != 'thread_detection'
          AND mo.id IN (SELECT memory_object_id FROM memory_feedback)
    """)
    inv_items = {row[0]: row for row in cur.fetchall()}

    for si_id, row in inv_items.items():
        ratings = _get_ratings(cur, si_id, "investigation_outcome")
        relevant_count = sum(1 for r in ratings if r["rating"] == "relevant")
        not_relevant_count = sum(1 for r in ratings if r["rating"] == "not_relevant")
        majority = "relevant" if relevant_count > not_relevant_count else "not_relevant"

        corpus.append(_build_entry(row, "investigation_outcome", majority, ratings))

    # Part B: Source items that produced constraint_memory (with feedback)
    # Constraints use relations table for source linkage, not payload source_id
    cur.execute("""
        SELECT DISTINCT si.id, si.content, si.role, si.source_type, si.source_id,
               si.artifact_kind, si.thread_ref, si.container_ref, si.visibility,
               si.metadata_json, si.created_at
        FROM memory_objects mo
        JOIN relations r ON r.from_id = mo.id AND r.relation_type = 'supported_by'
        JOIN source_items si ON si.id = r.to_id
        WHERE mo.type = 'constraint_memory'
          AND mo.id IN (SELECT memory_object_id FROM memory_feedback)
    """)
    constraint_items = {row[0]: row for row in cur.fetchall()}

    for si_id, row in constraint_items.items():
        ratings = _get_constraint_ratings(cur, si_id)
        relevant_count = sum(1 for r in ratings if r["rating"] == "relevant")
        not_relevant_count = sum(1 for r in ratings if r["rating"] == "not_relevant")
        majority = "relevant" if relevant_count > not_relevant_count else "not_relevant"

        corpus.append(_build_entry(row, "constraint_memory", majority, ratings))

    # Part C: Negative examples — items that produced NO typed memory
    cur.execute("""
        SELECT si.id, si.content, si.role, si.source_type, si.source_id,
               si.artifact_kind, si.thread_ref, si.container_ref, si.visibility,
               si.metadata_json, si.created_at
        FROM source_items si
        WHERE si.processing_status = 'completed'
          AND si.created_at > '2026-04-28'
          AND NOT EXISTS (
              SELECT 1 FROM memory_objects mo
              WHERE json_extract(mo.payload_json, '$.source_id') = si.source_id
                AND json_extract(mo.payload_json, '$.source_type') = si.source_type
                AND mo.type IN ('investigation_outcome', 'decision', 'constraint_memory')
          )
        ORDER BY RANDOM()
        LIMIT 200
    """)
    for row in cur.fetchall():
        corpus.append(_build_entry(row, None, None, []))

    # Part D: Build thread context for thread-level test
    thread_refs = set()
    for item in corpus:
        if item.get("thread_ref") and item["produced_type"] == "investigation_outcome":
            thread_refs.add(item["thread_ref"])

    thread_contexts = {}
    for thread_ref in thread_refs:
        cur.execute("""
            SELECT si.content, si.role, si.artifact_kind, si.source_id, si.created_at
            FROM source_items si
            WHERE si.thread_ref = ?
            ORDER BY si.created_at
        """, (thread_ref,))
        items = []
        for trow in cur.fetchall():
            items.append({
                "content": trow[0],
                "role": trow[1],
                "artifact_kind": trow[2],
                "source_id": trow[3],
                "created_at": trow[4],
            })
        thread_contexts[thread_ref] = {
            "thread_ref": thread_ref,
            "item_count": len(items),
            "items": items,
        }

    conn.close()

    # Save corpus
    with open(OUTPUT, "w", encoding="utf-8") as f:
        for item in corpus:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    # Save thread contexts
    with open(THREAD_CONTEXT_OUTPUT, "w", encoding="utf-8") as f:
        for ctx in thread_contexts.values():
            f.write(json.dumps(ctx, ensure_ascii=False) + "\n")

    # Report
    inv_items_list = [c for c in corpus if c["produced_type"] == "investigation_outcome"]
    con_items_list = [c for c in corpus if c["produced_type"] == "constraint_memory"]
    neg_items = [c for c in corpus if c["produced_type"] is None]

    print(f"Corpus saved: {len(corpus)} items → {OUTPUT}")
    print(f"  investigation_outcome: {len(inv_items_list)}")
    print(f"    relevant: {sum(1 for c in inv_items_list if c['majority_rating'] == 'relevant')}")
    print(f"    not_relevant: {sum(1 for c in inv_items_list if c['majority_rating'] == 'not_relevant')}")
    print(f"  constraint_memory: {len(con_items_list)}")
    print(f"    relevant: {sum(1 for c in con_items_list if c['majority_rating'] == 'relevant')}")
    print(f"    not_relevant: {sum(1 for c in con_items_list if c['majority_rating'] == 'not_relevant')}")
    print(f"  no_typed_memory (negatives): {len(neg_items)}")
    print(f"Thread contexts: {len(thread_contexts)} threads → {THREAD_CONTEXT_OUTPUT}")


def _get_ratings(cur, si_id: str, memory_type: str) -> list[dict]:
    cur.execute("""
        SELECT mf.rating, mf.reason
        FROM memory_objects mo
        JOIN memory_feedback mf ON mf.memory_object_id = mo.id
        JOIN source_items si ON si.source_id = json_extract(mo.payload_json, '$.source_id')
            AND si.source_type = json_extract(mo.payload_json, '$.source_type')
        WHERE si.id = ?
          AND mo.type = ?
    """, (si_id, memory_type))
    return [{"rating": row[0], "reason": row[1]} for row in cur.fetchall()]


def _get_constraint_ratings(cur, si_id: str) -> list[dict]:
    cur.execute("""
        SELECT mf.rating, mf.reason
        FROM memory_objects mo
        JOIN memory_feedback mf ON mf.memory_object_id = mo.id
        JOIN relations r ON r.from_id = mo.id AND r.relation_type = 'supported_by'
        WHERE r.to_id = ?
          AND mo.type = 'constraint_memory'
    """, (si_id,))
    return [{"rating": row[0], "reason": row[1]} for row in cur.fetchall()]


def _build_entry(row, produced_type, majority_rating, ratings):
    metadata_json = row[9]
    metadata = json.loads(metadata_json) if metadata_json else None
    signals = metadata.get("pallium_semantic_signals", {}) if metadata else {}

    return {
        "source_item_id": row[0],
        "content": row[1],
        "role": row[2],
        "source_type": row[3],
        "source_id": row[4],
        "artifact_kind": row[5],
        "thread_ref": row[6],
        "container_ref": row[7],
        "visibility": row[8],
        "created_at": row[10],
        "produced_type": produced_type,
        "majority_rating": majority_rating,
        "ratings": ratings,
        "current_signals": {
            "is_low_value_meta": signals.get("is_low_value_meta"),
            "progress_text": signals.get("progress_text"),
            "blocker_text": signals.get("blocker_text"),
            "next_step_text": signals.get("next_step_text"),
            "key_finding_text": signals.get("key_finding_text"),
            "constraint_text": signals.get("constraint_text"),
        },
    }


if __name__ == "__main__":
    build_corpus()
