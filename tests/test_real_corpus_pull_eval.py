from __future__ import annotations

import json
import os
import stat
import sqlite3
from collections import Counter
from pathlib import Path

import pytest

from evals.real_corpus_pull_eval import (
    CorpusSnapshot,
    PullCase,
    _build_parser,
    load_corpus,
    render_review_sheet,
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
              visibility TEXT, actor_ref TEXT, exposed_json TEXT, query_text TEXT,
              request_source_item_id TEXT
            );
            CREATE TABLE source_items (
              id TEXT PRIMARY KEY, content TEXT, forgotten_at TEXT,
              container_ref TEXT, visibility TEXT, actor_ref TEXT,
              thread_ref TEXT, role TEXT, created_at TEXT
            );
            """
        )
        conn.executemany(
            "INSERT INTO historical_lookup_reuse_event VALUES (?, ?, 'lookup', ?, 'c:test', 'agent_pull', 'private', 'actor-test', ?, ?, ?)",
            [
                (
                    eid,
                    f"2026-01-01T00:01:{i:02d}",
                    f"thread-{i}",
                    exposed,
                    f"search: {query}",
                    f"request-{eid}",
                )
                for i, (eid, query, exposed) in enumerate(events)
            ],
        )
        conn.executemany(
            "INSERT INTO source_items VALUES (?, ?, NULL, 'c:test', 'private', 'actor-test', ?, 'user', ?)",
            [
                (f"request-{eid}", query, f"thread-{i}", f"2026-01-01T00:00:{i:02d}")
                for i, (eid, query, _) in enumerate(events)
            ],
        )
        conn.executemany(
            "INSERT INTO source_items VALUES (?, ?, ?, 'c:test', 'private', 'actor-test', 'historical', 'assistant', '2025-01-01T00:00:00')",
            sources,
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


def test_loader_uses_exact_linked_request_and_reports_link_attrition(
    tmp_path: Path,
) -> None:
    db = tmp_path / "links.db"
    events = [
        (f"e{i}", f"request {i}", json.dumps([{"source_item_id": f"s{i}"}]))
        for i in range(8)
    ]
    sources = [(f"s{i}", f"history {i}", None) for i in range(8)]
    _db(db, events, sources)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE historical_lookup_reuse_event SET request_source_item_id = NULL WHERE id = 'e0'"
        )
        conn.execute(
            "UPDATE historical_lookup_reuse_event SET request_source_item_id = 'missing' WHERE id = 'e1'"
        )
        conn.execute(
            "UPDATE source_items SET thread_ref = 'wrong' WHERE id = 'request-e2'"
        )
        conn.execute(
            "UPDATE source_items SET role = 'assistant' WHERE id = 'request-e3'"
        )
        conn.execute(
            "UPDATE source_items SET forgotten_at = '2026-01-02' WHERE id = 'request-e4'"
        )
        conn.execute(
            "UPDATE source_items SET content = '' WHERE id = 'request-e5'"
        )
        conn.execute(
            "UPDATE source_items SET created_at = '2027-01-01' WHERE id = 'request-e6'"
        )
        conn.execute(
            "UPDATE source_items SET content = '任务: résumé request' WHERE id = 'request-e7'"
        )
        conn.execute(
            "UPDATE historical_lookup_reuse_event SET query_text = 'agent search phrase' WHERE id = 'e7'"
        )

    snapshot = load_corpus(
        db, container_ref="c:test", visibility="private", sample_size=20
    )

    assert [case.event_id for case in snapshot.cases] == ["e7"]
    assert snapshot.cases[0].query == "任务: résumé request"
    assert snapshot.attrition["unlinked_requests"] == 1
    assert snapshot.attrition["missing_request_links"] == 1
    assert snapshot.attrition["wrong_scope_request_links"] == 1
    assert snapshot.attrition["non_user_request_links"] == 1
    assert snapshot.attrition["forgotten_request_links"] == 1
    assert snapshot.attrition["empty_request_links"] == 1
    assert snapshot.attrition["temporally_unsafe_request_links"] == 1
    assert snapshot.counts["directly_linked_requests"] == 1


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
        load_corpus(db, container_ref="c:test", visibility="private", sample_size=21)
    with pytest.raises(FileNotFoundError):
        load_corpus(tmp_path / "missing.db", container_ref="c:test", visibility="private")


def test_sampling_balances_requester_sessions_before_refilling(tmp_path: Path) -> None:
    db = tmp_path / "balanced.db"
    sources = [(f"s{i}", f"source {i}", None) for i in range(15)]
    events = [(f"e{i:02d}", f"query {i}", json.dumps([{"source_item_id": f"s{i}"}])) for i in range(15)]
    _db(db, events, sources)
    with sqlite3.connect(db) as conn:
        for i in range(15):
            session_id = f"session-{i // 5}"
            conn.execute(
                "UPDATE historical_lookup_reuse_event SET session_id = ? WHERE id = ?",
                (session_id, f"e{i:02d}"),
            )
            conn.execute(
                "UPDATE source_items SET thread_ref = ? WHERE id = ?",
                (session_id, f"request-e{i:02d}"),
            )

    snapshot = load_corpus(db, container_ref="c:test", visibility="private", sample_size=12, seed=7)

    assert Counter(case.session_id for case in snapshot.cases) == {
        "session-0": 4,
        "session-1": 4,
        "session-2": 4,
    }
    assert snapshot.counts["requester_sessions_sampled"] == 3
    assert snapshot.counts["requester_session_case_counts"] == [4, 4, 4]


def test_review_sheet_is_blinded_private_and_unicode_safe() -> None:
    sheet = render_review_sheet({"cases": [{
        "case_id": "abc",
        "query": "מה הוחלט?",
        "source_texts": ["résumé context"],
        "with_history_answer": "context answer",
        "without_history_answer": "baseline answer",
        "blind_with_history_is_a": False,
    }]})

    assert "private task history" in sheet
    assert "מה הוחלט?" in sheet and "résumé context" in sheet
    assert sheet.index("baseline answer") < sheet.index("context answer")
    assert "Better answer: [ ] A  [ ] B  [ ] Tie" in sheet
    assert "with_history_answer" not in sheet and "blind_with_history" not in sheet


def test_three_arm_review_sheet_includes_all_losses_and_only_two_wins() -> None:
    def case(case_id: str, winner: str) -> dict:
        return {
            "case_id": case_id,
            "query": f"task {case_id}",
            "source_texts": ["old"],
            "guarded_history": "current",
            "answers": {"raw": f"raw {case_id}", "guarded": f"guarded {case_id}"},
            "without_history_answer": f"none {case_id}",
            "arm_results": {
                "raw": {"winner": winner, "history_relevance": "useful"},
                "guarded": {"winner": "with_history", "history_relevance": "useful"},
            },
        }

    sheet = render_review_sheet({"cases": [
        case("loss", "without_history"),
        case("win-c", "with_history"),
        case("win-a", "with_history"),
        case("win-b", "with_history"),
    ]})

    assert "Case loss" in sheet
    assert "Case win-a" in sheet and "Case win-b" in sheet
    assert "Case win-c" not in sheet
    assert "Better answer: [ ] A  [ ] B  [ ] C  [ ] Tie" in sheet
    assert "Answer mapping — open after judging" in sheet

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
    assert args.sample_size == 20 and args.seed == 0
    assert args.max_model_calls == 100 and args.max_estimated_input_tokens == 50000
    assert args.case_id is None and args.no_model_judge is False
    assert "never publish" in parser.format_help()

def test_exact_case_selection_preserves_order_and_rejects_bad_ids(tmp_path: Path) -> None:
    db = tmp_path / "exact.db"
    _db(
        db,
        [(f"e{i}", f"query {i}", json.dumps([{"source_item_id": f"s{i}"}])) for i in range(3)],
        [(f"s{i}", f"source {i}", None) for i in range(3)],
    )
    all_cases = load_corpus(db, container_ref="c:test", visibility="private", sample_size=3).cases
    requested = (all_cases[2].case_id, all_cases[0].case_id)
    selected = load_corpus(
        db, container_ref="c:test", visibility="private", case_ids=requested
    )
    assert tuple(case.case_id for case in selected.cases) == requested
    with pytest.raises(ValueError, match="duplicates"):
        load_corpus(db, container_ref="c:test", visibility="private", case_ids=(requested[0], requested[0]))
    with pytest.raises(ValueError, match="unknown case_ids"):
        load_corpus(db, container_ref="c:test", visibility="private", case_ids=("missing",))

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
        "max_cases": 20,
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
        conn.execute(
            "INSERT INTO source_items VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("foreign", "foreign text", None, "c:other", "private", "actor-test", "historical", "assistant", "2025-01-01"),
        )
        conn.execute(
            "INSERT INTO source_items VALUES (?, ?, NULL, 'c:test', 'private', 'actor-test', 't2', 'user', ?)",
            ("request-e2", "foreign exposed", "2026-01-01T00:00:00"),
        )
        conn.execute(
            "INSERT INTO historical_lookup_reuse_event VALUES (?, ?, 'lookup', ?, ?, 'agent_pull', ?, ?, ?, ?, ?)",
            ("e2", "2026-01-01T00:01:00", "t2", "c:test", "private", "actor-test", json.dumps([{ "source_item_id": "foreign" }]), "search", "request-e2"),
        )
        conn.execute(
            "INSERT INTO historical_lookup_reuse_event VALUES (?, ?, 'lookup', ?, ?, 'agent_pull', ?, ?, ?, ?, ?)",
            ("e3", "2026-01-01T00:02:00", "t3", "c:other", "private", "actor-test", json.dumps([{ "source_item_id": "s1" }]), "search", "request-e1"),
        )
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
        cases=(PullCase("e-huge", "t", "task", ("s",), ("X" * 300000,)),),
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
    sheet_path = tmp_path / "review.md"
    assert runner.main(["--db", str(db), "--container-ref", "c:test", "--visibility", "private", "--sample-size", "1", "--aggregate-output", str(aggregate_path), "--review-output", str(review_path), "--review-sheet-output", str(sheet_path), "--acknowledge-private-review-output"]) == 0
    assert db.read_bytes() == before
    aggregate = aggregate_path.read_text(encoding="utf-8")
    review = review_path.read_text(encoding="utf-8")
    sheet = sheet_path.read_text(encoding="utf-8")
    assert "CLI SECRET_QUERY" not in aggregate and "CLI SECRET_SOURCE" not in aggregate
    assert "CLI SECRET_QUERY" in review and "CLI SECRET_QUERY" in sheet
    assert "contains_raw_private_text" in review and "never_publish" in review
    if os.name != "nt":
        assert stat.S_IMODE(review_path.stat().st_mode) == 0o600
    with pytest.raises(SystemExit):
        runner.main(["--db", str(db), "--container-ref", "c:test", "--visibility", "private", "--aggregate-output", str(db), "--review-output", str(tmp_path / "other.json")])
    with pytest.raises(SystemExit):
        runner.main(["--db", str(db), "--container-ref", "c:test", "--visibility", "private", "--aggregate-output", str(aggregate_path), "--review-output", str(review_path), "--review-sheet-output", str(review_path), "--acknowledge-private-review-output"])

def test_cli_insufficient_linked_cases_skips_provider_setup(
    tmp_path: Path, monkeypatch,
) -> None:
    import evals.real_corpus_pull_eval as runner

    db = tmp_path / "insufficient.db"
    _db(
        db,
        [("e1", "one linked request", json.dumps([{"source_item_id": "s1"}]))],
        [("s1", "history", None)],
    )
    monkeypatch.setattr(
        runner.AppConfig,
        "from_env",
        staticmethod(lambda: (_ for _ in ()).throw(AssertionError("config loaded"))),
    )
    monkeypatch.setattr(
        runner,
        "build_eval_providers",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("provider built")),
    )
    aggregate_path = tmp_path / "aggregate.json"
    review_path = tmp_path / "review.json"

    assert runner.main([
        "--db", str(db),
        "--container-ref", "c:test",
        "--visibility", "private",
        "--aggregate-output", str(aggregate_path),
        "--review-output", str(review_path),
        "--acknowledge-private-review-output",
    ]) == 0

    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    assert aggregate["decision_gate"]["status"] == "blocked_insufficient_linked_cases"
    assert aggregate["sampling"]["requested_cases"] == 20
    assert aggregate["results"]["model_calls"] == 0
    assert aggregate["results"]["estimated_input_tokens_total"] == 0


def test_cli_exact_no_judge_run_obeys_caps_and_rejects_unknown_before_calls(tmp_path: Path, monkeypatch) -> None:
    import evals.real_corpus_pull_eval as runner

    db = tmp_path / "cli-controls.db"
    _db(
        db,
        [(f"e{i}", f"private query {i}", json.dumps([{"source_item_id": f"s{i}"}])) for i in range(2)],
        [(f"s{i}", f"private source {i}", None) for i in range(2)],
    )
    selected_id = load_corpus(
        db, container_ref="c:test", visibility="private", sample_size=2
    ).cases[1].case_id
    provider = ScriptedProvider()
    monkeypatch.setattr(runner.AppConfig, "from_env", staticmethod(lambda: object()))
    monkeypatch.setattr(runner, "build_eval_providers", lambda *args, **kwargs: (provider, provider))
    aggregate_path = tmp_path / "aggregate.json"
    review_path = tmp_path / "review.json"
    base = [
        "--db", str(db), "--container-ref", "c:test", "--visibility", "private",
        "--aggregate-output", str(aggregate_path), "--review-output", str(review_path),
        "--sample-size", "1",
        "--acknowledge-private-review-output", "--case-id", selected_id,
        "--no-model-judge", "--max-model-calls", "2", "--max-estimated-input-tokens", "5000",
    ]
    assert runner.main(base) == 0
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    review = json.loads(review_path.read_text(encoding="utf-8"))
    assert provider.calls == aggregate["results"]["model_calls"] == 2
    assert aggregate["results"]["judge_calls"] == 0
    assert aggregate["sampling"]["paired_cases"] == 1
    assert review["cases"][0]["case_id"] == selected_id
    invalid = base.copy()
    invalid[invalid.index(selected_id)] = "missing"
    with pytest.raises(SystemExit):
        runner.main(invalid)
    assert provider.calls == 2

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
        conn.executemany(
            "INSERT INTO source_items VALUES (?, ?, ?, 'c:test', ?, ?, 'historical', 'assistant', '2025-01-01')",
            [
                ("s-container", "container text", None, "container", "actor-test"),
                ("s-public", "public text", None, "public", None),
            ],
        )
    private = load_corpus(db, container_ref="c:test", visibility="private")
    assert private.cases[0].source_ids == ("s-private", "s-container", "s-public")
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE historical_lookup_reuse_event SET visibility = 'public', actor_ref = NULL WHERE id = 'e1'")
        conn.execute("UPDATE source_items SET visibility = 'public', actor_ref = NULL WHERE id = 'request-e1'")
    public = load_corpus(db, container_ref="c:test", visibility="public")
    assert public.cases[0].source_ids == ("s-public",)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE historical_lookup_reuse_event SET visibility = 'container', actor_ref = NULL WHERE id = 'e1'")
        conn.execute("UPDATE source_items SET visibility = 'container', actor_ref = NULL WHERE id = 'request-e1'")
    container = load_corpus(db, container_ref="c:test", visibility="container")
    assert container.cases[0].source_ids == ("s-container", "s-public")

def _add_lineage(db: Path) -> None:
    with sqlite3.connect(db) as conn:
        conn.executescript("""
            CREATE TABLE memory_objects (
              id TEXT PRIMARY KEY, type TEXT, payload_json TEXT, lifecycle TEXT,
              visibility TEXT, container_ref TEXT, actor_ref TEXT,
              created_at TEXT, freshness_at TEXT, subject TEXT,
              superseded_by_id TEXT, is_soft_deleted INTEGER DEFAULT 0
            );
            CREATE TABLE relations (
              from_kind TEXT, from_id TEXT, relation_type TEXT, to_kind TEXT, to_id TEXT
            );
        """)
        conn.executemany(
            "INSERT INTO memory_objects VALUES (?, ?, ?, ?, 'private', 'c:test', NULL, ?, ?, NULL, ?, 0)",
            [
                ("old", "decision", '{"statement":"use old"}', "superseded", "2026-01-01", "2026-01-01", "new"),
                ("new", "decision", '{"statement":"use new"}', "active", "2026-01-02", "2026-01-02", None),
                ("summary-old", "thread_summary", '{"summary":"old roll-up"}', "superseded", "2026-01-01", "2026-01-01", "summary-new"),
                ("summary-new", "thread_summary", '{"summary":"unrelated roll-up"}', "active", "2026-01-02", "2026-01-02", None),
                ("atomic-old", "atomic_fact", '{"statement":"old atom"}', "superseded", "2026-01-01", "2026-01-01", "fact-summary"),
                ("fact-summary", "fact_summary", '{"summary":"merged facts"}', "active", "2026-01-02", "2026-01-02", None),
            ],
        )
        conn.executemany("INSERT INTO relations VALUES (?, ?, ?, ?, ?)", [
            ("memory_object", "old", "supported_by", "source_item", "s1"),
            ("memory_object", "new", "supersedes", "memory_object", "old"),
            ("memory_object", "summary-old", "supported_by", "source_item", "s1"),
            ("memory_object", "summary-new", "supersedes", "memory_object", "summary-old"),
            ("memory_object", "atomic-old", "supported_by", "source_item", "s1"),
            ("memory_object", "fact-summary", "supersedes", "memory_object", "atomic-old"),
        ])


def test_guarded_history_uses_supported_lineage_and_both_arms(tmp_path: Path) -> None:
    db = tmp_path / "lineage.db"
    _db(db, [("e1", "which decision?", json.dumps([{"source_item_id": "s1"}]))], [("s1", "we used old", None)])
    _add_lineage(db)
    snapshot = load_corpus(db, container_ref="c:test", visibility="private")
    assert snapshot.lineage["sampled_cases_with_supported_replacements"] == 1
    raw_payload = json.loads(snapshot.cases[0].raw_history)
    assert "historical_updates" not in raw_payload["results"][0]
    payload = json.loads(snapshot.cases[0].guarded_history)
    assert len(payload["results"][0]["historical_updates"]) == 1
    assert payload["results"][0]["historical_updates"][0]["memory_type"] == "decision"
    assert payload["results"][0]["historical_updates"][0]["replacement_status"] == "current"
    assert payload["results"][0]["historical_updates"][0]["current_text"] == "use new"
    assert snapshot.lineage["supported_memory_claims"] == 1
    provider = ScriptedProvider()
    aggregate, _ = run_pilot(snapshot, provider=provider, history_arm="both")
    assert aggregate["results"]["arms"] == ["raw", "guarded"]
    assert aggregate["results"]["model_calls"] == 5
    assert aggregate["results"]["category_results"]["raw"]["replaced_decision"]["wins"]
    assert provider.calls == 5


def test_guarded_history_follows_visible_cross_container_successor(tmp_path: Path) -> None:
    db = tmp_path / "cross-container-lineage.db"
    _db(db, [("e1", "which decision?", json.dumps([{"source_item_id": "s1"}]))], [("s1", "we used old", None)])
    _add_lineage(db)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE memory_objects SET container_ref = 'c:other', visibility = 'public' WHERE id = 'new'"
        )

    snapshot = load_corpus(db, container_ref="c:test", visibility="private")
    update = json.loads(snapshot.cases[0].guarded_history)["results"][0]["historical_updates"][0]
    assert update["replacement_status"] == "current"
    assert update["current_memory_object_id"] == "new"
    assert snapshot.lineage["sampled_cases_with_supported_replacements"] == 1


def test_guarded_arm_stops_before_provider_when_lineage_is_absent(tmp_path: Path) -> None:
    db = tmp_path / "no-lineage.db"
    _db(db, [("e1", "query", json.dumps([{"source_item_id": "s1"}]))], [("s1", "source", None)])
    snapshot = load_corpus(
        db,
        container_ref="c:test",
        visibility="private",
        category_labels={"e1": "replaced_decision"},
    )
    assert snapshot.cases[0].category == "replaced_decision"
    assert snapshot.lineage["sampled_cases_with_supported_replacements"] == 0
    aggregate, _ = run_pilot(snapshot, history_arm="guarded")
    assert aggregate["decision_gate"]["status"] == "blocked_no_supported_lineage"
    assert aggregate["results"]["model_calls"] == 0
    assert aggregate["results"]["judge_calls"] == 0
    assert aggregate["results"]["max_model_calls"] == 100
    assert aggregate["results"]["max_estimated_input_tokens"] == 50000


def test_guarded_preflight_recomputes_case_lineage_and_fails_closed() -> None:
    snapshot = CorpusSnapshot(
        cases=(PullCase("e1", "t1", "task", ("s1",), ("context",)),),
        counts={"valid_cases": 1},
        attrition={},
        lineage={"sampled_cases_with_supported_replacements": 99},
    )
    provider = ScriptedProvider(fail=True)
    aggregate, _ = run_pilot(snapshot, provider=provider, history_arm="guarded")
    assert provider.calls == 0
    assert aggregate["decision_gate"]["status"] == "blocked_no_supported_lineage"
    assert aggregate["corpus"]["lineage"]["sampled_cases_with_supported_replacements"] == 0

def test_mid_case_budget_stop_does_not_commit_partial_judge_counts() -> None:
    snapshot = CorpusSnapshot(
        cases=(PullCase("e1", "t1", "task", ("s1",), ("context",), guarded_history='["guarded"]', has_supported_replacement=True),),
        counts={"valid_cases": 1},
        attrition={},
        lineage={"sampled_cases_with_supported_replacements": 1},
    )
    aggregate, _ = run_pilot(
        snapshot, provider=ScriptedProvider(), history_arm="both", max_model_calls=4
    )

    assert aggregate["sampling"]["paired_cases"] == 0
    assert aggregate["results"]["budget_failures"] == 1
    assert all(sum(wins.values()) == 0 for wins in aggregate["results"]["wins"].values())

def test_no_model_judge_emits_blinded_three_arm_review_with_three_calls() -> None:
    snapshot = CorpusSnapshot(
        cases=(PullCase("e1", "t1", "task", ("s1",), ("context",), guarded_history='["guarded"]', has_supported_replacement=True),),
        counts={"valid_cases": 1},
        attrition={},
        lineage={"sampled_cases_with_supported_replacements": 1},
    )
    provider = ScriptedProvider()
    aggregate, review = run_pilot(
        snapshot, provider=provider, history_arm="both", model_judge=False
    )
    assert provider.calls == aggregate["results"]["model_calls"] == 3
    assert aggregate["results"]["judge_calls"] == 0
    assert aggregate["decision_gate"]["status"] == "awaiting_agent_review"
    assert all("winner" not in schema for _, _, schema in provider.requests)
    assert set(review["cases"][0]["answers"]) == {"raw", "guarded"}
    assert "Better answer: [ ] A  [ ] B  [ ] C  [ ] Tie" in render_review_sheet(review)


def test_raw_no_judge_sheet_uses_exact_raw_prompt() -> None:
    snapshot = CorpusSnapshot(
        cases=(PullCase(
            "e1", "t1", "task", ("s1",), ("SOURCE_TEXT",),
            raw_history="RAW_SERIALIZED",
        ),),
        counts={"valid_cases": 1},
        attrition={},
    )
    _, review = run_pilot(
        snapshot, provider=ScriptedProvider(), history_arm="raw", model_judge=False
    )
    sheet = render_review_sheet(review)
    assert "RAW_SERIALIZED" in sheet
    assert "SOURCE_TEXT" not in sheet

def test_guarded_no_judge_sheet_uses_exact_guarded_prompt() -> None:
    snapshot = CorpusSnapshot(
        cases=(PullCase(
            "e1", "t1", "task", ("s1",), ("RAW_CONTEXT",),
            guarded_history="GUARDED_SERIALIZED", has_supported_replacement=True,
        ),),
        counts={"valid_cases": 1},
        attrition={},
    )
    _, review = run_pilot(
        snapshot, provider=ScriptedProvider(), history_arm="guarded", model_judge=False
    )
    sheet = render_review_sheet(review)
    assert "GUARDED_SERIALIZED" in sheet
    assert "RAW_CONTEXT" not in sheet

def test_caller_budget_caps_are_lower_bounded_and_stop_before_call() -> None:
    snapshot = CorpusSnapshot(
        cases=(PullCase("e1", "t1", "task", ("s1",), ("context",)),),
        counts={"valid_cases": 1},
        attrition={},
    )
    provider = ScriptedProvider()
    aggregate, _ = run_pilot(
        snapshot, provider=provider, max_model_calls=1, max_estimated_input_tokens=1
    )
    assert provider.calls == aggregate["results"]["model_calls"] == 0
    assert aggregate["sampling"]["paired_cases"] == 0
    assert aggregate["results"]["max_model_calls"] == 1
    assert aggregate["results"]["max_estimated_input_tokens"] == 1
    with pytest.raises(ValueError, match="max_model_calls"):
        run_pilot(snapshot, provider=provider, max_model_calls=101)
    with pytest.raises(ValueError, match="max_estimated_input_tokens"):
        run_pilot(snapshot, provider=provider, max_estimated_input_tokens=50001)

def test_both_arms_respect_hard_call_cap() -> None:
    snapshot = CorpusSnapshot(
        cases=tuple(
            PullCase(f"e{i}", f"t{i}", f"task {i}", (f"s{i}",), (f"context {i}",), guarded_history=f'["guarded {i}"]', has_supported_replacement=True)
            for i in range(20)
        ),
        counts={"valid_cases": 20},
        attrition={},
        lineage={"sampled_cases_with_supported_replacements": 20},
    )
    provider = ScriptedProvider()
    aggregate, _ = run_pilot(snapshot, provider=provider, history_arm="both")
    assert aggregate["results"]["model_calls"] == 100
    assert aggregate["sampling"]["paired_cases"] == 20
