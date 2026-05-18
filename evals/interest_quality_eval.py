"""Interest extraction quality eval.

Tests whether the extraction prompt correctly identifies genuine interests vs
false positives (task instructions, questions, active work, IDE events).

Baseline (v8b production prompt): 14% precision — only 10/72 extracted interests
are genuine uncommitted curiosity useful in future threads.

Usage:
    python -m evals.interest_quality_eval [--variant VARIANT] [--provider PROVIDER]

Runs each labeled corpus item through the extraction prompt and checks whether
the LLM would extract an interest or not. Compares against ground truth.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.stdout.reconfigure(encoding="utf-8")

CORPUS_FILE = Path(__file__).parent / "interest_quality_corpus.jsonl"


@dataclass
class EvalResult:
    item_id: str
    interest_text: str
    label: str
    bad_pattern: str | None
    predicted_interest: bool
    predicted_interest_text: str | None
    correct: bool
    raw_response: dict[str, Any] | None = None


@dataclass
class EvalSummary:
    total: int
    true_positives: int
    true_negatives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float
    fp_by_pattern: dict[str, int] = field(default_factory=dict)


def load_corpus(path: Path = CORPUS_FILE) -> list[dict[str, Any]]:
    items = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                items.append(json.loads(line))
    return items


def build_extraction_message(item: dict[str, Any], prompt_text: str, schema_description: str) -> list[dict[str, str]]:
    source_role = item.get("source_role") or "null"
    artifact_kind = item.get("artifact_kind") or "null"
    content = item["source_content"]
    user_prompt = (
        f"Source type: agent_artifact\n"
        f"Source id: eval-{item['id'][:8]}\n"
        f"Content type: text/plain\n"
        f"Artifact kind: {artifact_kind}\n"
        f"Role: {source_role}\n"
        f"Metadata: {{}}\n"
        f"Content:\n{content}"
        f"\n\nReturn exactly one JSON object matching this schema:\n{schema_description}"
    )
    return [
        {"role": "system", "content": prompt_text},
        {"role": "user", "content": user_prompt},
    ]


def call_llm(messages: list[dict[str, str]], provider: str) -> dict[str, Any]:
    if provider == "anthropic":
        return _call_anthropic(messages)
    elif provider == "openai":
        return _call_openai(messages)
    elif provider == "proxy":
        return _call_proxy(messages)
    else:
        raise ValueError(f"Unknown provider: {provider}")


def _call_proxy(messages: list[dict[str, str]]) -> dict[str, Any]:
    """Call via local Anthropic-compatible proxy (same as production)."""
    import httpx
    import os
    from dotenv import load_dotenv
    load_dotenv(".env.local")

    base_url = os.environ.get("PALLIUM_PROXY_URL", "http://localhost:6655/anthropic/v1")
    api_key = os.environ.get("PALLIUM_API_KEY", "dummy")
    model = os.environ.get("PALLIUM_LLM_MODEL", "anthropic--claude-sonnet-latest")

    system_msg = next((m["content"] for m in messages if m["role"] == "system"), "")
    user_msgs = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"]

    resp = httpx.post(
        f"{base_url}/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 1024,
            "system": system_msg,
            "messages": user_msgs,
        },
        timeout=60,
    )
    resp.raise_for_status()
    result = resp.json()
    text = result["content"][0]["text"].strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(text)


def _call_anthropic(messages: list[dict[str, str]]) -> dict[str, Any]:
    import anthropic

    client = anthropic.Anthropic()
    system_msg = next((m["content"] for m in messages if m["role"] == "system"), "")
    user_msgs = [m for m in messages if m["role"] != "system"]

    resp = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=system_msg,
        messages=user_msgs,
    )
    text = resp.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(text)


def _call_openai(messages: list[dict[str, str]]) -> dict[str, Any]:
    from openai import OpenAI
    import os

    base_url = os.environ.get("OPENAI_BASE_URL", os.environ.get("PALLIUM_OPENAI_BASE_URL"))
    api_key = os.environ.get("OPENAI_API_KEY", os.environ.get("PALLIUM_OPENAI_API_KEY"))
    model = os.environ.get("PALLIUM_LLM_MODEL", "gpt-4o-mini")

    client = OpenAI(base_url=base_url, api_key=api_key)
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=1024,
        temperature=0,
    )
    text = resp.choices[0].message.content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(text)


def get_prompt_variant(variant: str) -> tuple[str, str]:
    """Returns (prompt_text, schema_description)."""
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from semantic.llm_agent_memory import PROMPT_VARIANTS, SCHEMA_DESCRIPTION
    if variant not in PROMPT_VARIANTS:
        raise ValueError(f"Unknown variant: {variant}. Available: {list(PROMPT_VARIANTS.keys())}")
    return PROMPT_VARIANTS[variant], SCHEMA_DESCRIPTION


def evaluate_item(item: dict[str, Any], prompt_text: str, schema_description: str, provider: str) -> EvalResult:
    messages = build_extraction_message(item, prompt_text, schema_description)

    try:
        response = call_llm(messages, provider)
    except Exception as e:
        return EvalResult(
            item_id=item["id"][:8],
            interest_text=item["interest_text"],
            label=item["label"],
            bad_pattern=item.get("bad_pattern"),
            predicted_interest=False,
            predicted_interest_text=None,
            correct=(item["label"] == "bad"),
            raw_response={"error": str(e)},
        )

    interest_text = response.get("interest_text")
    candidate_type = response.get("candidate_type")
    predicted_interest = (candidate_type == "interest" or bool(interest_text))

    if item["label"] == "good":
        correct = predicted_interest
    else:
        correct = not predicted_interest

    return EvalResult(
        item_id=item["id"][:8],
        interest_text=item["interest_text"],
        label=item["label"],
        bad_pattern=item.get("bad_pattern"),
        predicted_interest=predicted_interest,
        predicted_interest_text=interest_text,
        correct=correct,
        raw_response=response,
    )


def compute_summary(results: list[EvalResult]) -> EvalSummary:
    tp = sum(1 for r in results if r.label == "good" and r.predicted_interest)
    tn = sum(1 for r in results if r.label == "bad" and not r.predicted_interest)
    fp = sum(1 for r in results if r.label == "bad" and r.predicted_interest)
    fn = sum(1 for r in results if r.label == "good" and not r.predicted_interest)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    fp_by_pattern: dict[str, int] = {}
    for r in results:
        if r.label == "bad" and r.predicted_interest and r.bad_pattern:
            fp_by_pattern[r.bad_pattern] = fp_by_pattern.get(r.bad_pattern, 0) + 1

    return EvalSummary(
        total=len(results),
        true_positives=tp,
        true_negatives=tn,
        false_positives=fp,
        false_negatives=fn,
        precision=precision,
        recall=recall,
        f1=f1,
        fp_by_pattern=fp_by_pattern,
    )


def print_report(summary: EvalSummary, results: list[EvalResult], variant: str) -> None:
    print("\n" + "=" * 70)
    print(f"INTEREST EXTRACTION QUALITY EVAL — variant: {variant}")
    print("=" * 70)
    print(f"\n  Total items: {summary.total}")
    print(f"  True Positives (good, extracted):     {summary.true_positives}")
    print(f"  True Negatives (bad, not extracted):  {summary.true_negatives}")
    print(f"  False Positives (bad, extracted):     {summary.false_positives}")
    print(f"  False Negatives (good, not extracted): {summary.false_negatives}")
    print(f"\n  Precision: {summary.precision:.1%}")
    print(f"  Recall:    {summary.recall:.1%}")
    print(f"  F1:        {summary.f1:.1%}")

    if summary.fp_by_pattern:
        print(f"\n  False positives by pattern:")
        for pattern, count in sorted(summary.fp_by_pattern.items(), key=lambda x: -x[1]):
            print(f"    {pattern}: {count}")

    # Show false positives
    fps = [r for r in results if r.label == "bad" and r.predicted_interest]
    if fps:
        print(f"\n" + "-" * 70)
        print(f"FALSE POSITIVES ({len(fps)} items — bad items incorrectly extracted)")
        print("-" * 70)
        for r in fps[:15]:
            print(f"  [{r.item_id}] pattern={r.bad_pattern}")
            print(f"    original: {r.interest_text[:80]}")
            print(f"    predicted: {r.predicted_interest_text[:80] if r.predicted_interest_text else 'N/A'}")
            print()

    # Show false negatives
    fns = [r for r in results if r.label == "good" and not r.predicted_interest]
    if fns:
        print(f"\n" + "-" * 70)
        print(f"FALSE NEGATIVES ({len(fns)} items — good items NOT extracted)")
        print("-" * 70)
        for r in fns:
            print(f"  [{r.item_id}] {r.interest_text[:80]}")
            print()

    print("=" * 70)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run interest extraction quality eval")
    parser.add_argument(
        "--variant",
        default="strict_typed_memory_v8b_work_refs_separate",
        help="Prompt variant to test",
    )
    parser.add_argument(
        "--provider",
        default="proxy",
        choices=["anthropic", "openai", "proxy"],
        help="LLM provider (proxy = local Anthropic proxy, same as production)",
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=CORPUS_FILE,
        help="Path to labeled corpus JSONL",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of items to evaluate (for quick testing)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Delay between LLM calls (seconds)",
    )
    args = parser.parse_args()

    prompt_text, schema_description = get_prompt_variant(args.variant)
    corpus = load_corpus(args.corpus)

    if args.limit:
        corpus = corpus[:args.limit]

    print(f"Running interest quality eval: {len(corpus)} items, variant={args.variant}, provider={args.provider}")

    results: list[EvalResult] = []
    for i, item in enumerate(corpus):
        result = evaluate_item(item, prompt_text, schema_description, args.provider)
        results.append(result)
        status = "OK" if result.correct else "WRONG"
        print(f"  [{i+1}/{len(corpus)}] {status} — {item['id'][:8]} ({item['label']})", end="")
        if not result.correct:
            if result.predicted_interest:
                print(f" — FP: extracted '{result.predicted_interest_text[:50]}'", end="")
            else:
                print(f" — FN: missed '{item['interest_text'][:50]}'", end="")
        print()
        if args.delay and i < len(corpus) - 1:
            time.sleep(args.delay)

    summary = compute_summary(results)
    print_report(summary, results, args.variant)

    # Write results to JSON for analysis
    output_path = Path(__file__).parent / "interest_quality_results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "variant": args.variant,
                "provider": args.provider,
                "summary": {
                    "total": summary.total,
                    "precision": summary.precision,
                    "recall": summary.recall,
                    "f1": summary.f1,
                    "tp": summary.true_positives,
                    "tn": summary.true_negatives,
                    "fp": summary.false_positives,
                    "fn": summary.false_negatives,
                    "fp_by_pattern": summary.fp_by_pattern,
                },
                "results": [
                    {
                        "item_id": r.item_id,
                        "label": r.label,
                        "bad_pattern": r.bad_pattern,
                        "predicted_interest": r.predicted_interest,
                        "correct": r.correct,
                        "interest_text": r.interest_text,
                        "predicted_interest_text": r.predicted_interest_text,
                    }
                    for r in results
                ],
            },
            f,
            indent=2,
            ensure_ascii=False,
        )
    print(f"\nResults written to {output_path}")

    # Exit code: 0 if precision >= 50%, else 1
    return 0 if summary.precision >= 0.5 else 1


if __name__ == "__main__":
    sys.exit(main())
