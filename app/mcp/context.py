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


_CODEX_TURN_METADATA_MAX_CHARS = 4096


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

@dataclass(frozen=True)
class _CodexRequestMetadata:
    source: str
    shape: str
    thread_present: bool = False
    thread_valid: bool = False
    thread_ref: str | None = None
    session_present: bool = False
    session_valid: bool = False
    session_ref: str | None = None
    turn_present: bool = False
    turn_valid: bool = False

    def status(self) -> dict[str, object]:
        if self.source == "absent" or self.shape == "invalid":
            return {"source": self.source, "shape": self.shape}
        return {
            "source": self.source,
            "shape": self.shape,
            "thread_id": {
                "present": self.thread_present,
                "valid": self.thread_valid,
                "sha256": sha256(self.thread_ref.encode()).hexdigest() if self.thread_ref else None,
            },
            "session_id": {
                "present": self.session_present,
                "valid": self.session_valid,
                "sha256": sha256(self.session_ref.encode()).hexdigest() if self.session_ref else None,
            },
            "turn_id": {"present": self.turn_present, "valid": self.turn_valid},
            "identity_conflict": bool(
                self.thread_ref and self.session_ref and self.thread_ref != self.session_ref
            ),
        }


def _valid_identifier(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if 0 < len(value) <= 255 and value.isprintable() else None


def _parse_codex_request_metadata(request_meta: Mapping[str, Any] | None) -> _CodexRequestMetadata:
    if not isinstance(request_meta, Mapping) or "x-codex-turn-metadata" not in request_meta:
        return _CodexRequestMetadata(source="absent", shape="absent")
    raw = request_meta["x-codex-turn-metadata"]
    if raw is None:
        return _CodexRequestMetadata(source="codex_turn_metadata", shape="invalid")
    if isinstance(raw, str):
        if len(raw) > _CODEX_TURN_METADATA_MAX_CHARS:
            return _CodexRequestMetadata(source="codex_turn_metadata", shape="invalid")
        try:
            raw = json.loads(raw)
        except (ValueError, RecursionError):
            return _CodexRequestMetadata(source="codex_turn_metadata", shape="invalid")
    if not isinstance(raw, Mapping):
        return _CodexRequestMetadata(source="codex_turn_metadata", shape="invalid")

    def identity(*keys: str) -> tuple[bool, bool, str | None]:
        supplied = [raw[key] for key in keys if key in raw]
        values = [_valid_identifier(value) for value in supplied]
        valid = bool(supplied) and all(values) and len(set(values)) == 1
        return bool(supplied), bool(valid), values[0] if valid else None

    thread_present, thread_valid, thread_ref = identity("thread_id", "threadId")
    session_present, session_valid, session_ref = identity("session_id", "sessionId")
    turn_present, turn_valid, _ = identity("turn_id", "turnId")
    return _CodexRequestMetadata(
        source="codex_turn_metadata",
        shape="object",
        thread_present=thread_present,
        thread_valid=thread_valid,
        thread_ref=thread_ref,
        session_present=session_present,
        session_valid=session_valid,
        session_ref=session_ref,
        turn_present=turn_present,
        turn_valid=turn_valid,
    )


def codex_request_metadata_status(request_meta: Mapping[str, Any] | None) -> dict[str, object]:
    """Return an allowlisted, non-claiming view of Codex turn metadata."""
    return _parse_codex_request_metadata(request_meta).status()


def codex_request_receive_session_ref(
    request_meta: Mapping[str, Any] | None,
    env: Mapping[str, object] = os.environ,
) -> tuple[str | None, bool]:
    """Return (request-local session_ref, blocked); absent metadata permits legacy fallback."""
    metadata = _parse_codex_request_metadata(request_meta)
    if metadata.source == "absent":
        return None, False
    if not (
        metadata.shape == "object"
        and metadata.thread_valid
        and metadata.session_valid
        and metadata.turn_valid
        and metadata.thread_ref == metadata.session_ref
    ):
        return None, True
    for key in ("PALLIUM_THREAD_REF", "CODEX_THREAD_ID", "CODEX_SESSION_ID"):
        if key in env and _valid_identifier(env[key]) != metadata.session_ref:
            return None, True
    return metadata.session_ref, False

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
