"""Deterministic self-test for the history-pull decision harness.

No live LLM: the decision agent uses the scripted stub provider and the service's
extraction LLM is stubbed by ``InProcessService``. Everything runs in-process via
TestClient against a scratch SQLite DB in a tmp dir; no network, no bound port.

Proves the funnel-persistence chain (agent-chosen search → persisted lookup →
agent-chosen expand → parent-linked expansion) and that the persisted events feed
the existing rollup + judge as libraries.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from evals.history_pull_decision.agent import DecisionAgent, ScriptedDecisionProvider
from evals.history_pull_decision.harness import (
    InProcessService,
    Scenario,
    compute_behavioural_metrics,
    load_scenarios,
    run_harness,
)
from evals.historical_lookup_measurement import compute_reuse_rollup, load_events_from_storage
from evals.historical_lookup_judge import _NullProvider, run_judge


# ---------------------------------------------------------------------------
# Unit: scenario loader + decision protocol + metrics
# ---------------------------------------------------------------------------


def test_load_scenarios_shapes() -> None:
    scenarios = load_scenarios()
    assert scenarios, "expected authored scenarios"
    ids = {s.id for s in scenarios}
    assert len(ids) == len(scenarios), "scenario ids must be unique"
    assert any(s.opportunity for s in scenarios)
    assert any(not s.opportunity for s in scenarios)
    assert any(s.user_directed for s in scenarios)
    assert any(not s.user_directed for s in scenarios)


def test_scripted_agent_decides_search_then_expand() -> None:
    agent = DecisionAgent(ScriptedDecisionProvider())
    search = agent.decide_search(scenario_id="s", task="do a thing", seed=0)
    assert search.search is True and search.query
    after = agent.decide_after_results(
        scenario_id="s", task="do a thing",
        results=[{"source_item_id": "x", "excerpt": "prior decision"}], seed=0,
    )
    assert after.expand is True and after.expand_index == 0 and after.answer


def test_after_decision_guards_out_of_range_index() -> None:
    # expand_index beyond the result set falls back to 0 (or no-expand if empty).
    def handler(_sys: str, user: str) -> dict:
        if "step=search" in user:
            return {"search": True, "query": "q"}
        return {"expand": True, "expand_index": 9, "answer": "a"}

    agent = DecisionAgent(ScriptedDecisionProvider(handler))
    after = agent.decide_after_results(
        scenario_id="s", task="t", results=[{"source_item_id": "x", "excerpt": "e"}], seed=0
    )
    assert after.expand_index == 0
    empty = agent.decide_after_results(scenario_id="s", task="t", results=[], seed=0)
    assert empty.expand is False and empty.expand_index is None


def test_behavioural_metrics_empty_safe() -> None:
    m = compute_behavioural_metrics([])
    assert m["n_trials"] == 0
    assert m["lookup_rate"] is None
    assert m["unprompted_pull_rate"] is None


# ---------------------------------------------------------------------------
# Integration: full dry-run chain persists funnel events + feeds rollup/judge
# ---------------------------------------------------------------------------


def _reuse_events(db_path: Path, event_type: str) -> list[dict]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, session_id, container_ref, parent_lookup_id, event_type "
            "FROM historical_lookup_reuse_event WHERE event_type = ?",
            (event_type,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def test_dry_run_persists_lookup_and_linked_expansion(tmp_path) -> None:
    db_path = tmp_path / "hpd.db"
    scenarios = [
        Scenario(
            id="unit-opp",
            user_directed=False,
            opportunity=True,
            prior_turns=[
                {"role": "user", "content": "What convention did we agree on for prior decision policy naming?"},
                {"role": "assistant", "content": "Decision: prior decision convention policy is dot.separated.lowercase."},
            ],
            current_task="Follow our established convention for the new item.",
        )
    ]
    seeds = [0, 1]

    service = InProcessService(db_path)
    try:
        trials = run_harness(
            service=service, agent=DecisionAgent(ScriptedDecisionProvider()),
            scenarios=scenarios, seeds=seeds,
        )
    finally:
        service.close()

    # Every scripted trial searched (lookup_rate == 1.0) and expanded.
    assert len(trials) == 2
    assert all(t.error is None for t in trials), [t.error for t in trials]
    assert all(t.searched for t in trials)
    metrics = compute_behavioural_metrics(trials)
    assert metrics["lookup_rate"] == 1.0
    assert metrics["unprompted_pull_rate"] == 1.0

    # (i) a lookup event persisted per seed; (ii) an expansion event linked to it.
    lookups = _reuse_events(db_path, "lookup")
    assert len(lookups) >= 2
    lookup_ids = {row["id"] for row in lookups}
    expansions = _reuse_events(db_path, "expansion")
    assert expansions, "expected at least one expansion event"
    assert any(e["parent_lookup_id"] in lookup_ids for e in expansions)

    # (iii) the persisted events feed the existing loader + rollup, well-formed.
    eligible, events = load_events_from_storage(db_path, eligibility_n=1)
    assert eligible, "expected at least one eligible session"
    rollup = compute_reuse_rollup(eligible, events, eligibility_n=1, window={})
    assert set(rollup["rungs"]) == {"incorporation", "influence", "downstream"}
    assert rollup["n_eligible_sessions"] == len(set(eligible))


def test_judge_wiring_smoke_null_provider(tmp_path) -> None:
    # Build a tiny funnel DB via the harness, then run the reuse judge over it
    # with the null provider (no LLM, no label writes) to prove the wiring.
    db_path = tmp_path / "hpd.db"
    scenarios = [
        Scenario(
            id="unit-judge", user_directed=False, opportunity=True,
            prior_turns=[
                {"role": "user", "content": "prior decision convention policy question"},
                {"role": "assistant", "content": "Answer about prior decision convention policy."},
            ],
            current_task="Use the established prior decision convention policy.",
        )
    ]
    service = InProcessService(db_path)
    try:
        run_harness(service=service, agent=DecisionAgent(ScriptedDecisionProvider()),
                    scenarios=scenarios, seeds=[0])
    finally:
        service.close()

    report = run_judge(
        db_path, provider=_NullProvider(), eligibility_n=1,
        seeds=[0, 1, 2], sample_size=50, write_labels=False,
    )
    # Null provider yields "none" rungs, but the pipeline must run and shape out.
    assert report.n_lookups >= 1
    assert set(report.rung_rates) == {"incorporation", "influence", "downstream"}
