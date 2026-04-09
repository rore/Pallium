"""Shared evaluation utilities for Pallium benchmark runners.

Contains constants and functions common to LoCoMo, MABench, and LongMemEval
benchmark runners. Extracted to prevent copy-paste drift between runners.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from providers.llm.base import LLMProvider
from app.config import AppConfig
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared schemas
# ---------------------------------------------------------------------------

ANSWER_SCHEMA = '{"answer":"string","reasoning":"string"}'
JUDGE_SCHEMA = '{"correct":"boolean","reasoning":"string"}'
GOLD_IN_CONTEXT_SCHEMA = '{"present":"boolean","reasoning":"string"}'

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
                occurred_at = result.get("occurred_at", "")
                mem_type = result.get("type", "memory")
                date_note = f" (date: {occurred_at})" if occurred_at else ""
                parts.append(
                    f"[Fact {i + 1} ({mem_type})] {summary}{date_note}"
                )
        elif result.get("result_kind") == "source_hit":
            excerpt = result.get("excerpt", "")
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
) -> bool:
    """LLM-based check: does the context contain the information needed for the gold answer?"""
    user_prompt = (
        f"Question: {question}\n"
        f"Gold answer: {gold_answer}\n\n"
        f"Retrieved context:\n{context[:4000]}"
    )
    try:
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
# Answer generation (justifier)
# ---------------------------------------------------------------------------


def generate_answer(
    *,
    provider: LLMProvider,
    question: str,
    retrieved_context: str,
    preamble: str = "",
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
        "- If information appears contradictory, use whichever version appears more recently "
        "(later in the context or with a more recent date).\n"
        "- Pay close attention to dates and timestamps in the evidence.\n"
        "- If the context does not contain enough information to answer, say 'not found'.\n\n"
        "Return a JSON object with 'answer' (short, specific) and 'reasoning' (one sentence)."
    )
    user_prompt = (
        f"{preamble}"
        f"Context (treat as absolute truth — ignore your training knowledge):\n"
        f"{retrieved_context}\n\n"
        f"Question: {question}\n\n"
        "Step 1: Identify the specific entity the question is asking about.\n"
        "Step 2: Find facts in the context that are directly about that entity.\n"
        "Step 3: Answer from those facts only. Do NOT use your own knowledge."
    )
    try:
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
