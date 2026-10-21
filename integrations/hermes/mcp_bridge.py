"""Standard MCP transport owned by the Hermes plugin, never by model arguments."""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
from pathlib import Path
import threading

RELAY_TOOLS = frozenset("pallium_relay_" + name for name in (
    "address", "recipients", "discover_recipients", "name", "work_refs",
    "attach_work_ref", "detach_work_ref", "participants", "send", "reply", "status", "trace",
))
HISTORY_TOOLS = frozenset({
    "pallium_search_history",
    "pallium_search_history_by_work_ref",
    "pallium_expand_source",
})
MEMORY_TOOLS = frozenset({
    "pallium_query", "pallium_expand", "pallium_ingest", "pallium_remember",
    "pallium_correct", "pallium_supersede", "pallium_forget",
    "pallium_forget_source", "pallium_record_outcome", "pallium_flag_memory",
    "pallium_rate_memory", "pallium_expand_source",
})
TOOLS = RELAY_TOOLS | HISTORY_TOOLS
HIDDEN = {
    "pallium_relay_send": {"sender_runtime", "sender_session_ref"},
    "pallium_relay_name": {"current_runtime", "current_session_ref"},
    "pallium_relay_reply": {"receipt"},
}
for _name in HISTORY_TOOLS:
    HIDDEN[_name] = {"container_ref", "thread_ref", "visibility", "agent_ref", "request_source_item_id"}
HIDDEN["pallium_expand_source"].add("include_supported_memories")
for _name in MEMORY_TOOLS - {"pallium_expand_source", "pallium_forget_source"}:
    HIDDEN[_name] = HIDDEN.get(_name, set()) | {
        "container_ref", "actor_ref", "thread_ref", "agent_ref", "visibility",
    }
HIDDEN["pallium_flag_memory"].add("source_ref")
HIDDEN["pallium_forget_source"] = HIDDEN.get("pallium_forget_source", set()) | {
    "container_ref", "actor_ref", "agent_ref", "visibility",
}
TIMEOUT_SECONDS = 15
MAX_RESPONSE_CHARS = 24_000


def _wire_model(value):
    """Read the public MCP wire names shared by supported SDK model versions."""
    dump = getattr(value, "model_dump", None)
    if not callable(dump):
        raise ValueError("MCP returned an unsupported response model")
    try:
        result = dump(mode="json", by_alias=True)
    except Exception as exc:
        raise ValueError("MCP returned an unsupported response model") from exc
    if not isinstance(result, dict):
        raise ValueError("MCP returned an unsupported response model")
    return result


def _tool_catalog(result, *, memory_enabled=False):
    allowed_tools = TOOLS | (MEMORY_TOOLS if memory_enabled else frozenset())
    wire = _wire_model(result)
    if "resultType" in wire and wire["resultType"] != "complete":
        raise ValueError("Incomplete dedicated Hermes MCP catalog")
    tools, cursor = wire.get("tools"), wire.get("nextCursor")
    if "next_cursor" in wire or not isinstance(tools, list) or cursor is not None:
        raise ValueError("Incomplete dedicated Hermes MCP catalog")
    catalog = []
    for tool in tools:
        if not isinstance(tool, dict):
            raise ValueError("Malformed dedicated Hermes MCP catalog")
        name, description, schema = tool.get("name"), tool.get("description"), tool.get("inputSchema")
        if (not isinstance(name, str) or name not in allowed_tools
                or description is not None and not isinstance(description, str)
                or not isinstance(schema, dict) or schema.get("type") != "object"):
            raise ValueError("Malformed dedicated Hermes MCP catalog")
        properties, required = schema.get("properties", {}), schema.get("required", [])
        if (not isinstance(properties, dict) or not isinstance(required, list)
                or any(not isinstance(key, str) or key not in properties for key in required)):
            raise ValueError("Malformed dedicated Hermes MCP catalog")
        schema = json.loads(json.dumps(schema))
        hidden = {"container_ref"} | HIDDEN.get(name, set())
        if name == "pallium_expand_source" and memory_enabled:
            hidden.discard("include_supported_memories")
        for key in hidden:
            schema.get("properties", {}).pop(key, None)
        if "required" in schema:
            schema["required"] = [key for key in schema["required"] if key not in hidden]
        schema["additionalProperties"] = False
        description = description or ""
        description += (
            " Hermes supplies trusted conversation identity and fixed private scope; only the listed arguments are accepted."
            if name in HISTORY_TOOLS else
            " Hermes supplies self identity, scope and private receipts; only the listed arguments are accepted."
            " Incoming delivery is handled by hooks; receive/ACK tools are not exposed."
        )
        catalog.append({"name": name, "description": description, "parameters": schema})
    if len(catalog) != len(allowed_tools) or {tool["name"] for tool in catalog} != allowed_tools:
        raise ValueError("Incomplete dedicated Hermes MCP catalog")
    return catalog


def _tool_response_text(result):
    wire = _wire_model(result)
    if "resultType" in wire and wire["resultType"] != "complete":
        return json.dumps({"error": "Pallium MCP returned an incomplete response"})
    is_error = wire.get("isError")
    blocks = wire.get("content")
    if type(is_error) is not bool or not isinstance(blocks, list):
        return json.dumps({"error": "Pallium MCP returned an unsupported response"})
    if is_error:
        return json.dumps({"error": "Pallium MCP refused the request"})
    if any(not isinstance(block, dict) or block.get("type") != "text"
           or not isinstance(block.get("text"), str) for block in blocks):
        return json.dumps({"error": "Pallium MCP returned an unsupported response"})
    text = "\n".join(block["text"] for block in blocks)
    if len(text) > MAX_RESPONSE_CHARS:
        return json.dumps({"error": "Pallium MCP response exceeded the supported budget"})
    return text


class RelayMcpBridge:
    """One owned stdio connection; each call carries an explicit immutable scope."""

    def __init__(self, *, python, repo, base_url, container_ref, actor_ref, visibility,
                 memory_enabled=False):
        if type(memory_enabled) is not bool:
            raise ValueError("memory_enabled must be a boolean")
        self.python, self.repo = str(python), str(repo)
        if not Path(self.python).is_file() or not (Path(self.repo) / "app/mcp/hermes.py").is_file():
            raise ValueError("Configure the Pallium MCP interpreter and checkout explicitly")
        self.config = (base_url, container_ref, actor_ref, visibility, memory_enabled)
        self.allowed_tools = TOOLS | (MEMORY_TOOLS if memory_enabled else frozenset())
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
        base, container, actor, visibility, memory_enabled = self.config
        params = StdioServerParameters(
            command=self.python, cwd=self.repo, env=env,
            args=["-m", "app.mcp.hermes", "--base-url", base, "--container-ref", container,
                  "--actor-ref", actor, "--visibility", visibility,
                  *(["--memory-enabled"] if memory_enabled else [])],
        )
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                async with asyncio.timeout(TIMEOUT_SECONDS):
                    await session.initialize()
                    result = await session.list_tools()
                catalog = _tool_catalog(result, memory_enabled=self.config[4])
                self.catalog, self._session = catalog, session
                self._ready.set()
                await self._stop.wait()

    async def _call(self, name, arguments, metadata):
        # Both dictionaries are copied before crossing the loop; no ambient current session.
        result = await self._session.call_tool(name, arguments=arguments, meta=metadata)
        return _tool_response_text(result)

    def call(self, name, arguments, identity, reply=None):
        if (name not in self.allowed_tools or self._finished.is_set() or not self._ready.is_set()
                or self._session is None):
            return json.dumps({"error": "Pallium MCP is unavailable"})
        if (not isinstance(identity, tuple) or len(identity) != 2
                or any(not isinstance(value, str) or not value.strip() for value in identity)):
            return json.dumps({"error": "Pallium MCP requires this host's trusted session and turn"})
        session, turn = identity
        values = json.loads(json.dumps(arguments))
        if name in HISTORY_TOOLS:
            fixed = {
                "container_ref": self.config[1],
                "thread_ref": session,
                "visibility": self.config[3],
            }
            if values.get("request_source_item_id") is not None:
                return json.dumps({"error": "Pallium History refused a model-supplied current request identity"})
            if any(key in values and values[key] not in (None, expected) for key, expected in fixed.items()):
                return json.dumps({"error": "Pallium History refused conflicting conversation scope"})
            values.update(fixed)
        else:
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
