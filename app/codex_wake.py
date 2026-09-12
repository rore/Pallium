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
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from core.codex_wake import CodexWakeRegistry, CodexWakeReservation
from core.relay_activation import ActivationAttemptResult


_DEBOUNCE_SECONDS = 1.0
_QUEUE_TIMEOUT_SECONDS = 30
_LaunchOutcome = Literal["queued", "ambiguous", "failed"]
_LaunchResult = tuple[_LaunchOutcome, str | None, int | None]
_LaunchStart = tuple[subprocess.Popen[str] | None, _LaunchResult | None]
_scheduled_delivery_ids: set[str] = set()
_scheduled_session_generations: dict[tuple[str, str], int] = {}
_scheduled_session_delivery_ids: dict[tuple[str, str], str] = {}
_scheduled_lock = threading.Lock()
_registry_lock = threading.Lock()
_default_registry: CodexWakeRegistry | None = None
_default_registry_dir: Path | None = None
logger = logging.getLogger(__name__)
_popen = subprocess.Popen


def get_codex_wake_registry(state_dir: Path | None = None) -> CodexWakeRegistry:
    """Return the one trusted-local registry owned by this service process."""
    target = state_dir or Path(
        os.environ.get(
            "PALLIUM_CODEX_WAKE_DIR",
            str(Path.home() / ".pallium" / "codex-wake"),
        )
    )
    global _default_registry, _default_registry_dir
    with _registry_lock:
        if _default_registry is None or _default_registry_dir != target:
            _default_registry = CodexWakeRegistry(target)
            _default_registry_dir = target
        return _default_registry


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
    relay_service: Any | None = None,
    registry: CodexWakeRegistry | None = None,
    on_unreachable: Callable[[datetime], None] | None = None,
) -> threading.Thread | None:
    """Reserve durably, then schedule one exact Codex native submission."""
    del on_unreachable
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
    container_ref = delivery.get("recipient_container_ref") or scope.get("container_ref")
    recipient = result.get("recipient")
    selector = recipient.removeprefix("codex:") if isinstance(recipient, str) else ""
    valid_selector = selector == session_ref or bool(
        re.fullmatch(r"@[a-z0-9][a-z0-9_-]{0,31}", selector)
    )
    if (
        delivery.get("recipient_runtime") != "codex"
        or not all(isinstance(value, str) and value for value in (
            delivery_id, endpoint_id, session_ref, container_ref,
        ))
        or session_ref != session_ref.strip()
        or not session_ref.isprintable()
        or not valid_selector
    ):
        return None

    registry = registry or get_codex_wake_registry()

    def still_pending() -> bool:
        if relay_service is None:
            return True
        candidate = relay_service.pending_candidate(
            runtime="codex",
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

    reservation = registry.reserve(
        recipient_endpoint_id=endpoint_id,
        delivery_id=delivery_id,
        session_ref=session_ref,
        container_ref=container_ref,
        still_pending=still_pending,
    )
    if reservation is None:
        return None

    wake_key = (session_ref, container_ref)
    with _scheduled_lock:
        _scheduled_delivery_ids.add(delivery_id)
        _scheduled_session_delivery_ids[wake_key] = delivery_id
        _scheduled_session_generations[wake_key] = reservation.generation
    worker = threading.Thread(
        target=_wake_after_debounce,
        args=(reservation, registry),
        daemon=True,
    )
    try:
        worker.start()
    except RuntimeError:
        if registry.release_generation(reservation):
            _clear_schedule(reservation)
        return None
    return worker


def _clear_schedule(reservation: CodexWakeReservation) -> None:
    wake_key = (reservation.session_ref, reservation.container_ref)
    with _scheduled_lock:
        if _scheduled_session_generations.get(wake_key) == reservation.generation:
            _scheduled_session_generations.pop(wake_key, None)
            _scheduled_session_delivery_ids.pop(wake_key, None)
        _scheduled_delivery_ids.discard(reservation.delivery_id)


def _wake_after_debounce(
    reservation: CodexWakeReservation,
    registry: CodexWakeRegistry,
) -> None:
    time.sleep(_DEBOUNCE_SECONDS)
    attempt_started = time.monotonic()

    def start() -> _LaunchStart:
        return _start_launch(reservation.session_ref, _wake_prompt())

    try:
        current, launch = registry.run_if_current(reservation, start)
    except Exception:
        current, launch = True, (
            None,
            ("ambiguous", "unexpected_error", None),
        )
    attempt = _attempt_from_launch(_finish_launch(launch)) if launch is not None else None
    if not current or attempt is None:
        _clear_schedule(reservation)
        return

    delivery_ref, session_fp, container_fp = relay_wake_log_refs(
        reservation.delivery_id,
        reservation.session_ref,
        reservation.container_ref,
    )
    logger.info(
        "codex_relay_wake delivery_ref=%s session_fp=%s container_fp=%s "
        "outcome=%s reason=%s latency_ms=%d",
        delivery_ref,
        session_fp,
        container_fp,
        attempt.outcome,
        attempt.reason,
        int((time.monotonic() - attempt_started) * 1000),
    )
    if attempt.outcome in {"accepted", "uncertain"}:
        registry.record_outcome(reservation, attempt.outcome)
        return
    if attempt.native_retry_safe and registry.release_generation(reservation):
        _clear_schedule(reservation)


def release_codex_relay_wake(
    delivery_id: str,
    *,
    registry: CodexWakeRegistry | None = None,
) -> bool:
    registry = registry or get_codex_wake_registry()
    released = registry.release_delivery(delivery_id)
    if released is None:
        return False
    _clear_schedule(released)
    return True


def mark_codex_relay_wake_admitted(
    session_ref: str,
    container_ref: str,
) -> None:
    """Compatibility no-op: turn observation is not payload admission."""
    del session_ref, container_ref

def _wake(session_ref: str) -> _LaunchResult:
    return _launch_result(session_ref, _wake_prompt())


def _launch(session_ref: str, prompt: str) -> _LaunchOutcome:
    return _launch_result(session_ref, prompt)[0]


def _launch_result(session_ref: str, prompt: str) -> _LaunchResult:
    return _finish_launch(_start_launch(session_ref, prompt))


def _start_launch(session_ref: str, prompt: str) -> _LaunchStart:
    cwd = _codex_home()
    if cwd is None:
        return None, ("failed", "invalid_codex_home", None)
    try:
        process = _popen(
            [
                _codex_executable(), "queue", "--profile", "pallium-relay",
                "--thread", session_ref, "--message", prompt,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            cwd=str(cwd),
            **_hidden_process_kwargs(),
        )
    except OSError:
        return None, ("failed", "os_error", None)
    except ValueError:
        return None, ("failed", "value_error", None)
    return process, None


def _finish_launch(start: _LaunchStart) -> _LaunchResult:
    process, immediate = start
    if immediate is not None:
        return immediate
    assert process is not None
    try:
        process.communicate(timeout=_QUEUE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
            process.communicate()
        except (OSError, ValueError):
            pass
        return "ambiguous", "timeout", None
    except (OSError, ValueError):
        return "ambiguous", "post_start_error", None
    if process.returncode == 0:
        return "queued", None, 0
    return "failed", "nonzero_exit", process.returncode


def _attempt_from_launch(result: _LaunchResult) -> ActivationAttemptResult:
    outcome, reason, _exit_code = result
    if outcome == "queued":
        return ActivationAttemptResult(
            "accepted", "queued",
            ("submission_attempted", "transport_accepted"),
        )
    if outcome == "ambiguous" or reason == "nonzero_exit":
        return ActivationAttemptResult(
            "uncertain", reason or "ambiguous", ("submission_attempted",),
        )
    if outcome == "failed" and reason in {
        "invalid_codex_home", "os_error", "value_error",
    }:
        return ActivationAttemptResult("deferred", reason, native_retry_safe=True)
    return ActivationAttemptResult(
        "uncertain", reason or "malformed_result", ("submission_attempted",),
    )

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