"""Retroactive cleanup: supersede memories derived from too-short source items.

Applies the same structural gates that now exist in the ingestion pipeline:
  - interest memories where the source item has < 10 tokens -> supersede
  - turn_summary memories where the source item has < 20 tokens -> supersede

Only updates lifecycle='superseded'; does NOT delete rows or touch relations.

Usage:
    python -m scripts.cleanup_short_source_memories --db-path path/to/pallium.db
    python -m scripts.cleanup_short_source_memories --db-path path/to/pallium.db --execute
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import text, update

from core.text import tokenize_text
from storage.sqlite import SQLiteStorageProvider
from storage.sqlite_schema import MemoryObjectRecord


# Structural gate thresholds (must match ingestion-time gates)
INTEREST_MIN_TOKENS = 10
TURN_SUMMARY_MIN_TOKENS = 20


def find_short_source_memories(
    storage: SQLiteStorageProvider,
    memory_type: str,
    min_tokens: int,
) -> list[dict]:
    """Find active memories of given type whose source item content is below the token threshold."""
    query = text("""
        SELECT mo.id AS memory_id, si.content AS source_content
        FROM memory_objects mo
        JOIN relations r
            ON r.from_kind = 'memory_object' AND r.from_id = mo.id
            AND r.relation_type = 'supported_by'
            AND r.to_kind = 'source_item'
        JOIN source_items si ON si.id = r.to_id
        WHERE mo.type = :memory_type
          AND mo.lifecycle = 'active'
    """)
    with storage._session_factory() as session:
        rows = session.execute(query, {"memory_type": memory_type}).all()

    # Group by memory_id, keeping only the richest (longest) source item.
    # A memory should only be superseded if its best source is below threshold.
    best_per_memory: dict[str, tuple[str, int]] = {}  # memory_id -> (content, token_count)
    for memory_id, source_content in rows:
        tokens = tokenize_text(source_content)
        token_count = len(tokens)
        existing = best_per_memory.get(memory_id)
        if existing is None or token_count > existing[1]:
            best_per_memory[memory_id] = (source_content, token_count)

    results = []
    for memory_id, (content, token_count) in best_per_memory.items():
        if token_count < min_tokens:
            results.append({
                "memory_id": memory_id,
                "source_content": content,
                "token_count": token_count,
            })
    return results


def supersede_memories(storage: SQLiteStorageProvider, memory_ids: list[str]) -> int:
    """Set lifecycle='superseded' for the given memory object IDs."""
    if not memory_ids:
        return 0

    def _do(session):
        result = session.execute(
            update(MemoryObjectRecord)
            .where(MemoryObjectRecord.id.in_(memory_ids))
            .values(lifecycle="superseded")
        )
        return result.rowcount

    return storage._with_retry(_do)


def content_preview(content: str, max_len: int = 60) -> str:
    """Truncate content for display."""
    oneline = content.replace("\n", " ").strip()
    if len(oneline) > max_len:
        return oneline[:max_len] + "..."
    return oneline


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Supersede memories derived from too-short source items"
    )
    parser.add_argument("--db-path", required=True, help="Path to SQLite database file")
    parser.add_argument(
        "--execute", action="store_true",
        help="Apply changes (dry-run by default)"
    )
    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"ERROR: Database not found: {db_path}", file=sys.stderr)
        return 1

    db_url = f"sqlite:///{db_path}"
    storage = SQLiteStorageProvider(db_url)

    # --- Interest memories with short source content ---
    interest_hits = find_short_source_memories(storage, "interest", INTEREST_MIN_TOKENS)

    print(f"=== Interest memories with short source content (<{INTEREST_MIN_TOKENS} tokens) ===")
    if interest_hits:
        for hit in interest_hits:
            preview = content_preview(hit["source_content"])
            action = "superseded" if args.execute else "would supersede"
            print(f'  [{hit["memory_id"]}] source: "{preview}" ({hit["token_count"]} tokens) -> {action}')
    else:
        print("  (none found)")
    print()

    # --- Turn summary memories with short source content ---
    discussion_hits = find_short_source_memories(
        storage, "turn_summary", TURN_SUMMARY_MIN_TOKENS
    )

    print(f"=== Turn summaries with short source content (<{TURN_SUMMARY_MIN_TOKENS} tokens) ===")
    if discussion_hits:
        for hit in discussion_hits:
            preview = content_preview(hit["source_content"])
            action = "superseded" if args.execute else "would supersede"
            print(f'  [{hit["memory_id"]}] source: "{preview}" ({hit["token_count"]} tokens) -> {action}')
    else:
        print("  (none found)")
    print()

    # --- Summary ---
    total = len(interest_hits) + len(discussion_hits)
    print("=== Summary ===")
    print(f"  Interest memories to supersede: {len(interest_hits)}")
    print(f"  Turn summaries to supersede: {len(discussion_hits)}")
    print(f"  Total: {total}")
    print()

    if total == 0:
        print("Nothing to do.")
        return 0

    if not args.execute:
        print("Dry run -- no changes made. Use --execute to apply.")
        return 0

    # --- Execute ---
    all_ids = [h["memory_id"] for h in interest_hits] + [h["memory_id"] for h in discussion_hits]
    updated = supersede_memories(storage, all_ids)
    print(f"Done. Updated {updated} memory objects to lifecycle='superseded'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
