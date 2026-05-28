"""B6 — counterfactual better-subject judge.

Hypothesis: subject extraction is too generic; if subjects were rewritten
as the first concrete noun phrase from the BODY, the same subject-only
relevance signal (B5: 54%) would lift substantially.

Method: for the 26 wrongly-dropped relevant cards from B5, give the
judge the QUERY + the FULL BODY (not just subject) and ask: "is the body
specific enough to provide a better subject? if you rewrote the subject
to be the first concrete noun phrase from the body, would that subject
be a clear answer to the query?"

This is a counterfactual on the EXTRACTION layer: would better subjects
have caught these cards?

Decision rule:
  - improved_keep_rate >= 75% ⇒ subject extraction is the lever — fix
    extraction prompts, not routing.
  - improved_keep_rate 50-75% ⇒ partial — subjects help but other
    issues remain.
  - <50% ⇒ subjects can't be rescued by rephrasing; deeper signal
    issue.

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

JUDGE_SYSTEM_PROMPT = """\
You audit subject quality for a memory-retrieval system.

You are shown:
1. A user query.
2. The CURRENT subject the production extractor produced for a memory.
3. The full BODY of that memory.

Imagine a HYPOTHETICAL improved extractor that rewrites the subject as
"the first concrete, specific noun phrase from the body that names the
topic the body is actually about." A concrete noun phrase mentions
specific systems, files, decisions, entities — not generic words like
"findings", "summary", "task", "discussion".

Your job:
- Step 1: in your head, write a hypothetical improved subject (do not
  output it; just use it for judgment).
- Step 2: would that hypothetical improved subject — alone — be a clear
  answer-anchor for the user query?

Calibrate:
- If the body is so generic itself that no concrete subject exists →
  not_recoverable.
- If a concrete subject exists in the body AND it would clearly anchor
  the query → recoverable.
- If a concrete subject exists in the body BUT it's about a different
  topic than the query → not_recoverable.

Return JSON:
- recoverable: true | false
- proposed_subject: short phrase (≤60 chars) you would have used
- reason: one sentence (≤25 words)
"""

JUDGE_SCHEMA = '{"recoverable":"boolean","proposed_subject":"string","reason":"string"}'


def _excerpt(s: str, n: int = 600) -> str:
    return (s or "").replace("\n", " ").strip()[:n]


def _rule_rs400(c) -> bool:
    if not rule_baseline(c):
        return False
    rs = (c.target_candidate or {}).get("routing_score") or 0
    return rs >= 400


def _rule_drop_io(c) -> bool:
    if not rule_baseline(c):
        return False
    return c.rated_type != "investigation_outcome"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(Path.home() / ".pallium" / "data" / "pallium.db"))
    ap.add_argument("--since", default="2026-05-18")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--out", type=Path,
                    default=_PROJECT_ROOT / ".local" / "research"
                    / "counterfactual_better_subject_2026-05-27.md")
    args = ap.parse_args()

    cases = load_cases(args.db, args.since)
    wronged = []
    for c in cases:
        if c.rating != "relevant" or not rule_baseline(c):
            continue
        if not _rule_rs400(c) or not _rule_drop_io(c):
            wronged.append(c)
    seen = set(); deduped = []
    for c in wronged:
        key = (c.rated_mid, c.query[:80])
        if key in seen: continue
        seen.add(key); deduped.append(c)
    deduped = deduped[:args.limit]
    print(f"wrongly-dropped relevant cards: {len(wronged)} -> {len(deduped)} after dedupe/limit")

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
    if yes_rate >= 0.75:
        verdict = "VERDICT: subject extraction is the lever — better subjects would catch >=75% of wrongly-dropped relevant cards"
    elif yes_rate >= 0.50:
        verdict = "VERDICT: subject extraction helps (50-75%) — partial lever"
    else:
        verdict = "VERDICT: subjects can't be rescued by rephrasing (<50%) — deeper signal issue"

    out = "\n".join([
        f"# Counterfactual better-subject judge",
        "",
        f"- since: {args.since}",
        f"- wrongly-dropped relevant cards (rs400 OR drop_io dropped): {len(wronged)} -> {len(deduped)} after dedupe/limit",
        f"- recoverable with better subject: {counts['yes']} ({yes_rate*100:.0f}%)",
        f"- not recoverable: {counts['no']}",
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
