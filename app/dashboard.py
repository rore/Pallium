from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import and_, func, or_, select

from storage.metrics import MetricsStore
from storage.sqlite import SQLiteStorageProvider, _extract_display_text
from core.subject import subject_text_for_payload
from storage.sqlite_schema import (
    MemoryFeedbackRecord, MemoryFlagRecord, MemoryObjectRecord,
    RelayDeliveryRecord, RelayMessageRecord, RelaySessionRecord,
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
}


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
        service = app.state.pallium_service
        storage = service._storage
        if not isinstance(storage, SQLiteStorageProvider):
            return JSONResponse(content={"error": "requires SQLite backend"}, status_code=501)

        with storage._session_factory() as session:
            rows = session.execute(
                select(MemoryObjectRecord.container_ref)
                .where(MemoryObjectRecord.container_ref.isnot(None))
                .distinct()
                .order_by(MemoryObjectRecord.container_ref)
            ).scalars().all()

        return JSONResponse(content={"containers": list(rows)})

    @app.get("/dashboard/api/actors")
    def dashboard_actors() -> JSONResponse:
        service = app.state.pallium_service
        storage = service._storage
        if not isinstance(storage, SQLiteStorageProvider):
            return JSONResponse(content={"error": "requires SQLite backend"}, status_code=501)

        with storage._session_factory() as session:
            rows = session.execute(
                select(MemoryObjectRecord.actor_ref)
                .where(MemoryObjectRecord.actor_ref.isnot(None))
                .distinct()
                .order_by(MemoryObjectRecord.actor_ref)
            ).scalars().all()

        return JSONResponse(content={"actors": list(rows)})

    @app.get("/dashboard/api/activity")
    def dashboard_activity(limit: int = Query(10, ge=1, le=50)) -> JSONResponse:
        service = app.state.pallium_service
        storage = service._storage
        if not isinstance(storage, SQLiteStorageProvider):
            return JSONResponse(content={"error": "requires SQLite backend"}, status_code=501)

        with storage._session_factory() as session:
            records = session.scalars(
                select(MemoryObjectRecord)
                .order_by(MemoryObjectRecord.created_at.desc())
                .limit(limit)
            ).all()

        items = []
        for rec in records:
            payload = json.loads(rec.payload_json) if rec.payload_json else {}
            created_at = rec.created_at
            if created_at and created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            items.append({
                "event": "memory_created",
                "type": rec.type,
                "display_text": _extract_display_text(payload),
                "container_ref": rec.container_ref,
                "created_at": created_at.isoformat() if created_at else None,
            })

        return JSONResponse(content={"items": items})

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

        with storage._session_factory() as session:
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
