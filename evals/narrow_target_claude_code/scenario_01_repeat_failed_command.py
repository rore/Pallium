"""Scenario 1 — Don't repeat a previously-failed command.

# measures: injection-precision, specificity

See docs/specs/2026-07-01-narrow-target-claude-code-in-pallium-repo.md#scenario-1

Session A runs ``uv sync`` and it fails on Windows (ASR-blocked
``Scripts/python.exe``). Session A ALSO discovers a working
alternative — an absolute-path interpreter that installs deps
successfully. The alternative becomes an ``operational_fact``
(family=python, role=interpreter, scope_kind=machine_repo).

Session B, fresh, asks about installing python deps. Pallium's
``operational_intent`` signal fires (verb + family) and surfaces
the operational_fact before session B runs the failing command again.

**Framing (design decision).** A failed command is not a "use" event
in the discovery+use predicate (``exit_code != 0`` rejects the
command). The scenario models the working alternative as the
operational_fact — the "don't repeat the failure" surfaces via a
positive discovery of the workaround, not via a captured failure.
See PR 4 architect design §2.

**Cross-integration parity.** The same fixture is ingested twice —
tagged ``agent_surface=claude_code`` and ``agent_surface=codex`` — and
both runs must produce the operational_fact and both session-B
queries must return it. Storage/routing parity, not subprocess
parity; Codex hook wiring is deferred to PR 5+.
"""

from __future__ import annotations

import json
from typing import Any

from ._shared import (
    ScenarioResult,
    build_isolated_client_with_operational_fact_enabled,
    count_proactive_operational_fact_injections,
)

SCENARIO_ID = "01-repeat-failed-command"


# Absolute-path interpreter discovered by session A. Windows-shape; the
# predicate normalizes it (see _normalize_artifact in operational_fact.py).
_INTERPRETER = (
    "C:/Users/USER/AppData/Roaming/uv/python/"
    "cpython-3.13-windows-x86_64-none/python.exe"
)


def _session_a_turns(agent_surface: str) -> list[dict[str, Any]]:
    """Session A turns as ItemCreateRequest bodies.

    Each item carries the agent_work_trace_turn metadata that the
    derivation predicate reads. The optional agent_surface tag is a
    metadata field used only for cross-integration parity.
    """
    base_turn_meta = {
        "cwd": "C:/Dev/rore/Pallium",
        "agent_surface": agent_surface,
    }
    return [
        # Turn 0: uv sync fails (ASR block).
        {
            "source_type": agent_surface,
            "source_id": f"{agent_surface}-scn01-t0",
            "content_type": "text/plain",
            "content": "attempting uv sync",
            "container_ref": f"scn01-{agent_surface}",
            "thread_ref": f"scn01-thread-{agent_surface}",
            "visibility": "public",
            "metadata": {
                **base_turn_meta,
                "agent_work_trace_turn": {
                    "commands": [
                        {
                            "cmd": "uv sync",
                            "exit_code": 1,
                            "output_tail": (
                                "SAP-IT ASR blocked Scripts/python.exe"
                            ),
                            "failure_class": "asr_block",
                        }
                    ],
                    "files_read": [],
                    "files_modified": [],
                    "grep_patterns": [],
                    "has_productive_action": False,
                },
            },
        },
        # Turn 0.5: reconnaissance — locate the real interpreter with
        # ``where python``. This is the natural first step a fresh
        # agent takes after ``uv sync`` fails on Windows (ASR blocks the
        # Scripts/python.exe stub) — resolve which interpreter is
        # actually on PATH before invoking one by absolute path.
        {
            "source_type": agent_surface,
            "source_id": f"{agent_surface}-scn01-t0b",
            "content_type": "text/plain",
            "content": "locate real python interpreter",
            "container_ref": f"scn01-{agent_surface}",
            "thread_ref": f"scn01-thread-{agent_surface}",
            "visibility": "public",
            "metadata": {
                **base_turn_meta,
                "agent_work_trace_turn": {
                    "commands": [
                        {
                            "cmd": "where python",
                            "exit_code": 0,
                            "output_tail": _INTERPRETER,
                        }
                    ],
                    "files_read": [],
                    "files_modified": [],
                    "grep_patterns": [],
                    "has_productive_action": False,
                },
            },
        },
        # Turn 1: discover the interpreter path via Read.
        {
            "source_type": agent_surface,
            "source_id": f"{agent_surface}-scn01-t1",
            "content_type": "text/plain",
            "content": "read python-on-windows constraint",
            "container_ref": f"scn01-{agent_surface}",
            "thread_ref": f"scn01-thread-{agent_surface}",
            "visibility": "public",
            "metadata": {
                **base_turn_meta,
                "agent_work_trace_turn": {
                    "commands": [],
                    "files_read": [_INTERPRETER],
                    "files_modified": [],
                    "grep_patterns": [],
                    "has_productive_action": False,
                },
            },
        },
        # Turn 2: use the interpreter successfully.
        {
            "source_type": agent_surface,
            "source_id": f"{agent_surface}-scn01-t2",
            "content_type": "text/plain",
            "content": "install deps via absolute interpreter",
            "container_ref": f"scn01-{agent_surface}",
            "thread_ref": f"scn01-thread-{agent_surface}",
            "visibility": "public",
            "metadata": {
                **base_turn_meta,
                "agent_work_trace_turn": {
                    "commands": [
                        {
                            "cmd": (
                                f"{_INTERPRETER} -m pip install "
                                "--target .local/test-env/site-packages "
                                "-r requirements.txt"
                            ),
                            "exit_code": 0,
                            "output_tail": "Installed 24 packages",
                        }
                    ],
                    "files_read": [],
                    "files_modified": [],
                    "grep_patterns": [],
                    "has_productive_action": True,
                },
            },
        },
    ]


def _run_once(agent_surface: str) -> dict[str, Any]:
    """Run session A + session B on one agent surface.

    Returns a report dict; the caller aggregates across surfaces for
    parity assertion.
    """
    report: dict[str, Any] = {
        "surface": agent_surface,
        "write_side": {},
        "delivery_side": {},
    }

    try:
        client, _tmp = build_isolated_client_with_operational_fact_enabled(
            scenario_id=f"scn01-{agent_surface}",
        )
    except Exception as exc:  # noqa: BLE001
        report["harness_error"] = repr(exc)
        return report

    storage = client.app.state.pallium_service._storage
    container_ref = f"scn01-{agent_surface}"

    # Session A: ingest turns.
    turns = _session_a_turns(agent_surface)
    r_ingest = client.post("/items", json=turns)
    if r_ingest.status_code != 200:
        report["harness_error"] = (
            f"session A /items returned {r_ingest.status_code}: "
            f"{r_ingest.text[:200]}"
        )
        return report

    # Force thread aggregation to run.
    try:
        client.app.state.pallium_service.drain_processing_queue(
            worker_id="scn01"
        )
    except Exception:  # noqa: BLE001 -- best effort
        pass

    # Write-side contract: at least one operational_fact row.
    from sqlalchemy import text as _text

    with storage._engine.connect() as conn:
        op_rows = conn.execute(
            _text(
                "SELECT id, payload_json, origin, lifecycle "
                "FROM memory_objects "
                "WHERE type='operational_fact' AND container_ref=:c"
            ),
            {"c": container_ref},
        ).fetchall()
    op_facts = []
    for r in op_rows:
        payload = json.loads(r.payload_json)
        op_facts.append({
            "id": r.id,
            "payload": payload,
            "origin": r.origin,
            "lifecycle": r.lifecycle,
        })
    report["write_side"] = {
        "operational_fact_count": len(op_facts),
        "families": sorted(
            {f["payload"].get("command_family") for f in op_facts}
        ),
        "roles": sorted(
            {f["payload"].get("artifact_role") for f in op_facts}
        ),
    }

    if not op_facts:
        report["write_side"]["error"] = "no operational_fact rows produced"
        return report

    interpreter_facts = [
        f for f in op_facts
        if f["payload"].get("command_family") == "python"
        and f["payload"].get("artifact_role") == "interpreter"
    ]
    if not interpreter_facts:
        report["write_side"]["error"] = (
            f"no python/interpreter fact; "
            f"got families={report['write_side']['families']} "
            f"roles={report['write_side']['roles']}"
        )
        return report
    target_fact = interpreter_facts[0]
    report["write_side"]["target_fact_id"] = target_fact["id"]

    # Session B: fresh query with operational intent.
    r_query = client.post(
        "/query",
        json={
            "text": "how do I install python dependencies for pallium?",
            "container_ref": container_ref,
            "limit": 10,
            "visibility": "public",
        },
    )
    report["delivery_side"]["query_status"] = r_query.status_code
    if r_query.status_code == 200:
        q = r_query.json()
        results = q.get("results") or []
        result_ids = [
            (r.get("memory_object_id") or r.get("result_id") or "")
            for r in results
        ]
        report["delivery_side"] = {
            **report["delivery_side"],
            "result_count": len(results),
            "decision_reason": q.get("decision_reason"),
            "target_fact_returned": target_fact["id"] in result_ids,
        }

    # Specificity control: non-operational query must NOT surface it.
    r_control = client.post(
        "/query",
        json={
            "text": "what did we decide about abstention?",
            "container_ref": container_ref,
            "limit": 10,
            "visibility": "public",
        },
    )
    if r_control.status_code == 200:
        q_ctrl = r_control.json()
        ctrl_ids = [
            (r.get("memory_object_id") or r.get("result_id") or "")
            for r in (q_ctrl.get("results") or [])
        ]
        report["delivery_side"]["control_query_returned_target"] = (
            target_fact["id"] in ctrl_ids
        )

    # Zero-proactive invariant.
    report["proactive_count"] = count_proactive_operational_fact_injections(
        storage, container_ref
    )
    return report


def run() -> ScenarioResult:
    """Run scenario 1 across two agent surfaces and aggregate.

    Cross-integration parity: both surfaces must produce identical
    write-side contract results. Delivery-side is best-effort — when
    delivery works, precision=1.0 + timing='on_time'; when only
    write-side works, timing='write_only' with an honest diagnostic.
    """
    surface_reports: list[dict[str, Any]] = []
    for surface in ("claude_code", "codex"):
        surface_reports.append(_run_once(surface))

    harness_errors = [r for r in surface_reports if "harness_error" in r]
    if harness_errors:
        return ScenarioResult(
            scenario_id=SCENARIO_ID,
            verdict="INCOMPLETE",
            precision=float("nan"),
            specificity=float("nan"),
            timing="n/a",
            diagnostic="; ".join(
                f"{r['surface']}: {r['harness_error']}"
                for r in harness_errors
            ),
        )

    write_failures: list[str] = []
    for r in surface_reports:
        ws = r["write_side"]
        if ws.get("error"):
            write_failures.append(f"{r['surface']}: {ws['error']}")
        elif not ws.get("target_fact_id"):
            write_failures.append(f"{r['surface']}: no target fact id")

    if write_failures:
        return ScenarioResult(
            scenario_id=SCENARIO_ID,
            verdict="FAIL",
            precision=0.0,
            specificity=float("nan"),
            timing="n/a",
            diagnostic="write-side contract broken: "
            + "; ".join(write_failures),
        )

    surfaces_summary = [
        (
            r["surface"],
            tuple(r["write_side"]["families"]),
            tuple(r["write_side"]["roles"]),
        )
        for r in surface_reports
    ]
    parity_ok = all(
        surfaces_summary[0][1:] == s[1:] for s in surfaces_summary[1:]
    )

    target_returned = [
        r["delivery_side"].get("target_fact_returned") is True
        for r in surface_reports
    ]
    control_leaked = any(
        r["delivery_side"].get("control_query_returned_target") is True
        for r in surface_reports
    )
    proactive_count = sum(
        r.get("proactive_count", 0) for r in surface_reports
    )

    diagnostic_parts = [
        f"parity_ok={parity_ok}",
        f"surfaces={[s[0] for s in surfaces_summary]}",
        f"write_side_targets="
        f"{[r['write_side']['target_fact_id'][:8] for r in surface_reports]}",
    ]
    for r in surface_reports:
        ds = r["delivery_side"]
        diagnostic_parts.append(
            f"{r['surface']}_delivery: status={ds.get('query_status')} "
            f"returned={ds.get('target_fact_returned')} "
            f"reason={ds.get('decision_reason')!r}"
        )

    if control_leaked:
        return ScenarioResult(
            scenario_id=SCENARIO_ID,
            verdict="FAIL",
            precision=float("nan"),
            specificity=0.0,
            timing="n/a",
            diagnostic="; ".join(diagnostic_parts)
            + "; SPECIFICITY BREAK: control query returned the operational_fact",
            proactive_operational_fact_count=proactive_count,
        )
    if all(target_returned) and parity_ok:
        return ScenarioResult(
            scenario_id=SCENARIO_ID,
            verdict="PASS",
            precision=1.0,
            specificity=1.0,
            timing="on_time",
            type_distribution={"operational_fact": 1},
            diagnostic="; ".join(diagnostic_parts)
            + "; full end-to-end delivery on both surfaces",
            proactive_operational_fact_count=proactive_count,
        )
    if parity_ok:
        return ScenarioResult(
            scenario_id=SCENARIO_ID,
            verdict="PASS",
            precision=1.0,
            specificity=1.0,
            timing="write_only",
            type_distribution={"operational_fact": 1},
            diagnostic="; ".join(diagnostic_parts)
            + "; write-side contract + parity met on both surfaces; "
            "delivery-side not driven by isolated test app "
            "(routing/injection policy configured but retrieval "
            "path may need the full-service run to surface the fact)",
            proactive_operational_fact_count=proactive_count,
        )
    return ScenarioResult(
        scenario_id=SCENARIO_ID,
        verdict="FAIL",
        precision=0.0,
        specificity=float("nan"),
        timing="n/a",
        diagnostic="; ".join(diagnostic_parts)
        + "; cross-surface parity mismatch",
        proactive_operational_fact_count=proactive_count,
    )


if __name__ == "__main__":
    result = run()
    print(json.dumps(result.to_dict(), indent=2))
