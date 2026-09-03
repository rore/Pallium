"""Trusted-local Claude Code wake capability registry."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import json
import math
import os
from pathlib import Path
import threading
import time
from typing import Callable, Literal
import unicodedata

RUNTIME = "claude-code"
TTL_SECONDS = 900  # Compatibility only for memory-only test registries.
MAX_REGISTRATIONS = 256
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
    generation: int = 0
    expires_at: float = float("inf")
    idle: bool = False
    state: str = "busy"
    delivery_id: str | None = None
    attempted_at: float | None = None


Transport = Callable[[str, str], bool]


def _valid(value: object, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and len(value) <= maximum
        and not any(unicodedata.category(char) == "Cc" for char in value)
    )


def _safe_session_file(session_ref: str) -> str:
    import hashlib
    return hashlib.sha256(session_ref.encode("utf-8")).hexdigest() + ".json"


class ClaudeWakeRegistry:
    """Exact-scope capability state; persistence is trusted-local and fail closed."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic, wall_clock: Callable[[], float] = time.time, state_dir: Path | None = None) -> None:
        self._clock = clock
        self._wall_clock = wall_clock
        self._lock = threading.RLock()
        self._generation = 0
        self._registrations: dict[tuple[str, str], _Registration] = {}
        self._state_dir = state_dir
        self._canonical = state_dir / "capabilities.json" if state_dir else None
        self._intents = state_dir / "intents" if state_dir else None
        self._unusable = state_dir / "store-unusable" if state_dir else None
        self._rehydration_refused = False
        self._durability_degraded = False
        self._reconcile_signal: Callable[[], None] | None = None
        if state_dir is not None:
            self._load()

    def register(
        self,
        *,
        runtime: str,
        session_ref: str,
        container_ref: str,
        actor_ref: str,
        socket_path: str,
        token: str,
        idle: bool = False,
        intent_id: str | None = None,
    ) -> bool:
        if not isinstance(idle, bool) or not self._valid_registration(
            runtime, session_ref, container_ref, actor_ref, socket_path, token
        ):
            raise ValueError("invalid registration")
        if self._state_dir is not None and not _valid(intent_id, 128):
            raise ValueError("invalid registration")
        with self._lock:
            key = (runtime, session_ref)
            if self._state_dir is None:
                now = self._clock()
                self._registrations = {
                    current_key: current for current_key, current in self._registrations.items()
                    if current.expires_at > now
                }
            if self._state_dir is not None:
                intent = self._read_intent_locked(session_ref)
                # Compare-before-apply: a delayed request can never replace newer state.
                if intent is None or intent.get("intent_id") != intent_id or not self._intent_matches(intent, runtime, session_ref, container_ref, actor_ref, socket_path, token, idle):
                    return False
                if key not in self._registrations and not self._ensure_capacity_locked():
                    return False
            elif key not in self._registrations and len(self._registrations) >= MAX_REGISTRATIONS:
                raise ValueError("registration capacity reached")
            self._generation += 1
            registration = _Registration(
                runtime=runtime,
                session_ref=session_ref,
                container_ref=container_ref,
                actor_ref=actor_ref,
                socket_path=socket_path,
                token=token,
                generation=self._generation,
                expires_at=(float("inf") if self._state_dir else self._clock() + TTL_SECONDS),
                idle=idle,
                state="idle" if idle else "busy",
            )
            if self._state_dir is not None and not self._write_canonical_locked({**self._registrations, key: registration}):
                return False
            self._registrations[key] = registration
            if self._state_dir is not None:
                self._delete_intent_locked(session_ref, expected_intent_id=intent_id)
                self._clear_unusable_locked()
                self.signal_reconcile()
            return True

    def mark_busy(
        self, *, runtime: str, session_ref: str, container_ref: str, actor_ref: str
    ) -> bool:
        """Fail closed immediately when a coordinator observes active Claude work."""
        with self._lock:
            registration = self._active_locked(runtime, session_ref)
            if registration is None or registration.container_ref != container_ref or registration.actor_ref != actor_ref:
                return False
            self._generation += 1
            busy = replace(registration, generation=self._generation, idle=False, state="busy", delivery_id=None, attempted_at=None)
            key = (runtime, session_ref)
            if self._state_dir is None or self._write_canonical_locked({**self._registrations, key: busy}):
                self._registrations[key] = busy
                return True
            # A stale durable idle is unsafe after restart. Keep this process busy and fence rehydration.
            self._registrations[key] = busy
            self._rehydration_refused = True
            self._durability_degraded = not self._quarantine_or_mark_unusable_locked()
            return True

    def probe(
        self,
        *,
        runtime: str,
        session_ref: str,
        container_ref: str,
        actor_ref: str,
        transport: Transport | None,
        delivery_id: str | None = None,
    ) -> bool:
        if transport is None:
            return False
        with self._lock:
            registration = self._active_locked(runtime, session_ref)
            if (
                registration is None
                or registration.container_ref != container_ref
                or registration.actor_ref != actor_ref
                or not registration.idle
            ):
                return False
            self._generation += 1
            consumed = replace(
                registration,
                generation=self._generation,
                idle=False,
                state="wake_inflight",
                delivery_id=delivery_id,
                attempted_at=self._wall_clock(),
            )
            key = (runtime, session_ref)
            if self._state_dir is not None and not self._write_canonical_locked({**self._registrations, key: consumed}):
                return False
            self._registrations[key] = consumed
        try:
            outcome = transport(consumed.socket_path, consumed.token)
        except Exception:
            outcome = "retryable"
        if outcome is True:
            outcome = "accepted"
        elif outcome is False or outcome not in {"accepted", "retryable", "terminal"}:
            outcome = "retryable"
        if outcome != "accepted":
            with self._lock:
                current = self._active_locked(runtime, session_ref)
                if current is not None and current.generation == consumed.generation:
                    if outcome == "terminal":
                        updated = dict(self._registrations)
                        updated.pop((runtime, session_ref), None)
                        if self._state_dir is None or self._write_canonical_locked(updated):
                            self._registrations = updated
                    else:
                        idle = replace(current, idle=True, state="idle", delivery_id=None, attempted_at=None)
                        if self._state_dir is None or self._write_canonical_locked({**self._registrations, (runtime, session_ref): idle}):
                            self._registrations[(runtime, session_ref)] = idle
        return outcome == "accepted"

    @property
    def persistent(self) -> bool:
        return self._state_dir is not None

    @property
    def durability_degraded(self) -> bool:
        return self._durability_degraded

    def set_reconcile_signal(self, signal: Callable[[], None] | None) -> None:
        self._reconcile_signal = signal

    def signal_reconcile(self) -> None:
        if self._reconcile_signal is not None:
            self._reconcile_signal()
    def recovery_candidates(self) -> list[dict[str, str | None]]:
        """Return scope-only eligible records; credentials never leave the registry."""
        with self._lock:
            if self._rehydration_refused:
                return []
            return [
                {
                    "runtime": registration.runtime,
                    "session_ref": registration.session_ref,
                    "container_ref": registration.container_ref,
                    "actor_ref": registration.actor_ref,
                    "state": registration.state,
                    "delivery_id": registration.delivery_id,
                    "attempted_at": registration.attempted_at,
                }
                for registration in self._registrations.values()
                if registration.state in {"idle", "wake_inflight"}
            ]
    def recover_intents(self) -> None:
        """Apply write-ahead intents after startup without claiming Relay work."""
        if self._intents is None:
            return
        with self._lock:
            try:
                intent_paths = list(self._intents.glob("*.json"))
            except OSError:
                return
            for path in intent_paths:
                intent = self._read_json(path)
                if not isinstance(intent, dict):
                    continue
                if intent.get("closed") is True:
                    session_ref = intent.get("session_ref")
                    if isinstance(session_ref, str):
                        updated = dict(self._registrations)
                        updated.pop((runtime, session_ref), None)
                        if self._state_dir is None or self._write_canonical_locked(updated):
                            self._registrations = updated
                    continue
                try:
                    self.register(**{key: intent[key] for key in ("runtime", "session_ref", "container_ref", "actor_ref", "socket_path", "token", "idle", "intent_id")})
                except (KeyError, ValueError):
                    continue

    def rearm_inflight(self, *, runtime: str, session_ref: str, container_ref: str, actor_ref: str, delivery_id: str, grace_seconds: float) -> bool:
        """Make an observed pending inflight delivery eligible after bounded grace."""
        with self._lock:
            current = self._active_locked(runtime, session_ref)
            if (current is None or current.container_ref != container_ref or current.actor_ref != actor_ref
                    or current.state != "wake_inflight" or current.delivery_id != delivery_id
                    or current.attempted_at is None or self._wall_clock() - current.attempted_at < grace_seconds):
                return False
            idle = replace(current, generation=current.generation + 1, idle=True, state="idle", delivery_id=None, attempted_at=None)
            if self._state_dir is not None and not self._write_canonical_locked({**self._registrations, (runtime, session_ref): idle}):
                return False
            self._generation = max(self._generation, idle.generation)
            self._registrations[(runtime, session_ref)] = idle
            return True

    def clear_inflight(self, *, runtime: str, session_ref: str, container_ref: str, actor_ref: str, delivery_id: str) -> bool:
        return self.rearm_inflight(runtime=runtime, session_ref=session_ref, container_ref=container_ref, actor_ref=actor_ref, delivery_id=delivery_id, grace_seconds=0)
    def close(
        self, *, runtime: str, session_ref: str, container_ref: str, actor_ref: str, intent_id: str | None = None
    ) -> bool:
        """Consume an exact closed intent without opening or admitting its endpoint."""
        with self._lock:
            if self._state_dir is not None:
                intent = self._read_intent_locked(session_ref)
                if not isinstance(intent, dict) or intent.get("intent_id") != intent_id or intent.get("closed") is not True:
                    return False
                if any(intent.get(key) != value for key, value in {
                    "runtime": runtime, "session_ref": session_ref, "container_ref": container_ref, "actor_ref": actor_ref,
                }.items()):
                    return False
            registration = self._registrations.get((runtime, session_ref))
            if registration is not None and (registration.container_ref != container_ref or registration.actor_ref != actor_ref):
                return False
            return self._remove_locked(session_ref, expected_intent_id=intent_id)
    def remove(self, *, runtime: str, session_ref: str, container_ref: str, actor_ref: str) -> bool:
        with self._lock:
            registration = self._registrations.get((runtime, session_ref))
            if registration is None or registration.container_ref != container_ref or registration.actor_ref != actor_ref:
                return False
            return self._remove_locked(session_ref, expected_intent_id=intent_id)

    def _remove_locked(self, session_ref: str, *, expected_intent_id: str | None = None) -> bool:
        key = (RUNTIME, session_ref)
        updated = dict(self._registrations)
        updated.pop(key, None)
        if self._state_dir is not None and not self._write_canonical_locked(updated):
            return False
        self._registrations = updated
        self._delete_intent_locked(session_ref, expected_intent_id=expected_intent_id)
        self.signal_reconcile()
        return True

    def _active_locked(self, runtime: str, session_ref: str) -> _Registration | None:
        registration = self._registrations.get((runtime, session_ref))
        if registration is None:
            return None
        if self._state_dir is not None or registration.expires_at > self._clock():
            return registration
        if self._registrations.get((runtime, session_ref)) is registration:
            del self._registrations[(runtime, session_ref)]
        return None

    @staticmethod
    def _valid_registration(runtime: object, session_ref: object, container_ref: object, actor_ref: object, socket_path: object, token: object) -> bool:
        return (
            runtime == RUNTIME
            and _valid(runtime, MAX_RUNTIME_CHARS)
            and _valid(session_ref, MAX_SESSION_CHARS)
            and _valid(container_ref, MAX_CONTAINER_CHARS)
            and _valid(actor_ref, MAX_ACTOR_CHARS)
            and _valid(socket_path, MAX_SOCKET_CHARS)
            and _valid(token, MAX_TOKEN_CHARS)
        )

    def _load(self) -> None:
        assert self._state_dir is not None and self._canonical is not None and self._unusable is not None
        if self._unusable.exists():
            self._rehydration_refused = True
            return
        raw = self._read_json(self._canonical)
        if not isinstance(raw, dict) or raw.get("version") != 1 or not isinstance(raw.get("registrations"), list):
            return
        loaded: dict[tuple[str, str], _Registration] = {}
        for item in raw["registrations"]:
            if not isinstance(item, dict):
                continue
            if not self._valid_loaded_item(item):
                continue
            registration = _Registration(**item)
            if self._valid_registration(registration.runtime, registration.session_ref, registration.container_ref, registration.actor_ref, registration.socket_path, registration.token):
                loaded[(registration.runtime, registration.session_ref)] = registration
                self._generation = max(self._generation, registration.generation)
        self._registrations = loaded

    @staticmethod
    def _valid_loaded_item(item: dict) -> bool:
        state = item.get("state")
        delivery_id = item.get("delivery_id")
        attempted_at = item.get("attempted_at")
        return (
            isinstance(item.get("generation"), int) and item["generation"] >= 0
            and isinstance(item.get("idle"), bool)
            and state in {"idle", "busy", "wake_inflight"}
            and item["idle"] == (state == "idle")
            and ((state == "wake_inflight" and _valid(delivery_id, 128) and isinstance(attempted_at, (int, float)))
                 or (state != "wake_inflight" and delivery_id is None and attempted_at is None))
            and all(key in item for key in ("runtime", "session_ref", "container_ref", "actor_ref", "socket_path", "token", "expires_at"))
        )
    def _ensure_capacity_locked(self) -> bool:
        if len(self._registrations) < MAX_REGISTRATIONS:
            return True
        # Capacity cleanup is deliberately non-admitting: only an absent endpoint is proof.
        for key, registration in list(self._registrations.items()):
            if not self._endpoint_is_provably_absent(registration.socket_path):
                continue
            updated = dict(self._registrations)
            del updated[key]
            if self._write_canonical_locked(updated):
                self._registrations = updated
                return True
        return False

    @staticmethod
    def _endpoint_is_provably_absent(socket_path: str) -> bool:
        if os.name != "nt":
            return not Path(socket_path).exists()
        try:
            import pywintypes
            import win32pipe
            import winerror
            try:
                win32pipe.WaitNamedPipe(socket_path, 0)
                return False
            except pywintypes.error as exc:
                return exc.winerror == winerror.ERROR_FILE_NOT_FOUND
        except Exception:
            return False
    def _intent_path(self, session_ref: str) -> Path | None:
        return self._intents / _safe_session_file(session_ref) if self._intents else None

    def _read_intent_locked(self, session_ref: str) -> dict | None:
        path = self._intent_path(session_ref)
        raw = self._read_json(path) if path else None
        return raw if isinstance(raw, dict) else None

    @staticmethod
    def _intent_matches(intent: dict, runtime: str, session_ref: str, container_ref: str, actor_ref: str, socket_path: str, token: str, idle: bool) -> bool:
        return all(intent.get(key) == value for key, value in {
            "runtime": runtime, "session_ref": session_ref, "container_ref": container_ref,
            "actor_ref": actor_ref, "socket_path": socket_path, "token": token, "idle": idle,
        }.items())

    def _delete_intent_locked(self, session_ref: str, expected_intent_id: str | None) -> bool:
        path = self._intent_path(session_ref)
        if path is None:
            return True
        raw = self._read_json(path)
        if expected_intent_id is not None and (not isinstance(raw, dict) or raw.get("intent_id") != expected_intent_id):
            return False
        try:
            path.unlink(missing_ok=True)
            return True
        except OSError:
            return False

    def _write_canonical_locked(self, registrations: dict[tuple[str, str], _Registration]) -> bool:
        if self._canonical is None:
            return True
        payload = {"version": 1, "registrations": [asdict(item) for item in registrations.values()]}
        return self._atomic_write(self._canonical, payload)

    def _quarantine_or_mark_unusable_locked(self) -> bool:
        assert self._canonical is not None and self._unusable is not None
        try:
            if self._canonical.exists():
                self._canonical.replace(self._canonical.with_suffix(".unusable"))
                return self._atomic_write(self._unusable, {"unusable": True})
                return
        except OSError:
            pass
        return self._atomic_write(self._unusable, {"unusable": True})

    def _clear_unusable_locked(self) -> None:
        if self._unusable is None:
            return
        try:
            self._unusable.unlink(missing_ok=True)
            self._rehydration_refused = False
        except OSError:
            pass

    def _atomic_write(self, path: Path, payload: dict) -> bool:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if os.name != "nt":
                try:
                    os.chmod(path.parent, 0o700)
                except OSError:
                    pass
            temp = path.with_name(path.name + ".tmp")
            temp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
            if os.name != "nt":
                try:
                    os.chmod(temp, 0o600)
                except OSError:
                    pass
            os.replace(temp, path)
            return True
        except (OSError, TypeError, ValueError):
            return False

    @staticmethod
    def _read_json(path: Path | None) -> object:
        if path is None:
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return None
