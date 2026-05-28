"""Counterfactual write-tier novelty gate replay.

Hypothesis: a cosine-similarity gate at write time would have skipped many
near-duplicate cards without losing useful content. Measure cost and gain
of each threshold against the current production memory store.

For each active memory_object M ordered by created_at:
  1. Resolve M's vector V via index_entries -> idmap -> usearch.
  2. Compute max cosine to its prior same-type same-container neighbors,
     under two pool definitions:
        - pool_recent_N (N=20, default)
        - pool_all
  3. For thresholds {0.70..0.90} count which would have been skipped.
  4. Bucket each skipped card by historical signal (relevant > injected >
     not_relevant > superseded > retrieved > never_retrieved).

Read-only on DB and vector index. No LLM calls. Writes only under .local/.

Usage:
    .venv/Scripts/python.exe -m evals.write_gate_replay.replay \\
        --out .local/research/write_gate_replay_2026-05-28.md
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


DEFAULT_THRESHOLDS = [0.70, 0.75, 0.80, 0.85, 0.90]
# `THRESHOLDS` is the runtime list (mutable so callers / CLI can override).
THRESHOLDS = list(DEFAULT_THRESHOLDS)
BUCKETS = [
    "relevant",
    "injected",
    "not_relevant",
    "superseded",
    "retrieved",
    "never_retrieved",
]
HISTOGRAM_BINS = [round(0.05 * i, 2) for i in range(21)]  # 0.00, 0.05, ..., 1.00

# Deterministic preference for a single vector per memory_object when multiple
# index_entries exist.
_TEXT_VIEW_PREFERENCE = [
    "memory_object.fact_embedding",
    "memory_object.fact_summary_embedding",
    "memory_object.investigation_context.embedding",
    "memory_object.decision_context.embedding",
    "memory_object.thread_summary_context.embedding",
    "memory_object.task_checkpoint_context.embedding",
    "memory_object.constraint_memory_context.embedding",
    "memory_object.interest_context.embedding",
    "memory_object.note_context.embedding",
]
_TEXT_VIEW_RANK = {n: i for i, n in enumerate(_TEXT_VIEW_PREFERENCE)}

PRIMARY_TYPES = [
    "atomic_fact",
    "fact_summary",
    "investigation_outcome",
    "decision",
    "thread_summary",
    "turn_summary",
]


@dataclass
class MemRow:
    mid: str
    type: str
    container: str
    subject: str
    created_at: str
    lifecycle: str
    vec: Optional[np.ndarray] = None  # L2-normalized 768-dim, or None


@dataclass
class GateResult:
    """Per-memory analysis result for one pool definition."""
    mid: str
    type: str
    container: str
    subject: str
    has_vector: bool
    max_cos: float = -1.0  # -1 if no prior neighbor or no vector
    nearest_subject: str = ""
    nearest_mid: str = ""
    bucket: str = ""  # filled later from history


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_memories(con: sqlite3.Connection, types: Optional[set[str]]) -> list[MemRow]:
    sql = """
    SELECT id, type, container_ref, subject, created_at, lifecycle
    FROM memory_objects
    WHERE lifecycle = 'active'
    """
    if types:
        placeholders = ",".join(["?"] * len(types))
        sql += f" AND type IN ({placeholders})"
        params = tuple(types)
    else:
        params = ()
    sql += " ORDER BY created_at ASC, id ASC"
    rows = con.execute(sql, params).fetchall()
    out = []
    for r in rows:
        out.append(
            MemRow(
                mid=r["id"],
                type=r["type"] or "",
                container=r["container_ref"] or "",
                subject=r["subject"] or "",
                created_at=r["created_at"] or "",
                lifecycle=r["lifecycle"] or "",
            )
        )
    return out


def attach_vectors(con: sqlite3.Connection, mems: list[MemRow], index_basename_path: Path) -> dict:
    """Attach a single deterministic vector per memory_object. Returns coverage stats.

    `index_basename_path` is the full path to the usearch index file (e.g.
    `~/.pallium/data/vector_index`). The sidecars are at
    `<basename>.idmap.json` and `<basename>.meta.json`.
    """
    # Pull all vector index entries for memory_objects.
    rows = con.execute(
        """
        SELECT id, target_id, text_view_name
        FROM index_entries
        WHERE target_kind='memory_object' AND index_type='vector'
        """,
    ).fetchall()
    by_mid: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for r in rows:
        by_mid[r["target_id"]].append((r["text_view_name"] or "", r["id"]))

    # Pick preferred entry id per memory.
    chosen_iid_by_mid: dict[str, str] = {}
    for mid, entries in by_mid.items():
        # Sort by preference rank (lower is better), then by iid for stability.
        entries.sort(key=lambda t: (_TEXT_VIEW_RANK.get(t[0], 999), t[1]))
        chosen_iid_by_mid[mid] = entries[0][1]

    # Load idmap.
    idmap_path = Path(f"{index_basename_path}.idmap.json")
    with open(idmap_path) as f:
        idmap = json.load(f)
    id_to_key = idmap["id_to_key"]

    # Load usearch index.
    from usearch.index import Index
    meta_path = Path(f"{index_basename_path}.meta.json")
    with open(meta_path) as f:
        meta = json.load(f)
    ndim = int(meta["dimensions"])
    idx = Index(ndim=ndim, metric="cos")
    idx.load(str(index_basename_path))

    coverage_total = 0
    coverage_with_vec = 0
    multi_entry_count = 0
    for m in mems:
        coverage_total += 1
        entries = by_mid.get(m.mid, [])
        if len(entries) > 1:
            multi_entry_count += 1
        iid = chosen_iid_by_mid.get(m.mid)
        if not iid:
            continue
        key = id_to_key.get(iid)
        if key is None:
            continue
        v = idx.get(int(key))
        if v is None:
            continue
        # Defensive normalize (already normalized by provider; cheap to verify).
        v = np.asarray(v, dtype=np.float32)
        norm = float(np.linalg.norm(v))
        if norm > 0:
            v = v / norm
        m.vec = v
        coverage_with_vec += 1

    return {
        "total": coverage_total,
        "with_vector": coverage_with_vec,
        "without_vector": coverage_total - coverage_with_vec,
        "multi_entry_memories": multi_entry_count,
        "ndim": ndim,
        "model": meta.get("model_name", ""),
        "index_entry_count": meta.get("entry_count", 0),
    }


# ---------------------------------------------------------------------------
# History (audit + feedback + supersedes)
# ---------------------------------------------------------------------------

def load_history(con: sqlite3.Connection) -> dict[str, dict]:
    """Build per-memory historical signal flags."""
    history: dict[str, dict] = defaultdict(lambda: {
        "rated_relevant": False,
        "rated_not_relevant": False,
        "injected": False,
        "retrieved": False,
        "superseded": False,
    })

    # Feedback ratings.
    rows = con.execute(
        "SELECT memory_object_id, rating FROM memory_feedback WHERE rating IN ('relevant','not_relevant')"
    ).fetchall()
    for r in rows:
        mid = r["memory_object_id"]
        if not mid:
            continue
        if r["rating"] == "relevant":
            history[mid]["rated_relevant"] = True
        elif r["rating"] == "not_relevant":
            history[mid]["rated_not_relevant"] = True

    # Audit candidate scores.
    rows = con.execute(
        "SELECT candidate_scores_json FROM query_audit_log WHERE candidate_scores_json IS NOT NULL"
    ).fetchall()
    for r in rows:
        try:
            cands = json.loads(r["candidate_scores_json"]) or []
        except (json.JSONDecodeError, TypeError):
            continue
        for c in cands:
            if not isinstance(c, dict):
                continue
            mid = c.get("memory_object_id")
            if not mid:
                continue
            history[mid]["retrieved"] = True
            if c.get("injected"):
                history[mid]["injected"] = True

    # Supersedes relations (incoming).
    rows = con.execute(
        "SELECT to_id FROM relations WHERE relation_type='supersedes' AND to_kind='memory_object'"
    ).fetchall()
    for r in rows:
        mid = r["to_id"]
        if mid:
            history[mid]["superseded"] = True

    # Lifecycle == superseded (won't show up here since we filtered active mems,
    # but include any lifecycle marker we can see for safety).
    rows = con.execute(
        "SELECT id, lifecycle FROM memory_objects WHERE lifecycle != 'active'"
    ).fetchall()
    for r in rows:
        if r["lifecycle"] == "superseded":
            history[r["id"]]["superseded"] = True

    return history


def classify_bucket(history: dict[str, dict], mid: str) -> str:
    h = history.get(mid)
    if not h:
        return "never_retrieved"
    if h.get("rated_relevant"):
        return "relevant"
    if h.get("injected"):
        return "injected"
    if h.get("rated_not_relevant"):
        return "not_relevant"
    if h.get("superseded"):
        return "superseded"
    if h.get("retrieved"):
        return "retrieved"
    return "never_retrieved"


# ---------------------------------------------------------------------------
# Gate analysis
# ---------------------------------------------------------------------------

def compute_gates(mems: list[MemRow], n_recent: int) -> tuple[list[GateResult], list[GateResult]]:
    """For each memory with a vector, compute max_cos against:
      - pool_recent_N: most recent N prior same-type same-container with vectors
      - pool_all: all prior same-type same-container with vectors

    Memories without vectors are returned with has_vector=False.
    """
    # Group keys: (type, container) -> list of (created_at, MemRow_with_vec)
    # We iterate mems in created_at ascending order (already sorted).
    # Maintain per-key matrix of stacked vectors and parallel list of MemRow refs.
    per_key_vecs: dict[tuple[str, str], np.ndarray] = {}
    per_key_mems: dict[tuple[str, str], list[MemRow]] = {}

    recent_results: list[GateResult] = []
    all_results: list[GateResult] = []

    for m in mems:
        if m.vec is None:
            r_rec = GateResult(
                mid=m.mid, type=m.type, container=m.container,
                subject=m.subject, has_vector=False,
            )
            r_all = GateResult(
                mid=m.mid, type=m.type, container=m.container,
                subject=m.subject, has_vector=False,
            )
            recent_results.append(r_rec)
            all_results.append(r_all)
            continue

        key = (m.type, m.container)
        prior_vecs = per_key_vecs.get(key)
        prior_mems = per_key_mems.get(key, [])

        max_cos_all = -1.0
        nearest_all_subj = ""
        nearest_all_mid = ""
        max_cos_rec = -1.0
        nearest_rec_subj = ""
        nearest_rec_mid = ""

        if prior_vecs is not None and len(prior_mems) > 0:
            # Cosine == dot product since both sides are unit-normalized.
            sims = prior_vecs @ m.vec  # shape (k,)
            # pool_all
            i_all = int(np.argmax(sims))
            max_cos_all = float(sims[i_all])
            nearest_all_subj = prior_mems[i_all].subject
            nearest_all_mid = prior_mems[i_all].mid
            # pool_recent_N: take the last N entries in prior_mems
            n = min(n_recent, len(prior_mems))
            sims_rec = sims[-n:]
            i_rec_local = int(np.argmax(sims_rec))
            i_rec = len(prior_mems) - n + i_rec_local
            max_cos_rec = float(sims_rec[i_rec_local])
            nearest_rec_subj = prior_mems[i_rec].subject
            nearest_rec_mid = prior_mems[i_rec].mid

        recent_results.append(GateResult(
            mid=m.mid, type=m.type, container=m.container,
            subject=m.subject, has_vector=True,
            max_cos=max_cos_rec,
            nearest_subject=nearest_rec_subj,
            nearest_mid=nearest_rec_mid,
        ))
        all_results.append(GateResult(
            mid=m.mid, type=m.type, container=m.container,
            subject=m.subject, has_vector=True,
            max_cos=max_cos_all,
            nearest_subject=nearest_all_subj,
            nearest_mid=nearest_all_mid,
        ))

        # Append m's vector to the running matrix for this key.
        v_row = m.vec.reshape(1, -1)
        if prior_vecs is None:
            per_key_vecs[key] = v_row.copy()
            per_key_mems[key] = [m]
        else:
            per_key_vecs[key] = np.vstack([prior_vecs, v_row])
            per_key_mems[key].append(m)

    return recent_results, all_results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def fmt_pct(num: int, den: int) -> str:
    if den <= 0:
        return "n/a"
    return f"{100.0 * num / den:.1f}%"


def matrix_for(results: list[GateResult], threshold: float) -> dict:
    """Compute skip stats and bucket counts for a single threshold over a result set.

    Only memories with vectors and a valid prior neighbor (max_cos >= 0) participate.
    """
    population = [r for r in results if r.has_vector and r.max_cos >= 0.0]
    no_prior = sum(1 for r in results if r.has_vector and r.max_cos < 0.0)
    no_vector = sum(1 for r in results if not r.has_vector)
    total = len(results)
    skipped = [r for r in population if r.max_cos >= threshold]
    counts = Counter(r.bucket for r in skipped)
    pop_counts = Counter(r.bucket for r in population)
    skipped_n = len(skipped)
    pop_n = len(population)
    cost_n = counts.get("relevant", 0) + counts.get("injected", 0)
    false_skip_rate = (cost_n / skipped_n) if skipped_n else 0.0
    pct_skipped = (skipped_n / pop_n) if pop_n else 0.0
    dedup_yield = pct_skipped * (1.0 - false_skip_rate)
    return {
        "threshold": threshold,
        "total_memories": total,
        "no_vector": no_vector,
        "no_prior_neighbor": no_prior,
        "population": pop_n,
        "skipped": skipped_n,
        "pct_skipped": pct_skipped,
        "false_skip_rate": false_skip_rate,
        "dedup_yield": dedup_yield,
        "cost_n": cost_n,
        "bucket_counts": dict(counts),
        "population_bucket_counts": dict(pop_counts),
    }


def histogram(results: list[GateResult]) -> list[int]:
    """Bin counts of max_cos into HISTOGRAM_BINS edges."""
    counts = [0] * (len(HISTOGRAM_BINS) - 1)
    for r in results:
        if not r.has_vector or r.max_cos < 0.0:
            continue
        c = r.max_cos
        # Clamp into [0,1]; e5 cosines may briefly go slightly negative for unrelated docs.
        if c < 0:
            c = 0.0
        if c > 1:
            c = 1.0
        idx = int(c / 0.05)
        if idx >= len(counts):
            idx = len(counts) - 1
        counts[idx] += 1
    return counts


def histogram_shape_summary(counts: list[int]) -> str:
    """Heuristic 2-sentence summary describing distribution shape."""
    total = sum(counts)
    if total == 0:
        return "No data."
    # Find peak bin
    peak_idx = max(range(len(counts)), key=lambda i: counts[i])
    peak_lo = HISTOGRAM_BINS[peak_idx]
    peak_hi = HISTOGRAM_BINS[peak_idx + 1]
    # Top heavy mass in 0.85-1.0?
    top_mass = sum(counts[17:])  # bins 0.85-1.00
    top_pct = 100.0 * top_mass / total if total else 0.0
    mid_mass = sum(counts[10:17])  # 0.50-0.85
    mid_pct = 100.0 * mid_mass / total if total else 0.0
    low_mass = sum(counts[:10])
    low_pct = 100.0 * low_mass / total if total else 0.0

    # Bimodality: peak in top region AND meaningful mass below 0.7?
    bimodal = top_pct >= 25.0 and (low_pct + mid_pct) >= 25.0
    smeared = 0.20 <= top_pct <= 0.5 and mid_pct >= 30.0 and not bimodal
    flat = max(counts) / total < 0.20

    if bimodal:
        shape = (
            f"Bimodal: peak in {peak_lo:.2f}-{peak_hi:.2f} with {top_pct:.0f}% mass at "
            f"cos>=0.85 and {(low_pct+mid_pct):.0f}% spread below 0.85 — clear duplicate "
            "cluster plus a unique tail. A vector gate has a defensible cutoff here."
        )
    elif top_pct >= 50.0:
        shape = (
            f"Heavily right-shifted: {top_pct:.0f}% of cards already have a near-duplicate "
            f"at cos>=0.85 (peak {peak_lo:.2f}-{peak_hi:.2f}). Unique novelty is rare; "
            "even an aggressive gate skips a large fraction of writes."
        )
    elif smeared or flat:
        shape = (
            f"Smeared: max-cos is broadly distributed (peak {peak_lo:.2f}-{peak_hi:.2f}, "
            f"top {top_pct:.0f}% / mid {mid_pct:.0f}% / low {low_pct:.0f}%). No clean "
            "separation between duplicate and novel writes — the gate is fragile here."
        )
    else:
        shape = (
            f"Distribution peak at {peak_lo:.2f}-{peak_hi:.2f}; mass split "
            f"top={top_pct:.0f}% mid={mid_pct:.0f}% low={low_pct:.0f}%. "
            "Gate selectivity depends strongly on threshold choice."
        )
    return shape


def render_matrix_block(label: str, m: dict) -> list[str]:
    lines = []
    lines.append(f"**{label}**")
    lines.append("")
    lines.append(
        f"- population (has vector + has prior neighbor): {m['population']} "
        f"(no_vector={m['no_vector']}, no_prior_neighbor={m['no_prior_neighbor']})"
    )
    lines.append(
        f"- cards_skipped: {m['skipped']}  "
        f"pct_skipped: {m['pct_skipped']*100:.1f}%  "
        f"false_skip_rate: {m['false_skip_rate']*100:.1f}%  "
        f"dedup_yield: {m['dedup_yield']*100:.1f}%"
    )
    bc = m["bucket_counts"]
    lines.append(
        "- skipped buckets: "
        + ", ".join(f"{b}={bc.get(b,0)}" for b in BUCKETS)
    )
    lines.append("")
    return lines


def render_histogram(counts: list[int], label: str) -> list[str]:
    lines = []
    lines.append(f"**{label}** (max_cos histogram, bin width 0.05)")
    lines.append("")
    lines.append("| bin | count | bar |")
    lines.append("|---|---:|---|")
    total = sum(counts) or 1
    max_c = max(counts) if counts else 1
    for i, c in enumerate(counts):
        lo = HISTOGRAM_BINS[i]
        hi = HISTOGRAM_BINS[i + 1]
        bar_len = int(round(40 * c / max_c)) if max_c else 0
        lines.append(f"| {lo:.2f}-{hi:.2f} | {c} | {'#' * bar_len} |")
    lines.append("")
    lines.append(f"_{histogram_shape_summary(counts)}_")
    lines.append("")
    return lines


def render_report(
    *,
    db_path: str,
    vec_dir: str,
    coverage: dict,
    mems: list[MemRow],
    types_by_count: list[tuple[str, int]],
    coverage_by_type: dict[str, dict],
    recent_results: list[GateResult],
    all_results: list[GateResult],
    n_recent: int,
    timestamp: str,
) -> str:
    lines: list[str] = []
    lines.append("# Write-Tier Novelty Gate Replay")
    lines.append("")
    lines.append(f"- Run timestamp: `{timestamp}`")
    lines.append(f"- DB: `{db_path}`")
    lines.append(f"- Vector index basename: `{vec_dir}`")
    lines.append(f"- Embedding model: `{coverage['model']}` ({coverage['ndim']} dims)")
    lines.append(f"- Index entry count: {coverage['index_entry_count']}")
    lines.append(f"- Total active memory_objects analyzed: {len(mems)}")
    lines.append(f"- N (recent-pool size): {n_recent}")
    lines.append("")
    lines.append("Totals per type (active):")
    lines.append("")
    lines.append("| type | count |")
    lines.append("|---|---:|")
    for t, c in types_by_count:
        lines.append(f"| {t} | {c} |")
    lines.append("")

    lines.append("## Coverage caveat")
    lines.append("")
    lines.append(
        "Some memory types have low vectorization coverage in this DB. Results for "
        "those types reflect only the vectorized subset — treat per-type numbers as a "
        "partial sample. This vectorization gap is itself a finding: types without a "
        "vector are invisible to any cosine-based novelty gate without a re-embed pass."
    )
    lines.append("")
    lines.append("| type | total | has_vector | no_vector | coverage |")
    lines.append("|---|---:|---:|---:|---:|")
    for t, _ in types_by_count:
        s = coverage_by_type.get(t, {})
        tot = s.get("total", 0)
        hv = s.get("has_vector", 0)
        nv = tot - hv
        pct = (100.0 * hv / tot) if tot else 0.0
        lines.append(f"| {t} | {tot} | {hv} | {nv} | {pct:.1f}% |")
    lines.append("")

    # 2x2 matrix per threshold (overall).
    lines.append("## 2x2 matrix per threshold (overall)")
    lines.append("")
    lines.append(
        "For each threshold τ, a card is 'skipped' if its max cosine to a prior "
        "same-type same-container neighbor is >= τ. Bucket precedence on skipped "
        "cards: relevant > injected > not_relevant > superseded > retrieved > "
        "never_retrieved. `false_skip_rate = (relevant+injected)/skipped`. "
        "`dedup_yield = pct_skipped * (1 - false_skip_rate)`."
    )
    lines.append("")
    lines.append("| τ | pool | population | skipped | pct_skipped | false_skip_rate | dedup_yield |")
    lines.append("|---:|---|---:|---:|---:|---:|---:|")
    for tau in THRESHOLDS:
        for label, results in [("recent_N", recent_results), ("all", all_results)]:
            m = matrix_for(results, tau)
            lines.append(
                f"| {tau:.2f} | {label} | {m['population']} | {m['skipped']} | "
                f"{m['pct_skipped']*100:.1f}% | {m['false_skip_rate']*100:.1f}% | "
                f"{m['dedup_yield']*100:.1f}% |"
            )
    lines.append("")

    # Detailed skip-bucket breakdown per threshold.
    lines.append("### Skipped-card bucket breakdown")
    lines.append("")
    lines.append(
        "| τ | pool | "
        + " | ".join(BUCKETS)
        + " |"
    )
    lines.append("|---:|---|" + "---:|" * len(BUCKETS))
    for tau in THRESHOLDS:
        for label, results in [("recent_N", recent_results), ("all", all_results)]:
            m = matrix_for(results, tau)
            bc = m["bucket_counts"]
            row = f"| {tau:.2f} | {label} | " + " | ".join(str(bc.get(b, 0)) for b in BUCKETS) + " |"
            lines.append(row)
    lines.append("")

    # Per-type breakdown for primary types.
    lines.append("## Per-type breakdown (primary types)")
    lines.append("")
    for t in PRIMARY_TYPES:
        type_recent = [r for r in recent_results if r.type == t]
        type_all = [r for r in all_results if r.type == t]
        n_with_vec = sum(1 for r in type_recent if r.has_vector)
        if n_with_vec == 0:
            lines.append(f"### {t}")
            lines.append("")
            lines.append(f"_No vectorized memories of this type — skipping._")
            lines.append("")
            continue
        lines.append(f"### {t}")
        lines.append("")
        lines.append(
            f"- vectorized in this type: {n_with_vec}"
        )
        lines.append("")
        lines.append("| τ | pool | population | skipped | pct_skipped | false_skip_rate | dedup_yield |")
        lines.append("|---:|---|---:|---:|---:|---:|---:|")
        for tau in THRESHOLDS:
            for label, results in [("recent_N", type_recent), ("all", type_all)]:
                m = matrix_for(results, tau)
                lines.append(
                    f"| {tau:.2f} | {label} | {m['population']} | {m['skipped']} | "
                    f"{m['pct_skipped']*100:.1f}% | {m['false_skip_rate']*100:.1f}% | "
                    f"{m['dedup_yield']*100:.1f}% |"
                )
        lines.append("")

    # Cosine distribution histograms.
    lines.append("## Cosine distribution histograms")
    lines.append("")
    lines.append("Distribution of max_cos values (using `pool_all`) across the population.")
    lines.append("")
    lines.extend(render_histogram(histogram(all_results), "Overall"))
    for t in PRIMARY_TYPES:
        type_all = [r for r in all_results if r.type == t]
        if not any(r.has_vector and r.max_cos >= 0 for r in type_all):
            continue
        lines.extend(render_histogram(histogram(type_all), f"{t}"))

    # Top-20 false-skip examples at the lowest active threshold (skipped + rated relevant).
    sample_tau = THRESHOLDS[0] if THRESHOLDS else 0.85
    lines.append(f"## Top-20 false-skip examples at τ={sample_tau:.2f}")
    lines.append("")
    lines.append(
        f"Cards that would be skipped at τ={sample_tau:.2f} (pool_all) and were rated relevant."
    )
    lines.append("")
    lines.append("| subject | type | container | max_cos | nearest_subject |")
    lines.append("|---|---|---|---:|---|")
    false_skips = [
        r for r in all_results
        if r.has_vector and r.max_cos >= sample_tau and r.bucket == "relevant"
    ]
    false_skips.sort(key=lambda r: -r.max_cos)
    if not false_skips:
        lines.append("| _(none)_ | | | | |")
    else:
        for r in false_skips[:20]:
            lines.append(
                f"| {(r.subject or '')[:60]} | {r.type} | {(r.container or '')[:40]} "
                f"| {r.max_cos:.3f} | {(r.nearest_subject or '')[:60]} |"
            )
    lines.append("")

    # Top-20 good-skip examples at the lowest active threshold (skipped + rated NR).
    lines.append(f"## Top-20 good-skip examples at τ={sample_tau:.2f}")
    lines.append("")
    lines.append(
        f"Cards that would be skipped at τ={sample_tau:.2f} (pool_all) and were rated not_relevant."
    )
    lines.append("")
    lines.append("| subject | type | container | max_cos | nearest_subject |")
    lines.append("|---|---|---|---:|---|")
    good_skips = [
        r for r in all_results
        if r.has_vector and r.max_cos >= sample_tau and r.bucket == "not_relevant"
    ]
    good_skips.sort(key=lambda r: -r.max_cos)
    if not good_skips:
        lines.append("| _(none)_ | | | | |")
    else:
        for r in good_skips[:20]:
            lines.append(
                f"| {(r.subject or '')[:60]} | {r.type} | {(r.container or '')[:40]} "
                f"| {r.max_cos:.3f} | {(r.nearest_subject or '')[:60]} |"
            )
    lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _safe_outpath(path: Path) -> Path:
    """Refuse to write outside .local/."""
    abs_path = path.resolve()
    project_root = _PROJECT_ROOT.resolve()
    try:
        rel = abs_path.relative_to(project_root)
    except ValueError:
        raise SystemExit(
            f"Refusing to write outside project root: {abs_path}"
        )
    parts = rel.parts
    if not parts or parts[0] != ".local":
        raise SystemExit(
            f"Refusing to write outside .local/: {abs_path}"
        )
    return abs_path


def _resolve_index_basename_path(vector_index_arg: str, index_basename: str) -> Path:
    """Resolve the full path to the usearch index basename file.

    Priority:
      1. Env var `PALLIUM_VECTOR_INDEX_PATH` (matches the runtime override at
         `app/cli/service.py`). When set, its value wins outright so the eval
         always points at whatever the live service is using.
      2. `--vector-index` value: if it points at an existing file or ends in
         `.index` (legacy form like `pallium_vector.index`), treat it as the
         full basename path. Otherwise treat it as a directory and resolve
         `<dir>/<index_basename>` (default basename `vector_index`, matching
         the production runtime default at `app/cli/service.py:40`).
    """
    env_path = os.environ.get("PALLIUM_VECTOR_INDEX_PATH")
    if env_path:
        return Path(env_path).expanduser().resolve()

    p = Path(vector_index_arg).expanduser()
    # If the arg points at an existing file, or its basename ends in .index,
    # treat it as a full basename path.
    if p.is_file() or p.name.endswith(".index"):
        return p.resolve()
    # Otherwise it's a directory.
    return (p / index_basename).resolve()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--db",
        default=str(Path.home() / ".pallium" / "data" / "pallium.db"),
    )
    ap.add_argument(
        "--vector-index",
        default=str(Path.home() / ".pallium" / "data"),
        help=(
            "Path to the usearch vector index. Accepts either a directory "
            "(in which case `--index-basename` picks the file inside) or a "
            "full file path (a value ending in `.index` or pointing at an "
            "existing file is treated as a full basename path). Overridden "
            "by env var PALLIUM_VECTOR_INDEX_PATH if set."
        ),
    )
    ap.add_argument(
        "--index-basename",
        default="vector_index",
        help=(
            "Basename of the usearch index file inside `--vector-index` when "
            "that arg is a directory. Default `vector_index` matches the "
            "production runtime (app/cli/service.py)."
        ),
    )
    ap.add_argument("--n", type=int, default=20, help="recent-pool size N")
    ap.add_argument(
        "--out",
        default=".local/research/write_gate_replay_2026-05-28.md",
    )
    ap.add_argument(
        "--types",
        default=None,
        help="Comma-separated list of memory types to include (default: all active)",
    )
    ap.add_argument(
        "--thresholds",
        default=None,
        help=(
            "Comma-separated list of cosine thresholds (e.g. '0.85,0.90,0.95'). "
            f"Default: {','.join(f'{t:.2f}' for t in DEFAULT_THRESHOLDS)}"
        ),
    )
    args = ap.parse_args()

    out_path = _safe_outpath(Path(args.out))
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Apply --thresholds override (mutates module-level THRESHOLDS so all
    # downstream rendering picks it up).
    if args.thresholds:
        try:
            taus = [float(t.strip()) for t in args.thresholds.split(",") if t.strip()]
        except ValueError as e:
            raise SystemExit(f"Invalid --thresholds value: {e}")
        if not taus:
            raise SystemExit("--thresholds parsed to an empty list")
        for t in taus:
            if not (0.0 <= t <= 1.0):
                raise SystemExit(f"Threshold out of [0,1]: {t}")
        THRESHOLDS[:] = sorted(taus)

    db_path = args.db
    vec_dir = Path(args.vector_index)
    index_basename_path = _resolve_index_basename_path(args.vector_index, args.index_basename)
    types = None
    if args.types:
        types = {t.strip() for t in args.types.split(",") if t.strip()}

    # Surface the resolved index path + entry count up front so future
    # path-mismatch bugs (e.g. an orphaned snapshot vs the live index)
    # are visible immediately.
    meta_for_print = Path(f"{index_basename_path}.meta.json")
    if not index_basename_path.exists():
        raise SystemExit(
            f"Vector index file not found: {index_basename_path}\n"
            f"  --vector-index={args.vector_index!r} --index-basename={args.index_basename!r}\n"
            f"  PALLIUM_VECTOR_INDEX_PATH={os.environ.get('PALLIUM_VECTOR_INDEX_PATH', '<unset>')!r}"
        )
    if not meta_for_print.exists():
        raise SystemExit(f"Vector index meta sidecar not found: {meta_for_print}")
    try:
        _meta_preview = json.loads(meta_for_print.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise SystemExit(f"Could not read meta sidecar {meta_for_print}: {e}")
    print(
        f"Resolved vector index: {index_basename_path}  "
        f"(entries={_meta_preview.get('entry_count', '?')}, "
        f"model={_meta_preview.get('model_name', '?')}, "
        f"dims={_meta_preview.get('dimensions', '?')})"
    )

    # Read-only connection (URI mode).
    con_uri = f"file:{db_path}?mode=ro"
    con = sqlite3.connect(con_uri, uri=True)
    con.row_factory = sqlite3.Row

    print(f"Loading active memory_objects from {db_path} ...")
    mems = load_memories(con, types)
    print(f"  loaded {len(mems)} memories")

    print("Attaching vectors ...")
    coverage = attach_vectors(con, mems, index_basename_path)
    print(
        f"  with vector: {coverage['with_vector']}/{coverage['total']}  "
        f"(model={coverage['model']}, ndim={coverage['ndim']})"
    )

    # Per-type counts for header + coverage table.
    type_counter: Counter[str] = Counter()
    type_coverage: dict[str, dict] = defaultdict(lambda: {"total": 0, "has_vector": 0})
    for m in mems:
        type_counter[m.type] += 1
        type_coverage[m.type]["total"] += 1
        if m.vec is not None:
            type_coverage[m.type]["has_vector"] += 1
    types_by_count = type_counter.most_common()

    print("Loading historical signal (audit + feedback + supersedes) ...")
    history = load_history(con)
    con.close()

    print(f"Computing gate cosines (N_recent={args.n}) ...")
    recent_results, all_results = compute_gates(mems, args.n)

    # Stamp buckets onto each result.
    for r in recent_results:
        r.bucket = classify_bucket(history, r.mid)
    for r in all_results:
        r.bucket = classify_bucket(history, r.mid)

    # Build report.
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).isoformat()
    md = render_report(
        db_path=db_path,
        vec_dir=str(index_basename_path),
        coverage=coverage,
        mems=mems,
        types_by_count=types_by_count,
        coverage_by_type=type_coverage,
        recent_results=recent_results,
        all_results=all_results,
        n_recent=args.n,
        timestamp=ts,
    )
    out_path.write_text(md, encoding="utf-8")
    print(f"\nReport written to {out_path}")

    # Print headline table to stdout.
    print()
    print("Headline (overall):")
    print(f"  {'tau':>5}  {'pool':<10}  {'pct_skipped':>12}  {'false_skip':>10}  {'dedup_yield':>12}")
    for tau in THRESHOLDS:
        for label, results in [("recent_N", recent_results), ("all", all_results)]:
            m = matrix_for(results, tau)
            print(
                f"  {tau:>5.2f}  {label:<10}  "
                f"{m['pct_skipped']*100:>11.1f}%  "
                f"{m['false_skip_rate']*100:>9.1f}%  "
                f"{m['dedup_yield']*100:>11.1f}%"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
