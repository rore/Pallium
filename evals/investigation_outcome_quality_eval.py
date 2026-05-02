"""Investigation outcome extraction quality eval.

Measures how well the extraction pipeline rejects bad investigation_outcome
patterns (generic titles, meta-verdicts, status updates, pointers) while
preserving good self-contained findings.

Two layers tested:
1. Deterministic gate (_investigation_payload_is_quality_viable) — token minimum
2. LLM extraction — prompt guidance for self-contained findings

Usage:
    # Gate-only (no LLM calls, instant):
    python -m evals.investigation_outcome_quality_eval --gate-only

    # Full re-extraction (requires LLM):
    python -m evals.investigation_outcome_quality_eval --cache-dir .local/llm-cache
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from core.models import SourceItem
from core.text import TOKEN_PATTERN
from semantic.common import SemanticExtraction, _investigation_payload_is_quality_viable


CORPUS_PATH = Path(__file__).parent / "investigation_outcome_quality_corpus.jsonl"


def load_corpus() -> list[dict]:
    return [json.loads(line) for line in open(CORPUS_PATH, encoding="utf-8") if line.strip()]


def run_gate_eval(corpus: list[dict]) -> dict:
    """Test the deterministic quality gate against the annotated corpus."""
    results = {"passed": 0, "failed": 0, "failures": []}

    for item in corpus:
        if item["expected_viable"]:
            continue

        investigation_text = item["investigation_text"] or ""
        tokens = TOKEN_PATTERN.findall(investigation_text)

        source_item = SourceItem(
            source_type=item["source_type"],
            source_id=item["source_id"],
            content_type=item["content_type"] or "text/plain",
            content=item["source_content"],
            role=item.get("role"),
            artifact_kind=item.get("artifact_kind"),
        )

        extraction = SemanticExtraction(
            summary="test",
            candidate_type="investigation_outcome",
            investigation_text=investigation_text,
            investigation_evidence_text=investigation_text,
            key_finding_text=investigation_text,
            rationale_text=item.get("rationale"),
        )

        is_viable = _investigation_payload_is_quality_viable(extraction, source_item)

        if not is_viable:
            results["passed"] += 1
        else:
            results["failed"] += 1
            results["failures"].append({
                "index": item["index"],
                "pattern": item["failure_pattern"],
                "tokens": len(tokens),
                "text": investigation_text[:80],
            })

    # Also check no regressions on good items
    regressions = []
    for item in corpus:
        if not item["expected_viable"]:
            continue

        investigation_text = item["investigation_text"] or ""

        source_item = SourceItem(
            source_type=item["source_type"],
            source_id=item["source_id"],
            content_type=item["content_type"] or "text/plain",
            content=item["source_content"],
            role=item.get("role"),
            artifact_kind=item.get("artifact_kind"),
        )

        extraction = SemanticExtraction(
            summary="test",
            candidate_type="investigation_outcome",
            investigation_text=investigation_text,
            investigation_evidence_text=investigation_text,
            key_finding_text=investigation_text,
            rationale_text=item.get("rationale"),
        )

        is_viable = _investigation_payload_is_quality_viable(extraction, source_item)
        if not is_viable:
            regressions.append({
                "index": item["index"],
                "tokens": len(TOKEN_PATTERN.findall(investigation_text)),
                "text": investigation_text[:80],
            })

    results["regressions"] = regressions
    return results


def run_llm_eval(corpus: list[dict], cache_dir: str | None = None) -> dict:
    """Re-extract from source items and check investigation_outcome quality."""
    from app.config import AppConfig
    from app.dependencies import build_llm_provider
    from semantic.llm_agent_memory import LLMAgentMemoryPlugin

    config = AppConfig.from_env()
    package = config.package_config(config.default_use_case)
    if not package.llm_provider or not package.model:
        raise ValueError(f"{config.default_use_case} is not configured with a real provider/model")
    provider = build_llm_provider(config, provider_name=package.llm_provider, model=package.model)
    plugin = LLMAgentMemoryPlugin(provider=provider)

    results = {
        "bad_now_rejected": 0,
        "bad_still_extracted": 0,
        "good_still_extracted": 0,
        "good_now_rejected": 0,
        "bad_failures": [],
        "good_regressions": [],
    }

    for item in corpus:
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
        except Exception as e:
            print(f"  SKIP #{item['index']}: {type(e).__name__}: {str(e)[:60]}")
            continue

        extraction = trace.extraction
        has_investigation = (
            extraction.candidate_type == "investigation_outcome"
            and extraction.investigation_text
        )

        if not item["expected_viable"]:
            if not has_investigation:
                results["bad_now_rejected"] += 1
            else:
                results["bad_still_extracted"] += 1
                results["bad_failures"].append({
                    "index": item["index"],
                    "pattern": item["failure_pattern"],
                    "original_text": item["investigation_text"][:60],
                    "new_text": (extraction.investigation_text or "")[:60],
                })
        else:
            if has_investigation:
                results["good_still_extracted"] += 1
            else:
                results["good_now_rejected"] += 1
                results["good_regressions"].append({
                    "index": item["index"],
                    "original_text": item["investigation_text"][:60],
                    "new_candidate_type": extraction.candidate_type,
                })

    return results


def main():
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Investigation outcome quality eval")
    parser.add_argument("--gate-only", action="store_true", help="Only test deterministic gate")
    parser.add_argument("--cache-dir", type=str, help="LLM cache directory")
    args = parser.parse_args()

    corpus = load_corpus()
    bad_count = sum(1 for c in corpus if not c["expected_viable"])
    good_count = sum(1 for c in corpus if c["expected_viable"])

    print(f"Corpus: {len(corpus)} items ({bad_count} bad, {good_count} good)")
    print()

    # Always run gate eval
    print("=" * 60)
    print("DETERMINISTIC GATE EVAL")
    print("=" * 60)
    gate_results = run_gate_eval(corpus)
    gate_total_bad = gate_results["passed"] + gate_results["failed"]
    print(f"Bad items rejected by gate: {gate_results['passed']}/{gate_total_bad} "
          f"({gate_results['passed']/gate_total_bad*100:.0f}%)")
    print(f"Good items regressed: {len(gate_results['regressions'])}/{good_count}")

    if gate_results["failures"]:
        print(f"\nBad items that PASS the gate ({gate_results['failed']} items):")
        for f in gate_results["failures"]:
            print(f"  #{f['index']:2} [{f['pattern']:15}] [{f['tokens']:2} tok] {f['text']}")

    if gate_results["regressions"]:
        print(f"\nREGRESSIONS - good items rejected by gate:")
        for r in gate_results["regressions"]:
            print(f"  #{r['index']:2} [{r['tokens']:2} tok] {r['text']}")

    if args.gate_only:
        return

    # LLM eval
    print()
    print("=" * 60)
    print("LLM RE-EXTRACTION EVAL")
    print("=" * 60)
    llm_results = run_llm_eval(corpus, cache_dir=args.cache_dir)

    print(f"Bad items now rejected by LLM: {llm_results['bad_now_rejected']}/{bad_count} "
          f"({llm_results['bad_now_rejected']/bad_count*100:.0f}%)")
    print(f"Good items still extracted: {llm_results['good_still_extracted']}/{good_count} "
          f"({llm_results['good_still_extracted']/good_count*100:.0f}%)")

    if llm_results["bad_failures"]:
        print(f"\nBad items STILL extracted ({llm_results['bad_still_extracted']}):")
        for f in llm_results["bad_failures"]:
            print(f"  #{f['index']:2} [{f['pattern']:15}] {f['new_text']}")

    if llm_results["good_regressions"]:
        print(f"\nREGRESSIONS - good items no longer extracted ({llm_results['good_now_rejected']}):")
        for r in llm_results["good_regressions"]:
            print(f"  #{r['index']:2} [{r['new_candidate_type']}] {r['original_text']}")

    # Summary
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    total_bad_caught = llm_results["bad_now_rejected"]
    total_good_kept = llm_results["good_still_extracted"]
    print(f"Precision improvement: {total_bad_caught}/{bad_count} bad rejected ({total_bad_caught/bad_count*100:.0f}%)")
    print(f"Recall preservation: {total_good_kept}/{good_count} good kept ({total_good_kept/good_count*100:.0f}%)")


if __name__ == "__main__":
    main()
