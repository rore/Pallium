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

# Drives the full ingest→search→expand→loader pipeline via TestClient +
# drain_processing_queue. Fast (~3s) — stays in the default CI gate (NOT
# slow-marked): this is core historical-lookup correctness, not a benchmark.

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
        priv_internal = _ingest(client, source_id="priv-a", content=_WORK, role="user",
                                artifact_kind="message",
                                container_ref="chat:room-a", thread_ref="chat:room-a:t1")
        # Search a DIFFERENT container B.
        result = _search_history(client, container_ref="chat:room-b", thread_ref="chat:room-b:t1")
        returned = {r.get("source_id") for r in result["results"]}
        assert "priv-a" not in returned  # not surfaced

        # The persisted lookup event for the B-scoped search must not leak the
        # A-container source item id into its exposed set (0 violations).
        lookups = _events(client, "lookup")
        assert len(lookups) == 1
        exposed_ids = {e["source_item_id"] for e in json.loads(lookups[0]["exposed_json"])}
        assert priv_internal not in exposed_ids


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

        # The persisted lookup event must not carry the forgotten source item id.
        lookups = _events(client, "lookup")
        assert lookups, "expected a persisted lookup event"
        latest = lookups[-1]
        exposed_ids = {e["source_item_id"] for e in json.loads(latest["exposed_json"])}
        assert drop_id not in exposed_ids


# ---------------------------------------------------------------------------
# Gap 1: chain depth > 2 (persistence-only)
# ---------------------------------------------------------------------------


def test_chain_depth_greater_than_two_persistence_only(monkeypatch, test_db_url: str) -> None:
    """A depth>2 reuse chain persists — PERSISTENCE-ONLY.

    The API only ever echoes the INPUT parent_lookup_id back
    (api/routes.py:726 → core/service.py:1609); the expansion row's own
    minted id (core/service.py:1595) is NEVER surfaced over HTTP. So to
    build a genuine depth>2 chain the SECOND expand must be fed the FIRST
    expansion ROW's id read directly from storage — not any value the
    route returns (feeding the echoed id back would just re-link the same
    lookup, staying depth-2).

    This guards only that the write ACCEPTS a chained id and persists it:
    parent_lookup_id is an unvalidated stored string (core/service.py:1602)
    with NO chain-walking consumer in the loader (the rollup keys on
    lookup_event_id, never on the parent chain). It asserts nothing about
    chain semantics, because none exist.
    """
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(client, source_id="u1", content=_USER, role="user", artifact_kind="message")
        _ingest(client, source_id="a1", content=_WORK, role="assistant", artifact_kind="assistant_output")

        result = _search_history(client)
        lookup_id = result["lookup_event_id"]
        assert lookup_id is not None
        source_hits = [r for r in result["results"] if r["result_kind"] == "source_hit"]
        assert source_hits, result
        anchor_id = source_hits[0]["source_item_id"]

        # Expand #1 — parent is the lookup event (depth 2).
        resp1 = client.get(
            f"/source/{anchor_id}/context",
            params={"container_ref": CONTAINER, "parent_lookup_id": lookup_id},
        )
        assert resp1.status_code == 200, resp1.text

        # Read the first expansion ROW's own minted id from storage — the
        # only way to obtain it (the route never returns it).
        expansions = _events(client, "expansion")
        assert len(expansions) == 1
        first_expansion_row_id = expansions[0]["id"]
        assert expansions[0]["parent_lookup_id"] == lookup_id
        assert first_expansion_row_id != lookup_id

        # Expand #2 — parent is the FIRST EXPANSION ROW's id (depth 3).
        resp2 = client.get(
            f"/source/{anchor_id}/context",
            params={"container_ref": CONTAINER, "parent_lookup_id": first_expansion_row_id},
        )
        assert resp2.status_code == 200, resp2.text
        # The route echoes the INPUT id, not the new row's id (regression
        # guard for the correctness point above).
        assert resp2.json()["parent_lookup_id"] == first_expansion_row_id

        # A second expansion row persists, carrying the chained parent id.
        expansions = _events(client, "expansion")
        assert len(expansions) == 2
        chained = [e for e in expansions if e["parent_lookup_id"] == first_expansion_row_id]
        assert len(chained) == 1
        assert chained[0]["id"] != first_expansion_row_id


# ---------------------------------------------------------------------------
# Gap 2: /status.historical_lookup_funnel.events_recorded increments
# ---------------------------------------------------------------------------


def _events_recorded(client: TestClient) -> int:
    resp = client.get("/status")
    assert resp.status_code == 200, resp.text
    return resp.json()["historical_lookup_funnel"]["events_recorded"] or 0


def test_status_events_recorded_increments(monkeypatch, test_db_url: str) -> None:
    """GET /status.events_recorded reflects each persisted funnel event.

    events_recorded is a global COUNT(*) over the reuse-event table
    (app/main.py:419-423), so the increment across a single ingest→search
    →expand chain is exactly the number of persisted events: 1 lookup +
    1 expansion = 2.
    """
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(client, source_id="u1", content=_USER, role="user", artifact_kind="message")
        _ingest(client, source_id="a1", content=_WORK, role="assistant", artifact_kind="assistant_output")

        before = _events_recorded(client)

        result = _search_history(client)  # persists 1 "lookup"
        lookup_id = result["lookup_event_id"]
        assert lookup_id is not None
        source_hits = [r for r in result["results"] if r["result_kind"] == "source_hit"]
        assert source_hits, result
        anchor_id = source_hits[0]["source_item_id"]

        resp = client.get(  # persists 1 "expansion"
            f"/source/{anchor_id}/context",
            params={"container_ref": CONTAINER, "parent_lookup_id": lookup_id},
        )
        assert resp.status_code == 200, resp.text

        after = _events_recorded(client)
        assert after - before == 2, (before, after)


# ---------------------------------------------------------------------------
# Gap 3: exposed set reflects post-redaction results
# ---------------------------------------------------------------------------


def test_exposed_set_reflects_post_redaction_results(monkeypatch, test_db_url: str) -> None:
    """The persisted exposed set is derived from the POST-redaction results.

    The lookup event's exposed set is built from ``result.results`` AFTER
    ``_redact_query_result`` runs (core/service.py:703-726). We prove two
    things:

    1. Redaction is live on the surface the exposed set is derived from:
       an ingested secret in the content is redacted out of the returned
       source-hit excerpt (the raw secret never appears; a ``[REDACTED]``
       marker does).
    2. The exposed source_item_ids persisted in the lookup row are exactly
       the ids of the post-redaction, visibility-filtered result surface —
       no leaked or extra id (exposed ⊆ visible, and here exposed == the
       returned source-hit id set).

    LIMITATION: exposed_json stores ids/raw_rank/score only, never content
    (core/service.py:718-726). So the content-level redaction itself cannot
    manifest as a difference in the stored exposed set — redaction mutates
    excerpt/payload text but never drops a result or changes its id. The
    redaction signal is therefore asserted on the returned surface (1); the
    exposed set is asserted to reflect that same post-redaction result set
    by id (2).
    """
    secret = "hunter2SuperSecretValue1234567890"  # noqa: S105 - synthetic test fixture, not a real credential
    content = (
        f"Deploy note: password={secret} for the reservation ordering "
        "duplicate holds service."
    )
    with _build_client(monkeypatch, test_db_url) as client:
        sid = _ingest(client, source_id="sec-1", content=content, role="user",
                      artifact_kind="message")

        result = _search_history(client)
        source_hits = [r for r in result["results"] if r["result_kind"] == "source_hit"]
        assert source_hits, result

        # (1) The secret-bearing hit's excerpt is redacted on the surface.
        hit = next((h for h in source_hits if h["source_item_id"] == sid), None)
        assert hit is not None, source_hits
        assert hit["excerpt"] is not None
        assert secret not in hit["excerpt"]
        assert "[REDACTED]" in hit["excerpt"]

        # (2) The persisted exposed id set == the post-redaction returned
        # source-hit id set (no leaked/extra id; exposed ⊆ visible).
        import json
        lookups = _events(client, "lookup")
        assert len(lookups) == 1
        exposed_ids = {e["source_item_id"] for e in json.loads(lookups[0]["exposed_json"])}
        returned_ids = {h["source_item_id"] for h in source_hits}
        assert exposed_ids == returned_ids
        assert sid in exposed_ids


# ---------------------------------------------------------------------------
# Active-session attribution (fix-lookup-and-expansion-active-attribution)
# ---------------------------------------------------------------------------

_SESSION_A = "chat:funnel:A"
_SESSION_B = "chat:funnel:B"


def _events_attr(client: TestClient, event_type: str) -> list[dict]:
    """Like _events but also reads the attribution columns."""
    storage = client.app.state.pallium_service._storage
    with storage._engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, session_id, source_session_ref, actor_ref, "
                "parent_lookup_id FROM historical_lookup_reuse_event "
                "WHERE event_type = :et"
            ),
            {"et": event_type},
        ).mappings().all()
    return [dict(r) for r in rows]


def test_expansion_attributed_to_requesting_session_not_anchor(monkeypatch, test_db_url: str) -> None:
    """Source ingested in session A, searched + expanded from session B: the
    expansion event records B as the active session and A only as
    source_session_ref — never A as the active session (the mis-attribution
    this fixes). Completion criteria 1 + 2."""
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(client, source_id="u1", content=_USER, role="user",
                artifact_kind="message", thread_ref=_SESSION_A)
        _ingest(client, source_id="a1", content=_WORK, role="assistant",
                artifact_kind="assistant_output", thread_ref=_SESSION_A)

        # Search from session B (same container, different session).
        result = _search_history(client, thread_ref=_SESSION_B)
        lookup_id = result["lookup_event_id"]
        assert lookup_id is not None
        source_hits = [r for r in result["results"] if r["result_kind"] == "source_hit"]
        assert source_hits, result
        anchor_id = source_hits[0]["source_item_id"]

        lk = _events_attr(client, "lookup")
        assert len(lk) == 1
        assert lk[0]["session_id"] == _SESSION_B  # active requesting session
        assert lk[0]["source_session_ref"] is None  # a lookup has no single source session

        # Expand from session B, passing the active session explicitly.
        resp = client.get(
            f"/source/{anchor_id}/context",
            params={
                "container_ref": CONTAINER,
                "parent_lookup_id": lookup_id,
                "active_session_ref": _SESSION_B,
            },
        )
        assert resp.status_code == 200, resp.text

        ex = _events_attr(client, "expansion")
        assert len(ex) == 1
        assert ex[0]["session_id"] == _SESSION_B  # requester, NOT the anchor's session A
        assert ex[0]["source_session_ref"] == _SESSION_A  # anchor's session, recorded separately
        assert ex[0]["parent_lookup_id"] == lookup_id


def test_expansion_without_active_identity_is_unattributed_not_anchor(monkeypatch, test_db_url: str) -> None:
    """When the caller supplies no active session, the expansion event is
    unattributed (session_id NULL) — it must NOT fall back to the anchor's or
    the parent lookup's session. This is the exact bug being fixed. The
    parent_lookup_id belongs to session A; the event must still be NULL, never A."""
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(client, source_id="u1", content=_USER, role="user",
                artifact_kind="message", thread_ref=_SESSION_A)
        _ingest(client, source_id="a1", content=_WORK, role="assistant",
                artifact_kind="assistant_output", thread_ref=_SESSION_A)

        result = _search_history(client, thread_ref=_SESSION_A)
        lookup_id = result["lookup_event_id"]
        source_hits = [r for r in result["results"] if r["result_kind"] == "source_hit"]
        assert source_hits, result
        anchor_id = source_hits[0]["source_item_id"]

        # Expand with NO active_session_ref (route default None).
        resp = client.get(
            f"/source/{anchor_id}/context",
            params={"container_ref": CONTAINER, "parent_lookup_id": lookup_id},
        )
        assert resp.status_code == 200, resp.text

        ex = _events_attr(client, "expansion")
        assert len(ex) == 1
        assert ex[0]["session_id"] is None  # unattributed — NOT the anchor's session A
        assert ex[0]["source_session_ref"] == _SESSION_A


def test_expansion_write_failure_does_not_fail_the_request(monkeypatch, test_db_url: str) -> None:
    """Telemetry stays best-effort: a raising event write must not fail the
    expansion. Completion criterion 5."""
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(client, source_id="u1", content=_USER, role="user",
                artifact_kind="message", thread_ref=_SESSION_A)
        _ingest(client, source_id="a1", content=_WORK, role="assistant",
                artifact_kind="assistant_output", thread_ref=_SESSION_A)
        result = _search_history(client, thread_ref=_SESSION_A)
        source_hits = [r for r in result["results"] if r["result_kind"] == "source_hit"]
        assert source_hits, result
        anchor_id = source_hits[0]["source_item_id"]

        storage = client.app.state.pallium_service._storage

        def _boom(_row):
            raise RuntimeError("telemetry down")

        monkeypatch.setattr(storage, "write_historical_lookup_event_row", _boom)
        resp = client.get(f"/source/{anchor_id}/context", params={"container_ref": CONTAINER})
        assert resp.status_code == 200, resp.text  # expansion still returns


def test_concurrent_expansions_get_distinct_active_sessions(monkeypatch, test_db_url: str) -> None:
    """Two sessions expanding the same anchor concurrently each get an event
    attributed to their own active session — no cross-call/global contamination.
    Completion criterion 3 (concurrency)."""
    import threading

    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(client, source_id="u1", content=_USER, role="user",
                artifact_kind="message", thread_ref=_SESSION_A)
        _ingest(client, source_id="a1", content=_WORK, role="assistant",
                artifact_kind="assistant_output", thread_ref=_SESSION_A)
        result = _search_history(client, thread_ref=_SESSION_A)
        source_hits = [r for r in result["results"] if r["result_kind"] == "source_hit"]
        assert source_hits, result
        anchor_id = source_hits[0]["source_item_id"]

        service = client.app.state.pallium_service
        sessions = ["sess:one", "sess:two"]

        def _expand(active: str) -> None:
            service.get_source_context(anchor_id, container_ref=CONTAINER, active_session_ref=active)

        threads = [threading.Thread(target=_expand, args=(s,)) for s in sessions]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        ex = _events_attr(client, "expansion")
        got = sorted(e["session_id"] for e in ex)
        assert got == sorted(sessions)  # exactly two, each its own active session


# ---------------------------------------------------------------------------
# Redacted query text + always-on eval population (continuous-eval-lookup-population)
# ---------------------------------------------------------------------------


def test_lookup_query_text_redacted_and_feeds_eval_with_audit_off(monkeypatch, test_db_url: str) -> None:
    """A source_only search persists a REDACTED query phrase on the always-on
    funnel event, and the RAW/DERIVED/HYBRID evaluator finds it even though
    query_audit_log is OFF (the default in build_llm_test_config)."""
    from evals.raw_derived_hybrid.runner import count_lookup_population, load_query_rows

    secret = "hunter2SuperSecretValue1234567890"  # noqa: S105 - synthetic fixture
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(client, source_id="u1", content=_USER, role="user", artifact_kind="message")
        resp = client.post("/query", json={
            "text": f"reservation ordering password={secret}",
            "container_ref": CONTAINER, "thread_ref": THREAD, "visibility": "private",
            "limit": 5, "source_only": True, "trigger_origin": "agent_pull",
        })
        assert resp.status_code == 200, resp.text

        storage = client.app.state.pallium_service._storage
        with storage._engine.connect() as conn:
            row = conn.execute(text(
                "SELECT query_text, trigger_origin FROM historical_lookup_reuse_event "
                "WHERE event_type = 'lookup'"
            )).mappings().one()
        # Redacted, not raw — the secret never lands on the always-on event.
        assert secret not in (row["query_text"] or "")
        assert "[REDACTED]" in (row["query_text"] or "")
        assert row["trigger_origin"] == "agent_pull"  # in the eval's default origin filter

        # Audit is OFF, yet the evaluator's population loader finds the lookup.
        db = _db_file(test_db_url)
        origins = ("agent_pull", "mcp_pull")
        rows = load_query_rows(db, container_ref=CONTAINER, thread_ref=None, actor_ref=None,
                               trigger_origins=origins)
        assert len(rows) >= 1
        assert all(secret not in (r.query_text or "") for r in rows)
        pop = count_lookup_population(db, container_ref=CONTAINER, thread_ref=None, actor_ref=None,
                                     trigger_origins=origins)
        assert pop["with_query_text"] >= 1
