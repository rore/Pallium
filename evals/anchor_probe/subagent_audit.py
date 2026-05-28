"""Per-injection-decision qualitative judge.

For each case where a candidate rule's keep/drop decision differs from
baseline, ask an LLM judge: was the rule's call better, worse, or neutral
than the baseline's call, given the user query and the candidate memory?

Inputs:
  - a list of `Case` objects (from `replay_harness.load_cases`)
  - a rule callable `(Case) -> bool` (returns True if the rule would keep
    the candidate)

Outputs:
  - Counts of better / worse / neutral
  - A markdown table of per-case verdicts

Usage as a library:
    from evals.anchor_probe.subagent_audit import audit_rule
    cases = load_cases(db, since)
    summary = audit_rule(cases, rule_fn, rule_name="rs>=400", limit=30)

Usage as a CLI (stand-alone smoke check):
    python -m evals.anchor_probe.subagent_audit --rule rs400 \
        --since 2026-05-18 --limit 20

Notes:
- Every change must be validated data-driven; this judge is the
  qualitative side of that validation. Quantitative side stays the rated
  slice from the replay harness.
- The judge has no access to the rating field. The rule's decision and
  the baseline's decision are masked as "decision A" / "decision B" so
  the judge cannot game on which side the rule is.
- Public-repo terminology only. Memory text and query text are passed
  verbatim from the local DB; treat them as potentially non-public.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.config import AppConfig  # noqa: E402
from app.dependencies import build_llm_provider  # noqa: E402
from evals.anchor_probe.replay_harness import (  # noqa: E402
    Case,
    load_cases,
    rule_baseline,
    rule_R2_subject_overlap,
    rule_R2b_subject_overlap_2,
)

# ---------------------------------------------------------------------------
# Judge prompt
# ---------------------------------------------------------------------------

JUDGE_SYSTEM_PROMPT = """\
You are reviewing one memory-injection decision made by an AI agent's
memory system. The system retrieved a candidate memory for a user query.
Two different gating policies disagree about whether to inject this
memory.

Your job is to decide whether DECISION A or DECISION B is the better call
on the *signal level* — would the user be better served if this memory
were shown (kept) or hidden (dropped)?

Definitions:
- "kept" = the memory is shown to the agent as injected context.
- "dropped" = the memory is suppressed and never shown.

Judging criteria:
1. Topical relevance: is the memory's subject actually related to what
   the user is asking about *now*?
2. Specific usefulness: would a competent agent reading this memory be
   better off (more accurate, less wasted reasoning) than not reading
   it? Vague / generic / over-summarized memories are worse than no
   memory at all.
3. Distractor risk: an off-topic memory pulls the agent toward the
   wrong answer. Treat clearly off-topic injections as harmful.

Calibrate:
- If the memory is clearly off-topic for this query, "dropped" is the
  better call.
- If the memory is clearly on-topic and substantive, "kept" is the
  better call.
- If the memory is on-topic but redundant with what the agent already
  has from the immediate conversation, "dropped" is mildly better.
- If you genuinely cannot tell, say "neutral".

Return a JSON object with:
- verdict: one of "A_better", "B_better", "neutral"
- reason: one short sentence explaining why (under 30 words).
"""

JUDGE_SCHEMA = '{"verdict":"string","reason":"string"}'


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class CaseVerdict:
    fid: str
    rated_mid: str
    rated_type: str
    rating: str
    query_excerpt: str
    subject_excerpt: str
    body_excerpt: str
    baseline_keep: bool
    rule_keep: bool
    rule_correct: str  # "better" | "worse" | "neutral"
    judge_reason: str
    judge_raw_verdict: str  # "A_better" | "B_better" | "neutral"
    a_is_baseline: bool


@dataclass
class AuditSummary:
    rule_name: str
    n_total: int
    n_differ: int
    n_judged: int
    counts: dict
    rule_better_rate: float
    rule_worse_rate: float
    rule_neutral_rate: float
    table_md: str


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _excerpt(s: str, n: int = 400) -> str:
    s = (s or "").replace("\n", " ").strip()
    return s[:n]


def _build_user_prompt(case: Case, a_is_baseline: bool, baseline_keep: bool, rule_keep: bool) -> str:
    a_decision = "kept" if (baseline_keep if a_is_baseline else rule_keep) else "dropped"
    b_decision = "kept" if (rule_keep if a_is_baseline else baseline_keep) else "dropped"
    return (
        f"User query:\n{_excerpt(case.query, 800)}\n\n"
        f"Candidate memory:\n"
        f"  type: {case.rated_type}\n"
        f"  subject: {_excerpt(case.memory_subject, 200)}\n"
        f"  body: {_excerpt(case.memory_text, 800)}\n\n"
        f"DECISION A: {a_decision}\n"
        f"DECISION B: {b_decision}\n\n"
        "Which decision is better? Respond with the JSON schema."
    )


def _interpret_verdict(raw: str, a_is_baseline: bool) -> str:
    raw = (raw or "").strip()
    if raw == "neutral":
        return "neutral"
    rule_won = (raw == "B_better") if a_is_baseline else (raw == "A_better")
    if rule_won:
        return "better"
    if raw in ("A_better", "B_better"):
        return "worse"
    return "neutral"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def audit_rule(
    cases: list[Case],
    rule_fn,
    *,
    rule_name: str,
    limit: int | None = 30,
    seed: int = 17,
    config: AppConfig | None = None,
    provider=None,
    verbose: bool = False,
) -> AuditSummary:
    """Run the qualitative judge on the differing cases.

    Returns an AuditSummary including per-case verdicts.
    """
    config = config or AppConfig.from_env()
    if provider is None:
        provider = build_llm_provider(
            config,
            provider_name="hai_anthropic",
            model="anthropic--claude-sonnet-latest",
        )

    rng = random.Random(seed)
    differ: list[Case] = []
    for c in cases:
        b = rule_baseline(c)
        r = rule_fn(c)
        if b != r:
            differ.append(c)

    rng.shuffle(differ)
    sampled = differ if (limit is None or limit >= len(differ)) else differ[:limit]

    verdicts: list[CaseVerdict] = []
    counts = {"better": 0, "worse": 0, "neutral": 0}

    for i, c in enumerate(sampled, 1):
        b = rule_baseline(c)
        r = rule_fn(c)
        a_is_baseline = bool(rng.random() < 0.5)

        user_prompt = _build_user_prompt(c, a_is_baseline, b, r)
        try:
            response = provider.generate_json(
                system_prompt=JUDGE_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                schema_description=JUDGE_SCHEMA,
            )
            parsed = response.parsed_json
            raw_verdict = str(parsed.get("verdict", "neutral"))
            judge_reason = str(parsed.get("reason", ""))[:300]
        except Exception as exc:
            raw_verdict = "neutral"
            judge_reason = f"[judge error: {exc!r}]"

        rule_correct = _interpret_verdict(raw_verdict, a_is_baseline)
        counts[rule_correct] += 1

        verdicts.append(
            CaseVerdict(
                fid=c.fid,
                rated_mid=(c.rated_mid or "")[:8],
                rated_type=c.rated_type,
                rating=c.rating,
                query_excerpt=_excerpt(c.query, 80),
                subject_excerpt=_excerpt(c.memory_subject, 60),
                body_excerpt=_excerpt(c.memory_text, 80),
                baseline_keep=b,
                rule_keep=r,
                rule_correct=rule_correct,
                judge_reason=judge_reason,
                judge_raw_verdict=raw_verdict,
                a_is_baseline=a_is_baseline,
            )
        )

        if verbose:
            print(
                f"  [{i}/{len(sampled)}] {c.fid[:8]}  base={b} rule={r}  "
                f"-> {rule_correct}  ({judge_reason[:80]})"
            )

    n_judged = len(verdicts)
    rule_better_rate = counts["better"] / n_judged if n_judged else 0.0
    rule_worse_rate = counts["worse"] / n_judged if n_judged else 0.0
    rule_neutral_rate = counts["neutral"] / n_judged if n_judged else 0.0

    table = _format_verdict_table(verdicts)

    return AuditSummary(
        rule_name=rule_name,
        n_total=len(cases),
        n_differ=len(differ),
        n_judged=n_judged,
        counts=counts,
        rule_better_rate=rule_better_rate,
        rule_worse_rate=rule_worse_rate,
        rule_neutral_rate=rule_neutral_rate,
        table_md=table,
    )


def _format_verdict_table(verdicts: list[CaseVerdict]) -> str:
    lines = [
        "| # | fid | mid | type | rating | base/rule | verdict | reason |",
        "|-|-|-|-|-|-|-|-|",
    ]
    for i, v in enumerate(verdicts, 1):
        bk = "K" if v.baseline_keep else "D"
        rk = "K" if v.rule_keep else "D"
        reason = v.judge_reason.replace("|", "/").replace("\n", " ")[:80]
        subj_or_q = (v.subject_excerpt or v.query_excerpt).replace("|", "/")
        lines.append(
            f"| {i} | {v.fid[:8]} | {v.rated_mid} | {v.rated_type} | "
            f"{v.rating[:3]} | {bk}/{rk} | {v.rule_correct} | {reason} |"
        )
    return "\n".join(lines)


def format_summary(summary: AuditSummary) -> str:
    lines = [
        f"# Subagent qualitative judge — {summary.rule_name}",
        "",
        f"- total cases: {summary.n_total}",
        f"- cases where rule differs from baseline: {summary.n_differ}",
        f"- judged: {summary.n_judged}",
        f"- rule better: {summary.counts['better']}  "
        f"({summary.rule_better_rate*100:.0f}%)",
        f"- rule worse:  {summary.counts['worse']}   "
        f"({summary.rule_worse_rate*100:.0f}%)",
        f"- neutral:     {summary.counts['neutral']} "
        f"({summary.rule_neutral_rate*100:.0f}%)",
        "",
        "## Per-case verdicts",
        "",
        summary.table_md,
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI smoke entry point
# ---------------------------------------------------------------------------


def _resolve_named_rule(name: str):
    """Map short names used by the CLI to rule callables."""
    name = name.lower()
    if name in ("baseline", "bl"):
        return rule_baseline, "baseline"
    if name in ("subj1", "r2"):
        return (lambda c: rule_R2_subject_overlap(c, 1)), "subject_overlap>=1"
    if name in ("subj2", "r2b"):
        return rule_R2b_subject_overlap_2, "subject_overlap>=2"
    if name in ("rs400",):
        def fn(c: Case) -> bool:
            if not rule_baseline(c):
                return False
            rs = (c.target_candidate or {}).get("routing_score") or 0
            return rs >= 400
        return fn, "routing_score>=400"
    if name in ("rs400+subj2",):
        def fn(c: Case) -> bool:
            if not rule_baseline(c):
                return False
            rs = (c.target_candidate or {}).get("routing_score") or 0
            if rs < 400:
                return False
            return rule_R2_subject_overlap(c, 2)
        return fn, "routing_score>=400 AND subject_overlap>=2"
    if name in ("rs300",):
        def fn(c: Case) -> bool:
            if not rule_baseline(c):
                return False
            rs = (c.target_candidate or {}).get("routing_score") or 0
            return rs >= 300
        return fn, "routing_score>=300"
    if name in ("drop_io",):
        def fn(c: Case) -> bool:
            if not rule_baseline(c):
                return False
            return c.rated_type != "investigation_outcome"
        return fn, "drop_investigation_outcome"
    if name in ("drop_io_selfref",):
        self_ref_terms = {"pallium", "memory", "extraction", "investigation", "injection"}
        def fn(c: Case) -> bool:
            if not rule_baseline(c):
                return False
            if c.rated_type != "investigation_outcome":
                return True
            if "rore/pallium" not in (c.container or ""):
                return True
            q_lower = (c.query or "").lower()
            if any(t in q_lower for t in self_ref_terms):
                return False
            return True
        return fn, "drop investigation_outcome in self-referential pallium queries"
    raise SystemExit(f"unknown rule name: {name!r}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(Path.home() / ".pallium" / "data" / "pallium.db"))
    ap.add_argument("--since", default="2026-05-18")
    ap.add_argument("--rule", required=True, help="Rule name (rs400, rs400+subj2, subj2, drop_io, ...)")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    rule_fn, pretty = _resolve_named_rule(args.rule)
    cases = load_cases(args.db, args.since)
    print(f"# Subagent audit — {pretty}")
    print(f"loaded {len(cases)} rated cases since {args.since}")

    started = time.time()
    summary = audit_rule(
        cases,
        rule_fn,
        rule_name=pretty,
        limit=args.limit,
        seed=args.seed,
        verbose=args.verbose,
    )
    elapsed = time.time() - started

    out_md = format_summary(summary) + f"\n\n_judged in {elapsed:.1f}s_\n"
    print(out_md)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(out_md, encoding="utf-8")
        print(f"\nwrote {args.out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
