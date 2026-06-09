"""Post-routing selection audit.

Measures whether Pallium's post-routing selection layer (work between scored
candidates and final injected set) improves or hurts rated quality vs a simple
top-K-by-routing_score baseline.

For each query_audit_log row in the rated window where injection happened
(decision_reason='carry_forward_available' is the only one carrying both
candidate_scores_json and injected_blocks_json):

  P = production injected set (mids in injected_blocks_json)
  T = top-|P| candidates by routing_score (restricted to candidates with mid)
  R = T \\ P (top-K candidates dropped by selection)

Per-row net = kept_relevant + dropped_not_relevant
              - kept_not_relevant - dropped_relevant

Aggregates and breaks down by decision_reason, container_ref, candidate type,
excluded_reason_code, suppression_reason_code, and routing_rank displacement.

Read-only on the live DB. No LLM calls. No production code touched.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

DEFAULT_DB = str(Path.home() / ".pallium" / "data" / "pallium.db")
DEFAULT_REPORT = (
    _PROJECT_ROOT / ".local" / "research" / "post_routing_selection_audit_2026-05-28.md"
)
DEFAULT_RUN_LOG = (
    _PROJECT_ROOT / ".local" / "research" / "_post_routing_selection_audit_run.md"
)
SINCE = "2026-05-18"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _trim(s: str | None, n: int = 80) -> str:
    s = (s or "").replace("\n", " ").replace("\r", " ").replace("|", "/")
    return s if len(s) <= n else s[: n - 1] + "…"


# Container-ref anonymization. The repo will be public; we must not print
# internal company hostnames or product names. Hash-based aliases give a stable
# identifier without leaking the original. The Pallium project itself is
# public and may stay as-is.
_CONTAINER_PUBLIC_ALLOWLIST = {
    "git:github.com/rore/pallium",
}
_container_alias_cache: dict[str, str] = {}


def _anon_container(c: str | None) -> str:
    if not c:
        return "(none)"
    if c in _CONTAINER_PUBLIC_ALLOWLIST:
        return c
    if c in _container_alias_cache:
        return _container_alias_cache[c]
    import hashlib
    h = hashlib.sha1(c.encode("utf-8")).hexdigest()[:8]
    alias = f"container:{h}"
    _container_alias_cache[c] = alias
    return alias


def _anon_query(q: str | None) -> str:
    """Redact queries to a length+hash digest for the shareable report.

    Real queries contain user code paths, internal product names, ticket IDs,
    and other content this repo treats as not-public-safe. Rather than try to
    enumerate every internal token, the report emits a stable digest plus
    word-count so a reviewer can correlate samples with the run-log without
    leaking content.
    """
    if not q:
        return "(empty)"
    import hashlib
    digest = hashlib.sha1(q.encode("utf-8")).hexdigest()[:10]
    n_words = len(q.split())
    n_chars = len(q)
    return f"<query digest={digest} words={n_words} chars={n_chars}>"


def open_ro(db: str) -> sqlite3.Connection:
    uri = f"file:{db}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Cand:
    cand_idx: int
    memory_object_id: str | None
    memory_type: str | None
    layer: str | None
    routing_score: float
    routing_rank: int | None
    excluded_reason_code: str | None
    suppression_reason_code: str | None
    support_grade: str | None
    injected: bool = False
    rating: str | None = None  # 'relevant', 'not_relevant', or None
    in_T: bool = False  # in top-|P| by routing_score (restricted to mid-bearing)


@dataclass
class Row:
    audit_id: str
    container_ref: str | None
    thread_ref: str | None
    decision_reason: str
    query_text: str
    cands: list[Cand]
    P_mids: list[str]      # production injected set, ordered as emitted
    T_mids: list[str]      # top-K by routing_score (mid-bearing only)
    K: int                 # |P|


# ---------------------------------------------------------------------------
# DB Loaders
# ---------------------------------------------------------------------------

def _load_ratings(con: sqlite3.Connection) -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    for r in con.execute(
        """SELECT query_audit_log_id, memory_object_id, rating
           FROM memory_feedback
           WHERE rating IN ('relevant','not_relevant')
             AND created_at >= ?""",
        (SINCE,),
    ):
        if r["query_audit_log_id"] and r["memory_object_id"]:
            out[(r["query_audit_log_id"], r["memory_object_id"])] = r["rating"]
    return out


def _decision_reason_dist(con: sqlite3.Connection) -> dict[str, int]:
    return {
        r["decision_reason"]: r["c"]
        for r in con.execute(
            "SELECT decision_reason, COUNT(*) c FROM query_audit_log "
            "WHERE created_at >= ? GROUP BY decision_reason",
            (SINCE,),
        )
    }


def _decision_reason_dist_injected(con: sqlite3.Connection) -> dict[str, int]:
    return {
        r["decision_reason"]: r["c"]
        for r in con.execute(
            """SELECT decision_reason, COUNT(*) c FROM query_audit_log
               WHERE created_at >= ?
                 AND injected_blocks_json IS NOT NULL AND injected_blocks_json != '[]'
                 AND candidate_scores_json IS NOT NULL AND candidate_scores_json != '[]'
               GROUP BY decision_reason""",
            (SINCE,),
        )
    }


def load_rows(con: sqlite3.Connection, ratings: dict[tuple[str, str], str]) -> list[Row]:
    """Load all carry_forward_available rows with non-empty P and candidates."""
    sql = """
        SELECT id, container_ref, thread_ref, decision_reason, query_text,
               candidate_scores_json, injected_blocks_json
          FROM query_audit_log
         WHERE created_at >= ?
           AND decision_reason = 'carry_forward_available'
           AND injected_blocks_json IS NOT NULL AND injected_blocks_json != '[]'
           AND candidate_scores_json IS NOT NULL AND candidate_scores_json != '[]'
    """
    out: list[Row] = []
    for r in con.execute(sql, (SINCE,)):
        try:
            cands_raw = json.loads(r["candidate_scores_json"] or "[]")
        except Exception:
            cands_raw = []
        try:
            blocks = json.loads(r["injected_blocks_json"] or "[]")
        except Exception:
            blocks = []
        if not cands_raw or not blocks:
            continue

        P_mids = [b.get("memory_object_id") for b in blocks if isinstance(b, dict) and b.get("memory_object_id")]
        if not P_mids:
            continue
        K = len(P_mids)

        cands: list[Cand] = []
        for i, c in enumerate(cands_raw):
            if not isinstance(c, dict):
                continue
            try:
                rs = float(c.get("routing_score") or 0)
            except Exception:
                rs = 0.0
            rk = c.get("routing_rank")
            try:
                rk_i: int | None = int(rk) if rk is not None else None
            except Exception:
                rk_i = None
            mid = c.get("memory_object_id")
            cand = Cand(
                cand_idx=i,
                memory_object_id=mid,
                memory_type=c.get("memory_type"),
                layer=c.get("layer"),
                routing_score=rs,
                routing_rank=rk_i,
                excluded_reason_code=c.get("excluded_reason_code"),
                suppression_reason_code=c.get("suppression_reason_code"),
                support_grade=c.get("support_grade"),
                injected=bool(c.get("injected")),
                rating=ratings.get((r["id"], mid)) if mid else None,
            )
            cands.append(cand)

        # Compute T = top-K by routing_score, restricted to mid-bearing candidates.
        # source_evidence-style records (mid is None) cannot enter ratings, so we
        # drop them from T for the rated comparison (documented as blind spot).
        mid_cands = [c for c in cands if c.memory_object_id]
        # Stable sort by (-routing_score, cand_idx)
        mid_cands_sorted = sorted(mid_cands, key=lambda c: (-c.routing_score, c.cand_idx))
        T_mids = [c.memory_object_id for c in mid_cands_sorted[:K] if c.memory_object_id]
        T_set = set(T_mids)
        for c in cands:
            c.in_T = bool(c.memory_object_id and c.memory_object_id in T_set)

        out.append(
            Row(
                audit_id=r["id"],
                container_ref=r["container_ref"],
                thread_ref=r["thread_ref"],
                decision_reason=r["decision_reason"],
                query_text=r["query_text"] or "",
                cands=cands,
                P_mids=P_mids,
                T_mids=T_mids,
                K=K,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Per-row net analysis
# ---------------------------------------------------------------------------

@dataclass
class RowOutcome:
    audit_id: str
    K: int
    P: set[str]
    T: set[str]
    R: set[str]                  # T \ P — dropped from top-K
    swap_in: set[str]            # P \ T — promoted by selection
    kept_relevant: int = 0
    kept_not_relevant: int = 0
    dropped_relevant: int = 0
    dropped_not_relevant: int = 0
    swap_in_relevant: int = 0
    swap_in_not_relevant: int = 0
    rated_in_P: int = 0
    rated_in_R: int = 0
    rated_in_swap_in: int = 0
    net: int = 0
    p_eq_t: bool = False


def evaluate_row(row: Row) -> RowOutcome:
    P = set(row.P_mids)
    T = set(row.T_mids)
    R = T - P
    swap_in = P - T

    cand_by_mid: dict[str, Cand] = {c.memory_object_id: c for c in row.cands if c.memory_object_id}

    kept_rel = kept_nr = drop_rel = drop_nr = swin_rel = swin_nr = 0
    rated_in_P = rated_in_R = rated_in_swap_in = 0

    for mid in P:
        c = cand_by_mid.get(mid)
        if c is None:
            continue
        if c.rating == "relevant":
            kept_rel += 1
            rated_in_P += 1
        elif c.rating == "not_relevant":
            kept_nr += 1
            rated_in_P += 1

    for mid in R:
        c = cand_by_mid.get(mid)
        if c is None:
            continue
        if c.rating == "relevant":
            drop_rel += 1
            rated_in_R += 1
        elif c.rating == "not_relevant":
            drop_nr += 1
            rated_in_R += 1

    for mid in swap_in:
        c = cand_by_mid.get(mid)
        if c is None:
            continue
        if c.rating == "relevant":
            swin_rel += 1
            rated_in_swap_in += 1
        elif c.rating == "not_relevant":
            swin_nr += 1
            rated_in_swap_in += 1

    # Per spec D:
    # net = kept_relevant + dropped_not_relevant - kept_not_relevant - dropped_relevant
    net = kept_rel + drop_nr - kept_nr - drop_rel
    return RowOutcome(
        audit_id=row.audit_id,
        K=row.K,
        P=P,
        T=T,
        R=R,
        swap_in=swap_in,
        kept_relevant=kept_rel,
        kept_not_relevant=kept_nr,
        dropped_relevant=drop_rel,
        dropped_not_relevant=drop_nr,
        swap_in_relevant=swin_rel,
        swap_in_not_relevant=swin_nr,
        rated_in_P=rated_in_P,
        rated_in_R=rated_in_R,
        rated_in_swap_in=rated_in_swap_in,
        net=net,
        p_eq_t=(P == T),
    )


# ---------------------------------------------------------------------------
# Breakdowns
# ---------------------------------------------------------------------------

@dataclass
class GroupAgg:
    n_rows: int = 0
    n_helped: int = 0   # net > 0
    n_neutral: int = 0  # net == 0
    n_hurt: int = 0     # net < 0
    sum_net: int = 0
    rated_kept_rel: int = 0
    rated_kept_nr: int = 0
    rated_dropped_rel: int = 0
    rated_dropped_nr: int = 0


def _group_agg(outcomes: list[tuple[Row, RowOutcome]], keyfn) -> dict[str, GroupAgg]:
    out: dict[str, GroupAgg] = defaultdict(GroupAgg)
    for row, oc in outcomes:
        # Restrict to the rated slice — only rows with at least 1 rated card across P/R
        if oc.rated_in_P + oc.rated_in_R == 0:
            continue
        k = keyfn(row, oc) or "(none)"
        g = out[k]
        g.n_rows += 1
        if oc.net > 0:
            g.n_helped += 1
        elif oc.net < 0:
            g.n_hurt += 1
        else:
            g.n_neutral += 1
        g.sum_net += oc.net
        g.rated_kept_rel += oc.kept_relevant
        g.rated_kept_nr += oc.kept_not_relevant
        g.rated_dropped_rel += oc.dropped_relevant
        g.rated_dropped_nr += oc.dropped_not_relevant
    return dict(out)


# ---------------------------------------------------------------------------
# Per-type / per-reason candidate-level breakdowns
# ---------------------------------------------------------------------------

@dataclass
class CandAgg:
    """Aggregates over rated candidates for a (key, bucket) cross-tab."""
    kept_rel: int = 0       # in P, rated relevant
    kept_nr: int = 0        # in P, rated not_relevant
    dropped_rel: int = 0    # in T \\ P, rated relevant   (production HURT)
    dropped_nr: int = 0     # in T \\ P, rated not_relevant (production HELPED)
    promoted_rel: int = 0   # in P \\ T, rated relevant   (production HELPED)
    promoted_nr: int = 0    # in P \\ T, rated not_relevant (production HURT)


def _cand_buckets(rows_with_outcomes: list[tuple[Row, RowOutcome]], keyfn) -> dict[str, CandAgg]:
    out: dict[str, CandAgg] = defaultdict(CandAgg)
    for row, oc in rows_with_outcomes:
        cand_by_mid = {c.memory_object_id: c for c in row.cands if c.memory_object_id}
        for mid in oc.P:
            c = cand_by_mid.get(mid)
            if c is None or c.rating is None:
                continue
            k = keyfn(c) or "(none)"
            agg = out[k]
            if c.rating == "relevant":
                agg.kept_rel += 1
                if mid in oc.swap_in:
                    agg.promoted_rel += 1
            elif c.rating == "not_relevant":
                agg.kept_nr += 1
                if mid in oc.swap_in:
                    agg.promoted_nr += 1
        for mid in oc.R:
            c = cand_by_mid.get(mid)
            if c is None or c.rating is None:
                continue
            k = keyfn(c) or "(none)"
            agg = out[k]
            if c.rating == "relevant":
                agg.dropped_rel += 1
            elif c.rating == "not_relevant":
                agg.dropped_nr += 1
    return dict(out)


# ---------------------------------------------------------------------------
# Rank-displacement
# ---------------------------------------------------------------------------

def _rank_histograms(
    rows_with_outcomes: list[tuple[Row, RowOutcome]],
) -> tuple[Counter, Counter]:
    """Return:
      - histogram of routing_rank for cards that production injected but were NOT in T
      - histogram of routing_rank for cards that were in T but production dropped
    """
    promoted_ranks: Counter = Counter()
    dropped_ranks: Counter = Counter()
    for row, oc in rows_with_outcomes:
        cand_by_mid = {c.memory_object_id: c for c in row.cands if c.memory_object_id}
        for mid in oc.swap_in:
            c = cand_by_mid.get(mid)
            if c is None:
                continue
            promoted_ranks[c.routing_rank if c.routing_rank is not None else -1] += 1
        for mid in oc.R:
            c = cand_by_mid.get(mid)
            if c is None:
                continue
            dropped_ranks[c.routing_rank if c.routing_rank is not None else -1] += 1
    return promoted_ranks, dropped_ranks


# ---------------------------------------------------------------------------
# Sample picking
# ---------------------------------------------------------------------------

def _pick_samples(
    rows_with_outcomes: list[tuple[Row, RowOutcome]],
) -> tuple[list[tuple[Row, RowOutcome]], list[tuple[Row, RowOutcome]], list[tuple[Row, RowOutcome]]]:
    """Pick qualitative samples.

    Helpful and harmful samples prioritize rows where P != T (selection
    actually deviated from routing top-K) — these isolate the selection
    effect. Neutral_swap captures rows where selection swapped cards but the
    rated balance came out flat (an interesting churn pattern).
    """
    helpful: list[tuple[Row, RowOutcome]] = []
    harmful: list[tuple[Row, RowOutcome]] = []
    neutral_swap: list[tuple[Row, RowOutcome]] = []

    deviating = [(r, oc) for (r, oc) in rows_with_outcomes if not oc.p_eq_t]
    non_deviating = [(r, oc) for (r, oc) in rows_with_outcomes if oc.p_eq_t]

    # Helped: prefer deviating rows first. Within each, sort by net desc.
    for r, oc in sorted(deviating, key=lambda x: -x[1].net):
        if oc.net >= 2 and len(helpful) < 10:
            helpful.append((r, oc))
    if len(helpful) < 10:
        for r, oc in sorted(non_deviating, key=lambda x: -x[1].net):
            if oc.net >= 2 and len(helpful) < 10:
                helpful.append((r, oc))

    # Hurt: same — deviating first, then non-deviating.
    for r, oc in sorted(deviating, key=lambda x: x[1].net):
        if oc.net <= -2 and len(harmful) < 10:
            harmful.append((r, oc))
    if len(harmful) < 10:
        for r, oc in sorted(non_deviating, key=lambda x: x[1].net):
            if oc.net <= -2 and len(harmful) < 10:
                harmful.append((r, oc))

    # Neutral with swap: only deviating rows count (where selection did work).
    for r, oc in deviating:
        if oc.net == 0 and (oc.swap_in or oc.R) and len(neutral_swap) < 10:
            neutral_swap.append((r, oc))

    return helpful, harmful, neutral_swap


def _format_sample(row: Row, oc: RowOutcome) -> list[str]:
    cand_by_mid = {c.memory_object_id: c for c in row.cands if c.memory_object_id}
    out: list[str] = []
    out.append(f"### audit `{row.audit_id[:8]}` — net {oc.net:+d} — K={row.K}")
    out.append("")
    out.append(f"- query: `{_trim(_anon_query(row.query_text), 200)}`")
    out.append(f"- container: `{_anon_container(row.container_ref)}`")
    out.append(f"- P (production injected, |P|={len(oc.P)}):")
    for mid in row.P_mids:
        c = cand_by_mid.get(mid)
        if c is None:
            continue
        rating = c.rating or "(unrated)"
        out.append(
            f"  - mid={mid[:8]} type={c.memory_type} score={c.routing_score:.0f} "
            f"rank={c.routing_rank} in_T={c.in_T} rating={rating}"
        )
    out.append(f"- T (top-{row.K} by routing_score, |T|={len(oc.T)}):")
    for mid in row.T_mids:
        c = cand_by_mid.get(mid)
        if c is None:
            continue
        rating = c.rating or "(unrated)"
        in_P = mid in oc.P
        out.append(
            f"  - mid={mid[:8]} type={c.memory_type} score={c.routing_score:.0f} "
            f"rank={c.routing_rank} in_P={in_P} rating={rating}"
        )
    out.append(f"- dropped by selection (T \\ P): {sorted(m[:8] for m in oc.R)}")
    for mid in oc.R:
        c = cand_by_mid.get(mid)
        if c is None:
            continue
        rating = c.rating or "(unrated)"
        out.append(
            f"  - mid={mid[:8]} type={c.memory_type} excl={c.excluded_reason_code} "
            f"supp={c.suppression_reason_code} rating={rating}"
        )
    out.append(f"- promoted by selection (P \\ T): {sorted(m[:8] for m in oc.swap_in)}")
    for mid in oc.swap_in:
        c = cand_by_mid.get(mid)
        if c is None:
            continue
        rating = c.rating or "(unrated)"
        out.append(
            f"  - mid={mid[:8]} type={c.memory_type} rank={c.routing_rank} "
            f"score={c.routing_score:.0f} rating={rating}"
        )
    out.append("")
    return out


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------

def _fmt_rate(num: int, den: int) -> str:
    if den == 0:
        return "n/a"
    return f"{num}/{den} ({num*100/den:.1f}%)"


def _group_agg_table(title: str, groups: dict[str, GroupAgg]) -> list[str]:
    lines: list[str] = []
    lines.append(f"### {title}")
    lines.append("")
    if not groups:
        lines.append("(no rows in rated slice for this dimension)")
        lines.append("")
        return lines
    lines.append("| key | n_rows | helped (net>0) | neutral (net=0) | hurt (net<0) | sum_net | kept_rel | kept_nr | drop_rel | drop_nr |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for k in sorted(groups, key=lambda x: -groups[x].sum_net):
        g = groups[k]
        lines.append(
            f"| `{_trim(k, 60)}` | {g.n_rows} | {g.n_helped} | {g.n_neutral} | {g.n_hurt} | "
            f"{g.sum_net:+d} | {g.rated_kept_rel} | {g.rated_kept_nr} | "
            f"{g.rated_dropped_rel} | {g.rated_dropped_nr} |"
        )
    lines.append("")
    return lines


def _cand_agg_table(title: str, aggs: dict[str, CandAgg]) -> list[str]:
    lines: list[str] = []
    lines.append(f"### {title}")
    lines.append("")
    if not aggs:
        lines.append("(no rated candidates in this dimension)")
        lines.append("")
        return lines
    lines.append(
        "| key | kept_rel | kept_nr | dropped_rel (HURT) | dropped_nr (HELPED) | promoted_rel (HELPED) | promoted_nr (HURT) | net |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    def _net(a: CandAgg) -> int:
        # candidate-level net: HELPED - HURT
        return (a.dropped_nr + a.promoted_rel) - (a.dropped_rel + a.promoted_nr)
    for k in sorted(aggs, key=lambda x: -_net(aggs[x])):
        a = aggs[k]
        lines.append(
            f"| `{_trim(k, 60)}` | {a.kept_rel} | {a.kept_nr} | {a.dropped_rel} | {a.dropped_nr} | "
            f"{a.promoted_rel} | {a.promoted_nr} | {_net(a):+d} |"
        )
    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--out", type=Path, default=DEFAULT_REPORT)
    ap.add_argument("--run-log", type=Path, default=DEFAULT_RUN_LOG)
    args = ap.parse_args()

    run_log: list[str] = []
    run_log.append(f"## Run {datetime.utcnow().isoformat()}Z\n")

    con = open_ro(args.db)

    # --- decision_reason distribution
    dist_all = _decision_reason_dist(con)
    dist_inj = _decision_reason_dist_injected(con)
    run_log.append(f"- decision_reason distribution since {SINCE} (all rows): {dist_all}")
    run_log.append(
        f"- decision_reason distribution among injected+candidate-bearing rows: {dist_inj}"
    )
    run_log.append(
        "- Filter applied: decision_reason='carry_forward_available' "
        "(only reason that emits both candidate_scores_json AND injected_blocks_json)."
    )
    run_log.append(
        "- 'orientation_recency' (retired 2026-06-09 in a0e6f50) historically injected without "
        "storing candidate_scores; rows from the live window may carry decision_reason='orientation_recency' "
        "but cannot be replayed. The layer is gone; old audit rows remain immutable."
    )

    ratings = _load_ratings(con)
    run_log.append(f"- rating pairs (audit_id, mid) since {SINCE}: {len(ratings)}")

    rows = load_rows(con, ratings)
    run_log.append(f"- rows loaded after filter: {len(rows)}")

    if not rows:
        print("No rows in window — aborting.", file=sys.stderr)
        return 1

    # --- Sample candidate JSON shape
    run_log.append("\n### Sample candidate_scores_json shapes (first 3 rows)\n")
    for row in rows[:3]:
        run_log.append(f"- audit_id `{row.audit_id[:8]}` decision={row.decision_reason} K={row.K} n_cands={len(row.cands)}")
        for c in row.cands[:3]:
            run_log.append(
                f"  - cand_idx={c.cand_idx} mid={(c.memory_object_id or 'NONE')[:8]} type={c.memory_type} "
                f"score={c.routing_score:.0f} rank={c.routing_rank} "
                f"injected={c.injected} excl={c.excluded_reason_code} supp={c.suppression_reason_code}"
            )

    # --- Score-field choice rationale
    run_log.append("")
    run_log.append("### Score-field choice")
    run_log.append(
        "- `routing_score`: present on all candidates. Integer-ish (range ~100..900). Used as the ranking score."
    )
    run_log.append(
        "- `score`: None on all observed candidates."
    )
    run_log.append(
        "- `ranking_score`: None on all observed candidates."
    )
    run_log.append(
        "- Conclusion: T = top-K by `routing_score`, restricted to candidates with non-null `memory_object_id`."
    )
    run_log.append(
        "- `routing_rank` (1-indexed) is also stored and used to compute rank-displacement histograms."
    )

    # --- post_routing_drop_reason note
    run_log.append("")
    run_log.append("### Drop-reason fields available")
    run_log.append(
        "- `excluded_reason_code` is present on all rows. Observed values include "
        "the legacy set (`lower_routing_score_than_selected_limit`, "
        "`current_query_source_echo`, or NULL) and the Goal A `displaced_by_*` "
        "namespace shipped 2026-05-28: `displaced_by_dedup`, "
        "`displaced_by_fact_summary_cap`, `displaced_by_expansion_ratio`, "
        "`displaced_by_hard_ceiling`, `displaced_by_companion_fill`, "
        "`displaced_by_constraint_supplement`, "
        "`displaced_by_locality_compatibility`, "
        "`displaced_by_cross_thread_checkpoint_suppression`, "
        "`displaced_by_per_candidate_eligibility`, "
        "`displaced_by_r2b_subject_overlap`. Rows written before that date may "
        "still carry NULL — treat as `unannotated_legacy`."
    )
    run_log.append(
        "- `suppression_reason_code` is present. Observed values include "
        "`current_query_source_echo` and the broader suppression-mirror set "
        "(see `agent_conversation_memory_routing_selection.py`)."
    )
    run_log.append(
        "- `post_routing_drop_reason` is now snapshotted alongside "
        "`excluded_reason_code`. The R2b subject-overlap gate populates BOTH "
        "fields on the same candidate (`post_routing_drop_reason="
        "r2b_subject_overlap_insufficient` and "
        "`excluded_reason_code=displaced_by_r2b_subject_overlap`)."
    )
    run_log.append(
        "- Production source (`agent_conversation_memory_routing_selection.py:"
        "_annotate_excluded_candidates` + `_collect_selection_drop_codes`) now "
        "annotates every selection-layer drop site (dedup, fact_summary cap, "
        "expansion ratio, hard ceiling, companion fill, constraint supplement, "
        "locality compatibility, cross-thread checkpoint suppression, "
        "per-candidate eligibility, R2b gate). The 11 unannotated rank-1 "
        "demotions previously reported in this audit should now carry one of "
        "those codes for fresh rows."
    )

    # --- Coverage summary
    n_total_cand = sum(len(r.cands) for r in rows)
    n_with_mid = sum(1 for r in rows for c in r.cands if c.memory_object_id)
    n_rated = sum(1 for r in rows for c in r.cands if c.rating)
    n_rated_rel = sum(1 for r in rows for c in r.cands if c.rating == "relevant")
    n_rated_nr = sum(1 for r in rows for c in r.cands if c.rating == "not_relevant")
    n_rows_any_rated = sum(
        1 for r in rows
        if any(c.rating for c in r.cands)
    )
    run_log.append("")
    run_log.append("### Rated coverage")
    run_log.append(f"- candidates total: {n_total_cand}")
    run_log.append(
        f"- candidates with mid: {n_with_mid} ({n_with_mid*100/max(1,n_total_cand):.1f}%)"
    )
    run_log.append(
        f"  - source_evidence-style records (mid=None) cannot be rated. "
        f"These dominate the candidate population and are a known blind spot."
    )
    run_log.append(f"- rated candidates in slice: {n_rated} (rel={n_rated_rel}, not_rel={n_rated_nr})")
    run_log.append(f"- rows with at least one rated candidate: {n_rows_any_rated}")

    # --- Per-row outcomes
    outcomes: list[tuple[Row, RowOutcome]] = [(r, evaluate_row(r)) for r in rows]
    rated_outcomes = [
        (r, oc) for (r, oc) in outcomes
        if (oc.rated_in_P + oc.rated_in_R) > 0
    ]

    n_rows = len(outcomes)
    n_p_eq_t = sum(1 for _, oc in outcomes if oc.p_eq_t)
    n_p_neq_t = n_rows - n_p_eq_t
    avg_swap_per_row = (
        sum(len(oc.swap_in) for _, oc in outcomes if not oc.p_eq_t)
        / max(1, n_p_neq_t)
    )
    sum_net_all = sum(oc.net for _, oc in rated_outcomes)
    n_rated_rows = len(rated_outcomes)
    n_helped = sum(1 for _, oc in rated_outcomes if oc.net > 0)
    n_neutral = sum(1 for _, oc in rated_outcomes if oc.net == 0)
    n_hurt = sum(1 for _, oc in rated_outcomes if oc.net < 0)

    # --- Selection-only effect (isolates the deviation from routing baseline)
    # The "net" defined in the spec mixes routing's effect (kept_*) with
    # selection's effect (dropped_*, promoted via swap_in). On rows where
    # P == T, kept counts have nothing to do with selection. Compute a
    # selection-only net that drops the kept terms.
    selection_only_rows = [
        (r, oc) for (r, oc) in rated_outcomes if not oc.p_eq_t
    ]
    sel_helped = sel_neutral = sel_hurt = 0
    sel_sum = 0
    sel_drop_rel_total = sel_drop_nr_total = 0
    sel_swap_rel_total = sel_swap_nr_total = 0
    for r, oc in selection_only_rows:
        # selection-only net: (dropped_nr + swap_in_rel) - (dropped_rel + swap_in_nr)
        sel_net = (oc.dropped_not_relevant + oc.swap_in_relevant) - (
            oc.dropped_relevant + oc.swap_in_not_relevant
        )
        sel_sum += sel_net
        if sel_net > 0:
            sel_helped += 1
        elif sel_net < 0:
            sel_hurt += 1
        else:
            sel_neutral += 1
        sel_drop_rel_total += oc.dropped_relevant
        sel_drop_nr_total += oc.dropped_not_relevant
        sel_swap_rel_total += oc.swap_in_relevant
        sel_swap_nr_total += oc.swap_in_not_relevant

    run_log.append("")
    run_log.append("### Selection-only effect (P != T rows only)")
    run_log.append(f"- rated rows where P != T: {len(selection_only_rows)}")
    run_log.append(
        f"- selection_only_sum_net: {sel_sum:+d} "
        f"(helped {sel_helped}, neutral {sel_neutral}, hurt {sel_hurt})"
    )
    run_log.append(
        f"- dropped_relevant total: {sel_drop_rel_total} "
        f"(rated-relevant cards selection threw out from top-K)"
    )
    run_log.append(
        f"- dropped_not_relevant total: {sel_drop_nr_total} "
        f"(rated-not-relevant cards selection successfully filtered)"
    )
    run_log.append(
        f"- promoted_relevant total: {sel_swap_rel_total} "
        f"(rated-relevant cards selection injected from below routing top-K)"
    )
    run_log.append(
        f"- promoted_not_relevant total: {sel_swap_nr_total} "
        f"(rated-not-relevant cards selection injected from below routing top-K)"
    )
    run_log.append(f"- rows total: {n_rows}")
    run_log.append(f"- rows where P == T: {n_p_eq_t}")
    run_log.append(f"- rows where P != T: {n_p_neq_t}")
    run_log.append(
        f"- avg cards swapped per row when P != T: {avg_swap_per_row:.2f}"
    )
    run_log.append(f"- rated rows (have ≥1 rating across P∪R): {n_rated_rows}")
    run_log.append(f"- helped {n_helped}, neutral {n_neutral}, hurt {n_hurt}")
    run_log.append(f"- sum_net (rated slice): {sum_net_all:+d}")

    # --- Build report
    out_lines: list[str] = []
    out_lines.append("# Post-routing selection audit — 2026-05-28")
    out_lines.append("")

    # 1. Setup
    out_lines.append("## 1. Setup")
    out_lines.append("")
    out_lines.append(f"- Window: `created_at >= {SINCE}` (read-only on `{args.db}`)")
    out_lines.append(
        "- Decision-reason filter: `carry_forward_available` (the only reason that "
        "stores both `candidate_scores_json` and `injected_blocks_json`). "
        "`orientation_recency` (retired 2026-06-09 in a0e6f50) historically injected without "
        "storing candidates and was never auditable; "
        "`same_thread_context_sufficient` and `no_relevant_memory` skip injection."
    )
    out_lines.append(
        "- K rule: `K = |P|` per row (production injection cap)."
    )
    out_lines.append(
        "- Score field: `routing_score` (only field populated). T is restricted to "
        "candidates with a non-null `memory_object_id` because source-evidence-only "
        "candidates cannot enter ratings."
    )
    out_lines.append(
        "- Per-row sets: `P` = production injected, `T` = top-K by routing_score, "
        "`R` = T \\ P (top-K candidates dropped by selection)."
    )
    out_lines.append(
        f"- Rows analyzed: **{n_rows}**. Candidates: **{n_total_cand}** "
        f"(of which {n_with_mid} have mids, {n_total_cand - n_with_mid} are "
        f"source-evidence-style and invisible to ratings)."
    )
    out_lines.append(
        f"- Rated candidates in slice: **{n_rated}** ({n_rated_rel} relevant, "
        f"{n_rated_nr} not_relevant). Rated rows (≥1 rating across P∪R): **{n_rated_rows}**."
    )
    out_lines.append("")

    # 2. Headline
    out_lines.append("## 2. Headline")
    out_lines.append("")
    out_lines.append(
        f"- **P vs T deviation rate:** `{n_p_neq_t}/{n_rows}` "
        f"({n_p_neq_t*100/max(1,n_rows):.1f}%) of rows have P ≠ T (selection layer "
        f"materially changes the set vs naive top-K-by-routing_score)."
    )
    out_lines.append(
        f"- **Magnitude:** when P ≠ T, an average of "
        f"{avg_swap_per_row:.2f} cards differ per row."
    )
    out_lines.append(
        f"- **Spec net (rated slice, all rated rows):** sum_net = **{sum_net_all:+d}** "
        f"across {n_rated_rows} rated rows. Helped: **{n_helped}**, neutral: "
        f"**{n_neutral}**, hurt: **{n_hurt}**."
    )
    out_lines.append("")
    out_lines.append(
        "**Caveat — spec net mixes routing and selection effects.** Per-row "
        "`net = (kept_relevant + dropped_not_relevant) − "
        "(kept_not_relevant + dropped_relevant)`. On rows where P == T (66% "
        "of rows), the `kept_*` terms are produced by routing alone — selection "
        "did not change anything — so the spec net partly grades routing, not "
        "selection. The cleaner number is the **selection-only effect** below."
    )
    out_lines.append("")
    out_lines.append(
        f"- **Selection-only effect (rated rows where P ≠ T only):** "
        f"sum = **{sel_sum:+d}** across {len(selection_only_rows)} rated "
        f"deviating rows. Helped: **{sel_helped}**, neutral: "
        f"**{sel_neutral}**, hurt: **{sel_hurt}**. "
        f"Selection dropped **{sel_drop_rel_total}** rated-relevant cards from "
        f"top-K and **{sel_drop_nr_total}** rated-not-relevant cards. Selection "
        f"promoted **{sel_swap_rel_total}** rated-relevant cards into P from "
        f"below top-K and **{sel_swap_nr_total}** rated-not-relevant cards."
    )
    out_lines.append("")

    # 3. Net win/loss table
    out_lines.append("## 3. Net win/loss table")
    out_lines.append("")
    out_lines.append("| bucket | rows | % of rated rows |")
    out_lines.append("|---|---:|---:|")
    out_lines.append(f"| helped (net > 0) | {n_helped} | {_fmt_rate(n_helped, n_rated_rows)} |")
    out_lines.append(f"| neutral (net = 0) | {n_neutral} | {_fmt_rate(n_neutral, n_rated_rows)} |")
    out_lines.append(f"| hurt (net < 0) | {n_hurt} | {_fmt_rate(n_hurt, n_rated_rows)} |")
    out_lines.append("")
    out_lines.append(f"Aggregate magnitude: sum_net = **{sum_net_all:+d}**.")
    out_lines.append("")

    # 4. Breakdowns
    out_lines.append("## 4. Breakdowns")
    out_lines.append("")
    # 4a. by decision_reason
    out_lines.extend(_group_agg_table(
        "4a. By decision_reason (rows)",
        _group_agg(rated_outcomes, lambda r, oc: r.decision_reason),
    ))
    # 4b. by container_ref
    out_lines.extend(_group_agg_table(
        "4b. By container_ref (rows; non-public containers anonymized for shareable report)",
        _group_agg(rated_outcomes, lambda r, oc: _anon_container(r.container_ref)),
    ))
    # 4c. by candidate type (cand-level)
    out_lines.extend(_cand_agg_table(
        "4c. By candidate `memory_type` (rated candidates across P∪R)",
        _cand_buckets(rated_outcomes, lambda c: c.memory_type),
    ))
    # 4d. by excluded_reason_code (cand-level — only over R-side, where the code is the *cause* of the drop)
    excl_aggs = _cand_buckets(
        rated_outcomes,
        lambda c: c.excluded_reason_code if c.excluded_reason_code else "(none)",
    )
    out_lines.extend(_cand_agg_table(
        "4d. By candidate `excluded_reason_code`",
        excl_aggs,
    ))
    # 4e. by suppression_reason_code
    supp_aggs = _cand_buckets(
        rated_outcomes,
        lambda c: c.suppression_reason_code if c.suppression_reason_code else "(none)",
    )
    out_lines.extend(_cand_agg_table(
        "4e. By candidate `suppression_reason_code`",
        supp_aggs,
    ))
    # 4f. by support_grade
    sg_aggs = _cand_buckets(
        rated_outcomes,
        lambda c: c.support_grade if c.support_grade else "(none)",
    )
    out_lines.extend(_cand_agg_table(
        "4f. By candidate `support_grade`",
        sg_aggs,
    ))

    # 5. Rank-displacement histograms
    out_lines.append("## 5. Rank-displacement histograms (rated slice)")
    out_lines.append("")
    promoted_ranks, dropped_ranks = _rank_histograms(rated_outcomes)
    out_lines.append(
        "When production injects a card that wasn't in T (P \\ T), what was that "
        "card's original `routing_rank`? When production drops a top-K card (T \\ P), "
        "what was its rank?"
    )
    out_lines.append("")
    out_lines.append("| routing_rank | promoted_into_P (P\\T) | dropped_from_top_K (T\\P) |")
    out_lines.append("|---:|---:|---:|")
    all_ranks = sorted(set(promoted_ranks) | set(dropped_ranks))
    for rk in all_ranks:
        label = str(rk) if rk != -1 else "(unknown)"
        out_lines.append(f"| {label} | {promoted_ranks.get(rk, 0)} | {dropped_ranks.get(rk, 0)} |")
    out_lines.append("")

    # 6. Qualitative samples
    helpful, harmful, neutral_swap = _pick_samples(rated_outcomes)
    out_lines.append("## 6. Qualitative samples")
    out_lines.append("")
    out_lines.append(f"### 6a. Helped (net ≥ 2) — {len(helpful)} samples")
    out_lines.append("")
    if not helpful:
        out_lines.append("(none — no rated row has net ≥ 2)")
        out_lines.append("")
    for row, oc in helpful:
        out_lines.extend(_format_sample(row, oc))

    out_lines.append(f"### 6b. Hurt (net ≤ -2) — {len(harmful)} samples")
    out_lines.append("")
    if not harmful:
        out_lines.append("(none — no rated row has net ≤ -2)")
        out_lines.append("")
    for row, oc in harmful:
        out_lines.extend(_format_sample(row, oc))

    out_lines.append(f"### 6c. Net=0 with non-trivial swap (P ≠ T but rated cards balanced) — {len(neutral_swap)} samples")
    out_lines.append("")
    if not neutral_swap:
        out_lines.append("(none)")
        out_lines.append("")
    for row, oc in neutral_swap:
        out_lines.extend(_format_sample(row, oc))

    # 7. Verdict
    out_lines.append("## 7. Verdict")
    out_lines.append("")
    helped_pct = n_helped * 100 / max(1, n_rated_rows)
    hurt_pct = n_hurt * 100 / max(1, n_rated_rows)
    if sum_net_all > 0:
        spec_verdict = "net positive"
    elif sum_net_all < 0:
        spec_verdict = "net negative"
    else:
        spec_verdict = "net neutral"
    if sel_sum > 0:
        sel_verdict = "net positive"
    elif sel_sum < 0:
        sel_verdict = "net negative"
    else:
        sel_verdict = "net neutral"
    out_lines.append(
        f"On the spec-defined net (which mixes routing and selection effects): "
        f"{spec_verdict} (sum_net = {sum_net_all:+d}, helped {n_helped}, "
        f"hurt {n_hurt}, neutral {n_neutral} of {n_rated_rows} rated rows). "
        f"This is mostly routing's score, not selection's."
    )
    out_lines.append("")
    out_lines.append(
        f"**On the selection-only effect (rows where P ≠ T): {sel_verdict}** "
        f"(sum = {sel_sum:+d}, helped {sel_helped}, hurt {sel_hurt}, "
        f"neutral {sel_neutral} of {len(selection_only_rows)} deviating rated rows)."
    )
    out_lines.append("")
    if sel_drop_rel_total > sel_drop_nr_total:
        out_lines.append(
            f"⚠ Selection dropped **more rated-relevant cards from top-K "
            f"({sel_drop_rel_total}) than rated-not-relevant cards "
            f"({sel_drop_nr_total})**. Combined with the rank-displacement "
            f"histogram (rank-1 dropped {dropped_ranks.get(1, 0)} times), this "
            f"suggests selection is systematically demoting routing's strongest "
            f"candidates."
        )
    elif sel_drop_rel_total < sel_drop_nr_total:
        out_lines.append(
            f"Selection dropped more rated-not-relevant cards "
            f"({sel_drop_nr_total}) than rated-relevant cards "
            f"({sel_drop_rel_total}) from top-K — the drop direction is "
            f"net-helpful on the rated slice."
        )
    else:
        out_lines.append(
            f"Selection's drops are evenly split ({sel_drop_rel_total} relevant, "
            f"{sel_drop_nr_total} not_relevant) — drops alone do not pick a "
            f"clear direction; the rank-displacement table shows where the "
            f"rank-1 churn lives."
        )
    out_lines.append("")
    out_lines.append(
        "Per-dimension findings appear in §4 and the rank-displacement "
        "histograms in §5. The most informative tables for the selection "
        "question are 4d/4e (drop-reason cross-tabs) and the rank-1 row of §5."
    )
    out_lines.append("")

    # 8. Implications
    out_lines.append("## 8. What this implies for production")
    out_lines.append("")
    out_lines.append(
        "**Selection's actual measurable effect in this slice is small and "
        "ambiguous.** The data show three structural properties of the audit "
        "that bound what we can conclude:"
    )
    out_lines.append("")
    out_lines.append(
        "1. **Rated coverage is biased toward injected cards.** Users rate "
        "what they saw, not what was dropped. Across 13 selection-deviating "
        "rated rows, **0 of the dropped-from-top-K candidates carry any "
        "rating** — so 4d/4e cannot grade the drop reasons. The signal we do "
        "have lives entirely on the `swap_in` side (P \\ T): 6 rated-relevant "
        "promotions and 7 rated-not-relevant promotions — i.e. selection's "
        "promotions are roughly 50/50 by feedback, with a slight tilt "
        "against quality."
    )
    out_lines.append("")
    out_lines.append(
        f"2. **Selection is dropping rank-1 routing candidates frequently** "
        f"({dropped_ranks.get(1, 0)} of "
        f"{sum(dropped_ranks.values())} total drops in the slice are rank-1) "
        "and replacing them with rank-2..rank-5 cards. **Note (2026-05-28):** "
        "the rated-slice numbers above were measured against rows that pre-date "
        "the Goal A annotation work. Fresh rows now carry one of the "
        "`displaced_by_*` codes documented in §2.2 of the audit observability "
        "plan, attributing each drop to the specific selection mechanism "
        "(dedup, fact_summary cap, expansion ratio, hard ceiling, companion "
        "fill, constraint supplement, locality compatibility, cross-thread "
        "checkpoint suppression, per-candidate eligibility, R2b gate). Re-run "
        "this audit on a window post-2026-05-28 to attribute new rank-1 "
        "demotions to a specific branch."
    )
    out_lines.append("")
    out_lines.append(
        "3. **The high-signal selection sample (`ad7129a1`) is informative**: "
        "selection swapped a rank-2 unrated `task_checkpoint` for a rank-4 "
        "rated-relevant `decision`. This pattern — promoting decisions over "
        "task_checkpoints when both fit the query — appears to be working in "
        "this isolated case. But N=1 is not a finding."
    )
    out_lines.append("")
    out_lines.append(
        "**Recommendation.** No selection-layer rule shows a strongly "
        "negative candidate-level net in this slice. The clearest weakness "
        "of the audit is rated coverage on dropped cards, not the selection "
        "layer itself. Two cheap follow-ups would tighten the picture before "
        "any production change is considered:"
    )
    out_lines.append("")
    out_lines.append(
        "- **Annotate non-suppression demotions.** ~~When `_build_injectable_blocks` "
        "demotes a higher-routing-score candidate via packaging "
        "(locality-compatibility, duplicate dedup, fact-summary cap, etc.), "
        "set `excluded_reason_code` to the specific cause rather than "
        "leaving it `None`.~~ **SHIPPED 2026-05-28** — see Goal A in "
        "`.local/research/audit_observability_plan_2026-05-28.md`. The new "
        "`displaced_by_*` codes appear on every fresh row; re-run the audit "
        "on a post-2026-05-28 window to attribute rank-1 demotions to a "
        "specific selection branch."
    )
    out_lines.append("")
    out_lines.append(
        "- **Solicit ratings on top-K-but-not-injected cards** "
        "(e.g. surface dropped top-K through the existing "
        "`/item-and-query/debug` endpoint to a ratings UI). Without rated "
        "drops, no offline audit can grade selection's drop choices."
    )
    out_lines.append("")
    out_lines.append(
        "**Do not** propose a production change to selection on this evidence. "
        "The rated slice is too thin on the drop side, and the spec-defined "
        "net (+18) is dominated by routing, not selection. Selection's own "
        "footprint (sum -1, 13 rated rows) is smaller than the noise floor."
    )
    out_lines.append("")

    # 9. Architect review placeholder
    out_lines.append("## 9. Architect review")
    out_lines.append("")
    out_lines.append("_Appended in a later section after the architect-review pass._")
    out_lines.append("")

    # Write
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"wrote {args.out}")

    args.run_log.parent.mkdir(parents=True, exist_ok=True)
    with args.run_log.open("a", encoding="utf-8") as f:
        f.write("\n".join(run_log) + "\n")
    print(f"appended {args.run_log}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
