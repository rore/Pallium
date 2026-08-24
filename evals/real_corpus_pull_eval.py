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
from collections import Counter
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.config import AppConfig  # noqa: E402
from app.mcp.server import _compact_history, _json_text  # noqa: E402
from evals.eval_common import build_eval_providers  # noqa: E402
from providers.llm.base import LLMProvider  # noqa: E402
from redaction import redact_sensitive  # noqa: E402
from core.models import HISTORICAL_GUIDANCE_MEMORY_TYPES  # noqa: E402
from core.visibility import is_visible  # noqa: E402

MAX_SAMPLE_SIZE = 20
MAX_VISIBLE_SOURCES = 3
MAX_SOURCE_CHARS = 480
MAX_QUERY_CHARS = 1000
MAX_ANSWER_CHARS = 2000
MAX_TOTAL_ESTIMATED_INPUT_TOKENS = 50000
MAX_MODEL_CALLS = 100
_ALLOWED_CATEGORIES = {"applicable", "unrelated", "replaced_decision", "unlabeled"}
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
    raw_history: str | None = None
    guarded_history: str | None = None
    category: str = "unlabeled"
    has_supported_replacement: bool = False

    @property
    def case_id(self) -> str:
        return _hash_id(self.event_id)


@dataclass(frozen=True)
class CorpusSnapshot:
    cases: tuple[PullCase, ...]
    counts: dict[str, int]
    attrition: dict[str, int]
    lineage: dict[str, int] = field(default_factory=dict)


def _hash_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _valid_sample_size(value: int) -> int:
    if not 1 <= value <= MAX_SAMPLE_SIZE:
        raise ValueError(f"sample_size must be between 1 and {MAX_SAMPLE_SIZE}")
    return value


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _sample_cases(cases: list[PullCase], *, sample_size: int, seed: int) -> list[PullCase]:
    """Select deterministically while spreading cases across requester sessions."""
    grouped: dict[str, list[PullCase]] = {}
    for case in cases:
        grouped.setdefault(case.session_id, []).append(case)
    rng = random.Random(seed)
    session_ids = sorted(grouped)
    rng.shuffle(session_ids)
    for group in grouped.values():
        rng.shuffle(group)

    selected: list[PullCase] = []
    target = min(sample_size, len(cases))
    while len(selected) < target:
        added = False
        for session_id in session_ids:
            group = grouped[session_id]
            if group and len(selected) < target:
                selected.append(group.pop())
                added = True
        if not added:
            break
    selected.sort(key=lambda case: case.event_id)
    return selected


def _memory_text(row: sqlite3.Row) -> str:
    try:
        payload = json.loads(row['payload_json'] or '{}')
    except (TypeError, json.JSONDecodeError):
        payload = {}
    if isinstance(payload, dict):
        for key in ('text', 'statement', 'fact', 'summary', 'decision', 'content'):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    subject = row['subject'] if 'subject' in row.keys() else None
    return str(subject or '').strip()



def _load_lineage(
    conn: sqlite3.Connection,
    *,
    container_ref: str,
    visibility: str,
    query_actor_ref: str | None,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    """Read supported supersession chains using the production relation shape."""
    memory_columns = _table_columns(conn, 'memory_objects')
    relation_columns = _table_columns(conn, 'relations')
    required_memory = {'id', 'type', 'payload_json', 'lifecycle', 'visibility', 'container_ref', 'actor_ref', 'created_at'}
    required_relation = {'from_kind', 'from_id', 'relation_type', 'to_kind', 'to_id'}
    empty = {'supported_memory_claims': 0, 'superseded_claims': 0, 'supported_replacements': 0, 'conflicting_or_missing_replacements': 0, 'sources_with_supported_replacements': 0}
    if not required_memory.issubset(memory_columns) or not required_relation.issubset(relation_columns):
        return {}, empty
    optional = [column for column in ('freshness_at', 'subject', 'superseded_by_id', 'is_soft_deleted') if column in memory_columns]
    selected = ['id', 'type', 'payload_json', 'lifecycle', 'visibility', 'container_ref', 'actor_ref', 'created_at', *optional]
    records = conn.execute(
        f"SELECT {', '.join('m.' + column for column in selected)} FROM memory_objects m"
    ).fetchall()
    by_id = {str(row['id']): row for row in records}
    if not by_id:
        return {}, empty
    successors: dict[str, set[str]] = {memory_id: set() for memory_id in by_id}
    if 'superseded_by_id' in memory_columns:
        for row in records:
            successor = row['superseded_by_id']
            if successor:
                successors[str(row['id'])].add(str(successor))
    for row in conn.execute(
        "SELECT from_id, to_id FROM relations "
        "WHERE from_kind = 'memory_object' AND to_kind = 'memory_object' "
        "AND relation_type = 'supersedes'"
    ):
        if str(row['to_id']) in successors:
            successors[str(row['to_id'])].add(str(row['from_id']))
    source_memory_rows = conn.execute(
        "SELECT r.to_id AS source_id, r.from_id AS memory_id FROM relations r "
        "WHERE r.from_kind = 'memory_object' AND r.to_kind = 'source_item' "
        "AND r.relation_type = 'supported_by'"
    ).fetchall()
    updates_by_source: dict[str, list[dict[str, Any]]] = {}
    supported = 0
    replaced = 0
    conflicted = 0
    seen_sources: set[str] = set()
    for link in source_memory_rows:
        memory_id = str(link['memory_id'])
        memory = by_id.get(memory_id)
        if memory is None:
            continue
        soft_deleted = bool(memory["is_soft_deleted"]) if "is_soft_deleted" in memory.keys() else False
        if (
            soft_deleted
            or str(memory["type"]) not in HISTORICAL_GUIDANCE_MEMORY_TYPES
            or str(memory["lifecycle"]) != "superseded"
            or not is_visible(
                memory["visibility"],
                memory["container_ref"],
                container_ref,
                memory["actor_ref"],
                query_visibility=visibility,
                query_actor_ref=query_actor_ref,
            )
        ):
            continue
        supported += 1
        current = memory
        visited = {memory_id}
        replacement_status = 'unavailable'
        current_id = None
        current_text = None
        current_recorded_at = None
        while True:
            next_ids = successors.get(str(current['id']), set())
            if len(next_ids) != 1:
                replacement_status = 'conflict' if len(next_ids) > 1 else replacement_status
                break
            next_id = next(iter(next_ids))
            if next_id in visited or next_id not in by_id:
                replacement_status = 'cycle' if next_id in visited else 'unavailable'
                break
            visited.add(next_id)
            current = by_id[next_id]
            soft_deleted = bool(current['is_soft_deleted']) if 'is_soft_deleted' in current.keys() else False
            visible = (
                not soft_deleted
                and str(current['type']) in HISTORICAL_GUIDANCE_MEMORY_TYPES
                and str(current['lifecycle']) == 'active'
                and is_visible(
                    current['visibility'], current['container_ref'], container_ref, current['actor_ref'],
                    query_visibility=visibility, query_actor_ref=query_actor_ref,
                )
            )
            if visible:
                replacement_status = 'current'
                current_id = next_id
                current_text = redact_sensitive(_memory_text(current))[:240] or None
                current_recorded_at = current['freshness_at'] if 'freshness_at' in current.keys() and current['freshness_at'] else current['created_at']
                break
        update = {'memory_type': str(memory['type']), 'status': 'outdated', 'replacement_status': replacement_status}
        if current_id:
            update.update({'current_memory_object_id': current_id, 'current_text': current_text, 'current_recorded_at': current_recorded_at})
            replaced += 1
            seen_sources.add(str(link['source_id']))
        else:
            conflicted += 1
        updates_by_source.setdefault(str(link['source_id']), []).append(update)
    empty['supported_memory_claims'] = supported
    empty['superseded_claims'] = sum(len(items) for items in updates_by_source.values())
    empty['supported_replacements'] = replaced
    empty['conflicting_or_missing_replacements'] = conflicted
    empty['sources_with_supported_replacements'] = len(seen_sources)
    return updates_by_source, empty


def _raw_history(
    source_ids: tuple[str, ...],
    source_texts: tuple[str, ...],
    *,
    query: str,
) -> str:
    return _json_text(_compact_history(
        {
            "results": [
                {"source_item_id": source_id, "excerpt": text}
                for source_id, text in zip(source_ids, source_texts)
            ],
            "lookup_event_id": None,
        },
        query=query,
        limit=len(source_ids),
    ))

def _guarded_history(
    source_ids: tuple[str, ...],
    source_texts: tuple[str, ...],
    *,
    query: str,
    source_rows: dict[str, sqlite3.Row],
    updates_by_source: dict[str, list[dict[str, Any]]],
) -> str:
    items = []
    for source_id, text in zip(source_ids, source_texts):
        row = source_rows.get(source_id)
        item: dict[str, Any] = {'source_item_id': source_id, 'excerpt': text}
        if row is not None:
            for column in ('occurred_at', 'created_at'):
                if column in row.keys() and row[column]:
                    item['recorded_at'] = row[column]
                    item['recorded_at_source'] = 'event' if column == 'occurred_at' else 'ingest'
                    break
        item['historical_updates'] = updates_by_source.get(source_id, [])
        items.append(item)
    return _json_text(_compact_history(
        {"results": items, "lookup_event_id": None},
        query=query,
        limit=len(items),
    ))


def load_corpus(db_path: Path, *, container_ref: str, visibility: str, sample_size: int = MAX_SAMPLE_SIZE, seed: int = 0, category_labels: dict[str, str] | None = None) -> CorpusSnapshot:
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
    lineage: dict[str, int] = {}

    db_uri = "file:" + db_path.resolve().as_posix() + "?mode=ro"
    with closing(sqlite3.connect(db_uri, uri=True)) as conn:
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
        _, lineage = _load_lineage(
            conn,
            container_ref=container_ref,
            visibility=visibility,
            query_actor_ref=None,
        )
        updates_by_actor: dict[str | None, dict[str, list[dict[str, Any]]]] = {}

        for row in rows:
            if not is_visible(row["visibility"], row["container_ref"], container_ref, row["actor_ref"], query_visibility=visibility, query_actor_ref=row["actor_ref"]):
                continue
            actor_ref = row["actor_ref"]
            if actor_ref not in updates_by_actor:
                updates_by_actor[actor_ref], _ = _load_lineage(
                    conn,
                    container_ref=container_ref,
                    visibility=visibility,
                    query_actor_ref=actor_ref,
                )
            updates_by_source = updates_by_actor[actor_ref]
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
                f"SELECT * FROM source_items WHERE id IN ({placeholders}) AND container_ref = ?",
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
                text = redact_sensitive(str(source["content"] or ""))
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
            category = (category_labels or {}).get(
                str(row["id"]),
                (category_labels or {}).get(_hash_id(str(row["id"])), "unlabeled"),
            )
            if category not in _ALLOWED_CATEGORIES:
                raise ValueError(f"invalid category for event {row['id']!r}: {category!r}")
            has_supported_replacement = any(
                update.get("replacement_status") == "current"
                for source_id in surviving_ids
                for update in updates_by_source.get(source_id, [])
            )
            if category == "unlabeled" and has_supported_replacement:
                category = "replaced_decision"
            cases.append(PullCase(
                event_id=str(row["id"]),
                session_id=str(row["session_id"] or ""),
                query=query,
                source_ids=tuple(surviving_ids),
                source_texts=tuple(surviving_texts),
                raw_history=_raw_history(
                    tuple(surviving_ids),
                    tuple(surviving_texts),
                    query=query,
                ),
                guarded_history=_guarded_history(
                    tuple(surviving_ids),
                    tuple(surviving_texts),
                    query=query,
                    source_rows=by_id,
                    updates_by_source=updates_by_source,
                ),
                category=category,
                has_supported_replacement=has_supported_replacement,
            ))

    selected = _sample_cases(cases, sample_size=sample_size, seed=seed)
    lineage["sampled_cases_with_supported_replacements"] = sum(
        case.has_supported_replacement for case in selected
    )
    return CorpusSnapshot(
        cases=tuple(selected),
        counts={
            "lookup_events": len(rows),
            "query_bearing_events": query_rows,
            "query_bearing_nonempty": query_bearing_nonempty,
            "valid_cases": len(cases),
            "sampled_cases": len(selected),
            "requester_sessions_sampled": len({case.session_id for case in selected}),
            "requester_session_case_counts": sorted(
                Counter(case.session_id for case in selected).values(),
                reverse=True,
            ),
        },
        attrition=attrition,
        lineage=lineage,
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


def _response_input_tokens(response: Any) -> int | None:
    metadata = getattr(response, "metadata", None)
    for name in ("input_tokens", "prompt_tokens"):
        value = getattr(metadata, name, None)
        if isinstance(value, int) and value >= 0:
            return value
    usage = getattr(metadata, "usage", None)
    value = getattr(usage, "input_tokens", None)
    return value if isinstance(value, int) and value >= 0 else None

def _answer(provider: LLMProvider, *, query: str, history: str | None) -> tuple[str, float, int, int | None]:
    system_prompt, user_prompt = _answer_prompt(query, history)
    started = time.perf_counter()
    response = provider.generate_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        schema_description=ANSWER_SCHEMA,
    )
    answer = str(response.parsed_json.get("answer", ""))
    return answer, (time.perf_counter() - started) * 1000, _estimate_input_tokens(system_prompt, user_prompt), _response_input_tokens(response)


def _judge_prompt(case_id: str, query: str, history: str, with_answer: str, without_answer: str) -> tuple[str, str, bool]:
    with_first = int(hashlib.sha256(case_id.encode("utf-8")).hexdigest()[:2], 16) % 2 == 0
    answer_a, answer_b = (with_answer, without_answer) if with_first else (without_answer, with_answer)
    user_prompt = (
        f"TASK:\n{query}\n\nHISTORICAL CONTEXT:\n{history}\n\n"
        f"ANSWER A:\n{answer_a}\n\nANSWER B:\n{answer_b}"
    )
    return JUDGE_SYSTEM_PROMPT, user_prompt, with_first


def _judge(provider: LLMProvider, *, case_id: str, query: str, history: str, with_answer: str, without_answer: str) -> tuple[str, str, str, bool, int, int | None]:
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
    return mapped, relevance, rationale, with_first, _estimate_input_tokens(system_prompt, user_prompt), _response_input_tokens(response)


def run_pilot(
    snapshot: CorpusSnapshot,
    *,
    provider: LLMProvider | None = None,
    judge_provider: LLMProvider | None = None,
    history_arm: str = "raw",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run bounded downstream-task comparisons; no calls happen without lineage in guarded mode."""
    if history_arm not in {"raw", "guarded", "both"}:
        raise ValueError("history_arm must be raw, guarded, or both")
    if history_arm in {"guarded", "both"} and snapshot.lineage.get("sampled_cases_with_supported_replacements", 0) == 0:
        return {
            "eval": "real-corpus-pull-pilot",
            "claim": {"measures": CLAIM_SEAM, "preflight": "supported supersession lineage coverage is zero; no model calls made"},
            "sampling": {"sampled_cases": len(snapshot.cases), "paired_cases": 0},
            "corpus": {**snapshot.counts, "attrition": snapshot.attrition, "lineage": snapshot.lineage},
            "decision_gate": {"status": "blocked_no_supported_lineage", "broad_product_recommendation": "none"},
            "results": {"model_calls": 0, "estimated_input_tokens_total": 0, "budget_is_estimate": True},
        }, {"eval": "real-corpus-pull-pilot-review", "contains_raw_private_text": True, "never_publish": True, "cases": []}
    if provider is None:
        raise ValueError("provider is required when the guarded preflight passes")
    judge_provider = judge_provider or provider

    arms = ["raw"] if history_arm == "raw" else ["guarded"] if history_arm == "guarded" else ["raw", "guarded"]
    outcomes = {arm: {"with_history": 0, "without_history": 0, "tie": 0} for arm in arms}
    relevance = {arm: {"useful": 0, "harmful": 0, "irrelevant": 0} for arm in arms}
    category_counts = Counter(case.category for case in snapshot.cases)
    category_results: dict[str, dict[str, dict[str, Counter]]] = {
        arm: {} for arm in arms
    }
    review_cases: list[dict[str, Any]] = []
    aggregate_cases: list[str] = []
    failures = budget_failures = budget_stopped_cases = model_calls = 0
    total_input_tokens = 0
    exact_input_tokens = 0
    exact_usage_calls = 0
    missing_usage_calls = 0
    incremental_history_tokens = {arm: 0 for arm in arms}
    latencies = {arm: [] for arm in arms}
    latencies["without_history"] = []

    def reserve(estimate: int) -> bool:
        nonlocal total_input_tokens, model_calls
        if model_calls >= MAX_MODEL_CALLS or total_input_tokens + estimate > MAX_TOTAL_ESTIMATED_INPUT_TOKENS:
            return False
        total_input_tokens += estimate
        model_calls += 1
        return True

    for index, case in enumerate(snapshot.cases):
        case_review: dict[str, Any] = {
            "case_id": case.case_id, "lookup_event_id": _hash_id(case.event_id),
            "query": case.query, "source_ids": list(case.source_ids),
            "source_texts": list(case.source_texts), "category": case.category,
        }
        raw_history = case.raw_history or "\n\n".join(case.source_texts)
        guarded_history = case.guarded_history or raw_history
        histories = {"raw": raw_history, "guarded": guarded_history}
        answers: dict[str, str] = {}
        answer_ms: dict[str, float] = {}
        try:
            for arm in arms:
                system, user = _answer_prompt(case.query, histories[arm])
                estimate = _estimate_input_tokens(system, user)
                if not reserve(estimate):
                    raise _BudgetStop
                answers[arm], answer_ms[arm], _, exact = _answer(provider, query=case.query, history=histories[arm])
                if exact is None:
                    missing_usage_calls += 1
                else:
                    exact_input_tokens += exact
                    exact_usage_calls += 1
                incremental_history_tokens[arm] += max(1, len(histories[arm]) // 4)
                latencies[arm].append(round(answer_ms[arm], 3))
            no_system, no_user = _answer_prompt(case.query, None)
            if not reserve(_estimate_input_tokens(no_system, no_user)):
                raise _BudgetStop
            without_answer, without_ms, _, exact = _answer(provider, query=case.query, history=None)
            if exact is None:
                missing_usage_calls += 1
            else:
                exact_input_tokens += exact
                exact_usage_calls += 1
            latencies["without_history"].append(round(without_ms, 3))
            arm_results = {}
            pending_counts: list[tuple[str, str, str]] = []
            for arm in arms:
                judge_system, judge_user, _ = _judge_prompt(
                    case.case_id, case.query, histories[arm],
                    answers[arm][:MAX_ANSWER_CHARS], without_answer[:MAX_ANSWER_CHARS],
                )
                if not reserve(_estimate_input_tokens(judge_system, judge_user)):
                    raise _BudgetStop
                winner, rel, rationale, with_first, _, exact = _judge(
                    judge_provider, case_id=case.case_id, query=case.query,
                    history=histories[arm], with_answer=answers[arm][:MAX_ANSWER_CHARS],
                    without_answer=without_answer[:MAX_ANSWER_CHARS],
                )
                if exact is None:
                    missing_usage_calls += 1
                else:
                    exact_input_tokens += exact
                    exact_usage_calls += 1
                pending_counts.append((arm, winner, rel))
                arm_results[arm] = {
                    "winner": winner, "history_relevance": rel,
                    "judge_rationale": rationale, "blind_with_history_is_a": with_first,
                }
            for arm, winner, rel in pending_counts:
                outcomes[arm][winner] += 1
                relevance[arm][rel] += 1
                category_bucket = category_results[arm].setdefault(
                    case.category,
                    {"wins": Counter(), "history_relevance": Counter()},
                )
                category_bucket["wins"][winner] += 1
                category_bucket["history_relevance"][rel] += 1
            aggregate_cases.append(case.case_id)
            case_review.update({
                "with_history_answer": answers[arms[0]][:MAX_ANSWER_CHARS],
                "without_history_answer": without_answer[:MAX_ANSWER_CHARS],
                "judge_winner": arm_results[arms[0]]["winner"],
                "history_relevance": arm_results[arms[0]]["history_relevance"],
                "judge_rationale": arm_results[arms[0]]["judge_rationale"],
                "blind_with_history_is_a": arm_results[arms[0]]["blind_with_history_is_a"],
                "arm_results": arm_results,
            })
            if len(arms) > 1:
                case_review["guarded_history"] = guarded_history
                case_review["answers"] = {arm: answers[arm][:MAX_ANSWER_CHARS] for arm in arms}
        except _BudgetStop:
            budget_failures += 1
            budget_stopped_cases = len(snapshot.cases) - index
            case_review["failure_type"] = "budget_exceeded"
            review_cases.append(case_review)
            break
        except Exception as exc:
            failures += 1
            case_review["failure_type"] = type(exc).__name__
        review_cases.append(case_review)

    default_outcomes = outcomes["raw"] if arms == ["raw"] else outcomes
    default_relevance = relevance["raw"] if arms == ["raw"] else relevance
    decision_status = "directional_read_ready" if len(aggregate_cases) >= 3 and failures <= 1 and budget_failures == 0 else "insufficient_data"
    aggregate = {
        "eval": "real-corpus-pull-pilot",
        "claim": {
            "measures": CLAIM_SEAM,
            "does_not_measure": ["candidate-recovery", "injection-precision", "observed live improvement"],
            "estimation": {"method": "chars_div_4", "exact_token_ceiling": False, "unicode_may_underestimate": True, "provider_completion_pre_capped": False},
            "limitations": {"max_cases": MAX_SAMPLE_SIZE, "judge": "single uncalibrated model judge", "paired_draws": 1, "human_spot_check": False, "linked_observed_work_after": False, "judge_sees_history": True},
        },
        "sampling": {"sample_size_cap": MAX_SAMPLE_SIZE, "sampled_cases": len(snapshot.cases), "paired_cases": len(aggregate_cases), "case_ids": aggregate_cases},
        "corpus": {**snapshot.counts, "attrition": snapshot.attrition, "lineage": snapshot.lineage},
        "decision_gate": {"status": decision_status, "broad_product_recommendation": "none", "note": "directional pilot only; no broad product recommendation"},
        "results": {
            "failures": failures, "budget_failures": budget_failures, "budget_stopped_cases": budget_stopped_cases,
            "model_calls": model_calls, "max_model_calls": MAX_MODEL_CALLS,
            "estimated_input_tokens_total": total_input_tokens, "max_estimated_input_tokens": MAX_TOTAL_ESTIMATED_INPUT_TOKENS,
            "exact_input_tokens_total": exact_input_tokens if missing_usage_calls == 0 and exact_usage_calls else None,
            "token_measurement": "exact" if missing_usage_calls == 0 and exact_usage_calls else "estimate",
            "usage_calls_observed": exact_usage_calls, "usage_calls_missing": missing_usage_calls,
            "budget_is_estimate": True, "wins": default_outcomes, "history_relevance": default_relevance,
            "category_counts": dict(sorted(category_counts.items())),
            "category_results": {
                arm: {
                    category: {
                        metric: dict(counter)
                        for metric, counter in metrics.items()
                    }
                    for category, metrics in sorted(by_category.items())
                }
                for arm, by_category in category_results.items()
            },
            "incremental_history_tokens": incremental_history_tokens if len(arms) > 1 else incremental_history_tokens["raw"],
            "latency_ms": {
                "with_history_total": {arm: round(sum(latencies[arm]), 3) for arm in arms},
                "without_history_total": round(sum(latencies["without_history"]), 3),
            },
            "arms": arms,
        },
    }
    return aggregate, {"eval": "real-corpus-pull-pilot-review", "contains_raw_private_text": True, "never_publish": True, "cases": review_cases}


class _BudgetStop(Exception):
    pass

def _spotcheck_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not any(case.get("arm_results") for case in cases):
        return cases
    required = [
        case for case in cases
        if any(
            result.get("winner") != "with_history" or result.get("history_relevance") == "harmful"
            for result in case.get("arm_results", {}).values()
        )
    ]
    required_ids = {case["case_id"] for case in required}
    wins = sorted(
        (case for case in cases if case["case_id"] not in required_ids and not case.get("failure_type")),
        key=lambda case: case["case_id"],
    )[:2]
    return required + wins


def render_review_sheet(review: dict[str, Any]) -> str:
    """Render a private, blinded worksheet for one human reviewer."""
    lines = [
        "# Pallium real-corpus review (private)",
        "",
        "This file contains private task history. Do not publish it.",
        "Judge each case before opening its answer mapping.",
        "",
    ]

    def block(value: str) -> list[str]:
        text = value.strip() or "[empty]"
        return [f"    {line}" for line in text.splitlines()]

    for case in _spotcheck_cases(list(review.get("cases", []))):
        lines.extend([f"## Case {case['case_id']}", ""])
        if case.get("failure_type"):
            lines.extend([f"Run failure: {case['failure_type']}", ""])
            continue
        answers = case.get("answers")
        if isinstance(answers, dict) and {"raw", "guarded"}.issubset(answers):
            candidates = {
                "pre-guard history": answers["raw"],
                "guarded history": answers["guarded"],
                "no history": case["without_history_answer"],
            }
            order = sorted(candidates, key=lambda label: _hash_id(f"{case['case_id']}:{label}"))
            raw_history = "\n\n".join(case.get("source_texts", []))
            guarded_history = case.get("guarded_history", "")
            lines.extend([
                "### Task", "", *block(case["query"]), "",
                "### Pre-guard history", "", *block(raw_history), "",
                "### Guarded history", "", *block(guarded_history), "",
            ])
            for label, arm in zip(("A", "B", "C"), order):
                lines.extend([f"### Answer {label}", "", *block(candidates[arm]), ""])
            lines.extend([
                "### Your judgement", "",
                "- Better answer: [ ] A  [ ] B  [ ] C  [ ] Tie",
                "- Any answer stale, reversed, or harmful: [ ] A  [ ] B  [ ] C  [ ] None",
                "- Notes:", "",
                "<details><summary>Answer mapping — open after judging</summary>", "",
                *(f"- Answer {label}: {arm}" for label, arm in zip(("A", "B", "C"), order)),
                "", "</details>", "", "---", "",
            ])
            continue
        with_first = bool(case["blind_with_history_is_a"])
        answer_a = case["with_history_answer"] if with_first else case["without_history_answer"]
        answer_b = case["without_history_answer"] if with_first else case["with_history_answer"]
        history = "\n\n".join(case.get("source_texts", []))
        lines.extend([
            "### Task", "", *block(case["query"]), "",
            "### Retrieved history", "", *block(history), "",
            "### Answer A", "", *block(answer_a), "",
            "### Answer B", "", *block(answer_b), "",
            "### Your judgement", "",
            "- Better answer: [ ] A  [ ] B  [ ] Tie",
            "- History was: [ ] Useful  [ ] Irrelevant  [ ] Harmful",
            "- History was stale or reversed: [ ] Yes  [ ] No  [ ] Unsure",
            "- Notes:", "", "---", "",
        ])
    return "\n".join(lines)

def _write_private(path: Path, content: str) -> None:
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    path.write_text(content, encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--db", type=Path, required=True, help="Existing scratch SQLite database")
    parser.add_argument("--container-ref", required=True)
    parser.add_argument("--visibility", required=True)
    parser.add_argument("--aggregate-output", type=Path, required=True, help="Text-free aggregate JSON output")
    parser.add_argument("--review-output", type=Path, required=True, help="PRIVATE: contains raw text; local only; never publish")
    parser.add_argument("--review-sheet-output", type=Path, default=None, help="PRIVATE: optional blinded Markdown worksheet for one human reviewer")
    parser.add_argument("--acknowledge-private-review-output", action="store_true", help="Acknowledge that the review output contains raw private text and must never be published")
    parser.add_argument("--history-arm", choices=("raw", "guarded", "both"), default="raw", help="Compare raw, production-shaped guarded history, or both")
    parser.add_argument("--categories-json", type=Path, default=None, help="Optional JSON mapping event id or case id to applicable/unrelated/replaced_decision")
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
        output_paths = [args.aggregate_output.resolve(), args.review_output.resolve()]
        if args.review_sheet_output is not None:
            output_paths.append(args.review_sheet_output.resolve())
        if any(path in db_targets for path in output_paths):
            parser.error("report outputs must not equal the scratch database or its sidecars")
        if len(set(output_paths)) != len(output_paths):
            parser.error("report outputs must be different files")
        if not args.acknowledge_private_review_output:
            parser.error("--acknowledge-private-review-output is required before writing private review output")
        category_labels = None
        if args.categories_json is not None:
            category_labels = json.loads(args.categories_json.read_text(encoding="utf-8"))
            if not isinstance(category_labels, dict):
                parser.error("--categories-json must contain an object")
        snapshot = load_corpus(
            args.db,
            container_ref=args.container_ref,
            visibility=args.visibility,
            sample_size=args.sample_size,
            seed=args.seed,
            category_labels=category_labels,
        )
        if args.history_arm in {"guarded", "both"} and snapshot.lineage.get("sampled_cases_with_supported_replacements", 0) == 0:
            aggregate, review = run_pilot(snapshot, history_arm=args.history_arm)
        else:
            config = AppConfig.from_env()
            provider, judge_provider = build_eval_providers(
                config, cache_dir=args.cache_dir, no_eval_cache=args.no_eval_cache
            )
            aggregate, review = run_pilot(
                snapshot, provider=provider, judge_provider=judge_provider, history_arm=args.history_arm
            )
        args.aggregate_output.parent.mkdir(parents=True, exist_ok=True)
        args.review_output.parent.mkdir(parents=True, exist_ok=True)
        args.aggregate_output.write_text(json.dumps(aggregate, indent=2) + "\n", encoding="utf-8")
        _write_private(args.review_output, json.dumps(review, indent=2, ensure_ascii=False) + "\n")
        if args.review_sheet_output is not None:
            args.review_sheet_output.parent.mkdir(parents=True, exist_ok=True)
            _write_private(args.review_sheet_output, render_review_sheet(review) + "\n")
    except (ValueError, FileNotFoundError, sqlite3.Error) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
