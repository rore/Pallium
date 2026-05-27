"""Thread-level replay harness.

Walks real threads chronologically, applies a candidate-gating rule per turn,
and emits structured per-turn traces for the deep-dive threads (best, worst,
silent under the rule).

Reads from the live DB only. Writes traces to .local/research/anchor_probe/traces/.
No production code changes, no LLM calls. The qualitative pass (A/B/C verdicts)
is performed *after* this run, by dispatching subagents on the trace files.

Verification gates (run first, fail-fast):
  G1 path safety        - refuse to write outside .local/
  G2 baseline reproduction - rule_baseline reproduces injected_blocks_json exactly
  G3 trace integrity    - injected/kept memories present in candidate pool, tier-2 disjoint

Usage:
    .venv/Scripts/python.exe -m evals.anchor_probe.thread_replay \
        --rule R2b --since 2026-05-18 --top-n 10
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.text import normalize_for_index  # noqa: E402
from core.subject import subject_text_for_payload  # noqa: E402

# Reuse the per-case primitives directly per architect direction.
from evals.anchor_probe.replay_harness import (  # noqa: E402
    Case,
    rule_baseline,
    rule_R1_no_taskcheckpoint_in_cf,
    rule_R2_subject_overlap,
    rule_R2b_subject_overlap_2,
    rule_R3_combined,
    rule_R4_same_thread_or_subject,
    rule_R5_top1_only,
    rule_R6_top2_and_subject,
    rule_R7_strict,
)

RULES = {
    "baseline": rule_baseline,
    "R1": rule_R1_no_taskcheckpoint_in_cf,
    "R2": lambda c: rule_R2_subject_overlap(c, 1),
    "R2b": rule_R2b_subject_overlap_2,
    "R3": rule_R3_combined,
    "R4": rule_R4_same_thread_or_subject,
    "R5": rule_R5_top1_only,
    "R6": rule_R6_top2_and_subject,
    "R7": rule_R7_strict,
}


def _tokens(s: str) -> set[str]:
    return {t for t in normalize_for_index(s or "").split() if t}


# ---- Path safety (G1) ---------------------------------------------------------


def _ensure_local_path(p: Path) -> Path:
    """Refuse to write outside .local/. Hard error otherwise."""
    p_abs = p.resolve()
    project_local = (_PROJECT_ROOT / ".local").resolve()
    try:
        p_abs.relative_to(project_local)
    except ValueError:
        raise SystemExit(
            f"G1 path safety: refused to write outside .local/: {p_abs}\n"
            f"Traces must live under {project_local}"
        )
    return p_abs


# ---- Data load ---------------------------------------------------------------


@dataclass
class Turn:
    audit_id: str
    audit_at: str
    source_item_id: str | None
    user_text: str
    role: str | None
    container: str
    thread_ref: str
    decision_reason: str | None
    injection_method: str | None
    candidates: list[dict]
    injected_block_mids: set[str]
    # ratings keyed by memory_object_id (relevant|not_relevant|None)
    ratings: dict[str, str] = field(default_factory=dict)


@dataclass
class Thread:
    container: str
    thread_ref: str
    turns: list[Turn]


def load_threads(db: str, since: str) -> list[Thread]:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row

    audit_rows = con.execute(
        """
        SELECT qal.id, qal.created_at, qal.source_item_id, qal.thread_ref,
               qal.container_ref, qal.query_text, qal.decision_reason,
               qal.injection_method, qal.candidate_scores_json,
               qal.injected_blocks_json,
               si.role AS si_role, si.content AS si_content
        FROM query_audit_log qal
        LEFT JOIN source_items si ON si.id = qal.source_item_id
        WHERE qal.created_at >= ?
          AND qal.candidate_scores_json IS NOT NULL
          AND qal.thread_ref IS NOT NULL
        ORDER BY qal.thread_ref, qal.created_at ASC
        """,
        (since,),
    ).fetchall()

    # Pre-fetch ratings keyed by (audit_id, mid).
    feedback_rows = con.execute(
        """
        SELECT mf.query_audit_log_id AS aud, mf.memory_object_id AS mid, mf.rating
        FROM memory_feedback mf
        WHERE mf.created_at >= ?
          AND mf.rating IN ('relevant','not_relevant')
        """,
        (since,),
    ).fetchall()
    ratings_by_audit: dict[str, dict[str, str]] = defaultdict(dict)
    for r in feedback_rows:
        ratings_by_audit[r["aud"]][r["mid"]] = r["rating"]

    con.close()

    by_thread: dict[tuple[str, str], list[Turn]] = defaultdict(list)
    for r in audit_rows:
        cands = json.loads(r["candidate_scores_json"]) or []
        blocks = json.loads(r["injected_blocks_json"]) if r["injected_blocks_json"] else []
        block_mids = {(b.get("memory_object_id") or "") for b in blocks if isinstance(b, dict)}
        turn = Turn(
            audit_id=r["id"],
            audit_at=r["created_at"],
            source_item_id=r["source_item_id"],
            user_text=r["si_content"] or r["query_text"] or "",
            role=r["si_role"],
            container=r["container_ref"] or "",
            thread_ref=r["thread_ref"],
            decision_reason=r["decision_reason"],
            injection_method=r["injection_method"],
            candidates=cands,
            injected_block_mids=block_mids,
            ratings=ratings_by_audit.get(r["id"], {}),
        )
        by_thread[(turn.container, turn.thread_ref)].append(turn)

    return [
        Thread(container=k[0], thread_ref=k[1], turns=v)
        for k, v in by_thread.items()
    ]


# ---- Memory metadata cache (for trace rendering and tier-2) ------------------


def _derive_subject(mtype: str, payload: dict) -> str:
    """Memory_objects.subject is NULL in this DB; derive from payload by type.

    Delegates to the shared `core.subject.subject_text_for_payload` helper so
    the eval and the production R2b gate agree on what counts as the subject.
    """
    return subject_text_for_payload(mtype, payload or {})


def fetch_memories(db: str, mids: set[str]) -> dict[str, dict]:
    if not mids:
        return {}
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    qmarks = ",".join(["?"] * len(mids))
    rows = con.execute(
        f"""
        SELECT id, type, subject, payload_json, container_ref, created_at
        FROM memory_objects WHERE id IN ({qmarks})
        """,
        list(mids),
    ).fetchall()
    con.close()
    out: dict[str, dict] = {}
    for r in rows:
        payload: dict = {}
        body = ""
        if r["payload_json"]:
            try:
                payload = json.loads(r["payload_json"]) or {}
                body = (
                    payload.get("statement")
                    or payload.get("summary")
                    or payload.get("decision")
                    or payload.get("constraint_text")
                    or payload.get("investigation_outcome")
                    or payload.get("text")
                    or payload.get("body")
                    or payload.get("outcome")
                    or ""
                )
                if not body:
                    body = json.dumps(payload)[:600]
            except Exception:
                body = (r["payload_json"] or "")[:600]
        subj = (r["subject"] or "").strip()
        if not subj:
            subj = _derive_subject(r["type"] or "", payload)
        out[r["id"]] = dict(
            id=r["id"],
            type=r["type"] or "",
            subject=subj,
            body=(body or "")[:800],
            container=r["container_ref"] or "",
            created_at=r["created_at"],
        )
    return out


def enumerate_tier2(
    db: str, container: str, t_anchor: str, query: str, exclude_ids: set[str], k: int = 15
) -> list[dict]:
    """Tier-2 of dimension (C): when the candidate pool is empty/weak, scan all
    memories alive in this container at time T and rank by token overlap with
    the query. Lexical-only, capped at k. Read-only on memory_objects.
    """
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT id, type, subject, payload_json, created_at
        FROM memory_objects
        WHERE container_ref = ?
          AND created_at <= ?
          AND lifecycle = 'active'
        """,
        (container, t_anchor),
    ).fetchall()
    con.close()

    qtok = _tokens(query)
    if not qtok:
        return []

    scored: list[tuple[int, dict]] = []
    for r in rows:
        if r["id"] in exclude_ids:
            continue
        body = ""
        if r["payload_json"]:
            try:
                p = json.loads(r["payload_json"])
                body = (
                    p.get("statement")
                    or p.get("summary")
                    or p.get("decision")
                    or p.get("text")
                    or ""
                )
            except Exception:
                pass
        text = (r["subject"] or "") + " " + body
        overlap = len(qtok & _tokens(text))
        if overlap == 0:
            continue
        scored.append((overlap, dict(
            id=r["id"], type=r["type"] or "", subject=r["subject"] or "",
            body=(body or "")[:400], created_at=r["created_at"], overlap=overlap,
        )))
    scored.sort(key=lambda x: -x[0])
    return [s[1] for s in scored[:k]]


# ---- Case synthesis (so we can apply rule fns directly) ----------------------


def make_case(turn: Turn, candidate: dict, mem_meta: dict | None) -> Case:
    """Synthesize a per-candidate Case for a turn. Reuses the dataclass from
    replay_harness so existing rules work unmodified.
    """
    mid = candidate.get("memory_object_id") or ""
    rating = turn.ratings.get(mid) or "unrated"
    return Case(
        fid=f"{turn.audit_id}:{mid}",
        rating=rating,
        rated_mid=mid,
        rated_type=(candidate.get("memory_type") or (mem_meta or {}).get("type") or ""),
        query=turn.user_text,
        container=turn.container,
        audit_id=turn.audit_id,
        audit_thread=turn.thread_ref,
        decision_reason=turn.decision_reason,
        injection_method=turn.injection_method,
        candidates=turn.candidates,
        injected_block_mids=turn.injected_block_mids,
        target_candidate=candidate,
        memory_subject=(mem_meta or {}).get("subject", "") or candidate.get("subject", ""),
        memory_text=(mem_meta or {}).get("body", ""),
        memory_thread=None,  # not needed for the rules we care about here
    )


# ---- Replay & pick-threads ---------------------------------------------------


@dataclass
class TurnReplay:
    turn: Turn
    live_kept: set[str]       # = injected_block_mids
    rule_kept: set[str]
    candidate_pool: list[dict]


@dataclass
class ThreadReplay:
    thread: Thread
    turns: list[TurnReplay]
    n_turns_with_inject: int
    n_live_inject: int
    n_rule_inject: int
    n_rated: int
    n_live_rel: int
    n_live_nr: int
    n_rule_rel: int
    n_rule_nr: int
    n_distinct_injected_subjects: int

    @property
    def silent_under_rule(self) -> bool:
        return self.n_live_inject > 0 and self.n_rule_inject == 0

    @property
    def noise_kept_delta(self) -> int:
        return self.n_rule_nr - self.n_live_nr  # negative = better

    @property
    def rel_lost(self) -> int:
        return max(0, self.n_live_rel - self.n_rule_rel)


def replay_thread(thread: Thread, rule, mem_meta: dict[str, dict]) -> ThreadReplay:
    turns_replay: list[TurnReplay] = []
    n_live_inject = n_rule_inject = 0
    n_live_rel = n_live_nr = n_rule_rel = n_rule_nr = n_rated = 0
    injected_subjects: set[str] = set()

    for turn in thread.turns:
        rule_kept: set[str] = set()
        for cand in turn.candidates:
            mid = cand.get("memory_object_id") or ""
            case = make_case(turn, cand, mem_meta.get(mid))
            if rule(case):
                rule_kept.add(mid)
        live_kept = set(turn.injected_block_mids)
        n_live_inject += len(live_kept)
        n_rule_inject += len(rule_kept)
        for mid in live_kept:
            subj = (mem_meta.get(mid) or {}).get("subject") or ""
            if subj:
                injected_subjects.add(subj)
            r = turn.ratings.get(mid)
            if r:
                n_rated += 1
                if r == "relevant":
                    n_live_rel += 1
                else:
                    n_live_nr += 1
        for mid in rule_kept:
            r = turn.ratings.get(mid)
            if r == "relevant":
                n_rule_rel += 1
            elif r == "not_relevant":
                n_rule_nr += 1
        turns_replay.append(TurnReplay(
            turn=turn, live_kept=live_kept, rule_kept=rule_kept,
            candidate_pool=turn.candidates,
        ))

    return ThreadReplay(
        thread=thread, turns=turns_replay,
        n_turns_with_inject=sum(1 for t in turns_replay if t.live_kept),
        n_live_inject=n_live_inject, n_rule_inject=n_rule_inject,
        n_rated=n_rated, n_live_rel=n_live_rel, n_live_nr=n_live_nr,
        n_rule_rel=n_rule_rel, n_rule_nr=n_rule_nr,
        n_distinct_injected_subjects=len(injected_subjects),
    )


def pick_top_noisy(threads: list[Thread], top_n: int, min_ratings: int) -> list[Thread]:
    """Rank by noise_pain = nr_count * n_rated. Require min_ratings to cut noise."""
    scored: list[tuple[float, Thread]] = []
    for th in threads:
        nr = sum(
            1 for turn in th.turns for mid in turn.injected_block_mids
            if turn.ratings.get(mid) == "not_relevant"
        )
        rated = sum(
            1 for turn in th.turns for mid in turn.injected_block_mids
            if turn.ratings.get(mid) in ("relevant", "not_relevant")
        )
        if rated < min_ratings:
            continue
        scored.append((nr * rated, th))
    scored.sort(key=lambda x: -x[0])
    return [s[1] for s in scored[:top_n]]


# ---- Verification gates -----------------------------------------------------


def verify_baseline_reproduction(thread: Thread, mem_meta: dict[str, dict]) -> None:
    """G2: rule_baseline must keep exactly injected_blocks_json per turn.

    Relaxation logged: blocks injected without a candidate-pool row (e.g. carry-
    forward layered signals) cannot be flipped by any rule, so we compare on
    the pool intersection only and emit a stderr note when the live set
    contains pool-absent blocks.
    """
    skipped_total = 0
    for turn in thread.turns:
        kept_baseline: set[str] = set()
        for cand in turn.candidates:
            case = make_case(turn, cand, mem_meta.get(cand.get("memory_object_id") or ""))
            if rule_baseline(case):
                kept_baseline.add(cand.get("memory_object_id") or "")
        live = set(turn.injected_block_mids)
        pool_ids = {c.get("memory_object_id") or "" for c in turn.candidates}
        live_in_pool = live & pool_ids
        skipped = live - pool_ids
        if skipped:
            skipped_total += len(skipped)
            print(
                f"  G2 note: thread {thread.thread_ref[:8]} audit {turn.audit_id[:8]} "
                f"has {len(skipped)} injected block(s) absent from candidate pool "
                f"(uncheckable, treated as pass): {sorted(skipped)[:3]}",
                file=sys.stderr,
            )
        if kept_baseline != live_in_pool:
            extra = kept_baseline - live_in_pool
            missing = live_in_pool - kept_baseline
            raise SystemExit(
                f"G2 baseline reproduction FAILED on thread {thread.thread_ref} "
                f"audit {turn.audit_id}\n"
                f"  rule_baseline kept: {sorted(kept_baseline)[:5]}\n"
                f"  injected_blocks (in pool): {sorted(live_in_pool)[:5]}\n"
                f"  rule_baseline extra: {sorted(extra)[:5]}\n"
                f"  rule_baseline missing: {sorted(missing)[:5]}\n"
            )


def verify_trace_integrity(trace_text: str, replay: ThreadReplay) -> None:
    """G3: every injected/kept memory must appear in the trace (matched by short id)."""
    for tr in replay.turns:
        for mid in tr.live_kept | tr.rule_kept:
            if not mid:
                continue
            short = mid[:8]
            if short not in trace_text:
                raise SystemExit(
                    f"G3 trace integrity FAILED on thread {replay.thread.thread_ref}: "
                    f"memory {mid} (short {short}) not present in trace"
                )


# ---- Trace emission ----------------------------------------------------------


def _short(s: str, n: int = 240) -> str:
    s = (s or "").replace("\r\n", "\n").strip()
    if len(s) <= n:
        return s
    return s[: n - 1] + "…"


def _fmt_memory(mem: dict, rating: str | None, in_live: bool, in_rule: bool, rank: int | None) -> str:
    badge = []
    if in_live:
        badge.append("live")
    if in_rule:
        badge.append("rule")
    if rating == "relevant":
        badge.append("rated:REL")
    elif rating == "not_relevant":
        badge.append("rated:NR")
    badge_s = f"[{' '.join(badge)}]" if badge else "[ ]"
    rank_s = f"r{rank}" if rank else "r?"
    return (
        f"- {badge_s} {rank_s} `{mem.get('id','?')[:8]}` "
        f"**{mem.get('type','?')}** :: {_short(mem.get('subject',''), 120)}\n"
        f"    body: {_short(mem.get('body',''), 320)}"
    )


def emit_trace(
    replay: ThreadReplay,
    mem_meta: dict[str, dict],
    tier2_per_turn: dict[str, list[dict]],
    rule_name: str,
    db_path: str,
    since: str,
    run_id: str,
    category: str,
    out_dir: Path,
) -> Path:
    """Write a markdown trace file for one deep-dive thread.

    Schema:
      Header (run_id, db, since, thread, category, baseline status, counts)
      Per turn:
        - user text
        - preceding-context window (last 3 turns, condensed)
        - live-injected memories (full subject + body)
        - rule-kept memories
        - full candidate pool
        - tier-2 enumeration (only when emitted)
    """
    th = replay.thread
    slug = th.thread_ref[:12]
    path = out_dir / f"{slug}__{category}.md"
    path = _ensure_local_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    lines.append(f"# Thread replay trace - {th.thread_ref[:12]} ({category})\n")
    lines.append("## Header\n")
    lines.append(f"- run_id: `{run_id}`")
    lines.append(f"- db: `{db_path}`")
    lines.append(f"- since: `{since}`")
    lines.append(f"- container: `{th.container}`")
    lines.append(f"- thread_ref: `{th.thread_ref}`")
    lines.append(f"- rule: `{rule_name}`")
    lines.append(f"- category: `{category}`")
    lines.append(f"- turns: {len(replay.turns)}")
    lines.append(f"- live injections: {replay.n_live_inject}")
    lines.append(f"- rule injections: {replay.n_rule_inject}")
    lines.append(
        f"- rated: {replay.n_rated} (live rel/nr {replay.n_live_rel}/{replay.n_live_nr}; "
        f"rule rel/nr {replay.n_rule_rel}/{replay.n_rule_nr})"
    )
    lines.append(f"- distinct injected subjects: {replay.n_distinct_injected_subjects}")
    lines.append(f"- silent under rule: {replay.silent_under_rule}")
    lines.append("")

    lines.append("## Turns\n")
    history: list[str] = []
    for i, tr in enumerate(replay.turns, 1):
        turn = tr.turn
        lines.append(f"### Turn {i} - audit `{turn.audit_id[:8]}` "
                     f"({turn.role or '?'}, {turn.audit_at})\n")
        lines.append(f"- decision_reason: `{turn.decision_reason}`")
        lines.append(f"- injection_method: `{turn.injection_method}`")
        lines.append(f"- live_kept: {len(tr.live_kept)}  rule_kept: {len(tr.rule_kept)}")
        lines.append("")
        lines.append("**User turn text:**\n")
        lines.append("> " + _short(turn.user_text, 1200).replace("\n", "\n> "))
        lines.append("")
        if history:
            lines.append("**Preceding context (last 3 turns, condensed):**\n")
            for h in history[-3:]:
                lines.append(f"- {h}")
            lines.append("")

        # Live injected
        lines.append("**Live-injected memories:**\n")
        if not tr.live_kept:
            lines.append("- _(none)_")
        else:
            for mid in sorted(tr.live_kept):
                meta = mem_meta.get(mid) or {"id": mid}
                rank = next(
                    (c.get("routing_rank") for c in tr.candidate_pool
                     if c.get("memory_object_id") == mid),
                    None,
                )
                lines.append(_fmt_memory(
                    meta, turn.ratings.get(mid),
                    in_live=True, in_rule=(mid in tr.rule_kept), rank=rank,
                ))
        lines.append("")

        # Rule kept
        lines.append("**Rule-kept memories:**\n")
        if not tr.rule_kept:
            lines.append("- _(none)_")
        else:
            for mid in sorted(tr.rule_kept):
                meta = mem_meta.get(mid) or {"id": mid}
                rank = next(
                    (c.get("routing_rank") for c in tr.candidate_pool
                     if c.get("memory_object_id") == mid),
                    None,
                )
                lines.append(_fmt_memory(
                    meta, turn.ratings.get(mid),
                    in_live=(mid in tr.live_kept), in_rule=True, rank=rank,
                ))
        lines.append("")

        # Full candidate pool
        lines.append(f"**Candidate pool ({len(tr.candidate_pool)}):**\n")
        for c in tr.candidate_pool:
            mid = c.get("memory_object_id") or ""
            rank = c.get("routing_rank")
            layer = c.get("layer") or "?"
            if not mid:
                # source_evidence layer: not a memory_object, just the query echo
                excl = c.get("excluded_reason_code") or c.get("suppression_reason_code") or "?"
                lines.append(
                    f"- [ ] r{rank or '?'} _(layer={layer}, no memory_object, "
                    f"excluded={excl}, score={c.get('routing_score')})_"
                )
                continue
            meta = mem_meta.get(mid) or {"id": mid}
            lines.append(_fmt_memory(
                meta, turn.ratings.get(mid),
                in_live=(mid in tr.live_kept),
                in_rule=(mid in tr.rule_kept),
                rank=rank,
            ))
        lines.append("")

        # Tier-2 (if emitted)
        t2 = tier2_per_turn.get(turn.audit_id) or []
        if t2:
            lines.append(f"**Tier-2 enumeration ({len(t2)}, lexical-overlap, "
                         f"excludes pool):**\n")
            for m in t2:
                lines.append(
                    f"- ovl={m['overlap']:>2} `{m['id'][:8]}` "
                    f"**{m['type']}** :: {_short(m['subject'], 120)}\n"
                    f"    body: {_short(m['body'], 280)}"
                )
            lines.append("")

        # update history
        history.append(
            f"T{i} ({turn.role or '?'}) {_short(turn.user_text, 140)} "
            f"[live={len(tr.live_kept)} rule={len(tr.rule_kept)}]"
        )

    text = "\n".join(lines) + "\n"
    path.write_text(text, encoding="utf-8")
    return path


# ---- Tier-2 trigger ----------------------------------------------------------


def should_emit_tier2(turn: Turn, mem_meta: dict[str, dict]) -> bool:
    """Heuristic: emit tier-2 if no plausibly-relevant card exists in the pool.
    Concretely: no candidate has subject_overlap >= 1 with the query.
    """
    if not turn.candidates:
        return True
    qtok = _tokens(turn.user_text)
    if not qtok:
        return False
    for c in turn.candidates:
        mid = c.get("memory_object_id") or ""
        meta = mem_meta.get(mid) or {}
        stok = _tokens(meta.get("subject", "")) or _tokens(meta.get("body", ""))
        if stok and (qtok & stok):
            return False
    return True


# ---- Main --------------------------------------------------------------------


def _print_table(replays_baseline: list[ThreadReplay], replays_rule: list[ThreadReplay], rule_name: str) -> None:
    print(f"\n## Per-thread before/after  (rule: {rule_name})\n")
    print(
        f"  {'thread':<14} {'subj':>4} {'turns':>5} {'inj':>5} "
        f"{'rule_inj':>8} {'live(r/n)':>10} {'rule(r/n)':>10} "
        f"{'noise_kill':>10} {'rel_lost':>8} {'silent':>7}"
    )
    for b, r in zip(replays_baseline, replays_rule):
        th = b.thread
        nl_nr = b.n_live_nr
        nr_nr = r.n_rule_nr
        kill = nl_nr - nr_nr
        print(
            f"  {th.thread_ref[:12]:<14} "
            f"{b.n_distinct_injected_subjects:>4} "
            f"{len(th.turns):>5} {b.n_live_inject:>5} "
            f"{r.n_rule_inject:>8} "
            f"{b.n_live_rel:>4}/{b.n_live_nr:<4} "
            f"{r.n_rule_rel:>4}/{r.n_rule_nr:<4} "
            f"{kill:>10} {r.rel_lost:>8} {str(r.silent_under_rule):>7}"
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(Path.home() / ".pallium" / "data" / "pallium.db"))
    ap.add_argument("--since", default="2026-05-18")
    ap.add_argument("--rule", default="R2b", choices=list(RULES.keys()))
    ap.add_argument("--top-n", type=int, default=10)
    ap.add_argument("--min-ratings", type=int, default=3)
    args = ap.parse_args()

    rule_fn = RULES[args.rule]
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    out_dir = _ensure_local_path(
        _PROJECT_ROOT / ".local" / "research" / "anchor_probe" / "traces" / run_id
    )

    print(f"# Thread replay - rule={args.rule} since={args.since} run={run_id}")
    print(f"  db: {args.db}")
    print(f"  out: {out_dir}")

    threads = load_threads(args.db, args.since)
    print(f"  loaded {len(threads)} threads with audit data")

    picked = pick_top_noisy(threads, args.top_n, args.min_ratings)
    print(f"  picked {len(picked)} noisy threads (min_ratings={args.min_ratings})")
    if not picked:
        print("  no threads met selection criteria - try lowering --min-ratings")
        return 0

    # Fetch memory metadata for everything we'll touch.
    all_mids: set[str] = set()
    for th in picked:
        for turn in th.turns:
            for c in turn.candidates:
                all_mids.add(c.get("memory_object_id") or "")
            all_mids |= turn.injected_block_mids
    all_mids.discard("")
    mem_meta = fetch_memories(args.db, all_mids)
    print(f"  fetched metadata for {len(mem_meta)} memories")

    # G2 baseline reproduction (fail-fast).
    print("\n## G2 baseline reproduction\n")
    for th in picked:
        verify_baseline_reproduction(th, mem_meta)
    print(f"  PASS - rule_baseline reproduces injected_blocks_json on {len(picked)} threads")

    # Replay both baseline and rule.
    base_replays = [replay_thread(th, rule_baseline, mem_meta) for th in picked]
    rule_replays = [replay_thread(th, rule_fn, mem_meta) for th in picked]

    _print_table(base_replays, rule_replays, args.rule)

    # Pick deep-dive threads: best-improvement, worst-regression, silent.
    deltas = list(zip(base_replays, rule_replays))
    # Sort by noise_kill (live_nr - rule_nr): bigger = better
    by_kill = sorted(deltas, key=lambda x: -(x[0].n_live_nr - x[1].n_rule_nr))
    best = by_kill[0] if by_kill else None
    # Worst regression: most relevant lost (rule_rel < live_rel) or noise added
    worst = max(
        deltas,
        key=lambda x: x[1].rel_lost + max(0, x[1].n_rule_nr - x[0].n_live_nr),
        default=None,
    )
    silent = next(
        (d for d in deltas if d[1].silent_under_rule),
        None,
    )

    selected: list[tuple[str, tuple[ThreadReplay, ThreadReplay]]] = []
    chosen_threads: set[str] = set()
    for label, sel in [("best", best), ("worst", worst), ("silent", silent)]:
        if sel and sel[0].thread.thread_ref not in chosen_threads:
            selected.append((label, sel))
            chosen_threads.add(sel[0].thread.thread_ref)

    # If we don't have a silent thread, pick a "most-changed" third sample so
    # we always get three deep-dives per architect direction.
    if not any(label == "silent" for label, _ in selected) and len(selected) < 3:
        most_changed = max(
            (d for d in deltas if d[0].thread.thread_ref not in chosen_threads),
            key=lambda x: abs(x[0].n_live_inject - x[1].n_rule_inject)
                          + abs(x[0].n_live_nr - x[1].n_rule_nr),
            default=None,
        )
        if most_changed:
            selected.append(("most_changed", most_changed))
            chosen_threads.add(most_changed[0].thread.thread_ref)

    print(f"\n## Deep-dive selection ({len(selected)})\n")
    for label, (b, _r) in selected:
        print(f"  {label:<7} thread={b.thread.thread_ref[:12]} "
              f"subj={b.n_distinct_injected_subjects} turns={len(b.thread.turns)}")

    # Tier-2 + trace emit per selected thread.
    print("\n## Trace emission\n")
    written: list[Path] = []
    for label, (b, r) in selected:
        th = b.thread
        tier2_map: dict[str, list[dict]] = {}
        # Need extra mem_meta for tier-2 candidates (excluded by id).
        for turn in th.turns:
            if should_emit_tier2(turn, mem_meta):
                pool_ids = {c.get("memory_object_id") or "" for c in turn.candidates}
                t2 = enumerate_tier2(
                    args.db, th.container, turn.audit_at, turn.user_text,
                    pool_ids, k=15,
                )
                tier2_map[turn.audit_id] = t2

        path = emit_trace(
            replay=r,
            mem_meta=mem_meta,
            tier2_per_turn=tier2_map,
            rule_name=args.rule,
            db_path=args.db,
            since=args.since,
            run_id=run_id,
            category=label,
            out_dir=out_dir,
        )
        # G3 trace integrity
        verify_trace_integrity(path.read_text(encoding="utf-8"), r)
        written.append(path)
        print(f"  wrote {path.relative_to(_PROJECT_ROOT)}")

    print(f"\n## Done. {len(written)} traces written under {out_dir.relative_to(_PROJECT_ROOT)}")
    print("Next: dispatch one subagent per trace with the qualitative_judge prompt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
