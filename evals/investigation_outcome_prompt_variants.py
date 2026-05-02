"""Investigation outcome prompt variant comparison.

Tests different prompt additions against the subset of items that PASS the
deterministic gate but should be rejected by the LLM (meta-verdicts, titles
with 6+ tokens, etc.).

Usage:
    python -m evals.investigation_outcome_prompt_variants
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from app.config import AppConfig
from app.dependencies import build_llm_provider
from core.models import SourceItem
from core.text import TOKEN_PATTERN
from semantic.llm_agent_memory import (
    LLMAgentMemoryPlugin,
    PROMPT_VARIANTS,
    DEFAULT_PROMPT_VARIANT,
)


CORPUS_PATH = Path(__file__).parent / "investigation_outcome_quality_corpus.jsonl"

# --- Prompt variant additions (appended after investigation_outcome cue line) ---

# Baseline: the original v8b prompt with NO additions
VARIANT_BASELINE = ""

# Variant A: Generalized principle (~30 tokens)
VARIANT_A_GENERALIZED = """  investigation_text must state what was DISCOVERED about a system or domain, not what was JUDGED about work quality. Architect reviews, plan approvals, and self-critiques are quality judgments, not findings."""

# Variant B: Specific examples (~130 tokens) — current implementation
VARIANT_B_SPECIFIC = """  investigation_text MUST be a self-contained finding that names its subject. A reader seeing ONLY this field must understand what was investigated and what was found.
  REJECT as investigation_outcome (set candidate_type null):
  - Section headings or document titles ("Root Causes Found", "Issues by category", "Architect Review Results") — headings are not findings.
  - Meta-assessments of work/plan quality ("the approach is correct", "the 4 problems are real", "approve with adjustments") — these validate a process, not state a domain finding.
  - Conclusions that don't name their subject ("not worth building" without saying WHAT isn't worth building).
  - File path pointers ("The findings document is at docs/...") — a location is not a finding.
  - Process status ("The investigation is parked", "Looking at my own review") — status is not an outcome."""

# Variant C: Cue-refined (~50 tokens)
VARIANT_C_CUE_REFINED = """  investigation_text must be a self-contained finding that names its subject — a reader must understand what was investigated and what was found.
  Investigation cues ("Verdict:", "Conclusion:") only qualify when they introduce a discovered property, measurement, or cause. They do NOT qualify when they express approval, rejection, deferral, or validation of proposed or completed work."""

VARIANTS = {
    "baseline": VARIANT_BASELINE,
    "A_generalized": VARIANT_A_GENERALIZED,
    "B_specific": VARIANT_B_SPECIFIC,
    "C_cue_refined": VARIANT_C_CUE_REFINED,
}


def _build_variant_prompt(variant_text: str) -> str:
    """Insert the variant addition into the v8b prompt after the investigation cue line."""
    base = PROMPT_VARIANTS[DEFAULT_PROMPT_VARIANT]
    cue_line = '- investigation_outcome: requires resolved-finding language ("Root cause:", "Investigation found", "Analysis found", "Findings:", "Outcome:", "We found that", "Verdict:", "Conclusion:", "Investigation concluded", "The conclusion is").'

    if not variant_text:
        return base

    return base.replace(cue_line, cue_line + "\n" + variant_text)


def load_gate_passing_bad_items() -> list[dict]:
    """Load items that are bad but pass the 6-token gate — these need the prompt to reject."""
    corpus = [json.loads(line) for line in open(CORPUS_PATH, encoding="utf-8") if line.strip()]
    return [
        item for item in corpus
        if not item["expected_viable"]
        and len(TOKEN_PATTERN.findall(item["investigation_text"] or "")) >= 6
    ]


def run_variant(variant_name: str, items: list[dict], provider) -> dict:
    """Run one variant against the gate-passing bad items."""
    variant_prompt = _build_variant_prompt(VARIANTS[variant_name])

    # Monkey-patch the prompt temporarily
    original = PROMPT_VARIANTS[DEFAULT_PROMPT_VARIANT]
    PROMPT_VARIANTS[DEFAULT_PROMPT_VARIANT] = variant_prompt

    plugin = LLMAgentMemoryPlugin(provider=provider)
    results = {"rejected": 0, "still_extracted": 0, "errors": 0, "failures": []}

    try:
        for item in items:
            source_item = SourceItem(
                source_type=item["source_type"],
                source_id=item["source_id"],
                content_type=item["content_type"] or "text/plain",
                content=item["source_content"],
                role=item.get("role"),
                artifact_kind=item.get("artifact_kind"),
            )

            try:
                trace = plugin.analyze_item(source_item)
            except Exception:
                results["errors"] += 1
                continue

            has_investigation = (
                trace.extraction.candidate_type == "investigation_outcome"
                and trace.extraction.investigation_text
            )

            if not has_investigation:
                results["rejected"] += 1
            else:
                results["still_extracted"] += 1
                results["failures"].append({
                    "index": item["index"],
                    "pattern": item["failure_pattern"],
                    "text": (trace.extraction.investigation_text or "")[:70],
                })
    finally:
        PROMPT_VARIANTS[DEFAULT_PROMPT_VARIANT] = original

    return results


def main():
    sys.stdout.reconfigure(encoding="utf-8")

    items = load_gate_passing_bad_items()
    print(f"Testing {len(items)} bad items that pass the deterministic gate")
    print(f"These items need the LLM prompt to reject them.")
    print()

    config = AppConfig.from_env()
    package = config.package_config(config.default_use_case)
    if not package.llm_provider or not package.model:
        raise ValueError(f"{config.default_use_case} is not configured")
    provider = build_llm_provider(config, provider_name=package.llm_provider, model=package.model)

    # Token cost comparison
    base_prompt = PROMPT_VARIANTS[DEFAULT_PROMPT_VARIANT]
    print("Token cost comparison (approx prompt chars added):")
    for name, text in VARIANTS.items():
        added = len(text)
        print(f"  {name:15}: +{added:4} chars")
    print()

    # Run each variant
    all_results = {}
    for name in VARIANTS:
        print(f"Running variant: {name}...")
        results = run_variant(name, items, provider)
        all_results[name] = results
        total = results["rejected"] + results["still_extracted"] + results["errors"]
        print(f"  Rejected: {results['rejected']}/{total} ({results['rejected']/max(total,1)*100:.0f}%)")
        if results["errors"]:
            print(f"  Errors: {results['errors']}")

    # Summary comparison
    print()
    print("=" * 70)
    print(f"{'Variant':<16} {'Rejected':>8} {'Still Bad':>10} {'Rate':>8} {'Chars Added':>12}")
    print("-" * 70)
    for name, results in all_results.items():
        total = results["rejected"] + results["still_extracted"] + results["errors"]
        rate = results["rejected"] / max(total, 1) * 100
        chars = len(VARIANTS[name])
        print(f"{name:<16} {results['rejected']:>8} {results['still_extracted']:>10} {rate:>7.0f}% {chars:>12}")

    # Show what each variant still misses
    print()
    best_name = max(all_results, key=lambda n: all_results[n]["rejected"])
    best = all_results[best_name]
    if best["failures"]:
        print(f"Best variant ({best_name}) still misses:")
        for f in best["failures"]:
            print(f"  #{f['index']:2} [{f['pattern']:15}] {f['text']}")


if __name__ == "__main__":
    main()
