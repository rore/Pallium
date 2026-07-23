"""Re-admission counterfactual: which suppressed candidates should we bring back?

Ground truth: the underinjection judge labeled each suppressed top-candidate
(same_thread_context_sufficient skips, user turns only) as:
  yes_helpful  -> re-admitting it is a WIN  (recovered signal)
  no_helpful   -> re-admitting it is a LOSS (re-admitted noise)
  neutral      -> excluded from precision (ambiguous)

A "re-admission rule" decides, per suppressed candidate, whether to bring it
back. Evaluated against the judge labels:

  admit_yes  = rule admits a yes_helpful   (true positive)
  admit_no   = rule admits a no_helpful    (false positive)
  miss_yes   = rule leaves a yes_helpful suppressed (missed recovery)

  recovery_precision = admit_yes / (admit_yes + admit_no)
  recovery_recall    = admit_yes / total_yes

Baseline = current system (admits nothing; all suppressed). So recovery=0.
The question: is there a rule that recovers most yes_helpful while keeping
recovery_precision high (few no_helpful re-admitted)?

Usage:
  python -m evals.anchor_probe.readmission_counterfactual --labels c:/tmp/uj_labeled.jsonl
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

def load(path):
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows

# --- Rules: given a labeled suppressed-candidate row, admit it back? ---
def rule_rs(thresh):
    return lambda r: (r.get("rs") or 0) >= thresh

def rule_rs_rank1(thresh):
    return lambda r: (r.get("rs") or 0) >= thresh and r.get("rank") == 1

def rule_rs_supported(thresh):
    return lambda r: (r.get("rs") or 0) >= thresh and r.get("support_grade") == "supported"

def rule_rs_rank1_supported(thresh):
    return lambda r: ((r.get("rs") or 0) >= thresh and r.get("rank") == 1
                      and r.get("support_grade") == "supported")

def rule_lexical_grounded(thresh, lex_min):
    # require both high routing score AND a real lexical match (query vocabulary overlap)
    return lambda r: ((r.get("rs") or 0) >= thresh
                      and (r.get("lexical_score") or 0) >= lex_min)

def evaluate(rows, rule, name):
    total_yes = sum(1 for r in rows if r["verdict"] == "yes_helpful")
    total_no  = sum(1 for r in rows if r["verdict"] == "no_helpful")
    admit_yes = admit_no = admit_neutral = 0
    for r in rows:
        if rule(r):
            if r["verdict"] == "yes_helpful": admit_yes += 1
            elif r["verdict"] == "no_helpful": admit_no += 1
            else: admit_neutral += 1
    admitted_judged = admit_yes + admit_no
    prec = admit_yes / admitted_judged if admitted_judged else float("nan")
    rec = admit_yes / total_yes if total_yes else float("nan")
    print(f"  {name:<34} admit(yes/no/neu)={admit_yes:>2}/{admit_no:>2}/{admit_neutral:>2}  "
          f"recovery_P={prec:.2f} recovery_R={rec:.2f}")
    return {"name": name, "admit_yes": admit_yes, "admit_no": admit_no,
            "prec": prec, "rec": rec}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default="c:/tmp/uj_labeled.jsonl")
    args = ap.parse_args()
    rows = load(args.labels)
    ny = sum(1 for r in rows if r["verdict"]=="yes_helpful")
    nn = sum(1 for r in rows if r["verdict"]=="no_helpful")
    nu = sum(1 for r in rows if r["verdict"]=="neutral")
    print(f"# Re-admission counterfactual — {len(rows)} labeled suppressed candidates")
    print(f"  yes_helpful={ny}  no_helpful={nn}  neutral={nu}")
    print(f"  base rate (yes / judged) = {ny/(ny+nn):.2f}  <- a rule beats noise only if recovery_P > this")
    print()
    print("## Rules (recovery_P = of admitted-and-judged, fraction actually helpful)")
    rules = [
        ("admit rs>=300", rule_rs(300)),
        ("admit rs>=400", rule_rs(400)),
        ("admit rs>=500", rule_rs(500)),
        ("admit rs>=600", rule_rs(600)),
        ("admit rs>=650", rule_rs(650)),
        ("admit rs>=400 & rank1", rule_rs_rank1(400)),
        ("admit rs>=400 & supported", rule_rs_supported(400)),
        ("admit rs>=400 & rank1 & supported", rule_rs_rank1_supported(400)),
        ("admit rs>=600 & rank1", rule_rs_rank1(600)),
        ("admit rs>=400 & lexical>=5", rule_lexical_grounded(400, 5)),
        ("admit rs>=400 & lexical>=10", rule_lexical_grounded(400, 10)),
    ]
    results = [evaluate(rows, fn, name) for name, fn in rules]
    print()
    # buckets by rs to show the calibration curve directly
    print("## Helpful-rate by routing_score bucket (the calibration curve)")
    buckets = [(300,400),(400,500),(500,600),(600,700),(700,9999)]
    for lo,hi in buckets:
        sub=[r for r in rows if lo <= (r.get("rs") or 0) < hi]
        y=sum(1 for r in sub if r["verdict"]=="yes_helpful")
        n=sum(1 for r in sub if r["verdict"]=="no_helpful")
        u=sum(1 for r in sub if r["verdict"]=="neutral")
        judged=y+n
        rate=f"{y/judged:.2f}" if judged else "n/a"
        print(f"  rs [{lo},{hi}): n={len(sub):>2}  yes/no/neu={y}/{n}/{u}  helpful_rate={rate}")
    print()
    # by memory_type
    print("## Helpful-rate by memory_type")
    from collections import Counter
    types = Counter(r.get("memory_type") for r in rows)
    for t,_ in types.most_common():
        sub=[r for r in rows if r.get("memory_type")==t]
        y=sum(1 for r in sub if r["verdict"]=="yes_helpful")
        n=sum(1 for r in sub if r["verdict"]=="no_helpful")
        judged=y+n
        rate=f"{y/judged:.2f}" if judged else "n/a"
        print(f"  {str(t):22} n={len(sub):>2}  yes/no={y}/{n}  helpful_rate={rate}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
