"""Best-effort Claude Code wake adapter for persisted Relay deliveries."""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import TYPE_CHECKING

from app.claude_wake_transport import claude_wake_transport

if TYPE_CHECKING:
    from core.claude_wake import ClaudeWakeRegistry


logger = logging.getLogger(__name__)
_workers: set[tuple[int, str]] = set()
_workers_lock = threading.Lock()


def schedule_claude_relay_wake(
    result: object,
    scope: object,
    *,
    registry: ClaudeWakeRegistry,
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
        try:
            try:
                triggered = registry.probe(
                    runtime="claude-code",
                    session_ref=session_ref,
                    container_ref=container_ref,
                    actor_ref=actor_ref,
                    transport=claude_wake_transport,
                )
                category = "trigger_written" if triggered else "not_triggered"
            except Exception:
                category = "worker_error"
            logger.info(
                "claude_relay_wake outcome delivery_id=%s session_ref=%s category=%s latency_ms=%d",
                delivery_id,
                session_ref,
                category,
                int((time.monotonic() - started) * 1000),
            )
        finally:
            with _workers_lock:
                _workers.discard(key)
    # ponytail: module-local coalescing; add persistence only if cold wake is required.
    worker = threading.Thread(target=run, name="pallium-claude-wake", daemon=True)
    try:
        worker.start()
    except Exception:
        with _workers_lock:
            _workers.discard(key)
        raise
    return worker
