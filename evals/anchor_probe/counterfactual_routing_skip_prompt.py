"""B4 — counterfactual routing-skip prompt judge.

The current `same_thread_context_sufficient` short-circuit fires before
the candidate pool is examined. I1 found that on 30 sampled skips with
top routing_score >= 400, 60% of the candidates would have been helpful
(yes_helpful).

This experiment tests the OTHER side: if we added a "reconsider"
HYPOTHETICAL prompt rule to the skip path that says "don't skip when a
high-routing-score candidate clearly answers the query", how often would
that produce a better outcome?

Note: I1 already implies the answer should be similar (~60%). B4 is a
robustness check using a different framing of the SAME data — if B4
disagrees materially with I1, the "60% useful skip" finding is fragile
and we should distrust both.

We are NOT shipping any change. Counterfactual analysis only.

Cost: ~30 LLM calls.
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

HYPOTHETICAL_RULE = """\
HYPOTHETICAL ROUTING RULE — when the standard 'same_thread_context_sufficient'
short-circuit would normally fire (the current immediate conversation
appears to provide enough context), reconsider before skipping if a
candidate memory in the retrieval pool has BOTH:

  (a) routing_score >= 400 (top 1/4 of strong routes)
  (b) a subject/body that DIRECTLY ANSWERS the user's current query
      with a fact, decision, or finding the agent would not otherwise
      have access to from the immediate turn.

If (a) AND (b), inject the candidate. Otherwise, skip as before.
"""

JUDGE_SYSTEM_PROMPT = f"""\
You are auditing routing-quality. The system fired a 'skip' decision
because immediate-conversation context appeared sufficient. We are
testing a hypothetical NEW rule that would have reconsidered.

Given:
- the user query that triggered the audit
- the top-routing-score candidate from the retrieval pool that was NOT
  injected because the system skipped

Apply the HYPOTHETICAL rule below. Should the rule have FIRED (i.e.,
override the skip and inject this candidate)?

HYPOTHETICAL RULE:
{HYPOTHETICAL_RULE}

Be calibrated:
- Only say YES (rule should fire) if the candidate clearly adds something
  the user would not have from the immediate turn alone.
- Vague / generic candidates → NO.
- Off-topic candidates → NO.

Return JSON:
- rule_fires: true | false
- reason: one short sentence (under 25 words)
"""

JUDGE_SCHEMA = '{"rule_fires":"boolean","reason":"string"}'


def _excerpt(s: str, n: int = 600) -> str:
    return (s or "").replace("\n", " ").strip()[:n]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(Path.home() / ".pallium" / "data" / "pallium.db"))
    ap.add_argument("--since", default="2026-05-18")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--min-rs", type=int, default=400)
    ap.add_argument("--distinct", action="store_true", default=True)
    ap.add_argument("--out", type=Path,
                    default=_PROJECT_ROOT / ".local" / "research"
                    / "counterfactual_routing_skip_prompt_2026-05-27.md")
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
    seen = set()
    for r in rows:
        cs = json.loads(r["candidate_scores_json"]) or []
        if not cs:
            continue
        top = max(cs, key=lambda c: (c.get("routing_score") or 0))
        rs = (top.get("routing_score") or 0)
        if rs < args.min_rs:
            continue
        mid = top.get("memory_object_id")
        if args.distinct:
            key = (mid, r["thread_ref"])
            if key in seen:
                continue
            seen.add(key)
        m = con.execute(
            "SELECT subject, payload_json FROM memory_objects WHERE id=?",
            (mid,),
        ).fetchone()
        subj = ""; body = ""
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
            "type": top.get("layer"),
            "mid": mid,
            "subject": subj, "body": body,
        })

    samples.sort(key=lambda s: -s["rs"])
    samples = samples[:args.limit]

    config = AppConfig.from_env()
    provider = build_llm_provider(
        config, provider_name="hai_anthropic",
        model="anthropic--claude-sonnet-latest",
    )

    started = time.time()
    counts = {"yes": 0, "no": 0, "err": 0}
    table = ["| # | rs | type | subject | query | fires | reason |", "|-|-|-|-|-|-|-|"]
    for i, s in enumerate(samples, 1):
        user_prompt = (
            f"User query:\n{_excerpt(s['query'], 800)}\n\n"
            f"Top candidate:\n  type: {s['type']}\n"
            f"  subject: {_excerpt(s['subject'], 200)}\n"
            f"  body: {_excerpt(s['body'], 600)}\n"
            f"  routing_score: {s['rs']:.0f}\n\n"
            "Apply the hypothetical rule. Respond JSON."
        )
        try:
            resp = provider.generate_json(
                system_prompt=JUDGE_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                schema_description=JUDGE_SCHEMA,
            )
            fires = bool(resp.parsed_json.get("rule_fires"))
            reason = str(resp.parsed_json.get("reason", ""))[:200]
        except Exception as exc:
            fires = False
            reason = f"[err: {exc!r}]"
            counts["err"] += 1
        if fires: counts["yes"] += 1
        else:     counts["no"] += 1
        print(f"  [{i}/{len(samples)}] rs={s['rs']:.0f} type={s['type']} -> {'FIRE' if fires else 'skip'}  ({reason[:80]})")
        table.append(
            f"| {i} | {s['rs']:.0f} | {s['type']} | {_excerpt(s['subject'], 40).replace('|','/')} "
            f"| {_excerpt(s['query'], 50).replace('|','/')} | {'Y' if fires else 'N'} | {reason.replace('|','/')[:80]} |"
        )

    elapsed = time.time() - started
    n = counts["yes"] + counts["no"]
    yes_rate = counts["yes"] / n if n else 0
    if yes_rate >= 0.50:
        verdict = "VERDICT: hypothetical reconsider rule fires often (>=50%) — confirms underinjection lever"
    elif yes_rate < 0.30:
        verdict = "VERDICT: hypothetical rule rarely fires (<30%) — disagrees with I1, distrust both findings"
    else:
        verdict = "VERDICT: hypothetical rule fires moderately (30-50%) — partial confirmation"

    out = "\n".join([
        f"# Counterfactual routing-skip prompt judge",
        "",
        f"- since: {args.since}",
        f"- min routing_score: {args.min_rs}",
        f"- sampled: {n} skips (distinct: {args.distinct})",
        f"- rule fires: {counts['yes']} ({yes_rate*100:.0f}%)",
        f"- rule skips: {counts['no']}",
        f"- errors: {counts['err']}",
        f"- elapsed: {elapsed:.0f}s",
        "",
        f"## {verdict}",
        "",
        "## Hypothetical rule tested",
        "",
        "```",
        HYPOTHETICAL_RULE,
        "```",
        "",
        "## Per-case verdicts",
        "",
        *table,
    ])
    print()
    print(out)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(out, encoding="utf-8")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
