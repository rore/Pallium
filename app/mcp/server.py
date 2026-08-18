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
from retrieval.common import build_excerpt


_MCP_SEARCH_MAX_CHARS = 2000
_MCP_SEARCH_EMPTY_MAX_CHARS = 300
_MCP_EXPANSION_MAX_CHARS = 4000
_MCP_EXPANSION_MIN_CHARS = 256


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _bounded_error(result: dict, budget: int) -> dict:
    payload = {key: result[key] for key in ("error", "detail") if key in result}
    if len(_json_text(payload)) <= budget:
        return payload
    payload.pop("detail", None)
    if len(_json_text(payload)) <= budget:
        return payload
    error = str(payload.get("error") or "request failed")
    low, high = 0, len(error)
    while low < high:
        mid = (low + high + 1) // 2
        if len(_json_text({"error": error[:mid]})) <= budget:
            low = mid
        else:
            high = mid - 1
    compact = {"error": error[:low]}
    return compact if len(_json_text(compact)) <= budget else {}

def _compact_history(result: dict, query: str, limit: int = 3) -> dict:
    if "error" in result:
        return _bounded_error(result, _MCP_SEARCH_MAX_CHARS)
    hits = []
    for item in result.get("results", [])[:max(0, limit)]:
        if item.get("source_item_id") is None:
            continue
        hit = {"source_item_id": item["source_item_id"], "excerpt": build_excerpt(item.get("excerpt") or "", max_length=240, query=query)}
        for key in ("role", "occurred_at"):
            if item.get(key) is not None:
                hit[key] = item[key]
        hits.append(hit)
    payload = {"results": hits, "lookup_event_id": result.get("lookup_event_id")}
    budget = _MCP_SEARCH_EMPTY_MAX_CHARS if not hits else _MCP_SEARCH_MAX_CHARS
    while len(_json_text(payload)) > budget and hits:
        longest = max(hits, key=lambda hit: len(hit.get("excerpt", "")))
        excerpt = longest.get("excerpt", "")
        if not excerpt:
            hits.pop()
            payload["results"] = hits
            continue
        excess = len(_json_text(payload)) - budget
        longest["excerpt"] = excerpt[:max(0, len(excerpt) - excess - 1)]
    while len(_json_text(payload)) > budget and hits:
        hits.pop()
        payload["results"] = hits
    if len(_json_text(payload)) > budget:
        return {"error": "historical search result exceeds the response budget"}
    return payload


def _bounded_expansion(result: dict, max_chars: int = _MCP_EXPANSION_MAX_CHARS) -> dict:
    max_chars = min(_MCP_EXPANSION_MAX_CHARS, max_chars)
    if max_chars < _MCP_EXPANSION_MIN_CHARS:
        return {"error": "max_chars is too small for the expansion anchor", "min_max_chars": _MCP_EXPANSION_MIN_CHARS}
    if "error" in result:
        return _bounded_error(result, max_chars)
    projected = []
    for item in result.get("items") or []:
        projected.append({
            "source_item_id": item.get("source_item_id"),
            "is_anchor": bool(item.get("is_anchor")),
            **{k: item[k] for k in ("role", "occurred_at") if item.get(k) is not None},
            "content": item.get("content") or "",
        })
    anchor = next((item for item in projected if item.get("is_anchor")), projected[0] if projected else None)
    if anchor is None:
        out = {"items": [], "supported_memories": result.get("supported_memories"), "parent_lookup_id": result.get("parent_lookup_id")}
        if len(_json_text(out)) > max_chars:
            out["supported_memories"] = None
        if len(_json_text(out)) > max_chars:
            return {"error": "expansion exceeds the response budget", "min_max_chars": _MCP_EXPANSION_MIN_CHARS}
        return out
    full_content = {id(item): item["content"] for item in projected}
    for item in projected:
        item["content"] = ""
        if full_content[id(item)]:
            item["content_truncated"] = True
    out = {"items": projected, "supported_memories": result.get("supported_memories"), "parent_lookup_id": result.get("parent_lookup_id")}
    omitted = 0
    if len(_json_text(out)) > max_chars:
        out["supported_memories"] = None
    while len(_json_text(out)) > max_chars and len(projected) > 1:
        anchor_index = projected.index(anchor)
        farthest = max(
            (item for item in projected if not item.get("is_anchor")),
            key=lambda item: (abs(projected.index(item) - anchor_index), projected.index(item)),
            default=None,
        )
        if farthest is None:
            break
        projected.remove(farthest)
        omitted += 1
        out["items_omitted"] = omitted
    if len(_json_text(out)) > max_chars:
        return {"error": "max_chars is too small for the expansion anchor", "min_max_chars": _MCP_EXPANSION_MIN_CHARS}

    anchor_index = projected.index(anchor)
    order = [anchor_index]
    order.extend(sorted((i for i in range(len(projected)) if i != anchor_index), key=lambda i: (abs(i - anchor_index), i)))
    for index in order:
        original = projected[index]
        content = full_content[id(original)]
        if not content:
            continue
        candidate = dict(original)
        candidate["content"] = content
        candidate.pop("content_truncated", None)
        projected[index] = candidate
        if len(_json_text(out)) <= max_chars:
            continue
        projected[index] = original
        low, high = 0, len(content)
        while low < high:
            mid = (low + high + 1) // 2
            candidate = dict(original)
            candidate["content"] = content[:mid]
            candidate["content_truncated"] = True
            projected[index] = candidate
            if len(_json_text(out)) <= max_chars:
                low = mid
            else:
                high = mid - 1
            projected[index] = original
        candidate = dict(original)
        candidate["content"] = content[:low]
        candidate["content_truncated"] = True
        projected[index] = candidate
    if len(_json_text(out)) > max_chars:
        return {"error": "expansion exceeds the response budget", "min_max_chars": _MCP_EXPANSION_MIN_CHARS}
    return out
NOT_CONFIGURED_MSG = (
    "Pallium memory system is not configured. "
    "No memory tools available. "
    "Set PALLIUM_BASE_URL to the Pallium HTTP server URL."
)


def create_server(*, host: str = "127.0.0.1", port: int = 8001) -> FastMCP:
    """Create a FastMCP server with Pallium tools registered."""
    # stateless_http: every Pallium MCP tool is a single-shot RPC, so we don't
    # need server-side session affinity. Stateless mode survives server
    # restarts (sessions are otherwise in-process only) — without it, clients
    # holding a session id from before the restart get -32600 "Session not
    # found" and have to reinitialize.
    server = FastMCP("pallium", host=host, port=port, stateless_http=True)

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
    async def pallium_search_history(
        query: str,
        limit: int = 3,
        container_ref: str | None = None,
        thread_ref: str | None = None,
        actor_ref: str | None = None,
        visibility: str | None = None,
        source_type: str | None = None,
        role: str | None = None,
        artifact_kind: str | None = None,
        work_refs: list[str] | None = None,
    ) -> str:
        """Search prior raw turns for historical context. Returns compact match-centred excerpts with stable source_item_id values and lookup_event_id for optional expansion linkage."""
        ctx = resolve_context(
            container_ref=container_ref,
            thread_ref=thread_ref,
            actor_ref=actor_ref,
            visibility=visibility,
        )
        if not ctx.is_configured:
            return NOT_CONFIGURED_MSG
        client = PalliumMcpClient(ctx)
        result = await client.search_history(
            query,
            limit=limit,
            source_type=source_type,
            role=role,
            artifact_kind=artifact_kind,
            work_refs=work_refs,
        )
        return _json_text(_compact_history(result, query, limit))

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
        """Store a conversation artifact in Pallium for semantic processing. Pass artifact_kind="note" when the user explicitly asks to remember something — this preserves content faithfully with a dedicated extraction prompt. Without artifact_kind, the standard type-classification extraction pipeline is used. Do not use for routine conversation — the integration layer already ingests outputs automatically."""
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
    async def pallium_expand(
        memory_object_id: str,
        container_ref: str | None = None,
        actor_ref: str | None = None,
        visibility: str | None = None,
    ) -> str:
        """Get the full structured payload and source items for a memory object.

        Use when a memory card has [+expand] available and you need:
        - The complete structured fields (decision evidence, key findings, conclusions, etc.)
        - The original source conversation turns that backed the memory

        Returns a JSON object with 'payload' (structured fields) and 'items' (source turns).
        Pass the memory_object_id from the [ref: ...] annotation on a memory block."""
        ctx = resolve_context(
            container_ref=container_ref,
            actor_ref=actor_ref,
            visibility=visibility,
        )
        if not ctx.is_configured:
            return NOT_CONFIGURED_MSG
        client = PalliumMcpClient(ctx)
        result = await client.get_memory_expand(memory_object_id)
        return json.dumps(result, indent=2, default=str)

    @server.tool()
    async def pallium_expand_source(
        source_item_id: str,
        before: int = 1,
        after: int = 1,
        max_chars: int = 4000,
        include_supported_memories: bool = False,
        parent_lookup_id: str | None = None,
        container_ref: str | None = None,
        actor_ref: str | None = None,
        visibility: str | None = None,
        thread_ref: str | None = None,
    ) -> str:
        """Expand a raw source hit into a bounded chronological neighborhood. The anchor is always represented; pass parent_lookup_id from search to preserve lookup linkage."""
        ctx = resolve_context(
            container_ref=container_ref,
            actor_ref=actor_ref,
            visibility=visibility,
            thread_ref=thread_ref,
        )
        if not ctx.is_configured:
            return NOT_CONFIGURED_MSG
        if max_chars < _MCP_EXPANSION_MIN_CHARS:
            return _json_text(_bounded_expansion({}, max_chars))
        max_chars = min(_MCP_EXPANSION_MAX_CHARS, max_chars)
        client = PalliumMcpClient(ctx)
        result = await client.get_source_context(
            source_item_id,
            before=before,
            after=after,
            max_chars=max_chars,
            include_supported_memories=include_supported_memories,
            parent_lookup_id=parent_lookup_id,
        )
        return _json_text(_bounded_expansion(result, max_chars))
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

    # ── W3 explicit memory-write tools ─────────────────────────────
    # See docs/specs/2026-07-01-milestone-shaped-memory-contract.md §W3.
    # These tools let the agent deliberately shape memory — remember a
    # fact worth keeping, correct a wrong memory, supersede an obsolete
    # one, forget an irrelevant one, record a procedure outcome. Writes
    # are tagged origin='agent_explicit' for audit.
    #
    # Invariant 1 (retrieval is not use): none of these tools update
    # retrieval ranking or accessibility state. Confidence is audit-only.

    @server.tool()
    async def pallium_remember(
        text: str,
        type: str,
        confidence: float | None = None,
        evidence: list[str] | None = None,
        container_ref: str | None = None,
        thread_ref: str | None = None,
        actor_ref: str | None = None,
        visibility: str | None = None,
    ) -> str:
        """Explicitly store a durable fact in Pallium memory.

        Use when a fact is worth keeping across sessions and automatic
        extraction may not capture it reliably — for example, an
        architectural decision the user just made, a repository constraint
        the current session discovered, or an operational fact worth
        remembering. `type` must be one of: decision, investigation_outcome,
        constraint_memory, operational_fact, note. `text` is the fact in
        the agent's own words (max ~10k chars). `confidence` is audit-only
        (never boosts retrieval ranking). `evidence` is an optional list of
        source refs (max 5)."""
        ctx = resolve_context(
            container_ref=container_ref,
            thread_ref=thread_ref,
            actor_ref=actor_ref,
            visibility=visibility,
        )
        if not ctx.is_configured:
            return NOT_CONFIGURED_MSG
        client = PalliumMcpClient(ctx)
        result = await client.remember_memory(
            text=text,
            type=type,
            confidence=confidence,
            evidence=evidence,
        )
        return json.dumps(result, indent=2, default=str)

    @server.tool()
    async def pallium_correct(
        memory_object_id: str,
        corrected_text: str,
        reason: str,
    ) -> str:
        """Fix a memory in place — the extraction was incomplete or mislabeled.

        Use when the memory is partially wrong. For fully obsolete
        memories, use pallium_supersede instead. Returns 409 if the memory
        is not currently active — in that case, walk the supersession chain
        via pallium_expand and correct the head. `reason` should include a
        short note about the prior evidence (max 500 chars)."""
        ctx = resolve_context()
        if not ctx.is_configured:
            return NOT_CONFIGURED_MSG
        client = PalliumMcpClient(ctx)
        result = await client.correct_memory(
            memory_object_id,
            corrected_text=corrected_text,
            reason=reason,
        )
        return json.dumps(result, indent=2, default=str)

    @server.tool()
    async def pallium_supersede(
        new_text: str,
        supersedes_id: str,
        reason: str | None = None,
        type: str | None = None,
        container_ref: str | None = None,
        thread_ref: str | None = None,
        actor_ref: str | None = None,
        visibility: str | None = None,
    ) -> str:
        """Replace an obsolete memory with a new one. Both persist.

        Use when a memory is fully obsolete and a new memory replaces it
        end-to-end (e.g., "Actually, use approach Y instead of X"). The
        old memory is marked lifecycle='superseded' and gets a pointer to
        the new one. Retrieval hides superseded rows by default;
        retrospective queries can still see them. Returns 409 if the old
        memory is already superseded (first writer wins)."""
        ctx = resolve_context(
            container_ref=container_ref,
            thread_ref=thread_ref,
            actor_ref=actor_ref,
            visibility=visibility,
        )
        if not ctx.is_configured:
            return NOT_CONFIGURED_MSG
        client = PalliumMcpClient(ctx)
        result = await client.supersede_memory(
            new_text=new_text,
            supersedes_id=supersedes_id,
            reason=reason,
            type=type,
        )
        return json.dumps(result, indent=2, default=str)

    @server.tool()
    async def pallium_forget(
        memory_object_id: str,
        reason: str,
    ) -> str:
        """Soft-delete a memory. Hidden from retrieval; audit trail preserved.

        Use when a memory is irrelevant, misleading, or should not be
        surfaced again. The row stays in the database (audit / retrospective
        queries can still see it), but default retrieval excludes it.
        Idempotent — forgetting an already-forgotten memory returns
        forgotten=false. `reason` is required (max 500 chars). Distinct
        from pallium_flag_memory: forget is agent-decisive and immediate,
        flag is a votes-based suppression signal."""
        ctx = resolve_context()
        if not ctx.is_configured:
            return NOT_CONFIGURED_MSG
        client = PalliumMcpClient(ctx)
        result = await client.forget_memory(memory_object_id, reason=reason)
        return json.dumps(result, indent=2, default=str)

    @server.tool()
    async def pallium_forget_source(
        reason: str,
        source_item_id: str | None = None,
        thread_ref: str | None = None,
    ) -> str:
        """Forget raw source turns (prior conversation/agent turns). Soft + auditable.

        Use when a user asks to forget specific raw history so it no longer
        surfaces in search results or source-context expansion. This acts on
        raw SOURCE TURNS — distinct from pallium_forget, which soft-deletes
        derived MEMORY objects. Neither affects the other.

        Provide `source_item_id` to forget one turn, or omit it and pass
        `thread_ref` to forget the current container's turns in that thread
        (point-in-time: turns added later are not affected). The row is kept
        for audit (who/when/why); it is not hard-deleted. Idempotent per turn.
        `reason` is required (max 500 chars)."""
        ctx = resolve_context()
        if not ctx.is_configured:
            return NOT_CONFIGURED_MSG
        client = PalliumMcpClient(ctx)
        result = await client.forget_source(
            source_item_id=source_item_id,
            thread_ref=thread_ref,
            reason=reason,
        )
        return json.dumps(result, indent=2, default=str)

    @server.tool()
    async def pallium_record_outcome(
        procedure_id: str,
        outcome: Literal["success", "failure", "inconclusive"],
        evidence: list[str] | None = None,
        note: str | None = None,
    ) -> str:
        """Record the outcome of following an operational procedure.

        Use after attempting to apply an operational_fact memory (e.g., a
        test command, a wrapper script, a repository setup step) so
        Pallium can track which procedures actually work. `outcome` must be
        one of: success, failure, inconclusive. This is stored as an
        agent_explicit note linked to the procedure; W4 operational-fact
        memory will consume these outcomes for its success/failure
        counters. Ranking is NOT updated from these outcomes until W4
        integration testing verifies the contract."""
        ctx = resolve_context()
        if not ctx.is_configured:
            return NOT_CONFIGURED_MSG
        client = PalliumMcpClient(ctx)
        result = await client.record_outcome(
            procedure_id=procedure_id,
            outcome=outcome,
            evidence=evidence,
            note=note,
        )
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
