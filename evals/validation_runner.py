"""Unified validation runner for Pallium gating-rule proposals.

Runs four checks defined in `.local/research/validation_playbook_2026-05-27.md`:

1. Replay rated-slice (via `evals.anchor_probe.replay_harness`).
   PASS iff: precision moves up >= +2pp AND recall drop <= 5pp absolute
   relative to baseline measured on the same rated slice.
2. Invariant runner (`evals.generated_exploratory.invariant_runner`).
   Optional: only runs when a flag-name + value is supplied via
   `--with-flag NAME=VAL`. Otherwise marked SKIPPED-NO-FLAG. PASS iff:
   scenarios_violated == 0 (no regression vs. flag OFF baseline).
3. Fact-consolidation eval (`evals.fact_consolidation_eval`).
   Same gating as Check 2: only runs with a flag. PASS iff: 3/3 PASS.
4. Qualitative judge (`evals.anchor_probe.subagent_audit`).
   PASS iff: better-rate >= 60% AND worse-rate <= 20% on differing cases.

Usage:
    python -m evals.validation_runner --rule rs400
    python -m evals.validation_runner --rule rs400+subj2 --judge-limit 20

To exercise checks 2 and 3 once a rule is shipped behind a flag:
    python -m evals.validation_runner --rule r2b \
        --with-flag PALLIUM_R2B_SUBJECT_OVERLAP_GATE=1

Output: prints a single markdown report and writes it to
.local/research/validation_<rule>_<utc>.md.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from evals.anchor_probe.replay_harness import (  # noqa: E402
    Case,
    load_cases,
    rule_baseline,
    rule_R2_subject_overlap,
)
from evals.anchor_probe.subagent_audit import (  # noqa: E402
    audit_rule,
    format_summary as format_judge_summary,
)


# ---------------------------------------------------------------------------
# Rule registry — keep in sync with subagent_audit._resolve_named_rule
# ---------------------------------------------------------------------------


def _rs_floor(thr: int) -> Callable[[Case], bool]:
    def fn(c: Case) -> bool:
        if not rule_baseline(c):
            return False
        rs = (c.target_candidate or {}).get("routing_score") or 0
        return rs >= thr
    return fn


def _rs_floor_and_subj(thr: int, sub_thr: int) -> Callable[[Case], bool]:
    def fn(c: Case) -> bool:
        if not rule_baseline(c):
            return False
        rs = (c.target_candidate or {}).get("routing_score") or 0
        if rs < thr:
            return False
        return rule_R2_subject_overlap(c, sub_thr)
    return fn


def _drop_type(t: str) -> Callable[[Case], bool]:
    def fn(c: Case) -> bool:
        if not rule_baseline(c):
            return False
        return c.rated_type != t
    return fn


def _drop_io_self_referential() -> Callable[[Case], bool]:
    """P7: drop investigation_outcome only in self-referential containers."""
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
    return fn


def _vector_score_gate(min_v: float, fallback_subj: int) -> Callable[[Case], bool]:
    """P5: gate on vector_score>=min_v if present; else fall through to
    subject_overlap>=fallback_subj."""
    def fn(c: Case) -> bool:
        if not rule_baseline(c):
            return False
        v = (c.target_candidate or {}).get("vector_score")
        if v is not None:
            return float(v) >= min_v
        return rule_R2_subject_overlap(c, fallback_subj)
    return fn


RULES: dict[str, tuple[Callable[[Case], bool], str]] = {
    "baseline": (rule_baseline, "baseline"),
    "rs300":    (_rs_floor(300), "routing_score>=300"),
    "rs400":    (_rs_floor(400), "routing_score>=400"),
    "rs450":    (_rs_floor(450), "routing_score>=450"),
    "rs400+subj2": (_rs_floor_and_subj(400, 2), "routing_score>=400 AND subject_overlap>=2"),
    "rs350+subj2": (_rs_floor_and_subj(350, 2), "routing_score>=350 AND subject_overlap>=2"),
    "subj2":    (lambda c: rule_R2_subject_overlap(c, 2), "subject_overlap>=2"),
    "drop_io":  (_drop_type("investigation_outcome"), "drop investigation_outcome"),
    "drop_io_selfref": (_drop_io_self_referential(), "drop investigation_outcome in self-referential pallium queries"),
    "vec850+subj2": (_vector_score_gate(850.0, 2), "vector>=850 if present else subj>=2"),
}


# ---------------------------------------------------------------------------
# Check 1: replay rated-slice
# ---------------------------------------------------------------------------


def _eval_rule_on_slice(cases: list[Case], rule_fn) -> dict:
    """Reproduce the metric block from replay_harness.evaluate without printing."""
    kr = kn = dr = dn = 0
    n_baseline = 0
    for c in cases:
        b = rule_baseline(c)
        if b:
            n_baseline += 1
        if rule_fn(c):
            if c.rating == "relevant": kr += 1
            else: kn += 1
        else:
            if b:
                if c.rating == "relevant": dr += 1
                else: dn += 1
    kept = kr + kn
    p = (kr / kept) if kept else 0.0
    base_rel = kr + dr
    r = (kr / base_rel) if base_rel else 0.0
    base_nr = kn + dn
    nk = (dn / base_nr) if base_nr else 0.0
    return {
        "kept_rel": kr, "kept_nr": kn, "dropped_rel": dr, "dropped_nr": dn,
        "precision": p, "recall_vs_base": r, "noise_kill": nk,
        "n_baseline_injected": n_baseline,
    }


def check_replay(cases: list[Case], rule_fn) -> dict:
    base = _eval_rule_on_slice(cases, rule_baseline)
    rule = _eval_rule_on_slice(cases, rule_fn)
    p_delta = rule["precision"] - base["precision"]
    r_delta = rule["recall_vs_base"] - base["recall_vs_base"]
    p_pass = p_delta >= 0.02
    r_pass = r_delta >= -0.05
    passed = p_pass and r_pass
    return {
        "name": "replay_rated_slice",
        "passed": passed,
        "baseline": base,
        "rule": rule,
        "p_delta": p_delta,
        "r_delta": r_delta,
        "p_pass": p_pass,
        "r_pass": r_pass,
    }


# ---------------------------------------------------------------------------
# Check 2 / 3: subprocess runners
# ---------------------------------------------------------------------------


def _run_subproc(cmd: list[str], extra_env: dict | None = None, cwd: Path | None = None,
                 timeout: int = 1800) -> tuple[int, str, str]:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    started = time.time()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, env=env, cwd=str(cwd or _PROJECT_ROOT),
            timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        return 124, exc.stdout or "", f"TIMEOUT after {time.time()-started:.0f}s"


def check_invariants(*, with_flag: dict | None) -> dict:
    if not with_flag:
        return {"name": "invariant_runner", "passed": None, "skipped_reason": "no flag supplied; rule lives only in replay"}
    py = sys.executable
    code, out, err = _run_subproc(
        [py, "-m", "evals.generated_exploratory.invariant_runner"],
        extra_env=with_flag, timeout=2700,
    )
    last_line = (out.strip().splitlines() or [""])[-1]
    summary_path = Path(last_line) / "summary.json"
    summary = None
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception:
            summary = None
    if summary:
        passed = summary.get("scenarios_violated", 1) == 0 and summary.get("new_failures", 1) <= 0
    else:
        passed = (code == 0)
    return {
        "name": "invariant_runner",
        "passed": passed,
        "exit_code": code,
        "summary": summary,
        "stderr_tail": (err or "")[-2000:],
    }


def check_fact_consolidation(*, with_flag: dict | None) -> dict:
    if not with_flag:
        return {"name": "fact_consolidation", "passed": None, "skipped_reason": "no flag supplied; rule lives only in replay"}
    py = sys.executable
    code, out, err = _run_subproc(
        [py, "-m", "evals.fact_consolidation_eval"],
        extra_env=with_flag, timeout=900,
    )
    return {
        "name": "fact_consolidation",
        "passed": (code == 0),
        "exit_code": code,
        "stdout_tail": (out or "")[-2000:],
        "stderr_tail": (err or "")[-1000:],
    }


# ---------------------------------------------------------------------------
# Check 4: qualitative judge
# ---------------------------------------------------------------------------


def check_judge(cases: list[Case], rule_fn, *, rule_pretty: str, limit: int) -> dict:
    summary = audit_rule(cases, rule_fn, rule_name=rule_pretty, limit=limit)
    better = summary.rule_better_rate
    worse = summary.rule_worse_rate
    passed = (summary.n_judged > 0) and (better >= 0.60) and (worse <= 0.20)
    return {
        "name": "qualitative_judge",
        "passed": passed,
        "n_differ": summary.n_differ,
        "n_judged": summary.n_judged,
        "rule_better_rate": better,
        "rule_worse_rate": worse,
        "rule_neutral_rate": summary.rule_neutral_rate,
        "counts": summary.counts,
        "table_md": summary.table_md,
        "summary_obj": summary,
    }


# ---------------------------------------------------------------------------
# Skip-pressure metric (underinjection axis, no LLM)
# ---------------------------------------------------------------------------


def measure_skip_pressure(db: str, since: str, min_rs: int = 400) -> dict:
    """Pure-SQL look at the underinjection axis the rated slice cannot see.

    Counts `same_thread_context_sufficient` skips that had a strong
    candidate (routing_score >= min_rs) in the pool, vs. injected audits
    in the same window. The rated slice only contains injected cases, so
    it cannot show changes in this axis.
    """
    import sqlite3 as _sql
    con = _sql.connect(db)
    con.row_factory = _sql.Row
    rows = con.execute(
        "SELECT decision_reason, candidate_scores_json FROM query_audit_log "
        "WHERE created_at >= ? AND candidate_scores_json IS NOT NULL",
        (since,),
    ).fetchall()
    n_total = len(rows)
    n_skip_same_thread = 0
    n_skip_with_strong = 0
    n_decision_counts: dict = {}
    for r in rows:
        dr = r["decision_reason"] or "(unset)"
        n_decision_counts[dr] = n_decision_counts.get(dr, 0) + 1
        if dr == "same_thread_context_sufficient":
            n_skip_same_thread += 1
            try:
                cs = json.loads(r["candidate_scores_json"]) or []
                top_rs = max((c.get("routing_score") or 0) for c in cs) if cs else 0
                if top_rs >= min_rs:
                    n_skip_with_strong += 1
            except Exception:
                pass
    return {
        "since": since,
        "min_rs": min_rs,
        "audit_rows": n_total,
        "decision_counts": n_decision_counts,
        "same_thread_skips": n_skip_same_thread,
        "same_thread_skips_with_strong_candidate": n_skip_with_strong,
        "skip_pressure_pct": (
            n_skip_with_strong / n_total * 100.0 if n_total else 0.0
        ),
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _fmt_pass(p) -> str:
    if p is None:
        return "SKIPPED"
    return "PASS" if p else "FAIL"


def render_report(*, rule_key: str, rule_pretty: str, since: str,
                  c1: dict, c2: dict, c3: dict, c4: dict,
                  skip_pressure: dict | None = None) -> str:
    failures = []
    for c in (c1, c2, c3, c4):
        if c.get("passed") is False:
            failures.append(c["name"])
    verdict = "FAIL" if failures else ("PASS" if all(c.get("passed") in (True, None) for c in (c1, c2, c3, c4)) else "FAIL")
    if all(c.get("passed") is None for c in (c2, c3)) and c1.get("passed") and c4.get("passed"):
        verdict = "PASS-REPLAY-ONLY"

    base = c1["baseline"]; rule = c1["rule"]
    lines = [
        f"# Validation report: {rule_pretty}  ({datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')})",
        "",
        f"rule key: `{rule_key}`",
        f"rated slice: cases since {since}",
        "",
        "## 1. Replay rated-slice          " + _fmt_pass(c1["passed"]),
        f"   baseline P={base['precision']:.3f} R={base['recall_vs_base']:.2f} "
        f"(kept {base['kept_rel']}/{base['kept_nr']})",
        f"   variant  P={rule['precision']:.3f} R={rule['recall_vs_base']:.2f} "
        f"(kept {rule['kept_rel']}/{rule['kept_nr']}, dropped {rule['dropped_rel']}/{rule['dropped_nr']})",
        f"   delta    P {c1['p_delta']:+.3f} ({'OK' if c1['p_pass'] else 'FAIL P<+2pp'}), "
        f"R {c1['r_delta']:+.3f} ({'OK' if c1['r_pass'] else 'FAIL R drop > 5pp'})",
        "",
        "## 2. Invariant runner            " + _fmt_pass(c2["passed"]),
    ]
    if c2.get("passed") is None:
        lines.append(f"   {c2.get('skipped_reason','')}")
    elif c2.get("summary"):
        s = c2["summary"]
        lines.append(f"   total={s.get('scenarios_total')} passed={s.get('scenarios_passed')} "
                     f"violated={s.get('scenarios_violated')} new_failures={s.get('new_failures')}")
    else:
        lines.append(f"   exit_code={c2.get('exit_code')} (no summary.json)")
    lines += [
        "",
        "## 3. Fact-consolidation          " + _fmt_pass(c3["passed"]),
    ]
    if c3.get("passed") is None:
        lines.append(f"   {c3.get('skipped_reason','')}")
    else:
        lines.append(f"   exit_code={c3.get('exit_code')}")
    lines += [
        "",
        "## 4. Qualitative judge           " + _fmt_pass(c4["passed"]),
        f"   {c4['n_differ']} differing cases, {c4['n_judged']} judged",
        f"   better: {c4['counts']['better']}, worse: {c4['counts']['worse']}, neutral: {c4['counts']['neutral']}",
        f"   rates: better {c4['rule_better_rate']*100:.0f}%, "
        f"worse {c4['rule_worse_rate']*100:.0f}%, "
        f"neutral {c4['rule_neutral_rate']*100:.0f}%",
        "",
    ]
    if skip_pressure:
        lines += [
            "## Skip-pressure (underinjection axis, diagnostic only)",
            f"   audit rows since {since}: {skip_pressure['audit_rows']}",
            f"   same-thread skips: {skip_pressure['same_thread_skips']}",
            f"   skips with strong rs>={skip_pressure['min_rs']} candidate: "
            f"{skip_pressure['same_thread_skips_with_strong_candidate']} "
            f"({skip_pressure['skip_pressure_pct']:.1f}% of audits)",
            "   note: rated slice (above) is INJECTED CASES ONLY. This block",
            "   shows the unrated underinjection axis the rule does not see.",
            "",
        ]
    lines += [
        f"## VERDICT: {verdict}" + (f" ({', '.join(failures)})" if failures else ""),
        "",
        "## Judge per-case verdicts",
        "",
        c4["table_md"],
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_flag(s: str) -> dict:
    if not s:
        return {}
    if "=" not in s:
        raise SystemExit(f"--with-flag expects NAME=VAL, got {s!r}")
    k, v = s.split("=", 1)
    return {k: v}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rule", required=True, choices=sorted(RULES.keys()))
    ap.add_argument("--db", default=str(Path.home() / ".pallium" / "data" / "pallium.db"))
    ap.add_argument("--since", default="2026-05-18")
    ap.add_argument("--judge-limit", type=int, default=20)
    ap.add_argument("--with-flag", default=None,
                    help="env var to set when running invariant + fact-consolidation, e.g. PALLIUM_R2B_SUBJECT_OVERLAP_GATE=1")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    rule_fn, pretty = RULES[args.rule]
    flag_env = parse_flag(args.with_flag) if args.with_flag else None

    print(f"# Validating rule: {pretty}")
    print("Loading rated cases...")
    cases = load_cases(args.db, args.since)
    print(f"  {len(cases)} cases loaded")

    print("[1/4] Replay rated-slice...")
    c1 = check_replay(cases, rule_fn)

    print("[2/4] Invariant runner..." if flag_env else "[2/4] Invariant runner: SKIPPED (no flag)")
    c2 = check_invariants(with_flag=flag_env)

    print("[3/4] Fact-consolidation eval..." if flag_env else "[3/4] Fact-consolidation: SKIPPED (no flag)")
    c3 = check_fact_consolidation(with_flag=flag_env)

    print("[4/4] Qualitative judge...")
    c4 = check_judge(cases, rule_fn, rule_pretty=pretty, limit=args.judge_limit)

    print("[skip-pressure] Underinjection axis (no LLM)...")
    sp = measure_skip_pressure(args.db, args.since)
    print(
        f"   skip_pressure: {sp['same_thread_skips_with_strong_candidate']} of "
        f"{sp['audit_rows']} audits ({sp['skip_pressure_pct']:.0f}%) skipped "
        f"with rs>={sp['min_rs']} candidate present"
    )

    report = render_report(
        rule_key=args.rule, rule_pretty=pretty, since=args.since,
        c1=c1, c2=c2, c3=c3, c4=c4, skip_pressure=sp,
    )
    print()
    print(report)

    out_path = args.out
    if out_path is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ")
        out_path = _PROJECT_ROOT / ".local" / "research" / f"validation_{args.rule}_{ts}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
