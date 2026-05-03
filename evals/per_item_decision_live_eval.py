"""Live LLM eval for per-item decision extraction prompt v9.

Re-runs the extraction prompt against source items that previously produced
decisions, checking whether the v9 prompt correctly rejects bad items
and keeps good items.

Usage:
    python -m evals.per_item_decision_live_eval
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from app.config import AppConfig
from app.dependencies import build_semantic_plugins
from core.models import SourceItem
from semantic.agent_conversation_memory import AgentConversationMemoryPlugin
from semantic.llm_agent_memory import LLMAgentMemoryPlugin


CORPUS_PATH = Path(__file__).parent / "per_item_decision_quality_corpus.jsonl"
DB_PATH = Path.home() / ".pallium" / "data" / "pallium.db"


def load_corpus() -> list[dict]:
    return [json.loads(line) for line in open(CORPUS_PATH, encoding="utf-8") if line.strip()]


def get_source_items_for_corpus() -> dict[str, dict]:
    """Map corpus item ID prefix → source item data."""
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    cur.execute("""
        SELECT mo.id, si.content, si.role, si.source_type, si.source_id, si.visibility
        FROM memory_objects mo
        JOIN source_items si ON si.source_id = json_extract(mo.payload_json, '$.source_id')
            AND si.source_type = json_extract(mo.payload_json, '$.source_type')
        WHERE mo.type = 'decision'
          AND json_extract(mo.payload_json, '$.source_type') != 'thread_detection'
    """)
    result = {}
    for row in cur.fetchall():
        prefix = row[0][:8]
        if prefix not in result:
            result[prefix] = {
                "content": row[1],
                "role": row[2],
                "source_type": row[3],
                "source_id": row[4],
                "visibility": row[5],
            }
    conn.close()
    return result


def main():
    sys.stdout.reconfigure(encoding="utf-8")

    corpus = load_corpus()
    source_map = get_source_items_for_corpus()

    config = AppConfig.from_env()
    plugins = build_semantic_plugins(config)
    acm_plugin = plugins.get("agent_conversation_memory")
    if not isinstance(acm_plugin, AgentConversationMemoryPlugin):
        print("ERROR: 'agent_conversation_memory' plugin not found")
        sys.exit(1)
    plugin = acm_plugin._delegate

    print(f"Corpus: {len(corpus)} items")
    print(f"Source items found: {len(source_map)}")
    print(f"Provider: {plugin.prompt_variant}")
    print()

    results = {
        "good_kept": [],
        "good_rejected": [],
        "bad_kept": [],
        "bad_rejected": [],
    }

    print("=" * 60)
    print("LIVE LLM EVAL — Per-Item Decision Extraction v9")
    print("=" * 60)
    print()

    for item in corpus:
        prefix = item["id"][:8]
        if prefix not in source_map:
            print(f"  SKIP {prefix} — no source item found")
            continue

        source_data = source_map[prefix]
        source_item = SourceItem(
            source_type=source_data["source_type"],
            source_id=source_data["source_id"],
            content_type="text/plain",
            content=source_data["content"],
            role=source_data["role"],
            visibility=source_data.get("visibility") or "private",
        )

        try:
            trace = plugin.analyze_item(source_item)
            extraction = trace.extraction
        except Exception as e:
            print(f"  ERROR {prefix} — {e}")
            continue

        is_decision = extraction.candidate_type == "decision"

        if item["expected_viable"]:
            if is_decision:
                results["good_kept"].append(item)
                print(f"  OK   {prefix} [good→kept] | {item['decision_text'][:50]}")
            else:
                results["good_rejected"].append(item)
                ct = extraction.candidate_type or "null"
                print(f"  REGR {prefix} [good→{ct}] | {item['decision_text'][:50]}")
        else:
            if is_decision:
                results["bad_kept"].append(item)
                print(f"  MISS {prefix} [bad→kept] | {item['decision_text'][:50]}")
            else:
                results["bad_rejected"].append(item)
                ct = extraction.candidate_type or "null"
                print(f"  FIX  {prefix} [bad→{ct}] | {item['decision_text'][:50]}")

    print()
    print("=" * 60)
    print("RESULTS")
    print("=" * 60)
    total_good = len(results["good_kept"]) + len(results["good_rejected"])
    total_bad = len(results["bad_kept"]) + len(results["bad_rejected"])
    print(f"  Good items kept (no regression): {len(results['good_kept'])}/{total_good}")
    print(f"  Good items rejected (REGRESSION): {len(results['good_rejected'])}/{total_good}")
    print(f"  Bad items rejected (FIXED): {len(results['bad_rejected'])}/{total_bad}")
    print(f"  Bad items kept (still wrong): {len(results['bad_kept'])}/{total_bad}")
    print()

    if results["good_rejected"]:
        print("  REGRESSIONS (good items now rejected):")
        for item in results["good_rejected"]:
            print(f"    - {item['id']} | {item['decision_text'][:60]}")
        print()

    if results["bad_kept"]:
        print("  REMAINING BAD (still classified as decision):")
        for item in results["bad_kept"]:
            print(f"    - {item['id']} | {item['decision_text'][:60]}")
        print()

    regression_rate = len(results["good_rejected"]) / total_good * 100 if total_good else 0
    fix_rate = len(results["bad_rejected"]) / total_bad * 100 if total_bad else 0
    print(f"  Fix rate: {fix_rate:.1f}% of bad items now correctly rejected")
    print(f"  Regression rate: {regression_rate:.1f}% of good items incorrectly rejected")
    print()
    print(f"  VERDICT: {'PASS' if not results['good_rejected'] else 'FAIL — regressions detected'}")


if __name__ == "__main__":
    main()
