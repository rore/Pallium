"""Phase 6 measurement-script tests.

See: docs/specs/2026-06-27-injection-policy-abstention.md (Phase 6).

Live-DB rollup tests are out of scope (no measurement-window data yet
in this session). These tests cover the pure rollup logic with
in-memory fixtures so the script is correct when the live data arrives.
"""

from __future__ import annotations

import pytest

from evals.injection_policy_2026_06.phase6_measurement import (
    build_report,
    rollup_by_trigger,
    rollup_demoted_type_discovery,
    rollup_proactive_usage,
)


def _row(
    *,
    memory_type: str,
    trigger_origin: str | None = None,
    populated: bool = False,
    referenced: bool = False,
    memory_object_id: str = "m",
    query_audit_log_id: str = "q",
) -> dict:
    return {
        "id": f"row-{memory_object_id}-{query_audit_log_id}-{trigger_origin}",
        "query_audit_log_id": query_audit_log_id,
        "memory_object_id": memory_object_id,
        "memory_type": memory_type,
        "trigger_origin": trigger_origin,
        "populated_at": "2026-06-28T00:00:00" if populated else None,
        "referenced_in_next_turn": (1 if referenced else 0) if populated else None,
        "created_at": "2026-06-27T00:00:00",
    }


# ---------------------------------------------------------------------------
# rollup_proactive_usage
# ---------------------------------------------------------------------------


def test_proactive_rollup_excludes_triggered_rows() -> None:
    rows = [
        _row(memory_type="decision", trigger_origin=None,
             populated=True, referenced=True, memory_object_id="m1",
             query_audit_log_id="q1"),
        _row(memory_type="decision", trigger_origin="post_tool_failure",
             populated=True, referenced=True, memory_object_id="m2",
             query_audit_log_id="q2"),
    ]
    out = rollup_proactive_usage(rows, {})
    assert out["decision"]["n_total"] == 1  # triggered row excluded


def test_proactive_rollup_usage_rate() -> None:
    rows = [
        _row(memory_type="decision", populated=True, referenced=True,
             memory_object_id=f"m{i}", query_audit_log_id=f"q{i}")
        for i in range(7)
    ] + [
        _row(memory_type="decision", populated=True, referenced=False,
             memory_object_id=f"mn{i}", query_audit_log_id=f"qn{i}")
        for i in range(3)
    ] + [
        _row(memory_type="decision", populated=False,
             memory_object_id=f"mp{i}", query_audit_log_id=f"qp{i}")
        for i in range(5)
    ]
    out = rollup_proactive_usage(rows, {})
    assert out["decision"]["n_total"] == 15
    assert out["decision"]["n_populated"] == 10
    assert out["decision"]["n_referenced"] == 7
    assert out["decision"]["usage_rate"] == pytest.approx(0.7)


def test_proactive_rollup_rating_precision_joins_feedback() -> None:
    rows = [
        _row(memory_type="decision",
             memory_object_id=f"m{i}", query_audit_log_id=f"q{i}")
        for i in range(5)
    ]
    feedback_index = {
        ("m0", "q0"): "relevant",
        ("m1", "q1"): "relevant",
        ("m2", "q2"): "not_relevant",
        # m3, m4 unrated
    }
    out = rollup_proactive_usage(rows, feedback_index)
    assert out["decision"]["n_rated_relevant"] == 2
    assert out["decision"]["n_rated_bad"] == 1
    assert out["decision"]["rating_precision"] == pytest.approx(2 / 3)


def test_proactive_rollup_handles_empty_input() -> None:
    out = rollup_proactive_usage([], {})
    assert out == {}


def test_proactive_rollup_usage_rate_none_when_nothing_populated() -> None:
    rows = [
        _row(memory_type="decision", populated=False,
             memory_object_id="m", query_audit_log_id="q"),
    ]
    out = rollup_proactive_usage(rows, {})
    assert out["decision"]["usage_rate"] is None


# ---------------------------------------------------------------------------
# rollup_by_trigger
# ---------------------------------------------------------------------------


def test_by_trigger_includes_proactive_default_with_null_key() -> None:
    rows = [
        _row(memory_type="decision", trigger_origin=None,
             populated=True, referenced=False,
             memory_object_id="m1", query_audit_log_id="q1"),
        _row(memory_type="investigation_outcome",
             trigger_origin="post_tool_failure",
             populated=True, referenced=True,
             memory_object_id="m2", query_audit_log_id="q2"),
    ]
    out = rollup_by_trigger(rows, {})
    assert "(proactive_default)" in out
    assert "post_tool_failure" in out
    assert out["(proactive_default)"]["n_populated"] == 1
    assert out["post_tool_failure"]["usage_rate"] == 1.0


# ---------------------------------------------------------------------------
# rollup_demoted_type_discovery
# ---------------------------------------------------------------------------


def test_demoted_type_discovery_separates_trigger_origin() -> None:
    rows = [
        # investigation_outcome surfaced only via trigger
        _row(memory_type="investigation_outcome",
             trigger_origin="post_tool_failure",
             memory_object_id="m1", query_audit_log_id="q1"),
        # task_checkpoint surfaced only proactively
        _row(memory_type="task_checkpoint", trigger_origin=None,
             memory_object_id="m2", query_audit_log_id="q2"),
    ]
    out = rollup_demoted_type_discovery(rows)
    inv = out["investigation_outcome"]
    assert inv["n_proactive_injections"] == 0
    assert inv["n_triggered_injections"] == 1
    assert inv["trigger_breakdown"]["post_tool_failure"] == 1
    tc = out["task_checkpoint"]
    assert tc["n_proactive_injections"] == 1
    assert tc["n_triggered_injections"] == 0


def test_demoted_type_discovery_returns_zero_for_unseen_types() -> None:
    out = rollup_demoted_type_discovery([])
    for mtype in ("investigation_outcome", "thread_summary",
                   "fact_summary", "task_checkpoint"):
        assert out[mtype]["n_proactive_injections"] == 0
        assert out[mtype]["n_triggered_injections"] == 0


# ---------------------------------------------------------------------------
# build_report smoke
# ---------------------------------------------------------------------------


def test_build_report_has_expected_sections() -> None:
    rows = [
        _row(memory_type="decision", trigger_origin=None,
             populated=True, referenced=True,
             memory_object_id="m1", query_audit_log_id="q1"),
    ]
    feedback_rows = [
        {"memory_object_id": "m1", "query_audit_log_id": "q1", "rating": "relevant"},
    ]
    report = build_report(rows, feedback_rows, since="2026-06-27")
    assert report["phase"].startswith("6")
    assert "per_type_proactive" in report
    assert "per_trigger" in report
    assert "demoted_type_discovery" in report
    assert report["window"]["n_usage_rows"] == 1
    assert report["window"]["n_feedback_rows"] == 1


def test_load_usage_audit_rows_returns_empty_when_table_missing(tmp_path) -> None:
    """Defensive: if the schema migration hasn't run yet (pre-Phase-5a
    DB), the script must yield empty rows, not crash.
    """
    import sqlite3
    from evals.injection_policy_2026_06.phase6_measurement import (
        load_usage_audit_rows,
    )
    db_path = tmp_path / "no_table.db"
    con = sqlite3.connect(db_path)
    con.execute("CREATE TABLE other_table (id TEXT)")
    con.commit()
    con.row_factory = sqlite3.Row
    rows = load_usage_audit_rows(con)
    con.close()
    assert rows == []
