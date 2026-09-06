"""Best-effort Codex wake adapter for persisted Relay deliveries."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal


_ACTIVE_WRITER = "already has an active writer"
_ACTIVE_WRITER_CODE = "(code -32600)"
_DEBOUNCE_SECONDS = 1.0
_TIMEOUT_SECONDS = 300
_QUEUE_TIMEOUT_SECONDS = 30
_RETRY_SECONDS = 30.0
_LaunchOutcome = Literal["exec_completed", "queued", "ambiguous", "failed"]
_WakeKey = tuple[str, str, str]
_scheduled_delivery_ids: set[str] = set()
_scheduled_session_generations: dict[_WakeKey, int] = {}
_generation_counter = 0
_scheduled_session_delivery_ids: dict[_WakeKey, str] = {}
_scheduled_session_retry_at: dict[_WakeKey, float] = {}
_scheduled_lock = threading.Lock()
logger = logging.getLogger(__name__)


def schedule_codex_relay_wake(
    result: object,
    scope: object,
    *,
    on_unreachable: Callable[[datetime], None] | None = None,
) -> None:
    """Start one hidden notification attempt for one exact Codex delivery."""
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
    # Only wake for work still awaiting a turn; replies/already-delivered records do not trigger Codex.
    if delivery.get("state") != "pending":
        return
    delivery_id = delivery.get("delivery_id")
    session_ref = delivery.get("recipient_session_ref")
    recipient = result.get("recipient")
    container_ref = scope.get("container_ref")
    actor_ref = scope.get("actor_ref")
    selector = recipient.removeprefix("codex:") if isinstance(recipient, str) else ""
    valid_selector = selector == session_ref or bool(
        re.fullmatch(r"@[a-z0-9][a-z0-9_-]{0,31}", selector)
    )
    if (
        delivery.get("recipient_runtime") != "codex"
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
    wake_key = (session_ref, container_ref, actor_ref)
    with _scheduled_lock:
        if wake_key in _scheduled_session_generations:
            retry_at = _scheduled_session_retry_at.get(wake_key)
            if retry_at is None or time.monotonic() < retry_at:
                return
            # The persisted recovery sweep owns retries; retain the oldest trigger.
            delivery_id = _scheduled_session_delivery_ids[wake_key]
            _scheduled_session_retry_at.pop(wake_key, None)
        else:
            if delivery_id in _scheduled_delivery_ids:
                return
            _scheduled_delivery_ids.add(delivery_id)
            _scheduled_session_delivery_ids[wake_key] = delivery_id
        global _generation_counter
        _generation_counter += 1
        generation = _generation_counter
        _scheduled_session_generations[wake_key] = generation
    try:
        threading.Thread(
            target=_wake_after_debounce,
            args=(delivery_id, wake_key, generation, on_unreachable),
            daemon=True,
        ).start()
    except RuntimeError:
        with _scheduled_lock:
            if _scheduled_session_generations.get(wake_key) == generation:
                _clear_schedule_locked(wake_key)
            else:
                _scheduled_delivery_ids.discard(delivery_id)


def _clear_schedule_locked(wake_key: _WakeKey) -> None:
    _scheduled_session_generations.pop(wake_key, None)
    delivery_id = _scheduled_session_delivery_ids.pop(wake_key, None)
    _scheduled_session_retry_at.pop(wake_key, None)
    if delivery_id is not None:
        _scheduled_delivery_ids.discard(delivery_id)


def _wake_after_debounce(
    delivery_id: str,
    wake_key: _WakeKey,
    generation: int,
    on_unreachable: Callable[[datetime], None] | None = None,
) -> None:
    time.sleep(_DEBOUNCE_SECONDS)
    with _scheduled_lock:
        if _scheduled_session_generations.get(wake_key) != generation:
            _scheduled_delivery_ids.discard(delivery_id)
            return
    attempt_started_at = datetime.now(timezone.utc)
    started = time.monotonic()
    try:
        outcome = _wake(wake_key[0])
    except Exception:
        outcome = "failed"
    logger.info(
        "codex_relay_wake outcome=%s latency_ms=%d",
        outcome,
        int((time.monotonic() - started) * 1000),
    )
    if outcome in {"queued", "ambiguous"}:
        with _scheduled_lock:
            if _scheduled_session_generations.get(wake_key) == generation:
                _scheduled_session_retry_at[wake_key] = time.monotonic() + _RETRY_SECONDS
        logger.info(
            "codex_relay_wake outcome=retry_scheduled delay_seconds=%d",
            int(_RETRY_SECONDS),
        )
        return
    with _scheduled_lock:
        if _scheduled_session_generations.get(wake_key) != generation:
            return
        _clear_schedule_locked(wake_key)
    if on_unreachable is not None:
        try:
            on_unreachable(attempt_started_at)
        except Exception:
            logger.exception("codex_relay_wake unreachable callback failed")


def _wake(session_ref: str) -> _LaunchOutcome:
    # UserPromptSubmit claims persisted Relay only after this turn is admitted.
    return _launch(session_ref, _wake_prompt())


def mark_codex_relay_wake_admitted(
    session_ref: str,
    container_ref: str,
    actor_ref: str,
) -> None:
    with _scheduled_lock:
        _clear_schedule_locked((session_ref, container_ref, actor_ref))


def _launch(session_ref: str, prompt: str) -> _LaunchOutcome:
    codex_executable = _codex_executable()
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
            input=prompt,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            timeout=_TIMEOUT_SECONDS,
            **_hidden_process_kwargs(),
        )
    except subprocess.TimeoutExpired:
        return "ambiguous"
    except (OSError, ValueError):
        return "failed"
    if completed.returncode == 0:
        return "exec_completed"
    if not _is_active_writer(completed):
        return "failed"
    try:
        queued = subprocess.run(
            [
                codex_executable,
                "queue",
                "--profile",
                "pallium-relay",
                "--thread",
                session_ref,
                "--message",
                prompt,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            timeout=_QUEUE_TIMEOUT_SECONDS,
            **_hidden_process_kwargs(),
        )
    except subprocess.TimeoutExpired:
        # The queue write may already be durable. Native queue deduplication is false,
        # so retain ownership until the target hook proves admission.
        return "ambiguous"
    except (OSError, ValueError):
        return "failed"
    return "queued" if queued.returncode == 0 else "failed"

def _is_active_writer(completed: subprocess.CompletedProcess[str]) -> bool:
    stderr = completed.stderr or ""
    return (
        completed.returncode == 1
        and _ACTIVE_WRITER in stderr
        and _ACTIVE_WRITER_CODE in stderr
    )


def _wake_prompt() -> str:
    return (
        "Pallium Relay wake: a persisted delivery may be pending. "
        "The installed UserPromptSubmit hook will claim and inject it for this turn."
    )


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