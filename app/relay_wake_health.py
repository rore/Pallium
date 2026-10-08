"""Observational Codex scheduling health, not recipient reachability."""
from datetime import datetime, timezone
from threading import Event, Thread

from app.codex_bridge_pipe import RetainedService
from app.claude_wake import ClaudeWakeReconciler
from core.relay import RelayService

_ENROLLMENT_FAILURE_STAGES = {"register", "maintenance", "reopen", "state-read", "owner-result"}
_ENROLLMENT_FAILURE_REASONS = {
    "busy", "deadline", "file-unavailable", "file-write-failed", "invalid-message", "invalid-path",
    "invalid-policy", "invalid-policy-lock", "invalid-response", "message-limit", "native-failed",
    "native-tool-failed", "path-unavailable", "peer-gone", "peer-mismatch", "peer-unavailable",
    "policy-busy", "policy-changed", "policy-inactive", "stopped", "timeout", "transport-failed",
    "unsafe-acl", "unsafe-owner", "unsafe-path", "unsupported-acl",
}


def _native_enrollment_health(retained_service: object) -> dict:
    unavailable = {
        "state": "unavailable", "evidence": "unavailable", "observed_at": None,
        "accepted": None, "registration_remembered": None, "custody_present": None,
        "unresolved_handles": None, "continuity_opted_in": None,
        "last_failure_stage": None, "last_failure_reason": None,
    }
    if retained_service is None:
        unavailable["reason"] = "service_missing"
        return unavailable
    if type(retained_service) is not RetainedService:
        unavailable["reason"] = "snapshot_unavailable"
        return unavailable
    try:
        value = RetainedService.enrollment_diagnostics(retained_service)
        keys = {
            "observed_at", "accepted", "registration_remembered", "custody_present",
            "unresolved_handles", "continuity_opted_in", "last_failure_stage", "last_failure_reason",
        }
        if type(value) is not dict or set(value) != keys:
            raise ValueError
        observed_at = value["observed_at"]
        if type(observed_at) is not str or len(observed_at) > 64:
            raise ValueError
        datetime.fromisoformat(observed_at)
        booleans = ("accepted", "registration_remembered", "custody_present",
                    "unresolved_handles", "continuity_opted_in")
        if any(type(value[name]) is not bool for name in booleans):
            raise ValueError
        stage, reason = value["last_failure_stage"], value["last_failure_reason"]
        if ((stage is None) != (reason is None) or
                (stage is not None and (type(stage) is not str or type(reason) is not str
                 or len(stage) > 24 or len(reason) > 32
                 or stage not in _ENROLLMENT_FAILURE_STAGES
                 or reason not in _ENROLLMENT_FAILURE_REASONS))):
            raise ValueError
        accepted = value["accepted"]
        remembered = value["registration_remembered"]
        custody = value["custody_present"]
        unresolved = value["unresolved_handles"]
        if remembered and not accepted:
            raise ValueError
        state = ("unresolved_handles" if unresolved else
                 "never_registered" if not accepted else
                 "registered" if remembered and custody else
                 "retained_disconnected" if remembered else
                 "authority_cleared" if custody else "released")
        return {
            "state": state, "evidence": "cached_lifecycle_observation", "observed_at": observed_at,
            **{name: value[name] for name in booleans},
            "last_failure_stage": stage, "last_failure_reason": reason,
        }
    except Exception:
        unavailable["reason"] = "snapshot_unavailable"
        return unavailable


def relay_wake_health(relay_service: RelayService | None, reconciler: object,
                      retained_service: object = None) -> dict:
    observed_at = datetime.now(timezone.utc)
    running = None
    if isinstance(reconciler, ClaudeWakeReconciler):
        thread, stop = reconciler._thread, reconciler._stop
        if isinstance(stop, Event) and (thread is None or isinstance(thread, Thread)):
            running = bool(callable(reconciler._claim_recovery) and thread is not None
                           and thread.is_alive() and not stop.is_set())
    snapshot = {
        "authority_initialized": None, "reservations": None,
        "eligible_pending_count": None, "oldest_pending_age_seconds": None,
        "pending_evidence": "unavailable", "unresolved_uncertain_count": None,
        "uncertainty_evidence": "unavailable", "uncertainty_reason": "evidence_incomplete",
    }
    try:
        if relay_service is not None:
            snapshot = relay_service.codex_wake_health(now=observed_at)
    except Exception:
        pass  # Fixed unavailable evidence; no SQL, paths, payloads or raw errors.
    initialized = snapshot["authority_initialized"]
    state, reason = (
        ("unknown", "authority_unavailable") if initialized is None else
        ("degraded", "authority_uninitialized") if not initialized else
        ("unknown", "recovery_unobserved") if running is None else
        ("degraded", "recovery_not_running") if not running else
        ("usable", "recovery_running")
    )
    return {
        "assessment": "codex_scheduling_only", "state": state, "reason": reason,
        "observed_at": observed_at.isoformat(), "recovery_running": running,
        **snapshot,
        "last_recovery_progress_at": None, "recovery_progress_evidence": "not_recorded",
        "trace_loss_count": None, "trace_loss_evidence": "not_recorded",
        "native_enrollment": _native_enrollment_health(retained_service),
    }
