"""Correction deep-dive — classifies WHY users correct the agent and maps
each correction type to a memory capability that could prevent it.

Takes the cached efficiency classifications, pulls correction messages with
their preceding assistant context, and uses Haiku to categorize the correction.

Usage:
    python -m evals.agent_correction_analysis --cache-dir .local/llm-cache
    python -m evals.agent_correction_analysis --cache-dir .local/llm-cache --verbose
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.config import AppConfig
from app.dependencies import build_llm_provider
from evals.eval_rate_limiter import TokenBucketRateLimiter


DB_PATH = Path.home() / ".pallium" / "data" / "pallium.db"
RESULTS_PATH = Path(__file__).parent / "agent_correction_results.json"
CONTAINER_REF = "git:github.com/rore/pallium"


# ---------------------------------------------------------------------------
# LLM cache (reused pattern)
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


def _cache_key(prefix: str, content: str) -> str:
    h = hashlib.sha256(content.encode(errors="replace")).hexdigest()[:16]
    return f"{prefix}_{h}"


# ---------------------------------------------------------------------------
# Classification prompt
# ---------------------------------------------------------------------------

CORRECTION_CLASSIFY_SYSTEM = """\
You analyze WHY a user corrected an AI coding assistant. You are given:
1. The assistant's message that triggered the correction
2. The user's correction message

Classify the correction into exactly ONE primary category. Return a JSON object.

Categories:
- "preference_violation": The assistant did the work correctly but used an \
approach/style/tool the user doesn't prefer. The output was functional but \
not how the user wants it done. Examples: wrong formatting, wrong library, \
too verbose, wrong abstraction level, unnecessary additions.
- "scope_misunderstanding": The assistant worked on the wrong thing entirely \
or misunderstood what was being asked. The assistant's output doesn't address \
the actual request. Examples: implementing wrong feature, answering wrong question, \
editing wrong file, solving a different problem.
- "missed_context": The assistant didn't account for information available in \
the conversation or project. It re-explored something already known, repeated \
a failed approach, or ignored a constraint already stated. Examples: "we already \
tried that", "I told you X", "look at what we discussed".
- "wrong_approach": The assistant understood the task but chose a poor \
implementation strategy. The direction is roughly right but the specific \
technical approach is wrong. Examples: wrong algorithm, wrong API usage, \
inefficient method, architectural mismatch.
- "incomplete_work": The assistant stopped too early, skipped steps, or \
delivered partial results. Examples: "you didn't finish", "what about X", \
"you missed Y".
- "over_engineering": The assistant added unnecessary complexity, abstractions, \
features, or scaffolding beyond what was asked. Examples: "I just wanted X, \
not all this", "too much", "simpler please".
- "communication_issue": The assistant talked too much, explained unnecessarily, \
asked when it should have acted, or was otherwise annoying in HOW it communicated \
rather than WHAT it did. Examples: "just do it", "stop asking", "I don't need \
an explanation".

Also provide:
- "could_memory_prevent": boolean - could a memory system realistically have \
prevented this correction by providing the right context/preference/constraint?
- "memory_type_needed": string or null - if preventable, what kind of memory \
would help? One of: "behavioral_preference", "project_convention", \
"prior_decision", "task_context", "approach_pattern", "scope_boundary", null
- "confidence": float 0-1 - how confident are you in this classification?

Return exactly one JSON object."""

CORRECTION_CLASSIFY_SCHEMA = json.dumps({
    "category": "string (one of: preference_violation, scope_misunderstanding, missed_context, wrong_approach, incomplete_work, over_engineering, communication_issue)",
    "could_memory_prevent": "boolean",
    "memory_type_needed": "string or null (one of: behavioral_preference, project_convention, prior_decision, task_context, approach_pattern, scope_boundary, null)",
    "confidence": "float 0-1",
    "brief_reason": "string (1 sentence explaining the classification)",
})


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_conversation_items(db_path: Path) -> list[dict]:
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("""
        SELECT id, content, role, thread_ref, LENGTH(content) as content_len,
               created_at
        FROM source_items
        WHERE container_ref = ?
          AND thread_ref IS NOT NULL
          AND role IN ('user', 'assistant')
          AND LENGTH(content) > 10
        ORDER BY created_at
    """, (CONTAINER_REF,))
    items = []
    for row in cur.fetchall():
        items.append({
            "id": row[0],
            "content": row[1],
            "role": row[2],
            "thread_ref": row[3],
            "content_len": row[4],
            "created_at": row[5],
        })
    conn.close()
    return items


def load_injection_data(db_path: Path) -> dict:
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("""
        SELECT thread_ref,
               SUM(CASE WHEN should_inject = 1 THEN 1 ELSE 0 END) as injections
        FROM query_audit_log
        WHERE thread_ref IS NOT NULL
        GROUP BY thread_ref
    """)
    thread_injections = {}
    for row in cur.fetchall():
        thread_injections[row[0]] = row[1]
    conn.close()
    return thread_injections


# ---------------------------------------------------------------------------
# Identify corrections using cached efficiency classifications
# ---------------------------------------------------------------------------

def find_corrections(
    items: list[dict],
    efficiency_cache_dir: Path | None,
) -> list[dict]:
    """Find user messages classified as corrections and pair with preceding assistant message."""
    efficiency_cache = LLMCache(efficiency_cache_dir)
    corrections = []

    # Group by thread to find preceding messages
    threads: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        threads[item["thread_ref"]].append(item)

    for thread_ref, thread_items in threads.items():
        for i, item in enumerate(thread_items):
            if item["role"] != "user":
                continue

            # Check if this was classified as a correction
            content = item["content"][:2000]
            cache_key = f"eff_user_{hashlib.sha256(content.encode(errors='replace')).hexdigest()[:16]}"
            cached = efficiency_cache.get(cache_key)
            if not cached or not cached.get("is_correction"):
                continue

            # Find preceding assistant message
            preceding_assistant = None
            for j in range(i - 1, -1, -1):
                if thread_items[j]["role"] == "assistant":
                    preceding_assistant = thread_items[j]
                    break

            corrections.append({
                "thread_ref": thread_ref,
                "correction_msg": item["content"],
                "preceding_msg": preceding_assistant["content"] if preceding_assistant else "",
                "created_at": item["created_at"],
            })

    return corrections


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_correction(
    correction: dict,
    provider,
    cache: LLMCache,
    limiter: TokenBucketRateLimiter,
) -> dict | None:
    # Build the input for classification
    preceding = correction["preceding_msg"][:1500]
    user_correction = correction["correction_msg"][:1000]

    combined = f"ASSISTANT MESSAGE (that triggered correction):\n{preceding}\n\n---\n\nUSER CORRECTION:\n{user_correction}"
    cache_key = _cache_key("corr", combined[:3000])

    cached = cache.get(cache_key)
    if cached:
        return cached

    try:
        limiter.acquire()
        response = provider.generate_json(
            system_prompt=CORRECTION_CLASSIFY_SYSTEM,
            user_prompt=combined,
            schema_description=CORRECTION_CLASSIFY_SCHEMA,
        )
        result = response.parsed_json
        cache.put(cache_key, result)
        return result
    except Exception as e:
        print(f"    ERROR: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Analysis and report
# ---------------------------------------------------------------------------

def run_analysis(
    corrections: list[dict],
    thread_injections: dict,
    provider,
    cache: LLMCache,
    limiter: TokenBucketRateLimiter,
    verbose: bool = False,
) -> dict:
    results = []
    errors = 0

    for i, correction in enumerate(corrections):
        if i % 20 == 0:
            print(f"  Classifying correction {i}/{len(corrections)}...", file=sys.stderr)

        classification = classify_correction(correction, provider, cache, limiter)
        if classification is None:
            errors += 1
            continue

        has_memory = thread_injections.get(correction["thread_ref"], 0) > 0
        results.append({
            "thread_ref": correction["thread_ref"],
            "category": classification.get("category", "unknown"),
            "could_memory_prevent": classification.get("could_memory_prevent", False),
            "memory_type_needed": classification.get("memory_type_needed"),
            "confidence": classification.get("confidence", 0),
            "brief_reason": classification.get("brief_reason", ""),
            "has_memory": has_memory,
            "correction_preview": correction["correction_msg"][:150],
        })

        if verbose:
            print(f"    [{classification.get('category', '?')}] {correction['correction_msg'][:100]}", file=sys.stderr)

    return {"corrections": results, "total": len(corrections), "errors": errors}


def print_report(analysis: dict, thread_injections: dict):
    corrections = analysis["corrections"]
    total = analysis["total"]
    errors = analysis["errors"]

    print("\n=== Correction Deep-Dive Analysis ===\n")
    print(f"Total corrections analyzed: {total}")
    print(f"Successfully classified: {len(corrections)}")
    print(f"Errors: {errors}")

    # Category breakdown
    categories = defaultdict(int)
    for c in corrections:
        categories[c["category"]] += 1

    print("\n--- Correction Categories ---")
    for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
        pct = count * 100 // max(len(corrections), 1)
        print(f"  {cat}: {count} ({pct}%)")

    # Memory preventability
    preventable = [c for c in corrections if c["could_memory_prevent"]]
    not_preventable = [c for c in corrections if not c["could_memory_prevent"]]

    print(f"\n--- Memory Preventability ---")
    print(f"  Could memory prevent: {len(preventable)} ({len(preventable)*100//max(len(corrections),1)}%)")
    print(f"  Not preventable by memory: {len(not_preventable)} ({len(not_preventable)*100//max(len(corrections),1)}%)")

    # Memory type needed breakdown
    memory_types = defaultdict(int)
    for c in preventable:
        mt = c["memory_type_needed"] or "unspecified"
        memory_types[mt] += 1

    print(f"\n--- Memory Types Needed (for preventable corrections) ---")
    for mt, count in sorted(memory_types.items(), key=lambda x: -x[1]):
        pct = count * 100 // max(len(preventable), 1)
        print(f"  {mt}: {count} ({pct}%)")

    # Category × preventability cross-tab
    print(f"\n--- Category x Preventability ---")
    cat_preventable = defaultdict(lambda: {"yes": 0, "no": 0})
    for c in corrections:
        key = "yes" if c["could_memory_prevent"] else "no"
        cat_preventable[c["category"]][key] += 1

    for cat, counts in sorted(cat_preventable.items(), key=lambda x: -(x[1]["yes"] + x[1]["no"])):
        total_cat = counts["yes"] + counts["no"]
        prev_pct = counts["yes"] * 100 // max(total_cat, 1)
        print(f"  {cat}: {total_cat} total, {counts['yes']} preventable ({prev_pct}%)")

    # Memory correlation: are corrections in memory sessions more preventable?
    with_mem = [c for c in corrections if c["has_memory"]]
    without_mem = [c for c in corrections if not c["has_memory"]]

    print(f"\n--- Corrections in Memory vs Non-Memory Sessions ---")
    for label, group in [("WITH memory", with_mem), ("WITHOUT memory", without_mem)]:
        if not group:
            print(f"  {label}: no corrections")
            continue
        prev = sum(1 for c in group if c["could_memory_prevent"])
        cats = defaultdict(int)
        for c in group:
            cats[c["category"]] += 1
        top_cats = sorted(cats.items(), key=lambda x: -x[1])[:3]
        print(f"  {label} ({len(group)} corrections):")
        print(f"    Preventable: {prev} ({prev*100//len(group)}%)")
        print(f"    Top categories: {', '.join(f'{cat}({n})' for cat, n in top_cats)}")

    # Actionable summary
    print(f"\n--- Actionable Opportunities ---")
    print(f"  Total addressable corrections: {len(preventable)}/{len(corrections)}")

    # Estimate token savings
    # From efficiency analysis: ~84K tokens on correction cycles for 201 corrections
    # So ~417 tokens per correction cycle
    tokens_per_correction = 417
    potential_savings = len(preventable) * tokens_per_correction
    print(f"  Estimated token savings if all preventable corrections eliminated: ~{potential_savings:,}")

    # Top memory capabilities to build
    print(f"\n  Priority memory capabilities to build/improve:")
    for mt, count in sorted(memory_types.items(), key=lambda x: -x[1])[:5]:
        savings = count * tokens_per_correction
        print(f"    {mt}: prevents {count} corrections (~{savings:,} tokens saved)")

    # Example corrections per category
    print(f"\n--- Example Corrections (1 per category) ---")
    seen_cats = set()
    for c in sorted(corrections, key=lambda x: -x.get("confidence", 0)):
        cat = c["category"]
        if cat in seen_cats:
            continue
        seen_cats.add(cat)
        print(f"  [{cat}]")
        print(f"    \"{c['correction_preview']}\"")
        print(f"    Reason: {c['brief_reason']}")
        print(f"    Preventable: {'yes' if c['could_memory_prevent'] else 'no'}"
              f"{' -> ' + c['memory_type_needed'] if c['memory_type_needed'] else ''}")
        print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Correction deep-dive analysis")
    parser.add_argument("--cache-dir", type=Path, default=None, help="LLM response cache directory")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--rate-limit", type=int, default=20, help="Requests per minute")
    parser.add_argument("--db-path", type=Path, default=DB_PATH)
    args = parser.parse_args()

    cache_path = args.cache_dir / "correction-analysis" if args.cache_dir else None
    efficiency_cache_path = args.cache_dir / "efficiency-analysis" if args.cache_dir else None

    print("Loading config...", file=sys.stderr)
    config = AppConfig.from_env()

    print("Building Haiku provider...", file=sys.stderr)
    default_package = config.package_config(config.default_use_case)
    provider = build_llm_provider(
        config,
        provider_name=default_package.llm_provider,
        model="anthropic--claude-haiku-latest",
    )

    print(f"Loading conversation items from {args.db_path}...", file=sys.stderr)
    items = load_conversation_items(args.db_path)
    print(f"  Loaded {len(items)} items", file=sys.stderr)

    print("Identifying corrections from cached classifications...", file=sys.stderr)
    corrections = find_corrections(items, efficiency_cache_path)
    print(f"  Found {len(corrections)} corrections with context", file=sys.stderr)

    print("Loading injection data...", file=sys.stderr)
    thread_injections = load_injection_data(args.db_path)

    cache = LLMCache(cache_path)
    limiter = TokenBucketRateLimiter(capacity=args.rate_limit, refill_interval=60.0 / args.rate_limit)

    print("Classifying corrections...", file=sys.stderr)
    analysis = run_analysis(corrections, thread_injections, provider, cache, limiter, verbose=args.verbose)

    RESULTS_PATH.write_text(json.dumps(analysis, indent=2, default=str), encoding="utf-8")
    print(f"\nRaw results saved to {RESULTS_PATH}", file=sys.stderr)

    print_report(analysis, thread_injections)
    return 0


if __name__ == "__main__":
    sys.exit(main())
