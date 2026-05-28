"""Inspect the atomic_fact cos>=0.95 cluster.

For atomic_fact memories at max_cos >= 0.95 (pool_all, same-type same-container),
compute:
  - count of pairs whose embedding text_view is bit-identical
  - count of pairs whose payload_json is bit-identical (excluding mid/created_at)
  - count of pairs whose `statement` field is bit-identical
  - 20 random samples (mid, neighbor_mid, max_cos, payload excerpts)

Read-only. No LLM calls. Writes only under .local/.

Usage:
    .venv/Scripts/python.exe -m evals.write_gate_replay.atomic_fact_cluster_inspect \\
        --out .local/research/_atomic_fact_cluster_samples.md
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from evals.write_gate_replay.replay import (
    _TEXT_VIEW_RANK,
    _safe_outpath,
    attach_vectors,
    compute_gates,
    load_memories,
)


def _normalize_payload_for_compare(p: dict) -> str:
    """Drop volatile fields so we compare semantic content, not extraction timestamps."""
    if not isinstance(p, dict):
        return json.dumps(p, sort_keys=True, ensure_ascii=False)
    drop = {"extraction_watermark", "created_at", "freshness_at", "id"}
    cleaned = {k: v for k, v in p.items() if k not in drop}
    return json.dumps(cleaned, sort_keys=True, ensure_ascii=False)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--db",
        default=str(Path.home() / ".pallium" / "data" / "pallium.db"),
    )
    ap.add_argument(
        "--vector-index",
        default=str(Path.home() / ".pallium" / "data"),
    )
    ap.add_argument("--threshold", type=float, default=0.95)
    ap.add_argument("--n-samples", type=int, default=20)
    ap.add_argument("--seed", type=int, default=20260528)
    ap.add_argument(
        "--out",
        default=".local/research/_atomic_fact_cluster_samples.md",
    )
    args = ap.parse_args()

    out_path = _safe_outpath(Path(args.out))
    out_path.parent.mkdir(parents=True, exist_ok=True)

    con_uri = f"file:{args.db}?mode=ro"
    con = sqlite3.connect(con_uri, uri=True)
    con.row_factory = sqlite3.Row

    print(f"Loading atomic_fact memory_objects from {args.db} ...")
    mems = load_memories(con, {"atomic_fact"})
    print(f"  loaded {len(mems)} memories")

    print("Attaching vectors ...")
    coverage = attach_vectors(con, mems, Path(args.vector_index))
    print(
        f"  with vector: {coverage['with_vector']}/{coverage['total']}  "
        f"(model={coverage['model']}, ndim={coverage['ndim']})"
    )

    print("Computing per-memory pool_all max_cos ...")
    _, all_results = compute_gates(mems, n_recent=20)

    # Cards in the threshold cluster.
    cluster = [
        r for r in all_results
        if r.has_vector and r.max_cos >= args.threshold
    ]
    print(
        f"Cards with max_cos >= {args.threshold:.2f}: {len(cluster)}"
    )

    # Pull payloads + chosen text_view for cluster mids and their nearest neighbors.
    needed_mids: set[str] = set()
    for r in cluster:
        needed_mids.add(r.mid)
        if r.nearest_mid:
            needed_mids.add(r.nearest_mid)

    payloads: dict[str, dict] = {}
    if needed_mids:
        placeholders = ",".join(["?"] * len(needed_mids))
        rows = con.execute(
            f"SELECT id, payload_json FROM memory_objects WHERE id IN ({placeholders})",
            tuple(needed_mids),
        ).fetchall()
        for r in rows:
            try:
                payloads[r["id"]] = json.loads(r["payload_json"]) or {}
            except (TypeError, json.JSONDecodeError):
                payloads[r["id"]] = {}

    # Also pull the chosen text_view for each mid (preferred entry).
    text_views: dict[str, str] = {}
    if needed_mids:
        ie_rows = con.execute(
            f"""
            SELECT target_id, text_view, text_view_name
            FROM index_entries
            WHERE index_type='vector' AND target_kind='memory_object'
              AND target_id IN ({placeholders})
            """,
            tuple(needed_mids),
        ).fetchall()
        # Pick the preferred entry per mid using the same rank as replay.py.
        best: dict[str, tuple[int, str]] = {}
        for r in ie_rows:
            mid = r["target_id"]
            rank = _TEXT_VIEW_RANK.get(r["text_view_name"] or "", 999)
            tv = r["text_view"] or ""
            cur = best.get(mid)
            if cur is None or rank < cur[0]:
                best[mid] = (rank, tv)
        text_views = {mid: tv for mid, (_, tv) in best.items()}

    con.close()

    # Bit-identical pair counts.
    bit_identical_text_view = 0
    bit_identical_payload = 0
    bit_identical_statement = 0
    pairs_with_text_view = 0
    pairs_with_payload = 0
    pairs_with_statement = 0
    for r in cluster:
        nbr = r.nearest_mid
        if not nbr or nbr == r.mid:
            continue
        # Text view.
        a_tv = text_views.get(r.mid)
        b_tv = text_views.get(nbr)
        if a_tv is not None and b_tv is not None:
            pairs_with_text_view += 1
            if a_tv == b_tv:
                bit_identical_text_view += 1
        # Payload (normalized).
        a_p = payloads.get(r.mid)
        b_p = payloads.get(nbr)
        if a_p is not None and b_p is not None:
            pairs_with_payload += 1
            if _normalize_payload_for_compare(a_p) == _normalize_payload_for_compare(b_p):
                bit_identical_payload += 1
        # statement field (atomic_fact-specific).
        if isinstance(a_p, dict) and isinstance(b_p, dict):
            sa = a_p.get("statement")
            sb = b_p.get("statement")
            if isinstance(sa, str) and isinstance(sb, str):
                pairs_with_statement += 1
                if sa.strip() == sb.strip():
                    bit_identical_statement += 1

    # Random sample of N pairs.
    rng = random.Random(args.seed)
    sample_pool = [r for r in cluster if r.nearest_mid]
    rng.shuffle(sample_pool)
    samples = sample_pool[: args.n_samples]

    # Build report.
    lines: list[str] = []
    lines.append("# atomic_fact cos>=%.2f cluster inspection" % args.threshold)
    lines.append("")
    lines.append(f"- DB: `{args.db}`")
    lines.append(f"- Embedding model: `{coverage['model']}` ({coverage['ndim']} dims)")
    lines.append(f"- atomic_fact total active: {len(mems)}")
    lines.append(f"- atomic_fact with vector: {coverage['with_vector']}")
    lines.append(f"- Cluster size (max_cos >= {args.threshold:.2f}, pool_all): {len(cluster)}")
    lines.append("")

    lines.append("## Bit-identical neighbor counts")
    lines.append("")
    lines.append(
        "For each cluster card, compare it to its nearest same-type same-container "
        "prior neighbor. A `bit_identical_text_view` pair has identical embedded "
        "text. A `bit_identical_payload` pair has identical payload after dropping "
        "extraction_watermark/created_at/freshness_at. A `bit_identical_statement` "
        "pair has identical `statement` strings."
    )
    lines.append("")
    lines.append("| signal | identical | total pairs | pct |")
    lines.append("|---|---:|---:|---:|")

    def _pct(a: int, b: int) -> str:
        return f"{(100.0 * a / b):.1f}%" if b else "n/a"

    lines.append(
        f"| text_view | {bit_identical_text_view} | {pairs_with_text_view} | "
        f"{_pct(bit_identical_text_view, pairs_with_text_view)} |"
    )
    lines.append(
        f"| payload (normalized) | {bit_identical_payload} | {pairs_with_payload} | "
        f"{_pct(bit_identical_payload, pairs_with_payload)} |"
    )
    lines.append(
        f"| statement field | {bit_identical_statement} | {pairs_with_statement} | "
        f"{_pct(bit_identical_statement, pairs_with_statement)} |"
    )
    lines.append("")

    # Sample pairs table.
    lines.append("## Random sample of pairs")
    lines.append("")
    lines.append(
        f"{len(samples)} random pairs from the cluster (seed={args.seed})."
    )
    lines.append("")
    for i, r in enumerate(samples, 1):
        a_p = payloads.get(r.mid, {})
        b_p = payloads.get(r.nearest_mid, {})
        a_stmt = (a_p.get("statement") or "")[:200] if isinstance(a_p, dict) else ""
        b_stmt = (b_p.get("statement") or "")[:200] if isinstance(b_p, dict) else ""
        a_subj = (a_p.get("subject") or r.subject or "")[:60] if isinstance(a_p, dict) else r.subject
        b_subj = (b_p.get("subject") or "")[:60] if isinstance(b_p, dict) else ""
        a_cat = a_p.get("category", "") if isinstance(a_p, dict) else ""
        b_cat = b_p.get("category", "") if isinstance(b_p, dict) else ""
        lines.append(f"### Pair {i}  (max_cos={r.max_cos:.4f})")
        lines.append("")
        lines.append(f"- A id: `{r.mid}`  subject=`{a_subj}`  category=`{a_cat}`")
        lines.append(f"  - statement: {a_stmt}")
        lines.append(f"- B id: `{r.nearest_mid}`  subject=`{b_subj}`  category=`{b_cat}`")
        lines.append(f"  - statement: {b_stmt}")
        lines.append("")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nReport written to {out_path}")
    print(
        f"\nBit-identical pairs (out of {len(cluster)} cluster cards):"
        f"\n  text_view:   {bit_identical_text_view}/{pairs_with_text_view}"
        f"\n  payload:     {bit_identical_payload}/{pairs_with_payload}"
        f"\n  statement:   {bit_identical_statement}/{pairs_with_statement}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
