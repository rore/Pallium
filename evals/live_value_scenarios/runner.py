"""Live value scenario eval — tests Pallium's value proposition against real data.

Each scenario represents a real moment where Pallium SHOULD (or SHOULD NOT)
provide value by injecting memory. Scenarios are derived from confirmed
feedback-rated injection events in the live DB.

Unlike synthetic evals, these scenarios run against the actual live memory pool.
This means:
- No setup/teardown — the memory already exists
- Assertions are content-pattern based, not exact-ID based (the pool evolves)
- Newer memories about the same topic may supersede originals — that's fine
  as long as the VALUE JUDGMENT still holds

Usage:
    python -m evals.live_value_scenarios.runner [--db PATH] [--host URL]

Requires a running Pallium service OR direct DB path for offline mode.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


SCENARIOS_FILE = Path(__file__).parent / "scenarios.json"


@dataclass
class ScenarioResult:
    scenario_id: str
    category: str
    description: str
    value_story: str
    expected_status: str
    passed: bool
    injection_correct: bool
    type_match: bool
    content_match: bool
    anti_pattern_clean: bool
    actual_should_inject: bool
    actual_types: list[str]
    actual_content_preview: str
    failure_reasons: list[str] = field(default_factory=list)


def load_scenarios(path: Path = SCENARIOS_FILE) -> list[dict[str, Any]]:
    with open(path) as f:
        return json.loads(f.read())


def run_query(host: str, query: dict[str, Any]) -> dict[str, Any]:
    resp = httpx.post(
        f"{host}/query",
        json={
            "text": query["text"],
            "container_ref": query["container_ref"],
            "thread_ref": f"eval-live-value-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}",
            "visibility": query["visibility"],
            "limit": 5,
        },
        timeout=30,
    )
    resp.raise_for_status()
    result = resp.json()

    # Enrich blocks with memory content via evidence endpoint
    for block in result.get("injectable_blocks", []):
        mo_id = block.get("memory_object_id")
        if mo_id and query.get("container_ref"):
            try:
                ev_resp = httpx.get(
                    f"{host}/memory/{mo_id}/expand",
                    params={"container_ref": query["container_ref"]},
                    timeout=10,
                )
                if ev_resp.status_code == 200:
                    block["_evidence_items"] = ev_resp.json().get("items", [])
            except Exception:
                pass

    return result


def evaluate_scenario(scenario: dict[str, Any], query_result: dict[str, Any]) -> ScenarioResult:
    expected = scenario["expected"]
    anti = scenario.get("anti_patterns", {})
    failures: list[str] = []

    actual_inject = query_result.get("should_inject", False)
    blocks = query_result.get("injectable_blocks", [])

    actual_types = [b.get("memory_type", "") for b in blocks]
    # Build content corpus from block previews + evidence items
    content_parts = []
    for b in blocks:
        content_parts.append(b.get("title_preview", ""))
        content_parts.append(b.get("text", ""))
        for ev in b.get("_evidence_items", []):
            content_parts.append(ev.get("content", ""))
    content_texts = " ".join(content_parts).lower()

    # Assertion 1: injection decision
    injection_correct = actual_inject == expected["should_inject"]
    if not injection_correct:
        failures.append(
            f"should_inject: expected={expected['should_inject']}, got={actual_inject}"
        )

    # Assertion 2: memory type match (at least one expected type present)
    type_match = True
    if expected["memory_types"]:
        type_match = any(t in actual_types for t in expected["memory_types"])
        if not type_match and actual_inject:
            failures.append(
                f"types: expected one of {expected['memory_types']}, got {actual_types}"
            )
    elif actual_inject:
        type_match = True  # no type requirement for negative scenarios that inject anyway

    # Assertion 3: content pattern match
    content_match = True
    if expected["content_patterns"] and actual_inject:
        # Need content from the memory objects — use result_id or fetch
        # For now, check against what we can see in the blocks
        # The blocks may not contain full text, so we also check types
        content_match = any(
            p.lower() in content_texts for p in expected["content_patterns"]
        )
        if not content_match:
            failures.append(
                f"content: none of {expected['content_patterns']} found in block text"
            )

    # Assertion 4: anti-pattern check
    anti_clean = True
    bad_types = anti.get("should_not_inject_types", [])
    if bad_types and actual_inject:
        offending = [t for t in actual_types if t in bad_types]
        if offending:
            anti_clean = False
            failures.append(f"anti-pattern types present: {offending}")

    bad_content = anti.get("should_not_contain", [])
    if bad_content and actual_inject:
        found_bad = [p for p in bad_content if p.lower() in content_texts]
        if found_bad:
            anti_clean = False
            failures.append(f"anti-pattern content found: {found_bad}")

    passed = injection_correct and type_match and content_match and anti_clean

    return ScenarioResult(
        scenario_id=scenario["scenario_id"],
        category=scenario["category"],
        description=scenario["description"],
        value_story=scenario["value_story"],
        expected_status=scenario.get("expected_status", "pass"),
        passed=passed,
        injection_correct=injection_correct,
        type_match=type_match,
        content_match=content_match,
        anti_pattern_clean=anti_clean,
        actual_should_inject=actual_inject,
        actual_types=actual_types,
        actual_content_preview=content_texts[:200],
        failure_reasons=failures,
    )


def print_report(results: list[ScenarioResult]) -> None:
    print("\n" + "=" * 70)
    print("LIVE VALUE SCENARIO EVAL")
    print("=" * 70)

    passed = sum(1 for r in results if r.passed)
    expected_fail = sum(
        1 for r in results if not r.passed and r.expected_status == "known_fail"
    )
    unexpected_fail = sum(
        1 for r in results if not r.passed and r.expected_status != "known_fail"
    )
    unexpected_pass = sum(
        1 for r in results if r.passed and r.expected_status == "known_fail"
    )

    print(f"\nResults: {passed}/{len(results)} passed")
    if expected_fail:
        print(f"  Known failures: {expected_fail}")
    if unexpected_fail:
        print(f"  UNEXPECTED FAILURES: {unexpected_fail}")
    if unexpected_pass:
        print(f"  UNEXPECTED PASSES (fixed regressions!): {unexpected_pass}")

    print("\n" + "-" * 70)
    print("DETAIL")
    print("-" * 70)

    for r in results:
        if r.passed and r.expected_status == "known_fail":
            status = "FIXED"
        elif r.passed:
            status = "PASS"
        elif r.expected_status == "known_fail":
            status = "KNOWN_FAIL"
        else:
            status = "FAIL"

        print(f"\n[{status}] {r.scenario_id}")
        print(f"  Category: {r.category}")
        print(f"  Value: {r.value_story[:120]}")
        if not r.passed:
            for f in r.failure_reasons:
                print(f"  FAILURE: {f}")
            if r.expected_status == "known_fail":
                # Find the scenario to get the reason
                print(f"  (Known: this is a documented regression)")
        if r.actual_should_inject:
            print(f"  Injected types: {r.actual_types}")

    # Summary by category
    print("\n" + "-" * 70)
    print("BY CATEGORY")
    print("-" * 70)
    categories: dict[str, list[ScenarioResult]] = {}
    for r in results:
        categories.setdefault(r.category, []).append(r)
    for cat, cat_results in sorted(categories.items()):
        cat_passed = sum(1 for r in cat_results if r.passed)
        print(f"  {cat}: {cat_passed}/{len(cat_results)}")

    # Value assessment
    print("\n" + "-" * 70)
    print("VALUE ASSESSMENT")
    print("-" * 70)
    positive_scenarios = [r for r in results if r.category != "negative_no_inject"]
    negative_scenarios = [r for r in results if r.category == "negative_no_inject"]
    pos_pass = sum(1 for r in positive_scenarios if r.passed)
    neg_pass = sum(1 for r in negative_scenarios if r.passed)
    print(f"  Positive value (memory surfaced correctly): {pos_pass}/{len(positive_scenarios)}")
    print(f"  Negative value (silence when appropriate): {neg_pass}/{len(negative_scenarios)}")
    print()


def run_eval(host: str, scenarios_path: Path = SCENARIOS_FILE) -> list[ScenarioResult]:
    scenarios = load_scenarios(scenarios_path)
    results = []

    for scenario in scenarios:
        try:
            query_result = run_query(host, scenario["query"])
            result = evaluate_scenario(scenario, query_result)
            results.append(result)
        except Exception as e:
            results.append(ScenarioResult(
                scenario_id=scenario["scenario_id"],
                category=scenario.get("category", "unknown"),
                description=scenario.get("description", ""),
                value_story=scenario.get("value_story", ""),
                expected_status=scenario.get("expected_status", "pass"),
                passed=False,
                injection_correct=False,
                type_match=False,
                content_match=False,
                anti_pattern_clean=False,
                actual_should_inject=False,
                actual_types=[],
                actual_content_preview="",
                failure_reasons=[f"Error: {e}"],
            ))

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Run live value scenario eval")
    parser.add_argument(
        "--host",
        default="http://127.0.0.1:19836",
        help="Pallium service URL",
    )
    parser.add_argument(
        "--scenarios",
        type=Path,
        default=SCENARIOS_FILE,
        help="Path to scenarios JSON file",
    )
    args = parser.parse_args()

    results = run_eval(args.host, args.scenarios)
    print_report(results)

    # Exit code: 0 if all pass or all failures are known_fail
    unexpected = [
        r for r in results
        if not r.passed and r.expected_status != "known_fail"
    ]
    return 1 if unexpected else 0


if __name__ == "__main__":
    sys.exit(main())
