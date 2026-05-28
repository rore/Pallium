"""B8 — NR collateral check on better-subject hypothesis.

B6 found that for 26 wrongly-dropped RELEVANT cards, a body-anchored
noun-phrase subject would anchor the user query 73% of the time. The
question this experiment answers: would the same hypothetical apply
generously to the NOT_RELEVANT side too? If yes, the 73% lift is
illusory — a body-anchored subject would simply look related to ANY
query, including off-topic ones.

Method: take the NR rated cards (rating='not_relevant') from the same
window, apply the same B6 judge prompt, and measure the rate at which
the judge says a body-anchored subject would still anchor the query.

Decision rule:
  - NR-recover rate <= 30% ⇒ B6 lift is real (REL 73% / NR ≤30% =
    clean differential signal).
  - NR-recover rate 30-50% ⇒ partial (lift exists but smaller).
  - NR-recover rate > 50% ⇒ B6 lift is illusory (judge generously
    says any body anchors any query).

Cost: ≤30 LLM calls.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.config import AppConfig  # noqa: E402
from app.dependencies import build_llm_provider  # noqa: E402
from evals.anchor_probe.replay_harness import load_cases, rule_baseline  # noqa: E402
from evals.anchor_probe.counterfactual_better_subject import (  # noqa: E402
    JUDGE_SYSTEM_PROMPT, JUDGE_SCHEMA, _excerpt,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(Path.home() / ".pallium" / "data" / "pallium.db"))
    ap.add_argument("--since", default="2026-05-18")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--out", type=Path,
                    default=_PROJECT_ROOT / ".local" / "research"
                    / "counterfactual_better_subject_NR_collateral_2026-05-27.md")
    args = ap.parse_args()

    cases = load_cases(args.db, args.since)
    nr_cases = [c for c in cases if c.rating == "not_relevant"]
    seen = set(); deduped = []
    for c in nr_cases:
        key = (c.rated_mid, c.query[:80])
        if key in seen: continue
        seen.add(key); deduped.append(c)
    deduped = deduped[:args.limit]
    print(f"NR cards: {len(nr_cases)} -> {len(deduped)} after dedupe/limit")

    config = AppConfig.from_env()
    provider = build_llm_provider(
        config, provider_name="hai_anthropic",
        model="anthropic--claude-sonnet-latest",
    )

    started = time.time()
    counts = {"yes": 0, "no": 0, "err": 0}
    table = ["| # | type | current_subject | proposed_subject | query | recover | reason |", "|-|-|-|-|-|-|-|"]
    for i, c in enumerate(deduped, 1):
        user_prompt = (
            f"User query:\n{_excerpt(c.query, 600)}\n\n"
            f"Current subject: {_excerpt(c.memory_subject, 200)}\n\n"
            f"Body:\n{_excerpt(c.memory_text, 800)}\n\n"
            "Apply the hypothetical rule. Respond JSON."
        )
        try:
            resp = provider.generate_json(
                system_prompt=JUDGE_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                schema_description=JUDGE_SCHEMA,
            )
            rec = bool(resp.parsed_json.get("recoverable"))
            ps = str(resp.parsed_json.get("proposed_subject", ""))[:80]
            rs = str(resp.parsed_json.get("reason", ""))[:200]
        except Exception as exc:
            rec = False; ps = ""; rs = f"[err: {exc!r}]"
            counts["err"] += 1
        if rec: counts["yes"] += 1
        else:   counts["no"] += 1
        cur = _excerpt(c.memory_subject or "(none)", 35).replace("|", "/")
        q = _excerpt(c.query, 40).replace("|", "/")
        ps_short = ps.replace("|", "/")[:40]
        print(f"  [{i}/{len(deduped)}] type={c.rated_type} -> {'REC' if rec else 'no'}  ({rs[:80]})")
        table.append(
            f"| {i} | {c.rated_type} | {cur} | {ps_short} | {q} | {'Y' if rec else 'N'} | {rs.replace('|','/')[:80]} |"
        )

    elapsed = time.time() - started
    n = counts["yes"] + counts["no"]
    yes_rate = counts["yes"] / n if n else 0
    if yes_rate <= 0.30:
        verdict = "VERDICT: B6 lift is REAL — NR collateral is low (REL 73% vs NR <=30% = clean differential)"
    elif yes_rate <= 0.50:
        verdict = "VERDICT: B6 lift is PARTIAL — NR collateral 30-50% means some illusion in the 73%"
    else:
        verdict = "VERDICT: B6 lift is ILLUSORY — NR collateral >50% means the judge generously anchors any body to any query"

    out = "\n".join([
        f"# Counterfactual better-subject — NR collateral check",
        "",
        f"- since: {args.since}",
        f"- NR cards (deduped): {n}",
        f"- judge says NR ALSO recoverable: {counts['yes']} ({yes_rate*100:.0f}%)",
        f"- judge says NR not recoverable: {counts['no']}",
        f"- errors: {counts['err']}",
        f"- elapsed: {elapsed:.0f}s",
        "",
        f"## {verdict}",
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
