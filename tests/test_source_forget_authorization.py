"""Container-scoped authorization for raw-turn forgetting (IDOR fix).

Single-item ``forget_source`` used to mutate by primary key with no ownership
check, so any caller holding an id could soft-delete any turn in any container.
This suite locks the fixed policy through the real HTTP surface, the MCP client
scope-threading, and the serve-time loopback guard:

- Container match required when the caller supplies a scope (a
  supplied-but-mismatched scope is ALWAYS denied, even in trusted mode).
- Missing caller scope allowed ONLY in single-user trusted (compatibility)
  mode; denied in strict multi-user mode.
- Untagged (NULL-container) turns deletable only via the missing-scope
  compatibility path.
- Single-item AND bulk paths enforce identical rules.
- Denied attempts write NO forgotten marker (audited distinctly from success).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app
from core.models import SourceItem
from storage.vector_index import VectorIndexConfig
from tests.config_helpers import DEMO_SEMANTIC_PACKAGES

OWNER = "chat:room-a"
OTHER = "chat:room-b"
THREAD = "chat:room-a:thread-1"


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _build_client(db_url: str, *, trusted: bool) -> TestClient:
    app = create_app(
        AppConfig(
            storage_backend="sqlite",
            sqlite_url=db_url,
            default_use_case="demo_agent_memory",
            semantic_packages=DEMO_SEMANTIC_PACKAGES,
            vector_index=VectorIndexConfig(enabled=False),
            single_user_trusted_mode=trusted,
        )
    )
    return TestClient(app)


@pytest.fixture()
def trusted_client(tmp_path: Path) -> TestClient:
    return _build_client(f"sqlite:///{tmp_path / 'trusted.db'}", trusted=True)


@pytest.fixture()
def strict_client(tmp_path: Path) -> TestClient:
    return _build_client(f"sqlite:///{tmp_path / 'strict.db'}", trusted=False)


def _storage(client: TestClient):
    return client.app.state.pallium_service._storage


def _seed(client: TestClient, *, source_id: str, container_ref: str | None, thread_ref: str | None = THREAD) -> str:
    item = SourceItem(
        source_type="chat_message",
        source_id=source_id,
        content_type="text/plain",
        content="Decision: use item event time for reservation ordering to avoid duplicate holds.",
        container_ref=container_ref,
        thread_ref=thread_ref,
        artifact_kind="message",
        role="user",
        visibility="private",
    )
    _storage(client).create_source_item(item)
    return item.id


def _forget(client: TestClient, **body):
    return client.post("/source/forget", json=body)


def _marker(client: TestClient, source_item_id: str) -> tuple:
    item = _storage(client).get_source_item(source_item_id)
    return (item.forgotten, item.forgotten_at, item.forgotten_by, item.forgotten_reason)


# ---------------------------------------------------------------------------
# A. Single-item permission matrix (compatibility / trusted mode default)
# ---------------------------------------------------------------------------

def test_owner_workspace_forgets_own_turn(trusted_client: TestClient) -> None:
    sid = _seed(trusted_client, source_id="own-1", container_ref=OWNER)
    resp = _forget(trusted_client, source_item_id=sid, caller_container_ref=OWNER, reason="mine")
    assert resp.status_code == 200, resp.text
    assert resp.json()["forgotten"] is True
    forgotten, at, by, why = _marker(trusted_client, sid)
    assert forgotten is True and at is not None and why == "mine"


def test_different_workspace_denied(trusted_client: TestClient) -> None:
    """A caller in another workspace cannot forget a foreign turn by id — even
    in compatibility mode (supplied-but-mismatched scope is always denied)."""
    sid = _seed(trusted_client, source_id="foreign-1", container_ref=OWNER)
    resp = _forget(trusted_client, source_item_id=sid, caller_container_ref=OTHER, reason="attack")
    assert resp.status_code == 403, resp.text
    # No forgotten marker written on denial.
    assert _marker(trusted_client, sid) == (False, None, None, None)


def test_no_identity_allowed_in_trusted_mode(trusted_client: TestClient) -> None:
    sid = _seed(trusted_client, source_id="noid-1", container_ref=OWNER)
    resp = _forget(trusted_client, source_item_id=sid, reason="local single-user")
    assert resp.status_code == 200, resp.text
    assert resp.json()["forgotten"] is True
    assert _marker(trusted_client, sid)[0] is True


def test_untagged_null_container_deletable_in_trusted_mode(trusted_client: TestClient) -> None:
    sid = _seed(trusted_client, source_id="untagged-1", container_ref=None)
    # Missing caller scope + trusted mode → allowed (legacy local install path).
    resp = _forget(trusted_client, source_item_id=sid, reason="legacy cleanup")
    assert resp.status_code == 200, resp.text
    assert _marker(trusted_client, sid)[0] is True


def test_untagged_null_container_with_supplied_scope_denied(trusted_client: TestClient) -> None:
    """A supplied scope against a NULL-container target is a mismatch → denied,
    even in trusted mode (trusted relaxes ONLY the missing-scope case)."""
    sid = _seed(trusted_client, source_id="untagged-2", container_ref=None)
    resp = _forget(trusted_client, source_item_id=sid, caller_container_ref=OWNER, reason="x")
    assert resp.status_code == 403, resp.text
    assert _marker(trusted_client, sid) == (False, None, None, None)


# ---------------------------------------------------------------------------
# B. Strict multi-user mode
# ---------------------------------------------------------------------------

def test_no_identity_denied_in_strict_mode(strict_client: TestClient) -> None:
    sid = _seed(strict_client, source_id="strict-noid", container_ref=OWNER)
    resp = _forget(strict_client, source_item_id=sid, reason="no scope")
    assert resp.status_code == 403, resp.text
    assert _marker(strict_client, sid) == (False, None, None, None)


def test_matching_identity_allowed_in_strict_mode(strict_client: TestClient) -> None:
    sid = _seed(strict_client, source_id="strict-match", container_ref=OWNER)
    resp = _forget(strict_client, source_item_id=sid, caller_container_ref=OWNER, reason="mine")
    assert resp.status_code == 200, resp.text
    assert _marker(strict_client, sid)[0] is True


def test_untagged_null_container_denied_in_strict_mode(strict_client: TestClient) -> None:
    sid = _seed(strict_client, source_id="strict-untagged", container_ref=None)
    resp = _forget(strict_client, source_item_id=sid, reason="legacy")
    assert resp.status_code == 403, resp.text
    assert _marker(strict_client, sid) == (False, None, None, None)


# ---------------------------------------------------------------------------
# C. Bulk scope path enforces identical rules (single==bulk parity)
# ---------------------------------------------------------------------------

def test_bulk_matching_scope_allowed(trusted_client: TestClient) -> None:
    _seed(trusted_client, source_id="bulk-a", container_ref=OWNER)
    _seed(trusted_client, source_id="bulk-b", container_ref=OWNER)
    resp = _forget(trusted_client, container_ref=OWNER, caller_container_ref=OWNER, reason="clear")
    assert resp.status_code == 200, resp.text
    assert resp.json()["count"] == 2


def test_bulk_mismatched_scope_denied(trusted_client: TestClient) -> None:
    sid = _seed(trusted_client, source_id="bulk-guarded", container_ref=OWNER)
    resp = _forget(trusted_client, container_ref=OWNER, caller_container_ref=OTHER, reason="attack")
    assert resp.status_code == 403, resp.text
    # Nothing forgotten in the targeted scope.
    assert _marker(trusted_client, sid) == (False, None, None, None)


def test_bulk_no_identity_denied_in_strict_mode(strict_client: TestClient) -> None:
    sid = _seed(strict_client, source_id="bulk-strict", container_ref=OWNER)
    resp = _forget(strict_client, container_ref=OWNER, reason="no scope")
    assert resp.status_code == 403, resp.text
    assert _marker(strict_client, sid) == (False, None, None, None)


@pytest.mark.parametrize("trusted", [True, False])
@pytest.mark.parametrize(
    "caller_scope, expect_status",
    [
        (OWNER, 200),   # matching scope → allowed in both modes
        (OTHER, 403),   # mismatched scope → denied in both modes
    ],
)
def test_single_and_bulk_parity(tmp_path: Path, trusted: bool, caller_scope: str, expect_status: int) -> None:
    """The single-item and bulk paths must reach the SAME authorization
    verdict for a given (mode, supplied-scope) — bulk is not a bypass."""
    single = _build_client(f"sqlite:///{tmp_path / f'single-{trusted}-{caller_scope[-1]}.db'}", trusted=trusted)
    bulk = _build_client(f"sqlite:///{tmp_path / f'bulk-{trusted}-{caller_scope[-1]}.db'}", trusted=trusted)

    sid = _seed(single, source_id="parity-single", container_ref=OWNER)
    _seed(bulk, source_id="parity-bulk", container_ref=OWNER)

    single_resp = _forget(single, source_item_id=sid, caller_container_ref=caller_scope, reason="parity")
    bulk_resp = _forget(bulk, container_ref=OWNER, caller_container_ref=caller_scope, reason="parity")

    assert single_resp.status_code == expect_status
    assert bulk_resp.status_code == single_resp.status_code


# ---------------------------------------------------------------------------
# D. Denial writes nothing; audit distinguishes denied vs success
# ---------------------------------------------------------------------------

def test_denied_then_authorized_audit_distinct(trusted_client: TestClient) -> None:
    sid = _seed(trusted_client, source_id="audit-distinct", container_ref=OWNER)

    denied = _forget(trusted_client, source_item_id=sid, caller_container_ref=OTHER, reason="attack")
    assert denied.status_code == 403
    # Denied: no marker fields whatsoever.
    assert _marker(trusted_client, sid) == (False, None, None, None)

    ok = _forget(trusted_client, source_item_id=sid, caller_container_ref=OWNER, reason="owner delete")
    assert ok.status_code == 200
    forgotten, at, by, why = _marker(trusted_client, sid)
    assert forgotten is True and at is not None and why == "owner delete"


# ---------------------------------------------------------------------------
# E. Lifecycle: idempotency, nonexistent, search/expansion exclusion
# ---------------------------------------------------------------------------

def test_authorized_forget_idempotent(trusted_client: TestClient) -> None:
    sid = _seed(trusted_client, source_id="idem-1", container_ref=OWNER)
    first = _forget(trusted_client, source_item_id=sid, caller_container_ref=OWNER, reason="r")
    assert first.status_code == 200 and first.json()["forgotten"] is True
    second = _forget(trusted_client, source_item_id=sid, caller_container_ref=OWNER, reason="again")
    assert second.status_code == 200
    body = second.json()
    assert body["forgotten"] is False and body["count"] == 0


def test_nonexistent_id_preserved(trusted_client: TestClient) -> None:
    resp = _forget(trusted_client, source_item_id="does-not-exist", caller_container_ref=OWNER, reason="r")
    assert resp.status_code == 404, resp.text


def test_authorized_forget_gone_from_search_and_expansion(trusted_client: TestClient) -> None:
    from core.models import MemoryObject, Relation

    service = trusted_client.app.state.pallium_service
    storage = service._storage
    sid = _seed(trusted_client, source_id="search-gone", container_ref=OWNER)
    memory = MemoryObject(
        type="decision", schema_id="test", schema_version="v1",
        payload={"decision": "x", "decision_evidence_text": "quote"},
        container_ref=OWNER,
    )
    storage.create_memory_object(memory)
    storage.create_relation(Relation(
        from_kind="memory_object", from_id=memory.id,
        relation_type="supported_by", to_kind="source_item", to_id=sid,
    ))
    _payload, items, _mt = service.get_memory_expand(memory.id, container_ref=OWNER)
    assert sid in {i.id for i in items}

    resp = _forget(trusted_client, source_item_id=sid, caller_container_ref=OWNER, reason="gone")
    assert resp.status_code == 200

    _payload, items, _mt = service.get_memory_expand(memory.id, container_ref=OWNER)
    assert sid not in {i.id for i in items}


# ---------------------------------------------------------------------------
# F. MCP client threads the caller scope onto BOTH paths
# ---------------------------------------------------------------------------

def _capture_client(container_ref: str | None):
    from app.mcp.client import PalliumMcpClient
    from app.mcp.context import PalliumContext

    ctx = PalliumContext(base_url="http://test", container_ref=container_ref, actor_ref="user:alice")
    client = PalliumMcpClient(ctx)
    captured: dict = {}

    async def _fake_post(path, payload):
        captured["path"] = path
        captured["payload"] = payload
        return {"ok": True}

    client._post_or_error = _fake_post  # type: ignore[assignment]
    return client, captured


def test_mcp_client_injects_caller_scope_single_item() -> None:
    import asyncio

    client, captured = _capture_client(OWNER)
    asyncio.run(client.forget_source(source_item_id="s-1", reason="r"))
    payload = captured["payload"]
    # Single-item path carries the caller AUTHORIZATION scope ...
    assert payload["caller_container_ref"] == OWNER
    # ... but must NOT widen into a scope forget (no bulk container_ref).
    assert "container_ref" not in payload
    assert payload["source_item_id"] == "s-1"


def test_mcp_client_binds_scope_on_bulk_path() -> None:
    import asyncio

    client, captured = _capture_client(OWNER)
    asyncio.run(client.forget_source(thread_ref=THREAD, reason="r"))
    payload = captured["payload"]
    # Bulk path binds ctx container as the scope AND as the caller scope so the
    # strict-mode authorization check still fires.
    assert payload["container_ref"] == OWNER
    assert payload["caller_container_ref"] == OWNER


def test_mcp_client_omits_caller_scope_when_ctx_has_none() -> None:
    import asyncio

    client, captured = _capture_client(None)
    asyncio.run(client.forget_source(source_item_id="s-2", reason="r"))
    assert "caller_container_ref" not in captured["payload"]


# ---------------------------------------------------------------------------
# G. Serve-time loopback guard
# ---------------------------------------------------------------------------

def test_loopback_host_classification() -> None:
    from app import run

    assert run._is_loopback_host("127.0.0.1") is True
    assert run._is_loopback_host("::1") is True
    assert run._is_loopback_host("localhost") is True
    assert run._is_loopback_host("0.0.0.0") is False
    assert run._is_loopback_host("192.168.1.10") is False


def test_serve_refuses_non_loopback_in_trusted_mode(monkeypatch) -> None:
    from app import config as config_mod
    from app import run

    monkeypatch.setattr(
        config_mod.AppConfig, "from_env",
        classmethod(lambda cls: config_mod.AppConfig(single_user_trusted_mode=True)),
    )

    def _boom(*a, **k):  # pragma: no cover - must not be reached
        raise AssertionError("uvicorn.run must not be called when the guard refuses")

    monkeypatch.setattr(run.uvicorn, "run", _boom)
    assert run.run(["serve", "--host", "0.0.0.0"]) == 2


def test_serve_allows_loopback_in_trusted_mode(monkeypatch) -> None:
    from app import config as config_mod
    from app import run

    monkeypatch.setattr(
        config_mod.AppConfig, "from_env",
        classmethod(lambda cls: config_mod.AppConfig(single_user_trusted_mode=True)),
    )
    called: dict = {}
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://test-guard")
    monkeypatch.setattr(run.uvicorn, "run", lambda *a, **k: called.setdefault("run", True))
    assert run.run(["serve", "--host", "127.0.0.1"]) == 0
    assert called.get("run") is True


def test_serve_allows_non_loopback_in_strict_mode(monkeypatch) -> None:
    from app import config as config_mod
    from app import run

    monkeypatch.setattr(
        config_mod.AppConfig, "from_env",
        classmethod(lambda cls: config_mod.AppConfig(single_user_trusted_mode=False)),
    )
    called: dict = {}
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://test-guard")
    monkeypatch.setattr(run.uvicorn, "run", lambda *a, **k: called.setdefault("run", True))
    assert run.run(["serve", "--host", "0.0.0.0"]) == 0
    assert called.get("run") is True
