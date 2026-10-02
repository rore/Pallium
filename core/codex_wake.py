"""Relay SQLite current fences and a single-owner native initiation guard."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
import logging
from pathlib import Path
import re
import threading
from typing import Callable, TypeVar

MAX_RESERVATIONS = 256
# The old writer escaped each astral character as two six-character escapes.
# 256 rows * (128 + 512 + 512) field characters * 12 plus JSON overhead fits.
MAX_LEGACY_JSON_CHARACTERS = 4 * 1024 * 1024
_ENDPOINT_RE = re.compile(r"^relay-session-[0-9a-f]{32}$")
_T = TypeVar("_T")
logger = logging.getLogger(__name__)


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

    def __init__(self, state_dir: Path | None = None, *, relay_service=None, legacy_state_dir: Path | None = None, ownership_lock=None, enabled: bool = True) -> None:
        self._lock = ownership_lock if ownership_lock is not None else threading.RLock()
        self._path = state_dir / "reservations.json" if state_dir else None
        self._reservations: dict[str, CodexWakeReservation] = {}
        self._generation = 0
        self._usable = enabled and state_dir is None
        self._relay = relay_service
        if relay_service is not None:
            self._path = legacy_state_dir / "reservations.json" if legacy_state_dir else None
            self._refresh()
        elif state_dir is not None:
            # Old file-only construction is deliberately fail-closed. Legacy
            # data is read only by explicit offline SQLite initialization.
            self._usable = False

    def _refresh(self) -> None:
        if self._relay is None:
            return
        try:
            initialized, items = self._relay.codex_wake_snapshot()
            if len(items) > MAX_RESERVATIONS or any(not self._valid_item(item) for item in items):
                raise ValueError("invalid persisted Codex wake fence")
            self._usable = initialized
            self._initialized = initialized
            self._reservations = {item.recipient_endpoint_id: item for item in items}
        except Exception as exc:
            logger.warning("codex_wake_authority_read_failed error_type=%s", type(exc).__name__)
            self._usable = False
            self._initialized = None
            self._reservations = {}

    @classmethod
    def _valid_item(cls, item: CodexWakeReservation) -> bool:
        return (
            cls._valid(item.recipient_endpoint_id, item.delivery_id, item.session_ref, item.container_ref)
            and type(item.generation) is int and 1 <= item.generation < 2**63
            and item.outcome in {"prepared", "reserved", "accepted", "uncertain"}
            and (item.correlated_claim_attempts is None or
                 (type(item.correlated_claim_attempts) is int and 1 <= item.correlated_claim_attempts < 2**63))
        )

    def initialize(self, *, old_owner_drained: bool) -> bool:
        """Offline only: caller must prove the old file owner has stopped."""
        with self._lock:
            self._refresh()
            if self._usable:
                return True
            if self._relay is None or old_owner_drained is not True or self._initialized is not False:
                return False
            self._reservations = {}
            self._usable = True
            if self._path is not None:
                self._load()
            if not self._usable:
                return False
            try:
                self._relay.codex_wake_initialize(tuple(self._reservations.values()))
            except Exception as exc:
                logger.warning("codex_wake_initialization_failed error_type=%s", type(exc).__name__)
            self._refresh()
            return self._usable

    def _transition(self, operation: str, **kwargs):
        try:
            return self._relay.codex_wake_transition(operation, **kwargs)
        except Exception as exc:
            logger.warning("codex_wake_transition_failed operation=%s error_type=%s", operation, type(exc).__name__)
            # A commit/return error can be ambiguous. Never launch from its
            # return value; the next operation reads the durable authority.
            return None

    @property
    def usable(self) -> bool:
        with self._lock:
            self._refresh()
            return self._usable

    @property
    def persistent(self) -> bool:
        return self._relay is not None

    def reconcile(self, reservation: CodexWakeReservation):
        with self._lock:
            return self._transition("reconcile", reservation=reservation)

    def reserve(
        self, *, recipient_endpoint_id: str, delivery_id: str,
        session_ref: str, container_ref: str,
        still_pending: Callable[[], bool] | None = None,
    ) -> CodexWakeReservation | None:
        if not self._valid(recipient_endpoint_id, delivery_id, session_ref, container_ref):
            return None
        with self._lock:
            if self._relay is not None:
                return self._transition("reserve", values={
                    "recipient_endpoint_id": recipient_endpoint_id, "delivery_id": delivery_id,
                    "session_ref": session_ref, "container_ref": container_ref,
                })
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
                self._generation, outcome="prepared",
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
            self._refresh()
            if not self._usable:
                return False, None
            if self._reservations.get(reservation.recipient_endpoint_id) != reservation:
                return False, None
            return True, operation()

    def record_outcome(self, reservation: CodexWakeReservation, outcome: str) -> bool:
        if outcome not in {"accepted", "uncertain"}:
            return False
        with self._lock:
            self._refresh()
            current = self._reservations.get(reservation.recipient_endpoint_id)
            if (
                current is None
                or current.delivery_id != reservation.delivery_id
                or current.generation != reservation.generation
                or current.session_ref != reservation.session_ref
                or current.container_ref != reservation.container_ref
            ):
                return False
            if outcome == "accepted":
                if current.outcome != "uncertain" or reservation.outcome != "uncertain":
                    return False
            elif current != reservation:
                return False
            if self._relay is not None:
                return self._transition("outcome", reservation=current, outcome=outcome) is not None
            updated_item = replace(current, outcome=outcome)
            updated = {**self._reservations, current.recipient_endpoint_id: updated_item}
            if not self._write_locked(updated):
                self._usable = False
                return False
            self._reservations = updated
            return True

    def begin_native_attempt(self, reservation: CodexWakeReservation) -> CodexWakeReservation | None:
        """Spend a never-written prepared generation before native initiation."""
        with self._lock:
            self._refresh()
            if not self._usable or reservation.outcome != "prepared" or reservation.correlated_claim_attempts is not None:
                return None
            current = self._reservations.get(reservation.recipient_endpoint_id)
            if current != reservation:
                return None
            if self._relay is not None:
                return self._transition("begin_native_attempt", reservation=reservation)
            updated_item = replace(reservation, outcome="uncertain")
            updated = {**self._reservations, reservation.recipient_endpoint_id: updated_item}
            if not self._write_locked(updated):
                self._usable = False
                return None
            self._reservations = updated
            return updated_item

    def correlate_claim(
        self,
        *,
        delivery_id: str,
        recipient_endpoint_id: str,
        session_ref: str,
        container_ref: str,
        attempts: int,
        expected_generation: int,
    ) -> bool:
        """Persist the exact hook claim correlated to the current wake fence."""
        if (
            not self._valid(
                recipient_endpoint_id, delivery_id, session_ref, container_ref
            )
            or type(attempts) is not int
            or attempts < 1
            or type(expected_generation) is not int
            or expected_generation < 1
        ):
            return False
        with self._lock:
            self._refresh()
            current = self._reservations.get(recipient_endpoint_id)
            if (
                current is None
                or current.delivery_id != delivery_id
                or current.session_ref != session_ref
                or current.container_ref != container_ref
                or current.generation != expected_generation
                or current.correlated_claim_attempts not in (None, attempts)
            ):
                return False
            if self._relay is not None:
                return self._transition("correlate", reservation=current, attempts=attempts) is not None
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
            self._refresh()
            if self._reservations.get(reservation.recipient_endpoint_id) != reservation:
                return None
            if self._relay is not None:
                return self._transition("replace", reservation=reservation, values={
                    "session_ref": session_ref, "container_ref": container_ref,
                })
            self._generation += 1
            replacement = replace(
                reservation,
                session_ref=session_ref,
                container_ref=container_ref,
                generation=self._generation,
                outcome="prepared",
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
            if self._relay is not None:
                return self._transition("release", reservations=reservations) or ()
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
            self._refresh()
            match = next((item for item in self._reservations.values() if item.delivery_id == delivery_id), None)
            if self._relay is not None:
                return match if match is not None and self.release_generation(match) else None
            if match is None or not self._remove_locked(match.recipient_endpoint_id):
                return None
            return match

    def reserved(self, recipient_endpoint_id: str) -> bool:
        with self._lock:
            self._refresh()
            return recipient_endpoint_id in self._reservations or not self._usable

    def snapshot(self, recipient_endpoint_id: str) -> CodexWakeReservation | None:
        with self._lock:
            self._refresh()
            return self._reservations.get(recipient_endpoint_id)

    def reservations(self) -> tuple[CodexWakeReservation, ...]:
        with self._lock:
            self._refresh()
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
        try:
            with self._path.open(encoding="utf-8") as source:
                encoded = source.read(MAX_LEGACY_JSON_CHARACTERS + 1)
            if len(encoded) > MAX_LEGACY_JSON_CHARACTERS:
                raise ValueError
            raw = json.loads(encoded)
            if not isinstance(raw, dict):
                raise ValueError
            version = raw.get("version")
            items = raw["reservations"]
            if type(version) is not int or version not in {1, 2} or not isinstance(items, list) or len(items) > MAX_RESERVATIONS:
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
                    not self._valid_item(item)
                    or
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
        except FileNotFoundError:
            return
        except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
            self._usable = False
            self._reservations = {}

    def _write_locked(self, reservations: dict[str, CodexWakeReservation]) -> bool:
        # Ephemeral registries have no persistence side effects.
        return self._path is None and self._relay is None
