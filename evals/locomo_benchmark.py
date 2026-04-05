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
import urllib.request
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from fastapi.testclient import TestClient

from app.config import AppConfig
from app.dependencies import build_llm_provider
from app.main import create_app
from providers.llm.base import LLMProvider

DEFAULT_DATASET_PATH = Path("evals/locomo/datasets/locomo10.json")
DEFAULT_OUTPUT_DIR = Path("evals/locomo/output")
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

ANSWER_SCHEMA = '{"answer":"string","reasoning":"string"}'
JUDGE_SCHEMA = '{"correct":"boolean","reasoning":"string"}'

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
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Directory for caching LLM extraction calls.",
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

    default_package = config.package_config(config.default_use_case)
    if answer_provider is None:
        if not default_package.llm_provider or not default_package.model:
            raise ValueError(
                f"Default use case '{config.default_use_case}' is missing "
                "LLM package config"
            )
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
                limit_questions=limit_questions,
                query_limit=query_limit,
                cache_dir=cache_dir,
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
    limit_questions: int | None,
    query_limit: int,
    cache_dir: Path | None,
) -> list[dict[str, Any]]:
    sample_id = conversation["sample_id"]
    conv = conversation["conversation"]
    qa_pairs = [qa for qa in conversation["qa"] if qa.get("category") != 5]
    if limit_questions:
        qa_pairs = qa_pairs[:limit_questions]

    sessions = _parse_sessions(conv)
    speaker_a = conv.get("speaker_a", "Speaker A")
    speaker_b = conv.get("speaker_b", "Speaker B")

    results: list[dict[str, Any]] = []

    with TemporaryDirectory() as temp_dir:
        database_url = f"sqlite:///{Path(temp_dir) / 'locomo.db'}"
        vector_index_config = replace(
            config.vector_index,
            index_path=str(Path(temp_dir) / "vector.index"),
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

            # --- evaluate each QA pair ---
            for qa_index, qa in enumerate(qa_pairs):
                result = _evaluate_question(
                    client=client,
                    answer_provider=answer_provider,
                    sample_id=sample_id,
                    qa=qa,
                    query_limit=query_limit,
                    speaker_a=speaker_a,
                    speaker_b=speaker_b,
                )
                results.append(result)

                if (qa_index + 1) % 50 == 0 or qa_index == len(qa_pairs) - 1:
                    correct_so_far = sum(
                        1 for r in results if r["correct"]
                    )
                    print(
                        f"  QA progress: {qa_index + 1}/{len(qa_pairs)} "
                        f"({correct_so_far} correct)"
                    )

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
    turn_count = 0
    for session_key, session_date, turns in sessions:
        for turn in turns:
            item = _turn_to_item(
                turn=turn,
                sample_id=sample_id,
                session_key=session_key,
                session_date=session_date,
                speaker_a=speaker_a,
                speaker_b=speaker_b,
            )
            response = client.post("/items", json=[item])
            response.raise_for_status()
            turn_count += 1
    return turn_count


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


def _evaluate_question(
    *,
    client: TestClient,
    answer_provider: LLMProvider,
    sample_id: str,
    qa: dict[str, Any],
    query_limit: int,
    speaker_a: str,
    speaker_b: str,
) -> dict[str, Any]:
    question = qa["question"]
    gold_answer = qa.get("answer", "")
    category = qa.get("category", 0)
    category_name = CATEGORY_NAMES.get(category, f"unknown_{category}")

    query_payload = {
        "text": question,
        "limit": query_limit,
        "container_ref": sample_id,
        "visibility": "public",
        "runtime_context": {
            "turn_kind": "new_session",
            "session_has_sufficient_local_context": False,
        },
    }
    query_response = client.post("/query/debug", json=query_payload)
    query_response.raise_for_status()
    memory_payload = query_response.json()

    retrieved_context = _format_retrieved_context(memory_payload)
    answer_result = _generate_answer(
        provider=answer_provider,
        question=question,
        retrieved_context=retrieved_context,
        speaker_a=speaker_a,
        speaker_b=speaker_b,
    )

    judge_result = _judge_answer(
        provider=answer_provider,
        question=question,
        gold_answer=gold_answer,
        predicted_answer=answer_result["answer"],
    )

    return {
        "sample_id": sample_id,
        "question": question,
        "gold_answer": gold_answer,
        "category": category,
        "category_name": category_name,
        "evidence_ids": qa.get("evidence", []),
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
    }


def _format_retrieved_context(memory_payload: dict[str, Any]) -> str:
    """Format Pallium retrieval results for the justifier LLM."""
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
                payload.get("carry_forward_answer")
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
    speaker_a: str,
    speaker_b: str,
) -> dict[str, Any]:
    """Generate an answer from retrieved context (justifier step)."""
    system_prompt = (
        f"You are a helpful assistant answering questions about conversations "
        f"between {speaker_a} and {speaker_b} based on retrieved memory "
        f"context. Answer based only on the provided context. Be specific and "
        f"concise. Return a JSON object with 'answer' and 'reasoning' fields."
    )
    user_prompt = (
        "# INSTRUCTIONS:\n"
        "1. Carefully analyze all provided memories and evidence\n"
        "2. Pay special attention to timestamps to determine the answer\n"
        "3. If the question asks about a specific event or fact, look for "
        "direct evidence in the memories\n"
        "4. If memories contain contradictory information or multiple "
        "instances, mention all of them\n"
        "5. Convert relative time references to specific dates when possible\n"
        "6. Be as specific as possible about people, places, and events\n"
        "7. If the answer is not explicitly stated, use logical reasoning "
        "based on the available information\n\n"
        f"Retrieved context:\n{retrieved_context}\n\n"
        f"Question: {question}\n\n"
        "Answer the question based on the retrieved context above."
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
) -> dict[str, Any]:
    """Judge whether the predicted answer is correct (LLM-as-judge)."""
    user_prompt = (
        f"Question: {question}\n"
        f"Gold answer: {gold_answer}\n"
        f"Generated answer: {predicted_answer}"
    )
    try:
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


# ---------------------------------------------------------------------------
# Summary & report
# ---------------------------------------------------------------------------


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
    return f"locomo-benchmark__{provider}__{model}__{timestamp}"


if __name__ == "__main__":
    raise SystemExit(main())
