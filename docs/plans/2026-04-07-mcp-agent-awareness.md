# MCP Server for Agent Awareness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a stdio MCP server in Pallium that exposes `pallium_query`, `pallium_query_debug`, and `pallium_ingest` tools, wrapping Pallium's existing HTTP API.

**Architecture:** A thin `app/mcp/` module provides a FastMCP stdio server that reads env-based context defaults and proxies tool calls to Pallium's HTTP endpoints via httpx. No dependency on Pallium core code — the MCP server is a pure HTTP client. Context resolution happens once per tool call in the server layer; the HTTP client receives a fully-resolved context and reads scope from it directly.

**Tech Stack:** Python `mcp[cli]` (FastMCP), `httpx` (async HTTP client, already a Pallium dep)

**Spec:** `docs/specs/2026-04-07-mcp-agent-awareness-design.md`

---

## File Map

| File | Responsibility | Change |
|---|---|---|
| `app/mcp/__init__.py` | Package marker | Create |
| `app/mcp/context.py` | Env var reading + per-call override merge | Create |
| `app/mcp/client.py` | Async HTTP client, reads scope from context only | Create |
| `app/mcp/server.py` | FastMCP server, tool registration, context resolution, entry point | Create |
| `app/run.py` | CLI entry point | Add `mcp` subcommand with helpful import error |
| `pyproject.toml` | Dependencies + package list | Add `mcp[cli]`, `pytest-asyncio`, register `app.mcp` |
| `tests/test_mcp_context.py` | Context resolution tests | Create |
| `tests/test_mcp_client.py` | HTTP client tests (mocked) | Create |
| `tests/test_mcp_server.py` | MCP tool tests (mocked client) | Create |
| `tests/test_mcp_integration.py` | MCP client → Pallium ASGI app passthrough | Create |

---

### Task 1: Add Dependencies + Register Package

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add mcp optional dependency, pytest-asyncio, and register package**

In `pyproject.toml`, add `mcp` to optional dependencies, `pytest-asyncio` to dev, and `app.mcp` to packages:

```toml
[project.optional-dependencies]
vector = [
    "usearch>=2.9,<3.0",
    "onnxruntime>=1.17,<2.0",
    "tokenizers>=0.21,<1.0",
]
mcp = [
    "mcp[cli]>=1.20,<2.0",
]
dev = [
    "pytest>=8.3,<9.0",
    "pytest-asyncio>=0.24,<1.0",
    "pytest-xdist>=3.6,<4.0",
]
```

In the `[tool.setuptools] packages` list, add `"app.mcp"`:

```toml
[tool.setuptools]
packages = [
    "app",
    "app.mcp",
    "capabilities",
    "api",
    "core",
    "evals",
    "providers",
    "providers.embedding",
    "providers.llm",
    "retrieval",
    "semantic",
    "storage",
]
```

- [ ] **Step 2: Install the dependencies**

Run: `pip install -e ".[mcp,dev]"`

- [ ] **Step 3: Verify imports**

Run: `python -c "from mcp.server.fastmcp import FastMCP; print('mcp ok')" && python -c "import pytest_asyncio; print('pytest-asyncio ok')"`
Expected: Both print `ok`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "feat(mcp): add mcp[cli] and pytest-asyncio dependencies"
```

---

### Task 2: Context Resolution Module

**Files:**
- Create: `app/mcp/__init__.py`
- Create: `app/mcp/context.py`
- Create: `tests/test_mcp_context.py`

- [ ] **Step 1: Create package marker**

Create `app/mcp/__init__.py` (empty file).

- [ ] **Step 2: Write failing tests for context resolution**

Create `tests/test_mcp_context.py`:

```python
"""Tests for MCP environment-based context resolution."""

from __future__ import annotations

import pytest

from app.mcp.context import resolve_context, PalliumContext


class TestResolveContext:
    """resolve_context merges explicit params with env var defaults."""

    def test_all_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
        monkeypatch.setenv("PALLIUM_CONTAINER_REF", "slack:channel:C04ABC")
        monkeypatch.setenv("PALLIUM_THREAD_REF", "slack:thread:C04ABC:123")
        monkeypatch.setenv("PALLIUM_ACTOR_REF", "slack:user:U789")
        monkeypatch.setenv("PALLIUM_VISIBILITY", "container")

        ctx = resolve_context()
        assert ctx.base_url == "http://localhost:8000"
        assert ctx.container_ref == "slack:channel:C04ABC"
        assert ctx.thread_ref == "slack:thread:C04ABC:123"
        assert ctx.actor_ref == "slack:user:U789"
        assert ctx.visibility == "container"

    def test_explicit_overrides_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PALLIUM_CONTAINER_REF", "env-container")
        monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")

        ctx = resolve_context(container_ref="explicit-container")
        assert ctx.container_ref == "explicit-container"

    def test_explicit_none_falls_through_to_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PALLIUM_CONTAINER_REF", "env-container")
        monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")

        ctx = resolve_context(container_ref=None)
        assert ctx.container_ref == "env-container"

    def test_missing_env_returns_none_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
        monkeypatch.delenv("PALLIUM_CONTAINER_REF", raising=False)
        monkeypatch.delenv("PALLIUM_THREAD_REF", raising=False)
        monkeypatch.delenv("PALLIUM_ACTOR_REF", raising=False)
        monkeypatch.delenv("PALLIUM_VISIBILITY", raising=False)

        ctx = resolve_context()
        assert ctx.base_url == "http://localhost:8000"
        assert ctx.container_ref is None
        assert ctx.thread_ref is None
        assert ctx.actor_ref is None
        assert ctx.visibility is None

    def test_missing_base_url_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PALLIUM_BASE_URL", raising=False)

        ctx = resolve_context()
        assert ctx.base_url is None


class TestPalliumContext:
    """PalliumContext.is_configured checks base_url presence."""

    def test_configured_when_base_url_set(self) -> None:
        ctx = PalliumContext(base_url="http://localhost:8000")
        assert ctx.is_configured is True

    def test_not_configured_when_base_url_none(self) -> None:
        ctx = PalliumContext(base_url=None)
        assert ctx.is_configured is False
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_mcp_context.py -x -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.mcp.context'`

- [ ] **Step 4: Implement context module**

Create `app/mcp/context.py`:

```python
"""Environment-based context resolution for Pallium MCP server."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class PalliumContext:
    """Resolved Pallium connection and scope context."""

    base_url: str | None = None
    container_ref: str | None = None
    thread_ref: str | None = None
    actor_ref: str | None = None
    visibility: str | None = None

    @property
    def is_configured(self) -> bool:
        return self.base_url is not None


def resolve_context(
    *,
    container_ref: str | None = None,
    thread_ref: str | None = None,
    actor_ref: str | None = None,
    visibility: str | None = None,
) -> PalliumContext:
    """Merge explicit parameters with environment variable defaults.

    Resolution order: explicit parameter > environment variable > None.
    """
    return PalliumContext(
        base_url=os.environ.get("PALLIUM_BASE_URL"),
        container_ref=container_ref if container_ref is not None else os.environ.get("PALLIUM_CONTAINER_REF"),
        thread_ref=thread_ref if thread_ref is not None else os.environ.get("PALLIUM_THREAD_REF"),
        actor_ref=actor_ref if actor_ref is not None else os.environ.get("PALLIUM_ACTOR_REF"),
        visibility=visibility if visibility is not None else os.environ.get("PALLIUM_VISIBILITY"),
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_mcp_context.py -x -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add app/mcp/__init__.py app/mcp/context.py tests/test_mcp_context.py
git commit -m "feat(mcp): add context resolution module"
```

---

### Task 3: HTTP Client Module

The client reads scope exclusively from the `PalliumContext` it receives. No per-call scope overrides — context resolution is the server's job.

**Files:**
- Create: `app/mcp/client.py`
- Create: `tests/test_mcp_client.py`

- [ ] **Step 1: Write failing tests for the HTTP client**

Create `tests/test_mcp_client.py`:

```python
"""Tests for MCP HTTP client wrapping Pallium REST API."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.mcp.client import PalliumMcpClient
from app.mcp.context import PalliumContext


@pytest.fixture()
def ctx() -> PalliumContext:
    return PalliumContext(
        base_url="http://localhost:8000",
        container_ref="test-container",
        thread_ref="test-thread",
        actor_ref="test-actor",
        visibility="container",
    )


def _mock_response(status_code: int = 200, json_data: dict | list | None = None) -> AsyncMock:
    resp = AsyncMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = json.dumps(json_data or {})
    resp.raise_for_status = AsyncMock()
    return resp


class TestQuery:
    @pytest.mark.asyncio
    async def test_query_sends_scope_from_context(self, ctx: PalliumContext) -> None:
        mock_resp = _mock_response(json_data={"results": [], "should_inject": False, "decision_reason": "no_relevant_memory", "injectable_blocks": []})
        with patch("httpx.AsyncClient.post", return_value=mock_resp) as mock_post:
            client = PalliumMcpClient(ctx)
            await client.query("test query", limit=3)

            mock_post.assert_called_once()
            payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
            assert payload["text"] == "test query"
            assert payload["limit"] == 3
            assert payload["container_ref"] == "test-container"
            assert payload["thread_ref"] == "test-thread"
            assert payload["actor_ref"] == "test-actor"
            assert payload["visibility"] == "container"

    @pytest.mark.asyncio
    async def test_query_omits_none_scope_fields(self) -> None:
        ctx = PalliumContext(base_url="http://localhost:8000")
        mock_resp = _mock_response(json_data={"results": [], "should_inject": False, "decision_reason": "no_relevant_memory", "injectable_blocks": []})
        with patch("httpx.AsyncClient.post", return_value=mock_resp) as mock_post:
            client = PalliumMcpClient(ctx)
            await client.query("test query")

            payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
            assert "container_ref" not in payload
            assert "thread_ref" not in payload
            assert "actor_ref" not in payload
            assert "visibility" not in payload

    @pytest.mark.asyncio
    async def test_query_returns_raw_json(self, ctx: PalliumContext) -> None:
        expected = {"results": [{"score": 0.9}], "should_inject": True, "decision_reason": "carry_forward_available", "injectable_blocks": []}
        mock_resp = _mock_response(json_data=expected)
        with patch("httpx.AsyncClient.post", return_value=mock_resp):
            client = PalliumMcpClient(ctx)
            result = await client.query("test")
            assert result == expected


class TestQueryDebug:
    @pytest.mark.asyncio
    async def test_query_debug_hits_debug_endpoint(self, ctx: PalliumContext) -> None:
        mock_resp = _mock_response(json_data={"results": [], "should_inject": False, "decision_reason": "no_relevant_memory", "injectable_blocks": [], "trace": {}})
        with patch("httpx.AsyncClient.post", return_value=mock_resp) as mock_post:
            client = PalliumMcpClient(ctx)
            await client.query_debug("test")

            url = mock_post.call_args.args[0] if mock_post.call_args.args else mock_post.call_args.kwargs.get("url", "")
            assert "/query/debug" in str(url)

    @pytest.mark.asyncio
    async def test_query_debug_omits_limit(self, ctx: PalliumContext) -> None:
        """query_debug intentionally omits limit — uses API default (5)."""
        mock_resp = _mock_response(json_data={"results": [], "should_inject": False, "decision_reason": "no_relevant_memory", "trace": {}})
        with patch("httpx.AsyncClient.post", return_value=mock_resp) as mock_post:
            client = PalliumMcpClient(ctx)
            await client.query_debug("test")

            payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
            assert "limit" not in payload


class TestIngest:
    @pytest.mark.asyncio
    async def test_ingest_sends_single_item_array(self, ctx: PalliumContext) -> None:
        mock_resp = _mock_response(json_data=[{"source_item_id": "si-123", "processing_status": "pending", "memory_object_ids": [], "relation_ids": [], "index_entry_ids": [], "processing_attempts": 0, "processing_error": None}])
        with patch("httpx.AsyncClient.post", return_value=mock_resp) as mock_post:
            client = PalliumMcpClient(ctx)
            await client.ingest(
                content="Remember this decision",
                source_type="agent_artifact",
                source_id="test-123",
                artifact_kind="assistant_output",
                role="assistant",
            )

            payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
            assert isinstance(payload, list)
            assert len(payload) == 1
            item = payload[0]
            assert item["content"] == "Remember this decision"
            assert item["source_type"] == "agent_artifact"
            assert item["source_id"] == "test-123"
            assert item["content_type"] == "text/plain"
            assert item["artifact_kind"] == "assistant_output"
            assert item["role"] == "assistant"
            assert item["container_ref"] == "test-container"

    @pytest.mark.asyncio
    async def test_ingest_omits_none_optional_fields(self, ctx: PalliumContext) -> None:
        """artifact_kind and role should be omitted when None, not sent as null."""
        mock_resp = _mock_response(json_data=[{"source_item_id": "si-123", "processing_status": "pending", "memory_object_ids": [], "relation_ids": [], "index_entry_ids": [], "processing_attempts": 0}])
        with patch("httpx.AsyncClient.post", return_value=mock_resp) as mock_post:
            client = PalliumMcpClient(ctx)
            await client.ingest(content="test", source_type="agent_artifact", source_id="x")

            item = mock_post.call_args.kwargs.get("json")[0]
            assert "artifact_kind" not in item
            assert "role" not in item

    @pytest.mark.asyncio
    async def test_ingest_returns_first_item_response(self, ctx: PalliumContext) -> None:
        resp_data = [{"source_item_id": "si-abc", "processing_status": "pending", "memory_object_ids": [], "relation_ids": [], "index_entry_ids": [], "processing_attempts": 0}]
        mock_resp = _mock_response(json_data=resp_data)
        with patch("httpx.AsyncClient.post", return_value=mock_resp):
            client = PalliumMcpClient(ctx)
            result = await client.ingest(content="test", source_type="agent_artifact", source_id="x")
            assert result == resp_data[0]


class TestConnectionError:
    @pytest.mark.asyncio
    async def test_connection_error_returns_error_dict(self, ctx: PalliumContext) -> None:
        with patch("httpx.AsyncClient.post", side_effect=Exception("Connection refused")):
            client = PalliumMcpClient(ctx)
            result = await client.query("test")
            assert "error" in result
            assert "Connection refused" in result["error"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_mcp_client.py -x -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.mcp.client'`

- [ ] **Step 3: Implement HTTP client**

Create `app/mcp/client.py`:

```python
"""Async HTTP client wrapping Pallium's REST API for MCP tools.

The client reads all scope parameters (container_ref, thread_ref, actor_ref,
visibility) from the PalliumContext it receives. Context resolution (merging
explicit overrides with env var defaults) is the server layer's responsibility.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx

from app.mcp.context import PalliumContext


class PalliumMcpClient:
    """Thin HTTP client that proxies MCP tool calls to Pallium's REST API."""

    def __init__(self, ctx: PalliumContext) -> None:
        self._ctx = ctx
        self._base_url = ctx.base_url or ""

    def _scope_params(self) -> dict[str, str]:
        """Build scope parameters from context. None values are omitted."""
        params: dict[str, str] = {}
        for key in ("container_ref", "thread_ref", "actor_ref", "visibility"):
            value = getattr(self._ctx, key, None)
            if value is not None:
                params[key] = value
        return params

    async def query(self, text: str, limit: int = 5) -> dict[str, Any]:
        payload: dict[str, Any] = {"text": text, "limit": limit}
        payload.update(self._scope_params())
        return await self._post("/query", payload)

    async def query_debug(self, text: str) -> dict[str, Any]:
        # Intentionally omits limit — uses API default (5).
        payload: dict[str, Any] = {"text": text}
        payload.update(self._scope_params())
        return await self._post("/query/debug", payload)

    async def ingest(
        self,
        content: str,
        source_type: str = "agent_artifact",
        source_id: str | None = None,
        *,
        artifact_kind: str | None = None,
        role: str | None = None,
    ) -> dict[str, Any]:
        item: dict[str, Any] = {
            "source_type": source_type,
            "source_id": source_id or f"mcp-{uuid.uuid4().hex[:12]}",
            "content_type": "text/plain",
            "content": content,
        }
        if artifact_kind is not None:
            item["artifact_kind"] = artifact_kind
        if role is not None:
            item["role"] = role
        item.update(self._scope_params())
        result = await self._post("/items", [item])
        if isinstance(result, list) and len(result) > 0:
            return result[0]
        return result

    async def _post(self, path: str, payload: Any) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=30.0) as http:
                response = await http.post(path, json=payload)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            # Return the API error body for 4xx/5xx so the LLM sees validation errors
            try:
                body = exc.response.json()
            except Exception:
                body = exc.response.text
            return {"error": str(exc), "detail": body}
        except Exception as exc:
            return {"error": str(exc)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_mcp_client.py -x -q`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add app/mcp/client.py tests/test_mcp_client.py
git commit -m "feat(mcp): add HTTP client wrapping Pallium REST API"
```

---

### Task 4: MCP Server + Tool Registration

The server owns context resolution. Each tool call resolves context once via `resolve_context()`, creates a `PalliumMcpClient` with the resolved context, and delegates. No scope params are passed to client methods — the context object is the single source of truth.

**Files:**
- Create: `app/mcp/server.py`
- Create: `tests/test_mcp_server.py`

- [ ] **Step 1: Write failing tests for MCP server tools**

Create `tests/test_mcp_server.py`:

```python
"""Tests for MCP server tool registration and self-gating."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.mcp.server import create_server


class TestSelfGating:
    @pytest.mark.asyncio
    async def test_query_returns_not_configured_when_no_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PALLIUM_BASE_URL", raising=False)
        server = create_server()
        tools = await server.list_tools()
        tool_names = [t.name for t in tools]
        assert "pallium_query" in tool_names

        result = await server.call_tool("pallium_query", {"query": "test"})
        text = result.content[0].text
        assert "not configured" in text.lower()

    @pytest.mark.asyncio
    async def test_ingest_returns_not_configured_when_no_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PALLIUM_BASE_URL", raising=False)
        server = create_server()
        result = await server.call_tool("pallium_ingest", {"content": "test"})
        text = result.content[0].text
        assert "not configured" in text.lower()


class TestToolsWithMockedClient:
    @pytest.mark.asyncio
    async def test_query_passes_through_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
        expected = {"results": [{"score": 0.9}], "should_inject": True, "decision_reason": "carry_forward_available"}

        with patch("app.mcp.client.PalliumMcpClient.query", new_callable=AsyncMock, return_value=expected):
            server = create_server()
            result = await server.call_tool("pallium_query", {"query": "test decision"})
            text = result.content[0].text
            parsed = json.loads(text)
            assert parsed == expected

    @pytest.mark.asyncio
    async def test_query_debug_passes_through_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
        expected = {"results": [], "trace": {"stages": []}, "should_inject": False, "decision_reason": "no_relevant_memory"}

        with patch("app.mcp.client.PalliumMcpClient.query_debug", new_callable=AsyncMock, return_value=expected):
            server = create_server()
            result = await server.call_tool("pallium_query_debug", {"query": "test"})
            text = result.content[0].text
            parsed = json.loads(text)
            assert parsed == expected

    @pytest.mark.asyncio
    async def test_ingest_passes_through_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
        expected = {"source_item_id": "si-123", "processing_status": "pending"}

        with patch("app.mcp.client.PalliumMcpClient.ingest", new_callable=AsyncMock, return_value=expected):
            server = create_server()
            result = await server.call_tool("pallium_ingest", {"content": "remember this"})
            text = result.content[0].text
            parsed = json.loads(text)
            assert parsed == expected

    @pytest.mark.asyncio
    async def test_query_scope_override_resolved_in_context(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Scope overrides are resolved by the server into context, not passed to client."""
        monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
        monkeypatch.setenv("PALLIUM_CONTAINER_REF", "env-container")

        with patch("app.mcp.client.PalliumMcpClient.__init__", return_value=None) as mock_init, \
             patch("app.mcp.client.PalliumMcpClient.query", new_callable=AsyncMock, return_value={"results": []}):
            server = create_server()
            await server.call_tool("pallium_query", {
                "query": "test",
                "container_ref": "override-container",
            })
            # The client should receive a context with the override applied
            ctx_arg = mock_init.call_args.args[0]
            assert ctx_arg.container_ref == "override-container"


class TestToolDescriptions:
    @pytest.mark.asyncio
    async def test_all_three_tools_registered(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
        server = create_server()
        tools = await server.list_tools()
        tool_names = {t.name for t in tools}
        assert tool_names == {"pallium_query", "pallium_query_debug", "pallium_ingest"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_mcp_server.py -x -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.mcp.server'`

- [ ] **Step 3: Implement MCP server**

Create `app/mcp/server.py`:

```python
"""Pallium MCP server — stdio transport adapter wrapping the HTTP API."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from app.mcp.client import PalliumMcpClient
from app.mcp.context import resolve_context

NOT_CONFIGURED_MSG = (
    "Pallium memory system is not configured. "
    "No memory tools available. "
    "Set PALLIUM_BASE_URL to the Pallium HTTP server URL."
)


def create_server() -> FastMCP:
    """Create a FastMCP server with Pallium tools registered."""
    server = FastMCP("pallium")

    @server.tool()
    async def pallium_query(
        query: str,
        limit: int = 5,
        container_ref: str | None = None,
        thread_ref: str | None = None,
        actor_ref: str | None = None,
        visibility: str | None = None,
    ) -> str:
        """Search Pallium memory. Use when automatic memory injection is missing something specific — e.g. a past decision, investigation outcome, or context from a previous conversation that wasn't auto-injected."""
        ctx = resolve_context(
            container_ref=container_ref,
            thread_ref=thread_ref,
            actor_ref=actor_ref,
            visibility=visibility,
        )
        if not ctx.is_configured:
            return NOT_CONFIGURED_MSG
        client = PalliumMcpClient(ctx)
        result = await client.query(query, limit=limit)
        return json.dumps(result, indent=2, default=str)

    @server.tool()
    async def pallium_query_debug(
        query: str,
        container_ref: str | None = None,
        thread_ref: str | None = None,
        actor_ref: str | None = None,
        visibility: str | None = None,
    ) -> str:
        """Investigate Pallium retrieval — debug why a memory was or wasn't found. Returns retrieval stages, candidate scores, visibility filtering, and injection decision reasoning. Use when a user asks 'why don't you remember X?' or when you suspect a memory should exist but wasn't injected."""
        ctx = resolve_context(
            container_ref=container_ref,
            thread_ref=thread_ref,
            actor_ref=actor_ref,
            visibility=visibility,
        )
        if not ctx.is_configured:
            return NOT_CONFIGURED_MSG
        client = PalliumMcpClient(ctx)
        result = await client.query_debug(query)
        return json.dumps(result, indent=2, default=str)

    @server.tool()
    async def pallium_ingest(
        content: str,
        source_type: str = "agent_artifact",
        source_id: str | None = None,
        artifact_kind: str | None = None,
        role: str | None = None,
        container_ref: str | None = None,
        thread_ref: str | None = None,
        actor_ref: str | None = None,
        visibility: str | None = None,
    ) -> str:
        """Store a conversation artifact in Pallium for semantic processing. The artifact goes through the standard extraction pipeline — it does not create memory objects directly. Use when the user explicitly asks to remember something, or to record a decision or outcome for future reference. Do not use for routine conversation — the integration layer already ingests outputs automatically."""
        ctx = resolve_context(
            container_ref=container_ref,
            thread_ref=thread_ref,
            actor_ref=actor_ref,
            visibility=visibility,
        )
        if not ctx.is_configured:
            return NOT_CONFIGURED_MSG
        client = PalliumMcpClient(ctx)
        result = await client.ingest(
            content=content,
            source_type=source_type,
            source_id=source_id,
            artifact_kind=artifact_kind,
            role=role,
        )
        return json.dumps(result, indent=2, default=str)

    return server


def main() -> None:
    """Run the Pallium MCP server with stdio transport."""
    server = create_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_mcp_server.py -x -q`
Expected: All pass

Note: If the FastMCP `call_tool` / `list_tools` test API differs from what's shown, adjust the test harness to match the actual SDK. The key assertions (tool names, passthrough behavior, self-gating, context resolution) remain the same.

- [ ] **Step 5: Commit**

```bash
git add app/mcp/server.py tests/test_mcp_server.py
git commit -m "feat(mcp): add MCP server with query, debug, and ingest tools"
```

---

### Task 5: CLI Entry Point

**Files:**
- Modify: `app/run.py`

- [ ] **Step 1: Write a manual verification test**

Run: `PALLIUM_BASE_URL=http://localhost:9999 python -m app.run mcp`
Expected: Currently fails — `mcp` is not a valid mode choice.

- [ ] **Step 2: Add `mcp` mode to CLI with helpful import error**

In `app/run.py`, add `"mcp"` to the mode choices and handle it:

Add `"mcp"` to the choices tuple in `build_parser()`:

```python
parser.add_argument(
    "mode",
    nargs="?",
    choices=("all", "serve", "processor", "cleaner", "rebuild-vector-index", "download-embedding-model", "mcp"),
    default="all",
)
```

Add the handler in `run()`, after the `parsed.mode == "serve"` block:

```python
if parsed.mode == "mcp":
    try:
        from app.mcp.server import main as mcp_main
    except ImportError:
        logger.error("MCP dependencies not installed. Run: pip install -e '.[mcp]'")
        return 1
    mcp_main()
    return 0
```

- [ ] **Step 3: Verify the entry point starts**

Run: `PALLIUM_BASE_URL=http://localhost:9999 timeout 2 python -m app.run mcp 2>&1 || true`
Expected: The process starts and waits for stdio input (or times out after 2 seconds without error). No import errors.

- [ ] **Step 4: Commit**

```bash
git add app/run.py
git commit -m "feat(mcp): add 'mcp' subcommand to CLI entry point"
```

---

### Task 6: End-to-End Integration Test

This test uses `httpx.ASGITransport` to wire the async MCP client directly to the Pallium ASGI app, proving the full passthrough chain: MCP client → HTTP request → Pallium API → response → MCP client.

**Files:**
- Create: `tests/test_mcp_integration.py`

- [ ] **Step 1: Write integration test**

Create `tests/test_mcp_integration.py`:

```python
"""End-to-end integration test: MCP client → Pallium ASGI app.

Uses httpx.ASGITransport to connect the async MCP client directly to the
Pallium ASGI application, verifying the full passthrough chain without
needing a real HTTP server.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.main import create_app
from app.config import AppConfig
from app.mcp.client import PalliumMcpClient
from app.mcp.context import PalliumContext


@pytest.fixture()
def pallium_asgi_app(test_db_url: str):
    from storage.vector_index import VectorIndexConfig
    return create_app(
        AppConfig(
            storage_backend="sqlite",
            sqlite_url=test_db_url,
            default_use_case="demo_agent_memory",
            vector_index=VectorIndexConfig(enabled=False),
        )
    )


@pytest.fixture()
def mcp_client(pallium_asgi_app) -> PalliumMcpClient:
    """MCP client wired to the ASGI app via ASGITransport."""
    ctx = PalliumContext(
        base_url="http://testserver",
        visibility="public",
    )
    client = PalliumMcpClient(ctx)
    # Monkey-patch _post to use ASGITransport instead of real HTTP
    original_post = client._post

    async def _asgi_post(path, payload):
        transport = httpx.ASGITransport(app=pallium_asgi_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=30.0) as http:
            response = await http.post(path, json=payload)
            response.raise_for_status()
            return response.json()

    client._post = _asgi_post
    return client


class TestMcpClientPassthrough:
    """Verify MCP client responses match what the HTTP API returns."""

    @pytest.mark.asyncio
    async def test_query_returns_valid_response(self, mcp_client: PalliumMcpClient) -> None:
        result = await mcp_client.query("test query", limit=5)
        assert "results" in result
        assert "should_inject" in result
        assert "decision_reason" in result
        assert "injectable_blocks" in result

    @pytest.mark.asyncio
    async def test_query_debug_returns_trace(self, mcp_client: PalliumMcpClient) -> None:
        result = await mcp_client.query_debug("test query")
        assert "results" in result
        assert "trace" in result
        assert "should_inject" in result

    @pytest.mark.asyncio
    async def test_ingest_returns_processing_status(self, mcp_client: PalliumMcpClient) -> None:
        result = await mcp_client.ingest(
            content="Remember this decision about caching",
            source_type="agent_artifact",
            source_id="mcp-integration-test-001",
        )
        assert "source_item_id" in result
        assert "processing_status" in result
        assert result["processing_status"] in ("pending", "completed", "skipped")

    @pytest.mark.asyncio
    async def test_query_response_matches_direct_http(self, pallium_asgi_app, mcp_client: PalliumMcpClient) -> None:
        """MCP client response must be identical to direct HTTP API response."""
        query_payload = {"text": "test match", "limit": 3, "visibility": "public"}

        # Direct HTTP response
        transport = httpx.ASGITransport(app=pallium_asgi_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            direct_response = await http.post("/query", json=query_payload)
            direct_result = direct_response.json()

        # MCP client response
        mcp_result = await mcp_client.query("test match", limit=3)

        # Must match exactly — no transformation layer
        assert mcp_result == direct_result
```

- [ ] **Step 2: Run integration tests**

Run: `python -m pytest tests/test_mcp_integration.py -x -q`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add tests/test_mcp_integration.py
git commit -m "test(mcp): add end-to-end integration tests with ASGI transport"
```

---

### Task 7: Full Test Suite + Documentation

**Files:**
- Modify: `docs/context/architecture.md`

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: All existing tests pass, all new MCP tests pass.

- [ ] **Step 2: Verify no namespace collision**

Run: `python -c "import mcp; from mcp.server.fastmcp import FastMCP; print('PyPI mcp OK')"`
Expected: `PyPI mcp OK` — the `mcp` PyPI package resolves correctly, not shadowed by `app/mcp/`.

- [ ] **Step 3: Verify self-gating end-to-end**

Run: `python -c "from app.mcp.server import create_server; import asyncio; s = create_server(); r = asyncio.run(s.call_tool('pallium_query', {'query': 'test'})); print(r.content[0].text)"`
Expected: Output contains "not configured"

- [ ] **Step 4: Add MCP to architecture docs**

In `docs/context/architecture.md`, add under the API layer section:

```markdown
### MCP Transport Adapter

`app/mcp/` provides a stdio MCP server that wraps the HTTP API. It is a separate
process entry point (`python -m app.run mcp`) used by MCP-compatible agent runtimes.
The MCP server depends only on `mcp[cli]` and `httpx` — no core Pallium imports.
It reads scope defaults from environment variables and proxies tool calls to the
running Pallium HTTP server.
```

- [ ] **Step 5: Commit**

```bash
git add docs/context/architecture.md
git commit -m "docs: add MCP transport adapter to architecture docs"
```

---

## Summary

| Task | What | Files | Review fixes applied |
|------|------|-------|---------------------|
| 1 | Dependencies | `pyproject.toml` | Added `pytest-asyncio` (issue #2) |
| 2 | Context resolution | `app/mcp/context.py`, tests | — |
| 3 | HTTP client | `app/mcp/client.py`, tests | Removed per-call scope overrides (#1), fixed `is not None` (#4), added HTTP error body (#5), added missing test cases (#9, #10) |
| 4 | MCP server + tools | `app/mcp/server.py`, tests | Single context resolution, no double-pass (#1), added context verification test |
| 5 | CLI entry point | `app/run.py` | Helpful import error (#6) |
| 6 | Integration test | `tests/test_mcp_integration.py` | Real MCP client → ASGI passthrough (#3), exact match assertion |
| 7 | Full suite + docs | `docs/context/architecture.md` | Concrete doc update (#7) |
