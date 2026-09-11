"""Pallium MCP server — exposes memory tools over MCP protocol.

Wraps Pallium's HTTP API. Supports stdio (local testing) and
streamable-http (production, remote access) transports.
"""

from __future__ import annotations

import json
import os
from functools import wraps
from typing import Annotated, Literal

from pydantic import BeforeValidator

from app.mcp.client import PalliumMcpClient
from app.mcp.context import resolve_codex_thread_ref, resolve_context, resolve_relay_context
from core.work_ref import readable_work_ref
from redaction import redact_sensitive
from retrieval.common import build_excerpt


_MCP_SEARCH_MAX_CHARS = 2000
_MCP_SEARCH_EMPTY_MAX_CHARS = 300
_MCP_EXPANSION_MAX_CHARS = 4000
_MCP_EXPANSION_MIN_CHARS = 256
_MCP_RELAY_MAX_CHARS = 2000
_MCP_RELAY_MIN_CHARS = 256
_MCP_RELAY_WORK_REFS_MAX_CHARS = 12000


def _mask_invalid_work_ref(value: object) -> object:
    """Keep malformed values out of public validation errors."""
    return value if isinstance(value, str) else "\x00"



def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _history_fields(item: dict) -> dict:
    fields = {
        key: item[key]
        for key in ("recorded_at", "recorded_at_source")
        if item.get(key) is not None
    }
    updates = [
        {
            key: update[key]
            for key in (
                "memory_type",
                "status",
                "replacement_status",
                "current_memory_object_id",
                "current_text",
                "current_text_truncated",
                "current_recorded_at",
            )
            if update.get(key) is not None
        }
        for update in item.get("historical_updates") or []
    ]
    if updates:
        fields["historical_updates"] = updates
    omitted = item.get("historical_updates_omitted") or 0
    if omitted:
        fields["historical_updates_omitted"] = omitted
    return fields


def _trim_update_details(payload: dict, items: list[dict], budget: int) -> None:
    while len(_json_text(payload)) > budget:
        texts = [
            update
            for item in items
            for update in item.get("historical_updates") or []
            if update.get("current_text")
        ]
        if not texts:
            break
        longest = max(texts, key=lambda update: len(update["current_text"]))
        excess = len(_json_text(payload)) - budget
        longest["current_text_truncated"] = True
        longest["current_text"] = longest["current_text"][
            : max(0, len(longest["current_text"]) - excess - 1)
        ]
        if not longest["current_text"]:
            longest.pop("current_text", None)
    while len(_json_text(payload)) > budget:
        removable = [
            (item, index, update)
            for item in items
            if len(item.get("historical_updates") or []) > 1
            for index, update in enumerate(item["historical_updates"])
        ]
        if not removable:
            break
        item, index, _ = min(
            removable,
            key=lambda candidate: candidate[2].get("replacement_status") == "current",
        )
        item["historical_updates"].pop(index)
        item["historical_updates_omitted"] = item.get("historical_updates_omitted", 0) + 1


def _strip_pydantic_input(detail: object) -> object:
    """Remove 'input' and 'url' from Pydantic validation error items.

    FastAPI echoes the full request value in each item's 'input' field, which
    can inflate a 422 detail past the MCP relay budget and cause it to be dropped.
    """
    if isinstance(detail, dict) and isinstance(detail.get("detail"), list):
        stripped = [
            {k: v for k, v in item.items() if k not in ("input", "url")}
            if isinstance(item, dict)
            else item
            for item in detail["detail"]
        ]
        return {**detail, "detail": stripped}
    return detail


def _bounded_error(result: dict, budget: int) -> dict:
    payload = {
        key: result[key]
        for key in ("error", "status_code", "detail", "min_max_chars", "error_kind", "retryable", "action")
        if key in result
    }
    if "detail" in payload:
        payload["detail"] = _strip_pydantic_input(payload["detail"])
    if len(_json_text(payload)) <= budget:
        return payload
    payload.pop("detail", None)
    if len(_json_text(payload)) <= budget:
        return payload
    error = str(payload.get("error") or "request failed")
    base = {"status_code": payload["status_code"]} if "status_code" in payload else {}
    low, high = 0, len(error)
    while low < high:
        mid = (low + high + 1) // 2
        if len(_json_text({"error": error[:mid], **base})) <= budget:
            low = mid
        else:
            high = mid - 1
    compact = {"error": error[:low], **base}
    return compact if len(_json_text(compact)) <= budget else {}


def _redact_error_value(value: object) -> object:
    if isinstance(value, str):
        return redact_sensitive(value)
    if isinstance(value, list):
        return [_redact_error_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_error_value(item) for key, item in value.items()}
    return value


def _relay_error_text(result: object, budget: int = _MCP_RELAY_MAX_CHARS) -> str:
    redacted = _redact_error_value(result)
    payload = _bounded_error(redacted, budget) if isinstance(redacted, dict) else {
        "error": redact_sensitive(str(result)),
    }
    return _json_text(payload)


def _relay_text(result: object) -> str:
    """Serialize normal Relay responses compactly while keeping errors visible."""
    if isinstance(result, dict) and "error" in result:
        return _relay_error_text(result)
    if not isinstance(result, dict):
        return _relay_error_text({"error": "invalid relay response"})
    deliveries = result.get("deliveries")
    if isinstance(deliveries, list):
        result = {
            **result,
            "deliveries": [
                {key: value for key, value in delivery.items() if key != "claim_token"}
                if isinstance(delivery, dict) else delivery
                for delivery in deliveries
            ],
        }
    if len(_json_text(result)) <= _MCP_RELAY_MAX_CHARS:
        return _json_text(result)
    deliveries = result.get("deliveries")
    if isinstance(deliveries, list):
        states: dict[str, int] = {}
        projected = []
        delivery_fields = (
            "recipient_endpoint_id",
            "recipient_runtime",
            "recipient_session_ref",
            "recipient_container_ref",
            "state",
            "destination_health",
        )
        for delivery in deliveries:
            state = str(delivery.get("state", "unknown"))
            states[state] = states.get(state, 0) + 1
            projected.append({key: delivery[key] for key in delivery_fields if key in delivery})
        summary = {
            key: result[key]
            for key in ("message_id", "recipient", "redacted", "in_reply_to", "created_at", "expires_at")
            if key in result
        }
        summary.update(
            delivery_count=len(deliveries),
            delivery_states=states,
            deliveries=projected,
        )
        payload = result.get("payload")
        has_redacted_payload = result.get("redacted") is True and isinstance(payload, str)
        if has_redacted_payload:
            summary["payload_omitted"] = True

        if len(_json_text(summary)) > _MCP_RELAY_MAX_CHARS and "recipient" in summary:
            summary.pop("recipient")
            summary["response_fields_omitted"] = ["recipient"]
        for key in ("recipient_session_ref", "recipient_container_ref"):
            for delivery in projected:
                if len(_json_text(summary)) <= _MCP_RELAY_MAX_CHARS:
                    break
                if key in delivery:
                    delivery.pop(key)
                    delivery.setdefault("omitted_fields", []).append(key)
        while projected and len(_json_text(summary)) > _MCP_RELAY_MAX_CHARS:
            projected.pop()
            summary["deliveries_omitted"] = len(deliveries) - len(projected)

        if has_redacted_payload:
            summary.pop("payload_omitted")
            summary["payload"] = payload
            if len(_json_text(summary)) > _MCP_RELAY_MAX_CHARS:
                summary["payload_truncated"] = True
                marker = "…[truncated]"
                summary["payload"] = marker
                if len(_json_text(summary)) > _MCP_RELAY_MAX_CHARS:
                    summary.pop("payload")
                    summary.pop("payload_truncated")
                    summary["payload_omitted"] = True
                else:
                    low, high = 0, len(payload)
                    while low < high:
                        mid = (low + high + 1) // 2
                        summary["payload"] = payload[:mid] + marker
                        if len(_json_text(summary)) <= _MCP_RELAY_MAX_CHARS:
                            low = mid
                        else:
                            high = mid - 1
                    summary["payload"] = payload[:low] + marker
        return _json_text(summary)
    return _relay_error_text({"error": "relay response exceeds the response budget"})

def _relay_status_text(result: object, offset: int) -> str:
    if isinstance(result, dict) and "error" in result:
        return _relay_error_text(result)
    if not isinstance(result, dict) or not isinstance(result.get("payload"), str):
        return _relay_error_text({"error": "invalid relay status response"})

    payload = result["payload"]
    payload_offset = result.get("payload_offset")
    total = result.get("payload_total_chars")
    truncated = result.get("content_truncated")
    next_offset = result.get("next_offset")
    valid = (
        type(payload_offset) is int
        and payload_offset == offset
        and type(total) is int
        and total >= payload_offset + len(payload)
        and type(truncated) is bool
        and (next_offset is None or (type(next_offset) is int and next_offset > payload_offset))
        and next_offset == (payload_offset + len(payload) if payload_offset + len(payload) < total else None)
        and truncated == (payload_offset != 0 or next_offset is not None)
    )
    if not valid:
        return _relay_error_text({"error": "invalid relay status pagination metadata", "offset": offset})

    deliveries = result.get("deliveries")
    if not isinstance(deliveries, list):
        return _relay_error_text({"error": "invalid relay status response"})
    states: dict[str, int] = {}
    safe_deliveries = []
    for delivery in deliveries:
        if not isinstance(delivery, dict):
            return _relay_error_text({"error": "invalid relay status response"})
        safe_delivery = {key: value for key, value in delivery.items() if key != "claim_token"}
        safe_deliveries.append(safe_delivery)
        state = str(safe_delivery.get("state", "unknown"))
        states[state] = states.get(state, 0) + 1
    deliveries = safe_deliveries
    result = {**result, "deliveries": deliveries}

    full_text = _json_text(result)
    if len(full_text) <= _MCP_RELAY_MAX_CHARS:
        return full_text

    def page(chars: int) -> dict[str, object]:
        body = payload[:chars]
        continued = payload_offset + chars < total
        return {
            **{
                key: result[key]
                for key in (
                    "message_id", "sender_runtime", "sender_session_ref", "redacted",
                    "in_reply_to", "created_at", "expires_at",
                )
                if key in result
            },
            "payload": body,
            "payload_offset": payload_offset,
            "payload_total_chars": total,
            "content_truncated": payload_offset != 0 or continued,
            "next_offset": payload_offset + chars if continued else None,
            "delivery_count": len(deliveries),
            "delivery_states": states,
        }

    low, high = 0, len(payload)
    while low < high:
        middle = (low + high + 1) // 2
        if len(_json_text(page(middle))) <= _MCP_RELAY_MAX_CHARS:
            low = middle
        else:
            high = middle - 1
    if low == 0 and total > payload_offset:
        return _relay_error_text({"error": "relay status metadata exceeds the response budget", "offset": offset})
    return _json_text(page(low))


def _relay_recipients_text(result: object, offset: int = 0) -> str:
    """Serialize one deterministic recipient page within the MCP Relay budget."""
    if offset < 0:
        return _relay_error_text({"error": "offset must be non-negative"})
    if isinstance(result, dict) and "error" in result:
        return _relay_error_text(result)
    if not isinstance(result, list) or not all(isinstance(row, dict) for row in result):
        return _relay_error_text({"error": "invalid relay recipients response"})

    rows = [dict(row) for row in result]
    rows.sort(key=lambda row: str(row.get("session_ref", "")))
    rows.sort(key=lambda row: str(row.get("last_seen_at", "")), reverse=True)
    rows.sort(key=lambda row: str(row.get("runtime", "")))
    for row in rows:
        row["exact_selector"] = row.get("endpoint_id")
        if row.get("alias"):
            row["alias_selector"] = f"@{row['alias']}"

    total = len(rows)

    def envelope(page: list[dict]) -> dict:
        next_offset = offset + len(page)
        return {
            "recipients": page,
            "offset": offset,
            "next_offset": next_offset if next_offset < total else None,
            "has_more": next_offset < total,
            "total_count": total,
        }

    page: list[dict] = []
    for row in rows[offset:]:
        if len(_json_text(envelope([*page, row]))) > _MCP_RELAY_MAX_CHARS:
            break
        page.append(row)
    payload = envelope(page)
    if not page and offset < total:
        return _relay_error_text({"error": "relay recipient entry exceeds the response budget", "offset": offset})
    return _json_text(payload)

def _compact_history(
    result: dict,
    query: str,
    limit: int = 3,
    container_ref: str | None = None,
    thread_ref: str | None = None,
    search_mode: str | None = None,
    requested_work_ref: str | None = None,
) -> dict:
    if "error" in result:
        return _bounded_error(result, _MCP_SEARCH_MAX_CHARS)
    hits = []
    foreign_sessions: dict[str, str] = {}
    for item in result.get("results", [])[:max(0, limit)]:
        if item.get("source_item_id") is None:
            continue
        updates = item.get("historical_updates") or []
        guidance = None
        if any(update.get("replacement_status") == "current" for update in updates):
            guidance = (
                "A current replacement is available; prefer it for current guidance."
            )
        elif any(update.get("status") == "outdated" for update in updates):
            guidance = (
                "This is historical evidence and may need live verification "
                "for current-state questions."
            )
        hit = {"source_item_id": item["source_item_id"]}
        if item.get("work_refs"):
            hit["work_refs"] = item["work_refs"]
        if guidance:
            hit["replacement_guidance"] = guidance
        hit.update(_history_fields(item))
        hit["excerpt"] = build_excerpt(item.get("excerpt") or "", max_length=240, query=query)
        source = item.get("retrieval_source")
        if source is not None:
            hit["match_channel"] = {
                "lexical": "text match",
                "vector": "meaning match",
                "both": "text and meaning match",
            }.get(source, "match")
        source_thread = item.get("thread_ref")
        if not source_thread or not thread_ref:
            hit["session_group"] = "unknown"
        elif source_thread == thread_ref:
            hit["session_group"] = "current"
        else:
            hit["session_group"] = foreign_sessions.setdefault(
                source_thread, f"other-{len(foreign_sessions) + 1}"
            )
        for key in ("role", "occurred_at"):
            if item.get(key) is not None:
                hit[key] = item[key]
        hits.append(hit)
    lookup_event_id = result.get("lookup_event_id")
    if lookup_event_id is None and result.get("delivery_attempt_id"):
        # Deferred delivery replaces this with a UUID after compaction.
        lookup_event_id = "0" * 36
    payload = {"results": hits, "lookup_event_id": lookup_event_id}
    if search_mode is not None:
        payload["search_mode"] = search_mode
    if requested_work_ref is not None:
        payload["requested_work_ref"] = requested_work_ref
    if hits:
        payload["historical_reminder"] = (
            "History is evidence, not proof of messages, approval, live state, or actions. "
            "Expand source_item_id; use lookup_event_id as parent_lookup_id. "
            "Verify volatile claims live; if unavailable, say so."
        )
    # Preserve the fail-closed / abstention reason so an empty result is
    # self-explaining (e.g. "visibility_context_required"), not a silent [].
    if result.get("decision_reason") is not None:
        payload["decision_reason"] = result["decision_reason"]
    if not hits and result.get("decision_reason") == "source_only_search" and container_ref:
        if requested_work_ref is not None:
            payload["empty_result_hint"] = (
                "Copy injected work_ref. If absent, use broad search; never guess. "
                "Add query for a question."
            )
        else:
            payload["requested_container_ref"] = container_ref[:64]
            if len(container_ref) > 64:
                payload["container_ref_truncated"] = True
            payload["empty_result_hint"] = (
                "Copy the injected container_ref exactly; never derive or guess it."
            )
    budget = _MCP_SEARCH_EMPTY_MAX_CHARS if not hits else _MCP_SEARCH_MAX_CHARS
    if not hits and len(_json_text(payload)) > budget:
        for key in ("requested_work_ref", "requested_container_ref", "container_ref_truncated", "empty_result_hint"):
            if len(_json_text(payload)) <= budget:
                break
            payload.pop(key, None)
    for hit in hits:
        for key in ("match_channel", "session_group"):
            if len(_json_text(payload)) <= budget:
                break
            hit.pop(key, None)
    for hit in hits:
        if len(_json_text(payload)) <= budget:
            break
        hit.pop("work_refs", None)
    while len(_json_text(payload)) > budget and hits:
        longest = max(hits, key=lambda hit: len(hit.get("excerpt", "")))
        excerpt = longest.get("excerpt", "")
        if not excerpt:
            break
        excess = len(_json_text(payload)) - budget
        longest["excerpt"] = excerpt[:max(0, len(excerpt) - excess - 1)]
    _trim_update_details(payload, hits, budget)
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
            "presentation_role": "anchor" if item.get("is_anchor") else "neighbor",
            **{k: item[k] for k in ("role", "occurred_at") if item.get(k) is not None},
            **_history_fields(item),
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
    _trim_update_details(out, projected, max_chars)
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
    from mcp.server.fastmcp import Context, FastMCP
    try:
        from mcp.server.fastmcp.exceptions import ToolError
    except ImportError:
        from mcp.server.fastmcp import ToolError
    # stateless_http: every Pallium MCP tool is a single-shot RPC, so we don't
    # need server-side session affinity. Stateless mode survives server
    # restarts (sessions are otherwise in-process only) — without it, clients
    # holding a session id from before the restart get -32600 "Session not
    # found" and have to reinitialize.
    server = FastMCP("pallium", host=host, port=port, stateless_http=True)

    def relay_tool(function):
        @wraps(function)
        async def wrapped(*args, **kwargs):
            result = await function(*args, **kwargs)
            if not isinstance(result, str):
                return result
            try:
                payload = json.loads(result)
            except (TypeError, ValueError):
                payload = {"error": result}
            if not isinstance(payload, dict):
                payload = {"error": "invalid relay response"}
            if "error" in payload:
                budget = (
                    _MCP_RELAY_WORK_REFS_MAX_CHARS
                    if function.__name__ in {
                        "pallium_relay_work_refs",
                        "pallium_relay_attach_work_ref",
                        "pallium_relay_detach_work_ref",
                        "pallium_relay_participants",
                    }
                    else _MCP_RELAY_MAX_CHARS
                )
                if function.__name__ == "pallium_relay_receive":
                    requested = kwargs.get("max_chars", args[0] if args else 0)
                    if type(requested) is int and requested >= _MCP_RELAY_MIN_CHARS:
                        budget = min(requested, _MCP_RELAY_MAX_CHARS)
                prefix = f"Error executing tool {function.__name__}: "
                raise ToolError(_relay_error_text(payload, max(2, budget - len(prefix))))
            return result
        return wrapped

    def current_relay_identity(ctx, request_ctx):
        runtime = ctx.agent_ref
        session_ref = ctx.thread_ref
        if not runtime:
            return None, None, (
                "Error: PALLIUM_AGENT_REF is not set. Relay work-reference tools "
                "require integration-injected runtime identity."
            )
        if runtime == "codex":
            metadata = None
            if request_ctx:
                try:
                    metadata = request_ctx.request_context.meta
                except ValueError:
                    pass
            session_ref, metadata_error = resolve_codex_thread_ref(metadata)
            if metadata_error:
                return None, None, (
                    f"Error: {metadata_error}; upgrade or reload Codex, then retry. "
                    "Relay work-reference tools remain fail-closed."
                )
        if not session_ref:
            return None, None, (
                "Error: PALLIUM_THREAD_REF is not set. Relay work-reference tools "
                "require integration-injected session identity."
            )
        return runtime, session_ref, None
    @server.tool()
    async def pallium_query(
        query: str,
        limit: int = 5,
        container_ref: str | None = None,
        thread_ref: str | None = None,
        actor_ref: str | None = None,
        visibility: str | None = None,
    ) -> str:
        """Search Pallium memory. Use when automatic memory injection is missing something specific — e.g. a past decision, investigation outcome, or context from a previous conversation that wasn't auto-injected. Requires a visibility context: pass BOTH `container_ref` and `visibility` (e.g. "private"), or the search fails closed and returns no results with `decision_reason: "visibility_context_required"`."""
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
    async def pallium_search_history_by_work_ref(
        work_ref: Annotated[str, BeforeValidator(_mask_invalid_work_ref)],
        query: str | None = None, limit: int = 3,
        container_ref: str | None = None, thread_ref: str | None = None,
        actor_ref: str | None = None, visibility: str | None = None,
        request_source_item_id: str | None = None,
    ) -> str:
        """A narrow exact-reference search for current work. Copy injected `work_ref`; never guess it. It can miss related work; use broad topic-level search then. Blank `query` resumes newest state. Omitted `actor_ref` spans eligible actors; supplied is an exact metadata filter."""
        from core.work_ref import work_refs_from_metadata

        requested_refs = work_refs_from_metadata({"pallium_work_refs": [work_ref]})
        if len(requested_refs) != 1:
            return _json_text({"error": "work_ref must be one valid identifier"})
        requested_work_ref = requested_refs[0]
        ctx = resolve_context(container_ref=container_ref, thread_ref=thread_ref, actor_ref=actor_ref, visibility=visibility)
        if not ctx.is_configured:
            return NOT_CONFIGURED_MSG
        client = PalliumMcpClient(ctx)
        result = await client.search_history_by_work_ref(
            requested_work_ref, query, limit=limit,
            actor_ref=actor_ref,
            request_source_item_id=request_source_item_id, defer_delivery=True,
        )
        compact = _compact_history(
            result, query or "", limit, ctx.container_ref, ctx.thread_ref,
            search_mode="exact_work_ref", requested_work_ref=requested_work_ref,
        )
        if "error" not in compact and result.get("delivery_attempt_id"):
            receipt = await client.finalize_historical_delivery(
                result["delivery_attempt_id"],
                items=[{"source_item_id": item["source_item_id"], "role": "search_match"} for item in compact.get("results", [])],
            )
            if receipt.get("error"):
                return _json_text(receipt)
            compact["lookup_event_id"] = receipt.get("lookup_event_id")
        return _json_text(compact)

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
        request_source_item_id: str | None = None,
    ) -> str:
        """Search eligible raw history by topic. `work_refs` is compatibility-only; prefer exact work-ref search. History cannot prove messages were received or sent, live state was checked, approval was received, or actions were completed; verify live. Use `current_text` over outdated `historical_updates`. Copy injected `container_ref`. Omitted `actor_ref` spans eligible actors; supplied is an exact metadata filter. Requires `container_ref` and visibility."""
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
            actor_ref=actor_ref,
            work_refs=work_refs,
            request_source_item_id=request_source_item_id,
            defer_delivery=True,
        )
        compact = _compact_history(result, query, limit, ctx.container_ref, ctx.thread_ref)
        if "error" not in compact and result.get("delivery_attempt_id"):
            receipt = await client.finalize_historical_delivery(
                result["delivery_attempt_id"],
                items=[
                    {
                        "source_item_id": item["source_item_id"],
                        "role": "search_match",
                    }
                    for item in compact.get("results", [])
                ],
            )
            if receipt.get("error"):
                return _json_text(receipt)
            compact["lookup_event_id"] = receipt.get("lookup_event_id")
        return _json_text(compact)

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
        """Expand a raw hit around its anchor. Omitted `actor_ref` spans eligible actors; supplied is an exact metadata filter. Treat outdated `historical_updates` as historical; pass `parent_lookup_id` from search."""
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
            actor_ref=actor_ref,
            defer_delivery=True,
        )
        bounded = _bounded_expansion(result, max_chars)
        attempt_id = result.get("delivery_attempt_id")
        if "error" not in bounded and attempt_id:
            receipt = await client.finalize_historical_delivery(
                attempt_id,
                items=[
                    {
                        "source_item_id": item["source_item_id"],
                        "role": "anchor" if item.get("is_anchor") else "neighbor",
                    }
                    for item in bounded.get("items", [])
                ],
            )
            if receipt.get("error"):
                return _json_text(receipt)
        return _json_text(bounded)
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

    @server.tool()
    @relay_tool
    async def pallium_relay_recipients(
        runtime: str | None = None,
        session_ref: str | None = None,
        include_inactive: bool = False,
        container_ref: str | None = None,
        offset: int = 0,
    ) -> str:
        """Return a bounded Relay address-book page. For exact session_ref lookup, runtime is required. Each item includes canonical exact_selector (relay-session-...) and optional service-global alias_selector (`@name`; internal wire-field name). Continue with next_offset; use pallium_relay_receive for inbox delivery."""
        if offset < 0:
            return _relay_recipients_text([], offset)
        ctx, scope_error = resolve_relay_context(container_ref=container_ref)
        if scope_error:
            return scope_error
        if not ctx.is_configured:
            return NOT_CONFIGURED_MSG
        result = await PalliumMcpClient(ctx).relay_recipients(
            runtime=runtime, session_ref=session_ref, include_inactive=include_inactive,
        )
        return _relay_recipients_text(result, offset)

    @server.tool()
    @relay_tool
    async def pallium_relay_name(
        current_runtime: str,
        current_session_ref: str,
        name: str | None = None,
        replace_existing: bool = False,
        container_ref: str | None = None,
    ) -> str:
        """Name the current Relay endpoint. Copy current_runtime from injected agent_ref and current_session_ref from injected thread_ref; never discover self from recipient listings. First try without takeover. If the service-global name is occupied, ask the user before retrying with replace_existing=true. Use replace_existing=true immediately only when the user already explicitly said to take over that name."""
        ctx, scope_error = resolve_relay_context(container_ref=container_ref)
        if scope_error:
            return scope_error
        if not ctx.is_configured:
            return NOT_CONFIGURED_MSG
        result = await PalliumMcpClient(ctx).relay_name(
            alias=name,
            current_runtime=current_runtime,
            current_session_ref=current_session_ref,
            replace_existing=replace_existing,
        )
        return _relay_text(result)

    async def pallium_relay_work_refs(
        container_ref: str | None = None,
        request_ctx: object | None = None,
    ) -> str:
        """List this session's readable Relay work references. Returned exact keys can be copied into the existing exact History search. Registry membership is durable; History coverage is evaluated per turn."""
        ctx, scope_error = resolve_relay_context(container_ref=container_ref)
        if scope_error:
            return scope_error
        if not ctx.is_configured:
            return NOT_CONFIGURED_MSG
        runtime, session_ref, identity_error = current_relay_identity(ctx, request_ctx)
        if identity_error:
            return identity_error
        result = await PalliumMcpClient(ctx).relay_work_refs(
            current_runtime=runtime,
            current_session_ref=session_ref,
        )
        if isinstance(result, dict) and "error" in result:
            return _relay_error_text(result, _MCP_RELAY_WORK_REFS_MAX_CHARS)
        if not isinstance(result, dict):
            return _relay_error_text({"error": "invalid relay work-reference response"}, _MCP_RELAY_WORK_REFS_MAX_CHARS)
        rendered = _json_text(result)
        return rendered if len(rendered) <= _MCP_RELAY_WORK_REFS_MAX_CHARS else _relay_error_text(
            {"error": "relay work-reference response exceeds the response budget"},
            _MCP_RELAY_WORK_REFS_MAX_CHARS,
        )

    pallium_relay_work_refs.__annotations__["request_ctx"] = Context | None
    server.tool()(relay_tool(pallium_relay_work_refs))

    async def pallium_relay_attach_work_ref(
        scope_ref: str,
        local_ref: str,
        container_ref: str | None = None,
        request_ctx: object | None = None,
    ) -> str:
        """Attach one readable explicit work reference to this exact Relay session. The response includes the canonical exact key and guidance for the existing exact History search."""
        ctx, scope_error = resolve_relay_context(container_ref=container_ref)
        if scope_error:
            return scope_error
        if not ctx.is_configured:
            return NOT_CONFIGURED_MSG
        runtime, session_ref, identity_error = current_relay_identity(ctx, request_ctx)
        if identity_error:
            return identity_error
        result = await PalliumMcpClient(ctx).relay_attach_work_ref(
            current_runtime=runtime,
            current_session_ref=session_ref,
            scope_ref=scope_ref,
            local_ref=local_ref,
        )
        if isinstance(result, dict) and "error" in result:
            return _relay_error_text(result, _MCP_RELAY_WORK_REFS_MAX_CHARS)
        if not isinstance(result, dict):
            return _relay_error_text({"error": "invalid relay work-reference response"}, _MCP_RELAY_WORK_REFS_MAX_CHARS)
        rendered = _json_text(result)
        return rendered if len(rendered) <= _MCP_RELAY_WORK_REFS_MAX_CHARS else _relay_error_text(
            {"error": "relay work-reference response exceeds the response budget"},
            _MCP_RELAY_WORK_REFS_MAX_CHARS,
        )

    pallium_relay_attach_work_ref.__annotations__["request_ctx"] = Context | None
    server.tool()(relay_tool(pallium_relay_attach_work_ref))

    async def pallium_relay_detach_work_ref(
        scope_ref: str,
        local_ref: str,
        container_ref: str | None = None,
        request_ctx: object | None = None,
    ) -> str:
        """Detach only this session's explicit origin for one readable work reference. A structural origin may remain and is reported."""
        ctx, scope_error = resolve_relay_context(container_ref=container_ref)
        if scope_error:
            return scope_error
        if not ctx.is_configured:
            return NOT_CONFIGURED_MSG
        runtime, session_ref, identity_error = current_relay_identity(ctx, request_ctx)
        if identity_error:
            return identity_error
        result = await PalliumMcpClient(ctx).relay_detach_work_ref(
            current_runtime=runtime,
            current_session_ref=session_ref,
            scope_ref=scope_ref,
            local_ref=local_ref,
        )
        if isinstance(result, dict) and "error" in result:
            return _relay_error_text(result, _MCP_RELAY_WORK_REFS_MAX_CHARS)
        if not isinstance(result, dict):
            return _relay_error_text({"error": "invalid relay work-reference response"}, _MCP_RELAY_WORK_REFS_MAX_CHARS)
        rendered = _json_text(result)
        return rendered if len(rendered) <= _MCP_RELAY_WORK_REFS_MAX_CHARS else _relay_error_text(
            {"error": "relay work-reference response exceeds the response budget"},
            _MCP_RELAY_WORK_REFS_MAX_CHARS,
        )

    pallium_relay_detach_work_ref.__annotations__["request_ctx"] = Context | None
    server.tool()(relay_tool(pallium_relay_detach_work_ref))

    @server.tool()
    @relay_tool
    async def pallium_relay_participants(
        scope_ref: str,
        local_ref: str,
        include_closed: bool = False,
        container_ref: str | None = None,
        offset: int = 0,
    ) -> str:
        """Find a bounded service-global page of Relay sessions with one exact readable work reference. Dormant sessions are included; closed sessions require include_closed=true. Continue with next_offset when present."""
        if offset < 0:
            return _relay_error_text({"error": "offset must be non-negative"})
        try:
            readable_work_ref(scope_ref, local_ref)
        except ValueError:
            return _relay_error_text({"error": "invalid readable work reference"})
        ctx, scope_error = resolve_relay_context(container_ref=container_ref)
        if scope_error:
            return scope_error
        if not ctx.is_configured:
            return NOT_CONFIGURED_MSG
        result = await PalliumMcpClient(ctx).relay_work_ref_participants(
            scope_ref=scope_ref,
            local_ref=local_ref,
            include_closed=include_closed,
            offset=offset,
            limit=5,
        )
        if not isinstance(result, dict) or not isinstance(result.get("participants"), list):
            if isinstance(result, dict) and "error" in result:
                return _relay_error_text(result, _MCP_RELAY_WORK_REFS_MAX_CHARS)
            rendered = _json_text(result)
            return rendered if len(rendered) <= _MCP_RELAY_WORK_REFS_MAX_CHARS else _relay_error_text(
                {"error": "relay participant response exceeds the response budget"},
                _MCP_RELAY_WORK_REFS_MAX_CHARS,
            )
        result = dict(result)
        participants = list(result["participants"])
        fetched_count = len(participants)
        while participants:
            result["participants"] = participants
            result["next_offset"] = (
                offset + len(participants)
                if len(participants) < fetched_count or fetched_count == 5
                else None
            )
            rendered = _json_text(result)
            if len(rendered) <= _MCP_RELAY_WORK_REFS_MAX_CHARS:
                return rendered
            participants.pop()
        result["participants"] = []
        result["next_offset"] = None
        rendered = _json_text(result)
        return rendered if len(rendered) <= _MCP_RELAY_WORK_REFS_MAX_CHARS else _relay_error_text(
            {"error": "relay participant response exceeds the response budget"},
            _MCP_RELAY_WORK_REFS_MAX_CHARS,
        )
    @server.tool()
    @relay_tool
    async def pallium_relay_send(
        message: str,
        recipient: str,
        sender_runtime: str,
        sender_session_ref: str,
        expires_in_seconds: int | None = None,
        container_ref: str | None = None,
    ) -> str:
        """Send new text of at most 16,000 Unicode code points to one canonical endpoint ID (relay-session-...) or service-global name (@review). For a role recipient, use its current @name; before reusing an exact endpoint, rediscover and verify its session/container. Returned delivery identity is the admission snapshot. Bare runtimes are rejected and broadcast is not supported. Copy sender_runtime from injected agent_ref and sender_session_ref from injected thread_ref. Use pallium_relay_reply for one reply to a received delivery."""
        ctx, scope_error = resolve_relay_context(container_ref=container_ref)
        if scope_error:
            return scope_error
        if not ctx.is_configured:
            return NOT_CONFIGURED_MSG
        result = await PalliumMcpClient(ctx).relay_send(
            message=message,
            recipient=recipient,
            sender_runtime=sender_runtime,
            sender_session_ref=sender_session_ref,
            expires_in_seconds=expires_in_seconds,
        )
        return _relay_text(result)

    @server.tool()
    @relay_tool
    async def pallium_relay_reply(
        delivery_id: str,
        message: str,
        receipt: str | None = None,
        expires_in_seconds: int | None = None,
        container_ref: str | None = None,
    ) -> str:
        """Reply once to a received Relay delivery with at most 16,000 Unicode code points. A delivery permits one idempotent reply. If this MCP configuration lacks Relay scope, copy container_ref from injected scope. When replying via pallium_relay_receive, also pass the receipt — this atomically ACKs and replies in one step. Hook-injected delivery replies need no receipt."""
        ctx, scope_error = resolve_relay_context(container_ref=container_ref)
        if scope_error:
            return scope_error
        if not ctx.is_configured:
            return NOT_CONFIGURED_MSG
        result = await PalliumMcpClient(ctx).relay_reply(
            delivery_id=delivery_id,
            receipt=receipt,
            message=message,
            expires_in_seconds=expires_in_seconds,
        )
        return _relay_text(result)
    @server.tool()
    @relay_tool
    async def pallium_relay_status(
        message_id: str,
        offset: int = 0,
        container_ref: str | None = None,
    ) -> str:
        """Read a bounded Relay body page and compact delivery status. Continue with next_offset until null."""
        if offset < 0:
            return _relay_error_text({"error": "offset must be non-negative"})
        ctx, scope_error = resolve_relay_context(container_ref=container_ref)
        if scope_error:
            return scope_error
        if not ctx.is_configured:
            return NOT_CONFIGURED_MSG
        result = await PalliumMcpClient(ctx).relay_status(
            message_id, offset=offset, page_size=_MCP_RELAY_MAX_CHARS,
        )
        return _relay_status_text(result, offset)

    async def pallium_relay_receive(
        max_chars: int = 0,
        container_ref: str | None = None,
        request_ctx: object | None = None,
    ) -> str:
        """Claim one bounded Relay delivery for this runtime session. max_chars=0 uses 2,000; larger values clamp to 2,000. Continue truncated bodies with pallium_relay_status(message_id, next_offset). If this MCP configuration lacks Relay scope, copy container_ref from injected scope. Call pallium_relay_ack(delivery_id, receipt), or pallium_relay_reply to reply and ACK atomically."""
        if max_chars < 0 or 0 < max_chars < _MCP_RELAY_MIN_CHARS:
            return _json_text({
                "error": f"max_chars must be 0 or at least {_MCP_RELAY_MIN_CHARS}",
                "min_max_chars": _MCP_RELAY_MIN_CHARS,
            })
        effective_max_chars = _MCP_RELAY_MAX_CHARS if max_chars == 0 else min(max_chars, _MCP_RELAY_MAX_CHARS)
        ctx, scope_error = resolve_relay_context(container_ref=container_ref)
        if scope_error:
            return (
                f"{scope_error} Relay receive needs its trusted scope from the integration; "
                "copy injected container_ref, never a session identity."
            )
        if not ctx.is_configured:
            return NOT_CONFIGURED_MSG
        runtime, session_ref, identity_error = current_relay_identity(ctx, request_ctx)
        if identity_error:
            return identity_error
        result = await PalliumMcpClient(ctx).relay_receive(
            runtime=runtime, session_ref=session_ref, max_response_chars=effective_max_chars,
        )
        if not isinstance(result, dict):
            return _relay_error_text({"error": "invalid relay receive response"})
        if "error" in result:
            return _relay_error_text(result, effective_max_chars)
        deliveries = result.get("deliveries")
        if not isinstance(deliveries, list):
            return _relay_error_text({"error": "invalid relay receive response"})
        result.pop("session", None)  # storage sizes this larger superset; MCP does not expose session metadata
        for delivery in deliveries:
            if not isinstance(delivery, dict):
                return _relay_error_text({"error": "invalid relay receive response"})
            delivery.pop("claim_token", None)  # receipt stays; claim_token is never exposed
        rendered = _json_text(result)
        # The storage transaction sizes a superset before claim. If that invariant ever
        # regresses, returning the claimed body is safer than hiding it behind an error.
        if len(rendered) > effective_max_chars:
            return _relay_error_text({"error": "relay receive response exceeds the response budget"}, effective_max_chars)
        return rendered

    pallium_relay_receive.__annotations__["request_ctx"] = Context | None
    server.tool()(relay_tool(pallium_relay_receive))

    @server.tool()
    @relay_tool
    async def pallium_relay_ack(
        delivery_id: str,
        receipt: str,
        container_ref: str | None = None,
    ) -> str:
        """Acknowledge a Relay delivery after receiving its payload. If this MCP configuration lacks Relay scope, copy container_ref from injected scope. Pass the receipt from pallium_relay_receive; use pallium_relay_reply when replying atomically. If the result says already_delivered=true, this is a duplicate: do not act on it again."""
        ctx, scope_error = resolve_relay_context(container_ref=container_ref)
        if scope_error:
            return scope_error
        if not ctx.is_configured:
            return NOT_CONFIGURED_MSG
        result = await PalliumMcpClient(ctx).relay_mcp_ack(delivery_id=delivery_id, receipt=receipt)
        return _relay_text(result)

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
        agent_ref: str | None = None,
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
            agent_ref=agent_ref,
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
        agent_ref: str | None = None,
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
            agent_ref=agent_ref,
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
        container_ref: str | None = None,
        thread_ref: str | None = None,
        actor_ref: str | None = None,
        agent_ref: str | None = None,
        visibility: str | None = None,
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
        ctx = resolve_context(container_ref=container_ref, thread_ref=thread_ref, actor_ref=actor_ref, agent_ref=agent_ref, visibility=visibility)
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
