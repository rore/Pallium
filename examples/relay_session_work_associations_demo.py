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
        print(json.dumps(summary, indent=2, ensure_ascii=False))

        if args.serve:
            import uvicorn

            print(f"Isolated dashboard: http://127.0.0.1:{args.port}/dashboard")
            print("The temporary database is deleted when this process exits.")
            uvicorn.run(create_app(config), host="127.0.0.1", port=args.port)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
