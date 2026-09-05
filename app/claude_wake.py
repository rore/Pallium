"""Best-effort Claude Code wake adapter for persisted Relay deliveries."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import re
import threading
import time
from typing import TYPE_CHECKING, Any, Callable

from app.claude_wake_transport import claude_wake_transport

if TYPE_CHECKING:
    from core.claude_wake import ClaudeWakeRegistry


logger = logging.getLogger(__name__)
_workers: set[tuple[int, str]] = set()
_workers_lock = threading.Lock()


def _log_outcome(delivery_id: str, session_ref: str, category: str, started: float) -> None:
    try:
        logger.info(
            "claude_relay_wake outcome delivery_id=%s session_ref=%s category=%s latency_ms=%d",
            delivery_id,
            session_ref,
            category,
            int((time.monotonic() - started) * 1000),
        )
    except Exception:
        pass


def schedule_claude_relay_wake(
    result: object,
    scope: object,
    *,
    registry: ClaudeWakeRegistry,
    on_unreachable: Callable[[datetime], None] | None = None,
) -> threading.Thread | None:
    """Schedule one bounded wake for a pending Claude delivery."""
    if not isinstance(result, dict) or not isinstance(scope, dict):
        return None
    deliveries = result.get("deliveries")
    if (
        not isinstance(deliveries, list)
        or len(deliveries) != 1
        or not isinstance(deliveries[0], dict)
    ):
        return None
    delivery = deliveries[0]
    if delivery.get("state") != "pending":
        return None
    delivery_id = delivery.get("delivery_id")
    session_ref = delivery.get("recipient_session_ref")
    recipient = result.get("recipient")
    container_ref = scope.get("container_ref")
    actor_ref = scope.get("actor_ref")
    selector = recipient.removeprefix("claude-code:") if isinstance(recipient, str) else ""
    valid_selector = selector == session_ref or bool(
        re.fullmatch(r"@[a-z0-9][a-z0-9_-]{0,31}", selector)
    )
    if (
        delivery.get("recipient_runtime") != "claude-code"
        or not isinstance(delivery_id, str)
        or not delivery_id
        or not isinstance(session_ref, str)
        or not session_ref
        or session_ref != session_ref.strip()
        or not session_ref.isprintable()
        or not isinstance(container_ref, str)
        or not container_ref
        or not isinstance(actor_ref, str)
        or not actor_ref
        or not valid_selector
    ):
        return None

    key = (id(registry), session_ref)
    with _workers_lock:
        if key in _workers:
            return None
        _workers.add(key)

    def run() -> None:
        started = time.monotonic()
        attempt_started_at = datetime.now(timezone.utc)
        attempted = False
        try:
            def transport(socket_path: str, token: str) -> str:
                nonlocal attempted
                attempted = True
                return claude_wake_transport(socket_path, token)

            def notify_unreachable() -> None:
                if on_unreachable is None:
                    return
                try:
                    on_unreachable(attempt_started_at)
                except Exception:
                    logger.exception("claude_relay_wake unreachable callback failed")

            triggered = registry.probe(
                runtime="claude-code",
                session_ref=session_ref,
                container_ref=container_ref,
                actor_ref=actor_ref,
                transport=transport,
                delivery_id=delivery_id,
                on_unreachable=notify_unreachable,
            )
            category = "trigger_written" if triggered else (
                "transport_failed" if attempted else "not_eligible"
            )
        except Exception:
            category = "worker_error"
        finally:
            _log_outcome(delivery_id, session_ref, category, started)
            with _workers_lock:
                _workers.discard(key)

    # ponytail: module-local coalescing; add persistence only if cold wake is required.
    worker = threading.Thread(target=run, name="pallium-claude-wake", daemon=True)
    started = time.monotonic()
    try:
        worker.start()
    except Exception:
        with _workers_lock:
            _workers.discard(key)
        _log_outcome(delivery_id, session_ref, "worker_start_failed", started)
        return None
    return worker


def recover_claude_relay_wakes(registry: ClaudeWakeRegistry, relay_service: Any) -> None:
    """Read persisted exact-scope candidates and schedule only Relay-pending work."""
    registry.recover_intents()
    for candidate in registry.recovery_candidates():
        try:
            status = relay_service.pending_candidate(
                runtime="claude-code",
                session_ref=candidate["session_ref"],
                container_ref=candidate["container_ref"],
                actor_ref=candidate["actor_ref"],
                delivery_id=candidate["delivery_id"] if candidate["state"] == "wake_inflight" else None,
            )
        except Exception:
            continue
        if candidate["state"] == "wake_inflight":
            delivery_id = candidate["delivery_id"]
            if not isinstance(delivery_id, str):
                continue
            if not isinstance(status, dict) or status.get("state") != "pending":
                registry.clear_inflight(runtime="claude-code", session_ref=candidate["session_ref"], container_ref=candidate["container_ref"], actor_ref=candidate["actor_ref"], delivery_id=delivery_id)
                continue
            with _workers_lock:
                if (id(registry), candidate["session_ref"]) in _workers:
                    continue
            if not registry.rearm_inflight(runtime="claude-code", session_ref=candidate["session_ref"], container_ref=candidate["container_ref"], actor_ref=candidate["actor_ref"], delivery_id=delivery_id, grace_seconds=1.0):
                continue
        if not isinstance(status, dict) or status.get("state") != "pending":
            continue
        delivery_id = status.get("delivery_id")
        if not isinstance(delivery_id, str) or not delivery_id:
            continue
        schedule_claude_relay_wake(
            {
                "recipient": "claude-code:" + str(candidate["session_ref"]),
                "deliveries": [{
                    "delivery_id": delivery_id,
                    "state": "pending",
                    "recipient_runtime": "claude-code",
                    "recipient_session_ref": candidate["session_ref"],
                }],
            },
            {"container_ref": candidate["container_ref"], "actor_ref": candidate["actor_ref"]},
            registry=registry,
        )
class ClaudeWakeReconciler:
    """One app-local Event loop; no Relay claim or ACK path exists here."""

    def __init__(self, registry: ClaudeWakeRegistry, relay_service: Any, *, interval_seconds: float = 1.0) -> None:
        self._registry = registry
        self._relay_service = relay_service
        self._interval_seconds = interval_seconds
        self._event = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="pallium-claude-wake-reconcile", daemon=True)
            self._thread.start()
        self.signal()

    def signal(self) -> None:
        self._event.set()

    def stop(self) -> None:
        self._stop.set()
        self._event.set()
        if self._thread is not None:
            self._thread.join(timeout=self._interval_seconds + 1)

    def _run(self) -> None:
        while not self._stop.is_set():
            self._event.wait(timeout=self._interval_seconds)
            self._event.clear()
            if not self._stop.is_set():
                recover_claude_relay_wakes(self._registry, self._relay_service)

def start_claude_wake_reconciler(registry: ClaudeWakeRegistry, relay_service: Any) -> ClaudeWakeReconciler | None:
    if not registry.persistent:
        return None
    reconciler = ClaudeWakeReconciler(registry, relay_service)
    reconciler.start()
    return reconciler