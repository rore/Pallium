from __future__ import annotations

import json
import threading
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from api.schemas import HistoricalDeliveryRequest
from app.mcp.server import create_server
from core.models import utc_now
from core.service import PalliumService
from storage.sqlite import SQLiteStorageProvider


class FakeStorage:
    def __init__(self, event: dict[str, Any]) -> None:
        self.event = event
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get_historical_lookup_event_row(self, event_id: str) -> dict[str, Any] | None:
        return self.event if event_id == self.event.get("id") else None

    def finalize_historical_lookup_delivery(self, attempt_id: str, payload: dict[str, Any]) -> str:
        self.calls.append((attempt_id, payload))
        return "final-id"


def service(event: dict[str, Any]) -> PalliumService:
    out = PalliumService.__new__(PalliumService)
    out._storage = FakeStorage(event)
    return out


def attempt(kind: str = "lookup_attempt", exposed: list[dict[str, Any]] | None = None, parent: str | None = None) -> dict[str, Any]:
    return {"id": "a", "event_type": kind, "exposed_json": json.dumps(exposed or [{"source_item_id": "s"}]), "parent_lookup_id": parent}


def test_receipt_missing_and_typed_boundary() -> None:
    with pytest.raises(KeyError):
        service(attempt()).finalize_historical_delivery("missing", items=[])
    with pytest.raises(ValidationError):
        HistoricalDeliveryRequest.model_validate({"items": [{"source_item_id": "", "role": "search_match"}]})


def test_lookup_receipt_rejects_duplicate_and_wrong_role() -> None:
    svc = service(attempt())
    duplicate = [{"source_item_id": "s", "role": "search_match"}] * 2
    with pytest.raises(ValueError, match="unique"):
        svc.finalize_historical_delivery("a", items=duplicate)
    with pytest.raises(ValueError, match="search_match"):
        svc.finalize_historical_delivery("a", items=[{"source_item_id": "s", "role": "neighbor"}])


def test_expansion_receipt_requires_actual_anchor() -> None:
    svc = service(attempt("expansion_attempt", [{"source_item_id": "anchor", "role": "anchor"}], parent="lookup"))
    with pytest.raises(ValueError, match="expansion anchor"):
        svc.finalize_historical_delivery("a", items=[{"source_item_id": "anchor", "role": "neighbor"}])


def test_empty_lookup_and_unicode_ids() -> None:
    svc = service(attempt(exposed=[{"source_item_id": "空"}]))
    assert svc.finalize_historical_delivery("a", items=[]) == "final-id"
    assert svc._storage.calls[-1][1]["exposed_json"] == "[]"


def test_receipt_payload_order_is_canonical() -> None:
    svc = service(attempt(exposed=[{"source_item_id": "a"}, {"source_item_id": "b"}]))
    svc.finalize_historical_delivery("a", items=[{"source_item_id": "b", "role": "search_match"}, {"source_item_id": "a", "role": "search_match"}])
    assert json.loads(svc._storage.calls[-1][1]["exposed_json"]) == [{"source_item_id": "b", "role": "search_match"}, {"source_item_id": "a", "role": "search_match"}]


def test_sqlite_receipt_is_idempotent_and_concurrent(tmp_path) -> None:
    storage = SQLiteStorageProvider(f"sqlite:///{tmp_path / 'receipt.db'}")
    storage.write_historical_lookup_event_row({"id": "attempt", "created_at": utc_now(), "event_type": "lookup_attempt", "session_id": "session", "container_ref": "container", "actor_ref": "actor", "trigger_origin": "agent_pull", "parent_lookup_id": None, "exposed_json": '[{"source_item_id":"s"}]', "visibility": "private", "source_session_ref": None, "query_text": "q", "request_source_item_id": None})
    payload = {"exposed_json": '[{"source_item_id":"s","role":"search_match"}]'}
    assert storage.finalize_historical_lookup_delivery("attempt", payload)
    assert storage.finalize_historical_lookup_delivery("attempt", payload)
    results: list[str] = []
    threads = [threading.Thread(target=lambda: results.append(storage.finalize_historical_lookup_delivery("attempt", payload))) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(set(results)) == 1
    with pytest.raises(RuntimeError):
        storage.finalize_historical_lookup_delivery("attempt", {"exposed_json": "[]"})


def _sqlite_event(storage: SQLiteStorageProvider, *, event_id: str, event_type: str, parent: str | None = None, container: str = "container", session: str = "session", actor: str = "actor") -> None:
    storage.write_historical_lookup_event_row({"id": event_id, "created_at": utc_now(), "event_type": event_type, "session_id": session, "container_ref": container, "actor_ref": actor, "trigger_origin": "agent_pull", "parent_lookup_id": parent, "exposed_json": "[]", "visibility": "private", "source_session_ref": None, "query_text": "q", "request_source_item_id": None})


def test_sqlite_expansion_parent_missing_scope_and_nonfinal(tmp_path) -> None:
    storage = SQLiteStorageProvider(f"sqlite:///{tmp_path / 'parents.db'}")
    _sqlite_event(storage, event_id="exp", event_type="expansion_attempt", parent="missing")
    with pytest.raises(ValueError, match="finalized parent"):
        storage.finalize_historical_lookup_delivery("exp", {"exposed_json": "[]"})
    _sqlite_event(storage, event_id="parent-attempt", event_type="lookup_attempt")
    parent_id = storage.finalize_historical_lookup_delivery("parent-attempt", {"exposed_json": "[]"})
    _sqlite_event(storage, event_id="wrong", event_type="expansion_attempt", parent=parent_id, container="other")
    with pytest.raises(ValueError, match="out of scope"):
        storage.finalize_historical_lookup_delivery("wrong", {"exposed_json": "[]"})


def test_sqlite_conflicting_concurrent_retry_is_captured(tmp_path) -> None:
    storage = SQLiteStorageProvider(f"sqlite:///{tmp_path / 'races.db'}")
    _sqlite_event(storage, event_id="attempt", event_type="lookup_attempt")
    errors: list[RuntimeError] = []

    def run(payload: dict[str, str]) -> None:
        try:
            storage.finalize_historical_lookup_delivery("attempt", payload)
        except RuntimeError as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run, args=({"exposed_json": value},)) for value in ('[{"source_item_id":"a","role":"search_match"}]', "[]")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert any(isinstance(error, RuntimeError) for error in errors)

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "results",
    [[], [{"source_item_id": "only", "excerpt": "x"}]],
)
async def test_mcp_search_receipt_matches_compacted_results(
    results: list[dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("mcp", reason="mcp[cli] not installed")
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
    raw = {
        "results": results,
        "delivery_attempt_id": "attempt",
    }
    receipt = AsyncMock(return_value={"lookup_event_id": "finalized"})
    with (
        patch(
            "app.mcp.client.PalliumMcpClient.search_history",
            new=AsyncMock(return_value=raw),
        ),
        patch(
            "app.mcp.client.PalliumMcpClient.finalize_historical_delivery",
            new=receipt,
        ),
    ):
        content, _ = await create_server().call_tool(
            "pallium_search_history",
            {"query": "x", "container_ref": "c", "visibility": "private"},
        )

    payload = json.loads(content[0].text)
    assert payload["lookup_event_id"] == "finalized"
    assert receipt.await_args.args[0] == "attempt"
    assert receipt.await_args.kwargs["items"] == [
        {"source_item_id": item["source_item_id"], "role": "search_match"}
        for item in payload["results"]
    ]


@pytest.mark.asyncio
async def test_mcp_search_receipt_failure_hides_unrecorded_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("mcp", reason="mcp[cli] not installed")
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
    raw = {
        "results": [{"source_item_id": "s", "excerpt": "x"}],
        "delivery_attempt_id": "attempt",
    }
    with (
        patch(
            "app.mcp.client.PalliumMcpClient.search_history",
            new=AsyncMock(return_value=raw),
        ),
        patch(
            "app.mcp.client.PalliumMcpClient.finalize_historical_delivery",
            new=AsyncMock(return_value={"error": "failed"}),
        ),
    ):
        content, _ = await create_server().call_tool(
            "pallium_search_history",
            {"query": "x", "container_ref": "c", "visibility": "private"},
        )

    assert json.loads(content[0].text) == {"error": "failed"}


@pytest.mark.asyncio
async def test_mcp_expansion_receipt_preserves_rendered_order_and_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("mcp", reason="mcp[cli] not installed")
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
    expansion = {
        "items": [
            {"source_item_id": "n1", "is_anchor": False, "content": "before"},
            {"source_item_id": "a", "is_anchor": True, "content": "anchor"},
        ],
        "delivery_attempt_id": "attempt",
    }
    receipt = AsyncMock(return_value={"lookup_event_id": "finalized"})
    with (
        patch(
            "app.mcp.client.PalliumMcpClient.get_source_context",
            new=AsyncMock(return_value=expansion),
        ),
        patch(
            "app.mcp.client.PalliumMcpClient.finalize_historical_delivery",
            new=receipt,
        ),
    ):
        content, _ = await create_server().call_tool(
            "pallium_expand_source",
            {
                "source_item_id": "a",
                "container_ref": "c",
                "visibility": "private",
            },
        )

    payload = json.loads(content[0].text)
    assert [item["source_item_id"] for item in payload["items"]] == ["n1", "a"]
    assert receipt.await_args.kwargs["items"] == [
        {"source_item_id": "n1", "role": "neighbor"},
        {"source_item_id": "a", "role": "anchor"},
    ]
