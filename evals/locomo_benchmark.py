"""LoCoMo benchmark -- end-to-end retrieval accuracy on standardized conversational QA.

Evaluates Pallium against the LoCoMo dataset (ACL 2024), measuring ability
to answer factual questions about multi-session conversations using
LLM-as-judge binary scoring, following the methodology established by
Hindsight and adopted by ByteRover.

Dataset: https://github.com/LuxiaraQian/locomo
Paper: "LoCoMo: Long-Context Conversational Memory" (ACL 2024)

Usage:
    python -m evals.locomo_benchmark --download
    python -m evals.locomo_benchmark --cache-dir .local/llm-cache
    python -m evals.locomo_benchmark --conversations conv-26 --limit-questions 5
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app
from providers.llm.base import LLMProvider
from evals.eval_common import (
    ANSWER_SCHEMA,
    JUDGE_SCHEMA,
    GOLD_IN_CONTEXT_SCHEMA,
    GOLD_IN_CONTEXT_SYSTEM_PROMPT,
    add_common_benchmark_args as _add_common_benchmark_args,
    build_eval_providers as _build_eval_providers,
    build_rate_limiter as _build_rate_limiter,
    build_run_id as _build_run_id_common,
    combined_judge as _combined_judge,
    compact_results as _compact_results,
    copy_vector_index as _copy_vector_index,
    extract_result_memory_ids as _extract_result_memory_ids,
    format_retrieved_context as _format_retrieved_context,
    generate_answer as _generate_answer_common,
    gold_in_context as _gold_in_context,
    gold_in_context_llm as _gold_in_context_llm,
    retrieval_summary as _retrieval_summary,
)
from evals.eval_rate_limiter import TokenBucketRateLimiter

logger = logging.getLogger(__name__)

DEFAULT_DATASET_PATH = Path("evals/locomo/datasets/locomo10.json")
DEFAULT_OUTPUT_DIR = Path("evals/locomo/output")
DEFAULT_DB_CACHE_DIR = Path("evals/locomo/db_cache")
LOCOMO_DATASET_URL = (
    "https://raw.githubusercontent.com/LuxiaraQian/locomo/main/data/locomo10.json"
)

CATEGORY_NAMES = {
    1: "multi_hop",
    2: "single_hop",
    3: "temporal",
    4: "open_domain",
    5: "adversarial",
}

# Hindsight's default LoCoMo judge prompt (generous grading).
LOCOMO_JUDGE_SYSTEM_PROMPT = """\
Your task is to label an answer to a question as 'CORRECT' or 'WRONG'. You will be given:
(1) a question (posed by one user to another user),
(2) a 'gold' (ground truth) answer,
(3) a generated answer
which you will score as CORRECT/WRONG.

The point of the question is to ask about something one user should know about the other user \
based on their prior conversations.
The gold answer will usually be a concise and short answer that includes the referenced topic. \
The generated answer might be much longer, but you should be generous with your grading - as long \
as it touches on the same topic as the gold answer, it should be counted as CORRECT.

For time related questions, the gold answer will be a specific date, month, year, etc. The generated \
answer might use relative time references or different formats, but as long as it refers to the same \
date or time period as the gold answer, it should be counted as CORRECT. Even if the format differs \
(e.g., "May 7th" vs "7 May"), consider it CORRECT if it's the same date.

There's an edge case where the actual answer can't be found in the data and in that case the gold \
answer will say so (e.g. 'You did not mention this information.'); if the generated answer says that \
it cannot be answered or it doesn't know, it should be counted as CORRECT.

Return a JSON object with:
- correct: true if the generated answer is correct, false otherwise
- reasoning: one sentence explanation of your judgement (keep it short)\
"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the LoCoMo retrieval accuracy benchmark."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-name", default=None)
    parser.add_argument(
        "--conversations",
        nargs="*",
        default=None,
        help="Specific conversation IDs to evaluate (e.g., conv-26). Default: all.",
    )
    parser.add_argument(
        "--limit-questions",
        type=int,
        default=None,
        help="Max questions per conversation (for quick testing).",
    )
    parser.add_argument(
        "--query-limit",
        type=int,
        default=10,
        help="Number of results to retrieve per query (default: 10).",
    )
    _add_common_benchmark_args(parser)
    parser.add_argument(
        "--mini",
        action="store_true",
        help="Run a small representative subset (3 questions per category per conversation).",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download the LoCoMo dataset if not present.",
    )
    args = parser.parse_args()

    if not args.dataset.exists():
        if args.download:
            _download_dataset(args.dataset)
        else:
            print(f"Dataset not found at {args.dataset}")
            print("Download it with:  python -m evals.locomo_benchmark --download")
            print(f"Or manually from:  {LOCOMO_DATASET_URL}")
            return 1

    run_dir = run_locomo_benchmark(
        dataset_path=args.dataset,
        output_root=args.output_dir,
        config=AppConfig.from_env(),
        run_name=args.run_name,
        conversation_ids=args.conversations,
        limit_questions=args.limit_questions,
        query_limit=args.query_limit,
        cache_dir=args.cache_dir,
        db_cache_dir=args.db_cache_dir,
        rebuild_db_cache=args.rebuild_db_cache,
        mini=args.mini,
        verbose_results=args.verbose_results,
        no_eval_cache=args.no_eval_cache,
        max_workers=args.max_workers,
        separate_judge=args.separate_judge,
        judge_model=args.judge_model,
        rate_limit=args.rate_limit,
    )
    print(f"\nResults: {run_dir}")
    return 0


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_locomo_benchmark(
    *,
    dataset_path: Path,
    output_root: Path,
    config: AppConfig,
    run_name: str | None = None,
    answer_provider: LLMProvider | None = None,
    conversation_ids: list[str] | None = None,
    limit_questions: int | None = None,
    query_limit: int = 10,
    cache_dir: Path | None = None,
    db_cache_dir: Path | None = None,
    rebuild_db_cache: bool = False,
    mini: bool = False,
    verbose_results: bool = False,
    no_eval_cache: bool = False,
    max_workers: int = 4,
    separate_judge: bool = False,
    judge_model: str | None = None,
    rate_limit: int = 20,
) -> Path:
    dataset = _load_dataset(dataset_path)
    if conversation_ids:
        dataset = [
            item for item in dataset if item["sample_id"] in conversation_ids
        ]
        if not dataset:
            raise ValueError(
                f"No conversations found matching: {conversation_ids}"
            )

    if answer_provider is not None:
        provider = answer_provider
        judge_provider = answer_provider
    else:
        provider, judge_provider = _build_eval_providers(
            config,
            cache_dir=cache_dir,
            no_eval_cache=no_eval_cache,
            judge_model=judge_model,
        )

    rate_limiter = _build_rate_limiter(rate_limit)

    run_id = run_name or _build_run_id_common(config, "locomo-benchmark")
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    results_path = run_dir / "results.jsonl"

    all_results: list[dict[str, Any]] = []
    with results_path.open("w", encoding="utf-8") as results_file:
        for conv_index, conversation in enumerate(dataset):
            sample_id = conversation["sample_id"]
            print(
                f"\n[{conv_index + 1}/{len(dataset)}] Processing {sample_id}..."
            )

            conv_results = _evaluate_conversation(
                conversation=conversation,
                config=config,
                answer_provider=provider,
                judge_provider=judge_provider,
                limit_questions=limit_questions,
                query_limit=query_limit,
                cache_dir=cache_dir,
                db_cache_dir=db_cache_dir,
                rebuild_db_cache=rebuild_db_cache,
                mini=mini,
                verbose_results=verbose_results,
                max_workers=max_workers,
                separate_judge=separate_judge,
                rate_limiter=rate_limiter,
            )
            for result in conv_results:
                all_results.append(result)
                results_file.write(json.dumps(result) + "\n")
                results_file.flush()

            correct = sum(1 for r in conv_results if r["correct"])
            print(f"  {sample_id}: {correct}/{len(conv_results)} correct")

    summary = _build_summary(
        results=all_results,
        config=config,
        run_id=run_id,
        dataset_path=dataset_path,
    )
    (run_dir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    report = _build_report(summary=summary, results=all_results)
    (run_dir / "report.md").write_text(report, encoding="utf-8")
    print(f"\n{report}")
    return run_dir


# ---------------------------------------------------------------------------
# Per-conversation evaluation
# ---------------------------------------------------------------------------


def _evaluate_conversation(
    *,
    conversation: dict[str, Any],
    config: AppConfig,
    answer_provider: LLMProvider,
    judge_provider: LLMProvider,
    limit_questions: int | None,
    query_limit: int,
    cache_dir: Path | None,
    db_cache_dir: Path | None = None,
    rebuild_db_cache: bool = False,
    mini: bool = False,
    verbose_results: bool = False,
    max_workers: int = 4,
    separate_judge: bool = False,
    rate_limiter: TokenBucketRateLimiter | None = None,
) -> list[dict[str, Any]]:
    sample_id = conversation["sample_id"]
    conv = conversation["conversation"]
    qa_pairs = [qa for qa in conversation["qa"] if qa.get("category") != 5]

    # Mini mode: 3 questions per category for fast iteration.
    if mini:
        by_cat: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for qa in qa_pairs:
            by_cat[qa.get("category", 0)].append(qa)
        qa_pairs = []
        for cat in sorted(by_cat):
            qa_pairs.extend(by_cat[cat][:3])

    if limit_questions:
        qa_pairs = qa_pairs[:limit_questions]

    sessions = _parse_sessions(conv)
    speaker_a = conv.get("speaker_a", "Speaker A")
    speaker_b = conv.get("speaker_b", "Speaker B")

    results: list[dict[str, Any]] = []

    # DB caching: reuse a processed DB if available.
    cached_db_path = None
    cached_vector_path = None
    use_cached_db = False
    if db_cache_dir is not None:
        db_cache_dir.mkdir(parents=True, exist_ok=True)
        cached_db_path = db_cache_dir / f"{sample_id}.db"
        cached_vector_prefix = db_cache_dir / f"{sample_id}.vector.index"
        use_cached_db = (
            not rebuild_db_cache
            and cached_db_path.exists()
            and cached_vector_prefix.exists()
        )

    with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = Path(temp_dir) / "locomo.db"
        vector_path = Path(temp_dir) / "vector.index"

        if use_cached_db:
            shutil.copy2(cached_db_path, db_path)
            _copy_vector_index(cached_vector_prefix, vector_path)
            print(f"  Using cached DB for {sample_id}")

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
                # --- ingest all turns ---
                turn_count = _ingest_conversation(
                    client=client,
                    sample_id=sample_id,
                    sessions=sessions,
                    speaker_a=speaker_a,
                    speaker_b=speaker_b,
                )
                print(
                    f"  Ingested {turn_count} turns across {len(sessions)} sessions"
                )

                # --- semantic extraction ---
                print("  Processing semantic extraction...")
                client.app.state.pallium_service.drain_processing_queue(
                    worker_id="locomo-runner"
                )
                client.app.state.pallium_service.reconcile_vector_index()
                print("  Processing complete")

                # Cache the processed DB for reuse.
                if cached_db_path is not None:
                    shutil.copy2(db_path, cached_db_path)
                    _copy_vector_index(vector_path, cached_vector_prefix)
                    print(f"  Cached DB for {sample_id}")

            # --- build evidence trace map (source_id → memory objects) ---
            evidence_map = _build_evidence_map(
                client=client,
                sample_id=sample_id,
            )

            # --- evaluate each QA pair (parallel justifier+judge) ---
            qa_inputs: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
            for qa_index, qa in enumerate(qa_pairs):
                query_payload = {
                    "text": qa["question"],
                    "limit": query_limit,
                    "container_ref": sample_id,
                    "visibility": "public",
                    "runtime_context": {
                        "turn_kind": "new_session",
                        "session_has_sufficient_local_context": False,
                    },
                }
                query_response = client.post(
                    "/query/debug", json=query_payload
                )
                query_response.raise_for_status()
                qa_inputs.append((qa_index, qa, query_response.json()))

            def _eval_one(
                entry: tuple[int, dict[str, Any], dict[str, Any]],
            ) -> tuple[int, dict[str, Any]]:
                qa_idx, qa_item, mem_payload = entry
                result = _evaluate_question_from_retrieval(
                    answer_provider=answer_provider,
                    judge_provider=judge_provider,
                    sample_id=sample_id,
                    qa=qa_item,
                    memory_payload=mem_payload,
                    speaker_a=speaker_a,
                    speaker_b=speaker_b,
                    verbose=verbose_results,
                    separate_judge=separate_judge,
                    rate_limiter=rate_limiter,
                )
                # Add evidence trace: where was the answer lost?
                result["evidence_trace"] = _trace_evidence(
                    qa=qa_item,
                    sample_id=sample_id,
                    evidence_map=evidence_map,
                    retrieval_result_ids=_extract_result_memory_ids(mem_payload),
                )
                return qa_idx, result

            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = {
                    pool.submit(_eval_one, inp): inp[0]
                    for inp in qa_inputs
                }
                indexed_results: list[tuple[int, dict[str, Any]]] = []
                done_count = 0
                for future in as_completed(futures):
                    idx, result = future.result()
                    indexed_results.append((idx, result))
                    done_count += 1
                    if done_count % 50 == 0 or done_count == len(qa_pairs):
                        correct_so_far = sum(
                            1
                            for _, r in indexed_results
                            if r["correct"]
                        )
                        print(
                            f"  QA progress: {done_count}/{len(qa_pairs)} "
                            f"({correct_so_far} correct)"
                        )

            indexed_results.sort(key=lambda x: x[0])
            results = [r for _, r in indexed_results]

            engine = getattr(
                client.app.state.pallium_service._storage, "_engine", None
            )
            if engine is not None:
                engine.dispose()

    return results


# ---------------------------------------------------------------------------
# Ingestion helpers
# ---------------------------------------------------------------------------


def _ingest_conversation(
    *,
    client: TestClient,
    sample_id: str,
    sessions: list[tuple[str, datetime | None, list[dict[str, Any]]]],
    speaker_a: str,
    speaker_b: str,
) -> int:
    BATCH_SIZE = 50
    all_items: list[dict[str, Any]] = []
    for session_key, session_date, turns in sessions:
        for turn in turns:
            all_items.append(
                _turn_to_item(
                    turn=turn,
                    sample_id=sample_id,
                    session_key=session_key,
                    session_date=session_date,
                    speaker_a=speaker_a,
                    speaker_b=speaker_b,
                )
            )
    for start in range(0, len(all_items), BATCH_SIZE):
        batch = all_items[start : start + BATCH_SIZE]
        response = client.post("/items", json=batch)
        response.raise_for_status()
    return len(all_items)


def _parse_sessions(
    conv: dict[str, Any],
) -> list[tuple[str, datetime | None, list[dict[str, Any]]]]:
    session_keys = sorted(
        key
        for key in conv
        if key.startswith("session_") and not key.endswith("_date_time")
    )
    sessions: list[tuple[str, datetime | None, list[dict[str, Any]]]] = []
    for key in session_keys:
        turns = conv[key]
        if not isinstance(turns, list):
            continue
        date_str = conv.get(f"{key}_date_time", "")
        session_date = _parse_locomo_date(date_str) if date_str else None
        sessions.append((key, session_date, turns))
    return sessions


def _parse_locomo_date(date_str: str) -> datetime | None:
    """Parse LoCoMo date format: '1:56 pm on 8 May, 2023'."""
    try:
        return datetime.strptime(
            date_str.strip(), "%I:%M %p on %d %B, %Y"
        ).replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None


def _turn_to_item(
    *,
    turn: dict[str, Any],
    sample_id: str,
    session_key: str,
    session_date: datetime | None,
    speaker_a: str,
    speaker_b: str,
) -> dict[str, Any]:
    speaker = turn.get("speaker", "")
    dia_id = turn.get("dia_id", "")
    text = turn.get("text", "")

    # Map speakers: speaker_a -> user, speaker_b -> assistant.
    role = "user" if speaker == speaker_a else "assistant"

    item: dict[str, Any] = {
        "source_type": "chat_message",
        "source_id": f"{sample_id}_{dia_id}",
        "content_type": "text/plain",
        "content": text,
        "role": role,
        "actor_ref": speaker,
        "container_ref": sample_id,
        "thread_ref": f"{sample_id}_{session_key}",
        "artifact_kind": "message",
        "visibility": "public",
    }
    if session_date:
        item["occurred_at"] = session_date.isoformat()
    return item


# ---------------------------------------------------------------------------
# Evaluation: generate answer & judge
# ---------------------------------------------------------------------------


def _evaluate_question_from_retrieval(
    *,
    answer_provider: LLMProvider,
    judge_provider: LLMProvider,
    sample_id: str,
    qa: dict[str, Any],
    memory_payload: dict[str, Any],
    speaker_a: str,
    speaker_b: str,
    verbose: bool = False,
    separate_judge: bool = False,
    rate_limiter: TokenBucketRateLimiter | None = None,
) -> dict[str, Any]:
    """Evaluate a QA pair given pre-fetched retrieval results (thread-safe)."""
    question = qa["question"]
    gold_answer = str(qa.get("answer", ""))
    category = qa.get("category", 0)
    category_name = CATEGORY_NAMES.get(category, f"unknown_{category}")

    retrieved_context = _format_retrieved_context(memory_payload)
    answer_result = _generate_answer_common(
        provider=answer_provider,
        question=question,
        retrieved_context=retrieved_context,
        preamble=f"Speakers in this conversation: {speaker_a} and {speaker_b}\n\n",
        rate_limiter=rate_limiter,
    )

    if separate_judge:
        # Legacy 3-call path: separate judge + gold-in-context.
        judge_result = _judge_answer(
            provider=judge_provider,
            question=question,
            gold_answer=gold_answer,
            predicted_answer=answer_result["answer"],
            rate_limiter=rate_limiter,
        )
        correct = judge_result["correct"]
        judge_reasoning = judge_result["reasoning"]

        gold_in_ctx = _gold_in_context(
            gold_answer,
            retrieved_context,
            provider=judge_provider,
            question=question,
            rate_limiter=rate_limiter,
        )
    else:
        # Merged 2-call path: combined judge + gold-in-context.
        combined = _combined_judge(
            provider=judge_provider,
            question=question,
            gold_answer=gold_answer,
            predicted_answer=answer_result["answer"],
            retrieved_context=retrieved_context,
            judge_system_prompt=LOCOMO_JUDGE_SYSTEM_PROMPT,
            rate_limiter=rate_limiter,
        )
        correct = combined["correct"]
        judge_reasoning = combined["judge_reasoning"]
        gold_in_ctx = combined["gold_in_context"]

    result: dict[str, Any] = {
        "sample_id": sample_id,
        "question": question,
        "gold_answer": gold_answer,
        "category": category,
        "category_name": category_name,
        "evidence_ids": qa.get("evidence", []),
        "predicted_answer": answer_result["answer"],
        "answer_reasoning": answer_result.get("reasoning", ""),
        "correct": correct,
        "judge_reasoning": judge_reasoning,
        "result_count": len(memory_payload.get("results", [])),
        "should_inject": memory_payload.get("should_inject"),
        "decision_reason": memory_payload.get("decision_reason"),
        "injectable_block_count": len(
            memory_payload.get("injectable_blocks", [])
        ),
        "retrieval_summary": _retrieval_summary(memory_payload),
        "gold_in_context": gold_in_ctx,
    }

    if verbose:
        result["retrieved_results"] = _compact_results(memory_payload)
        result["justifier_context"] = retrieved_context[:2000]

    return result


def _judge_answer(
    *,
    provider: LLMProvider,
    question: str,
    gold_answer: str,
    predicted_answer: str,
    rate_limiter: TokenBucketRateLimiter | None = None,
) -> dict[str, Any]:
    """Judge whether the predicted answer is correct (LLM-as-judge)."""
    user_prompt = (
        f"Question: {question}\n"
        f"Gold answer: {gold_answer}\n"
        f"Generated answer: {predicted_answer}"
    )
    try:
        if rate_limiter:
            rate_limiter.acquire()
        response = provider.generate_json(
            system_prompt=LOCOMO_JUDGE_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            schema_description=JUDGE_SCHEMA,
        )
        correct = response.parsed_json.get("correct", False)
        if isinstance(correct, str):
            correct = correct.lower() in {"true", "yes", "1"}
        return {
            "correct": bool(correct),
            "reasoning": str(response.parsed_json.get("reasoning", "")),
        }
    except Exception as exc:
        return {"correct": False, "reasoning": f"[ERROR: {exc}]"}


# ---------------------------------------------------------------------------
# Evidence trace: track where the answer is lost in the pipeline
# ---------------------------------------------------------------------------


def _build_evidence_map(
    *,
    client: TestClient,
    sample_id: str,
) -> dict[str, list[dict[str, Any]]]:
    """Build a map from source_id → memory objects created from that source item.

    Returns {source_id: [{type, id, text}]} for all source items that produced
    memory objects.
    """
    storage = client.app.state.pallium_service._storage
    # Get all active memory objects and their evidence links.
    all_memories = storage.list_memory_objects(lifecycle="active")
    evidence_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for mo in all_memories:
        evidence_refs = storage.get_evidence_for_memory_object(mo.id)
        payload = mo.payload or {}
        text = (
            payload.get("statement")
            or payload.get("summary")
            or payload.get("decision")
            or payload.get("investigation_outcome")
            or payload.get("carry_forward_answer")
            or ""
        )
        for ref in evidence_refs:
            if ref.source_id:
                evidence_map[ref.source_id].append({
                    "memory_id": mo.id,
                    "type": mo.type,
                    "text": str(text)[:200],
                })
    return dict(evidence_map)


def _trace_evidence(
    *,
    qa: dict[str, Any],
    sample_id: str,
    evidence_map: dict[str, list[dict[str, Any]]],
    retrieval_result_ids: set[str],
) -> dict[str, Any]:
    """Trace each evidence turn through the pipeline: extraction → retrieval."""
    evidence_ids = qa.get("evidence", [])
    if not evidence_ids:
        return {"evidence_ids": [], "extraction_found": False, "retrieval_found": False}

    traces: list[dict[str, Any]] = []
    any_extracted = False
    any_retrieved = False

    for eid in evidence_ids:
        source_id = f"{sample_id}_{eid}"
        memories = evidence_map.get(source_id, [])
        extracted = len(memories) > 0
        retrieved = any(m["memory_id"] in retrieval_result_ids for m in memories)
        if extracted:
            any_extracted = True
        if retrieved:
            any_retrieved = True
        traces.append({
            "evidence_id": eid,
            "source_id": source_id,
            "extracted": extracted,
            "memory_count": len(memories),
            "memory_types": [m["type"] for m in memories],
            "retrieved": retrieved,
        })

    return {
        "evidence_ids": evidence_ids,
        "traces": traces,
        "extraction_found": any_extracted,
        "retrieval_found": any_retrieved,
    }


# ---------------------------------------------------------------------------
# Summary & report
# ---------------------------------------------------------------------------


def _build_pipeline_diagnostic(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize where answers are lost: extraction, retrieval, or justification."""
    with_trace = [r for r in results if r.get("evidence_trace", {}).get("traces")]
    if not with_trace:
        return {}
    total = len(with_trace)
    extracted = sum(1 for r in with_trace if r["evidence_trace"]["extraction_found"])
    retrieved = sum(1 for r in with_trace if r["evidence_trace"]["retrieval_found"])
    in_context = sum(1 for r in with_trace if r.get("gold_in_context"))
    correct = sum(1 for r in with_trace if r["correct"])

    return {
        "questions_with_evidence": total,
        "extraction_found": extracted,
        "extraction_rate": round(extracted / total * 100, 1) if total else 0,
        "retrieval_found": retrieved,
        "retrieval_rate": round(retrieved / total * 100, 1) if total else 0,
        "gold_in_context": in_context,
        "context_rate": round(in_context / total * 100, 1) if total else 0,
        "correct": correct,
        "accuracy": round(correct / total * 100, 1) if total else 0,
        "loss_at_extraction": total - extracted,
        "loss_at_retrieval": extracted - retrieved,
        "loss_at_justification": in_context - correct,
    }


def _build_summary(
    *,
    results: list[dict[str, Any]],
    config: AppConfig,
    run_id: str,
    dataset_path: Path,
) -> dict[str, Any]:
    total = len(results)
    invalid = sum(
        1
        for r in results
        if r["predicted_answer"].startswith("[ERROR")
    )
    valid = total - invalid
    correct = sum(1 for r in results if r["correct"])

    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in results:
        by_category[r["category_name"]].append(r)
    category_stats = []
    for cat_name in sorted(by_category):
        cat_results = by_category[cat_name]
        cat_total = len(cat_results)
        cat_invalid = sum(
            1
            for r in cat_results
            if r["predicted_answer"].startswith("[ERROR")
        )
        cat_valid = cat_total - cat_invalid
        cat_correct = sum(1 for r in cat_results if r["correct"])
        category_stats.append(
            {
                "category": cat_name,
                "total": cat_total,
                "correct": cat_correct,
                "accuracy": (
                    round(cat_correct / cat_valid * 100, 1)
                    if cat_valid
                    else 0
                ),
            }
        )

    by_conversation: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in results:
        by_conversation[r["sample_id"]].append(r)
    conversation_stats = []
    for conv_id in sorted(by_conversation):
        conv_results = by_conversation[conv_id]
        conv_total = len(conv_results)
        conv_correct = sum(1 for r in conv_results if r["correct"])
        conversation_stats.append(
            {
                "conversation": conv_id,
                "total": conv_total,
                "correct": conv_correct,
                "accuracy": (
                    round(conv_correct / conv_total * 100, 1)
                    if conv_total
                    else 0
                ),
            }
        )

    avg_results = (
        sum(r["result_count"] for r in results) / total if total else 0
    )
    inject_count = sum(1 for r in results if r["should_inject"])
    inject_rate = inject_count / total * 100 if total else 0

    # Retrieval diagnostic: how often was the gold answer in the context?
    gold_in_ctx = sum(1 for r in results if r.get("gold_in_context"))
    gold_in_ctx_correct = sum(1 for r in results if r.get("gold_in_context") and r["correct"])
    gold_in_ctx_wrong = sum(1 for r in results if r.get("gold_in_context") and not r["correct"])
    gold_not_in_ctx = sum(1 for r in results if not r.get("gold_in_context"))
    gold_not_in_ctx_correct = sum(1 for r in results if not r.get("gold_in_context") and r["correct"])

    return {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": str(dataset_path),
        "provider": config.llm_provider_for_default_use_case,
        "model": config.llm_model_for_default_use_case,
        "total_questions": total,
        "valid_questions": valid,
        "invalid_questions": invalid,
        "correct": correct,
        "accuracy": round(correct / valid * 100, 1) if valid else 0,
        "by_category": category_stats,
        "by_conversation": conversation_stats,
        "retrieval_stats": {
            "avg_results_per_query": round(avg_results, 1),
            "injection_rate_pct": round(inject_rate, 1),
        },
        "retrieval_diagnostic": {
            "gold_in_context": gold_in_ctx,
            "gold_in_context_correct": gold_in_ctx_correct,
            "gold_in_context_wrong": gold_in_ctx_wrong,
            "gold_not_in_context": gold_not_in_ctx,
            "gold_not_in_context_but_correct": gold_not_in_ctx_correct,
        },
        "pipeline_diagnostic": _build_pipeline_diagnostic(results),
    }


def _build_report(
    *, summary: dict[str, Any], results: list[dict[str, Any]]
) -> str:
    invalid_note = (
        f", {summary['invalid_questions']} invalid"
        if summary["invalid_questions"]
        else ""
    )
    lines = [
        "# LoCoMo Benchmark Report",
        "",
        f"Run ID: `{summary['run_id']}`",
        f"Provider: `{summary['provider']}` / `{summary['model']}`",
        "",
        "## Overall Accuracy",
        "",
        f"**{summary['accuracy']}%** "
        f"({summary['correct']}/{summary['valid_questions']} correct"
        f"{invalid_note})",
        "",
        "## By Category",
        "",
        "| Category | Correct | Total | Accuracy |",
        "|----------|---------|-------|----------|",
    ]
    for cat in summary["by_category"]:
        lines.append(
            f"| {cat['category']} | {cat['correct']} | {cat['total']} "
            f"| {cat['accuracy']}% |"
        )
    lines.extend(
        [
            "",
            "## By Conversation",
            "",
            "| Conversation | Correct | Total | Accuracy |",
            "|-------------|---------|-------|----------|",
        ]
    )
    for conv in summary["by_conversation"]:
        lines.append(
            f"| {conv['conversation']} | {conv['correct']} "
            f"| {conv['total']} | {conv['accuracy']}% |"
        )
    lines.extend(
        [
            "",
            "## Retrieval Statistics",
            "",
            f"- Avg results per query: "
            f"{summary['retrieval_stats']['avg_results_per_query']}",
            f"- Injection rate: "
            f"{summary['retrieval_stats']['injection_rate_pct']}%",
        ]
    )

    diag = summary.get("retrieval_diagnostic", {})
    if diag:
        gold_in = diag.get("gold_in_context", 0)
        gold_in_correct = diag.get("gold_in_context_correct", 0)
        gold_in_wrong = diag.get("gold_in_context_wrong", 0)
        gold_out = diag.get("gold_not_in_context", 0)
        gold_out_correct = diag.get("gold_not_in_context_but_correct", 0)
        total_q = gold_in + gold_out
        lines.extend(
            [
                "",
                "## Retrieval Diagnostic",
                "",
                f"- Gold answer found in context: {gold_in}/{total_q} "
                f"({round(gold_in / total_q * 100, 1) if total_q else 0}%)",
                f"  - Correct when found: {gold_in_correct}/{gold_in} "
                f"({round(gold_in_correct / gold_in * 100, 1) if gold_in else 0}%)",
                f"  - Wrong despite found: {gold_in_wrong}/{gold_in} "
                f"({round(gold_in_wrong / gold_in * 100, 1) if gold_in else 0}%) — justifier failures",
                f"- Gold answer NOT in context: {gold_out}/{total_q} "
                f"({round(gold_out / total_q * 100, 1) if total_q else 0}%) — retrieval failures",
                f"  - Correct despite not found: {gold_out_correct}/{gold_out} "
                f"({round(gold_out_correct / gold_out * 100, 1) if gold_out else 0}%)",
            ]
        )

    pipeline = summary.get("pipeline_diagnostic", {})
    if pipeline and pipeline.get("questions_with_evidence"):
        total_q = pipeline["questions_with_evidence"]
        lines.extend(
            [
                "",
                "## Pipeline Diagnostic (where answers are lost)",
                "",
                f"- Evidence turns available: {total_q} questions",
                f"- Extracted into memory: {pipeline['extraction_found']}/{total_q} "
                f"({pipeline['extraction_rate']}%)",
                f"- Retrieved for query: {pipeline['retrieval_found']}/{total_q} "
                f"({pipeline['retrieval_rate']}%)",
                f"- Gold in justifier context: {pipeline['gold_in_context']}/{total_q} "
                f"({pipeline['context_rate']}%)",
                f"- Correct answer: {pipeline['correct']}/{total_q} "
                f"({pipeline['accuracy']}%)",
                "",
                f"Loss breakdown:",
                f"  - Lost at extraction: {pipeline['loss_at_extraction']} questions "
                f"(fact never created from evidence turn)",
                f"  - Lost at retrieval: {pipeline['loss_at_retrieval']} questions "
                f"(fact exists but not in top-{summary['retrieval_stats']['avg_results_per_query']:.0f} results)",
                f"  - Lost at justification: {pipeline['loss_at_justification']} questions "
                f"(answer in context but justifier got it wrong)",
            ]
        )

    failures = [
        r
        for r in results
        if not r["correct"] and not r["predicted_answer"].startswith("[ERROR")
    ]
    if failures:
        shown = min(10, len(failures))
        lines.extend(
            [
                "",
                f"## Sample Failures (showing {shown} of {len(failures)})",
                "",
            ]
        )
        for r in failures[:shown]:
            lines.append(
                f"- **{r['sample_id']}** [{r['category_name']}]: "
                f"{r['question']}"
            )
            lines.append(f"  - Gold: {r['gold_answer']}")
            lines.append(
                f"  - Predicted: {r['predicted_answer'][:200]}"
            )
            lines.append(f"  - Judge: {r['judge_reasoning']}")
            lines.append(
                f"  - Retrieved: {r['result_count']} results, "
                f"{r['injectable_block_count']} blocks"
            )
            lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _load_dataset(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def _download_dataset(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading LoCoMo dataset to {path} ...")
    urllib.request.urlretrieve(LOCOMO_DATASET_URL, path)
    print("Done.")


if __name__ == "__main__":
    raise SystemExit(main())
