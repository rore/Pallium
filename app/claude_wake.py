"""Best-effort Claude Code wake adapter for persisted Relay deliveries."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.claude_wake_transport import claude_wake_transport

if TYPE_CHECKING:
    from core.claude_wake import ClaudeWakeRegistry


def schedule_claude_relay_wake(
    result: object,
    scope: object,
    *,
    registry: ClaudeWakeRegistry,
) -> None:
    """Probe a registered Claude Code session and wake it with the new message.

    Mirrors codex_wake.py guard/selector shape but inline (no thread).
    Credentials never leave the registry; transport only receives (socket_path, token).

    ponytail: inline probe, bounded by transport timeout; thread it only if socket stalls send.
    """
    if not isinstance(result, dict) or not isinstance(scope, dict):
        return
    deliveries = result.get("deliveries")
    if (
        not isinstance(deliveries, list)
        or len(deliveries) != 1
        or not isinstance(deliveries[0], dict)
    ):
        return
    delivery = deliveries[0]
    if delivery.get("state") != "pending":
        return
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
        return
    registry.probe(
        runtime="claude-code",
        session_ref=session_ref,
        container_ref=container_ref,
        actor_ref=actor_ref,
        transport=claude_wake_transport,
    )
