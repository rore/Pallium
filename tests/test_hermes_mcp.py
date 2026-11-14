"""Caller-surface tests for the profile-scoped Hermes stdio MCP adapter."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

pytest.importorskip("mcp", reason="mcp[cli] is required for real stdio coverage")

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from anyio import ClosedResourceError

from integrations.hermes import mcp_bridge as bridge_module

from app.mcp.context import (
    PalliumContext,
    current_hermes_request,
)
from app.mcp.client import PalliumMcpClient
from app.mcp.hermes import HERMES_MEMORY_TOOLS, HERMES_TOOLS, _read_identity, create_hermes_server, make_tool_adapter
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


@pytest.fixture
def joined_bridge_recovery_context(client, monkeypatch):
    """Keep the real SDK/stdio/HTTP/storage path and exact owned cleanup handles."""
    import mcp.client.stdio as sdk_stdio
    import anyio

    lock = threading.Lock()
    bridges, bridge_threads, sessions, stdio_contexts, events = [], [], [], [], []
    requests, sdk_calls, errors = [], [], []
    processes, expected_close_failures = [], set()
    state = SimpleNamespace(poisoned=None, committed=None, injections=0, inject_send_loss=True)
    server = listener = None
    startup_error = None
    original_call = ClientSession.call_tool
    original_enter, original_exit = ClientSession.__aenter__, ClientSession.__aexit__
    original_stdio = sdk_stdio.stdio_client
    original_process = anyio.open_process

    async def owned_process(*args, **kwargs):
        process = await original_process(*args, **kwargs)
        with lock:
            processes.append(process)
        return process

    def event(kind, owner):
        with lock:
            events.append((kind, owner))

    async def enter_session(session):
        entry = SimpleNamespace(owner=session, entered=False, exited=False)
        with lock:
            sessions.append(entry)  # Retain partial construction too.
        result = await original_enter(session)
        entry.entered = True
        event("session-enter", session)
        return result

    async def exit_session(session, *failure):
        result = await original_exit(session, *failure)
        entry = next(entry for entry in sessions if entry.owner is session)
        entry.exited = True
        event("session-exit", session)
        return result

    @asynccontextmanager
    async def owned_stdio(*args, **kwargs):
        context = original_stdio(*args, **kwargs)
        entry = SimpleNamespace(owner=context, entered=False, exited=False)
        with lock:
            stdio_contexts.append(entry)
        streams = await context.__aenter__()
        entry.params = args[0]
        entry.entered = True
        event("stdio-enter", context)
        try:
            yield streams
        except BaseException:
            suppressed = await context.__aexit__(*os.sys.exc_info())
            entry.exited = True
            event("stdio-exit", context)
            if not suppressed:
                raise
        else:
            await context.__aexit__(None, None, None)
            entry.exited = True
            event("stdio-exit", context)

    async def forward_then_poison_original(session, name, arguments=None, **kwargs):
        observed = {
            "owner": session, "name": name,
            "arguments": json.loads(json.dumps(arguments)),
            "metadata": json.loads(json.dumps(kwargs.get("meta"))),
        }
        with lock:
            sdk_calls.append(observed)
            poisoned = session is state.poisoned
        if poisoned:
            raise ClosedResourceError("controlled original-session transport failure")
        result = await original_call(session, name, arguments=arguments, **kwargs)
        if name == "pallium_relay_send" and state.inject_send_loss and state.poisoned is None:
            wire = result.model_dump(mode="json", by_alias=True)
            if wire.get("isError") is False:
                text = "\n".join(block["text"] for block in wire["content"])
                committed = json.loads(text)
                if "message_id" in committed:
                    with lock:
                        state.committed = committed
                        state.poisoned = session
                        state.injections += 1
                    # The actual send already completed. Do not poison replacements,
                    # fake its response, close shared transports or replay the call.
                    raise ClosedResourceError("controlled lost response after commit")
        return result

    def owned_thread(*args, **kwargs):
        thread = threading.Thread(*args, **kwargs)
        with lock:
            bridge_threads.append(thread)
        return thread

    class Handler(_RelayHandler):
        mutation_responses = []

        def _write_response(self, response):
            if self.command == "POST" and self.path == "/relay/messages":
                with self.lock:
                    self.mutation_responses.append((response.status_code, response.json()))
            super()._write_response(response)

    Handler.client, Handler.calls, Handler.lock = client, [], threading.Lock()

    class Proxy(ThreadingHTTPServer):
        def process_request(self, request, client_address):
            worker = threading.Thread(
                target=self.process_request_thread, args=(request, client_address),
                name="hermes-bridge-recovery-http-request", daemon=True,
            )
            with lock:
                requests.append(worker)
            try:
                worker.start()
            except BaseException as error:
                errors.append(error)
                attempt(self.shutdown_request, request)
                raise

        def handle_error(self, request, client_address):
            with lock:
                errors.append(os.sys.exception() or RuntimeError("Forwarding request failed"))

    class Bridge(bridge_module.RelayMcpBridge):
        def __init__(self, **kwargs):
            bridges.append(self)
            super().__init__(**kwargs)

    def attempt(callback, *args):
        try:
            callback(*args)
        except BaseException as error:
            errors.append(error)

    def close_bridge(bridge):
        if bridge in expected_close_failures:
            with pytest.raises(RuntimeError, match="cleanup"):
                bridge.close()
        else:
            bridge.close()

    def join_owned(thread):
        if thread.ident is not None:
            thread.join(timeout=2)
        assert not thread.is_alive(), "Owned bridge regression thread did not exit"

    def check_context(entry):
        assert entry.entered and entry.exited, "Owned SDK context startup/cleanup incomplete"

    def serve():
        try:
            server.serve_forever(poll_interval=.01)
        except BaseException as error:
            with lock:
                errors.append(error)

    def create(scope, *, memory_enabled=False):
        return Bridge(
            python=os.sys.executable, repo=str(Path(__file__).resolve().parents[1]),
            base_url=f"http://127.0.0.1:{server.server_port}",
            container_ref=scope, actor_ref="bridge-test-actor", visibility="private",
            memory_enabled=memory_enabled,
        )

    try:
        threading_view = SimpleNamespace(**vars(threading))
        threading_view.Thread = owned_thread
        monkeypatch.setattr(bridge_module, "threading", threading_view)
        monkeypatch.setattr(ClientSession, "__aenter__", enter_session)
        monkeypatch.setattr(ClientSession, "__aexit__", exit_session)
        monkeypatch.setattr(ClientSession, "call_tool", forward_then_poison_original)
        monkeypatch.setattr(sdk_stdio, "stdio_client", owned_stdio)
        monkeypatch.setattr(anyio, "open_process", owned_process)
        server = Proxy(("127.0.0.1", 0), Handler)
        listener = threading.Thread(target=serve, name="hermes-bridge-recovery-http", daemon=True)
        listener.start()
        yield SimpleNamespace(
            create=create, state=state, sdk_calls=sdk_calls, http_calls=Handler.calls,
            http_mutations=Handler.mutation_responses,
            sessions=sessions, stdio_contexts=stdio_contexts, events=events,
            processes=processes, expected_close_failures=expected_close_failures,
        )
    except BaseException as error:
        startup_error = error
        raise
    finally:
        for bridge in reversed(bridges):
            if getattr(bridge, "_thread", None) is not None:
                attempt(close_bridge, bridge)
        with lock:
            owned = list(bridge_threads)
        for thread in owned:
            attempt(join_owned, thread)
        for entry in [*sessions, *stdio_contexts]:
            attempt(check_context, entry)
        for process in processes:
            if process.returncode is None:
                errors.append(AssertionError("Owned SDK subprocess did not exit"))
        if server is not None:
            if listener is not None and listener.is_alive():
                attempt(server.shutdown)
            attempt(server.server_close)
        if listener is not None:
            attempt(join_owned, listener)
        with lock:
            workers = list(requests)
        for worker in workers:
            attempt(join_owned, worker)
        if errors:
            # Pytest retains body failures separately; include setup errors when
            # teardown also fails, rather than replace either failure with a pass.
            failures = ([startup_error] if startup_error is not None else []) + errors
            raise BaseExceptionGroup("Bridge regression owned cleanup failed", failures) from None


def test_bridge_transport_failure_after_commit_is_not_replayed_and_next_call_recovers_e2e(
    client, joined_bridge_recovery_context,
) -> None:
    """Injected post-success transport loss, not genuine EOF/original-race proof."""
    joined = joined_bridge_recovery_context
    scope = {"container_ref": "git:example.test/hermes-bridge-recovery"}
    sender, recipient = "sending-שלום", "recipient-调用-שלום"
    sender_turn, later_turn = "send-turn-一", "later-turn-שני"
    payload = "bridge recovery héllo 任务"
    endpoints = {}
    # Recipient explicitly doubles as the later caller. Address does not register.
    for session in (sender, recipient):
        registered = client.post("/relay/turn", json={
            "runtime": "hermes", "session_ref": session, "max_messages": 0, **scope,
        })
        assert registered.status_code == 200, "Normal endpoint registration failed; not behavioral RED"
        endpoints[session] = registered.json()["session"]["endpoint_id"]
    empty = client.get("/dashboard/api/relay/messages", params=scope)
    assert empty.status_code == 200 and empty.json()["total"] == 0

    bridge = joined.create(scope["container_ref"])
    assert {tool["name"] for tool in bridge.catalog} == set(HERMES_TOOLS)
    first = json.loads(bridge.call("pallium_relay_send", {
        "recipient": endpoints[recipient], "message": payload, "expires_in_seconds": 3600,
    }, (sender, sender_turn)))
    assert joined.state.injections == 1 and joined.state.committed is not None, (
        "Real send did not complete before fault injection; not behavioral RED"
    )
    assert "error" in first and "message_id" not in first
    message_id = joined.state.committed["message_id"]
    original_session = joined.state.poisoned

    def assert_one_real_mutation_and_message():
        sdk_sends = [call for call in joined.sdk_calls if call["name"] == "pallium_relay_send"]
        assert len(sdk_sends) == 1, "The original invocation was replayed at the SDK boundary"
        assert "message_id" not in sdk_sends[0]["arguments"]
        assert sdk_sends[0]["metadata"] == _identity(sender, sender_turn)
        sends = [body for path, body in joined.http_calls if path == "/relay/messages"]
        assert len(sends) == 1, "Multiple HTTP attempts need prerequisite/replay disposition; not assumed RED"
        successful = [body for status, body in joined.http_mutations if 200 <= status < 300]
        assert len(successful) == 1 and successful[0]["message_id"] == message_id
        # The existing HTTP client generates a fresh ID per tool invocation.
        # It is not a caller-supplied retry key; count both dispatches and storage.
        assert sends[0]["message_id"] == message_id
        assert sends[0]["payload"] == payload and sends[0]["recipient"] == endpoints[recipient]
        assert sends[0]["sender_runtime"] == "hermes" and sends[0]["sender_session_ref"] == sender
        assert sends[0]["container_ref"] == scope["container_ref"]
        persisted = client.get(f"/relay/messages/{message_id}", params=scope)
        assert persisted.status_code == 200
        stored = persisted.json()
        assert stored["payload"] == payload
        assert len(stored["deliveries"]) == 1
        assert stored["deliveries"][0]["recipient_endpoint_id"] == endpoints[recipient]
        page = client.get("/dashboard/api/relay/messages", params={**scope, "limit": 200})
        assert page.status_code == 200
        rows = page.json()
        assert rows["total"] == len(rows["messages"]) == 1 and not rows["has_more"]
        assert rows["messages"][0]["id"] == message_id
        assert rows["messages"][0]["payload"] == payload

    assert_one_real_mutation_and_message()
    later = json.loads(bridge.call("pallium_relay_address", {}, (recipient, later_turn)))
    later_calls = [call for call in joined.sdk_calls if call["name"] == "pallium_relay_address"]
    assert len(later_calls) == 1
    assert later_calls[0]["metadata"] == _identity(recipient, later_turn)
    assert later_calls[0]["arguments"]["container_ref"] == scope["container_ref"]
    assert joined.state.poisoned is original_session and joined.state.injections == 1
    assert_one_real_mutation_and_message()

    # Baseline-predicted decisive failure: it reuses the exact poisoned session.
    # Preconditions above prove registration, real persistence and later metadata.
    assert "error" not in later, "A later independent registered caller must recover its own usable connection"
    assert later["runtime"] == "hermes" and later["session_ref"] == recipient
    assert later["exact_selector"] == endpoints[recipient]
    assert later_calls[0]["owner"] is not original_session
    assert "may have committed" in first["error"].lower()
    queries = [query for path, query in joined.http_calls
               if path == "/relay/sessions" and query.get("session_ref") == [recipient]]
    assert len(queries) == 1
    assert queries[0]["runtime"] == ["hermes"] and queries[0]["container_ref"] == [scope["container_ref"]]

    def event_index(kind, owner):
        return next(index for index, event in enumerate(joined.events)
                    if event[0] == kind and event[1] is owner)

    assert event_index("session-exit", original_session) < event_index("session-enter", later_calls[0]["owner"])
    assert len(joined.stdio_contexts) >= 2
    assert event_index("stdio-exit", joined.stdio_contexts[0].owner) < event_index(
        "stdio-enter", joined.stdio_contexts[1].owner,
    )


def _bridge_lifecycle_case(client, joined, *, memory_enabled=False):
    scope = {"container_ref": "git:example.test/bridge-lifecycle"}
    identities = ("sender-שלום", "caller-调用")
    endpoints = {}
    for identity in identities:
        response = client.post("/relay/turn", json={
            "runtime": "hermes", "session_ref": identity, "max_messages": 0, **scope,
        })
        assert response.status_code == 200, response.text
        endpoints[identity] = response.json()["session"]["endpoint_id"]
    joined.state.inject_send_loss = False
    bridge = joined.create(scope["container_ref"], memory_enabled=memory_enabled)
    return bridge, scope, identities, endpoints


def _bridge_address(bridge, identity, turn="turn-שלום"):
    return json.loads(bridge.call("pallium_relay_address", {}, (identity, turn)))


@pytest.mark.parametrize("fault", ["transport", "grouped-transport", "sdk-closed", "eof", "finished", "schedule", "timeout", "cancelled"])
def test_bridge_unusable_transport_recovers_for_next_call_e2e(
    client, joined_bridge_recovery_context, monkeypatch, fault,
):
    from mcp.shared.exceptions import McpError
    from mcp.types import CONNECTION_CLOSED, ErrorData

    joined = joined_bridge_recovery_context
    bridge, scope, identities, endpoints = _bridge_lifecycle_case(client, joined)
    sender, caller = identities
    assert _bridge_address(bridge, sender)["exact_selector"] == endpoints[sender]
    original = bridge._connection
    forward = ClientSession.call_tool
    pending = []

    async def broken(session, name, arguments=None, **kwargs):
        if session is original.session:
            if fault == "grouped-transport":
                raise BaseExceptionGroup("private receipt marker", [ClosedResourceError(), asyncio.CancelledError()])
            if fault == "sdk-closed":
                raise McpError(ErrorData(code=CONNECTION_CLOSED, message="private receipt marker"))
            if fault == "cancelled":
                raise asyncio.CancelledError()
            if fault == "timeout":
                await asyncio.Event().wait()
            raise ClosedResourceError("private receipt marker")
        return await forward(session, name, arguments=arguments, **kwargs)

    if fault == "eof":
        process = joined.processes[0]

        async def end_input():
            await process.stdin.aclose()
            return await process.wait()

        asyncio.run_coroutine_threadsafe(end_input(), original.loop).result(timeout=3)
        assert process.returncode is not None
    elif fault == "finished":
        bridge._retire(original)
        original.thread.join(timeout=3)
        assert original.finished.is_set() and original.loop.is_closed()
    elif fault == "schedule":
        view = SimpleNamespace(**vars(asyncio))

        def refuse(coroutine, loop):
            if loop is original.loop:
                pending.append(coroutine)
                raise RuntimeError("closed scheduling loop")
            return asyncio.run_coroutine_threadsafe(coroutine, loop)

        view.run_coroutine_threadsafe = refuse
        monkeypatch.setattr(bridge_module, "asyncio", view)
    else:
        monkeypatch.setattr(ClientSession, "call_tool", broken)
    if fault == "timeout":
        monkeypatch.setattr(bridge_module, "TIMEOUT_SECONDS", .1)
    first = _bridge_address(bridge, caller, "failed-一")
    first_succeeded = "error" not in first
    if fault == "finished" or fault == "eof" and first_succeeded:
        assert first["exact_selector"] == endpoints[caller]
    else:
        assert "error" in first and "private receipt marker" not in first["error"]
        if fault == "schedule":
            assert "before dispatch" in first["error"]
            assert pending and all(item.cr_frame is None for item in pending)
        else:
            assert "may have committed" in first["error"]
    monkeypatch.setattr(bridge_module, "TIMEOUT_SECONDS", 15)
    recovered = _bridge_address(bridge, caller, "later-שני")
    assert recovered["exact_selector"] == endpoints[caller]
    assert bridge._connection is not original
    assert not original.thread.is_alive() and not original.cleanup_failed
    assert all(entry.exited for entry in joined.sessions if entry.owner is original.session)
    assert len(joined.stdio_contexts) == 2
    assert len([query for path, query in joined.http_calls if path == "/relay/sessions"
                and query.get("session_ref") == [caller]]) == (2 if first_succeeded else 1)
    bridge.close()
    assert all(process.returncode is not None for process in joined.processes)


@pytest.mark.parametrize("memory_enabled", [False, True])
def test_bridge_repeated_recovery_preserves_construction_and_catalog_e2e(
    client, joined_bridge_recovery_context, monkeypatch, memory_enabled,
):
    joined = joined_bridge_recovery_context
    bridge, scope, identities, endpoints = _bridge_lifecycle_case(client, joined, memory_enabled=memory_enabled)
    original_catalog = json.loads(json.dumps(bridge.catalog))
    first_params = joined.stdio_contexts[0].params.model_dump()
    forward = ClientSession.call_tool
    failed = set()

    async def fail_once(session, name, arguments=None, **kwargs):
        if session in failed:
            raise ClosedResourceError("dead generation")
        return await forward(session, name, arguments=arguments, **kwargs)

    monkeypatch.setattr(ClientSession, "call_tool", fail_once)
    for cycle in range(3):
        old = bridge._connection
        failed.add(old.session)
        assert "may have committed" in _bridge_address(bridge, identities[0])["error"]
        # Reconnection must use immutable construction, not these public aliases.
        bridge.python, bridge.repo = "not-an-interpreter", "not-a-checkout"
        bridge.config = ("http://127.0.0.1:1", "git:example.test/foreign", "other", "global", not memory_enabled)
        recovered = _bridge_address(bridge, identities[1], f"cycle-{cycle}-调用")
        assert recovered["exact_selector"] == endpoints[identities[1]]
        assert bridge.catalog == original_catalog
        assert joined.stdio_contexts[-1].params.model_dump() == first_params
        assert old.finished.is_set() and not old.thread.is_alive()
    assert len(joined.stdio_contexts) == 4
    bridge.close()
    bridge.close()
    assert "error" in _bridge_address(bridge, identities[1])
    assert all(entry.exited for entry in [*joined.sessions, *joined.stdio_contexts])


def test_bridge_healthy_refusals_and_invalid_bindings_do_not_reconnect_e2e(
    client, joined_bridge_recovery_context,
):
    joined = joined_bridge_recovery_context
    bridge, scope, identities, endpoints = _bridge_lifecycle_case(client, joined)
    original = bridge._connection
    for identity in (None, (), ("", "turn"), ("caller", " "), (1, "turn")):
        assert "trusted session and turn" in json.loads(bridge.call("pallium_relay_address", {}, identity))["error"]
    for values in ([], {"bad": set()}):
        assert "unsupported" in json.loads(bridge.call("pallium_relay_address", values, (identities[0], "turn")))["error"]
    assert "error" in json.loads(bridge.call("not-a-tool", {}, (identities[0], "turn")))
    assert not joined.sdk_calls
    for values in ({}, {"message": ""}, {"message": "hello", "recipient": 42}):
        refused = json.loads(bridge.call("pallium_relay_send", values, (identities[0], "turn")))
        assert "refused" in refused["error"]
    for identity in ("unregistered", "x" * 256):
        assert "error" in _bridge_address(bridge, identity)
    missing = json.loads(bridge.call("pallium_relay_status", {"message_id": "missing"}, (identities[0], "missing-turn")))
    assert "error" in missing
    maximum = "调用" * 127 + "é"
    assert len(maximum) == 255
    registered = client.post("/relay/turn", json={"runtime": "hermes", "session_ref": maximum, "max_messages": 0, **scope})
    assert registered.status_code == 200
    for identity in (maximum, identities[0], identities[1]):
        assert _bridge_address(bridge, identity)["session_ref"] == identity
    assert bridge._connection is original and len(joined.stdio_contexts) == 1
    assert not any(path == "/relay/messages" for path, _ in joined.http_calls)


@pytest.mark.parametrize("fault", ["before-initialize", "after-initialize", "initialize-timeout", "list-tools", "session-construction"])
def test_bridge_partial_reconnect_startup_disposes_and_later_call_recovers_e2e(
    client, joined_bridge_recovery_context, monkeypatch, fault,
):
    joined = joined_bridge_recovery_context
    bridge, scope, identities, endpoints = _bridge_lifecycle_case(client, joined)
    old = bridge._connection
    bridge._retire(old)
    original_init, original_initialize = ClientSession.__init__, ClientSession.initialize
    original_list = ClientSession.list_tools
    injected = []

    def construct(session, *args, **kwargs):
        if fault == "session-construction" and not injected:
            injected.append(session)
            raise ValueError("controlled partial session construction")
        original_init(session, *args, **kwargs)

    async def initialize(session, *args, **kwargs):
        if fault in {"before-initialize", "after-initialize", "initialize-timeout"} and not injected:
            injected.append(session)
            if fault == "initialize-timeout":
                await asyncio.Event().wait()
            if fault == "after-initialize":
                await original_initialize(session, *args, **kwargs)
            raise ClosedResourceError("controlled startup failure")
        return await original_initialize(session, *args, **kwargs)

    async def list_tools(session, *args, **kwargs):
        if fault == "list-tools" and not injected:
            injected.append(session)
            raise ClosedResourceError("controlled list failure")
        return await original_list(session, *args, **kwargs)

    monkeypatch.setattr(ClientSession, "__init__", construct)
    monkeypatch.setattr(ClientSession, "initialize", initialize)
    monkeypatch.setattr(ClientSession, "list_tools", list_tools)
    if fault == "initialize-timeout":
        monkeypatch.setattr(bridge_module, "TIMEOUT_SECONDS", 1)
    assert "error" in _bridge_address(bridge, identities[0])
    monkeypatch.setattr(bridge_module, "TIMEOUT_SECONDS", 15)
    failed = bridge._connection
    assert failed is not old and failed.finished.is_set() and not failed.cleanup_failed
    assert not joined.sdk_calls
    assert _bridge_address(bridge, identities[1])["exact_selector"] == endpoints[identities[1]]
    assert len(injected) == 1 and len(joined.stdio_contexts) == 3
    assert all(entry.exited for entry in joined.stdio_contexts[:-1])


@pytest.mark.parametrize("change", ["order", "schema", "missing-tool"])
def test_bridge_reconnect_catalog_is_normalized_or_fails_closed_e2e(
    client, joined_bridge_recovery_context, monkeypatch, change,
):
    joined = joined_bridge_recovery_context
    bridge, scope, identities, endpoints = _bridge_lifecycle_case(client, joined)
    before = json.loads(json.dumps(bridge.catalog))
    original_list = ClientSession.list_tools

    async def changed(session, *args, **kwargs):
        result = await original_list(session, *args, **kwargs)
        if change == "order":
            result.tools.reverse()
        elif change == "schema":
            result.tools[0].inputSchema["properties"]["unexpected"] = {"type": "string"}
        else:
            result.tools.pop()
        return result

    monkeypatch.setattr(ClientSession, "list_tools", changed)
    bridge._retire(bridge._connection)
    result = _bridge_address(bridge, identities[0])
    if change == "order":
        assert result["exact_selector"] == endpoints[identities[0]]
        assert len(joined.sdk_calls) == 1
    else:
        assert "error" in result and bridge._connection.catalog_failed
        assert "error" in _bridge_address(bridge, identities[1])
        assert not joined.sdk_calls
        assert all(entry.exited for entry in joined.stdio_contexts)
    assert len(joined.stdio_contexts) == 2 and bridge.catalog == before


def test_bridge_initial_startup_failure_disposes_partial_owners_e2e(
    joined_bridge_recovery_context, monkeypatch,
):
    joined = joined_bridge_recovery_context
    initialize = ClientSession.initialize

    async def fail_after_initialization(session, *args, **kwargs):
        await initialize(session, *args, **kwargs)
        raise ClosedResourceError("partial initial startup")

    monkeypatch.setattr(ClientSession, "initialize", fail_after_initialization)
    with pytest.raises(ValueError, match="could not initialize"):
        joined.create("git:example.test/bridge-startup")
    assert len(joined.stdio_contexts) == len(joined.sessions) == 1
    assert all(entry.exited for entry in [*joined.sessions, *joined.stdio_contexts])
    assert all(process.returncode is not None for process in joined.processes)
    assert not joined.sdk_calls


def test_bridge_concurrent_recovery_keeps_each_call_snapshot_e2e(
    client, joined_bridge_recovery_context, monkeypatch,
):
    joined = joined_bridge_recovery_context
    bridge, scope, identities, endpoints = _bridge_lifecycle_case(client, joined)
    old = bridge._connection
    bridge._retire(old)
    original_get = bridge._get_connection
    captured = threading.Barrier(3)
    release = threading.Event()

    def wait_after_snapshot():
        captured.wait(timeout=3)
        assert release.wait(3)
        return original_get()

    monkeypatch.setattr(bridge, "_get_connection", wait_after_snapshot)
    payloads = ["任务" * 8000, "שלום concurrent mutation"]
    arguments = [{"recipient": endpoints[identities[1 - index]], "message": text}
                 for index, text in enumerate(payloads)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(bridge.call, "pallium_relay_send", arguments[index],
                               (identity, f"turn-{index}-调用")) for index, identity in enumerate(identities)]
        try:
            captured.wait(timeout=3)
            for values in arguments:
                values.update(message="changed after snapshot", recipient="invalid-after-snapshot")
            release.set()
            results = [json.loads(future.result(timeout=10)) for future in futures]
        finally:
            release.set()
    assert all("message_id" in result for result in results), results
    assert len(joined.stdio_contexts) == 2 and old.finished.is_set()
    assert len(joined.sdk_calls) == len(joined.http_mutations) == 2
    for index, result in enumerate(results):
        stored = client.get(f"/relay/messages/{result['message_id']}", params=scope)
        assert stored.status_code == 200 and stored.json()["payload"] == payloads[index]
        observed = next(call for call in joined.sdk_calls
                        if call["metadata"] == _identity(identities[index], f"turn-{index}-调用"))
        assert observed["arguments"]["message"] == payloads[index]
        assert observed["arguments"]["container_ref"] == scope["container_ref"]
    page = client.get("/dashboard/api/relay/messages", params=scope).json()
    assert page["total"] == len(page["messages"]) == 2 and not page["has_more"]
    monkeypatch.setattr(bridge, "_get_connection", original_get)
    current = bridge._connection
    for text in ("", "x" * 16001):
        refused = json.loads(bridge.call("pallium_relay_send", {
            "recipient": endpoints[identities[1]], "message": text,
        }, (identities[0], "boundary-turn")))
        assert "error" in refused
    assert bridge._connection is current and len(joined.stdio_contexts) == 2
    assert client.get("/dashboard/api/relay/messages", params=scope).json()["total"] == 2


def test_bridge_concurrent_failed_recovery_is_one_attempt_e2e(
    client, joined_bridge_recovery_context, monkeypatch,
):
    joined = joined_bridge_recovery_context
    bridge, scope, identities, endpoints = _bridge_lifecycle_case(client, joined)
    bridge._retire(bridge._connection)
    initializing, waiting = threading.Event(), threading.Event()
    gate = asyncio.Event()
    owner, attempts = [], []
    original_init, usable = ClientSession.initialize, bridge._usable

    async def initialize(session, *args, **kwargs):
        attempts.append(session)
        if len(attempts) == 1:
            owner.append(asyncio.get_running_loop())
            initializing.set()
            await gate.wait()
            raise ClosedResourceError("one failed recovery attempt")
        return await original_init(session, *args, **kwargs)

    def observe(connection):
        if initializing.is_set() and connection is bridge._connection and not connection.ready.is_set():
            waiting.set()
        return usable(connection)

    monkeypatch.setattr(ClientSession, "initialize", initialize)
    monkeypatch.setattr(bridge, "_usable", observe)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(_bridge_address, bridge, identities[0])
        try:
            assert initializing.wait(3)
            second = pool.submit(_bridge_address, bridge, identities[1])
            assert waiting.wait(3)
            owner[0].call_soon_threadsafe(gate.set)
            assert "error" in first.result(timeout=5)
            assert "error" in second.result(timeout=5)
        finally:
            if owner and not owner[0].is_closed():
                owner[0].call_soon_threadsafe(gate.set)
    assert len(attempts) == 1 and len(joined.stdio_contexts) == 2
    assert not joined.sdk_calls
    assert _bridge_address(bridge, identities[1])["exact_selector"] == endpoints[identities[1]]
    assert len(attempts) == 2 and len(joined.stdio_contexts) == 3


def test_bridge_recovery_snapshots_private_reply_before_waiting_e2e(
    client, joined_bridge_recovery_context, monkeypatch,
):
    joined = joined_bridge_recovery_context
    bridge, scope, identities, endpoints = _bridge_lifecycle_case(client, joined)
    sent = client.post("/relay/messages", json={
        "sender_runtime": "hermes", "sender_session_ref": identities[0],
        "recipient": endpoints[identities[1]], "payload": "question", **scope,
    })
    assert sent.status_code == 200
    received = client.post("/relay/turn", json={
        "runtime": "hermes", "session_ref": identities[1], "max_messages": 1, **scope,
    })
    assert received.status_code == 200 and len(received.json()["deliveries"]) == 1
    delivery = received.json()["deliveries"][0]
    arguments = {"delivery_id": delivery["delivery_id"], "message": "réponse 调用"}
    private = {"delivery_id": delivery["delivery_id"], "receipt": delivery["receipt"]}
    expected_private = dict(private)
    bridge._retire(bridge._connection)
    captured, release = threading.Event(), threading.Event()
    original_get = bridge._get_connection

    def wait_after_snapshot():
        captured.set()
        assert release.wait(3)
        return original_get()

    monkeypatch.setattr(bridge, "_get_connection", wait_after_snapshot)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(bridge.call, "pallium_relay_reply", arguments,
                             (identities[1], "reply-שלום"), private)
        try:
            assert captured.wait(3)
            arguments.update(delivery_id="wrong-delivery", message="wrong message")
            private.update(delivery_id="wrong-private", receipt="wrong-receipt")
            release.set()
            result = json.loads(future.result(timeout=10))
        finally:
            release.set()
    assert "message_id" in result, result
    assert joined.sdk_calls[-1]["metadata"] == _identity(identities[1], "reply-שלום", reply=expected_private)
    stored = client.get(f"/relay/messages/{result['message_id']}", params=scope)
    assert stored.status_code == 200 and stored.json()["payload"] == "réponse 调用"
    original = client.get(f"/relay/messages/{sent.json()['message_id']}", params=scope)
    assert original.json()["deliveries"][0]["state"] == "delivered"
    assert len([path for path, _ in joined.http_calls if path == "/relay/replies"]) == 1
    assert len(joined.stdio_contexts) == 2


def test_bridge_late_old_failure_cannot_retire_successor_e2e(
    client, joined_bridge_recovery_context, monkeypatch,
):
    joined = joined_bridge_recovery_context
    bridge, scope, identities, endpoints = _bridge_lifecycle_case(client, joined)
    old = bridge._connection
    forward, retire = ClientSession.call_tool, bridge._retire
    entered, release = threading.Event(), threading.Event()

    async def fail_old(session, name, arguments=None, **kwargs):
        if session is old.session:
            raise ClosedResourceError("old connection")
        return await forward(session, name, arguments=arguments, **kwargs)

    def delayed_retire(connection):
        if connection is old and threading.current_thread().name.startswith("stale-caller"):
            entered.set()
            assert release.wait(5)
        retire(connection)

    monkeypatch.setattr(ClientSession, "call_tool", fail_old)
    monkeypatch.setattr(bridge, "_retire", delayed_retire)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="stale-caller") as pool:
        stale = pool.submit(_bridge_address, bridge, identities[0], "old-turn")
        try:
            assert entered.wait(3)
            assert _bridge_address(bridge, identities[1], "new-turn")["exact_selector"] == endpoints[identities[1]]
            successor = bridge._connection
            release.set()
            assert "may have committed" in stale.result(timeout=3)["error"]
        finally:
            release.set()
    assert _bridge_address(bridge, identities[0], "still-new")["exact_selector"] == endpoints[identities[0]]
    assert bridge._connection is successor and not successor.retired.is_set()
    assert len(joined.stdio_contexts) == 2


def test_bridge_unresolved_cleanup_fences_replacement_until_owned_exit_e2e(
    client, joined_bridge_recovery_context, monkeypatch,
):
    joined = joined_bridge_recovery_context
    bridge, scope, identities, endpoints = _bridge_lifecycle_case(client, joined)
    old = bridge._connection
    original_exit = ClientSession.__aexit__
    entered = threading.Event()
    gate = asyncio.Event()

    async def delayed_exit(session, *failure):
        if session is old.session:
            entered.set()
            await gate.wait()
        return await original_exit(session, *failure)

    monkeypatch.setattr(ClientSession, "__aexit__", delayed_exit)
    bridge._retire(old)
    try:
        assert entered.wait(3)
        # Simulate a bounded join expiring, without spending ten seconds per case.
        with monkeypatch.context() as bounded:
            bounded.setattr(old.thread, "join", lambda timeout: None)
            result = _bridge_address(bridge, identities[0])
        assert "owned cleanup" in result["error"]
        assert bridge._connection is old and len(joined.stdio_contexts) == 1
        assert not old.finished.is_set() and not joined.sdk_calls
    finally:
        old.loop.call_soon_threadsafe(gate.set)
        old.thread.join(timeout=3)
    assert old.finished.is_set() and not old.cleanup_failed
    assert _bridge_address(bridge, identities[1])["exact_selector"] == endpoints[identities[1]]
    assert len(joined.stdio_contexts) == 2


def test_bridge_cleanup_failure_remains_fail_closed_and_retains_primary_e2e(
    client, joined_bridge_recovery_context, monkeypatch,
):
    joined = joined_bridge_recovery_context
    bridge, scope, identities, endpoints = _bridge_lifecycle_case(client, joined)
    old = bridge._connection
    original_init, original_exit = ClientSession.initialize, ClientSession.__aexit__

    async def startup_failure(session, *args, **kwargs):
        await original_init(session, *args, **kwargs)
        raise ValueError("private primary startup detail")

    async def cleanup_failure(session, *failure):
        result = await original_exit(session, *failure)
        if session is not old.session:
            raise RuntimeError("private cleanup detail")
        return result

    monkeypatch.setattr(ClientSession, "initialize", startup_failure)
    monkeypatch.setattr(ClientSession, "__aexit__", cleanup_failure)
    bridge._retire(old)
    result = _bridge_address(bridge, identities[0])
    failed = bridge._connection
    assert "error" in result and "private" not in result["error"]
    assert failed.cleanup_failed and isinstance(failed.failure, BaseExceptionGroup)
    assert len(failed.failure.exceptions) == 2
    assert "error" in _bridge_address(bridge, identities[1])
    assert bridge._connection is failed and len(joined.stdio_contexts) == 2
    assert all(entry.exited for entry in [*joined.sessions, *joined.stdio_contexts])
    assert not joined.sdk_calls
    with pytest.raises(RuntimeError, match="cleanup"):
        bridge.close()
    joined.expected_close_failures.add(bridge)


@pytest.mark.parametrize("phase", ["call", "recovery"])
def test_bridge_close_during_work_is_terminal_and_disposes_owners_e2e(
    client, joined_bridge_recovery_context, monkeypatch, phase,
):
    joined = joined_bridge_recovery_context
    bridge, scope, identities, endpoints = _bridge_lifecycle_case(client, joined)
    entered, closing = threading.Event(), threading.Event()
    gate = asyncio.Event()
    old = bridge._connection
    original_init, original_call, original_retire = ClientSession.initialize, ClientSession.call_tool, bridge._retire
    owner = []

    async def initialize(session, *args, **kwargs):
        result = await original_init(session, *args, **kwargs)
        if phase == "recovery":
            owner.append(asyncio.get_running_loop())
            entered.set()
            await gate.wait()
        return result

    async def call(session, name, arguments=None, **kwargs):
        result = await original_call(session, name, arguments=arguments, **kwargs)
        if phase == "call":
            owner.append(asyncio.get_running_loop())
            entered.set()
            await gate.wait()
        return result

    def retire(connection):
        original_retire(connection)
        if bridge._closed:
            closing.set()

    monkeypatch.setattr(ClientSession, "initialize", initialize)
    monkeypatch.setattr(ClientSession, "call_tool", call)
    monkeypatch.setattr(bridge, "_retire", retire)
    if phase == "recovery":
        bridge._retire(old)
    with ThreadPoolExecutor(max_workers=2) as pool:
        invocation = pool.submit(_bridge_address, bridge, identities[0])
        try:
            assert entered.wait(3)
            close = pool.submit(bridge.close)
            assert closing.wait(3)
            owner[0].call_soon_threadsafe(gate.set)
            result = invocation.result(timeout=5)
            close.result(timeout=5)
        finally:
            if owner and not owner[0].is_closed():
                owner[0].call_soon_threadsafe(gate.set)
    if phase == "recovery":
        assert "error" in result and not joined.sdk_calls
    else:
        assert result.get("exact_selector") == endpoints[identities[0]] or "may have committed" in result["error"]
    count = len(joined.stdio_contexts)
    bridge.close()
    assert "error" in _bridge_address(bridge, identities[1])
    assert len(joined.stdio_contexts) == count
    assert all(entry.exited for entry in [*joined.sessions, *joined.stdio_contexts])
    assert all(process.returncode is not None for process in joined.processes)


def test_default_server_registration_is_unchanged() -> None:
    names = {tool.name for tool in asyncio.run(create_server().list_tools())}
    assert "pallium_query" in names
    assert "pallium_relay_receive" in names


def test_hermes_memory_catalog_is_explicitly_opt_in() -> None:
    kwargs = {
        "base_url": "http://127.0.0.1:19836",
        "container_ref": "git:test/hermes",
        "actor_ref": "hermes-test-actor",
    }
    off = {tool.name for tool in asyncio.run(create_hermes_server(**kwargs).list_tools())}
    on = {tool.name for tool in asyncio.run(create_hermes_server(**kwargs, memory_enabled=True).list_tools())}
    assert off == set(HERMES_TOOLS)
    assert on == set(HERMES_TOOLS | HERMES_MEMORY_TOOLS)
    assert "pallium_query_debug" not in on and "pallium_status" not in on


def test_hermes_source_forget_accepts_an_explicit_historical_target_thread() -> None:
    context = PalliumContext(
        base_url="http://127.0.0.1:19836", container_ref="git:test/hermes",
        actor_ref="hermes-test-actor", agent_ref="hermes", visibility="private",
    )
    seen = {}

    def handler(**kwargs):
        seen.update(kwargs)
        return "ok"

    adapter = make_tool_adapter(context, memory_enabled=True)
    guarded = adapter("pallium_forget_source", handler, lambda: type(
        "RequestContext", (), {"request_context": type("Meta", (), {"meta": _identity("active-session")})()}
    )())
    assert guarded is not None
    assert asyncio.run(guarded(reason="requested", thread_ref="prior-session")) == "ok"
    assert seen["thread_ref"] == "prior-session"


def test_mutation_target_scope_requires_an_active_hermes_request() -> None:
    context = PalliumContext(
        base_url="http://127.0.0.1:19836", container_ref="git:test/hermes",
        actor_ref="hermes-test-actor", visibility="private",
    )
    assert PalliumMcpClient(context)._hermes_target_scope() is None


async def _exercise_memory_stdio(base_url: str, *, source_item_id: str, visible_memories: list[str], foreign_memory: str) -> None:
    repo = str(Path(__file__).resolve().parents[1])
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (repo, env.get("PYTHONPATH"))))
    params = StdioServerParameters(
        command=os.sys.executable,
        args=["-m", "app.mcp.hermes", "--base-url", base_url,
              "--container-ref", "git:test/hermes", "--actor-ref", "hermes-test-actor",
              "--visibility", "private", "--memory-enabled"],
        env=env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            names = {tool.name for tool in (await session.list_tools()).tools}
            assert names == HERMES_TOOLS | HERMES_MEMORY_TOOLS

            before = len(_RelayHandler.calls)
            refused = await session.call_tool(
                "pallium_remember",
                {"text": "must not persist", "type": "note", "actor_ref": "forged-actor"},
                meta=_identity("memory-session", "turn-refused"),
            )
            assert refused.isError
            assert len(_RelayHandler.calls) == before
            forged_flag = await session.call_tool(
                "pallium_flag_memory",
                {"memory_object_id": "unknown", "reason": "test", "source_ref": "forged-actor"},
                meta=_identity("memory-session", "turn-forged-flag"),
            )
            assert forged_flag.isError
            assert len(_RelayHandler.calls) == before

            remembered = await session.call_tool(
                "pallium_remember", {"text": "bounded Hermes memory marker", "type": "note"},
                meta=_identity("memory-session", "turn-remember"),
            )
            assert not remembered.isError, [item.text for item in remembered.content if hasattr(item, "text")]
            memory = json.loads(remembered.content[0].text)
            memory_id = memory["memory_object_id"]

            queried = await session.call_tool(
                "pallium_query", {"query": "bounded Hermes memory marker"},
                meta=_identity("memory-session", "turn-query"),
            )
            assert not queried.isError
            expanded = await session.call_tool(
                "pallium_expand", {"memory_object_id": memory_id},
                meta=_identity("memory-session", "turn-expand"),
            )
            assert not expanded.isError
            assert "error" not in json.loads(expanded.content[0].text)
            for visible_memory in visible_memories:
                expanded_visible = await session.call_tool(
                    "pallium_expand", {"memory_object_id": visible_memory},
                    meta=_identity("memory-session", "turn-expand-visible"),
                )
                assert not expanded_visible.isError
                assert "error" not in json.loads(expanded_visible.content[0].text)
            refused_foreign = await session.call_tool(
                "pallium_expand", {"memory_object_id": foreign_memory},
                meta=_identity("memory-session", "turn-expand-foreign"),
            )
            assert "error" in json.loads(refused_foreign.content[0].text)
            source_expanded = await session.call_tool(
                "pallium_expand_source", {
                    "source_item_id": source_item_id, "include_supported_memories": True,
                }, meta=_identity("memory-session", "turn-expand-supported"),
            )
            assert not source_expanded.isError
            corrected = await session.call_tool(
                "pallium_correct", {"memory_object_id": memory_id,
                                     "corrected_text": "corrected bounded marker", "reason": "test"},
                meta=_identity("memory-session", "turn-correct"),
            )
            assert not corrected.isError
            forgotten = await session.call_tool(
                "pallium_forget", {"memory_object_id": memory_id, "reason": "test"},
                meta=_identity("memory-session", "turn-forget"),
            )
            assert not forgotten.isError
            historical_forget = await session.call_tool(
                "pallium_forget_source", {"reason": "test", "thread_ref": "prior-session"},
                meta=_identity("memory-session", "turn-forget-source"),
            )
            assert not historical_forget.isError
            omitted_target_forget = await session.call_tool(
                "pallium_forget_source", {"reason": "test"},
                meta=_identity("memory-session", "turn-forget-source-omitted"),
            )
            assert not omitted_target_forget.isError


def test_hermes_opt_in_memory_stdio_reuses_scoped_memory_handlers(client) -> None:
    _RelayHandler.client = client
    _RelayHandler.calls = []
    source = client.post("/items", json=[{
        "source_type": "hermes", "source_id": "hermes-old-source",
        "content_type": "text/plain", "content": "private old session source",
        "role": "assistant", "agent_ref": "hermes", "container_ref": "git:test/hermes",
        "thread_ref": "prior-session", "actor_ref": "hermes-test-actor",
        "visibility": "private", "artifact_kind": "message",
    }])
    assert source.status_code == 200, source.text
    source_item_id = source.json()[0]["source_item_id"]
    memory_ids = []
    for container, actor, visibility in (
        ("git:test/hermes", "other-actor", "private"),
        ("git:test/other", "hermes-test-actor", "global"),
        ("git:test/other", "other-actor", "global"),
    ):
        stored = client.post("/memory/remember", json={
            "text": "visibility fixture ✓", "type": "note", "container_ref": container,
            "actor_ref": actor, "visibility": visibility, "thread_ref": "prior-session", "agent_ref": "test-agent",
        })
        assert stored.status_code == 200, stored.text
        memory_ids.append(stored.json()["memory_object_id"])
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RelayHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        asyncio.run(_exercise_memory_stdio(
            f"http://127.0.0.1:{server.server_port}", source_item_id=source_item_id,
            visible_memories=memory_ids[:2], foreign_memory=memory_ids[2],
        ))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    remember = next(payload for path, payload in _RelayHandler.calls if path == "/memory/remember")
    assert {key: remember[key] for key in ("container_ref", "actor_ref", "thread_ref", "agent_ref", "visibility")} == {
        "container_ref": "git:test/hermes", "actor_ref": "hermes-test-actor",
        "thread_ref": "memory-session", "agent_ref": "hermes", "visibility": "private",
    }
    assert all("request_source_item_id" not in payload for path, payload in _RelayHandler.calls if path in {"/memory/remember", "/items"})
    scoped_mutations = [payload for path, payload in _RelayHandler.calls
                        if path.endswith("/correct") or path.endswith("/forget") or path == "/source/forget"]
    assert scoped_mutations
    assert all(payload["target_scope"] == {
        "container_ref": "git:test/hermes", "actor_ref": "hermes-test-actor", "visibility": "private",
    } for payload in scoped_mutations)
    source_forgets = [payload for path, payload in _RelayHandler.calls if path == "/source/forget"]
    assert source_forgets[0]["thread_ref"] == "prior-session"
    assert "thread_ref" not in source_forgets[1]
    query_params = next(query for path, query in _RelayHandler.calls if path == "/query")
    assert query_params["actor_ref"] == "hermes-test-actor"
    expand_params = next(query for path, query in _RelayHandler.calls if path.startswith("/memory/") and path.endswith("/expand"))
    assert expand_params["query_visibility"] == ["private"]
    assert expand_params["query_actor_ref"] == ["hermes-test-actor"]
    source_expand_params = next(query for path, query in _RelayHandler.calls if path.startswith(f"/source/{source_item_id}/context"))
    assert source_expand_params["include_supported_memories"] == ["true"]
    assert source_expand_params["query_visibility"] == ["private"]


async def _exercise_hermes_memory_lifecycle(
    base_url: str, foreign_memory_id: str, scratch_path: Path,
) -> None:
    repo = str(Path(__file__).resolve().parents[1])
    scratch = scratch_path.resolve()
    isolated_dirs = {
        "HOME": scratch / "home",
        "USERPROFILE": scratch / "user-profile",
        "APPDATA": scratch / "app-data",
        "LOCALAPPDATA": scratch / "local-app-data",
        "XDG_CONFIG_HOME": scratch / "xdg-config",
        "XDG_CACHE_HOME": scratch / "xdg-cache",
        "XDG_DATA_HOME": scratch / "xdg-data",
        "TMP": scratch / "tmp",
        "TEMP": scratch / "temp",
        "TMPDIR": scratch / "tmpdir",
    }
    for path in isolated_dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    env = {
        key: os.environ[key]
        for key in ("SYSTEMROOT", "WINDIR", "PATH")
        if os.environ.get(key)
    }
    env.update({key: str(path) for key, path in isolated_dirs.items()})
    env["PYTHONPATH"] = repo
    params = StdioServerParameters(
        command=os.sys.executable,
        args=[
            "-m", "app.mcp.hermes", "--base-url", base_url,
            "--container-ref", "git:test/hermes", "--actor-ref", "hermes-test-actor",
            "--visibility", "private", "--memory-enabled",
        ],
        env=env,
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def call(name: str, arguments: dict, session_id: str) -> dict:
                result = await session.call_tool(
                    name, arguments, meta=_identity(session_id, f"turn-{name}-{session_id}"),
                )
                if result.isError:
                    pytest.fail(f"{name} failed: {[item.text for item in result.content if hasattr(item, 'text')]}")
                return json.loads(result.content[0].text)

            remembered = await call("pallium_remember", {
                "text": "Quartz lantern remains in vault", "type": "decision",
            }, "write-session")
            first_id = remembered["memory_object_id"]

            async def recalled(query: str) -> list[dict]:
                return (await call("pallium_query", {"query": query}, "later-session"))["results"]

            assert [hit["memory_object_id"] for hit in await recalled("quartz lantern")] == [first_id]
            await call("pallium_correct", {
                "memory_object_id": first_id,
                "corrected_text": "Opal compass stays in archive", "reason": "updated",
            }, "later-session")
            assert [hit["memory_object_id"] for hit in await recalled("opal compass")] == [first_id]
            assert await recalled("quartz lantern") == []

            second_id = (await call("pallium_supersede", {
                "new_text": "Amber map stays in catalog", "supersedes_id": first_id,
            }, "later-session"))["new_memory_object_id"]
            third_id = (await call("pallium_supersede", {
                "new_text": "Cobalt key stays in cabinet", "supersedes_id": second_id,
            }, "third-session"))["new_memory_object_id"]
            assert [hit["memory_object_id"] for hit in await recalled("cobalt key")] == [third_id]
            assert await recalled("amber map") == []
            forgotten = await call("pallium_forget", {
                "memory_object_id": third_id, "reason": "removed",
            }, "later-session")
            assert forgotten["forgotten"] is True
            assert await recalled("cobalt key") == []

            foreign = await call("pallium_expand", {
                "memory_object_id": foreign_memory_id,
            }, "later-session")
            assert "error" in foreign
            conflicting_scope = await session.call_tool(
                "pallium_query", {"query": "cobalt key", "container_ref": "git:test/other"},
                meta=_identity("later-session", "turn-conflicting-scope"),
            )
            assert conflicting_scope.isError


def test_dedicated_hermes_mcp_memory_lifecycle_uses_fixed_scope(client, tmp_path: Path) -> None:
    _RelayHandler.client = client
    _RelayHandler.calls = []
    foreign = client.post("/memory/remember", json={
        "text": "Foreign container must remain hidden", "type": "decision",
        "container_ref": "git:test/other", "actor_ref": "hermes-test-actor",
        "thread_ref": "foreign-session", "agent_ref": "hermes", "visibility": "private",
    })
    assert foreign.status_code == 200, foreign.text

    server = ThreadingHTTPServer(("127.0.0.1", 0), _RelayHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        asyncio.run(_exercise_hermes_memory_lifecycle(
            f"http://127.0.0.1:{server.server_port}",
            foreign.json()["memory_object_id"], tmp_path / "hermes-mcp-scratch",
        ))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    remember = next(payload for path, payload in _RelayHandler.calls if path == "/memory/remember")
    assert {key: remember[key] for key in (
        "container_ref", "actor_ref", "thread_ref", "agent_ref", "visibility",
    )} == {
        "container_ref": "git:test/hermes", "actor_ref": "hermes-test-actor",
        "thread_ref": "write-session", "agent_ref": "hermes", "visibility": "private",
    }
    query_calls = [payload for path, payload in _RelayHandler.calls if path == "/query"]
    assert query_calls and all(payload["container_ref"] == "git:test/hermes" for payload in query_calls)
    assert all(payload["actor_ref"] == "hermes-test-actor" for payload in query_calls)


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
            before_memory_opt_in = len(_RelayHandler.calls)
            memory_opt_in = await session.call_tool(
                "pallium_expand_source",
                {"source_item_id": expected_ids["actor_a"], "include_supported_memories": True},
                meta=_identity("later-session", "turn-memory-refusal"),
            )
            assert memory_opt_in.isError
            assert len(_RelayHandler.calls) == before_memory_opt_in

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
