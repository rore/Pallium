"""Trusted-local Claude Code wake capability registry."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import json
import math
import os
import re
from pathlib import Path
import threading
import time
from typing import Callable
import unicodedata

from core.relay_activation import ActivationAttemptResult

RUNTIME = "claude-code"
TTL_SECONDS = 900  # Compatibility only for memory-only test registries.
MAX_REGISTRATIONS = 256
MAX_RUNTIME_CHARS = 32
MAX_SESSION_CHARS = 512
MAX_CONTAINER_CHARS = 512
MAX_SOCKET_CHARS = 4096
MAX_TOKEN_CHARS = 8192
_ENDPOINT_RE = re.compile(r"^relay-session-[0-9a-f]{32}$")


@dataclass(frozen=True)
class _Registration:
    runtime: str
    session_ref: str
    container_ref: str
    socket_path: str = field(repr=False)
    token: str = field(repr=False)
    generation: int = 0
    expires_at: float = float("inf")
    idle: bool = False
    state: str = "busy"
    delivery_id: str | None = None
    attempted_at: float | None = None
    recipient_endpoint_id: str | None = None


Transport = Callable[[str, str], object]


def _valid(value: object, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and len(value) <= maximum
        and not any(unicodedata.category(char) == "Cc" for char in value)
    )



def _safe_session_file(runtime: str, session_ref: str, container_ref: str) -> str:
    import hashlib
    identity = json.dumps(
        [runtime, session_ref, container_ref],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest() + ".json"


class ClaudeWakeRegistry:
    """Exact-scope capability state; persistence is trusted-local and fail closed."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic, wall_clock: Callable[[], float] = time.time, state_dir: Path | None = None) -> None:
        self._clock = clock
        self._wall_clock = wall_clock
        self._lock = threading.RLock()
        self._generation = 0
        self._registrations: dict[tuple[str, str, str], _Registration] = {}
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
        socket_path: str,
        token: str,
        idle: bool = False,
        intent_id: str | None = None,
    ) -> bool:
        if not isinstance(idle, bool) or not self._valid_registration(
            runtime, session_ref, container_ref, socket_path, token
        ):
            raise ValueError("invalid registration")
        if self._state_dir is not None and not _valid(intent_id, 128):
            raise ValueError("invalid registration")
        with self._lock:
            if self._rehydration_refused:
                return False
            key = (runtime, session_ref, container_ref)
            if self._state_dir is None:
                now = self._clock()
                self._registrations = {
                    current_key: current for current_key, current in self._registrations.items()
                    if current.expires_at > now
                }
            if self._state_dir is not None:
                intent = self._read_intent_locked(runtime, session_ref, container_ref)
                # Compare-before-apply: a delayed request can never replace newer state.
                if intent is None or intent.get("intent_id") != intent_id or not self._intent_matches(intent, runtime, session_ref, container_ref, socket_path, token, idle):
                    return False
                if key not in self._registrations and not self._ensure_capacity_locked():
                    return False
            elif key not in self._registrations and len(self._registrations) >= MAX_REGISTRATIONS:
                raise ValueError("registration capacity reached")
            self._generation += 1
            existing = self._registrations.get(key)
            registration = (
                replace(
                    existing, socket_path=socket_path, token=token,
                    generation=self._generation,
                    expires_at=(float("inf") if self._state_dir else self._clock() + TTL_SECONDS),
                )
                if existing is not None and existing.state == "wake_inflight"
                else _Registration(
                    runtime=runtime, session_ref=session_ref, container_ref=container_ref,
                    socket_path=socket_path, token=token, generation=self._generation,
                    expires_at=(float("inf") if self._state_dir else self._clock() + TTL_SECONDS),
                    idle=idle, state="idle" if idle else "busy",
                )
            )
            if self._state_dir is not None and not self._write_canonical_locked({**self._registrations, key: registration}):
                return False
            if self._state_dir is not None and not self._clear_unusable_locked():
                return False
            self._registrations[key] = registration
            if self._state_dir is not None:
                self._delete_intent_locked(
                    runtime, session_ref, container_ref,
                    expected_intent_id=intent_id,
                )
                self.signal_reconcile()
            return True

    def mark_busy(
        self, *, runtime: str, session_ref: str, container_ref: str
    ) -> bool:
        """Fail closed immediately when a coordinator observes active Claude work."""
        with self._lock:
            registration = self._active_locked(runtime, session_ref, container_ref)
            if registration is None or registration.container_ref != container_ref:
                return False
            if registration.state == "wake_inflight":
                return True
            self._generation += 1
            busy = replace(registration, generation=self._generation, idle=False, state="busy", delivery_id=None, attempted_at=None, recipient_endpoint_id=None)
            key = (runtime, session_ref, container_ref)
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
        transport: Transport | None,
        delivery_id: str | None = None,
        recipient_endpoint_id: str | None = None,
        still_pending: Callable[[], bool] | None = None,
        on_unreachable: Callable[[], None] | None = None,
    ) -> bool:
        return self.attempt(
            runtime=runtime, session_ref=session_ref, container_ref=container_ref,
            transport=transport, delivery_id=delivery_id,
            recipient_endpoint_id=recipient_endpoint_id,
            still_pending=still_pending, on_unreachable=on_unreachable,
        ).outcome == "accepted"

    def attempt(
        self,
        *,
        runtime: str,
        session_ref: str,
        container_ref: str,
        transport: Transport | None,
        delivery_id: str | None = None,
        recipient_endpoint_id: str | None = None,
        still_pending: Callable[[], bool] | None = None,
        on_unreachable: Callable[[], None] | None = None,
    ) -> ActivationAttemptResult:
        if transport is None:
            return ActivationAttemptResult("deferred", "transport_unavailable", native_retry_safe=True)
        if delivery_id is not None and (
            not _valid(delivery_id, 128)
            or not isinstance(recipient_endpoint_id, str)
            or not _ENDPOINT_RE.fullmatch(recipient_endpoint_id)
        ):
            return ActivationAttemptResult("deferred", "invalid_reservation")
        notify = False
        with self._lock:
            registration = self._active_locked(runtime, session_ref, container_ref)
            if registration is None or registration.container_ref != container_ref or not registration.idle:
                return ActivationAttemptResult("deferred", "not_eligible")
            for current in self._registrations.values():
                if current.state != "wake_inflight":
                    continue
                same_endpoint = recipient_endpoint_id is not None and current.recipient_endpoint_id == recipient_endpoint_id
                legacy_same_session = current.recipient_endpoint_id is None and current.runtime == runtime and current.session_ref == session_ref
                if same_endpoint or legacy_same_session:
                    return ActivationAttemptResult("deferred", "reservation_exists")
            try:
                if still_pending is not None and still_pending() is not True:
                    return ActivationAttemptResult("deferred", "delivery_not_pending")
            except Exception:
                return ActivationAttemptResult("deferred", "pending_check_failed")

            self._generation += 1
            consumed = replace(
                registration, generation=self._generation, idle=False,
                state="wake_inflight", delivery_id=delivery_id,
                attempted_at=self._wall_clock(),
                recipient_endpoint_id=recipient_endpoint_id,
            )
            key = (runtime, session_ref, container_ref)
            if self._state_dir is not None and not self._write_canonical_locked({**self._registrations, key: consumed}):
                return ActivationAttemptResult("deferred", "reservation_write_failed")
            self._registrations[key] = consumed

            try:
                raw = transport(consumed.socket_path, consumed.token)
            except Exception:
                raw = ActivationAttemptResult("uncertain", "transport_exception", ("submission_attempted",))
            if isinstance(raw, ActivationAttemptResult):
                result = raw
            elif raw is True or raw == "accepted":
                result = ActivationAttemptResult("accepted", "transport_accepted", ("submission_attempted", "transport_accepted"))
            elif raw == "unreachable":
                result = ActivationAttemptResult("failed", "endpoint_missing", native_retry_safe=True, destination_health_update="unreachable")
            else:
                result = ActivationAttemptResult("uncertain", "transport_uncertain", ("submission_attempted",))

            if result.outcome in {"accepted", "uncertain"} or not result.native_retry_safe:
                return result
            updated = replace(
                consumed,
                idle=result.destination_health_update is None,
                state="unreachable" if result.destination_health_update == "unreachable" else "idle",
                delivery_id=None, attempted_at=None, recipient_endpoint_id=None,
            )
            if self._state_dir is not None and not self._write_canonical_locked({**self._registrations, key: updated}):
                self._rehydration_refused = True
                self._durability_degraded = not self._quarantine_or_mark_unusable_locked()
                return ActivationAttemptResult("uncertain", "safe_reset_write_failed", ("submission_attempted",))
            self._registrations[key] = updated
            notify = result.destination_health_update == "unreachable"

        if notify and on_unreachable is not None:
            try:
                on_unreachable()
            except Exception:
                pass
        return result

    def release_delivery(self, delivery_id: str) -> bool:
        """Release only the exact ACK-authoritative activation reservation."""
        if not _valid(delivery_id, 128):
            return False
        with self._lock:
            matches = [
                (key, item)
                for key, item in self._registrations.items()
                if item.state == "wake_inflight" and item.delivery_id == delivery_id
            ]
            if len(matches) != 1:
                return False
            key, current = matches[0]
            self._generation += 1
            released = replace(
                current, generation=self._generation, idle=False, state="busy",
                delivery_id=None, attempted_at=None, recipient_endpoint_id=None,
            )
            if self._state_dir is not None and not self._write_canonical_locked({**self._registrations, key: released}):
                self._rehydration_refused = True
                self._durability_degraded = not self._quarantine_or_mark_unusable_locked()
                return False
            self._registrations[key] = released
            return True

    def state_for(
        self,
        *,
        recipient_endpoint_id: str,
        session_ref: str,
        container_ref: str,
    ) -> str | None:
        # Read paths must not wait behind a native write; unknown is truthful here.
        if not self._lock.acquire(blocking=False):
            return None
        try:
            if self._rehydration_refused:
                return None
            for item in self._registrations.values():
                if (
                    item.state == "wake_inflight"
                    and item.recipient_endpoint_id == recipient_endpoint_id
                ):
                    return item.state
            item = self._active_locked(RUNTIME, session_ref, container_ref)
            return item.state if item is not None else None
        finally:
            self._lock.release()

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
            intents = []
            for path in intent_paths:
                intent = self._read_json(path)
                if not isinstance(intent, dict) or "actor_ref" in intent:
                    continue
                scope = tuple(
                    intent.get(key)
                    for key in ("runtime", "session_ref", "container_ref")
                )
                if not all(isinstance(value, str) for value in scope):
                    continue
                intents.append((path, intent, scope, path == self._intent_path(*scope)))
            intents.sort(key=lambda item: not item[3])
            applied_scopes = set()
            for path, intent, scope, is_scoped in intents:
                if is_scoped:
                    try:
                        if intent.get("closed") is True:
                            applied = self.close(**{key: intent[key] for key in ("runtime", "session_ref", "container_ref", "intent_id")})
                        else:
                            applied = self.register(**{key: intent[key] for key in ("runtime", "session_ref", "container_ref", "socket_path", "token", "idle", "intent_id")})
                    except (KeyError, ValueError):
                        applied = False
                    if applied:
                        applied_scopes.add(scope)
                    continue

                # Pre-scoped intents cannot safely compete with exact-scope state.
                # Fence unless a newer scoped intent was successfully applied.
                current = self._registrations.get(scope)
                if (
                    scope not in applied_scopes
                    and (current is None or current.state != "wake_inflight")
                ):
                    updated = dict(self._registrations)
                    updated.pop(scope, None)
                    if not self._write_canonical_locked(updated):
                        self._registrations = updated
                        self._rehydration_refused = True
                        self._durability_degraded = (
                            not self._quarantine_or_mark_unusable_locked()
                        )
                        continue
                    self._registrations = updated
                current = self._read_json(path)
                if isinstance(current, dict) and current.get("intent_id") == intent.get("intent_id"):
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        pass

    def rearm_inflight(self, **_kwargs: object) -> bool:
        """Compatibility no-op: elapsed time never releases a reservation."""
        return False

    def clear_inflight(self, **_kwargs: object) -> bool:
        """Compatibility no-op: pending/absence reads never release a reservation."""
        return False
    def close(
        self, *, runtime: str, session_ref: str, container_ref: str, intent_id: str | None = None
    ) -> bool:
        """Consume an exact closed intent without opening or admitting its endpoint."""
        with self._lock:
            if self._state_dir is not None:
                intent = self._read_intent_locked(runtime, session_ref, container_ref)
                if not isinstance(intent, dict) or intent.get("intent_id") != intent_id or intent.get("closed") is not True:
                    return False
                if any(intent.get(key) != value for key, value in {
                    "runtime": runtime, "session_ref": session_ref, "container_ref": container_ref,
                }.items()):
                    return False
            registration = self._registrations.get((runtime, session_ref, container_ref))
            if registration is not None and (registration.container_ref != container_ref):
                return False
            if registration is not None and registration.state == "wake_inflight":
                self._delete_intent_locked(runtime, session_ref, container_ref, expected_intent_id=intent_id)
                return True
            return self._remove_locked(
                runtime, session_ref, container_ref,
                expected_intent_id=intent_id,
            )
    def remove(self, *, runtime: str, session_ref: str, container_ref: str) -> bool:
        with self._lock:
            registration = self._registrations.get((runtime, session_ref, container_ref))
            if registration is None or registration.container_ref != container_ref:
                return False
            if registration.state == "wake_inflight":
                return True
            return self._remove_locked(runtime, session_ref, container_ref)
    def _remove_locked(
        self,
        runtime: str,
        session_ref: str,
        container_ref: str,
        *,
        expected_intent_id: str | None = None,
    ) -> bool:
        key = (runtime, session_ref, container_ref)
        updated = dict(self._registrations)
        updated.pop(key, None)
        if self._state_dir is not None and not self._write_canonical_locked(updated):
            return False
        self._registrations = updated
        self._delete_intent_locked(
            runtime, session_ref, container_ref,
            expected_intent_id=expected_intent_id,
        )
        self.signal_reconcile()
        return True

    def _active_locked(
        self, runtime: str, session_ref: str, container_ref: str
    ) -> _Registration | None:
        registration = self._registrations.get((runtime, session_ref, container_ref))
        if registration is None:
            return None
        if (
            registration.state == "wake_inflight"
            or self._state_dir is not None
            or registration.expires_at > self._clock()
        ):
            return registration
        if self._registrations.get((runtime, session_ref, container_ref)) is registration:
            del self._registrations[(runtime, session_ref, container_ref)]
        return None

    @staticmethod
    def _valid_registration(runtime: object, session_ref: object, container_ref: object, socket_path: object, token: object) -> bool:
        return (
            runtime == RUNTIME
            and _valid(runtime, MAX_RUNTIME_CHARS)
            and _valid(session_ref, MAX_SESSION_CHARS)
            and _valid(container_ref, MAX_CONTAINER_CHARS)
            and _valid(socket_path, MAX_SOCKET_CHARS)
            and _valid(token, MAX_TOKEN_CHARS)
        )

    def _load(self) -> None:
        assert self._state_dir is not None and self._canonical is not None and self._unusable is not None
        if self._unusable.exists():
            self._rehydration_refused = True
            return
        if not self._canonical.exists():
            return
        raw = self._read_json(self._canonical)
        if (
            not isinstance(raw, dict)
            or raw.get("version") != 1
            or not isinstance(raw.get("registrations"), list)
            or len(raw["registrations"]) > MAX_REGISTRATIONS
        ):
            self._rehydration_refused = True
            return
        loaded: dict[tuple[str, str, str], _Registration] = {}
        inflight_deliveries: set[str] = set()
        inflight_endpoints: set[str] = set()
        for item in raw["registrations"]:
            if not isinstance(item, dict) or not self._valid_loaded_item(item):
                self._rehydration_refused = True
                self._registrations = {}
                return
            registration = _Registration(**item)
            key = (registration.runtime, registration.session_ref, registration.container_ref)
            if (
                not self._valid_registration(
                    registration.runtime, registration.session_ref,
                    registration.container_ref, registration.socket_path,
                    registration.token,
                )
                or key in loaded
                or (
                    registration.state == "wake_inflight"
                    and (
                        registration.delivery_id in inflight_deliveries
                        or (
                            registration.recipient_endpoint_id is not None
                            and registration.recipient_endpoint_id in inflight_endpoints
                        )
                    )
                )
            ):
                self._rehydration_refused = True
                self._registrations = {}
                return
            loaded[key] = registration
            if registration.state == "wake_inflight":
                assert registration.delivery_id is not None
                inflight_deliveries.add(registration.delivery_id)
                if registration.recipient_endpoint_id is not None:
                    inflight_endpoints.add(registration.recipient_endpoint_id)
            self._generation = max(self._generation, registration.generation)
        self._registrations = loaded

    @staticmethod
    def _valid_loaded_item(item: dict) -> bool:
        required = {
            "runtime", "session_ref", "container_ref", "socket_path", "token",
            "generation", "expires_at", "idle", "state", "delivery_id",
            "attempted_at",
        }
        if set(item) not in (required, required | {"recipient_endpoint_id"}):
            return False
        if (
            type(item["generation"]) is not int
            or item["generation"] < 0
            or type(item["idle"]) is not bool
            or type(item["state"]) is not str
            or type(item["expires_at"]) not in (int, float)
        ):
            return False
        state = item["state"]
        delivery_id = item["delivery_id"]
        attempted_at = item["attempted_at"]
        endpoint_id = item.get("recipient_endpoint_id")
        if state not in {"idle", "busy", "wake_inflight", "unreachable"} or item["idle"] != (state == "idle"):
            return False
        if state != "wake_inflight":
            return delivery_id is None and attempted_at is None and endpoint_id is None
        return (
            _valid(delivery_id, 128)
            and type(attempted_at) in (int, float)
            and math.isfinite(attempted_at)
            and (endpoint_id is None or (
                isinstance(endpoint_id, str)
                and bool(_ENDPOINT_RE.fullmatch(endpoint_id))
            ))
        )
    def _ensure_capacity_locked(self) -> bool:
        if len(self._registrations) < MAX_REGISTRATIONS:
            return True
        # Capacity cleanup is deliberately non-admitting: only an absent endpoint is proof.
        for key, registration in list(self._registrations.items()):
            if registration.state == "wake_inflight" or not self._endpoint_is_provably_absent(registration.socket_path):
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
    def _intent_path(
        self, runtime: str, session_ref: str, container_ref: str
    ) -> Path | None:
        return self._intents / _safe_session_file(
            runtime, session_ref, container_ref
        ) if self._intents else None

    def _read_intent_locked(
        self, runtime: str, session_ref: str, container_ref: str
    ) -> dict | None:
        path = self._intent_path(runtime, session_ref, container_ref)
        raw = self._read_json(path) if path else None
        return raw if isinstance(raw, dict) else None

    @staticmethod
    def _intent_matches(intent: dict, runtime: str, session_ref: str, container_ref: str, socket_path: str, token: str, idle: bool) -> bool:
        return all(intent.get(key) == value for key, value in {
            "runtime": runtime, "session_ref": session_ref, "container_ref": container_ref,
            "socket_path": socket_path, "token": token, "idle": idle,
        }.items())

    def _delete_intent_locked(
        self,
        runtime: str,
        session_ref: str,
        container_ref: str,
        expected_intent_id: str | None,
    ) -> bool:
        path = self._intent_path(runtime, session_ref, container_ref)
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

    def _write_canonical_locked(self, registrations: dict[tuple[str, str, str], _Registration]) -> bool:
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

    def _clear_unusable_locked(self) -> bool:
        if self._unusable is None:
            return True
        try:
            self._unusable.unlink(missing_ok=True)
        except OSError:
            self._rehydration_refused = True
            return False
        self._rehydration_refused = False
        return True

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
