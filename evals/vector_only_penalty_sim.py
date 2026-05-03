"""Simulate Direction A (lexical floor penalty) and Direction B (vector-only block).

Uses stored audit log data — no live queries needed. For each query that has
feedback-rated injections, simulates what would change under each variant:
- Which false positives get removed
- Which true positives get lost

Run: python -m evals.vector_only_penalty_sim
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


DB_PATH = Path.home() / ".pallium" / "data" / "pallium.db"


@dataclass
class Variant:
    name: str
    description: str

    def would_inject(self, candidate: dict) -> bool:
        raise NotImplementedError


class Baseline(Variant):
    """Current behavior: inject everything the pipeline injected."""

    def would_inject(self, candidate: dict) -> bool:
        return bool(candidate.get("injected"))


class DirectionA(Variant):
    """Lexical floor penalty: require BM25 >= threshold for 'both' candidates."""

    def __init__(self, bm25_floor: float):
        self.bm25_floor = bm25_floor
        super().__init__(
            name=f"A_lex>={int(bm25_floor)}",
            description=f"Block injected items with lexical_score < {bm25_floor} (when lexical exists)",
        )

    def would_inject(self, candidate: dict) -> bool:
        if not candidate.get("injected"):
            return False
        lex = candidate.get("lexical_score")
        if lex is None:
            return True  # vector-only: pass through (Direction A only targets has-lexical)
        return lex >= self.bm25_floor


class DirectionAStrict(Variant):
    """Lexical floor penalty applied to ALL candidates (including vector-only)."""

    def __init__(self, bm25_floor: float):
        self.bm25_floor = bm25_floor
        super().__init__(
            name=f"A_strict_lex>={int(bm25_floor)}",
            description=f"Block injected items without lexical_score >= {bm25_floor} (blocks vector-only too)",
        )

    def would_inject(self, candidate: dict) -> bool:
        if not candidate.get("injected"):
            return False
        lex = candidate.get("lexical_score")
        if lex is None:
            return False  # No lexical at all -> blocked
        return lex >= self.bm25_floor


class DirectionB(Variant):
    """Block vector-only injection entirely."""

    def __init__(self):
        super().__init__(
            name="B_block_vec_only",
            description="Block all vector-only candidates (require any lexical match)",
        )

    def would_inject(self, candidate: dict) -> bool:
        if not candidate.get("injected"):
            return False
        lex = candidate.get("lexical_score")
        return lex is not None


class DirectionBSoftVecFloor(Variant):
    """Allow vector-only only if vector >= high threshold."""

    def __init__(self, vec_floor: int):
        self.vec_floor = vec_floor
        super().__init__(
            name=f"B_soft_vec>={vec_floor}",
            description=f"Block vector-only unless vector_score >= {vec_floor}",
        )

    def would_inject(self, candidate: dict) -> bool:
        if not candidate.get("injected"):
            return False
        lex = candidate.get("lexical_score")
        vec = candidate.get("vector_score")
        if lex is not None:
            return True  # has lexical -> pass
        if vec is not None and vec >= self.vec_floor:
            return True
        return False


@dataclass
class QueryResult:
    query_text: str
    baseline_tp: list[dict]
    baseline_fp: list[dict]
    variant_tp: list[dict]
    variant_fp: list[dict]
    lost_tp: list[dict]   # relevant items that variant drops
    removed_fp: list[dict]  # irrelevant items that variant drops


def load_data():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    feedback_idx: dict[str, str] = {}
    memory_text_idx: dict[str, str] = {}
    for row in conn.execute("SELECT memory_object_id, rating, memory_text FROM memory_feedback"):
        feedback_idx[row["memory_object_id"]] = row["rating"]
        if row["memory_text"]:
            memory_text_idx[row["memory_object_id"]] = row["memory_text"]

    # Also get text from memory_objects for items missing feedback text
    for row in conn.execute("SELECT id, payload_json FROM memory_objects WHERE payload_json IS NOT NULL"):
        if row["id"] not in memory_text_idx:
            try:
                payload = json.loads(row["payload_json"])
                text = payload.get("text") or payload.get("summary") or payload.get("title", "")
                if text:
                    memory_text_idx[row["id"]] = text[:120]
            except (json.JSONDecodeError, TypeError):
                pass

    queries = []
    for row in conn.execute(
        "SELECT query_text, candidate_scores_json FROM query_audit_log "
        "WHERE candidate_scores_json IS NOT NULL AND query_text IS NOT NULL"
    ):
        candidates = json.loads(row["candidate_scores_json"])
        rated_candidates = []
        for c in candidates:
            mo_id = c.get("memory_object_id")
            if mo_id and mo_id in feedback_idx:
                c["_rating"] = feedback_idx[mo_id]
                c["_text"] = memory_text_idx.get(mo_id, "(no text)")[:100]
                rated_candidates.append(c)
        if rated_candidates:
            queries.append((row["query_text"], rated_candidates))

    conn.close()
    return queries


def simulate(queries: list, variant: Variant) -> dict:
    total_tp = 0
    total_fp = 0
    lost_tp = 0
    removed_fp = 0
    lost_tp_examples = []
    removed_fp_examples = []

    for query_text, candidates in queries:
        for c in candidates:
            was_injected = bool(c.get("injected"))
            would_inject = variant.would_inject(c)
            is_relevant = c["_rating"] == "relevant"

            if was_injected and is_relevant:
                total_tp += 1
            if was_injected and not is_relevant:
                total_fp += 1

            # Lost TP: was injected + relevant, but variant would not inject
            if was_injected and is_relevant and not would_inject:
                lost_tp += 1
                if len(lost_tp_examples) < 15:
                    lost_tp_examples.append({
                        "query": query_text[:70],
                        "type": c.get("memory_type"),
                        "text": c["_text"],
                        "lex": c.get("lexical_score"),
                        "vec": c.get("vector_score"),
                    })

            # Removed FP: was injected + not_relevant, and variant would not inject
            if was_injected and not is_relevant and not would_inject:
                removed_fp += 1
                if len(removed_fp_examples) < 10:
                    removed_fp_examples.append({
                        "query": query_text[:70],
                        "type": c.get("memory_type"),
                        "text": c["_text"],
                        "lex": c.get("lexical_score"),
                        "vec": c.get("vector_score"),
                    })

    new_tp = total_tp - lost_tp
    new_fp = total_fp - removed_fp
    new_total = new_tp + new_fp
    baseline_total = total_tp + total_fp

    return {
        "variant": variant.name,
        "description": variant.description,
        "baseline_precision": total_tp / baseline_total * 100 if baseline_total else 0,
        "new_precision": new_tp / new_total * 100 if new_total else 0,
        "baseline_recall": total_tp,
        "new_recall": new_tp,
        "recall_loss": lost_tp,
        "recall_loss_pct": lost_tp / total_tp * 100 if total_tp else 0,
        "fp_removed": removed_fp,
        "fp_removed_pct": removed_fp / total_fp * 100 if total_fp else 0,
        "total_injections_removed": lost_tp + removed_fp,
        "lost_tp_examples": lost_tp_examples,
        "removed_fp_examples": removed_fp_examples,
    }


def main():
    queries = load_data()
    print(f"Loaded {len(queries)} queries with feedback-rated injections\n")

    variants = [
        Baseline(name="baseline", description="Current behavior"),
        DirectionA(bm25_floor=10),
        DirectionA(bm25_floor=12),
        DirectionA(bm25_floor=15),
        DirectionB(),
        DirectionBSoftVecFloor(vec_floor=920),
        DirectionBSoftVecFloor(vec_floor=940),
        DirectionAStrict(bm25_floor=8),
        DirectionAStrict(bm25_floor=10),
        DirectionAStrict(bm25_floor=12),
    ]

    results = []
    for v in variants:
        r = simulate(queries, v)
        results.append(r)

    # Summary table
    print(f"{'Variant':<22} {'Precision':<12} {'Recall':<10} {'FP removed':<14} {'TP lost':<10} {'Net':<8}")
    print("-" * 76)
    for r in results:
        prec = f"{r['new_precision']:.1f}%"
        recall_loss = f"-{r['recall_loss']} ({r['recall_loss_pct']:.0f}%)" if r["recall_loss"] else "0"
        fp_rem = f"-{r['fp_removed']} ({r['fp_removed_pct']:.0f}%)" if r["fp_removed"] else "0"
        net = r["fp_removed"] - r["recall_loss"]
        print(f"{r['variant']:<22} {prec:<12} {recall_loss:<10} {fp_rem:<14} {r['recall_loss']:<10} +{net}")

    # Show examples for the most interesting variants
    interesting = [r for r in results if r["variant"] in ("A_lex>=12", "B_block_vec_only", "A_strict_lex>=10")]
    for r in interesting:
        print(f"\n{'='*76}")
        print(f"VARIANT: {r['variant']} — {r['description']}")
        print(f"  Precision: {r['baseline_precision']:.1f}% -> {r['new_precision']:.1f}%")
        print(f"  FP removed: {r['fp_removed']}, TP lost: {r['recall_loss']}")

        if r["lost_tp_examples"]:
            print(f"\n  RELEVANT MEMORIES THAT WOULD BE LOST ({r['recall_loss']} total):")
            for ex in r["lost_tp_examples"]:
                src = f"lex={ex['lex']}" if ex["lex"] is not None else f"vec={ex['vec']}"
                print(f"    [{ex['type']}] {src}")
                print(f"      query: {ex['query']}")
                print(f"      memory: {ex['text']}")

        if r["removed_fp_examples"]:
            print(f"\n  FALSE POSITIVES THAT WOULD BE REMOVED ({r['fp_removed']} total, showing 10):")
            for ex in r["removed_fp_examples"]:
                src = f"lex={ex['lex']}" if ex["lex"] is not None else f"vec={ex['vec']}"
                print(f"    [{ex['type']}] {src}")
                print(f"      query: {ex['query']}")
                print(f"      memory: {ex['text']}")


if __name__ == "__main__":
    main()
