"""Budget-capped paired evaluation of real historical-pull events.

This is an offline, controlled downstream-task-effect experiment.  It does
not measure candidate recovery or injection precision, and it never mutates
the source database.  The aggregate report is deliberately text-free so it
can be shared; the review report is private and may contain the sampled text.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.config import AppConfig  # noqa: E402
from evals.eval_common import build_eval_providers  # noqa: E402
from providers.llm.base import LLMProvider  # noqa: E402
from core.visibility import is_visible  # noqa: E402

MAX_SAMPLE_SIZE = 5
MAX_VISIBLE_SOURCES = 3
MAX_SOURCE_CHARS = 480
MAX_QUERY_CHARS = 1000
MAX_ANSWER_CHARS = 2000
MAX_TOTAL_ESTIMATED_INPUT_TOKENS = 20000
ANSWER_SCHEMA = '{"answer":"string"}'
JUDGE_SCHEMA = '{"winner":"A|B|tie","history_relevance":"useful|harmful|irrelevant","rationale":"string"}'
CLAIM_SEAM = "offline controlled downstream-task-effect"


@dataclass(frozen=True)
class PullCase:
    event_id: str
    session_id: str
    query: str
    source_ids: tuple[str, ...]
    source_texts: tuple[str, ...]

    @property
    def case_id(self) -> str:
        return _hash_id(self.event_id)


@dataclass(frozen=True)
class CorpusSnapshot:
    cases: tuple[PullCase, ...]
    counts: dict[str, int]
    attrition: dict[str, int]


def _hash_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _valid_sample_size(value: int) -> int:
    if not 1 <= value <= MAX_SAMPLE_SIZE:
        raise ValueError(f"sample_size must be between 1 and {MAX_SAMPLE_SIZE}")
    return value


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def load_corpus(db_path: Path, *, container_ref: str, visibility: str, sample_size: int = MAX_SAMPLE_SIZE, seed: int = 0) -> CorpusSnapshot:
    """Load and deterministically sample valid historical-pull episodes."""
    _valid_sample_size(sample_size)
    if not container_ref or not visibility:
        raise ValueError("container_ref and visibility are required")
    if visibility not in {"private", "container", "public"}:
        raise ValueError("visibility must be private, container, or public")
    if not db_path.exists():
        raise FileNotFoundError(str(db_path))

    attrition = {
        "malformed_exposed_json": 0,
        "no_valid_exposed_ids": 0,
        "missing_sources": 0,
        "forgotten_sources": 0,
        "empty_source_text": 0,
        "zero_surviving_sources": 0,
        "sources_beyond_visible_limit": 0,
        "source_chars_truncated": 0,
        "oversized_queries": 0,
    }
    candidates = 0
    query_bearing_nonempty = 0
    query_rows = 0
    cases: list[PullCase] = []

    db_uri = "file:" + db_path.resolve().as_posix() + "?mode=ro"
    with sqlite3.connect(db_uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        if not _table_columns(conn, "historical_lookup_reuse_event"):
            raise ValueError("database has no historical lookup event table")
        event_columns = _table_columns(conn, "historical_lookup_reuse_event")
        required = {"id", "session_id", "created_at", "event_type", "trigger_origin", "container_ref", "visibility", "actor_ref", "exposed_json", "query_text"}
        if not required.issubset(event_columns):
            raise ValueError("historical lookup event table is missing required columns")
        rows = conn.execute(
            "SELECT id, session_id, container_ref, visibility, actor_ref, exposed_json, query_text "
            "FROM historical_lookup_reuse_event "
            "WHERE event_type = 'lookup' AND trigger_origin = 'agent_pull' "
            "AND container_ref = ? "
            "ORDER BY created_at, id",
            (container_ref,),
        ).fetchall()
        source_columns = _table_columns(conn, "source_items")
        if not {"id", "content", "forgotten_at", "container_ref", "visibility", "actor_ref"}.issubset(source_columns):
            raise ValueError("database source_items table is missing required columns")

        for row in rows:
            if not is_visible(row["visibility"], row["container_ref"], container_ref, row["actor_ref"], query_visibility=visibility, query_actor_ref=row["actor_ref"]):
                continue
            raw_query = row["query_text"]
            raw_exposed = row["exposed_json"]
            query = str(raw_query or "").strip()
            if not query:
                continue
            query_rows += 1
            if len(query) > MAX_QUERY_CHARS:
                attrition["oversized_queries"] += 1
                continue
            candidates += 1
            try:
                exposed = json.loads(raw_exposed or "[]")
            except (TypeError, json.JSONDecodeError):
                attrition["malformed_exposed_json"] += 1
                continue
            if not isinstance(exposed, list) or not exposed:
                continue
            query_bearing_nonempty += 1

            ordered_ids: list[str] = []
            malformed = False
            for entry in exposed:
                if not isinstance(entry, dict):
                    malformed = True
                    continue
                source_id = entry.get("source_item_id")
                if not isinstance(source_id, str) or not source_id:
                    malformed = True
                    continue
                if source_id not in ordered_ids:
                    ordered_ids.append(source_id)
            if malformed:
                attrition["malformed_exposed_json"] += 1
            if not ordered_ids:
                attrition["no_valid_exposed_ids"] += 1
                attrition["zero_surviving_sources"] += 1
                continue

            if len(ordered_ids) > MAX_VISIBLE_SOURCES:
                attrition["sources_beyond_visible_limit"] += len(ordered_ids) - MAX_VISIBLE_SOURCES
                ordered_ids = ordered_ids[:MAX_VISIBLE_SOURCES]

            placeholders = ",".join("?" for _ in ordered_ids)
            source_rows = conn.execute(
                f"SELECT id, content, forgotten_at, container_ref, visibility, actor_ref FROM source_items WHERE id IN ({placeholders}) "
                "AND container_ref = ?",
                (*ordered_ids, container_ref),
            ).fetchall()
            by_id = {str(source["id"]): source for source in source_rows}
            surviving_ids: list[str] = []
            surviving_texts: list[str] = []
            missing = forgotten = empty = 0
            for source_id in ordered_ids:
                source = by_id.get(source_id)
                if source is None:
                    missing += 1
                    continue
                if source["forgotten_at"] is not None:
                    forgotten += 1
                    continue
                if not is_visible(source["visibility"], source["container_ref"], container_ref, source["actor_ref"], query_visibility=visibility, query_actor_ref=row["actor_ref"]):
                    missing += 1
                    continue
                text = str(source["content"] or "")
                if not text.strip():
                    empty += 1
                    continue
                if len(text) > MAX_SOURCE_CHARS:
                    attrition["source_chars_truncated"] += len(text) - MAX_SOURCE_CHARS
                    text = text[:MAX_SOURCE_CHARS]
                surviving_ids.append(source_id)
                surviving_texts.append(text)
            attrition["missing_sources"] += missing
            attrition["forgotten_sources"] += forgotten
            attrition["empty_source_text"] += empty
            if not surviving_ids:
                attrition["zero_surviving_sources"] += 1
                continue
            cases.append(PullCase(
                event_id=str(row["id"]),
                session_id=str(row["session_id"] or ""),
                query=query,
                source_ids=tuple(surviving_ids),
                source_texts=tuple(surviving_texts),
            ))

    rng = random.Random(seed)
    selected = rng.sample(cases, min(sample_size, len(cases)))
    selected.sort(key=lambda case: case.event_id)
    return CorpusSnapshot(
        cases=tuple(selected),
        counts={
            "lookup_events": len(rows),
            "query_bearing_events": query_rows,
            "query_bearing_nonempty": query_bearing_nonempty,
            "valid_cases": len(cases),
            "sampled_cases": len(selected),
        },
        attrition=attrition,
    )


def _task_prompt(query: str, history: str | None) -> str:
    task = f"Task:\n{query}\n\nAnswer the task directly and concisely."
    if history:
        return f"{task}\n\nHistorical context (use only if relevant):\n{history}"
    return f"{task}\n\nNo historical context is available."


def _estimate_input_tokens(system_prompt: str, user_prompt: str) -> int:
    return max(1, (len(system_prompt) + len(user_prompt)) // 4)


ANSWER_SYSTEM_PROMPT = (
    "You are a helpful software assistant. Answer the user task using only the "
    "task and optional context supplied in the user prompt. If context is "
    "irrelevant, ignore it. Return JSON."
)
JUDGE_SYSTEM_PROMPT = (
    "You are a blind evaluator. A and B are answers to the same task. Choose the "
    "better answer, or tie. Label history_relevance as useful when task-specific "
    "context improves or could improve the answer; harmful when misleading, stale, "
    "or off-scope context degrades or could degrade it; irrelevant when neither "
    "applies. Do not infer which answer had context. Return JSON."
)


def _answer_prompt(query: str, history: str | None) -> tuple[str, str]:
    return ANSWER_SYSTEM_PROMPT, _task_prompt(query, history)


def _answer(provider: LLMProvider, *, query: str, history: str | None) -> tuple[str, float, int]:
    system_prompt, user_prompt = _answer_prompt(query, history)
    started = time.perf_counter()
    response = provider.generate_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        schema_description=ANSWER_SCHEMA,
    )
    answer = str(response.parsed_json.get("answer", ""))
    return answer, (time.perf_counter() - started) * 1000, _estimate_input_tokens(system_prompt, user_prompt)


def _judge_prompt(case_id: str, query: str, history: str, with_answer: str, without_answer: str) -> tuple[str, str, bool]:
    with_first = int(hashlib.sha256(case_id.encode("utf-8")).hexdigest()[:2], 16) % 2 == 0
    answer_a, answer_b = (with_answer, without_answer) if with_first else (without_answer, with_answer)
    user_prompt = (
        f"TASK:\n{query}\n\nHISTORICAL CONTEXT:\n{history}\n\n"
        f"ANSWER A:\n{answer_a}\n\nANSWER B:\n{answer_b}"
    )
    return JUDGE_SYSTEM_PROMPT, user_prompt, with_first


def _judge(provider: LLMProvider, *, case_id: str, query: str, history: str, with_answer: str, without_answer: str) -> tuple[str, str, str, bool, int]:
    system_prompt, user_prompt, with_first = _judge_prompt(
        case_id, query, history, with_answer, without_answer
    )
    response = provider.generate_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        schema_description=JUDGE_SCHEMA,
    )
    parsed = response.parsed_json
    winner = str(parsed.get("winner", "")).strip().lower()
    relevance = str(parsed.get("history_relevance", "")).strip().lower()
    rationale = str(parsed.get("rationale", ""))
    if winner not in {"a", "b", "tie"}:
        raise ValueError("invalid judge winner")
    if relevance not in {"useful", "harmful", "irrelevant"}:
        raise ValueError("invalid history relevance")
    if winner == "tie":
        mapped = "tie"
    else:
        winner_is_with = (winner == "a") == with_first
        mapped = "with_history" if winner_is_with else "without_history"
    return mapped, relevance, rationale, with_first, _estimate_input_tokens(system_prompt, user_prompt)


def run_pilot(
    snapshot: CorpusSnapshot,
    *,
    provider: LLMProvider,
    judge_provider: LLMProvider | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run paired calls and return privacy-safe aggregate plus private review."""
    judge_provider = judge_provider or provider
    aggregate_cases: list[str] = []
    review_cases: list[dict[str, Any]] = []
    outcomes = {"with_history": 0, "without_history": 0, "tie": 0}
    relevance = {"useful": 0, "harmful": 0, "irrelevant": 0}
    latencies = {"with_history_ms": [], "without_history_ms": []}
    total_input_tokens = 0
    incremental_history_tokens = 0
    failures = 0
    budget_failures = 0
    budget_stopped_cases = 0

    for index, case in enumerate(snapshot.cases):
        case_review: dict[str, Any] = {
            "case_id": case.case_id,
            "lookup_event_id": _hash_id(case.event_id),
            "query": case.query,
            "source_ids": list(case.source_ids),
            "source_texts": list(case.source_texts),
        }
        history = "\n\n".join(case.source_texts)
        with_system, with_user = _answer_prompt(case.query, history)
        with_estimate = _estimate_input_tokens(with_system, with_user)
        if total_input_tokens + with_estimate > MAX_TOTAL_ESTIMATED_INPUT_TOKENS:
            budget_failures += 1
            budget_stopped_cases = len(snapshot.cases) - index
            case_review["failure_type"] = "budget_exceeded"
            review_cases.append(case_review)
            break
        try:
            total_input_tokens += with_estimate
            with_answer, with_ms, _ = _answer(provider, query=case.query, history=history)
            without_system, without_user = _answer_prompt(case.query, None)
            without_estimate = _estimate_input_tokens(without_system, without_user)
            if total_input_tokens + without_estimate > MAX_TOTAL_ESTIMATED_INPUT_TOKENS:
                budget_failures += 1
                budget_stopped_cases = len(snapshot.cases) - index
                case_review["failure_type"] = "budget_exceeded"
                review_cases.append(case_review)
                break
            total_input_tokens += without_estimate
            without_answer, without_ms, _ = _answer(provider, query=case.query, history=None)
            judge_with_answer = with_answer[:MAX_ANSWER_CHARS]
            judge_without_answer = without_answer[:MAX_ANSWER_CHARS]
            judge_system, judge_user, _ = _judge_prompt(
                case.case_id, case.query, history, judge_with_answer, judge_without_answer
            )
            judge_estimate = _estimate_input_tokens(judge_system, judge_user)
            if total_input_tokens + judge_estimate > MAX_TOTAL_ESTIMATED_INPUT_TOKENS:
                budget_failures += 1
                budget_stopped_cases = len(snapshot.cases) - index
                case_review["failure_type"] = "budget_exceeded"
                review_cases.append(case_review)
                break
            total_input_tokens += judge_estimate
            winner, history_relevance, rationale, with_first, _ = _judge(
                judge_provider,
                case_id=case.case_id,
                query=case.query,
                history=history,
                with_answer=judge_with_answer,
                without_answer=judge_without_answer,
            )
            outcomes[winner] += 1
            relevance[history_relevance] += 1
            aggregate_cases.append(case.case_id)
            incremental_history_tokens += max(1, len(history) // 4)
            latencies["with_history_ms"].append(round(with_ms, 3))
            latencies["without_history_ms"].append(round(without_ms, 3))
            case_review.update({
                "with_history_answer": with_answer[:MAX_ANSWER_CHARS],
                "without_history_answer": without_answer[:MAX_ANSWER_CHARS],
                "judge_winner": winner,
                "history_relevance": history_relevance,
                "judge_rationale": rationale,
                "blind_with_history_is_a": with_first,
            })
        except Exception as exc:
            failures += 1
            case_review["failure_type"] = type(exc).__name__
        review_cases.append(case_review)

    decision_status = (
        "directional_read_ready"
        if len(aggregate_cases) >= 3 and failures <= 1 and budget_failures == 0
        else "insufficient_data"
    )
    aggregate = {
        "eval": "real-corpus-pull-pilot",
        "claim": {
            "measures": CLAIM_SEAM,
            "does_not_measure": ["candidate-recovery", "injection-precision", "observed live improvement"],
            "estimation": {
                "method": "chars_div_4",
                "exact_token_ceiling": False,
                "unicode_may_underestimate": True,
                "provider_completion_pre_capped": False,
            },
            "limitations": {
                "max_cases": MAX_SAMPLE_SIZE,
                "judge": "single uncalibrated model judge",
                "paired_draws": 1,
                "human_spot_check": False,
                "linked_observed_work_after": False,
            },
        },
        "sampling": {
            "sample_size_cap": MAX_SAMPLE_SIZE,
            "sampled_cases": len(snapshot.cases),
            "paired_cases": len(aggregate_cases),
            "case_ids": aggregate_cases,
        },
        "corpus": {**snapshot.counts, "attrition": snapshot.attrition},
        "decision_gate": {
            "status": decision_status,
            "broad_product_recommendation": "none",
            "note": "directional pilot only; no broad product recommendation",
        },
        "results": {
            "failures": failures,
            "budget_failures": budget_failures,
            "budget_stopped_cases": budget_stopped_cases,
            "estimated_input_tokens_total": total_input_tokens,
            "max_estimated_input_tokens": MAX_TOTAL_ESTIMATED_INPUT_TOKENS,
            "budget_is_estimate": True,
            "wins": outcomes,
            "history_relevance": relevance,
            "incremental_history_tokens": incremental_history_tokens,
            "added_context_tokens": {"total": incremental_history_tokens, "mean": round(incremental_history_tokens / len(aggregate_cases), 3) if aggregate_cases else None},
            "latency_ms": {
                "with_history_total": round(sum(latencies["with_history_ms"]), 3),
                "without_history_total": round(sum(latencies["without_history_ms"]), 3),
                "with_history_mean": round(sum(latencies["with_history_ms"]) / len(latencies["with_history_ms"]), 3) if latencies["with_history_ms"] else None,
                "without_history_mean": round(sum(latencies["without_history_ms"]) / len(latencies["without_history_ms"]), 3) if latencies["without_history_ms"] else None,
            },
        },
    }
    return aggregate, {"eval": "real-corpus-pull-pilot-review", "contains_raw_private_text": True, "never_publish": True, "cases": review_cases}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--db", type=Path, required=True, help="Existing scratch SQLite database")
    parser.add_argument("--container-ref", required=True)
    parser.add_argument("--visibility", required=True)
    parser.add_argument("--aggregate-output", type=Path, required=True, help="Text-free aggregate JSON output")
    parser.add_argument("--review-output", type=Path, required=True, help="PRIVATE: contains raw text; local only; never publish")
    parser.add_argument("--acknowledge-private-review-output", action="store_true", help="Acknowledge that the review output contains raw private text and must never be published")
    parser.add_argument("--sample-size", type=int, default=MAX_SAMPLE_SIZE)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--no-eval-cache", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        _valid_sample_size(args.sample_size)
        if not args.db.exists() or not args.db.is_file():
            parser.error("--db must name an existing scratch SQLite database")
        db_targets = {args.db.resolve(), Path(str(args.db) + "-wal").resolve(), Path(str(args.db) + "-shm").resolve(), Path(str(args.db) + "-journal").resolve()}
        if args.aggregate_output.resolve() in db_targets or args.review_output.resolve() in db_targets:
            parser.error("report outputs must not equal the scratch database or its sidecars")
        if args.aggregate_output.resolve() == args.review_output.resolve():
            parser.error("aggregate and review outputs must be different files")
        if not args.acknowledge_private_review_output:
            parser.error("--acknowledge-private-review-output is required before writing private review output")
        snapshot = load_corpus(
            args.db,
            container_ref=args.container_ref,
            visibility=args.visibility,
            sample_size=args.sample_size,
            seed=args.seed,
        )
        config = AppConfig.from_env()
        provider, judge_provider = build_eval_providers(
            config, cache_dir=args.cache_dir, no_eval_cache=args.no_eval_cache
        )
        aggregate, review = run_pilot(snapshot, provider=provider, judge_provider=judge_provider)
        args.aggregate_output.parent.mkdir(parents=True, exist_ok=True)
        args.review_output.parent.mkdir(parents=True, exist_ok=True)
        args.aggregate_output.write_text(json.dumps(aggregate, indent=2) + "\n", encoding="utf-8")
        args.review_output.write_text(json.dumps(review, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except (ValueError, FileNotFoundError, sqlite3.Error) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
