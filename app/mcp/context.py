"""Environment-based context resolution for Pallium MCP server."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

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
        return os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_SESSION_ID")
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

def codex_request_metadata_status(request_meta: Mapping[str, Any] | None) -> dict[str, object]:
    """Return an allowlisted, non-claiming view of Codex turn metadata."""
    raw = request_meta.get("x-codex-turn-metadata") if isinstance(request_meta, Mapping) else None
    if raw is None:
        return {"source": "absent", "shape": "absent"}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {"source": "codex_turn_metadata", "shape": "invalid"}
    if not isinstance(raw, Mapping):
        return {"source": "codex_turn_metadata", "shape": "invalid"}

    def identity(*keys: str) -> tuple[bool, bool, str | None, str | None]:
        supplied = [raw[key] for key in keys if key in raw]
        values = [value.strip() for value in supplied if isinstance(value, str) and 0 < len(value.strip()) <= 255]
        valid = bool(supplied) and len(values) == len(supplied) and len(set(values)) == 1
        value = values[0] if valid else None
        return bool(supplied), valid, sha256(value.encode()).hexdigest() if value else None, value

    thread_present, thread_valid, thread_hash, thread = identity("thread_id", "threadId")
    session_present, session_valid, session_hash, session = identity("session_id", "sessionId")
    turn_present, turn_valid, _, _ = identity("turn_id", "turnId")
    return {
        "source": "codex_turn_metadata",
        "shape": "object",
        "thread_id": {"present": thread_present, "valid": thread_valid, "sha256": thread_hash},
        "session_id": {"present": session_present, "valid": session_valid, "sha256": session_hash},
        "turn_id": {"present": turn_present, "valid": turn_valid},
        "identity_conflict": bool(thread and session and thread != session),
    }

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
