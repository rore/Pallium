from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy.exc import OperationalError as SAOperationalError

_TRANSIENT_SQLITE_ERROR_SUBSTRINGS = (
    "disk i/o error",
    "database is locked",
    "database table is locked",
    "unable to open database file",
)


class ImmediateTransactionBusyError(RuntimeError):
    """A bounded SQLite immediate-transaction acquisition did not succeed."""

    ACQUISITION_STAGES = frozenset({
        "local_gate", "pre_attempt_deadline", "setup_deadline", "late_begin",
        "retry_exhausted", "backoff_no_fit",
    })

    def __init__(self, *args, acquisition_stage=None, acquisition_phase_ms=None):
        super().__init__(*args)
        self.acquisition_stage = acquisition_stage
        self.acquisition_phase_ms = acquisition_phase_ms


_relay_writer_operation = ContextVar("relay_writer_operation", default=None)
_RELAY_WRITER_OPERATIONS = frozenset({
    "ack", "activation_projection", "attach_work_ref", "begin_native_attempt",
    "close_session", "correlate", "detach_work_ref", "initialize", "list_sessions",
    "mark_active", "mcp_ack", "message_status", "message_trace", "name_session",
    "opencode_wake", "outcome", "pending_candidate", "reconcile", "release",
    "release_delivery", "replace", "reply", "reserve", "retry", "retry_target",
    "send", "session_work_refs", "turn", "work_ref_participant_counts",
    "work_ref_participants", "unknown",
})
_RELAY_TURN_SITES = frozenset({
    "body_setup", "scope_lookup", "expiry_update", "eligible_count",
    "candidate_execute", "candidate_fetch", "candidate_project",
    "claim_mutation", "final_flush", "final_check", "none",
})
_RELAY_EXPIRY_SITES = frozenset({
    "observer_setup", "orm", "autoflush", "cursor_envelope", "orm_return", "post_return", "none",
})
_RELAY_EXPIRY_FLAGS = frozenset({"flush_entered", "flush_returned", "cursor_entered", "cursor_returned"})
_RELAY_OPENCODE_VERBS = frozenset({"enroll", "poll", "detach", "admitted", "terminal", "context", "unknown"})
_RELAY_OPENCODE_SITES = frozenset({
    "body_setup", "binding", "state_update", "anchor_lookup", "candidate_execute",
    "candidate_fetch", "candidate_validate", "response", "none",
})
_RELAY_BODY_HOOK_STATES = frozenset({"not_reached", "ineligible", "valid", "invalid", "unknown"})


def _relay_opencode_verb(value):
    return value if type(value) is str and value in _RELAY_OPENCODE_VERBS else "unknown"


def _relay_turn_body_fields(value, *, allowed_sites=_RELAY_TURN_SITES):
    try:
        sites = ("current_site", "slowest_site")
        numbers = ("current_site_ms_lower_bound", "body_ms_lower_bound",
                   "holder_cpu_ms_through_sample", "cpu_sample_age_ms_lower_bound",
                   "slowest_site_ms_lower_bound", "slowest_site_cpu_ms_between_samples")
        if type(value) is not dict or set(value) != {"state", *sites, *numbers}:
            return "unknown"
        if type(value["state"]) is not str or value["state"] not in {"inflight", "complete", "exception"}:
            return "unknown"
        if any(type(value[key]) is not str or value[key] not in allowed_sites for key in sites):
            return "unknown"
        if any(not (type(value[key]) is int and 0 <= value[key] <= 604_800_000
                    or type(value[key]) is str and value[key] in {"unknown", "over_limit"}) for key in numbers):
            return "unknown"
        return {key: value[key] for key in sorted(value)}
    except BaseException:
        return "unknown"


def _relay_turn_body_view(body, now, *, allowed_sites=_RELAY_TURN_SITES):
    try:
        if type(body) is not dict or type(now) is not int:
            return "unknown"
        started, sampled, boundary = body["started_ns"], body["sampled_ns"], body["boundary_ns"]
        if any(type(value) is not int for value in (started, sampled, boundary)) or not 0 <= started <= boundary <= sampled <= now:
            return "unknown"
        def milliseconds(value):
            if value is None:
                return "unknown"
            if type(value) is not int or value < 0:
                raise ValueError("invalid diagnostic interval")
            result = value // 1_000_000
            return result if result <= 604_800_000 else "over_limit"
        cpu, origin = body["sample_cpu_ns"], body["cpu_started_ns"]
        if cpu is None or origin is None:
            cpu_elapsed = None
        elif type(cpu) is int and type(origin) is int and 0 <= origin <= cpu:
            cpu_elapsed = cpu-origin
        else:
            return "unknown"
        active = body["state"] == "inflight"
        return _relay_turn_body_fields({
            "state": body["state"], "current_site": body["site"] if active else "none",
            "current_site_ms_lower_bound": milliseconds(now-sampled) if active else 0,
            "body_ms_lower_bound": milliseconds((now if active else boundary)-started),
            "holder_cpu_ms_through_sample": milliseconds(cpu_elapsed),
            "cpu_sample_age_ms_lower_bound": milliseconds(now-sampled),
            "slowest_site": body["slowest_site"],
            "slowest_site_ms_lower_bound": milliseconds(body["slowest_wall_ns"]),
            "slowest_site_cpu_ms_between_samples": milliseconds(body["slowest_cpu_ns"]),
        }, allowed_sites=allowed_sites)
    except BaseException:
        return "unknown"


@contextmanager
def _relay_writer_context(operation):
    parent = frame = token = None
    parent_active = False
    try:
        parent = _relay_writer_operation.get()
        if type(parent) is dict:
            parent_active = parent.get("active") is True
            parent["active"] = False
        frame = {"operation": operation, "active": True, "open": True}
        token = _relay_writer_operation.set(frame)
    except BaseException:
        try:
            token = _relay_writer_operation.set(None)
        except BaseException:
            pass
    try:
        yield
    finally:
        try:
            if type(frame) is dict:
                frame["active"] = False
                frame["open"] = False
            if token is not None:
                _relay_writer_operation.reset(token)
        except BaseException:
            pass
        finally:
            try:
                if type(parent) is dict:
                    parent["active"] = parent_active and parent.get("open") is True
            except BaseException:
                pass


def _relay_writer_operation_name():
    try:
        frame = _relay_writer_operation.get()
        if type(frame) is dict and frame.get("active") is True and frame.get("open") is True:
            value = frame.get("operation")
            if type(value) is str and value in _RELAY_WRITER_OPERATIONS:
                return value
    except BaseException:
        pass
    return "unknown"


def _relay_writer_observation(error):
    try:
        if not isinstance(error, ImmediateTransactionBusyError):
            return "unknown"
        stage = getattr(error, "acquisition_stage", None)
        if type(stage) is not str or stage != "local_gate":
            return "unknown"
        value = getattr(error, "observed_relay_writer", None)
        keys = {"owner_id", "operation", "phase", "held_ms_lower_bound", "phase_ms_lower_bound"}
        if type(value) is not dict or not keys <= set(value) or set(value) - keys - {"turn_body", "detail", "opencode_verb", "opencode_body"}:
            return "unknown"
        owner, operation, phase = value["owner_id"], value["operation"], value["phase"]
        if (type(owner) is not int or not 1 <= owner <= 2**53 - 1
                or type(operation) is not str or operation not in _RELAY_WRITER_OPERATIONS
                or type(phase) is not str or phase not in {"acquisition", "transaction", "settlement", "unknown"}):
            return "unknown"
        held, phase_age = value["held_ms_lower_bound"], value["phase_ms_lower_bound"]
        if not (type(held) is int and 0 <= held <= 604_800_000
                or type(held) is str and held == "over_limit"):
            return "unknown"
        if phase == "unknown":
            if type(phase_age) is not str or phase_age != "unknown":
                return "unknown"
        elif not (type(phase_age) is int and 0 <= phase_age <= 604_800_000
                  or type(phase_age) is str and phase_age == "over_limit"):
            return "unknown"
        if type(held) is int and type(phase_age) is int and phase_age > held:
            return "unknown"
        result = {key: value[key] for key in sorted(keys)}
        if "opencode_verb" in value or "opencode_body" in value:
            if operation != "opencode_wake":
                return "unknown"
            result["opencode_verb"] = _relay_opencode_verb(value.get("opencode_verb"))
            result["opencode_body"] = _relay_turn_body_fields(value.get("opencode_body"), allowed_sites=_RELAY_OPENCODE_SITES)
        if "turn_body" in value:
            result["turn_body"] = _relay_turn_body_fields(value["turn_body"])
        if "detail" in value:
            result["detail"] = _relay_owner_detail_fields(value["detail"])
        return result
    except BaseException:
        return "unknown"


def _relay_sql_observation_fields(value):
    if type(value) is str and value == "unknown":
        return value
    if type(value) is not dict or set(value) != {"span", *_RELAY_EXPIRY_FLAGS}:
        raise ValueError("invalid diagnostic observation")
    if any(type(value[name]) is not bool for name in _RELAY_EXPIRY_FLAGS):
        raise ValueError("invalid diagnostic flags")
    if any(value[f"{name}_returned"] and not value[f"{name}_entered"] for name in ("flush", "cursor")):
        raise ValueError("invalid diagnostic boundaries")
    return {"span": _relay_turn_body_fields(value["span"], allowed_sites=_RELAY_EXPIRY_SITES),
            **{name: value[name] for name in sorted(_RELAY_EXPIRY_FLAGS)}}


def _relay_owner_detail_fields(value):
    try:
        if type(value) is not dict or set(value) not in (
                {"body_hook_state", "expiry", "settlement"},
                {"body_hook_state", "expiry", "settlement", "count"}):
            return "unknown"
        state = value["body_hook_state"]
        if type(state) is not str or state not in _RELAY_BODY_HOOK_STATES:
            return "unknown"
        expiry = _relay_sql_observation_fields(value["expiry"])
        settlement = value["settlement"]
        if not (type(settlement) is str and settlement == "unknown"):
            if type(settlement) is not dict or set(settlement) != {"state", "elapsed_ms_lower_bound"}:
                return "unknown"
            if type(settlement["state"]) is not str or settlement["state"] not in {"inflight", "settled"}:
                return "unknown"
            elapsed = settlement["elapsed_ms_lower_bound"]
            if not (type(elapsed) is int and 0 <= elapsed <= 604_800_000
                    or type(elapsed) is str and elapsed == "over_limit"):
                return "unknown"
            settlement = dict(settlement)
        result = {"body_hook_state": state, "expiry": expiry, "settlement": settlement}
        if "count" in value:
            result["count"] = "unknown"
            try:
                count = value["count"]
                if type(count) is dict and set(count) == {"hook_state", "observation"}:
                    hook = count["hook_state"]
                    if type(hook) is str and hook in _RELAY_BODY_HOOK_STATES:
                        result["count"] = {"hook_state": hook,
                                           "observation": _relay_sql_observation_fields(count["observation"])}
            except BaseException:
                pass
        return result
    except BaseException:
        return "unknown"


def _relay_owner_detail_view(owner, now):
    try:
        if type(owner) is not dict or type(now) is not int or now < 0:
            return "unknown"
        expiry = "unknown"
        flags = owner.get("expiry_boundaries")
        span = _relay_turn_body_view(owner.get("expiry_detail"), now, allowed_sites=_RELAY_EXPIRY_SITES)
        if span != "unknown" and type(flags) is dict and set(flags) == _RELAY_EXPIRY_FLAGS:
            expiry = {"span": span, **flags}
        settlement = "unknown"
        raw = owner.get("settlement")
        if type(raw) is dict and type(raw.get("state")) is str and raw["state"] in {"inflight", "settled"}:
            end = now if raw["state"] == "inflight" else raw.get("ended_ns")
            start = raw.get("started_ns")
            if type(start) is int and type(end) is int and 0 <= start <= end <= now:
                elapsed = (end - start) // 1_000_000
                settlement = {"state": raw["state"], "elapsed_ms_lower_bound":
                              elapsed if elapsed <= 604_800_000 else "over_limit"}
        detail = {"body_hook_state": owner.get("body_hook_state", "unknown"),
                  "expiry": expiry, "settlement": settlement}
        if "count_hook_state" in owner:
            count = "unknown"
            try:
                flags = owner.get("count_boundaries")
                span = _relay_turn_body_view(owner.get("count_detail"), now, allowed_sites=_RELAY_EXPIRY_SITES)
                if span != "unknown" and type(flags) is dict and set(flags) == _RELAY_EXPIRY_FLAGS:
                    count = _relay_sql_observation_fields({"span": span, **flags})
            except BaseException:
                pass
            detail["count"] = {"hook_state": owner["count_hook_state"], "observation": count}
        return _relay_owner_detail_fields(detail)
    except BaseException:
        return "unknown"


def _relay_request_writer_view(owner, now):
    try:
        if type(owner) is not dict or type(now) is not int or now < 0:
            return "unknown"
        number, operation = owner["owner_id"], owner["operation"]
        if type(number) is not int or not 1 <= number <= 2**53 - 1 or type(operation) is not str or operation not in {"turn", "opencode_wake"}:
            return "unknown"
        result = {"owner_id": number, "operation": operation,
                "turn_body": _relay_turn_body_view(owner.get("turn_body"), now),
                "detail": _relay_owner_detail_view(owner, now)}
        if operation == "opencode_wake":
            result.update(opencode_verb=_relay_opencode_verb(owner.get("opencode_verb")),
                          opencode_body=_relay_turn_body_view(owner.get("opencode_body"), now, allowed_sites=_RELAY_OPENCODE_SITES))
        return result
    except BaseException:
        return "unknown"


def _relay_request_writer_observation(error):
    try:
        value = getattr(error, "request_relay_writer", None)
        if type(value) is not dict:
            return "unknown"
        number, operation = value["owner_id"], value["operation"]
        if type(number) is not int or not 1 <= number <= 2**53 - 1 or type(operation) is not str or operation not in {"turn", "opencode_wake"}:
            return "unknown"
        keys = {"owner_id", "operation", "turn_body", "detail"}
        if operation == "opencode_wake":
            keys |= {"opencode_verb", "opencode_body"}
        if set(value) != keys:
            return "unknown"
        result = {"owner_id": number, "operation": operation,
                "turn_body": _relay_turn_body_fields(value["turn_body"]),
                "detail": _relay_owner_detail_fields(value["detail"])}
        if operation == "opencode_wake":
            result.update(opencode_verb=_relay_opencode_verb(value["opencode_verb"]),
                          opencode_body=_relay_turn_body_fields(value["opencode_body"], allowed_sites=_RELAY_OPENCODE_SITES))
        return result
    except BaseException:
        return "unknown"


def is_transient_error(exc: Exception) -> bool:
    """Check if an exception is a transient error worth retrying.

    Currently covers SQLite transient errors (disk I/O, busy, locked),
    handling both raw sqlite3.OperationalError and SQLAlchemy-wrapped versions.
    """
    if isinstance(exc, ImmediateTransactionBusyError):
        return True
    original = exc
    if isinstance(exc, SAOperationalError) and exc.orig is not None:
        original = exc.orig
    if not isinstance(original, sqlite3.OperationalError):
        return False
    message = str(original).lower()
    return any(s in message for s in _TRANSIENT_SQLITE_ERROR_SUBSTRINGS)


class LookupRequestLinkError(ValueError):
    """A supplied lookup-to-request telemetry link is invalid."""


class SourceTurnSnapshotConflictError(ValueError):
    """A source turn key was reused with conflicting or forgotten attribution."""


class HistoryDiagnosticConflictError(Exception):
    """A diagnostic idempotency key was reused with different input."""


class HistoryDiagnosticCorruptError(ValueError):
    """A persisted History diagnostic snapshot is invalid or unsupported."""


class SupersessionConflictError(Exception):
    """Raised by W3 storage methods when a supersession or correction is
    attempted on a memory that is not currently active.

    Callers (typically the MCP tool boundary) surface this as HTTP 409
    Conflict so an agent that concurrently attempts the same operation
    gets a clean, retryable error rather than a corrupted supersession
    chain.

    Not a transient error — do not retry via _with_retry.
    """

