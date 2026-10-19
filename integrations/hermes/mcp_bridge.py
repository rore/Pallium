"""Standard MCP transport owned by the Hermes plugin, never by model arguments."""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
from pathlib import Path
import threading

TOOLS = frozenset("pallium_relay_" + name for name in (
    "address", "recipients", "discover_recipients", "name", "work_refs",
    "attach_work_ref", "detach_work_ref", "participants", "send", "reply", "status", "trace",
))
HIDDEN = {
    "pallium_relay_send": {"sender_runtime", "sender_session_ref"},
    "pallium_relay_name": {"current_runtime", "current_session_ref"},
    "pallium_relay_reply": {"receipt"},
}
TIMEOUT_SECONDS = 15
MAX_RESPONSE_CHARS = 24_000


class RelayMcpBridge:
    """One owned stdio connection; each call carries an explicit immutable scope."""

    def __init__(self, *, python, repo, base_url, container_ref, actor_ref, visibility):
        self.python, self.repo = str(python), str(repo)
        if not Path(self.python).is_file() or not (Path(self.repo) / "app/mcp/hermes.py").is_file():
            raise ValueError("Configure the Pallium MCP interpreter and checkout explicitly")
        self.config = (base_url, container_ref, actor_ref, visibility)
        self.catalog = []
        self._ready, self._finished = threading.Event(), threading.Event()
        self._loop = self._stop = self._session = None
        self._failed = False
        self._thread = threading.Thread(target=self._run, name="pallium-hermes-mcp", daemon=True)
        self._thread.start()
        if not self._ready.wait(TIMEOUT_SECONDS) or self._failed:
            self.close()
            raise ValueError("Pallium MCP could not initialize; check the explicit interpreter and service configuration")

    def _run(self):
        try:
            asyncio.run(self._serve())
        except Exception:
            self._failed = True
            self._ready.set()
        finally:
            self._finished.set()

    async def _serve(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        self._loop, self._stop = asyncio.get_running_loop(), asyncio.Event()
        allowed = {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT", "TEMP", "TMP",
                   "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA"}
        env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
        base, container, actor, visibility = self.config
        params = StdioServerParameters(
            command=self.python, cwd=self.repo, env=env,
            args=["-m", "app.mcp.hermes", "--base-url", base, "--container-ref", container,
                  "--actor-ref", actor, "--visibility", visibility],
        )
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                async with asyncio.timeout(TIMEOUT_SECONDS):
                    await session.initialize()
                    result = await session.list_tools()
                catalog = []
                for tool in result.tools:
                    if tool.name not in TOOLS:
                        raise ValueError("Unexpected tool in the dedicated Hermes MCP catalog")
                    schema = json.loads(json.dumps(tool.input_schema))
                    hidden = {"container_ref"} | HIDDEN.get(tool.name, set())
                    for key in hidden:
                        schema.get("properties", {}).pop(key, None)
                    if "required" in schema:
                        schema["required"] = [key for key in schema["required"] if key not in hidden]
                    schema["additionalProperties"] = False
                    catalog.append({"name": tool.name, "description": tool.description or "",
                                    "parameters": schema})
                if {tool["name"] for tool in catalog} != TOOLS or result.next_cursor:
                    raise ValueError("Incomplete dedicated Hermes MCP catalog")
                self.catalog, self._session = catalog, session
                self._ready.set()
                await self._stop.wait()

    async def _call(self, name, arguments, metadata):
        # Both dictionaries are copied before crossing the loop; no ambient current session.
        result = await self._session.call_tool(name, arguments=arguments, meta=metadata)
        blocks = getattr(result, "content", None)
        if not isinstance(blocks, list) or any(getattr(block, "type", None) != "text" for block in blocks):
            return json.dumps({"error": "Pallium MCP returned an unsupported response"})
        text = "\n".join(block.text for block in blocks)
        if len(text) > MAX_RESPONSE_CHARS:
            return json.dumps({"error": "Pallium MCP response exceeded the supported budget"})
        if result.is_error:
            # Server validation details may include private injected receipts.
            return json.dumps({"error": "Pallium MCP refused the request"})
        return text

    def call(self, name, arguments, identity, reply=None):
        if (name not in TOOLS or self._finished.is_set() or not self._ready.is_set()
                or self._session is None):
            return json.dumps({"error": "Pallium MCP is unavailable"})
        session, turn = identity
        values = json.loads(json.dumps(arguments))
        values["container_ref"] = self.config[1]
        if name == "pallium_relay_send":
            values.update(sender_runtime="hermes", sender_session_ref=session)
        elif name == "pallium_relay_name":
            values.update(current_runtime="hermes", current_session_ref=session)
        scope = {"session_id": session, "turn_id": turn}
        if reply is not None:
            scope["reply"] = dict(reply)
        future = asyncio.run_coroutine_threadsafe(
            self._call(name, values, {"pallium_hermes": scope}), self._loop)
        try:
            return future.result(timeout=TIMEOUT_SECONDS)
        except concurrent.futures.TimeoutError:
            future.cancel()
            return json.dumps({"error": "Pallium MCP timed out; the operation may have committed. Check status before retrying."})
        except Exception:
            return json.dumps({"error": "Pallium MCP failed; verify status before retrying."})

    def close(self):
        if self._loop is not None and not self._finished.is_set():
            try:
                self._loop.call_soon_threadsafe(self._stop.set)
            except RuntimeError:
                pass
        self._thread.join(timeout=10)
        if self._thread.is_alive():
            raise RuntimeError("Owned Pallium MCP connection has not finished cleanup")
