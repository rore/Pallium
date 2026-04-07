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
