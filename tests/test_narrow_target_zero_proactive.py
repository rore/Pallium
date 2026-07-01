"""W4 PR 4 — zero-proactive invariant across the narrow-target replay.

Milestone acceptance (docs/specs/2026-07-01-milestone-shaped-memory-contract.md §W4):
zero ``injection_mode="proactive"`` audit-log entries with
``type=operational_fact`` after ship.

This test drives the full narrow-target replay through run_all.main
and asserts the aggregate ``proactive_operational_fact_count == 0``.

The scenarios themselves each check their own container_ref-scoped
count; this test is the additional CI-level regression gate that
would trip loud if a future PR silently reintroduces proactive
operational_fact injection.

A **positive-control test** also verifies that the guard function
would actually detect a violation — inserting a fake audit-log row
with a proactive operational_fact block and asserting the counter
returns non-zero. Without this, the primary assertion could be
tautological (returning zero because the guard is broken).
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from evals.narrow_target_claude_code import run_all
from evals.narrow_target_claude_code._shared import (
    build_isolated_client_with_operational_fact_enabled,
    count_proactive_operational_fact_injections,
)
from storage.sqlite import SQLiteStorageProvider


def test_zero_proactive_operational_fact_across_replay(tmp_path):
    output = tmp_path / "baseline.json"
    exit_code = run_all.main(["--output", str(output)])
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["proactive_operational_fact_count"] == 0, (
        f"zero-proactive invariant broken: "
        f"{payload['proactive_operational_fact_count']} proactive "
        "operational_fact injections across scenario replay"
    )
    # Exit code respects both the FAIL count and the zero-proactive
    # gate — non-zero if either trips.
    assert exit_code == 0, (
        f"run_all.main exit={exit_code}; "
        f"verdicts={payload['verdicts']}, "
        f"proactive_count={payload['proactive_operational_fact_count']}"
    )


def test_counter_detects_positive_control(tmp_path):
    """Regression: the zero-proactive guard must actually detect a
    proactive operational_fact injection when one occurs.

    Without this test, ``count_proactive_operational_fact_injections``
    could silently return 0 due to schema drift (wrong column name,
    wrong JSON field, swallowed exceptions) and the milestone
    acceptance guard would be a tautology.
    """
    db_path = tmp_path / "positive_control.db"
    store = SQLiteStorageProvider(database_url=f"sqlite:///{db_path}")

    from sqlalchemy import text as _text

    container_ref = "positive-control"
    now = datetime.now(timezone.utc)

    # Seed a fake query_audit_log row that represents a proactive
    # operational_fact injection: no trigger_origin, should_inject=1,
    # blocks_json contains a memory_type="operational_fact" entry.
    blocks_json = json.dumps([{
        "result_id": "block-1",
        "memory_type": "operational_fact",
        "block_type": "structured",
        "score": 0.9,
        "memory_object_id": "fact-1",
    }])
    with store._engine.begin() as conn:
        conn.execute(
            _text(
                "INSERT INTO query_audit_log "
                "(id, created_at, source_item_id, source_id, container_ref, "
                " query_text, should_inject, decision_reason, "
                " injected_blocks_json, trigger_origin) "
                "VALUES (:id, :ts, :sid, :sdid, :ref, :q, 1, "
                "        'inject_positive_control', :blocks, NULL)"
            ),
            {
                "id": "aud-positive-control",
                "ts": now,
                "sid": "src-positive-control",
                "sdid": "src-id-pos-ctrl",
                "ref": container_ref,
                "q": "test query",
                "blocks": blocks_json,
            },
        )

    count = count_proactive_operational_fact_injections(store, container_ref)
    assert count == 1, (
        f"positive control failed: guard returned {count} for a container "
        "with exactly 1 proactive operational_fact audit row. "
        "The zero-proactive invariant is not enforceable."
    )


def test_counter_excludes_on_demand_trigger_origin(tmp_path):
    """Regression: the guard must NOT count on-demand injections.

    A row with a non-null trigger_origin (post_tool_failure, retry_threshold,
    session_start_checkpoint, user_explicit) is by definition NOT proactive —
    it was surfaced deterministically by an event. The guard must skip these.
    """
    db_path = tmp_path / "on_demand_neg.db"
    store = SQLiteStorageProvider(database_url=f"sqlite:///{db_path}")

    from sqlalchemy import text as _text

    container_ref = "on-demand-container"
    now = datetime.now(timezone.utc)
    blocks_json = json.dumps([{
        "result_id": "block-2",
        "memory_type": "operational_fact",
        "block_type": "structured",
        "memory_object_id": "fact-2",
    }])
    with store._engine.begin() as conn:
        conn.execute(
            _text(
                "INSERT INTO query_audit_log "
                "(id, created_at, source_item_id, source_id, container_ref, "
                " query_text, should_inject, decision_reason, "
                " injected_blocks_json, trigger_origin) "
                "VALUES (:id, :ts, :sid, :sdid, :ref, :q, 1, "
                "        'inject_on_demand', :blocks, 'post_tool_failure')"
            ),
            {
                "id": "aud-on-demand",
                "ts": now,
                "sid": "src-on-demand",
                "sdid": "src-id-od",
                "ref": container_ref,
                "q": "on-demand query",
                "blocks": blocks_json,
            },
        )

    count = count_proactive_operational_fact_injections(store, container_ref)
    assert count == 0, (
        f"guard mis-counted an on-demand (trigger_origin=post_tool_failure) "
        f"injection as proactive; got {count}"
    )


def test_counter_excludes_other_memory_types(tmp_path):
    """Regression: the guard must only count operational_fact injections,
    not decisions or investigations."""
    db_path = tmp_path / "other_type.db"
    store = SQLiteStorageProvider(database_url=f"sqlite:///{db_path}")

    from sqlalchemy import text as _text

    container_ref = "other-type-container"
    now = datetime.now(timezone.utc)
    blocks_json = json.dumps([{
        "result_id": "block-3",
        "memory_type": "decision",
        "block_type": "structured",
        "memory_object_id": "dec-1",
    }])
    with store._engine.begin() as conn:
        conn.execute(
            _text(
                "INSERT INTO query_audit_log "
                "(id, created_at, source_item_id, source_id, container_ref, "
                " query_text, should_inject, decision_reason, "
                " injected_blocks_json, trigger_origin) "
                "VALUES (:id, :ts, :sid, :sdid, :ref, :q, 1, "
                "        'inject_decision', :blocks, NULL)"
            ),
            {
                "id": "aud-decision",
                "ts": now,
                "sid": "src-decision",
                "sdid": "src-id-dec",
                "ref": container_ref,
                "q": "any query",
                "blocks": blocks_json,
            },
        )

    count = count_proactive_operational_fact_injections(store, container_ref)
    assert count == 0, (
        f"guard mis-counted a proactive DECISION injection as an "
        f"operational_fact; got {count}"
    )

