"""Anchor probe: measure whether anchor-trim and embedding-based query inference
would reduce noise in injected memories on real rated data.

Pulls every rated case (relevant + not_relevant) from a chosen container in
the live DB, joins to the memory's envelope.subjects, and replays three
mechanisms against each case:

  Baseline   — token-overlap between query tokens and any anchor value's
               tokens, on the FULL anchor list (proxy for current 'aligned'
               classification).
  Trimmed-K  — same overlap, but anchors limited to the top-K most
               distinctive ones by mean-IDF over container anchor vocabulary.
  Embedding  — max cosine(embed(query), embed(anchor_value)) over all anchor
               values; threshold-gated.

For each mechanism we compute a 2x2 against the rating label:
  - True positive  : kept a relevant memory   (good — relevant survived)
  - False positive : kept a not_relevant one  (bad — noise survived)
  - True negative  : dropped a not_relevant   (good — noise filtered)
  - False negative : dropped a relevant one   (bad — useful filtered)

Run:
    python -m evals.anchor_probe \
        --db ~/.pallium/data/pallium.db \
        --container 'path:project:abc1234567' \
        --days 30
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# Ensure project root on path so imports work when invoked from anywhere.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.text import normalize_for_index  # type: ignore  # noqa: E402


def _tokens(value: str) -> list[str]:
    return [t for t in normalize_for_index(value).split() if t]


@dataclass
class RatedCase:
    feedback_id: str
    memory_id: str
    memory_type: str
    rating: str  # 'relevant' | 'not_relevant'
    query: str
    memory_text: str
    anchors: list[dict]  # list of {'kind': str, 'value': str}
    created_at: str


def load_cases(db_path: str, container_ref: str, days: int) -> list[RatedCase]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        f"""
        SELECT mf.id, mf.memory_object_id, mf.rating, mf.memory_type,
               mf.query_context, mf.memory_text, mf.created_at,
               mo.envelope_json
        FROM memory_feedback mf
        LEFT JOIN memory_objects mo ON mo.id = mf.memory_object_id
        WHERE mf.container_ref = ?
          AND mf.created_at > datetime('now', ?)
          AND mf.rating IN ('relevant', 'not_relevant')
        ORDER BY mf.created_at DESC
        """,
        (container_ref, f"-{days} days"),
    ).fetchall()
    con.close()
    out: list[RatedCase] = []
    for r in rows:
        env = json.loads(r["envelope_json"]) if r["envelope_json"] else {}
        anchors = env.get("subjects", []) or []
        # Defensive: filter empty
        anchors = [
            {"kind": str(a.get("kind") or ""), "value": str(a.get("value") or "").strip()}
            for a in anchors
            if isinstance(a, dict) and a.get("value")
        ]
        out.append(
            RatedCase(
                feedback_id=r["id"],
                memory_id=r["memory_object_id"],
                memory_type=r["memory_type"] or "",
                rating=r["rating"],
                query=r["query_context"] or "",
                memory_text=r["memory_text"] or "",
                anchors=anchors,
                created_at=r["created_at"],
            )
        )
    return out


# ---------- IDF over container anchor vocabulary ----------------------------


def compute_anchor_token_idf(db_path: str, container_ref: str) -> dict[str, float]:
    """Compute IDF per token over all anchor values seen in this container.

    Each memory_object's set of anchor-value tokens forms one 'document'.
    """
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT envelope_json FROM memory_objects
        WHERE container_ref = ? AND envelope_json IS NOT NULL
        """,
        (container_ref,),
    ).fetchall()
    con.close()

    df: Counter[str] = Counter()
    n_docs = 0
    for r in rows:
        env = json.loads(r["envelope_json"])
        anchors = env.get("subjects", []) or []
        if not anchors:
            continue
        token_set: set[str] = set()
        for a in anchors:
            for t in _tokens(str(a.get("value") or "")):
                token_set.add(t)
        if not token_set:
            continue
        n_docs += 1
        for t in token_set:
            df[t] += 1
    if n_docs == 0:
        return {}
    return {tok: math.log((n_docs + 1) / (cnt + 0.5)) for tok, cnt in df.items()}


def anchor_distinctiveness(value: str, idf: dict[str, float]) -> float:
    toks = _tokens(value)
    if not toks:
        return 0.0
    return sum(idf.get(t, 0.0) for t in toks) / len(toks)


def trimmed_anchors(anchors: list[dict], idf: dict[str, float], k: int) -> list[dict]:
    if len(anchors) <= k:
        return anchors
    scored = sorted(
        anchors,
        key=lambda a: anchor_distinctiveness(a["value"], idf),
        reverse=True,
    )
    return scored[:k]


# ---------- Mechanisms -------------------------------------------------------


def has_token_overlap(query: str, anchors: list[dict]) -> bool:
    q = set(_tokens(query))
    if not q:
        return False
    for a in anchors:
        a_toks = _tokens(a["value"])
        if any(t in q for t in a_toks):
            return True
    return False


def cosine(a: list[float], b: list[float]) -> float:
    s = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        s += x * y
        na += x * x
        nb += y * y
    if na == 0 or nb == 0:
        return 0.0
    return s / (math.sqrt(na) * math.sqrt(nb))


def max_embed_similarity(
    query_vec: list[float], anchor_vecs: list[list[float]]
) -> float:
    if not anchor_vecs:
        return 0.0
    return max(cosine(query_vec, v) for v in anchor_vecs)


def _build_onnx_provider_minimal():
    """Construct OnnxEmbeddingProvider directly with default model.

    Avoids depending on app.dependencies (which pulls in FastAPI etc).
    """
    from providers.embedding.onnx_provider import OnnxEmbeddingProvider  # type: ignore

    return OnnxEmbeddingProvider()


# ---------- Confusion matrix accumulation -----------------------------------


@dataclass
class ConfMatrix:
    name: str
    tp: int = 0  # kept a relevant
    fp: int = 0  # kept a not_relevant (noise)
    tn: int = 0  # dropped a not_relevant
    fn: int = 0  # dropped a relevant

    def add(self, kept: bool, label: str) -> None:
        if label == "relevant" and kept:
            self.tp += 1
        elif label == "relevant" and not kept:
            self.fn += 1
        elif label == "not_relevant" and kept:
            self.fp += 1
        else:
            self.tn += 1

    def report(self) -> str:
        total = self.tp + self.fp + self.tn + self.fn
        kept = self.tp + self.fp
        dropped = self.tn + self.fn
        precision = self.tp / kept if kept else 0.0  # of kept, fraction relevant
        recall = self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0
        noise_rate_kept = self.fp / kept if kept else 0.0
        return (
            f"{self.name:<32} "
            f"kept={kept:>3} (tp={self.tp:>3} fp={self.fp:>3})  "
            f"dropped={dropped:>3} (tn={self.tn:>3} fn={self.fn:>3})  "
            f"P={precision:.2f} R={recall:.2f} noise_in_kept={noise_rate_kept:.2f}"
            f"  n={total}"
        )


# ---------- Main -------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        default=str(Path.home() / ".pallium" / "data" / "pallium.db"),
        help="Path to live Pallium SQLite DB",
    )
    parser.add_argument(
        "--container",
        required=True,
        help="container_ref to analyze (e.g. 'path:project:abc1234567')",
    )
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument(
        "--top-ks",
        default="3,5,7",
        help="Comma-separated K values for anchor trimming",
    )
    parser.add_argument(
        "--embed-thresholds",
        default="0.50,0.60,0.70,0.80",
        help="Comma-separated cosine thresholds for embedding mechanism",
    )
    parser.add_argument(
        "--no-embed",
        action="store_true",
        help="Skip the embedding-based mechanism (faster, text-only)",
    )
    parser.add_argument(
        "--out-json",
        default="",
        help="Optional path to write per-case JSON output",
    )
    args = parser.parse_args()

    print(f"# Anchor probe — {args.container}  (last {args.days}d)\n")

    cases = load_cases(args.db, args.container, args.days)
    if not cases:
        print("No rated cases found in window.")
        return 1
    rel = sum(1 for c in cases if c.rating == "relevant")
    nr = sum(1 for c in cases if c.rating == "not_relevant")
    print(f"Loaded {len(cases)} rated cases  (relevant={rel}, not_relevant={nr})\n")

    # IDF over anchor token vocabulary in this container.
    print("Computing anchor-token IDF over container memory vocabulary ...")
    idf = compute_anchor_token_idf(args.db, args.container)
    print(f"  vocabulary size: {len(idf)} tokens\n")

    # Anchor-count distribution sanity.
    counts = [len(c.anchors) for c in cases]
    if counts:
        print(
            f"Anchor count per memory  min={min(counts)} max={max(counts)} "
            f"mean={sum(counts)/len(counts):.1f}\n"
        )

    # Optional embedding setup.
    query_vecs: dict[str, list[float]] = {}
    anchor_vecs: dict[str, list[float]] = {}  # key: kind|value normalized
    if not args.no_embed:
        try:
            from providers.embedding.onnx_provider import (  # type: ignore # noqa: F401
                OnnxEmbeddingProvider,
            )
        except Exception as e:
            print(f"WARN: embedding setup failed at import time: {e}")
            args.no_embed = True

    if not args.no_embed:
        try:
            ep = _build_onnx_provider_minimal()
            unique_queries = sorted({c.query for c in cases if c.query})
            unique_anchor_values = sorted(
                {a["value"] for c in cases for a in c.anchors}
            )
            print(
                f"  embedding {len(unique_queries)} unique queries, "
                f"{len(unique_anchor_values)} unique anchor values ..."
            )
            qv = ep.embed(unique_queries, mode="query") if unique_queries else []
            av = (
                ep.embed(unique_anchor_values, mode="passage")
                if unique_anchor_values
                else []
            )
            for q, v in zip(unique_queries, qv):
                query_vecs[q] = v
            for a, v in zip(unique_anchor_values, av):
                anchor_vecs[a] = v
        except Exception as e:
            print(f"WARN: embedding run failed: {e}")
            args.no_embed = True

    # Mechanisms.
    cms: list[ConfMatrix] = []

    baseline = ConfMatrix("baseline (full anchor overlap)")
    cms.append(baseline)

    top_ks = [int(x) for x in args.top_ks.split(",") if x.strip()]
    trimmed_cms: dict[int, ConfMatrix] = {
        k: ConfMatrix(f"trimmed-K={k} (top-K by IDF)") for k in top_ks
    }
    for cm in trimmed_cms.values():
        cms.append(cm)

    embed_thresholds: list[float] = []
    embed_full_cms: dict[float, ConfMatrix] = {}
    embed_trim_cms: dict[float, ConfMatrix] = {}
    if not args.no_embed:
        embed_thresholds = [float(x) for x in args.embed_thresholds.split(",") if x.strip()]
        for t in embed_thresholds:
            embed_full_cms[t] = ConfMatrix(f"embed full   thr={t:.2f}")
            embed_trim_cms[t] = ConfMatrix(f"embed top-3  thr={t:.2f}")
        cms.extend(embed_full_cms.values())
        cms.extend(embed_trim_cms.values())

    per_case: list[dict] = []
    for c in cases:
        # Baseline: any token overlap on full anchor list.
        kept_baseline = has_token_overlap(c.query, c.anchors)
        baseline.add(kept_baseline, c.rating)

        # Trimmed-K mechanism.
        trim_decisions: dict[int, bool] = {}
        for k in top_ks:
            trimmed = trimmed_anchors(c.anchors, idf, k)
            kept = has_token_overlap(c.query, trimmed)
            trim_decisions[k] = kept
            trimmed_cms[k].add(kept, c.rating)

        # Embedding mechanism: compute once per case.
        embed_full_decisions: dict[float, bool] = {}
        embed_trim_decisions: dict[float, bool] = {}
        max_sim_full = None
        max_sim_trim3 = None
        if not args.no_embed and c.query in query_vecs:
            qv = query_vecs[c.query]
            full_anchor_vecs = [
                anchor_vecs[a["value"]] for a in c.anchors if a["value"] in anchor_vecs
            ]
            trim3 = trimmed_anchors(c.anchors, idf, 3)
            trim_anchor_vecs = [
                anchor_vecs[a["value"]] for a in trim3 if a["value"] in anchor_vecs
            ]
            max_sim_full = max_embed_similarity(qv, full_anchor_vecs)
            max_sim_trim3 = max_embed_similarity(qv, trim_anchor_vecs)
            for t in embed_thresholds:
                kept_f = max_sim_full >= t
                kept_t = max_sim_trim3 >= t
                embed_full_decisions[t] = kept_f
                embed_trim_decisions[t] = kept_t
                embed_full_cms[t].add(kept_f, c.rating)
                embed_trim_cms[t].add(kept_t, c.rating)

        per_case.append(
            {
                "id": c.feedback_id,
                "rating": c.rating,
                "type": c.memory_type,
                "query": c.query[:160],
                "memory": c.memory_text[:160],
                "n_anchors": len(c.anchors),
                "kept_baseline": kept_baseline,
                "trimmed": trim_decisions,
                "max_sim_full": max_sim_full,
                "max_sim_trim3": max_sim_trim3,
                "embed_full": embed_full_decisions,
                "embed_trim3": embed_trim_decisions,
            }
        )

    print("\n## Confusion matrices\n")
    print("(kept = mechanism would let this memory survive into injection)")
    print("(P = precision-of-kept; R = recall of relevant; noise_in_kept = FP/kept)\n")
    for cm in cms:
        print(cm.report())

    # Print per-case decisions for the mechanisms most likely to be useful.
    print("\n## Per-case detail (sorted by rating, then anchor count)\n")
    per_case_sorted = sorted(
        per_case, key=lambda x: (x["rating"], -x["n_anchors"])
    )
    header = (
        f"{'rat':<13} {'type':<22} {'#anc':>4}  "
        f"{'base':>4} {'k=3':>4} {'k=5':>4} "
        f"{'simF':>5} {'simT3':>6}  query"
    )
    print(header)
    for x in per_case_sorted:
        sim_f = f"{x['max_sim_full']:.2f}" if x["max_sim_full"] is not None else "  - "
        sim_t = f"{x['max_sim_trim3']:.2f}" if x["max_sim_trim3"] is not None else "  -  "
        line = (
            f"{x['rating']:<13} "
            f"{x['type'][:22]:<22} "
            f"{x['n_anchors']:>4}  "
            f"{('Y' if x['kept_baseline'] else 'n'):>4} "
            f"{('Y' if x['trimmed'].get(3, False) else 'n'):>4} "
            f"{('Y' if x['trimmed'].get(5, False) else 'n'):>4} "
            f"{sim_f:>5} {sim_t:>6}  "
            f"{x['query'][:80]}"
        )
        # ASCII-safe printing on Windows: replace anything that won't encode.
        try:
            print(line)
        except UnicodeEncodeError:
            print(line.encode("ascii", "replace").decode("ascii"))

    if args.out_json:
        Path(args.out_json).write_text(
            json.dumps(per_case, indent=2, default=str), encoding="utf-8"
        )
        print(f"\nWrote {args.out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
