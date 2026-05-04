"""Test Haiku signal extraction quality vs Sonnet ground truth.

Runs Haiku with a signal extraction prompt on items where we have
Sonnet's output, then compares quality.

Also tests constraint and investigation extraction at thread level.

Usage:
    python -m evals.extraction_alternatives_signals_eval --cache-dir .local/llm-cache
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from app.config import AppConfig
from app.dependencies import build_llm_provider

CORPUS_PATH = Path(__file__).parent / "extraction_alternatives_corpus.jsonl"
THREAD_CONTEXT_PATH = Path(__file__).parent / "extraction_alternatives_thread_context.jsonl"


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


def _cache_key(prefix: str, content: str) -> str:
    h = hashlib.sha256(content.encode()).hexdigest()[:16]
    return f"ext_sig_{prefix}_{h}"


# ---------------------------------------------------------------------------
# Haiku full signal extraction (same job as Sonnet currently does)
# ---------------------------------------------------------------------------

HAIKU_SIGNAL_SYSTEM_PROMPT = """\
Extract work-state signals from one source item in an AI agent conversation.
Return exactly one JSON object.

Fields:
- is_low_value_meta: true for non-durable noise (greetings, acknowledgments, "ok", \
"continue", status pings, capability boilerplate, short commands without knowledge).
- progress_text: substantive completed or partial work, for later resumption. \
Not boilerplate completion language. null if none.
- blocker_text: active impediment or failed attempt. null if none.
- next_step_text: a concrete future action stated in the source. \
Clarifying questions are NOT next steps. null if none.
- key_finding_text: a durable conclusion, verdict, or resolved finding. \
Not monitoring chatter or status updates. null if none.
- constraint_text: a definitive operational constraint — the speaker commits to \
a requirement, prohibition, or hard rule. Must be self-contained (resolve pronouns). \
null if hedged/tentative/anaphoric. null if none.

Rules:
- Only populate fields when the source EXPLICITLY states them.
- Prefer null over weak/speculative/inferred values.
- If is_low_value_meta is true, all other fields must be null.
- Write extracted text in the same language as the source."""

HAIKU_SIGNAL_SCHEMA = json.dumps({
    "is_low_value_meta": "boolean",
    "progress_text": "string or null",
    "blocker_text": "string or null",
    "next_step_text": "string or null",
    "key_finding_text": "string or null",
    "constraint_text": "string or null",
}, indent=2)


def run_signal_comparison(corpus: list[dict], provider, cache: LLMCache) -> dict:
    """Compare Haiku signal extraction with Sonnet ground truth."""
    items_with_signals = [c for c in corpus if any(
        c.get("current_signals", {}).get(k)
        for k in ("progress_text", "blocker_text", "next_step_text", "key_finding_text", "constraint_text")
    )]

    results = {
        "total_compared": 0,
        "per_signal": {},
        "errors": 0,
    }

    for signal_name in ("progress_text", "blocker_text", "next_step_text", "key_finding_text", "constraint_text"):
        results["per_signal"][signal_name] = {
            "sonnet_has": 0,
            "haiku_agrees": 0,
            "haiku_misses": 0,
            "haiku_adds": 0,
            "quality_samples": [],
        }

    for i, item in enumerate(items_with_signals):
        content = item["content"] or ""
        if not content.strip():
            continue

        cache_key = _cache_key("haiku_signals", content[:4000])
        cached = cache.get(cache_key)
        if cached:
            haiku_output = cached
        else:
            try:
                user_prompt = f"Role: {item['role'] or 'unknown'}\nContent:\n{content[:4000]}"
                llm_response = provider.generate_json(
                    system_prompt=HAIKU_SIGNAL_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    schema_description=HAIKU_SIGNAL_SCHEMA,
                )
                haiku_output = llm_response.parsed_json
                cache.put(cache_key, haiku_output)
            except Exception as e:
                results["errors"] += 1
                continue

        results["total_compared"] += 1
        sonnet_signals = item.get("current_signals", {})

        for signal_name in ("progress_text", "blocker_text", "next_step_text", "key_finding_text", "constraint_text"):
            sonnet_val = sonnet_signals.get(signal_name) or None
            haiku_val = haiku_output.get(signal_name) or None

            stats = results["per_signal"][signal_name]
            if sonnet_val:
                stats["sonnet_has"] += 1
                if haiku_val:
                    stats["haiku_agrees"] += 1
                    if len(stats["quality_samples"]) < 5:
                        stats["quality_samples"].append({
                            "sonnet": sonnet_val[:150],
                            "haiku": haiku_val[:150],
                        })
                else:
                    stats["haiku_misses"] += 1
            elif haiku_val:
                stats["haiku_adds"] += 1

        if (i + 1) % 50 == 0:
            print(f"  Signal comparison progress: {i + 1}/{len(items_with_signals)}")

    return results


# ---------------------------------------------------------------------------
# Thread-level constraint extraction
# ---------------------------------------------------------------------------

THREAD_CONSTRAINT_SYSTEM_PROMPT = """\
Extract durable constraints stated in an agent conversation thread.
A constraint is a definitive operational rule the user commits to — a requirement, \
prohibition, or hard rule that should be remembered for future sessions.

For each constraint found:
- constraint_text: the constraint stated in self-contained form (resolve pronouns, \
include enough context to understand without the thread)
- evidence_text: exact quote from the thread where this was stated
- is_durable: true if this applies beyond this specific thread/task

NOT constraints: hedged preferences, tentative suggestions, one-time instructions \
("do X now"), thread-scoped directives that won't matter later.

Return JSON: {"constraints": [...]} or {"constraints": []} if none found.
Max 5 constraints per thread. Pick the most durable ones."""

THREAD_CONSTRAINT_SCHEMA = json.dumps({
    "constraints": [{
        "constraint_text": "string (self-contained)",
        "evidence_text": "string (exact quote)",
        "is_durable": "boolean",
    }]
}, indent=2)


def run_thread_constraint_test(corpus: list[dict], thread_contexts: dict, provider, cache: LLMCache) -> dict:
    """Test thread-level constraint extraction."""
    constraint_items = [c for c in corpus if c["produced_type"] == "constraint_memory"]
    thread_refs = set(c["thread_ref"] for c in constraint_items if c["thread_ref"])

    results = {
        "threads_tested": 0,
        "good_constraints": sum(1 for c in constraint_items if c["majority_rating"] == "relevant"),
        "bad_constraints": sum(1 for c in constraint_items if c["majority_rating"] == "not_relevant"),
        "thread_extractions": [],
    }

    for thread_ref in sorted(thread_refs):
        if thread_ref not in thread_contexts:
            continue

        ctx = thread_contexts[thread_ref]
        thread_items = ctx["items"]

        thread_text_parts = []
        char_budget = 12000
        for ti in thread_items:
            role = ti.get("role") or "unknown"
            content = ti.get("content") or ""
            entry = f"[{role}]: {content[:800]}"
            if sum(len(p) for p in thread_text_parts) + len(entry) > char_budget:
                break
            thread_text_parts.append(entry)

        thread_text = "\n\n".join(thread_text_parts)

        cache_key = _cache_key("thread_constraint", thread_ref)
        cached = cache.get(cache_key)
        if cached:
            response = cached
        else:
            try:
                llm_response = provider.generate_json(
                    system_prompt=THREAD_CONSTRAINT_SYSTEM_PROMPT,
                    user_prompt=thread_text,
                    schema_description=THREAD_CONSTRAINT_SCHEMA,
                )
                response = llm_response.parsed_json
                cache.put(cache_key, response)
            except Exception as e:
                print(f"  Error on thread {thread_ref[:8]}: {e}")
                continue

        constraints = response.get("constraints") or []
        durable = [c for c in constraints if c.get("is_durable")]

        # How many of this thread's constraint items are good vs bad?
        thread_constraints = [c for c in constraint_items if c["thread_ref"] == thread_ref]
        good = [c for c in thread_constraints if c["majority_rating"] == "relevant"]
        bad = [c for c in thread_constraints if c["majority_rating"] == "not_relevant"]

        results["threads_tested"] += 1
        results["thread_extractions"].append({
            "thread_ref": thread_ref[:8],
            "thread_size": ctx["item_count"],
            "per_item_good": len(good),
            "per_item_bad": len(bad),
            "thread_extracted": len(constraints),
            "thread_durable": len(durable),
            "sample_constraints": [c.get("constraint_text", "")[:100] for c in durable[:3]],
        })

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", default=".local/llm-cache")
    args = parser.parse_args()

    corpus = [json.loads(line) for line in open(CORPUS_PATH, encoding="utf-8") if line.strip()]
    thread_contexts = {}
    for line in open(THREAD_CONTEXT_PATH, encoding="utf-8"):
        if line.strip():
            ctx = json.loads(line)
            thread_contexts[ctx["thread_ref"]] = ctx

    cache = LLMCache(Path(args.cache_dir))
    config = AppConfig.from_env()

    haiku_provider = build_llm_provider(config, provider_name="hai_anthropic", model="anthropic--claude-haiku-latest")
    sonnet_provider = build_llm_provider(config, provider_name="hai_anthropic", model="anthropic--claude-sonnet-latest")

    # Part 1: Haiku signal extraction quality
    print("=" * 70)
    print("HAIKU SIGNAL EXTRACTION vs SONNET GROUND TRUTH")
    print("=" * 70)
    print()
    signal_results = run_signal_comparison(corpus, haiku_provider, cache)

    print(f"\nItems compared: {signal_results['total_compared']}")
    print(f"Errors: {signal_results['errors']}")
    print()
    print(f"{'Signal':<20} {'Sonnet has':<12} {'Haiku agrees':<14} {'Haiku misses':<14} {'Haiku adds':<12} {'Recall':<8}")
    print("-" * 80)
    for signal_name, stats in signal_results["per_signal"].items():
        recall = stats["haiku_agrees"] / max(stats["sonnet_has"], 1) * 100
        print(f"{signal_name:<20} {stats['sonnet_has']:<12} {stats['haiku_agrees']:<14} {stats['haiku_misses']:<14} {stats['haiku_adds']:<12} {recall:.0f}%")

    print("\nQuality samples (Sonnet vs Haiku):")
    for signal_name, stats in signal_results["per_signal"].items():
        if stats["quality_samples"]:
            print(f"\n  {signal_name}:")
            for s in stats["quality_samples"][:2]:
                print(f"    Sonnet: {s['sonnet'][:80]}")
                print(f"    Haiku:  {s['haiku'][:80]}")
                print()

    # Part 2: Thread-level constraint extraction
    print()
    print("=" * 70)
    print("THREAD-LEVEL CONSTRAINT EXTRACTION")
    print("=" * 70)
    print()

    # Need thread contexts for constraint threads too — check if we have them
    constraint_threads = set(c["thread_ref"] for c in corpus if c["produced_type"] == "constraint_memory" and c.get("thread_ref"))
    available = constraint_threads & set(thread_contexts.keys())
    print(f"Constraint threads available: {len(available)}/{len(constraint_threads)}")

    if available:
        constraint_results = run_thread_constraint_test(corpus, thread_contexts, sonnet_provider, cache)
        print(f"\nThreads tested: {constraint_results['threads_tested']}")
        print(f"Per-item constraints in corpus: {constraint_results['good_constraints']} good, {constraint_results['bad_constraints']} bad")
        print()
        for t in constraint_results["thread_extractions"]:
            print(f"  {t['thread_ref']} (size={t['thread_size']}): "
                  f"per-item={t['per_item_good']}good/{t['per_item_bad']}bad | "
                  f"thread={t['thread_extracted']} extracted ({t['thread_durable']} durable)")
            for c in t["sample_constraints"]:
                print(f"    → {c}")
    else:
        print("No constraint thread contexts available (constraints are in different threads from investigations)")
        print("Need to export constraint thread contexts separately.")

    # Save results
    all_results = {
        "signal_comparison": signal_results,
    }
    if available:
        all_results["thread_constraints"] = constraint_results

    output_path = Path(__file__).parent / "extraction_alternatives_signals_results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    main()
