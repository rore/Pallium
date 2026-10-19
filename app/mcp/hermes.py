"""Dedicated stdio MCP entry point for a Hermes profile."""

from __future__ import annotations

import argparse
import inspect
from collections.abc import Mapping
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
_META_KEY = "pallium_hermes"
_MAX_ID_CHARS = 255
_MAX_RECEIPT_CHARS = 64
_MAX_DELIVERY_ID_CHARS = 64


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
    if not set(identity) <= {"session_id", "turn_id", "reply"}:
        raise ValueError("unexpected Hermes metadata field")
    session_id, turn_id = identity["session_id"], identity["turn_id"]
    if not _valid_identity(session_id) or not _valid_identity(turn_id):
        raise ValueError("invalid Hermes session/turn metadata")
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


def _validate_arguments(
    tool_name: str,
    arguments: Mapping[str, Any],
    context: PalliumContext,
    identity: HermesMcpIdentity,
) -> None:
    for key, expected in (
        ("container_ref", context.container_ref),
        ("agent_ref", "hermes"),
        ("thread_ref", identity.session_id),
        ("actor_ref", context.actor_ref),
        ("visibility", context.visibility),
    ):
        if key in arguments and arguments[key] is not None and arguments[key] != expected:
            raise ValueError(f"conflicting Hermes {key}")

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


def make_tool_adapter(context: PalliumContext) -> Callable[..., Any]:
    """Build a per-request identity guard for the dedicated Hermes tool catalog."""
    try:
        from mcp.server.fastmcp.exceptions import ToolError
    except ImportError:
        from mcp.server.fastmcp import ToolError

    def adapt(tool_name: str, handler: Callable[..., Any], get_context: Callable[[], Any]):
        if tool_name not in HERMES_RELAY_TOOLS:
            return None

        @wraps(handler)
        async def guarded(*args: Any, **kwargs: Any) -> Any:
            try:
                request_context = get_context().request_context
                identity = _read_identity(request_context.meta, tool_name)
                bound = inspect.signature(handler).bind_partial(*args, **kwargs)
                _validate_arguments(tool_name, bound.arguments, context, identity)
                if tool_name == "pallium_relay_reply":
                    bound.arguments["receipt"] = identity.reply_receipt
            except (TypeError, ValueError) as exc:
                raise ToolError(str(exc)) from None
            except Exception:
                raise ToolError("invalid Hermes MCP request context") from None
            with bind_hermes_request(HermesMcpRequest(context, identity)):
                result = handler(*bound.args, **bound.kwargs)
                return await result if inspect.isawaitable(result) else result

        return guarded

    return adapt


def create_hermes_server(
    *, base_url: str, container_ref: str, actor_ref: str, visibility: str = "private",
):
    """Create a stdio server with only Relay tools and fixed profile scope."""
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
    if not _valid_identity(actor_ref):
        raise ValueError("--actor-ref must be printable, exact-trimmed, and at most 255 characters")
    if visibility != "private":
        raise ValueError("--visibility must be private")
    fixed_container = validate_explicit_container_ref(container_ref)
    context = PalliumContext(
        base_url=base_url.rstrip("/"),
        container_ref=fixed_container,
        actor_ref=actor_ref,
        agent_ref="hermes",
        visibility=visibility,
    )
    return create_server(tool_adapter=make_tool_adapter(context))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run Pallium's profile-scoped Hermes MCP server over stdio.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--container-ref", required=True)
    parser.add_argument("--actor-ref", required=True)
    parser.add_argument("--visibility", choices=("private",), default="private")
    args = parser.parse_args(argv)
    server = create_hermes_server(
        base_url=args.base_url,
        container_ref=args.container_ref,
        actor_ref=args.actor_ref,
        visibility=args.visibility,
    )
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
