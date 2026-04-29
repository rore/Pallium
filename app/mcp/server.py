"""Pallium MCP server — exposes memory tools over MCP protocol.

Wraps Pallium's HTTP API. Supports stdio (local testing) and
streamable-http (production, remote access) transports.
"""

from __future__ import annotations

import json
import os
from typing import Literal

from mcp.server.fastmcp import FastMCP

from app.mcp.client import PalliumMcpClient
from app.mcp.context import resolve_context

NOT_CONFIGURED_MSG = (
    "Pallium memory system is not configured. "
    "No memory tools available. "
    "Set PALLIUM_BASE_URL to the Pallium HTTP server URL."
)


def create_server(*, host: str = "127.0.0.1", port: int = 8001) -> FastMCP:
    """Create a FastMCP server with Pallium tools registered."""
    server = FastMCP("pallium", host=host, port=port)

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

    @server.tool()
    async def pallium_get_evidence(
        memory_object_id: str,
        container_ref: str | None = None,
        actor_ref: str | None = None,
        visibility: str | None = None,
    ) -> str:
        """Retrieve the source conversation items that a memory card was derived from. Use when an injected memory block's summary isn't enough and you need the original conversation context. Pass the memory_object_id from the [ref: ...] annotation on a memory block."""
        ctx = resolve_context(
            container_ref=container_ref,
            actor_ref=actor_ref,
            visibility=visibility,
        )
        if not ctx.is_configured:
            return NOT_CONFIGURED_MSG
        client = PalliumMcpClient(ctx)
        result = await client.get_memory_evidence(memory_object_id)
        return json.dumps(result, indent=2, default=str)

    @server.tool()
    async def pallium_flag_memory(
        memory_object_id: str,
        reason: str,
        source_ref: str | None = None,
        immediate: bool = False,
    ) -> str:
        """Flag a Pallium memory as bad. Use when an injected memory is incorrect, outdated, a meaningless fragment, or contradicts known facts. Pass the memory_object_id from the [ref: ...] annotation on the memory block. After enough independent flags, the memory is suppressed and stops being injected."""
        ctx = resolve_context()
        if not ctx.is_configured:
            return NOT_CONFIGURED_MSG
        resolved_source_ref = source_ref or ctx.actor_ref or "local"
        client = PalliumMcpClient(ctx)
        result = await client.flag_memory(
            memory_object_id=memory_object_id,
            reason=reason,
            source_ref=resolved_source_ref,
            immediate=immediate,
        )
        return json.dumps(result, indent=2, default=str)

    @server.tool()
    async def pallium_rate_memory(
        memory_object_id: str,
        rating: Literal["relevant", "not_relevant"],
        query_context: str,
        reason: str | None = None,
        thread_ref: str | None = None,
        container_ref: str | None = None,
        query_audit_log_id: str | None = None,
    ) -> str:
        """Rate an injected Pallium memory as relevant or not_relevant. Call proactively when a memory injected into this session is clearly off-topic for the current user message. rating must be 'relevant' or 'not_relevant'. reason should name the mismatch (1-2 sentences). query_context is the user message text that triggered the injection (required). query_audit_log_id links to the audit log entry for this injection if available."""
        ctx = resolve_context()
        if not ctx.is_configured:
            return NOT_CONFIGURED_MSG
        rater_ref = ctx.actor_ref or "local"
        resolved_thread_ref = thread_ref or ctx.thread_ref
        resolved_container_ref = container_ref or ctx.container_ref
        client = PalliumMcpClient(ctx)
        result = await client.rate_memory(
            memory_object_id=memory_object_id,
            rating=rating,
            reason=reason,
            query_context=query_context,
            query_audit_log_id=query_audit_log_id,
            rater_ref=rater_ref,
            thread_ref=resolved_thread_ref,
            container_ref=resolved_container_ref,
        )
        return json.dumps(result, indent=2, default=str)

    @server.tool()
    async def pallium_status() -> str:
        """Check Pallium system health and stats. Shows ingestion metrics (pending queue, source items, memory objects, storage) and injection/query stats (total queries, injection rate, skip reasons, flags). Use to diagnose whether memory is being stored and returned correctly."""
        ctx = resolve_context()
        if not ctx.is_configured:
            return NOT_CONFIGURED_MSG
        client = PalliumMcpClient(ctx)
        result = await client.get_status()
        return json.dumps(result, indent=2, default=str)

    return server


def main() -> None:
    """Run the Pallium MCP server.

    Transport and bind address are configured via environment:
      PALLIUM_MCP_TRANSPORT: "stdio" or "streamable-http" (default: streamable-http)
      FASTMCP_HOST: bind host (default: 127.0.0.1)
      FASTMCP_PORT: bind port (default: 8001)
    """
    transport_val = os.environ.get("PALLIUM_MCP_TRANSPORT", "streamable-http")
    if transport_val not in ("stdio", "sse", "streamable-http"):
        raise ValueError(f"Invalid MCP transport: {transport_val}")
    transport: Literal["stdio", "sse", "streamable-http"] = transport_val  # type: ignore[assignment]
    host = os.environ.get("FASTMCP_HOST", "127.0.0.1")
    port = int(os.environ.get("FASTMCP_PORT", "8001"))
    server = create_server(host=host, port=port)
    server.run(transport=transport)


if __name__ == "__main__":
    main()
