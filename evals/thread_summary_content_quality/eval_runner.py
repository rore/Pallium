"""Focused eval for thread summary content_quality LLM self-classification.

Loads thread material fixtures, calls the LLM with the thread summary schema,
and compares the returned content_quality against expected labels.

Usage:
    python -m evals.thread_summary_content_quality.eval_runner
    python -m evals.thread_summary_content_quality.eval_runner --cache-dir .local/llm-cache
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.config import AppConfig
from app.dependencies import build_llm_provider
from providers.llm.cached import CachedLLMProvider
from semantic.agent_conversation_memory_threads import (
    THREAD_SUMMARY_SCHEMA_DESCRIPTION,
    THREAD_SUMMARY_SYSTEM_PROMPT,
)

FIXTURE_PATH = Path(__file__).parent / "fixture.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Eval thread summary content_quality classification.")
    parser.add_argument("--cache-dir", type=Path, default=None)
    args = parser.parse_args()

    config = AppConfig.from_env()
    package_config = config.semantic_packages.get("agent_conversation_memory")
    if not package_config or not package_config.llm_provider:
        print("ERROR: agent_conversation_memory package not configured with an LLM provider.")
        return 1

    provider_config = config.llm_providers.get(package_config.llm_provider)
    if not provider_config:
        print(f"ERROR: LLM provider '{package_config.llm_provider}' not found in config.")
        return 1

    # Use model_roles.thread_aggregation if available, else default model
    model = (package_config.model_roles or {}).get("thread_aggregation", package_config.model)
    provider = build_llm_provider(config, provider_name=package_config.llm_provider, model=model)
    if args.cache_dir:
        provider = CachedLLMProvider(provider, args.cache_dir)

    fixture = json.loads(FIXTURE_PATH.read_text())
    items = fixture["items"]

    print(f"Running {len(items)} items against model={model} provider={provider_config.kind}")
    print(f"Schema: thread_summary_extraction v4")
    print()

    passed = 0
    failed = 0
    override_count = 0

    for item in items:
        item_id = item["id"]
        expected = item["expected_content_quality"]
        thread_material = item["thread_material"]

        user_prompt = (
            f"Container ref: chat:library-eval\n"
            f"Thread ref: chat:library-eval:thread-{item_id}\n"
            f"Latest occurred at: 2026-03-20T10:00:00Z\n"
            f"Carried conclusions:\n- none\n\n"
            f"Selected work artifacts:\n- none\n\n"
            f"Thread items:\n{thread_material}"
        )

        try:
            response = provider.generate_json(
                system_prompt=THREAD_SUMMARY_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                schema_description=THREAD_SUMMARY_SCHEMA_DESCRIPTION,
            )
            actual = response.parsed_json.get("content_quality", "<missing>")
            summary = response.parsed_json.get("summary", "")
        except Exception as e:
            print(f"  FAIL  {item_id}: expected={expected}, error={e}")
            failed += 1
            continue

        if actual == expected:
            print(f"  PASS  {item_id}: {actual}")
            passed += 1
        else:
            print(f"  FAIL  {item_id}: expected={expected}, got={actual}")
            print(f"        summary: {summary[:120]}")
            failed += 1

    print()
    print(f"Results: {passed}/{len(items)} passed, {failed} failed")
    if failed > 0:
        print("FAIL — fix prompt descriptions for failing cases before shipping.")
        return 1
    print("PASS — 100% accuracy on hand-authored fixture.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
