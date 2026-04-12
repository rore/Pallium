"""Shared evaluation utilities for Pallium benchmark runners.

Contains constants and functions common to LoCoMo, MABench, and LongMemEval
benchmark runners. Extracted to prevent copy-paste drift between runners.
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
from pathlib import Path
from typing import Any

from providers.llm.base import LLMProvider
from app.config import AppConfig
from app.dependencies import build_llm_provider
from providers.llm.cached import CachedLLMProvider
from evals.eval_rate_limiter import TokenBucketRateLimiter
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared schemas
# ---------------------------------------------------------------------------

ANSWER_SCHEMA = '{"answer":"string","reasoning":"string"}'
JUDGE_SCHEMA = '{"correct":"boolean","reasoning":"string"}'
GOLD_IN_CONTEXT_SCHEMA = '{"present":"boolean","reasoning":"string"}'

COMBINED_JUDGE_SCHEMA = '{"correct":"boolean","judge_reasoning":"string","gold_in_context":"boolean","context_reasoning":"string"}'

GOLD_IN_CONTEXT_SYSTEM_PROMPT = """\
Determine whether the retrieved context contains sufficient information to answer the question \
with the given gold answer. You are NOT judging whether the context is well-written or complete — \
only whether the key facts from the gold answer are present somewhere in the context.

Be generous: if the context contains the same information in different words, a different date format, \
or a paraphrase, that counts as present. For multi-part gold answers (e.g., "A, B, and C"), ALL parts \
must be present for the answer to count as present.

For "not mentioned" gold answers: if the context truly lacks the information and the gold answer says \
the information was not mentioned, return present=true (the absence is correctly represented).

Return a JSON object with:
- present: true if the context contains enough information to produce the gold answer, false otherwise
- reasoning: one sentence explanation (keep it short)\
"""


# ---------------------------------------------------------------------------
# Vector index utilities
# ---------------------------------------------------------------------------


def copy_vector_index(src: Path, dst: Path) -> None:
    """Copy all vector index files (main + .idmap.json + .meta.json)."""
    for suffix in ("", ".idmap.json", ".meta.json"):
        src_file = Path(f"{src}{suffix}")
        dst_file = Path(f"{dst}{suffix}")
        if src_file.exists():
            shutil.copy2(src_file, dst_file)


# ---------------------------------------------------------------------------
# Retrieval result helpers
# ---------------------------------------------------------------------------


def compact_results(memory_payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Create compact result records for verbose output."""
    compact: list[dict[str, Any]] = []
    for r in memory_payload.get("results", []):
        entry: dict[str, Any] = {
            "kind": r.get("result_kind"),
            "type": r.get("type"),
            "score": r.get("score"),
            "retrieval_source": r.get("retrieval_source"),
        }
        if r.get("result_kind") == "source_hit":
            entry["excerpt"] = (r.get("excerpt") or "")[:150]
            entry["occurred_at"] = r.get("occurred_at")
        else:
            payload = r.get("payload") or {}
            entry["text"] = (
                payload.get("statement")
                or payload.get("summary")
                or payload.get("decision")
                or payload.get("carry_forward_answer")
                or ""
            )[:150]
        compact.append(entry)
    return compact


def retrieval_summary(memory_payload: dict[str, Any]) -> dict[str, Any]:
    """Summarize retrieval results by type."""
    results = memory_payload.get("results", [])
    memory_hits = [r for r in results if r.get("result_kind") == "memory_hit"]
    source_hits = [r for r in results if r.get("result_kind") == "source_hit"]
    memory_types = sorted(
        {r.get("type", "") for r in memory_hits if r.get("type")}
    )
    return {
        "total_results": len(results),
        "memory_hits": len(memory_hits),
        "source_hits": len(source_hits),
        "memory_types": memory_types,
    }


def format_retrieved_context(memory_payload: dict[str, Any]) -> str:
    """Format Pallium retrieval results for the justifier LLM.

    Uses the fullest format: memory blocks with actor/date evidence,
    raw memory hits with dates, source hits with actor and date.
    """
    parts: list[str] = []

    # Primary: injectable blocks (the curated output Pallium thinks should be injected).
    for i, block in enumerate(memory_payload.get("injectable_blocks", [])):
        block_type = (
            block.get("block_type") or block.get("memory_type") or "memory"
        )
        title = block.get("title", "")
        text = block.get("text", "")
        evidence = block.get("evidence", [])

        part = f"[Memory {i + 1} ({block_type})]"
        if title:
            part += f" {title}"
        part += f"\n{text}"

        if evidence:
            dates = [
                e.get("occurred_at", "")
                for e in evidence
                if e.get("occurred_at")
            ]
            actors = [
                e.get("actor_ref", "")
                for e in evidence
                if e.get("actor_ref")
            ]
            if dates:
                part += f"\n(Evidence dates: {', '.join(dates[:3])})"
            if actors:
                part += f"\n(Speakers: {', '.join(sorted(set(actors)))})"
        parts.append(part)

    # Secondary: raw retrieval results for additional grounding.
    for i, result in enumerate(memory_payload.get("results", [])):
        if result.get("result_kind") == "memory_hit":
            payload = result.get("payload") or {}
            summary = (
                payload.get("statement")
                or payload.get("carry_forward_answer")
                or payload.get("decision")
                or payload.get("investigation_outcome")
                or payload.get("summary")
                or payload.get("description")
                or ""
            )
            if summary:
                # Prepend subject for atomic_fact / fact_summary so the
                # justifier can distinguish otherwise-identical statements.
                subject = payload.get("subject", "")
                if subject and subject.lower() not in summary.lower():
                    summary = f"{subject}: {summary}"
                occurred_at = result.get("occurred_at", "")
                mem_type = result.get("type", "memory")
                date_note = f" (date: {occurred_at})" if occurred_at else ""
                parts.append(
                    f"[Fact {i + 1} ({mem_type})] {summary}{date_note}"
                )
        elif result.get("result_kind") == "source_hit":
            # Prefer full source content (enriched by benchmark runners)
            # over the 160-char excerpt from the production API.
            excerpt = result.get("source_content") or result.get("excerpt", "")
            if excerpt:
                occurred_at = result.get("occurred_at", "")
                actor = result.get("actor_ref", "")
                date_note = f" (date: {occurred_at})" if occurred_at else ""
                parts.append(
                    f"[Source {i + 1}] {actor}: {excerpt}{date_note}"
                )

    return "\n\n".join(parts) if parts else "No relevant memories found."


# ---------------------------------------------------------------------------
# Gold-in-context check
# ---------------------------------------------------------------------------


def gold_in_context(
    gold_answer: str,
    context: str,
    *,
    provider: LLMProvider | None = None,
    question: str = "",
    rate_limiter: TokenBucketRateLimiter | None = None,
) -> bool:
    """Check if the gold answer's key information is present in the retrieved context.

    Uses LLM-as-judge when a provider is given, otherwise falls back to token overlap.
    """
    if provider is not None and question:
        return gold_in_context_llm(
            provider=provider,
            question=question,
            gold_answer=gold_answer,
            context=context,
            rate_limiter=rate_limiter,
        )
    # Fallback: simple token overlap heuristic.
    gold_lower = gold_answer.lower().strip()
    context_lower = context.lower()
    if gold_lower in context_lower:
        return True
    gold_tokens = {
        t for t in gold_lower.split()
        if len(t) >= 3 and t not in {"the", "and", "for", "was", "that", "with", "from", "she", "her", "his"}
    }
    if not gold_tokens:
        return False
    matched = sum(1 for t in gold_tokens if t in context_lower)
    return matched >= len(gold_tokens) * 0.6


def gold_in_context_llm(
    *,
    provider: LLMProvider,
    question: str,
    gold_answer: str,
    context: str,
    rate_limiter: TokenBucketRateLimiter | None = None,
) -> bool:
    """LLM-based check: does the context contain the information needed for the gold answer?"""
    user_prompt = (
        f"Question: {question}\n"
        f"Gold answer: {gold_answer}\n\n"
        f"Retrieved context:\n{context[:4000]}"
    )
    try:
        if rate_limiter:
            rate_limiter.acquire()
        response = provider.generate_json(
            system_prompt=GOLD_IN_CONTEXT_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            schema_description=GOLD_IN_CONTEXT_SCHEMA,
        )
        present = response.parsed_json.get("present", False)
        if isinstance(present, str):
            present = present.lower() in {"true", "yes", "1"}
        return bool(present)
    except Exception:
        logger.warning("Gold-in-context LLM check failed, falling back to heuristic")
        return gold_in_context(gold_answer, context)


# ---------------------------------------------------------------------------
# Combined judge + gold-in-context (merged into one LLM call)
# ---------------------------------------------------------------------------


def combined_judge(
    *,
    provider: LLMProvider,
    question: str,
    gold_answer: str,
    predicted_answer: str,
    retrieved_context: str,
    judge_system_prompt: str,
    rate_limiter: TokenBucketRateLimiter | None = None,
) -> dict[str, Any]:
    """Merged judge + gold-in-context check in a single LLM call.

    Returns dict with: correct (bool), judge_reasoning (str),
    gold_in_context (bool), context_reasoning (str).
    """
    system_prompt = (
        "You must perform two independent evaluation tasks on the same question.\n"
        "Evaluate each task separately — do not let one task's result influence the other.\n"
        "\n"
        "=== TASK 1: JUDGE THE GENERATED ANSWER ===\n"
        f"{judge_system_prompt}\n"
        "\n"
        "=== TASK 2: CHECK IF GOLD ANSWER INFORMATION IS IN THE RETRIEVED CONTEXT ===\n"
        "Determine whether the retrieved context contains sufficient information to answer "
        "the question with the given gold answer. Be generous: paraphrases, different formats, "
        "or rewordings count as present. For multi-part answers, ALL parts must be present.\n"
        "For \"not mentioned\" gold answers: if the context correctly lacks the information, "
        "return gold_in_context=true.\n"
        "\n"
        "=== INPUT ===\n"
        "Return a single JSON object with all four fields."
    )
    user_prompt = (
        f"Question: {question}\n"
        f"Gold answer: {gold_answer}\n"
        f"Generated answer: {predicted_answer}\n\n"
        f"Retrieved context:\n{retrieved_context[:4000]}"
    )
    try:
        if rate_limiter:
            rate_limiter.acquire()
        response = provider.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema_description=COMBINED_JUDGE_SCHEMA,
        )
        parsed = response.parsed_json

        correct = parsed.get("correct", False)
        if isinstance(correct, str):
            correct = correct.lower() in {"true", "yes", "1"}

        gold_in_ctx = parsed.get("gold_in_context", False)
        if isinstance(gold_in_ctx, str):
            gold_in_ctx = gold_in_ctx.lower() in {"true", "yes", "1"}

        return {
            "correct": bool(correct),
            "judge_reasoning": str(parsed.get("judge_reasoning", "")),
            "gold_in_context": bool(gold_in_ctx),
            "context_reasoning": str(parsed.get("context_reasoning", "")),
        }
    except Exception as exc:
        # Fall back to heuristic for gold_in_context to avoid corrupting
        # the metric with transient LLM failures.
        gic_fallback = gold_in_context(gold_answer, retrieved_context)
        return {
            "correct": False,
            "judge_reasoning": f"[ERROR: {exc}]",
            "gold_in_context": gic_fallback,
            "context_reasoning": f"[ERROR: {exc}] (heuristic fallback)",
        }


# ---------------------------------------------------------------------------
# Answer generation (justifier)
# ---------------------------------------------------------------------------


def generate_answer(
    *,
    provider: LLMProvider,
    question: str,
    retrieved_context: str,
    preamble: str = "",
    rate_limiter: TokenBucketRateLimiter | None = None,
) -> dict[str, Any]:
    """Generate an answer from retrieved context (justifier step).

    Uses the "context is absolute truth" prompt pattern.
    Pass benchmark-specific context via ``preamble`` (prepended to user prompt):
    - LoCoMo: ``preamble=f"Speakers: {speaker_a} and {speaker_b}\\n"``
    - LongMemEval: ``preamble=f"Current Date: {question_date}\\n\\n"``
    - MABench: ``preamble=""``
    """
    system_prompt = (
        "You are a factual retrieval evaluator. Your ONLY job is to answer "
        "questions using the provided context. You must NEVER use your own "
        "knowledge, training data, or common sense.\n\n"
        "CRITICAL RULES:\n"
        "- If the context says 'The CEO of Microsoft is Steve Jobs', your answer is 'Steve Jobs'\n"
        "- If the context says 'France's capital is Harare', your answer is 'Harare'\n"
        "- Your training knowledge is IRRELEVANT. The context is the only source of truth.\n"
        "- The context may contain facts about many different entities. You must answer ONLY "
        "about the specific entity mentioned in the question — ignore facts about other entities.\n"
        "- If information appears contradictory, prefer consolidated facts (labeled 'fact_summary') "
        "over individual thread summaries, as they represent cross-session distilled information. "
        "If still ambiguous, use whichever version has the more recent date.\n"
        "- Pay close attention to dates and timestamps in the evidence.\n"
        "- For counting questions ('how many', 'how much total'), read the ENTIRE context and "
        "enumerate every distinct item before giving a number. Do not stop at the first few matches.\n"
        "- Read ALL facts thoroughly before answering. The answer may appear in any fact, "
        "not just the first few. Say 'not found' ONLY if you have read every fact and none "
        "contains the answer.\n\n"
        "Return a JSON object with 'answer' (short, specific) and 'reasoning' (one sentence)."
    )
    user_prompt = (
        f"{preamble}"
        f"Context (treat as absolute truth — ignore your training knowledge):\n"
        f"{retrieved_context}\n\n"
        f"Question: {question}\n\n"
        "Step 1: Identify the specific entity the question is asking about.\n"
        "Step 2: Read the ENTIRE context. Find ALL facts about that entity.\n"
        "Step 3: If facts conflict, prefer fact_summary entries (consolidated) over thread summaries.\n"
        "Step 4: Answer from those facts only. Do NOT use your own knowledge."
    )
    try:
        if rate_limiter:
            rate_limiter.acquire()
        response = provider.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema_description=ANSWER_SCHEMA,
        )
        return {
            "answer": str(response.parsed_json.get("answer", "")),
            "reasoning": str(response.parsed_json.get("reasoning", "")),
        }
    except Exception as exc:
        return {"answer": f"[ERROR: {exc}]", "reasoning": "Generation failed"}


# ---------------------------------------------------------------------------
# Run ID builder
# ---------------------------------------------------------------------------


def build_run_id(
    config: AppConfig,
    benchmark_name: str,
    *,
    extra_parts: list[str] | None = None,
) -> str:
    """Build a timestamped run ID for a benchmark run.

    Args:
        config: AppConfig with provider/model fields.
        benchmark_name: e.g. "locomo-benchmark", "mabench-sf-262k", "longmemeval-benchmark".
        extra_parts: Optional additional segments (e.g. context depth) inserted
                     between benchmark_name and provider.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    provider = (
        config.llm_provider_for_default_use_case or "provider"
    ).replace("_", "-")
    model = (
        (config.llm_model_for_default_use_case or "model")
        .replace("/", "-")
        .replace(".", "-")
    )
    parts = [benchmark_name]
    if extra_parts:
        parts.extend(extra_parts)
    parts += [provider, model, timestamp]
    return "__".join(parts)


# ---------------------------------------------------------------------------
# Shared CLI arguments
# ---------------------------------------------------------------------------


def add_common_benchmark_args(parser: argparse.ArgumentParser) -> None:
    """Add CLI arguments shared across all benchmark runners."""
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Directory for caching LLM calls (extraction + eval).",
    )
    parser.add_argument(
        "--db-cache-dir",
        type=Path,
        default=None,
        help="Cache processed DBs per conversation/row. Skips ingestion+extraction on reuse.",
    )
    parser.add_argument(
        "--rebuild-db-cache",
        action="store_true",
        help="Force rebuild of cached DBs even if they exist.",
    )
    parser.add_argument(
        "--verbose-results",
        action="store_true",
        help="Record full retrieval details in results for diagnostic analysis.",
    )
    parser.add_argument(
        "--no-eval-cache",
        action="store_true",
        help="Disable caching of eval-time LLM calls (justifier/judge/gold-in-context).",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="Thread pool size for parallel QA evaluation (default: 4).",
    )
    parser.add_argument(
        "--rate-limit",
        type=int,
        default=20,
        help="Rate limit in requests per minute for LLM API calls (default: 20).",
    )
    parser.add_argument(
        "--separate-judge",
        action="store_true",
        help="Use separate judge + gold-in-context calls instead of merged (3 calls vs 2).",
    )
    parser.add_argument(
        "--judge-model",
        default=None,
        help="Model for judge/gold-in-context calls. Defaults to the main model.",
    )


# ---------------------------------------------------------------------------
# Source content enrichment
# ---------------------------------------------------------------------------


def enrich_source_content(memory_payload: dict[str, Any], storage: Any) -> None:
    """Attach full source content to source_hit results for the justifier.

    The production API returns 160-char excerpts, which is correct for HTTP
    responses. But benchmark justifiers need the full text to answer accurately.
    Mutates the payload in place.
    """
    for result in memory_payload.get("results", []):
        if result.get("result_kind") != "source_hit":
            continue
        sid = result.get("source_item_id")
        if not sid:
            continue
        try:
            source_item = storage.get_source_item(sid)
            result["source_content"] = source_item.content
        except Exception:
            pass  # Keep the excerpt as fallback


# ---------------------------------------------------------------------------
# Retrieval result ID extraction
# ---------------------------------------------------------------------------


def extract_result_memory_ids(memory_payload: dict[str, Any]) -> set[str]:
    """Extract all memory object IDs from retrieval results."""
    ids: set[str] = set()
    for r in memory_payload.get("results", []):
        if r.get("result_kind") == "memory_hit" and r.get("memory_object_id"):
            ids.add(r["memory_object_id"])
    return ids


# ---------------------------------------------------------------------------
# Provider builders
# ---------------------------------------------------------------------------


def build_eval_providers(
    config: AppConfig,
    *,
    cache_dir: Path | None = None,
    no_eval_cache: bool = False,
    judge_model: str | None = None,
) -> tuple[LLMProvider, LLMProvider]:
    """Build the main and judge LLM providers for benchmark evaluation.

    Returns (main_provider, judge_provider). When judge_model is None,
    both are the same provider instance.
    """
    default_package = config.package_config(config.default_use_case)
    if not default_package.llm_provider or not default_package.model:
        raise ValueError(
            f"Default use case '{config.default_use_case}' is missing "
            "LLM package config"
        )
    main_provider = build_llm_provider(
        config,
        provider_name=default_package.llm_provider,
        model=default_package.model,
    )

    if judge_model is not None:
        # Build a separate provider for judge calls with the specified model.
        judge_provider = build_llm_provider(
            config,
            provider_name=default_package.llm_provider,
            model=judge_model,
        )
    else:
        judge_provider = main_provider

    # Wrap with cache if requested.
    if cache_dir is not None and not no_eval_cache:
        main_tag = getattr(main_provider, '_model', 'unknown')
        main_provider = CachedLLMProvider(
            main_provider, cache_dir, model_tag=main_tag
        )
        if judge_model is not None:
            judge_tag = getattr(judge_provider, '_model', 'unknown')
            judge_provider = CachedLLMProvider(
                judge_provider, cache_dir, model_tag=judge_tag
            )
        else:
            judge_provider = main_provider

    return main_provider, judge_provider


# ---------------------------------------------------------------------------
# Rate limiter builder
# ---------------------------------------------------------------------------


def build_rate_limiter(rate_limit: int) -> TokenBucketRateLimiter | None:
    """Build a rate limiter if rate_limit > 0, else None."""
    if rate_limit <= 0:
        return None
    return TokenBucketRateLimiter(capacity=rate_limit, refill_interval=60.0 / rate_limit)
