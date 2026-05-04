"""Eval harness for note extraction prompt variants.

Tests prompt variants against a corpus of real explicit-ingest content.
Measures: title quality (conciseness, relevance to content).

Usage:
    python -m evals.note_extraction_eval
    python -m evals.note_extraction_eval --variant title_only --cache-dir .local/llm-cache
    python -m evals.note_extraction_eval --variant all
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import AppConfig
from app.dependencies import build_llm_provider
from providers.llm.base import LLMProvider

sys.stdout.reconfigure(encoding="utf-8")

CORPUS_FILE = Path(__file__).parent / "note_extraction_corpus.json"


# ---------------------------------------------------------------------------
# Prompt variants — the harness supports multiple for iteration
# ---------------------------------------------------------------------------

PROMPT_VARIANTS: dict[str, str] = {
    "title_only": (
        "Extract a concise title (1 sentence, max 15 words) that describes what this note is about.\n"
        "The title should work as a heading — someone scanning a list of notes should immediately "
        "know what this one contains.\n\n"
        "Do NOT paraphrase the content or add interpretation.\n"
        "Focus on the subject/topic, not on the fact that it was saved.\n\n"
        'Return JSON: {"title": "..."}'
    ),
    "title_and_topics": (
        "Extract metadata for this note that was explicitly saved by a user.\n\n"
        "1. title: A concise heading (max 15 words) — someone scanning a list of notes should "
        "immediately know what this one contains.\n"
        "2. topics: 1-5 topic keywords that characterize the content domain (e.g., \"sql\", "
        "\"deployment\", \"auth\", \"team-process\").\n\n"
        "Do NOT paraphrase the content or add interpretation.\n"
        "Focus on the subject/topic, not on the fact that it was saved.\n\n"
        'Return JSON: {"title": "...", "topics": ["..."]}'
    ),
}

SCHEMA_DESCRIPTIONS: dict[str, str] = {
    "title_only": '{"title": "string (max 15 words)"}',
    "title_and_topics": '{"title": "string (max 15 words)", "topics": ["string"]}',
}


# ---------------------------------------------------------------------------
# Evaluation data structures
# ---------------------------------------------------------------------------

@dataclass
class ItemResult:
    item_id: str
    category: str
    description: str
    title: str
    title_word_count: int
    title_within_limit: bool
    title_contains_expected: bool
    expected_terms: list[str]
    matched_terms: list[str]
    topics: list[str] | None
    raw_response: dict[str, Any]


@dataclass
class VariantSummary:
    variant_name: str
    total_items: int
    titles_within_limit: int
    titles_with_expected_terms: int
    avg_title_word_count: float
    items: list[ItemResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core evaluation logic
# ---------------------------------------------------------------------------

def load_corpus(path: Path = CORPUS_FILE) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def evaluate_item(
    item: dict[str, Any],
    *,
    provider: LLMProvider,
    variant_name: str,
) -> ItemResult:
    """Run extraction on a single corpus item and evaluate the result."""
    prompt = PROMPT_VARIANTS[variant_name]
    schema_desc = SCHEMA_DESCRIPTIONS[variant_name]
    content = item["content"]

    try:
        response = provider.generate_json(
            system_prompt=prompt,
            user_prompt=content,
            schema_description=schema_desc,
        )
        parsed = response.parsed_json
    except Exception as e:
        parsed = {"title": f"[ERROR: {e}]", "topics": []}

    title = (parsed.get("title") or "").strip()
    topics = parsed.get("topics")
    if topics and not isinstance(topics, list):
        topics = None

    # Evaluate title quality
    title_words = title.split()
    title_word_count = len(title_words)
    title_within_limit = title_word_count <= 15

    # Check if expected terms appear in title (case-insensitive)
    expected_terms = item.get("expected_title_contains", [])
    title_lower = title.lower()
    matched_terms = [term for term in expected_terms if term.lower() in title_lower]
    # Consider it a match if at least one expected term is found
    title_contains_expected = len(matched_terms) > 0 if expected_terms else True

    return ItemResult(
        item_id=item["id"],
        category=item.get("category", "unknown"),
        description=item["description"],
        title=title,
        title_word_count=title_word_count,
        title_within_limit=title_within_limit,
        title_contains_expected=title_contains_expected,
        expected_terms=expected_terms,
        matched_terms=matched_terms,
        topics=topics,
        raw_response=parsed,
    )


def run_variant(
    corpus: list[dict[str, Any]],
    *,
    provider: LLMProvider,
    variant_name: str,
    delay: float = 0.3,
) -> VariantSummary:
    """Run a single prompt variant against the entire corpus."""
    items: list[ItemResult] = []

    for i, item in enumerate(corpus):
        result = evaluate_item(item, provider=provider, variant_name=variant_name)
        items.append(result)

        status = "OK" if (result.title_within_limit and result.title_contains_expected) else "!!"
        print(
            f"  [{i+1}/{len(corpus)}] {status} "
            f"{result.item_id:25s} "
            f"title='{result.title[:50]}'"
        )
        if not result.title_contains_expected:
            print(f"         expected any of {result.expected_terms}, matched: {result.matched_terms}")

        if delay and i < len(corpus) - 1:
            time.sleep(delay)

    titles_within_limit = sum(1 for r in items if r.title_within_limit)
    titles_with_expected = sum(1 for r in items if r.title_contains_expected)
    avg_words = sum(r.title_word_count for r in items) / len(items) if items else 0

    return VariantSummary(
        variant_name=variant_name,
        total_items=len(items),
        titles_within_limit=titles_within_limit,
        titles_with_expected_terms=titles_with_expected,
        avg_title_word_count=avg_words,
        items=items,
    )


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def print_report(summaries: list[VariantSummary]) -> None:
    print("\n" + "=" * 78)
    print("NOTE EXTRACTION EVAL RESULTS")
    print("=" * 78)

    # Per-variant summary
    print(f"\n{'Variant':<25s} {'Items':>6s} {'<=15w':>6s} {'Terms':>6s} {'Avg wc':>8s}")
    print("-" * 55)
    for s in summaries:
        print(
            f"{s.variant_name:<25s} "
            f"{s.total_items:>6d} "
            f"{s.titles_within_limit:>6d} "
            f"{s.titles_with_expected_terms:>6d} "
            f"{s.avg_title_word_count:>8.1f}"
        )

    # Per-item detail for each variant
    for s in summaries:
        print(f"\n{'─' * 78}")
        print(f"VARIANT: {s.variant_name}")
        print(f"{'─' * 78}")
        for item in s.items:
            limit_ok = "OK" if item.title_within_limit else "LONG"
            terms_ok = "OK" if item.title_contains_expected else "MISS"
            print(
                f"  [{limit_ok:4s}] [{terms_ok:4s}] "
                f"{item.item_id:25s} "
                f"({item.title_word_count:2d}w) "
                f"'{item.title}'"
            )
            if item.topics:
                print(f"         topics: {item.topics}")

    print("\n" + "=" * 78)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run note extraction prompt eval against corpus."
    )
    parser.add_argument(
        "--variant",
        default="title_only",
        help="Prompt variant to test, or 'all' for all variants.",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Directory for caching LLM calls (speeds up repeated runs).",
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=CORPUS_FILE,
        help="Path to corpus JSON file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write raw JSON results to this file.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.3,
        help="Delay between LLM calls in seconds.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Override LLM model name (uses config default if not set).",
    )
    args = parser.parse_args()

    # Build LLM provider from config
    config = AppConfig.from_env()

    # Find agent_conversation_memory package for its provider config
    acm_config = None
    for _pkg_name, pkg_config in config.semantic_packages.items():
        if pkg_config.implementation == "agent_conversation_memory":
            acm_config = pkg_config
            break

    if acm_config is None or not acm_config.llm_provider or not acm_config.model:
        default_pkg = config.package_config(config.default_use_case)
        if not default_pkg.llm_provider or not default_pkg.model:
            print(
                "ERROR: No LLM provider configured for agent_conversation_memory "
                "or the default use case."
            )
            return 1
        provider_name = default_pkg.llm_provider
        model = args.model or default_pkg.model
    else:
        provider_name = acm_config.llm_provider
        model = args.model or acm_config.model

    provider: LLMProvider = build_llm_provider(config, provider_name=provider_name, model=model)

    if args.cache_dir:
        from providers.llm.cached import CachedLLMProvider
        provider = CachedLLMProvider(provider, args.cache_dir)

    # Select variants
    if args.variant == "all":
        variant_names = list(PROMPT_VARIANTS.keys())
    else:
        if args.variant not in PROMPT_VARIANTS:
            print(f"ERROR: Unknown variant '{args.variant}'. Available: {list(PROMPT_VARIANTS.keys())}")
            return 1
        variant_names = [args.variant]

    # Load corpus
    corpus = load_corpus(args.corpus)
    print(f"Loaded {len(corpus)} corpus items from {args.corpus}")

    # Run evaluation
    summaries: list[VariantSummary] = []
    for variant_name in variant_names:
        print(f"\nRunning variant: {variant_name}")
        summary = run_variant(corpus, provider=provider, variant_name=variant_name, delay=args.delay)
        summaries.append(summary)

    print_report(summaries)

    # Write JSON results if requested
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        output_data = {
            "variants": {
                s.variant_name: {
                    "total_items": s.total_items,
                    "titles_within_limit": s.titles_within_limit,
                    "titles_with_expected_terms": s.titles_with_expected_terms,
                    "avg_title_word_count": s.avg_title_word_count,
                    "items": [
                        {
                            "item_id": item.item_id,
                            "category": item.category,
                            "title": item.title,
                            "title_word_count": item.title_word_count,
                            "title_within_limit": item.title_within_limit,
                            "title_contains_expected": item.title_contains_expected,
                            "expected_terms": item.expected_terms,
                            "matched_terms": item.matched_terms,
                            "topics": item.topics,
                        }
                        for item in s.items
                    ],
                }
                for s in summaries
            },
        }
        args.output.write_text(json.dumps(output_data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nResults written to {args.output}")

    # Success if all titles are within limit and have expected terms for at least one variant
    any_variant_perfect = any(
        s.titles_within_limit == s.total_items and s.titles_with_expected_terms == s.total_items
        for s in summaries
    )
    # Relaxed: pass if >= 80% of items match expected terms
    any_variant_acceptable = any(
        s.titles_with_expected_terms >= s.total_items * 0.8
        for s in summaries
    )
    return 0 if (any_variant_perfect or any_variant_acceptable) else 1


if __name__ == "__main__":
    sys.exit(main())
