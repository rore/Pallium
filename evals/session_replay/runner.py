"""End-to-end session replay runner.

Reads one or more session JSONL files, mines miss signals on each turn,
joins to ``query_audit_log``, classifies failure stage, and emits
``miss_cases.jsonl`` plus a markdown summary.

Pure offline: no LLM calls, read-only on the Pallium DB.
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from evals.session_replay.audit_join import (
    decode_candidates,
    fetch_memory_lifecycles,
    find_audit_rows,
    open_audit_db,
    resolve_db_path,
)
from evals.session_replay.parse import parse, turns
from evals.session_replay.signals import (
    detect_future_oracle,
    detect_recall_intent,
    detect_repeated_work,
    is_boilerplate_only,
    turn_pallium_blocks,
)
from evals.session_replay.stage import classify_stage


@dataclass
class RunnerConfig:
    """Knobs for a single ``run`` invocation."""

    out_dir: Path
    db_path: str | None = None
    container_ref: str | None = None  # restricts audit-row matching
    max_audit_match: int = 3
    enable_signals: tuple[str, ...] = (
        "recall_intent",
        "repeated_work",
        "future_oracle",
    )

    def output_paths(self) -> tuple[Path, Path]:
        return (
            self.out_dir / "miss_cases.jsonl",
            self.out_dir / "summary.md",
        )


# ---------------------------------------------------------------------------
# Per-session scan (no DB access — pure transcript analysis)
# ---------------------------------------------------------------------------

def scan_session_transcript(
    path: str,
    enable_signals: Sequence[str],
) -> tuple[list[dict], dict]:
    """Run the configured signals over a single transcript file.

    Returns (rows, meta). Each row is a candidate miss case. Meta carries
    per-file counters for the summary report.
    """
    events = parse(path)
    parsed_turns = turns(events)
    sid: str | None = next(
        (e.get("session_id") for e in events if e.get("session_id")), None
    )
    cwd: str | None = next(
        (e.get("cwd") for e in events if e.get("cwd")), None
    )
    source_format = events[0]["source_format"] if events else "unknown"

    rows: list[dict] = []

    for ti, t in enumerate(parsed_turns):
        u = (t.get("user_text") or "").strip()
        if not u or is_boilerplate_only(u):
            continue
        u_short = u[:300]
        pal_blocks = turn_pallium_blocks(t)
        injected = bool(pal_blocks)

        common = {
            "session_file": path,
            "session_id": sid,
            "cwd": cwd,
            "source_format": source_format,
            "turn_index": ti,
            "turn_ts": (t.get("user_ev") or {}).get("ts"),
            "user_text": u_short,
            "was_injected_observed": injected,
            "n_pallium_blocks_observed": len(pal_blocks),
            "pallium_refs_observed": [b.get("ref") for b in pal_blocks if b.get("ref")],
        }

        if "recall_intent" in enable_signals:
            phrase = detect_recall_intent(t)
            if phrase:
                rows.append({**common, "miss_signal": "recall_intent", "matched_phrase": phrase})

        if "future_oracle" in enable_signals:
            ev = detect_future_oracle(t)
            if ev is not None:
                rows.append({
                    **common,
                    "miss_signal": "future_oracle",
                    "matched_phrase": "vague_prompt+discovery_only",
                    "discovery_evidence": ev,
                })

    if "repeated_work" in enable_signals:
        for hit in detect_repeated_work(parsed_turns):
            first_ti = hit["turn_indexes"][0]
            first_turn = parsed_turns[first_ti]
            u = (first_turn.get("user_text") or "").strip()[:300]
            pal_blocks = turn_pallium_blocks(first_turn)
            rows.append({
                "session_file": path,
                "session_id": sid,
                "cwd": cwd,
                "source_format": source_format,
                "turn_index": first_ti,
                "turn_ts": (first_turn.get("user_ev") or {}).get("ts"),
                "user_text": u,
                "was_injected_observed": bool(pal_blocks),
                "n_pallium_blocks_observed": len(pal_blocks),
                "pallium_refs_observed": [
                    b.get("ref") for b in pal_blocks if b.get("ref")
                ],
                "miss_signal": hit["kind"],
                "matched_phrase": hit["key"][:200],
                "occurred_in_turns": hit["turn_indexes"],
                "n_repeats": len(hit["turn_indexes"]),
            })

    meta = {
        "path": path,
        "size_bytes": Path(path).stat().st_size if Path(path).exists() else 0,
        "n_events": len(events),
        "n_turns": len(parsed_turns),
        "source_format": source_format,
        "session_id": sid,
        "cwd": cwd,
    }
    return rows, meta


# ---------------------------------------------------------------------------
# DB enrichment
# ---------------------------------------------------------------------------

def enrich_with_audit(
    rows: list[dict],
    cur: sqlite3.Cursor,
    container_ref: str | None,
    max_audit_match: int,
) -> None:
    """For each row with a ``user_text``, find matching audit rows, decode
    candidates, fetch top-candidate lifecycles, and classify the failure
    stage. Mutates rows in place.
    """
    for row in rows:
        ut = row.get("user_text") or ""
        if not ut:
            continue
        # Repeated_work rows already point at a turn; use that turn's
        # user_text. The user_text is already populated for them above.
        audits = find_audit_rows(
            cur, ut, container_ref=container_ref, limit=max_audit_match
        )
        if not audits:
            row["audit_match"] = None
            res = classify_stage(None, [], [], None)
            row["failure_stage"] = res["stage"]
            row["failure_evidence"] = res["evidence"]
            row["top_candidates"] = res["top_candidates"]
            continue

        primary = audits[0]
        candidates, injected = decode_candidates(primary)
        top_ids = [c.get("memory_object_id") for c in candidates[:5]
                   if c.get("memory_object_id")]
        lifecycles = fetch_memory_lifecycles(cur, top_ids)

        res = classify_stage(primary, candidates, injected, lifecycles)
        row["audit_match"] = {
            "audit_id": primary["audit_id"],
            "container_ref": primary["container_ref"],
            "should_inject": primary["should_inject"],
            "decision_reason": primary["decision_reason"],
            "n_candidates": len(candidates),
            "n_injected": len(injected),
            "created_at": primary["created_at"],
        }
        row["failure_stage"] = res["stage"]
        row["failure_evidence"] = res["evidence"]
        row["top_candidates"] = res["top_candidates"]


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _short_basename(p: str, n: int = 60) -> str:
    name = Path(p).name
    if len(name) <= n:
        return name
    return name[: n - 1] + "…"


def render_summary(
    rows: list[dict],
    metas: list[dict],
    out_path: Path,
) -> None:
    """Write a human-readable markdown summary alongside ``miss_cases.jsonl``."""
    sig_counts: Counter = Counter(r.get("miss_signal", "?") for r in rows)
    stage_counts: Counter = Counter(r.get("failure_stage", "?") for r in rows)
    fmt_counts: Counter = Counter(r.get("source_format", "?") for r in rows)

    lines: list[str] = []
    lines.append("# session_replay summary")
    lines.append("")
    lines.append(f"- sessions scanned: {len(metas)}")
    lines.append(f"- total candidate rows: {len(rows)}")
    lines.append(f"- by source format: {dict(fmt_counts)}")
    lines.append(f"- by signal: {dict(sig_counts)}")
    lines.append(f"- by failure stage: {dict(stage_counts)}")
    lines.append("")

    lines.append("## per-session")
    lines.append("")
    lines.append("| file | format | size | turns | rows |")
    lines.append("|------|--------|-----:|------:|-----:|")
    by_file: Counter = Counter(r.get("session_file", "?") for r in rows)
    for m in metas:
        lines.append(
            f"| {_short_basename(m['path'])} | {m.get('source_format', '?')} "
            f"| {m.get('size_bytes', 0)} | {m.get('n_turns', 0)} "
            f"| {by_file.get(m['path'], 0)} |"
        )
    lines.append("")

    # Show up to 5 routing_suppressed cases — most actionable
    interesting = [r for r in rows if r.get("failure_stage") == "routing_suppressed"][:5]
    if interesting:
        lines.append("## sample: routing_suppressed cases")
        lines.append("")
        for r in interesting:
            audit = r.get("audit_match") or {}
            lines.append(
                f"- **turn {r.get('turn_index')} of "
                f"{_short_basename(r.get('session_file', ''))}** "
                f"(signal={r.get('miss_signal')})"
            )
            lines.append(
                f"  - decision_reason: `{audit.get('decision_reason')}`; "
                f"n_candidates: {audit.get('n_candidates')}"
            )
            lines.append(f"  - evidence: {r.get('failure_evidence')}")
            top = (r.get("top_candidates") or [])[:1]
            if top:
                t = top[0]
                lines.append(
                    f"  - rank-1: id={t.get('memory_id')} "
                    f"type={t.get('type')} score={t.get('routing_score')} "
                    f"excluded_reason={t.get('excluded_reason')}"
                )
            user_excerpt = (r.get("user_text") or "").replace("\n", " ")[:140]
            lines.append(f"  - user: {user_excerpt!r}")
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------

def run(paths: Sequence[str], cfg: RunnerConfig) -> dict:
    """Run miss-signal mining + audit join over ``paths`` and write outputs.

    Returns a small dict of overall counts for callers (CLI prints them).
    """
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    metas: list[dict] = []

    for path in paths:
        try:
            session_rows, meta = scan_session_transcript(
                path, cfg.enable_signals
            )
        except (OSError, ValueError) as exc:
            metas.append({"path": path, "error": str(exc)})
            continue
        rows.extend(session_rows)
        metas.append(meta)

    db_path = resolve_db_path(cfg.db_path)
    db_used = False
    if Path(db_path).exists():
        try:
            with open_audit_db(db_path) as conn:
                cur = conn.cursor()
                enrich_with_audit(rows, cur, cfg.container_ref, cfg.max_audit_match)
                db_used = True
        except sqlite3.DatabaseError as exc:
            for r in rows:
                r.setdefault("failure_stage", "no_audit_match")
                r.setdefault(
                    "failure_evidence",
                    f"audit DB unavailable: {exc}",
                )
                r.setdefault("top_candidates", [])
                r.setdefault("audit_match", None)
    else:
        for r in rows:
            r.setdefault("failure_stage", "no_audit_match")
            r.setdefault(
                "failure_evidence",
                f"audit DB not found at {db_path}",
            )
            r.setdefault("top_candidates", [])
            r.setdefault("audit_match", None)

    miss_path, summary_path = cfg.output_paths()
    with miss_path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    render_summary(rows, metas, summary_path)

    return {
        "n_sessions": len(metas),
        "n_rows": len(rows),
        "miss_cases_path": str(miss_path),
        "summary_path": str(summary_path),
        "db_used": db_used,
        "db_path": db_path,
    }
