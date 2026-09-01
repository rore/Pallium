"""Best-effort Codex wake adapter for persisted Relay deliveries."""

from __future__ import annotations

import os
import subprocess
import threading


_NOTICE = "Pallium Relay message pending."
_ACTIVE_WRITER = "already has an active writer"
_ACTIVE_WRITER_CODE = "(code -32600)"
_TIMEOUT_SECONDS = 15
_scheduled_delivery_ids: set[str] = set()
_scheduled_lock = threading.Lock()


def schedule_codex_relay_wake(result: object) -> None:
    """Start one hidden notification attempt for one exact Codex delivery."""
    if not isinstance(result, dict):
        return
    deliveries = result.get("deliveries")
    if (
        not isinstance(deliveries, list)
        or len(deliveries) != 1
        or not isinstance(deliveries[0], dict)
    ):
        return
    delivery = deliveries[0]
    delivery_id = delivery.get("delivery_id")
    session_ref = delivery.get("recipient_session_ref")
    if (
        delivery.get("recipient_runtime") != "codex"
        or not isinstance(delivery_id, str)
        or not delivery_id
        or not isinstance(session_ref, str)
        or not session_ref
        or session_ref != session_ref.strip()
        or not session_ref.isprintable()
    ):
        return
    with _scheduled_lock:
        if delivery_id in _scheduled_delivery_ids:
            return
        _scheduled_delivery_ids.add(delivery_id)
    try:
        threading.Thread(target=_wake, args=(session_ref,), daemon=True).start()
    except RuntimeError:
        pass


def _wake(session_ref: str) -> None:
    try:
        completed = subprocess.run(
            [
                "codex.exe" if os.name == "nt" else "codex",
                "exec",
                "--profile",
                "pallium-relay",
                "resume",
                session_ref,
                "-",
                "--json",
            ],
            input=_NOTICE,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            **_hidden_process_kwargs(),
        )
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return
    if _is_active_writer(completed):
        _queue(session_ref)


def _is_active_writer(completed: subprocess.CompletedProcess[str]) -> bool:
    stderr = completed.stderr or ""
    return _ACTIVE_WRITER in stderr and _ACTIVE_WRITER_CODE in stderr


def _queue(session_ref: str) -> None:
    try:
        subprocess.Popen(
            [
                "codex.exe" if os.name == "nt" else "codex",
                "queue",
                "--thread",
                session_ref,
                "--message",
                _NOTICE,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **_hidden_process_kwargs(),
        )
    except (OSError, ValueError):
        pass


def _hidden_process_kwargs() -> dict[str, object]:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {"start_new_session": True}