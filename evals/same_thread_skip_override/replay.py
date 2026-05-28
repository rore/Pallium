"""Offline replay analysis of `same_thread_context_sufficient` skips.

Hypothesis: the same-thread-local-context suppression policy fires too eagerly.
When a same-thread local candidate qualifies as "local state", suppression
triggers even when a stronger cross-thread carry-forward candidate exists.

This script is read-only against the live Pallium DB and writes reports to
`.local/research/`. No production code changes, no LLM calls.

Run:
    python -m evals.same_thread_skip_override.replay
"""

from __future__ import annotations

import collections
import json
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# Production helpers (pure functions, no IO)
from core.subject import subject_text_for_payload
from core.text import normalize_for_index


LIVE_DB = Path.home() / ".pallium" / "data" / "pallium.db"
SINCE = "2026-05-18"
REPO_ROOT = Path(__file__).resolve().parents[2]
RESEARCH_DIR = REPO_ROOT / ".local" / "research"
DATE_TAG = "2026-05-28"
REPORT_PATH = RESEARCH_DIR / f"same_thread_skip_override_{DATE_TAG}.md"
RAW_PATH = RESEARCH_DIR / f"_same_thread_override_run.md"

NOISE_TYPES = {"turn_summary", "atomic_fact"}
SUPPORTED_OVERRIDE_TYPES = {"task_checkpoint", "decision", "investigation_outcome"}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def open_ro(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def load_audit_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    cur = conn.execute(
        """
        SELECT id, created_at, query_text, thread_ref, container_ref,
               actor_ref, candidate_scores_json, injected_blocks_json,
               injection_method
        FROM query_audit_log
        WHERE decision_reason = 'same_thread_context_sufficient'
          AND created_at >= ?
        ORDER BY created_at ASC
        """,
        (SINCE,),
    )
    return cur.fetchall()


def build_memory_index(conn: sqlite3.Connection, mids: set[str]) -> dict[str, dict[str, Any]]:
    """Map memory_object_id -> {type, payload, container_ref, freshness_at}.

    Skip null/empty.
    """
    if not mids:
        return {}
    out: dict[str, dict[str, Any]] = {}
    # batch in chunks
    chunk = 500
    mid_list = list(mids)
    for i in range(0, len(mid_list), chunk):
        sub = mid_list[i : i + chunk]
        placeholders = ",".join("?" * len(sub))
        cur = conn.execute(
            f"""
            SELECT id, type, payload_json, container_ref, freshness_at
            FROM memory_objects
            WHERE id IN ({placeholders})
            """,
            sub,
        )
        for r in cur.fetchall():
            payload: Any
            try:
                payload = json.loads(r["payload_json"] or "{}")
            except Exception:
                payload = {}
            out[r["id"]] = {
                "type": r["type"],
                "payload": payload if isinstance(payload, dict) else {},
                "container_ref": r["container_ref"],
                "freshness_at": r["freshness_at"],
            }
    return out


def build_thread_index(conn: sqlite3.Connection, mids: set[str]) -> dict[str, set[str]]:
    """Map memory_object_id -> set of thread_refs (via relations -> source_items)."""
    if not mids:
        return {}
    out: dict[str, set[str]] = {m: set() for m in mids}
    chunk = 500
    mid_list = list(mids)
    for i in range(0, len(mid_list), chunk):
        sub = mid_list[i : i + chunk]
        placeholders = ",".join("?" * len(sub))
        cur = conn.execute(
            f"""
            SELECT r.from_id AS mid, s.thread_ref AS tref
            FROM relations r
            JOIN source_items s ON s.id = r.to_id
            WHERE r.from_kind = 'memory_object'
              AND r.to_kind = 'source_item'
              AND r.relation_type = 'supported_by'
              AND r.from_id IN ({placeholders})
            """,
            sub,
        )
        for r in cur.fetchall():
            mid = r["mid"]
            tref = r["tref"]
            if tref:
                out.setdefault(mid, set()).add(tref)
    return out


def build_feedback_index(conn: sqlite3.Connection, mids: set[str]) -> dict[str, dict[str, int]]:
    """Map memory_object_id -> {'relevant': N, 'not_relevant': N}."""
    if not mids:
        return {}
    out: dict[str, dict[str, int]] = {}
    chunk = 500
    mid_list = list(mids)
    for i in range(0, len(mid_list), chunk):
        sub = mid_list[i : i + chunk]
        placeholders = ",".join("?" * len(sub))
        cur = conn.execute(
            f"""
            SELECT memory_object_id, rating, COUNT(*) AS n
            FROM memory_feedback
            WHERE memory_object_id IN ({placeholders})
            GROUP BY memory_object_id, rating
            """,
            sub,
        )
        for r in cur.fetchall():
            d = out.setdefault(r["memory_object_id"], {"relevant": 0, "not_relevant": 0})
            d[r["rating"]] = d.get(r["rating"], 0) + r["n"]
    return out


# ---------------------------------------------------------------------------
# Tokenization helpers
# ---------------------------------------------------------------------------


def tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    return {t for t in normalize_for_index(text).split() if t}


def memory_subject_text(meta: dict[str, Any] | None) -> str:
    if not meta:
        return ""
    payload = meta.get("payload") or {}
    subj = subject_text_for_payload(meta.get("type"), payload)
    if subj:
        return subj
    # fallback: flatten payload string values
    parts: list[str] = []
    for v in payload.values():
        if isinstance(v, str):
            parts.append(v)
    return " ".join(parts)[:400]


# ---------------------------------------------------------------------------
# Override evaluation
# ---------------------------------------------------------------------------


@dataclass
class CandClassified:
    candidate: dict[str, Any]
    memory_object_id: str | None
    layer: str
    type: str | None
    subject: str
    subject_tokens: set[str]
    overlap: int
    same_thread: bool | None  # None when unknown (source_evidence)
    is_low_value: bool
    eligible_override_type: bool


def classify_candidate(
    cand: dict[str, Any],
    audit_thread: str,
    memo_index: dict[str, dict[str, Any]],
    thread_index: dict[str, set[str]],
    query_tokens: set[str],
) -> CandClassified:
    mid = cand.get("memory_object_id")
    layer = str(cand.get("layer") or "")
    cand_type = cand.get("memory_type")
    meta = memo_index.get(mid) if mid else None
    if meta and not cand_type:
        cand_type = meta["type"]

    subject = memory_subject_text(meta) if meta else ""
    subj_tokens = tokens(subject)
    overlap = len(query_tokens & subj_tokens) if query_tokens else 0

    # same_thread classification
    if mid:
        threads = thread_index.get(mid, set())
        if not threads:
            same_thread: bool | None = None  # no thread evidence
        else:
            same_thread = audit_thread in threads
    else:
        # source_evidence: audit log doesn't carry source_item_id; we can't classify
        same_thread = None

    # low value
    payload = (meta or {}).get("payload") or {}
    is_low_value = bool(payload.get("low_value_meta"))
    if cand_type in NOISE_TYPES:
        is_low_value = True

    eligible_override_type = cand_type in SUPPORTED_OVERRIDE_TYPES and bool(payload)

    return CandClassified(
        candidate=cand,
        memory_object_id=mid,
        layer=layer,
        type=cand_type,
        subject=subject,
        subject_tokens=subj_tokens,
        overlap=overlap,
        same_thread=same_thread,
        is_low_value=is_low_value,
        eligible_override_type=eligible_override_type,
    )


@dataclass
class RowDecision:
    audit_id: str
    container_ref: str | None
    thread_ref: str | None
    query_text: str
    same_thread_top: CandClassified | None
    cross_thread_top: CandClassified | None
    n_same_thread: int
    n_cross_thread: int
    n_unknown_thread: int  # source_evidence with no thread evidence
    would_override: bool
    override_reason: str
    overlap_delta: int  # cross_top.overlap - same_top.overlap (0 if either None)


def evaluate_row(
    audit_row: sqlite3.Row,
    memo_index: dict[str, dict[str, Any]],
    thread_index: dict[str, set[str]],
) -> tuple[RowDecision, list[CandClassified]]:
    cands_raw = json.loads(audit_row["candidate_scores_json"] or "[]")
    audit_thread = audit_row["thread_ref"] or ""
    qtok = tokens(audit_row["query_text"])

    classified = [
        classify_candidate(c, audit_thread, memo_index, thread_index, qtok)
        for c in cands_raw
    ]

    same = [c for c in classified if c.same_thread is True]
    cross = [c for c in classified if c.same_thread is False]
    unknown = [c for c in classified if c.same_thread is None]

    def _rank(c: CandClassified) -> tuple[int, int, int]:
        # higher overlap, then higher routing_score (positive), then lower routing_rank
        rscore = int(c.candidate.get("routing_score") or 0)
        rrank = int(c.candidate.get("routing_rank") or 9999)
        return (-c.overlap, -rscore, rrank)

    same_top = sorted(same, key=_rank)[0] if same else None
    cross_top = sorted(cross, key=_rank)[0] if cross else None

    overlap_same = same_top.overlap if same_top else 0
    overlap_cross = cross_top.overlap if cross_top else 0
    overlap_delta = overlap_cross - overlap_same

    would_override = False
    reason = "no_override"

    # Codex's rule: 3 conjunctive conditions
    if cross_top is None:
        reason = "no_cross_thread_candidate"
    elif cross_top.is_low_value:
        reason = "cross_thread_low_value"
    elif not cross_top.eligible_override_type:
        reason = f"cross_thread_type_not_eligible:{cross_top.type}"
    else:
        # Condition 1: cross beats same OR no qualifying same-thread overlap
        cond1_no_same_overlap = same_top is None or same_top.overlap < 2
        cond1_cross_stronger = overlap_cross >= overlap_same + 2
        if not (cond1_no_same_overlap or cond1_cross_stronger):
            reason = (
                f"same_thread_holds_overlap (same={overlap_same} cross={overlap_cross})"
            )
        else:
            # Condition 3: payload non-empty was already checked via eligible_override_type;
            # we accept task_checkpoint/decision/investigation_outcome with non-empty payload.
            would_override = True
            if cond1_cross_stronger and not cond1_no_same_overlap:
                reason = "cross_overlap_materially_stronger"
            elif cond1_no_same_overlap:
                reason = "no_qualifying_same_thread_overlap"

    decision = RowDecision(
        audit_id=audit_row["id"],
        container_ref=audit_row["container_ref"],
        thread_ref=audit_row["thread_ref"],
        query_text=audit_row["query_text"] or "",
        same_thread_top=same_top,
        cross_thread_top=cross_top,
        n_same_thread=len(same),
        n_cross_thread=len(cross),
        n_unknown_thread=len(unknown),
        would_override=would_override,
        override_reason=reason,
        overlap_delta=overlap_delta,
    )
    return decision, classified


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def fmt_pct(n: int, d: int) -> str:
    return f"{(100.0 * n / d):.1f}%" if d else "n/a"


def short(s: str | None, n: int = 80) -> str:
    if not s:
        return ""
    s = s.replace("\n", " ").replace("\r", " ")
    return s if len(s) <= n else s[: n - 3] + "..."


def write_report(
    decisions: list[RowDecision],
    feedback_index: dict[str, dict[str, int]],
    raw_log_lines: list[str],
) -> None:
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    total = len(decisions)
    overrides = [d for d in decisions if d.would_override]
    n_override = len(overrides)
    n_kept = total - n_override

    # Distinct memory IDs that would have been promoted
    promoted_mids = {
        d.cross_thread_top.memory_object_id
        for d in overrides
        if d.cross_thread_top and d.cross_thread_top.memory_object_id
    }
    promoted_threads: set[str] = set()
    for d in overrides:
        if d.cross_thread_top and d.cross_thread_top.memory_object_id:
            # Use the memory's threads set
            pass
    # We track threads via classification: collect per-row cross thread refs
    # (we don't have that here directly — recompute below if needed)

    # Per-container
    by_container: dict[str, dict[str, int]] = collections.defaultdict(
        lambda: {"total": 0, "override": 0}
    )
    for d in decisions:
        c = d.container_ref or "(none)"
        by_container[c]["total"] += 1
        if d.would_override:
            by_container[c]["override"] += 1

    # Histogram of overlap_delta on rows with both pools present
    delta_rows = [
        d for d in decisions if d.same_thread_top is not None and d.cross_thread_top is not None
    ]
    delta_hist: collections.Counter[int] = collections.Counter()
    for d in delta_rows:
        delta_hist[d.overlap_delta] += 1

    # Reasons distribution
    reason_hist = collections.Counter(d.override_reason for d in decisions)

    # Override-type breakdown
    override_type_hist = collections.Counter(
        (d.cross_thread_top.type if d.cross_thread_top else "?") for d in overrides
    )

    # Pool-population: which rows have any cross-thread candidate at all?
    rows_with_cross = [d for d in decisions if d.cross_thread_top is not None]
    rows_with_same = [d for d in decisions if d.same_thread_top is not None]

    # Feedback precision proxy
    fb_relevant = 0
    fb_not_relevant = 0
    fb_seen = 0
    for mid in promoted_mids:
        fb = feedback_index.get(mid)
        if not fb:
            continue
        fb_seen += 1
        fb_relevant += fb.get("relevant", 0)
        fb_not_relevant += fb.get("not_relevant", 0)

    # Sample 20 qualitative examples — bias toward overrides + diversity of reasons
    samples: list[RowDecision] = []
    seen_reasons: set[str] = set()
    for d in overrides:
        if d.override_reason not in seen_reasons:
            samples.append(d)
            seen_reasons.add(d.override_reason)
        if len(samples) >= 10:
            break
    # Fill with non-overrides
    for d in decisions:
        if len(samples) >= 20:
            break
        if d in samples:
            continue
        samples.append(d)
    samples = samples[:20]

    lines: list[str] = []
    lines.append(f"# `same_thread_context_sufficient` skip override replay — {DATE_TAG}\n")
    lines.append(f"DB: `{LIVE_DB}`\n")
    lines.append(f"Window: created_at >= `{SINCE}`\n")
    lines.append("")
    lines.append("## Headline numbers\n")
    lines.append(f"- total skip rows analyzed: **{total}**")
    lines.append(
        f"- skip kept (no override): **{n_kept}** ({fmt_pct(n_kept, total)})"
    )
    lines.append(
        f"- override would inject: **{n_override}** ({fmt_pct(n_override, total)})"
    )
    lines.append(
        f"- distinct memories that would have been promoted: **{len(promoted_mids)}**"
    )
    lines.append("")
    lines.append("### Caveat — pool population\n")
    lines.append(
        f"- rows with at least one same-thread candidate: **{len(rows_with_same)}** ({fmt_pct(len(rows_with_same), total)})"
    )
    lines.append(
        f"- rows with at least one cross-thread candidate (memory_hit only): **{len(rows_with_cross)}** ({fmt_pct(len(rows_with_cross), total)})"
    )
    lines.append(
        "- `source_evidence` candidates lack `memory_object_id` in the audit log → no thread mapping. "
        "This analysis only sees structured-memory candidates (decision, investigation_outcome, "
        "task_checkpoint, thread_summary, constraint_memory, atomic_fact).\n"
    )
    lines.append("## Override reason distribution\n")
    for reason, n in reason_hist.most_common():
        lines.append(f"- `{reason}`: {n} ({fmt_pct(n, total)})")
    lines.append("")
    lines.append("## Override type breakdown (the cross-thread candidate that would inject)\n")
    for t, n in override_type_hist.most_common():
        lines.append(f"- `{t}`: {n}")
    lines.append("")
    lines.append("## Per-container breakdown\n")
    lines.append("| container | total | override | rate |")
    lines.append("|---|---:|---:|---:|")
    for c, d in sorted(by_container.items(), key=lambda kv: -kv[1]["total"]):
        lines.append(
            f"| `{c}` | {d['total']} | {d['override']} | {fmt_pct(d['override'], d['total'])} |"
        )
    lines.append("")
    lines.append("## Overlap delta histogram (cross_top.overlap − same_top.overlap)\n")
    lines.append(f"Rows where both pools have a candidate: {len(delta_rows)}\n")
    lines.append("| delta | count |")
    lines.append("|---:|---:|")
    for k in sorted(delta_hist.keys()):
        lines.append(f"| {k} | {delta_hist[k]} |")
    lines.append("")
    lines.append("## Feedback precision proxy\n")
    lines.append(
        f"- promoted memories with any feedback: **{fb_seen}** / {len(promoted_mids)}"
    )
    lines.append(f"- relevant ratings: **{fb_relevant}**")
    lines.append(f"- not_relevant ratings: **{fb_not_relevant}**")
    if (fb_relevant + fb_not_relevant) > 0:
        lines.append(
            f"- precision proxy (relevant / total): "
            f"**{fmt_pct(fb_relevant, fb_relevant + fb_not_relevant)}**"
        )
    lines.append("")
    lines.append("## Sampled qualitative examples\n")
    for i, d in enumerate(samples, 1):
        lines.append(f"### Example {i} — audit `{d.audit_id[:8]}` — {'OVERRIDE' if d.would_override else 'KEEP'}\n")
        lines.append(f"- container: `{d.container_ref}`")
        lines.append(f"- thread: `{d.thread_ref}`")
        lines.append(f"- query: `{short(d.query_text, 200)}`")
        lines.append(f"- same-thread top: " + (
            f"type={d.same_thread_top.type} overlap={d.same_thread_top.overlap} subj=`{short(d.same_thread_top.subject, 120)}`"
            if d.same_thread_top else "(none)"
        ))
        lines.append(f"- cross-thread top: " + (
            f"type={d.cross_thread_top.type} overlap={d.cross_thread_top.overlap} subj=`{short(d.cross_thread_top.subject, 120)}`"
            if d.cross_thread_top else "(none)"
        ))
        lines.append(f"- decision reason: `{d.override_reason}`")
        lines.append("")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")

    # Raw log
    raw_lines: list[str] = []
    raw_lines.append(f"# Raw replay log — {DATE_TAG}\n")
    raw_lines.append(f"DB: `{LIVE_DB}`\n")
    raw_lines.extend(raw_log_lines)
    RAW_PATH.write_text("\n".join(raw_lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    raw_log: list[str] = []
    raw_log.append(f"## Run started: {datetime.utcnow().isoformat()}Z\n")

    if not LIVE_DB.exists():
        print(f"DB not found: {LIVE_DB}", file=sys.stderr)
        return 2

    conn = open_ro(LIVE_DB)
    audit_rows = load_audit_rows(conn)
    raw_log.append(f"Loaded {len(audit_rows)} audit rows since {SINCE}.\n")
    print(f"Loaded {len(audit_rows)} audit rows since {SINCE}.")

    # Collect all memory_object_ids appearing in any candidate
    all_mids: set[str] = set()
    for r in audit_rows:
        cands = json.loads(r["candidate_scores_json"] or "[]")
        for c in cands:
            mid = c.get("memory_object_id")
            if mid:
                all_mids.add(mid)
    raw_log.append(f"Distinct memory_object_ids referenced: {len(all_mids)}\n")
    print(f"Distinct memory_object_ids referenced: {len(all_mids)}")

    memo_index = build_memory_index(conn, all_mids)
    thread_index = build_thread_index(conn, all_mids)
    feedback_index = build_feedback_index(conn, all_mids)
    raw_log.append(
        f"memory_objects looked up: {len(memo_index)} | thread_index entries: "
        f"{sum(1 for v in thread_index.values() if v)} | "
        f"feedback entries: {len(feedback_index)}\n"
    )

    # Sample first row's classified candidates for raw log
    if audit_rows:
        first = audit_rows[0]
        cands = json.loads(first["candidate_scores_json"] or "[]")
        raw_log.append(f"### Sample row {first['id'][:8]}\n")
        raw_log.append(f"- query: `{short(first['query_text'], 200)}`")
        raw_log.append(f"- thread_ref: `{first['thread_ref']}`")
        raw_log.append(f"- candidates ({len(cands)}):")
        qtok_sample = tokens(first["query_text"])
        for c in cands[:6]:
            cls = classify_candidate(c, first["thread_ref"] or "", memo_index, thread_index, qtok_sample)
            raw_log.append(
                f"  - mid={cls.memory_object_id} layer={cls.layer} type={cls.type} "
                f"same_thread={cls.same_thread} overlap={cls.overlap} subj=`{short(cls.subject,60)}`"
            )
        raw_log.append("")

    decisions: list[RowDecision] = []
    edge_cases = collections.Counter()
    for r in audit_rows:
        decision, classified = evaluate_row(r, memo_index, thread_index)
        decisions.append(decision)
        # edge case bookkeeping
        for c in classified:
            if c.memory_object_id and c.same_thread is None:
                edge_cases["mid_no_thread_evidence"] += 1
            if c.memory_object_id and c.memory_object_id not in memo_index:
                edge_cases["mid_not_in_memory_objects"] += 1

    raw_log.append(f"Edge cases: {dict(edge_cases)}\n")

    # Override rate by container, by reason, etc., logged raw
    write_report(decisions, feedback_index, raw_log)
    print(f"Wrote {REPORT_PATH}")
    print(f"Wrote {RAW_PATH}")
    n_override = sum(1 for d in decisions if d.would_override)
    print(f"Override rate: {n_override}/{len(decisions)} = {fmt_pct(n_override, len(decisions))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
