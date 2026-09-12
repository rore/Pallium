"""Trusted-local current Codex wake reservations.

One service process owns this store. Atomic replacement protects crash recovery,
not concurrent writers in multiple processes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
import os
from pathlib import Path
import re
import threading
from typing import Callable, TypeVar

MAX_RESERVATIONS = 256
_ENDPOINT_RE = re.compile(r"^relay-session-[0-9a-f]{32}$")
_T = TypeVar("_T")


@dataclass(frozen=True)
class CodexWakeReservation:
    recipient_endpoint_id: str
    delivery_id: str
    session_ref: str
    container_ref: str
    generation: int
    outcome: str = "reserved"


class CodexWakeRegistry:
    """Bounded current fences only; no attempt history."""

    def __init__(self, state_dir: Path | None = None) -> None:
        self._lock = threading.RLock()
        self._path = state_dir / "reservations.json" if state_dir else None
        self._reservations: dict[str, CodexWakeReservation] = {}
        self._generation = 0
        self._usable = True
        if self._path is not None:
            self._load()

    @property
    def usable(self) -> bool:
        return self._usable

    def reserve(
        self, *, recipient_endpoint_id: str, delivery_id: str,
        session_ref: str, container_ref: str,
        still_pending: Callable[[], bool] | None = None,
    ) -> CodexWakeReservation | None:
        if not self._valid(recipient_endpoint_id, delivery_id, session_ref, container_ref):
            return None
        with self._lock:
            if not self._usable or recipient_endpoint_id in self._reservations:
                return None
            if any(item.delivery_id == delivery_id for item in self._reservations.values()):
                return None
            if len(self._reservations) >= MAX_RESERVATIONS:
                return None
            try:
                if still_pending is not None and still_pending() is not True:
                    return None
            except Exception:
                return None
            self._generation += 1
            item = CodexWakeReservation(
                recipient_endpoint_id, delivery_id, session_ref, container_ref,
                self._generation,
            )
            updated = {**self._reservations, recipient_endpoint_id: item}
            if not self._write_locked(updated):
                self._usable = False
                return None
            self._reservations = updated
            return item

    def run_if_current(self, reservation: CodexWakeReservation, operation: Callable[[], _T]) -> tuple[bool, _T | None]:
        """Keep generation validation and non-idempotent native write indivisible."""
        with self._lock:
            if self._reservations.get(reservation.recipient_endpoint_id) != reservation:
                return False, None
            return True, operation()

    def record_outcome(self, reservation: CodexWakeReservation, outcome: str) -> bool:
        if outcome not in {"accepted", "uncertain"}:
            return False
        with self._lock:
            current = self._reservations.get(reservation.recipient_endpoint_id)
            if current != reservation:
                return False
            updated_item = replace(current, outcome=outcome)
            updated = {**self._reservations, current.recipient_endpoint_id: updated_item}
            if not self._write_locked(updated):
                self._usable = False
                return False
            self._reservations = updated
            return True

    def release_generation(self, reservation: CodexWakeReservation) -> bool:
        with self._lock:
            if self._reservations.get(reservation.recipient_endpoint_id) != reservation:
                return False
            return self._remove_locked(reservation.recipient_endpoint_id)

    def release_delivery(self, delivery_id: str) -> CodexWakeReservation | None:
        with self._lock:
            match = next((item for item in self._reservations.values() if item.delivery_id == delivery_id), None)
            if match is None or not self._remove_locked(match.recipient_endpoint_id):
                return None
            return match

    def reserved(self, recipient_endpoint_id: str) -> bool:
        with self._lock:
            return recipient_endpoint_id in self._reservations or not self._usable

    def snapshot(self, recipient_endpoint_id: str) -> CodexWakeReservation | None:
        with self._lock:
            return self._reservations.get(recipient_endpoint_id)

    def _remove_locked(self, endpoint_id: str) -> bool:
        updated = dict(self._reservations)
        updated.pop(endpoint_id, None)
        if not self._write_locked(updated):
            self._usable = False
            return False
        self._reservations = updated
        return True

    @staticmethod
    def _valid(endpoint_id: object, delivery_id: object, session_ref: object, container_ref: object) -> bool:
        return (
            isinstance(endpoint_id, str) and bool(_ENDPOINT_RE.fullmatch(endpoint_id))
            and all(isinstance(value, str) and 0 < len(value) <= maximum and value.isprintable()
                    for value, maximum in ((delivery_id, 128), (session_ref, 512), (container_ref, 512)))
        )

    def _load(self) -> None:
        assert self._path is not None
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            items = raw["reservations"]
            if raw.get("version") != 1 or not isinstance(items, list) or len(items) > MAX_RESERVATIONS:
                raise ValueError
            loaded: dict[str, CodexWakeReservation] = {}
            for value in items:
                if not isinstance(value, dict) or set(value) != {
                    "recipient_endpoint_id", "delivery_id", "session_ref", "container_ref", "generation", "outcome",
                }:
                    raise ValueError
                item = CodexWakeReservation(**value)
                if (not self._valid(item.recipient_endpoint_id, item.delivery_id, item.session_ref, item.container_ref)
                        or type(item.generation) is not int or item.generation < 1
                        or item.outcome not in {"reserved", "accepted", "uncertain"}
                        or item.recipient_endpoint_id in loaded
                        or any(current.delivery_id == item.delivery_id for current in loaded.values())):
                    raise ValueError
                loaded[item.recipient_endpoint_id] = item
                self._generation = max(self._generation, item.generation)
            self._reservations = loaded
        except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
            self._usable = False
            self._reservations = {}

    def _write_locked(self, reservations: dict[str, CodexWakeReservation]) -> bool:
        if self._path is None:
            return True
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temp = self._path.with_name(self._path.name + ".tmp")
            temp.write_text(json.dumps({
                "version": 1,
                "reservations": [asdict(item) for item in reservations.values()],
            }, separators=(",", ":")), encoding="utf-8")
            os.replace(temp, self._path)
            return True
        except (OSError, TypeError, ValueError):
            return False