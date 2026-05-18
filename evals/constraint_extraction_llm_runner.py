"""LLM-driven constraint extraction quality runner.

Replays each entry in ``constraint_quality_corpus.jsonl`` through the production
extraction prompt (default: ``strict_typed_memory_v8b_work_refs_separate``) via
the local Anthropic-compatible proxy and inspects the ``constraint_text`` field
of the LLM response.

Closes the validation loop on Fix 2 (cross-language anaphor REJECT rule). The
deterministic ``constraint_quality_eval`` cannot validate Fix 2 because Fix 2 is
prompt-only — the gate-side rules I prototyped in pass 1 had 67%/100% FP rates
on real data and were dropped.

Usage:
    python -m evals.constraint_extraction_llm_runner
    python -m evals.constraint_extraction_llm_runner --limit 5 --delay 0.0
    python -m evals.constraint_extraction_llm_runner --variant strict_typed_memory_v8b_work_refs_separate
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.stdout.reconfigure(encoding="utf-8")

CORPUS_FILE = Path(__file__).parent / "constraint_quality_corpus.jsonl"
RESULTS_FILE = Path(__file__).parent / "constraint_extraction_llm_results.json"

# Bare-anaphor items Fix 2 specifically targets — utterances that end with or
# consist solely of a pronoun/anaphor with no named referent in the constraint
# text itself. Fix 2 added a cross-language anchor rule, so the Hebrew case is
# load-bearing for the multilingual claim.
#
# NOTE: "a is the variable to use" is NOT a Fix 2 target. It is a single-letter
# subject case with a clear referent ("the variable"); pass 2 deliberately
# DROPPED that rule after live data showed a 100% false-positive rate on
# active constraints (11/12 such cases are legitimate "i don't want X"
# preferences). Tracking it elsewhere as out-of-scope.
ANAPHORIC_TARGETS = {
    "never do that",
    "don't touch that",
    "אל תיגע בזה",  # Hebrew: "don't touch that"
}


@dataclass
class EvalResult:
    constraint_text_input: str
    category: str
    cluster_id: str | None
    expected_reject: bool
    predicted_constraint_text: str | None
    predicted_rejected: bool
    correct: bool
    is_anaphoric_target: bool
    notes: str
    raw_response: dict[str, Any] | None = None


@dataclass
class EvalSummary:
    total: int
    correct: int
    # Reject metrics: positive class = "should be rejected"
    reject_tp: int  # vague item correctly rejected
    reject_fn: int  # vague item NOT rejected (Fix 2 miss)
    keep_tp: int    # good item correctly kept
    keep_fn: int    # good item incorrectly rejected (regression)
    reject_recall: float
    keep_recall: float
    by_category: dict[str, dict[str, int]] = field(default_factory=dict)
    anaphoric: dict[str, int] = field(default_factory=dict)


def load_corpus(path: Path = CORPUS_FILE) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                items.append(json.loads(line))
    return items


def build_extraction_message(
    constraint_text_input: str,
    prompt_text: str,
    schema_description: str,
    item_idx: int,
) -> list[dict[str, str]]:
    """Build a source-item-style user prompt around the corpus utterance.

    The corpus stores the bare utterance the user said; we wrap it in the same
    framing the production pipeline uses (artifact_kind=user_message, role=user)
    so the prompt's REJECT rules apply against realistic input.
    """
    user_prompt = (
        f"Source type: agent_artifact\n"
        f"Source id: constraint-eval-{item_idx:04d}\n"
        f"Content type: text/plain\n"
        f"Artifact kind: user_message\n"
        f"Role: user\n"
        f"Metadata: {{}}\n"
        f"Content:\n{constraint_text_input}"
        f"\n\nReturn exactly one JSON object matching this schema:\n{schema_description}"
    )
    return [
        {"role": "system", "content": prompt_text},
        {"role": "user", "content": user_prompt},
    ]


def _call_proxy(messages: list[dict[str, str]]) -> dict[str, Any]:
    import os
    import httpx
    from dotenv import load_dotenv
    load_dotenv(".env.local")

    base_url = os.environ.get("PALLIUM_PROXY_URL", "http://localhost:6655/anthropic/v1")
    api_key = os.environ.get("PALLIUM_API_KEY", "dummy")
    model = os.environ.get("PALLIUM_LLM_MODEL", "anthropic--claude-sonnet-latest")

    system_msg = next((m["content"] for m in messages if m["role"] == "system"), "")
    user_msgs = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"]

    resp = httpx.post(
        f"{base_url}/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 1024,
            "system": system_msg,
            "messages": user_msgs,
        },
        timeout=60,
    )
    resp.raise_for_status()
    result = resp.json()
    text = result["content"][0]["text"].strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(text)


def get_prompt_variant(variant: str) -> tuple[str, str]:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from semantic.llm_agent_memory import PROMPT_VARIANTS, SCHEMA_DESCRIPTION
    if variant not in PROMPT_VARIANTS:
        raise ValueError(f"Unknown variant: {variant}. Available: {list(PROMPT_VARIANTS.keys())}")
    return PROMPT_VARIANTS[variant], SCHEMA_DESCRIPTION


def evaluate_item(
    item: dict[str, Any],
    item_idx: int,
    prompt_text: str,
    schema_description: str,
) -> EvalResult:
    constraint_input = item["constraint_text"]
    expected_reject = bool(item["expected_reject"])
    is_target = constraint_input.strip() in ANAPHORIC_TARGETS

    try:
        response = _call_proxy(
            build_extraction_message(constraint_input, prompt_text, schema_description, item_idx)
        )
    except Exception as e:
        return EvalResult(
            constraint_text_input=constraint_input,
            category=item["category"],
            cluster_id=item.get("cluster_id"),
            expected_reject=expected_reject,
            predicted_constraint_text=None,
            predicted_rejected=False,
            correct=False,
            is_anaphoric_target=is_target,
            notes=item.get("notes", ""),
            raw_response={"error": str(e)},
        )

    predicted = response.get("constraint_text")
    if predicted is None:
        predicted_rejected = True
    elif isinstance(predicted, str):
        predicted_rejected = not predicted.strip()
    else:
        # Unexpected non-string non-null value — treat as kept so the surprise
        # surfaces in the report instead of silently passing as rejected.
        predicted_rejected = False
    correct = predicted_rejected == expected_reject

    return EvalResult(
        constraint_text_input=constraint_input,
        category=item["category"],
        cluster_id=item.get("cluster_id"),
        expected_reject=expected_reject,
        predicted_constraint_text=predicted if isinstance(predicted, str) else repr(predicted),
        predicted_rejected=predicted_rejected,
        correct=correct,
        is_anaphoric_target=is_target,
        notes=item.get("notes", ""),
        raw_response=response,
    )


def compute_summary(results: list[EvalResult]) -> EvalSummary:
    total = len(results)
    correct = sum(1 for r in results if r.correct)

    reject_tp = sum(1 for r in results if r.expected_reject and r.predicted_rejected)
    reject_fn = sum(1 for r in results if r.expected_reject and not r.predicted_rejected)
    keep_tp = sum(1 for r in results if not r.expected_reject and not r.predicted_rejected)
    keep_fn = sum(1 for r in results if not r.expected_reject and r.predicted_rejected)

    reject_total = reject_tp + reject_fn
    keep_total = keep_tp + keep_fn
    reject_recall = (reject_tp / reject_total) if reject_total else 0.0
    keep_recall = (keep_tp / keep_total) if keep_total else 0.0

    by_category: dict[str, dict[str, int]] = {}
    for r in results:
        bucket = by_category.setdefault(
            r.category,
            {"total": 0, "correct": 0},
        )
        bucket["total"] += 1
        if r.correct:
            bucket["correct"] += 1

    anaphoric_results = [r for r in results if r.is_anaphoric_target]
    anaphoric = {
        "total": len(anaphoric_results),
        "rejected": sum(1 for r in anaphoric_results if r.predicted_rejected),
    }

    return EvalSummary(
        total=total,
        correct=correct,
        reject_tp=reject_tp,
        reject_fn=reject_fn,
        keep_tp=keep_tp,
        keep_fn=keep_fn,
        reject_recall=reject_recall,
        keep_recall=keep_recall,
        by_category=by_category,
        anaphoric=anaphoric,
    )


def print_report(summary: EvalSummary, results: list[EvalResult], variant: str) -> None:
    print()
    print("=" * 72)
    print(f"CONSTRAINT EXTRACTION LLM EVAL  variant={variant}")
    print("=" * 72)

    print(f"\n  Total items:                 {summary.total}")
    print(f"  Overall correct:             {summary.correct}/{summary.total} "
          f"({summary.correct / summary.total:.1%})" if summary.total else "")

    reject_total = summary.reject_tp + summary.reject_fn
    keep_total = summary.keep_tp + summary.keep_fn
    print(f"\n  Vague-reject recall:         {summary.reject_tp}/{reject_total} "
          f"({summary.reject_recall:.1%})  -- higher = better; misses are Fix 2 failures")
    print(f"  Good-keep recall:            {summary.keep_tp}/{keep_total} "
          f"({summary.keep_recall:.1%})  -- higher = better; misses are regressions")

    print(f"\n  Anaphoric targets rejected:  "
          f"{summary.anaphoric['rejected']}/{summary.anaphoric['total']}  "
          "(Done criteria: all rejected)")

    print(f"\n  Per-category breakdown:")
    for cat in sorted(summary.by_category):
        s = summary.by_category[cat]
        pct = (s["correct"] / s["total"]) if s["total"] else 0.0
        print(f"    {cat:<26s} {s['correct']:>2d}/{s['total']:<2d} ({pct:.0%})")

    misses = [r for r in results if not r.correct]
    if misses:
        print()
        print("-" * 72)
        print(f"INCORRECT PREDICTIONS ({len(misses)})")
        print("-" * 72)
        for r in misses:
            kind = "FAIL-REJECT" if r.expected_reject else "FAIL-KEEP"
            target_tag = " [ANAPHORIC TARGET]" if r.is_anaphoric_target else ""
            print(f"  [{kind}] {r.category}{target_tag}")
            print(f"    input:     {r.constraint_text_input!r}")
            if r.expected_reject:
                print(f"    predicted: {r.predicted_constraint_text!r}  (expected null)")
            else:
                print(f"    predicted: null  (expected non-null)")
            if r.notes:
                print(f"    notes:     {r.notes}")
            print()

    print("=" * 72)


def main() -> int:
    parser = argparse.ArgumentParser(description="LLM-driven constraint extraction eval")
    parser.add_argument(
        "--variant",
        default="strict_typed_memory_v8b_work_refs_separate",
        help="Prompt variant under test (default = production)",
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=CORPUS_FILE,
        help="Path to constraint corpus JSONL",
    )
    parser.add_argument("--limit", type=int, default=None, help="Limit items (debugging)")
    parser.add_argument("--delay", type=float, default=0.3, help="Delay between LLM calls")
    args = parser.parse_args()

    if not args.corpus.exists():
        print(f"ERROR: corpus not found at {args.corpus}", file=sys.stderr)
        return 1

    prompt_text, schema_description = get_prompt_variant(args.variant)
    corpus = load_corpus(args.corpus)
    if args.limit:
        corpus = corpus[: args.limit]

    print(f"Running constraint extraction eval: {len(corpus)} items, "
          f"variant={args.variant}, provider=proxy")
    print()

    # Dispatch-coverage guard: warn whenever the slice is missing anaphoric
    # targets or good_unique baselines — applies under --limit too, since a
    # debugging slice that excludes both classes makes the eval meaningless.
    sliced_anaphoric = sum(
        1 for it in corpus if it["constraint_text"].strip() in ANAPHORIC_TARGETS
    )
    sliced_good = sum(1 for it in corpus if it["category"] == "good_unique")
    if sliced_anaphoric != len(ANAPHORIC_TARGETS):
        print(f"WARNING: slice contains {sliced_anaphoric}/{len(ANAPHORIC_TARGETS)} "
              "anaphoric Fix 2 targets — Done criteria check will be partial.")
    if sliced_good == 0:
        print("WARNING: no good_unique items in slice — regression check disabled.")

    results: list[EvalResult] = []
    for i, item in enumerate(corpus):
        result = evaluate_item(item, i, prompt_text, schema_description)
        results.append(result)
        verdict = "OK" if result.correct else "WRONG"
        marker = " [TARGET]" if result.is_anaphoric_target else ""
        print(f"  [{i+1:>2}/{len(corpus)}] {verdict}  {result.category}{marker}  "
              f"input={result.constraint_text_input[:60]!r}")
        if not result.correct:
            if result.expected_reject:
                print(f"            -> predicted: {result.predicted_constraint_text!r} (expected null)")
            else:
                print(f"            -> predicted: null (expected non-null)")
        if args.delay and i < len(corpus) - 1:
            time.sleep(args.delay)

    summary = compute_summary(results)
    print_report(summary, results, args.variant)

    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {
                "variant": args.variant,
                "summary": {
                    "total": summary.total,
                    "correct": summary.correct,
                    "reject_tp": summary.reject_tp,
                    "reject_fn": summary.reject_fn,
                    "keep_tp": summary.keep_tp,
                    "keep_fn": summary.keep_fn,
                    "reject_recall": summary.reject_recall,
                    "keep_recall": summary.keep_recall,
                    "anaphoric": summary.anaphoric,
                    "by_category": summary.by_category,
                },
                "results": [
                    {
                        "input": r.constraint_text_input,
                        "category": r.category,
                        "cluster_id": r.cluster_id,
                        "expected_reject": r.expected_reject,
                        "predicted_rejected": r.predicted_rejected,
                        "predicted_constraint_text": r.predicted_constraint_text,
                        "correct": r.correct,
                        "is_anaphoric_target": r.is_anaphoric_target,
                        "notes": r.notes,
                    }
                    for r in results
                ],
            },
            f,
            indent=2,
            ensure_ascii=False,
        )
    print(f"\nResults written to {RESULTS_FILE}")

    # Done criteria (matches investigation file):
    #  1. All anaphoric Fix 2 targets are rejected.
    #  2. Zero regressions on `good_unique` baselines (the production-safety set).
    # Cluster-paraphrase keep misses are NOT a regression signal — the clusters
    # contain intentionally terse and anaphoric variants the LLM is allowed to
    # judge case-by-case. Track them in the report; do not gate the exit code.
    good_unique = summary.by_category.get("good_unique", {"total": 0, "correct": 0})
    good_unique_clean = good_unique["total"] == 0 or good_unique["correct"] == good_unique["total"]
    targets_clean = (
        summary.anaphoric["total"] == 0
        or summary.anaphoric["rejected"] == summary.anaphoric["total"]
    )
    return 0 if (targets_clean and good_unique_clean) else 1


if __name__ == "__main__":
    sys.exit(main())
