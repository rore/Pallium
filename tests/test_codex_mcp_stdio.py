"""Real stdio MCP coverage for per-request Codex task identity."""

from __future__ import annotations

import asyncio
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

pytest.importorskip("mcp")
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


class _RelayHandler(BaseHTTPRequestHandler):
    calls: list[tuple[str, dict]] = []
    deliveries = {
        "thread-session": ("d-thread", "r-thread"),
        "任务-α": ("d-unicode", "r-unicode"),
    }
    acked: set[str] = set()

    def do_POST(self) -> None:  # noqa: N802
        size = int(self.headers.get("content-length", "0"))
        payload = json.loads(self.rfile.read(size) or b"{}")
        self.calls.append((self.path, payload))
        if self.path == "/relay/turn":
            delivery = self.deliveries.get(payload.get("session_ref"))
            if delivery is None or delivery[0] in self.acked:
                body = {"deliveries": []}
            else:
                delivery_id, receipt = delivery
                body = {
                    "deliveries": [
                        {
                            "delivery_id": delivery_id,
                            "receipt": receipt,
                            "payload": f"only {payload['session_ref']}",
                        }
                    ]
                }
        elif self.path == "/relay/deliveries/mcp-ack":
            match = next(
                (
                    pair
                    for pair in self.deliveries.values()
                    if pair
                    == (payload.get("delivery_id"), payload.get("receipt"))
                ),
                None,
            )
            if match is None:
                body = {"already_delivered": True}
            else:
                self.acked.add(match[0])
                body = {"already_delivered": False}
        else:
            body = {"error": "unexpected path"}
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *_args) -> None:
        return


async def _exercise_child(
    env: dict[str, str], endpoint: str
) -> tuple[list[str], str]:
    params = StdioServerParameters(
        command=env["PYTHON"],
        args=["-m", "app.run", "mcp"],
        env={**env, "PALLIUM_BASE_URL": endpoint},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            receive_schema = next(
                tool
                for tool in tools.tools
                if tool.name == "pallium_relay_receive"
            ).inputSchema
            properties = receive_schema.get("properties", {})
            assert not {
                "thread_ref",
                "session_ref",
                "request_ctx",
            } & set(properties)

            cases = [
                (
                    {
                        "threadId": "thread-session",
                        "x-codex-turn-metadata": {
                            "thread_id": "thread-session",
                            "session_id": "thread-session",
                        },
                    },
                    "thread-session",
                    "d-thread",
                    "r-thread",
                ),
                (
                    {
                        "x-codex-turn-metadata": {
                            "session_id": "任务-α",
                        }
                    },
                    "任务-α",
                    "d-unicode",
                    "r-unicode",
                ),
            ]
            for meta, session_ref, delivery_id, receipt in cases:
                received = await session.call_tool(
                    "pallium_relay_receive", {}, meta=meta
                )
                result = json.loads(received.content[0].text)
                assert [item["payload"] for item in result["deliveries"]] == [
                    f"only {session_ref}"
                ]
                acknowledged = await session.call_tool(
                    "pallium_relay_ack",
                    {"delivery_id": delivery_id, "receipt": receipt},
                )
                assert json.loads(acknowledged.content[0].text) == {
                    "already_delivered": False
                }

            unknown = await session.call_tool(
                "pallium_relay_receive",
                {},
                meta={
                    "unknown": "ignored",
                    "threadId": "thread-session",
                },
            )
            assert json.loads(unknown.content[0].text)["deliveries"] == []

            max_session = "ü" * 255
            maximum = await session.call_tool(
                "pallium_relay_receive",
                {},
                meta={"threadId": max_session},
            )
            assert json.loads(maximum.content[0].text)["deliveries"] == []

            calls_before_errors = len(_RelayHandler.calls)
            invalid = [
                {},
                {
                    "threadId": "a",
                    "x-codex-turn-metadata": {"thread_id": "b"},
                },
                {"threadId": 7},
                {"threadId": ""},
                {"threadId": " leading-space"},
                {"threadId": "line\nbreak"},
                {"threadId": "x" * 256},
                {"x-codex-turn-metadata": []},
            ]
            errors = [
                (
                    await session.call_tool(
                        "pallium_relay_receive", {}, meta=meta
                    )
                ).content[0].text
                for meta in invalid
            ]
            assert len(_RelayHandler.calls) == calls_before_errors
            return errors, max_session


def test_codex_stdio_metadata_identity() -> None:
    repo = str(Path(__file__).resolve().parents[1])
    base = os.environ.copy()
    base.update(
        {
            "PYTHON": os.sys.executable,
            "PYTHONPATH": os.pathsep.join(
                filter(None, (repo, os.environ.get("PYTHONPATH")))
            ),
            "PALLIUM_MCP_TRANSPORT": "stdio",
            "PALLIUM_AGENT_REF": "codex",
            "PALLIUM_CONTAINER_REF": "git:test/codex-mcp",
            "PALLIUM_ACTOR_REF": "test-actor",
            "PALLIUM_THREAD_REF": "wrong-pallium-thread",
            "CODEX_THREAD_ID": "wrong-outer-thread",
            "CODEX_SESSION_ID": "wrong-outer-session",
        }
    )
    server = HTTPServer(("127.0.0.1", 0), _RelayHandler)
    _RelayHandler.calls = []
    _RelayHandler.acked = set()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        errors, max_session = asyncio.run(
            _exercise_child(
                base, f"http://127.0.0.1:{server.server_port}"
            )
        )
    finally:
        server.shutdown()
        server.server_close()

    assert all(result.startswith("Error:") for result in errors)
    turns = [
        payload
        for path, payload in _RelayHandler.calls
        if path == "/relay/turn"
    ]
    assert [payload["session_ref"] for payload in turns] == [
        "thread-session",
        "任务-α",
        "thread-session",
        max_session,
    ]
    assert not {
        "wrong-pallium-thread",
        "wrong-outer-thread",
        "wrong-outer-session",
    } & {payload["session_ref"] for payload in turns}
    assert (
        len(
            [
                1
                for path, _ in _RelayHandler.calls
                if path == "/relay/deliveries/mcp-ack"
            ]
        )
        == 2
    )
    assert all(
        payload["runtime"] == "codex"
        and payload["container_ref"] == "git:test/codex-mcp"
        and payload["actor_ref"] == "test-actor"
        for path, payload in _RelayHandler.calls
        if path == "/relay/turn"
    )