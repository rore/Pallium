"""Memory quality dimension scorer.

Scores extraction quality across dimensions:
1. noise_suppression: % of expected_suppress items that produce NO memory
2. false_negative_protection: % of must_not_suppress items that DO produce memory
3. turn_summary_quality: % of discussion_summaries with substantive content
4. decision_detection: % of source items with decision language that produce decision memories
5. type_distribution: informational breakdown of memory types produced
"""
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

DB_PATH = Path.home() / ".pallium" / "data" / "pallium.db"
CORPUS_PATH = Path(__file__).parent / "memory_quality_corpus.jsonl"


@dataclass
class Dimension:
    name: str
    passed: int = 0
    total: int = 0
    failures: list = field(default_factory=list)

    @property
    def score(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def grade(self) -> str:
        s = self.score
        if s >= 0.9:
            return "A"
        if s >= 0.8:
            return "B+"
        if s >= 0.7:
            return "B"
        if s >= 0.6:
            return "C"
        if s >= 0.5:
            return "D"
        return "F"


def main():
    if not CORPUS_PATH.exists():
        print(f"Corpus not found at {CORPUS_PATH}. Run export_quality_corpus.py first.")
        return

    corpus = [json.loads(line) for line in open(CORPUS_PATH, encoding="utf-8") if line.strip()]

    if not DB_PATH.exists():
        print(f"DB not found at {DB_PATH}")
        return

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    cur.execute("""
        SELECT r.to_id, m.type, m.payload_json
        FROM relations r JOIN memory_objects m ON m.id = r.from_id
        WHERE r.relation_type='supported_by' AND r.from_kind='memory_object'
          AND r.to_kind='source_item' AND m.lifecycle='active'
    """)
    memories_by_source: dict[str, list[dict]] = {}
    for row in cur.fetchall():
        memories_by_source.setdefault(row[0], []).append({
            "type": row[1],
            "payload": json.loads(row[2]),
        })

    dims: dict[str, Dimension] = {}

    # 1. Noise suppression
    d = Dimension("noise_suppression")
    for item in corpus:
        if item.get("expected_suppress"):
            d.total += 1
            if not memories_by_source.get(item["source_item_id"]):
                d.passed += 1
            else:
                d.failures.append(item["content"][:80])
    dims["noise_suppression"] = d

    # 2. False negative protection
    d = Dimension("false_negative_protection")
    for item in corpus:
        if item.get("must_not_suppress"):
            d.total += 1
            if memories_by_source.get(item["source_item_id"]):
                d.passed += 1
            else:
                d.failures.append(item["content"][:80])
    dims["false_negative_protection"] = d

    # 3. Discussion summary quality
    d = Dimension("turn_summary_quality")
    for mems in memories_by_source.values():
        for m in mems:
            if m["type"] == "turn_summary":
                d.total += 1
                summary = m["payload"].get("summary", "")
                if len(summary) >= 50:
                    d.passed += 1
                else:
                    d.failures.append(summary[:80])
    dims["turn_summary_quality"] = d

    # 4. Decision detection (items that contain decision language → should have decision type)
    d = Dimension("decision_detection")
    decision_markers = ["decision:", "we decided", "we chose", "chosen approach", "switched to", "implemented"]
    for item in corpus:
        content_lower = item["content"].lower()
        if any(m in content_lower for m in decision_markers):
            d.total += 1
            mems = memories_by_source.get(item["source_item_id"], [])
            if any(m["type"] == "decision" for m in mems):
                d.passed += 1
            else:
                d.failures.append(item["content"][:80])
    dims["decision_detection"] = d

    # Type distribution (informational)
    type_counts: dict[str, int] = {}
    for mems in memories_by_source.values():
        for m in mems:
            type_counts[m["type"]] = type_counts.get(m["type"], 0) + 1

    conn.close()

    print("\nMemory Quality Report")
    print("=" * 60)
    for name, dim in dims.items():
        print(f"  {name:35s} {dim.score:5.1%} ({dim.passed}/{dim.total}) -> {dim.grade}")
        if dim.failures and dim.score < 0.9:
            print(f"    Sample failures:")
            for f in dim.failures[:3]:
                print(f"      - {f}")

    print(f"\nType Distribution ({sum(type_counts.values())} total memories):")
    for t, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {t:30s} {count:4d}")

    print(f"\nCorpus: {len(corpus)} source items")
    print(f"With memories: {len(memories_by_source)} items -> memories")


if __name__ == "__main__":
    main()
