"""Metrics storage — persistent operational event recording."""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import select, func, delete

from core.errors import is_transient_error
from core.models import new_id
from storage.sqlite_schema import MetricRecord


logger = logging.getLogger(__name__)

# Transient-error retry policy. Mirrors storage/sqlite.py deliberately so
# operators have one mental model for "transient SQLite contention". The
# transient predicate itself is the shared core.errors.is_transient_error so
# both code paths recognise the same class of failure (locked, disk i/o,
# unable to open database file, etc.).
_TRANSIENT_MAX_RETRIES = 3
_TRANSIENT_BACKOFF_BASE = 0.2  # seconds; total upper bound ~ 0.2 + 0.4 = 0.6s


VALID_EVENTS: dict[str, set[str]] = {
    "query": {"injection", "skip", "flag", "feedback"},
    "work_trace": {"thread_rebuild"},
    "processing": {"item_processed", "thread_rebuilt", "extraction_failed"},
    "system": {"service_start", "retention_run"},
    # Phase 4A (design 014): structural dry-run telemetry. No LLM call.
    "consolidation": {"workstream_aware_dryrun", "workstream_homogeneity"},
}


@dataclass
class MetricRow:
    id: str
    timestamp: datetime
    category: str
    event_type: str
    container_ref: str | None
    thread_ref: str | None
    actor_ref: str | None
    value: float | None
    payload: dict | None


@dataclass
class AggregateBucket:
    bucket: str
    event_type: str
    count: int
    sum_value: float
    avg_value: float


class MetricsStore:
    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    def record(self, category: str, event_type: str, *,
               container_ref: str | None = None,
               thread_ref: str | None = None,
               actor_ref: str | None = None,
               value: float | None = None,
               payload: dict | None = None) -> None:
        """Persist one metric event. Fire-and-forget by spec; never blocks the caller.

        On any transient SQLite error (per `core.errors.is_transient_error` —
        locked, disk i/o, busy, unable to open), retry up to
        `_TRANSIENT_MAX_RETRIES` with exponential backoff. On any other
        exception (including non-serializable payloads), OR after retries
        are exhausted, log at WARNING with metric name, exception class,
        and a 200-char message prefix. Never raise.
        """
        last_exc: BaseException | None = None
        for attempt in range(_TRANSIENT_MAX_RETRIES):
            try:
                # Serialise + build inside the guarded block so that
                # non-JSON-serialisable payloads degrade to a WARNING rather
                # than raising out of the fire-and-forget contract.
                record = MetricRecord(
                    id=new_id(),
                    timestamp=datetime.now(timezone.utc),
                    category=category,
                    event_type=event_type,
                    container_ref=container_ref,
                    thread_ref=thread_ref,
                    actor_ref=actor_ref,
                    value=value,
                    payload_json=json.dumps(payload) if payload is not None else None,
                )
                with self._session_factory() as session:
                    session.add(record)
                    session.commit()
                return  # success
            except Exception as exc:  # noqa: BLE001 — fire-and-forget by spec
                last_exc = exc
                if is_transient_error(exc) and attempt < _TRANSIENT_MAX_RETRIES - 1:
                    time.sleep(_TRANSIENT_BACKOFF_BASE * (2 ** attempt))
                    continue
                break  # non-transient OR retries exhausted

        # If we got here, we did not succeed.
        if last_exc is not None:
            message = str(last_exc)
            if len(message) > 200:
                message = message[:200] + "..."
            logger.warning(
                "metrics.record dropped event "
                "category=%s event_type=%s exc=%s message=%s",
                category, event_type, type(last_exc).__name__, message,
            )
        # Do NOT raise; metrics are fire-and-forget per
        # docs/specs/2026-05-05-metrics-collection-and-dashboard.md.

    def query(self, *,
              category: str | None = None,
              event_type: str | None = None,
              container_ref: str | None = None,
              thread_ref: str | None = None,
              since: datetime | None = None,
              until: datetime | None = None,
              limit: int = 1000) -> list[MetricRow]:
        with self._session_factory() as session:
            stmt = select(MetricRecord).order_by(MetricRecord.timestamp.desc())
            if category is not None:
                stmt = stmt.where(MetricRecord.category == category)
            if event_type is not None:
                stmt = stmt.where(MetricRecord.event_type == event_type)
            if container_ref is not None:
                stmt = stmt.where(MetricRecord.container_ref == container_ref)
            if thread_ref is not None:
                stmt = stmt.where(MetricRecord.thread_ref == thread_ref)
            if since is not None:
                stmt = stmt.where(MetricRecord.timestamp >= since)
            if until is not None:
                stmt = stmt.where(MetricRecord.timestamp < until)
            stmt = stmt.limit(limit)
            rows = session.execute(stmt).scalars().all()
            return [self._to_row(r) for r in rows]

    def aggregate(self, *,
                  category: str,
                  event_type: str | None = None,
                  container_ref: str | None = None,
                  since: datetime | None = None,
                  until: datetime | None = None,
                  group_by: Literal["hour", "day", "week"] = "day",
                  ) -> list[AggregateBucket]:
        with self._session_factory() as session:
            bucket_expr = self._bucket_expression(group_by)
            stmt = (
                select(
                    bucket_expr.label("bucket"),
                    MetricRecord.event_type,
                    func.count().label("count"),
                    func.sum(MetricRecord.value).label("sum_value"),
                    func.count(MetricRecord.value).label("value_count"),
                )
                .where(MetricRecord.category == category)
                .group_by(bucket_expr, MetricRecord.event_type)
                .order_by(bucket_expr)
            )
            if event_type is not None:
                stmt = stmt.where(MetricRecord.event_type == event_type)
            if container_ref is not None:
                stmt = stmt.where(MetricRecord.container_ref == container_ref)
            if since is not None:
                stmt = stmt.where(MetricRecord.timestamp >= since)
            if until is not None:
                stmt = stmt.where(MetricRecord.timestamp < until)
            rows = session.execute(stmt).all()
            return [
                AggregateBucket(
                    bucket=row.bucket,
                    event_type=row.event_type,
                    count=row.count,
                    sum_value=float(row.sum_value) if row.sum_value is not None else 0.0,
                    avg_value=float(row.sum_value) / row.value_count if row.value_count > 0 else 0.0,
                )
                for row in rows
            ]

    def cleanup(self, retention_days: int) -> int:
        if retention_days <= 0:
            return 0
        cutoff = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        cutoff = cutoff - timedelta(days=retention_days)
        with self._session_factory() as session:
            stmt = delete(MetricRecord).where(MetricRecord.timestamp < cutoff)
            result = session.execute(stmt)
            session.commit()
            return result.rowcount  # type: ignore[return-value]

    def _bucket_expression(self, group_by: str):
        if group_by == "hour":
            return func.strftime("%Y-%m-%dT%H", MetricRecord.timestamp)
        elif group_by == "week":
            return func.strftime("%Y-W%W", MetricRecord.timestamp)
        else:  # day
            return func.strftime("%Y-%m-%d", MetricRecord.timestamp)

    def _to_row(self, record: MetricRecord) -> MetricRow:
        payload = None
        if record.payload_json:
            try:
                payload = json.loads(record.payload_json)
            except (json.JSONDecodeError, TypeError):
                pass
        return MetricRow(
            id=record.id,
            timestamp=record.timestamp,
            category=record.category,
            event_type=record.event_type,
            container_ref=record.container_ref,
            thread_ref=record.thread_ref,
            actor_ref=record.actor_ref,
            value=record.value,
            payload=payload,
        )
