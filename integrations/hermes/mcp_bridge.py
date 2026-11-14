"""Standard MCP transport owned by the Hermes plugin, never by model arguments."""
from __future__ import annotations

import asyncio
import concurrent.futures
from contextlib import AsyncExitStack
import json
import os
from pathlib import Path
import threading
from types import SimpleNamespace

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


def _transport_failure(error):
    from anyio import BrokenResourceError, ClosedResourceError, EndOfStream
    from mcp.shared.exceptions import McpError
    from mcp.types import CONNECTION_CLOSED

    if isinstance(error, BaseExceptionGroup):
        return any(_transport_failure(item) for item in error.exceptions)
    return isinstance(error, (
        OSError, EOFError, BrokenResourceError, ClosedResourceError, EndOfStream,
        concurrent.futures.CancelledError, asyncio.CancelledError,
    )) or isinstance(error, McpError) and error.error.code == CONNECTION_CLOSED


class RelayMcpBridge:
    """Owned generations; a failed invocation is never replayed on its successor."""

    def __init__(self, *, python, repo, base_url, container_ref, actor_ref, visibility,
                 memory_enabled=False):
        if type(memory_enabled) is not bool:
            raise ValueError("memory_enabled must be a boolean")
        self.python, self.repo = str(python), str(repo)
        if not Path(self.python).is_file() or not (Path(self.repo) / "app/mcp/hermes.py").is_file():
            raise ValueError("Configure the Pallium MCP interpreter and checkout explicitly")
        self.config = (base_url, container_ref, actor_ref, visibility, memory_enabled)
        self._config = self.config
        allowed = {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT", "TEMP", "TMP",
                   "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA"}
        self._launch = (self.python, self.repo, tuple(
            (key, value) for key, value in os.environ.items() if key.upper() in allowed
        ))
        self.allowed_tools = TOOLS | (MEMORY_TOOLS if memory_enabled else frozenset())
        self.catalog = []
        self._catalog_key = None
        self._lock, self._recovery = threading.RLock(), threading.Lock()
        self._connection, self._closed = None, False
        if self._get_connection() is None:
            self.close()
            raise ValueError("Pallium MCP could not initialize; check the explicit interpreter and service configuration")

    @property
    def _loop(self):
        return self._connection.loop if self._connection else None

    @property
    def _thread(self):
        return self._connection.thread if self._connection else None

    @staticmethod
    def _usable(connection):
        return (connection is not None and connection.ready.is_set()
                and not connection.retired.is_set() and not connection.finished.is_set()
                and connection.failure is None and connection.session is not None
                and connection.loop is not None and not connection.loop.is_closed())

    @staticmethod
    def _retire(connection):
        connection.retired.set()
        if connection.loop is not None and connection.stop is not None:
            try:
                connection.loop.call_soon_threadsafe(connection.stop.set)
            except RuntimeError:
                pass  # Closed loop: its owner still has to exit before replacement.

    def _dispose(self, connection):
        self._retire(connection)
        if connection.thread is threading.current_thread():
            return False
        if connection.thread.ident is not None:
            connection.thread.join(timeout=10)
        return (connection.finished.is_set() and not connection.thread.is_alive()
                and not connection.cleanup_failed)

    def _get_connection(self):
        with self._lock:
            observed = self._connection
            starting = observed is not None and not observed.ready.is_set()
            if self._closed:
                return None
            if self._usable(observed):
                return observed
        if not self._recovery.acquire(timeout=TIMEOUT_SECONDS):
            return None
        try:
            with self._lock:
                current = self._connection
                if self._closed:
                    return None
                if self._usable(current):
                    return current
                # Coalesce failed as well as successful concurrent recovery attempts.
                if starting or current is not observed or current is not None and current.catalog_failed:
                    return None
            if current is not None and not self._dispose(current):
                return None
            with self._lock:
                if self._closed:
                    return None
                connection = SimpleNamespace(
                    ready=threading.Event(), finished=threading.Event(), retired=threading.Event(),
                    loop=None, stop=None, session=None, catalog=None, failure=None,
                    cleanup_failed=False, catalog_failed=False,
                )
                connection.thread = threading.Thread(
                    target=self._run, args=(connection,), name="pallium-hermes-mcp", daemon=True,
                )
                self._connection = connection
                try:
                    connection.thread.start()
                except Exception as error:
                    connection.failure = error
                    connection.finished.set()
                    connection.ready.set()
            connection.ready.wait(TIMEOUT_SECONDS)
            with self._lock:
                if not self._closed and self._usable(connection):
                    if self._catalog_key is None:
                        self.catalog = connection.catalog
                        self._catalog_key = self._catalog_signature(connection.catalog)
                    return connection
            self._dispose(connection)
            return None
        finally:
            self._recovery.release()

    @staticmethod
    def _catalog_signature(catalog):
        return json.dumps(sorted(catalog, key=lambda tool: tool["name"]), sort_keys=True)

    def _record_failure(self, connection, error):
        with self._lock:
            if connection.failure is None:
                connection.failure = error
            elif connection.failure is not error:
                connection.failure = BaseExceptionGroup("MCP generation failures", [connection.failure, error])

    def _run(self, connection):
        try:
            asyncio.run(self._serve(connection))
        except BaseException as error:
            self._record_failure(connection, error)
        finally:
            connection.finished.set()
            connection.ready.set()

    async def _serve(self, connection):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        connection.loop, connection.stop = asyncio.get_running_loop(), asyncio.Event()
        if connection.retired.is_set():
            return
        python, repo, environment = self._launch
        base, container, actor, visibility, memory_enabled = self._config
        params = StdioServerParameters(
            command=python, cwd=repo, env=dict(environment),
            args=["-m", "app.mcp.hermes", "--base-url", base, "--container-ref", container,
                  "--actor-ref", actor, "--visibility", visibility,
                  *(["--memory-enabled"] if memory_enabled else [])],
        )
        stack = AsyncExitStack()
        try:
            async with asyncio.timeout(TIMEOUT_SECONDS):
                reader, writer = await stack.enter_async_context(stdio_client(params))
                session = await stack.enter_async_context(ClientSession(reader, writer))
                await session.initialize()
                result = await session.list_tools()
            try:
                catalog = _tool_catalog(result, memory_enabled=memory_enabled)
                if self._catalog_key is not None and self._catalog_signature(catalog) != self._catalog_key:
                    raise ValueError("Dedicated Hermes MCP catalog changed")
            except Exception:
                connection.catalog_failed = True
                raise
            connection.catalog, connection.session = catalog, session
            connection.ready.set()
            if not connection.retired.is_set():
                await connection.stop.wait()
        except BaseException as error:
            self._record_failure(connection, error)
        finally:
            try:
                await stack.aclose()
            except BaseException as error:
                connection.cleanup_failed = True
                self._record_failure(connection, error)

    async def _call(self, name, arguments, metadata, connection=None):
        # Production passes the captured generation, never a later ambient session.
        connection = connection if connection is not None else self._connection
        result = await connection.session.call_tool(name, arguments=arguments, meta=metadata)
        return _tool_response_text(result)

    def call(self, name, arguments, identity, reply=None):
        if name not in self.allowed_tools:
            return json.dumps({"error": "Pallium MCP is unavailable"})
        if (not isinstance(identity, tuple) or len(identity) != 2
                or any(not isinstance(value, str) or not value.strip() for value in identity)):
            return json.dumps({"error": "Pallium MCP requires this host's trusted session and turn"})
        session, turn = identity
        try:
            values = json.loads(json.dumps(arguments))
            private_reply = json.loads(json.dumps(reply)) if reply is not None else None
        except (TypeError, ValueError):
            return json.dumps({"error": "Pallium MCP received unsupported tool arguments"})
        if not isinstance(values, dict) or private_reply is not None and not isinstance(private_reply, dict):
            return json.dumps({"error": "Pallium MCP received unsupported tool arguments"})
        if name in HISTORY_TOOLS:
            fixed = {
                "container_ref": self._config[1],
                "thread_ref": session,
                "visibility": self._config[3],
            }
            if values.get("request_source_item_id") is not None:
                return json.dumps({"error": "Pallium History refused a model-supplied current request identity"})
            if any(key in values and values[key] not in (None, expected) for key, expected in fixed.items()):
                return json.dumps({"error": "Pallium History refused conflicting conversation scope"})
            values.update(fixed)
        else:
            values["container_ref"] = self._config[1]
        if name == "pallium_relay_send":
            values.update(sender_runtime="hermes", sender_session_ref=session)
        elif name == "pallium_relay_name":
            values.update(current_runtime="hermes", current_session_ref=session)
        scope = {"session_id": session, "turn_id": turn}
        if private_reply is not None:
            scope["reply"] = private_reply
        connection = self._get_connection()
        if connection is None:
            return json.dumps({"error": "Pallium MCP is unavailable; connection startup or owned cleanup did not complete"})
        with self._lock:
            if self._closed or connection is not self._connection or not self._usable(connection):
                return json.dumps({"error": "Pallium MCP is unavailable before dispatch"})
            coroutine = self._call(name, values, {"pallium_hermes": scope}, connection)
            try:
                future = asyncio.run_coroutine_threadsafe(coroutine, connection.loop)
            except RuntimeError:
                coroutine.close()
                self._retire(connection)
                return json.dumps({"error": "Pallium MCP is unavailable before dispatch"})
        try:
            return future.result(timeout=TIMEOUT_SECONDS)
        except concurrent.futures.TimeoutError as error:
            future.cancel()
            self._record_failure(connection, error)
            self._retire(connection)
            return json.dumps({"error": "Pallium MCP timed out; the operation may have committed. Check status before retrying."})
        except (Exception, BaseExceptionGroup) as error:
            if _transport_failure(error):
                self._record_failure(connection, error)
                self._retire(connection)
            return json.dumps({"error": "Pallium MCP failed; the operation may have committed. Check status before retrying."})

    def close(self):
        with self._lock:
            self._closed = True
            connection = self._connection
        if connection is not None:
            self._retire(connection)
        if not self._recovery.acquire(timeout=TIMEOUT_SECONDS):
            raise RuntimeError("Owned Pallium MCP recovery has not finished cleanup")
        try:
            if connection is not None and not self._dispose(connection):
                raise RuntimeError("Owned Pallium MCP connection cleanup failed or has not finished")
        finally:
            self._recovery.release()
