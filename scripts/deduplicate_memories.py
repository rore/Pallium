"""Deduplicate memory objects that were created by the legacy/package-path race condition.

For each source_item that produced multiple memory_objects of the same type+schema,
keeps the earliest and deletes the rest using the standard cascade deletion.

Usage:
    python -m scripts.deduplicate_memories --db-path path/to/pallium.db
    python -m scripts.deduplicate_memories --db-path path/to/pallium.db --execute
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import select, text

from storage.sqlite import SQLiteStorageProvider
from storage.sqlite_schema import MemoryObjectRecord, RelationRecord


def find_duplicate_groups(storage: SQLiteStorageProvider) -> list[dict]:
    """Find memory_objects that share source_item + type + schema_id."""
    query = text("""
        SELECT r.to_id AS source_item_id, mo.type, mo.schema_id,
               GROUP_CONCAT(mo.id) AS ids, COUNT(*) AS cnt
        FROM memory_objects mo
        JOIN relations r ON r.from_kind = 'memory_object' AND r.from_id = mo.id
            AND r.relation_type = 'supported_by' AND r.to_kind = 'source_item'
        WHERE mo.lifecycle = 'active'
        GROUP BY r.to_id, mo.type, mo.schema_id
        HAVING cnt > 1
        ORDER BY cnt DESC
    """)
    with storage._session_factory() as session:
        rows = session.execute(query).all()

    groups = []
    for source_item_id, type_, schema_id, ids_csv, cnt in rows:
        mo_ids = ids_csv.split(",")
        # Determine which to keep: earliest created_at
        with storage._session_factory() as session:
            records = session.scalars(
                select(MemoryObjectRecord)
                .where(MemoryObjectRecord.id.in_(mo_ids))
                .order_by(MemoryObjectRecord.created_at.asc())
            ).all()
        keep_id = records[0].id
        delete_ids = [r.id for r in records[1:]]
        groups.append({
            "source_item_id": source_item_id,
            "type": type_,
            "schema_id": schema_id,
            "keep_id": keep_id,
            "delete_ids": delete_ids,
            "count": cnt,
        })
    return groups


def delete_duplicates(storage: SQLiteStorageProvider, groups: list[dict]) -> int:
    """Delete duplicate memory objects using the standard cascade."""
    total_deleted = 0
    with storage._session_factory.begin() as session:
        for group in groups:
            for mo_id in group["delete_ids"]:
                storage._delete_memory_object_cascade_in_session(session, mo_id)
                total_deleted += 1
    return total_deleted


def main() -> int:
    parser = argparse.ArgumentParser(description="Deduplicate memory objects")
    parser.add_argument("--db-path", required=True, help="Path to SQLite database file")
    parser.add_argument("--execute", action="store_true", help="Actually delete (dry-run by default)")
    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"ERROR: Database not found: {db_path}", file=sys.stderr)
        return 1

    db_url = f"sqlite:///{db_path}"
    storage = SQLiteStorageProvider(db_url)

    groups = find_duplicate_groups(storage)
    if not groups:
        print("No duplicates found.")
        return 0

    total_to_delete = sum(len(g["delete_ids"]) for g in groups)
    print(f"Found {len(groups)} duplicate groups, {total_to_delete} objects to delete:\n")

    for g in groups:
        print(f"  source_item={g['source_item_id'][:12]}... type={g['type']} schema={g['schema_id']}")
        print(f"    keep: {g['keep_id']}")
        for did in g["delete_ids"]:
            print(f"    delete: {did}")
        print()

    if not args.execute:
        print("DRY RUN — pass --execute to delete.")
        return 0

    deleted = delete_duplicates(storage, groups)
    print(f"Deleted {deleted} duplicate memory objects.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
