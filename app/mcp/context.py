"""Environment-based context resolution for Pallium MCP server."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from core.container_ref import canonicalize_container_ref


@dataclass(frozen=True)
class PalliumContext:
    """Resolved Pallium connection and scope context."""

    base_url: str | None = None
    container_ref: str | None = None
    thread_ref: str | None = None
    actor_ref: str | None = None
    agent_ref: str | None = None
    visibility: str | None = None

    @property
    def is_configured(self) -> bool:
        return self.base_url is not None


@dataclass(frozen=True)
class HermesMcpIdentity:
    """Trusted host identity and optional admitted reply data for one MCP request."""

    session_id: str
    turn_id: str
    reply_delivery_id: str | None = None
    reply_receipt: str | None = None


@dataclass(frozen=True)
class HermesMcpRequest:
    """Immutable per-request Hermes scope; never stored in process environment."""

    context: PalliumContext
    identity: HermesMcpIdentity


_hermes_request: ContextVar[HermesMcpRequest | None] = ContextVar("pallium_hermes_mcp_request", default=None)


def current_hermes_request() -> HermesMcpRequest | None:
    return _hermes_request.get()


@contextmanager
def bind_hermes_request(request: HermesMcpRequest) -> Iterator[None]:
    token: Token[HermesMcpRequest | None] = _hermes_request.set(request)
    try:
        yield
    finally:
        _hermes_request.reset(token)


def _canonicalize_container_ref(value: str | None) -> str | None:
    # Thin alias — the authoritative rule now lives in core.container_ref so the
    # server and this MCP boundary share one definition. Kept for existing
    # imports/tests that reference this name.
    return canonicalize_container_ref(value)


def _runtime_thread_ref(agent_ref: str | None) -> str | None:
    """Resolve a session ID supplied by the owning runtime, never by the model."""
    if agent_ref == "codex":
        return None
    if agent_ref != "claude-code":
        return None
    inherited = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if inherited:
        return inherited
    parent_pid = os.getppid()
    registry = Path.home() / ".claude" / "sessions" / f"{parent_pid}.json"
    try:
        record = json.loads(registry.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    session_id = record.get("sessionId")
    if record.get("pid") != parent_pid or not isinstance(session_id, str):
        return None
    session_id = session_id.strip()
    return session_id if 0 < len(session_id) <= 255 else None


def resolve_codex_thread_ref(meta: object) -> tuple[str | None, str | None]:
    """Resolve Codex task identity from one MCP request's transport metadata."""
    if meta is None:
        values: dict[str, object] = {}
    elif isinstance(meta, Mapping):
        values = dict(meta)
    elif callable(model_dump := getattr(meta, "model_dump", None)):
        dumped = model_dump()
        if not isinstance(dumped, Mapping):
            return None, "invalid Codex request metadata"
        values = dict(dumped)
    else:
        return None, "invalid Codex request metadata"
    supplied: list[object] = []
    if "threadId" in values:
        supplied.append(values["threadId"])
    nested = values.get("x-codex-turn-metadata")
    if nested is not None:
        if not isinstance(nested, Mapping):
            return None, "metadata x-codex-turn-metadata must be an object"
        for key in ("thread_id", "session_id"):
            if key in nested:
                supplied.append(nested[key])
    if not supplied:
        return None, "missing Codex task identity metadata"
    if any(
        not isinstance(value, str)
        or value != value.strip()
        or not 0 < len(value) <= 255
        or not value.isprintable()
        for value in supplied
    ):
        return None, "invalid Codex task identity metadata"
    if len(set(supplied)) != 1:
        return None, "conflicting Codex task identity metadata"
    return supplied[0], None


def resolve_context(
    *,
    container_ref: str | None = None,
    thread_ref: str | None = None,
    actor_ref: str | None = None,
    agent_ref: str | None = None,
    visibility: str | None = None,
) -> PalliumContext:
    """Merge explicit parameters with environment variable defaults.

    Resolution order: explicit parameter > environment variable > None.
    """
    hermes_request = current_hermes_request()
    if hermes_request is not None:
        return PalliumContext(
            base_url=hermes_request.context.base_url,
            container_ref=hermes_request.context.container_ref,
            thread_ref=hermes_request.identity.session_id,
            actor_ref=hermes_request.context.actor_ref,
            agent_ref="hermes",
            visibility=hermes_request.context.visibility,
        )

    resolved_agent = agent_ref if agent_ref is not None else os.environ.get("PALLIUM_AGENT_REF")
    resolved_thread = thread_ref if thread_ref is not None else os.environ.get("PALLIUM_THREAD_REF")
    return PalliumContext(
        base_url=os.environ.get("PALLIUM_BASE_URL"),
        container_ref=_canonicalize_container_ref(container_ref if container_ref is not None else os.environ.get("PALLIUM_CONTAINER_REF")),
        thread_ref=resolved_thread or _runtime_thread_ref(resolved_agent),
        actor_ref=actor_ref if actor_ref is not None else os.environ.get("PALLIUM_ACTOR_REF"),
        agent_ref=resolved_agent,
        visibility=visibility if visibility is not None else os.environ.get("PALLIUM_VISIBILITY"),
    )

_RELAY_CONTAINER_REF_MAX_CHARS = 512


def _valid_relay_scope_value(value: object, *, max_chars: int) -> str | None:
    if not isinstance(value, str) or value != value.strip():
        return None
    return value if 0 < len(value) <= max_chars and value.isprintable() else None


def resolve_relay_context(
    *, container_ref: str | None = None
) -> tuple[PalliumContext | None, str | None]:
    """Resolve the trusted Relay container scope."""
    hermes_request = current_hermes_request()
    if hermes_request is not None:
        supplied = _valid_relay_scope_value(container_ref, max_chars=_RELAY_CONTAINER_REF_MAX_CHARS)
        if container_ref is not None and supplied is None:
            return None, "Error: Relay scope requires a non-blank container_ref."
        requested = _canonicalize_container_ref(supplied) if supplied is not None else None
        if requested is not None and requested != hermes_request.context.container_ref:
            return None, "Error: Relay scope conflicts with configured Hermes scope."
        return resolve_context(), None

    supplied_container = _valid_relay_scope_value(
        container_ref, max_chars=_RELAY_CONTAINER_REF_MAX_CHARS
    )
    if container_ref is not None and supplied_container is None:
        return None, "Error: Relay scope requires a non-blank container_ref."

    configured_container = os.environ.get("PALLIUM_CONTAINER_REF")
    if configured_container is not None:
        configured_container = _valid_relay_scope_value(
            configured_container, max_chars=_RELAY_CONTAINER_REF_MAX_CHARS
        )
        if configured_container is None:
            return None, "Error: Configured Relay scope is invalid."
        configured_container = _canonicalize_container_ref(configured_container)

    if container_ref is None:
        if configured_container is None:
            return None, (
                "Error: Relay scope requires container_ref. Copy the injected "
                "container_ref exactly. If none was injected, check that Pallium "
                "hooks are enabled and trusted, or configure PALLIUM_CONTAINER_REF "
                "for an intentional hookless MCP integration. Do not infer Relay "
                "scope from the working directory or session IDs."
            )
        return resolve_context(container_ref=configured_container), None

    requested_container = _canonicalize_container_ref(supplied_container)
    if configured_container is not None and requested_container != configured_container:
        return None, "Error: Relay scope conflicts with configured trusted scope."
    return resolve_context(container_ref=requested_container), None
