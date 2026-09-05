"""Environment-based context resolution for Pallium MCP server."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

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
_RELAY_ACTOR_REF_MAX_CHARS = 255


def _valid_relay_scope_value(value: object, *, max_chars: int) -> str | None:
    if not isinstance(value, str) or value != value.strip():
        return None
    return value if 0 < len(value) <= max_chars and value.isprintable() else None


def resolve_relay_context(
    *, container_ref: str | None = None, actor_ref: str | None = None
) -> tuple[PalliumContext | None, str | None]:
    """Resolve a paired Relay scope without allowing model inputs to override config."""
    supplied_container = _valid_relay_scope_value(
        container_ref, max_chars=_RELAY_CONTAINER_REF_MAX_CHARS
    )
    supplied_actor = _valid_relay_scope_value(actor_ref, max_chars=_RELAY_ACTOR_REF_MAX_CHARS)
    if (container_ref is None) != (actor_ref is None):
        return None, "Error: Relay scope requires both container_ref and actor_ref."
    if container_ref is not None and (supplied_container is None or supplied_actor is None):
        return None, "Error: Relay scope requires paired non-blank container_ref and actor_ref."

    configured_container = os.environ.get("PALLIUM_CONTAINER_REF")
    configured_actor = os.environ.get("PALLIUM_ACTOR_REF")
    if (configured_container is None) != (configured_actor is None):
        return None, "Error: Configured Relay scope requires both container_ref and actor_ref."
    if configured_container is not None:
        configured_container = _valid_relay_scope_value(
            configured_container, max_chars=_RELAY_CONTAINER_REF_MAX_CHARS
        )
        configured_actor = _valid_relay_scope_value(
            configured_actor, max_chars=_RELAY_ACTOR_REF_MAX_CHARS
        )
        if configured_container is None or configured_actor is None:
            return None, "Error: Configured Relay scope is invalid."
        configured_container = _canonicalize_container_ref(configured_container)

    if container_ref is None:
        if configured_container is None:
            return None, "Error: Relay scope requires both container_ref and actor_ref."
        return resolve_context(container_ref=configured_container, actor_ref=configured_actor), None

    requested_container = _canonicalize_container_ref(supplied_container)
    if (
        configured_container is not None
        and (requested_container != configured_container or supplied_actor != configured_actor)
    ):
        return None, "Error: Relay scope conflicts with configured trusted scope."
    return resolve_context(container_ref=requested_container, actor_ref=supplied_actor), None
