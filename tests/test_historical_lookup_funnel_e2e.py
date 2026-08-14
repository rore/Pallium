"""Historical-lookup reuse funnel — end-to-end + visibility (PR-a).

Exercises the full PR-a chain under a VISIBILITY-ENFORCING plugin
(agent_conversation_memory requires visibility context — the demo plugin does
not, which would make the visibility invariants vacuous):

    ingest → search_history (source_only, audit OFF) → persisted "lookup" row
    with the minted id → expand → persisted "expansion" row with
    parent_lookup_id → seed rung labels → loader → non-empty rollup.

Plus the governance invariants: cross-container non-leak and forgotten-source
exclusion from the persisted exposed set.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from core.models import new_id, utc_now
from evals.historical_lookup_measurement import (
    compute_reuse_rollup,
    load_events_from_storage,
)
from sqlalchemy import text
from tests.config_helpers import build_llm_test_config
from tests.stub_providers import TieredMemorySemanticProvider

CONTAINER = "chat:funnel"
THREAD = "chat:funnel:thread-1"
_USER = "Decision: use item event time for reservation ordering to avoid duplicate holds."
_WORK = "We discussed reservation ordering and duplicate holds at length in this thread."


def _db_file(test_db_url: str) -> str:
    prefix = "sqlite:///"
    assert test_db_url.startswith(prefix)
    return test_db_url[len(prefix):]


def _build_client(monkeypatch, test_db_url: str) -> TestClient:
    # agent_conversation_memory is visibility-ENFORCING; audit logging defaults
    # OFF in build_llm_test_config, so the funnel persistence must be
    # audit-independent for these tests to see rows.
    monkeypatch.setattr(
        "app.dependencies.build_llm_provider",
        lambda config, **_: TieredMemorySemanticProvider(),
    )
    return TestClient(create_app(build_llm_test_config(
        default_use_case="agent_conversation_memory", sqlite_url=test_db_url,
    )))


def _ingest(client: TestClient, *, source_id: str, content: str, role: str,
            artifact_kind: str, container_ref: str = CONTAINER,
            thread_ref: str = THREAD, visibility: str = "private") -> str:
    source_type = "chat_message" if role == "user" else "assistant_artifact"
    resp = client.post("/items", json=[{
        "source_type": source_type,
        "source_id": source_id,
        "content_type": "text/plain",
        "content": content,
        "artifact_kind": artifact_kind,
        "role": role,
        "container_ref": container_ref,
        "thread_ref": thread_ref,
        "visibility": visibility,
    }])
    assert resp.status_code == 200, resp.text
    client.app.state.pallium_service.drain_processing_queue(worker_id="funnel-test")
    return resp.json()[0]["source_item_id"]


def _search_history(client: TestClient, *, container_ref: str = CONTAINER,
                    thread_ref: str = THREAD, visibility: str = "private") -> dict:
    resp = client.post("/query", json={
        "text": "reservation ordering duplicate holds",
        "container_ref": container_ref,
        "thread_ref": thread_ref,
        "visibility": visibility,
        "limit": 5,
        "source_only": True,
        "trigger_origin": "agent_pull",
    })
    assert resp.status_code == 200, resp.text
    return resp.json()


def _events(client: TestClient, event_type: str) -> list[dict]:
    storage = client.app.state.pallium_service._storage
    with storage._engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, session_id, container_ref, parent_lookup_id, exposed_json "
                "FROM historical_lookup_reuse_event WHERE event_type = :et"
            ),
            {"et": event_type},
        ).mappings().all()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Full chain
# ---------------------------------------------------------------------------


def test_full_funnel_chain_audit_off(monkeypatch, test_db_url: str) -> None:
    import json
    with _build_client(monkeypatch, test_db_url) as client:
        # Substantive session: a user turn + an assistant-work turn.
        _ingest(client, source_id="u1", content=_USER, role="user", artifact_kind="message")
        _ingest(client, source_id="a1", content=_WORK, role="assistant", artifact_kind="assistant_output")

        # search_history (source_only). Audit is OFF, so a non-null minted id
        # here proves the persistence is audit-independent.
        result = _search_history(client)
        assert result["decision_reason"] == "source_only_search"
        lookup_id = result["lookup_event_id"]
        assert lookup_id is not None

        lookups = _events(client, "lookup")
        assert len(lookups) == 1
        assert lookups[0]["id"] == lookup_id
        assert lookups[0]["session_id"] == THREAD

        source_hits = [r for r in result["results"] if r["result_kind"] == "source_hit"]
        assert source_hits, result
        anchor_id = source_hits[0]["source_item_id"]

        # Expand carrying the parent lookup id.
        resp = client.get(
            f"/source/{anchor_id}/context",
            params={"container_ref": CONTAINER, "parent_lookup_id": lookup_id},
        )
        assert resp.status_code == 200, resp.text

        expansions = _events(client, "expansion")
        assert len(expansions) == 1
        assert expansions[0]["parent_lookup_id"] == lookup_id

        # Seed rung labels for the lookup event (a PR-b judge would do this).
        storage = client.app.state.pallium_service._storage
        storage.write_historical_lookup_label_row({
            "id": new_id(),
            "lookup_event_id": lookup_id,
            "rater_seed": "seed-0",
            "rung": "incorporation",
            "rationale": "test",
            "created_at": utc_now(),
        })

        # Loader → non-empty rollup.
        eligible, events = load_events_from_storage(
            _db_file(test_db_url), container_ref=CONTAINER, eligibility_n=0
        )
        assert THREAD in eligible
        assert any(e["rung"] == "incorporation" for e in events)
        rollup = compute_reuse_rollup(eligible, events, eligibility_n=0, window={})
        assert rollup["rungs"]["incorporation"]["numerator"] == 1
        # exposed set carried real source ids, sanity check json shape.
        assert isinstance(json.loads(lookups[0]["exposed_json"]), list)


# ---------------------------------------------------------------------------
# Governance invariants (visibility-enforcing plugin)
# ---------------------------------------------------------------------------


def test_cross_container_non_leak_in_persisted_event(monkeypatch, test_db_url: str) -> None:
    import json
    with _build_client(monkeypatch, test_db_url) as client:
        # Private turn in container A.
        _ingest(client, source_id="priv-a", content=_WORK, role="user", artifact_kind="message",
                container_ref="chat:room-a", thread_ref="chat:room-a:t1")
        # Search a DIFFERENT container B.
        result = _search_history(client, container_ref="chat:room-b", thread_ref="chat:room-b:t1")
        returned = {r.get("source_id") for r in result["results"]}
        assert "priv-a" not in returned  # not surfaced

        # The persisted lookup event for the B-scoped search must not leak the
        # A-container source id into its exposed set (0 violations).
        lookups = _events(client, "lookup")
        assert len(lookups) == 1
        exposed_ids = {e["source_id"] for e in json.loads(lookups[0]["exposed_json"])}
        assert "priv-a" not in exposed_ids


def test_forgotten_source_excluded_from_exposed(monkeypatch, test_db_url: str) -> None:
    import json
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(client, source_id="keep", content=_WORK, role="user", artifact_kind="message")
        drop_id = _ingest(client, source_id="drop", content=_WORK, role="assistant",
                          artifact_kind="assistant_output")

        # Forget the drop turn.
        resp = client.post("/source/forget", json={"source_item_id": drop_id, "reason": "user request"})
        assert resp.status_code == 200, resp.text

        result = _search_history(client)
        returned = {r.get("source_id") for r in result["results"]}
        assert "drop" not in returned

        # The persisted lookup event must not carry the forgotten source id.
        lookups = _events(client, "lookup")
        assert lookups, "expected a persisted lookup event"
        latest = lookups[-1]
        exposed_ids = {e["source_id"] for e in json.loads(latest["exposed_json"])}
        assert "drop" not in exposed_ids
