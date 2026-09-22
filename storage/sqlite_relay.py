from __future__ import annotations

import hashlib
import hmac
import json
import re
import unicodedata
import uuid
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from core.relay import (
    RELAY_TRACE_MAX_ROWS,
    RELAY_TRACE_MAX_SEQUENCE,
    RelayConflictError,
    RelayNotFoundError,
)
from redaction import redact_sensitive
from storage.sqlite_schema import (
    RelayAliasRecord,
    RelayDeliveryRecord,
    RelayDeliveryTraceRecord,
    RelayEndpointGenerationRecord,
    RelayEndpointRepairRecord,
    RelayMessageRecord,
    RelaySessionRecord,
    RelaySessionWorkRefRecord,
)


_REPAIR_ENDPOINT_RE = re.compile(r"^relay-session-[0-9a-f]{32}$")
_REPAIR_DELIVERY_RE = re.compile(r"^relay-delivery-[0-9a-f]{32}$")
_TRACE_ATTEMPT_RE = re.compile(r"^relay-activation-[0-9a-f]{32}$")
_TRACE_STAGES = frozenset({"prepared", "associated", "completed"})
_TRACE_OUTCOMES = frozenset({"accepted", "deferred", "uncertain", "failed"})
_TRACE_EVIDENCE = frozenset(
    {"submission_attempted", "transport_accepted", "payload_admitted"}
)
_TRACE_REDACTED_REASON = "[REDACTED: diagnostic reason omitted]"


def _now(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    return current if current.tzinfo is not None else current.replace(tzinfo=timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


# ponytail: NOT NULL sentinel avoids a SQLite table rebuild; migrate only if year-9999 storage stops being portable.
_DURABLE_EXPIRY = datetime.max.replace(tzinfo=timezone.utc)
_MAX_EXPLICIT_WORK_REFS = 3


def _expiry_at(current: datetime, expires_in_seconds: int | None) -> datetime:
    return _DURABLE_EXPIRY if expires_in_seconds is None else current + timedelta(seconds=expires_in_seconds)


def _expiry_matches(message: RelayMessageRecord, expires_in_seconds: int | None) -> bool:
    expiry = _now(message.expires_at)
    if expires_in_seconds is None:
        return expiry == _DURABLE_EXPIRY
    return expiry - _now(message.created_at) == timedelta(seconds=expires_in_seconds)


def _expiry_iso(value: datetime) -> str | None:
    return None if _now(value) == _DURABLE_EXPIRY else _iso(value)


def _session_view(row: RelaySessionRecord, now: datetime, recent_seconds: int, scope_generation: int = 0) -> dict[str, Any]:
    if row.state == "closed":
        lifecycle = "closed"
    else:
        last_seen = _now(row.last_seen_at)
        lifecycle = "recent" if last_seen >= now - timedelta(seconds=recent_seconds) else "dormant"
    return {
        "endpoint_id": row.id,
        "runtime": row.runtime,
        "session_ref": row.session_ref,
        "container_ref": row.container_ref,
        "title": row.title,
        "alias": row.alias,
        "state": lifecycle,
        "destination_health": None if row.state == "closed" else row.state,
        "first_seen_at": _iso(row.first_seen_at),
        "last_seen_at": _iso(row.last_seen_at),
        "closed_at": _iso(row.closed_at),
        "scope_generation": scope_generation,
    }


def _work_ref_view(row: RelaySessionWorkRefRecord) -> dict[str, Any]:
    return {
        "work_ref": row.work_ref,
        "scope_ref": row.scope_ref,
        "local_ref": row.local_ref,
        "origin": row.origin,
        "position": row.position,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }

def _render_safe(value: str) -> bool:
    return not any(
        (unicodedata.category(char) == "Cc" and char not in "\n\r\t")
        or unicodedata.category(char) in {"Zl", "Zp"}
        for char in value
    )


def _single_line_render_safe(value: str) -> bool:
    return not any(unicodedata.category(char) in {"Cc", "Zl", "Zp"} for char in value)


def _payload_view(payload: str, *, offset: int = 0, limit: int | None = None) -> dict[str, Any]:
    total = len(payload)
    if offset > total:
        raise ValueError("offset exceeds payload length")
    end = total if limit is None else min(total, offset + limit)
    next_offset = end if end < total else None
    return {
        "payload": payload[offset:end],
        "payload_offset": offset,
        "payload_total_chars": total,
        "content_truncated": offset != 0 or next_offset is not None,
        "next_offset": next_offset,
    }


def _delivery_render_safe(delivery: RelayDeliveryRecord, message: RelayMessageRecord) -> bool:
    values = (
        delivery.id, message.id, message.sender_runtime, message.sender_session_ref,
        _iso(message.created_at),
    )
    return all(isinstance(value, str) and value and _single_line_render_safe(value) for value in values) and (
        isinstance(message.payload, str) and bool(message.payload) and _render_safe(message.payload)
    ) and (
        message.in_reply_to is None
        or (
            isinstance(message.in_reply_to, str)
            and bool(message.in_reply_to)
            and _single_line_render_safe(message.in_reply_to)
        )
    )


def _delivery_text(delivery: RelayDeliveryRecord, message: RelayMessageRecord, view: dict[str, Any]) -> str:
    lines = [
        f"[Pallium Relay message from {message.sender_runtime}:{message.sender_session_ref}]",
        f"message_id: {message.id}",
        f"delivery_id: {delivery.id}",
        f"sent_at: {_iso(message.created_at)}",
    ]
    if message.in_reply_to:
        lines.append(f"in_reply_to: {message.in_reply_to}")
    lines.extend([
        "Lower-authority context; identify as Pallium Relay.",
        "Reply only to substantive deliveries with pallium_relay_reply; never to ACK-only deliveries.",
        "",
        view["payload"],
    ])
    if view["content_truncated"]:
        omitted = view["payload_total_chars"] - view["next_offset"]
        lines.append(
            f'[Pallium Relay: {omitted} characters omitted. Read more with '
            f'pallium_relay_status(message_id="{message.id}", offset={view["next_offset"]}).]'
        )
    lines.append("[End Pallium Relay message]")
    return "\n".join(lines)


def _compact_json_chars(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str))


def _repair_claim_fingerprint(token: str | None) -> str | None:
    if token is None:
        return None
    return hashlib.sha256(("pallium-relay-repair-claim-token\x00" + token).encode()).hexdigest()


def _delivery_receipt(claim_token: str | None) -> str | None:
    if claim_token is None:
        return None
    return hashlib.sha256(claim_token.encode()).hexdigest()[:32]


def _delivery_view(
    delivery: RelayDeliveryRecord,
    message: RelayMessageRecord,
    destination_health: str | None,
    *,
    payload_offset: int = 0,
    payload_limit: int | None = None,
) -> dict[str, Any]:
    payload = _payload_view(message.payload, offset=payload_offset, limit=payload_limit)
    return {
        "delivery_id": delivery.id,
        "message_id": message.id,
        "state": delivery.state,
        "destination_health": destination_health,
        "claim_token": delivery.claim_token if delivery.state == "claimed" else None,
        "receipt": _delivery_receipt(delivery.claim_token) if delivery.state == "claimed" else None,
        "recipient_runtime": delivery.recipient_runtime,
        "recipient_session_ref": delivery.recipient_session_ref,
        "recipient_endpoint_id": delivery.recipient_endpoint_id,
        "recipient_container_ref": delivery.recipient_container_ref,
        "sender_runtime": message.sender_runtime,
        "sender_session_ref": message.sender_session_ref,
        "sender_endpoint_id": message.sender_endpoint_id,
        "recipient": message.recipient_selector,
        **payload,
        "redacted": bool(message.redacted),
        "in_reply_to": message.in_reply_to,
        "created_at": _iso(message.created_at),
        "expires_at": _expiry_iso(message.expires_at),
        "claimed_at": _iso(delivery.claimed_at),
        "lease_expires_at": _iso(delivery.lease_expires_at),
        "delivered_at": _iso(delivery.delivered_at),
        "attempts": delivery.attempts,
    }


class SQLiteRelayMixin:
    def relay_endpoint_repair_apply(self, manifest: dict[str, Any], *, reservation_validator: Callable[[], set[str]] | None = None, now: datetime | None = None) -> dict[str, Any]:
        """Apply one exact, reviewed repair snapshot under one write transaction."""
        required = {"schema_version", "database_identity", "source_endpoint_ids", "destination_endpoint_id", "expected_scopes", "endpoint_preimage", "reservation_evidence", "dispositions"}
        if not isinstance(manifest, dict) or set(manifest) != required or manifest.get("schema_version") not in {1, 2}:
            raise RelayConflictError("repair manifest schema is invalid")
        source_ids, destination_id, scopes = manifest["source_endpoint_ids"], manifest["destination_endpoint_id"], manifest["expected_scopes"]
        dispositions = manifest["dispositions"]
        if (not isinstance(source_ids, list) or not 1 <= len(source_ids) <= 32 or len(set(source_ids)) != len(source_ids) or any(not isinstance(value, str) or not _REPAIR_ENDPOINT_RE.fullmatch(value) for value in source_ids) or not isinstance(destination_id, str) or not _REPAIR_ENDPOINT_RE.fullmatch(destination_id) or destination_id in source_ids or not isinstance(scopes, dict) or set(scopes) != {*source_ids, destination_id} or any(not isinstance(value, str) or not value for value in scopes.values()) or not isinstance(dispositions, list) or not 1 <= len(dispositions) <= 512):
            raise RelayConflictError("repair manifest endpoint or disposition bounds are invalid")
        required_disposition = {"delivery_id", "disposition", "preimage"}
        schema_version = manifest["schema_version"]
        required_delivery = {"delivery_id", "message_id", "recipient_runtime", "recipient_session_ref", "recipient_endpoint_id", "recipient_container_ref", "state", "claim_token" if schema_version == 1 else "claim_token_fingerprint", "claimed_at", "lease_expires_at", "delivered_at", "attempts"}
        required_message = {"message_id", "sender_runtime", "sender_session_ref", "sender_endpoint_id", "recipient_selector", "container_ref", "payload_sha256", "payload_length", "redacted", "in_reply_to", "created_at", "expires_at"}
        if any(not isinstance(item, dict) or set(item) != required_disposition or not isinstance(item["delivery_id"], str) or not _REPAIR_DELIVERY_RE.fullmatch(item["delivery_id"]) or item["disposition"] not in {"adopt", "suppress"} or not isinstance(item["preimage"], dict) or set(item["preimage"]) != {"delivery", "message"} or not isinstance(item["preimage"]["delivery"], dict) or set(item["preimage"]["delivery"]) != required_delivery or not isinstance(item["preimage"]["message"], dict) or set(item["preimage"]["message"]) != required_message or item["preimage"]["delivery"].get("delivery_id") != item["delivery_id"] or item["preimage"]["delivery"].get("message_id") != item["preimage"]["message"].get("message_id") for item in dispositions):
            raise RelayConflictError("repair manifest disposition preimage is invalid")
        if any(
            item["preimage"]["delivery"]["state"] not in {"pending", "claimed"}
            or (
                schema_version == 2
                and (
                    (item["preimage"]["delivery"]["state"] == "pending" and item["preimage"]["delivery"]["claim_token_fingerprint"] is not None)
                    or (item["preimage"]["delivery"]["state"] == "claimed" and (not isinstance(item["preimage"]["delivery"]["claim_token_fingerprint"], str) or re.fullmatch(r"[0-9a-f]{64}", item["preimage"]["delivery"]["claim_token_fingerprint"]) is None))
                )
            )
            for item in dispositions
        ):
            raise RelayConflictError("repair manifest delivery state or claim fingerprint is invalid")
        if schema_version == 1 and any(item["preimage"]["delivery"]["state"] != "pending" for item in dispositions):
            raise RelayConflictError("version 1 repair manifests support pending deliveries only")
        if schema_version == 2 and any(item["preimage"]["delivery"]["state"] == "claimed" and item["disposition"] != "suppress" for item in dispositions):
            raise RelayConflictError("expired claimed delivery may only be suppressed")
        delivery_ids = [item["delivery_id"] for item in dispositions]
        if len(set(delivery_ids)) != len(delivery_ids):
            raise RelayConflictError("repair manifest has duplicate delivery IDs")
        endpoint_preimage = manifest["endpoint_preimage"]
        if not isinstance(endpoint_preimage, dict) or set(endpoint_preimage) != {*source_ids, destination_id}:
            raise RelayConflictError("repair endpoint preimage is incomplete")
        endpoint_keys = {"runtime", "session_ref", "container_ref", "title", "alias", "state", "first_seen_at", "last_seen_at", "closed_at", "generation", "aliases", "work_refs"}
        if any(not isinstance(value, dict) or set(value) != endpoint_keys or value["state"] not in {"active", "unreachable", "closed"} or type(value["generation"]) is not int or value["generation"] < 0 or not isinstance(value["aliases"], list) or not isinstance(value["work_refs"], list) for value in endpoint_preimage.values()):
            raise RelayConflictError("repair endpoint preimage is invalid")
        evidence = manifest["reservation_evidence"]
        evidence_rows = evidence.get("deliveries") if isinstance(evidence, dict) else None
        stores = evidence.get("stores") if isinstance(evidence, dict) else None
        if (
            not isinstance(evidence, dict)
            or set(evidence) != {"stores", "deliveries"}
            or not isinstance(stores, dict)
            or set(stores) != {"codex", "claude", "claude_intents"}
            or any(
                not isinstance(value, dict)
                or set(value) != {"status", "sha256", "count", "path"}
                or value["status"] not in {"missing", "valid"}
                or (value["sha256"] is not None and (not isinstance(value["sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is None))
                or type(value["count"]) is not int
                or value["count"] < 0
                or (value["path"] is not None and (not isinstance(value["path"], str) or not value["path"]))
                for value in stores.values()
            )
            or not isinstance(evidence_rows, list)
            or len(evidence_rows) != len(dispositions)
            or any(
                not isinstance(row, dict)
                or set(row) != {"delivery_id", "runtime", "status"}
                or row["status"] not in {"clean", "blocked", "unknown"}
                for row in evidence_rows
            )
            or {row["delivery_id"] for row in evidence_rows} != set(delivery_ids)
        ):
            raise RelayConflictError("repair reservation evidence is invalid")
        evidence_by_id = {row["delivery_id"]: row for row in evidence_rows}
        if any(evidence_by_id[item["delivery_id"]]["runtime"] != item["preimage"]["delivery"]["recipient_runtime"] for item in dispositions):
            raise RelayConflictError("repair reservation evidence runtime is invalid")
        canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        with self._begin_relay_immediate() as db:
            prior = db.get(RelayEndpointRepairRecord, digest)
            if prior is not None:
                try:
                    if json.dumps(json.loads(prior.manifest_json), ensure_ascii=False, sort_keys=True, separators=(",", ":")) != canonical:
                        raise ValueError("manifest mismatch")
                    result = json.loads(prior.result_json)
                    expected_adopted = [item["delivery_id"] for item in dispositions if item["disposition"] == "adopt"]
                    expected_suppressed = [item["delivery_id"] for item in dispositions if item["disposition"] == "suppress"]
                    if result != {
                        "manifest_digest": digest,
                        "adopted_delivery_ids": expected_adopted,
                        "suppressed_delivery_ids": expected_suppressed,
                        "residual_split": {"alias_sends": "destination", "exact_source_sends_and_replies": "source", "occupied_scopes": "unchanged"},
                    }:
                        raise ValueError("result mismatch")
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise RelayConflictError("repair ledger is corrupt") from exc
                return result
            for record in db.execute(select(RelayEndpointRepairRecord)).scalars():
                try:
                    previous = json.loads(record.manifest_json)
                    previous_canonical = json.dumps(previous, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    previous_dispositions = previous["dispositions"]
                    if (
                        hashlib.sha256(previous_canonical.encode()).hexdigest() != record.manifest_digest
                        or not isinstance(previous, dict)
                        or set(previous) != required
                        or previous.get("schema_version") not in {1, 2}
                        or not isinstance(previous_dispositions, list)
                        or not 1 <= len(previous_dispositions) <= 512
                        or any(not isinstance(item, dict) or set(item) != required_disposition or not isinstance(item.get("delivery_id"), str) or not _REPAIR_DELIVERY_RE.fullmatch(item["delivery_id"]) for item in previous_dispositions)
                    ):
                        raise ValueError("invalid manifest")
                    old_id_list = [item["delivery_id"] for item in previous_dispositions]
                    if len(set(old_id_list)) != len(old_id_list):
                        raise ValueError("duplicate delivery")
                    old_ids = set(old_id_list)
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise RelayConflictError("repair ledger is corrupt") from exc
                if set(delivery_ids) & old_ids:
                    raise RelayConflictError("delivery was already dispositioned by a repair ledger entry")
            clean_adoption_ids = reservation_validator() if reservation_validator is not None else set()
            if not isinstance(clean_adoption_ids, set) or any(not isinstance(value, str) for value in clean_adoption_ids):
                raise RelayConflictError("repair reservation validator returned invalid evidence")
            current = _now(now)
            path = Path(self._relay_engine.url.database or "").resolve()
            try:
                connection = db.connection()
                actual_identity = {"sqlite_path": str(path), "application_id": connection.exec_driver_sql("PRAGMA application_id").scalar(), "user_version": connection.exec_driver_sql("PRAGMA user_version").scalar(), "schema_version": connection.exec_driver_sql("PRAGMA schema_version").scalar()}
            except Exception as exc:
                raise RelayConflictError("cannot validate repair database identity") from exc
            if manifest["database_identity"] != actual_identity:
                raise RelayConflictError("repair database identity drifted")
            sources = [db.get(RelaySessionRecord, endpoint_id) for endpoint_id in source_ids]
            destination = db.get(RelaySessionRecord, destination_id)
            if destination is None or any(source is None for source in sources):
                raise RelayConflictError("repair endpoint is missing")

            def endpoint_actual(endpoint: RelaySessionRecord) -> dict[str, Any]:
                generation = db.get(RelayEndpointGenerationRecord, endpoint.id)
                aliases = [{"alias": row.alias, "endpoint_id": row.endpoint_id} for row in db.execute(select(RelayAliasRecord).where(RelayAliasRecord.endpoint_id == endpoint.id).order_by(RelayAliasRecord.alias)).scalars()]
                work_refs = [{"endpoint_id": row.endpoint_id, "work_ref": row.work_ref, "origin": row.origin, "scope_ref": row.scope_ref, "local_ref": row.local_ref, "position": row.position, "created_at": _iso(row.created_at), "updated_at": _iso(row.updated_at)} for row in db.execute(select(RelaySessionWorkRefRecord).where(RelaySessionWorkRefRecord.endpoint_id == endpoint.id).order_by(RelaySessionWorkRefRecord.work_ref, RelaySessionWorkRefRecord.origin)).scalars()]
                return {"runtime": endpoint.runtime, "session_ref": endpoint.session_ref, "container_ref": endpoint.container_ref, "title": endpoint.title, "alias": endpoint.alias, "state": endpoint.state, "first_seen_at": _iso(endpoint.first_seen_at), "last_seen_at": _iso(endpoint.last_seen_at), "closed_at": _iso(endpoint.closed_at), "generation": 0 if generation is None else generation.generation, "aliases": aliases, "work_refs": work_refs}

            for source in sources:
                assert source is not None
                actual = endpoint_actual(source)
                if endpoint_preimage[source.id] != actual or scopes[source.id] != source.container_ref or source.alias is not None or actual["aliases"] or actual["work_refs"]:
                    raise RelayConflictError("source endpoint preimage, alias, work-ref, or scope drifted")
            destination_actual = endpoint_actual(destination)
            alias_owner = None if destination.alias is None else db.get(RelayAliasRecord, destination.alias)
            if destination.alias is not None and (alias_owner is None or alias_owner.endpoint_id != destination.id):
                raise RelayConflictError("destination alias ownership is inconsistent")
            expected_aliases = [] if destination.alias is None else [{"alias": destination.alias, "endpoint_id": destination.id}]
            if destination_actual["aliases"] != expected_aliases:
                raise RelayConflictError("destination alias ownership is inconsistent")
            if endpoint_preimage[destination.id] != destination_actual or scopes[destination.id] != destination.container_ref:
                raise RelayConflictError("destination endpoint preimage or scope drifted")
            siblings = db.execute(select(RelaySessionRecord).where(RelaySessionRecord.runtime == destination.runtime, RelaySessionRecord.session_ref == destination.session_ref)).scalars().all()
            if {row.id for row in siblings} != {*source_ids, destination.id}:
                raise RelayConflictError("same runtime/session endpoint set is incomplete")
            claimed_rows = db.execute(select(RelayDeliveryRecord).where(RelayDeliveryRecord.recipient_endpoint_id.in_(source_ids), RelayDeliveryRecord.state == "claimed")).scalars().all()
            if schema_version == 1 and claimed_rows:
                raise RelayConflictError("a source has claimed work")
            if schema_version == 2 and any(
                not claimed.claim_token
                or claimed.lease_expires_at is None
                or _now(claimed.lease_expires_at) > current
                for claimed in claimed_rows
            ):
                raise RelayConflictError("a source has active or malformed claimed work")
            repairable_state = RelayDeliveryRecord.state == "pending"
            if schema_version == 2:
                repairable_state = or_(
                    repairable_state,
                    and_(
                        RelayDeliveryRecord.state == "claimed",
                        RelayDeliveryRecord.lease_expires_at.is_not(None),
                        RelayDeliveryRecord.lease_expires_at <= current,
                    ),
                )
            live = db.execute(select(RelayDeliveryRecord.id).join(RelayMessageRecord, RelayMessageRecord.id == RelayDeliveryRecord.message_id).where(RelayDeliveryRecord.recipient_endpoint_id.in_(source_ids), repairable_state, RelayMessageRecord.expires_at > current)).scalars().all()
            if set(live) != set(delivery_ids):
                raise RelayConflictError("repair manifest does not classify the complete live source inventory")
            result = {"manifest_digest": digest, "adopted_delivery_ids": [], "suppressed_delivery_ids": [], "residual_split": {"alias_sends": "destination", "exact_source_sends_and_replies": "source", "occupied_scopes": "unchanged"}}
            for item in dispositions:
                delivery = db.get(RelayDeliveryRecord, item["delivery_id"])
                message = None if delivery is None else db.get(RelayMessageRecord, delivery.message_id)
                if delivery is None or message is None:
                    raise RelayConflictError("repair delivery is missing")
                payload = message.payload.encode()
                actual = {"delivery": {"delivery_id": delivery.id, "message_id": delivery.message_id, "recipient_runtime": delivery.recipient_runtime, "recipient_session_ref": delivery.recipient_session_ref, "recipient_endpoint_id": delivery.recipient_endpoint_id, "recipient_container_ref": delivery.recipient_container_ref, "state": delivery.state, ("claim_token" if schema_version == 1 else "claim_token_fingerprint"): delivery.claim_token if schema_version == 1 else _repair_claim_fingerprint(delivery.claim_token), "claimed_at": _iso(delivery.claimed_at), "lease_expires_at": _iso(delivery.lease_expires_at), "delivered_at": _iso(delivery.delivered_at), "attempts": delivery.attempts}, "message": {"message_id": message.id, "sender_runtime": message.sender_runtime, "sender_session_ref": message.sender_session_ref, "sender_endpoint_id": message.sender_endpoint_id, "recipient_selector": message.recipient_selector, "container_ref": message.container_ref, "payload_sha256": hashlib.sha256(payload).hexdigest(), "payload_length": len(payload), "redacted": bool(message.redacted), "in_reply_to": message.in_reply_to, "created_at": _iso(message.created_at), "expires_at": _iso(message.expires_at)}}
                claim_expired = (
                    delivery.state == "claimed"
                    and delivery.lease_expires_at is not None
                    and _now(delivery.lease_expires_at) <= current
                )
                repairable = delivery.state == "pending" or (
                    schema_version == 2
                    and claim_expired
                    and item["disposition"] == "suppress"
                )
                if actual != item["preimage"] or delivery.recipient_endpoint_id not in source_ids or not repairable or _now(message.expires_at) <= current:
                    raise RelayConflictError("repair delivery or message preimage drifted")
                if item["disposition"] == "adopt":
                    if evidence_by_id[delivery.id]["status"] != "clean" or delivery.id not in clean_adoption_ids:
                        raise RelayConflictError("adoption requires clean authoritative reservation evidence")
                    delivery.recipient_endpoint_id = destination.id
                    result["adopted_delivery_ids"].append(delivery.id)
                else:
                    delivery.state = "suppressed"
                    if schema_version == 2 and actual["delivery"]["state"] == "claimed":
                        delivery.claim_token = None
                        delivery.lease_expires_at = None
                    result["suppressed_delivery_ids"].append(delivery.id)
            db.add(RelayEndpointRepairRecord(manifest_digest=digest, manifest_json=canonical, result_json=json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")), committed_at=current))
            return result

    def relay_mark_unreachable(
        self, *, runtime: str, session_ref: str, container_ref: str,
        attempt_started_at: datetime,
    ) -> bool:
        attempted = _now(attempt_started_at)
        with self._begin_relay_immediate() as db:
            row = self._relay_session(db, container_ref=container_ref, runtime=runtime, session_ref=session_ref)
            if row is None:
                raise RelayNotFoundError("relay entity not found in the requested scope")
            if row.state != "active" or not (_now(row.last_seen_at) < attempted):
                return False
            row.state = "unreachable"
            return True

    def relay_mark_active(
        self, *, runtime: str, session_ref: str, container_ref: str,
        now: datetime | None = None,
    ) -> bool:
        current = _now(now)
        with self._begin_relay_immediate() as db:
            row = self._relay_session(db, container_ref=container_ref, runtime=runtime, session_ref=session_ref)
            if row is None:
                raise RelayNotFoundError("relay entity not found in the requested scope")
            changed = row.state != "active"
            row.state = "active"
            row.closed_at = None
            if _now(row.last_seen_at) < current:
                row.last_seen_at = current
            return changed

    def _relay_session(
        self,
        db,
        *,
        container_ref: str,
        runtime: str,
        session_ref: str,
    ) -> RelaySessionRecord | None:
        return db.execute(
            select(RelaySessionRecord).where(
                RelaySessionRecord.container_ref == container_ref,
                RelaySessionRecord.runtime == runtime,
                RelaySessionRecord.session_ref == session_ref,
            )
        ).scalar_one_or_none()

    @staticmethod
    def _relay_session_view(db, row: RelaySessionRecord, now: datetime, recent_seconds: int) -> dict[str, Any]:
        generation = db.get(RelayEndpointGenerationRecord, row.id)
        return _session_view(
            row, now, recent_seconds,
            int(generation.generation) if generation is not None else 0,
        )

    @staticmethod
    def _relay_session_by_endpoint(
        db, *, endpoint_id: str | None
    ) -> RelaySessionRecord | None:
        return None if endpoint_id is None else db.get(RelaySessionRecord, endpoint_id)

    def _relay_target(
        self,
        db,
        *,
        recipient_runtime: str | None,
        recipient_kind: str,
        recipient_value: str,
    ) -> RelaySessionRecord:
        if recipient_kind == "endpoint":
            target = self._relay_session_by_endpoint(db, endpoint_id=recipient_value)
        elif recipient_kind == "alias":
            binding = db.get(RelayAliasRecord, recipient_value)
            if binding is None:
                raise RelayNotFoundError("relay entity not found in the requested scope")
            if binding.endpoint_id is None:
                raise RelayConflictError(
                    "relay alias has unresolved legacy owners; use replace_existing=true to take it over"
                )
            target = self._relay_session_by_endpoint(db, endpoint_id=binding.endpoint_id)
            if (
                target is not None
                and recipient_runtime is not None
                and target.runtime != recipient_runtime
            ):
                raise RelayConflictError(
                    "relay alias belongs to a different runtime; address the global name as @alias"
                )
        else:
            matches = db.execute(
                select(RelaySessionRecord).where(
                    RelaySessionRecord.runtime == recipient_runtime,
                    RelaySessionRecord.session_ref == recipient_value,
                )
            ).scalars().all()
            if len(matches) > 1:
                raise RelayConflictError(
                    "legacy recipient is ambiguous; use the canonical relay-session endpoint ID"
                )
            target = matches[0] if matches else None

        if target is None:
            raise RelayNotFoundError("relay entity not found in the requested scope")
        if target.state == "unreachable":
            raise RelayConflictError("recipient session is unreachable")
        if target.state == "closed":
            raise RelayConflictError("recipient session is closed")
        if target.state != "active":
            raise RelayNotFoundError("relay entity not found in the requested scope")
        return target

    def relay_turn(
        self,
        *,
        runtime: str,
        session_ref: str,
        container_ref: str,
        title: str | None,
        max_chars: int,
        max_messages: int,
        lease_seconds: int,
        exact_delivery_id: str | None = None,
        max_response_chars: int = 0,
        register_session: bool = True,
        previous_container_ref: str | None = None,
        previous_endpoint_id: str | None = None,
        previous_scope_generation: int | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if not register_session and any(
            value is not None
            for value in (previous_container_ref, previous_endpoint_id, previous_scope_generation)
        ):
            raise RelayConflictError("scope transitions require session registration")

        current = _now(now)
        with self._begin_relay_immediate() as db:
            registered = self._relay_session(
                db, container_ref=container_ref, runtime=runtime, session_ref=session_ref
            )
            generation_row = (
                db.get(RelayEndpointGenerationRecord, registered.id)
                if registered is not None
                else None
            )
            generation = int(generation_row.generation) if generation_row is not None else 0
            if previous_container_ref is not None:
                if previous_endpoint_id is None or previous_scope_generation is None:
                    raise RelayConflictError("incomplete Relay scope transition")
                generation_row = db.get(RelayEndpointGenerationRecord, previous_endpoint_id)
                generation = int(generation_row.generation) if generation_row is not None else 0
                source = self._relay_session(db, container_ref=previous_container_ref, runtime=runtime, session_ref=session_ref)
                if container_ref == previous_container_ref:
                    if registered is None or registered.state not in {"active", "unreachable"} or registered.id != previous_endpoint_id or generation != previous_scope_generation:
                        raise RelayConflictError("stale or invalid Relay scope transition")
                elif registered is not None:
                    if registered.state != "active" or registered.id != previous_endpoint_id or generation != previous_scope_generation + 1:
                        raise RelayConflictError("Relay scope destination is occupied or stale")
                    if source is not None:
                        raise RelayConflictError("Relay scope transition is ambiguous")
                    generation = previous_scope_generation + 1
                else:
                    if source is None or source.id != previous_endpoint_id:
                        raise RelayNotFoundError("Relay transition source not found")
                    if source.state != "active":
                        raise RelayConflictError("Relay transition source is not active")
                    if generation != previous_scope_generation:
                        raise RelayConflictError("stale Relay scope generation")
                    source.container_ref = container_ref
                    generation = previous_scope_generation + 1
                    if generation_row is None:
                        db.add(RelayEndpointGenerationRecord(endpoint_id=source.id, generation=generation))
                    else:
                        generation_row.generation = generation
                    registered = source
            if registered is None and not register_session:
                return {
                    "session": None,
                    "deliveries": [],
                    "has_more": False,
                    "remaining_count": 0,
                }
            if registered is None:
                registered = RelaySessionRecord(
                    id=f"relay-session-{uuid.uuid4().hex}",
                    runtime=runtime,
                    session_ref=session_ref,
                    container_ref=container_ref,
                    title=title,
                    state="active",
                    first_seen_at=current,
                    last_seen_at=current,
                )
                db.add(registered)
                db.flush()
            else:
                if not register_session and registered.state != "active":
                    return {
                        "session": self._relay_session_view(db, registered, current, 24 * 60 * 60),
                        "deliveries": [],
                        "has_more": False,
                        "remaining_count": 0,
                    }
                if register_session:
                    registered.state = "active"
                    registered.closed_at = None
                    registered.last_seen_at = current
                    if title is not None:
                        registered.title = title

            db.execute(
                update(RelayDeliveryRecord)
                .where(
                    RelayDeliveryRecord.state.in_(("pending", "claimed")),
                    RelayDeliveryRecord.message_id.in_(
                        select(RelayMessageRecord.id).where(
                            RelayMessageRecord.expires_at <= current
                        )
                    ),
                )
                .values(state="expired", claim_token=None)
            )

            rows = db.execute(
                select(RelayDeliveryRecord, RelayMessageRecord)
                .join(RelayMessageRecord, RelayMessageRecord.id == RelayDeliveryRecord.message_id)
                .where(
                    RelayDeliveryRecord.recipient_endpoint_id == registered.id,
                    RelayMessageRecord.expires_at > current,
                    or_(
                        RelayDeliveryRecord.state == "pending",
                        and_(
                            RelayDeliveryRecord.state == "claimed",
                            RelayDeliveryRecord.lease_expires_at <= current,
                        ),
                    ),
                )
                .order_by(RelayMessageRecord.created_at, RelayDeliveryRecord.id)
            ).all()

            eligible_rows = [
                (delivery, message)
                for delivery, message in rows
                if _delivery_render_safe(delivery, message)
                and (
                    exact_delivery_id is None
                    or delivery.id == exact_delivery_id
                )
            ]
            session_view = _session_view(registered, current, 24 * 60 * 60, generation)
            selected: list[tuple[RelayDeliveryRecord, RelayMessageRecord, dict[str, Any], int, str]] = []
            used = 0

            def response(deliveries: list[dict[str, Any]]) -> dict[str, Any]:
                remaining = len(rows) - len(deliveries)
                return {
                    "session": session_view,
                    "deliveries": deliveries,
                    "has_more": remaining > 0,
                    "remaining_count": remaining,
                }

            for delivery, message in eligible_rows:
                token = f"relay-claim-{uuid.uuid4().hex}"
                lease_expires_at = current + timedelta(seconds=lease_seconds)

                def project(prefix_chars: int) -> tuple[dict[str, Any], int] | None:
                    view = _delivery_view(
                        delivery, message, registered.state,
                        payload_limit=None if prefix_chars == len(message.payload) else prefix_chars,
                    )
                    view.update(
                        state="claimed",
                        claim_token=token,
                        receipt=_delivery_receipt(token),
                        claimed_at=_iso(current),
                        lease_expires_at=_iso(lease_expires_at),
                        attempts=int(delivery.attempts or 0) + 1,
                    )
                    rendered_chars = len(_delivery_text(delivery, message, view)) + (2 if selected else 0)
                    if max_chars and used + rendered_chars > max_chars:
                        return None
                    prospective = [*(item[2] for item in selected), view]
                    if max_response_chars and _compact_json_chars(response(prospective)) > max_response_chars:
                        return None
                    return view, rendered_chars

                projected = project(len(message.payload))
                if projected is None and not selected and len(message.payload) > 1:
                    low, high = 1, len(message.payload) - 1
                    while low <= high:
                        middle = (low + high) // 2
                        candidate = project(middle)
                        if candidate is None:
                            high = middle - 1
                        else:
                            projected = candidate
                            low = middle + 1
                if projected is None:
                    continue
                view, rendered_chars = projected
                selected.append((delivery, message, view, rendered_chars, token))
                used += rendered_chars
                if max_messages and len(selected) >= max_messages:
                    break

            claimed: list[dict[str, Any]] = []
            for delivery, message, view, _, token in selected:
                delivery.state = "claimed"
                delivery.claim_token = token
                delivery.claimed_at = current
                delivery.lease_expires_at = current + timedelta(seconds=lease_seconds)
                delivery.attempts = int(delivery.attempts or 0) + 1
                claimed.append(_delivery_view(
                    delivery, message, registered.state,
                    payload_limit=len(view["payload"]) if view["content_truncated"] else None,
                ))

            return response(claimed)

    def relay_refresh_structural_work_refs(
        self,
        *,
        runtime: str,
        session_ref: str,
        container_ref: str,
        work_refs: list[dict[str, str]],
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        current = _now(now)
        with self._begin_relay_immediate() as db:
            session = self._relay_session(
                db, container_ref=container_ref, runtime=runtime, session_ref=session_ref
            )
            if session is None or session.state != "active":
                raise RelayNotFoundError("relay entity not found in the requested scope")
            existing = db.execute(
                select(RelaySessionWorkRefRecord).where(
                    RelaySessionWorkRefRecord.endpoint_id == session.id,
                    RelaySessionWorkRefRecord.origin == "structural",
                )
            ).scalars().all()
            created_at = {row.work_ref: row.created_at for row in existing}
            db.execute(
                delete(RelaySessionWorkRefRecord).where(
                    RelaySessionWorkRefRecord.endpoint_id == session.id,
                    RelaySessionWorkRefRecord.origin == "structural",
                )
            )
            for position, work_ref in enumerate(work_refs):
                db.add(RelaySessionWorkRefRecord(
                    endpoint_id=session.id,
                    work_ref=work_ref["work_ref"],
                    origin="structural",
                    scope_ref=work_ref["scope_ref"],
                    local_ref=work_ref["local_ref"],
                    position=position,
                    created_at=created_at.get(work_ref["work_ref"], current),
                    updated_at=current,
                ))
            db.flush()
            return self._relay_session_work_ref_views(db, session.id)

    @staticmethod
    def _relay_session_work_ref_views(db, endpoint_id: str) -> list[dict[str, Any]]:
        rows = db.execute(
            select(RelaySessionWorkRefRecord)
            .where(RelaySessionWorkRefRecord.endpoint_id == endpoint_id)
            .order_by(
                RelaySessionWorkRefRecord.origin.desc(),
                RelaySessionWorkRefRecord.position,
                RelaySessionWorkRefRecord.created_at,
            )
        ).scalars().all()
        return [_work_ref_view(row) for row in rows]

    def relay_session_work_refs(
        self,
        *,
        runtime: str,
        session_ref: str,
        container_ref: str,
    ) -> dict[str, Any]:
        with self._relay_session_factory() as db:
            session = self._relay_session(
                db, container_ref=container_ref, runtime=runtime, session_ref=session_ref
            )
            if session is None:
                raise RelayNotFoundError("relay entity not found in the requested scope")
            return {
                "session": self._relay_session_view(db, session, _now(), 24 * 60 * 60),
                "work_refs": self._relay_session_work_ref_views(db, session.id),
            }

    def relay_attach_work_ref(
        self,
        *,
        runtime: str,
        session_ref: str,
        container_ref: str,
        work_ref: dict[str, str],
        now: datetime | None = None,
        allow_closed: bool = False,
    ) -> dict[str, Any]:
        current = _now(now)
        with self._begin_relay_immediate() as db:
            session = self._relay_session(
                db, container_ref=container_ref, runtime=runtime, session_ref=session_ref
            )
            if session is None:
                raise RelayNotFoundError("relay entity not found in the requested scope")
            if session.state == "closed" and not allow_closed:
                raise RelayConflictError("relay session is closed")
            row = db.get(
                RelaySessionWorkRefRecord,
                (session.id, work_ref["work_ref"], "explicit"),
            )
            if row is None:
                explicit_count = len(db.execute(
                    select(RelaySessionWorkRefRecord).where(
                        RelaySessionWorkRefRecord.endpoint_id == session.id,
                        RelaySessionWorkRefRecord.origin == "explicit",
                    )
                ).scalars().all())
                if explicit_count >= _MAX_EXPLICIT_WORK_REFS:
                    raise RelayConflictError(
                        "association_limit: at most 3 explicit work references; detach one before attaching another"
                    )
                row = RelaySessionWorkRefRecord(
                    endpoint_id=session.id,
                    work_ref=work_ref["work_ref"],
                    origin="explicit",
                    scope_ref=work_ref["scope_ref"],
                    local_ref=work_ref["local_ref"],
                    position=None,
                    created_at=current,
                    updated_at=current,
                )
                db.add(row)
            else:
                row.scope_ref = work_ref["scope_ref"]
                row.local_ref = work_ref["local_ref"]
                row.updated_at = current
            db.flush()
            return {
                "session": self._relay_session_view(db, session, current, 24 * 60 * 60),
                "attached": _work_ref_view(row),
                "work_refs": self._relay_session_work_ref_views(db, session.id),
            }

    def relay_detach_work_ref(
        self,
        *,
        runtime: str,
        session_ref: str,
        container_ref: str,
        work_ref: str,
        allow_closed: bool = False,
    ) -> dict[str, Any]:
        with self._begin_relay_immediate() as db:
            session = self._relay_session(
                db, container_ref=container_ref, runtime=runtime, session_ref=session_ref
            )
            if session is None:
                raise RelayNotFoundError("relay entity not found in the requested scope")
            if session.state == "closed" and not allow_closed:
                raise RelayConflictError("relay session is closed")
            row = db.get(RelaySessionWorkRefRecord, (session.id, work_ref, "explicit"))
            detached = row is not None
            if row is not None:
                db.delete(row)
                db.flush()
            remaining = self._relay_session_work_ref_views(db, session.id)
            return {
                "session": self._relay_session_view(db, session, _now(), 24 * 60 * 60),
                "detached": detached,
                "structural_remains": any(
                    item["work_ref"] == work_ref and item["origin"] == "structural"
                    for item in remaining
                ),
                "work_refs": remaining,
            }

    def relay_session_scope_by_endpoint(self, endpoint_id: str) -> dict[str, str]:
        with self._relay_session_factory() as db:
            session = db.get(RelaySessionRecord, endpoint_id)
            if session is None:
                raise RelayNotFoundError("relay endpoint not found")
            return {
                "runtime": session.runtime,
                "session_ref": session.session_ref,
                "container_ref": session.container_ref,
            }
    def relay_work_ref_participants(
        self,
        *,
        work_ref: str,
        include_closed: bool,
        container_ref: str | None,
        offset: int,
        limit: int,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        current = _now(now)
        with self._relay_session_factory() as db:
            page = (
                select(
                    RelaySessionRecord.id.label("endpoint_id"),
                    RelaySessionRecord.last_seen_at.label("last_seen_at"),
                )
                .join(
                    RelaySessionWorkRefRecord,
                    RelaySessionWorkRefRecord.endpoint_id == RelaySessionRecord.id,
                )
                .where(RelaySessionWorkRefRecord.work_ref == work_ref)
                .group_by(RelaySessionRecord.id, RelaySessionRecord.last_seen_at)
            )
            if not include_closed:
                page = page.where(RelaySessionRecord.state != "closed")
            if container_ref is not None:
                page = page.where(RelaySessionRecord.container_ref == container_ref)
            page = page.order_by(
                RelaySessionRecord.last_seen_at.desc(),
                RelaySessionRecord.id,
            ).offset(offset).limit(limit).subquery()
            statement = (
                select(RelaySessionRecord, RelaySessionWorkRefRecord)
                .join(page, page.c.endpoint_id == RelaySessionRecord.id)
                .join(
                    RelaySessionWorkRefRecord,
                    and_(
                        RelaySessionWorkRefRecord.endpoint_id == RelaySessionRecord.id,
                        RelaySessionWorkRefRecord.work_ref == work_ref,
                    ),
                )
                .order_by(
                    page.c.last_seen_at.desc(),
                    RelaySessionRecord.id,
                    RelaySessionWorkRefRecord.origin,
                )
            )
            grouped = []
            for session, association in db.execute(statement).all():
                if not grouped or grouped[-1][0].id != session.id:
                    grouped.append((session, [association]))
                else:
                    grouped[-1][1].append(association)
            result = []
            for session, associations in grouped:
                association = associations[0]
                session_view = self._relay_session_view(db, session, current, 24 * 60 * 60)
                result.append({
                    **session_view,
                    "state": session.state,
                    "lifecycle": session_view["state"],
                    "container_ref": session.container_ref,
                    "association": {
                        "work_ref": association.work_ref,
                        "scope_ref": association.scope_ref,
                        "local_ref": association.local_ref,
                        "origins": sorted(row.origin for row in associations),
                        "created_at": _iso(min(row.created_at for row in associations)),
                        "updated_at": _iso(max(row.updated_at for row in associations)),
                    },
                })
            return result

    def relay_close_session(
        self,
        *,
        runtime: str,
        session_ref: str,
        container_ref: str,
    ) -> dict[str, Any]:
        current = _now()
        with self._begin_relay_immediate() as db:
            row = self._relay_session(
                db, container_ref=container_ref, runtime=runtime, session_ref=session_ref
            )
            if row is None:
                raise RelayNotFoundError("relay entity not found in the requested scope")
            row.state = "closed"
            row.closed_at = current
            if row.alias is not None:
                binding = db.get(RelayAliasRecord, row.alias)
                if binding is not None and binding.endpoint_id == row.id:
                    db.delete(binding)
            row.alias = None
            return self._relay_session_view(db, row, current, 24 * 60 * 60)
    def relay_list_sessions(
        self,
        *,
        container_ref: str,
        runtime: str | None,
        session_ref: str | None,
        include_inactive: bool,
        recent_seconds: int,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        current = _now(now)
        cutoff = current - timedelta(seconds=recent_seconds)

        def run(db):
            if session_ref is not None:
                if runtime is None:
                    raise ValueError("runtime is required when session_ref is supplied")
                row = self._relay_session(
                    db,
                    container_ref=container_ref,
                    runtime=runtime,
                    session_ref=session_ref,
                )
                if row is None or (
                    not include_inactive
                    and (row.state != "active" or _now(row.last_seen_at) < cutoff)
                ):
                    return []
                return [self._relay_session_view(db, row, current, recent_seconds)]
            statement = select(RelaySessionRecord).where(
                RelaySessionRecord.container_ref == container_ref,
            )
            if runtime is not None:
                statement = statement.where(RelaySessionRecord.runtime == runtime)
            if not include_inactive:
                statement = statement.where(
                    RelaySessionRecord.state == "active",
                    RelaySessionRecord.last_seen_at >= cutoff,
                )
            rows = db.execute(
                statement.order_by(RelaySessionRecord.runtime, RelaySessionRecord.last_seen_at.desc())
            ).scalars().all()
            return [self._relay_session_view(db, row, current, recent_seconds) for row in rows]

        with self._relay_session_factory() as db:
            return run(db)

    def relay_name_session(
        self,
        *,
        runtime: str,
        session_ref: str,
        container_ref: str,
        alias: str | None,
        replace_existing: bool,
    ) -> dict[str, Any]:
        current = _now()
        try:
            with self._begin_relay_immediate() as db:
                row = self._relay_session(
                    db, container_ref=container_ref, runtime=runtime, session_ref=session_ref
                )
                if row is None:
                    raise RelayNotFoundError("relay entity not found in the requested scope")
                if row.state == "closed":
                    raise RelayConflictError("closed sessions cannot be named")

                old_alias = row.alias
                if alias is not None:
                    binding = db.get(RelayAliasRecord, alias)
                    other_owners = db.execute(
                        select(RelaySessionRecord).where(
                            RelaySessionRecord.alias == alias,
                            RelaySessionRecord.id != row.id,
                        )
                    ).scalars().all()
                    if (
                        (binding is not None and binding.endpoint_id != row.id)
                        or other_owners
                    ) and not replace_existing:
                        raise RelayConflictError(
                            "relay alias is already assigned; ask the user before retrying with replace_existing=true"
                        )
                    if old_alias != alias and old_alias is not None:
                        old_binding = db.get(RelayAliasRecord, old_alias)
                        if old_binding is not None and old_binding.endpoint_id == row.id:
                            db.delete(old_binding)
                    for previous in other_owners:
                        previous.alias = None
                    if other_owners:
                        db.flush()
                    if binding is None:
                        db.add(
                            RelayAliasRecord(
                                alias=alias,
                                endpoint_id=row.id,
                            )
                        )
                    else:
                        binding.endpoint_id = row.id
                    row.alias = alias
                else:
                    if old_alias is not None:
                        binding = db.get(RelayAliasRecord, old_alias)
                        if binding is not None and binding.endpoint_id == row.id:
                            db.delete(binding)
                    row.alias = None
                db.flush()
                return self._relay_session_view(db, row, current, 24 * 60 * 60)
        except IntegrityError as exc:
            raise RelayConflictError(
                "relay alias is already assigned; ask the user before retrying with replace_existing=true"
            ) from exc
    def relay_send(
        self,
        *,
        message_id: str,
        sender_runtime: str,
        sender_session_ref: str,
        recipient: str,
        recipient_runtime: str | None,
        recipient_kind: str,
        recipient_value: str,
        payload: str,
        redacted: bool,
        container_ref: str,
        expires_in_seconds: int | None,
        in_reply_to: str | None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = _now(now)
        with self._begin_relay_immediate() as db:
            sender = self._relay_session(
                db,
                container_ref=container_ref,
                runtime=sender_runtime,
                session_ref=sender_session_ref,
            )
            if sender is None:
                raise RelayNotFoundError("relay entity not found in the requested scope")
            if sender.state == "closed":
                raise RelayConflictError("closed sessions cannot send relay messages")

            if in_reply_to is not None:
                parent = db.get(RelayMessageRecord, in_reply_to)
                if parent is None:
                    raise RelayNotFoundError("relay entity not found in the requested scope")

            existing_message = db.get(RelayMessageRecord, message_id)
            if existing_message is not None:
                same_legacy_sender = (
                    existing_message.sender_endpoint_id is None
                    and existing_message.container_ref == container_ref
                    and existing_message.sender_runtime == sender_runtime
                    and existing_message.sender_session_ref == sender_session_ref
                )
                if (
                    (existing_message.sender_endpoint_id == sender.id or same_legacy_sender)
                    and existing_message.recipient_selector == recipient
                    and existing_message.payload == payload
                    and bool(existing_message.redacted) == bool(redacted)
                    and existing_message.in_reply_to == in_reply_to
                    and _expiry_matches(existing_message, expires_in_seconds)
                ):
                    return self._relay_status_in_session(db, existing_message, current)
                raise RelayConflictError("message_id is already in use")

            target = self._relay_target(
                db,
                recipient_runtime=recipient_runtime,
                recipient_kind=recipient_kind,
                recipient_value=recipient_value,
            )
            message = RelayMessageRecord(
                id=message_id,
                sender_runtime=sender_runtime,
                sender_session_ref=sender_session_ref,
                sender_endpoint_id=sender.id,
                recipient_selector=recipient,
                container_ref=sender.container_ref,
                payload=payload,
                redacted=1 if redacted else 0,
                in_reply_to=in_reply_to,
                created_at=current,
                expires_at=_expiry_at(current, expires_in_seconds),
            )
            db.add(message)
            db.flush()
            db.add(
                RelayDeliveryRecord(
                    id=f"relay-delivery-{uuid.uuid4().hex}",
                    message_id=message.id,
                    recipient_runtime=target.runtime,
                    recipient_session_ref=target.session_ref,
                    recipient_endpoint_id=target.id,
                    recipient_container_ref=target.container_ref,
                    state="pending",
                    attempts=0,
                    trace_version=1,
                )
            )
            db.flush()
            return self._relay_status_in_session(db, message, current)
    def relay_reply_atomic(
        self,
        *,
        delivery_id: str,
        receipt: str | None,
        reply_message_id: str,
        payload: str,
        redacted: bool,
        container_ref: str,
        expires_in_seconds: int | None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Validate, create reply, and optionally ACK the delivery in one transaction."""
        current = _now(now)
        expired = False

        def run(db):
            nonlocal expired
            row = db.execute(
                select(RelayDeliveryRecord, RelayMessageRecord)
                .join(RelayMessageRecord, RelayMessageRecord.id == RelayDeliveryRecord.message_id)
                .where(RelayDeliveryRecord.id == delivery_id)
            ).one_or_none()
            if row is None:
                raise RelayNotFoundError("relay entity not found in the requested scope")
            delivery, message = row

            if delivery.state == "claimed":
                if _now(message.expires_at) <= current:
                    delivery.state = "expired"
                    delivery.claim_token = None
                    expired = True
                    return None
                if delivery.lease_expires_at is None or _now(delivery.lease_expires_at) <= current:
                    raise RelayConflictError("claim lease has expired")
                if receipt is None:
                    raise RelayConflictError("receipt required when replying from claimed state")
                if not hmac.compare_digest(_delivery_receipt(delivery.claim_token) or "", receipt):
                    raise RelayConflictError("receipt does not match current claim")
            elif delivery.state == "delivered":
                expected = _delivery_receipt(delivery.claim_token)
                if receipt is not None and (
                    expected is None or not hmac.compare_digest(expected, receipt)
                ):
                    raise RelayConflictError("receipt does not match delivered claim")
            else:
                raise RelayConflictError("only claimed or delivered relay messages can be replied to")

            sender = self._relay_session_by_endpoint(
                db, endpoint_id=delivery.recipient_endpoint_id
            )
            if sender is None:
                raise RelayConflictError("legacy delivery has no canonical recipient endpoint")
            if sender.state != "active":
                raise RelayConflictError("closed or unreachable sessions cannot reply")

            existing = db.get(RelayMessageRecord, reply_message_id)
            if existing is not None:
                if (
                    existing.payload != payload
                    or bool(existing.redacted) != redacted
                    or not _expiry_matches(existing, expires_in_seconds)
                ):
                    raise RelayConflictError("reply already exists with different parameters")
                return self._relay_status_in_session(db, existing, current)

            recipient_session = self._relay_session_by_endpoint(
                db, endpoint_id=message.sender_endpoint_id
            )
            if recipient_session is None:
                raise RelayConflictError("legacy message has no canonical sender endpoint")
            if recipient_session.state == "unreachable":
                raise RelayConflictError("recipient session is unreachable")
            if recipient_session.state == "closed":
                raise RelayConflictError("recipient session is closed")
            if recipient_session.state != "active":
                raise RelayNotFoundError("relay entity not found in the requested scope")

            reply_msg = RelayMessageRecord(
                id=reply_message_id,
                sender_runtime=sender.runtime,
                sender_session_ref=sender.session_ref,
                sender_endpoint_id=sender.id,
                recipient_selector=recipient_session.id,
                container_ref=sender.container_ref,
                payload=payload,
                redacted=1 if redacted else 0,
                in_reply_to=message.id,
                created_at=current,
                expires_at=_expiry_at(current, expires_in_seconds),
            )
            db.add(reply_msg)
            db.flush()
            db.add(
                RelayDeliveryRecord(
                    id=f"relay-delivery-{uuid.uuid4().hex}",
                    message_id=reply_message_id,
                    recipient_runtime=recipient_session.runtime,
                    recipient_session_ref=recipient_session.session_ref,
                    recipient_endpoint_id=recipient_session.id,
                    recipient_container_ref=recipient_session.container_ref,
                    state="pending",
                    attempts=0,
                    trace_version=1,
                )
            )
            db.flush()
            if delivery.state == "claimed":
                delivery.state = "delivered"
                delivery.delivered_at = current
            return self._relay_status_in_session(db, reply_msg, current)

        with self._begin_relay_immediate() as db:
            result = run(db)
        if expired:
            raise RelayConflictError("message has expired")
        return result

    def _relay_status_in_session(
        self, db, message: RelayMessageRecord, current: datetime,
        *, payload_offset: int = 0, payload_limit: int | None = None,
    ) -> dict[str, Any]:
        if _now(message.expires_at) <= current:
            db.execute(
                update(RelayDeliveryRecord)
                .where(
                    RelayDeliveryRecord.message_id == message.id,
                    RelayDeliveryRecord.state.in_(("pending", "claimed")),
                )
                .values(state="expired", claim_token=None)
            )
        payload = _payload_view(message.payload, offset=payload_offset, limit=payload_limit)
        deliveries = db.execute(
            select(RelayDeliveryRecord)
            .where(RelayDeliveryRecord.message_id == message.id)
            .order_by(RelayDeliveryRecord.recipient_runtime, RelayDeliveryRecord.recipient_session_ref)
        ).scalars().all()
        return {
            "message_id": message.id,
            "sender_runtime": message.sender_runtime,
            "sender_session_ref": message.sender_session_ref,
            "sender_endpoint_id": message.sender_endpoint_id,
            "recipient": message.recipient_selector,
            **payload,
            "redacted": bool(message.redacted),
            "in_reply_to": message.in_reply_to,
            "created_at": _iso(message.created_at),
            "expires_at": _expiry_iso(message.expires_at),
            "deliveries": [
                _delivery_view(
                    row,
                    message,
                    (
                        session.state
                        if (session := self._relay_session_by_endpoint(
                            db,
                            endpoint_id=row.recipient_endpoint_id,
                        )) is not None and session.state != "closed"
                        else None
                    ),
                    payload_offset=payload_offset,
                    payload_limit=payload_limit,
                )
                for row in deliveries
            ],
        }

    def relay_pending_candidate(
        self,
        *,
        runtime: str,
        session_ref: str,
        container_ref: str,
        delivery_id: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        """Read exact-scope Relay state without claiming, ACKing, or admitting a turn."""
        current = _now(now)
        with self._relay_session_factory() as db:
            session = self._relay_session(
                db,
                container_ref=container_ref,
                runtime=runtime,
                session_ref=session_ref,
            )
            if session is None:
                return None
            statement = (
                select(RelayDeliveryRecord, RelayMessageRecord)
                .join(RelayMessageRecord, RelayMessageRecord.id == RelayDeliveryRecord.message_id)
                .where(
                    RelayDeliveryRecord.recipient_endpoint_id == session.id,
                )
                .order_by(RelayMessageRecord.created_at, RelayDeliveryRecord.id)
            )
            if delivery_id is not None:
                statement = statement.where(RelayDeliveryRecord.id == delivery_id)
            else:
                statement = statement.where(
                    RelayMessageRecord.expires_at > current,
                    or_(
                        RelayDeliveryRecord.state == "pending",
                        and_(
                            RelayDeliveryRecord.state == "claimed",
                            RelayDeliveryRecord.lease_expires_at.is_not(None),
                            RelayDeliveryRecord.lease_expires_at <= current,
                        ),
                    ),
                )
            rows = db.execute(statement)
            row = next(
                (
                    candidate for candidate in rows
                    if delivery_id is not None or _render_safe(candidate[1].payload)
                ),
                None,
            )
            if row is None:
                return None
            delivery, message = row
            state = "expired" if _now(message.expires_at) <= current and delivery.state in {"pending", "claimed"} else ("pending" if delivery.state == "claimed" and delivery.lease_expires_at is not None and _now(delivery.lease_expires_at) <= current else delivery.state)
            return {
                "delivery_id": delivery.id,
                "state": state,
                "recipient_endpoint_id": session.id,
            }

    @staticmethod
    def _relay_codex_wake_reservation_state(
        db, *, delivery_id: str, current: datetime
    ) -> dict[str, Any]:
        row = db.execute(
            select(RelayDeliveryRecord, RelayMessageRecord)
            .join(
                RelayMessageRecord,
                RelayMessageRecord.id == RelayDeliveryRecord.message_id,
            )
            .where(RelayDeliveryRecord.id == delivery_id)
        ).one_or_none()
        if row is None:
            raise RelayNotFoundError(
                "relay entity not found in the requested scope"
            )
        delivery, message = row
        state = delivery.state
        if (
            state in {"pending", "claimed"}
            and _now(message.expires_at) <= current
        ):
            state = "expired"
        elif (
            state == "claimed"
            and delivery.lease_expires_at is not None
            and _now(delivery.lease_expires_at) <= current
        ):
            state = "pending"
        session = db.get(RelaySessionRecord, delivery.recipient_endpoint_id)
        wake_target = None
        if (
            session is not None
            and session.state == "active"
            and session.runtime == "codex"
            and delivery.recipient_runtime == "codex"
            and _render_safe(message.payload)
        ):
            wake_target = {
                "runtime": session.runtime,
                "session_ref": session.session_ref,
                "container_ref": session.container_ref,
            }
        return {
            "delivery_id": delivery.id,
            "recipient_endpoint_id": delivery.recipient_endpoint_id,
            "state": state,
            "stored_state": delivery.state,
            "attempts": int(delivery.attempts or 0),
            "wake_target": wake_target,
        }

    def relay_codex_wake_reservation_state(
        self,
        *,
        delivery_id: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Read exact payload-free state without mutable session scope."""
        with self._relay_session_factory() as db:
            return self._relay_codex_wake_reservation_state(
                db, delivery_id=delivery_id, current=_now(now)
            )

    def relay_reconcile_codex_wake_reservation(
        self,
        *,
        delivery_id: str,
        decision: Callable[[dict[str, Any]], bool],
        now: datetime | None = None,
    ) -> bool:
        """Evaluate and replace a wake fence while blocking Relay claims."""
        with self._begin_relay_immediate() as db:
            state = self._relay_codex_wake_reservation_state(
                db, delivery_id=delivery_id, current=_now(now)
            )
            return decision(state) is True

    def relay_wake_candidates(
        self,
        *,
        delivery_id: str | None = None,
        now: datetime | None = None,
        include_pending: bool = True,
    ) -> list[dict[str, Any]]:
        """Return one safe wake candidate per active exact session without mutation."""
        current = _now(now)
        with self._relay_session_factory() as db:
            statement = (
                select(RelayDeliveryRecord, RelayMessageRecord, RelaySessionRecord)
                .join(
                    RelayMessageRecord,
                    RelayMessageRecord.id == RelayDeliveryRecord.message_id,
                )
                .join(
                    RelaySessionRecord,
                    and_(
                        RelaySessionRecord.id == RelayDeliveryRecord.recipient_endpoint_id,
                    ),
                )
                .where(
                    RelayDeliveryRecord.recipient_runtime.in_(("codex", "claude-code")),
                    or_(
                        RelayDeliveryRecord.state == "pending",
                        and_(
                            RelayDeliveryRecord.state == "claimed",
                            RelayDeliveryRecord.lease_expires_at.is_not(None),
                            RelayDeliveryRecord.lease_expires_at <= current,
                        ),
                    ) if include_pending else and_(
                        RelayDeliveryRecord.state == "claimed",
                        RelayDeliveryRecord.lease_expires_at.is_not(None),
                        RelayDeliveryRecord.lease_expires_at <= current,
                    ),
                    RelayMessageRecord.expires_at > current,
                    RelaySessionRecord.state == "active",
                )
                .order_by(RelayMessageRecord.created_at, RelayDeliveryRecord.id)
            )
            if delivery_id is not None:
                statement = statement.where(RelayDeliveryRecord.id == delivery_id)

            candidates: list[dict[str, Any]] = []
            seen: set[str] = set()
            for delivery, message, session in db.execute(statement):
                if not _render_safe(message.payload):
                    continue
                key = session.id
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(
                    {
                        "delivery_id": delivery.id,
                        "state": "pending",
                        "recipient_endpoint_id": session.id,
                        "recipient_runtime": session.runtime,
                        "recipient_session_ref": session.session_ref,
                        "container_ref": session.container_ref,
                    }
                )
            return candidates

    def relay_expired_claim_candidates(
        self,
        *,
        delivery_id: str | None = None,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Compatibility query for strict expired-claim recovery."""
        return self.relay_wake_candidates(
            delivery_id=delivery_id,
            now=now,
            include_pending=False,
        )

    def relay_message_status(
        self,
        *,
        message_id: str,
        container_ref: str,
        offset: int | None = None,
        page_size: int | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = _now(now)
        with self._begin_relay_immediate() as db:
            message = db.get(RelayMessageRecord, message_id)
            if message is None:
                raise RelayNotFoundError("relay entity not found in the requested scope")
            return self._relay_status_in_session(
                db, message, current,
                payload_offset=offset or 0,
                payload_limit=page_size,
            )

    def relay_ack_by_receipt(
        self,
        *,
        delivery_id: str,
        receipt: str,
        container_ref: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """ACK a claimed delivery using the receipt returned at claim time.

        receipt = sha256(claim_token)[:32] — proves the caller received this specific
        claim generation. If the lease expired and the delivery was re-claimed, the
        receipt from the stale claim will not match the new claim_token → 409.
        Idempotent: returns success if already delivered.
        """
        current = _now(now)
        with self._begin_relay_immediate() as db:
            row = db.execute(
                select(RelayDeliveryRecord, RelayMessageRecord)
                .join(RelayMessageRecord, RelayMessageRecord.id == RelayDeliveryRecord.message_id)
                .where(RelayDeliveryRecord.id == delivery_id)
            ).one_or_none()
            if row is None:
                raise RelayNotFoundError("relay entity not found in the requested scope")
            delivery, message = row
            if delivery.state == "delivered":
                expected = _delivery_receipt(delivery.claim_token)
                if expected is None or not hmac.compare_digest(expected, receipt):
                    raise RelayConflictError("receipt does not match delivered claim")
                return {
                    "delivery_id": delivery.id,
                    "state": "delivered",
                    "delivered_at": _iso(delivery.delivered_at),
                    "already_delivered": True,
                    "recipient_endpoint_id": delivery.recipient_endpoint_id,
                    "recipient_runtime": delivery.recipient_runtime,
                    "recipient_session_ref": delivery.recipient_session_ref,
                    "recipient_container_ref": delivery.recipient_container_ref,
                }
            if delivery.state != "claimed":
                raise RelayConflictError("delivery is not in claimed state")
            if _now(message.expires_at) <= current:
                delivery.state = "expired"
                delivery.claim_token = None
                expired = True
            else:
                expired = False
                if delivery.lease_expires_at is None or _now(delivery.lease_expires_at) <= current:
                    raise RelayConflictError("claim lease has expired")
                if not hmac.compare_digest(_delivery_receipt(delivery.claim_token) or "", receipt):
                    raise RelayConflictError("receipt does not match current claim")
                delivery.state = "delivered"
                delivery.delivered_at = current
                result = {
                    "delivery_id": delivery.id,
                    "state": "delivered",
                    "delivered_at": _iso(current),
                    "already_delivered": False,
                    "recipient_endpoint_id": delivery.recipient_endpoint_id,
                    "recipient_runtime": delivery.recipient_runtime,
                    "recipient_session_ref": delivery.recipient_session_ref,
                    "recipient_container_ref": delivery.recipient_container_ref,
                }
        if expired:
            raise RelayConflictError("message has expired")
        return result

    def relay_ack(
        self,
        *,
        delivery_id: str,
        claim_token: str,
        container_ref: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = _now(now)
        with self._begin_relay_immediate() as db:
            row = db.execute(
                select(RelayDeliveryRecord, RelayMessageRecord)
                .join(RelayMessageRecord, RelayMessageRecord.id == RelayDeliveryRecord.message_id)
                .where(RelayDeliveryRecord.id == delivery_id)
            ).one_or_none()
            if row is None:
                raise RelayNotFoundError("relay entity not found in the requested scope")
            delivery, message = row
            if delivery.state == "delivered":
                if delivery.claim_token == claim_token:
                    return {
                        "delivery_id": delivery.id,
                        "state": "delivered",
                        "delivered_at": _iso(delivery.delivered_at),
                        "already_delivered": True,
                        "recipient_endpoint_id": delivery.recipient_endpoint_id,
                        "recipient_runtime": delivery.recipient_runtime,
                        "recipient_session_ref": delivery.recipient_session_ref,
                        "recipient_container_ref": delivery.recipient_container_ref,
                    }
                raise RelayConflictError("claim token is stale")
            if delivery.state != "claimed" or delivery.claim_token != claim_token:
                raise RelayConflictError("claim token is stale")
            if _now(message.expires_at) <= current:
                delivery.state = "expired"
                delivery.claim_token = None
                expired = True
            else:
                expired = False
                if delivery.lease_expires_at is None or _now(delivery.lease_expires_at) <= current:
                    raise RelayConflictError("claim token is stale")
                delivery.state = "delivered"
                delivery.delivered_at = current
                result = {
                    "delivery_id": delivery.id,
                    "state": "delivered",
                    "delivered_at": _iso(current),
                    "already_delivered": False,
                    "recipient_endpoint_id": delivery.recipient_endpoint_id,
                    "recipient_runtime": delivery.recipient_runtime,
                    "recipient_session_ref": delivery.recipient_session_ref,
                    "recipient_container_ref": delivery.recipient_container_ref,
                }
        if expired:
            raise RelayConflictError("message has expired")
        return result

    def relay_trace_record(
        self,
        *,
        attempt_id: str,
        delivery_id: str,
        stage: str,
        outcome: str | None = None,
        reason: str | None = None,
        evidence: list[str] | tuple[str, ...] | None = None,
        native_retry_safe: bool | None = None,
        destination_health_update: str | None = None,
        scope_generation: int | None = None,
        recorded_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Append one immutable diagnostic fact without correctness-path retries."""
        if not isinstance(attempt_id, str) or not _TRACE_ATTEMPT_RE.fullmatch(attempt_id):
            raise ValueError("invalid trace attempt_id")
        if not isinstance(delivery_id, str) or not _REPAIR_DELIVERY_RE.fullmatch(delivery_id):
            raise ValueError("invalid trace delivery_id")
        if stage not in _TRACE_STAGES:
            raise ValueError("invalid trace stage")
        if scope_generation is not None and (
            type(scope_generation) is not int or scope_generation < 0
        ):
            raise ValueError("invalid trace scope_generation")
        result_fields = (
            outcome,
            reason,
            evidence,
            native_retry_safe,
            destination_health_update,
        )
        if stage != "completed" and any(value is not None for value in result_fields):
            raise ValueError("activation result is only valid for completed trace")
        safe_reason = redact_sensitive(reason) if isinstance(reason, str) else reason
        if isinstance(safe_reason, str) and len(safe_reason) > 128:
            safe_reason = _TRACE_REDACTED_REASON
        if stage == "completed":
            if outcome not in _TRACE_OUTCOMES:
                raise ValueError("completed trace requires a valid outcome")
            if (
                not isinstance(safe_reason, str)
                or not 0 < len(safe_reason) <= 128
                or not _single_line_render_safe(safe_reason)
            ):
                raise ValueError("completed trace requires a bounded safe reason")
            if (
                not isinstance(evidence, (list, tuple))
                or len(evidence) > 3
                or len(set(evidence)) != len(evidence)
                or any(item not in _TRACE_EVIDENCE for item in evidence)
                or type(native_retry_safe) is not bool
                or destination_health_update not in {None, "unreachable"}
            ):
                raise ValueError("invalid completed trace result")
        if recorded_at is not None and not isinstance(recorded_at, datetime):
            raise ValueError("invalid trace recorded_at")

        evidence_json = (
            json.dumps(list(evidence), separators=(",", ":"))
            if evidence is not None
            else None
        )
        current = _now(recorded_at)
        with self._begin_low_priority_relay_write() as db:

            delivery = db.get(RelayDeliveryRecord, delivery_id)
            if delivery is None:
                return {"recorded": False, "missing": True}
            message = db.get(RelayMessageRecord, delivery.message_id)
            if message is None:
                return {"recorded": False, "missing": True}

            existing = db.execute(
                select(RelayDeliveryTraceRecord).where(
                    RelayDeliveryTraceRecord.attempt_id == attempt_id,
                    RelayDeliveryTraceRecord.delivery_id == delivery_id,
                    RelayDeliveryTraceRecord.stage == stage,
                )
            ).scalar_one_or_none()
            values = (
                outcome,
                safe_reason,
                evidence_json,
                None if native_retry_safe is None else int(native_retry_safe),
                destination_health_update,
                scope_generation,
            )
            if existing is not None:
                same = (
                    existing.outcome,
                    existing.reason,
                    existing.evidence_json,
                    existing.native_retry_safe,
                    existing.destination_health_update,
                    existing.scope_generation,
                ) == values
                return {
                    "recorded": False,
                    "duplicate": same,
                    "conflict": not same,
                    "sequence": existing.recorded_sequence,
                }

            attempt_for_delivery = db.execute(
                select(RelayDeliveryTraceRecord.id)
                .where(
                    RelayDeliveryTraceRecord.attempt_id == attempt_id,
                    RelayDeliveryTraceRecord.delivery_id == delivery_id,
                )
                .limit(1)
            ).first()
            associated_deliveries = db.execute(
                select(func.count(RelayDeliveryTraceRecord.delivery_id.distinct()))
                .where(RelayDeliveryTraceRecord.attempt_id == attempt_id)
            ).scalar_one()
            total_rows = db.execute(
                select(func.count()).select_from(RelayDeliveryTraceRecord)
            ).scalar_one()
            delivery_rows = db.execute(
                select(func.count())
                .select_from(RelayDeliveryTraceRecord)
                .where(RelayDeliveryTraceRecord.delivery_id == delivery_id)
            ).scalar_one()
            delivery_attempts = db.execute(
                select(func.count(RelayDeliveryTraceRecord.attempt_id.distinct()))
                .where(RelayDeliveryTraceRecord.delivery_id == delivery_id)
            ).scalar_one()
            if (
                total_rows >= RELAY_TRACE_MAX_ROWS
                or delivery_rows >= 24
                or (attempt_for_delivery is None and delivery_attempts >= 8)
                or (attempt_for_delivery is None and associated_deliveries >= 64)
            ):
                delivery.trace_version = delivery.trace_version or 1
                delivery.trace_truncated = 1
                return {"recorded": False, "dropped": True}

            record = RelayDeliveryTraceRecord(
                id=f"relay-trace-{uuid.uuid4().hex}",
                attempt_id=attempt_id,
                delivery_id=delivery_id,
                message_id=message.id,
                stage=stage,
                outcome=outcome,
                reason=safe_reason,
                evidence_json=evidence_json,
                native_retry_safe=(
                    None if native_retry_safe is None else int(native_retry_safe)
                ),
                destination_health_update=destination_health_update,
                scope_generation=scope_generation,
                recorded_at=current,
            )
            db.add(record)
            db.flush()
            delivery.trace_version = delivery.trace_version or 1
            return {"recorded": True, "sequence": record.recorded_sequence}

    def relay_record_trace_event(self, event: dict[str, Any]) -> bool:
        if not isinstance(event, dict):
            return False
        try:
            result = self.relay_trace_record(
                attempt_id=event["attempt_id"],
                delivery_id=event["delivery_id"],
                stage=event["stage"],
                outcome=event.get("outcome"),
                reason=event.get("reason"),
                evidence=event.get("evidence"),
                native_retry_safe=event.get("native_retry_safe"),
                destination_health_update=event.get("destination_health_update"),
                scope_generation=event.get("scope_generation"),
                recorded_at=event.get("recorded_at"),
            )
        except (KeyError, TypeError, ValueError):
            return False
        return bool(result.get("recorded") or result.get("duplicate"))

    def relay_trace_message(
        self,
        *,
        message_id: str,
        limit: int = 100,
        after_sequence: int = 0,
        as_of_sequence: int | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Read shared activation evidence without mutating delivery state."""
        if (
            not 1 <= limit <= 100
            or type(after_sequence) is not int
            or not 0 <= after_sequence <= RELAY_TRACE_MAX_SEQUENCE
            or (
                as_of_sequence is not None
                and (
                    type(as_of_sequence) is not int
                    or not 0 <= as_of_sequence <= RELAY_TRACE_MAX_SEQUENCE
                    or after_sequence > as_of_sequence
                )
            )
        ):
            raise ValueError("invalid trace page")
        current = _now(now)
        with self._relay_session_factory() as db:
            message = db.get(RelayMessageRecord, message_id)
            if message is None and _REPAIR_DELIVERY_RE.fullmatch(message_id):
                delivery = db.get(RelayDeliveryRecord, message_id)
                if delivery is not None:
                    message_id = delivery.message_id
                    message = db.get(RelayMessageRecord, message_id)
            if message is None:
                raise RelayNotFoundError(
                    "relay entity not found in the requested scope"
                )
            deliveries = db.execute(
                select(RelayDeliveryRecord)
                .where(RelayDeliveryRecord.message_id == message_id)
                .order_by(RelayDeliveryRecord.id)
            ).scalars().all()
            upper = as_of_sequence
            if upper is None:
                upper = (
                    db.execute(
                        select(func.max(RelayDeliveryTraceRecord.recorded_sequence))
                    ).scalar_one()
                    or 0
                )
            delivery_ids = [row.id for row in deliveries]
            attempt_ids = (
                db.execute(
                    select(RelayDeliveryTraceRecord.attempt_id)
                    .where(
                        RelayDeliveryTraceRecord.delivery_id.in_(delivery_ids),
                        RelayDeliveryTraceRecord.recorded_sequence <= upper,
                    )
                    .distinct()
                ).scalars().all()
                if delivery_ids
                else []
            )
            rows = []
            if attempt_ids:
                statement = (
                    select(RelayDeliveryTraceRecord)
                    .where(
                        RelayDeliveryTraceRecord.attempt_id.in_(attempt_ids),
                        RelayDeliveryTraceRecord.recorded_sequence > after_sequence,
                        RelayDeliveryTraceRecord.recorded_sequence <= upper,
                        or_(
                            RelayDeliveryTraceRecord.delivery_id.in_(delivery_ids),
                            RelayDeliveryTraceRecord.stage.in_(
                                ("prepared", "completed")
                            ),
                        ),
                    )
                    .order_by(RelayDeliveryTraceRecord.recorded_sequence)
                    .limit(limit + 1)
                )
                rows = db.execute(statement).scalars().all()
            latest_completion = (
                db.execute(
                    select(RelayDeliveryTraceRecord)
                    .where(
                        RelayDeliveryTraceRecord.attempt_id.in_(attempt_ids),
                        RelayDeliveryTraceRecord.stage == "completed",
                        RelayDeliveryTraceRecord.recorded_sequence <= upper,
                    )
                    .order_by(RelayDeliveryTraceRecord.recorded_sequence.desc())
                    .limit(1)
                ).scalar_one_or_none()
                if attempt_ids
                else None
            )
            has_more = len(rows) > limit
            rows = rows[:limit]

            delivery_id_set = set(delivery_ids)
            events = [
                {
                    "sequence": row.recorded_sequence,
                    "attempt_id": row.attempt_id,
                    "delivery_id": (
                        row.delivery_id if row.delivery_id in delivery_id_set else None
                    ),
                    "shared": row.delivery_id not in delivery_id_set,
                    "stage": row.stage,
                    "outcome": row.outcome,
                    "reason": row.reason,
                    "evidence": (
                        json.loads(row.evidence_json)
                        if row.evidence_json is not None
                        else None
                    ),
                    "native_retry_safe": (
                        None
                        if row.native_retry_safe is None
                        else bool(row.native_retry_safe)
                    ),
                    "destination_health_update": row.destination_health_update,
                    "scope_generation": row.scope_generation,
                    "recorded_at": _iso(row.recorded_at),
                }
                for row in rows
            ]
            snapshots = []
            for delivery in deliveries:
                state = delivery.state
                if (
                    state in {"pending", "claimed"}
                    and _now(message.expires_at) <= current
                ):
                    state = "expired"
                elif (
                    state == "claimed"
                    and delivery.lease_expires_at is not None
                    and _now(delivery.lease_expires_at) <= current
                ):
                    state = "pending"
                endpoint = self._relay_session_by_endpoint(
                    db, endpoint_id=delivery.recipient_endpoint_id
                )
                snapshots.append(
                    {
                        "delivery_id": delivery.id,
                        "state": state,
                        "stored_state": delivery.state,
                        "attempts": int(delivery.attempts or 0),
                        "claimed_at": _iso(delivery.claimed_at),
                        "lease_expires_at": _iso(delivery.lease_expires_at),
                        "delivered_at": _iso(delivery.delivered_at),
                        "recipient_runtime": delivery.recipient_runtime,
                        "recipient_session_ref": delivery.recipient_session_ref,
                        "recipient_endpoint_id": delivery.recipient_endpoint_id,
                        "recipient_container_ref": delivery.recipient_container_ref,
                        "recipient_endpoint_state": (
                            None if endpoint is None else endpoint.state
                        ),
                        "trace_version": delivery.trace_version,
                        "trace_truncated": bool(delivery.trace_truncated),
                        "trace_pruned": bool(delivery.trace_pruned),
                    }
                )
            truncated = any(bool(row.trace_truncated) for row in deliveries)
            pruned = any(bool(row.trace_pruned) for row in deliveries)
            legacy = bool(deliveries) and all(
                row.trace_version is None for row in deliveries
            )
            states = {item["state"] for item in snapshots}
            state_counts = {
                state: sum(item["state"] == state for item in snapshots)
                for state in states
            }
            endpoint_states = {
                item["recipient_endpoint_state"] for item in snapshots
            }
            gap_suffix = (
                " Activation evidence is incomplete or unavailable."
                if legacy or truncated or pruned
                else ""
            )
            if states == {"delivered"}:
                explanation = (
                    "Delivered: All recipient deliveries were acknowledged; no reply "
                    "or action is implied."
                    + gap_suffix
                )
            elif len(states) > 1:
                counts = ", ".join(
                    f"{state}={state_counts[state]}" for state in sorted(states)
                )
                explanation = (
                    f"Mixed delivery states: {counts}. Review each recipient snapshot; "
                    "current delivery state is authoritative."
                    + gap_suffix
                )
            elif states == {"expired"}:
                never_claimed = all(
                    item["attempts"] == 0 and item["claimed_at"] is None
                    for item in snapshots
                )
                explanation = (
                    "Expired: The message expired before any recipient claimed it; no "
                    "valid payload was delivered before expiry."
                    if never_claimed
                    else "Expired: No recipient delivery was acknowledged before expiry. "
                    "Prior claim or activation evidence does not prove payload processing "
                    "and is not evidence of hook failure."
                ) + gap_suffix
            elif legacy:
                explanation = (
                    "Unknown: This delivery predates trace support; activation evidence "
                    "is unavailable. Use the current delivery state as authoritative."
                )
            elif truncated or pruned:
                explanation = (
                    "Unknown: Trace evidence has a known gap. Use the current delivery "
                    "state as authoritative; recorded activation events may be incomplete."
                )
            elif (
                states == {"pending"}
                and latest_completion is not None
                and latest_completion.outcome == "uncertain"
            ):
                explanation = (
                    "Needs intervention: Native activation is uncertain, so automatic "
                    "retry is held because the submission may already have succeeded. "
                    "Start an ordinary turn in the recipient task to process the retained "
                    "message; do not resend it."
                )
            elif states == {"pending"} and "unreachable" in endpoint_states:
                explanation = (
                    "Needs intervention: The target is currently unavailable. The pending "
                    "delivery remains stored; restore the recipient and start an ordinary "
                    "turn instead of resending it."
                )
            elif (
                states == {"pending"}
                and latest_completion is not None
                and latest_completion.outcome == "accepted"
            ):
                explanation = (
                    "Queued: Native activation was accepted and the Relay delivery remains "
                    "pending. It may wait for the recipient's current turn to finish before "
                    "a safe turn begins; acceptance does not prove payload admission."
                )
            elif (
                states == {"pending"}
                and latest_completion is not None
                and latest_completion.outcome in {"deferred", "failed"}
            ):
                explanation = (
                    "Queued: Native activation did not complete. The Relay delivery remains "
                    "pending for an ordinary eligible recipient turn."
                )
            elif states == {"claimed"}:
                explanation = (
                    "Claimed: The recipient holds an active delivery lease, but ACK has not "
                    "been recorded. Current delivery state is authoritative."
                )
            else:
                explanation = (
                    "Queued: No activation outcome is recorded. The pending delivery remains "
                    "stored for an ordinary eligible recipient turn."
                )
            return {
                "contract": "relay-delivery-trace/v1",
                "message_id": message_id,
                "events": events,
                "delivery_snapshots": snapshots,
                "next_sequence": (
                    events[-1]["sequence"] if events else after_sequence
                ),
                "as_of_sequence": upper,
                "has_more": has_more,
                "completeness": "best_effort",
                "legacy": legacy,
                "absent": not events,
                "truncated": truncated,
                "pruned": pruned,
                "gap": legacy or truncated or pruned,
                "explanation": explanation,
            }
