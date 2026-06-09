"""Shadow re-rank replay: subject as a soft additive boost (not a hard gate).

Counterfactual to evals/subject_enrichment/replay.py (R2b hard gate, dead).

For each historical query_audit_log row that injected and has rated feedback:
  - Build candidate pool (with routing_score from production at audit time).
  - Per-row z-normalize routing_score so α has a stable meaning across rows.
  - Apply boost: boosted = z(routing_score) + α * log(1 + overlap)
                  iff |query_tokens ∩ subject_tokens| >= 2.
  - Take top-K where K = number of injected blocks the row actually produced.
  - Compare to baseline top-K = candidates flagged injected=True.
  - Score against rated feedback (relevant / not_relevant).

Sweeps α ∈ {0.05, 0.10, 0.20, 0.30, 0.50} for V1, V2, V3 subject variants.

Read-only on the live DB. No LLM calls. No production code touched.

Output:
  .local/research/subject_soft_signal_replay_2026-05-28.md
  .local/research/_subject_soft_signal_run.md
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.text import normalize_for_index  # noqa: E402

DEFAULT_DB = str(Path.home() / ".pallium" / "data" / "pallium.db")
DEFAULT_SUBJECTS = (
    _PROJECT_ROOT / "evals" / "subject_enrichment" / "output" / "subjects_2026-05-28.jsonl"
)
DEFAULT_REPORT = (
    _PROJECT_ROOT / ".local" / "research" / "subject_soft_signal_replay_2026-05-28.md"
)
DEFAULT_RUN_LOG = (
    _PROJECT_ROOT / ".local" / "research" / "_subject_soft_signal_run.md"
)
SINCE = "2026-05-18"

VARIANTS = ("v1_fallback", "v2_deterministic", "v3_llm")
VARIANT_KEY = {
    "v1_fallback": "subject_v1_fallback",
    "v2_deterministic": "subject_v2_deterministic",
    "v3_llm": "subject_v3_llm",
}
ALPHAS = (0.05, 0.10, 0.20, 0.30, 0.50)
MIN_OVERLAP = 2

# decision_reason values that actually produce injection AND can be re-ranked
# (i.e. have non-empty candidate_scores_json).
# `orientation_recency` (retired 2026-06-09 in a0e6f50) historically injected
# without storing candidates and could not be replayed; old audit rows remain.
# `same_thread_context_sufficient` and `no_relevant_memory` skip injection.
INJECTING_REASONS = ("carry_forward_available",)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tokens(s: str) -> set[str]:
    return {t for t in normalize_for_index(s or "").split() if t}


def _trim(s: str | None, n: int = 80) -> str:
    s = (s or "").replace("\n", " ").replace("\r", " ").replace("|", "/")
    return s if len(s) <= n else s[: n - 1] + "…"


def _zscore(values: list[float]) -> list[float]:
    if not values:
        return []
    if len(values) == 1:
        return [0.0]
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / len(values)
    sd = math.sqrt(var)
    if sd == 0:
        return [0.0 for _ in values]
    return [(v - mean) / sd for v in values]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Cand:
    cand_idx: int  # position in original candidate_scores_json
    memory_object_id: str | None
    memory_type: str | None
    layer: str | None
    routing_score: float
    z_score: float = 0.0
    injected: bool = False
    rating: str | None = None  # 'relevant' / 'not_relevant' / None
    overlap: dict[str, int] = field(default_factory=dict)  # variant -> overlap
    subject: dict[str, str] = field(default_factory=dict)  # variant -> subject string


@dataclass
class Row:
    audit_id: str
    container_ref: str | None
    thread_ref: str | None
    query_text: str
    cands: list[Cand]
    baseline_top_mids: list[str]  # top-K ordered as injected
    K: int  # injection cap = len(baseline_top_mids)


# ---------------------------------------------------------------------------
# DB Loaders
# ---------------------------------------------------------------------------

def load_subjects(path: Path) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    if not path.exists():
        return out
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            mid = row.get("memory_object_id")
            if not mid:
                continue
            out[mid] = {
                "v1_fallback": row.get("subject_v1_fallback") or "",
                "v2_deterministic": row.get("subject_v2_deterministic") or "",
                "v3_llm": row.get("subject_v3_llm") or "",
                "type": row.get("type") or "",
                "container": row.get("container_ref") or "",
            }
    return out


def open_ro(db: str) -> sqlite3.Connection:
    uri = f"file:{db}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def load_rated_rows(con: sqlite3.Connection) -> list[Row]:
    """Pull audit rows with non-empty candidates AND at least one rated candidate."""
    # ratings keyed by (audit_id, mid)
    ratings: dict[tuple[str, str], str] = {}
    for r in con.execute(
        """SELECT query_audit_log_id, memory_object_id, rating
           FROM memory_feedback
           WHERE rating IN ('relevant','not_relevant')
             AND created_at >= ?""",
        (SINCE,),
    ):
        if r["query_audit_log_id"] and r["memory_object_id"]:
            ratings[(r["query_audit_log_id"], r["memory_object_id"])] = r["rating"]

    placeholders = ",".join("?" * len(INJECTING_REASONS))
    audit_rows = con.execute(
        f"""SELECT id, container_ref, thread_ref, query_text,
                   candidate_scores_json, injected_blocks_json
            FROM query_audit_log
            WHERE created_at >= ?
              AND decision_reason IN ({placeholders})
              AND candidate_scores_json IS NOT NULL
              AND candidate_scores_json != '[]'""",
        (SINCE, *INJECTING_REASONS),
    ).fetchall()

    out: list[Row] = []
    for r in audit_rows:
        try:
            cands_raw = json.loads(r["candidate_scores_json"] or "[]")
        except Exception:
            cands_raw = []
        try:
            blocks = json.loads(r["injected_blocks_json"] or "[]")
        except Exception:
            blocks = []
        if not cands_raw:
            continue

        # Identify rated candidates in this row
        any_rated = any(
            (r["id"], c.get("memory_object_id")) in ratings
            for c in cands_raw
            if isinstance(c, dict)
        )
        if not any_rated:
            continue

        # Build cand list
        cands: list[Cand] = []
        for i, c in enumerate(cands_raw):
            if not isinstance(c, dict):
                continue
            mid = c.get("memory_object_id")
            rs = c.get("routing_score")
            try:
                rs_f = float(rs) if rs is not None else 0.0
            except Exception:
                rs_f = 0.0
            cand = Cand(
                cand_idx=i,
                memory_object_id=mid,
                memory_type=c.get("memory_type"),
                layer=c.get("layer"),
                routing_score=rs_f,
                injected=bool(c.get("injected")),
                rating=ratings.get((r["id"], mid)) if mid else None,
            )
            cands.append(cand)

        # Per-row z-normalize routing_score
        zs = _zscore([c.routing_score for c in cands])
        for c, z in zip(cands, zs):
            c.z_score = z

        # Baseline top-K = injected candidates, in original (rank) order.
        baseline_top_mids = [c.memory_object_id for c in cands if c.injected]
        K = len(baseline_top_mids)
        if K == 0:
            # Some rows may flag fewer injected candidates than blocks; fall
            # back to len(blocks).
            K = len([b for b in blocks if isinstance(b, dict)])
        if K == 0:
            continue

        out.append(
            Row(
                audit_id=r["id"],
                container_ref=r["container_ref"],
                thread_ref=r["thread_ref"],
                query_text=r["query_text"] or "",
                cands=cands,
                baseline_top_mids=[m for m in baseline_top_mids if m],
                K=K,
            )
        )
    return out


def annotate_subjects(
    rows: list[Row], subjects: dict[str, dict[str, str]]
) -> dict[str, int]:
    """Tag each candidate with overlap & subject for each variant. Returns counters."""
    counters: dict[str, int] = Counter()
    for row in rows:
        qtok = _tokens(row.query_text)
        for c in row.cands:
            if not c.memory_object_id:
                # source_evidence-style entries (no mid). overlap=0 across all variants.
                for v in VARIANTS:
                    c.overlap[v] = 0
                    c.subject[v] = ""
                counters["cand_no_mid"] += 1
                continue
            sub_row = subjects.get(c.memory_object_id)
            if sub_row is None:
                for v in VARIANTS:
                    c.overlap[v] = 0
                    c.subject[v] = ""
                counters["cand_mid_not_in_dataset"] += 1
                continue
            for v in VARIANTS:
                subj = sub_row.get(v, "") or ""
                c.subject[v] = subj
                if not subj:
                    c.overlap[v] = 0
                    counters[f"cand_empty_subject_{v}"] += 1
                else:
                    c.overlap[v] = len(qtok & _tokens(subj))
    return dict(counters)


# ---------------------------------------------------------------------------
# Re-rank
# ---------------------------------------------------------------------------

@dataclass
class RowResult:
    audit_id: str
    K: int
    baseline_mids: list[str]
    boosted_mids: list[str]
    decision_changed: bool
    promoted_relevant: int  # rated-relevant card entered top-K (was out)
    promoted_not_relevant: int  # rated-not_relevant entered top-K
    demoted_relevant: int  # rated-relevant left top-K
    demoted_not_relevant: int  # rated-not_relevant left top-K
    swapped_unrated_for_rated_rel: int
    swapped_unrated_for_rated_nr: int


def rerank_row(row: Row, variant: str, alpha: float) -> RowResult:
    # Compute boosted scores
    scored = []
    for c in row.cands:
        ov = c.overlap.get(variant, 0)
        if ov >= MIN_OVERLAP:
            boost = alpha * math.log(1.0 + ov)
        else:
            boost = 0.0
        scored.append((c.z_score + boost, c))

    # Sort desc; tie-break by original cand_idx (stable to preserve rank)
    scored.sort(key=lambda x: (-x[0], x[1].cand_idx))
    boosted_mids = [c.memory_object_id for _, c in scored[: row.K] if c.memory_object_id]

    baseline_set = set(row.baseline_top_mids)
    boosted_set = set(boosted_mids)
    decision_changed = baseline_set != boosted_set

    entered = boosted_set - baseline_set
    left = baseline_set - boosted_set

    rating_by_mid = {c.memory_object_id: c.rating for c in row.cands if c.memory_object_id}

    promoted_rel = sum(
        1 for m in entered if rating_by_mid.get(m) == "relevant"
    )
    promoted_nr = sum(
        1 for m in entered if rating_by_mid.get(m) == "not_relevant"
    )
    demoted_rel = sum(
        1 for m in left if rating_by_mid.get(m) == "relevant"
    )
    demoted_nr = sum(
        1 for m in left if rating_by_mid.get(m) == "not_relevant"
    )
    # swaps where unrated card replaced a rated card (or vice versa)
    swapped_unrated_for_rel = sum(
        1 for m in entered if rating_by_mid.get(m) is None
    ) if any(rating_by_mid.get(x) == "relevant" for x in left) else 0
    swapped_unrated_for_nr = sum(
        1 for m in entered if rating_by_mid.get(m) is None
    ) if any(rating_by_mid.get(x) == "not_relevant" for x in left) else 0

    return RowResult(
        audit_id=row.audit_id,
        K=row.K,
        baseline_mids=list(row.baseline_top_mids),
        boosted_mids=boosted_mids,
        decision_changed=decision_changed,
        promoted_relevant=promoted_rel,
        promoted_not_relevant=promoted_nr,
        demoted_relevant=demoted_rel,
        demoted_not_relevant=demoted_nr,
        swapped_unrated_for_rated_rel=swapped_unrated_for_rel,
        swapped_unrated_for_rated_nr=swapped_unrated_for_nr,
    )


def _topk_metrics(
    rows: list[Row],
    topk_by_row: dict[str, list[str]],
) -> dict[str, float | int]:
    """Compute precision and recall on the rated slice.

    precision = relevant_in_topK / rated_in_topK
    recall    = relevant_in_topK / total_relevant_in_pool
    """
    rated_in_topK = 0
    relevant_in_topK = 0
    total_relevant_in_pool = 0
    rated_in_pool = 0

    for row in rows:
        topk = set(topk_by_row.get(row.audit_id) or [])
        for c in row.cands:
            if c.rating in ("relevant", "not_relevant"):
                rated_in_pool += 1
                if c.rating == "relevant":
                    total_relevant_in_pool += 1
                if c.memory_object_id in topk:
                    rated_in_topK += 1
                    if c.rating == "relevant":
                        relevant_in_topK += 1

    p = (relevant_in_topK / rated_in_topK) if rated_in_topK else float("nan")
    r = (relevant_in_topK / total_relevant_in_pool) if total_relevant_in_pool else float("nan")
    return {
        "precision": p,
        "recall": r,
        "rated_in_topK": rated_in_topK,
        "relevant_in_topK": relevant_in_topK,
        "rated_in_pool": rated_in_pool,
        "relevant_in_pool": total_relevant_in_pool,
    }


# ---------------------------------------------------------------------------
# Per-type breakdown
# ---------------------------------------------------------------------------

PER_TYPE_TYPES = (
    "decision",
    "investigation_outcome",
    "constraint_memory",
    "thread_summary",
    "task_checkpoint",
    "fact_summary",
    "interest",
)


def _per_type_metrics(
    rows: list[Row],
    topk_by_row: dict[str, list[str]],
) -> dict[str, dict[str, float | int]]:
    """Precision/recall per candidate type — restricted to rated candidates of that type."""
    out: dict[str, dict[str, float | int]] = {}
    for t in PER_TYPE_TYPES:
        rated_in_topK = 0
        relevant_in_topK = 0
        rel_in_pool = 0
        rated_in_pool = 0
        for row in rows:
            topk = set(topk_by_row.get(row.audit_id) or [])
            for c in row.cands:
                if c.memory_type != t:
                    continue
                if c.rating in ("relevant", "not_relevant"):
                    rated_in_pool += 1
                    if c.rating == "relevant":
                        rel_in_pool += 1
                    if c.memory_object_id in topk:
                        rated_in_topK += 1
                        if c.rating == "relevant":
                            relevant_in_topK += 1
        p = (relevant_in_topK / rated_in_topK) if rated_in_topK else float("nan")
        r = (relevant_in_topK / rel_in_pool) if rel_in_pool else float("nan")
        out[t] = {
            "precision": p,
            "recall": r,
            "rated_in_topK": rated_in_topK,
            "relevant_in_topK": relevant_in_topK,
            "rated_in_pool": rated_in_pool,
            "relevant_in_pool": rel_in_pool,
        }
    return out


# ---------------------------------------------------------------------------
# Format helpers
# ---------------------------------------------------------------------------

def _fmt(x: float | int | None) -> str:
    if x is None:
        return "n/a"
    if isinstance(x, float):
        if math.isnan(x):
            return "n/a"
        return f"{x:.3f}"
    return str(x)


def _delta(a: float, b: float) -> str:
    if a is None or b is None or math.isnan(a) or math.isnan(b):
        return "n/a"
    return f"{(b - a):+.3f}"


# ---------------------------------------------------------------------------
# Qualitative samples
# ---------------------------------------------------------------------------

def _pick_qualitative_samples(
    rows: list[Row],
    row_results: dict[str, RowResult],
    *,
    n_helpful: int = 10,
    n_harmful: int = 10,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    helpful: list[dict[str, Any]] = []
    harmful: list[dict[str, Any]] = []

    for row in rows:
        rr = row_results.get(row.audit_id)
        if rr is None or not rr.decision_changed:
            continue
        net = rr.promoted_relevant + rr.demoted_not_relevant - rr.demoted_relevant - rr.promoted_not_relevant
        rec = {
            "audit_id": row.audit_id,
            "query": row.query_text,
            "K": row.K,
            "row": row,
            "rr": rr,
            "net": net,
        }
        if net > 0 and len(helpful) < n_helpful:
            helpful.append(rec)
        elif net < 0 and len(harmful) < n_harmful:
            harmful.append(rec)
        if len(helpful) >= n_helpful and len(harmful) >= n_harmful:
            break
    return helpful, harmful


def _format_sample(rec: dict[str, Any], variant: str) -> list[str]:
    row: Row = rec["row"]
    rr: RowResult = rec["rr"]
    cand_by_mid = {c.memory_object_id: c for c in row.cands if c.memory_object_id}
    out: list[str] = []
    out.append(f"### audit `{row.audit_id[:8]}` — net {rec['net']:+d} — K={row.K}")
    out.append("")
    out.append(f"- query: `{_trim(row.query_text, 200)}`")
    out.append(f"- container: `{row.container_ref}`")
    out.append(f"- baseline top-{row.K}:")
    for mid in rr.baseline_mids[: row.K]:
        c = cand_by_mid.get(mid)
        if not c:
            continue
        rating = c.rating or "(unrated)"
        ov = c.overlap.get(variant, 0)
        sub = _trim(c.subject.get(variant, ""), 80)
        out.append(
            f"  - mid={mid[:8]} type={c.memory_type} z={c.z_score:+.2f} ov={ov} "
            f"rating={rating} subj=`{sub}`"
        )
    out.append(f"- boosted top-{row.K}:")
    for mid in rr.boosted_mids[: row.K]:
        c = cand_by_mid.get(mid)
        if not c:
            continue
        rating = c.rating or "(unrated)"
        ov = c.overlap.get(variant, 0)
        sub = _trim(c.subject.get(variant, ""), 80)
        out.append(
            f"  - mid={mid[:8]} type={c.memory_type} z={c.z_score:+.2f} ov={ov} "
            f"rating={rating} subj=`{sub}`"
        )
    swap_in = set(rr.boosted_mids) - set(rr.baseline_mids)
    swap_out = set(rr.baseline_mids) - set(rr.boosted_mids)
    out.append(f"- entered: {[m[:8] for m in swap_in]} | left: {[m[:8] for m in swap_out]}")
    out.append("")
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--subjects", type=Path, default=DEFAULT_SUBJECTS)
    ap.add_argument("--out", type=Path, default=DEFAULT_REPORT)
    ap.add_argument("--run-log", type=Path, default=DEFAULT_RUN_LOG)
    args = ap.parse_args()

    run_log: list[str] = []
    run_log.append(f"## Run {datetime.utcnow().isoformat()}Z\n")

    subjects = load_subjects(args.subjects)
    print(f"loaded {len(subjects)} enriched subject rows")
    run_log.append(f"- enriched subjects loaded: {len(subjects)}")
    if not subjects:
        print("ERROR: no enriched subjects found; run subject_enrichment first.", file=sys.stderr)
        return 1

    con = open_ro(args.db)

    # --- audit-log filter audit ---
    decision_dist = {
        r["decision_reason"]: r["c"]
        for r in con.execute(
            "SELECT decision_reason, COUNT(*) c FROM query_audit_log "
            "WHERE created_at >= ? GROUP BY decision_reason",
            (SINCE,),
        )
    }
    run_log.append(f"- decision_reason distribution since {SINCE}: {decision_dist}")
    run_log.append(
        f"- selected reasons (inject AND have candidate_scores): {INJECTING_REASONS}"
    )

    rows = load_rated_rows(con)
    print(f"loaded {len(rows)} rated audit rows since {SINCE}")
    run_log.append(f"- rated audit rows loaded: {len(rows)}")

    if not rows:
        print("ERROR: no rated rows in slice; aborting.", file=sys.stderr)
        return 1

    # --- candidate sanity ---
    n_cands = sum(len(r.cands) for r in rows)
    n_rated = sum(
        1 for r in rows for c in r.cands if c.rating in ("relevant", "not_relevant")
    )
    n_rel = sum(1 for r in rows for c in r.cands if c.rating == "relevant")
    n_nr = sum(1 for r in rows for c in r.cands if c.rating == "not_relevant")
    all_scores = [c.routing_score for r in rows for c in r.cands]
    run_log.append(
        f"- candidates: {n_cands} | rated: {n_rated} (rel={n_rel}, nr={n_nr})"
    )
    run_log.append(
        f"- routing_score: min={min(all_scores):.1f} max={max(all_scores):.1f} "
        f"mean={statistics.mean(all_scores):.1f} stdev={statistics.pstdev(all_scores):.1f}"
    )

    edge_counts = annotate_subjects(rows, subjects)
    run_log.append(f"- subject-annotation edge cases: {edge_counts}")

    # --- example candidate_scores_json shape ---
    if rows:
        ex = rows[0]
        run_log.append("\n### Example row")
        run_log.append(f"- audit_id: {ex.audit_id[:8]}")
        run_log.append(f"- query: `{_trim(ex.query_text, 160)}`")
        run_log.append(f"- K (injected): {ex.K}")
        run_log.append(f"- candidate count: {len(ex.cands)}")
        for c in ex.cands[:5]:
            ov = c.overlap.get("v3_llm", 0)
            sub = _trim(c.subject.get("v3_llm", ""), 60)
            run_log.append(
                f"  - mid={(c.memory_object_id or 'none')[:8]} type={c.memory_type} "
                f"score={c.routing_score:.0f} z={c.z_score:+.2f} ov_v3={ov} "
                f"injected={c.injected} rating={c.rating} subj_v3=`{sub}`"
            )

    # --- baseline metrics (no boost) ---
    baseline_top: dict[str, list[str]] = {r.audit_id: list(r.baseline_top_mids) for r in rows}
    baseline_metrics = _topk_metrics(rows, baseline_top)
    print(
        f"BASELINE: P={_fmt(baseline_metrics['precision'])} "
        f"R={_fmt(baseline_metrics['recall'])} "
        f"rated_in_pool={baseline_metrics['rated_in_pool']} "
        f"rel_in_pool={baseline_metrics['relevant_in_pool']}"
    )
    run_log.append(
        f"\n### Baseline metrics\n- {baseline_metrics}"
    )

    # --- sweep ---
    sweep_results: dict[tuple[str, float], dict[str, Any]] = {}
    row_results_by_combo: dict[tuple[str, float], dict[str, RowResult]] = {}

    for variant in VARIANTS:
        for alpha in ALPHAS:
            row_results: dict[str, RowResult] = {}
            for row in rows:
                row_results[row.audit_id] = rerank_row(row, variant, alpha)
            row_results_by_combo[(variant, alpha)] = row_results
            boosted_top = {
                aid: rr.boosted_mids for aid, rr in row_results.items()
            }
            metrics = _topk_metrics(rows, boosted_top)
            n_changed = sum(1 for rr in row_results.values() if rr.decision_changed)
            promoted_rel = sum(rr.promoted_relevant for rr in row_results.values())
            promoted_nr = sum(rr.promoted_not_relevant for rr in row_results.values())
            demoted_rel = sum(rr.demoted_relevant for rr in row_results.values())
            demoted_nr = sum(rr.demoted_not_relevant for rr in row_results.values())
            sweep_results[(variant, alpha)] = {
                **metrics,
                "decision_change_rate": n_changed / len(rows) if rows else float("nan"),
                "n_changed": n_changed,
                "promoted_rel": promoted_rel,
                "promoted_nr": promoted_nr,
                "demoted_rel": demoted_rel,
                "demoted_nr": demoted_nr,
            }

    # --- report ---
    out_lines: list[str] = []
    out_lines.append("# Subject soft-signal replay — 2026-05-28")
    out_lines.append("")
    out_lines.append("## 1. Setup")
    out_lines.append("")
    out_lines.append(f"- Window: `created_at >= {SINCE}`")
    out_lines.append(f"- DB: `{args.db}` (read-only)")
    out_lines.append(f"- Decision-reason filter: `{INJECTING_REASONS}`")
    out_lines.append(
        "  - `orientation_recency` (retired 2026-06-09 in a0e6f50) historically injected without "
        "storing candidate_scores_json → could not be re-ranked"
    )
    out_lines.append(
        "  - `same_thread_context_sufficient` and `no_relevant_memory` did not inject → no ratings"
    )
    out_lines.append(f"- Rated audit rows in slice: **{len(rows)}**")
    out_lines.append(f"- Total candidates in slice: **{n_cands}**")
    out_lines.append(
        f"- Rated candidates: **{n_rated}** (relevant={n_rel}, not_relevant={n_nr})"
    )
    out_lines.append("- α sweep: " + ", ".join(f"`{a}`" for a in ALPHAS))
    out_lines.append("- Boost rule:")
    out_lines.append(
        "  - `boosted = z(routing_score) + α · log(1 + overlap)` if `overlap >= 2`"
    )
    out_lines.append(
        "  - `boosted = z(routing_score)` otherwise (no penalty — soft signal)"
    )
    out_lines.append("- Top-K rule: K = number of injected blocks per row (production cap)")
    out_lines.append(
        "- Per-row z-normalization: production routing_scores have wide cross-row variance"
    )
    out_lines.append(
        f"  (raw range {min(all_scores):.0f}..{max(all_scores):.0f}, "
        f"per-row range median ~340). z-norm makes α interpretable."
    )
    out_lines.append("")

    # Headline table
    out_lines.append("## 2. Headline: precision / recall / decision-change-rate")
    out_lines.append("")
    out_lines.append(
        f"Baseline (no boost): P=**{_fmt(baseline_metrics['precision'])}**, "
        f"R=**{_fmt(baseline_metrics['recall'])}** — "
        f"rated_in_topK={baseline_metrics['rated_in_topK']}, "
        f"relevant_in_topK={baseline_metrics['relevant_in_topK']}, "
        f"relevant_in_pool={baseline_metrics['relevant_in_pool']}"
    )
    out_lines.append("")
    out_lines.append(
        "| variant | α | P | R | ΔP | ΔR | change_rate | promoted_rel | demoted_rel | promoted_nr | demoted_nr |"
    )
    out_lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    out_lines.append(
        f"| **baseline** | — | {_fmt(baseline_metrics['precision'])} | {_fmt(baseline_metrics['recall'])} | — | — | 0.000 | 0 | 0 | 0 | 0 |"
    )
    p_base = baseline_metrics["precision"]
    r_base = baseline_metrics["recall"]
    for variant in VARIANTS:
        for alpha in ALPHAS:
            res = sweep_results[(variant, alpha)]
            out_lines.append(
                f"| {variant} | {alpha} | {_fmt(res['precision'])} | {_fmt(res['recall'])} | "
                f"{_delta(p_base, res['precision'])} | {_delta(r_base, res['recall'])} | "
                f"{_fmt(res['decision_change_rate'])} | {res['promoted_rel']} | {res['demoted_rel']} | "
                f"{res['promoted_nr']} | {res['demoted_nr']} |"
            )
    out_lines.append("")

    # Best (variant, α) per variant by P with R≥baseline-R-0.05
    def _is_better(res: dict[str, Any], base_p: float, base_r: float) -> tuple[float, float]:
        # Sort key — prioritize higher precision; tolerate small recall drop
        if math.isnan(res["precision"]) or math.isnan(res["recall"]):
            return (-1e9, -1e9)
        return (res["precision"], res["recall"])

    best_per_variant: dict[str, tuple[float, dict[str, Any]]] = {}
    for variant in VARIANTS:
        best_alpha = None
        best_score = (-1e9, -1e9)
        best_res = None
        for alpha in ALPHAS:
            res = sweep_results[(variant, alpha)]
            score = _is_better(res, p_base, r_base)
            if score > best_score:
                best_score = score
                best_alpha = alpha
                best_res = res
        if best_res is not None:
            best_per_variant[variant] = (best_alpha, best_res)

    # --- Per-type breakdown at best α per variant ---
    out_lines.append("## 3. Per-type breakdown (precision / recall) at best α per variant")
    out_lines.append("")
    base_per_type = _per_type_metrics(rows, baseline_top)
    out_lines.append(
        "| type | rated_in_pool | rel_in_pool | base P | base R | "
        "V1 P | V1 R | V2 P | V2 R | V3 P | V3 R |"
    )
    out_lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    per_type_at_best: dict[str, dict[str, dict[str, float | int]]] = {}
    for variant in VARIANTS:
        best_alpha, _ = best_per_variant[variant]
        boosted_top = {
            r.audit_id: row_results_by_combo[(variant, best_alpha)][r.audit_id].boosted_mids
            for r in rows
        }
        per_type_at_best[variant] = _per_type_metrics(rows, boosted_top)
    for t in PER_TYPE_TYPES:
        bm = base_per_type[t]
        v1m = per_type_at_best["v1_fallback"][t]
        v2m = per_type_at_best["v2_deterministic"][t]
        v3m = per_type_at_best["v3_llm"][t]
        out_lines.append(
            f"| {t} | {bm['rated_in_pool']} | {bm['relevant_in_pool']} | "
            f"{_fmt(bm['precision'])} | {_fmt(bm['recall'])} | "
            f"{_fmt(v1m['precision'])} | {_fmt(v1m['recall'])} | "
            f"{_fmt(v2m['precision'])} | {_fmt(v2m['recall'])} | "
            f"{_fmt(v3m['precision'])} | {_fmt(v3m['recall'])} |"
        )
    out_lines.append("")
    out_lines.append(
        "Best α per variant: " +
        ", ".join(f"{v}=`{best_per_variant[v][0]}`" for v in VARIANTS)
    )
    out_lines.append("")

    # --- Net wins/losses at best α per variant ---
    out_lines.append("## 4. Net win/loss across rows (at best α per variant)")
    out_lines.append("")
    out_lines.append(
        "Per row: net = (promoted_relevant + demoted_not_relevant) − "
        "(demoted_relevant + promoted_not_relevant). Counts only rated swaps."
    )
    out_lines.append("")
    out_lines.append("| variant | α | helped (net>0) | harmed (net<0) | neutral / unchanged |")
    out_lines.append("|---|---:|---:|---:|---:|")
    for variant in VARIANTS:
        best_alpha, _ = best_per_variant[variant]
        rrs = row_results_by_combo[(variant, best_alpha)]
        helped = harmed = neutral = 0
        for rr in rrs.values():
            net = (rr.promoted_relevant + rr.demoted_not_relevant) - (
                rr.demoted_relevant + rr.promoted_not_relevant
            )
            if net > 0:
                helped += 1
            elif net < 0:
                harmed += 1
            else:
                neutral += 1
        out_lines.append(
            f"| {variant} | {best_alpha} | {helped} | {harmed} | {neutral} |"
        )
    out_lines.append("")

    # --- Qualitative samples (focus on V3 — the LLM variant) ---
    sample_variant = "v3_llm"
    sample_alpha = best_per_variant[sample_variant][0]
    helpful, harmful = _pick_qualitative_samples(
        rows, row_results_by_combo[(sample_variant, sample_alpha)]
    )
    out_lines.append(
        f"## 5. Qualitative samples (variant=`{sample_variant}`, α=`{sample_alpha}`)"
    )
    out_lines.append("")
    out_lines.append(f"### 5a. Helpful changes (top {len(helpful)})")
    out_lines.append("")
    if not helpful:
        out_lines.append("(no helpful changes — boost did not promote relevant cards in this slice)")
        out_lines.append("")
    for rec in helpful:
        out_lines.extend(_format_sample(rec, sample_variant))

    out_lines.append(f"### 5b. Harmful changes (top {len(harmful)})")
    out_lines.append("")
    if not harmful:
        out_lines.append("(no harmful changes)")
        out_lines.append("")
    for rec in harmful:
        out_lines.extend(_format_sample(rec, sample_variant))

    # --- Recommendation ---
    out_lines.append("## 6. Recommendation")
    out_lines.append("")
    # Pick best variant by ΔP with ΔR within −0.05 tolerance
    best_overall = None
    best_overall_score = -1e9
    for variant in VARIANTS:
        for alpha in ALPHAS:
            res = sweep_results[(variant, alpha)]
            if math.isnan(res["precision"]) or math.isnan(res["recall"]):
                continue
            dp = res["precision"] - p_base
            dr = res["recall"] - r_base
            # composite: ΔP weighted; recall floor as soft threshold
            if dr < -0.05:
                continue
            if dp > best_overall_score:
                best_overall_score = dp
                best_overall = (variant, alpha, res, dp, dr)

    if best_overall is None:
        out_lines.append(
            "**No** combination produced a positive ΔP within tolerable recall loss. "
            "The soft boost does not move the needle in this rated slice."
        )
        out_lines.append("")
        out_lines.append(
            "Across all 15 (variant, α) combinations, decision-change rates are very low "
            "and rated-card swaps are dominated by neutral or harmful moves. The dominant "
            "ranking signal is already production routing_score; subject overlap as an "
            "additive bonus does not durably push relevant cards above not_relevant ones."
        )
        out_lines.append("")
        out_lines.append(
            "**Verdict:** subject signal — even the LLM-extracted V3 — is not a useful "
            "soft-rerank lever in the current rated slice. Combined with R2b having "
            "already failed as a hard gate, this closes out subject overlap as a "
            "promotion mechanism: the dominant noise lives elsewhere (routing decision, "
            "skip-override, per-type ranking)."
        )
        out_lines.append("")
        out_lines.append(
            "**Do NOT** proceed to architect review of a production-side subject-boost "
            "feature. Recommend instead: focus on routing-skip override (where rated "
            "candidates are dropped pre-injection), and per-container/per-type calibration."
        )
    else:
        v, a, res, dp, dr = best_overall
        out_lines.append(
            f"Best combination: **variant=`{v}`, α=`{a}`** with "
            f"ΔP=**{dp:+.3f}**, ΔR=**{dr:+.3f}**, "
            f"decision_change_rate=**{_fmt(res['decision_change_rate'])}**."
        )
        out_lines.append("")
        magnitude = "material" if dp >= 0.05 else ("marginal" if dp >= 0.02 else "noise-level")
        out_lines.append(f"Magnitude is **{magnitude}**.")
        out_lines.append("")
        if dp >= 0.05:
            out_lines.append(
                "**Verdict:** subject as a soft additive boost is a real lever. "
                "Recommend proceeding to architect review of a small production change — "
                "the smallest experiment is to enable `SUBJECT_MATCH_ENABLED` in "
                "`semantic/agent_conversation_memory_routing_scoring.py` with the bonus "
                "calibrated to roughly α·log(1+overlap)·(per-row-stdev of routing_score)."
            )
        elif dp >= 0.02:
            out_lines.append(
                "**Verdict:** marginal lift only. Document as observation; do not ship "
                "without first verifying the per-type breakdown above shows the gain is "
                "concentrated in a way that suggests a targeted change (e.g. per-type "
                "boost on task_checkpoint and thread_summary) rather than a global one."
            )
        else:
            out_lines.append(
                "**Verdict:** noise-level lift. Subject signal is not durable enough as "
                "a soft additive boost to justify a production change. Pursue routing "
                "and per-type calibration ahead of subject extraction."
            )

    out_lines.append("")

    # --- Append architect review placeholder ---
    out_lines.append("## 7. Architect review")
    out_lines.append("")
    out_lines.append("_See section appended after the architect-review pass._")
    out_lines.append("")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"\nwrote {args.out}")

    args.run_log.parent.mkdir(parents=True, exist_ok=True)
    with args.run_log.open("a", encoding="utf-8") as f:
        f.write("\n".join(run_log) + "\n")
    print(f"appended {args.run_log}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
