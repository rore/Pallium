"""Best-effort Codex wake adapter for persisted Relay deliveries."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path


_NOTICE = "Pallium Relay delivery pending. Process the attributed Relay messages injected by the turn hook. If none are present, stop without taking action."
_DEBOUNCE_SECONDS = 1.0
_ACTIVE_WRITER = "already has an active writer"
_ACTIVE_WRITER_CODE = "(code -32600)"
_TIMEOUT_SECONDS = 300
_scheduled_delivery_ids: set[str] = set()
_scheduled_session_generations: dict[str, int] = {}
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
    recipient = result.get("recipient")
    selector = recipient.removeprefix("codex:") if isinstance(recipient, str) else ""
    valid_selector = selector == session_ref or bool(re.fullmatch(r"@[a-z0-9][a-z0-9_-]{0,31}", selector))
    if (
        delivery.get("recipient_runtime") != "codex"
        or not isinstance(delivery_id, str)
        or not delivery_id
        or not isinstance(session_ref, str)
        or not session_ref
        or session_ref != session_ref.strip()
        or not session_ref.isprintable()
        or not valid_selector
    ):
        return
    with _scheduled_lock:
        if delivery_id in _scheduled_delivery_ids:
            return
        _scheduled_delivery_ids.add(delivery_id)
        generation = _scheduled_session_generations.get(session_ref, 0) + 1
        _scheduled_session_generations[session_ref] = generation
    try:
        threading.Thread(
            target=_wake_after_debounce,
            args=(delivery_id, session_ref, generation),
            daemon=True,
        ).start()
    except RuntimeError:
        with _scheduled_lock:
            _scheduled_delivery_ids.discard(delivery_id)
            if _scheduled_session_generations.get(session_ref) == generation:
                _scheduled_session_generations.pop(session_ref, None)


def _wake_after_debounce(delivery_id: str, session_ref: str, generation: int) -> None:
    time.sleep(_DEBOUNCE_SECONDS)
    with _scheduled_lock:
        if _scheduled_session_generations.get(session_ref) != generation:
            _scheduled_delivery_ids.discard(delivery_id)
            return
    try:
        _wake(delivery_id, session_ref)
    finally:
        with _scheduled_lock:
            _scheduled_delivery_ids.discard(delivery_id)
            if _scheduled_session_generations.get(session_ref) == generation:
                _scheduled_session_generations.pop(session_ref, None)


def _wake(delivery_id: str, session_ref: str) -> None:
    codex_executable = _codex_executable()
    try:
        try:
            completed = subprocess.run(
                [
                    codex_executable,
                    "exec",
                    "--profile",
                    "pallium-relay",
                    "resume",
                    session_ref,
                    "-",
                    "--json",
                ],
                input=_NOTICE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=_TIMEOUT_SECONDS,
                **_hidden_process_kwargs(),
            )
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return
        if _is_active_writer(completed):
            _queue(session_ref, codex_executable)
    finally:
        with _scheduled_lock:
            _scheduled_delivery_ids.discard(delivery_id)


def _is_active_writer(completed: subprocess.CompletedProcess[str]) -> bool:
    stderr = completed.stderr or ""
    return _ACTIVE_WRITER in stderr and _ACTIVE_WRITER_CODE in stderr


def _queue(session_ref: str, codex_executable: str) -> None:
    try:
        subprocess.Popen(
            [
                codex_executable,
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


def _codex_executable() -> str:
    command = "codex.exe" if os.name == "nt" else "codex"
    configured = os.environ.get("CODEX_CLI_PATH")
    if configured and Path(configured).is_file():
        return configured
    if found := shutil.which(command):
        return found
    if os.name == "nt" and (local_app_data := os.environ.get("LOCALAPPDATA")):
        candidates: list[tuple[int, Path]] = []
        for candidate in (Path(local_app_data) / "OpenAI" / "Codex" / "bin").glob("*/codex.exe"):
            try:
                if candidate.is_file():
                    candidates.append((candidate.stat().st_mtime_ns, candidate))
            except OSError:
                continue
        if candidates:
            return str(max(candidates, key=lambda item: (item[0], str(item[1])))[1])
    return command


def _hidden_process_kwargs() -> dict[str, object]:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {"start_new_session": True}