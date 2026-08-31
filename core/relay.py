from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Any

from core.container_ref import validate_explicit_container_ref
from redaction import redact_sensitive
from storage.relay_codec import RelayCodecError, parts_projection, prepare_parts


RELAY_RUNTIMES = frozenset({"claude-code", "codex", "opencode"})
RELAY_MESSAGE_MAX_CHARS = 1500
RELAY_TURN_MAX_CHARS = 2400
RELAY_TURN_MAX_MESSAGES = 3
RELAY_BROADCAST_MAX_RECIPIENTS = 25
RELAY_DEFAULT_EXPIRY_SECONDS = 24 * 60 * 60
RELAY_MIN_EXPIRY_SECONDS = 60
RELAY_MAX_EXPIRY_SECONDS = 7 * 24 * 60 * 60
RELAY_RECENT_SECONDS = 24 * 60 * 60
RELAY_CLAIM_LEASE_SECONDS = 60
RELAY_BATCH_TURN_MAX_CHARS = 16_384
RELAY_BATCH_TURN_MAX_BYTES = 65_536
RELAY_BATCH_TURN_MAX_MESSAGES = 8

_ALIAS_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


class RelayError(Exception):
    pass


class RelayNotFoundError(RelayError):
    pass


class RelayConflictError(RelayError):
    pass


class RelayUnavailableError(RelayError):
    pass


def _opaque(value: str | None, field: str, *, maximum: int = 255) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} is required, non-blank, and must not have surrounding whitespace")
    if len(value) > maximum:
        raise ValueError(f"{field} exceeds {maximum} characters")
    if any(unicodedata.category(char) in {"Cc", "Zl", "Zp"} for char in value):
        raise ValueError(f"{field} contains control characters")
    return value


def validate_runtime(value: str) -> str:
    runtime = _opaque(value, "runtime", maximum=32)
    if runtime not in RELAY_RUNTIMES:
        raise ValueError(f"unknown runtime: {runtime}")
    return runtime


def validate_alias(value: str) -> str:
    alias = _opaque(value, "alias", maximum=32).lower()
    if not _ALIAS_RE.fullmatch(alias):
        raise ValueError("alias must match [a-z0-9][a-z0-9_-]{0,31}")
    return alias


def validate_payload(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("payload is required and must be non-blank")
    if len(value) > RELAY_MESSAGE_MAX_CHARS:
        raise ValueError(f"payload exceeds {RELAY_MESSAGE_MAX_CHARS} Unicode code points")
    if any(
        (unicodedata.category(char) == "Cc" and char not in "\n\r\t")
        or unicodedata.category(char) in {"Zl", "Zp"}
        for char in value
    ):
        raise ValueError("payload contains unsafe control characters")
    return value


def parse_selector(value: str) -> tuple[str, str, str | None]:
    selector = _opaque(value, "recipient", maximum=320)
    runtime, separator, target = selector.partition(":")
    validate_runtime(runtime)
    if not separator:
        return runtime, "runtime", None
    if not target:
        raise ValueError("recipient session or alias is required after ':'")
    if target.startswith("@"):
        return runtime, "alias", validate_alias(target[1:])
    return runtime, "session", _opaque(target, "recipient session_ref")


class RelayService:
    """Validated Relay boundary over the optional SQLite relay capability."""

    def __init__(self, store: Any, *, batch_candidate_enabled: bool = False) -> None:
        required = (
            "relay_turn",
            "relay_close_session",
            "relay_list_sessions",
            "relay_name_session",
            "relay_send",
            "relay_reply_atomic",
            "relay_message_status",
            "relay_ack",
            "relay_ack_by_receipt",
        )
        if not all(callable(getattr(store, name, None)) for name in required):
            raise RelayUnavailableError("relay is not supported by the configured storage")
        self._store = store
        # Only disposable fixtures opt in; production defaults to legacy Relay.
        self._batch_candidate_enabled = batch_candidate_enabled

    @staticmethod
    def _scope(container_ref: str, actor_ref: str) -> tuple[str, str]:
        return (
            validate_explicit_container_ref(container_ref),
            _opaque(actor_ref, "actor_ref", maximum=255),
        )

    def turn(
        self,
        *,
        runtime: str,
        session_ref: str,
        container_ref: str,
        actor_ref: str,
        title: str | None = None,
        max_chars: int = 0,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        container, actor = self._scope(container_ref, actor_ref)
        if max_chars < 0:
            raise ValueError("max_chars must be >= 0 (0 = no limit)")
        return self._store.relay_turn(
            runtime=validate_runtime(runtime),
            session_ref=_opaque(session_ref, "session_ref"),
            container_ref=container,
            actor_ref=actor,
            title=None if title is None else _opaque(title, "title", maximum=255),
            max_chars=min(max_chars or RELAY_BATCH_TURN_MAX_CHARS, RELAY_BATCH_TURN_MAX_CHARS) if self._batch_candidate_enabled else max_chars,
            max_messages=RELAY_BATCH_TURN_MAX_MESSAGES if self._batch_candidate_enabled else 0,
            max_bytes=RELAY_BATCH_TURN_MAX_BYTES if self._batch_candidate_enabled else 0,
            candidate_batch=self._batch_candidate_enabled,
            lease_seconds=RELAY_CLAIM_LEASE_SECONDS,
            now=now,
        )

    def start_publication(
        self,
        *,
        delivery_id: str,
        claim_token: str,
        envelope_digest: str,
        container_ref: str,
        actor_ref: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        container, actor = self._scope(container_ref, actor_ref)
        operation = getattr(self._store, "relay_start_publication", None)
        if not callable(operation):
            raise RelayUnavailableError("batch publication is not supported by the configured storage")
        return operation(
            delivery_id=_opaque(delivery_id, "delivery_id", maximum=128),
            claim_token=_opaque(claim_token, "claim_token", maximum=128),
            envelope_digest=_opaque(envelope_digest, "envelope_digest", maximum=64),
            container_ref=container,
            actor_ref=actor,
            now=now,
        )
    def admit(
        self,
        *,
        delivery_id: str,
        claim_token: str,
        envelope_digest: str,
        evidence: str,
        admitted_at: datetime | None = None,
        container_ref: str,
        actor_ref: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if not self._batch_candidate_enabled:
            raise RelayUnavailableError("candidate admission is disabled")
        container, actor = self._scope(container_ref, actor_ref)
        operation = getattr(self._store, "relay_admit", None)
        if not callable(operation):
            raise RelayUnavailableError("candidate admission is not supported by the configured storage")
        return operation(
            delivery_id=_opaque(delivery_id, "delivery_id", maximum=128),
            claim_token=_opaque(claim_token, "claim_token", maximum=128),
            envelope_digest=_opaque(envelope_digest, "envelope_digest", maximum=64),
            evidence=_opaque(evidence, "evidence", maximum=255),
            admitted_at=admitted_at,
            container_ref=container,
            actor_ref=actor,
            now=now,
        )
    def close_session(self, **scope: Any) -> dict[str, Any]:
        container, actor = self._scope(scope["container_ref"], scope["actor_ref"])
        return self._store.relay_close_session(
            runtime=validate_runtime(scope["runtime"]),
            session_ref=_opaque(scope["session_ref"], "session_ref"),
            container_ref=container,
            actor_ref=actor,
        )

    def list_sessions(
        self,
        *,
        container_ref: str,
        actor_ref: str,
        runtime: str | None = None,
        include_inactive: bool = False,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        container, actor = self._scope(container_ref, actor_ref)
        return self._store.relay_list_sessions(
            container_ref=container,
            actor_ref=actor,
            runtime=None if runtime is None else validate_runtime(runtime),
            include_inactive=include_inactive,
            recent_seconds=RELAY_RECENT_SECONDS,
            now=now,
        )

    def name_session(
        self,
        *,
        runtime: str,
        session_ref: str,
        container_ref: str,
        actor_ref: str,
        alias: str | None,
        replace_existing: bool = False,
    ) -> dict[str, Any]:
        container, actor = self._scope(container_ref, actor_ref)
        return self._store.relay_name_session(
            runtime=validate_runtime(runtime),
            session_ref=_opaque(session_ref, "session_ref"),
            container_ref=container,
            actor_ref=actor,
            alias=None if alias is None else validate_alias(alias),
            replace_existing=replace_existing,
        )

    def send(
        self,
        *,
        sender_runtime: str,
        sender_session_ref: str,
        recipient: str,
        payload: str | None,
        parts: list[str] | None = None,
        container_ref: str,
        actor_ref: str,
        expires_in_seconds: int = RELAY_DEFAULT_EXPIRY_SECONDS,
        in_reply_to: str | None = None,
        message_id: str | None = None,
        request_id: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        container, actor = self._scope(container_ref, actor_ref)
        if not RELAY_MIN_EXPIRY_SECONDS <= expires_in_seconds <= RELAY_MAX_EXPIRY_SECONDS:
            raise ValueError(f"expires_in_seconds must be between {RELAY_MIN_EXPIRY_SECONDS} and {RELAY_MAX_EXPIRY_SECONDS}")
        recipient_runtime, recipient_kind, recipient_value = parse_selector(recipient)
        if parts is not None:
            if payload is not None or not self._batch_candidate_enabled:
                raise RelayConflictError("multipart relay is only available in the explicit B2 fixture candidate")
            try:
                stored_payload = prepare_parts(parts)
                raw_payload = "".join(parts)
                redacted = parts_projection(stored_payload) != raw_payload
            except RelayCodecError as exc:
                raise ValueError(str(exc)) from exc
            payload_format = "parts_v1"
        else:
            if payload is None:
                raise ValueError("payload is required")
            raw_payload = validate_payload(payload)
            stored_payload = redact_sensitive(raw_payload)
            redacted = stored_payload != raw_payload
            payload_format = "text_v1"
        request = None if request_id is None else _opaque(request_id, "request_id", maximum=128)
        if request is not None and message_id is not None:
            raise ValueError("request_id and message_id cannot be combined")
        return self._store.relay_send(
            message_id=_opaque(message_id, "message_id", maximum=128) if message_id else f"relay-msg-{uuid.uuid4().hex}",
            request_id=request,
            sender_runtime=validate_runtime(sender_runtime),
            sender_session_ref=_opaque(sender_session_ref, "sender_session_ref"),
            recipient=recipient,
            recipient_runtime=recipient_runtime,
            recipient_kind=recipient_kind,
            recipient_value=recipient_value,
            payload=stored_payload,
            payload_format=payload_format,
            redacted=redacted,
            container_ref=container,
            actor_ref=actor,
            expires_in_seconds=expires_in_seconds,
            in_reply_to=None if in_reply_to is None else _opaque(in_reply_to, "in_reply_to", maximum=128),
            broadcast_recent_seconds=RELAY_RECENT_SECONDS,
            broadcast_max_recipients=RELAY_BROADCAST_MAX_RECIPIENTS,
            candidate_batch=self._batch_candidate_enabled,
            now=now,
        )
    def reply(
        self,
        *,
        delivery_id: str,
        receipt: str | None,
        payload: str | None,
        parts: list[str] | None = None,
        container_ref: str,
        actor_ref: str,
        expires_in_seconds: int = RELAY_DEFAULT_EXPIRY_SECONDS,
        request_id: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        container, actor = self._scope(container_ref, actor_ref)
        if not RELAY_MIN_EXPIRY_SECONDS <= expires_in_seconds <= RELAY_MAX_EXPIRY_SECONDS:
            raise ValueError(f"expires_in_seconds must be between {RELAY_MIN_EXPIRY_SECONDS} and {RELAY_MAX_EXPIRY_SECONDS}")
        delivery = _opaque(delivery_id, "delivery_id", maximum=128)
        if parts is not None:
            if payload is not None or not self._batch_candidate_enabled:
                raise RelayConflictError("multipart relay is only available in the explicit B2 fixture candidate")
            try:
                stored_payload = prepare_parts(parts)
                raw_payload = "".join(parts)
                redacted = parts_projection(stored_payload) != raw_payload
            except RelayCodecError as exc:
                raise ValueError(str(exc)) from exc
            payload_format = "parts_v1"
        else:
            if payload is None:
                raise ValueError("payload is required")
            raw_payload = validate_payload(payload)
            stored_payload = redact_sensitive(raw_payload)
            redacted = stored_payload != raw_payload
            payload_format = "text_v1"
        request = None if request_id is None else _opaque(request_id, "request_id", maximum=128)
        reply_id = "relay-reply-" + (hashlib.sha256(delivery.encode("utf-8")).hexdigest() if request is None else uuid.uuid4().hex)
        return self._store.relay_reply_atomic(
            delivery_id=delivery,
            receipt=_opaque(receipt, "receipt", maximum=64) if receipt is not None else None,
            reply_message_id=reply_id,
            request_id=request,
            payload=stored_payload,
            payload_format=payload_format,
            redacted=redacted,
            container_ref=container,
            actor_ref=actor,
            expires_in_seconds=expires_in_seconds,
            candidate_batch=self._batch_candidate_enabled,
            now=now,
        )
    def message_status(self, *, message_id: str, container_ref: str, actor_ref: str) -> dict[str, Any]:
        container, actor = self._scope(container_ref, actor_ref)
        return self._store.relay_message_status(
            message_id=_opaque(message_id, "message_id", maximum=128),
            container_ref=container,
            actor_ref=actor,
            now=datetime.now(timezone.utc),
        )

    def acknowledge(
        self,
        *,
        delivery_id: str,
        claim_token: str,
        container_ref: str,
        actor_ref: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        container, actor = self._scope(container_ref, actor_ref)
        return self._store.relay_ack(
            delivery_id=_opaque(delivery_id, "delivery_id", maximum=128),
            claim_token=_opaque(claim_token, "claim_token", maximum=128),
            container_ref=container,
            actor_ref=actor,
            now=now,
        )

    def ack_by_receipt(
        self,
        *,
        delivery_id: str,
        receipt: str,
        container_ref: str,
        actor_ref: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        container, actor = self._scope(container_ref, actor_ref)
        return self._store.relay_ack_by_receipt(
            delivery_id=_opaque(delivery_id, "delivery_id", maximum=128),
            receipt=_opaque(receipt, "receipt", maximum=64),
            container_ref=container,
            actor_ref=actor,
            now=now,
        )
