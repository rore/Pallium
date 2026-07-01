"""Scenario — Zero operational_facts + operational-intent query must not inject.

# measures: specificity

Strengthened negative case (per W4 PR 4 architect design §6).

With an empty operational_fact table, a session-B query that DOES fire
the ``operational_intent`` signal must:

1. Return zero operational_fact injections (specificity guard).
2. Log zero ``injection_mode='proactive'`` audit rows for operational_fact.
3. Confirm the operational_intent signal actually fired — otherwise the
   test trivially passes because the query text is ambiguous.

Defends against a class of trivial-pass bugs where the routing gate
happens to drop everything for reasons unrelated to the invariant.
"""

from __future__ import annotations

import json

from ._shared import (
    ScenarioResult,
    build_isolated_client_with_operational_fact_enabled,
    count_proactive_operational_fact_injections,
)

SCENARIO_ID = "negative-no-operational-fact"


def run() -> ScenarioResult:
    try:
        client, _tmp = build_isolated_client_with_operational_fact_enabled(
            scenario_id="scn-neg"
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
    container_ref = "scn-neg"

    # Ingest a single non-operational item so the container exists in
    # the audit path but no operational_facts are derived.
    r_ingest = client.post("/items", json=[{
        "source_type": "claude_code",
        "source_id": "scn-neg-t0",
        "content_type": "text/plain",
        "content": "unrelated turn",
        "container_ref": container_ref,
        "thread_ref": "scn-neg-thread",
        "visibility": "public",
        "metadata": {},
    }])
    if r_ingest.status_code != 200:
        return ScenarioResult(
            scenario_id=SCENARIO_ID,
            verdict="INCOMPLETE",
            precision=float("nan"),
            specificity=float("nan"),
            timing="n/a",
            diagnostic=(
                f"ingest failed: {r_ingest.status_code} {r_ingest.text[:200]}"
            ),
        )

    # Verify empty operational_fact table for this container.
    from sqlalchemy import text as _text

    with storage._engine.connect() as conn:
        count = conn.execute(
            _text(
                "SELECT COUNT(*) FROM memory_objects "
                "WHERE type='operational_fact' AND container_ref=:c"
            ),
            {"c": container_ref},
        ).scalar()
    if count and count > 0:
        return ScenarioResult(
            scenario_id=SCENARIO_ID,
            verdict="FAIL",
            precision=float("nan"),
            specificity=0.0,
            timing="n/a",
            diagnostic=(
                f"precondition broken: {count} operational_facts exist "
                "in an empty container"
            ),
        )

    # Confirm the operational_intent signal DOES fire on the query text.
    # We call the signal-derivation function directly rather than dig
    # through /query/debug's trace shape — the signal is a pure function
    # of query_tokens, so this is a valid direct assertion.
    from semantic.agent_conversation_memory_routing_signals import (
        _derive_operational_intent,
    )

    query_text = "how do I install python dependencies for pallium?"
    signal_fired, _derivation = _derive_operational_intent(
        tuple(query_text.split())
    )
    if not signal_fired:
        # Trivial-pass guard: if the signal didn't fire, the specificity
        # assertion is vacuous.
        return ScenarioResult(
            scenario_id=SCENARIO_ID,
            verdict="INCOMPLETE",
            precision=float("nan"),
            specificity=float("nan"),
            timing="n/a",
            diagnostic=(
                "operational_intent signal did NOT fire on the query text; "
                "specificity assertion would be vacuous"
            ),
        )

    # Real /query — assert zero operational_fact injections.
    r_query = client.post(
        "/query",
        json={
            "text": query_text,
            "container_ref": container_ref,
            "limit": 10,
            "visibility": "public",
        },
    )
    query_status = r_query.status_code
    result_types: list[str] = []
    if query_status == 200:
        q = r_query.json()
        for r in q.get("results") or []:
            result_types.append(r.get("type") or "")
    op_fact_injections = sum(1 for t in result_types if t == "operational_fact")

    proactive_count = count_proactive_operational_fact_injections(
        storage, container_ref
    )

    if op_fact_injections > 0:
        return ScenarioResult(
            scenario_id=SCENARIO_ID,
            verdict="FAIL",
            precision=float("nan"),
            specificity=0.0,
            timing="n/a",
            diagnostic=(
                f"SPECIFICITY BREAK: {op_fact_injections} operational_fact "
                "injections on a container with zero operational_fact rows"
            ),
            proactive_operational_fact_count=proactive_count,
        )
    if proactive_count > 0:
        return ScenarioResult(
            scenario_id=SCENARIO_ID,
            verdict="FAIL",
            precision=float("nan"),
            specificity=0.0,
            timing="n/a",
            diagnostic=(
                f"ZERO-PROACTIVE INVARIANT BREAK: {proactive_count} "
                "proactive operational_fact audit rows"
            ),
            proactive_operational_fact_count=proactive_count,
        )

    return ScenarioResult(
        scenario_id=SCENARIO_ID,
        verdict="PASS",
        precision=float("nan"),
        specificity=1.0,
        timing="n/a",
        diagnostic=(
            "operational_intent signal fired; zero operational_fact "
            "rows; zero injections; zero proactive audit rows"
        ),
        proactive_operational_fact_count=0,
    )


if __name__ == "__main__":
    result = run()
    print(json.dumps(result.to_dict(), indent=2))
