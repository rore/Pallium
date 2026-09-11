"""Best-effort Codex wake adapter for persisted Relay deliveries."""

from __future__ import annotations

import hashlib
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


_DEBOUNCE_SECONDS = 1.0
_QUEUE_TIMEOUT_SECONDS = 30
_LaunchOutcome = Literal["queued", "ambiguous", "failed"]
_LaunchResult = tuple[_LaunchOutcome, str | None, int | None]
_WakeKey = tuple[str, str]
_scheduled_delivery_ids: set[str] = set()
_scheduled_session_generations: dict[_WakeKey, int] = {}
_generation_counter = 0
_scheduled_session_delivery_ids: dict[_WakeKey, str] = {}
_scheduled_lock = threading.Lock()
logger = logging.getLogger(__name__)


def relay_wake_log_refs(
    delivery_id: str,
    session_ref: str,
    container_ref: str,
) -> tuple[str, str, str]:
    """Return bounded, non-secret correlation values for local wake logs."""
    delivery_ref = (
        delivery_id
        if re.fullmatch(r"relay-delivery-[0-9a-f]{32}", delivery_id)
        else _log_fingerprint(delivery_id)
    )
    return (
        delivery_ref,
        _log_fingerprint(session_ref),
        _log_fingerprint(container_ref),
    )


def _log_fingerprint(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8", errors="surrogatepass")).hexdigest()[:16]
    return f"sha256:{digest}"


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
        or not valid_selector
    ):
        return
    wake_key = (session_ref, container_ref)
    with _scheduled_lock:
        if wake_key in _scheduled_session_generations:
            return
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
        launch_result = _wake(wake_key[0])
        if isinstance(launch_result, tuple):
            outcome, reason, exit_code = launch_result
        else:
            outcome, reason, exit_code = launch_result, None, None
    except Exception:
        outcome, reason, exit_code = "failed", "unexpected_error", None
    delivery_ref, session_fp, container_fp = relay_wake_log_refs(
        delivery_id, wake_key[0], wake_key[1]
    )
    logger.info(
        "codex_relay_wake delivery_ref=%s session_fp=%s container_fp=%s "
        "outcome=%s reason=%s exit_code=%s latency_ms=%d",
        delivery_ref,
        session_fp,
        container_fp,
        outcome,
        reason or "none",
        exit_code if exit_code is not None else "none",
        int((time.monotonic() - started) * 1000),
    )
    if outcome in {"queued", "ambiguous"}:
        # Native wake writes are not idempotent. Keep one generation reserved
        # until hook admission rather than creating duplicate queued turns.
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


def _wake(session_ref: str) -> _LaunchResult:
    # UserPromptSubmit claims persisted Relay only after this turn is admitted.
    return _launch_result(session_ref, _wake_prompt())


def mark_codex_relay_wake_admitted(
    session_ref: str,
    container_ref: str,
) -> None:
    with _scheduled_lock:
        _clear_schedule_locked((session_ref, container_ref))


def _launch(session_ref: str, prompt: str) -> _LaunchOutcome:
    return _launch_result(session_ref, prompt)[0]


def _launch_result(session_ref: str, prompt: str) -> _LaunchResult:
    cwd = _codex_home()
    if cwd is None:
        return "failed", "invalid_codex_home", None
    try:
        queued = subprocess.run(
            [
                _codex_executable(), "queue", "--profile", "pallium-relay",
                "--thread", session_ref, "--message", prompt,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            timeout=_QUEUE_TIMEOUT_SECONDS,
            cwd=str(cwd),
            **_hidden_process_kwargs(),
        )
    except subprocess.TimeoutExpired:
        # The native write may already be durable and is not idempotent.
        return "ambiguous", "timeout", None
    except OSError:
        return "failed", "os_error", None
    except ValueError:
        return "failed", "value_error", None
    if queued.returncode == 0:
        return "queued", None, 0
    return "failed", "nonzero_exit", queued.returncode


def _codex_home() -> Path | None:
    try:
        candidate = Path.home() / ".codex"
        if not _is_local_absolute_path(candidate):
            return None
        resolved = candidate.resolve()
        service_cwd = Path.cwd().resolve()
        if (
            not _is_local_absolute_path(resolved)
            or not resolved.is_dir()
            or resolved == service_cwd
            or service_cwd in resolved.parents
        ):
            return None
        return resolved
    except (OSError, RuntimeError, ValueError):
        return None


def _is_local_absolute_path(path: Path) -> bool:
    if not path.is_absolute() or os.name != "nt":
        return path.is_absolute()
    backslash = chr(92)
    value = str(path).replace("/", backslash)
    if value.startswith(backslash * 2):
        return False
    drive, _ = os.path.splitdrive(value)
    return bool(drive) and _windows_drive_is_local(drive)


def _windows_drive_is_local(drive: str) -> bool:
    try:
        import ctypes

        drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive + chr(92))
    except (AttributeError, OSError, ValueError):
        return False
    return drive_type not in {0, 1, 4}

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