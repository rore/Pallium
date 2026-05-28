"""B3 — counterfactual extraction-prompt judge.

For each NOT_RELEVANT investigation_outcome card since 2026-05-18, ask the
production Sonnet judge: given the candidate body and a hypothetical
stricter extraction rule, would the rule have suppressed this card at
write time?

Constraint: we are NOT shipping any change. We're only PROVING that a
better extraction prompt would have helped.

To control collateral damage, we also run the same hypothetical rule
against a sample of RELEVANT investigation_outcome cards from the same
window — if the rule would suppress those too, the prompt is too coarse.

Decision rule:
  - rule_kills_NR / total_NR  ≥ 70%  AND  rule_kills_REL / total_REL  ≤ 10%
    ⇒ counterfactual prompt is a clear win, queue as next work-item.
  - rule_kills_NR ≥ 50% AND rule_kills_REL ≤ 20% ⇒ partial win, useful.
  - Otherwise ⇒ rule too coarse / not the right framing.

Cost: ≤ ~50 LLM calls.

Usage:
    python -m evals.anchor_probe.counterfactual_extraction_prompt
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

# The hypothetical extraction-time guard. Stated as a prompt rule that
# would be added to the investigation_outcome extraction prompt.
HYPOTHETICAL_RULE = """\
HARD RULE — refuse to emit an investigation_outcome card if the body is
a NULL FINDING or IGNORANCE CLAIM. That is, the body asserts only that
some fact, memory, or knowledge does NOT exist or is inaccessible —
without identifying a concrete root cause, mechanism, or actionable next
step for fixing it.

Refuse when the body is dominated by phrases like:
  - "X genuinely doesn't exist"
  - "no memory about X"
  - "I don't have access to X"
  - "It doesn't exist or I don't have access"
  - "X was never ingested"
  - "the memory hasn't been written"
  - "phrase X was not preserved" (with no further analysis)
  - Any single-sentence "the answer is no" / "nothing to show" body.

DO NOT refuse if the body identifies a concrete root cause, code
location, mechanism, or actionable bug — even if the bug is in the
memory/extraction system itself. Findings ABOUT a real bug are valid
investigation_outcome cards. Findings that only restate ignorance are
not.

Output: refuse with a single JSON {"refuse": true, "reason": "..."} when
the body is a null finding / ignorance claim; emit normally otherwise.
"""

JUDGE_SYSTEM_PROMPT = f"""\
You are auditing extraction quality. You are given:
1. The HYPOTHETICAL extraction-time rule shown below (it does NOT exist
   yet in production; we are testing if adding it WOULD have helped).
2. The body of an investigation_outcome card that WAS emitted by the
   current production extractor.
3. Some context about the user query / surrounding turn that triggered
   extraction.

Your job: simulate the hypothetical rule. Given ONLY the body, would the
hypothetical rule have refused to emit this card?

Be strict about the rule's "meta-commentary" definition. Apply it the
same way every time. Do not invent additional reasons to refuse — only
the rule above.

HYPOTHETICAL RULE:
{HYPOTHETICAL_RULE}

Return JSON:
- would_refuse: true | false
- reason: short sentence (under 25 words)
"""

JUDGE_SCHEMA = '{"would_refuse":"boolean","reason":"string"}'


def _excerpt(s: str, n: int = 600) -> str:
    return (s or "").replace("\n", " ").strip()[:n]


def _fetch_cards(con: sqlite3.Connection, rating: str, since: str, limit: int | None) -> list:
    q = """
        SELECT mf.id AS fid, mf.memory_text, mf.query_context, mf.container_ref,
               mf.memory_object_id AS mid
        FROM memory_feedback mf
        WHERE mf.rating=? AND mf.memory_type='investigation_outcome'
          AND mf.created_at >= ?
        ORDER BY mf.created_at DESC
    """
    args = [rating, since]
    if limit:
        q += f" LIMIT {int(limit)}"
    return con.execute(q, args).fetchall()


def _judge_card(provider, body: str, query: str) -> tuple[bool, str]:
    user_prompt = (
        f"Card body:\n{_excerpt(body, 800)}\n\n"
        f"Surrounding query / turn that triggered extraction:\n{_excerpt(query, 400)}\n\n"
        "Apply the hypothetical rule. Respond JSON."
    )
    try:
        resp = provider.generate_json(
            system_prompt=JUDGE_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            schema_description=JUDGE_SCHEMA,
        )
        wr = bool(resp.parsed_json.get("would_refuse"))
        rs = str(resp.parsed_json.get("reason", ""))[:200]
        return wr, rs
    except Exception as exc:
        return False, f"[err: {exc!r}]"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(Path.home() / ".pallium" / "data" / "pallium.db"))
    ap.add_argument("--since", default="2026-05-18")
    ap.add_argument("--rel-limit", type=int, default=30,
                    help="Cap on RELEVANT cards to test for collateral.")
    ap.add_argument("--out", type=Path,
                    default=_PROJECT_ROOT / ".local" / "research"
                    / "counterfactual_extraction_prompt_2026-05-27.md")
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row

    nr = _fetch_cards(con, "not_relevant", args.since, None)
    rel = _fetch_cards(con, "relevant", args.since, args.rel_limit)
    print(f"# Counterfactual extraction-prompt judge")
    print(f"NR cards: {len(nr)}    REL cards (sampled): {len(rel)}")

    config = AppConfig.from_env()
    provider = build_llm_provider(
        config, provider_name="hai_anthropic",
        model="anthropic--claude-sonnet-latest",
    )

    started = time.time()
    nr_kills = 0
    nr_lines = ["| # | mid | container | query | body | refuse | reason |", "|-|-|-|-|-|-|-|"]
    for i, r in enumerate(nr, 1):
        wr, rs = _judge_card(provider, r["memory_text"] or "", r["query_context"] or "")
        if wr:
            nr_kills += 1
        cont = (r["container_ref"] or "")[-25:]
        q = (r["query_context"] or "")[:40].replace("|", "/").replace("\n", " ")
        b = (r["memory_text"] or "")[:60].replace("|", "/").replace("\n", " ")
        print(f"  NR  [{i}/{len(nr)}] mid={r['mid'][:8]} -> {'REFUSE' if wr else 'emit'}  ({rs[:80]})")
        nr_lines.append(f"| {i} | {r['mid'][:8]} | {cont} | {q} | {b} | {'Y' if wr else 'N'} | {rs[:80]} |")

    rel_kills = 0
    rel_lines = ["| # | mid | container | query | body | refuse | reason |", "|-|-|-|-|-|-|-|"]
    for i, r in enumerate(rel, 1):
        wr, rs = _judge_card(provider, r["memory_text"] or "", r["query_context"] or "")
        if wr:
            rel_kills += 1
        cont = (r["container_ref"] or "")[-25:]
        q = (r["query_context"] or "")[:40].replace("|", "/").replace("\n", " ")
        b = (r["memory_text"] or "")[:60].replace("|", "/").replace("\n", " ")
        print(f"  REL [{i}/{len(rel)}] mid={r['mid'][:8]} -> {'REFUSE' if wr else 'emit'}  ({rs[:80]})")
        rel_lines.append(f"| {i} | {r['mid'][:8]} | {cont} | {q} | {b} | {'Y' if wr else 'N'} | {rs[:80]} |")

    elapsed = time.time() - started
    nr_rate = nr_kills / len(nr) if nr else 0.0
    rel_rate = rel_kills / len(rel) if rel else 0.0

    if nr_rate >= 0.70 and rel_rate <= 0.10:
        verdict = "VERDICT: clear win — counterfactual prompt suppresses NR with low collateral"
    elif nr_rate >= 0.50 and rel_rate <= 0.20:
        verdict = "VERDICT: partial win — useful but not decisive"
    else:
        verdict = "VERDICT: rule too coarse / wrong framing — needs refinement"

    out = "\n".join([
        f"# Counterfactual extraction-prompt judge ({len(nr)} NR + {len(rel)} REL since {args.since})",
        "",
        f"- NR refused: {nr_kills}/{len(nr)} ({nr_rate*100:.0f}%)",
        f"- REL refused (collateral): {rel_kills}/{len(rel)} ({rel_rate*100:.0f}%)",
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
        "## NR cards (would the rule kill these noise cards?)",
        "",
        *nr_lines,
        "",
        "## RELEVANT cards (would the rule cause collateral damage?)",
        "",
        *rel_lines,
    ])
    print()
    print(out)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(out, encoding="utf-8")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
