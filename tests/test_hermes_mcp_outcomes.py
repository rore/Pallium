"""Definite Relay refusals and uncertain commits through Hermes tools, stdio and HTTP."""
from __future__ import annotations

import asyncio
import json
import sys
import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from app.mcp.context import PalliumContext
from app.mcp.hermes import make_tool_adapter
from integrations.hermes.mcp_bridge import RelayMcpBridge, _tool_response_text
from tests.test_hermes_bridge import _Wire
from tests.test_hermes_mcp import _RelayHandler
from tests.test_hermes_project_scope import _project, _repo, _sessions, project_plugin
from tests.test_hermes_relay_plugin import _mcp_tool, plugin_context


@pytest.mark.parametrize("status", [404, 409, 422])
def test_only_known_relay_mutation_refusals_are_marked(status):
    from mcp.server.fastmcp.exceptions import ToolError

    context = PalliumContext(base_url="http://127.0.0.1:1", container_ref="git:test/project",
                             actor_ref="actor", agent_ref="hermes", visibility="private")
    request = SimpleNamespace(request_context=SimpleNamespace(meta={
        "pallium_hermes": {"session_id": "session", "turn_id": "turn"},
    }))
    adapter = make_tool_adapter(context, memory_enabled=True)

    for tool, payload, marked in [
        ("pallium_relay_send", {"error": "refused", "status_code": status}, True),
        ("pallium_relay_reply", {"error": "refused", "status_code": status}, True),
        ("pallium_relay_name", {"error": "refused", "status_code": status}, True),
        ("pallium_relay_attach_work_ref", {"error": "refused", "status_code": status}, True),
        ("pallium_relay_detach_work_ref", {"error": "refused", "status_code": status}, True),
        ("pallium_remember", {"error": "refused", "status_code": status}, False),
        ("pallium_relay_status", {"error": "refused", "status_code": status}, False),
        ("pallium_relay_send", {"error": "unknown", "status_code": 500}, False),
        ("pallium_relay_send", {"error": "unknown", "status_code": str(status)}, False),
        ("pallium_relay_send", {"error": "unknown", "status_code": status, "extra": True}, False),
        ("pallium_relay_send", {"error": {}, "status_code": status}, False),
        ("pallium_relay_send", {"error": "transport_timeout"}, False),
        ("pallium_relay_send", "Error executing tool: refusal", False),
    ]:
        async def handler(sender_runtime=None, sender_session_ref=None, delivery_id=None, receipt=None,
                          current_runtime=None, current_session_ref=None, **kwargs):
            raise ToolError(json.dumps(payload) if isinstance(payload, dict) else payload)

        guarded = adapter(tool, handler, lambda: request)
        args = {"sender_runtime": "hermes", "sender_session_ref": "session"} if tool == "pallium_relay_send" else {}
        if tool == "pallium_relay_name":
            args = {"current_runtime": "hermes", "current_session_ref": "session"}
        if tool == "pallium_relay_reply":
            request.request_context.meta["pallium_hermes"]["reply"] = {"delivery_id": "delivery", "receipt": "receipt"}
            args = {"delivery_id": "delivery"}
        else:
            request.request_context.meta["pallium_hermes"].pop("reply", None)
        if marked:
            result = asyncio.run(guarded(**args))
            outcome = json.loads(_tool_response_text(result))
            assert outcome["operation_uncertain"] is False
            assert "refused" in outcome["error"]
        else:
            with pytest.raises(ToolError):
                asyncio.run(guarded(**args))


@pytest.mark.parametrize("meta", [None, {}, {"pallium_hermes": {"operation_uncertain": 0}},
                                  {"pallium_hermes": {"operation_uncertain": "false"}},
                                  {"pallium_hermes": {"operation_uncertain": False}, "extra": True}])
def test_bridge_keeps_untrusted_error_metadata_uncertain(meta):
    outcome = json.loads(_tool_response_text(_Wire({
        "isError": True, "content": [{"type": "text", "text": "private-receipt"}], "_meta": meta,
    })))
    assert outcome["operation_uncertain"] is True
    assert "private-receipt" not in outcome["error"]


def test_own_predispatch_refusal_is_definite_but_malformed_marked_response_is_not():
    context = PalliumContext(base_url="http://127.0.0.1:1", container_ref="git:test/project", actor_ref="actor")

    async def handler():
        pytest.fail("invalid metadata reached the handler")

    guarded = make_tool_adapter(context)("pallium_relay_address", handler,
                                        lambda: SimpleNamespace(request_context=SimpleNamespace(meta={})))
    result = asyncio.run(guarded())
    assert json.loads(_tool_response_text(result))["operation_uncertain"] is False
    malformed = result.model_dump(mode="json", by_alias=True)
    malformed["content"] = [{"type": "image", "data": "private"}]
    assert json.loads(_tool_response_text(_Wire(malformed)))["operation_uncertain"] is True


@pytest.fixture
def real_project_bridge(client, project_plugin, monkeypatch):
    module, _ctx, pre, create, _calls, settings = project_plugin

    class Handler(_RelayHandler):
        calls = []
        committed = []
        mcp_results = []
        lose_response = False
        lock = threading.Lock()

        def _write_response(self, response):
            if self.path == "/relay/messages" and self.lose_response and response.status_code == 200:
                self.committed.append(response.json())
                raw = b'{"detail":"unknown response after persistence"}'
                self.send_response(500)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return
            super()._write_response(response)

    Handler.client = client
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    settings["service_url"] = f"http://127.0.0.1:{server.server_port}"
    def observe(result):
        Handler.mcp_results.append(result.model_dump(mode="json", by_alias=True))
        return _tool_response_text(result)

    monkeypatch.setattr(sys.modules[RelayMcpBridge.__module__], "_tool_response_text", observe)
    monkeypatch.setattr(sys.modules[module.__name__ + ".mcp_bridge"], "RelayMcpBridge", RelayMcpBridge)
    ctx = create()
    try:
        yield ctx, pre, create, Handler
    finally:
        for cleanup in ctx.cleanups:
            cleanup()
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


@pytest.mark.parametrize("refusal", ["missing", "closed", "invalid"])
def test_stdio_refused_send_allows_corrected_send_and_new_project_turn(client, real_project_bridge, tmp_path, refusal):
    ctx, pre, _create, handler = real_project_bridge
    a, b = _repo(tmp_path, "a"), _repo(tmp_path, "b")
    assert pre(str(a), turn="first", context=ctx)
    peer = client.post("/relay/turn", json={"runtime": "codex", "session_ref": "peer",
                                          "container_ref": _project("a")}).json()["session"]
    recipient = peer["endpoint_id"]
    if refusal == "missing":
        recipient = "relay-session-" + "0" * 32
    elif refusal == "closed":
        assert client.post("/relay/sessions/close", json={"runtime": "codex", "session_ref": "peer",
                                                        "container_ref": _project("a")}).status_code == 200
    else:
        recipient = "bare-runtime"
    refused = json.loads(_mcp_tool(ctx, "pallium_relay_send", {"recipient": recipient, "message": "refused café"},
                                   session="session", turn="first"))
    assert refused["operation_uncertain"] is False, handler.mcp_results
    assert handler.mcp_results[-1]["_meta"] == {"pallium_hermes": {"operation_uncertain": False}}
    if refusal == "closed":
        peer = client.post("/relay/turn", json={"runtime": "codex", "session_ref": "peer",
                                              "container_ref": _project("a")}).json()["session"]
    sent = json.loads(_mcp_tool(ctx, "pallium_relay_send", {"recipient": peer["endpoint_id"], "message": "corrected 任务"},
                                session="session", turn="first"))
    assert "message_id" in sent, sent
    assert pre(str(b), turn="next", context=ctx)
    after = json.loads(_mcp_tool(ctx, "pallium_relay_send", {"recipient": peer["endpoint_id"], "message": "new project turn"},
                                 session="session", turn="next"))
    assert "message_id" in after, after
    calls = [body for path, body in handler.calls if path == "/relay/messages"]
    assert len(calls) == 3
    assert [body["container_ref"] for body in calls] == [_project("a"), _project("a"), _project("b")]
    for result, project in [(sent, "a"), (after, "b")]:
        status = client.get("/relay/messages/" + result["message_id"], params={"container_ref": _project(project)})
        assert status.status_code == 200
        assert status.json()["payload"] == result["payload"]
        assert status.json()["deliveries"][0]["state"] == "pending"


def test_stdio_unknown_send_stays_fenced_after_commit_and_reload(client, real_project_bridge, tmp_path):
    ctx, pre, create, handler = real_project_bridge
    a, b = _repo(tmp_path, "a"), _repo(tmp_path, "b")
    assert pre(str(a), turn="first", context=ctx)
    peer = client.post("/relay/turn", json={"runtime": "codex", "session_ref": "peer",
                                          "container_ref": _project("a")}).json()["session"]
    handler.lose_response = True
    args = {"recipient": peer["endpoint_id"], "message": "committed response lost"}
    result = json.loads(_mcp_tool(ctx, "pallium_relay_send", args, session="session", turn="first"))
    assert result["operation_uncertain"] is True
    assert len(handler.committed) == 1
    persisted = client.get("/relay/messages/" + handler.committed[0]["message_id"],
                           params={"container_ref": _project("a")})
    assert persisted.status_code == 200 and persisted.json()["payload"] == args["message"]
    blocked = json.loads(_mcp_tool(ctx, "pallium_relay_send", args, session="session", turn="first"))
    assert "uncertain" in blocked["error"]
    assert len([body for path, body in handler.calls if path == "/relay/messages"]) == 1
    resumed = create(ctx.state)
    try:
        assert pre(str(b), turn="next", context=resumed) is None
        assert _sessions(client, _project("b")) == []
    finally:
        for cleanup in resumed.cleanups:
            cleanup()
