"""Async HTTP client wrapping Pallium's REST API for MCP tools.

The client reads all scope parameters (container_ref, thread_ref, actor_ref,
visibility) from the PalliumContext it receives. Context resolution (merging
explicit overrides with env var defaults) is the server layer's responsibility.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

import httpx

from app.mcp.context import PalliumContext


class PalliumMcpClient:
    """Thin HTTP client that proxies MCP tool calls to Pallium's REST API."""

    _RELAY_BUSY_ATTEMPTS = 12
    _RELAY_BUSY_BUDGET_SECONDS = 25.0

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

    def _relay_scope_params(self) -> dict[str, str]:
        """Return the exact Relay scope carried by the active context."""
        params: dict[str, str] = {}
        for key in ("container_ref", "actor_ref"):
            value = getattr(self._ctx, key, None)
            if value is not None:
                params[key] = value
        return params

    async def query(self, text: str, limit: int = 5) -> dict[str, Any]:
        payload: dict[str, Any] = {"text": text, "limit": limit}
        payload.update(self._scope_params())
        return await self._post("/query", payload)

    async def search_history(
        self,
        text: str,
        *,
        limit: int = 5,
        source_type: str | None = None,
        role: str | None = None,
        artifact_kind: str | None = None,
        work_refs: list[str] | None = None,
        request_source_item_id: str | None = None,
    ) -> dict[str, Any]:
        """Source-only history search: raw prior turns ranked on their own.

        Hardcodes ``source_only=True`` and ``trigger_origin="agent_pull"`` so
        every call through this method is unambiguously attributed as an
        agent-issued pull in the query audit log (the measurement event chain).
        """
        payload: dict[str, Any] = {
            "text": text,
            "limit": limit,
            "source_only": True,
            "trigger_origin": "agent_pull",
        }
        payload.update(self._scope_params())
        if source_type is not None:
            payload["source_type"] = source_type
        if role is not None:
            payload["role"] = role
        if artifact_kind is not None:
            payload["artifact_kind"] = artifact_kind
        if work_refs is not None:
            payload["work_refs"] = work_refs
        if request_source_item_id is not None:
            payload["request_source_item_id"] = request_source_item_id
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

    async def get_memory_expand(self, memory_object_id: str) -> dict[str, Any]:
        """Fetch payload and source items linked to a memory object, scoped to context container."""
        params: dict[str, str] = {}
        if self._ctx.container_ref:
            params["container_ref"] = self._ctx.container_ref
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=30.0) as http:
                response = await http.get(f"/memory/{memory_object_id}/expand", params=params)
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

    async def get_source_context(
        self,
        source_item_id: str,
        *,
        before: int | None = None,
        after: int | None = None,
        max_chars: int | None = None,
        include_supported_memories: bool = False,
        parent_lookup_id: str | None = None,
    ) -> dict[str, Any]:
        """Fetch a bounded neighborhood of raw turns around a source item.

        Scope (container/actor) comes from context so visibility is enforced
        for the caller.
        """
        params: dict[str, Any] = {}
        if self._ctx.container_ref:
            params["container_ref"] = self._ctx.container_ref
        actor = getattr(self._ctx, "actor_ref", None)
        if actor:
            params["query_actor_ref"] = actor
        # Active (requesting) session for reuse-funnel attribution — so the
        # expansion event records THIS session, never the historical anchor's.
        session = getattr(self._ctx, "thread_ref", None)
        if session:
            params["active_session_ref"] = session
        if self._ctx.visibility is not None:
            params["query_visibility"] = self._ctx.visibility
        if before is not None:
            params["before"] = before
        if after is not None:
            params["after"] = after
        if max_chars is not None:
            params["max_chars"] = max_chars
        if include_supported_memories:
            params["include_supported_memories"] = True
        if parent_lookup_id is not None:
            params["parent_lookup_id"] = parent_lookup_id
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=30.0) as http:
                response = await http.get(f"/source/{source_item_id}/context", params=params)
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

    async def _get_or_error(self, path: str, params: dict[str, Any]) -> Any:
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=30.0) as http:
                response = await http.get(path, params=params)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            try:
                body = exc.response.json()
            except Exception:
                body = exc.response.text
            return {"error": str(exc), "status_code": exc.response.status_code, "detail": body}
        except Exception as exc:
            return {"error": str(exc)}

    async def relay_recipients(
        self, *, runtime: str | None = None, include_inactive: bool = False
    ) -> Any:
        params = self._relay_scope_params()
        if runtime is not None:
            params["runtime"] = runtime
        if include_inactive:
            params["include_inactive"] = True
        return await self._get_or_error("/relay/sessions", params)

    async def relay_name(self, *, alias: str | None, current_runtime: str, current_session_ref: str, replace_existing: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "runtime": current_runtime,
            "session_ref": current_session_ref,
            **self._relay_scope_params(),
        }
        if alias is not None:
            payload["alias"] = alias
        if replace_existing:
            payload["replace_existing"] = True
        return await self._post_or_error("/relay/sessions/name", payload)

    async def relay_send(
        self,
        *,
        message: str,
        recipient: str,
        sender_runtime: str,
        sender_session_ref: str,
        expires_in_seconds: int | None = None,
        in_reply_to: str | None = None,
        message_id: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "payload": message,
            "recipient": recipient,
            "sender_runtime": sender_runtime,
            "sender_session_ref": sender_session_ref,
            "message_id": message_id or f"relay-msg-{uuid.uuid4().hex}",
            **self._relay_scope_params(),
        }
        for key, value in (
            ("expires_in_seconds", expires_in_seconds),
            ("in_reply_to", in_reply_to),
            ("message_id", message_id),
        ):
            if value is not None:
                payload[key] = value
        return await self._post_or_error("/relay/messages", payload, retry_relay_busy=True)

    async def relay_reply(
        self,
        *,
        delivery_id: str,
        message: str,
        receipt: str | None = None,
        expires_in_seconds: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "delivery_id": delivery_id,
            "payload": message,
            **self._relay_scope_params(),
        }
        if receipt is not None:
            payload["receipt"] = receipt
        if expires_in_seconds is not None:
            payload["expires_in_seconds"] = expires_in_seconds
        return await self._post_or_error("/relay/replies", payload, retry_relay_busy=True)

    async def relay_status(self, message_id: str) -> dict[str, Any]:
        params = self._relay_scope_params()
        return await self._get_or_error(f"/relay/messages/{message_id}", params)

    async def relay_receive(self, runtime: str, session_ref: str, max_chars: int = 0) -> Any:
        payload: dict[str, Any] = {
            "runtime": runtime,
            "session_ref": session_ref,
            "max_chars": max_chars,
            **self._relay_scope_params(),
        }
        return await self._post_or_error("/relay/turn", payload)

    async def relay_mcp_ack(self, delivery_id: str, receipt: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "delivery_id": delivery_id,
            "receipt": receipt,
            **self._relay_scope_params(),
        }
        return await self._post_or_error("/relay/deliveries/mcp-ack", payload, retry_relay_busy=True)

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

    async def rate_memory(
        self,
        memory_object_id: str,
        rating: str,
        reason: str | None = None,
        query_context: str | None = None,
        query_audit_log_id: str | None = None,
        rater_ref: str | None = None,
        thread_ref: str | None = None,
        container_ref: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"rating": rating}
        if reason is not None:
            payload["reason"] = reason
        if query_context is not None:
            payload["query_context"] = query_context
        if query_audit_log_id is not None:
            payload["query_audit_log_id"] = query_audit_log_id
        if rater_ref is not None:
            payload["rater_ref"] = rater_ref
        if thread_ref is not None:
            payload["thread_ref"] = thread_ref
        if container_ref is not None:
            payload["container_ref"] = container_ref
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=30.0) as http:
                response = await http.post(
                    f"/memory/{memory_object_id}/feedback",
                    json=payload,
                )
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

    # ── W3 explicit memory-write client methods ─────────────────────
    # Thin wrappers over /memory/remember, /memory/{id}/correct,
    # /memory/supersede, /memory/{id}/forget, /memory/record-outcome.
    # Errors surface as {"error", "status_code", "detail"} to keep the MCP
    # tool response format consistent and let the calling agent see the
    # reason (e.g. 409 Conflict) rather than an opaque exception.

    async def _post_or_error(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        retry_relay_busy: bool = False,
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=30.0) as http:
                attempts = self._RELAY_BUSY_ATTEMPTS if retry_relay_busy else 1
                deadline = (
                    time.monotonic() + self._RELAY_BUSY_BUDGET_SECONDS
                    if retry_relay_busy
                    else None
                )
                response = None
                for attempt in range(attempts):
                    if response is not None and deadline is not None and time.monotonic() >= deadline:
                        break
                    request_timeout = (
                        max(0.1, deadline - time.monotonic())
                        if deadline is not None
                        else None
                    )
                    if request_timeout is None:
                        response = await http.post(path, json=payload)
                    else:
                        response = await http.post(path, json=payload, timeout=request_timeout)
                    parse_error = None
                    try:
                        body = response.json()
                    except Exception as exc:
                        body = None
                        parse_error = exc
                    detail = body.get("detail") if isinstance(body, dict) else None
                    is_retryable_busy = (
                        response.status_code == 503
                        and isinstance(detail, dict)
                        and detail.get("code") == "relay_busy"
                        and detail.get("retryable") is True
                    )
                    if is_retryable_busy and attempt + 1 < attempts:
                        assert deadline is not None
                        remaining = deadline - time.monotonic()
                        if remaining > 0:
                            try:
                                delay = min(
                                    1.0,
                                    remaining,
                                    max(0.0, float(response.headers.get("Retry-After", "1"))),
                                )
                            except (TypeError, ValueError):
                                delay = min(1.0, remaining)
                            await asyncio.sleep(delay)
                            continue
                    response.raise_for_status()
                    if parse_error is not None:
                        raise parse_error
                    return body
                assert response is not None
                response.raise_for_status()
                raise AssertionError("unreachable")
        except httpx.HTTPStatusError as exc:
            try:
                body = exc.response.json()
            except Exception:
                body = exc.response.text
            return {
                "error": str(exc),
                "status_code": exc.response.status_code,
                "detail": body,
            }
        except Exception as exc:
            return {"error": str(exc)}
    async def remember_memory(
        self,
        *,
        text: str,
        type: str,
        confidence: float | None = None,
        evidence: list[str] | None = None,
        origin_session_id: str | None = None,
        origin_agent_id: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"text": text, "type": type}
        if confidence is not None:
            payload["confidence"] = confidence
        if evidence is not None:
            payload["evidence"] = evidence
        for key in ("container_ref", "actor_ref", "thread_ref"):
            v = getattr(self._ctx, key, None)
            if v is not None:
                payload[key] = v
        if origin_session_id is not None:
            payload["origin_session_id"] = origin_session_id
        if origin_agent_id is not None:
            payload["origin_agent_id"] = origin_agent_id
        for key in ("agent_ref", "visibility"):
            value = getattr(self._ctx, key, None)
            if value is not None:
                payload[key] = value
        return await self._post_or_error("/memory/remember", payload)

    async def correct_memory(
        self,
        memory_object_id: str,
        *,
        corrected_text: str,
        reason: str,
    ) -> dict[str, Any]:
        return await self._post_or_error(
            f"/memory/{memory_object_id}/correct",
            {"corrected_text": corrected_text, "reason": reason},
        )

    async def supersede_memory(
        self,
        *,
        new_text: str,
        supersedes_id: str,
        reason: str | None = None,
        type: str | None = None,
        origin_session_id: str | None = None,
        origin_agent_id: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "new_text": new_text,
            "supersedes_id": supersedes_id,
        }
        if reason is not None:
            payload["reason"] = reason
        if type is not None:
            payload["type"] = type
        for key in ("container_ref", "actor_ref", "thread_ref"):
            v = getattr(self._ctx, key, None)
            if v is not None:
                payload[key] = v
        if origin_session_id is not None:
            payload["origin_session_id"] = origin_session_id
        if origin_agent_id is not None:
            payload["origin_agent_id"] = origin_agent_id
        for key in ("agent_ref", "visibility"):
            value = getattr(self._ctx, key, None)
            if value is not None:
                payload[key] = value
        return await self._post_or_error("/memory/supersede", payload)

    async def forget_memory(
        self,
        memory_object_id: str,
        *,
        reason: str,
    ) -> dict[str, Any]:
        return await self._post_or_error(
            f"/memory/{memory_object_id}/forget",
            {"reason": reason},
        )

    async def forget_source(
        self,
        *,
        source_item_id: str | None = None,
        container_ref: str | None = None,
        thread_ref: str | None = None,
        reason: str,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"reason": reason}
        if source_item_id is not None:
            payload["source_item_id"] = source_item_id
        if container_ref is not None:
            payload["container_ref"] = container_ref
        if thread_ref is not None:
            payload["thread_ref"] = thread_ref
        # Scope-mode only: when neither an item id nor an explicit container is
        # given, bound the scope forget to the context container. Never widen a
        # single-item forget into a scope forget.
        if source_item_id is None and payload.get("container_ref") is None and self._ctx.container_ref:
            payload["container_ref"] = self._ctx.container_ref
        # Record the "who" for audit when the context knows the actor.
        if getattr(self._ctx, "actor_ref", None):
            payload["actor_ref"] = self._ctx.actor_ref
        return await self._post_or_error("/source/forget", payload)

    async def record_outcome(
        self,
        *,
        procedure_id: str,
        outcome: str,
        evidence: list[str] | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"procedure_id": procedure_id, "outcome": outcome}
        if evidence is not None:
            payload["evidence"] = evidence
        if note is not None:
            payload["note"] = note
        for key in ("container_ref", "actor_ref", "thread_ref", "agent_ref", "visibility"):
            value = getattr(self._ctx, key, None)
            if value is not None:
                payload[key] = value
        return await self._post_or_error("/memory/record-outcome", payload)
