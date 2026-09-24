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
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from core.codex_wake import CodexWakeRegistry, CodexWakeReservation
from core.relay import RelayNotFoundError
from core.relay_activation import ActivationAttemptResult


_DEBOUNCE_SECONDS = 1.0
_QUEUE_TIMEOUT_SECONDS = 30
_LaunchOutcome = Literal["queued", "ambiguous", "failed"]
_LaunchResult = tuple[_LaunchOutcome, str | None, int | None]
_LaunchStart = tuple[subprocess.Popen[str] | None, _LaunchResult | None]
_scheduled_delivery_ids: set[str] = set()
_scheduled_session_generations: dict[tuple[int, str, str], int] = {}
_scheduled_session_delivery_ids: dict[tuple[int, str, str], str] = {}
_scheduled_session_attempt_ids: dict[tuple[int, str, str], str] = {}
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


def get_codex_wake_registry_for_relay_database(relay_sqlite_url: str) -> CodexWakeRegistry:
    """Keep one Relay database's wake fences out of every other instance."""
    override = os.environ.get("PALLIUM_CODEX_WAKE_DIR")
    if override is not None:
        return get_codex_wake_registry(Path(override))
    if relay_sqlite_url == "sqlite:///:memory:":
        return CodexWakeRegistry()
    prefix = "sqlite:///"
    if not relay_sqlite_url.startswith(prefix):
        raise ValueError("Relay wake registry requires a SQLite database URL")
    relay_path = Path(relay_sqlite_url[len(prefix):]).resolve()
    if relay_path.parent.name == "data" and relay_path.name == "pallium-relay.db":
        state_dir = relay_path.parent.parent / "codex-wake"
    else:
        state_dir = relay_path.with_name(relay_path.name + "-codex-wake")
    return get_codex_wake_registry(state_dir)


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


def _reservation_state_is_stale(
    reservation: CodexWakeReservation, state: object
) -> bool:
    if not (
        isinstance(state, dict)
        and state.get("delivery_id") == reservation.delivery_id
        and state.get("recipient_endpoint_id") == reservation.recipient_endpoint_id
        and isinstance(state.get("state"), str)
    ):
        return False
    if state["state"] in {"delivered", "expired", "suppressed"}:
        return True
    return (
        state["state"] == "pending"
        and state.get("stored_state") == "claimed"
        and type(state.get("attempts")) is int
        and state["attempts"] > 0
        and (
            state["attempts"] == reservation.correlated_claim_attempts
            or (
                type(state.get("codex_wake_generation")) is int
                and state["codex_wake_generation"] == reservation.generation
            )
        )
    )



def reconcile_codex_relay_wake_reservations(
    relay_service: Any,
    *,
    registry: CodexWakeRegistry | None = None,
    reservations: tuple[CodexWakeReservation, ...] | None = None,
    trace_callback: Callable[[dict[str, object]], object] | None = None,
) -> int:
    """Remove terminal fences and atomically replace expired wake claims."""
    registry = registry or get_codex_wake_registry()
    candidates = registry.reservations() if reservations is None else reservations
    stale = []
    replaced = 0
    for reservation in candidates:
        if reservation.correlated_claim_attempts is None:
            try:
                state = relay_service.codex_wake_reservation_state(
                    delivery_id=reservation.delivery_id,
                )
            except RelayNotFoundError:
                stale.append(reservation)
                continue
            except Exception:
                continue
            if not _reservation_state_is_stale(reservation, state):
                continue
            if state["state"] in {"delivered", "expired", "suppressed"}:
                stale.append(reservation)
                continue

        def replace_if_stale(state: dict[str, object]) -> bool:
            if not _reservation_state_is_stale(reservation, state):
                return False
            if state["state"] in {"delivered", "expired", "suppressed"}:
                released = registry.release_generation(reservation)
                if released:
                    _clear_schedule(reservation, registry)
                return released
            wake_target = state.get("wake_target")
            if not (
                isinstance(wake_target, dict)
                and wake_target.get("runtime") == "codex"
                and isinstance(wake_target.get("session_ref"), str)
                and isinstance(wake_target.get("container_ref"), str)
            ):
                return False
            replacement = registry.replace_generation(
                reservation,
                session_ref=wake_target["session_ref"],
                container_ref=wake_target["container_ref"],
            )
            if replacement is None:
                return False
            _clear_schedule(reservation, registry)
            _schedule_reserved_codex_relay_wake(
                replacement, registry, trace_callback=trace_callback
            )
            return True

        try:
            if relay_service.reconcile_codex_wake_reservation(
                delivery_id=reservation.delivery_id,
                decision=replace_if_stale,
            ):
                replaced += 1
        except RelayNotFoundError:
            stale.append(reservation)
        except Exception:
            continue

    released = registry.release_generations(tuple(stale))
    for reservation in released:
        _clear_schedule(reservation, registry)
    reconciled = len(released) + replaced
    if reconciled:
        logger.info(
            "codex_relay_wake reconciled_stale_reservations=%d", reconciled
        )
    return reconciled

def _emit_trace(
    callback: Callable[[dict[str, object]], object] | None,
    attempt_id: str,
    delivery_id: str,
    endpoint_id: str,
    stage: str,
    result: ActivationAttemptResult | None = None,
) -> None:
    if callback is None:
        return
    event: dict[str, object] = {
        "attempt_id": attempt_id,
        "delivery_id": delivery_id,
        "stage": stage,
        "runtime": "codex",
        "recipient_endpoint_id": endpoint_id,
    }
    if result is not None:
        event.update(
            outcome=result.outcome,
            reason=result.reason,
            evidence=list(result.evidence),
            native_retry_safe=result.native_retry_safe,
            destination_health_update=result.destination_health_update,
        )
    try:
        callback(event)
    except Exception:
        logger.exception("codex relay trace callback failed")


def _restart_trace_attempt_id(
    relay_service: Any,
    retained: CodexWakeReservation,
    delivery: dict[str, object],
) -> str | None:
    """Return one retained uncertain attempt from complete exact-scope evidence."""
    if (
        retained.outcome != "uncertain"
        or retained.delivery_id == delivery.get("delivery_id")
        or delivery.get("recipient_runtime") != "codex"
        or delivery.get("recipient_endpoint_id") != retained.recipient_endpoint_id
        or delivery.get("recipient_session_ref") != retained.session_ref
        or delivery.get("recipient_container_ref") != retained.container_ref
    ):
        return None
    try:
        sessions = relay_service.list_sessions(
            container_ref=retained.container_ref,
            runtime="codex",
            session_ref=retained.session_ref,
            include_inactive=True,
        )
        trace = relay_service.trace_message(
            message_id=retained.delivery_id, limit=100
        )
    except Exception:
        return None
    if (
        not isinstance(sessions, list)
        or len(sessions) != 1
        or not isinstance(sessions[0], dict)
    ):
        return None
    current = sessions[0]
    if (
        current.get("endpoint_id") != retained.recipient_endpoint_id
        or current.get("runtime") != "codex"
        or current.get("session_ref") != retained.session_ref
        or current.get("container_ref") != retained.container_ref
        or type(current.get("scope_generation")) is not int
        or current["scope_generation"] != 0
    ):
        return None
    if (
        not isinstance(trace, dict)
        or trace.get("contract") != "relay-delivery-trace/v1"
        or any(
            trace.get(flag) is not False
            for flag in (
                "legacy", "absent", "gap", "truncated", "pruned", "has_more"
            )
        )
    ):
        return None
    snapshots = trace.get("delivery_snapshots")
    events = trace.get("events")
    if (
        not isinstance(snapshots, list)
        or len(snapshots) != 1
        or not isinstance(events, list)
    ):
        return None
    snapshot = snapshots[0]
    if (
        not isinstance(snapshot, dict)
        or snapshot.get("delivery_id") != retained.delivery_id
        or snapshot.get("recipient_runtime") != "codex"
        or snapshot.get("recipient_endpoint_id") != retained.recipient_endpoint_id
        or snapshot.get("recipient_session_ref") != retained.session_ref
        or snapshot.get("recipient_container_ref") != retained.container_ref
        or snapshot.get("state") not in {"pending", "claimed"}
    ):
        return None

    direct = [
        event
        for event in events
        if isinstance(event, dict)
        and event.get("delivery_id") == retained.delivery_id
        and event.get("shared") is False
    ]
    sequences = [event.get("sequence") for event in direct]
    if (
        not direct
        or any(type(sequence) is not int for sequence in sequences)
        or len(sequences) != len(set(sequences))
    ):
        return None
    activations = [
        event for event in direct if event.get("stage") in {"prepared", "completed"}
    ]
    if not activations:
        return None
    latest = max(activations, key=lambda event: event["sequence"])
    attempt_id = latest.get("attempt_id")
    prepared = [
        event
        for event in direct
        if event.get("stage") == "prepared"
        and event.get("attempt_id") == attempt_id
    ]
    if (
        latest.get("stage") != "completed"
        or not isinstance(attempt_id, str)
        or re.fullmatch(r"relay-activation-[0-9a-f]{32}", attempt_id) is None
        or latest.get("outcome") != "uncertain"
        or latest.get("native_retry_safe") is not False
        or len(prepared) != 1
        or prepared[0]["sequence"] >= latest["sequence"]
        or sum(
            event.get("stage") == "completed"
            and event.get("attempt_id") == attempt_id
            for event in direct
        )
        != 1
        or any(
            event.get("stage") == "associated"
            and event["sequence"] < latest["sequence"]
            for event in direct
        )
        or len([event for event in direct if event["sequence"] > latest["sequence"]]) > 1
        or any(
            event.get("stage") != "associated"
            or event.get("attempt_id") != attempt_id
            for event in direct
            if event["sequence"] > latest["sequence"]
        )
    ):
        return None
    return attempt_id

def _schedule_reserved_codex_relay_wake(
    reservation: CodexWakeReservation,
    registry: CodexWakeRegistry,
    *,
    trace_callback: Callable[[dict[str, object]], object] | None = None,
) -> threading.Thread | None:
    wake_key = (id(registry), reservation.session_ref, reservation.container_ref)
    attempt_id = f"relay-activation-{uuid.uuid4().hex}"
    with _scheduled_lock:
        _scheduled_delivery_ids.add(reservation.delivery_id)
        _scheduled_session_delivery_ids[wake_key] = reservation.delivery_id
        _scheduled_session_generations[wake_key] = reservation.generation
        _scheduled_session_attempt_ids[wake_key] = attempt_id
    _emit_trace(
        trace_callback, attempt_id, reservation.delivery_id,
        reservation.recipient_endpoint_id, "prepared",
    )
    worker = threading.Thread(
        target=_wake_after_debounce,
        args=(reservation, registry, attempt_id, trace_callback),
        daemon=True,
    )
    try:
        worker.start()
    except RuntimeError:
        if registry.release_generation(reservation):
            _clear_schedule(reservation, registry)
        _emit_trace(
            trace_callback, attempt_id, reservation.delivery_id,
            reservation.recipient_endpoint_id, "completed",
            ActivationAttemptResult(
                "deferred", "worker_start_failed", native_retry_safe=True
            ),
        )
        return None
    return worker


def schedule_codex_relay_wake(
    result: object,
    scope: object,
    *,
    relay_service: Any | None = None,
    registry: CodexWakeRegistry | None = None,
    on_unreachable: Callable[[datetime], None] | None = None,
    trace_callback: Callable[[dict[str, object]], object] | None = None,
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
    container_ref = delivery.get("recipient_container_ref") or scope.get(
        "container_ref"
    )
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

    wake_key = (id(registry), session_ref, container_ref)
    reservation = registry.reserve(
        recipient_endpoint_id=endpoint_id,
        delivery_id=delivery_id,
        session_ref=session_ref,
        container_ref=container_ref,
        still_pending=still_pending,
    )
    if reservation is None and relay_service is not None:
        existing = registry.snapshot(endpoint_id)
        if existing is not None:
            reconcile_codex_relay_wake_reservations(
                relay_service,
                registry=registry,
                reservations=(existing,),
                trace_callback=trace_callback,
            )
            if registry.snapshot(endpoint_id) is None:
                reservation = registry.reserve(
                    recipient_endpoint_id=endpoint_id,
                    delivery_id=delivery_id,
                    session_ref=session_ref,
                    container_ref=container_ref,
                    still_pending=still_pending,
                )
    if reservation is None:
        with _scheduled_lock:
            attempt_id = _scheduled_session_attempt_ids.get(wake_key)
        if attempt_id is not None:
            _emit_trace(
                trace_callback, attempt_id, delivery_id, endpoint_id,
                "associated",
            )
        elif relay_service is not None:
            retained = registry.snapshot(endpoint_id)
            if retained is not None:
                attempt_id = _restart_trace_attempt_id(
                    relay_service,
                    retained,
                    {**delivery, "recipient_container_ref": container_ref},
                )
                if attempt_id is not None:
                    _emit_trace(
                        trace_callback, attempt_id, delivery_id, endpoint_id,
                        "associated",
                    )
        return None

    return _schedule_reserved_codex_relay_wake(
        reservation, registry, trace_callback=trace_callback
    )

def _clear_schedule(reservation: CodexWakeReservation, registry: CodexWakeRegistry) -> None:
    wake_key = (id(registry), reservation.session_ref, reservation.container_ref)
    with _scheduled_lock:
        if _scheduled_session_generations.get(wake_key) == reservation.generation:
            _scheduled_session_generations.pop(wake_key, None)
            _scheduled_session_delivery_ids.pop(wake_key, None)
            _scheduled_session_attempt_ids.pop(wake_key, None)
        _scheduled_delivery_ids.discard(reservation.delivery_id)


def _wake_after_debounce(
    reservation: CodexWakeReservation,
    registry: CodexWakeRegistry,
    attempt_id: str | None = None,
    trace_callback: Callable[[dict[str, object]], object] | None = None,
) -> None:
    time.sleep(_DEBOUNCE_SECONDS)
    attempt_started = time.monotonic()

    def start() -> _LaunchStart:
        return _start_launch(
            reservation.session_ref, _wake_prompt(reservation.delivery_id)
        )

    try:
        current, launch = registry.run_if_current(reservation, start)
    except Exception:
        current, launch = True, (
            None,
            ("ambiguous", "unexpected_error", None),
        )
    launch_result = (
        _finish_launch(launch, delivery_id=reservation.delivery_id)
        if launch is not None else None
    )
    attempt = _attempt_from_launch(launch_result) if launch_result is not None else None
    if not current or attempt is None:
        _clear_schedule(reservation, registry)
        return

    delivery_ref, session_fp, container_fp = relay_wake_log_refs(
        reservation.delivery_id,
        reservation.session_ref,
        reservation.container_ref,
    )
    logger.info(
        "codex_relay_wake delivery_ref=%s session_fp=%s container_fp=%s "
        "outcome=%s reason=%s exit_code=%s latency_ms=%d",
        delivery_ref,
        session_fp,
        container_fp,
        attempt.outcome,
        attempt.reason,
        launch_result[2] if launch_result[2] is not None else "none",
        int((time.monotonic() - attempt_started) * 1000),
    )
    if attempt.outcome in {"accepted", "uncertain"}:
        registry.record_outcome(reservation, attempt.outcome)
    elif attempt.native_retry_safe and registry.release_generation(reservation):
        _clear_schedule(reservation, registry)
    if attempt_id is not None:
        _emit_trace(
            trace_callback, attempt_id, reservation.delivery_id,
            reservation.recipient_endpoint_id, "completed", attempt,
        )


def release_codex_relay_wake(
    delivery_id: str,
    *,
    registry: CodexWakeRegistry | None = None,
) -> bool:
    registry = registry or get_codex_wake_registry()
    released = registry.release_delivery(delivery_id)
    if released is None:
        return False
    _clear_schedule(released, registry)
    return True


def correlate_codex_relay_wake_claim(
    wake_delivery_id: str,
    session_ref: str,
    container_ref: str,
    turn_result: object,
    reservation: CodexWakeReservation | None,
    *,
    registry: CodexWakeRegistry | None = None,
) -> bool:
    """Correlate only the exact claimed delivery from a Codex wake turn."""
    if (
        re.fullmatch(r"relay-delivery-[0-9a-f]{32}", wake_delivery_id) is None
        or not isinstance(reservation, CodexWakeReservation)
        or reservation.delivery_id != wake_delivery_id
        or reservation.session_ref != session_ref
        or reservation.container_ref != container_ref
        or not isinstance(turn_result, dict)
    ):
        return False
    session = turn_result.get("session")
    deliveries = turn_result.get("deliveries")
    if not isinstance(session, dict) or not isinstance(deliveries, list):
        return False
    endpoint_id = session.get("endpoint_id")
    if not (
        session.get("runtime") == "codex"
        and session.get("session_ref") == session_ref
        and session.get("container_ref") == container_ref
        and isinstance(endpoint_id, str)
        and reservation.recipient_endpoint_id == endpoint_id
    ):
        return False
    matches = [
        delivery
        for delivery in deliveries
        if isinstance(delivery, dict)
        and delivery.get("delivery_id") == wake_delivery_id
        and delivery.get("state") == "claimed"
        and delivery.get("recipient_runtime") == "codex"
        and delivery.get("recipient_session_ref") == session_ref
        and delivery.get("recipient_endpoint_id") == endpoint_id
        and delivery.get("recipient_container_ref") == container_ref
        and type(delivery.get("attempts")) is int
        and delivery["attempts"] > 0
    ]
    if len(matches) != 1:
        return False
    registry = registry or get_codex_wake_registry()
    return registry.correlate_claim(
        delivery_id=wake_delivery_id,
        recipient_endpoint_id=endpoint_id,
        session_ref=session_ref,
        container_ref=container_ref,
        attempts=matches[0]["attempts"],
        expected_generation=reservation.generation,
    )


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
            errors="replace",
            cwd=str(cwd),
            **_hidden_process_kwargs(),
        )
    except OSError:
        return None, ("failed", "os_error", None)
    except ValueError:
        return None, ("failed", "value_error", None)
    return process, None


def _stderr_category(stderr: str | None) -> str:
    if not stderr:
        return "empty"
    sample = stderr[:2048].lower()
    if "usage:" in sample or "unexpected argument" in sample:
        return "cli_usage"
    if any(term in sample for term in ("thread not found", "unknown thread", "no such thread")):
        return "thread_unavailable"
    if any(term in sample for term in ("connection refused", "transport error", "timed out")):
        return "transport"
    return "other"


def _finish_launch(
    start: _LaunchStart, *, delivery_id: str | None = None,
) -> _LaunchResult:
    process, immediate = start
    if immediate is not None:
        return immediate
    assert process is not None

    def stop_and_reap() -> None:
        try:
            process.kill()
        except (OSError, ValueError):
            pass
        try:
            process.communicate(timeout=_QUEUE_TIMEOUT_SECONDS)
        except (subprocess.TimeoutExpired, OSError, ValueError):
            try:
                process.wait(timeout=_QUEUE_TIMEOUT_SECONDS)
            except (subprocess.TimeoutExpired, OSError, ValueError):
                pass

    try:
        _, stderr = process.communicate(timeout=_QUEUE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        stop_and_reap()
        return "ambiguous", "timeout", None
    except (OSError, ValueError):
        stop_and_reap()
        return "ambiguous", "post_start_error", None
    if process.returncode == 0:
        return "queued", None, 0
    if delivery_id is not None:
        delivery_ref = (
            delivery_id if re.fullmatch(r"relay-delivery-[0-9a-f]{32}", delivery_id)
            else _log_fingerprint(delivery_id)
        )
        logger.info(
            "codex_relay_wake_stderr delivery_ref=%s exit_code=%s category=%s",
            delivery_ref, process.returncode, _stderr_category(stderr),
        )
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


def _wake_prompt(delivery_id: str | None = None) -> str:
    legacy = (
        "Pallium Relay wake: a persisted delivery may be pending. "
        "The installed UserPromptSubmit hook will claim and inject it for this turn."
    )
    if not isinstance(delivery_id, str) or not re.fullmatch(
        r"relay-delivery-[0-9a-f]{32}", delivery_id
    ):
        return legacy
    return (
        f"Pallium Relay wake for {delivery_id}. If no [Pallium Relay message ...] "
        "block accompanies this turn, do not conclude the inbox is empty and do not "
        "call pallium_relay_receive or resend. Inspect this exact delivery with "
        "pallium_relay_trace by passing it as message_id."
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