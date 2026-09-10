from __future__ import annotations

import argparse
import json
import tempfile
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from app.config import AppConfig, SemanticPackageConfig
from app.main import create_app
from storage.vector_index import VectorIndexConfig


REPOSITORY_SCOPE = "git:github.com/rore/pallium"
FEATURE = {
    "scope_ref": f"roadmap:v1:{REPOSITORY_SCOPE}#roadmap",
    "local_ref": "feature:relay-session-work-associations",
}
WORK_RECORD = {
    "scope_ref": f"roadmap:v1:{REPOSITORY_SCOPE}#roadmap",
    "local_ref": "agent-workflow:relay-session-work-associations",
}
SOURCE_CONTAINER = "git:demo/source-worktree"
TARGET_CONTAINER = "git:demo/reviewer-worktree"
CLOSED_CONTAINER = "git:demo/closed-worktree"


def _config(database: Path) -> AppConfig:
    return AppConfig(
        storage_backend="sqlite",
        sqlite_url=f"sqlite:///{database}",
        default_use_case="demo_agent_memory",
        semantic_packages={
            "demo_agent_memory": SemanticPackageConfig(
                name="demo_agent_memory",
                implementation="demo_agent_memory",
                enabled=True,
            )
        },
        vector_index=VectorIndexConfig(enabled=False),
    )


def _request(client: TestClient, method: str, path: str, **kwargs: Any) -> dict:
    response = client.request(method, path, **kwargs)
    if response.status_code != 200:
        raise RuntimeError(f"{method} {path}: {response.status_code} {response.text}")
    return response.json()


def _register(
    client: TestClient,
    *,
    session_ref: str,
    container_ref: str,
    branch: str,
    alias: str,
) -> dict:
    turn = _request(
        client,
        "POST",
        "/relay/turn",
        json={
            "runtime": "opencode",
            "session_ref": session_ref,
            "container_ref": container_ref,
            "structural_work_refs": [
                {
                    "scope_ref": REPOSITORY_SCOPE,
                    "local_ref": f"git-branch:{branch}",
                },
                WORK_RECORD,
            ],
        },
    )
    _request(
        client,
        "POST",
        "/relay/sessions/name",
        json={
            "runtime": "opencode",
            "session_ref": session_ref,
            "container_ref": container_ref,
            "alias": alias,
        },
    )
    return turn["session"]


def run_mcp_journey(client: TestClient, *, target_endpoint: str) -> dict[str, Any]:
    """Exercise the real MCP wrappers against this isolated ASGI app."""
    import asyncio
    import os
    from unittest.mock import patch
    import httpx
    from app.mcp.client import PalliumMcpClient
    from app.mcp.server import create_server

    async def post(self, path, payload, **_kwargs):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client.app), base_url="http://demo") as http:
            response = await http.post(path, json=payload)
            response.raise_for_status()
            return response.json()

    async def get(self, path, params):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client.app), base_url="http://demo") as http:
            response = await http.get(path, params=params)
            response.raise_for_status()
            return response.json()

    async def call(server, name, arguments):
        content, _ = await server.call_tool(name, arguments)
        return json.loads(content[0].text)

    def require(result: Any, operation: str) -> dict[str, Any]:
        if not isinstance(result, dict) or result.get("error"):
            raise RuntimeError(f"MCP {operation} failed: {result}")
        return result

    async def journey():
        keys = ("PALLIUM_BASE_URL", "PALLIUM_AGENT_REF", "PALLIUM_THREAD_REF", "PALLIUM_CONTAINER_REF")
        original = {key: os.environ.get(key) for key in keys}
        os.environ.update(PALLIUM_BASE_URL="http://demo", PALLIUM_AGENT_REF="opencode", PALLIUM_THREAD_REF="relaydev", PALLIUM_CONTAINER_REF=SOURCE_CONTAINER)
        with patch.object(PalliumMcpClient, "_post", new=post), patch.object(PalliumMcpClient, "_post_or_error", new=post), patch.object(PalliumMcpClient, "_get_or_error", new=get):
            try:
                server = create_server()
                attached = require(await call(server, "pallium_relay_attach_work_ref", {**FEATURE, "container_ref": SOURCE_CONTAINER}), "attach")
                feature_key = attached["attached"]["work_ref"]
                current = require(await call(server, "pallium_relay_work_refs", {"container_ref": SOURCE_CONTAINER}), "work-reference listing")
                if not any(row.get("work_ref") == feature_key for row in current.get("work_refs", [])):
                    raise RuntimeError("MCP work-reference listing omitted the attached reference")
                participants = require(await call(server, "pallium_relay_participants", {**FEATURE, "container_ref": SOURCE_CONTAINER}), "participant discovery")
                participant_rows = participants.get("participants", [])
                destination = next((row.get("endpoint_id") for row in participant_rows if row.get("container_ref") == TARGET_CONTAINER), None)
                if destination != target_endpoint:
                    raise RuntimeError("MCP participant discovery omitted the intended destination")
                captured = await post(None, "/item-and-query", {"source_type": "opencode", "source_id": "mcp-demo-capture", "content_type": "text/plain", "content": "MCP exact History capture", "role": "assistant", "artifact_kind": "message", "use_case": "demo_agent_memory", "container_ref": SOURCE_CONTAINER, "thread_ref": "relaydev", "visibility": "private", "metadata": {"pallium_work_refs": [feature_key]}})
                sent = require(await call(server, "pallium_relay_send", {"message": "MCP review request", "recipient": destination, "sender_runtime": "opencode", "sender_session_ref": "relaydev", "container_ref": SOURCE_CONTAINER}), "send")
                os.environ.update(PALLIUM_THREAD_REF="architect", PALLIUM_CONTAINER_REF=TARGET_CONTAINER)
                received = require(await call(server, "pallium_relay_receive", {"container_ref": TARGET_CONTAINER}), "receive")
                deliveries = received.get("deliveries", [])
                if not deliveries:
                    raise RuntimeError("MCP receive failed: no deliveries")
                delivery = deliveries[0]
                reply = require(await call(server, "pallium_relay_reply", {"delivery_id": delivery["delivery_id"], "receipt": delivery["receipt"], "message": "MCP review complete", "container_ref": TARGET_CONTAINER}), "reply")
                os.environ.update(PALLIUM_THREAD_REF="relaydev", PALLIUM_CONTAINER_REF=SOURCE_CONTAINER)
                returned = require(await call(server, "pallium_relay_receive", {"container_ref": SOURCE_CONTAINER}), "reply receive")
                returned_deliveries = returned.get("deliveries", [])
                if not returned_deliveries:
                    raise RuntimeError("MCP reply receive failed: no deliveries")
                if returned_deliveries[0]["message_id"] != reply["message_id"]:
                    raise RuntimeError("MCP reply did not return to the sender")
                detached = require(await call(server, "pallium_relay_detach_work_ref", {**FEATURE, "container_ref": SOURCE_CONTAINER}), "detach")
                if not detached.get("detached"):
                    raise RuntimeError("MCP detach did not remove the explicit association")
                after_detach = require(await call(server, "pallium_relay_work_refs", {"container_ref": SOURCE_CONTAINER}), "post-detach listing")
                if any(row.get("work_ref") == feature_key for row in after_detach.get("work_refs", [])):
                    raise RuntimeError("MCP post-detach listing still contains the explicit association")
                history = require(await call(server, "pallium_search_history_by_work_ref", {"work_ref": feature_key, "query": "", "container_ref": SOURCE_CONTAINER, "visibility": "private"}), "exact History lookup")
                recovered = next((row.get("source_item_id") for row in history.get("results", []) if row.get("source_item_id") == captured["source_item_id"]), None)
                if recovered is None:
                    raise RuntimeError("MCP exact History lookup did not recover the detached capture")
                return {"work_ref": feature_key, "participants": len(participant_rows), "source_item_id": captured["source_item_id"], "message_id": sent["message_id"], "reply_id": reply["message_id"], "detached": True, "history_source_item_id": recovered}
            finally:
                for key, value in original.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

    return asyncio.run(journey())


def seed_demo(client: TestClient) -> dict[str, Any]:
    sender = _register(
        client,
        session_ref="relaydev",
        container_ref=SOURCE_CONTAINER,
        branch="feat/relay-session-work-associations",
        alias="RelayDev",
    )
    target = _register(
        client,
        session_ref="architect",
        container_ref=TARGET_CONTAINER,
        branch="review/relay-session-work-associations",
        alias="Architect",
    )
    closed = _register(
        client,
        session_ref="closed-reviewer",
        container_ref=CLOSED_CONTAINER,
        branch="review/completed",
        alias="ClosedReviewer",
    )

    attached: dict[str, dict] = {}
    for session_ref, container_ref in (
        ("relaydev", SOURCE_CONTAINER),
        ("architect", TARGET_CONTAINER),
        ("closed-reviewer", CLOSED_CONTAINER),
    ):
        attached[session_ref] = _request(
            client,
            "POST",
            "/relay/sessions/work-refs/attach",
            json={
                "runtime": "opencode",
                "session_ref": session_ref,
                "container_ref": container_ref,
                **FEATURE,
            },
        )

    feature_key = attached["relaydev"]["attached"]["work_ref"]
    participants = _request(
        client,
        "GET",
        "/relay/work-refs/participants",
        params=FEATURE,
    )["participants"]
    recipient = next(row for row in participants if row["session_ref"] == "architect")
    sent = _request(
        client,
        "POST",
        "/relay/messages",
        json={
            "sender_runtime": "opencode",
            "sender_session_ref": "relaydev",
            "recipient": recipient["endpoint_id"],
            "payload": "Please review the shared Relay association feature.",
            "container_ref": SOURCE_CONTAINER,
        },
    )
    claim = _request(
        client,
        "POST",
        "/relay/turn",
        json={
            "runtime": "opencode",
            "session_ref": "architect",
            "container_ref": TARGET_CONTAINER,
        },
    )["deliveries"][0]
    reply = _request(
        client,
        "POST",
        "/relay/replies",
        json={
            "delivery_id": claim["delivery_id"],
            "receipt": claim["receipt"],
            "payload": "Reviewed: the exact participant journey is sound.",
            "container_ref": TARGET_CONTAINER,
        },
    )
    received = _request(
        client,
        "POST",
        "/relay/turn",
        json={
            "runtime": "opencode",
            "session_ref": "relaydev",
            "container_ref": SOURCE_CONTAINER,
        },
    )["deliveries"]

    mcp_journey = run_mcp_journey(client, target_endpoint=recipient["endpoint_id"])

    captured = _request(
        client,
        "POST",
        "/item-and-query",
        json={
            "source_type": "codex",
            "source_id": "demo-feature-capture",
            "content_type": "text/plain",
            "content": "The Relay session/work association feature passed its focused review.",
            "role": "assistant",
            "artifact_kind": "message",
            "use_case": "demo_agent_memory",
            "container_ref": SOURCE_CONTAINER,
            "thread_ref": "relaydev",
            "visibility": "private",
            "metadata": {
                "pallium_work_refs": [feature_key],
                "pallium_work_ref_sources": ["registry"],
                "pallium_relay_work_refs_status": "complete",
            },
        },
    )
    _request(
        client,
        "POST",
        "/relay/sessions/work-refs/detach",
        json={
            "runtime": "opencode",
            "session_ref": "relaydev",
            "container_ref": SOURCE_CONTAINER,
            **FEATURE,
        },
    )
    historical = _request(
        client,
        "POST",
        "/query",
        json={
            "text": " ",
            "limit": 5,
            "source_only": True,
            "trigger_origin": "agent_pull_work",
            "work_refs": [feature_key],
            "container_ref": SOURCE_CONTAINER,
            "thread_ref": "relaydev",
            "visibility": "private",
        },
    )
    _request(
        client,
        "POST",
        "/relay/sessions/close",
        json={
            "runtime": "opencode",
            "session_ref": "closed-reviewer",
            "container_ref": CLOSED_CONTAINER,
        },
    )

    if not received or received[0]["message_id"] != reply["message_id"]:
        raise RuntimeError("send/reply round trip failed")
    if historical["results"][0]["source_item_id"] != captured["source_item_id"]:
        raise RuntimeError("detached immutable History snapshot was not recovered")

    return {
        "feature": {**FEATURE, "work_ref": feature_key},
        "sessions": {
            "sender": sender["endpoint_id"],
            "target": target["endpoint_id"],
            "closed": closed["endpoint_id"],
        },
        "participants_before_detach": len(participants),
        "message_id": sent["message_id"],
        "reply_id": reply["message_id"],
        "historical_source_item_id": captured["source_item_id"],
        "current_sender_detached": True,
        "mcp_journey": mcp_journey,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run an isolated Relay session/work association journey."
    )
    parser.add_argument("--serve", action="store_true", help="keep the seeded dashboard running")
    parser.add_argument("--port", type=int, default=19837)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="pallium-relay-work-demo-") as temp:
        database = Path(temp) / "demo.db"
        config = _config(database)
        with TestClient(create_app(config)) as client:
            summary = seed_demo(client)
            if args.serve:
                _request(client, "POST", "/relay/sessions/work-refs/attach", json={"runtime": "opencode", "session_ref": "relaydev", "container_ref": SOURCE_CONTAINER, **FEATURE})
                for local_ref in ("demo:second-explicit", "demo:third-explicit"):
                    _request(client, "POST", "/relay/sessions/work-refs/attach", json={"runtime": "opencode", "session_ref": "relaydev", "container_ref": SOURCE_CONTAINER, "scope_ref": FEATURE["scope_ref"], "local_ref": local_ref})
                visible = _request(client, "GET", "/relay/work-refs/participants", params=FEATURE)["participants"]
                summary["live_serve"] = {"active_feature_participants": len(visible), "sender_explicit_refs": 3, "closed_participant_available": True}
        print(json.dumps(summary, indent=2, ensure_ascii=False))

        if args.serve:
            import uvicorn

            print(f"Isolated dashboard: http://127.0.0.1:{args.port}/dashboard")
            print(f"Lookup Scope={FEATURE['scope_ref']} and Reference={FEATURE['local_ref']}.")
            print("RelayDev is at 3/3 explicit refs; Include closed reveals ClosedReviewer.")
            print("The temporary database is deleted when this process exits.")
            uvicorn.run(create_app(config), host="127.0.0.1", port=args.port)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
