"""Prompt variant eval — focused comparison of fact extraction prompt variants.

Runs 4 small synthetic thread snippets against each prompt variant and checks
concrete assertions (date resolution, dedup, trivial filtering, dense facts).
~16 LLM calls total. Uses the LLM cache for instant re-runs.

Usage:
    python -m evals.prompt_variant_eval --cache-dir .local/llm-cache
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from app.config import AppConfig
from app.dependencies import build_llm_provider
from providers.llm.base import LLMProvider
from semantic.conversational_knowledge import (
    FACT_EXTRACTION_SYSTEM_PROMPT,
)


# ---------------------------------------------------------------------------
# Test snippets — entities intentionally differ from Variant C examples
# (which use Jordan, Denver, half-marathon, 2024-03-12).
# ---------------------------------------------------------------------------

SNIPPETS: list[dict[str, Any]] = [
    {
        "id": "date_resolution",
        "description": "Relative date -> absolute date conversion",
        "thread_text": (
            "Session date: 2023-08-28\n"
            "[user]: I took the kids to Riverside Park yesterday. It was great!\n"
            "[assistant]: That sounds wonderful! How old are your kids?\n"
            "[user]: Emma is 7 and Jake is 5. We also went there last Saturday."
        ),
        "assertions": {
            "must_contain_pattern": [
                r"2023-08-2[67]|2[67]\s*(August|Aug)|August\s*2[67]",
                r"2023-08-2[0-6]|2[0-6]\s*(August|Aug)|August\s*2[0-6]",
            ],
            "must_not_contain": ["yesterday", "last Saturday", "last saturday"],
            "must_contain_any": [["Emma", "7"], ["Jake", "5"]],
        },
    },
    {
        "id": "dedup_across_turns",
        "description": "Repeated info extracted once",
        "thread_text": (
            "Session date: 2023-09-15\n"
            "[user]: I work at the downtown library. Been there for 3 years.\n"
            "[assistant]: Nice! Do you enjoy it?\n"
            "[user]: Yeah, I love working at the library. My colleague Sarah started last month.\n"
            "[assistant]: That's great that you enjoy your work at the library."
        ),
        "assertions": {
            "max_facts": 4,
            "count_containing": {"library": 1},
            "must_contain_any": [["Sarah"]],
            "must_contain_pattern": [r"2023-08|August\s*2023"],
        },
    },
    {
        "id": "trivial_filtering",
        "description": "Greetings/filler not extracted as facts",
        "thread_text": (
            "Session date: 2023-10-01\n"
            "[user]: Hi there!\n"
            "[assistant]: Hello! How are you?\n"
            "[user]: Good, thanks. My daughter Lily just turned 12 last week. "
            "We had a birthday party at the bowling alley.\n"
            "[assistant]: Happy birthday to Lily! That sounds fun.\n"
            "[user]: Yeah it was great. She invited 8 friends."
        ),
        "assertions": {
            "must_contain_any": [["Lily", "12"], ["bowling"], ["8"]],
            "must_not_contain_as_fact": ["Hi there", "Hello", "Good, thanks"],
            "max_facts": 5,
        },
    },
    {
        "id": "dense_facts",
        "description": "Quality over quantity for fact-rich text",
        "thread_text": (
            "Session date: 2023-11-20\n"
            "[user]: We just moved to Portland from Chicago last month. "
            "My wife Maria got a job at Oregon Health Sciences University. "
            "We bought a house in the Pearl District.\n"
            "[assistant]: Congratulations on the move! How do you like Portland so far?\n"
            "[user]: It's great. The kids are adjusting well. Our dog Max loves the parks here."
        ),
        "assertions": {
            "must_contain_any": [
                ["Portland"],
                ["Chicago"],
                ["Maria"],
                ["Oregon Health", "OHSU"],
                ["Pearl District"],
                ["Max"],
            ],
            "min_must_contain_hits": 5,
            "max_facts": 8,
            "must_contain_pattern": [r"2023-10|October\s*2023"],
        },
    },
]


# ---------------------------------------------------------------------------
# Assertion checker
# ---------------------------------------------------------------------------


def check_assertions(
    facts: list[dict[str, Any]],
    assertions: dict[str, Any],
) -> list[dict[str, Any]]:
    """Check assertions against extracted facts.

    Returns a list of {assertion, passed, detail} dicts.
    """
    results: list[dict[str, Any]] = []
    all_statements = [str(f.get("statement", "")) for f in facts]

    # max_facts
    if "max_facts" in assertions:
        limit = assertions["max_facts"]
        passed = len(facts) <= limit
        results.append({
            "assertion": f"max_facts <= {limit}",
            "passed": passed,
            "detail": f"got {len(facts)} facts",
        })

    # must_contain_pattern — each pattern must match at least one statement
    for pattern in assertions.get("must_contain_pattern", []):
        regex = re.compile(pattern, re.IGNORECASE)
        matched = any(regex.search(stmt) for stmt in all_statements)
        results.append({
            "assertion": f"must_contain_pattern: {pattern[:60]}",
            "passed": matched,
            "detail": "matched" if matched else "no match in any statement",
        })

    # must_not_contain — literal substring absent from all statements
    for phrase in assertions.get("must_not_contain", []):
        found_in = [
            stmt for stmt in all_statements if phrase.lower() in stmt.lower()
        ]
        passed = len(found_in) == 0
        results.append({
            "assertion": f"must_not_contain: \"{phrase}\"",
            "passed": passed,
            "detail": "absent" if passed else f"found in: {found_in[0][:80]}",
        })

    # must_not_contain_as_fact — phrase not in any statement
    for phrase in assertions.get("must_not_contain_as_fact", []):
        found_in = [
            stmt for stmt in all_statements if phrase.lower() in stmt.lower()
        ]
        passed = len(found_in) == 0
        results.append({
            "assertion": f"must_not_contain_as_fact: \"{phrase}\"",
            "passed": passed,
            "detail": "absent" if passed else f"found in: {found_in[0][:80]}",
        })

    # must_contain_any — list of keyword groups; each group requires all
    # keywords present in the same statement
    keyword_groups = assertions.get("must_contain_any", [])
    min_hits = assertions.get("min_must_contain_hits", len(keyword_groups))
    hits = 0
    for group in keyword_groups:
        group_matched = any(
            all(kw.lower() in stmt.lower() for kw in group)
            for stmt in all_statements
        )
        if group_matched:
            hits += 1
        results.append({
            "assertion": f"must_contain_any: {group}",
            "passed": group_matched,
            "detail": "found" if group_matched else "not found",
        })
    if keyword_groups and "min_must_contain_hits" in assertions:
        results.append({
            "assertion": f"min_must_contain_hits >= {min_hits}",
            "passed": hits >= min_hits,
            "detail": f"{hits}/{len(keyword_groups)} keyword groups matched",
        })

    # count_containing — keyword appears in exactly N facts
    for keyword, expected_count in assertions.get("count_containing", {}).items():
        actual = sum(
            1 for stmt in all_statements if keyword.lower() in stmt.lower()
        )
        passed = actual == expected_count
        results.append({
            "assertion": f"count_containing(\"{keyword}\") == {expected_count}",
            "passed": passed,
            "detail": f"found in {actual} facts",
        })

    return results


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_eval(
    provider: LLMProvider,
    *,
    cache_dir: Path | None = None,
    prompt_variants: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run prompt variants against all snippets. Returns structured results.

    If prompt_variants is None, tests only the current FACT_EXTRACTION_SYSTEM_PROMPT.
    Pass a dict of {name: prompt_text} to compare multiple variants.
    """

    if cache_dir is not None:
        from providers.llm.cached import CachedLLMProvider
        provider = CachedLLMProvider(provider, cache_dir)

    variants = prompt_variants or {"current": FACT_EXTRACTION_SYSTEM_PROMPT}
    variant_results: dict[str, list[dict[str, Any]]] = {}

    schema_description = json.dumps(
        {"facts": [{"subject": "string", "statement": "string", "category": "string"}]},
        indent=2,
    )

    for variant_name, system_prompt in variants.items():
        snippet_results: list[dict[str, Any]] = []
        for snippet in SNIPPETS:
            response = provider.generate_json(
                system_prompt=system_prompt,
                user_prompt=snippet["thread_text"],
                schema_description=schema_description,
            )
            parsed = response.parsed_json
            facts = parsed.get("facts", [])
            if not isinstance(facts, list):
                facts = []
            facts = [f for f in facts if isinstance(f, dict) and f.get("statement")]
            assertion_results = check_assertions(facts, snippet["assertions"])
            passed_count = sum(1 for r in assertion_results if r["passed"])
            total_count = len(assertion_results)
            snippet_results.append({
                "snippet_id": snippet["id"],
                "description": snippet["description"],
                "fact_count": len(facts),
                "facts": facts,
                "assertions": assertion_results,
                "passed": passed_count,
                "total": total_count,
                "all_passed": passed_count == total_count,
            })
        variant_results[variant_name] = snippet_results

    return {
        "variants": variant_results,
        "prompt_word_counts": {
            name: len(prompt.split())
            for name, prompt in variants.items()
        },
    }


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------


def print_results(results: dict[str, Any]) -> None:
    """Print a comparison table and recommend a winner."""
    variants = results["variants"]
    word_counts = results["prompt_word_counts"]

    # Header
    print("\n" + "=" * 78)
    print("PROMPT VARIANT EVAL — COMPARISON TABLE")
    print("=" * 78)

    # Per-snippet detail
    for snippet in SNIPPETS:
        sid = snippet["id"]
        print(f"\n--- {sid}: {snippet['description']} ---")
        for variant_name, snippet_results in variants.items():
            sr = next(s for s in snippet_results if s["snippet_id"] == sid)
            status = "PASS" if sr["all_passed"] else "FAIL"
            print(
                f"  {variant_name:12s}  {status}  "
                f"{sr['passed']}/{sr['total']} assertions  "
                f"{sr['fact_count']} facts"
            )
            for ar in sr["assertions"]:
                mark = "OK" if ar["passed"] else "XX"
                print(f"    [{mark}] {ar['assertion']}  ({ar['detail']})")

    # Summary table
    print("\n" + "=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print(f"{'Variant':12s} {'Pass Rate':>10s} {'Avg Facts':>10s} {'Words':>8s}")
    print("-" * 44)

    best_variant = None
    best_pass_rate = -1.0

    for variant_name, snippet_results in variants.items():
        total_passed = sum(sr["passed"] for sr in snippet_results)
        total_assertions = sum(sr["total"] for sr in snippet_results)
        pass_rate = total_passed / total_assertions if total_assertions else 0
        avg_facts = (
            sum(sr["fact_count"] for sr in snippet_results) / len(snippet_results)
            if snippet_results
            else 0
        )
        words = word_counts.get(variant_name, 0)
        print(
            f"{variant_name:12s} {pass_rate:>9.0%} {avg_facts:>10.1f} {words:>8d}"
        )
        if pass_rate > best_pass_rate:
            best_pass_rate = pass_rate
            best_variant = variant_name

    print("-" * 44)

    # Recommendation
    if best_variant:
        tied = [
            name
            for name, srs in variants.items()
            if sum(sr["passed"] for sr in srs)
            == sum(sr["passed"] for sr in variants[best_variant])
        ]
        if len(tied) > 1:
            # Tie-break by avg fact count (fewer = more disciplined)
            best_variant = min(
                tied,
                key=lambda name: sum(
                    sr["fact_count"] for sr in variants[name]
                ),
            )
            print(
                f"\nTie between {tied}. Recommending '{best_variant}' "
                f"(fewest avg facts = more disciplined extraction)."
            )
        else:
            print(f"\nRecommended winner: '{best_variant}' (highest pass rate)")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run prompt variant eval for fact extraction."
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Directory for caching LLM calls (recommended).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write raw JSON results to this file.",
    )
    args = parser.parse_args()

    config = AppConfig.from_env()

    # Find the conversational_knowledge package config to get its provider.
    ck_config = None
    for pkg_name, pkg_config in config.semantic_packages.items():
        if pkg_config.implementation == "conversational_knowledge":
            ck_config = pkg_config
            break

    if ck_config is None or not ck_config.llm_provider or not ck_config.model:
        # Fall back to default use case provider.
        default_pkg = config.package_config(config.default_use_case)
        if not default_pkg.llm_provider or not default_pkg.model:
            print(
                "ERROR: No LLM provider configured for conversational_knowledge "
                "or the default use case."
            )
            return 1
        provider = build_llm_provider(
            config,
            provider_name=default_pkg.llm_provider,
            model=default_pkg.model,
        )
    else:
        provider = build_llm_provider(
            config,
            provider_name=ck_config.llm_provider,
            model=ck_config.model,
        )

    results = run_eval(provider, cache_dir=args.cache_dir)
    print_results(results)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        # Strip raw facts from output to keep file size reasonable
        slim = {
            "prompt_word_counts": results["prompt_word_counts"],
            "variants": {
                name: [
                    {k: v for k, v in sr.items() if k != "facts"}
                    for sr in srs
                ]
                for name, srs in results["variants"].items()
            },
        }
        args.output.write_text(json.dumps(slim, indent=2), encoding="utf-8")
        print(f"Results written to {args.output}")

    # Exit code: 0 if any variant passed all assertions, 1 otherwise
    any_perfect = any(
        all(sr["all_passed"] for sr in srs)
        for srs in results["variants"].values()
    )
    return 0 if any_perfect else 1


if __name__ == "__main__":
    raise SystemExit(main())
