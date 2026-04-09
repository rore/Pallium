"""LongMemEval benchmark -- end-to-end memory accuracy on multi-session conversational QA.

Evaluates Pallium against the LongMemEval dataset (ICLR 2025), measuring ability
to answer factual questions about multi-session conversations using per-question
isolated ingestion, semantic extraction, and type-specific
LLM-as-judge scoring.

Dataset: https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned
Paper: "LongMemEval: Benchmarking Chat Assistants on Long-Term Interactive Memory" (ICLR 2025)

Usage:
    python -m evals.longmemeval_benchmark --download
    python -m evals.longmemeval_benchmark --mini
    python -m evals.longmemeval_benchmark --question-types knowledge-update temporal-reasoning
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
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app
from providers.llm.base import LLMProvider

DEFAULT_DATASET_PATH = Path("evals/longmemeval/datasets/longmemeval_s_cleaned.json")
DEFAULT_ORACLE_PATH = Path("data/longmemeval/longmemeval_oracle.json")
DEFAULT_OUTPUT_DIR = Path("evals/longmemeval/output")
DEFAULT_DB_CACHE_DIR = Path("evals/longmemeval/db_cache")

HF_REPO_URL = "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main"
DOWNLOAD_VARIANTS = {
    "s": ("longmemeval_s_cleaned.json", DEFAULT_DATASET_PATH),
    "oracle": ("longmemeval_oracle.json", DEFAULT_ORACLE_PATH),
}

QUESTION_TYPES = [
    "single-session-user",
    "single-session-assistant",
    "single-session-preference",
    "multi-session",
    "temporal-reasoning",
    "knowledge-update",
]

BATCH_SIZE = 50

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
# Judge prompts — type-specific, following the LongMemEval paper methodology.
# ---------------------------------------------------------------------------

_JUDGE_STANDARD = """\
Your task is to judge whether a generated answer to a question is correct.
You will be given a question, a gold (ground truth) answer, and a generated answer.

Please answer yes if the response contains the correct answer. If the response is \
equivalent to the correct answer or contains all the intermediate steps to get the \
correct answer, you should also answer yes. If the response only contains a subset \
of the information required by the answer, answer no.

Be generous: as long as the generated answer touches on the same topic and conveys \
the same core fact as the gold answer, count it as correct.

There's an edge case where the answer cannot be found in the data. If the gold answer \
says so (e.g. 'not mentioned') and the generated answer says it cannot be answered \
or doesn't know, it should be counted as correct.

Return a JSON object with:
- correct: true if the generated answer is correct, false otherwise
- reasoning: one sentence explanation of your judgement (keep it short)\
"""

_JUDGE_TEMPORAL = """\
Your task is to judge whether a generated answer to a question is correct.
You will be given a question, a gold (ground truth) answer, and a generated answer.

Please answer yes if the response contains the correct answer. If the response is \
equivalent to the correct answer or contains all the intermediate steps to get the \
correct answer, you should also answer yes. If the response only contains a subset \
of the information required by the answer, answer no.

Do not penalize off-by-one errors for the number of days. If the question asks for \
the number of days/weeks/months, etc., and the model makes off-by-one errors \
(e.g., predicting 19 days when the answer is 18), the model's response is still correct.

For time-related questions, the gold answer will be a specific date, month, year, etc. \
The generated answer might use relative time references or different formats, but as long \
as it refers to the same date or time period as the gold answer, it should be counted as \
correct. Even if the format differs (e.g., "May 7th" vs "7 May"), consider it correct.

Return a JSON object with:
- correct: true if the generated answer is correct, false otherwise
- reasoning: one sentence explanation of your judgement (keep it short)\
"""

_JUDGE_KNOWLEDGE_UPDATE = """\
Your task is to judge whether a generated answer to a question is correct.
You will be given a question, a gold (ground truth) answer, and a generated answer.

The question asks about information that has been updated over time. The gold answer \
reflects the most recent/updated value.

If the response contains some previous information along with an updated answer, the \
response should be considered as correct as long as the updated answer is the required \
answer. The key test is whether the generated answer includes the current/updated value.

Return a JSON object with:
- correct: true if the generated answer is correct, false otherwise
- reasoning: one sentence explanation of your judgement (keep it short)\
"""

_JUDGE_ABSTENTION = """\
Your task is to judge whether a generated answer correctly identifies a question as \
unanswerable based on the available information.

The question asks about something that was never mentioned in the conversation history. \
The correct response is to say that the information is not available or unknown.

Please answer yes if the model correctly identifies the question as unanswerable. \
The model could say that the information is incomplete, not found, or that the asked \
information was never mentioned. Any form of appropriate abstention counts as correct.

Return a JSON object with:
- correct: true if the model correctly abstains, false otherwise
- reasoning: one sentence explanation of your judgement (keep it short)\
"""

_JUDGE_PREFERENCE = """\
Your task is to judge whether a generated answer satisfies a question about user preferences.
You will be given a question, a gold answer (which serves as a rubric), and a generated answer.

Please answer yes if the response satisfies the desired response. The model does not \
need to reflect all the points in the rubric. The response is correct as long as it \
recalls and utilizes the user's personal information correctly to provide a relevant, \
personalized response.

Return a JSON object with:
- correct: true if the generated answer is correct, false otherwise
- reasoning: one sentence explanation of your judgement (keep it short)\
"""


def _judge_prompt_for_question(question_id: str, question_type: str) -> str:
    """Select the appropriate judge prompt based on question type and ID."""
    if question_id.endswith("_abs"):
        return _JUDGE_ABSTENTION
    if question_type == "temporal-reasoning":
        return _JUDGE_TEMPORAL
    if question_type == "knowledge-update":
        return _JUDGE_KNOWLEDGE_UPDATE
    if question_type == "single-session-preference":
        return _JUDGE_PREFERENCE
    return _JUDGE_STANDARD


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the LongMemEval end-to-end benchmark."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-name", default=None)
    parser.add_argument(
        "--question-types",
        nargs="*",
        default=None,
        help="Filter to specific question types (e.g., knowledge-update temporal-reasoning).",
    )
    parser.add_argument(
        "--limit-questions",
        type=int,
        default=None,
        help="Max questions to evaluate (for quick testing).",
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
        "--download",
        action="store_true",
        help="Download the LongMemEval dataset if not present.",
    )
    parser.add_argument(
        "--variant",
        default="s",
        choices=sorted(DOWNLOAD_VARIANTS),
        help="Which variant to download: s (default) or oracle.",
    )
    parser.add_argument(
        "--db-cache-dir",
        type=Path,
        default=None,
        help="Cache processed DBs per question. Skips ingestion+extraction on reuse.",
    )
    parser.add_argument(
        "--rebuild-db-cache",
        action="store_true",
        help="Force rebuild of cached DBs even if they exist.",
    )
    parser.add_argument(
        "--mini",
        action="store_true",
        help="Run a small representative subset (3 questions per category).",
    )
    parser.add_argument(
        "--verbose-results",
        action="store_true",
        help="Record full retrieval details in results for diagnostic analysis.",
    )
    args = parser.parse_args()

    # Auto-set --dataset when --variant oracle is used and --dataset was not
    # explicitly provided (still has the default value).
    if args.variant == "oracle" and args.dataset == DEFAULT_DATASET_PATH:
        args.dataset = DEFAULT_ORACLE_PATH

    if args.download:
        _download_dataset(args.variant)
        # Exit early if download was the sole intent (no run flags).
        if not args.limit_questions and not args.mini and not args.question_types:
            return 0

    if not args.dataset.exists():
        print(f"Dataset not found at {args.dataset}")
        print("Download it with:  python -m evals.longmemeval_benchmark --download")
        return 1

    run_dir = run_longmemeval_benchmark(
        dataset_path=args.dataset,
        output_root=args.output_dir,
        config=AppConfig.from_env(),
        run_name=args.run_name,
        question_types=args.question_types,
        limit_questions=args.limit_questions,
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


def run_longmemeval_benchmark(
    *,
    dataset_path: Path,
    output_root: Path,
    config: AppConfig,
    run_name: str | None = None,
    answer_provider: LLMProvider | None = None,
    question_types: list[str] | None = None,
    limit_questions: int | None = None,
    query_limit: int = 10,
    cache_dir: Path | None = None,
    db_cache_dir: Path | None = None,
    rebuild_db_cache: bool = False,
    mini: bool = False,
    verbose_results: bool = False,
) -> Path:

    dataset = _load_dataset(dataset_path)

    # Filter by question type.
    if question_types:
        dataset = [q for q in dataset if q.get("question_type") in question_types]
        if not dataset:
            raise ValueError(f"No questions found matching types: {question_types}")

    # Mini mode: 3 questions per category for fast iteration.
    if mini:
        by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for q in dataset:
            by_type[q.get("question_type", "unknown")].append(q)
        dataset = []
        for qt in sorted(by_type):
            dataset.extend(by_type[qt][:3])

    if limit_questions:
        dataset = dataset[:limit_questions]

    default_package = config.package_config(config.default_use_case)
    if answer_provider is None:
        if not default_package.llm_provider or not default_package.model:
            raise ValueError(
                f"Default use case '{config.default_use_case}' is missing "
                "LLM package config"
            )
        from app.dependencies import build_llm_provider
        provider = build_llm_provider(
            config,
            provider_name=default_package.llm_provider,
            model=default_package.model,
        )
    else:
        provider = answer_provider

    run_id = run_name or _build_run_id(config)
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    results_path = run_dir / "results.jsonl"

    # --- Phase 1: DB work (sequential) ---
    # Ingest, extract, query, and build evidence traces.
    # Each question needs its own isolated DB, so this must be sequential.
    # We create one TestClient and swap the service per question to avoid
    # re-initializing the embedding model (~2-4s) on every question.
    initial_config = replace(
        config,
        default_use_case="agent_conversation_memory",
    )
    qa_inputs: list[tuple[int, dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    with TestClient(create_app(initial_config)) as client:
        for q_index, question in enumerate(dataset):
            question_id = question["question_id"]
            print(
                f"\n[{q_index + 1}/{len(dataset)}] {question_id} "
                f"({question.get('question_type', '?')})..."
            )

            memory_payload, evidence_trace = _process_question(
                client=client,
                question=question,
                config=config,
                query_limit=query_limit,
                cache_dir=cache_dir,
                db_cache_dir=db_cache_dir,
                rebuild_db_cache=rebuild_db_cache,
            )
            qa_inputs.append((q_index, question, memory_payload, evidence_trace))

    # --- Phase 2: LLM evaluation (parallel) ---
    # Answer generation + judging are pure LLM calls, parallelized across questions.
    print(f"\nEvaluating {len(qa_inputs)} questions (parallel)...")

    def _eval_one(
        entry: tuple[int, dict[str, Any], dict[str, Any], dict[str, Any]],
    ) -> tuple[int, dict[str, Any]]:
        q_idx, q, mem_payload, ev_trace = entry
        result = _evaluate_question_from_retrieval(
            answer_provider=provider,
            question=q,
            memory_payload=mem_payload,
            verbose=verbose_results,
        )
        result["evidence_trace"] = ev_trace
        return q_idx, result

    all_results: list[dict[str, Any]] = [{}] * len(qa_inputs)
    with results_path.open("w", encoding="utf-8") as results_file:
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                pool.submit(_eval_one, inp): inp[0]
                for inp in qa_inputs
            }
            done_count = 0
            for future in as_completed(futures):
                idx, result = future.result()
                all_results[idx] = result
                done_count += 1
                status = "correct" if result["correct"] else "WRONG"
                if done_count % 10 == 0 or done_count == len(qa_inputs):
                    correct_so_far = sum(
                        1 for r in all_results if r.get("correct")
                    )
                    print(
                        f"  Eval progress: {done_count}/{len(qa_inputs)} "
                        f"({correct_so_far} correct)"
                    )

        # Write results in original order.
        for result in all_results:
            results_file.write(json.dumps(result) + "\n")

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
# Per-question evaluation
# ---------------------------------------------------------------------------


def _process_question(
    *,
    client: TestClient,
    question: dict[str, Any],
    config: AppConfig,
    query_limit: int,
    cache_dir: Path | None = None,
    db_cache_dir: Path | None = None,
    rebuild_db_cache: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """DB-bound work: ingest, extract, query, build evidence trace.

    Swaps the service on the shared TestClient per question (fresh DB + vector
    index) while reusing the app's embedding model and LLM providers.

    Returns (memory_payload, evidence_trace).
    """
    question_id = question["question_id"]
    sessions = question.get("haystack_sessions", [])
    session_dates = question.get("haystack_dates", [])
    session_ids = question.get("haystack_session_ids", [])

    # DB caching: reuse a processed DB if available.
    cached_db_path = None
    use_cached_db = False
    if db_cache_dir is not None:
        db_cache_dir.mkdir(parents=True, exist_ok=True)
        cached_db_path = db_cache_dir / f"{question_id}.db"
        cached_vector_prefix = db_cache_dir / f"{question_id}.vector.index"
        use_cached_db = (
            not rebuild_db_cache
            and cached_db_path.exists()
            and cached_vector_prefix.exists()
        )

    # Reuse embedding provider from the shared app's service.
    original_service = client.app.state.pallium_service
    shared_embedding = original_service._embedding_provider

    with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = Path(temp_dir) / "longmemeval.db"
        vector_path = Path(temp_dir) / "vector.index"

        if use_cached_db:
            shutil.copy2(cached_db_path, db_path)
            _copy_vector_index(cached_vector_prefix, vector_path)
            print(f"  Using cached DB for {question_id}")

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

        # Build a new service with fresh DB but reuse the shared embedding provider.
        from app.dependencies import (
            build_retrieval_provider,
            build_semantic_plugins,
            build_storage_provider,
        )
        from core.observability import IntegrationDebugLogger
        from core.service import PalliumService
        from core.type_registry import TypeRegistry
        from retrieval.composite import CompositeRetrievalProvider
        from retrieval.vector import VectorRetrievalProvider
        from storage.vector_index import VectorIndex

        storage = build_storage_provider(scenario_config)
        plugins = build_semantic_plugins(scenario_config)
        retrieval = build_retrieval_provider(storage)

        # Reuse embedding provider; build fresh vector index for this question's DB.
        vector_index = None
        if shared_embedding is not None:
            index_path = Path(scenario_config.vector_index.index_path)
            try:
                if index_path.exists() and Path(f"{index_path}.meta.json").exists():
                    vector_index = VectorIndex.load(index_path)
                else:
                    vector_index = VectorIndex.create_empty(
                        index_path,
                        dimensions=shared_embedding.dimensions(),
                        model_name=shared_embedding.model_name(),
                    )
            except Exception:
                vector_index = None

            if vector_index is not None:
                vector_retrieval = VectorRetrievalProvider(
                    storage=storage,
                    vector_index=vector_index,
                    embedding_provider=shared_embedding,
                    min_similarity=scenario_config.vector_index.min_similarity,
                )
                retrieval = CompositeRetrievalProvider(
                    lexical=retrieval,
                    vector=vector_retrieval,
                )

        type_registry = TypeRegistry()
        for plugin in plugins.values():
            register_fn = getattr(plugin, "register_routing_types", None)
            if callable(register_fn):
                register_fn(type_registry)

        service = PalliumService(
            storage=storage,
            retrieval=retrieval,
            semantic_plugins=plugins,
            default_use_case=scenario_config.default_use_case,
            observability=IntegrationDebugLogger(enabled=False),
            retention_enabled=False,
            embedding_provider=shared_embedding,
            vector_index=vector_index,
            type_registry=type_registry if len(type_registry) > 0 else None,
        )
        client.app.state.pallium_service = service

        # Wrap LLM providers with cache on the new service (must happen after swap).
        if cache_dir is not None:
            from evals.generated_exploratory.invariant_runner import (
                _wrap_providers_with_cache,
            )
            _wrap_providers_with_cache(client, cache_dir)

        if not use_cached_db:
            # --- ingest all sessions ---
            has_answer_source_ids = _ingest_sessions(
                client=client,
                question_id=question_id,
                sessions=sessions,
                session_dates=session_dates,
                session_ids=session_ids,
            )
            print(
                f"  Ingested {sum(len(s) for s in sessions)} turns "
                f"across {len(sessions)} sessions"
            )

            # --- semantic extraction ---
            print("  Processing semantic extraction...")
            service.drain_processing_queue(worker_id="longmemeval-runner")
            service.reconcile_vector_index()

            print("  Processing complete")

            # Cache the processed DB for reuse.
            if cached_db_path is not None:
                shutil.copy2(db_path, cached_db_path)
                _copy_vector_index(vector_path, cached_vector_prefix)
                print(f"  Cached DB for {question_id}")
        else:
            # Reconstruct has_answer_source_ids from the sessions data.
            has_answer_source_ids = _collect_has_answer_source_ids(
                question_id=question_id,
                sessions=sessions,
                session_ids=session_ids,
            )

        # --- build evidence map ---
        evidence_map = _build_evidence_map(client=client)

        # --- query ---
        query_payload = {
            "text": question["question"],
            "limit": query_limit,
            "container_ref": question_id,
            "visibility": "public",
            "runtime_context": {
                "turn_kind": "new_session",
                "session_has_sufficient_local_context": False,
            },
        }
        query_response = client.post("/query/debug", json=query_payload)
        query_response.raise_for_status()
        memory_payload = query_response.json()

        # --- evidence trace ---
        evidence_trace = _build_evidence_trace(
            question=question,
            has_answer_source_ids=has_answer_source_ids,
            evidence_map=evidence_map,
            retrieval_result_ids=_extract_result_memory_ids(memory_payload),
            session_ids=session_ids,
            memory_payload=memory_payload,
        )

        engine = getattr(service._storage, "_engine", None)
        if engine is not None:
            engine.dispose()

        # Restore original service so the shared client stays usable.
        client.app.state.pallium_service = original_service

    return memory_payload, evidence_trace


# ---------------------------------------------------------------------------
# Ingestion helpers
# ---------------------------------------------------------------------------


def _ingest_sessions(
    *,
    client: TestClient,
    question_id: str,
    sessions: list[list[dict[str, Any]]],
    session_dates: list[str],
    session_ids: list,
) -> set[str]:
    """Ingest all haystack sessions. Returns set of source_ids with has_answer=true."""
    has_answer_source_ids: set[str] = set()
    all_items: list[dict[str, Any]] = []

    for session_idx, session_turns in enumerate(sessions):
        session_date = _parse_longmemeval_date(
            session_dates[session_idx]
        ) if session_idx < len(session_dates) else None

        session_id = (
            session_ids[session_idx]
            if session_idx < len(session_ids)
            else session_idx
        )

        for turn_idx, turn in enumerate(session_turns):
            source_id = f"{question_id}_{session_id}_{turn_idx}"
            item: dict[str, Any] = {
                "source_type": "chat_message",
                "source_id": source_id,
                "content_type": "text/plain",
                "content": turn["content"],
                "role": turn.get("role", "user"),
                "actor_ref": turn.get("role", "user"),
                "container_ref": question_id,
                "thread_ref": f"{question_id}_{session_id}",
                "artifact_kind": "message",
                "visibility": "public",
            }
            if session_date:
                item["occurred_at"] = session_date.isoformat()
            all_items.append(item)

            if turn.get("has_answer"):
                has_answer_source_ids.add(source_id)

    for start in range(0, len(all_items), BATCH_SIZE):
        batch = all_items[start : start + BATCH_SIZE]
        response = client.post("/items", json=batch)
        response.raise_for_status()

    return has_answer_source_ids


def _collect_has_answer_source_ids(
    *,
    question_id: str,
    sessions: list[list[dict[str, Any]]],
    session_ids: list,
) -> set[str]:
    """Collect has_answer source_ids without ingesting (for cached DB path)."""
    has_answer_source_ids: set[str] = set()
    for session_idx, session_turns in enumerate(sessions):
        session_id = (
            session_ids[session_idx]
            if session_idx < len(session_ids)
            else session_idx
        )
        for turn_idx, turn in enumerate(session_turns):
            if turn.get("has_answer"):
                has_answer_source_ids.add(
                    f"{question_id}_{session_id}_{turn_idx}"
                )
    return has_answer_source_ids


def _parse_longmemeval_date(date_str: str) -> datetime | None:
    """Parse LongMemEval date like '2023/04/10 (Mon) 17:50'."""
    try:
        cleaned = re.sub(r"\s*\([A-Za-z]+\)\s*", " ", date_str).strip()
        return datetime.strptime(cleaned, "%Y/%m/%d %H:%M").replace(
            tzinfo=timezone.utc
        )
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# Evaluation: generate answer & judge
# ---------------------------------------------------------------------------


def _evaluate_question_from_retrieval(
    *,
    answer_provider: LLMProvider,
    question: dict[str, Any],
    memory_payload: dict[str, Any],
    verbose: bool = False,
) -> dict[str, Any]:
    """Evaluate a question given pre-fetched retrieval results."""
    question_id = question["question_id"]
    question_text = question["question"]
    question_type = question.get("question_type", "unknown")
    question_date = question.get("question_date", "")
    gold_answer = str(question.get("answer", ""))
    is_abstention = question_id.endswith("_abs")

    retrieved_context = _format_retrieved_context(memory_payload)
    answer_result = _generate_answer(
        provider=answer_provider,
        question=question_text,
        retrieved_context=retrieved_context,
        question_date=question_date,
    )

    judge_result = _judge_answer(
        provider=answer_provider,
        question=question_text,
        gold_answer=gold_answer,
        predicted_answer=answer_result["answer"],
        question_id=question_id,
        question_type=question_type,
    )

    gold_in_context = _gold_in_context(
        gold_answer,
        retrieved_context,
        provider=answer_provider,
        question=question_text,
    )

    result: dict[str, Any] = {
        "question_id": question_id,
        "question": question_text,
        "question_type": question_type,
        "question_date": question_date,
        "gold_answer": gold_answer,
        "is_abstention": is_abstention,
        "predicted_answer": answer_result["answer"],
        "answer_reasoning": answer_result.get("reasoning", ""),
        "correct": judge_result["correct"],
        "judge_reasoning": judge_result["reasoning"],
        "result_count": len(memory_payload.get("results", [])),
        "should_inject": memory_payload.get("should_inject"),
        "decision_reason": memory_payload.get("decision_reason"),
        "injectable_block_count": len(
            memory_payload.get("injectable_blocks", [])
        ),
        "retrieval_summary": _retrieval_summary(memory_payload),
        "gold_in_context": gold_in_context,
    }

    if verbose:
        result["retrieved_results"] = _compact_results(memory_payload)
        result["justifier_context"] = retrieved_context[:2000]

    return result


def _format_retrieved_context(memory_payload: dict[str, Any]) -> str:
    """Format Pallium retrieval results for the justifier LLM."""
    parts: list[str] = []

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


def _generate_answer(
    *,
    provider: LLMProvider,
    question: str,
    retrieved_context: str,
    question_date: str,
) -> dict[str, Any]:
    """Generate an answer from retrieved context (justifier step)."""
    system_prompt = (
        "You are a factual retrieval evaluator. Your ONLY job is to answer "
        "questions using the provided context about a user's conversation history. "
        "You must NEVER use your own knowledge, training data, or common sense.\n\n"
        "CRITICAL RULES:\n"
        "- The context is the only source of truth. Your training knowledge is IRRELEVANT.\n"
        "- If information was updated over time, use the MOST RECENT version "
        "(later date or later in the context).\n"
        "- Pay close attention to dates and timestamps in the evidence.\n"
        "- If the context does not contain enough information to answer, say 'not found'.\n\n"
        "Return a JSON object with 'answer' (short, specific) and 'reasoning' (one sentence)."
    )
    date_line = f"Current Date: {question_date}\n\n" if question_date else ""
    user_prompt = (
        f"{date_line}"
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


def _judge_answer(
    *,
    provider: LLMProvider,
    question: str,
    gold_answer: str,
    predicted_answer: str,
    question_id: str,
    question_type: str,
) -> dict[str, Any]:
    """Judge whether the predicted answer is correct (type-specific LLM-as-judge)."""
    judge_prompt = _judge_prompt_for_question(question_id, question_type)
    user_prompt = (
        f"Question: {question}\n"
        f"Gold answer: {gold_answer}\n"
        f"Generated answer: {predicted_answer}"
    )
    try:
        response = provider.generate_json(
            system_prompt=judge_prompt,
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


def _retrieval_summary(memory_payload: dict[str, Any]) -> dict[str, Any]:
    results = memory_payload.get("results", [])
    memory_hits = [
        r for r in results if r.get("result_kind") == "memory_hit"
    ]
    source_hits = [
        r for r in results if r.get("result_kind") == "source_hit"
    ]
    memory_types = sorted(
        {r.get("type", "") for r in memory_hits if r.get("type")}
    )
    return {
        "total_results": len(results),
        "memory_hits": len(memory_hits),
        "source_hits": len(source_hits),
        "memory_types": memory_types,
    }


def _gold_in_context(
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
        return _gold_in_context_llm(
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


def _gold_in_context_llm(
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
        return _gold_in_context(gold_answer, context)


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
# Evidence trace
# ---------------------------------------------------------------------------


def _build_evidence_map(
    *,
    client: TestClient,
) -> dict[str, list[dict[str, Any]]]:
    """Build source_id → memory objects map for pipeline tracing."""
    storage = client.app.state.pallium_service._storage
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


def _build_evidence_trace(
    *,
    question: dict[str, Any],
    has_answer_source_ids: set[str],
    evidence_map: dict[str, list[dict[str, Any]]],
    retrieval_result_ids: set[str],
    session_ids: list,
    memory_payload: dict[str, Any],
) -> dict[str, Any]:
    """Trace evidence turns through the pipeline: ingestion → extraction → retrieval."""
    answer_session_ids = set(str(sid) for sid in question.get("answer_session_ids", []))

    # Check if any answer session appeared in retrieval results via thread_ref.
    retrieved_thread_refs: set[str] = set()
    for r in memory_payload.get("results", []):
        evidence = r.get("evidence") or []
        for e in evidence:
            thread_ref = e.get("thread_ref", "")
            if thread_ref:
                retrieved_thread_refs.add(thread_ref)
        # Also check payload for thread_ref.
        payload = r.get("payload") or {}
        if payload.get("thread_ref"):
            retrieved_thread_refs.add(payload["thread_ref"])

    question_id = question["question_id"]
    answer_session_hit = any(
        f"{question_id}_{sid}" in retrieved_thread_refs
        for sid in answer_session_ids
    )

    if not has_answer_source_ids:
        return {
            "has_answer_source_ids": [],
            "extraction_found": False,
            "retrieval_found": False,
            "answer_session_hit": answer_session_hit,
        }

    any_extracted = False
    any_retrieved = False
    traces: list[dict[str, Any]] = []

    for source_id in sorted(has_answer_source_ids):
        memories = evidence_map.get(source_id, [])
        extracted = len(memories) > 0
        retrieved = any(m["memory_id"] in retrieval_result_ids for m in memories)
        if extracted:
            any_extracted = True
        if retrieved:
            any_retrieved = True
        traces.append({
            "source_id": source_id,
            "extracted": extracted,
            "memory_count": len(memories),
            "memory_types": [m["type"] for m in memories],
            "retrieved": retrieved,
        })

    return {
        "has_answer_source_ids": sorted(has_answer_source_ids),
        "traces": traces,
        "extraction_found": any_extracted,
        "retrieval_found": any_retrieved,
        "answer_session_hit": answer_session_hit,
    }


def _extract_result_memory_ids(memory_payload: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for r in memory_payload.get("results", []):
        if r.get("result_kind") == "memory_hit" and r.get("memory_object_id"):
            ids.add(r["memory_object_id"])
    return ids


# ---------------------------------------------------------------------------
# Summary & report
# ---------------------------------------------------------------------------


def _build_pipeline_diagnostic(results: list[dict[str, Any]]) -> dict[str, Any]:
    with_trace = [
        r for r in results
        if r.get("evidence_trace", {}).get("has_answer_source_ids")
    ]
    if not with_trace:
        return {}
    total = len(with_trace)
    extracted = sum(1 for r in with_trace if r["evidence_trace"]["extraction_found"])
    retrieved = sum(1 for r in with_trace if r["evidence_trace"]["retrieval_found"])
    session_hit = sum(1 for r in with_trace if r["evidence_trace"].get("answer_session_hit"))
    in_context = sum(1 for r in with_trace if r.get("gold_in_context"))
    correct = sum(1 for r in with_trace if r["correct"])

    return {
        "questions_with_evidence": total,
        "extraction_found": extracted,
        "extraction_rate": round(extracted / total * 100, 1) if total else 0,
        "retrieval_found": retrieved,
        "retrieval_rate": round(retrieved / total * 100, 1) if total else 0,
        "answer_session_hit": session_hit,
        "answer_session_hit_rate": round(session_hit / total * 100, 1) if total else 0,
        "gold_in_context": in_context,
        "context_rate": round(in_context / total * 100, 1) if total else 0,
        "correct": correct,
        "accuracy": round(correct / total * 100, 1) if total else 0,
        "loss_at_extraction": total - extracted,
        "loss_at_retrieval": extracted - retrieved,
        "loss_at_justification": max(0, in_context - correct),
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

    # Per question-type breakdown.
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in results:
        by_type[r["question_type"]].append(r)
    type_stats = []
    for qt in QUESTION_TYPES:
        qt_results = by_type.get(qt, [])
        if not qt_results:
            continue
        qt_total = len(qt_results)
        qt_invalid = sum(
            1 for r in qt_results
            if r["predicted_answer"].startswith("[ERROR")
        )
        qt_valid = qt_total - qt_invalid
        qt_correct = sum(1 for r in qt_results if r["correct"])
        qt_gold_in_ctx = sum(1 for r in qt_results if r.get("gold_in_context"))
        qt_injected = sum(1 for r in qt_results if r.get("should_inject"))
        qt_session_hit = sum(
            1 for r in qt_results
            if r.get("evidence_trace", {}).get("answer_session_hit")
        )
        type_stats.append({
            "question_type": qt,
            "total": qt_total,
            "correct": qt_correct,
            "accuracy": round(qt_correct / qt_valid * 100, 1) if qt_valid else 0,
            "gold_in_context": qt_gold_in_ctx,
            "gold_in_context_rate": round(qt_gold_in_ctx / qt_total * 100, 1) if qt_total else 0,
            "injection_rate": round(qt_injected / qt_total * 100, 1) if qt_total else 0,
            "answer_session_hit_rate": round(qt_session_hit / qt_total * 100, 1) if qt_total else 0,
        })

    # Abstention breakdown.
    abstention_results = [r for r in results if r.get("is_abstention")]
    abstention_total = len(abstention_results)
    abstention_correct = sum(1 for r in abstention_results if r["correct"])

    avg_results = (
        sum(r["result_count"] for r in results) / total if total else 0
    )
    inject_count = sum(1 for r in results if r["should_inject"])

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
        "memory_delivery_accuracy": round(gold_in_ctx / valid * 100, 1) if valid else 0,
        "justifier_failures": gold_in_ctx_wrong,
        "by_question_type": type_stats,
        "abstention": {
            "total": abstention_total,
            "correct": abstention_correct,
            "accuracy": round(abstention_correct / abstention_total * 100, 1) if abstention_total else 0,
        },
        "retrieval_stats": {
            "avg_results_per_query": round(avg_results, 1),
            "injection_rate_pct": round(inject_count / total * 100, 1) if total else 0,
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
        "# LongMemEval Benchmark Report",
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
        f"Memory delivery accuracy: **{summary['memory_delivery_accuracy']}%** "
        f"(gold answer in retrieved context — Pallium's retrieval success rate)",
        f"Justifier failures: {summary['justifier_failures']} "
        f"(correct context delivered but answer generation failed)",
        "",
        "## By Question Type",
        "",
        "| Type | Correct | Total | Accuracy | Gold in Ctx | Inject Rate | Session Hit |",
        "|------|---------|-------|----------|-------------|-------------|-------------|",
    ]
    for qt in summary["by_question_type"]:
        lines.append(
            f"| {qt['question_type']} | {qt['correct']} | {qt['total']} "
            f"| {qt['accuracy']}% | {qt['gold_in_context_rate']}% "
            f"| {qt['injection_rate']}% | {qt['answer_session_hit_rate']}% |"
        )

    abstention = summary.get("abstention", {})
    if abstention.get("total"):
        lines.extend([
            "",
            "## Abstention Questions",
            "",
            f"**{abstention['accuracy']}%** "
            f"({abstention['correct']}/{abstention['total']} correct)",
        ])

    lines.extend([
        "",
        "## Retrieval Statistics",
        "",
        f"- Avg results per query: "
        f"{summary['retrieval_stats']['avg_results_per_query']}",
        f"- Injection rate: "
        f"{summary['retrieval_stats']['injection_rate_pct']}%",
    ])

    diag = summary.get("retrieval_diagnostic", {})
    if diag:
        gold_in = diag.get("gold_in_context", 0)
        gold_in_correct = diag.get("gold_in_context_correct", 0)
        gold_in_wrong = diag.get("gold_in_context_wrong", 0)
        gold_out = diag.get("gold_not_in_context", 0)
        gold_out_correct = diag.get("gold_not_in_context_but_correct", 0)
        total_q = gold_in + gold_out
        lines.extend([
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
        ])

    pipeline = summary.get("pipeline_diagnostic", {})
    if pipeline and pipeline.get("questions_with_evidence"):
        total_q = pipeline["questions_with_evidence"]
        lines.extend([
            "",
            "## Pipeline Diagnostic (where answers are lost)",
            "",
            f"- Evidence turns available: {total_q} questions",
            f"- Extracted into memory: {pipeline['extraction_found']}/{total_q} "
            f"({pipeline['extraction_rate']}%)",
            f"- Retrieved for query: {pipeline['retrieval_found']}/{total_q} "
            f"({pipeline['retrieval_rate']}%)",
            f"- Answer session in results: {pipeline['answer_session_hit']}/{total_q} "
            f"({pipeline['answer_session_hit_rate']}%)",
            f"- Gold in justifier context: {pipeline['gold_in_context']}/{total_q} "
            f"({pipeline['context_rate']}%)",
            f"- Correct answer: {pipeline['correct']}/{total_q} "
            f"({pipeline['accuracy']}%)",
            "",
            "Loss breakdown:",
            f"  - Lost at extraction: {pipeline['loss_at_extraction']} questions "
            f"(fact never created from evidence turn)",
            f"  - Lost at retrieval: {pipeline['loss_at_retrieval']} questions "
            f"(fact exists but not in top results)",
            f"  - Lost at justification: {pipeline['loss_at_justification']} questions "
            f"(answer in context but justifier got it wrong)",
        ])

    failures = [
        r
        for r in results
        if not r["correct"] and not r["predicted_answer"].startswith("[ERROR")
    ]
    if failures:
        shown = min(10, len(failures))
        lines.extend([
            "",
            f"## Sample Failures (showing {shown} of {len(failures)})",
            "",
        ])
        for r in failures[:shown]:
            lines.append(
                f"- **{r['question_id']}** [{r['question_type']}]: "
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


def _download_dataset(variant: str) -> None:
    filename, target_path = DOWNLOAD_VARIANTS[variant]
    if target_path.exists():
        print(f"Dataset already exists at {target_path}")
        return
    target_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"{HF_REPO_URL}/{filename}"
    print(f"Downloading LongMemEval ({variant}) to {target_path} ...")
    print(f"Source: {url}")
    print("(This may take a few minutes for the _s variant)")
    urllib.request.urlretrieve(url, target_path)
    print("Done.")


def _copy_vector_index(src: Path, dst: Path) -> None:
    """Copy all vector index files (main + .idmap.json + .meta.json)."""
    for suffix in ("", ".idmap.json", ".meta.json"):
        src_file = Path(f"{src}{suffix}")
        dst_file = Path(f"{dst}{suffix}")
        if src_file.exists():
            shutil.copy2(src_file, dst_file)


def _build_run_id(config: AppConfig) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    provider = (
        config.llm_provider_for_default_use_case or "provider"
    ).replace("_", "-")
    model = (
        (config.llm_model_for_default_use_case or "model")
        .replace("/", "-")
        .replace(".", "-")
    )
    return f"longmemeval-benchmark__{provider}__{model}__{timestamp}"


if __name__ == "__main__":
    raise SystemExit(main())
