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

    async def get_memory_evidence(self, memory_object_id: str) -> dict[str, Any]:
        """Fetch source items linked to a memory object, scoped to context container."""
        params: dict[str, str] = {}
        if self._ctx.container_ref:
            params["container_ref"] = self._ctx.container_ref
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=30.0) as http:
                response = await http.get(f"/memory/{memory_object_id}/evidence", params=params)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            try:
                body = exc.response.json()
            except Exception:
                body = exc.response.text
            return {"error": str(exc), "detail": body}
        except Exception as exc:
            return {"error": str(exc)}

    async def get_status(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=30.0) as http:
                response = await http.get("/status")
                response.raise_for_status()
                return response.json()
        except Exception as exc:
            return {"error": str(exc)}

    async def flag_memory(
        self,
        memory_object_id: str,
        reason: str,
        source_ref: str,
        immediate: bool = False,
    ) -> dict[str, Any]:
        payload = {
            "reason": reason,
            "source_ref": source_ref,
            "immediate": immediate,
        }
        return await self._post(f"/memory/{memory_object_id}/flag", payload)
