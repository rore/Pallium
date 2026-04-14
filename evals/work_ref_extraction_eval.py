"""Work-ref extraction evaluator — focused comparison of work_refs extraction quality.

Tests write_extraction prompt variants on synthetic snippets that contain or
lack external work identifiers. Validates extraction correctness, false positive
prevention, and regression on existing fields.

Usage:
    python -m evals.work_ref_extraction_eval --cache-dir .local/llm-cache
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.config import AppConfig
from app.dependencies import build_llm_provider
from providers.llm.base import LLMProvider
from semantic.llm_agent_memory import (
    PROMPT_VARIANTS,
    SCHEMA_DESCRIPTION,
    _normalize_extraction,
    _normalize_work_refs,
)
from semantic.prompt_variant_metrics import prompt_text_metrics


# ---------------------------------------------------------------------------
# Test snippets — negative (no work_refs) and positive (with work_refs)
# ---------------------------------------------------------------------------

SNIPPETS: list[dict[str, Any]] = [
    # --- Negative: must NOT extract work_refs ---
    {
        "id": "neg_version_number",
        "description": "Version number is not a work ref",
        "source_type": "assistant_artifact",
        "artifact_kind": "assistant_output",
        "role": "assistant",
        "content": "Root cause: version 2.3.1 introduced a regression in the sync path. The fix is in progress.",
        "expect_work_refs": [],
    },
    {
        "id": "neg_http_status",
        "description": "HTTP status code is not a work ref",
        "source_type": "assistant_artifact",
        "artifact_kind": "tool_use_summary",
        "role": "assistant",
        "content": "Blocked: catalog API returned 401 because the service token expired.",
        "expect_work_refs": [],
    },
    {
        "id": "neg_batch_number",
        "description": "Batch number is not a work ref",
        "source_type": "assistant_artifact",
        "artifact_kind": "tool_use_summary",
        "role": "assistant",
        "content": "Partial progress: refreshed 312 reservation records before failure.",
        "expect_work_refs": [],
    },
    {
        "id": "neg_batch_resume",
        "description": "Batch resume point is not a work ref",
        "source_type": "assistant_artifact",
        "artifact_kind": "tool_use_summary",
        "role": "assistant",
        "content": "Next step: refresh the catalog service token and rerun from batch 313.",
        "expect_work_refs": [],
    },
    {
        "id": "neg_no_identifiers",
        "description": "Plain work content with no external identifiers",
        "source_type": "assistant_artifact",
        "artifact_kind": "assistant_output",
        "role": "assistant",
        "content": "The admin toggle wiring is ready, but branch kiosk fallback coverage is still missing before review can pass.",
        "expect_work_refs": [],
    },
    {
        "id": "neg_casual_mention",
        "description": "Casual historical mention is not active work",
        "source_type": "chat_message",
        "artifact_kind": "message",
        "role": "user",
        "content": "We saw something similar in PROJ-999 last year, but that's not relevant here. Let's focus on the current issue.",
        "expect_work_refs": [],
    },
    {
        "id": "neg_tool_bash",
        "description": "Bash tool name is not a work ref",
        "source_type": "assistant_artifact",
        "artifact_kind": "tool_use_summary",
        "role": "assistant",
        "content": "Tool summary: Bash [done]: git commit -m 'Update docs'",
        "expect_work_refs": [],
    },
    {
        "id": "neg_constraint",
        "description": "Constraint with no work identifiers",
        "source_type": "chat_message",
        "artifact_kind": "message",
        "role": "user",
        "content": "Constraint: do not open a browser or use SSO-backed tools.",
        "expect_work_refs": [],
    },
    {
        "id": "neg_low_value",
        "description": "Low value chatter has no work refs",
        "source_type": "chat_message",
        "artifact_kind": "message",
        "role": "user",
        "content": "Hello, good morning!",
        "expect_work_refs": [],
    },
    # --- Multilingual negative ---
    {
        "id": "neg_hebrew_version",
        "description": "Hebrew content with version number, not a work ref",
        "source_type": "chat_message",
        "artifact_kind": "message",
        "role": "user",
        "content": "בדקנו את הבעיה בגרסה 2.3.1 ומצאנו שגיאה בסנכרון",
        "expect_work_refs": [],
    },
    {
        "id": "neg_japanese_port",
        "description": "Japanese content with port number, not a work ref",
        "source_type": "assistant_artifact",
        "artifact_kind": "assistant_output",
        "role": "assistant",
        "content": "サーバーがポート8080でエラーを返しました",
        "expect_work_refs": [],
    },
    # --- Positive: must extract work_refs ---
    {
        "id": "pos_decision_with_ticket",
        "description": "Decision referencing a Jira ticket",
        "source_type": "assistant_artifact",
        "artifact_kind": "assistant_output",
        "role": "assistant",
        "content": "Decision: use event-time ordering for PROJ-123 to avoid duplicate holds after delayed catalog sync.",
        "expect_work_refs": ["proj-123"],
    },
    {
        "id": "pos_tool_summary_ticket",
        "description": "Tool summary creating a ticket",
        "source_type": "assistant_artifact",
        "artifact_kind": "tool_use_summary",
        "role": "assistant",
        "content": "Tool summary: jira_create_issue [done]: Created SYNC-42",
        "expect_work_refs": ["sync-42"],
    },
    {
        "id": "pos_multiple_tickets",
        "description": "Message referencing multiple tickets",
        "source_type": "chat_message",
        "artifact_kind": "message",
        "role": "user",
        "content": "The auth migration (AUTH-100) is blocked by the token service issue (SYNC-42). We need both resolved.",
        "expect_work_refs": ["auth-100", "sync-42"],
    },
    {
        "id": "pos_progress_with_ticket",
        "description": "Progress report with ticket ID",
        "source_type": "assistant_artifact",
        "artifact_kind": "tool_use_summary",
        "role": "assistant",
        "content": "Partial progress: ticket LIB-241 has the schema change and backfill done.",
        "expect_work_refs": ["lib-241"],
    },
    {
        "id": "pos_no_identifier",
        "description": "Work content without any external identifier",
        "source_type": "assistant_artifact",
        "artifact_kind": "assistant_output",
        "role": "assistant",
        "content": "The overdue notice batching is ready for review.",
        "expect_work_refs": [],
    },
    # --- Multilingual positive ---
    {
        "id": "pos_hebrew_ticket",
        "description": "Hebrew content with ASCII ticket ID",
        "source_type": "chat_message",
        "artifact_kind": "message",
        "role": "user",
        "content": "בוא נמשיך לעבוד על PROJ-123",
        "expect_work_refs": ["proj-123"],
    },
    {
        "id": "pos_japanese_ticket",
        "description": "Japanese content with ASCII ticket ID",
        "source_type": "chat_message",
        "artifact_kind": "message",
        "role": "user",
        "content": "SYNC-42のチケットを確認してください",
        "expect_work_refs": ["sync-42"],
    },
]


# ---------------------------------------------------------------------------
# Assertion checker
# ---------------------------------------------------------------------------


def check_snippet(
    extraction: dict[str, Any],
    snippet: dict[str, Any],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    expected = snippet["expect_work_refs"]
    actual_raw = extraction.get("work_refs") or []
    actual = sorted(_normalize_work_refs(actual_raw))
    expected_sorted = sorted(expected)

    if expected_sorted:
        # Positive case: all expected work_refs must be present
        for ref in expected_sorted:
            found = ref in actual
            results.append({
                "assertion": f"work_ref '{ref}' extracted",
                "passed": found,
                "detail": f"actual: {actual}" if not found else "found",
            })
        # No unexpected refs
        unexpected = [r for r in actual if r not in expected_sorted]
        results.append({
            "assertion": "no unexpected work_refs",
            "passed": len(unexpected) == 0,
            "detail": "clean" if not unexpected else f"unexpected: {unexpected}",
        })
    else:
        # Negative case: work_refs must be empty
        results.append({
            "assertion": "work_refs must be empty",
            "passed": len(actual) == 0,
            "detail": "empty" if not actual else f"false positive: {actual}",
        })

    return results


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_eval(
    provider: LLMProvider,
    *,
    cache_dir: Path | None = None,
    variant_names: list[str] | None = None,
) -> dict[str, Any]:
    if cache_dir is not None:
        from providers.llm.cached import CachedLLMProvider
        provider = CachedLLMProvider(provider, cache_dir)

    if variant_names is None:
        variant_names = [
            "strict_typed_memory_v7_claude_structured",
            "strict_typed_memory_v8b_work_refs_separate",
        ]

    variant_results: dict[str, list[dict[str, Any]]] = {}

    for variant_name in variant_names:
        system_prompt = PROMPT_VARIANTS[variant_name]
        snippet_results: list[dict[str, Any]] = []

        for snippet in SNIPPETS:
            metadata = json.dumps({}, sort_keys=True)
            user_prompt = (
                f"Source type: {snippet['source_type']}\n"
                f"Source id: eval-{snippet['id']}\n"
                f"Content type: text/plain\n"
                f"Artifact kind: {snippet['artifact_kind']}\n"
                f"Role: {snippet['role']}\n"
                f"Metadata: {metadata}\n"
                f"Content:\n{snippet['content']}"
            )
            response = provider.generate_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema_description=SCHEMA_DESCRIPTION,
            )
            parsed = response.parsed_json
            assertion_results = check_snippet(parsed, snippet)
            passed_count = sum(1 for r in assertion_results if r["passed"])
            total_count = len(assertion_results)
            snippet_results.append({
                "snippet_id": snippet["id"],
                "description": snippet["description"],
                "raw_work_refs": parsed.get("work_refs"),
                "raw_candidate_type": parsed.get("candidate_type"),
                "raw_is_low_value_meta": parsed.get("is_low_value_meta"),
                "assertions": assertion_results,
                "passed": passed_count,
                "total": total_count,
                "all_passed": passed_count == total_count,
            })

        variant_results[variant_name] = snippet_results

    return {
        "variants": variant_results,
        "prompt_metrics": {
            name: prompt_text_metrics(PROMPT_VARIANTS[name])
            for name in variant_names
        },
    }


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------


def print_results(results: dict[str, Any]) -> None:
    variants = results["variants"]
    metrics = results["prompt_metrics"]

    print("\n" + "=" * 78)
    print("WORK-REF EXTRACTION EVAL — COMPARISON TABLE")
    print("=" * 78)

    # Per-snippet detail
    for snippet in SNIPPETS:
        sid = snippet["id"]
        print(f"\n--- {sid}: {snippet['description']} ---")
        for variant_name, snippet_results in variants.items():
            sr = next(s for s in snippet_results if s["snippet_id"] == sid)
            status = "PASS" if sr["all_passed"] else "FAIL"
            short_name = variant_name.replace("strict_typed_memory_", "")
            print(
                f"  {short_name:30s}  {status}  "
                f"{sr['passed']}/{sr['total']}  "
                f"work_refs={sr['raw_work_refs']}"
            )
            for ar in sr["assertions"]:
                if not ar["passed"]:
                    print(f"    [XX] {ar['assertion']}  ({ar['detail']})")

    # Summary
    print("\n" + "=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print(f"{'Variant':35s} {'Pass':>6s} {'Fail':>6s} {'Rate':>8s} {'Tokens':>8s}")
    print("-" * 65)

    for variant_name, snippet_results in variants.items():
        total_passed = sum(sr["passed"] for sr in snippet_results)
        total_assertions = sum(sr["total"] for sr in snippet_results)
        total_failed = total_assertions - total_passed
        pass_rate = total_passed / total_assertions if total_assertions else 0
        short_name = variant_name.replace("strict_typed_memory_", "")
        tokens = metrics.get(variant_name, {}).get("estimated_tokens", 0)
        print(f"{short_name:35s} {total_passed:>6d} {total_failed:>6d} {pass_rate:>7.0%} {tokens:>8d}")

    # Negative vs positive breakdown
    print(f"\n{'Variant':35s} {'Neg OK':>8s} {'Pos OK':>8s}")
    print("-" * 55)
    for variant_name, snippet_results in variants.items():
        neg_ok = sum(1 for sr in snippet_results if sr["snippet_id"].startswith("neg_") and sr["all_passed"])
        neg_total = sum(1 for sr in snippet_results if sr["snippet_id"].startswith("neg_"))
        pos_ok = sum(1 for sr in snippet_results if sr["snippet_id"].startswith("pos_") and sr["all_passed"])
        pos_total = sum(1 for sr in snippet_results if sr["snippet_id"].startswith("pos_"))
        short_name = variant_name.replace("strict_typed_memory_", "")
        print(f"{short_name:35s} {neg_ok}/{neg_total:>5d} {pos_ok}/{pos_total:>5d}")

    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run work-ref extraction eval."
    )
    parser.add_argument(
        "--cache-dir", type=Path, default=None,
        help="Directory for caching LLM calls.",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Write raw JSON results to this file.",
    )
    parser.add_argument(
        "--variants", type=str, default=None,
        help="Comma-separated variant names to test.",
    )
    args = parser.parse_args()

    config = AppConfig.from_env()

    # Find agent_conversation_memory package for write_extraction provider.
    acm_config = None
    for pkg_name, pkg_config in config.semantic_packages.items():
        if pkg_config.implementation == "agent_conversation_memory":
            acm_config = pkg_config
            break

    if acm_config is None or not acm_config.llm_provider or not acm_config.model:
        # Fall back to default use case provider.
        default_pkg = config.package_config(config.default_use_case)
        if not default_pkg.llm_provider or not default_pkg.model:
            print(
                "ERROR: No LLM provider configured for agent_conversation_memory "
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
            provider_name=acm_config.llm_provider,
            model=acm_config.model,
        )

    variant_names = args.variants.split(",") if args.variants else None
    results = run_eval(provider, cache_dir=args.cache_dir, variant_names=variant_names)
    print_results(results)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
        print(f"Results written to {args.output}")

    # Exit 0 if at least one v8 variant passes all assertions
    v8_variants = [
        name for name in results["variants"]
        if "v8" in name
    ]
    any_v8_perfect = any(
        all(sr["all_passed"] for sr in results["variants"][name])
        for name in v8_variants
    )
    return 0 if any_v8_perfect else 1


if __name__ == "__main__":
    raise SystemExit(main())
