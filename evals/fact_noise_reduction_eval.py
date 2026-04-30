"""Fact extraction noise reduction eval.

Measures how many ephemeral-noise facts vs. durable-knowledge facts
are produced by the FACT_EXTRACTION_SYSTEM_PROMPT on real production
source items.

Categories:
  NOISE   — assistant narration/plan/test/UI confirmations (should produce few facts)
  GOOD    — root-cause knowledge, architectural findings (must produce durable facts)
  BOUNDARY — implementation-shaped but durable (must NOT be suppressed)

Usage:
    python -m evals.fact_noise_reduction_eval
    python -m evals.fact_noise_reduction_eval --verbose
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
from semantic.conversational_knowledge import (
    FACT_EXTRACTION_SYSTEM_PROMPT,
    FACT_EXTRACTION_SCHEMA_DESCRIPTION,
)


# ── Fixtures ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FixtureItem:
    category: str  # "noise", "good", "boundary"
    label: str
    content: str
    # For noise: max facts expected (fewer is better)
    max_facts: int | None = None
    # For good/boundary: keywords that MUST appear in extracted facts
    required_keywords: list[str] | None = None
    min_keywords: int | None = None


NOISE_FIXTURES = [
    FixtureItem(
        category="noise",
        label="plan_and_implementation_narration",
        content=(
            "[user]: do a deep review of this as an architect\n"
            "[assistant]: The plan creates 8 new files across two new packages "
            "(app/service/, app/service/platforms/) for service management. "
            "The Protocol-based platform plugin system for 3 concrete implementations "
            "is over-structured. A single detect_platform() function with if/elif would "
            "cover Linux systemd, macOS launchd, and Windows Task Scheduler without the "
            "abstraction overhead.\n"
            "[user]: ok implement it\n"
            "[assistant]: Done. All service implementation changes are in place — "
            "7 files, 805 insertions. The modified files and two new files "
            "(app/cli/service.py, tests/test_service.py) constitute the full feature. "
            "Committed as 9e19594."
        ),
        max_facts=3,
    ),
    FixtureItem(
        category="noise",
        label="ui_tweaks_and_confirmations",
        content=(
            "[user]: the dashboard header needs to be cleaner\n"
            "[assistant]: Done. The dashboard header was modified to display only "
            "'Pallium' in clean blue text. The pallium_header.png is 837KB, I compressed "
            "it to 420KB without visible quality loss. All three ephemeral metric sections "
            "now show 'since restart Xm Ys ago' in subtle small text below each card.\n"
            "[user]: what about the queries card?\n"
            "[assistant]: Done. The Queries metric card now shows 'since restart 8m 23s ago' "
            "(subtle, small text). Logo converted from RGB to transparent background."
        ),
        max_facts=2,
    ),
    FixtureItem(
        category="noise",
        label="test_writing_session",
        content=(
            "[user]: add tests for the service module\n"
            "[assistant]: Done. Added 15 new tests covering TestSeedConfig (5 tests), "
            "TestStartupSequence (4 tests), TestGracefulShutdown (3 tests), "
            "and TestPlatformDetection (3 tests). All pass. The test file is at "
            "tests/test_service.py, 340 lines total.\n"
            "[user]: make sure no pallium is running now\n"
            "[assistant]: All good — confirmed no pallium processes active. "
            "The scheduled task is deleted and no longer registered in Task Scheduler."
        ),
        max_facts=2,
    ),
    FixtureItem(
        category="noise",
        label="config_and_ops_changes",
        content=(
            "[user]: the log files are getting too big\n"
            "[assistant]: Done. The log now rotates at 5MB with 5 backups (max ~30MB). "
            "I also added timestamps to each rotation boundary in the log output.\n"
            "[user]: now stop and remove the current install service\n"
            "[assistant]: The task was created with elevated privileges. I've stopped the "
            "task successfully — it's no longer running. The Pallium scheduled task is "
            "deleted and no longer registered in Task Scheduler.\n"
            "[user]: ok, make sure it's deleted\n"
            "[assistant]: Done — verified the task is fully removed."
        ),
        max_facts=3,
    ),
    FixtureItem(
        category="noise",
        label="debugging_steps_no_conclusion",
        content=(
            "[user]: why is the embedding slow on first load?\n"
            "[assistant]: Let me check. The model download cache is at ~/.cache/huggingface. "
            "I see the model files are present (384MB total). Loading time is 3.2 seconds "
            "on first call, then 0.02s on subsequent calls. The ONNX runtime is doing JIT "
            "optimization on first load. Process memory jumps from 180MB to 340MB during "
            "first inference.\n"
            "[user]: ok\n"
            "[assistant]: The first-load penalty is expected behavior for ONNX models. "
            "Nothing to fix here."
        ),
        max_facts=2,
    ),
]

GOOD_FIXTURES = [
    FixtureItem(
        category="good",
        label="root_cause_knowledge",
        content=(
            "[user]: why are completion reports being stored as decisions?\n"
            "[assistant]: The generic problem is: completion confirmations are being "
            "misread as decisions by the extraction LLM. The model sees 'rename + "
            "threshold + prompt...' in an assistant completion and treats it as a choice, "
            "not a report. This class includes git pushes, deployments, and test run "
            "completions. The decision extraction prompt needs explicit guidance that "
            "completed actions reported after the fact are NOT decisions — a decision "
            "requires deliberation between alternatives."
        ),
        required_keywords=["completion", "confirmation", "decision"],
        min_keywords=2,
    ),
    FixtureItem(
        category="good",
        label="architectural_finding",
        content=(
            "[user]: the stats don't seem right after restart\n"
            "[assistant]: Stats reset at 10:13 (our last restart ~6 minutes ago). "
            "Only 2 queries since then — that's this session's SessionStart hook + "
            "the UserPromptSubmit for your last message. The in-memory stats counter "
            "is ephemeral by design — it zeros on restart because the counter lives "
            "in the FastAPI app state, not in SQLite. If you want persistent query "
            "counts, they'd need to go into the DB."
        ),
        required_keywords=["stats", "restart", "SessionStart", "ephemeral"],
        min_keywords=2,
    ),
    FixtureItem(
        category="good",
        label="system_behavior_discovery",
        content=(
            "[user]: where do subprocess logs go?\n"
            "[assistant]: The log file uses RotatingFileHandler — it rotates at 5MB "
            "with 5 backups, so max ~30MB total on disk. That's configured in "
            "runtime_logging.py:79-81. However, there's a child-process logging issue: "
            "subprocess logs aren't captured by the parent handler because each "
            "subprocess has its own Python interpreter and logging context. They write "
            "to stderr instead. This means background worker output is lost unless "
            "explicitly redirected."
        ),
        required_keywords=["RotatingFileHandler", "subprocess", "stderr", "child-process"],
        min_keywords=2,
    ),
]

BOUNDARY_FIXTURES = [
    FixtureItem(
        category="boundary",
        label="sql_race_condition_fix",
        content=(
            "[user]: items are getting processed twice sometimes\n"
            "[assistant]: Found it. claim_next_source_item only checks the source_items "
            "status column and had no awareness of the package table. When two packages "
            "run concurrently, both can claim the same item because the status update "
            "and package creation aren't atomic. SQL race condition fix: added a NOT "
            "EXISTS subquery to the legacy claim SQL that skips items with active "
            "package_processing rows. This eliminates the double-processing window."
        ),
        required_keywords=["claim_next_source_item", "race condition", "NOT EXISTS"],
        min_keywords=2,
    ),
    FixtureItem(
        category="boundary",
        label="hf_hub_offline_flag",
        content=(
            "[user]: embedding loads hang for 60 seconds under rate limiting\n"
            "[assistant]: The issue is HuggingFace Hub freshness checks. On every model "
            "load, the HF client checks if a newer version exists on the hub. Under "
            "rate limiting (HTTP 429), this check blocks for 60 seconds waiting for "
            "the retry. Fix: set HF_HUB_OFFLINE=1 in the environment. This tells the "
            "HF client to use only the local cache without any network calls. It "
            "affects all embedding model loads but since we pin model versions anyway, "
            "there's no downside."
        ),
        required_keywords=["HF_HUB_OFFLINE", "HuggingFace", "60 second", "embedding"],
        min_keywords=2,
    ),
]

ALL_FIXTURES = NOISE_FIXTURES + GOOD_FIXTURES + BOUNDARY_FIXTURES


def _load_jsonl_fixtures() -> list[FixtureItem]:
    """Load additional fixtures from JSONL file."""
    jsonl_path = Path(__file__).parent / "fact_noise_fixtures.jsonl"
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
            max_facts=rec.get("max_facts"),
            required_keywords=rec.get("required_keywords"),
            min_keywords=rec.get("min_keywords"),
        ))
    return items


# ── Eval logic ──────────────────────────────────────────────────────────────

@dataclass
class ItemResult:
    fixture: FixtureItem
    facts: list[dict]
    fact_count: int
    passed: bool
    reason: str


def build_user_prompt(content: str) -> str:
    """Build the user prompt for fact extraction, matching production format.

    Production (_extract_facts) passes thread_text directly as user_prompt.
    Thread text is pre-formatted as '[role]: content' lines by _build_chunk_texts.
    """
    return content


def extract_facts(provider: LLMProvider, content: str) -> list[dict]:
    """Call the LLM to extract facts from a source item."""
    response: LLMJsonResponse = provider.generate_json(
        system_prompt=FACT_EXTRACTION_SYSTEM_PROMPT,
        user_prompt=build_user_prompt(content),
        schema_description=FACT_EXTRACTION_SCHEMA_DESCRIPTION,
    )
    facts = response.parsed_json.get("facts", [])
    if not isinstance(facts, list):
        return []
    return facts


def evaluate_noise_item(fixture: FixtureItem, facts: list[dict]) -> ItemResult:
    """Noise items should produce few or no facts."""
    count = len(facts)
    max_allowed = fixture.max_facts or 2
    passed = count <= max_allowed
    reason = (
        f"OK: {count} facts (<= {max_allowed})"
        if passed
        else f"TOO MANY: {count} facts (max {max_allowed})"
    )
    return ItemResult(
        fixture=fixture,
        facts=facts,
        fact_count=count,
        passed=passed,
        reason=reason,
    )


def evaluate_good_item(fixture: FixtureItem, facts: list[dict]) -> ItemResult:
    """Good items must produce facts containing required keywords."""
    all_fact_text = " ".join(
        f.get("statement", "") + " " + f.get("subject", "")
        for f in facts
    ).lower()

    required = fixture.required_keywords or []
    min_kw = fixture.min_keywords or 1
    found = [kw for kw in required if kw.lower() in all_fact_text]
    passed = len(found) >= min_kw
    reason = (
        f"OK: {len(found)}/{len(required)} keywords found ({found})"
        if passed
        else f"MISSING: only {len(found)}/{min_kw} required keywords "
        f"(found={found}, missing={[k for k in required if k.lower() not in all_fact_text]})"
    )
    return ItemResult(
        fixture=fixture,
        facts=facts,
        fact_count=len(facts),
        passed=passed,
        reason=reason,
    )


def evaluate_boundary_item(fixture: FixtureItem, facts: list[dict]) -> ItemResult:
    """Boundary items must still produce durable facts (not be suppressed)."""
    if not facts:
        return ItemResult(
            fixture=fixture,
            facts=facts,
            fact_count=0,
            passed=False,
            reason="SUPPRESSED: no facts extracted (boundary items must produce facts)",
        )
    return evaluate_good_item(fixture, facts)


def evaluate_item(fixture: FixtureItem, facts: list[dict]) -> ItemResult:
    if fixture.category == "noise":
        return evaluate_noise_item(fixture, facts)
    elif fixture.category == "boundary":
        return evaluate_boundary_item(fixture, facts)
    else:
        return evaluate_good_item(fixture, facts)


# ── Main ────────────────────────────────────────────────────────────────────

def resolve_provider(config: AppConfig) -> LLMProvider:
    """Resolve the LLM provider for the conversational_knowledge package."""
    package_config = config.semantic_packages.get("conversational_knowledge")
    if package_config and package_config.llm_provider and package_config.model:
        return build_llm_provider(
            config,
            provider_name=package_config.llm_provider,
            model=package_config.model,
        )
    # Fallback: try the first available LLM-backed package
    for pkg_name, pkg_config in config.semantic_packages.items():
        if pkg_config.llm_provider and pkg_config.model:
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
    print("Fact Noise Reduction Eval")
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
            facts = extract_facts(provider, fixture.content)
            result = evaluate_item(fixture, facts)
            results.append(result)
            status = "PASS" if result.passed else "FAIL"
            print(f"{status} ({result.fact_count} facts)")
            if verbose or not result.passed:
                print(f"           {result.reason}")
            if verbose and facts:
                for f in facts:
                    stmt = f.get("statement", "?")[:80]
                    print(f"             - {stmt}")
        except Exception as exc:
            print(f"ERROR: {exc}")
            results.append(ItemResult(
                fixture=fixture,
                facts=[],
                fact_count=0,
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
            avg_facts = sum(r.fact_count for r in cat_results) / max(1, total)
            print(f"             avg facts per noise item: {avg_facts:.1f}")

    total_passed = sum(1 for r in results if r.passed)
    total_items = len(results)
    print(f"\n  OVERALL: {total_passed}/{total_items} {'PASS' if all_passed else 'FAIL'}")
    print("=" * 60)

    return all_passed


def main():
    parser = argparse.ArgumentParser(
        description="Fact extraction noise reduction eval"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show extracted facts for each item",
    )
    args = parser.parse_args()

    success = run_eval(verbose=args.verbose)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
