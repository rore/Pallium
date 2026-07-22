"""I1 — would the top-routing-score candidate from a `same_thread_context_sufficient`
skip have helped the user query?

The fast experiments showed 358 skips since 2026-05-18 with `routing_score>=200`
in the candidate pool 96% of the time. This is the underinjection hypothesis:
the system suppresses many useful candidates.

Test: sample 30 skips with the highest top-routing-score in pool, ask the
qualitative-judge: would the top candidate have improved the answer?

Decision rule:
- If >=50% say yes → routing-gate calibration is the priority lever.
- If <30% say yes → suppressing was correct; underinjection isn't the
  blocker.
- 30-50% → ambiguous, look at patterns.

Cost: ~30 LLM calls.

Usage:
    python -m evals.anchor_probe.underinjection_judge \
        --since 2026-05-18 --limit 30 --min-rs 400
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.config import AppConfig  # noqa: E402
from app.dependencies import build_llm_provider  # noqa: E402

JUDGE_SYSTEM_PROMPT = """\
You are reviewing one memory-retrieval skip event from an AI agent's
memory system. The system DID NOT inject any memory for this user query
because it judged the immediate conversation context already sufficient.
But there was a candidate memory available in the retrieval pool — the
top-ranked one is shown to you.

Your job: would showing this top candidate to the agent have made the
agent's response measurably better?

"Better" means:
- More specific or accurate answer (correctness lift).
- Avoids re-asking or re-deriving information the user already gave.
- Helps the agent connect the current request to a prior decision/outcome.

"No better" means:
- The memory is off-topic for this query.
- The agent has plenty of context already and the memory adds nothing.
- The memory is too vague or generic to act on.

Bias: the system already decided to skip. Only call "yes_helpful" if
showing the memory would clearly help; if you're unsure, say "no".

Return a JSON object:
- verdict: one of "yes_helpful", "no_helpful", "neutral"
- reason: one short sentence (under 30 words).
"""

JUDGE_SCHEMA = '{"verdict":"string","reason":"string"}'


def _excerpt(s: str, n: int = 400) -> str:
    return (s or "").replace("\n", " ").strip()[:n]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(Path.home() / ".pallium" / "data" / "pallium.db"))
    ap.add_argument("--since", default="2026-05-18")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--min-rs", type=int, default=400)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--distinct", action="store_true",
                    help="Dedupe samples by (top mid, thread_ref) so one underlying decision can't dominate the sample.")
    ap.add_argument("--exclude-internal", action="store_true",
                    help="Drop agent-internal / automated monitoring prompts so the sample reflects genuine user recall turns.")
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT id, query_text, candidate_scores_json, thread_ref, container_ref
        FROM query_audit_log
        WHERE created_at >= ? AND decision_reason='same_thread_context_sufficient'
          AND candidate_scores_json IS NOT NULL
        """,
        (args.since,),
    ).fetchall()

    samples = []
    for r in rows:
        cs = json.loads(r["candidate_scores_json"]) or []
        if not cs:
            continue
        if args.exclude_internal:
            ql = (r["query_text"] or "").lower()
            _markers = ("check import", "check fast import", "check if the article",
                        "check extraction", "read last", "read the last", "background task",
                        "task-notification", "bringing up nodes", "monitor", "progress:",
                        "output file", "log file c:/")
            if any(m in ql for m in _markers):
                continue
        top = max(cs, key=lambda c: (c.get("routing_score") or 0))
        rs = (top.get("routing_score") or 0)
        if rs < args.min_rs:
            continue
        mid = top.get("memory_object_id")
        m = con.execute(
            "SELECT subject, payload_json FROM memory_objects WHERE id=?",
            (mid,),
        ).fetchone()
        subj = ""
        body = ""
        if m:
            subj = m["subject"] or ""
            if m["payload_json"]:
                try:
                    pl = json.loads(m["payload_json"])
                    if not subj:
                        for k in ("subject", "title", "decision", "summary", "statement"):
                            if isinstance(pl.get(k), str) and pl[k]:
                                subj = pl[k]; break
                    body = pl.get("decision") or pl.get("statement") or pl.get("summary") \
                        or pl.get("investigation_outcome") or pl.get("description") or ""
                    if isinstance(body, list): body = " | ".join(str(x) for x in body)
                except Exception:
                    pass
        samples.append({
            "audit_id": r["id"],
            "query": r["query_text"] or "",
            "rs": rs,
            "rank": top.get("routing_rank"),
            "type": top.get("layer"),
            "memory_type": top.get("memory_type"),
            "lexical_score": top.get("lexical_score"),
            "vector_score": top.get("vector_score"),
            "support_grade": top.get("support_grade"),
            "container_ref": r["container_ref"],
            "mid": mid,
            "thread_ref": r["thread_ref"],
            "subject": subj,
            "body": body,
        })

    samples.sort(key=lambda s: -s["rs"])
    if args.distinct:
        seen: set[tuple] = set()
        deduped = []
        for s in samples:
            key = (s["mid"], s.get("thread_ref"))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(s)
        samples = deduped
    samples = samples[:args.limit]

    print(f"# Underinjection judge — same_thread_context_sufficient skips with rs>={args.min_rs}")
    print(f"sampled {len(samples)} of {len(rows)} skips")

    config = AppConfig.from_env()
    provider = build_llm_provider(
        config, provider_name="hai",
        model="claude-sonnet-latest",
    )

    counts = {"yes_helpful": 0, "no_helpful": 0, "neutral": 0}
    table_lines = ["| # | rs | type | subject | query | verdict | reason |", "|-|-|-|-|-|-|-|"]
    started = time.time()
    for i, s in enumerate(samples, 1):
        user_prompt = (
            f"User query:\n{_excerpt(s['query'], 800)}\n\n"
            f"Top candidate memory:\n"
            f"  type: {s['type']}\n"
            f"  subject: {_excerpt(s['subject'], 200)}\n"
            f"  body: {_excerpt(s['body'], 600)}\n"
            f"  routing_score: {s['rs']:.0f}\n\n"
            "Would showing this memory help? Respond with the JSON schema."
        )
        try:
            resp = provider.generate_json(
                system_prompt=JUDGE_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                schema_description=JUDGE_SCHEMA,
            )
            verdict = str(resp.parsed_json.get("verdict", "neutral")).strip()
            reason = str(resp.parsed_json.get("reason", ""))[:200]
        except Exception as exc:
            verdict = "neutral"
            reason = f"[err: {exc!r}]"

        if verdict not in counts:
            verdict = "neutral"
        counts[verdict] += 1
        s["verdict"] = verdict
        s["reason"] = reason

        print(f"  [{i}/{len(samples)}] rs={s['rs']:.0f} type={s['type']} -> {verdict}  ({reason[:80]})")
        table_lines.append(
            f"| {i} | {s['rs']:.0f} | {s['type']} | {_excerpt(s['subject'], 40).replace('|','/')} "
            f"| {_excerpt(s['query'], 50).replace('|','/')} | {verdict} | {reason.replace('|','/')[:80]} |"
        )

    elapsed = time.time() - started
    n = sum(counts.values())
    yes_rate = counts["yes_helpful"] / n if n else 0
    no_rate = counts["no_helpful"] / n if n else 0
    nu_rate = counts["neutral"] / n if n else 0

    if yes_rate >= 0.50:
        verdict_line = "VERDICT: routing-gate calibration IS the priority lever (yes >= 50%)"
    elif yes_rate < 0.30:
        verdict_line = "VERDICT: skips are mostly correct — underinjection NOT the blocker (yes < 30%)"
    else:
        verdict_line = "VERDICT: ambiguous (30-50% helpful) — sample more or look at patterns"

    out = "\n".join([
        f"# Underinjection judge — `same_thread_context_sufficient` skips",
        "",
        f"- since: {args.since}",
        f"- min routing_score in pool: {args.min_rs}",
        f"- sampled: {n} of {len(rows)} skips",
        f"- yes_helpful: {counts['yes_helpful']} ({yes_rate*100:.0f}%)",
        f"- no_helpful:  {counts['no_helpful']}  ({no_rate*100:.0f}%)",
        f"- neutral:     {counts['neutral']} ({nu_rate*100:.0f}%)",
        f"- judged in {elapsed:.0f}s",
        "",
        f"## {verdict_line}",
        "",
        "## Per-case verdicts",
        "",
        *table_lines,
    ])
    print()
    print(out)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(out, encoding="utf-8")
        print(f"\nwrote {args.out}")
        # JSONL sidecar: one labeled row per judged sample, for building a
        # re-admission counterfactual rule (judge verdict = ground truth).
        jsonl_path = args.out.with_suffix(".jsonl")
        with jsonl_path.open("w", encoding="utf-8") as fh:
            for s in samples:
                fh.write(json.dumps({
                    "audit_id": s["audit_id"],
                    "container_ref": s.get("container_ref"),
                    "query": s["query"][:300],
                    "rs": s["rs"],
                    "rank": s["rank"],
                    "layer": s["type"],
                    "memory_type": s.get("memory_type"),
                    "lexical_score": s.get("lexical_score"),
                    "vector_score": s.get("vector_score"),
                    "support_grade": s.get("support_grade"),
                    "subject": s["subject"][:200],
                    "verdict": s.get("verdict", "neutral"),
                    "reason": s.get("reason", ""),
                }) + "\n")
        print(f"wrote {jsonl_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
