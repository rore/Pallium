from __future__ import annotations

import json
import os
import stat
import sqlite3
from pathlib import Path

import pytest

from evals.real_corpus_pull_eval import (
    CorpusSnapshot,
    PullCase,
    _build_parser,
    load_corpus,
    run_pilot,
)
from providers.llm.base import LLMJsonResponse


class ScriptedProvider:
    def __init__(self, *, fail=False, giant_answer=False):
        self.calls = 0
        self.fail = fail
        self.giant_answer = giant_answer
        self.requests = []

    def generate_json(self, *, system_prompt, user_prompt, schema_description):
        self.calls += 1
        self.requests.append((system_prompt, user_prompt, schema_description))
        if self.fail:
            raise RuntimeError("PRIVATE_PROVIDER_SENTINEL")
        if "winner" in schema_description:
            payload = {"winner": "A", "history_relevance": "useful", "rationale": "private rationale"}
        else:
            payload = {"answer": ("A" * 3000) if self.giant_answer else f"answer-{self.calls}"}
        return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)


def _db(path: Path, events: list[tuple[str, str, str]], sources: list[tuple[str, str, str | None]]) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE historical_lookup_reuse_event (
              id TEXT PRIMARY KEY, created_at TEXT, event_type TEXT,
              session_id TEXT, container_ref TEXT, trigger_origin TEXT,
              visibility TEXT, actor_ref TEXT, exposed_json TEXT, query_text TEXT
            );
            CREATE TABLE source_items (
              id TEXT PRIMARY KEY, content TEXT, forgotten_at TEXT,
              container_ref TEXT, visibility TEXT, actor_ref TEXT
            );
            """
        )
        conn.executemany(
            "INSERT INTO historical_lookup_reuse_event VALUES (?, ?, 'lookup', ?, 'c:test', 'agent_pull', 'private', NULL, ?, ?)",
            [(eid, f"2026-01-01T00:00:{i:02d}", f"thread-{i}", exposed, query) for i, (eid, query, exposed) in enumerate(events)],
        )
        conn.executemany(
            "INSERT INTO source_items VALUES (?, ?, ?, 'c:test', 'private', NULL)", sources
        )


def test_lifecycle_filters_sources_and_keeps_aggregate_private_free(tmp_path: Path) -> None:
    db = tmp_path / "scratch.db"
    _db(db, [
        ("e-good", "résumé SECRET_QUERY", json.dumps([
            {"source_item_id": "s1", "raw_rank": 1}, {"source_item_id": "s1", "raw_rank": 2}, {"source_item_id": "s2", "raw_rank": 3}, {"source_item_id": "s3", "raw_rank": 4}, {"source_item_id": "s4", "raw_rank": 5}, {"source_item_id": "s5", "raw_rank": 6}
        ])),
        ("e-missing", "missing", json.dumps([{ "source_item_id": "nope" }])),
        ("e-forgotten", "forgotten", json.dumps([{ "source_item_id": "s2" }])),
        ("e-malformed", "malformed", "{not-json"),
        ("e-invalid", "invalid", json.dumps([{}, "bad"])),
        ("e-empty", "empty", json.dumps([{ "source_item_id": "s-empty" }])),
    ], [
        ("s1", "Unicode source SECRET_SOURCE", None),
        ("s2", "forgotten source", "2026-01-02"),
        ("s3", "X" * 600, None),
        ("s4", "source four", None),
        ("s5", "source five", None),
        ("s-empty", "", None),
    ])
    snapshot = load_corpus(db, container_ref="c:test", visibility="private", sample_size=5, seed=0)
    assert [case.source_ids for case in snapshot.cases] == [("s1", "s3")]
    assert snapshot.attrition["missing_sources"] == 1
    assert snapshot.attrition["forgotten_sources"] == 2
    assert snapshot.attrition["malformed_exposed_json"] == 2
    assert snapshot.attrition["zero_surviving_sources"] == 4
    assert snapshot.attrition["no_valid_exposed_ids"] == 1
    assert snapshot.attrition["empty_source_text"] == 1
    assert snapshot.attrition["sources_beyond_visible_limit"] == 2
    assert snapshot.attrition["source_chars_truncated"] == 120

    provider = ScriptedProvider()
    aggregate, review = run_pilot(snapshot, provider=provider)
    encoded = json.dumps(aggregate)
    assert "SECRET_QUERY" not in encoded and "SECRET_SOURCE" not in encoded
    assert aggregate["claim"]["measures"] == "offline controlled downstream-task-effect"
    assert aggregate["claim"]["estimation"]["method"] == "chars_div_4"
    assert aggregate["claim"]["estimation"]["exact_token_ceiling"] is False
    assert aggregate["claim"]["estimation"]["unicode_may_underestimate"] is True
    assert aggregate["results"]["wins"]["with_history"] == 1
    assert "SECRET_QUERY" in json.dumps(review)
    assert len(review["cases"][0]["source_texts"][1]) == 480
    assert aggregate["decision_gate"]["status"] == "insufficient_data"
    assert provider.requests[0][0].startswith("You are a helpful software assistant")
    judge_system = provider.requests[2][0]
    assert "task-specific context improves or could improve" in judge_system
    assert "misleading, stale, or off-scope context degrades or could degrade" in judge_system
    assert "irrelevant when neither applies" in judge_system
    judge_prompt = provider.requests[2][1]
    assert "résumé SECRET_QUERY" in judge_prompt
    assert "HISTORICAL CONTEXT" in judge_prompt
    assert "with_history" not in judge_prompt and "without_history" not in judge_prompt


def test_sampling_is_seeded_and_capped(tmp_path: Path) -> None:
    db = tmp_path / "many.db"
    sources = [(f"s{i}", f"source {i}", None) for i in range(7)]
    events = [(f"e{i}", f"query {i}", json.dumps([{ "source_item_id": f"s{i}" }])) for i in range(7)]
    _db(db, events, sources)
    one = load_corpus(db, container_ref="c:test", visibility="private", sample_size=5, seed=4)
    two = load_corpus(db, container_ref="c:test", visibility="private", sample_size=5, seed=4)
    assert len(one.cases) == 5
    assert [c.case_id for c in one.cases] == [c.case_id for c in two.cases]
    with pytest.raises(ValueError):
        load_corpus(db, container_ref="c:test", visibility="invalid", sample_size=5)
    with pytest.raises(ValueError):
        load_corpus(db, container_ref="c:test", visibility="private", sample_size=0)
    with pytest.raises(ValueError):
        load_corpus(db, container_ref="c:test", visibility="private", sample_size=6)
    with pytest.raises(FileNotFoundError):
        load_corpus(tmp_path / "missing.db", container_ref="c:test", visibility="private")


def test_provider_failure_is_case_scoped_and_does_not_leak(tmp_path: Path) -> None:
    db = tmp_path / "fail.db"
    _db(db, [("e1", "PRIVATE_QUERY", json.dumps([{ "source_item_id": "s1" }]))], [("s1", "PRIVATE_SOURCE", None)])
    aggregate, review = run_pilot(load_corpus(db, container_ref="c:test", visibility="private"), provider=ScriptedProvider(fail=True))
    assert aggregate["results"]["failures"] == 1
    assert "PRIVATE_PROVIDER_SENTINEL" not in json.dumps(aggregate)
    assert review["cases"][0]["failure_type"] == "RuntimeError"


def test_cli_requires_explicit_db_and_outputs() -> None:
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])
    args = parser.parse_args(["--db", "x.db", "--container-ref", "c:test", "--visibility", "private", "--aggregate-output", "a.json", "--review-output", "r.json"])
    assert args.sample_size == 5 and args.seed == 0
    assert "never publish" in parser.format_help()

def test_loader_opens_db_read_only(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "readonly.db"
    _db(db, [("e1", "query", json.dumps([{"source_item_id": "s1"}]))], [("s1", "source", None)])
    import evals.real_corpus_pull_eval as runner
    real_connect = sqlite3.connect
    calls = []

    def capture(database, *args, **kwargs):
        conn = real_connect(database, *args, **kwargs)
        calls.append((database, kwargs, conn))
        return conn

    monkeypatch.setattr(runner.sqlite3, "connect", capture)
    load_corpus(db, container_ref="c:test", visibility="private")
    assert calls and "mode=ro" in calls[0][0]
    assert calls[0][1]["uri"] is True
    with pytest.raises(sqlite3.ProgrammingError):
        calls[0][2].execute("SELECT 1")


def test_decision_gate_requires_three_successful_pairs() -> None:
    snapshot = CorpusSnapshot(
        cases=tuple(PullCase(f"e{i}", f"t{i}", f"task {i}", (f"s{i}",), (f"context {i}",)) for i in range(3)),
        counts={"valid_cases": 3},
        attrition={},
    )
    aggregate, _ = run_pilot(snapshot, provider=ScriptedProvider())
    assert aggregate["sampling"]["paired_cases"] == 3
    assert aggregate["decision_gate"]["status"] == "directional_read_ready"
    assert aggregate["decision_gate"]["broad_product_recommendation"] == "none"
    limitations = aggregate["claim"]["limitations"]
    assert limitations == {
        "max_cases": 5,
        "judge": "single uncalibrated model judge",
        "paired_draws": 1,
        "human_spot_check": False,
        "linked_observed_work_after": False,
        "judge_sees_history": True,
    }
class InvalidJudgeProvider(ScriptedProvider):
    def generate_json(self, *, system_prompt, user_prompt, schema_description):
        self.calls += 1
        self.requests.append((system_prompt, user_prompt, schema_description))
        if "winner" in schema_description:
            raise ValueError("PRIVATE_INVALID_JUDGE")
        payload = {"answer": "answer"}
        return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)


def test_cross_scope_rows_and_exposed_sources_are_excluded(tmp_path: Path) -> None:
    db = tmp_path / "scope.db"
    _db(db, [("e1", "query", json.dumps([{ "source_item_id": "s1" }]))], [("s1", "source", None)])
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO source_items VALUES (?, ?, ?, ?, ?, ?)", ("foreign", "foreign text", None, "c:other", "private", None))
        conn.execute("INSERT INTO historical_lookup_reuse_event VALUES (?, ?, 'lookup', ?, ?, 'agent_pull', ?, NULL, ?, ?)", ("e2", "2026-01-01T00:01:00", "t2", "c:test", "private", json.dumps([{ "source_item_id": "foreign" }]), "foreign exposed"))
        conn.execute("INSERT INTO historical_lookup_reuse_event VALUES (?, ?, 'lookup', ?, ?, 'agent_pull', ?, NULL, ?, ?)", ("e3", "2026-01-01T00:02:00", "t3", "c:other", "private", json.dumps([{ "source_item_id": "s1" }]), "foreign event"))
    snapshot = load_corpus(db, container_ref="c:test", visibility="private")
    assert [case.event_id for case in snapshot.cases] == ["e1"]
    assert snapshot.attrition["missing_sources"] == 1


def test_missing_scope_schema_is_rejected(tmp_path: Path) -> None:
    db = tmp_path / "bad-schema.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE historical_lookup_reuse_event (id TEXT, session_id TEXT, created_at TEXT, event_type TEXT, trigger_origin TEXT, exposed_json TEXT, query_text TEXT)")
        conn.execute("CREATE TABLE source_items (id TEXT, content TEXT, forgotten_at TEXT)")
    with pytest.raises(ValueError):
        load_corpus(db, container_ref="c:test", visibility="private")


def test_invalid_judge_json_is_case_scoped(tmp_path: Path) -> None:
    db = tmp_path / "judge.db"
    _db(db, [("e1", "query", json.dumps([{ "source_item_id": "s1" }]))], [("s1", "source", None)])
    aggregate, review = run_pilot(
        load_corpus(db, container_ref="c:test", visibility="private"),
        provider=InvalidJudgeProvider(),
    )
    assert aggregate["results"]["failures"] == 1
    assert "PRIVATE_INVALID_JUDGE" not in json.dumps(aggregate)
    assert review["cases"][0]["failure_type"] == "ValueError"


def test_oversized_query_and_total_budget_stop(tmp_path: Path) -> None:
    db = tmp_path / "large.db"
    _db(db, [("e1", "Q" * 1001, json.dumps([{ "source_item_id": "s1" }]))], [("s1", "source", None)])
    snapshot = load_corpus(db, container_ref="c:test", visibility="private")
    assert not snapshot.cases
    assert snapshot.attrition["oversized_queries"] == 1
    huge = CorpusSnapshot(
        cases=(PullCase("e-huge", "t", "task", ("s",), ("X" * 100000,)),),
        counts={"valid_cases": 1}, attrition={},
    )
    aggregate, _ = run_pilot(huge, provider=ScriptedProvider())
    assert aggregate["results"]["budget_failures"] == 1
    assert aggregate["results"]["estimated_input_tokens_total"] == 0
    assert aggregate["decision_gate"]["status"] == "insufficient_data"


def test_cli_main_writes_reports_without_mutating_db_or_leaking_aggregate(tmp_path: Path, monkeypatch) -> None:
    import evals.real_corpus_pull_eval as runner
    db = tmp_path / "cli.db"
    _db(db, [("e1", "CLI SECRET_QUERY", json.dumps([{ "source_item_id": "s1" }]))], [("s1", "CLI SECRET_SOURCE", None)])
    before = db.read_bytes()
    monkeypatch.setattr(runner.AppConfig, "from_env", staticmethod(lambda: object()))
    monkeypatch.setattr(runner, "build_eval_providers", lambda *args, **kwargs: (ScriptedProvider(), ScriptedProvider()))
    aggregate_path = tmp_path / "aggregate.json"
    review_path = tmp_path / "review.json"
    assert runner.main(["--db", str(db), "--container-ref", "c:test", "--visibility", "private", "--aggregate-output", str(aggregate_path), "--review-output", str(review_path), "--acknowledge-private-review-output"]) == 0
    assert db.read_bytes() == before
    aggregate = aggregate_path.read_text(encoding="utf-8")
    review = review_path.read_text(encoding="utf-8")
    assert "CLI SECRET_QUERY" not in aggregate and "CLI SECRET_SOURCE" not in aggregate
    assert "CLI SECRET_QUERY" in review
    assert "contains_raw_private_text" in review and "never_publish" in review
    if os.name != "nt":
        assert stat.S_IMODE(review_path.stat().st_mode) == 0o600
    with pytest.raises(SystemExit):
        runner.main(["--db", str(db), "--container-ref", "c:test", "--visibility", "private", "--aggregate-output", str(db), "--review-output", str(tmp_path / "other.json")])

def test_answer_is_capped_before_blinded_judge(tmp_path: Path) -> None:
    db = tmp_path / "answers.db"
    _db(db, [("e1", "query", json.dumps([{ "source_item_id": "s1" }]))], [("s1", "source", None)])
    provider = ScriptedProvider(giant_answer=True)
    _, review = run_pilot(load_corpus(db, container_ref="c:test", visibility="private"), provider=provider)
    judge_prompt = provider.requests[2][1]
    assert "A" * 2000 in judge_prompt
    assert "A" * 2001 not in judge_prompt
    assert len(review["cases"][0]["with_history_answer"]) == 2000

def test_same_container_visibility_matches_production_rules(tmp_path: Path) -> None:
    db = tmp_path / "visibility.db"
    _db(db, [("e1", "query", json.dumps([{ "source_item_id": "s-private" }, { "source_item_id": "s-container" }, { "source_item_id": "s-public" }]))], [("s-private", "private text", None)])
    with sqlite3.connect(db) as conn:
        conn.executemany("INSERT INTO source_items VALUES (?, ?, ?, 'c:test', ?, NULL)", [
            ("s-container", "container text", None, "container"),
            ("s-public", "public text", None, "public"),
        ])
    private = load_corpus(db, container_ref="c:test", visibility="private")
    assert private.cases[0].source_ids == ("s-private", "s-container", "s-public")
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE historical_lookup_reuse_event SET visibility = 'public' WHERE id = 'e1'")
    public = load_corpus(db, container_ref="c:test", visibility="public")
    assert public.cases[0].source_ids == ("s-public",)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE historical_lookup_reuse_event SET visibility = 'container' WHERE id = 'e1'")
    container = load_corpus(db, container_ref="c:test", visibility="container")
    assert container.cases[0].source_ids == ("s-container", "s-public")