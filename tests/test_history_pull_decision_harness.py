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

import pytest

from evals.history_pull_decision import harness as harness_mod
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


def test_after_decision_missing_index_disables_expand() -> None:
    # Finding 1: expand=true with a missing/non-integer index must NOT claim an
    # expansion the harness cannot perform.
    def handler(_sys: str, user: str) -> dict:
        if "step=search" in user:
            return {"search": True, "query": "q"}
        return {"expand": True, "answer": "a"}  # no expand_index

    agent = DecisionAgent(ScriptedDecisionProvider(handler))
    after = agent.decide_after_results(
        scenario_id="s", task="t", results=[{"source_item_id": "x", "excerpt": "e"}], seed=0
    )
    assert after.expand is False and after.expand_index is None


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


def _declining_handler(_sys: str, user: str) -> dict:
    """Scripted agent that never searches and completes from 'own knowledge'."""
    if "step=search" in user:
        return {"search": False, "query": "", "reason": "scripted: no search"}
    if "step=complete" in user:
        return {"answer": "A real, self-contained answer written without history."}
    return {"expand": False, "expand_index": 0, "answer": "unused"}


def test_no_search_completion_persists_real_work_and_is_eligible(tmp_path) -> None:
    # Finding 2: a no-search trial must persist a REAL answer (not a placeholder)
    # so the session is legitimately substantive and counts in the denominator.
    db_path = tmp_path / "hpd.db"
    scenarios = [
        Scenario(
            id="unit-nosrch", user_directed=False, opportunity=False,
            prior_turns=[
                {"role": "user", "content": "Unrelated prior chatter about lunch plans."},
                {"role": "assistant", "content": "Acknowledged the lunch plans."},
            ],
            current_task="Write a pure function; do not consult project history.",
        )
    ]
    service = InProcessService(db_path)
    try:
        trials = run_harness(
            service=service, agent=DecisionAgent(ScriptedDecisionProvider(_declining_handler)),
            scenarios=scenarios, seeds=[0],
        )
    finally:
        service.close()

    assert len(trials) == 1 and trials[0].error is None
    assert trials[0].searched is False
    assert trials[0].lookup_event_id is None

    # No lookup event persisted for a no-search trial.
    assert _reuse_events(db_path, "lookup") == []

    # The persisted assistant turn is the real answer, not the placeholder.
    conn = sqlite3.connect(str(db_path))
    try:
        rows = [
            r[0] for r in conn.execute(
                "SELECT content FROM source_items WHERE role='assistant'"
            ).fetchall()
        ]
    finally:
        conn.close()
    assert any("self-contained answer" in c for c in rows)
    assert all("(no answer produced)" not in c for c in rows)

    # Session is substantive → eligible (user turn + real assistant-work turn).
    eligible, _events = load_events_from_storage(db_path, eligibility_n=1)
    assert eligible, "no-search session must still count as eligible"


def test_db_reject_existing_then_overwrite(tmp_path) -> None:
    # Finding 4: an existing --db is rejected unless --overwrite (so reruns do
    # not accumulate events into a mixed set).
    db_path = tmp_path / "existing.db"
    db_path.write_text("stale")  # pre-existing file
    argv = ["--dry-run", "--db", str(db_path), "--seeds", "0", "--eligibility-n", "1"]

    with pytest.raises(SystemExit):
        harness_mod.main(argv)

    # With --overwrite it proceeds (the stale file is replaced by a real DB).
    rc = harness_mod.main(argv + ["--overwrite"])
    assert rc == 0
    lookups = _reuse_events(db_path, "lookup")
    assert lookups, "overwrite run should have produced fresh lookup events"


def test_keep_db_requires_explicit_db() -> None:
    # --keep-db without --db would "keep" a temp path deleted on exit.
    with pytest.raises(SystemExit):
        harness_mod.main(["--dry-run", "--seeds", "0", "--keep-db"])


def test_output_db_collision_rejected(tmp_path) -> None:
    # An --output that resolves onto the DB path would clobber the SQLite file.
    db_path = tmp_path / "hpd.db"
    with pytest.raises(SystemExit):
        harness_mod.main(
            ["--dry-run", "--seeds", "0", "--eligibility-n", "1",
             "--db", str(db_path), "--output", str(db_path)]
        )
