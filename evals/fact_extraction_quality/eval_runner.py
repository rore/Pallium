"""Eval runner for fact extraction quality.

Re-runs fact extraction on source chunks with different prompt variants,
then scores each extracted fact against the reference annotations.

Metrics:
  - noise_rate: % of extracted facts classified as noise
  - precision: % of extracted facts that are good (1 - noise_rate)
  - volume: total facts extracted (lower is better if precision holds)

Usage:
  python -m evals.fact_extraction_quality.eval_runner --variant baseline
  python -m evals.fact_extraction_quality.eval_runner --variant durability
  python -m evals.fact_extraction_quality.eval_runner --variant extract_only
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from evals.fact_extraction_quality.build_corpus import classify_fact
from providers.llm.base import LLMProvider
from semantic.conversational_knowledge import FACT_EXTRACTION_SYSTEM_PROMPT, FACT_EXTRACTION_SCHEMA_DESCRIPTION

EVAL_DIR = Path(__file__).parent
CHUNKS_PATH = EVAL_DIR / "source_chunks.jsonl"


# ══════════════════════════════════════════════════════════════════════════
# Prompt variants to test
# ══════════════════════════════════════════════════════════════════════════

PROMPT_VARIANTS: dict[str, str] = {}

# Baseline: current production prompt (from conversational_knowledge.py)
PROMPT_VARIANTS["baseline"] = FACT_EXTRACTION_SYSTEM_PROMPT

# Variant: Durability heuristic — single principle replaces SKIP list
PROMPT_VARIANTS["durability"] = (
    "Extract specific, atomic facts from the conversation below. "
    "Record what participants stated, not what is objectively true — if a statement contradicts common knowledge or a prior fact, still extract it. "
    "Each fact should answer a possible future question about these people, places, events, or preferences. "
    "Each statement must be self-contained and explicitly name its subject; do not return subjectless predicate fragments. "
    "\n\n"
    "DURABILITY RULE (apply to every candidate fact):\n"
    "Only extract facts that will still be true and useful 30 days from now. "
    "If it describes something that will change with the next code commit, conversation, session, or deployment — do not extract it.\n\n"
    "DURABLE (extract):\n"
    "- Root cause analysis: WHY something broke or behaved unexpectedly\n"
    "- System behavior discoveries: how a component actually works under specific conditions\n"
    "- Architectural constraints: what cannot be done and why\n"
    "- Durable configuration truths: what flag/setting controls what behavior and why it was chosen\n"
    "- Personal facts: names, relationships, preferences, significant events\n"
    "- Stated commitments: decisions that were made and implemented\n"
    "\n"
    "EPHEMERAL (never extract):\n"
    "- Implementation narration: what was built, fixed, deployed, committed, renamed, or pushed\n"
    "- Plans and proposals: task breakdowns, improvement plans, recommended approaches not yet proven\n"
    "- Test/eval results: pass counts, scores, benchmark numbers\n"
    "- Runtime state: port numbers, PIDs, memory usage, process counts, disk sizes\n"
    "- Git state: commit hashes, push confirmations, branch status\n"
    "- UI/asset descriptions: layout details, file sizes, pixel dimensions, color values\n"
    "- Session progress: what was checked off, debugging steps taken, options considered\n"
    "- Prescriptive statements: 'should be X', 'needs to Y' (unless stating a discovered constraint)\n"
    "\n"
    "SPECIFICITY: Preserve proper nouns, qualifying details, activity specifics. "
    "Never produce a vague version alongside a specific one. "
    "If the same fact is mentioned multiple times, extract it once in its most specific form. "
    "Resolve relative dates using the session date.\n"
    "\n"
    "Return JSON with key 'facts' containing up to 20 items. "
    "Each: subject (string), statement (string), category (personal | event | preference | relationship | activity). "
    "Prioritize facts with names, dates, numbers, or specific details. "
    "If no extractable facts, return {\"facts\": []}. "
    "\n"
    "LANGUAGE: Write statements in the same language as the conversation. Do not translate."
)

# Variant: Extract-only (no SKIP list, just positive extraction categories)
PROMPT_VARIANTS["extract_only"] = (
    "Extract specific, atomic facts from the conversation below. "
    "Record what participants stated, not what is objectively true. "
    "Each fact should answer a possible future question about these people, systems, events, or preferences. "
    "Each statement must be self-contained and explicitly name its subject.\n\n"
    "ONLY extract facts in these categories:\n"
    "1. ROOT CAUSES — why something broke or behaved unexpectedly\n"
    "2. SYSTEM BEHAVIOR — how a component actually works under specific conditions\n"
    "3. ARCHITECTURAL CONSTRAINTS — what cannot be done and why\n"
    "4. DURABLE CONFIGURATION — what setting/flag controls what behavior\n"
    "5. PERSONAL FACTS — names, relationships, preferences, significant life events\n"
    "6. COMMITTED DECISIONS — choices that were made AND implemented (not proposals)\n"
    "\n"
    "Do NOT extract anything else. In particular, skip:\n"
    "- What was built/fixed/deployed/committed (implementation narration)\n"
    "- Plans, tasks, proposals, recommendations\n"
    "- Test results, eval scores, benchmarks\n"
    "- Runtime state, git state, process info\n"
    "- UI descriptions, asset details\n"
    "\n"
    "SPECIFICITY: Preserve proper nouns, qualifying details. "
    "Extract once in most specific form. "
    "Resolve relative dates using the session date.\n\n"
    "Return JSON with key 'facts' containing up to 20 items. "
    "Each: subject (string), statement (string), category (personal | event | preference | relationship | activity). "
    "If no extractable facts, return {\"facts\": []}. "
    "\n"
    "LANGUAGE: Write statements in the same language as the conversation. Do not translate."
)

# Variant: Baseline with stronger negative examples
PROMPT_VARIANTS["baseline_reinforced"] = FACT_EXTRACTION_SYSTEM_PROMPT + (
    "\n\n"
    "ADDITIONAL REMINDERS — common mistakes to avoid:\n"
    "- 'X was renamed to Y' → SKIP (implementation narration)\n"
    "- 'Task N was completed' → SKIP (session progress)\n"
    "- 'Plan includes/creates/defers X' → SKIP (plan detail)\n"
    "- 'Recommended approach is X' → SKIP (assistant recommendation)\n"
    "- 'X should be Y' without explaining WHY → SKIP (prescriptive)\n"
    "- 'Improvement targets N% of X' → SKIP (plan metric)\n"
    "- 'All N tests pass' → SKIP (test result)\n"
    "- 'X now does Y' describing a code change → SKIP (implementation)\n"
    "Apply the SKIP rules strictly. When in doubt, do NOT extract."
)


def load_chunks(max_chunks: int | None = None) -> list[dict]:
    chunks = []
    with open(CHUNKS_PATH, encoding="utf-8") as f:
        for line in f:
            chunks.append(json.loads(line))
            if max_chunks and len(chunks) >= max_chunks:
                break
    return chunks


def extract_facts_with_prompt(
    provider: LLMProvider,
    prompt_variant: str,
    chunk_text: str,
    existing_facts: list[dict] | None = None,
) -> list[dict]:
    """Run fact extraction with a specific prompt variant.

    When existing_facts is provided, prepends them to simulate production
    conditions where the LLM sees prior extractions.
    """
    system_prompt = PROMPT_VARIANTS[prompt_variant]
    user_prompt = chunk_text
    if existing_facts:
        existing_lines = "\n".join(
            f"- {f.get('subject', '')}: {f.get('statement', '')}"
            for f in existing_facts[-40:]
        )
        user_prompt = (
            f"IMPORTANT: Only extract facts that are genuinely new and durable. "
            f"If the conversation below contains no new extractable facts beyond what is already known, "
            f"return {{\"facts\": []}}. Do NOT lower your quality bar to produce output.\n\n"
            f"Previously extracted facts (do NOT re-extract these):\n"
            f"{existing_lines}\n\n"
            f"New conversation messages:\n"
            f"{chunk_text}"
        )
    response = provider.generate_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        schema_description=FACT_EXTRACTION_SCHEMA_DESCRIPTION,
    )
    raw_facts = response.parsed_json.get("facts", [])
    if not isinstance(raw_facts, list):
        return []
    return [f for f in raw_facts if isinstance(f, dict) and f.get("statement")]


def score_extraction(extracted_facts: list[dict]) -> dict:
    """Score extracted facts against noise classifier."""
    total = len(extracted_facts)
    if total == 0:
        return {"total": 0, "noise": 0, "good": 0, "noise_rate": 0.0, "precision": 1.0}

    noise = 0
    noise_reasons: dict[str, int] = {}
    for fact in extracted_facts:
        judgment, reason = classify_fact(fact.get("statement", ""))
        if judgment == "noise":
            noise += 1
            noise_reasons[reason or "unknown"] = noise_reasons.get(reason or "unknown", 0) + 1

    good = total - noise
    return {
        "total": total,
        "noise": noise,
        "good": good,
        "noise_rate": noise / total,
        "precision": good / total,
        "noise_reasons": noise_reasons,
    }


def load_existing_facts_from_db(thread_ref: str | None = None) -> list[dict]:
    """Load real production facts from the DB for existing_facts simulation."""
    import sqlite3
    db_path = Path(os.environ.get("PALLIUM_DB", r"C:\Users\I347041\.pallium\data\pallium.db"))
    if not db_path.exists():
        return []
    db = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row
    if thread_ref:
        rows = db.execute("""
            SELECT payload_json FROM memory_objects
            WHERE type = 'atomic_fact' AND lifecycle = 'active'
            AND json_extract(payload_json, '$.thread_ref') = ?
            ORDER BY created_at
        """, (thread_ref,)).fetchall()
    else:
        rows = db.execute("""
            SELECT payload_json FROM memory_objects
            WHERE type = 'atomic_fact' AND lifecycle = 'active'
            ORDER BY created_at
            LIMIT 100
        """).fetchall()
    db.close()
    facts = []
    for row in rows:
        payload = json.loads(row["payload_json"])
        facts.append({
            "subject": payload.get("subject", ""),
            "statement": payload.get("statement", ""),
            "category": payload.get("category", ""),
        })
    return facts


def run_eval(variant: str, max_chunks: int | None = None, verbose: bool = False,
             with_existing_facts: bool = False, existing_facts_count: int | None = None):
    """Run the full evaluation for a prompt variant.

    Args:
        existing_facts_count: When set, controls how many existing facts are passed
            to the LLM. Tests the "pressure effect" — does having N prior facts
            push the model into lower-quality extraction? Defaults to all available
            when with_existing_facts is True.
    """
    from app.config import AppConfig
    from app.dependencies import build_llm_provider

    config = AppConfig.from_env()
    package_config = config.semantic_packages.get("conversational_knowledge")
    if package_config and package_config.llm_provider and package_config.model:
        provider = build_llm_provider(
            config,
            provider_name=package_config.llm_provider,
            model=package_config.model,
        )
    else:
        for pkg_name, pkg_config in config.semantic_packages.items():
            if pkg_config.llm_provider and pkg_config.model:
                provider = build_llm_provider(config, provider_name=pkg_config.llm_provider, model=pkg_config.model)
                break
        else:
            raise RuntimeError("No LLM provider configured")

    chunks = load_chunks(max_chunks)
    print(f"Running variant '{variant}' on {len(chunks)} chunks...")
    print(f"Prompt length: {len(PROMPT_VARIANTS[variant])} chars")
    if with_existing_facts:
        cap_desc = f", capped at {existing_facts_count}" if existing_facts_count else " (all available)"
        print(f"  (simulating production: existing_facts context enabled{cap_desc})")
    print()

    # Pre-load existing facts per thread if simulating production
    thread_facts_cache: dict[str, list[dict]] = {}
    if with_existing_facts:
        for chunk in chunks:
            tr = chunk.get("thread_ref")
            if tr and tr not in thread_facts_cache:
                all_facts = load_existing_facts_from_db(tr)
                if existing_facts_count is not None:
                    all_facts = all_facts[-existing_facts_count:]
                thread_facts_cache[tr] = all_facts

    all_extracted: list[dict] = []
    chunk_scores: list[dict] = []

    for i, chunk in enumerate(chunks):
        chunk_text = chunk["chunk_text"]
        existing = thread_facts_cache.get(chunk.get("thread_ref", "")) if with_existing_facts else None
        try:
            facts = extract_facts_with_prompt(provider, variant, chunk_text, existing_facts=existing)
        except Exception as e:
            print(f"  ERROR on chunk {chunk['chunk_id']}: {e}")
            continue

        score = score_extraction(facts)
        chunk_scores.append(score)
        all_extracted.extend(facts)

        if verbose:
            print(f"  {chunk['chunk_id']}: {score['total']} facts, {score['noise']} noise ({score['noise_rate']:.0%})")
            if score["noise"] > 0:
                for fact in facts:
                    j, r = classify_fact(fact.get("statement", ""))
                    if j == "noise":
                        print(f"    NOISE [{r}]: {fact.get('statement', '')[:90]}")

        # Progress
        if (i + 1) % 10 == 0:
            running_total = sum(s["total"] for s in chunk_scores)
            running_noise = sum(s["noise"] for s in chunk_scores)
            print(f"  ... {i+1}/{len(chunks)} chunks, {running_total} facts, noise rate: {running_noise/max(running_total,1):.1%}")

    # Aggregate scores
    total_facts = sum(s["total"] for s in chunk_scores)
    total_noise = sum(s["noise"] for s in chunk_scores)
    total_good = sum(s["good"] for s in chunk_scores)

    all_noise_reasons: dict[str, int] = {}
    for s in chunk_scores:
        for reason, count in s.get("noise_reasons", {}).items():
            all_noise_reasons[reason] = all_noise_reasons.get(reason, 0) + count

    print()
    print(f"{'='*60}")
    print(f"RESULTS: variant='{variant}'")
    print(f"{'='*60}")
    print(f"  Chunks processed: {len(chunk_scores)}")
    print(f"  Total facts extracted: {total_facts}")
    print(f"  Good facts: {total_good}")
    print(f"  Noise facts: {total_noise}")
    print(f"  Noise rate: {total_noise/max(total_facts,1):.1%}")
    print(f"  Precision: {total_good/max(total_facts,1):.1%}")
    print(f"  Avg facts/chunk: {total_facts/max(len(chunk_scores),1):.1f}")
    print()
    if all_noise_reasons:
        print("  Noise breakdown:")
        for reason, count in sorted(all_noise_reasons.items(), key=lambda x: -x[1]):
            print(f"    {reason:35s} {count}")

    # Write results
    results_path = EVAL_DIR / f"results_{variant}.json"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump({
            "variant": variant,
            "chunks_processed": len(chunk_scores),
            "total_facts": total_facts,
            "good_facts": total_good,
            "noise_facts": total_noise,
            "noise_rate": total_noise / max(total_facts, 1),
            "precision": total_good / max(total_facts, 1),
            "avg_facts_per_chunk": total_facts / max(len(chunk_scores), 1),
            "noise_reasons": all_noise_reasons,
            "per_chunk": chunk_scores,
        }, f, indent=2)
    print(f"\n  Results written to: {results_path}")

    return total_noise / max(total_facts, 1)


def main():
    parser = argparse.ArgumentParser(description="Fact extraction quality eval")
    parser.add_argument("--variant", required=True, choices=list(PROMPT_VARIANTS.keys()))
    parser.add_argument("--max-chunks", type=int, default=None, help="Limit chunks for quick test")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--with-existing-facts", action="store_true",
                        help="Simulate production by prepending real existing facts from DB")
    parser.add_argument("--existing-facts-count", type=int, default=None,
                        help="Cap existing facts to N most recent (tests pressure effect)")
    args = parser.parse_args()

    run_eval(args.variant, max_chunks=args.max_chunks, verbose=args.verbose,
             with_existing_facts=args.with_existing_facts,
             existing_facts_count=args.existing_facts_count)


if __name__ == "__main__":
    main()
