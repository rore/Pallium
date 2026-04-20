"""
Abstraction loss failure analysis for LoCoMo benchmark results.
Analyzes incorrect answers where memory was injected but the answer was wrong,
focusing on fact_summary vs atomic_fact memory types and gold_in_context patterns.
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

RESULTS_FILE = Path(
    "evals/locomo/output/"
    "locomo-benchmark__anthropic-claude__anthropic--claude-sonnet-latest__20260417T174555Z/"
    "results.jsonl"
)


def load_records(path: Path) -> list[dict]:
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def has_memory_type_in_retrieval(record: dict, mem_type: str) -> bool:
    """Check if a memory type appears in retrieval_summary.memory_types."""
    rs = record.get("retrieval_summary", {})
    return mem_type in rs.get("memory_types", [])


def has_memory_type_in_evidence_trace(record: dict, mem_type: str) -> bool:
    """Check if a memory type appears anywhere in evidence_trace.traces[].memory_types."""
    et = record.get("evidence_trace", {})
    for trace in et.get("traces", []):
        if mem_type in trace.get("memory_types", []):
            return True
    return False


def get_all_memory_types_in_retrieval(record: dict) -> list[str]:
    rs = record.get("retrieval_summary", {})
    return rs.get("memory_types", [])


def get_all_memory_types_in_evidence(record: dict) -> list[str]:
    et = record.get("evidence_trace", {})
    all_types = []
    for trace in et.get("traces", []):
        all_types.extend(trace.get("memory_types", []))
    return all_types


def main():
    records = load_records(RESULTS_FILE)
    print(f"Total records: {len(records)}")

    correct = [r for r in records if r["correct"]]
    incorrect = [r for r in records if not r["correct"]]
    print(f"Correct: {len(correct)}, Incorrect: {len(incorrect)}")
    print(f"Accuracy: {len(correct)/len(records)*100:.1f}%")
    print()

    # ========================================================================
    # SECTION A: Incorrect records where should_inject=True
    # ========================================================================
    injected_incorrect = [r for r in incorrect if r.get("should_inject")]
    no_inject_incorrect = [r for r in incorrect if not r.get("should_inject")]
    print("=" * 80)
    print("SECTION A: Incorrect records where should_inject=True (memory injected but wrong)")
    print("=" * 80)
    print(f"Total injected-but-incorrect: {len(injected_incorrect)}")
    print(f"Total no-inject-and-incorrect: {len(no_inject_incorrect)}")
    print()

    # Count memory types in evidence_trace
    has_fact_summary_et = [r for r in injected_incorrect if has_memory_type_in_evidence_trace(r, "fact_summary")]
    has_atomic_fact_et = [r for r in injected_incorrect if has_memory_type_in_evidence_trace(r, "atomic_fact")]
    has_both_et = [r for r in injected_incorrect
                   if has_memory_type_in_evidence_trace(r, "fact_summary")
                   and has_memory_type_in_evidence_trace(r, "atomic_fact")]

    print("Memory types in evidence_trace (extraction-side):")
    print(f"  fact_summary present: {len(has_fact_summary_et)} / {len(injected_incorrect)}")
    print(f"  atomic_fact present:  {len(has_atomic_fact_et)} / {len(injected_incorrect)}")
    print(f"  BOTH present:         {len(has_both_et)} / {len(injected_incorrect)}")
    print()

    # Count memory types in retrieval_summary
    has_fact_summary_rs = [r for r in injected_incorrect if has_memory_type_in_retrieval(r, "fact_summary")]
    has_atomic_fact_rs = [r for r in injected_incorrect if has_memory_type_in_retrieval(r, "atomic_fact")]
    has_both_rs = [r for r in injected_incorrect
                   if has_memory_type_in_retrieval(r, "fact_summary")
                   and has_memory_type_in_retrieval(r, "atomic_fact")]

    print("Memory types in retrieval_summary (what was actually retrieved/injected):")
    print(f"  fact_summary present: {len(has_fact_summary_rs)} / {len(injected_incorrect)}")
    print(f"  atomic_fact present:  {len(has_atomic_fact_rs)} / {len(injected_incorrect)}")
    print(f"  BOTH present:         {len(has_both_rs)} / {len(injected_incorrect)}")
    print()

    # gold_in_context breakdown
    gold_in = [r for r in injected_incorrect if r.get("gold_in_context")]
    gold_not_in = [r for r in injected_incorrect if not r.get("gold_in_context")]
    print(f"gold_in_context=True  (gold was in injected blocks): {len(gold_in)}")
    print(f"gold_in_context=False (gold NOT in injected blocks): {len(gold_not_in)}")
    print()

    # ========================================================================
    # SECTION B: Incorrect + gold_in_context=False breakdown
    # ========================================================================
    print("=" * 80)
    print("SECTION B: Incorrect + should_inject=True + gold_in_context=False")
    print("  (Memory injected, but the gold answer was NOT in the context)")
    print("=" * 80)
    print(f"Count: {len(gold_not_in)}")
    print()

    # Memory types in retrieval_summary for these
    retrieval_type_counter = Counter()
    for r in gold_not_in:
        for mt in get_all_memory_types_in_retrieval(r):
            retrieval_type_counter[mt] += 1

    print("Retrieval memory types (frequency across gold_not_in_context records):")
    for mt, count in retrieval_type_counter.most_common():
        print(f"  {mt}: {count}")
    print()

    # How many have fact_summary vs atomic_fact in retrieval
    gni_fs = sum(1 for r in gold_not_in if has_memory_type_in_retrieval(r, "fact_summary"))
    gni_af = sum(1 for r in gold_not_in if has_memory_type_in_retrieval(r, "atomic_fact"))
    gni_both = sum(1 for r in gold_not_in
                   if has_memory_type_in_retrieval(r, "fact_summary")
                   and has_memory_type_in_retrieval(r, "atomic_fact"))
    gni_neither = sum(1 for r in gold_not_in
                      if not has_memory_type_in_retrieval(r, "fact_summary")
                      and not has_memory_type_in_retrieval(r, "atomic_fact"))
    print(f"  fact_summary only in retrieval: {gni_fs - gni_both}")
    print(f"  atomic_fact only in retrieval:  {gni_af - gni_both}")
    print(f"  BOTH in retrieval:              {gni_both}")
    print(f"  NEITHER in retrieval:           {gni_neither}")
    print()

    # Was the evidence extracted at all?
    extraction_found = sum(1 for r in gold_not_in
                           if r.get("evidence_trace", {}).get("extraction_found"))
    retrieval_found = sum(1 for r in gold_not_in
                          if r.get("evidence_trace", {}).get("retrieval_found"))
    print(f"  extraction_found=True: {extraction_found} / {len(gold_not_in)}")
    print(f"  retrieval_found=True:  {retrieval_found} / {len(gold_not_in)}")
    print()

    # Category breakdown for gold_not_in
    cat_counter = Counter(r.get("category_name", "unknown") for r in gold_not_in)
    print("Category breakdown (gold_not_in_context):")
    for cat, count in cat_counter.most_common():
        print(f"  {cat}: {count}")
    print()

    # ========================================================================
    # SECTION C: Incorrect + gold_in_context=True breakdown
    # ========================================================================
    print("=" * 80)
    print("SECTION C: Incorrect + should_inject=True + gold_in_context=True")
    print("  (Memory injected, gold was IN context, but LLM still got it wrong)")
    print("=" * 80)
    print(f"Count: {len(gold_in)}")
    print()

    cat_counter_in = Counter(r.get("category_name", "unknown") for r in gold_in)
    print("Category breakdown (gold_in_context=True but wrong):")
    for cat, count in cat_counter_in.most_common():
        print(f"  {cat}: {count}")
    print()

    # ========================================================================
    # SECTION D: Sample 20 failures where gold_in_context=False + fact_summary in retrieval
    # ========================================================================
    print("=" * 80)
    print("SECTION D: Sampled failures — gold_in_context=False + fact_summary in retrieval")
    print("=" * 80)

    fs_gold_not_in = [r for r in gold_not_in if has_memory_type_in_retrieval(r, "fact_summary")]
    sample_size = min(20, len(fs_gold_not_in))
    # Take evenly spaced samples to get variety
    if len(fs_gold_not_in) <= 20:
        sample = fs_gold_not_in
    else:
        step = len(fs_gold_not_in) / sample_size
        sample = [fs_gold_not_in[int(i * step)] for i in range(sample_size)]

    for i, r in enumerate(sample):
        print(f"\n--- Failure {i+1} [{r.get('category_name', '?')}] ---")
        print(f"Sample: {r.get('sample_id')}")
        print(f"Question: {r.get('question')}")
        print(f"Gold answer: {r.get('gold_answer')}")
        print(f"Predicted: {r.get('predicted_answer')}")
        print(f"Answer reasoning: {r.get('answer_reasoning')}")
        print(f"Judge reasoning: {r.get('judge_reasoning')}")
        print(f"Retrieval types: {get_all_memory_types_in_retrieval(r)}")
        print(f"Result count: {r.get('result_count')}")
        print(f"Injectable blocks: {r.get('injectable_block_count')}")

        # Evidence trace details
        et = r.get("evidence_trace", {})
        print(f"Extraction found: {et.get('extraction_found')}")
        print(f"Retrieval found: {et.get('retrieval_found')}")
        for trace in et.get("traces", []):
            eid = trace.get("evidence_id")
            extracted = trace.get("extracted")
            retrieved = trace.get("retrieved")
            mem_types = trace.get("memory_types", [])
            type_counts = Counter(mem_types)
            print(f"  Evidence {eid}: extracted={extracted}, retrieved={retrieved}, "
                  f"memory_count={trace.get('memory_count')}, "
                  f"types={dict(type_counts)}")

    print()

    # ========================================================================
    # SECTION E: No-injection cases (should_inject=False) — decision_reason breakdown
    # ========================================================================
    print("=" * 80)
    print("SECTION E: No-injection cases (should_inject=False)")
    print("=" * 80)

    no_inject = [r for r in records if not r.get("should_inject")]
    print(f"Total no-inject: {len(no_inject)}")

    ni_correct = sum(1 for r in no_inject if r["correct"])
    ni_incorrect = sum(1 for r in no_inject if not r["correct"])
    print(f"  Correct: {ni_correct}, Incorrect: {ni_incorrect}")
    print()

    reason_counter = Counter(r.get("decision_reason", "unknown") for r in no_inject)
    print("Decision reason breakdown (all no-inject):")
    for reason, count in reason_counter.most_common():
        print(f"  {reason}: {count}")
    print()

    # For incorrect no-inject cases, show detail
    print("Incorrect no-inject cases:")
    for r in no_inject:
        if not r["correct"]:
            print(f"  [{r.get('category_name')}] Q: {r.get('question')[:80]}")
            print(f"    Gold: {r.get('gold_answer')[:80]}")
            print(f"    Predicted: {str(r.get('predicted_answer'))[:80]}")
            print(f"    Reason: {r.get('decision_reason')}")
            print()

    # ========================================================================
    # SECTION F: Temporal category failure analysis
    # ========================================================================
    print("=" * 80)
    print("SECTION F: Temporal category failure analysis")
    print("=" * 80)

    temporal = [r for r in records if r.get("category_name") == "temporal"]
    temporal_correct = [r for r in temporal if r["correct"]]
    temporal_incorrect = [r for r in temporal if not r["correct"]]
    print(f"Total temporal: {len(temporal)}")
    print(f"Temporal correct: {len(temporal_correct)} ({len(temporal_correct)/len(temporal)*100:.1f}%)")
    print(f"Temporal incorrect: {len(temporal_incorrect)} ({len(temporal_incorrect)/len(temporal)*100:.1f}%)")
    print()

    # Temporal failures by injection status
    temp_inj = [r for r in temporal_incorrect if r.get("should_inject")]
    temp_noinj = [r for r in temporal_incorrect if not r.get("should_inject")]
    print(f"Temporal failures with injection: {len(temp_inj)}")
    print(f"Temporal failures without injection: {len(temp_noinj)}")
    print()

    # gold_in_context for temporal failures
    temp_gold_in = [r for r in temp_inj if r.get("gold_in_context")]
    temp_gold_not = [r for r in temp_inj if not r.get("gold_in_context")]
    print(f"Temporal injected failures, gold_in_context=True: {len(temp_gold_in)}")
    print(f"Temporal injected failures, gold_in_context=False: {len(temp_gold_not)}")
    print()

    # List all temporal failures
    print("All temporal failures:")
    for i, r in enumerate(temporal_incorrect):
        print(f"\n  [{i+1}] Sample: {r.get('sample_id')}")
        print(f"  Q: {r.get('question')}")
        print(f"  Gold: {r.get('gold_answer')}")
        print(f"  Predicted: {r.get('predicted_answer')}")
        print(f"  should_inject={r.get('should_inject')}, gold_in_context={r.get('gold_in_context')}")
        print(f"  Retrieval types: {get_all_memory_types_in_retrieval(r)}")
        print(f"  Judge: {r.get('judge_reasoning')}")
    print()

    # ========================================================================
    # SECTION G: Overall category breakdown
    # ========================================================================
    print("=" * 80)
    print("SECTION G: Overall category breakdown")
    print("=" * 80)

    categories = sorted(set(r.get("category_name", "unknown") for r in records))
    for cat in categories:
        cat_records = [r for r in records if r.get("category_name") == cat]
        cat_correct = sum(1 for r in cat_records if r["correct"])
        cat_total = len(cat_records)
        cat_inc = cat_total - cat_correct
        print(f"  {cat}: {cat_correct}/{cat_total} correct ({cat_correct/cat_total*100:.1f}%), "
              f"{cat_inc} failures")

    print()

    # ========================================================================
    # SECTION H: Abstraction loss signal — fact_summary retrieved but detail lost
    # ========================================================================
    print("=" * 80)
    print("SECTION H: Abstraction loss signal analysis")
    print("  Records where fact_summary was retrieved, evidence was extracted,")
    print("  retrieval found the evidence, but gold_in_context=False")
    print("=" * 80)

    abstraction_loss = [
        r for r in injected_incorrect
        if not r.get("gold_in_context")
        and has_memory_type_in_retrieval(r, "fact_summary")
        and r.get("evidence_trace", {}).get("extraction_found")
        and r.get("evidence_trace", {}).get("retrieval_found")
    ]
    print(f"Abstraction loss candidates: {len(abstraction_loss)}")
    print()

    # Of these, how many also have atomic_fact retrieved?
    al_with_af = [r for r in abstraction_loss if has_memory_type_in_retrieval(r, "atomic_fact")]
    al_without_af = [r for r in abstraction_loss if not has_memory_type_in_retrieval(r, "atomic_fact")]
    print(f"  With atomic_fact also retrieved: {len(al_with_af)}")
    print(f"  Without atomic_fact (fact_summary only): {len(al_without_af)}")
    print()

    # Category breakdown
    al_cat = Counter(r.get("category_name", "unknown") for r in abstraction_loss)
    print("  Category breakdown of abstraction loss candidates:")
    for cat, count in al_cat.most_common():
        print(f"    {cat}: {count}")
    print()

    # ========================================================================
    # SECTION I: Extraction gap — evidence extracted but NOT retrieved
    # ========================================================================
    print("=" * 80)
    print("SECTION I: Extraction gap (extracted but not retrieved)")
    print("=" * 80)

    extraction_gap = [
        r for r in injected_incorrect
        if r.get("evidence_trace", {}).get("extraction_found")
        and not r.get("evidence_trace", {}).get("retrieval_found")
    ]
    print(f"Extraction gap count: {len(extraction_gap)}")
    for r in extraction_gap:
        print(f"  [{r.get('category_name')}] Q: {r.get('question')[:80]}")
        print(f"    Gold: {r.get('gold_answer')[:60]}")
    print()

    # Not extracted at all
    not_extracted = [
        r for r in injected_incorrect
        if not r.get("evidence_trace", {}).get("extraction_found")
    ]
    print(f"Not extracted at all: {len(not_extracted)}")
    for r in not_extracted:
        print(f"  [{r.get('category_name')}] Q: {r.get('question')[:80]}")
        print(f"    Gold: {r.get('gold_answer')[:60]}")
        print(f"    Evidence IDs: {r.get('evidence_trace', {}).get('evidence_ids', [])}")
    print()

    # ========================================================================
    # SECTION J: Retrieval-only memory type combinations for all incorrect
    # ========================================================================
    print("=" * 80)
    print("SECTION J: Retrieval memory type combinations (injected-incorrect)")
    print("=" * 80)

    combo_counter = Counter()
    for r in injected_incorrect:
        types = tuple(sorted(set(get_all_memory_types_in_retrieval(r))))
        combo_counter[types] += 1

    for combo, count in combo_counter.most_common():
        print(f"  {combo}: {count}")
    print()

    # ========================================================================
    # SECTION K: Sample ID breakdown — which conversations have most failures
    # ========================================================================
    print("=" * 80)
    print("SECTION K: Failures by sample_id (conversation)")
    print("=" * 80)

    sample_failures = Counter(r.get("sample_id", "?") for r in incorrect)
    sample_totals = Counter(r.get("sample_id", "?") for r in records)

    for sid, fail_count in sample_failures.most_common(20):
        total = sample_totals[sid]
        print(f"  {sid}: {fail_count}/{total} failed ({fail_count/total*100:.1f}%)")
    print()

    # ========================================================================
    # Summary
    # ========================================================================
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total: {len(records)}, Correct: {len(correct)}, Incorrect: {len(incorrect)}")
    print(f"Accuracy: {len(correct)/len(records)*100:.1f}%")
    print(f"Injected-but-incorrect: {len(injected_incorrect)}")
    print(f"  gold_in_context=True (LLM reasoning failure):  {len(gold_in)}")
    print(f"  gold_in_context=False (retrieval/abstraction):  {len(gold_not_in)}")
    print(f"    Abstraction loss (fs retrieved, evidence found, gold missing): {len(abstraction_loss)}")
    print(f"      fact_summary only (no atomic_fact): {len(al_without_af)}")
    print(f"      fact_summary + atomic_fact:         {len(al_with_af)}")
    print(f"    Extraction gap (extracted but not retrieved): {len(extraction_gap)}")
    print(f"    Not extracted at all: {len(not_extracted)}")
    print(f"No-inject incorrect: {len(no_inject_incorrect)}")


if __name__ == "__main__":
    main()
