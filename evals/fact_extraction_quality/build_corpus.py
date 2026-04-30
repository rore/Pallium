"""Build evaluation corpus from production DB atomic facts.

Extracts source chunks (as the LLM sees them) and annotated reference facts.
Outputs:
  - source_chunks.jsonl: input chunks for re-extraction testing
  - reference_facts.jsonl: all facts with noise/good annotations
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from collections import Counter
from pathlib import Path

DB_PATH = Path(os.environ.get("PALLIUM_DB", r"C:\Users\I347041\.pallium\data\pallium.db"))
OUTPUT_DIR = Path(__file__).parent


def classify_fact(stmt: str) -> tuple[str, str | None]:
    """Classify a fact statement as 'noise' or 'good' with reason."""
    lower = stmt.lower()

    # Implementation narration — past-tense changes
    if any(kw in lower for kw in [
        "was fixed", "was changed", "was added", "was removed", "was updated",
        "was extended", "was renamed", "was restructured", "was deployed",
        "was pushed", "was completed", "was superseded", "was run", "was cleaned",
        "was built", "was rewritten", "was moved", "was merged",
        "were superseded", "were removed", "were duplicated", "were pushed",
    ]):
        return "noise", "implementation_narration"

    # 'now X' narration — describing what changed
    if any(kw in lower for kw in [
        "now load", "now send", "now include", "now has", "now goes",
        "now contain", "now use", "now show", "now default", "now does", "now call",
    ]):
        return "noise", "implementation_narration_now"

    # Plan/task references
    if any(kw in lower for kw in [
        "task 1", "task 2", "task 3", "task 4", "task 5",
        "task 6", "task 7", "task 8", "task 9",
    ]):
        return "noise", "plan_task_reference"

    if "improvement " in lower and any(kw in lower for kw in [
        "target", "focus", "address", "priority", "identified",
    ]):
        return "noise", "improvement_plan"

    if "plan" in lower and any(kw in lower for kw in [
        "defers", "includes", "creates", "revision", "should include", "does not address",
    ]):
        return "noise", "plan_detail"

    if any(kw in lower for kw in ["proposed ", "recommendation is", "recommends"]):
        return "noise", "proposal_recommendation"

    # Test/eval results
    if any(kw in lower for kw in [
        "tests pass", "test run", "eval achieved", "eval confirmed", "all passing",
    ]):
        return "noise", "test_eval_result"

    # Git state
    if any(kw in lower for kw in ["commit ", "ahead of commit"]):
        return "noise", "git_state"

    # Runtime status
    if any(kw in lower for kw in [
        "port ", " pid", "uptime", "approximately 91mb", "approximately 5mb", "0 rows in",
    ]):
        return "noise", "runtime_status"

    if any(kw in lower for kw in ["mb memory", "kb in size"]):
        if not any(good in lower for good in ["because", "race", "root cause", "caused by"]):
            return "noise", "runtime_resource"

    # Prescriptive (should/must without constraint justification)
    if any(kw in lower for kw in [
        "should be", "should include", "should not", "needs to be", "must be", "must include",
    ]):
        if not any(good in lower for good in ["because", "constraint", "cannot", "limitation", "required"]):
            return "noise", "prescriptive_not_factual"

    # UI layout detail
    if any(kw in lower for kw in [
        "dashboard section", "collapsible section", "panel display", "two-column layout",
    ]):
        return "noise", "ui_layout_detail"

    return "good", None


def build_corpus():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row

    # Get all facts with annotations
    all_facts = db.execute("""
        SELECT id, payload_json
        FROM memory_objects
        WHERE type = 'atomic_fact' AND lifecycle = 'active'
    """).fetchall()

    facts_by_thread: dict[str | None, list[dict]] = {}
    for f in all_facts:
        payload = json.loads(f["payload_json"])
        thread_ref = payload.get("thread_ref")
        judgment, reason = classify_fact(payload.get("statement", ""))
        entry = {
            "fact_id": f["id"],
            "subject": payload.get("subject", ""),
            "statement": payload.get("statement", ""),
            "category": payload.get("category", ""),
            "expected_judgment": judgment,
            "noise_reason": reason,
        }
        facts_by_thread.setdefault(thread_ref, []).append(entry)

    # Build source chunks per thread
    threads = db.execute("""
        SELECT DISTINCT json_extract(payload_json, '$.thread_ref') as thread_ref
        FROM memory_objects
        WHERE type = 'atomic_fact' AND lifecycle = 'active'
        AND json_extract(payload_json, '$.thread_ref') IS NOT NULL
    """).fetchall()

    corpus_chunks = []
    chunk_idx = 0

    for thread_row in threads:
        thread_ref = thread_row["thread_ref"]

        sources = db.execute("""
            SELECT DISTINCT s.id, s.content, s.role, s.artifact_kind, s.created_at
            FROM relations r
            JOIN source_items s ON r.to_id = s.id
            WHERE r.from_kind = 'memory_object'
            AND r.to_kind = 'source_item'
            AND r.relation_type = 'supported_by'
            AND r.from_id IN (
                SELECT id FROM memory_objects
                WHERE type = 'atomic_fact' AND lifecycle = 'active'
                AND json_extract(payload_json, '$.thread_ref') = ?
            )
            ORDER BY s.created_at
        """, (thread_ref,)).fetchall()

        # Build chunks (same logic as _build_chunk_texts in conversational_knowledge.py)
        current_lines: list[str] = []
        current_chars = 0
        current_count = 0

        for item in sources:
            role = item["role"] or "unknown"
            content = item["content"] or ""
            line = f"[{role}]: {content}"
            line_chars = len(line) + 1

            if current_count > 0 and (current_count >= 10 or current_chars + line_chars > 6000):
                corpus_chunks.append({
                    "chunk_id": f"chunk_{chunk_idx:03d}",
                    "thread_ref": thread_ref,
                    "chunk_index": len([c for c in corpus_chunks if c["thread_ref"] == thread_ref]),
                    "chunk_text": "\n".join(current_lines),
                    "source_item_count": current_count,
                })
                chunk_idx += 1
                current_lines = []
                current_chars = 0
                current_count = 0

            current_lines.append(line)
            current_chars += line_chars
            current_count += 1

        if current_lines:
            corpus_chunks.append({
                "chunk_id": f"chunk_{chunk_idx:03d}",
                "thread_ref": thread_ref,
                "chunk_index": len([c for c in corpus_chunks if c["thread_ref"] == thread_ref]),
                "chunk_text": "\n".join(current_lines),
                "source_item_count": current_count,
            })
            chunk_idx += 1

    # Write source chunks
    chunks_path = OUTPUT_DIR / "source_chunks.jsonl"
    with open(chunks_path, "w", encoding="utf-8") as f:
        for entry in corpus_chunks:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # Write reference facts
    facts_path = OUTPUT_DIR / "reference_facts.jsonl"
    with open(facts_path, "w", encoding="utf-8") as f:
        for thread_ref, facts in facts_by_thread.items():
            for fact in facts:
                fact_entry = dict(fact)
                fact_entry["thread_ref"] = thread_ref
                f.write(json.dumps(fact_entry, ensure_ascii=False) + "\n")

    # Summary
    total_facts = sum(len(facts) for facts in facts_by_thread.values())
    noise_facts = sum(1 for facts in facts_by_thread.values() for fa in facts if fa["expected_judgment"] == "noise")

    print(f"Chunks: {len(corpus_chunks)} (from {len(threads)} threads)")
    print(f"Facts:  {total_facts} ({noise_facts} noise / {total_facts - noise_facts} good)")
    print(f"Noise rate: {noise_facts * 100 / total_facts:.1f}%")
    print()
    print(f"Written: {chunks_path}")
    print(f"Written: {facts_path}")

    # Noise breakdown
    reasons = Counter(fa["noise_reason"] for facts in facts_by_thread.values() for fa in facts if fa["noise_reason"])
    print("\nNoise reasons:")
    for reason, count in reasons.most_common():
        print(f"  {reason:35s} {count}")

    db.close()


if __name__ == "__main__":
    build_corpus()
