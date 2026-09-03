"""Best-effort Claude Code wake adapter for persisted Relay deliveries."""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import TYPE_CHECKING, Any

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
        attempted = False
        try:
            def transport(socket_path: str, token: str) -> bool:
                nonlocal attempted
                attempted = True
                return claude_wake_transport(socket_path, token)

            triggered = registry.probe(
                runtime="claude-code",
                session_ref=session_ref,
                container_ref=container_ref,
                actor_ref=actor_ref,
                transport=transport,
                delivery_id=delivery_id,
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