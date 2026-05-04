"""Thread-level investigation extraction prompt variant eval.

Tests 3 prompt variants for adding investigation_outcome extraction to the
existing thread summary LLM call. Measures recall of known-good investigations,
false positive rate, grounding quality, and self-containedness.

Usage:
    python -m evals.thread_investigation_prompt_eval --cache-dir .local/llm-cache
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

from app.config import AppConfig
from app.dependencies import build_llm_provider
from providers.llm.base import LLMProvider

CORPUS_PATH = Path(__file__).parent / "extraction_alternatives_corpus.jsonl"
THREAD_CONTEXT_PATH = Path(__file__).parent / "extraction_alternatives_thread_context.jsonl"
RESULTS_PATH = Path(__file__).parent / "thread_investigation_prompt_results.json"


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


def _cache_key(variant: str, model_tag: str, thread_ref: str) -> str:
    h = hashlib.sha256(f"{variant}:{model_tag}:{thread_ref}".encode()).hexdigest()[:16]
    return f"thread_inv_prompt_{variant}_{model_tag}_{h}"


# ---------------------------------------------------------------------------
# Existing thread summary prompt (base)
# ---------------------------------------------------------------------------

THREAD_SUMMARY_SYSTEM_PROMPT_BASE = (
    "Summarize one agent-mediated conversation thread for future recall. "
    "Return exactly one JSON object and no extra prose. "
    "Use only facts that are explicitly present in the thread items, selected work artifacts, or carried conclusions. "
    "Selected work artifacts may describe explicit partial progress, blockers, next steps, constraints, or durable findings; include them only when they are explicitly stated. "
    "Do not infer causes, recommendations, next steps, risks, or unresolved conclusions that are not stated. "
    "Only say the thread is unresolved when the supplied content truly lacks any resolved conclusion, durable constraint, progress state, blocker, or supported next step. "
    "Keep the summary concise: at most two sentences and roughly 60 words. "
    "For content_quality, classify the summary you wrote: "
    '"substantive" when the thread contains resolved conclusions, durable findings, constraints, progress state, or work artifacts worth recalling; '
    '"query_only" when the thread contains only a user question or request with no substantive response — an assistant reply that merely acknowledges or promises to investigate does not count as a substantive response; '
    '"unresolved" when the thread has substantive back-and-forth discussion but no resolved conclusions, decisions, or durable findings; '
    '"weak" when the thread is a greeting, phatic exchange, sign-off, or otherwise carries no recallable information. '
    "For retrieval_context: write one short search-friendly context line (12-30 words) that helps this record match later queries, "
    "or null when the summary already has enough search cues. Do not restate the summary. "
    "For decisions: identify choices that were made AND committed during the thread. "
    "A decision exists when a specific approach was proposed or discussed AND then implemented, confirmed, or accepted. "
    "Each decision must be self-contained: comprehensible when read in a different conversation weeks later with no surrounding context. "
    "The decision_text must name WHAT was decided about — the subject or system. "
    "For each decision, decision_text and evidence must be EXACT QUOTES copied verbatim from the thread items. Do not paraphrase. "
    "Not decisions: unresolved discussion, proposals without follow-through, questions, status updates, preferences without implementation. "
    "Return an empty array if no decisions were committed in this thread. "
    "Write all text fields in the same language as the thread items. Do not translate to English."
)


# ---------------------------------------------------------------------------
# Prompt variants: investigation instructions appended to base
# ---------------------------------------------------------------------------

V1_MINIMAL_INSTRUCTIONS = (
    "For investigations: identify resolved findings or verified conclusions with evidence. "
    "Each investigation must be self-contained. investigation_text and evidence must be EXACT QUOTES from the thread items. "
    "Return an empty array if no investigations were resolved."
)

V2_EXPLICIT_GROUNDING_INSTRUCTIONS = (
    "For investigations: identify durable findings, resolved outcomes, or verified conclusions reached during this thread. "
    "An investigation_outcome exists when the thread resolves a question, verifies a hypothesis, or reaches a conclusion supported by evidence. "
    "Each investigation must be self-contained: comprehensible weeks later without surrounding context. "
    "The investigation_text must state the FINDING — what was discovered or concluded. "
    "For each investigation, investigation_text and evidence must be EXACT QUOTES copied verbatim from the thread items. Do not paraphrase. "
    "Not investigations: open questions, hypotheses without verification, status updates, or work-in-progress. "
    "Return an empty array if no investigations were resolved in this thread."
)

V3_GENERALIZED_CONCLUSIONS_INSTRUCTIONS = (
    "For conclusions: identify both committed decisions AND resolved investigation findings from this thread. "
    'Each conclusion has: type ("decision" or "investigation"), conclusion_text (exact quote of the decision or finding), evidence (exact quote supporting it). '
    "conclusions must be self-contained and exactly quoted from thread items. "
    "Not conclusions: open questions, proposals without follow-through, status updates, work-in-progress. "
    "Return an empty array if none found."
)


# ---------------------------------------------------------------------------
# Schema descriptions per variant
# ---------------------------------------------------------------------------

SCHEMA_V1_V2 = json.dumps({
    "summary": "string",
    "content_quality": "string",
    "retrieval_context": "string or null",
    "decisions": [{"decision_text": "string (exact quote)", "evidence": "string (exact quote)"}],
    "investigations": [{"investigation_text": "string (exact quote)", "evidence": "string (exact quote)"}],
}, indent=2)

SCHEMA_V3 = json.dumps({
    "summary": "string",
    "content_quality": "string",
    "retrieval_context": "string or null",
    "conclusions": [{"type": "decision|investigation", "conclusion_text": "string (exact quote)", "evidence": "string (exact quote)"}],
}, indent=2)


def _build_system_prompt(variant: str) -> str:
    """Build system prompt by appending investigation instructions to the base."""
    if variant == "v3_generalized":
        # v3 replaces the decision instructions with combined conclusions
        # Remove the decision instructions from base and add conclusions
        base = THREAD_SUMMARY_SYSTEM_PROMPT_BASE
        # Find and replace the decision block
        decision_start = "For decisions: identify choices"
        decision_end = "Return an empty array if no decisions were committed in this thread. "
        start_idx = base.index(decision_start)
        end_idx = base.index(decision_end) + len(decision_end)
        return base[:start_idx] + V3_GENERALIZED_CONCLUSIONS_INSTRUCTIONS + " " + base[end_idx:]
    else:
        # v1 and v2: append investigation instructions after the decision block
        if variant == "v1_minimal":
            instructions = V1_MINIMAL_INSTRUCTIONS
        else:
            instructions = V2_EXPLICIT_GROUNDING_INSTRUCTIONS
        return THREAD_SUMMARY_SYSTEM_PROMPT_BASE + " " + instructions


def _get_schema(variant: str) -> str:
    if variant == "v3_generalized":
        return SCHEMA_V3
    return SCHEMA_V1_V2


VARIANTS = ["v1_minimal", "v2_explicit_grounding", "v3_generalized"]


# ---------------------------------------------------------------------------
# Data loading
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


def get_ground_truth(corpus: list[dict]) -> dict[str, list[dict]]:
    """Group investigation_outcome items by thread_ref, split by rating."""
    by_thread: dict[str, list[dict]] = {}
    for item in corpus:
        if item.get("produced_type") != "investigation_outcome":
            continue
        thread_ref = item.get("thread_ref")
        if not thread_ref:
            continue
        by_thread.setdefault(thread_ref, []).append(item)
    return by_thread


# ---------------------------------------------------------------------------
# Thread text construction (matches production logic)
# ---------------------------------------------------------------------------

THREAD_SUMMARY_MAX_TEXT_CHARS = 4000


def _build_thread_text(thread_items: list[dict]) -> str:
    """Build thread text from items, matching production format."""
    lines = []
    for item in thread_items:
        role = item.get("role") or "unknown"
        artifact_kind = item.get("artifact_kind") or ""
        content = (item.get("content") or "").strip()
        if not content:
            continue
        if artifact_kind and artifact_kind != "None":
            prefix = f"{role}/{artifact_kind}"
        else:
            prefix = f"{role}/message" if role == "user" else f"{role}/assistant_output"
        # Truncate long items
        lines.append(f"{prefix}: {content[:800]}")
    thread_text = "\n".join(lines)
    if len(thread_text) > THREAD_SUMMARY_MAX_TEXT_CHARS:
        thread_text = thread_text[:THREAD_SUMMARY_MAX_TEXT_CHARS].rstrip() + "\n[thread items truncated for token budget]"
    return thread_text


# ---------------------------------------------------------------------------
# Grounding and quality checks
# ---------------------------------------------------------------------------

def _normalize_for_containment(text: str) -> str:
    """Normalize text for substring containment checks."""
    return " ".join(text.lower().split())


def check_grounding(investigation_text: str, evidence: str, thread_text: str) -> dict:
    """Check if investigation_text and evidence are grounded in thread text."""
    normalized_thread = _normalize_for_containment(thread_text)
    inv_grounded = _normalize_for_containment(investigation_text) in normalized_thread if investigation_text else False
    ev_grounded = _normalize_for_containment(evidence) in normalized_thread if evidence else False
    return {
        "investigation_grounded": inv_grounded,
        "evidence_grounded": ev_grounded,
        "both_grounded": inv_grounded and ev_grounded,
    }


def check_self_containedness(investigation_text: str) -> dict:
    """Check if investigation_text is self-contained (comprehensible in isolation)."""
    if not investigation_text:
        return {"length_ok": False, "has_subject": False, "self_contained_score": 0.0}

    normalized = investigation_text.strip()
    # Length check: at least 30 chars for self-containedness
    length_ok = len(normalized) >= 30
    # Subject check: should not start with pronouns or references that need context
    context_dependent_starts = ("it ", "this ", "that ", "these ", "those ", "they ", "we ", "the same ")
    has_subject = not normalized.lower().startswith(context_dependent_starts)
    # Score (0-1)
    score = 0.0
    if length_ok:
        score += 0.5
    if has_subject:
        score += 0.5
    return {
        "length_ok": length_ok,
        "has_subject": has_subject,
        "self_contained_score": score,
    }


def check_recall(
    extracted_investigations: list[dict],
    good_items: list[dict],
    thread_text: str,
) -> dict:
    """Check how many known-good investigations are covered by extracted ones."""
    if not good_items:
        return {"total_good": 0, "found": 0, "missed": 0, "recall": 1.0}

    # Build text from all extracted investigations for matching
    extracted_text = " ".join(
        (inv.get("investigation_text") or inv.get("conclusion_text") or "") + " " +
        (inv.get("evidence") or "")
        for inv in extracted_investigations
    ).lower()

    found = 0
    missed_items = []
    for item in good_items:
        item_content = (item.get("content") or "").lower()
        # Use word overlap matching (same as existing eval)
        content_words = set(item_content.split()[:30])
        significant_words = {w for w in content_words if len(w) > 4}
        if not significant_words:
            # Fallback: try any substring
            if item_content[:50] in extracted_text:
                found += 1
            else:
                missed_items.append(item.get("content", "")[:80])
            continue
        overlap = sum(1 for w in significant_words if w in extracted_text)
        if overlap >= min(3, len(significant_words)):
            found += 1
        else:
            missed_items.append(item.get("content", "")[:80])

    return {
        "total_good": len(good_items),
        "found": found,
        "missed": len(good_items) - found,
        "recall": found / len(good_items) if good_items else 1.0,
        "missed_samples": missed_items[:3],
    }


def check_false_positives(
    extracted_investigations: list[dict],
    bad_items: list[dict],
    thread_text: str,
) -> dict:
    """Check how many known-bad investigations are captured (false positives)."""
    if not bad_items:
        return {"total_bad": 0, "captured": 0, "avoided": 0, "avoidance_rate": 1.0}

    extracted_text = " ".join(
        (inv.get("investigation_text") or inv.get("conclusion_text") or "") + " " +
        (inv.get("evidence") or "")
        for inv in extracted_investigations
    ).lower()

    captured = 0
    for item in bad_items:
        item_content = (item.get("content") or "").lower()
        content_words = set(item_content.split()[:30])
        significant_words = {w for w in content_words if len(w) > 4}
        if not significant_words:
            if item_content[:50] in extracted_text:
                captured += 1
            continue
        overlap = sum(1 for w in significant_words if w in extracted_text)
        if overlap >= min(3, len(significant_words)):
            captured += 1

    return {
        "total_bad": len(bad_items),
        "captured": captured,
        "avoided": len(bad_items) - captured,
        "avoidance_rate": (len(bad_items) - captured) / len(bad_items) if bad_items else 1.0,
    }


# ---------------------------------------------------------------------------
# Extract investigations from LLM response (variant-aware)
# ---------------------------------------------------------------------------

def _extract_investigations_from_response(response: dict, variant: str) -> list[dict]:
    """Extract investigation items from the LLM response, normalizing across variants."""
    if variant == "v3_generalized":
        conclusions = response.get("conclusions") or []
        return [
            {
                "investigation_text": c.get("conclusion_text", ""),
                "evidence": c.get("evidence", ""),
            }
            for c in conclusions
            if isinstance(c, dict) and c.get("type") == "investigation"
        ]
    else:
        investigations = response.get("investigations") or []
        return [
            {
                "investigation_text": inv.get("investigation_text", ""),
                "evidence": inv.get("evidence", ""),
            }
            for inv in investigations
            if isinstance(inv, dict)
        ]


def _extract_decisions_from_response(response: dict, variant: str) -> list[dict]:
    """Extract decision items from the LLM response, normalizing across variants."""
    if variant == "v3_generalized":
        conclusions = response.get("conclusions") or []
        return [
            {
                "decision_text": c.get("conclusion_text", ""),
                "evidence": c.get("evidence", ""),
            }
            for c in conclusions
            if isinstance(c, dict) and c.get("type") == "decision"
        ]
    else:
        decisions = response.get("decisions") or []
        return [
            {
                "decision_text": d.get("decision_text", ""),
                "evidence": d.get("evidence", ""),
            }
            for d in decisions
            if isinstance(d, dict)
        ]


# ---------------------------------------------------------------------------
# Run one variant against all threads
# ---------------------------------------------------------------------------

def run_variant(
    variant: str,
    model_tag: str,
    provider: LLMProvider,
    thread_contexts: dict[str, dict],
    ground_truth: dict[str, list[dict]],
    all_thread_refs: set[str],
    cache: LLMCache,
) -> dict:
    """Run a prompt variant against all threads, return metrics."""
    system_prompt = _build_system_prompt(variant)
    schema = _get_schema(variant)
    prompt_char_count = len(system_prompt)

    results = {
        "variant": variant,
        "model": model_tag,
        "prompt_chars": prompt_char_count,
        "prompt_delta_chars": prompt_char_count - len(THREAD_SUMMARY_SYSTEM_PROMPT_BASE),
        "threads_tested": 0,
        "threads_with_ground_truth": 0,
        "threads_without_ground_truth": 0,
        "per_thread": [],
        "aggregate": {
            "total_good_items": 0,
            "good_found": 0,
            "good_missed": 0,
            "total_bad_items": 0,
            "bad_captured": 0,
            "bad_avoided": 0,
            "total_extracted": 0,
            "total_grounded_both": 0,
            "total_grounded_inv_only": 0,
            "total_grounded_neither": 0,
            "total_self_contained_score": 0.0,
            "total_decisions_extracted": 0,
            "fp_threads_with_investigations": 0,
            "fp_total_spurious": 0,
        },
        "errors": 0,
    }

    for thread_ref in sorted(all_thread_refs):
        if thread_ref not in thread_contexts:
            continue

        ctx = thread_contexts[thread_ref]
        thread_items = ctx["items"]
        thread_text = _build_thread_text(thread_items)

        if not thread_text.strip():
            continue

        # Build user prompt
        user_prompt = (
            "Summarize this thread conservatively for later recall. "
            "Use only explicit information from the provided content.\n\n"
            f"Thread ref: {thread_ref}\n\n"
            f"Thread items:\n{thread_text}"
        )

        cache_key = _cache_key(variant, model_tag, thread_ref)
        cached = cache.get(cache_key)
        if cached:
            response = cached
        else:
            try:
                llm_response = provider.generate_json(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    schema_description=schema,
                )
                response = llm_response.parsed_json
                cache.put(cache_key, response)
            except Exception as e:
                results["errors"] += 1
                if results["errors"] <= 5:
                    print(f"  [{variant}/{model_tag}] Error on thread {thread_ref[:8]}: {e}")
                continue

        results["threads_tested"] += 1

        # Extract investigations and decisions
        investigations = _extract_investigations_from_response(response, variant)
        decisions = _extract_decisions_from_response(response, variant)
        results["aggregate"]["total_extracted"] += len(investigations)
        results["aggregate"]["total_decisions_extracted"] += len(decisions)

        # Grounding checks
        for inv in investigations:
            grounding = check_grounding(
                inv.get("investigation_text", ""),
                inv.get("evidence", ""),
                thread_text,
            )
            if grounding["both_grounded"]:
                results["aggregate"]["total_grounded_both"] += 1
            elif grounding["investigation_grounded"]:
                results["aggregate"]["total_grounded_inv_only"] += 1
            else:
                results["aggregate"]["total_grounded_neither"] += 1

            sc = check_self_containedness(inv.get("investigation_text", ""))
            results["aggregate"]["total_self_contained_score"] += sc["self_contained_score"]

        # Ground truth comparison
        thread_gt = ground_truth.get(thread_ref, [])
        good_items = [i for i in thread_gt if i.get("majority_rating") == "relevant"]
        bad_items = [i for i in thread_gt if i.get("majority_rating") == "not_relevant"]

        thread_result: dict[str, Any] = {
            "thread_ref": thread_ref[:8],
            "thread_size": ctx["item_count"],
            "investigations_extracted": len(investigations),
            "decisions_extracted": len(decisions),
        }

        if thread_gt:
            results["threads_with_ground_truth"] += 1

            recall_result = check_recall(investigations, good_items, thread_text)
            fp_result = check_false_positives(investigations, bad_items, thread_text)

            results["aggregate"]["total_good_items"] += recall_result["total_good"]
            results["aggregate"]["good_found"] += recall_result["found"]
            results["aggregate"]["good_missed"] += recall_result["missed"]
            results["aggregate"]["total_bad_items"] += fp_result["total_bad"]
            results["aggregate"]["bad_captured"] += fp_result["captured"]
            results["aggregate"]["bad_avoided"] += fp_result["avoided"]

            thread_result["good_items"] = recall_result["total_good"]
            thread_result["good_found"] = recall_result["found"]
            thread_result["bad_items"] = fp_result["total_bad"]
            thread_result["bad_captured"] = fp_result["captured"]
            thread_result["recall"] = recall_result["recall"]
            thread_result["avoidance_rate"] = fp_result["avoidance_rate"]
        else:
            results["threads_without_ground_truth"] += 1
            # Any investigations here are potential false positives
            if investigations:
                results["aggregate"]["fp_threads_with_investigations"] += 1
                results["aggregate"]["fp_total_spurious"] += len(investigations)
            thread_result["no_ground_truth"] = True
            thread_result["spurious_investigations"] = len(investigations)

        results["per_thread"].append(thread_result)

    # Compute aggregate metrics
    agg = results["aggregate"]
    agg["recall"] = agg["good_found"] / max(agg["total_good_items"], 1)
    agg["avoidance_rate"] = agg["bad_avoided"] / max(agg["total_bad_items"], 1)
    total_ext = agg["total_extracted"]
    agg["grounding_rate"] = agg["total_grounded_both"] / max(total_ext, 1)
    agg["self_contained_avg"] = agg["total_self_contained_score"] / max(total_ext, 1)
    # Precision: among all extracted from GT threads, how many match a good item?
    produced_in_gt_threads = agg["good_found"] + agg["bad_captured"]
    agg["precision_in_gt_threads"] = agg["good_found"] / max(produced_in_gt_threads, 1)

    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_variant_results(results: dict):
    """Print results for one variant."""
    variant = results["variant"]
    model = results["model"]
    agg = results["aggregate"]

    print(f"\n{'─' * 60}")
    print(f"  Variant: {variant}  |  Model: {model}")
    print(f"  Prompt size: {results['prompt_chars']} chars (+{results['prompt_delta_chars']} over base)")
    print(f"{'─' * 60}")

    print(f"\n  Threads tested: {results['threads_tested']} "
          f"(with GT: {results['threads_with_ground_truth']}, "
          f"without GT: {results['threads_without_ground_truth']})")
    print(f"  Total investigations extracted: {agg['total_extracted']}")
    print(f"  Total decisions extracted: {agg['total_decisions_extracted']}")

    print(f"\n  RECALL (known-good investigations):")
    print(f"    Found: {agg['good_found']}/{agg['total_good_items']} "
          f"({agg['recall']:.1%})")
    print(f"    Missed: {agg['good_missed']}")

    print(f"\n  PRECISION / FALSE POSITIVES:")
    print(f"    Bad items avoided: {agg['bad_avoided']}/{agg['total_bad_items']} "
          f"({agg['avoidance_rate']:.1%})")
    print(f"    Bad items captured: {agg['bad_captured']}")
    print(f"    Precision in GT threads: {agg['precision_in_gt_threads']:.1%}")
    print(f"    Threads without GT that produced investigations: "
          f"{agg['fp_threads_with_investigations']} "
          f"(total spurious: {agg['fp_total_spurious']})")

    print(f"\n  GROUNDING QUALITY:")
    print(f"    Both grounded: {agg['total_grounded_both']}/{agg['total_extracted']} "
          f"({agg['grounding_rate']:.1%})")
    print(f"    Investigation only: {agg['total_grounded_inv_only']}")
    print(f"    Neither grounded: {agg['total_grounded_neither']}")

    print(f"\n  SELF-CONTAINEDNESS:")
    print(f"    Average score: {agg['self_contained_avg']:.2f}/1.0")

    if results["errors"]:
        print(f"\n  Errors: {results['errors']}")

    # Per-thread breakdown (top threads by size)
    gt_threads = [t for t in results["per_thread"] if not t.get("no_ground_truth")]
    if gt_threads:
        print(f"\n  Per-thread (with GT, sorted by size):")
        for t in sorted(gt_threads, key=lambda x: -x["thread_size"])[:8]:
            print(f"    {t['thread_ref']} (size={t['thread_size']}): "
                  f"extracted={t['investigations_extracted']} | "
                  f"good={t.get('good_found', '?')}/{t.get('good_items', '?')} "
                  f"bad={t.get('bad_captured', '?')}/{t.get('bad_items', '?')}")


def print_comparison_summary(all_results: list[dict]):
    """Print a comparison table across variants and models."""
    print("\n" + "=" * 70)
    print("COMPARISON SUMMARY")
    print("=" * 70)

    # Group by model
    models = sorted(set(r["model"] for r in all_results))
    variants = sorted(set(r["variant"] for r in all_results))

    header = f"{'Variant':<25} {'Model':<12} {'Recall':<8} {'Avoid':<8} {'Ground':<8} {'SelfCont':<8} {'Prec':<8} {'#Ext':<6}"
    print(f"\n{header}")
    print("─" * len(header))

    for model in models:
        for variant in variants:
            matching = [r for r in all_results if r["model"] == model and r["variant"] == variant]
            if not matching:
                continue
            r = matching[0]
            agg = r["aggregate"]
            print(
                f"{variant:<25} {model:<12} "
                f"{agg['recall']:<8.1%} "
                f"{agg['avoidance_rate']:<8.1%} "
                f"{agg['grounding_rate']:<8.1%} "
                f"{agg['self_contained_avg']:<8.2f} "
                f"{agg['precision_in_gt_threads']:<8.1%} "
                f"{agg['total_extracted']:<6}"
            )
        print()

    # Model comparison
    if len(models) > 1:
        print("\nMODEL COMPARISON (is Haiku sufficient?):")
        for variant in variants:
            haiku_results = [r for r in all_results if "haiku" in r["model"] and r["variant"] == variant]
            sonnet_results = [r for r in all_results if "sonnet" in r["model"] and r["variant"] == variant]
            if haiku_results and sonnet_results:
                h = haiku_results[0]["aggregate"]
                s = sonnet_results[0]["aggregate"]
                recall_diff = h["recall"] - s["recall"]
                ground_diff = h["grounding_rate"] - s["grounding_rate"]
                print(f"  {variant}:")
                print(f"    Recall: Haiku={h['recall']:.1%} Sonnet={s['recall']:.1%} (diff={recall_diff:+.1%})")
                print(f"    Grounding: Haiku={h['grounding_rate']:.1%} Sonnet={s['grounding_rate']:.1%} (diff={ground_diff:+.1%})")
                print(f"    Avoidance: Haiku={h['avoidance_rate']:.1%} Sonnet={s['avoidance_rate']:.1%}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Thread investigation prompt variant eval")
    parser.add_argument("--cache-dir", default=".local/llm-cache", help="LLM response cache directory")
    parser.add_argument("--variant", default="all", help="Which variant: v1_minimal, v2_explicit_grounding, v3_generalized, or all")
    parser.add_argument("--model", default="both", help="Which model: haiku, sonnet, or both")
    args = parser.parse_args()

    print("Thread Investigation Prompt Variant Eval")
    print("=" * 50)

    # Load data
    corpus = load_corpus()
    thread_contexts = load_thread_contexts()
    ground_truth = get_ground_truth(corpus)
    print(f"Corpus: {len(corpus)} items")
    print(f"Thread contexts: {len(thread_contexts)} threads")
    print(f"Threads with investigation GT: {len(ground_truth)}")

    relevant_count = sum(
        1 for items in ground_truth.values()
        for item in items
        if item.get("majority_rating") == "relevant"
    )
    not_relevant_count = sum(
        1 for items in ground_truth.values()
        for item in items
        if item.get("majority_rating") == "not_relevant"
    )
    print(f"  Relevant investigations: {relevant_count}")
    print(f"  Not-relevant investigations: {not_relevant_count}")

    # All thread refs to test (union of those with GT + all available contexts)
    all_thread_refs = set(thread_contexts.keys())
    print(f"Total threads to test: {len(all_thread_refs)}")

    # Setup
    cache = LLMCache(Path(args.cache_dir) if args.cache_dir else None)
    config = AppConfig.from_env()

    # Determine which variants to run
    if args.variant == "all":
        variants_to_run = VARIANTS
    else:
        variants_to_run = [args.variant]

    # Determine which models to run
    models_to_run: list[tuple[str, str, str]] = []  # (tag, provider_name, model_name)
    if args.model in ("haiku", "both"):
        models_to_run.append(("haiku", "hai_anthropic", "anthropic--claude-haiku-latest"))
    if args.model in ("sonnet", "both"):
        models_to_run.append(("sonnet", "hai_anthropic", "anthropic--claude-sonnet-latest"))

    # Print prompt sizes for reference
    print("\nPrompt variant sizes:")
    for variant in VARIANTS:
        prompt = _build_system_prompt(variant)
        delta = len(prompt) - len(THREAD_SUMMARY_SYSTEM_PROMPT_BASE)
        print(f"  {variant}: {len(prompt)} chars (+{delta} over base)")

    # Run all combinations
    all_results: list[dict] = []
    total_combinations = len(variants_to_run) * len(models_to_run)
    combo_idx = 0

    for model_tag, provider_name, model_name in models_to_run:
        print(f"\nBuilding {model_tag} provider...")
        provider = build_llm_provider(config, provider_name=provider_name, model=model_name)

        for variant in variants_to_run:
            combo_idx += 1
            print(f"\n[{combo_idx}/{total_combinations}] Running variant={variant} model={model_tag}...")
            start_time = time.time()

            result = run_variant(
                variant=variant,
                model_tag=model_tag,
                provider=provider,
                thread_contexts=thread_contexts,
                ground_truth=ground_truth,
                all_thread_refs=all_thread_refs,
                cache=cache,
            )

            elapsed = time.time() - start_time
            result["elapsed_seconds"] = round(elapsed, 1)
            all_results.append(result)

            print_variant_results(result)
            print(f"  (elapsed: {elapsed:.1f}s)")

    # Print comparison
    if len(all_results) > 1:
        print_comparison_summary(all_results)

    # Save results
    output = {
        "meta": {
            "corpus_items": len(corpus),
            "thread_contexts": len(thread_contexts),
            "threads_with_gt": len(ground_truth),
            "relevant_investigations": relevant_count,
            "not_relevant_investigations": not_relevant_count,
            "variants_tested": variants_to_run,
            "models_tested": [m[0] for m in models_to_run],
        },
        "results": all_results,
    }
    RESULTS_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nResults saved to {RESULTS_PATH}")


if __name__ == "__main__":
    main()
