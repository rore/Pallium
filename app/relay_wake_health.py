"""Observational Codex scheduling health, not recipient reachability."""
from datetime import datetime, timezone
from threading import Event, Thread

from app.claude_wake import ClaudeWakeReconciler
from core.relay import RelayService


def relay_wake_health(relay_service: RelayService | None, reconciler: object) -> dict:
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
    }
