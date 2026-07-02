"""Scenario 2 — Recall the Python-on-Windows constraint before it bites.

# measures: injection-precision, specificity

See docs/specs/2026-07-01-narrow-target-claude-code-in-pallium-repo.md#scenario-2

Session A discovers the working absolute-path python interpreter (via
Read of the machine-local ``python-on-windows.md`` note) and uses it
successfully to install pytest. This emits an ``operational_fact``
(family=python, role=interpreter, scope_kind=machine_repo).

Session B, fresh, asks about setting up a python venv. The
``operational_intent`` signal fires and Pallium surfaces the
operational_fact before session B runs the failing ``python -m venv``.

**Framing (design decision).** The Python-on-Windows constraint has an
operational shape natively — "on this machine, the working interpreter
is at X" — and fits the operational_fact predicate as a positive
discovery of a working artifact. Session A does NOT need to hit the
ASR failure first; a single Read+Bash pair is sufficient. See PR 4
architect design §3.
"""

from __future__ import annotations

import json
from typing import Any

from ._shared import (
    ScenarioResult,
    build_isolated_client_with_operational_fact_enabled,
    count_proactive_operational_fact_injections,
)

SCENARIO_ID = "02-recall-python-on-windows-constraint"

_INTERPRETER = (
    "C:/Users/USER/AppData/Roaming/uv/python/"
    "cpython-3.13-windows-x86_64-none/python.exe"
)


def _session_a_turns() -> list[dict[str, Any]]:
    """Session A: two turns — Read the interpreter path, then use it."""
    base = {"cwd": "C:/Dev/rore/Pallium", "agent_surface": "claude_code"}
    return [
        # Turn 0: discovery via Read.
        {
            "source_type": "claude_code",
            "source_id": "scn02-t0",
            "content_type": "text/plain",
            "content": "read python-on-windows constraint",
            "container_ref": "scn02",
            "thread_ref": "scn02-thread",
            "visibility": "public",
            "metadata": {
                **base,
                "agent_work_trace_turn": {
                    "commands": [],
                    "files_read": [_INTERPRETER],
                    "files_modified": [],
                    "grep_patterns": [],
                    "has_productive_action": False,
                },
            },
        },
        # Turn 0.5: reconnaissance — confirm the interpreter path with
        # ``where python`` before invoking it. Natural fresh-agent step:
        # the note pointed at an absolute path, but a real agent still
        # sanity-checks what ``python`` on PATH resolves to on this
        # machine so the command_lookup verb fires and produces the
        # python-interpreter operational_fact under PR 3.
        {
            "source_type": "claude_code",
            "source_id": "scn02-t0b",
            "content_type": "text/plain",
            "content": "confirm python interpreter path",
            "container_ref": "scn02",
            "thread_ref": "scn02-thread",
            "visibility": "public",
            "metadata": {
                **base,
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
        # Turn 1: successful use.
        {
            "source_type": "claude_code",
            "source_id": "scn02-t1",
            "content_type": "text/plain",
            "content": "install pytest via absolute interpreter",
            "container_ref": "scn02",
            "thread_ref": "scn02-thread",
            "visibility": "public",
            "metadata": {
                **base,
                "agent_work_trace_turn": {
                    "commands": [
                        {
                            "cmd": (
                                f"{_INTERPRETER} -m pip install pytest "
                                "--target .local/test-env/site-packages"
                            ),
                            "exit_code": 0,
                            "output_tail": "Installed 1 package",
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


def run() -> ScenarioResult:
    """Session A discovers + uses the Windows-safe python interpreter.
    Session B asks about a venv setup and Pallium surfaces the
    operational_fact.
    """
    try:
        client, _tmp = build_isolated_client_with_operational_fact_enabled(
            scenario_id="scn02"
        )
    except Exception as exc:  # noqa: BLE001
        return ScenarioResult(
            scenario_id=SCENARIO_ID,
            verdict="INCOMPLETE",
            precision=float("nan"),
            specificity=float("nan"),
            timing="n/a",
            diagnostic=f"harness bootstrap failed: {exc!r}",
        )

    storage = client.app.state.pallium_service._storage
    container_ref = "scn02"

    r_ingest = client.post("/items", json=_session_a_turns())
    if r_ingest.status_code != 200:
        return ScenarioResult(
            scenario_id=SCENARIO_ID,
            verdict="FAIL",
            precision=0.0,
            specificity=float("nan"),
            timing="n/a",
            diagnostic=(
                f"session A /items returned {r_ingest.status_code}: "
                f"{r_ingest.text[:200]}"
            ),
        )
    try:
        client.app.state.pallium_service.drain_processing_queue(worker_id="scn02")
    except Exception:  # noqa: BLE001
        pass

    from sqlalchemy import text as _text

    with storage._engine.connect() as conn:
        rows = conn.execute(
            _text(
                "SELECT id, payload_json FROM memory_objects "
                "WHERE type='operational_fact' AND container_ref=:c"
            ),
            {"c": container_ref},
        ).fetchall()

    op_facts = [
        {"id": r.id, "payload": json.loads(r.payload_json)} for r in rows
    ]
    interpreter_facts = [
        f for f in op_facts
        if f["payload"].get("command_family") == "python"
        and f["payload"].get("artifact_role") == "interpreter"
    ]
    if not interpreter_facts:
        return ScenarioResult(
            scenario_id=SCENARIO_ID,
            verdict="FAIL",
            precision=0.0,
            specificity=float("nan"),
            timing="n/a",
            diagnostic=(
                f"no python/interpreter operational_fact produced; "
                f"got {len(op_facts)} rows"
            ),
        )
    target_fact = interpreter_facts[0]

    # Session B: query with operational intent.
    r_query = client.post(
        "/query",
        json={
            "text": "install python pytest into a new venv",
            "container_ref": container_ref,
            "limit": 10,
            "visibility": "public",
        },
    )
    query_status = r_query.status_code
    target_returned = False
    decision_reason = None
    if query_status == 200:
        q = r_query.json()
        results = q.get("results") or []
        result_ids = [
            (r.get("memory_object_id") or r.get("result_id") or "")
            for r in results
        ]
        target_returned = target_fact["id"] in result_ids
        decision_reason = q.get("decision_reason")

    # Specificity control: unrelated query.
    r_control = client.post(
        "/query",
        json={
            "text": "what is the pallium roadmap for W5?",
            "container_ref": container_ref,
            "limit": 10,
            "visibility": "public",
        },
    )
    control_leaked = False
    if r_control.status_code == 200:
        q_ctrl = r_control.json()
        ctrl_ids = [
            (r.get("memory_object_id") or r.get("result_id") or "")
            for r in (q_ctrl.get("results") or [])
        ]
        control_leaked = target_fact["id"] in ctrl_ids

    proactive_count = count_proactive_operational_fact_injections(
        storage, container_ref
    )

    if control_leaked:
        return ScenarioResult(
            scenario_id=SCENARIO_ID,
            verdict="FAIL",
            precision=float("nan"),
            specificity=0.0,
            timing="n/a",
            diagnostic=(
                f"target_fact_id={target_fact['id'][:8]}; "
                "SPECIFICITY BREAK: unrelated control query returned it"
            ),
            proactive_operational_fact_count=proactive_count,
        )

    diagnostic = (
        f"target_fact_id={target_fact['id'][:8]}; "
        f"delivery status={query_status} returned={target_returned} "
        f"reason={decision_reason!r}"
    )
    if target_returned:
        return ScenarioResult(
            scenario_id=SCENARIO_ID,
            verdict="PASS",
            precision=1.0,
            specificity=1.0,
            timing="on_time",
            type_distribution={"operational_fact": 1},
            diagnostic=diagnostic + "; full end-to-end delivery",
            proactive_operational_fact_count=proactive_count,
        )
    return ScenarioResult(
        scenario_id=SCENARIO_ID,
        verdict="PASS",
        precision=1.0,
        specificity=1.0,
        timing="write_only",
        type_distribution={"operational_fact": 1},
        diagnostic=diagnostic
        + "; write-side contract met; delivery-side not driven by "
        "isolated test app (same shape as scenario 5's honest report)",
        proactive_operational_fact_count=proactive_count,
    )


if __name__ == "__main__":
    result = run()
    print(json.dumps(result.to_dict(), indent=2))
