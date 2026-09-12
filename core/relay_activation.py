"""Bounded, side-effect-free Relay activation contract."""

from __future__ import annotations

from dataclasses import dataclass
import re
import sys
from typing import Literal

ActivationOutcome = Literal["accepted", "deferred", "uncertain", "failed"]
ActivationEvidence = Literal["submission_attempted", "transport_accepted", "payload_admitted"]
_OUTCOMES = {"accepted", "deferred", "uncertain", "failed"}
_EVIDENCE = {"submission_attempted", "transport_accepted", "payload_admitted"}
_ENDPOINT_RE = re.compile(r"^relay-session-[0-9a-f]{32}$")


@dataclass(frozen=True)
class ActivationAttemptResult:
    outcome: ActivationOutcome
    reason: str
    evidence: tuple[ActivationEvidence, ...] = ()
    native_retry_safe: bool = False
    destination_health_update: Literal["unreachable"] | None = None

    def __post_init__(self) -> None:
        if (
            self.outcome not in _OUTCOMES
            or not isinstance(self.reason, str)
            or not 0 < len(self.reason) <= 128
            or not self.reason.isprintable()
            or len(set(self.evidence)) != len(self.evidence)
            or any(value not in _EVIDENCE for value in self.evidence)
            or self.destination_health_update not in {None, "unreachable"}
        ):
            raise ValueError("invalid activation attempt result")


def current_platform() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "macos"
    return "other"


def _coherent(row: dict[str, object], names: tuple[str, ...]) -> tuple[object, bool]:
    values = [row[name] for name in names if row.get(name) is not None]
    return (values[0] if values else None, len({str(value) for value in values}) <= 1)


def relay_activation_snapshot(
    session: object,
    *,
    platform: str,
    claude_state: str | None = None,
    codex_reserved: bool = False,
) -> dict[str, object]:
    """Project current facts without probing, claiming, or optimistic inference."""
    row = session if isinstance(session, dict) else {}
    runtime, runtime_ok = _coherent(row, ("runtime", "recipient_runtime"))
    endpoint_names = ("recipient_endpoint_id", "endpoint_id") if row.get("recipient_endpoint_id") is not None else ("endpoint_id", "id")
    endpoint_id, endpoint_ok = _coherent(row, endpoint_names)
    session_ref, session_ok = _coherent(row, ("session_ref", "recipient_session_ref"))
    container_ref, container_ok = _coherent(row, ("container_ref", "recipient_container_ref"))
    runtime = runtime if runtime in {"codex", "claude-code", "opencode"} else "unknown"
    platform = platform if platform in {"windows", "linux", "macos", "other"} else "unknown"

    state = row.get("state")
    lifecycle = row.get("lifecycle")
    state_conflict = (
        state == "closed" and lifecycle not in {None, "closed"}
    ) or (
        lifecycle == "closed" and state not in {None, "closed"}
    )
    closed = state == "closed" or lifecycle == "closed"
    stale = state == "dormant" or lifecycle == "dormant"
    identity_ok = (
        runtime_ok and endpoint_ok and session_ok and container_ok
        and runtime != "unknown"
        and isinstance(endpoint_id, str)
        and bool(_ENDPOINT_RE.fullmatch(endpoint_id))
        and isinstance(session_ref, str)
        and 0 < len(session_ref) <= 512
        and session_ref.isprintable()
        and isinstance(container_ref, str)
        and 0 < len(container_ref) <= 512
        and container_ref.isprintable()
        and not state_conflict
    )
    topology = "existing_session" if identity_ok else "unknown"
    qualified = identity_ok and not closed and not stale and runtime in {"codex", "claude-code"} and platform in {"windows", "linux"}

    if runtime == "codex":
        integration, behavior = "codex_queue", "busy_queue" if qualified else "passive"
    elif runtime == "claude-code":
        integration, behavior = "claude_peer", "idle_wake" if qualified else "passive"
    elif runtime == "opencode":
        integration, behavior = "hook_only", "passive"
    else:
        integration, behavior = "unknown", "unknown"

    if not identity_ok or closed or stale or platform == "unknown":
        qualification, qualification_source = "unknown", "none"
        fallback = "unknown"
        evidence: list[str] = []
    elif qualified:
        qualification, qualification_source = "qualified", "installed_witness"
        fallback = "next_natural_turn"
        evidence = ["submission_attempted", "transport_accepted", "payload_admitted"]
    else:
        qualification, qualification_source = "unqualified", "documented_fallback"
        fallback = "next_natural_turn"
        evidence = ["payload_admitted"]

    health = row.get("destination_health")
    if closed:
        availability, availability_source = "closed", "lifecycle"
    elif not identity_ok or stale:
        availability, availability_source = "unknown", "none"
    elif (
        runtime == "claude-code"
        and qualified
        and claude_state in {"idle", "busy", "wake_inflight", "unreachable"}
    ):
        if health == "unreachable" and claude_state != "unreachable":
            availability, availability_source = "unknown", "none"
        else:
            availability = {
                "idle": "ready",
                "busy": "busy",
                "wake_inflight": "attempt_inflight",
                "unreachable": "unreachable",
            }[claude_state]
            availability_source = "durable_reservation" if claude_state == "wake_inflight" else "runtime_registration"
    elif runtime == "codex" and qualified and codex_reserved:
        availability, availability_source = "attempt_inflight", "durable_reservation"
    elif health == "unreachable":
        availability, availability_source = "unreachable", "endpoint_health"
    else:
        availability, availability_source = "unknown", "none"

    return {
        "contract": "relay-activation/v1",
        "runtime": runtime,
        "platform": platform,
        "integration": integration,
        "topology": topology,
        "behavior": behavior,
        "qualification": qualification,
        "qualification_source": qualification_source,
        "availability": availability,
        "availability_source": availability_source,
        "fallback": fallback,
        "supported_evidence": evidence,
    }