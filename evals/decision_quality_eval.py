"""Decision extraction quality eval.

Measures the deterministic quality gate against the labeled corpus.
Reports: true rejections (bad correctly rejected), false rejections (good incorrectly rejected),
and gate misses (bad that pass).

Usage:
    python -m evals.decision_quality_eval
    python -m evals.decision_quality_eval --verbose
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


CORPUS_PATH = Path(__file__).parent / "decision_quality_corpus.jsonl"


def load_corpus() -> list[dict]:
    return [json.loads(line) for line in open(CORPUS_PATH, encoding="utf-8") if line.strip()]


def build_thread_text(item: dict) -> str:
    """Build synthetic thread_text containing both decision_text and evidence.

    The validator checks that both are literal substrings of thread_text (after
    normalization). We embed them in a realistic thread structure so grounding
    passes, letting us test the substance filters in isolation.
    """
    evidence = item["evidence"]
    decision_text = item["decision_text"]
    return f"user/msg: {evidence}\nassistant/msg: {decision_text}\nassistant/msg: Implementation complete."


def run_eval(corpus: list[dict], verbose: bool = False) -> dict:
    """Run the decision quality gate against the corpus."""
    from semantic.agent_conversation_memory_threads import _validate_thread_decisions

    good_items = [item for item in corpus if item["expected_viable"]]
    bad_items = [item for item in corpus if not item["expected_viable"]]

    results = {
        "total": len(corpus),
        "good_total": len(good_items),
        "bad_total": len(bad_items),
        "true_rejections": [],     # bad items correctly rejected
        "false_rejections": [],    # good items incorrectly rejected
        "gate_misses": [],         # bad items that pass
        "correct_keeps": [],       # good items correctly kept
    }

    for item in corpus:
        thread_text = build_thread_text(item)
        raw_decisions = [{"decision_text": item["decision_text"], "evidence": item["evidence"]}]
        validated = _validate_thread_decisions(raw_decisions, thread_text)
        kept = len(validated) > 0

        if item["expected_viable"]:
            if kept:
                results["correct_keeps"].append(item)
            else:
                results["false_rejections"].append(item)
        else:
            if kept:
                results["gate_misses"].append(item)
            else:
                results["true_rejections"].append(item)

    return results


def main():
    parser = argparse.ArgumentParser(description="Decision extraction quality eval")
    parser.add_argument("--verbose", action="store_true", help="Show per-item details")
    args = parser.parse_args()

    if not CORPUS_PATH.exists():
        print(f"ERROR: Corpus not found at {CORPUS_PATH}")
        sys.exit(1)

    corpus = load_corpus()
    good_count = sum(1 for c in corpus if c["expected_viable"])
    bad_count = sum(1 for c in corpus if not c["expected_viable"])

    print(f"Corpus: {len(corpus)} items ({good_count} good, {bad_count} bad)")
    print()

    # -----------------------------------------------------------------------
    # Run gate eval
    # -----------------------------------------------------------------------
    print("=" * 60)
    print("DECISION QUALITY GATE")
    print("=" * 60)

    results = run_eval(corpus, verbose=args.verbose)

    true_rejections = len(results["true_rejections"])
    false_rejections = len(results["false_rejections"])
    gate_misses = len(results["gate_misses"])
    correct_keeps = len(results["correct_keeps"])

    # Gate precision: of items kept, what fraction are truly good?
    total_kept = correct_keeps + gate_misses
    gate_precision = (correct_keeps / total_kept * 100) if total_kept else 100.0

    # Gate recall: of bad items, what fraction are correctly rejected?
    gate_recall = (true_rejections / results["bad_total"] * 100) if results["bad_total"] else 100.0

    print(f"  Gate precision (kept items truly good): {gate_precision:.1f}%")
    print(f"  Gate recall (bad items rejected):       {gate_recall:.1f}%")
    print()
    print(f"  True rejections (bad correctly rejected): {true_rejections}/{results['bad_total']}")
    print(f"  False rejections (good incorrectly rejected): {false_rejections}/{results['good_total']}")
    print(f"  Gate misses (bad items that pass): {gate_misses}/{results['bad_total']}")
    print(f"  Correct keeps (good items kept): {correct_keeps}/{results['good_total']}")

    # -----------------------------------------------------------------------
    # Details
    # -----------------------------------------------------------------------
    if false_rejections > 0:
        print()
        print(f"  FALSE REJECTIONS (must be 0):")
        for item in results["false_rejections"]:
            print(f"    - [{item['id']}] \"{item['decision_text'][:70]}\"")
            if args.verbose:
                print(f"      evidence: \"{item['evidence'][:80]}\"")
                print(f"      notes: {item['notes']}")

    if gate_misses > 0:
        print()
        print(f"  GATE MISSES (bad items that pass — need prompt-level fix):")
        for item in results["gate_misses"]:
            print(f"    - [{item['id']}] \"{item['decision_text'][:70]}\"")
            print(f"      pattern: {item['failure_pattern']}")
            if args.verbose:
                print(f"      evidence: \"{item['evidence'][:80]}\"")
                print(f"      notes: {item['notes']}")

    if args.verbose and results["true_rejections"]:
        print()
        print(f"  TRUE REJECTIONS (correctly caught):")
        for item in results["true_rejections"]:
            print(f"    - [{item['id']}] \"{item['decision_text'][:70]}\"")
            print(f"      pattern: {item['failure_pattern']}")

    if args.verbose and results["correct_keeps"]:
        print()
        print(f"  CORRECT KEEPS (good items kept):")
        for item in results["correct_keeps"]:
            print(f"    - [{item['id']}] \"{item['decision_text'][:70]}\"")

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)

    gate_pass = false_rejections == 0
    print(f"  Precision:        {gate_precision:.1f}% (target: 100%)")
    print(f"  Recall:           {gate_recall:.1f}%")
    print(f"  False rejections: {false_rejections} (MUST be 0) — {'PASS' if gate_pass else 'FAIL'}")
    print(f"  Gate misses:      {gate_misses} (lower is better)")
    print()
    print(f"  RESULT: {'PASS' if gate_pass else 'FAIL'}")

    if not gate_pass:
        sys.exit(1)


if __name__ == "__main__":
    main()
