"""Thread-level decision extraction prompt variant eval.

Tests prompt variants for improving decision extraction from multi-turn design
discussions. Measures recall (expected decisions found), precision (no hallucinations),
and regression (existing good decisions still pass).

Usage:
    python -m evals.thread_extraction_prompt_eval --cache-dir .local/llm-cache
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from app.config import AppConfig
from app.dependencies import build_llm_provider
from providers.llm.base import LLMProvider
from semantic.agent_conversation_memory_threads import (
    THREAD_SUMMARY_MAX_TEXT_CHARS,
    THREAD_SUMMARY_SYSTEM_PROMPT,
    _validate_thread_decisions,
    _validate_thread_investigations,
)
from semantic.common import _normalize_for_containment

CORPUS_PATH = Path(__file__).parent / "thread_extraction_design_discussion_corpus.jsonl"
RESULTS_PATH = Path(__file__).parent / "thread_extraction_prompt_results.json"

SCHEMA_DECISIONS_AND_INVESTIGATIONS = json.dumps({
    "summary": "string",
    "content_quality": "string",
    "retrieval_context": "string or null",
    "decisions": [{"decision_text": "string (exact quote)", "evidence": "string (exact quote)"}],
    "investigations": [{"investigation_text": "string (self-contained finding, exact quote)", "evidence": "string (exact quote)"}],
}, indent=2)

SCHEMA_SYNTHESIZED_DECISIONS = json.dumps({
    "summary": "string",
    "content_quality": "string",
    "retrieval_context": "string or null",
    "decisions": [{"decision_text": "string (concise statement of what was decided)", "evidence": "string (exact quote)"}],
    "investigations": [{"investigation_text": "string (self-contained finding, exact quote)", "evidence": "string (exact quote)"}],
}, indent=2)


# ---------------------------------------------------------------------------
# LLM cache
# ---------------------------------------------------------------------------

class LLMCache:
    def __init__(self, cache_dir: Path | None):
        self._dir = cache_dir
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> dict | None:
        if not self._dir:
            return None
        path = self._dir / f"{key}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return None

    def put(self, key: str, value: dict):
        if not self._dir:
            return
        path = self._dir / f"{key}.json"
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _cache_key(variant: str, thread_id: str) -> str:
    h = hashlib.sha256(f"{variant}:{thread_id}".encode()).hexdigest()[:16]
    return f"thread_decision_eval_{variant}_{h}"


# ---------------------------------------------------------------------------
# Prompt variants
# ---------------------------------------------------------------------------

VARIANT_A_SYSTEM_PROMPT = THREAD_SUMMARY_SYSTEM_PROMPT

VARIANT_B_DECISION_BLOCK = (
    "For decisions: identify choices that were made AND committed during the thread. "
    "A decision exists when a specific approach was proposed AND then confirmed, accepted, or explicitly chosen by the user. "
    "Implementation is not required — explicit user confirmation is sufficient. "
    "Look for directional commitments: the user choosing approach A over B, confirming a proposed plan, or explicitly approving a recommendation. "
    "Each decision must be self-contained: comprehensible when read in a different conversation weeks later with no surrounding context. "
    "The decision_text must name WHAT was decided about — the subject or system. "
    "decision_text should be a concise self-contained statement of what was decided (synthesized from the discussion — does not need to be a verbatim quote). "
    "evidence must be an EXACT QUOTE copied verbatim from the thread items that demonstrates the commitment. Do not paraphrase the evidence. "
    "Not decisions: unresolved discussion, proposals without follow-through, questions, status updates, preferences without implementation. "
    "Return an empty array if no decisions were committed in this thread. "
)

VARIANT_C_DECISION_BLOCK = (
    VARIANT_B_DECISION_BLOCK +
    "Design decisions also count: when a user explicitly chooses one approach over alternatives after discussion, that is a committed decision even if code has not been written yet. "
)

VARIANT_D_INVESTIGATION_ADDITION = (
    "Quantitative findings also count: when analysis produces specific numeric results with conclusions "
    "(precision rates, noise percentages, performance measurements), these are investigation outcomes "
    "even if no explicit 'investigation' was declared. "
)


def _build_variant_prompt(variant: str) -> str:
    base = THREAD_SUMMARY_SYSTEM_PROMPT
    # Find the decision block boundaries in the base prompt
    decision_start_marker = "For decisions: identify choices"
    investigation_start_marker = "For investigations: identify resolved findings"

    decision_start = base.index(decision_start_marker)
    investigation_start = base.index(investigation_start_marker)

    prefix = base[:decision_start]
    investigation_block = base[investigation_start:]

    if variant == "baseline":
        return base
    elif variant == "B_soften_decision":
        return prefix + VARIANT_B_DECISION_BLOCK + investigation_block
    elif variant == "C_design_decision":
        return prefix + VARIANT_C_DECISION_BLOCK + investigation_block
    elif variant == "D_with_quantitative":
        return prefix + VARIANT_C_DECISION_BLOCK + investigation_block + " " + VARIANT_D_INVESTIGATION_ADDITION
    else:
        raise ValueError(f"Unknown variant: {variant}")


def _get_schema(variant: str) -> str:
    if variant == "baseline":
        return SCHEMA_DECISIONS_AND_INVESTIGATIONS
    return SCHEMA_SYNTHESIZED_DECISIONS


VARIANTS = ["baseline", "B_soften_decision", "C_design_decision", "D_with_quantitative"]


# ---------------------------------------------------------------------------
# Corpus loading and thread text construction
# ---------------------------------------------------------------------------

def load_corpus() -> list[dict]:
    return [json.loads(line) for line in open(CORPUS_PATH, encoding="utf-8") if line.strip()]


def _build_thread_text(items: list[dict]) -> str:
    """Build thread text from items, matching production _build_thread_material format."""
    lines = []
    for item in items:
        role = item.get("role") or "unknown"
        artifact_kind = item.get("artifact_kind") or "message"
        content = (item.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"{role}/{artifact_kind}: {content}")
    thread_text = "\n".join(lines)
    if len(thread_text) > THREAD_SUMMARY_MAX_TEXT_CHARS:
        thread_text = "[earlier thread items truncated for token budget]\n" + thread_text[-THREAD_SUMMARY_MAX_TEXT_CHARS:].lstrip()
    return thread_text


# ---------------------------------------------------------------------------
# Scoring: keyword-based recall matching
# ---------------------------------------------------------------------------

def _matches_expected(extracted_text: str, expected: dict) -> bool:
    """Check if extracted text matches an expected item via keyword overlap."""
    keywords = expected.get("keywords", [])
    if not keywords:
        return False
    text_lower = extracted_text.lower()
    matched = sum(1 for kw in keywords if kw.lower() in text_lower)
    return matched >= 3


def score_recall(
    extracted_decisions: list[dict],
    extracted_investigations: list[dict],
    expected_decisions: list[dict],
    expected_investigations: list[dict],
) -> dict:
    """Score recall: how many expected items were found."""
    decision_found = 0
    decision_missed = []
    for exp in expected_decisions:
        combined_texts = [
            (d.get("decision_text", "") + " " + d.get("evidence", ""))
            for d in extracted_decisions
        ]
        if any(_matches_expected(t, exp) for t in combined_texts):
            decision_found += 1
        else:
            decision_missed.append(exp["description"])

    investigation_found = 0
    investigation_missed = []
    for exp in expected_investigations:
        combined_texts = [
            (inv.get("investigation_text", "") + " " + inv.get("evidence", ""))
            for inv in extracted_investigations
        ]
        if any(_matches_expected(t, exp) for t in combined_texts):
            investigation_found += 1
        else:
            investigation_missed.append(exp["description"])

    total_expected = len(expected_decisions) + len(expected_investigations)
    total_found = decision_found + investigation_found

    return {
        "decision_recall": decision_found / len(expected_decisions) if expected_decisions else 1.0,
        "investigation_recall": investigation_found / len(expected_investigations) if expected_investigations else 1.0,
        "overall_recall": total_found / total_expected if total_expected > 0 else 1.0,
        "decision_missed": decision_missed,
        "investigation_missed": investigation_missed,
    }


def score_regression(
    extracted_decisions: list[dict],
    extracted_investigations: list[dict],
    regression_decisions: list[dict],
    regression_investigations: list[dict],
) -> dict:
    """Score regression: all regression items must still be found."""
    decision_found = 0
    decision_failed = []
    for reg in regression_decisions:
        combined_texts = [
            (d.get("decision_text", "") + " " + d.get("evidence", ""))
            for d in extracted_decisions
        ]
        if any(_matches_expected(t, reg) for t in combined_texts):
            decision_found += 1
        else:
            decision_failed.append(reg["description"])

    investigation_found = 0
    investigation_failed = []
    for reg in regression_investigations:
        combined_texts = [
            (inv.get("investigation_text", "") + " " + inv.get("evidence", ""))
            for inv in extracted_investigations
        ]
        if any(_matches_expected(t, reg) for t in combined_texts):
            investigation_found += 1
        else:
            investigation_failed.append(reg["description"])

    total_regression = len(regression_decisions) + len(regression_investigations)
    total_found = decision_found + investigation_found

    return {
        "regression_pass": len(decision_failed) == 0 and len(investigation_failed) == 0,
        "regression_found": total_found,
        "regression_total": total_regression,
        "regression_failed": decision_failed + investigation_failed,
    }


def score_precision(
    extracted_decisions: list[dict],
    extracted_investigations: list[dict],
    all_expected: list[dict],
    thread_text: str,
    variant: str,
) -> dict:
    """Score precision: fraction of extracted items with grounded evidence.

    For baseline: both decision_text/investigation_text AND evidence must be grounded.
    For non-baseline: only evidence must be grounded (synthesized text is allowed).
    """
    total_extracted = len(extracted_decisions) + len(extracted_investigations)
    if total_extracted == 0:
        return {"precision": 1.0, "total_extracted": 0, "grounded": 0, "ungrounded": []}

    normalized_thread = _normalize_for_containment(thread_text)
    grounded_count = 0
    ungrounded = []

    for d in extracted_decisions:
        ev = d.get("evidence", "")
        ev_grounded = _normalize_for_containment(ev) in normalized_thread if ev else False
        if variant == "baseline":
            dt = d.get("decision_text", "")
            dt_grounded = _normalize_for_containment(dt) in normalized_thread if dt else False
            if dt_grounded and ev_grounded:
                grounded_count += 1
            else:
                ungrounded.append(f"decision: {d.get('decision_text', '')[:60]}")
        else:
            if ev_grounded:
                grounded_count += 1
            else:
                ungrounded.append(f"decision: {d.get('decision_text', '')[:60]}")

    for inv in extracted_investigations:
        ev = inv.get("evidence", "")
        ev_grounded = _normalize_for_containment(ev) in normalized_thread if ev else False
        if variant == "baseline":
            it = inv.get("investigation_text", "")
            it_grounded = _normalize_for_containment(it) in normalized_thread if it else False
            if it_grounded and ev_grounded:
                grounded_count += 1
            else:
                ungrounded.append(f"investigation: {inv.get('investigation_text', '')[:60]}")
        else:
            if ev_grounded:
                grounded_count += 1
            else:
                ungrounded.append(f"investigation: {inv.get('investigation_text', '')[:60]}")

    return {
        "precision": grounded_count / total_extracted if total_extracted > 0 else 1.0,
        "total_extracted": total_extracted,
        "grounded": grounded_count,
        "ungrounded": ungrounded[:5],
    }


# ---------------------------------------------------------------------------
# Validation (variant-aware)
# ---------------------------------------------------------------------------

def validate_decisions(raw_decisions: list[dict], thread_text: str, variant: str) -> list[dict]:
    """Validate decisions — for non-baseline variants, skip decision_text grounding."""
    if variant == "baseline":
        return _validate_thread_decisions(raw_decisions, thread_text)

    # For variants B/C/D: ground on evidence only, still apply substance filters
    if not isinstance(raw_decisions, list):
        return []
    normalized_thread = _normalize_for_containment(thread_text)
    grounded = []
    for d in raw_decisions:
        if not isinstance(d, dict):
            continue
        dt = d.get("decision_text", "")
        ev = d.get("evidence", "")
        if not (dt and ev):
            continue
        # Evidence must be grounded (exact substring)
        if _normalize_for_containment(ev) not in normalized_thread:
            continue
        # Substance filters (same as production)
        norm_dt = _normalize_for_containment(dt)
        norm_ev = _normalize_for_containment(ev)
        if len(norm_dt) < 30:
            continue
        if norm_dt == norm_ev:
            continue
        if len(norm_dt) < 50 and norm_dt in norm_ev and norm_dt != norm_ev:
            continue
        grounded.append({"decision_text": dt, "evidence": ev})
    return grounded


def validate_investigations(raw_investigations: list[dict], thread_text: str, variant: str) -> list[dict]:
    """Validate investigations — for non-baseline variants, skip investigation_text grounding."""
    if variant == "baseline":
        return _validate_thread_investigations(raw_investigations, thread_text)

    # For variants B/C/D: ground on evidence only, still apply substance filters
    if not isinstance(raw_investigations, list):
        return []
    normalized_thread = _normalize_for_containment(thread_text)
    grounded = []
    for d in raw_investigations:
        if not isinstance(d, dict):
            continue
        it = d.get("investigation_text", "")
        ev = d.get("evidence", "")
        if not (it and ev):
            continue
        # Evidence must be grounded (exact substring)
        if _normalize_for_containment(ev) not in normalized_thread:
            continue
        # Substance filters (same as production)
        norm_it = _normalize_for_containment(it)
        norm_ev = _normalize_for_containment(ev)
        if len(norm_it) < 40:
            continue
        if norm_it == norm_ev:
            continue
        if len(norm_it) < 60 and norm_it in norm_ev and norm_it != norm_ev:
            continue
        grounded.append({"investigation_text": it, "evidence": ev})
    return grounded


# ---------------------------------------------------------------------------
# Main eval loop
# ---------------------------------------------------------------------------

def run_eval(provider: LLMProvider, cache: LLMCache) -> dict:
    corpus = load_corpus()
    results = {}

    for variant in VARIANTS:
        print(f"\n{'='*60}")
        print(f"  Variant: {variant}")
        print(f"{'='*60}")

        system_prompt = _build_variant_prompt(variant)
        schema = _get_schema(variant)
        variant_results = []

        for entry in corpus:
            thread_id = entry["thread_id"]
            items = entry["items"]
            thread_text = _build_thread_text(items)

            user_prompt = (
                "Summarize this thread conservatively for later recall. "
                "Use only explicit information from the provided content.\n\n"
                f"Thread ref: {thread_id}\n\n"
                f"Thread items:\n{thread_text}"
            )

            cache_key = _cache_key(variant, thread_id)
            cached = cache.get(cache_key)
            if cached:
                response = cached
                print(f"  [{thread_id}] cached")
            else:
                try:
                    llm_response = provider.generate_json(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        schema_description=schema,
                    )
                    response = llm_response.parsed_json
                    cache.put(cache_key, response)
                    print(f"  [{thread_id}] called LLM")
                except Exception as e:
                    print(f"  [{thread_id}] ERROR: {e}")
                    variant_results.append({"thread_id": thread_id, "error": str(e)})
                    continue

            # Extract and validate
            raw_decisions = response.get("decisions") or []
            raw_investigations = response.get("investigations") or []

            valid_decisions = validate_decisions(raw_decisions, thread_text, variant)
            valid_investigations = validate_investigations(raw_investigations, thread_text, variant)

            # Score
            recall = score_recall(
                valid_decisions, valid_investigations,
                entry.get("expected_decisions", []),
                entry.get("expected_investigations", []),
            )
            regression = score_regression(
                valid_decisions, valid_investigations,
                entry.get("regression_decisions", []),
                entry.get("regression_investigations", []),
            )
            precision = score_precision(
                valid_decisions, valid_investigations,
                entry.get("expected_decisions", []) + entry.get("regression_decisions", []),
                thread_text, variant,
            )

            entry_result = {
                "thread_id": thread_id,
                "raw_decisions": len(raw_decisions),
                "valid_decisions": len(valid_decisions),
                "raw_investigations": len(raw_investigations),
                "valid_investigations": len(valid_investigations),
                "recall": recall,
                "regression": regression,
                "precision": precision,
                "decisions_detail": [
                    {"decision_text": d["decision_text"][:100], "evidence": d["evidence"][:80]}
                    for d in valid_decisions
                ],
                "investigations_detail": [
                    {"investigation_text": inv["investigation_text"][:100], "evidence": inv["evidence"][:80]}
                    for inv in valid_investigations
                ],
            }
            variant_results.append(entry_result)

            # Print summary
            print(f"    decisions: {len(raw_decisions)} raw -> {len(valid_decisions)} valid")
            print(f"    investigations: {len(raw_investigations)} raw -> {len(valid_investigations)} valid")
            print(f"    recall: {recall['overall_recall']:.0%} (D:{recall['decision_recall']:.0%} I:{recall['investigation_recall']:.0%})")
            if recall["decision_missed"]:
                print(f"    missed decisions: {recall['decision_missed']}")
            if recall["investigation_missed"]:
                print(f"    missed investigations: {recall['investigation_missed']}")
            if not regression["regression_pass"]:
                print(f"    REGRESSION: {regression['regression_failed']}")
            print(f"    precision: {precision['precision']:.0%} ({precision['grounded']}/{precision['total_extracted']} grounded)")

        results[variant] = variant_results

    return results


def print_summary(results: dict):
    print(f"\n\n{'='*70}")
    print("  SUMMARY")
    print(f"{'='*70}\n")

    header = f"{'Variant':<25} {'Dec Recall':<12} {'Inv Recall':<12} {'Precision':<12} {'Regression':<12}"
    print(header)
    print("-" * len(header))

    for variant, entries in results.items():
        # Aggregate across corpus entries
        all_dec_recall = []
        all_inv_recall = []
        all_precision = []
        all_regression_pass = True

        for entry in entries:
            if "error" in entry:
                continue
            r = entry["recall"]
            if entry.get("thread_id") == "design-review-arc":
                all_dec_recall.append(r["decision_recall"])
                all_inv_recall.append(r["investigation_recall"])
            all_precision.append(entry["precision"]["precision"])
            if not entry["regression"]["regression_pass"]:
                all_regression_pass = False

        avg_dec_recall = sum(all_dec_recall) / len(all_dec_recall) if all_dec_recall else 0
        avg_inv_recall = sum(all_inv_recall) / len(all_inv_recall) if all_inv_recall else 0
        avg_precision = sum(all_precision) / len(all_precision) if all_precision else 0
        reg_str = "PASS" if all_regression_pass else "FAIL"

        print(f"{variant:<25} {avg_dec_recall:<12.0%} {avg_inv_recall:<12.0%} {avg_precision:<12.0%} {reg_str:<12}")

    print()


def main():
    parser = argparse.ArgumentParser(description="Thread decision extraction prompt eval")
    parser.add_argument("--cache-dir", type=str, default=None, help="LLM response cache directory")
    args = parser.parse_args()

    cache_dir = Path(args.cache_dir) if args.cache_dir else None
    cache = LLMCache(cache_dir)

    config = AppConfig.from_env()
    provider_config = config.provider_config("hai_anthropic")
    from providers.llm.anthropic_claude import AnthropicClaudeLLMProvider
    provider = AnthropicClaudeLLMProvider(
        provider_name="hai_anthropic",
        model="anthropic--claude-sonnet-latest",
        base_url=provider_config.base_url,
        api_key=provider_config.api_key,
        timeout_seconds=provider_config.timeout_seconds,
        retry_policy=provider_config.retry_policy,
        auth_style=provider_config.auth_style,
        max_tokens=4096,
    )

    results = run_eval(provider, cache)
    print_summary(results)

    # Save detailed results
    RESULTS_PATH.write_text(
        json.dumps(results, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    print(f"Detailed results saved to {RESULTS_PATH}")


if __name__ == "__main__":
    main()
