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
    correlated_claim_attempts: int | None = None


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
            if (
                current is None
                or current.delivery_id != reservation.delivery_id
                or current.generation != reservation.generation
            ):
                return False
            updated_item = replace(current, outcome=outcome)
            updated = {**self._reservations, current.recipient_endpoint_id: updated_item}
            if not self._write_locked(updated):
                self._usable = False
                return False
            self._reservations = updated
            return True

    def correlate_claim(
        self,
        *,
        delivery_id: str,
        recipient_endpoint_id: str,
        session_ref: str,
        container_ref: str,
        attempts: int,
    ) -> bool:
        """Persist the exact hook claim correlated to the current wake fence."""
        if (
            not self._valid(
                recipient_endpoint_id, delivery_id, session_ref, container_ref
            )
            or type(attempts) is not int
            or attempts < 1
        ):
            return False
        with self._lock:
            current = self._reservations.get(recipient_endpoint_id)
            if (
                current is None
                or current.delivery_id != delivery_id
                or current.session_ref != session_ref
                or current.container_ref != container_ref
                or current.correlated_claim_attempts not in (None, attempts)
            ):
                return False
            updated_item = replace(current, correlated_claim_attempts=attempts)
            updated = {**self._reservations, recipient_endpoint_id: updated_item}
            if not self._write_locked(updated):
                self._usable = False
                return False
            self._reservations = updated
            return True

    def replace_generation(
        self,
        reservation: CodexWakeReservation,
        *,
        session_ref: str,
        container_ref: str,
    ) -> CodexWakeReservation | None:
        """Replace one current fence without exposing an unfenced endpoint."""
        if not self._valid(
            reservation.recipient_endpoint_id,
            reservation.delivery_id,
            session_ref,
            container_ref,
        ):
            return None
        with self._lock:
            if self._reservations.get(reservation.recipient_endpoint_id) != reservation:
                return None
            self._generation += 1
            replacement = replace(
                reservation,
                session_ref=session_ref,
                container_ref=container_ref,
                generation=self._generation,
                outcome="reserved",
                correlated_claim_attempts=None,
            )
            updated = {
                **self._reservations,
                reservation.recipient_endpoint_id: replacement,
            }
            if not self._write_locked(updated):
                self._usable = False
                return None
            self._reservations = updated
            return replacement

    def release_generation(self, reservation: CodexWakeReservation) -> bool:
        return bool(self.release_generations((reservation,)))

    def release_generations(
        self, reservations: tuple[CodexWakeReservation, ...]
    ) -> tuple[CodexWakeReservation, ...]:
        """Atomically remove only generations that are still current."""
        with self._lock:
            matches = {
                item.recipient_endpoint_id: item
                for item in reservations
                if self._reservations.get(item.recipient_endpoint_id) == item
            }
            if not matches:
                return ()
            updated = {
                endpoint_id: item
                for endpoint_id, item in self._reservations.items()
                if endpoint_id not in matches
            }
            if not self._write_locked(updated):
                self._usable = False
                return ()
            self._reservations = updated
            return tuple(matches.values())

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

    def reservations(self) -> tuple[CodexWakeReservation, ...]:
        with self._lock:
            return tuple(self._reservations.values())

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
            version = raw.get("version")
            items = raw["reservations"]
            if version not in {1, 2} or not isinstance(items, list) or len(items) > MAX_RESERVATIONS:
                raise ValueError
            legacy_fields = {
                "recipient_endpoint_id", "delivery_id", "session_ref",
                "container_ref", "generation", "outcome",
            }
            loaded: dict[str, CodexWakeReservation] = {}
            for value in items:
                if not isinstance(value, dict):
                    raise ValueError
                expected = legacy_fields if version == 1 else {
                    *legacy_fields, "correlated_claim_attempts",
                }
                if set(value) != expected:
                    raise ValueError
                item = CodexWakeReservation(
                    **value,
                    **({"correlated_claim_attempts": None} if version == 1 else {}),
                )
                if (
                    not self._valid(
                        item.recipient_endpoint_id,
                        item.delivery_id,
                        item.session_ref,
                        item.container_ref,
                    )
                    or type(item.generation) is not int
                    or item.generation < 1
                    or item.outcome not in {"reserved", "accepted", "uncertain"}
                    or (
                        item.correlated_claim_attempts is not None
                        and (
                            type(item.correlated_claim_attempts) is not int
                            or item.correlated_claim_attempts < 1
                        )
                    )
                    or item.recipient_endpoint_id in loaded
                    or any(
                        current.delivery_id == item.delivery_id
                        for current in loaded.values()
                    )
                ):
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
                "version": 2,
                "reservations": [asdict(item) for item in reservations.values()],
            }, separators=(",", ":")), encoding="utf-8")
            os.replace(temp, self._path)
            return True
        except (OSError, TypeError, ValueError):
            return False