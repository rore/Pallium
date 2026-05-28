"""B5 — counterfactual subject-anchor judge.

The 6 failing rules (rs400, drop_io, etc.) all dropped many RELEVANT
cards. This experiment asks: for those wrongly-dropped cases, would a
hypothetical "subject-anchor" rule have caught the relevance signal that
score/type filtering missed?

Hypothetical rule: keep the candidate iff the memory's subject (the
extracted, structured subject text — not body) is a coherent answer to
the user's query, ignoring routing_score, layer, and type.

This is the lightest possible signal — we are testing whether the SHAPE
of memories (their subjects) carries more usable signal than score/type
floors at injection time. If yes, that points future work toward
embedding-on-subject or stricter subject extraction. If no, the
extraction layer is producing weak subjects and we need to fix subjects
before we can trust them as a routing signal.

Cost: ≤ 30 LLM calls.

Usage:
  python -m evals.anchor_probe.counterfactual_subject_anchor
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
from evals.anchor_probe.replay_harness import load_cases, rule_baseline  # noqa: E402

JUDGE_SYSTEM_PROMPT = """\
You are auditing a single memory candidate.

You are shown:
- the user query
- the candidate memory's SUBJECT only (not the body)
- the candidate's TYPE

The current production routing system DROPPED this candidate using a
score-or-type filter. We're testing a hypothetical alternative:
"subject-anchor" routing — keep the candidate iff the subject ALONE
is a coherent answer to the query.

Apply the hypothetical rule. Use ONLY the subject. Ignore type as a
filter; type is only there for context.

Be calibrated:
- Subject directly addresses the query topic with a specific noun phrase
  the user could find useful → KEEP.
- Subject is a generic/vague phrase ("findings", "decisions", "summary")
  → DROP.
- Subject mentions a clearly different topic from the query → DROP.

Return JSON:
- keep: true | false
- reason: short sentence (under 25 words)
"""

JUDGE_SCHEMA = '{"keep":"boolean","reason":"string"}'


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
                    / "counterfactual_subject_anchor_2026-05-27.md")
    args = ap.parse_args()

    cases = load_cases(args.db, args.since)
    print(f"loaded {len(cases)} rated cases")

    # Build the wrongly-dropped set: rule_rs400 OR rule_drop_io dropped a
    # RELEVANT card that baseline kept.
    wronged = []
    for c in cases:
        if c.rating != "relevant":
            continue
        if not rule_baseline(c):
            continue
        rs400_kept = _rule_rs400(c)
        drop_io_kept = _rule_drop_io(c)
        if not rs400_kept or not drop_io_kept:
            wronged.append((c, "rs400" if not rs400_kept else "drop_io"))

    # Dedupe by (mid, query[:80]) for sanity.
    seen = set(); deduped = []
    for c, by in wronged:
        key = (c.rated_mid, c.query[:80])
        if key in seen: continue
        seen.add(key); deduped.append((c, by))
    deduped = deduped[:args.limit]
    print(f"wrongly-dropped cases (RELEVANT, dropped by rs400 OR drop_io): {len(wronged)} -> {len(deduped)} after dedupe/limit")

    config = AppConfig.from_env()
    provider = build_llm_provider(
        config, provider_name="hai_anthropic",
        model="anthropic--claude-sonnet-latest",
    )

    started = time.time()
    counts = {"keep": 0, "drop": 0, "err": 0}
    table = ["| # | by | type | subject | query | keep | reason |", "|-|-|-|-|-|-|-|"]
    for i, (c, by) in enumerate(deduped, 1):
        user_prompt = (
            f"User query:\n{_excerpt(c.query, 600)}\n\n"
            f"Candidate:\n  type: {c.rated_type}\n"
            f"  subject: {_excerpt(c.memory_subject or c.memory_text[:80], 200)}\n\n"
            "Apply the hypothetical rule (subject only). Respond JSON."
        )
        try:
            resp = provider.generate_json(
                system_prompt=JUDGE_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                schema_description=JUDGE_SCHEMA,
            )
            keep = bool(resp.parsed_json.get("keep"))
            reason = str(resp.parsed_json.get("reason", ""))[:200]
        except Exception as exc:
            keep = False
            reason = f"[err: {exc!r}]"
            counts["err"] += 1
        if keep: counts["keep"] += 1
        else:    counts["drop"] += 1
        subj = _excerpt(c.memory_subject or c.memory_text[:60], 40).replace("|", "/")
        q = _excerpt(c.query, 50).replace("|", "/")
        print(f"  [{i}/{len(deduped)}] by={by} type={c.rated_type} -> {'KEEP' if keep else 'drop'}  ({reason[:80]})")
        table.append(
            f"| {i} | {by} | {c.rated_type} | {subj} | {q} | {'Y' if keep else 'N'} | {reason.replace('|','/')[:80]} |"
        )

    elapsed = time.time() - started
    n = counts["keep"] + counts["drop"]
    keep_rate = counts["keep"] / n if n else 0

    if keep_rate >= 0.70:
        verdict = "VERDICT: subject alone catches >=70% of wrongly-dropped relevant cards — subject-anchor is a strong signal"
    elif keep_rate >= 0.50:
        verdict = "VERDICT: subject catches 50-70% — moderate signal, worth investigating"
    else:
        verdict = "VERDICT: subject alone catches <50% — subjects are too weak/generic; fix extraction first"

    out = "\n".join([
        f"# Counterfactual subject-anchor judge",
        "",
        f"- since: {args.since}",
        f"- wrongly-dropped relevant cards (by rs400 OR drop_io): {len(wronged)} (judged: {n})",
        f"- subject judged KEEP: {counts['keep']} ({keep_rate*100:.0f}%)",
        f"- subject judged DROP: {counts['drop']}",
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
