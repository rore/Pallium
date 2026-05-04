"""Injection replay simulation — measures what would happen if same-thread
suppression was lifted after N turns.

For each suppressed query, simulates what would have been injected, then
uses Haiku to classify whether the injection would have been:
- helpful (provides context the agent needs)
- redundant (agent already has this in recent context)
- noise (irrelevant to what's being discussed)

Runs at multiple thresholds to find the optimal turn count.

Usage:
    python -m evals.injection_replay_simulation --cache-dir .local/llm-cache
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
RESULTS_PATH = Path(__file__).parent / "injection_replay_results.json"
CONTAINER_REF = "git:github.com/rore/pallium"


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


def _cache_key(content: str) -> str:
    h = hashlib.sha256(content.encode(errors="replace")).hexdigest()[:16]
    return f"replay_{h}"


CLASSIFY_SYSTEM = """\
You evaluate whether injecting a memory block into an AI coding assistant's \
context would have been helpful at a specific point in a conversation.

You are given:
1. The user's message (what they just asked/said)
2. The memory block that WOULD have been injected (but wasn't)
3. The next few turns of conversation (to see what happened after)

Classify the hypothetical injection:
- "helpful": The memory provides context that would have helped the assistant \
respond correctly. The subsequent conversation shows the assistant struggled, \
got corrected, or missed something this memory addresses.
- "reinforcing": The memory provides relevant context that the assistant \
probably already knew from earlier in the conversation, but re-stating it \
would reinforce it and reduce drift risk. Not strictly necessary but not noise.
- "redundant": The memory restates something just discussed in the last few \
turns. Adding it would be pure repetition with no value.
- "noise": The memory is not relevant to what's being discussed at this point. \
Injecting it would distract rather than help.

Also rate confidence (0-1).

Return exactly one JSON object."""

CLASSIFY_SCHEMA = json.dumps({
    "classification": "string (helpful, reinforcing, redundant, noise)",
    "confidence": "float 0-1",
    "brief_reason": "string (1 sentence)",
})


def load_suppressed_queries(db_path: Path) -> list[dict]:
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    cur.execute("""
        SELECT qa.query_text, qa.candidate_scores_json, qa.thread_ref, qa.created_at
        FROM query_audit_log qa
        WHERE qa.container_ref = ?
          AND qa.decision_reason = 'same_thread_context_sufficient'
          AND qa.candidate_scores_json IS NOT NULL
        ORDER BY qa.created_at
    """, (CONTAINER_REF,))
    suppressed = []
    for row in cur.fetchall():
        suppressed.append({
            "query_text": row[0],
            "candidate_scores_json": row[1],
            "thread_ref": row[2],
            "created_at": row[3],
        })

    conn.close()
    return suppressed


def load_thread_items(db_path: Path) -> dict[str, list[dict]]:
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("""
        SELECT content, role, thread_ref, created_at
        FROM source_items
        WHERE container_ref = ?
          AND thread_ref IS NOT NULL
          AND role IN ('user', 'assistant')
        ORDER BY created_at
    """, (CONTAINER_REF,))
    threads = defaultdict(list)
    for row in cur.fetchall():
        threads[row[2]].append({
            "content": row[0],
            "role": row[1],
            "created_at": row[3],
        })
    conn.close()
    return dict(threads)


def load_memory_content(db_path: Path) -> dict[str, str]:
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("""
        SELECT id, type, payload_json
        FROM memory_objects
        WHERE container_ref = ?
    """, (CONTAINER_REF,))
    memories = {}
    for row in cur.fetchall():
        payload = json.loads(row[1] if row[2] is None else row[2])
        summary = _extract_memory_summary(row[1], payload)
        memories[row[0]] = summary
    conn.close()
    return memories


def _extract_memory_summary(mem_type: str, payload: dict) -> str:
    if mem_type == "decision":
        return payload.get("decision", "") or payload.get("decision_text", "")
    if mem_type == "investigation_outcome":
        return payload.get("investigation_outcome", "") or payload.get("investigation_text", "")
    if mem_type == "task_checkpoint":
        parts = [payload.get("task", ""), payload.get("current_state", ""), payload.get("next_step", "")]
        return " | ".join(p for p in parts if p)
    if mem_type == "constraint_memory":
        return payload.get("constraint_text", "")
    if mem_type == "thread_summary":
        return payload.get("summary", "")
    if mem_type == "atomic_fact":
        return payload.get("statement", "")
    if mem_type == "fact_summary":
        return payload.get("summary", "") or payload.get("consolidated_statement", "")
    return json.dumps(payload)[:300]


def get_following_context(thread_items: list[dict], query_time: str, n_turns: int = 4) -> str:
    """Get the next N turns after a query timestamp."""
    following = []
    found_start = False
    for item in thread_items:
        if not found_start:
            if item["created_at"] >= query_time:
                found_start = True
            continue
        following.append(f"[{item['role']}]: {item['content'][:300]}")
        if len(following) >= n_turns:
            break
    return "\n".join(following) if following else "(no following context available)"


def get_thread_position(thread_items: list[dict], query_time: str) -> int:
    """Get the position (item count) in the thread at query time."""
    count = 0
    for item in thread_items:
        if item["created_at"] >= query_time:
            break
        count += 1
    return count


def find_top_candidate(candidates_json: str, memory_content: dict) -> dict | None:
    """Find the top viable candidate from the suppressed query's candidates."""
    candidates = json.loads(candidates_json)
    sorted_cands = sorted(candidates, key=lambda x: x.get("routing_score", 0), reverse=True)

    for c in sorted_cands:
        if c.get("suppression_reason_code"):
            continue
        mem_id = c.get("memory_object_id", "")
        mem_type = c.get("memory_type")
        score = c.get("routing_score", 0)
        content = memory_content.get(mem_id, "")
        if not content and not mem_type:
            continue
        return {
            "memory_object_id": mem_id,
            "memory_type": mem_type or "source_hit",
            "routing_score": score,
            "content_preview": content[:400] if content else "(source evidence)",
        }
    return None


def classify_injection(
    query_text: str,
    candidate: dict,
    following_context: str,
    provider,
    cache: LLMCache,
    limiter: TokenBucketRateLimiter,
) -> dict | None:
    user_input = (
        f"USER MESSAGE: {query_text[:300]}\n\n"
        f"MEMORY BLOCK THAT WOULD HAVE BEEN INJECTED:\n"
        f"[{candidate['memory_type']}] {candidate['content_preview'][:400]}\n\n"
        f"WHAT HAPPENED NEXT IN THE CONVERSATION:\n{following_context[:800]}"
    )
    cache_key = _cache_key(user_input[:2000])

    cached = cache.get(cache_key)
    if cached:
        return cached

    try:
        limiter.acquire()
        response = provider.generate_json(
            system_prompt=CLASSIFY_SYSTEM,
            user_prompt=user_input,
            schema_description=CLASSIFY_SCHEMA,
        )
        result = response.parsed_json
        cache.put(cache_key, result)
        return result
    except Exception as e:
        print(f"    ERROR: {e}", file=sys.stderr)
        return None


def run_simulation(
    suppressed: list[dict],
    thread_items: dict[str, list[dict]],
    memory_content: dict[str, str],
    provider,
    cache: LLMCache,
    limiter: TokenBucketRateLimiter,
    thresholds: list[int],
    verbose: bool = False,
) -> dict:
    results_by_threshold: dict[int, list[dict]] = {t: [] for t in thresholds}
    errors = 0

    for i, query in enumerate(suppressed):
        if i % 20 == 0:
            print(f"  Processing {i}/{len(suppressed)}...", file=sys.stderr)

        thread = query["thread_ref"]
        items = thread_items.get(thread, [])
        position = get_thread_position(items, query["created_at"])

        candidate = find_top_candidate(query["candidate_scores_json"], memory_content)
        if not candidate:
            continue

        following = get_following_context(items, query["created_at"])

        classification = classify_injection(
            query["query_text"] or "",
            candidate,
            following,
            provider,
            cache,
            limiter,
        )
        if classification is None:
            errors += 1
            continue

        result = {
            "thread_ref": thread,
            "position": position,
            "query_text": (query["query_text"] or "")[:100],
            "candidate_type": candidate["memory_type"],
            "candidate_score": candidate["routing_score"],
            "classification": classification.get("classification", "unknown"),
            "confidence": classification.get("confidence", 0),
            "brief_reason": classification.get("brief_reason", ""),
        }

        for threshold in thresholds:
            if position >= threshold:
                results_by_threshold[threshold].append(result)

        if verbose and classification.get("classification") == "noise":
            print(f"    NOISE: \"{query['query_text'][:60]}\" -> [{candidate['memory_type']}]", file=sys.stderr)

    return {
        "results_by_threshold": {str(t): r for t, r in results_by_threshold.items()},
        "total_suppressed": len(suppressed),
        "errors": errors,
    }


def print_report(simulation: dict, thresholds: list[int]):
    print("\n=== Injection Replay Simulation ===\n")
    print(f"Total suppressed queries analyzed: {simulation['total_suppressed']}")
    print(f"Classification errors: {simulation['errors']}")

    print("\n--- Results by Threshold ---\n")
    print(f"{'Threshold':<12} {'Queries':<10} {'Helpful':<10} {'Reinforcing':<12} {'Redundant':<10} {'Noise':<8} {'Precision':<10}")
    print("-" * 72)

    for threshold in thresholds:
        results = simulation["results_by_threshold"].get(str(threshold), [])
        if not results:
            print(f"{threshold:<12} {'0':<10}")
            continue

        counts = defaultdict(int)
        for r in results:
            counts[r["classification"]] += 1

        total = len(results)
        helpful = counts.get("helpful", 0)
        reinforcing = counts.get("reinforcing", 0)
        redundant = counts.get("redundant", 0)
        noise = counts.get("noise", 0)
        precision = (helpful + reinforcing) * 100 // max(total, 1)

        print(f"{threshold:<12} {total:<10} {helpful:<10} {reinforcing:<12} {redundant:<10} {noise:<8} {precision}%")

    # Best threshold
    best_threshold = None
    best_precision = 0
    for threshold in thresholds:
        results = simulation["results_by_threshold"].get(str(threshold), [])
        if not results:
            continue
        counts = defaultdict(int)
        for r in results:
            counts[r["classification"]] += 1
        helpful = counts.get("helpful", 0) + counts.get("reinforcing", 0)
        total = len(results)
        precision = helpful * 100 // max(total, 1)
        if precision > best_precision or (precision == best_precision and total > 0):
            best_precision = precision
            best_threshold = threshold

    print(f"\n  Recommended threshold: {best_threshold} (precision={best_precision}%)")

    # Token savings estimate
    if best_threshold:
        results = simulation["results_by_threshold"].get(str(best_threshold), [])
        helpful_count = sum(1 for r in results if r["classification"] in ("helpful", "reinforcing"))
        noise_count = sum(1 for r in results if r["classification"] == "noise")
        # Each helpful injection prevents ~417 tokens of correction waste
        # Each noise injection costs ~200 tokens (injection block size)
        savings = helpful_count * 417 - noise_count * 200
        print(f"  Estimated net token savings: ~{savings:,} tokens")
        print(f"    Corrections prevented: {helpful_count} * 417 = ~{helpful_count * 417:,} saved")
        print(f"    Noise cost: {noise_count} * 200 = ~{noise_count * 200:,} wasted")

    # By memory type
    print("\n--- Injection Quality by Memory Type ---\n")
    type_stats = defaultdict(lambda: defaultdict(int))
    for threshold in thresholds:
        results = simulation["results_by_threshold"].get(str(thresholds[-1]), [])
        for r in results:
            type_stats[r["candidate_type"]][r["classification"]] += 1

    for mem_type, counts in sorted(type_stats.items(), key=lambda x: -sum(x[1].values())):
        total = sum(counts.values())
        helpful = counts.get("helpful", 0) + counts.get("reinforcing", 0)
        noise_ct = counts.get("noise", 0)
        print(f"  {mem_type}: {total} total, {helpful} useful ({helpful*100//max(total,1)}%), {noise_ct} noise")


def main():
    parser = argparse.ArgumentParser(description="Injection replay simulation")
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--rate-limit", type=int, default=20)
    parser.add_argument("--db-path", type=Path, default=DB_PATH)
    parser.add_argument("--thresholds", type=str, default="8,12,16,20,24",
                        help="Comma-separated turn count thresholds to test")
    args = parser.parse_args()

    thresholds = [int(t) for t in args.thresholds.split(",")]
    cache_path = args.cache_dir / "injection-replay" if args.cache_dir else None

    print("Loading config...", file=sys.stderr)
    config = AppConfig.from_env()

    print("Building Haiku provider...", file=sys.stderr)
    default_package = config.package_config(config.default_use_case)
    provider = build_llm_provider(
        config,
        provider_name=default_package.llm_provider,
        model="anthropic--claude-haiku-latest",
    )

    print(f"Loading suppressed queries from {args.db_path}...", file=sys.stderr)
    suppressed = load_suppressed_queries(args.db_path)
    print(f"  Found {len(suppressed)} suppressed queries", file=sys.stderr)

    print("Loading thread items...", file=sys.stderr)
    thread_items = load_thread_items(args.db_path)

    print("Loading memory content...", file=sys.stderr)
    memory_content = load_memory_content(args.db_path)
    print(f"  Loaded {len(memory_content)} memory objects", file=sys.stderr)

    cache = LLMCache(cache_path)
    limiter = TokenBucketRateLimiter(capacity=args.rate_limit, refill_interval=60.0 / args.rate_limit)

    print(f"Running simulation with thresholds {thresholds}...", file=sys.stderr)
    simulation = run_simulation(
        suppressed, thread_items, memory_content,
        provider, cache, limiter, thresholds,
        verbose=args.verbose,
    )

    RESULTS_PATH.write_text(json.dumps(simulation, indent=2, default=str), encoding="utf-8")
    print(f"\nRaw results saved to {RESULTS_PATH}", file=sys.stderr)

    print_report(simulation, thresholds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
