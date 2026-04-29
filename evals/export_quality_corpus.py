"""Export production DB source items into annotated eval corpus.

Annotations:
- expected_suppress: True if this should produce NO memory at all
- must_not_suppress: True if this MUST produce memory (false-negative guard)
"""
import json
import sqlite3
from pathlib import Path

DB_PATH = Path.home() / ".pallium" / "data" / "pallium.db"
OUTPUT = Path(__file__).parent / "memory_quality_corpus.jsonl"

MUST_NOT_SUPPRESS_PATTERNS = [
    "root cause",
    "race condition",
    "vector index corruption",
    "demo packages",
    "multilingual-e5-small",
    "vanilla html",
    "documentation pass",
    "minimal config",
    "investigation found",
    "verdict:",
    "decision:",
]


def export():
    if not DB_PATH.exists():
        print(f"DB not found at {DB_PATH}")
        return

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    cur.execute("""
        SELECT id, content, role, artifact_kind, thread_ref, container_ref,
               visibility, source_type, source_id
        FROM source_items
        WHERE processing_status = 'completed' AND container_ref != 'test-container'
        ORDER BY created_at
    """)
    items = []
    for row in cur.fetchall():
        content = row[1] or ""
        items.append({
            "source_item_id": row[0],
            "content": content,
            "role": row[2],
            "artifact_kind": row[3],
            "thread_ref": row[4],
            "container_ref": row[5],
            "visibility": row[6],
            "source_type": row[7],
            "source_id": row[8],
            "expected_suppress": _should_suppress(content),
            "must_not_suppress": _must_not_suppress(content),
        })
    conn.close()

    with open(OUTPUT, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"Exported {len(items)} items to {OUTPUT}")


def _should_suppress(content: str) -> bool:
    c = content.strip()
    if len(c) < 15:
        return True
    if "<ide_opened_file>" in c and len(c) < 200:
        return True
    return False


def _must_not_suppress(content: str) -> bool:
    cl = content.lower()
    return any(p in cl for p in MUST_NOT_SUPPRESS_PATTERNS)


if __name__ == "__main__":
    export()
