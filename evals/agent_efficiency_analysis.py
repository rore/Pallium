"""Agent efficiency analysis — classifies conversation messages using Haiku
to measure exploration, corrections, and off-track work across sessions.

Correlates with memory injection data to assess whether memory reduces agent work.

Usage:
    python -m evals.agent_efficiency_analysis --cache-dir .local/llm-cache
    python -m evals.agent_efficiency_analysis --cache-dir .local/llm-cache --verbose
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
RESULTS_PATH = Path(__file__).parent / "agent_efficiency_results.json"
CONTAINER_REF = "git:github.com/rore/pallium"


# ---------------------------------------------------------------------------
# LLM cache (same pattern as extraction_alternatives_eval)
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


def _cache_key(role: str, content: str) -> str:
    h = hashlib.sha256(content[:2000].encode(errors="replace")).hexdigest()[:16]
    return f"eff_{role}_{h}"


# ---------------------------------------------------------------------------
# Classification prompts
# ---------------------------------------------------------------------------

USER_CLASSIFY_SYSTEM = """\
You classify messages from a user talking to an AI coding assistant.
The user is a developer directing the AI to do tasks on a codebase.
Return exactly one JSON object.

Classify the message:
- is_correction: true if the user is correcting, redirecting, or expressing \
frustration at the assistant for doing the wrong thing, going off track, or \
not following instructions. Examples: "that's not what I asked", "wrong", \
"why did you do that", "you keep doing X", "stop", "no not that".
- is_re_explanation: true if the user is repeating information or instructions \
they already gave before in this conversation. Indicator: "I already told you", \
"we discussed this", "like I said".
- is_new_instruction: true if the user is giving a new task, direction, or request. \
This is the normal case for a developer directing work.
- is_feedback: true if the user is acknowledging, confirming, or giving brief \
positive/neutral feedback. Examples: "ok", "looks good", "yes", "thanks", "got it"."""

USER_CLASSIFY_SCHEMA = json.dumps({
    "is_correction": "boolean",
    "is_re_explanation": "boolean",
    "is_new_instruction": "boolean",
    "is_feedback": "boolean",
})

ASSISTANT_CLASSIFY_SYSTEM = """\
You classify messages from an AI coding assistant responding to a developer.
The assistant works on a codebase — reading files, making changes, running commands.
Return exactly one JSON object.

Classify the message:
- is_exploration: true if the assistant is reading, investigating, orienting, \
trying to understand the codebase or problem. Indicators: "let me read", \
"let me check", "looking at", "I need to understand", presenting analysis \
of existing code without making changes.
- is_constructive: true if the assistant is producing deliverable output — \
making edits, running commands that change state, presenting finished work, \
creating plans, writing code. Indicators: "Done", "Pushed", "Here's the \
implementation", code blocks that are new code being written.
- is_clarifying: true if the assistant is asking questions, presenting options, \
or requesting confirmation before proceeding.
- is_off_track: true if the assistant appears to be working on the wrong thing, \
has misunderstood the request, or is drifting from the stated task. Indicators: \
the content doesn't relate to what was just asked, the assistant is revisiting \
something already concluded, or analyzing something irrelevant."""

ASSISTANT_CLASSIFY_SCHEMA = json.dumps({
    "is_exploration": "boolean",
    "is_constructive": "boolean",
    "is_clarifying": "boolean",
    "is_off_track": "boolean",
})


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_source_items(db_path: Path) -> list[dict]:
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

    # Threads with injections
    cur.execute("""
        SELECT thread_ref,
               SUM(CASE WHEN should_inject = 1 THEN 1 ELSE 0 END) as injections,
               COUNT(*) as total_queries
        FROM query_audit_log
        WHERE thread_ref IS NOT NULL
        GROUP BY thread_ref
    """)
    thread_injections = {}
    for row in cur.fetchall():
        thread_injections[row[0]] = {"injections": row[1], "total_queries": row[2]}

    # Feedback per thread
    cur.execute("""
        SELECT qa.thread_ref, mf.rating, COUNT(*)
        FROM memory_feedback mf
        JOIN query_audit_log qa ON qa.id = mf.query_audit_log_id
        WHERE qa.thread_ref IS NOT NULL
        GROUP BY qa.thread_ref, mf.rating
    """)
    thread_feedback = defaultdict(lambda: {"relevant": 0, "not_relevant": 0})
    for row in cur.fetchall():
        if row[0] and row[1]:
            thread_feedback[row[0]][row[1]] = row[2]

    conn.close()
    return {"thread_injections": thread_injections, "thread_feedback": dict(thread_feedback)}


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_item(
    item: dict,
    provider,
    cache: LLMCache,
    limiter: TokenBucketRateLimiter,
) -> dict | None:
    content = item["content"][:2000]
    role = item["role"]
    cache_key = _cache_key(role, content)

    cached = cache.get(cache_key)
    if cached:
        return cached

    if role == "user":
        system_prompt = USER_CLASSIFY_SYSTEM
        schema = USER_CLASSIFY_SCHEMA
    else:
        system_prompt = ASSISTANT_CLASSIFY_SYSTEM
        schema = ASSISTANT_CLASSIFY_SCHEMA

    try:
        limiter.acquire()
        response = provider.generate_json(
            system_prompt=system_prompt,
            user_prompt=content,
            schema_description=schema,
        )
        result = response.parsed_json
        cache.put(cache_key, result)
        return result
    except Exception as e:
        return None


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def run_analysis(
    items: list[dict],
    injection_data: dict,
    provider,
    cache: LLMCache,
    limiter: TokenBucketRateLimiter,
    verbose: bool = False,
) -> dict:
    thread_stats = defaultdict(lambda: {
        "user_msgs": 0, "asst_msgs": 0, "total_tokens": 0,
        "user_corrections": 0, "user_re_explanations": 0,
        "user_new_instructions": 0, "user_feedback": 0,
        "asst_exploration": 0, "asst_constructive": 0,
        "asst_clarifying": 0, "asst_off_track": 0,
        "errors": 0,
    })

    total = len(items)
    errors = 0

    for i, item in enumerate(items):
        if i % 50 == 0:
            print(f"  Classifying {i}/{total}...", file=sys.stderr)

        thread = item["thread_ref"]
        role = item["role"]
        est_tokens = item["content_len"] // 4

        thread_stats[thread]["total_tokens"] += est_tokens

        classification = classify_item(item, provider, cache, limiter)
        if classification is None:
            errors += 1
            thread_stats[thread]["errors"] += 1
            continue

        if role == "user":
            thread_stats[thread]["user_msgs"] += 1
            if classification.get("is_correction"):
                thread_stats[thread]["user_corrections"] += 1
            if classification.get("is_re_explanation"):
                thread_stats[thread]["user_re_explanations"] += 1
            if classification.get("is_new_instruction"):
                thread_stats[thread]["user_new_instructions"] += 1
            if classification.get("is_feedback"):
                thread_stats[thread]["user_feedback"] += 1
        else:
            thread_stats[thread]["asst_msgs"] += 1
            if classification.get("is_exploration"):
                thread_stats[thread]["asst_exploration"] += 1
            if classification.get("is_constructive"):
                thread_stats[thread]["asst_constructive"] += 1
            if classification.get("is_clarifying"):
                thread_stats[thread]["asst_clarifying"] += 1
            if classification.get("is_off_track"):
                thread_stats[thread]["asst_off_track"] += 1

        if verbose and classification.get("is_correction"):
            print(f"    CORRECTION: {item['content'][:100]}", file=sys.stderr)
        if verbose and classification.get("is_off_track"):
            print(f"    OFF-TRACK: {item['content'][:100]}", file=sys.stderr)

    return {
        "thread_stats": dict(thread_stats),
        "injection_data": injection_data,
        "total_items": total,
        "total_errors": errors,
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_report(analysis: dict):
    thread_stats = analysis["thread_stats"]
    injection_data = analysis["injection_data"]
    thread_injections = injection_data["thread_injections"]

    # Aggregate totals
    totals = {
        "user_msgs": 0, "asst_msgs": 0, "total_tokens": 0,
        "user_corrections": 0, "user_re_explanations": 0,
        "user_new_instructions": 0, "user_feedback": 0,
        "asst_exploration": 0, "asst_constructive": 0,
        "asst_clarifying": 0, "asst_off_track": 0,
    }
    for stats in thread_stats.values():
        for k in totals:
            totals[k] += stats[k]

    total_msgs = totals["user_msgs"] + totals["asst_msgs"]

    print("\n=== Agent Efficiency Analysis ===\n")
    print(f"Total sessions: {len(thread_stats)}")
    print(f"Total messages analyzed: {total_msgs}")
    print(f"Total estimated tokens: ~{totals['total_tokens']:,}")
    print(f"Classification errors: {analysis['total_errors']}")

    # User message breakdown
    print("\n--- User Message Classification ---")
    um = totals["user_msgs"] or 1
    print(f"  New instructions: {totals['user_new_instructions']} ({totals['user_new_instructions']*100//um}%)")
    print(f"  Feedback/acknowledgment: {totals['user_feedback']} ({totals['user_feedback']*100//um}%)")
    print(f"  Corrections/redirections: {totals['user_corrections']} ({totals['user_corrections']*100//um}%)")
    print(f"  Re-explanations: {totals['user_re_explanations']} ({totals['user_re_explanations']*100//um}%)")

    # Assistant message breakdown
    print("\n--- Assistant Message Classification ---")
    am = totals["asst_msgs"] or 1
    print(f"  Constructive output: {totals['asst_constructive']} ({totals['asst_constructive']*100//am}%)")
    print(f"  Exploration/orientation: {totals['asst_exploration']} ({totals['asst_exploration']*100//am}%)")
    print(f"  Clarifying/asking: {totals['asst_clarifying']} ({totals['asst_clarifying']*100//am}%)")
    print(f"  Off-track work: {totals['asst_off_track']} ({totals['asst_off_track']*100//am}%)")

    # Efficiency metrics
    print("\n--- Efficiency Metrics ---")
    print(f"  Correction rate: {totals['user_corrections']*100/um:.1f}% (corrections / user messages)")
    print(f"  Exploration ratio: {totals['asst_exploration']*100/am:.1f}% (exploration / assistant messages)")
    print(f"  Off-track rate: {totals['asst_off_track']*100/am:.1f}% (off-track / assistant messages)")

    # Memory correlation
    with_memory = []
    without_memory = []
    for thread, stats in thread_stats.items():
        inj = thread_injections.get(thread, {})
        if inj.get("injections", 0) > 0:
            with_memory.append(stats)
        else:
            without_memory.append(stats)

    print(f"\n--- Memory Correlation ---")
    for label, group in [("WITH memory injection", with_memory), ("WITHOUT memory injection", without_memory)]:
        if not group:
            print(f"  {label}: no sessions")
            continue
        n = len(group)
        avg_corrections = sum(s["user_corrections"] for s in group) / sum(max(s["user_msgs"], 1) for s in group) * 100
        avg_exploration = sum(s["asst_exploration"] for s in group) / sum(max(s["asst_msgs"], 1) for s in group) * 100
        avg_off_track = sum(s["asst_off_track"] for s in group) / sum(max(s["asst_msgs"], 1) for s in group) * 100
        avg_tokens = sum(s["total_tokens"] for s in group) / n
        print(f"  {label} ({n} sessions):")
        print(f"    Avg correction rate: {avg_corrections:.1f}%")
        print(f"    Avg exploration ratio: {avg_exploration:.1f}%")
        print(f"    Avg off-track rate: {avg_off_track:.1f}%")
        print(f"    Avg tokens per session: {avg_tokens:,.0f}")

    # Per-session breakdown (top 10 by cost)
    print(f"\n--- Per-Session Breakdown (top 10 by cost) ---")
    sorted_threads = sorted(thread_stats.items(), key=lambda x: x[1]["total_tokens"], reverse=True)
    for thread, stats in sorted_threads[:10]:
        um_t = max(stats["user_msgs"], 1)
        am_t = max(stats["asst_msgs"], 1)
        corr = stats["user_corrections"] * 100 // um_t
        expl = stats["asst_exploration"] * 100 // am_t
        offt = stats["asst_off_track"] * 100 // am_t
        has_mem = "MEM" if thread_injections.get(thread, {}).get("injections", 0) > 0 else "   "
        print(f"  [{has_mem}] {thread[:8]}: ~{stats['total_tokens']:,} tok | "
              f"{corr}% corrections | {expl}% exploration | {offt}% off-track")

    # Wasted token estimate
    print(f"\n--- Wasted Token Estimate ---")
    # Estimate: off-track assistant messages waste their full token content
    # Corrections cause ~2 turns of waste (correction + redo)
    off_track_tokens = 0
    exploration_tokens = 0
    correction_tokens = 0
    for thread, stats in thread_stats.items():
        if stats["asst_msgs"] > 0:
            avg_asst_tokens = stats["total_tokens"] * 0.85 / stats["asst_msgs"]  # ~85% is assistant
            off_track_tokens += int(stats["asst_off_track"] * avg_asst_tokens)
            exploration_tokens += int(stats["asst_exploration"] * avg_asst_tokens)
        if stats["user_msgs"] > 0:
            avg_turn_tokens = stats["total_tokens"] / (stats["user_msgs"] + stats["asst_msgs"])
            correction_tokens += int(stats["user_corrections"] * avg_turn_tokens * 2)

    print(f"  Tokens on off-track work: ~{off_track_tokens:,} ({off_track_tokens*100//max(totals['total_tokens'],1)}% of total)")
    print(f"  Tokens on exploration: ~{exploration_tokens:,} ({exploration_tokens*100//max(totals['total_tokens'],1)}% of total)")
    print(f"  Tokens on correction cycles: ~{correction_tokens:,} ({correction_tokens*100//max(totals['total_tokens'],1)}% of total)")
    print(f"  Combined waste estimate: ~{off_track_tokens + correction_tokens:,} tokens")
    print(f"  (Exploration is not necessarily waste — included for reference)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Agent efficiency analysis via Haiku classification")
    parser.add_argument("--cache-dir", type=Path, default=None, help="LLM response cache directory")
    parser.add_argument("--verbose", action="store_true", help="Print individual corrections/off-track items")
    parser.add_argument("--rate-limit", type=int, default=20, help="Requests per minute (default: 20)")
    parser.add_argument("--db-path", type=Path, default=DB_PATH, help="Path to pallium.db")
    args = parser.parse_args()

    cache_path = args.cache_dir / "efficiency-analysis" if args.cache_dir else None

    print("Loading config...", file=sys.stderr)
    config = AppConfig.from_env()

    print("Building Haiku provider...", file=sys.stderr)
    default_package = config.package_config(config.default_use_case)
    provider = build_llm_provider(
        config,
        provider_name=default_package.llm_provider,
        model="anthropic--claude-haiku-latest",
    )

    print(f"Loading source items from {args.db_path}...", file=sys.stderr)
    items = load_source_items(args.db_path)
    print(f"  Loaded {len(items)} items across {len(set(i['thread_ref'] for i in items))} threads", file=sys.stderr)

    print("Loading injection data...", file=sys.stderr)
    injection_data = load_injection_data(args.db_path)

    cache = LLMCache(cache_path)
    limiter = TokenBucketRateLimiter(capacity=args.rate_limit, refill_interval=60.0 / args.rate_limit)

    print("Running classification...", file=sys.stderr)
    analysis = run_analysis(items, injection_data, provider, cache, limiter, verbose=args.verbose)

    # Save raw results
    RESULTS_PATH.write_text(json.dumps(analysis, indent=2, default=str), encoding="utf-8")
    print(f"\nRaw results saved to {RESULTS_PATH}", file=sys.stderr)

    # Print report
    print_report(analysis)

    return 0


if __name__ == "__main__":
    sys.exit(main())
