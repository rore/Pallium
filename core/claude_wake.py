"""Memory-only Claude Code wake credential registry."""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
import time
from typing import Callable
import unicodedata

RUNTIME = "claude-code"
TTL_SECONDS = 900
MAX_RUNTIME_CHARS = 32
MAX_SESSION_CHARS = 512
MAX_CONTAINER_CHARS = 512
MAX_ACTOR_CHARS = 255
MAX_SOCKET_CHARS = 4096
MAX_TOKEN_CHARS = 8192


@dataclass(frozen=True)
class _Registration:
    runtime: str
    session_ref: str
    container_ref: str
    actor_ref: str
    socket_path: str = field(repr=False)
    token: str = field(repr=False)
    generation: int
    expires_at: float


Transport = Callable[[str, str], bool]


def _valid(value: object, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and len(value) <= maximum
        and not any(unicodedata.category(char) == "Cc" for char in value)
    )


class ClaudeWakeRegistry:
    """One app-owned credential registry; credentials never leave this module except to an injected transport."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._generation = 0
        self._registrations: dict[tuple[str, str], _Registration] = {}

    def register(
        self,
        *,
        runtime: str,
        session_ref: str,
        container_ref: str,
        actor_ref: str,
        socket_path: str,
        token: str,
    ) -> None:
        if (
            runtime != RUNTIME
            or not _valid(runtime, MAX_RUNTIME_CHARS)
            or not _valid(session_ref, MAX_SESSION_CHARS)
            or not _valid(container_ref, MAX_CONTAINER_CHARS)
            or not _valid(actor_ref, MAX_ACTOR_CHARS)
            or not _valid(socket_path, MAX_SOCKET_CHARS)
            or not _valid(token, MAX_TOKEN_CHARS)
        ):
            raise ValueError("invalid registration")
        with self._lock:
            self._generation += 1
            self._registrations[(runtime, session_ref)] = _Registration(
                runtime=runtime,
                session_ref=session_ref,
                container_ref=container_ref,
                actor_ref=actor_ref,
                socket_path=socket_path,
                token=token,
                generation=self._generation,
                expires_at=self._clock() + TTL_SECONDS,
            )

    def probe(
        self,
        *,
        runtime: str,
        session_ref: str,
        container_ref: str,
        actor_ref: str,
        transport: Transport | None,
    ) -> bool:
        if transport is None:
            return False
        with self._lock:
            registration = self._active_locked(runtime, session_ref)
            if (
                registration is None
                or registration.container_ref != container_ref
                or registration.actor_ref != actor_ref
            ):
                return False
        try:
            return bool(transport(registration.socket_path, registration.token))
        except Exception:
            return False

    def _active_locked(self, runtime: str, session_ref: str) -> _Registration | None:
        registration = self._registrations.get((runtime, session_ref))
        if registration is None:
            return None
        if registration.expires_at > self._clock():
            return registration
        if self._registrations.get((runtime, session_ref)) is registration:
            del self._registrations[(runtime, session_ref)]
        return None
