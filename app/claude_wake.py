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
    relay_service: Any | None = None,
    on_unreachable: Callable[[datetime], None] | None = None,
) -> threading.Thread | None:
    """Schedule one bounded wake for one exact pending Claude delivery."""
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
    endpoint_id = delivery.get("recipient_endpoint_id")
    session_ref = delivery.get("recipient_session_ref")
    recipient = result.get("recipient")
    container_ref = delivery.get("recipient_container_ref") or scope.get("container_ref")
    selector = recipient.removeprefix("claude-code:") if isinstance(recipient, str) else ""
    valid_selector = selector == session_ref or bool(
        re.fullmatch(r"@[a-z0-9][a-z0-9_-]{0,31}", selector)
    )
    if (
        delivery.get("recipient_runtime") != "claude-code"
        or not all(isinstance(value, str) and value for value in (
            delivery_id, endpoint_id, session_ref, container_ref,
        ))
        or session_ref != session_ref.strip()
        or not session_ref.isprintable()
        or not valid_selector
    ):
        return None

    key = (id(registry), endpoint_id)
    with _workers_lock:
        if key in _workers:
            return None
        _workers.add(key)

    def still_pending() -> bool:
        if relay_service is None:
            return True
        candidate = relay_service.pending_candidate(
            runtime="claude-code",
            session_ref=session_ref,
            container_ref=container_ref,
            delivery_id=delivery_id,
        )
        return (
            isinstance(candidate, dict)
            and candidate.get("delivery_id") == delivery_id
            and candidate.get("recipient_endpoint_id") == endpoint_id
            and candidate.get("state") == "pending"
        )

    def run() -> None:
        started = time.monotonic()
        attempt_started_at = datetime.now(timezone.utc)

        def notify_unreachable() -> None:
            if on_unreachable is None:
                return
            try:
                on_unreachable(attempt_started_at)
            except Exception:
                logger.exception("claude_relay_wake unreachable callback failed")
                raise

        try:
            attempt = registry.attempt(
                runtime="claude-code",
                session_ref=session_ref,
                container_ref=container_ref,
                transport=claude_wake_transport,
                delivery_id=delivery_id,
                recipient_endpoint_id=endpoint_id,
                still_pending=still_pending,
                on_unreachable=notify_unreachable,
            )
            category = attempt.outcome
        except Exception:
            category = "worker_error"
        finally:
            _log_outcome(delivery_id, session_ref, category, started)
            with _workers_lock:
                _workers.discard(key)

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
    """Schedule only idle capabilities; unresolved reservations stay fenced."""
    registry.recover_intents()
    for candidate in registry.recovery_candidates():
        if candidate["state"] == "wake_inflight":
            continue
        try:
            status = relay_service.pending_candidate(
                runtime="claude-code",
                session_ref=candidate["session_ref"],
                container_ref=candidate["container_ref"],
            )
        except Exception:
            continue
        if not isinstance(status, dict) or status.get("state") != "pending":
            continue
        delivery_id = status.get("delivery_id")
        endpoint_id = status.get("recipient_endpoint_id")
        if not all(isinstance(value, str) and value for value in (delivery_id, endpoint_id)):
            continue
        schedule_claude_relay_wake(
            {
                "recipient": "claude-code:" + str(candidate["session_ref"]),
                "deliveries": [{
                    "delivery_id": delivery_id,
                    "state": "pending",
                    "recipient_endpoint_id": endpoint_id,
                    "recipient_runtime": "claude-code",
                    "recipient_session_ref": candidate["session_ref"],
                    "recipient_container_ref": candidate["container_ref"],
                }],
            },
            {"container_ref": candidate["container_ref"]},
            registry=registry,
            relay_service=relay_service,
            on_unreachable=lambda attempt_started_at, candidate=candidate: relay_service.mark_unreachable(
                runtime="claude-code",
                session_ref=candidate["session_ref"],
                container_ref=candidate["container_ref"],
                attempt_started_at=attempt_started_at,
            ),
        )

_CLAIM_RECOVERY_INTERVAL_SECONDS = 30.0


class ClaudeWakeReconciler:
    """One app-local event loop for Claude capability and Relay claim recovery."""

    def __init__(
        self,
        registry: ClaudeWakeRegistry,
        relay_service: Any,
        *,
        claim_recovery: Callable[[], None] | None = None,
        interval_seconds: float = 1.0,
        claim_interval_seconds: float = _CLAIM_RECOVERY_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._registry = registry
        self._relay_service = relay_service
        self._claim_recovery = claim_recovery
        self._interval_seconds = interval_seconds
        self._claim_interval_seconds = claim_interval_seconds
        self._clock = clock
        self._next_claim_recovery = 0.0
        self._event = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(
                target=self._run,
                name="pallium-relay-wake-reconcile",
                daemon=True,
            )
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
            if self._stop.is_set():
                continue
            try:
                recover_claude_relay_wakes(self._registry, self._relay_service)
            except Exception:
                logger.exception("Claude wake reconciliation failed")
            now = self._clock()
            if self._claim_recovery is None or now < self._next_claim_recovery:
                continue
            self._next_claim_recovery = now + self._claim_interval_seconds
            try:
                self._claim_recovery()
            except Exception:
                logger.exception("Relay wake recovery sweep failed")


def start_claude_wake_reconciler(
    registry: ClaudeWakeRegistry,
    relay_service: Any,
    *,
    claim_recovery: Callable[[], None] | None = None,
) -> ClaudeWakeReconciler:
    # ponytail: reuse one service loop; split by runtime only if recovery workloads diverge.
    reconciler = ClaudeWakeReconciler(
        registry,
        relay_service,
        claim_recovery=claim_recovery,
    )
    reconciler.start()
    return reconciler
