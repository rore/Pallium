"""Caller-surface tests for the profile-scoped Hermes stdio MCP adapter."""

from __future__ import annotations

import asyncio
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

pytest.importorskip("mcp", reason="mcp[cli] is required for real stdio coverage")

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from app.mcp.context import (
    PalliumContext,
    current_hermes_request,
)
from app.mcp.hermes import HERMES_TOOLS, _read_identity, create_hermes_server, make_tool_adapter
from app.mcp.server import create_server


class _RelayHandler(BaseHTTPRequestHandler):
    client = None
    calls: list[tuple[str, dict]] = []
    lock = threading.Lock()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        with self.lock:
            self.calls.append((parsed.path, query))
        response = self.client.get(parsed.path, params=query)
        self._write_response(response)

    def do_POST(self) -> None:  # noqa: N802
        size = int(self.headers.get("content-length", "0"))
        payload = json.loads(self.rfile.read(size) or b"{}")
        with self.lock:
            self.calls.append((self.path, payload))
        response = self.client.post(self.path, json=payload)
        self._write_response(response)

    def _write_response(self, response) -> None:
        raw = response.content
        self.send_response(response.status_code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *_args) -> None:
        return


def _identity(session_id: str, turn_id: str = "turn-1", **extra: object) -> dict:
    return {"pallium_hermes": {"session_id": session_id, "turn_id": turn_id, **extra}}


async def _exercise_stdio(base_url: str, *, peer_endpoint: str, reply_delivery: dict) -> dict:
    repo = str(Path(__file__).resolve().parents[1])
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": os.pathsep.join(filter(None, (repo, env.get("PYTHONPATH")))),
        # These hostile ambient values must not become this entry's fixed profile scope.
        "PALLIUM_BASE_URL": "http://127.0.0.1:1",
        "PALLIUM_AGENT_REF": "codex",
        "PALLIUM_THREAD_REF": "wrong-static-session",
        "PALLIUM_CONTAINER_REF": "git:test/wrong-container",
    })
    params = StdioServerParameters(
        command=os.sys.executable,
        args=[
            "-m", "app.mcp.hermes",
            "--base-url", base_url,
            "--container-ref", "git:test/hermes",
            "--actor-ref", "hermes-test-actor",
            "--visibility", "private",
        ],
        env=env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            names = {tool.name for tool in listed.tools}
            assert names == set(HERMES_TOOLS)

            before = len(_RelayHandler.calls)
            missing = await session.call_tool("pallium_relay_address", {})
            malformed = await session.call_tool(
                "pallium_relay_address", {}, meta=_identity(" ", "turn-1")
            )
            conflicting = await session.call_tool(
                "pallium_relay_address",
                {},
                meta={**_identity("session-a", "turn-a"), "turn_id": "turn-b"},
            )
            bad_scope = await session.call_tool(
                "pallium_relay_address",
                {"container_ref": "git:test/other"},
                meta=_identity("session-a", "turn-a"),
            )
            assert missing.isError and malformed.isError and conflicting.isError and bad_scope.isError
            assert len(_RelayHandler.calls) == before

            valid = await session.call_tool(
                "pallium_relay_address", {}, meta=_identity("session-a", "turn-a")
            )
            assert not valid.isError, [item.text for item in valid.content if hasattr(item, "text")]
            address = json.loads(valid.content[0].text)
            assert address["runtime"] == "hermes"
            assert address["session_ref"] == "session-a"

            max_unicode_session = "ü" * 255
            maximum = await session.call_tool(
                "pallium_relay_address", {}, meta=_identity(max_unicode_session, "turn-max")
            )
            assert not maximum.isError
            before_over_max = len(_RelayHandler.calls)
            over_max = await session.call_tool(
                "pallium_relay_address", {}, meta=_identity("x" * 256, "turn-over")
            )
            assert over_max.isError
            assert len(_RelayHandler.calls) == before_over_max

            # Concurrent requests on one stdio session must keep their own trusted identity.
            await asyncio.gather(*[
                session.call_tool(
                    "pallium_relay_address", {}, meta=_identity(session_id, f"turn-{session_id}")
                )
                for session_id in ("session-concurrent-a", "session-concurrent-b")
            ])

            target_filter = await session.call_tool(
                "pallium_relay_recipients",
                {"runtime": "codex", "session_ref": "other-task"},
                meta=_identity("session-a", "turn-target"),
            )
            assert not target_filter.isError

            before_send = len(_RelayHandler.calls)
            wrong_sender = await session.call_tool(
                "pallium_relay_send",
                {
                    "message": "should not send", "recipient": "@peer",
                    "sender_runtime": "hermes", "sender_session_ref": "session-other",
                },
                meta=_identity("session-a", "turn-send"),
            )
            assert wrong_sender.isError
            assert not any(path == "/relay/messages" for path, _ in _RelayHandler.calls[before_send:])
            wrong_container = await session.call_tool(
                "pallium_relay_send",
                {
                    "message": "should not send", "recipient": "@peer",
                    "sender_runtime": "hermes", "sender_session_ref": "session-a",
                    "container_ref": "git:test/other",
                },
                meta=_identity("session-a", "turn-send"),
            )
            assert wrong_container.isError
            assert not any(path == "/relay/messages" for path, _ in _RelayHandler.calls[before_send:])

            sent = await session.call_tool(
                "pallium_relay_send",
                {
                    "message": "héllo 任务", "recipient": peer_endpoint,
                    "sender_runtime": "hermes", "sender_session_ref": "session-a",
                    "container_ref": "git:test/hermes",
                },
                meta=_identity("session-a", "turn-send"),
            )
            assert not sent.isError
            sent_result = json.loads(sent.content[0].text)

            before_reply = len(_RelayHandler.calls)
            wrong_reply = await session.call_tool(
                "pallium_relay_reply",
                {"delivery_id": "delivery-other", "message": "reply"},
                meta=_identity("session-a", "turn-reply", reply={
                    "delivery_id": reply_delivery["delivery_id"], "receipt": reply_delivery["receipt"],
                }),
            )
            assert wrong_reply.isError
            assert not any(path == "/relay/replies" for path, _ in _RelayHandler.calls[before_reply:])
            wrong_receipt = await session.call_tool(
                "pallium_relay_reply",
                {"delivery_id": reply_delivery["delivery_id"], "message": "reply", "receipt": "forged"},
                meta=_identity("session-a", "turn-reply", reply={
                    "delivery_id": reply_delivery["delivery_id"], "receipt": reply_delivery["receipt"],
                }),
            )
            assert wrong_receipt.isError
            assert not any(path == "/relay/replies" for path, _ in _RelayHandler.calls[before_reply:])

            replied = await session.call_tool(
                "pallium_relay_reply",
                {"delivery_id": reply_delivery["delivery_id"], "message": "réponse"},
                meta=_identity("session-a", "turn-reply", reply={
                    "delivery_id": reply_delivery["delivery_id"], "receipt": reply_delivery["receipt"],
                }),
            )
            assert not replied.isError
            return {"tools": names, "sent": sent_result}


def test_dedicated_hermes_stdio_binds_identity_and_reuses_relay_tools(client) -> None:
    _RelayHandler.client = client
    _RelayHandler.calls = []
    scope = {"container_ref": "git:test/hermes"}

    def register(runtime: str, session_ref: str) -> dict:
        response = client.post("/relay/turn", json={
            "runtime": runtime, "session_ref": session_ref, **scope,
        })
        assert response.status_code == 200, response.text
        return response.json()["session"]

    hermes_endpoints = {
        name: register("hermes", name)
        for name in ("session-a", "ü" * 255, "session-concurrent-a", "session-concurrent-b")
    }
    codex_peer = register("codex", "other-task")
    register("codex", "reply-sender")
    incoming = client.post("/relay/messages", json={
        "sender_runtime": "codex", "sender_session_ref": "reply-sender",
        "recipient": hermes_endpoints["session-a"]["endpoint_id"],
        "payload": "question", **scope,
    })
    assert incoming.status_code == 200, incoming.text
    delivered = client.post("/relay/turn", json={
        "runtime": "hermes", "session_ref": "session-a",
        "max_chars": 2400, "max_messages": 1, **scope,
    })
    assert delivered.status_code == 200, delivered.text
    reply_delivery = delivered.json()["deliveries"][0]

    server = ThreadingHTTPServer(("127.0.0.1", 0), _RelayHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = asyncio.run(_exercise_stdio(
            f"http://127.0.0.1:{server.server_port}",
            peer_endpoint=codex_peer["endpoint_id"],
            reply_delivery=reply_delivery,
        ))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    recipient_calls = [payload for path, payload in _RelayHandler.calls if path == "/relay/sessions"]
    address_calls = [query for query in recipient_calls if query["runtime"] == ["hermes"]]
    assert {query["session_ref"][0] for query in address_calls} == {
        "session-a", "ü" * 255, "session-concurrent-a", "session-concurrent-b",
    }
    assert all(query["runtime"] == ["hermes"] for query in address_calls)
    assert all(query["container_ref"] == ["git:test/hermes"] for query in address_calls)
    assert any(
        query["runtime"] == ["codex"] and query["session_ref"] == ["other-task"]
        for query in recipient_calls
    )

    sends = [payload for path, payload in _RelayHandler.calls if path == "/relay/messages"]
    assert len(sends) == 1
    assert sends[0]["payload"] == "héllo 任务"
    assert sends[0]["sender_runtime"] == "hermes"
    assert sends[0]["sender_session_ref"] == "session-a"
    assert sends[0]["container_ref"] == "git:test/hermes"

    replies = [payload for path, payload in _RelayHandler.calls if path == "/relay/replies"]
    assert len(replies) == 1
    assert replies[0]["delivery_id"] == reply_delivery["delivery_id"]
    assert replies[0]["receipt"] == reply_delivery["receipt"]
    assert replies[0]["payload"] == "réponse"
    assert replies[0]["container_ref"] == "git:test/hermes"

    sent_message_id = result["sent"]["message_id"]
    sent_status = client.get(f"/relay/messages/{sent_message_id}", params=scope)
    assert sent_status.status_code == 200, sent_status.text
    assert sent_status.json()["payload"] == "héllo 任务"
    assert sent_status.json()["deliveries"][0]["state"] == "pending"
    replied_status = client.get(f"/relay/messages/{incoming.json()['message_id']}", params=scope)
    assert replied_status.status_code == 200, replied_status.text
    assert replied_status.json()["deliveries"][0]["state"] == "delivered"
    peer_inbox = client.post("/relay/turn", json={
        "runtime": "codex", "session_ref": "reply-sender", "max_chars": 2400, **scope,
    })
    assert peer_inbox.status_code == 200, peer_inbox.text
    assert any(item["payload"] == "réponse" for item in peer_inbox.json()["deliveries"])


def test_default_server_registration_is_unchanged() -> None:
    names = {tool.name for tool in asyncio.run(create_server().list_tools())}
    assert "pallium_query" in names
    assert "pallium_relay_receive" in names


@pytest.mark.parametrize("base_url", [
    "https://127.0.0.1:19836",
    "http://example.com:19836",
    "http://127.0.0.2:19836",
    "http://user:secret@127.0.0.1:19836",
    "http://127.0.0.1:19836/path",
    "http://127.0.0.1:19836/?token=x",
    " http://127.0.0.1:19836",
    "http://127.0.0.1:70000",
])
def test_hermes_server_rejects_non_private_loopback_topology(base_url: str) -> None:
    with pytest.raises(ValueError):
        create_hermes_server(
            base_url=base_url,
            container_ref="git:test/hermes",
            actor_ref="hermes-test-actor",
            visibility="private",
        )


@pytest.mark.parametrize(("actor_ref", "visibility"), [
    (" actor ", "private"),
    ("hermes", "shared"),
    ("x" * 256, "private"),
])
def test_hermes_server_rejects_invalid_fixed_scope(actor_ref: str, visibility: str) -> None:
    with pytest.raises(ValueError):
        create_hermes_server(
            base_url="http://127.0.0.1:19836",
            container_ref="git:test/hermes",
            actor_ref=actor_ref,
            visibility=visibility,
        )


def test_reply_admission_delivery_id_has_api_bound() -> None:
    with pytest.raises(ValueError, match="invalid admitted reply metadata"):
        _read_identity(_identity("session", reply={
            "delivery_id": "d" * 65,
            "receipt": "r" * 64,
        }), "pallium_relay_reply")


def test_bound_hermes_context_resets_after_handler_exception() -> None:
    context = PalliumContext(
        base_url="http://127.0.0.1:19836",
        container_ref="git:test/hermes",
        actor_ref="hermes-test-actor",
        agent_ref="hermes",
        visibility="private",
    )

    def failing_handler():
        assert current_hermes_request() is not None
        raise RuntimeError("handler failed")

    adapter = make_tool_adapter(context)
    guarded = adapter("pallium_relay_address", failing_handler, lambda: type(
        "RequestContext", (), {"request_context": type("Meta", (), {"meta": _identity("session")})()}
    )())
    assert guarded is not None
    assert current_hermes_request() is None

    async def invoke() -> None:
        with pytest.raises(RuntimeError, match="handler failed"):
            await guarded()
        assert current_hermes_request() is None

    asyncio.run(invoke())


async def _exercise_history_stdio(base_url: str, *, expected_ids: dict[str, str]) -> dict:
    repo = str(Path(__file__).resolve().parents[1])
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (repo, env.get("PYTHONPATH"))))
    params = StdioServerParameters(
        command=os.sys.executable,
        args=[
            "-m", "app.mcp.hermes",
            "--base-url", base_url,
            "--container-ref", "git:test/hermes",
            "--actor-ref", "hermes-test-actor",
            "--visibility", "private",
        ],
        env=env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            names = {tool.name for tool in listed.tools}
            assert names == set(HERMES_TOOLS)
            assert names.isdisjoint({"pallium_ingest", "pallium_forget_source", "pallium_query"})

            before_query = sum(path == "/query" for path, _ in _RelayHandler.calls)
            missing = await session.call_tool("pallium_search_history", {"query": "Hermes history marker"})
            conflicting = await session.call_tool(
                "pallium_search_history", {"query": "Hermes history marker", "container_ref": "git:test/other"},
                meta=_identity("later-session", "turn-history"),
            )
            wrong_thread = await session.call_tool(
                "pallium_search_history", {"query": "Hermes history marker", "thread_ref": "other-session"},
                meta=_identity("later-session", "turn-history"),
            )
            wrong_visibility = await session.call_tool(
                "pallium_search_history", {"query": "Hermes history marker", "visibility": "public"},
                meta=_identity("later-session", "turn-history"),
            )
            forged_request = await session.call_tool(
                "pallium_search_history", {
                    "query": "Hermes history marker", "request_source_item_id": "forged-current-request",
                }, meta=_identity("later-session", "turn-history"),
            )
            conflicting_identity = await session.call_tool(
                "pallium_search_history", {"query": "Hermes history marker"},
                meta={**_identity("later-session", "turn-history"), "session_id": "other-session"},
            )
            assert all(item.isError for item in (
                missing, conflicting, wrong_thread, wrong_visibility, forged_request, conflicting_identity,
            ))
            assert sum(path == "/query" for path, _ in _RelayHandler.calls) == before_query

            broad = await session.call_tool(
                "pallium_search_history",
                {"query": "Hermes history marker", "limit": 50},
                meta=_identity("later-session", "turn-broad"),
            )
            assert not broad.isError, [item.text for item in broad.content if hasattr(item, "text")]
            broad_data = json.loads(broad.content[0].text)
            broad_ids = {item["source_item_id"] for item in broad_data["results"]}
            assert expected_ids["actor_a"] in broad_ids
            assert expected_ids["actor_b"] in broad_ids
            assert expected_ids["foreign"] not in broad_ids
            assert broad_data["lookup_event_id"]

            filtered = await session.call_tool(
                "pallium_search_history",
                {
                    "query": "Hermes history marker", "limit": 50,
                    "actor_ref": "actor-b", "source_thread_ref": "prior-b",
                },
                meta=_identity("later-session", "turn-filter"),
            )
            assert not filtered.isError
            filtered_data = json.loads(filtered.content[0].text)
            assert {item["source_item_id"] for item in filtered_data["results"]} == {expected_ids["actor_b"]}
            assert filtered_data["lookup_event_id"]

            exact = await session.call_tool(
                "pallium_search_history_by_work_ref",
                {"work_ref": "TASK-42", "query": "Hermes history marker", "limit": 10},
                meta=_identity("later-session", "turn-exact"),
            )
            assert not exact.isError
            exact_data = json.loads(exact.content[0].text)
            assert {item["source_item_id"] for item in exact_data["results"]} == {expected_ids["actor_a"]}
            assert exact_data["search_mode"] == "exact_work_ref"

            expand = await session.call_tool(
                "pallium_expand_source",
                {
                    "source_item_id": expected_ids["actor_a"],
                    "parent_lookup_id": exact_data["lookup_event_id"],
                    "max_chars": 4000,
                },
                meta=_identity("later-session", "turn-expand"),
            )
            assert not expand.isError
            expanded = json.loads(expand.content[0].text)
            assert expanded["parent_lookup_id"] == exact_data["lookup_event_id"]
            assert any(item["source_item_id"] == expected_ids["actor_a"] for item in expanded["items"])
            assert "Hermes history marker alpha" in expanded["items"][0]["content"]

            concurrent = await asyncio.gather(*[
                session.call_tool(
                    "pallium_search_history",
                    {"query": "Hermes history marker", "limit": 1},
                    meta=_identity(session_id, f"turn-{session_id}"),
                )
                for session_id in ("later-concurrent-a", "later-concurrent-b")
            ])
            assert all(not item.isError for item in concurrent)
            concurrent_sessions = {
                payload["active_session_ref"]
                for path, payload in _RelayHandler.calls
                if path == "/query" and payload.get("active_session_ref", "").startswith("later-concurrent-")
            }
            assert concurrent_sessions == {"later-concurrent-a", "later-concurrent-b"}
            return {"broad": broad_data, "exact": exact_data, "expanded": expanded}


def test_hermes_stdio_history_reuses_scoped_search_and_expand(client) -> None:
    _RelayHandler.client = client
    _RelayHandler.calls = []
    rows = [
        ("hermes-history-a", "Hermes history marker alpha; use the exact work stream.", "prior-a", "actor-a", "TASK-42"),
        ("hermes-history-b", "Hermes history marker beta; a different historical session.", "prior-b", "actor-b", "TASK-43"),
        ("hermes-history-other-container", "Hermes history marker must remain private.", "prior-a", "actor-a", "TASK-42"),
    ]
    source_ids = {}
    for source_id, content, thread_ref, actor_ref, work_ref in rows:
        item = {
            "source_type": "hermes",
            "source_id": source_id,
            "content_type": "text/plain",
            "content": content,
            "role": "user",
            "agent_ref": "hermes",
            "container_ref": "git:test/hermes" if source_id != "hermes-history-other-container" else "git:test/other",
            "thread_ref": thread_ref,
            "actor_ref": actor_ref,
            "visibility": "private",
            "artifact_kind": "message",
            "metadata": {"pallium_work_refs": [work_ref]},
        }
        response = client.post("/items", json=[item])
        assert response.status_code == 200, response.text
        source_ids[source_id] = response.json()[0]["source_item_id"]

    server = ThreadingHTTPServer(("127.0.0.1", 0), _RelayHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = asyncio.run(_exercise_history_stdio(
            f"http://127.0.0.1:{server.server_port}",
            expected_ids={
                "actor_a": source_ids["hermes-history-a"],
                "actor_b": source_ids["hermes-history-b"],
                "foreign": source_ids["hermes-history-other-container"],
            },
        ))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    history_posts = [payload for path, payload in _RelayHandler.calls if path == "/query"]
    assert len(history_posts) >= 5
    assert all(payload["container_ref"] == "git:test/hermes" for payload in history_posts)
    assert all(payload["visibility"] == "private" for payload in history_posts)
    assert all(payload["active_session_ref"].startswith("later-") for payload in history_posts)
    assert any(payload.get("actor_ref") == "actor-b" for payload in history_posts)
    assert any(payload.get("thread_ref") == "prior-b" for payload in history_posts)
    assert result["expanded"]["parent_lookup_id"] == result["exact"]["lookup_event_id"]


def test_hermes_stdio_history_paging_redaction_and_forgetting(client) -> None:
    _RelayHandler.client = client
    _RelayHandler.calls = []
    marker = "Hermes pagination marker "
    items = []
    for index in range(12):
        items.append({
            "source_type": "hermes", "source_id": f"hermes-page-{index}",
            "content_type": "text/plain",
            "content": marker + str(index) + " " + ("paragraph about private decisions and evidence " * 12),
            "role": "assistant", "agent_ref": "hermes", "container_ref": "git:test/hermes",
            "thread_ref": "prior-page", "actor_ref": "actor-page", "visibility": "private",
            "artifact_kind": "message",
        })
    fake_secret = "sk-" + "ABCD1234efgh5678" + "IJKL9012mnop3456" + "qrst7890"
    secret_item = {
        "source_type": "hermes", "source_id": "hermes-redaction-row",
        "content_type": "text/plain", "content": f"Hermes redaction marker with token {fake_secret}",
        "role": "assistant", "agent_ref": "hermes", "container_ref": "git:test/hermes",
        "thread_ref": "prior-secret", "actor_ref": "actor-page", "visibility": "private",
        "artifact_kind": "message",
    }
    foreign_item = {
        "source_type": "hermes", "source_id": "hermes-foreign-container-source",
        "content_type": "text/plain", "content": "Foreign container must not expand.",
        "role": "assistant", "agent_ref": "hermes", "container_ref": "git:test/other",
        "thread_ref": "prior-foreign", "actor_ref": "actor-page", "visibility": "private",
        "artifact_kind": "message",
    }
    response = client.post("/items", json=[*items, secret_item, foreign_item])
    assert response.status_code == 200, response.text
    page_source = response.json()[0]["source_item_id"]
    secret_source = response.json()[-2]["source_item_id"]
    foreign_source = response.json()[-1]["source_item_id"]

    server = ThreadingHTTPServer(("127.0.0.1", 0), _RelayHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = asyncio.run(_exercise_history_pages(
            f"http://127.0.0.1:{server.server_port}",
            client=client,
            page_source=page_source,
            secret_source=secret_source,
            foreign_source=foreign_source,
            fake_secret=fake_secret,
        ))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert result["page2"]["result_offset"] == result["page1"]["next_offset"]
    assert result["secret_item_id"] == secret_source


async def _exercise_history_pages(
    base_url: str, *, client, page_source: str, secret_source: str,
    foreign_source: str, fake_secret: str,
) -> dict:
    repo = str(Path(__file__).resolve().parents[1])
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (repo, env.get("PYTHONPATH"))))
    params = StdioServerParameters(
        command=os.sys.executable,
        args=["-m", "app.mcp.hermes", "--base-url", base_url,
              "--container-ref", "git:test/hermes", "--actor-ref", "hermes-test-actor",
              "--visibility", "private"],
        env=env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            page1_result = await session.call_tool(
                "pallium_search_history",
                {"query": "Hermes pagination marker", "limit": 12},
                meta=_identity("later-paging", "turn-page-1"),
            )
            assert not page1_result.isError
            page1 = json.loads(page1_result.content[0].text)
            assert page1["next_offset"] is not None
            page2_result = await session.call_tool(
                "pallium_search_history",
                {"query": "Hermes pagination marker", "limit": 12,
                 "result_offset": page1["next_offset"], "result_revision": page1["result_revision"]},
                meta=_identity("later-paging", "turn-page-2"),
            )
            assert not page2_result.isError
            page2 = json.loads(page2_result.content[0].text)
            assert page2["result_offset"] == page1["next_offset"]
            assert page2["result_revision"] == page1["result_revision"]
            missing_revision = await session.call_tool(
                "pallium_search_history",
                {"query": "Hermes pagination marker", "limit": 12, "result_offset": page1["next_offset"]},
                meta=_identity("later-paging", "turn-page-missing-revision"),
            )
            assert not missing_revision.isError
            assert json.loads(missing_revision.content[0].text)["error_kind"] == "result_revision_required"
            stale_revision = await session.call_tool(
                "pallium_search_history",
                {"query": "Hermes pagination marker", "limit": 12,
                 "result_offset": page1["next_offset"], "result_revision": "0" * 64},
                meta=_identity("later-paging", "turn-page-stale-revision"),
            )
            assert not stale_revision.isError
            assert json.loads(stale_revision.content[0].text)["error_kind"] == "stale_result_revision"

            secret_result = await session.call_tool(
                "pallium_search_history", {"query": "Hermes redaction marker", "limit": 5},
                meta=_identity("later-paging", "turn-secret-search"),
            )
            assert not secret_result.isError
            secret_data = json.loads(secret_result.content[0].text)
            assert secret_source in {item["source_item_id"] for item in secret_data["results"]}
            assert fake_secret not in secret_result.content[0].text
            foreign_expand = await session.call_tool(
                "pallium_expand_source", {"source_item_id": foreign_source, "max_chars": 4000},
                meta=_identity("later-paging", "turn-foreign-expand"),
            )
            assert not foreign_expand.isError
            assert json.loads(foreign_expand.content[0].text).get("error")
            secret_expand_result = await session.call_tool(
                "pallium_expand_source", {"source_item_id": secret_source,
                    "parent_lookup_id": secret_data["lookup_event_id"], "max_chars": 4000},
                meta=_identity("later-paging", "turn-secret-expand"),
            )
            assert not secret_expand_result.isError
            secret_expanded = secret_expand_result.content[0].text
            assert fake_secret not in secret_expanded
            assert "[REDACTED" in secret_expanded

            forgotten = client.post("/source/forget", json={
                "source_item_id": secret_source, "reason": "Hermes History E2E",
            })
            assert forgotten.status_code == 200, forgotten.text
            after_forget = await session.call_tool(
                "pallium_search_history", {"query": "Hermes redaction marker", "limit": 5},
                meta=_identity("later-paging", "turn-after-forget"),
            )
            assert not after_forget.isError
            after_data = json.loads(after_forget.content[0].text)
            assert secret_source not in {item["source_item_id"] for item in after_data["results"]}
            forgotten_expand = await session.call_tool(
                "pallium_expand_source", {"source_item_id": secret_source, "max_chars": 4000},
                meta=_identity("later-paging", "turn-after-forget-expand"),
            )
            assert not forgotten_expand.isError
            assert json.loads(forgotten_expand.content[0].text).get("error")
            returned_page_ids = {
                item["source_item_id"] for item in page1["results"] + page2["results"]
            }
            assert page_source in returned_page_ids
            return {"page1": page1, "page2": page2, "secret_item_id": secret_source}
