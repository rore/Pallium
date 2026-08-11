from __future__ import annotations

import json
import types

import pytest

from providers.llm.base import LLMCallMetadata, LLMJsonResponse, LLMProvider
from semantic.agent_conversation_memory_subtask_selector_shadow import (
    SubtaskSelectorShadowRunner,
)


# ── test doubles ───────────────────────────────────────────────────────────


class FakeProvider(LLMProvider):
    """Scripted LLM provider. Pops one response per generate_json call."""

    def __init__(self, responses, *, raise_exc: Exception | None = None):
        self._responses = list(responses)
        self._raise = raise_exc
        self.calls = []

    def generate_json(self, *, system_prompt, user_prompt, schema_description):
        self.calls.append({"system": system_prompt, "user": user_prompt})
        if self._raise is not None:
            raise self._raise
        parsed = self._responses.pop(0) if self._responses else {"pick": "NONE", "reason": "x"}
        return LLMJsonResponse(
            raw_text=json.dumps(parsed),
            parsed_json=parsed,
            metadata=LLMCallMetadata(
                provider_name="fake", provider_kind="fake", model="fake-haiku",
            ),
        )


class FakeStorage:
    def __init__(self):
        self.rows = []

    def get_source_item(self, source_item_id):
        return types.SimpleNamespace(
            metadata={"cwd": "/repo/x", "agent_work_trace_turn": "was doing X"}
        )

    def write_subtask_selector_shadow_row(self, row):
        self.rows.append(row)


def _evidence(source_item_id, thread_ref):
    return types.SimpleNamespace(source_item_id=source_item_id, thread_ref=thread_ref)


def _item(mid, thread_ref, text, mtype="task_checkpoint"):
    return types.SimpleNamespace(
        result_id=f"memory_object:{mid}",
        memory_object_id=mid,
        type=mtype,
        payload={"summary": text},
        evidence=[_evidence(f"s_{mid}", thread_ref)],
    )


def _entry(mid, rank):
    return {
        "result_id": f"memory_object:{mid}",
        "result_origin": "memory",
        "memory_type": "task_checkpoint",
        "support_grade": "strong",
        "routing_rank": rank,
        "routing_score": 100 - rank,
        "retrieval_score": 50 - rank,
    }


def _make_result(*, wr_state="strongly_eligible", items_and_threads, current_thread="T_current"):
    """Build a minimal stand-in QueryResult the runner can read.

    items_and_threads: list of (mid, thread_ref, text). The first goes into
    selected_results, the rest into excluded_high_scoring_candidates.
    """
    items = [_item(mid, tref, text) for (mid, tref, text) in items_and_threads]
    ranked = [{"item": it} for it in items]
    entries = [_entry(mid, i + 1) for i, (mid, _, _) in enumerate(items_and_threads)]
    routing = {
        "lane_narrowing": {
            "lane_details": [{"lane": "work_resumption", "state": wr_state}]
        },
        "selected_results": entries[:1],
        "excluded_high_scoring_candidates": entries[1:],
        "demoted_higher_level_hits": [],
    }
    result = types.SimpleNamespace(
        trace=types.SimpleNamespace(routing=routing),
        _ranked_candidates=ranked,
        should_inject=True,
        injectable_blocks=["frozen-block"],
        decision_reason="inject",
    )
    return result


def _runner(provider, storage, **kw):
    return SubtaskSelectorShadowRunner(
        storage=storage, provider=provider, model="fake-haiku", synchronous=True, **kw
    )


def _observe(runner, result, thread_ref="T_current"):
    return runner.observe(
        result=result, query_text="pick up where we left off",
        container_ref="c", thread_ref=thread_ref, actor_ref="a",
        visibility="private", trigger_origin="user_prompt_submit",
    )


# ── gate behaviour ──────────────────────────────────────────────────────────


def test_gate_skips_when_not_strongly_eligible():
    provider = FakeProvider([])
    storage = FakeStorage()
    result = _make_result(
        wr_state="plausible",
        items_and_threads=[("m1", "T_a", "a"), ("m2", "T_b", "b")],
    )
    dispatched = _observe(_runner(provider, storage), result)
    assert dispatched is False
    assert provider.calls == []
    assert storage.rows == []


def test_gate_skips_when_fewer_than_two_cross_session():
    provider = FakeProvider([])
    storage = FakeStorage()
    # only m1 is cross-session; m2 is on the current thread
    result = _make_result(
        items_and_threads=[("m1", "T_a", "a"), ("m2", "T_current", "b")],
    )
    dispatched = _observe(_runner(provider, storage), result)
    assert dispatched is False
    assert provider.calls == []
    assert storage.rows == []


def test_gate_skips_when_no_routing_trace():
    provider = FakeProvider([])
    storage = FakeStorage()
    result = types.SimpleNamespace(trace=None, _ranked_candidates=[])
    dispatched = _observe(_runner(provider, storage), result)
    assert dispatched is False
    assert storage.rows == []


# ── happy path: runs both selectors and writes one row ──────────────────────


def test_runs_both_selectors_and_writes_row():
    provider = FakeProvider([
        {"pick": "m1", "reason": "on the current sub-task"},   # B
        {"pick": "NONE", "reason": "not specific enough"},      # C
    ])
    storage = FakeStorage()
    result = _make_result(
        items_and_threads=[("m1", "T_a", "resume the migration"), ("m2", "T_b", "unrelated")],
    )
    dispatched = _observe(_runner(provider, storage), result)

    assert dispatched is True
    assert len(provider.calls) == 2                       # B and C, one call each
    assert len(storage.rows) == 1
    row = storage.rows[0]
    assert row["selector_b_pick"] == "m1"
    assert row["selector_c_pick"] == "NONE"
    assert row["work_resumption_state"] == "strongly_eligible"
    assert row["cross_session_candidate_count"] == 2
    assert row["prompt_version"] == "report6_frozen_v1"
    # candidate set is recorded with source-task context filled in for C
    cands = json.loads(row["candidate_set_json"])
    assert {c["opt_id"] for c in cands} == {"m1", "m2"}
    assert any("working dir" in (c.get("source_task") or "") for c in cands)
    selectors = json.loads(row["selectors_json"])
    assert selectors["B"]["parse_status"] == "ok"
    assert selectors["C"]["parse_status"] == "ok"
    assert selectors["B"]["est_prompt_tokens"] > 0
    assert row["total_latency_ms"] >= 0.0


def test_c_prompt_includes_source_task_b_does_not():
    provider = FakeProvider([
        {"pick": "NONE", "reason": "b"},
        {"pick": "NONE", "reason": "c"},
    ])
    storage = FakeStorage()
    result = _make_result(
        items_and_threads=[("m1", "T_a", "x"), ("m2", "T_b", "y")],
    )
    _observe(_runner(provider, storage), result)
    b_user = provider.calls[0]["user"]
    c_user = provider.calls[1]["user"]
    assert "source_task" not in b_user
    assert "source_task" in c_user


def test_invalid_pick_recorded_as_none_with_flag():
    provider = FakeProvider([
        {"pick": "does-not-exist", "reason": "b"},
        {"pick": "m2", "reason": "c"},
    ])
    storage = FakeStorage()
    result = _make_result(
        items_and_threads=[("m1", "T_a", "x"), ("m2", "T_b", "y")],
    )
    _observe(_runner(provider, storage), result)
    selectors = json.loads(storage.rows[0]["selectors_json"])
    assert storage.rows[0]["selector_b_pick"] == "NONE"
    assert selectors["B"]["parse_status"] == "invalid_pick"
    assert storage.rows[0]["selector_c_pick"] == "m2"


def test_provider_error_is_contained_and_recorded():
    provider = FakeProvider([], raise_exc=RuntimeError("boom"))
    storage = FakeStorage()
    result = _make_result(
        items_and_threads=[("m1", "T_a", "x"), ("m2", "T_b", "y")],
    )
    dispatched = _observe(_runner(provider, storage), result)   # must not raise
    assert dispatched is True
    row = storage.rows[0]
    assert row["selector_b_pick"] is None
    assert row["selector_c_pick"] is None
    selectors = json.loads(row["selectors_json"])
    assert selectors["B"]["parse_status"] == "llm_error"


# ── end-to-end persistence through the real SQLite table ────────────────────


def test_row_persists_to_real_sqlite_table(tmp_path):
    from storage.sqlite import SQLiteStorageProvider
    from sqlalchemy import text

    db_url = f"sqlite:///{(tmp_path / 'shadow.db').as_posix()}"
    storage = SQLiteStorageProvider(db_url)
    provider = FakeProvider([
        {"pick": "m1", "reason": "on task"},
        {"pick": "NONE", "reason": "abstain"},
    ])
    result = _make_result(
        items_and_threads=[("m1", "T_a", "resume migration"), ("m2", "T_b", "other")],
    )
    _observe(_runner(provider, storage), result)

    with storage._engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT selector_b_pick, selector_c_pick, work_resumption_state, "
            "cross_session_candidate_count FROM subtask_selector_shadow"
        )).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "m1"
    assert rows[0][1] == "NONE"
    assert rows[0][2] == "strongly_eligible"
    assert rows[0][3] == 2


# ── the core invariant: shadow mode cannot affect injection output ──────────


def _seam_executor(monkeypatch, shadow_runner):
    """Build a QueryExecutor whose routing is canned, so we can drive the
    shadow seam and compare the returned QueryResult with/without shadow."""
    from core import routing as core_routing
    from core.contracts import PackageQueryOutcome
    from core.query import QueryExecutor
    from retrieval.base import RetrievalQueryResult

    canned = PackageQueryOutcome(
        results=[],
        trace=None,
        should_inject=True,
        decision_reason="canned_inject",
        injectable_blocks=["real-block"],
        ranked_candidates=[],
        injection_method="proactive",
    )
    monkeypatch.setattr(core_routing, "route_query_results", lambda **kw: canned)

    class _FakeRetrieval:
        def query(self, **kwargs):
            return RetrievalQueryResult(results=[], trace=None)

    plugin = types.SimpleNamespace(requires_visibility_context=True, route_query_results=lambda **k: None)
    return QueryExecutor(
        storage=types.SimpleNamespace(),
        retrieval=_FakeRetrieval(),
        semantic_plugins={"uc": plugin},
        default_use_case="uc",
        shadow_subtask_selector=shadow_runner,
    )


def _run_query(executor):
    return executor.query(
        "resume work", 5, container_ref="c", thread_ref="t", actor_ref="a",
        visibility="private", include_trace=True, trigger_origin="user_prompt_submit",
    )


def test_shadow_none_matches_baseline(monkeypatch):
    baseline = _run_query(_seam_executor(monkeypatch, None))
    assert baseline.should_inject is True
    assert baseline.injectable_blocks == ["real-block"]
    assert baseline.decision_reason == "canned_inject"


def test_raising_shadow_does_not_change_result_or_raise(monkeypatch):
    baseline = _run_query(_seam_executor(monkeypatch, None))

    class RaisingRunner:
        def observe(self, **kwargs):
            raise RuntimeError("shadow blew up")

    result = _run_query(_seam_executor(monkeypatch, RaisingRunner()))
    assert result.should_inject == baseline.should_inject
    assert result.injectable_blocks == baseline.injectable_blocks
    assert result.decision_reason == baseline.decision_reason
    assert result.injection_method == baseline.injection_method


def test_shadow_observe_is_invoked_with_finalized_result(monkeypatch):
    class RecordingRunner:
        def __init__(self):
            self.calls = []

        def observe(self, **kwargs):
            self.calls.append(kwargs)
            return True

    runner = RecordingRunner()
    result = _run_query(_seam_executor(monkeypatch, runner))
    assert len(runner.calls) == 1
    observed = runner.calls[0]["result"]
    # the runner sees the SAME finalized, already-injecting result
    assert observed is result
    assert observed.should_inject is True
    assert observed.injectable_blocks == ["real-block"]


def test_config_default_is_disabled():
    from app.config import ObservabilityConfig
    assert ObservabilityConfig().shadow_subtask_selector_enabled is False
