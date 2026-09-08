from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import and_, func, or_, select

from storage.metrics import MetricsStore
from storage.sqlite import SQLiteStorageProvider, _extract_display_text
from core.filters import source_item_matches_filters
from core.models import QueryFilters, SourceItem
from core.service import _redact_ingest_value
from core.subject import subject_text_for_payload
from core.visibility import is_visible
from redaction import redact_sensitive
from storage.sqlite_schema import (
    HistoricalLookupReuseEventRecord, HistoricalLookupReuseLabelRecord,
    MemoryFeedbackRecord, MemoryFlagRecord, MemoryObjectRecord,
    RelayDeliveryRecord, RelayMessageRecord, RelaySessionRecord,
    SourceItemRecord,
)

logger = logging.getLogger(__name__)

_DASHBOARD_HTML_PATH = Path(__file__).parent / "dashboard.html"

# PR 3 of operational_fact redesign: the dashboard /api/memories view
# runs a raw SELECT (not through ``list_memory_objects``), so it needs
# its own allowlist mirror. Kept in sync with the storage-layer default
# ``_DEFAULT_VISIBLE_LIFECYCLES``; drift between the two is a bug.
_DASHBOARD_VISIBLE_LIFECYCLES: tuple[str, ...] = ("active", "superseded", "suppressed")

# "How memory helps" view — offline eval reports surfaced read-only.
# The dashboard serves the LAST-WRITTEN report files only; it never runs the
# rollup/loader on-request (that would scan ``source_items`` unbounded on a
# sync handler at 10s cadence). Report keys map to HARDCODED, cwd-relative
# ``Path`` constants — there is NO user-supplied filename/path, so the route
# is traversal-proof. A missing dir/file yields a present-but-empty 200 state,
# never a 404/500. Paths mirror the eval runners' default outputs
# (``evals/raw_derived_hybrid/runner.py`` + ``evals/derivation_fidelity/runner.py``).
_EFFECTIVENESS_REPORT_PATHS: dict[str, Path] = {
    "raw_derived_hybrid": Path(".local") / "research" / "raw_derived_hybrid_report.json",
    "derivation_fidelity": Path(".local") / "research" / "derivation_fidelity_report.json",
    # Judge-vs-gold calibration for the reuse KPI (evals/reuse_judge_calibration.py).
    # Drives the "calibrated vs uncalibrated" affordance on the reuse-KPI panel.
    "reuse_judge_calibration": Path(".local") / "research" / "reuse_judge_calibration.json",
    "historical_lookup_measurement": Path(".local") / "research" / "historical_lookup_measurement.json",
    "historical_lookup_judge": Path(".local") / "research" / "historical_lookup_judge.json",
}


def _dashboard_utc(value: datetime | None) -> datetime | None:
    return value if value is None else (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc))


def _dashboard_time(value: datetime | None) -> str | None:
    value = _dashboard_utc(value)
    return value.isoformat() if value else None


def _dashboard_source_item(record: SourceItemRecord) -> SourceItem:
    try:
        metadata = json.loads(record.metadata_json) if record.metadata_json else None
    except (TypeError, json.JSONDecodeError):
        metadata = None
    return SourceItem(
        id=record.id, source_type=record.source_type, source_id=record.source_id,
        content_type=record.content_type, content=record.content, metadata=metadata if isinstance(metadata, dict) else None,
        occurred_at=record.occurred_at, actor_ref=record.actor_ref, agent_ref=record.agent_ref,
        role=record.role, container_ref=record.container_ref, thread_ref=record.thread_ref,
        source_ref=record.source_ref, artifact_kind=record.artifact_kind,
        visibility=record.visibility or "private", use_case=record.use_case,
        processing_status=record.processing_status, processing_attempts=record.processing_attempts,
        thread_position=record.thread_position, forgotten_at=record.forgotten_at,
        forgotten_by=record.forgotten_by, forgotten_reason=record.forgotten_reason,
        created_at=record.created_at,
    )


def _dashboard_source_visible(record: SourceItemRecord, *, container_ref: str, actor_ref: str,
                              query_visibility: str, filters: QueryFilters) -> bool:
    item = _dashboard_source_item(record)
    return not item.forgotten and is_visible(
        item.visibility, item.container_ref, container_ref, item.actor_ref,
        query_visibility=query_visibility, query_actor_ref=actor_ref,
    ) and source_item_matches_filters(item, filters)


def _dashboard_source_view(record: SourceItemRecord) -> dict:
    item = _dashboard_source_item(record)
    content, metadata = item.content, item.metadata
    if item.artifact_kind != "note":
        content = redact_sensitive(content) if content else content
        metadata = _redact_ingest_value(metadata) if metadata else metadata
    return {
        "id": item.id, "source_type": item.source_type, "source_id": item.source_id,
        "content_type": item.content_type, "content": content, "metadata": metadata,
        "occurred_at": _dashboard_time(item.occurred_at), "created_at": _dashboard_time(item.created_at),
        "actor_ref": item.actor_ref, "agent_ref": item.agent_ref, "role": item.role,
        "container_ref": item.container_ref, "thread_ref": item.thread_ref, "source_ref": item.source_ref,
        "artifact_kind": item.artifact_kind, "visibility": item.visibility, "use_case": item.use_case,
        "processing_status": item.processing_status, "thread_position": item.thread_position,
    }


def _dashboard_source_scope_clause(*, container_ref: str, actor_ref: str, query_visibility: str):
    visibility = func.coalesce(SourceItemRecord.visibility, "private")
    actor_matches = or_(SourceItemRecord.actor_ref.is_(None), SourceItemRecord.actor_ref == actor_ref)
    global_same_actor = and_(visibility == "global", SourceItemRecord.actor_ref == actor_ref)
    public = and_(visibility == "public", SourceItemRecord.actor_ref.is_(None))
    if query_visibility == "public":
        accessible = or_(global_same_actor, public)
    elif query_visibility == "container":
        accessible = or_(global_same_actor, public, and_(
            SourceItemRecord.container_ref == container_ref, visibility != "private", actor_matches,
        ))
    else:
        accessible = or_(global_same_actor, public, and_(SourceItemRecord.container_ref == container_ref, actor_matches))
    return and_(SourceItemRecord.forgotten_at.is_(None), accessible)


def _sanitize_non_finite(obj):
    """Recursively replace non-finite floats (NaN / ±Infinity) with None.

    Python's ``json.loads`` accepts ``NaN``/``Infinity`` (they can appear in an
    eval report, e.g. a rate computed as 0/0), but FastAPI's ``JSONResponse``
    would then re-emit bare ``NaN``/``Infinity`` — invalid JSON that a browser's
    ``fetch().json()`` rejects, breaking the panel. Coercing to ``None`` keeps
    the response strictly valid; the renderer already treats missing/null
    fields as "not available".
    """
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _sanitize_non_finite(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_non_finite(v) for v in obj]
    return obj


def _read_effectiveness_report(path: Path) -> dict:
    """Read one last-written eval JSON report as an empty-safe payload.

    Returns ``{"available": False, ...}`` when the dir/file is absent or the
    file is unreadable/corrupt (HTTP stays 200 — the caller renders a friendly
    "run this eval" empty state). When present, returns the parsed report plus
    the file's ``last_modified`` mtime (ISO, UTC) for a stale affordance.
    """
    try:
        if not path.exists():
            return {"available": False, "last_modified": None}
        data = json.loads(path.read_text(encoding="utf-8"))
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        return {
            "available": True,
            "last_modified": mtime.isoformat(),
            "report": _sanitize_non_finite(data),
        }
    except Exception:
        logger.warning("effectiveness report unreadable: %s", path, exc_info=True)
        return {"available": False, "last_modified": None, "error": "unreadable"}


def mount_dashboard(app: FastAPI) -> None:
    assets_dir = Path(__file__).resolve().parent.parent / "assets"
    app.mount("/static", StaticFiles(directory=str(assets_dir)), name="static")

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard_page() -> HTMLResponse:
        html = _DASHBOARD_HTML_PATH.read_text(encoding="utf-8")
        return HTMLResponse(content=html)

    @app.get("/dashboard/api/effectiveness/reports")
    def dashboard_effectiveness_reports() -> JSONResponse:
        """Serve the last-written offline eval reports for the "How memory
        helps" view. Read-only, file-backed — does NOT require the SQLite
        backend and NEVER runs the rollup/loader on-request. Report keys are a
        fixed, hardcoded set (no user input), so the route is traversal-proof.
        A missing dir/file returns a present-but-empty 200 state per report.
        """
        reports = {
            key: _read_effectiveness_report(path)
            for key, path in _EFFECTIVENESS_REPORT_PATHS.items()
        }
        return JSONResponse(content={"reports": reports})

    @app.get("/dashboard/api/containers")
    def dashboard_containers() -> JSONResponse:
        storage = app.state.pallium_service._storage
        if not isinstance(storage, SQLiteStorageProvider):
            return JSONResponse(content={"error": "requires SQLite backend"}, status_code=501)
        with storage._session_factory() as session:
            values = set(session.scalars(select(MemoryObjectRecord.container_ref).where(MemoryObjectRecord.container_ref.isnot(None)).distinct()))
            values.update(session.scalars(select(SourceItemRecord.container_ref).where(SourceItemRecord.container_ref.isnot(None)).distinct()))
        factory = getattr(storage, "_relay_session_factory", storage._session_factory)
        with factory() as session:
            values.update(session.scalars(select(RelaySessionRecord.container_ref).where(RelaySessionRecord.container_ref.isnot(None)).distinct()))
        return JSONResponse(content={"containers": sorted(values)})
    @app.get("/dashboard/api/actors")
    def dashboard_actors() -> JSONResponse:
        storage = app.state.pallium_service._storage
        if not isinstance(storage, SQLiteStorageProvider):
            return JSONResponse(content={"error": "requires SQLite backend"}, status_code=501)
        with storage._session_factory() as session:
            values = set(session.scalars(select(MemoryObjectRecord.actor_ref).where(MemoryObjectRecord.actor_ref.isnot(None)).distinct()))
            values.update(session.scalars(select(SourceItemRecord.actor_ref).where(SourceItemRecord.actor_ref.isnot(None)).distinct()))
        return JSONResponse(content={"actors": sorted(values)})
    @app.get("/dashboard/api/activity")
    def dashboard_activity(limit: int = Query(10, ge=1, le=50)) -> JSONResponse:
        storage = app.state.pallium_service._storage
        if not isinstance(storage, SQLiteStorageProvider):
            return JSONResponse(content={"error": "requires SQLite backend"}, status_code=501)
        with storage._session_factory() as session:
            memories = session.scalars(select(MemoryObjectRecord).order_by(MemoryObjectRecord.created_at.desc()).limit(limit)).all()
            sources = session.scalars(select(SourceItemRecord).order_by(SourceItemRecord.created_at.desc()).limit(limit)).all()
        items = []
        for record in memories:
            payload = json.loads(record.payload_json) if record.payload_json else {}
            items.append({"event": "memory_created", "type": record.type, "display_text": _extract_display_text(payload),
                          "container_ref": record.container_ref, "created_at": _dashboard_time(record.created_at), "_at": record.created_at})
        for record in sources:
            items.append({"event": "source_ingested", "type": record.source_type,
                          "display_text": record.artifact_kind or record.content_type,
                          "container_ref": record.container_ref, "created_at": _dashboard_time(record.created_at), "_at": record.created_at})
        factory = getattr(storage, "_relay_session_factory", storage._session_factory)
        with factory() as session:
            messages = session.scalars(select(RelayMessageRecord).order_by(RelayMessageRecord.created_at.desc()).limit(limit)).all()
        for record in messages:
            items.append({"event": "relay_sent", "type": record.sender_runtime, "display_text": None,
                          "container_ref": record.container_ref, "created_at": _dashboard_time(record.created_at), "_at": record.created_at})
        items.sort(key=lambda item: _dashboard_time(item["_at"]) or "", reverse=True)
        for item in items:
            item.pop("_at")
        return JSONResponse(content={"items": items[:limit]})
    @app.get("/dashboard/api/relay/summary")
    def dashboard_relay_summary() -> JSONResponse:
        service = app.state.pallium_service
        storage = service._storage
        if not isinstance(storage, SQLiteStorageProvider):
            return JSONResponse(content={"error": "requires SQLite backend"}, status_code=501)

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=24)
        active_states = ("pending", "claimed")

        def utc(value):
            if value is None:
                return None
            return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)

        def percentile(values, fraction):
            if not values:
                return None
            ordered = sorted(values)
            index = max(0, math.ceil(len(ordered) * fraction) - 1)
            return round(ordered[index], 3)

        relay_session_factory = getattr(storage, "_relay_session_factory", storage._session_factory)
        with relay_session_factory() as session:
            messages_total = session.scalar(select(func.count()).select_from(RelayMessageRecord)) or 0
            messages_24h = session.scalar(
                select(func.count()).select_from(RelayMessageRecord).where(
                    RelayMessageRecord.created_at >= cutoff
                )
            ) or 0
            replies_24h = session.scalar(
                select(func.count()).select_from(RelayMessageRecord).where(
                    RelayMessageRecord.created_at >= cutoff,
                    RelayMessageRecord.in_reply_to.isnot(None),
                )
            ) or 0
            deliveries_total = session.scalar(select(func.count()).select_from(RelayDeliveryRecord)) or 0
            delivered_total = session.scalar(
                select(func.count()).select_from(RelayDeliveryRecord).where(
                    RelayDeliveryRecord.state == "delivered"
                )
            ) or 0
            delivered_24h = session.scalar(
                select(func.count()).select_from(RelayDeliveryRecord).where(
                    RelayDeliveryRecord.state == "delivered",
                    RelayDeliveryRecord.delivered_at >= cutoff,
                )
            ) or 0
            pending_now = session.scalar(
                select(func.count())
                .select_from(RelayDeliveryRecord)
                .join(RelayMessageRecord, RelayMessageRecord.id == RelayDeliveryRecord.message_id)
                .where(
                    RelayDeliveryRecord.state.in_(active_states),
                    RelayMessageRecord.expires_at > now,
                )
            ) or 0
            expired_total = session.scalar(
                select(func.count())
                .select_from(RelayDeliveryRecord)
                .join(RelayMessageRecord, RelayMessageRecord.id == RelayDeliveryRecord.message_id)
                .where(or_(
                    RelayDeliveryRecord.state == "expired",
                    and_(
                        RelayDeliveryRecord.state.in_(active_states),
                        RelayMessageRecord.expires_at <= now,
                    ),
                ))
            ) or 0
            expired_24h = session.scalar(
                select(func.count())
                .select_from(RelayDeliveryRecord)
                .join(RelayMessageRecord, RelayMessageRecord.id == RelayDeliveryRecord.message_id)
                .where(
                    RelayMessageRecord.expires_at >= cutoff,
                    RelayMessageRecord.expires_at <= now,
                    RelayDeliveryRecord.state != "delivered",
                )
            ) or 0
            oldest_pending = session.scalar(
                select(func.min(RelayMessageRecord.created_at))
                .select_from(RelayDeliveryRecord)
                .join(RelayMessageRecord, RelayMessageRecord.id == RelayDeliveryRecord.message_id)
                .where(
                    RelayDeliveryRecord.state.in_(active_states),
                    RelayMessageRecord.expires_at > now,
                )
            )
            latency_rows = session.execute(
                select(
                    RelayMessageRecord.created_at,
                    RelayDeliveryRecord.claimed_at,
                    RelayDeliveryRecord.delivered_at,
                    RelayDeliveryRecord.attempts,
                )
                .join(RelayMessageRecord, RelayMessageRecord.id == RelayDeliveryRecord.message_id)
                .where(
                    RelayDeliveryRecord.state == "delivered",
                    RelayDeliveryRecord.delivered_at >= cutoff,
                )
            ).all()

            runtimes = {}
            for runtime in ("claude-code", "codex", "opencode"):
                recent = session.scalar(
                    select(func.count()).select_from(RelaySessionRecord).where(
                        RelaySessionRecord.runtime == runtime,
                        RelaySessionRecord.state != "closed",
                        RelaySessionRecord.last_seen_at >= cutoff,
                    )
                ) or 0
                dormant = session.scalar(
                    select(func.count()).select_from(RelaySessionRecord).where(
                        RelaySessionRecord.runtime == runtime,
                        RelaySessionRecord.state != "closed",
                        RelaySessionRecord.last_seen_at < cutoff,
                    )
                ) or 0
                closed = session.scalar(
                    select(func.count()).select_from(RelaySessionRecord).where(
                        RelaySessionRecord.runtime == runtime,
                        RelaySessionRecord.state == "closed",
                    )
                ) or 0
                runtimes[runtime] = {"recent": recent, "dormant": dormant, "closed": closed}

        queue_wait = []
        acknowledgement = []
        total_latency = []
        redeliveries = 0
        for created_at, claimed_at, delivered_at, attempts in latency_rows:
            created = utc(created_at)
            claimed = utc(claimed_at)
            delivered = utc(delivered_at)
            if created and delivered:
                total_latency.append((delivered - created).total_seconds())
            if created and claimed:
                queue_wait.append((claimed - created).total_seconds())
            if claimed and delivered:
                acknowledgement.append((delivered - claimed).total_seconds())
            if (attempts or 0) > 1:
                redeliveries += 1

        oldest_pending_age = None
        if oldest_pending is not None:
            oldest_pending_age = max(0, int((now - utc(oldest_pending)).total_seconds()))

        return JSONResponse(content={
            "status": "attention" if expired_24h else ("active" if deliveries_total else "idle"),
            "messages": {"last_24h": messages_24h, "total": messages_total, "replies_last_24h": replies_24h},
            "deliveries": {
                "last_24h": delivered_24h,
                "delivered_total": delivered_total,
                "total": deliveries_total,
                "pending_now": pending_now,
                "expired_last_24h": expired_24h,
                "expired_total": expired_total,
                "redeliveries_last_24h": redeliveries,
                "oldest_pending_age_seconds": oldest_pending_age,
            },
            "latency_seconds": {
                "sample_size": len(total_latency),
                "queue_wait_p50": percentile(queue_wait, 0.5),
                "acknowledgement_p95": percentile(acknowledgement, 0.95),
                "total_p50": percentile(total_latency, 0.5),
                "total_p95": percentile(total_latency, 0.95),
            },
            "sessions": runtimes,
        })

    @app.get("/dashboard/api/sources")
    def dashboard_sources(
        container_ref: str = Query(..., min_length=1), actor_ref: str = Query(..., min_length=1),
        query_visibility: Literal["public", "container", "private", "global"] = Query(...),
        source_type: str | None = Query(None), role: str | None = Query(None),
        artifact_kind: str | None = Query(None), thread_ref: str | None = Query(None),
        agent_ref: str | None = Query(None), search: str | None = Query(None), limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ) -> JSONResponse:
        storage = app.state.pallium_service._storage
        if not isinstance(storage, SQLiteStorageProvider):
            return JSONResponse(content={"error": "requires SQLite backend"}, status_code=501)
        filters = QueryFilters(container_ref=container_ref, actor_ref=actor_ref, source_type=source_type,
                               role=role, artifact_kind=artifact_kind, thread_ref=thread_ref)
        clause = _dashboard_source_scope_clause(container_ref=container_ref, actor_ref=actor_ref,
                                                query_visibility=query_visibility)
        with storage._session_factory() as session:
            stmt = select(SourceItemRecord).where(clause)
            count_stmt = select(func.count()).select_from(SourceItemRecord).where(clause)
            for column, value in ((SourceItemRecord.source_type, source_type), (SourceItemRecord.role, role),
                                  (SourceItemRecord.artifact_kind, artifact_kind), (SourceItemRecord.thread_ref, thread_ref),
                                  (SourceItemRecord.agent_ref, agent_ref)):
                if value is not None:
                    stmt, count_stmt = stmt.where(column == value), count_stmt.where(column == value)
            if search and search.strip():
                match = f"%{search.strip()}%"
                predicate = or_(SourceItemRecord.content.ilike(match), SourceItemRecord.metadata_json.ilike(match))
                stmt, count_stmt = stmt.where(predicate), count_stmt.where(predicate)
            total = session.scalar(count_stmt) or 0
            effective_at = func.coalesce(SourceItemRecord.occurred_at, SourceItemRecord.created_at)
            records = session.scalars(stmt.order_by(effective_at.desc(), SourceItemRecord.id.desc()).offset(offset).limit(limit)).all()
        visible = [record for record in records if (agent_ref is None or record.agent_ref == agent_ref) and _dashboard_source_visible(
            record, container_ref=container_ref, actor_ref=actor_ref, query_visibility=query_visibility, filters=filters,
        )]
        return JSONResponse(content={"sources": [_dashboard_source_view(record) for record in visible],
                                     "total": total, "offset": offset, "limit": limit})

    @app.get("/dashboard/api/sources/{source_item_id}")
    def dashboard_source_detail(
        source_item_id: str, container_ref: str = Query(..., min_length=1), actor_ref: str = Query(..., min_length=1),
        query_visibility: Literal["public", "container", "private", "global"] = Query(...),
    ) -> JSONResponse:
        storage = app.state.pallium_service._storage
        if not isinstance(storage, SQLiteStorageProvider):
            return JSONResponse(content={"error": "requires SQLite backend"}, status_code=501)
        filters = QueryFilters(container_ref=container_ref, actor_ref=actor_ref)
        with storage._session_factory() as session:
            record = session.get(SourceItemRecord, source_item_id)
        if record is None or not _dashboard_source_visible(record, container_ref=container_ref, actor_ref=actor_ref,
                                                            query_visibility=query_visibility, filters=filters):
            raise HTTPException(status_code=404, detail="source item not found")
        return JSONResponse(content={"source": _dashboard_source_view(record)})

    @app.get("/dashboard/api/history/reuse-events")
    def dashboard_reuse_events(
        container_ref: str = Query(..., min_length=1), actor_ref: str = Query(..., min_length=1),
        query_visibility: Literal["public", "container", "private", "global"] = Query(...),
        limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
    ) -> JSONResponse:
        storage = app.state.pallium_service._storage
        if not isinstance(storage, SQLiteStorageProvider):
            return JSONResponse(content={"error": "requires SQLite backend"}, status_code=501)
        visibility = func.coalesce(HistoricalLookupReuseEventRecord.visibility, "private")
        actor_matches = or_(HistoricalLookupReuseEventRecord.actor_ref.is_(None), HistoricalLookupReuseEventRecord.actor_ref == actor_ref)
        public = and_(visibility == "public", HistoricalLookupReuseEventRecord.actor_ref.is_(None))
        global_same_actor = and_(visibility == "global", HistoricalLookupReuseEventRecord.actor_ref == actor_ref)
        local = HistoricalLookupReuseEventRecord.container_ref == container_ref
        if query_visibility == "public":
            clause = or_(public, global_same_actor)
        elif query_visibility == "container":
            clause = or_(public, global_same_actor, and_(local, visibility != "private", actor_matches))
        else:
            clause = or_(public, global_same_actor, and_(local, actor_matches))
        with storage._session_factory() as session:
            total = session.scalar(select(func.count()).select_from(HistoricalLookupReuseEventRecord).where(clause)) or 0
            events = session.scalars(select(HistoricalLookupReuseEventRecord).where(clause).order_by(
                HistoricalLookupReuseEventRecord.created_at.desc(), HistoricalLookupReuseEventRecord.id.desc()).offset(offset).limit(limit)).all()
            event_ids = [event.id for event in events]
            labels = session.scalars(select(HistoricalLookupReuseLabelRecord).where(
                HistoricalLookupReuseLabelRecord.lookup_event_id.in_(event_ids)).order_by(
                HistoricalLookupReuseLabelRecord.created_at.desc(), HistoricalLookupReuseLabelRecord.id.desc())).all() if event_ids else []
            source_ids = {event.request_source_item_id for event in events if event.request_source_item_id}
            exposed = {}
            for event in events:
                try:
                    exposed[event.id] = json.loads(event.exposed_json or "[]")
                except (TypeError, json.JSONDecodeError):
                    exposed[event.id] = []
                source_ids.update(entry.get("source_item_id") for entry in exposed[event.id] if isinstance(entry, dict) and entry.get("source_item_id"))
            records = {record.id: record for record in session.scalars(select(SourceItemRecord).where(SourceItemRecord.id.in_(source_ids))).all()} if source_ids else {}
        filters = QueryFilters(container_ref=container_ref, actor_ref=actor_ref)
        readable = {source_id for source_id, record in records.items() if _dashboard_source_visible(
            record, container_ref=container_ref, actor_ref=actor_ref, query_visibility=query_visibility, filters=filters)}
        event_text_allowed: dict[str, bool] = {}
        for event in events:
            references = ([event.request_source_item_id] if event.request_source_item_id else []) + [
                entry.get("source_item_id") for entry in exposed[event.id]
                if isinstance(entry, dict) and entry.get("source_item_id")
            ]
            event_text_allowed[event.id] = bool(references) and all(source_id in readable for source_id in references)
        labels_by_event: dict[str, list[dict]] = {}
        for label in labels:
            allowed = event_text_allowed.get(label.lookup_event_id, False)
            labels_by_event.setdefault(label.lookup_event_id, []).append({"id": label.id, "rung": label.rung,
                "rationale": redact_sensitive(label.rationale) if allowed and label.rationale else None,
                "created_at": _dashboard_time(label.created_at)})
        items = []
        for event in events:
            request_id = event.request_source_item_id
            text_allowed = event_text_allowed[event.id]
            item = {"id": event.id, "event_type": event.event_type, "created_at": _dashboard_time(event.created_at),
                    "session_id": event.session_id, "parent_lookup_id": event.parent_lookup_id,
                    "source_session_ref": event.source_session_ref,
                    "query_text": redact_sensitive(event.query_text) if text_allowed and event.query_text else None,
                    "text_available": text_allowed,
                    "request_source_item": {"id": request_id if request_id in readable else None, "available": request_id in readable},
                    "labels": labels_by_event.get(event.id, []), "exposed": []}
            for entry in exposed[event.id]:
                if not isinstance(entry, dict):
                    continue
                source_id = entry.get("source_item_id")
                item["exposed"].append({"source_item_id": source_id if source_id in readable else None,
                                        "available": source_id in readable, "role": entry.get("role"), "raw_rank": entry.get("raw_rank"), "score": entry.get("score")})
            items.append(item)
        return JSONResponse(content={"events": items, "total": total, "offset": offset, "limit": limit})

    @app.get("/dashboard/api/relay/sessions")
    def dashboard_relay_sessions(
        runtime: str | None = Query(None),
        container_ref: str | None = Query(None),
        lifecycle: Literal["recent", "dormant", "closed"] | None = Query(None),
        destination_health: Literal["active", "unreachable"] | None = Query(None), limit: int = Query(100, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ) -> JSONResponse:
        storage = app.state.pallium_service._storage
        if not isinstance(storage, SQLiteStorageProvider):
            return JSONResponse(content={"error": "requires SQLite backend"}, status_code=501)
        as_of = datetime.now(timezone.utc)
        cutoff = as_of - timedelta(hours=24)
        clause = True
        if runtime is not None:
            clause = and_(clause, RelaySessionRecord.runtime == runtime)
        if container_ref is not None:
            clause = and_(clause, RelaySessionRecord.container_ref == container_ref)
        if destination_health is not None:
            clause = and_(clause, RelaySessionRecord.state == destination_health, RelaySessionRecord.state != "closed")
        if lifecycle == "closed":
            clause = and_(clause, RelaySessionRecord.state == "closed")
        elif lifecycle == "recent":
            clause = and_(clause, RelaySessionRecord.state != "closed", RelaySessionRecord.last_seen_at >= cutoff)
        elif lifecycle == "dormant":
            clause = and_(clause, RelaySessionRecord.state != "closed", RelaySessionRecord.last_seen_at < cutoff)
        factory = getattr(storage, "_relay_session_factory", storage._session_factory)
        with factory() as session:
            total = session.scalar(select(func.count()).select_from(RelaySessionRecord).where(clause)) or 0
            records = session.scalars(select(RelaySessionRecord).where(clause).order_by(
                RelaySessionRecord.last_seen_at.desc(), RelaySessionRecord.id.desc()).offset(offset).limit(limit)).all()
        sessions = []
        for record in records:
            item_lifecycle = "closed" if record.state == "closed" else (
                "recent" if (record.last_seen_at if record.last_seen_at.tzinfo else record.last_seen_at.replace(tzinfo=timezone.utc)) >= cutoff else "dormant"
            )
            sessions.append({"id": record.id, "runtime": record.runtime, "session_ref": record.session_ref,
                "container_ref": record.container_ref, "title": record.title,
                "alias": record.alias, "state": item_lifecycle, "lifecycle": item_lifecycle,
                "destination_health": None if item_lifecycle == "closed" else record.state,
                "first_seen_at": _dashboard_time(record.first_seen_at), "last_seen_at": _dashboard_time(record.last_seen_at),
                "closed_at": _dashboard_time(record.closed_at)})
        return JSONResponse(content={"sessions": sessions, "total": total, "offset": offset, "limit": limit,
                                     "as_of": _dashboard_time(as_of)})
    @app.get("/dashboard/api/relay/messages")
    def dashboard_relay_messages(
        limit: int = Query(50, ge=1, le=200),
        until: datetime | None = Query(None), before_created_at: datetime | None = Query(None), before_id: str | None = Query(None),
        since: datetime | None = Query(None), runtime: str | None = Query(None), container_ref: str | None = Query(None),
        endpoint_id: str | None = Query(None), peer_endpoint_id: str | None = Query(None),
        delivery_state: Literal["pending", "claimed", "delivered", "expired"] | None = Query(None),
    ) -> JSONResponse:
        if (before_created_at is None) != (before_id is None):
            raise HTTPException(status_code=422, detail="before_created_at and before_id must be supplied together")
        if peer_endpoint_id is not None and endpoint_id is None:
            raise HTTPException(status_code=422, detail="peer_endpoint_id requires endpoint_id")
        storage = app.state.pallium_service._storage
        if not isinstance(storage, SQLiteStorageProvider):
            return JSONResponse(content={"error": "requires SQLite backend"}, status_code=501)
        as_of = _dashboard_utc(until) or datetime.now(timezone.utc)
        since = _dashboard_utc(since)
        before_created_at = _dashboard_utc(before_created_at)
        clause = RelayMessageRecord.created_at <= as_of
        if since is not None:
            clause = and_(clause, RelayMessageRecord.created_at >= since)
        if runtime is not None:
            clause = and_(clause, RelayMessageRecord.sender_runtime == runtime)
        if container_ref is not None:
            clause = and_(clause, RelayMessageRecord.container_ref == container_ref)
        delivery_filter = select(RelayDeliveryRecord.id).where(RelayDeliveryRecord.message_id == RelayMessageRecord.id)
        if endpoint_id is not None:
            endpoint_match = or_(RelayMessageRecord.sender_endpoint_id == endpoint_id,
                                 delivery_filter.where(RelayDeliveryRecord.recipient_endpoint_id == endpoint_id).exists())
            clause = and_(clause, endpoint_match)
            if peer_endpoint_id is not None:
                pair_match = or_(and_(RelayMessageRecord.sender_endpoint_id == endpoint_id,
                                      delivery_filter.where(RelayDeliveryRecord.recipient_endpoint_id == peer_endpoint_id).exists()),
                                 and_(RelayMessageRecord.sender_endpoint_id == peer_endpoint_id,
                                      delivery_filter.where(RelayDeliveryRecord.recipient_endpoint_id == endpoint_id).exists()))
                clause = and_(clause, pair_match)
        if delivery_state is not None:
            effective_delivery_state = (
                or_(RelayDeliveryRecord.state == "expired", and_(
                    RelayDeliveryRecord.state.in_(("pending", "claimed")), RelayMessageRecord.expires_at <= as_of,
                )) if delivery_state == "expired" else (
                    and_(RelayDeliveryRecord.state == delivery_state, RelayMessageRecord.expires_at > as_of)
                    if delivery_state in ("pending", "claimed") else RelayDeliveryRecord.state == delivery_state
                )
            )
            clause = and_(clause, delivery_filter.where(effective_delivery_state).exists())
        if before_created_at is not None:
            clause = and_(clause, or_(RelayMessageRecord.created_at < before_created_at,
                                      and_(RelayMessageRecord.created_at == before_created_at, RelayMessageRecord.id < before_id)))
        factory = getattr(storage, "_relay_session_factory", storage._session_factory)
        with factory() as session:
            total_clause = RelayMessageRecord.created_at <= as_of
            if since is not None:
                total_clause = and_(total_clause, RelayMessageRecord.created_at >= since)
            if runtime is not None:
                total_clause = and_(total_clause, RelayMessageRecord.sender_runtime == runtime)
            if container_ref is not None:
                total_clause = and_(total_clause, RelayMessageRecord.container_ref == container_ref)
            if endpoint_id is not None:
                endpoint_match = or_(RelayMessageRecord.sender_endpoint_id == endpoint_id,
                                     delivery_filter.where(RelayDeliveryRecord.recipient_endpoint_id == endpoint_id).exists())
                total_clause = and_(total_clause, endpoint_match)
                if peer_endpoint_id is not None:
                    pair_match = or_(and_(RelayMessageRecord.sender_endpoint_id == endpoint_id,
                                          delivery_filter.where(RelayDeliveryRecord.recipient_endpoint_id == peer_endpoint_id).exists()),
                                     and_(RelayMessageRecord.sender_endpoint_id == peer_endpoint_id,
                                          delivery_filter.where(RelayDeliveryRecord.recipient_endpoint_id == endpoint_id).exists()))
                    total_clause = and_(total_clause, pair_match)
            if delivery_state is not None:
                total_clause = and_(total_clause, delivery_filter.where(effective_delivery_state).exists())
            total = session.scalar(select(func.count()).select_from(RelayMessageRecord).where(total_clause)) or 0
            page = session.scalars(select(RelayMessageRecord).where(clause).order_by(
                RelayMessageRecord.created_at.desc(), RelayMessageRecord.id.desc()).limit(limit + 1)).all()
            has_more, messages = len(page) > limit, page[:limit]
            message_ids = [message.id for message in messages]
            delivery_query = select(RelayDeliveryRecord).where(RelayDeliveryRecord.message_id.in_(message_ids)).order_by(RelayDeliveryRecord.id)
            deliveries = session.scalars(delivery_query).all() if message_ids else []
        deliveries_by_message: dict[str, list[dict]] = {}
        message_by_id = {message.id: message for message in messages}
        for delivery in deliveries:
            expires = _dashboard_utc(message_by_id[delivery.message_id].expires_at)
            effective_state = "expired" if delivery.state in ("pending", "claimed") and expires <= as_of else delivery.state
            if delivery_state is not None and effective_state != delivery_state:
                continue
            deliveries_by_message.setdefault(delivery.message_id, []).append({"id": delivery.id,
                "recipient_runtime": delivery.recipient_runtime, "recipient_session_ref": delivery.recipient_session_ref,
                "recipient_endpoint_id": delivery.recipient_endpoint_id, "recipient_container_ref": delivery.recipient_container_ref,
                "state": effective_state, "claimed_at": _dashboard_time(delivery.claimed_at),
                "lease_expires_at": _dashboard_time(delivery.lease_expires_at), "delivered_at": _dashboard_time(delivery.delivered_at),
                "attempts": delivery.attempts})
        items = []
        for message in messages:
            expires = _dashboard_utc(message.expires_at)
            durable = expires.year >= 9999
            items.append({"id": message.id, "sender_runtime": message.sender_runtime, "sender_session_ref": message.sender_session_ref,
                "sender_endpoint_id": message.sender_endpoint_id, "recipient_selector": message.recipient_selector,
                "container_ref": message.container_ref,
                "payload": redact_sensitive(message.payload) if message.payload else message.payload, "redacted": bool(message.redacted),
                "in_reply_to": message.in_reply_to, "created_at": _dashboard_time(message.created_at),
                "expires_at": None if durable else _dashboard_time(expires), "effective_expired": not durable and expires <= as_of,
                "deliveries": deliveries_by_message.get(message.id, [])})
        return JSONResponse(content={"messages": items, "total": total, "limit": limit, "until": _dashboard_time(as_of),
                                     "as_of": _dashboard_time(as_of), "has_more": has_more,
                                     "next_before_created_at": _dashboard_time(messages[-1].created_at) if has_more else None,
                                     "next_before_id": messages[-1].id if has_more else None})
    @app.get("/dashboard/api/memories")
    def dashboard_memories(
        type: str | None = Query(None),
        lifecycle: str | None = Query(None),
        container_ref: str | None = Query(None),
        search: str | None = Query(None),
        limit: int = Query(50, ge=1),
        offset: int = Query(0, ge=0),
        sort: str | None = Query(None),
        include_soft_deleted: bool = Query(False),
        include_candidates: bool = Query(False),
    ) -> JSONResponse:
        limit = min(limit, 200)
        service = app.state.pallium_service
        storage = service._storage
        if not isinstance(storage, SQLiteStorageProvider):
            return JSONResponse(content={"error": "requires SQLite backend"}, status_code=501)

        with storage._session_factory() as session:
            stmt = select(MemoryObjectRecord)
            count_stmt = select(func.count()).select_from(MemoryObjectRecord)

            if type is not None:
                stmt = stmt.where(MemoryObjectRecord.type == type)
                count_stmt = count_stmt.where(MemoryObjectRecord.type == type)
            if lifecycle == "flagged":
                # Pseudo-lifecycle: memories with at least one flag entry
                flagged_ids = select(MemoryFlagRecord.memory_object_id).distinct().scalar_subquery()
                stmt = stmt.where(MemoryObjectRecord.id.in_(flagged_ids))
                count_stmt = count_stmt.where(MemoryObjectRecord.id.in_(flagged_ids))
            elif lifecycle is not None:
                stmt = stmt.where(MemoryObjectRecord.lifecycle == lifecycle)
                count_stmt = count_stmt.where(MemoryObjectRecord.lifecycle == lifecycle)
            elif not include_candidates:
                # PR 3 of operational_fact redesign: default filter —
                # hide ``candidate`` (and any future non-allowlist)
                # rows unless the caller explicitly passes
                # ``include_candidates=1`` or an exact
                # ``?lifecycle=candidate`` filter. Mirrors the storage
                # default at ``list_memory_objects``.
                stmt = stmt.where(
                    MemoryObjectRecord.lifecycle.in_(_DASHBOARD_VISIBLE_LIFECYCLES)
                )
                count_stmt = count_stmt.where(
                    MemoryObjectRecord.lifecycle.in_(_DASHBOARD_VISIBLE_LIFECYCLES)
                )
            if container_ref is not None:
                stmt = stmt.where(MemoryObjectRecord.container_ref == container_ref)
                count_stmt = count_stmt.where(MemoryObjectRecord.container_ref == container_ref)
            if search is not None and search.strip():
                like_pattern = f"%{search.strip()}%"
                stmt = stmt.where(MemoryObjectRecord.payload_json.ilike(like_pattern))
                count_stmt = count_stmt.where(MemoryObjectRecord.payload_json.ilike(like_pattern))
            if not include_soft_deleted:
                # PR 1 of operational_fact redesign: exclude tombstones
                # from the default dashboard view. Audit UI can pass
                # ``?include_soft_deleted=1`` to review purged rows.
                stmt = stmt.where(MemoryObjectRecord.is_soft_deleted == 0)
                count_stmt = count_stmt.where(MemoryObjectRecord.is_soft_deleted == 0)

            total = session.scalar(count_stmt) or 0

            if sort == "most_negative":
                # Left-join feedback counts so we can order by not_relevant count descending
                from sqlalchemy import Integer, case, literal_column, outerjoin
                neg_count = (
                    select(
                        MemoryFeedbackRecord.memory_object_id,
                        func.count().label("cnt"),
                    )
                    .where(MemoryFeedbackRecord.rating == "not_relevant")
                    .group_by(MemoryFeedbackRecord.memory_object_id)
                    .subquery()
                )
                stmt = (
                    select(MemoryObjectRecord)
                    .outerjoin(neg_count, MemoryObjectRecord.id == neg_count.c.memory_object_id)
                    .order_by(func.coalesce(neg_count.c.cnt, 0).desc(), MemoryObjectRecord.created_at.desc())
                )
                if type is not None:
                    stmt = stmt.where(MemoryObjectRecord.type == type)
                if lifecycle == "flagged":
                    flagged_ids = select(MemoryFlagRecord.memory_object_id).distinct().scalar_subquery()
                    stmt = stmt.where(MemoryObjectRecord.id.in_(flagged_ids))
                elif lifecycle is not None:
                    stmt = stmt.where(MemoryObjectRecord.lifecycle == lifecycle)
                elif not include_candidates:
                    stmt = stmt.where(
                        MemoryObjectRecord.lifecycle.in_(_DASHBOARD_VISIBLE_LIFECYCLES)
                    )
                if container_ref is not None:
                    stmt = stmt.where(MemoryObjectRecord.container_ref == container_ref)
                if search is not None and search.strip():
                    like_pattern = f"%{search.strip()}%"
                    stmt = stmt.where(MemoryObjectRecord.payload_json.ilike(like_pattern))
                if not include_soft_deleted:
                    # Pre-PR-3 bug: the ``most_negative`` sort branch
                    # rebuilt ``stmt`` from scratch but forgot to
                    # re-apply the is_soft_deleted filter, leaking
                    # tombstoned rows to this view. Fixed as part of
                    # PR 3's dashboard audit.
                    stmt = stmt.where(MemoryObjectRecord.is_soft_deleted == 0)
            else:
                stmt = stmt.order_by(MemoryObjectRecord.created_at.desc())

            stmt = stmt.offset(offset).limit(limit)
            records = session.scalars(stmt).all()

            memory_ids = [r.id for r in records]

            # Batch-fetch feedback counts for these memories
            feedback_counts: dict[str, dict[str, int]] = {}
            if memory_ids:
                fb_rows = session.execute(
                    select(
                        MemoryFeedbackRecord.memory_object_id,
                        MemoryFeedbackRecord.rating,
                        func.count(),
                    )
                    .where(MemoryFeedbackRecord.memory_object_id.in_(memory_ids))
                    .group_by(MemoryFeedbackRecord.memory_object_id, MemoryFeedbackRecord.rating)
                ).all()
                for mem_id, rating, count in fb_rows:
                    feedback_counts.setdefault(mem_id, {"relevant": 0, "not_relevant": 0})
                    feedback_counts[mem_id][rating] = count

        memories = []
        for rec in records:
            payload = json.loads(rec.payload_json) if rec.payload_json else {}
            envelope = json.loads(rec.envelope_json) if rec.envelope_json else {}
            confidence = envelope.get("confidence", "unknown")
            created_at = rec.created_at
            if created_at and created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)

            fb = feedback_counts.get(rec.id)

            # Prefer the stored subject column when populated; fall
            # back to the shared subject helper so older rows (subject
            # column NULL before the writer landed) and types whose
            # subject lives only in payload still surface cleanly.
            subject = rec.subject or subject_text_for_payload(rec.type, payload)
            display_text = _extract_display_text(payload) or subject

            memories.append({
                "id": rec.id,
                "type": rec.type,
                "lifecycle": rec.lifecycle,
                "container_ref": rec.container_ref,
                "display_text": display_text,
                "confidence": confidence,
                "created_at": created_at.isoformat() if created_at else None,
                "visibility": rec.visibility,
                "actor_ref": rec.actor_ref,
                "origin_agent_id": rec.origin_agent_id,
                "origin_session_id": rec.origin_session_id,
                "subject": subject,
                "schema_id": rec.schema_id,
                "payload": payload,
                "feedback": fb,
            })

        return JSONResponse(content={
            "memories": memories,
            "total": total,
            "offset": offset,
            "limit": limit,
        })

    @app.get("/dashboard/api/memories/{memory_object_id}/feedback")
    def dashboard_memory_feedback(memory_object_id: str) -> JSONResponse:
        service = app.state.pallium_service
        storage = service._storage
        if not isinstance(storage, SQLiteStorageProvider):
            return JSONResponse(content={"error": "requires SQLite backend"}, status_code=501)

        with storage._session_factory() as session:
            rows = session.scalars(
                select(MemoryFeedbackRecord)
                .where(MemoryFeedbackRecord.memory_object_id == memory_object_id)
                .order_by(MemoryFeedbackRecord.created_at.desc())
            ).all()

        items = []
        for r in rows:
            created_at = r.created_at
            if created_at and created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            items.append({
                "id": r.id,
                "rating": r.rating,
                "reason": r.reason,
                "query_context": r.query_context,
                "rater_ref": r.rater_ref,
                "created_at": created_at.isoformat() if created_at else None,
            })

        return JSONResponse(content={"items": items})

    @app.get("/dashboard/api/memories/{memory_object_id}/flags")
    def dashboard_memory_flags(memory_object_id: str) -> JSONResponse:
        service = app.state.pallium_service
        storage = service._storage
        if not isinstance(storage, SQLiteStorageProvider):
            return JSONResponse(content={"error": "requires SQLite backend"}, status_code=501)

        with storage._session_factory() as session:
            rows = session.scalars(
                select(MemoryFlagRecord)
                .where(MemoryFlagRecord.memory_object_id == memory_object_id)
                .order_by(MemoryFlagRecord.flagged_at.desc())
            ).all()

        items = []
        for r in rows:
            flagged_at = r.flagged_at
            if flagged_at and flagged_at.tzinfo is None:
                flagged_at = flagged_at.replace(tzinfo=timezone.utc)
            items.append({
                "id": r.id,
                "reason": r.reason,
                "source_ref": r.source_ref,
                "flagged_at": flagged_at.isoformat() if flagged_at else None,
            })

        return JSONResponse(content={"items": items})

    def _get_metrics_store() -> MetricsStore | None:
        return getattr(app.state, "metrics_store", None)

    @app.get("/dashboard/api/metrics/query")
    def dashboard_metrics_query(
        category: str | None = Query(None),
        event_type: str | None = Query(None),
        container_ref: str | None = Query(None),
        thread_ref: str | None = Query(None),
        since: str | None = Query(None),
        until: str | None = Query(None),
        limit: int = Query(100, ge=1),
    ) -> JSONResponse:
        metrics_store = _get_metrics_store()
        if metrics_store is None:
            return JSONResponse(content={"error": "requires SQLite backend"}, status_code=501)

        limit = min(limit, 1000)

        since_dt: datetime | None = None
        until_dt: datetime | None = None
        if since is not None:
            try:
                since_dt = datetime.fromisoformat(since)
                if since_dt.tzinfo is None:
                    since_dt = since_dt.replace(tzinfo=timezone.utc)
            except ValueError:
                return JSONResponse(content={"error": "invalid 'since' datetime"}, status_code=422)
        if until is not None:
            try:
                until_dt = datetime.fromisoformat(until)
                if until_dt.tzinfo is None:
                    until_dt = until_dt.replace(tzinfo=timezone.utc)
            except ValueError:
                return JSONResponse(content={"error": "invalid 'until' datetime"}, status_code=422)

        rows = metrics_store.query(
            category=category,
            event_type=event_type,
            container_ref=container_ref,
            thread_ref=thread_ref,
            since=since_dt,
            until=until_dt,
            limit=limit,
        )

        metrics = []
        for row in rows:
            ts = row.timestamp
            if ts is not None and ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            metrics.append({
                "id": row.id,
                "timestamp": ts.isoformat() if ts else None,
                "category": row.category,
                "event_type": row.event_type,
                "container_ref": row.container_ref,
                "thread_ref": row.thread_ref,
                "actor_ref": row.actor_ref,
                "value": row.value,
                "payload": row.payload,
            })

        return JSONResponse(content={"metrics": metrics, "count": len(metrics)})

    @app.get("/dashboard/api/metrics/aggregate")
    def dashboard_metrics_aggregate(
        category: str = Query(...),
        event_type: str | None = Query(None),
        container_ref: str | None = Query(None),
        since: str | None = Query(None),
        until: str | None = Query(None),
        group_by: str | None = Query(None),
    ) -> JSONResponse:
        metrics_store = _get_metrics_store()
        if metrics_store is None:
            return JSONResponse(content={"error": "requires SQLite backend"}, status_code=501)

        resolved_group_by = group_by or "day"
        if resolved_group_by not in ("hour", "day", "week"):
            return JSONResponse(
                content={"error": "group_by must be one of: hour, day, week"},
                status_code=422,
            )

        since_dt: datetime | None = None
        until_dt: datetime | None = None
        if since is not None:
            try:
                since_dt = datetime.fromisoformat(since)
                if since_dt.tzinfo is None:
                    since_dt = since_dt.replace(tzinfo=timezone.utc)
            except ValueError:
                return JSONResponse(content={"error": "invalid 'since' datetime"}, status_code=422)
        if until is not None:
            try:
                until_dt = datetime.fromisoformat(until)
                if until_dt.tzinfo is None:
                    until_dt = until_dt.replace(tzinfo=timezone.utc)
            except ValueError:
                return JSONResponse(content={"error": "invalid 'until' datetime"}, status_code=422)

        buckets = metrics_store.aggregate(
            category=category,
            event_type=event_type,
            container_ref=container_ref,
            since=since_dt,
            until=until_dt,
            group_by=resolved_group_by,
        )

        return JSONResponse(content={
            "buckets": [
                {
                    "bucket": b.bucket,
                    "event_type": b.event_type,
                    "count": b.count,
                    "sum_value": b.sum_value,
                    "avg_value": b.avg_value,
                }
                for b in buckets
            ]
        })

    @app.get("/dashboard/api/metrics/totals")
    def dashboard_metrics_totals(
        category: str = Query(...),
        container_ref: str | None = Query(None),
        window_hours: int = Query(24, ge=1, le=720),
    ) -> JSONResponse:
        """Returns per-event_type totals for two windows in one round-trip:
        - `recent`: events in the last `window_hours` (default 24h)
        - `alltime`: every event ever recorded for this category

        Each window maps event_type -> {count, sum_value}. Sum is the
        SUM(value) — useful for events whose `value` carries a count
        (e.g. injection.value = blocks_injected).
        """
        metrics_store = _get_metrics_store()
        if metrics_store is None:
            return JSONResponse(content={"error": "requires SQLite backend"}, status_code=501)

        now = datetime.now(tz=timezone.utc)
        cutoff = now - timedelta(hours=window_hours)

        recent_buckets = metrics_store.aggregate(
            category=category,
            container_ref=container_ref,
            since=cutoff,
            group_by="day",
        )
        alltime_buckets = metrics_store.aggregate(
            category=category,
            container_ref=container_ref,
            group_by="day",
        )

        def _fold(buckets) -> dict[str, dict[str, float]]:
            out: dict[str, dict[str, float]] = {}
            for b in buckets:
                slot = out.setdefault(b.event_type, {"count": 0, "sum_value": 0.0})
                slot["count"] += b.count
                slot["sum_value"] += b.sum_value
            return out

        return JSONResponse(content={
            "category": category,
            "container_ref": container_ref,
            "window_hours": window_hours,
            "recent": _fold(recent_buckets),
            "alltime": _fold(alltime_buckets),
            "as_of": now.isoformat(),
        })

    @app.get("/dashboard/api/feedback/stats")
    def dashboard_feedback_stats() -> JSONResponse:
        service = app.state.pallium_service
        storage = service._storage
        if not isinstance(storage, SQLiteStorageProvider):
            return JSONResponse(content={"error": "requires SQLite backend"}, status_code=501)

        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=24)

        with storage._session_factory() as session:
            rows = session.execute(
                select(MemoryFeedbackRecord.rating, func.count())
                .group_by(MemoryFeedbackRecord.rating)
            ).all()
            rows_24h = session.execute(
                select(MemoryFeedbackRecord.rating, func.count())
                .where(MemoryFeedbackRecord.created_at >= cutoff)
                .group_by(MemoryFeedbackRecord.rating)
            ).all()

        counts = {"relevant": 0, "not_relevant": 0}
        for rating, count in rows:
            counts[rating] = count

        counts_24h = {"relevant": 0, "not_relevant": 0}
        for rating, count in rows_24h:
            counts_24h[rating] = count

        total = counts["relevant"] + counts["not_relevant"]
        total_24h = counts_24h["relevant"] + counts_24h["not_relevant"]
        return JSONResponse(content={
            "total": total,
            "relevant": counts["relevant"],
            "not_relevant": counts["not_relevant"],
            "not_relevant_rate": round(counts["not_relevant"] / total, 3) if total > 0 else None,
            "total_24h": total_24h,
            "not_relevant_24h": counts_24h["not_relevant"],
            "not_relevant_rate_24h": round(counts_24h["not_relevant"] / total_24h, 3) if total_24h > 0 else None,
        })
