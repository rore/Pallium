"""Turn summary substance eval.

Measures whether the write extraction prompt correctly classifies
source items as low-value meta (operational noise) vs. substantive
(worth retaining as turn_summary memory).

Categories:
  NOISE    — commands, bug reports, questions, completion confirmations (should be is_low_value_meta=true)
  GOOD     — root cause analysis, architectural findings, constraints (must NOT be is_low_value_meta)
  BOUNDARY — completion reports WITH durable design choices (must NOT be is_low_value_meta)

Usage:
    python -m evals.turn_summary_substance_eval
    python -m evals.turn_summary_substance_eval --verbose
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from app.config import AppConfig
from app.dependencies import build_llm_provider
from providers.llm.base import LLMProvider, LLMJsonResponse
from semantic.llm_agent_memory import (
    PROMPT_VARIANTS,
    SCHEMA_DESCRIPTION,
    DEFAULT_PROMPT_VARIANT,
)


# ── Fixtures ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FixtureItem:
    category: str  # "noise", "good", "boundary"
    label: str
    content: str
    role: str  # "user" or "assistant"
    # For good/boundary: keywords that MUST appear in the summary
    required_keywords: list[str] | None = None
    min_keywords: int | None = None


NOISE_FIXTURES = [
    FixtureItem(
        category="noise",
        label="user_command_short",
        content="do an architect review",
        role="user",
    ),
    FixtureItem(
        category="noise",
        label="user_bug_report_no_insight",
        content="still says discussion summary",
        role="user",
    ),
    FixtureItem(
        category="noise",
        label="user_question_no_answer",
        content="did you migrate the db in the user data dir?",
        role="user",
    ),
    FixtureItem(
        category="noise",
        label="assistant_completion_no_knowledge",
        content="Done. Logo converted from RGB to transparent.",
        role="assistant",
    ),
    FixtureItem(
        category="noise",
        label="assistant_completion_operational_config",
        content="Done. The log now rotates at 5MB with 5 backups (max ~30MB)",
        role="assistant",
    ),
]

GOOD_FIXTURES = [
    FixtureItem(
        category="good",
        label="root_cause_analysis",
        content=(
            "The generic problem is: completion confirmations are being misread as "
            "decisions. The model sees 'rename + threshold + prompt...' and treats it "
            "as a choice, not a report. This class includes git pushes, deployments, "
            "test run completions."
        ),
        role="assistant",
        required_keywords=["completion", "confirmation", "decision"],
        min_keywords=2,
    ),
    FixtureItem(
        category="good",
        label="architectural_finding",
        content=(
            "claim_next_source_item only checks source_items status column and had "
            "no awareness of the package table. SQL race condition fix: NOT EXISTS "
            "subquery added to legacy claim SQL to skip items with active package rows"
        ),
        role="assistant",
        required_keywords=["claim_next_source_item", "race condition", "NOT EXISTS"],
        min_keywords=2,
    ),
    FixtureItem(
        category="good",
        label="user_constraint",
        content="first, i don't want us to add any new llm request",
        role="user",
        # This should produce constraint_text, not just a summary
        required_keywords=["llm", "request"],
        min_keywords=1,
    ),
]

BOUNDARY_FIXTURES = [
    FixtureItem(
        category="boundary",
        label="completion_with_design_choice",
        content=(
            "Done. Switched to FTS5 for lexical search. The old full-scan approach "
            "was O(N) per query — now we get inverted-index lookup with BM25 scoring."
        ),
        role="assistant",
        required_keywords=["FTS5", "lexical", "BM25"],
        min_keywords=2,
    ),
    FixtureItem(
        category="boundary",
        label="fix_with_architectural_detail",
        content=(
            "Fixed. The NOT EXISTS subquery resolves the race condition in claim SQL "
            "by checking package_processing_status before claiming."
        ),
        role="assistant",
        required_keywords=["NOT EXISTS", "race condition", "claim"],
        min_keywords=2,
    ),
]

ALL_FIXTURES = NOISE_FIXTURES + GOOD_FIXTURES + BOUNDARY_FIXTURES


def _load_jsonl_fixtures() -> list[FixtureItem]:
    """Load additional fixtures from JSONL file."""
    jsonl_path = Path(__file__).parent / "turn_summary_substance_fixtures.jsonl"
    if not jsonl_path.exists():
        return []
    items = []
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        items.append(FixtureItem(
            category=rec["category"],
            label=rec["label"],
            content=rec["content"],
            role=rec.get("role", "assistant"),
            required_keywords=rec.get("required_keywords"),
            min_keywords=rec.get("min_keywords"),
        ))
    return items

# Prefixes that indicate a parroting summary (no substance added)
BAD_SUMMARY_PREFIXES = (
    "User asks",
    "User instructs",
    "User requests",
    "User states",
)


# ── Eval logic ──────────────────────────────────────────────────────────────

@dataclass
class ItemResult:
    fixture: FixtureItem
    is_low_value_meta: bool
    summary: str
    constraint_text: str | None
    passed: bool
    reason: str


def build_user_prompt(content: str, role: str) -> str:
    """Build the user prompt for write extraction, matching production format."""
    return (
        f"Source type: agent_artifact\n"
        f"Source id: eval-turn-summary-001\n"
        f"Content type: text/plain\n"
        f"Artifact kind: null\n"
        f"Role: {role}\n"
        f"Metadata: {{}}\n"
        f"Content:\n{content}"
    )


def extract_summary(provider: LLMProvider, content: str, role: str) -> dict:
    """Call the LLM to extract summary fields from a source item."""
    response: LLMJsonResponse = provider.generate_json(
        system_prompt=PROMPT_VARIANTS[DEFAULT_PROMPT_VARIANT],
        user_prompt=build_user_prompt(content, role),
        schema_description=SCHEMA_DESCRIPTION,
    )
    return response.parsed_json


def evaluate_noise_item(fixture: FixtureItem, result: dict) -> ItemResult:
    """Noise items should have is_low_value_meta=true."""
    is_low_value = bool(result.get("is_low_value_meta", False))
    summary = result.get("summary", "")
    constraint_text = result.get("constraint_text")
    passed = is_low_value
    reason = (
        "OK: is_low_value_meta=true"
        if passed
        else f"FAIL: is_low_value_meta=false (expected true)"
    )
    return ItemResult(
        fixture=fixture,
        is_low_value_meta=is_low_value,
        summary=summary,
        constraint_text=constraint_text,
        passed=passed,
        reason=reason,
    )


def evaluate_good_item(fixture: FixtureItem, result: dict) -> ItemResult:
    """Good items must NOT be is_low_value_meta and should have substantive summaries."""
    is_low_value = bool(result.get("is_low_value_meta", False))
    summary = result.get("summary", "")
    constraint_text = result.get("constraint_text")

    if is_low_value:
        return ItemResult(
            fixture=fixture,
            is_low_value_meta=is_low_value,
            summary=summary,
            constraint_text=constraint_text,
            passed=False,
            reason="FAIL: is_low_value_meta=true (expected false for substantive content)",
        )

    # Check for parroting prefixes
    for prefix in BAD_SUMMARY_PREFIXES:
        if summary.startswith(prefix):
            return ItemResult(
                fixture=fixture,
                is_low_value_meta=is_low_value,
                summary=summary,
                constraint_text=constraint_text,
                passed=False,
                reason=f"FAIL: summary starts with parroting prefix '{prefix}'",
            )

    # Check for required keywords in summary or constraint_text
    required = fixture.required_keywords or []
    min_kw = fixture.min_keywords or 1
    all_text = (summary + " " + (constraint_text or "")).lower()
    found = [kw for kw in required if kw.lower() in all_text]
    passed = len(found) >= min_kw
    reason = (
        f"OK: {len(found)}/{len(required)} keywords found ({found})"
        if passed
        else f"MISSING: only {len(found)}/{min_kw} required keywords "
        f"(found={found}, missing={[k for k in required if k.lower() not in all_text]})"
    )
    return ItemResult(
        fixture=fixture,
        is_low_value_meta=is_low_value,
        summary=summary,
        constraint_text=constraint_text,
        passed=passed,
        reason=reason,
    )


def evaluate_boundary_item(fixture: FixtureItem, result: dict) -> ItemResult:
    """Boundary items must NOT be is_low_value_meta and should retain key knowledge."""
    is_low_value = bool(result.get("is_low_value_meta", False))
    summary = result.get("summary", "")
    constraint_text = result.get("constraint_text")

    if is_low_value:
        return ItemResult(
            fixture=fixture,
            is_low_value_meta=is_low_value,
            summary=summary,
            constraint_text=constraint_text,
            passed=False,
            reason="FAIL: is_low_value_meta=true (boundary items with design choices must be retained)",
        )

    # Check for required keywords in summary
    required = fixture.required_keywords or []
    min_kw = fixture.min_keywords or 1
    all_text = summary.lower()
    found = [kw for kw in required if kw.lower() in all_text]
    passed = len(found) >= min_kw
    reason = (
        f"OK: {len(found)}/{len(required)} keywords found ({found})"
        if passed
        else f"MISSING: only {len(found)}/{min_kw} required keywords in summary "
        f"(found={found}, missing={[k for k in required if k.lower() not in all_text]})"
    )
    return ItemResult(
        fixture=fixture,
        is_low_value_meta=is_low_value,
        summary=summary,
        constraint_text=constraint_text,
        passed=passed,
        reason=reason,
    )


def evaluate_item(fixture: FixtureItem, result: dict) -> ItemResult:
    if fixture.category == "noise":
        return evaluate_noise_item(fixture, result)
    elif fixture.category == "boundary":
        return evaluate_boundary_item(fixture, result)
    else:
        return evaluate_good_item(fixture, result)


# ── Main ────────────────────────────────────────────────────────────────────

def resolve_provider(config: AppConfig) -> LLMProvider:
    """Resolve the LLM provider for the llm_agent_memory package."""
    package_config = config.semantic_packages.get("llm_agent_memory")
    if package_config and package_config.llm_provider and package_config.model:
        return build_llm_provider(
            config,
            provider_name=package_config.llm_provider,
            model=package_config.model,
        )
    # Fallback: try agent_conversation_memory or first available LLM-backed package
    for pkg_name in ("agent_conversation_memory", *config.semantic_packages.keys()):
        pkg_config = config.semantic_packages.get(pkg_name)
        if pkg_config and pkg_config.llm_provider and pkg_config.model:
            print(f"  (using provider from '{pkg_name}' package)")
            return build_llm_provider(
                config,
                provider_name=pkg_config.llm_provider,
                model=pkg_config.model,
            )
    raise RuntimeError(
        "No LLM provider configured. Check pallium.local.toml for "
        "a semantic package with llm_provider and model set."
    )


def run_eval(*, verbose: bool = False) -> bool:
    config = AppConfig.from_env()
    print("Turn Summary Substance Eval")
    print("=" * 60)

    print("\nResolving LLM provider...")
    provider = resolve_provider(config)
    print("  Provider ready.\n")

    all_fixtures = ALL_FIXTURES + _load_jsonl_fixtures()
    print(f"  Loaded {len(all_fixtures)} fixtures ({len(ALL_FIXTURES)} inline + {len(all_fixtures) - len(ALL_FIXTURES)} from JSONL)\n")

    results: list[ItemResult] = []

    for fixture in all_fixtures:
        print(f"  [{fixture.category.upper():8s}] {fixture.label}...", end=" ", flush=True)
        try:
            result = extract_summary(provider, fixture.content, fixture.role)
            item_result = evaluate_item(fixture, result)
            results.append(item_result)
            status = "PASS" if item_result.passed else "FAIL"
            print(f"{status} (is_low_value_meta={item_result.is_low_value_meta})")
            if verbose or not item_result.passed:
                print(f"           {item_result.reason}")
                print(f"           summary: {(item_result.summary or '')[:100]}")
                if item_result.constraint_text:
                    print(f"           constraint_text: {item_result.constraint_text[:100]}")
        except Exception as exc:
            print(f"ERROR: {exc}")
            results.append(ItemResult(
                fixture=fixture,
                is_low_value_meta=False,
                summary="",
                constraint_text=None,
                passed=False,
                reason=f"LLM error: {exc}",
            ))

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    by_category: dict[str, list[ItemResult]] = {}
    for r in results:
        by_category.setdefault(r.fixture.category, []).append(r)

    all_passed = True
    for cat in ("noise", "good", "boundary"):
        cat_results = by_category.get(cat, [])
        passed = sum(1 for r in cat_results if r.passed)
        total = len(cat_results)
        cat_pass = passed == total
        if not cat_pass:
            all_passed = False
        marker = "PASS" if cat_pass else "FAIL"
        print(f"  {cat.upper():10s}: {passed}/{total} {marker}")
        if cat == "noise":
            noise_true = sum(1 for r in cat_results if r.is_low_value_meta)
            print(f"             is_low_value_meta=true: {noise_true}/{total}")

    total_passed = sum(1 for r in results if r.passed)
    total_items = len(results)
    print(f"\n  OVERALL: {total_passed}/{total_items} {'PASS' if all_passed else 'FAIL'}")
    print("=" * 60)

    return all_passed


def main():
    parser = argparse.ArgumentParser(
        description="Turn summary substance eval"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show summary and constraint_text for each item",
    )
    args = parser.parse_args()

    success = run_eval(verbose=args.verbose)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
