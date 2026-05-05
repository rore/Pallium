from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from storage.metrics import MetricsStore
from storage.sqlite import SQLiteStorageProvider, _extract_display_text
from storage.sqlite_schema import MemoryFeedbackRecord, MemoryFlagRecord, MemoryObjectRecord, MetricRecord

logger = logging.getLogger(__name__)

_DASHBOARD_HTML_PATH = Path(__file__).parent / "dashboard.html"


def mount_dashboard(app: FastAPI) -> None:
    assets_dir = Path(__file__).resolve().parent.parent / "assets"
    app.mount("/static", StaticFiles(directory=str(assets_dir)), name="static")

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard_page() -> HTMLResponse:
        html = _DASHBOARD_HTML_PATH.read_text(encoding="utf-8")
        return HTMLResponse(content=html)

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

    @app.get("/dashboard/api/memories")
    def dashboard_memories(
        type: str | None = Query(None),
        lifecycle: str | None = Query(None),
        container_ref: str | None = Query(None),
        search: str | None = Query(None),
        limit: int = Query(50, ge=1),
        offset: int = Query(0, ge=0),
        sort: str | None = Query(None),
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
            if container_ref is not None:
                stmt = stmt.where(MemoryObjectRecord.container_ref == container_ref)
                count_stmt = count_stmt.where(MemoryObjectRecord.container_ref == container_ref)
            if search is not None and search.strip():
                like_pattern = f"%{search.strip()}%"
                stmt = stmt.where(MemoryObjectRecord.payload_json.ilike(like_pattern))
                count_stmt = count_stmt.where(MemoryObjectRecord.payload_json.ilike(like_pattern))

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
                if container_ref is not None:
                    stmt = stmt.where(MemoryObjectRecord.container_ref == container_ref)
                if search is not None and search.strip():
                    like_pattern = f"%{search.strip()}%"
                    stmt = stmt.where(MemoryObjectRecord.payload_json.ilike(like_pattern))
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

            memories.append({
                "id": rec.id,
                "type": rec.type,
                "lifecycle": rec.lifecycle,
                "container_ref": rec.container_ref,
                "display_text": _extract_display_text(payload),
                "confidence": confidence,
                "created_at": created_at.isoformat() if created_at else None,
                "visibility": rec.visibility,
                "subject": rec.subject,
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
        service = app.state.pallium_service
        storage = service._storage
        if not isinstance(storage, SQLiteStorageProvider):
            return None
        return MetricsStore(storage._session_factory)

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

    @app.get("/dashboard/api/metrics/query-activity")
    def dashboard_metrics_query_activity(
        days: int = Query(7, ge=1, le=365),
    ) -> JSONResponse:
        metrics_store = _get_metrics_store()
        if metrics_store is None:
            return JSONResponse(content={"error": "requires SQLite backend"}, status_code=501)

        since_dt = datetime.now(timezone.utc) - timedelta(days=days)

        event_types = ("injection", "skip", "flag", "feedback")
        buckets = metrics_store.aggregate(
            category="query",
            since=since_dt,
            group_by="day",
        )

        totals: dict[str, int] = {et: 0 for et in event_types}
        for b in buckets:
            if b.event_type in totals:
                totals[b.event_type] += b.count

        return JSONResponse(content={
            "buckets": [
                {
                    "bucket": b.bucket,
                    "event_type": b.event_type,
                    "count": b.count,
                }
                for b in buckets
            ],
            "totals": totals,
        })

    @app.get("/dashboard/api/metrics/work-trace")
    def dashboard_metrics_work_trace(
        limit: int = Query(20, ge=1),
    ) -> JSONResponse:
        service = app.state.pallium_service
        storage = service._storage
        if not isinstance(storage, SQLiteStorageProvider):
            return JSONResponse(content={"error": "requires SQLite backend"}, status_code=501)

        with storage._session_factory() as session:
            records = session.scalars(
                select(MemoryObjectRecord)
                .where(MemoryObjectRecord.type == "task_trace")
                .order_by(MemoryObjectRecord.created_at.desc())
                .limit(limit)
            ).all()

        sessions = []
        for rec in records:
            payload = json.loads(rec.payload_json) if rec.payload_json else {}
            created_at = rec.created_at
            if created_at and created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            sessions.append({
                "thread_ref": rec.subject,
                "timestamp": created_at.isoformat() if created_at else None,
                "turn_count": payload.get("turn_count", 0),
                "subject": payload.get("investigation_subject", ""),
                "exploratory_file_count": len(payload.get("exploratory_files", [])),
                "productive_file_count": len(payload.get("productive_files", [])),
                "has_outcome": "outcome" in payload,
            })

        return JSONResponse(content={"sessions": sessions})

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
