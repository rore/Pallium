"""Dedicated stdio MCP entry point for a Hermes profile."""

from __future__ import annotations

import argparse
import inspect
import json
from collections.abc import Mapping
from dataclasses import replace
from functools import wraps
from typing import Any, Callable
from urllib.parse import urlsplit

from app.mcp.context import (
    HermesMcpIdentity,
    HermesMcpRequest,
    PalliumContext,
    bind_hermes_request,
)
from app.mcp.server import create_server
from core.container_ref import validate_explicit_container_ref


HERMES_RELAY_TOOLS = frozenset({
    "pallium_relay_address",
    "pallium_relay_recipients",
    "pallium_relay_discover_recipients",
    "pallium_relay_name",
    "pallium_relay_work_refs",
    "pallium_relay_attach_work_ref",
    "pallium_relay_detach_work_ref",
    "pallium_relay_participants",
    "pallium_relay_send",
    "pallium_relay_reply",
    "pallium_relay_status",
    "pallium_relay_trace",
})
HERMES_HISTORY_TOOLS = frozenset({
    "pallium_search_history",
    "pallium_search_history_by_work_ref",
    "pallium_expand_source",
})
HERMES_MEMORY_TOOLS = frozenset({
    "pallium_query", "pallium_expand", "pallium_ingest", "pallium_remember",
    "pallium_correct", "pallium_supersede", "pallium_forget",
    "pallium_forget_source", "pallium_record_outcome", "pallium_flag_memory",
    "pallium_rate_memory", "pallium_expand_source",
})
HERMES_TOOLS = HERMES_RELAY_TOOLS | HERMES_HISTORY_TOOLS
_META_KEY = "pallium_hermes"
_MAX_ID_CHARS = 255
_MAX_RECEIPT_CHARS = 64
_MAX_DELIVERY_ID_CHARS = 64
_RELAY_MUTATIONS = frozenset({
    "pallium_relay_send", "pallium_relay_reply", "pallium_relay_name",
    "pallium_relay_attach_work_ref", "pallium_relay_detach_work_ref",
})
_RELAY_ERROR_FIELDS = frozenset({
    "error", "status_code", "detail", "min_max_chars", "error_kind", "retryable", "action",
})


def _refused_request():
    from mcp.types import CallToolResult, TextContent

    text = "Pallium MCP refused the request"
    return CallToolResult(
        isError=True, content=[TextContent(type="text", text=text)], structuredContent={"result": text},
        _meta={"pallium_hermes": {"operation_uncertain": False}},
    )


def _as_mapping(value: object) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dict(dumped) if isinstance(dumped, Mapping) else None
    return None


def _valid_identity(value: object, *, max_chars: int = _MAX_ID_CHARS) -> bool:
    return (
        isinstance(value, str)
        and value == value.strip()
        and 0 < len(value) <= max_chars
        and value.isprintable()
    )


def _read_identity(meta: object, tool_name: str) -> HermesMcpIdentity:
    values = _as_mapping(meta)
    nested = values.get(_META_KEY) if values is not None else None
    identity = _as_mapping(nested)
    if identity is None or not {"session_id", "turn_id"} <= set(identity):
        raise ValueError("missing Hermes session/turn metadata")
    if not set(identity) <= {"session_id", "turn_id", "reply", "scope", "request_source_item_id"}:
        raise ValueError("unexpected Hermes metadata field")
    session_id, turn_id = identity["session_id"], identity["turn_id"]
    if not _valid_identity(session_id) or not _valid_identity(turn_id):
        raise ValueError("invalid Hermes session/turn metadata")
    source_id = identity.get("request_source_item_id")
    if source_id is not None and not _valid_identity(source_id):
        raise ValueError("invalid Hermes current request source metadata")
    for key, value in (("session_id", session_id), ("turn_id", turn_id)):
        if key in values and values[key] != value:
            raise ValueError(f"conflicting Hermes {key} metadata")

    reply_value = identity.get("reply")
    if tool_name == "pallium_relay_reply":
        reply = _as_mapping(reply_value)
        if reply is None or set(reply) != {"delivery_id", "receipt"}:
            raise ValueError("missing or invalid admitted reply metadata")
        delivery_id, receipt = reply["delivery_id"], reply["receipt"]
        if not _valid_identity(delivery_id, max_chars=_MAX_DELIVERY_ID_CHARS) or not _valid_identity(
            receipt, max_chars=_MAX_RECEIPT_CHARS
        ):
            raise ValueError("invalid admitted reply metadata")
        return HermesMcpIdentity(session_id, turn_id, delivery_id, receipt)
    if reply_value is not None:
        raise ValueError("reply metadata is only valid for pallium_relay_reply")
    return HermesMcpIdentity(session_id, turn_id)


def _request_scope(meta: object, context: PalliumContext) -> PalliumContext:
    values = _as_mapping(meta)
    nested = _as_mapping(values.get(_META_KEY)) if values is not None else None
    supplied = nested.get("scope") if nested is not None else None
    if context.container_ref is not None:
        if supplied is not None:
            raise ValueError("fixed Hermes transport does not accept request scope")
        return context
    scope = _as_mapping(supplied)
    if scope is None or set(scope) != {"container_ref", "actor_ref"}:
        raise ValueError("missing or invalid trusted Hermes request scope")
    container = scope["container_ref"]
    if not _valid_identity(container, max_chars=512) or not _valid_identity(scope["actor_ref"]):
        raise ValueError("invalid trusted Hermes request scope")
    return replace(context, container_ref=validate_explicit_container_ref(container), actor_ref=scope["actor_ref"])


def _validate_arguments(
    tool_name: str,
    arguments: Mapping[str, Any],
    context: PalliumContext,
    identity: HermesMcpIdentity,
    *,
    memory_enabled: bool = False,
) -> None:
    fixed_fields = [
        ("container_ref", context.container_ref),
        ("agent_ref", "hermes"),
        ("visibility", context.visibility),
    ]
    if tool_name != "pallium_forget_source":
        fixed_fields.append(("thread_ref", identity.session_id))
    if tool_name not in HERMES_HISTORY_TOOLS:
        fixed_fields.append(("actor_ref", context.actor_ref))
    if tool_name == "pallium_flag_memory":
        fixed_fields.append(("source_ref", context.actor_ref))
    for key, expected in fixed_fields:
        if key in arguments and arguments[key] is not None and arguments[key] != expected:
            raise ValueError(f"conflicting Hermes {key}")

    if tool_name in HERMES_HISTORY_TOOLS and arguments.get("request_source_item_id") is not None:
        raise ValueError("request_source_item_id is unavailable for Hermes History")
    if tool_name == "pallium_expand_source" and arguments.get("include_supported_memories") and not memory_enabled:
        raise ValueError("derived-memory expansion is not qualified for Hermes")

    identity_pairs = (
        ("sender_runtime", "sender_session_ref"),
        ("current_runtime", "current_session_ref"),
    )
    for runtime_key, session_key in identity_pairs:
        if runtime_key not in arguments and session_key not in arguments:
            continue
        if arguments.get(runtime_key) != "hermes" or arguments.get(session_key) != identity.session_id:
            raise ValueError(f"conflicting Hermes {runtime_key}/{session_key}")

    if tool_name == "pallium_relay_send" and not (
        arguments.get("sender_runtime") == "hermes"
        and arguments.get("sender_session_ref") == identity.session_id
    ):
        raise ValueError("send requires the trusted Hermes sender identity")
    if tool_name == "pallium_relay_name" and not (
        arguments.get("current_runtime") == "hermes"
        and arguments.get("current_session_ref") == identity.session_id
    ):
        raise ValueError("name requires the trusted Hermes current identity")

    if tool_name == "pallium_relay_reply":
        if arguments.get("delivery_id") != identity.reply_delivery_id:
            raise ValueError("reply delivery does not match admitted metadata")
        if arguments.get("receipt") is not None and arguments["receipt"] != identity.reply_receipt:
            raise ValueError("reply receipt conflicts with admitted metadata")


def make_tool_adapter(context: PalliumContext, *, memory_enabled: bool = False) -> Callable[..., Any]:
    """Build a per-request identity guard for the dedicated Hermes tool catalog."""
    try:
        from mcp.server.fastmcp.exceptions import ToolError
    except ImportError:
        from mcp.server.fastmcp import ToolError

    def adapt(tool_name: str, handler: Callable[..., Any], get_context: Callable[[], Any]):
        allowed_tools = HERMES_TOOLS | (HERMES_MEMORY_TOOLS if memory_enabled else frozenset())
        if tool_name not in allowed_tools:
            return None

        @wraps(handler)
        async def guarded(*args: Any, **kwargs: Any) -> Any:
            try:
                request_context = get_context().request_context
                identity = _read_identity(request_context.meta, tool_name)
                request_scope = _request_scope(request_context.meta, context)
                bound = inspect.signature(handler).bind_partial(*args, **kwargs)
                if bound.arguments.get("container_ref") is not None:
                    bound.arguments["container_ref"] = validate_explicit_container_ref(bound.arguments["container_ref"])
                _validate_arguments(tool_name, bound.arguments, request_scope, identity, memory_enabled=memory_enabled)
                if tool_name in {"pallium_search_history", "pallium_search_history_by_work_ref"}:
                    nested = _as_mapping(_as_mapping(request_context.meta).get(_META_KEY))
                    if nested.get("request_source_item_id") is not None:
                        bound.arguments["request_source_item_id"] = nested["request_source_item_id"]
                if tool_name == "pallium_relay_reply":
                    bound.arguments["receipt"] = identity.reply_receipt
            except Exception:
                return _refused_request()
            with bind_hermes_request(HermesMcpRequest(request_scope, identity)):
                try:
                    result = handler(*bound.args, **bound.kwargs)
                    return await result if inspect.isawaitable(result) else result
                except ToolError as exc:
                    if tool_name in _RELAY_MUTATIONS:
                        try:
                            error = json.loads(str(exc))
                        except (TypeError, ValueError):
                            error = None
                        # Only the Relay HTTP adapter's known refusals establish a definite outcome.
                        if (isinstance(error, dict) and set(error) <= _RELAY_ERROR_FIELDS
                                and isinstance(error.get("error"), str) and error["error"]
                                and type(error.get("status_code")) is int
                                and error["status_code"] in {404, 409, 422}):
                            return _refused_request()
                    raise

        return guarded

    return adapt


def create_hermes_server(
    *, base_url: str, container_ref: str | None = None, actor_ref: str | None = None, visibility: str = "private",
    memory_enabled: bool = False,
):
    """Create a dedicated transport with host-owned immutable scope per request."""
    if not isinstance(base_url, str) or not base_url.strip() or base_url != base_url.strip():
        raise ValueError("--base-url is required")
    parsed = urlsplit(base_url)
    hostname = parsed.hostname
    try:
        port = parsed.port
    except ValueError:
        raise ValueError("--base-url has an invalid port") from None
    loopback = hostname in {"localhost", "127.0.0.1", "::1"}
    if (
        parsed.scheme != "http" or not hostname or not loopback
        or (port is not None and not 1 <= port <= 65535)
        or parsed.username is not None or parsed.password is not None
        or parsed.query or parsed.fragment or parsed.path not in {"", "/"}
    ):
        raise ValueError("--base-url must be an uncredentialed loopback HTTP origin")
    if container_ref is not None and not _valid_identity(actor_ref):
        raise ValueError("--actor-ref must be printable, exact-trimmed, and at most 255 characters")
    if container_ref is None and actor_ref is not None:
        raise ValueError("session-scoped Hermes transport receives actor identity per request")
    if visibility != "private":
        raise ValueError("--visibility must be private")
    if type(memory_enabled) is not bool:
        raise ValueError("--memory-enabled must be a boolean")
    fixed_container = validate_explicit_container_ref(container_ref) if container_ref is not None else None
    context = PalliumContext(
        base_url=base_url.rstrip("/"),
        container_ref=fixed_container,
        actor_ref=actor_ref,
        agent_ref="hermes",
        visibility=visibility,
    )
    return create_server(tool_adapter=make_tool_adapter(context, memory_enabled=memory_enabled))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run Pallium's profile-scoped Hermes MCP server over stdio.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--container-ref", help="Explicit fixed-scope compatibility transport")
    parser.add_argument("--actor-ref", help="Actor for explicit fixed-scope transport")
    parser.add_argument("--visibility", choices=("private",), default="private")
    parser.add_argument("--memory-enabled", action="store_true", help="Expose the opt-in memory catalog")
    args = parser.parse_args(argv)
    server = create_hermes_server(
        base_url=args.base_url,
        container_ref=args.container_ref,
        actor_ref=args.actor_ref,
        visibility=args.visibility,
        memory_enabled=args.memory_enabled,
    )
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
