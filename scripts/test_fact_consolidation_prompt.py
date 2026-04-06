"""Prompt iteration script for fact consolidation.

Tests prompt candidates against real conv-26 fact groups.
Not committed — run manually during development.

Usage: python scripts/test_fact_consolidation_prompt.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import AppConfig
from app.dependencies import build_llm_provider


DB_PATH = Path("evals/locomo/db_cache/conv-26.db")

PROMPT_CANDIDATES = {
    "A_semicolon": (
        "Consolidate the atomic facts below into one summary for the given subject and category. "
        'Return JSON: {"summary": "..."}\n'
        "Format: semicolon-separated list of distinct facts. Merge duplicates into their most specific form. "
        "Preserve: proper nouns, dates, numbers, qualifying details. "
        "Do not add inferences or facts not in the input. "
        "Write in the same language as the input facts."
    ),
    "B_enumerated": (
        "Consolidate the atomic facts below into one summary for the given subject and category. "
        'Return JSON: {"summary": "..."}\n'
        "Format: a single sentence starting with \"{subject}'s {category}:\" followed by a comma-separated enumeration. "
        "Include sub-details in parentheses where multiple facts relate to the same topic. "
        "Merge duplicates. Preserve all proper nouns, dates, numbers, and qualifying details. "
        "Do not add inferences or facts not in the input. "
        "Write in the same language as the input facts."
    ),
    "C_minimal": (
        "Merge these facts about one subject into a single concise summary. "
        'Return JSON: {"summary": "..."}\n'
        "Preserve all specific details. Merge duplicates. No inferences. "
        "Same language as input."
    ),
}

SCHEMA_DESC = json.dumps({"summary": "consolidated fact summary as enumerated list"}, indent=2)

GOLD_CHECKS = {
    ("Melanie", "activity"): {
        "required": ["pottery", "painting", "camping", "swimming", "running", "violin", "clarinet", "reading", "hiking"],
        "bonus": ["marshmallows", "sunrise", "sunset", "bowl", "plate"],
    },
    ("Caroline", "activity"): {
        "required": ["hiking", "yoga", "tennis", "gardening"],
        "bonus": [],
    },
    ("Melanie", "preference"): {
        "required": ["pottery", "camping"],
        "bonus": ["beach", "nature"],
    },
}


def load_fact_groups(db_path: Path) -> dict[tuple[str, str], list[str]]:
    """Load atomic_fact statements grouped by (subject, category) from cached DB."""
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("""
        SELECT json_extract(payload_json, '$.subject') as subject,
               json_extract(payload_json, '$.category') as category,
               json_extract(payload_json, '$.statement') as statement
        FROM memory_objects
        WHERE type='atomic_fact' AND lifecycle='active'
        ORDER BY subject, category
    """).fetchall()
    conn.close()

    groups: dict[tuple[str, str], list[str]] = {}
    for subject, category, statement in rows:
        groups.setdefault((subject, category), []).append(statement)
    return groups


def build_user_prompt(subject: str, category: str, statements: list[str]) -> str:
    fact_lines = [f"- {s}" for s in statements]
    return f"Subject: {subject}\nCategory: {category}\nFacts ({len(fact_lines)}):\n" + "\n".join(fact_lines)


def check_keywords(summary: str, keywords: list[str]) -> tuple[int, int, list[str]]:
    """Returns (found, total, missing)."""
    lowered = summary.lower()
    found = [k for k in keywords if k.lower() in lowered]
    missing = [k for k in keywords if k.lower() not in lowered]
    return len(found), len(keywords), missing


def main():
    if not DB_PATH.exists():
        print(f"ERROR: {DB_PATH} not found. Run LoCoMo benchmark first to create cache.")
        sys.exit(1)

    groups = load_fact_groups(DB_PATH)
    config = AppConfig.from_env()
    default_package = config.package_config(config.default_use_case)
    provider = build_llm_provider(config, provider_name=default_package.llm_provider, model=default_package.model)

    test_groups = [(s, c) for (s, c) in GOLD_CHECKS.keys() if (s, c) in groups]
    if not test_groups:
        print("ERROR: No matching groups found in DB")
        sys.exit(1)

    print(f"Testing {len(PROMPT_CANDIDATES)} prompt candidates against {len(test_groups)} groups\n")

    results: dict[str, dict] = {}
    for prompt_name, system_prompt in PROMPT_CANDIDATES.items():
        print(f"=== {prompt_name} ===")
        total_required_found = 0
        total_required = 0
        total_bonus_found = 0
        total_bonus = 0
        total_output_chars = 0

        for subject, category in test_groups:
            statements = groups[(subject, category)]
            user_prompt = build_user_prompt(subject, category, statements)

            response = provider.generate_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema_description=SCHEMA_DESC,
            )
            summary = response.parsed_json.get("summary", "")

            gold = GOLD_CHECKS[(subject, category)]
            req_found, req_total, req_missing = check_keywords(summary, gold["required"])
            bon_found, bon_total, _ = check_keywords(summary, gold["bonus"])

            total_required_found += req_found
            total_required += req_total
            total_bonus_found += bon_found
            total_bonus += bon_total
            total_output_chars += len(summary)

            pct = req_found / req_total * 100 if req_total else 100
            status = "PASS" if pct >= 80 else "FAIL"
            print(f"  {subject}/{category}: {status} required={req_found}/{req_total} ({pct:.0f}%) bonus={bon_found}/{bon_total} chars={len(summary)}")
            if req_missing:
                print(f"    Missing: {req_missing}")
            print(f"    Summary: {summary[:200]}{'...' if len(summary) > 200 else ''}")

        overall_pct = total_required_found / total_required * 100 if total_required else 100
        print(f"  TOTAL: required={total_required_found}/{total_required} ({overall_pct:.0f}%) "
              f"bonus={total_bonus_found}/{total_bonus} avg_chars={total_output_chars // len(test_groups)}")
        results[prompt_name] = {
            "required_pct": overall_pct,
            "bonus_found": total_bonus_found,
            "avg_chars": total_output_chars // len(test_groups),
        }
        print()

    print("=== COMPARISON ===")
    for name, r in sorted(results.items(), key=lambda x: -x[1]["required_pct"]):
        print(f"  {name}: required={r['required_pct']:.0f}% bonus={r['bonus_found']} avg_chars={r['avg_chars']}")


if __name__ == "__main__":
    main()
