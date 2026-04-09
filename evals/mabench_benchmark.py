"""MABench FactConsolidation benchmark — contradiction handling evaluation.

Evaluates Pallium against the FactConsolidation datasets from MemoryAgentBench
(ICLR 2026), measuring ability to prefer newer contradictory information over
stale facts using SubEM scoring and layered pipeline diagnostics.

Dataset: https://huggingface.co/datasets/ai-hyz/MemoryAgentBench
Paper: arXiv 2507.05257

Usage:
    python -m evals.mabench_benchmark --download
    python -m evals.mabench_benchmark
    python -m evals.mabench_benchmark --datasets sf-sh --context-depth 32k
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from fastapi.testclient import TestClient

from app.config import AppConfig
from app.dependencies import build_llm_provider
from app.main import create_app
from providers.llm.base import LLMProvider

DEFAULT_DATASET_DIR = Path("evals/mabench/datasets")
DEFAULT_OUTPUT_DIR = Path("evals/mabench/output")
DEFAULT_DB_CACHE_DIR = Path("evals/mabench/db_cache")

# HuggingFace datasets viewer API for fetching rows without pyarrow.
HF_API_URL = (
    "https://datasets-server.huggingface.co/rows"
    "?dataset=ai-hyz/MemoryAgentBench&config=default&split=Conflict_Resolution"
    "&offset=0&length=100"
)

ANSWER_SCHEMA = '{"answer":"string","reasoning":"string"}'

# Available dataset configurations.
DATASET_CONFIGS: dict[str, dict[str, Any]] = {
    "sf-sh": {
        "name": "FactConsolidation-SH",
        "sub_dataset_prefix": "factconsolidation_sh",
        "competency": "selective_forgetting",
        "hop_type": "single_hop",
    },
    "sf-mh": {
        "name": "FactConsolidation-MH",
        "sub_dataset_prefix": "factconsolidation_mh",
        "competency": "selective_forgetting",
        "hop_type": "multi_hop",
    },
}

CONTEXT_DEPTHS = {"6k", "32k", "64k", "262k"}

# Chunking constants.
CHUNK_SIZE_CHARS = 16000  # Fallback for non-fact-list contexts.
THREAD_GROUP_SIZE = 20  # Facts per thread — keeps threads within extraction windows.
FACT_LINE_PATTERN = re.compile(r"(?:^|\n)\d+\.\s+")  # "0. Fact text here."
TIMESTAMP_BASE = datetime(2024, 1, 1, tzinfo=timezone.utc)
TIMESTAMP_INCREMENT = timedelta(hours=1)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the MABench FactConsolidation benchmark."
    )
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-name", default=None)
    parser.add_argument(
        "--datasets",
        nargs="*",
        default=None,
        help="Datasets to run: sf-sh, sf-mh, or all. Default: all.",
    )
    parser.add_argument(
        "--context-depth",
        default="262k",
        choices=sorted(CONTEXT_DEPTHS),
        help="Context depth variant (default: 262k).",
    )
    parser.add_argument(
        "--query-limit",
        type=int,
        default=10,
        help="Number of results to retrieve per query (default: 10).",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Directory for caching LLM extraction calls.",
    )
    parser.add_argument(
        "--db-cache-dir",
        type=Path,
        default=None,
        help="Cache processed DBs per test row.",
    )
    parser.add_argument(
        "--rebuild-db-cache",
        action="store_true",
        help="Force rebuild of cached DBs even if they exist.",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download the MABench dataset if not present.",
    )
    parser.add_argument(
        "--mini",
        action="store_true",
        help="Run a small subset (5 questions per dataset).",
    )
    parser.add_argument(
        "--verbose-results",
        action="store_true",
        help="Record full retrieval details in results.",
    )
    args = parser.parse_args()

    dataset_path = args.dataset_dir / "conflict_resolution.json"
    if not dataset_path.exists():
        if args.download:
            _download_dataset(args.dataset_dir)
        else:
            print(f"Dataset not found at {dataset_path}")
            print("Download it with:  python -m evals.mabench_benchmark --download")
            return 1

    dataset_ids = args.datasets or list(DATASET_CONFIGS.keys())
    if "all" in dataset_ids:
        dataset_ids = list(DATASET_CONFIGS.keys())
    for did in dataset_ids:
        if did not in DATASET_CONFIGS:
            print(f"Unknown dataset: {did}. Available: {', '.join(DATASET_CONFIGS)}")
            return 1

    run_dir = run_mabench_benchmark(
        dataset_path=dataset_path,
        output_root=args.output_dir,
        config=AppConfig.from_env(),
        run_name=args.run_name,
        dataset_ids=dataset_ids,
        context_depth=args.context_depth,
        query_limit=args.query_limit,
        cache_dir=args.cache_dir,
        db_cache_dir=args.db_cache_dir,
        rebuild_db_cache=args.rebuild_db_cache,
        mini=args.mini,
        verbose_results=args.verbose_results,
    )
    print(f"\nResults: {run_dir}")
    return 0


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_mabench_benchmark(
    *,
    dataset_path: Path,
    output_root: Path,
    config: AppConfig,
    run_name: str | None = None,
    answer_provider: LLMProvider | None = None,
    dataset_ids: list[str] | None = None,
    context_depth: str = "262k",
    query_limit: int = 10,
    cache_dir: Path | None = None,
    db_cache_dir: Path | None = None,
    rebuild_db_cache: bool = False,
    mini: bool = False,
    verbose_results: bool = False,
) -> Path:
    raw_dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    dataset_ids = dataset_ids or list(DATASET_CONFIGS.keys())

    default_package = config.package_config(config.default_use_case)
    if answer_provider is None:
        if not default_package.llm_provider or not default_package.model:
            raise ValueError(
                f"Default use case '{config.default_use_case}' is missing LLM config"
            )
        provider = build_llm_provider(
            config,
            provider_name=default_package.llm_provider,
            model=default_package.model,
        )
    else:
        provider = answer_provider

    run_id = run_name or _build_run_id(config, context_depth)
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    results_path = run_dir / "results.jsonl"

    all_results: list[dict[str, Any]] = []
    with results_path.open("w", encoding="utf-8") as results_file:
        for dataset_id in dataset_ids:
            ds_config = DATASET_CONFIGS[dataset_id]
            rows = _select_rows(raw_dataset, ds_config, context_depth)
            if not rows:
                print(f"\n  No rows found for {dataset_id} at depth {context_depth}")
                continue

            print(f"\n{'='*60}")
            print(f"Dataset: {ds_config['name']} ({context_depth} context)")
            print(f"Rows: {len(rows)}")

            for row_index, row in enumerate(rows):
                row_id = f"{dataset_id}-row{row_index}"
                questions = row["questions"]
                answers = row["answers"]
                if mini:
                    questions = questions[:5]
                    answers = answers[:5]

                print(f"\n  [{row_index + 1}/{len(rows)}] {row_id}: {len(questions)} questions")

                row_results = _evaluate_row(
                    row=row,
                    row_id=row_id,
                    dataset_id=dataset_id,
                    questions=questions,
                    answers=answers,
                    config=config,
                    answer_provider=provider,
                    query_limit=query_limit,
                    cache_dir=cache_dir,
                    db_cache_dir=db_cache_dir,
                    rebuild_db_cache=rebuild_db_cache,
                    verbose_results=verbose_results,
                )
                for result in row_results:
                    all_results.append(result)
                    results_file.write(json.dumps(result) + "\n")
                    results_file.flush()

                correct = sum(1 for r in row_results if r["correct"])
                print(f"    {row_id}: {correct}/{len(row_results)} correct")

    summary = _build_summary(
        results=all_results,
        config=config,
        run_id=run_id,
        context_depth=context_depth,
    )
    (run_dir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    report = _build_report(summary)
    (run_dir / "report.md").write_text(report, encoding="utf-8")
    print(f"\n{report}")
    return run_dir


# ---------------------------------------------------------------------------
# Row selection
# ---------------------------------------------------------------------------


def _select_rows(
    raw_dataset: list[dict[str, Any]],
    ds_config: dict[str, Any],
    context_depth: str,
) -> list[dict[str, Any]]:
    """Select rows matching the dataset config and context depth.

    The HF dataset has metadata.source like "factconsolidation_mh_6k".
    """
    prefix = ds_config["sub_dataset_prefix"]
    target_sub = f"{prefix}_{context_depth}"
    return [
        row for row in raw_dataset
        if row.get("metadata", {}).get("source", "").lower().replace("-", "_") == target_sub
    ]


# ---------------------------------------------------------------------------
# Per-row evaluation
# ---------------------------------------------------------------------------


def _evaluate_row(
    *,
    row: dict[str, Any],
    row_id: str,
    dataset_id: str,
    questions: list[str],
    answers: list[Any],
    config: AppConfig,
    answer_provider: LLMProvider,
    query_limit: int,
    cache_dir: Path | None,
    db_cache_dir: Path | None = None,
    rebuild_db_cache: bool = False,
    verbose_results: bool = False,
) -> list[dict[str, Any]]:
    context = row["context"]
    metadata = row.get("metadata", {})
    haystack_sessions = metadata.get("haystack_sessions") or []

    # Build fact lookup for old/new identification.
    fact_lookup = _build_fact_lookup(haystack_sessions, questions)

    # Check DB cache.
    cached_db_path = None
    use_cached_db = False
    if db_cache_dir is not None:
        db_cache_dir.mkdir(parents=True, exist_ok=True)
        cached_db_path = db_cache_dir / f"{row_id}.db"
        cached_vector_prefix = db_cache_dir / f"{row_id}.vector.index"
        use_cached_db = (
            not rebuild_db_cache
            and cached_db_path.exists()
            and cached_vector_prefix.exists()
        )

    results: list[dict[str, Any]] = []

    with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = Path(temp_dir) / "mabench.db"
        vector_path = Path(temp_dir) / "vector.index"

        if use_cached_db:
            shutil.copy2(cached_db_path, db_path)
            _copy_vector_index(cached_vector_prefix, vector_path)
            print(f"    Using cached DB for {row_id}")

        database_url = f"sqlite:///{db_path}"
        vector_index_config = replace(
            config.vector_index,
            index_path=str(vector_path),
        )
        scenario_config = replace(
            config,
            sqlite_url=database_url,
            default_use_case="agent_conversation_memory",
            vector_index=vector_index_config,
        )

        with TestClient(create_app(scenario_config)) as client:
            if cache_dir is not None:
                from evals.generated_exploratory.invariant_runner import (
                    _wrap_providers_with_cache,
                )
                _wrap_providers_with_cache(client, cache_dir)

            if not use_cached_db:
                chunks = _chunk_text(context)
                item_count = _ingest_chunks(
                    client=client,
                    row_id=row_id,
                    chunks=chunks,
                )
                print(f"    Ingested {item_count} items across {_thread_count(len(chunks))} threads")

                print("    Processing semantic extraction...")
                client.app.state.pallium_service.drain_processing_queue(
                    worker_id="mabench-runner"
                )
                client.app.state.pallium_service.reconcile_vector_index()
                print("    Processing complete")


                if cached_db_path is not None:
                    shutil.copy2(db_path, cached_db_path)
                    _copy_vector_index(vector_path, cached_vector_prefix)
                    print(f"    Cached DB for {row_id}")

            # Query and evaluate each question.
            qa_inputs: list[tuple[int, str, list[str], dict[str, Any]]] = []
            for q_index, (question, answer_list) in enumerate(zip(questions, answers)):
                query_payload = {
                    "text": question,
                    "limit": query_limit,
                    "container_ref": row_id,
                    "visibility": "public",
                    "runtime_context": {
                        "turn_kind": "new_session",
                        "session_has_sufficient_local_context": False,
                    },
                }
                query_response = client.post("/query/debug", json=query_payload)
                query_response.raise_for_status()

                gold_answers = answer_list if isinstance(answer_list, list) else [str(answer_list)]
                qa_inputs.append((q_index, question, gold_answers, query_response.json()))

            def _eval_one(
                entry: tuple[int, str, list[str], dict[str, Any]],
            ) -> tuple[int, dict[str, Any]]:
                q_idx, question, golds, mem_payload = entry
                result = _evaluate_question(
                    answer_provider=answer_provider,
                    row_id=row_id,
                    dataset_id=dataset_id,
                    question=question,
                    gold_answers=golds,
                    memory_payload=mem_payload,
                    fact_lookup=fact_lookup.get(q_idx),
                    verbose=verbose_results,
                )
                return q_idx, result

            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = {pool.submit(_eval_one, inp): inp[0] for inp in qa_inputs}
                indexed: list[tuple[int, dict[str, Any]]] = []
                done_count = 0
                for future in as_completed(futures):
                    idx, result = future.result()
                    indexed.append((idx, result))
                    done_count += 1
                    if done_count % 20 == 0 or done_count == len(qa_inputs):
                        correct_so_far = sum(1 for _, r in indexed if r["correct"])
                        print(
                            f"    QA progress: {done_count}/{len(qa_inputs)} "
                            f"({correct_so_far} correct)"
                        )

            indexed.sort(key=lambda x: x[0])
            results = [r for _, r in indexed]

            engine = getattr(
                client.app.state.pallium_service._storage, "_engine", None
            )
            if engine is not None:
                engine.dispose()

    return results


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def _chunk_text(context: str) -> list[str]:
    """Split context into individual facts or sentence-aligned chunks.

    FactConsolidation data is a numbered list of atomic facts:
        "0. Thomas Kyd was born in London.\n1. The chairperson of Fatah is..."
    Each fact becomes one chunk (= one source item), matching Pallium's
    per-message ingestion model.

    Falls back to sentence-aligned chunking if the context doesn't match
    the numbered-fact pattern.
    """
    facts = _split_numbered_facts(context)
    if facts:
        return facts
    # Fallback: sentence-aligned chunking for non-fact-list contexts.
    return _chunk_by_sentences(context)


def _split_numbered_facts(context: str) -> list[str]:
    """Split '0. Fact one.\n1. Fact two.\n...' into individual fact strings."""
    # Split on the numbered fact boundaries.
    parts = FACT_LINE_PATTERN.split(context)
    # First part is preamble (e.g., "Here is a list of facts:\n").
    facts: list[str] = []
    for part in parts:
        text = part.strip()
        if text and len(text) > 5:  # Skip empty/trivial fragments.
            facts.append(text)
    return facts


def _chunk_by_sentences(context: str) -> list[str]:
    """Fallback: split on sentence boundaries into ~CHUNK_SIZE_CHARS chunks."""
    sentences = _split_sentences(context)
    chunks: list[str] = []
    current_chunk: list[str] = []
    current_len = 0

    for sentence in sentences:
        sentence_len = len(sentence)
        if current_len + sentence_len > CHUNK_SIZE_CHARS and current_chunk:
            chunks.append(" ".join(current_chunk))
            current_chunk = []
            current_len = 0
        current_chunk.append(sentence)
        current_len += sentence_len

    if current_chunk:
        chunks.append(" ".join(current_chunk))
    return chunks


def _split_sentences(text: str) -> list[str]:
    """Simple sentence splitter — split on sentence-ending punctuation."""
    parts = re.split(r'(?<=[.!?])\s+', text)
    return [p.strip() for p in parts if p.strip()]


def _thread_count(num_chunks: int) -> int:
    return max(1, (num_chunks + THREAD_GROUP_SIZE - 1) // THREAD_GROUP_SIZE)


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


def _ingest_chunks(
    *,
    client: TestClient,
    row_id: str,
    chunks: list[str],
) -> int:
    BATCH_SIZE = 50
    all_items: list[dict[str, Any]] = []

    for chunk_index, chunk in enumerate(chunks):
        thread_index = chunk_index // THREAD_GROUP_SIZE
        thread_ref = f"{row_id}-t{thread_index}"
        occurred_at = TIMESTAMP_BASE + (TIMESTAMP_INCREMENT * chunk_index)

        all_items.append({
            "source_type": "chat_message",
            "source_id": f"{row_id}_chunk{chunk_index}",
            "content_type": "text/plain",
            "content": chunk,
            "role": "user",
            "artifact_kind": "message",
            "container_ref": row_id,
            "thread_ref": thread_ref,
            "visibility": "public",
            "occurred_at": occurred_at.isoformat(),
        })

    for start in range(0, len(all_items), BATCH_SIZE):
        batch = all_items[start : start + BATCH_SIZE]
        response = client.post("/items", json=batch)
        response.raise_for_status()
    return len(all_items)


# ---------------------------------------------------------------------------
# Fact lookup for old/new identification
# ---------------------------------------------------------------------------


def _build_fact_lookup(
    haystack_sessions: list[Any],
    questions: list[str],
) -> dict[int, dict[str, Any]]:
    """Build a per-question lookup for diagnostic classification.

    NOTE: In the actual MABench Conflict_Resolution split, haystack_sessions
    is null for all rows. The old/new fact provenance is not available in
    metadata. Instead, we use gold-answer presence in retrieval results as
    the diagnostic signal (see _pipeline_diagnostic).
    """
    # haystack_sessions is null for Conflict_Resolution rows.
    # Return empty — diagnostics fall back to gold-answer-based analysis.
    if not haystack_sessions:
        return {}

    lookup: dict[int, dict[str, Any]] = {}
    for q_idx in range(min(len(questions), len(haystack_sessions))):
        sessions = haystack_sessions[q_idx]
        if not isinstance(sessions, list):
            continue

        original_texts: list[str] = []
        rewrite_texts: list[str] = []

        for session in sessions:
            if not isinstance(session, dict):
                continue
            content = session.get("content", "")
            has_answer = session.get("has_answer", False)
            role = str(session.get("role", "")).lower()

            if not has_answer:
                continue
            if "rewrite" in role or "new" in role or "update" in role:
                rewrite_texts.append(content)
            elif "original" in role or "old" in role:
                original_texts.append(content)
            else:
                rewrite_texts.append(content)

        if original_texts or rewrite_texts:
            lookup[q_idx] = {
                "original_texts": original_texts,
                "rewrite_texts": rewrite_texts,
            }

    return lookup


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def _evaluate_question(
    *,
    answer_provider: LLMProvider,
    row_id: str,
    dataset_id: str,
    question: str,
    gold_answers: list[str],
    memory_payload: dict[str, Any],
    fact_lookup: dict[str, Any] | None,
    verbose: bool = False,
) -> dict[str, Any]:
    """Evaluate a single question with SubEM scoring and pipeline diagnostics."""
    retrieved_context = _format_retrieved_context(memory_payload)

    answer_result = _generate_answer(
        provider=answer_provider,
        question=question,
        retrieved_context=retrieved_context,
    )

    predicted = answer_result["answer"]
    correct = _subem_score(predicted, gold_answers)

    # Pipeline diagnostic.
    pipeline = _pipeline_diagnostic(memory_payload, fact_lookup, gold_answers=gold_answers)

    result: dict[str, Any] = {
        "row_id": row_id,
        "dataset_id": dataset_id,
        "question": question,
        "gold_answers": gold_answers,
        "predicted_answer": predicted,
        "answer_reasoning": answer_result.get("reasoning", ""),
        "correct": correct,
        "result_count": len(memory_payload.get("results", [])),
        "should_inject": memory_payload.get("should_inject"),
        "injectable_block_count": len(memory_payload.get("injectable_blocks", [])),
        "pipeline_diagnostic": pipeline,
    }

    if verbose:
        result["retrieved_results"] = _compact_results(memory_payload)
        result["justifier_context"] = retrieved_context[:2000]

    return result


def _subem_score(prediction: str, gold_answers: list[str]) -> bool:
    """Substring Exact Match: true if any gold answer is a substring of prediction."""
    pred_norm = _normalize_answer(prediction)
    return any(_normalize_answer(g) in pred_norm for g in gold_answers if g)


def _normalize_answer(text: str) -> str:
    """Normalize answer for SubEM comparison."""
    text = text.lower().strip()
    # Remove articles and extra whitespace.
    text = re.sub(r"\b(a|an|the)\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _pipeline_diagnostic(
    memory_payload: dict[str, Any],
    fact_lookup: dict[str, Any] | None,
    gold_answers: list[str] | None = None,
) -> dict[str, Any]:
    """Diagnose retrieval quality for contradiction handling.

    Since haystack_sessions is null for Conflict_Resolution rows (no old/new
    fact provenance in metadata), we use gold-answer presence in retrieval
    results as the primary diagnostic: did the system retrieve content
    containing the correct (newer) answer?

    If fact_lookup is available (future data versions), we also classify
    old-vs-new fact preference.
    """
    results = memory_payload.get("results", [])
    blocks = memory_payload.get("injectable_blocks", [])
    all_text = _all_retrieved_text(results, blocks)

    # Gold answer retrieval: is the correct answer in retrieved context?
    gold_in_context = False
    if gold_answers:
        gold_in_context = any(
            _normalize_answer(g) in all_text for g in gold_answers if g
        )

    diag: dict[str, Any] = {
        "gold_in_context": gold_in_context,
        "result_count": len(results),
        "memory_hits": sum(1 for r in results if r.get("result_kind") == "memory_hit"),
        "source_hits": sum(1 for r in results if r.get("result_kind") == "source_hit"),
    }

    # If fact_lookup is available, add old/new classification.
    if fact_lookup:
        original_texts = fact_lookup.get("original_texts", [])
        rewrite_texts = fact_lookup.get("rewrite_texts", [])

        original_found = any(
            _text_overlap(orig, all_text) for orig in original_texts
        )
        rewrite_found = any(
            _text_overlap(rw, all_text) for rw in rewrite_texts
        )

        if original_found and rewrite_found:
            original_best_rank = _best_rank(results, original_texts)
            rewrite_best_rank = _best_rank(results, rewrite_texts)
            if rewrite_best_rank < original_best_rank:
                classification = "both_found_newer_higher"
            elif original_best_rank < rewrite_best_rank:
                classification = "both_found_older_higher"
            else:
                classification = "both_found_same_rank"
        elif rewrite_found and not original_found:
            classification = "only_newer"
        elif original_found and not rewrite_found:
            classification = "only_older"
        else:
            classification = "neither_found"

        diag["classification"] = classification
        diag["original_found"] = original_found
        diag["rewrite_found"] = rewrite_found

    return diag


def _all_retrieved_text(
    results: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
) -> str:
    """Concatenate all text from retrieval results and injectable blocks."""
    parts: list[str] = []
    for r in results:
        if r.get("result_kind") == "memory_hit":
            payload = r.get("payload") or {}
            for key in ("statement", "summary", "decision", "carry_forward_answer",
                        "investigation_outcome", "description"):
                val = payload.get(key)
                if val:
                    parts.append(str(val))
        elif r.get("result_kind") == "source_hit":
            parts.append(r.get("excerpt", ""))
    for block in blocks:
        parts.append(block.get("text", ""))
        for ev in block.get("evidence", []):
            parts.append(ev.get("excerpt", ""))
    return " ".join(parts).lower()


def _text_overlap(needle: str, haystack: str) -> bool:
    """Check if key content from needle appears in haystack."""
    needle_lower = needle.lower().strip()
    if len(needle_lower) < 10:
        return needle_lower in haystack

    # Extract key content words.
    words = [w for w in needle_lower.split() if len(w) >= 4]
    if not words:
        return needle_lower in haystack

    # Require 60% of key words to appear.
    matched = sum(1 for w in words if w in haystack)
    return matched >= max(1, len(words) * 0.6)


def _best_rank(results: list[dict[str, Any]], fact_texts: list[str]) -> int:
    """Find the best (lowest) rank where any fact text appears in results."""
    for rank, r in enumerate(results):
        text = ""
        if r.get("result_kind") == "memory_hit":
            payload = r.get("payload") or {}
            text = " ".join(
                str(v) for k, v in payload.items() if isinstance(v, str)
            )
        elif r.get("result_kind") == "source_hit":
            text = r.get("excerpt", "")
        text_lower = text.lower()
        for fact in fact_texts:
            if _text_overlap(fact, text_lower):
                return rank
    return len(results)  # Not found — worst possible rank.


# ---------------------------------------------------------------------------
# Answer generation
# ---------------------------------------------------------------------------


def _generate_answer(
    *,
    provider: LLMProvider,
    question: str,
    retrieved_context: str,
) -> dict[str, Any]:
    """Generate an answer from retrieved context (justifier step)."""
    system_prompt = (
        "You are a factual retrieval evaluator. Your ONLY job is to answer "
        "questions using the provided context. You must NEVER use your own "
        "knowledge, training data, or common sense.\n\n"
        "CRITICAL RULES:\n"
        "- If the context says 'The CEO of Microsoft is Steve Jobs', your answer is 'Steve Jobs'\n"
        "- If the context says 'France's capital is Harare', your answer is 'Harare'\n"
        "- Your training knowledge is IRRELEVANT. The context is the only source of truth.\n"
        "- If information appears contradictory, use whichever version appears more recently "
        "(later in the context or with a more recent date).\n"
        "- If the context does not contain enough information to answer, say 'not found'.\n\n"
        "Return a JSON object with 'answer' (short, specific) and 'reasoning' (one sentence)."
    )
    user_prompt = (
        f"Context (treat as absolute truth — ignore your training knowledge):\n"
        f"{retrieved_context}\n\n"
        f"Question: {question}\n\n"
        "Answer ONLY from the context above. Do NOT use your own knowledge."
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


def _format_retrieved_context(memory_payload: dict[str, Any]) -> str:
    """Format Pallium retrieval results for the justifier LLM."""
    parts: list[str] = []

    for i, block in enumerate(memory_payload.get("injectable_blocks", [])):
        block_type = block.get("block_type") or block.get("memory_type") or "memory"
        title = block.get("title", "")
        text = block.get("text", "")
        evidence = block.get("evidence", [])

        part = f"[Memory {i + 1} ({block_type})]"
        if title:
            part += f" {title}"
        part += f"\n{text}"

        if evidence:
            dates = [e.get("occurred_at", "") for e in evidence if e.get("occurred_at")]
            if dates:
                part += f"\n(Evidence dates: {', '.join(dates[:3])})"
        parts.append(part)

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
                parts.append(f"[Fact {i + 1} ({mem_type})] {summary}{date_note}")
        elif result.get("result_kind") == "source_hit":
            excerpt = result.get("excerpt", "")
            if excerpt:
                occurred_at = result.get("occurred_at", "")
                date_note = f" (date: {occurred_at})" if occurred_at else ""
                parts.append(f"[Source {i + 1}] {excerpt}{date_note}")

    return "\n\n".join(parts) if parts else "No relevant information found."


def _compact_results(memory_payload: dict[str, Any]) -> list[dict[str, Any]]:
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


# ---------------------------------------------------------------------------
# Summary & report
# ---------------------------------------------------------------------------


def _build_summary(
    *,
    results: list[dict[str, Any]],
    config: AppConfig,
    run_id: str,
    context_depth: str,
) -> dict[str, Any]:
    total = len(results)
    invalid = sum(1 for r in results if r["predicted_answer"].startswith("[ERROR"))
    valid = total - invalid
    correct = sum(1 for r in results if r["correct"])

    by_dataset: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in results:
        by_dataset[r["dataset_id"]].append(r)

    dataset_stats = []
    for ds_id in sorted(by_dataset):
        ds_results = by_dataset[ds_id]
        ds_total = len(ds_results)
        ds_correct = sum(1 for r in ds_results if r["correct"])
        ds_valid = ds_total - sum(
            1 for r in ds_results if r["predicted_answer"].startswith("[ERROR")
        )
        dataset_stats.append({
            "dataset": ds_id,
            "name": DATASET_CONFIGS.get(ds_id, {}).get("name", ds_id),
            "total": ds_total,
            "correct": ds_correct,
            "accuracy": round(ds_correct / ds_valid * 100, 1) if ds_valid else 0,
        })

    # Pipeline diagnostic aggregation.
    gold_in_ctx = sum(
        1 for r in results
        if r.get("pipeline_diagnostic", {}).get("gold_in_context")
    )
    gold_in_ctx_correct = sum(
        1 for r in results
        if r.get("pipeline_diagnostic", {}).get("gold_in_context") and r["correct"]
    )
    gold_not_in_ctx = sum(
        1 for r in results
        if not r.get("pipeline_diagnostic", {}).get("gold_in_context")
    )
    gold_not_in_ctx_correct = sum(
        1 for r in results
        if not r.get("pipeline_diagnostic", {}).get("gold_in_context") and r["correct"]
    )

    # Recency classifications (if fact_lookup was available).
    classifications: dict[str, int] = defaultdict(int)
    for r in results:
        diag = r.get("pipeline_diagnostic", {})
        cls = diag.get("classification")
        if cls:
            classifications[cls] += 1

    return {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "context_depth": context_depth,
        "provider": config.llm_provider_for_default_use_case,
        "model": config.llm_model_for_default_use_case,
        "total_questions": total,
        "valid_questions": valid,
        "invalid_questions": invalid,
        "correct": correct,
        "accuracy": round(correct / valid * 100, 1) if valid else 0,
        "by_dataset": dataset_stats,
        "retrieval_diagnostic": {
            "gold_in_context": gold_in_ctx,
            "gold_in_context_correct": gold_in_ctx_correct,
            "gold_in_context_pct": round(gold_in_ctx / total * 100, 1) if total else 0,
            "gold_not_in_context": gold_not_in_ctx,
            "gold_not_in_context_but_correct": gold_not_in_ctx_correct,
        },
        "recency_classifications": dict(classifications) if classifications else None,
    }


def _build_report(summary: dict[str, Any]) -> str:
    invalid_note = (
        f", {summary['invalid_questions']} invalid"
        if summary["invalid_questions"]
        else ""
    )
    lines = [
        "# MABench FactConsolidation Report",
        "",
        f"Run ID: `{summary['run_id']}`",
        f"Provider: `{summary['provider']}` / `{summary['model']}`",
        f"Context depth: {summary['context_depth']}",
        "",
        "## Overall Accuracy (SubEM)",
        "",
        f"**{summary['accuracy']}%** "
        f"({summary['correct']}/{summary['valid_questions']} correct{invalid_note})",
        "",
        "## By Dataset",
        "",
        "| Dataset | Correct | Total | Accuracy |",
        "|---------|---------|-------|----------|",
    ]
    for ds in summary["by_dataset"]:
        lines.append(
            f"| {ds['name']} | {ds['correct']} | {ds['total']} | {ds['accuracy']}% |"
        )

    diag = summary["retrieval_diagnostic"]
    total_q = summary["total_questions"]
    lines.extend([
        "",
        "## Retrieval Diagnostic",
        "",
        f"- Gold answer in context: {diag['gold_in_context']}/{total_q} "
        f"({diag['gold_in_context_pct']}%)",
        f"  - Correct when found: {diag['gold_in_context_correct']}/{diag['gold_in_context']}",
        f"- Gold answer NOT in context: {diag['gold_not_in_context']}/{total_q}",
        f"  - Correct despite not found: {diag['gold_not_in_context_but_correct']}"
        f"/{diag['gold_not_in_context']}",
    ])

    recency = summary.get("recency_classifications")
    if recency:
        lines.extend([
            "",
            "## Recency Classification",
            "",
        ])
        for cls, count in sorted(recency.items()):
            pct = round(count / total_q * 100, 1) if total_q else 0
            lines.append(f"- {cls}: {count} ({pct}%)")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def _download_dataset(dataset_dir: Path) -> None:
    """Download the Conflict_Resolution split from HuggingFace."""
    dataset_dir.mkdir(parents=True, exist_ok=True)
    output_path = dataset_dir / "conflict_resolution.json"

    print("Downloading MABench Conflict_Resolution split...")
    print(f"Source: {HF_API_URL}")

    try:
        req = urllib.request.Request(HF_API_URL)
        req.add_header("User-Agent", "pallium-benchmark/1.0")
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"HuggingFace API download failed: {exc}")
        print("\nFallback: install the datasets library and run:")
        print("  pip install datasets")
        print("  python -c \"")
        print("    from datasets import load_dataset; import json")
        print("    ds = load_dataset('ai-hyz/MemoryAgentBench', split='Conflict_Resolution')")
        print("    json.dump([dict(r) for r in ds], open('evals/mabench/datasets/conflict_resolution.json', 'w'))")
        print("  \"")
        raise

    # The HF rows API returns {"rows": [{"row": {...}}, ...]}
    rows = [item["row"] for item in data.get("rows", [])]
    if not rows:
        raise ValueError("No rows returned from HuggingFace API")

    output_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"Downloaded {len(rows)} rows to {output_path}")


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _copy_vector_index(src: Path, dst: Path) -> None:
    for suffix in ("", ".idmap.json", ".meta.json"):
        src_file = Path(f"{src}{suffix}")
        dst_file = Path(f"{dst}{suffix}")
        if src_file.exists():
            shutil.copy2(src_file, dst_file)


def _build_run_id(config: AppConfig, context_depth: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    provider = (
        config.llm_provider_for_default_use_case or "provider"
    ).replace("_", "-")
    model = (
        (config.llm_model_for_default_use_case or "model")
        .replace("/", "-")
        .replace(".", "-")
    )
    return f"mabench-sf-{context_depth}__{provider}__{model}__{timestamp}"


if __name__ == "__main__":
    raise SystemExit(main())
