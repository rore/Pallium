"""Extraction alternatives eval — tests Haiku triage, thread-level extraction,
and routing vs extraction quality analysis on the labeled corpus.

Runs real LLM calls against the local proxy to measure each alternative.

Usage:
    python -m evals.extraction_alternatives_eval [--test 1|2|3|all] [--cache-dir .local/llm-cache]
"""
from __future__ import annotations

import argparse
import json
import hashlib
import sys
import time
from pathlib import Path
from typing import Any

from app.config import AppConfig
from app.dependencies import build_llm_provider

CORPUS_PATH = Path(__file__).parent / "extraction_alternatives_corpus.jsonl"
THREAD_CONTEXT_PATH = Path(__file__).parent / "extraction_alternatives_thread_context.jsonl"
RESULTS_PATH = Path(__file__).parent / "extraction_alternatives_results.json"


# ---------------------------------------------------------------------------
# LLM cache (same pattern as other evals)
# ---------------------------------------------------------------------------

class LLMCache:
    def __init__(self, cache_dir: Path | None):
        self._dir = cache_dir
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> dict | None:
        if not self._dir:
            return None
        path = self._dir / f"{key}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return None

    def put(self, key: str, value: dict):
        if not self._dir:
            return
        path = self._dir / f"{key}.json"
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _cache_key(prompt_id: str, content: str) -> str:
    h = hashlib.sha256(f"{prompt_id}:{content}".encode()).hexdigest()[:16]
    return f"ext_alt_{prompt_id}_{h}"


# ---------------------------------------------------------------------------
# Test 1: Haiku triage
# ---------------------------------------------------------------------------

HAIKU_TRIAGE_SYSTEM_PROMPT = """\
You classify a source item from an AI agent conversation for downstream processing.
Return exactly one JSON object.

Classify:
- is_low_value_meta: true if this is non-durable orchestration noise (greetings, \
acknowledgments, status pings, "ok"/"continue"/"got it", capability boilerplate, \
short commands without embedded knowledge). false otherwise.
- has_investigation_finding: true if this item contains a resolved finding, \
root cause, conclusion, diagnostic outcome, verdict, or analytical conclusion. \
The finding must be STATED (not implied) and RESOLVED (not speculative). \
Look for: "Root cause:", "Investigation found", "Verdict:", "Conclusion:", \
"The problem was", "found that", "turns out", explicit analytical conclusions.
- has_constraint: true if the speaker commits to a requirement, prohibition, or \
hard rule. Not preferences, not tentative, not hedged.
- signal_summary: null if is_low_value_meta=true. Otherwise, a very brief (1 sentence) \
description of any work-state present: progress made, blockers hit, next steps stated, \
key findings. null if none are present."""

HAIKU_TRIAGE_SCHEMA = json.dumps({
    "is_low_value_meta": "boolean",
    "has_investigation_finding": "boolean",
    "has_constraint": "boolean",
    "signal_summary": "string or null",
}, indent=2)


def run_test_1(corpus: list[dict], provider, cache: LLMCache) -> dict:
    """Test Haiku triage: can Haiku correctly classify items?"""
    results = {
        "total": len(corpus),
        "lvm_agreement": {"agree": 0, "disagree": 0, "details": []},
        "investigation_detection": {
            "true_positive": 0, "false_negative": 0,
            "true_negative": 0, "false_positive": 0,
        },
        "constraint_detection": {
            "true_positive": 0, "false_negative": 0,
            "true_negative": 0, "false_positive": 0,
        },
        "errors": 0,
    }

    for i, item in enumerate(corpus):
        content = item["content"] or ""
        if not content.strip():
            continue

        cache_key = _cache_key("haiku_triage", content[:4000])
        cached = cache.get(cache_key)
        if cached:
            response = cached
        else:
            try:
                user_prompt = f"Role: {item['role'] or 'unknown'}\nContent:\n{content[:4000]}"
                llm_response = provider.generate_json(
                    system_prompt=HAIKU_TRIAGE_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    schema_description=HAIKU_TRIAGE_SCHEMA,
                )
                response = llm_response.parsed_json
                cache.put(cache_key, response)
            except Exception as e:
                results["errors"] += 1
                if results["errors"] <= 3:
                    print(f"  Error on item {i}: {e}")
                continue

        # Compare with ground truth
        sonnet_lvm = item["current_signals"].get("is_low_value_meta") or False
        haiku_lvm = response.get("is_low_value_meta") or False

        if sonnet_lvm == haiku_lvm:
            results["lvm_agreement"]["agree"] += 1
        else:
            results["lvm_agreement"]["disagree"] += 1
            if len(results["lvm_agreement"]["details"]) < 10:
                results["lvm_agreement"]["details"].append({
                    "content_preview": content[:100],
                    "sonnet": sonnet_lvm,
                    "haiku": haiku_lvm,
                })

        # Investigation detection
        haiku_has_inv = response.get("has_investigation_finding") or False
        actual_produced_inv = item["produced_type"] == "investigation_outcome"

        if actual_produced_inv and haiku_has_inv:
            results["investigation_detection"]["true_positive"] += 1
        elif actual_produced_inv and not haiku_has_inv:
            results["investigation_detection"]["false_negative"] += 1
        elif not actual_produced_inv and not haiku_has_inv:
            results["investigation_detection"]["true_negative"] += 1
        elif not actual_produced_inv and haiku_has_inv:
            results["investigation_detection"]["false_positive"] += 1

        # Constraint detection
        haiku_has_constraint = response.get("has_constraint") or False
        actual_produced_constraint = item["produced_type"] == "constraint_memory"

        if actual_produced_constraint and haiku_has_constraint:
            results["constraint_detection"]["true_positive"] += 1
        elif actual_produced_constraint and not haiku_has_constraint:
            results["constraint_detection"]["false_negative"] += 1
        elif not actual_produced_constraint and not haiku_has_constraint:
            results["constraint_detection"]["true_negative"] += 1
        elif not actual_produced_constraint and haiku_has_constraint:
            results["constraint_detection"]["false_positive"] += 1

        if (i + 1) % 50 == 0:
            print(f"  Test 1 progress: {i + 1}/{len(corpus)}")

    return results


# ---------------------------------------------------------------------------
# Test 2: Thread-level investigation extraction
# ---------------------------------------------------------------------------

THREAD_INVESTIGATION_SYSTEM_PROMPT = """\
Extract investigation outcomes from an agent conversation thread.
An investigation_outcome is a RESOLVED finding — something that was discovered, \
concluded, or proven during the conversation. Not proposals, not open questions, \
not status updates.

For each investigation outcome found:
- finding_text: exact quote from the thread stating the finding (must be a literal substring)
- evidence_text: exact quote of supporting evidence or context
- is_durable: true if this finding would be useful in a DIFFERENT conversation weeks later. \
false if it's only relevant within this specific thread context.

Return JSON: {"investigation_outcomes": [...]} or {"investigation_outcomes": []} if none found.

Rules:
- Only extract findings that are EXPLICITLY STATED, not inferred
- Findings must be self-contained: understandable without the surrounding thread
- Maximum 5 outcomes per thread (pick the most significant)
- Architect reviews, plan approvals, and quality judgments are NOT investigation outcomes
- Bug fix completion reports ("Fixed X") are NOT investigation outcomes unless they state a root cause"""

THREAD_INVESTIGATION_SCHEMA = json.dumps({
    "investigation_outcomes": [{
        "finding_text": "string (exact quote)",
        "evidence_text": "string (exact quote)",
        "is_durable": "boolean",
    }]
}, indent=2)


def run_test_2(corpus: list[dict], thread_contexts: dict, provider, cache: LLMCache) -> dict:
    """Test thread-level investigation extraction."""
    # Only test threads that contain items with known investigation outcomes
    inv_items = [c for c in corpus if c["produced_type"] == "investigation_outcome"]
    thread_refs = set(c["thread_ref"] for c in inv_items if c["thread_ref"])

    results = {
        "threads_tested": 0,
        "per_thread": [],
        "aggregate": {
            "source_items_with_good_inv": 0,
            "source_items_with_bad_inv": 0,
            "thread_found_good": 0,
            "thread_missed_good": 0,
            "thread_found_bad": 0,
            "thread_avoided_bad": 0,
        },
    }

    for thread_ref in sorted(thread_refs):
        if thread_ref not in thread_contexts:
            continue

        ctx = thread_contexts[thread_ref]
        thread_items = ctx["items"]

        # Build thread text (truncate to fit context)
        thread_text_parts = []
        char_budget = 12000
        for ti in thread_items:
            role = ti.get("role") or "unknown"
            content = ti.get("content") or ""
            artifact = ti.get("artifact_kind") or ""
            prefix = f"[{role}]"
            if artifact:
                prefix = f"[{role}/{artifact}]"
            entry = f"{prefix}: {content[:800]}"
            if sum(len(p) for p in thread_text_parts) + len(entry) > char_budget:
                thread_text_parts.append("... [truncated] ...")
                break
            thread_text_parts.append(entry)

        thread_text = "\n\n".join(thread_text_parts)

        cache_key = _cache_key("thread_inv", thread_ref)
        cached = cache.get(cache_key)
        if cached:
            response = cached
        else:
            try:
                llm_response = provider.generate_json(
                    system_prompt=THREAD_INVESTIGATION_SYSTEM_PROMPT,
                    user_prompt=thread_text,
                    schema_description=THREAD_INVESTIGATION_SCHEMA,
                )
                response = llm_response.parsed_json
                cache.put(cache_key, response)
            except Exception as e:
                print(f"  Error on thread {thread_ref[:8]}: {e}")
                continue

        # Score: which items' investigation outcomes does the thread-level approach find?
        thread_inv_items = [c for c in inv_items if c["thread_ref"] == thread_ref]
        good_items = [c for c in thread_inv_items if c["majority_rating"] == "relevant"]
        bad_items = [c for c in thread_inv_items if c["majority_rating"] == "not_relevant"]

        thread_outcomes = response.get("investigation_outcomes") or []
        thread_findings_text = " ".join(
            (o.get("finding_text") or "") + " " + (o.get("evidence_text") or "")
            for o in thread_outcomes
        ).lower()

        # Check if good items' content appears in thread findings
        good_found = 0
        for item in good_items:
            # Check if ANY of the thread-level findings overlap with this item's content
            item_content_words = set(item["content"].lower().split()[:20])
            overlap = sum(1 for w in item_content_words if len(w) > 4 and w in thread_findings_text)
            if overlap >= 3:
                good_found += 1

        bad_found = 0
        for item in bad_items:
            item_content_words = set(item["content"].lower().split()[:20])
            overlap = sum(1 for w in item_content_words if len(w) > 4 and w in thread_findings_text)
            if overlap >= 3:
                bad_found += 1

        results["threads_tested"] += 1
        results["aggregate"]["source_items_with_good_inv"] += len(good_items)
        results["aggregate"]["source_items_with_bad_inv"] += len(bad_items)
        results["aggregate"]["thread_found_good"] += good_found
        results["aggregate"]["thread_missed_good"] += len(good_items) - good_found
        results["aggregate"]["thread_found_bad"] += bad_found
        results["aggregate"]["thread_avoided_bad"] += len(bad_items) - bad_found

        results["per_thread"].append({
            "thread_ref": thread_ref[:8],
            "thread_size": ctx["item_count"],
            "good_items": len(good_items),
            "good_found": good_found,
            "bad_items": len(bad_items),
            "bad_found": bad_found,
            "outcomes_extracted": len(thread_outcomes),
            "durable_outcomes": sum(1 for o in thread_outcomes if o.get("is_durable")),
        })

        if results["threads_tested"] % 5 == 0:
            print(f"  Test 2 progress: {results['threads_tested']}/{len(thread_refs)} threads")

    return results


# ---------------------------------------------------------------------------
# Test 3: Routing vs extraction analysis
# ---------------------------------------------------------------------------

def run_test_3(corpus: list[dict]) -> dict:
    """Analyze whether 'not_relevant' ratings are extraction failures or routing failures.

    Classifies based on feedback reasons:
    - If reason says "unrelated to [query topic]" → routing failure (memory is fine, wrong target)
    - If reason implies memory content is bad → extraction failure
    """
    inv_items = [c for c in corpus if c["produced_type"] == "investigation_outcome" and c["majority_rating"] == "not_relevant"]

    routing_indicators = [
        "unrelated to", "not related to", "not relevant to",
        "different sub", "different thread", "not about",
        "user is asking about", "user asked about",
        "user wants", "current discussion",
    ]
    extraction_indicators = [
        "too vague", "not a finding", "not an investigation",
        "trivial", "obvious", "no value", "already known",
        "duplicate", "same as",
    ]

    results = {
        "total_bad_investigations": len(inv_items),
        "routing_failures": [],
        "extraction_failures": [],
        "ambiguous": [],
    }

    for item in inv_items:
        all_reasons = " ".join(r.get("reason", "") or "" for r in item["ratings"] if r["rating"] == "not_relevant").lower()

        is_routing = any(ind in all_reasons for ind in routing_indicators)
        is_extraction = any(ind in all_reasons for ind in extraction_indicators)

        entry = {
            "content_preview": (item["content"] or "")[:100],
            "reasons": [r["reason"][:100] for r in item["ratings"] if r["rating"] == "not_relevant"][:3],
        }

        if is_routing and not is_extraction:
            results["routing_failures"].append(entry)
        elif is_extraction and not is_routing:
            results["extraction_failures"].append(entry)
        elif is_routing and is_extraction:
            results["ambiguous"].append(entry)
        else:
            # Default: check if reasons mention the query context
            if "about" in all_reasons or "related" in all_reasons:
                results["routing_failures"].append(entry)
            else:
                results["ambiguous"].append(entry)

    # Same for constraints
    con_items = [c for c in corpus if c["produced_type"] == "constraint_memory" and c["majority_rating"] == "not_relevant"]
    results["total_bad_constraints"] = len(con_items)
    results["constraint_routing_failures"] = 0
    results["constraint_extraction_failures"] = 0

    for item in con_items:
        all_reasons = " ".join(r.get("reason", "") or "" for r in item["ratings"] if r["rating"] == "not_relevant").lower()
        if any(ind in all_reasons for ind in routing_indicators):
            results["constraint_routing_failures"] += 1
        elif any(ind in all_reasons for ind in extraction_indicators):
            results["constraint_extraction_failures"] += 1

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load_corpus() -> list[dict]:
    return [json.loads(line) for line in open(CORPUS_PATH, encoding="utf-8") if line.strip()]


def load_thread_contexts() -> dict[str, dict]:
    contexts = {}
    for line in open(THREAD_CONTEXT_PATH, encoding="utf-8"):
        if line.strip():
            ctx = json.loads(line)
            contexts[ctx["thread_ref"]] = ctx
    return contexts


def print_test_1_results(results: dict):
    print("\n" + "=" * 60)
    print("TEST 1: HAIKU TRIAGE CAPABILITY")
    print("=" * 60)

    lvm = results["lvm_agreement"]
    total_lvm = lvm["agree"] + lvm["disagree"]
    print(f"\nis_low_value_meta agreement with Sonnet:")
    print(f"  Agree: {lvm['agree']}/{total_lvm} ({lvm['agree']/max(total_lvm,1)*100:.1f}%)")
    print(f"  Disagree: {lvm['disagree']}/{total_lvm} ({lvm['disagree']/max(total_lvm,1)*100:.1f}%)")
    if lvm["details"]:
        print(f"  Sample disagreements:")
        for d in lvm["details"][:5]:
            print(f"    Sonnet={d['sonnet']} Haiku={d['haiku']}: {d['content_preview'][:60]}")

    inv = results["investigation_detection"]
    print(f"\nInvestigation finding detection:")
    tp, fn, tn, fp = inv["true_positive"], inv["false_negative"], inv["true_negative"], inv["false_positive"]
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    print(f"  True positive (correct flag): {tp}")
    print(f"  False negative (missed): {fn}")
    print(f"  True negative (correct skip): {tn}")
    print(f"  False positive (over-flag): {fp}")
    print(f"  Precision: {precision:.1%}  Recall: {recall:.1%}")
    if tp + fp > 0:
        print(f"  → If we only send flagged items to Sonnet: {tp+fp} items ({(tp+fp)/results['total']*100:.0f}% of traffic)")

    con = results["constraint_detection"]
    tp_c, fn_c, tn_c, fp_c = con["true_positive"], con["false_negative"], con["true_negative"], con["false_positive"]
    precision_c = tp_c / max(tp_c + fp_c, 1)
    recall_c = tp_c / max(tp_c + fn_c, 1)
    print(f"\nConstraint detection:")
    print(f"  Precision: {precision_c:.1%}  Recall: {recall_c:.1%}")
    print(f"  TP={tp_c} FN={fn_c} TN={tn_c} FP={fp_c}")

    print(f"\nErrors: {results['errors']}")


def print_test_2_results(results: dict):
    print("\n" + "=" * 60)
    print("TEST 2: THREAD-LEVEL INVESTIGATION EXTRACTION")
    print("=" * 60)

    agg = results["aggregate"]
    print(f"\nThreads tested: {results['threads_tested']}")
    print(f"\nGood investigation items (should find):")
    print(f"  Found: {agg['thread_found_good']}/{agg['source_items_with_good_inv']} ({agg['thread_found_good']/max(agg['source_items_with_good_inv'],1)*100:.0f}%)")
    print(f"  Missed: {agg['thread_missed_good']}")
    print(f"\nBad investigation items (should avoid):")
    print(f"  Avoided: {agg['thread_avoided_bad']}/{agg['source_items_with_bad_inv']} ({agg['thread_avoided_bad']/max(agg['source_items_with_bad_inv'],1)*100:.0f}%)")
    print(f"  Still found: {agg['thread_found_bad']}")

    if agg["source_items_with_good_inv"] > 0:
        current_precision = agg["source_items_with_good_inv"] / (agg["source_items_with_good_inv"] + agg["source_items_with_bad_inv"])
        thread_produced = agg["thread_found_good"] + agg["thread_found_bad"]
        thread_precision = agg["thread_found_good"] / max(thread_produced, 1)
        print(f"\nPrecision comparison:")
        print(f"  Current per-item: {current_precision:.1%}")
        print(f"  Thread-level: {thread_precision:.1%}")
        print(f"  Recall at thread-level: {agg['thread_found_good']/max(agg['source_items_with_good_inv'],1):.1%}")

    print(f"\nPer-thread breakdown:")
    for t in sorted(results["per_thread"], key=lambda x: -x["thread_size"])[:10]:
        print(f"  {t['thread_ref']} (size={t['thread_size']}): "
              f"extracted={t['outcomes_extracted']} durable={t['durable_outcomes']} | "
              f"good={t['good_found']}/{t['good_items']} bad={t['bad_found']}/{t['bad_items']}")


def print_test_3_results(results: dict):
    print("\n" + "=" * 60)
    print("TEST 3: ROUTING vs EXTRACTION FAILURE ANALYSIS")
    print("=" * 60)

    total = results["total_bad_investigations"]
    routing = len(results["routing_failures"])
    extraction = len(results["extraction_failures"])
    ambiguous = len(results["ambiguous"])

    print(f"\nBad investigation outcomes: {total}")
    print(f"  Routing failures (memory fine, wrong target): {routing} ({routing/max(total,1)*100:.0f}%)")
    print(f"  Extraction failures (memory itself bad): {extraction} ({extraction/max(total,1)*100:.0f}%)")
    print(f"  Ambiguous: {ambiguous} ({ambiguous/max(total,1)*100:.0f}%)")

    print(f"\nBad constraints: {results['total_bad_constraints']}")
    print(f"  Routing: {results['constraint_routing_failures']}")
    print(f"  Extraction: {results['constraint_extraction_failures']}")

    print(f"\nImplication:")
    if routing > extraction:
        improvable = extraction + ambiguous
        print(f"  Routing is the primary failure mode ({routing}/{total} = {routing/max(total,1)*100:.0f}%)")
        print(f"  Extraction improvements can address at most {improvable}/{total} items")
        print(f"  → Better routing/targeting would have more impact than better extraction")
    else:
        print(f"  Extraction is the primary failure mode")
        print(f"  → Improving extraction quality directly addresses the problem")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", default="all", help="Which test: 1, 2, 3, or all")
    parser.add_argument("--cache-dir", default=".local/llm-cache", help="LLM response cache")
    args = parser.parse_args()

    corpus = load_corpus()
    print(f"Loaded corpus: {len(corpus)} items")

    cache = LLMCache(Path(args.cache_dir) if args.cache_dir else None)
    config = AppConfig.from_env()

    all_results = {}

    # Test 3 is pure analysis — no LLM needed
    if args.test in ("3", "all"):
        print("\n--- Running Test 3: Routing vs Extraction Analysis ---")
        results_3 = run_test_3(corpus)
        all_results["test_3"] = results_3
        print_test_3_results(results_3)

    # Test 1: Haiku triage (needs Haiku provider)
    if args.test in ("1", "all"):
        print("\n--- Running Test 1: Haiku Triage ---")
        haiku_provider = build_llm_provider(
            config, provider_name="hai_anthropic", model="anthropic--claude-haiku-latest"
        )
        results_1 = run_test_1(corpus, haiku_provider, cache)
        all_results["test_1"] = results_1
        print_test_1_results(results_1)

    # Test 2: Thread-level (needs Sonnet provider + thread contexts)
    if args.test in ("2", "all"):
        print("\n--- Running Test 2: Thread-Level Investigation Extraction ---")
        thread_contexts = load_thread_contexts()
        sonnet_provider = build_llm_provider(
            config, provider_name="hai_anthropic", model="anthropic--claude-sonnet-latest"
        )
        results_2 = run_test_2(corpus, thread_contexts, sonnet_provider, cache)
        all_results["test_2"] = results_2
        print_test_2_results(results_2)

    # Save all results
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved to {RESULTS_PATH}")


if __name__ == "__main__":
    main()
