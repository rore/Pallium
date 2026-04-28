from __future__ import annotations

import json
import logging
from datetime import timezone
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from storage.sqlite import SQLiteStorageProvider
from storage.sqlite_schema import MemoryObjectRecord

logger = logging.getLogger(__name__)

_DASHBOARD_HTML_PATH = Path(__file__).parent / "dashboard.html"


def _extract_display_text(payload: dict) -> str:
    for key in ("summary", "decision", "investigation_outcome", "interest_text", "constraint_text", "carry_forward_answer"):
        val = payload.get(key)
        if val:
            return str(val)
    return ""


def mount_dashboard(app: FastAPI) -> None:
    assets_dir = Path(__file__).resolve().parent.parent / "assets"
    app.mount("/static", StaticFiles(directory=str(assets_dir)), name="static")

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard_page() -> HTMLResponse:
        html = _DASHBOARD_HTML_PATH.read_text(encoding="utf-8")
        return HTMLResponse(content=html)

    @app.get("/dashboard/api/memories")
    def dashboard_memories(
        type: str | None = Query(None),
        lifecycle: str | None = Query(None),
        container_ref: str | None = Query(None),
        limit: int = Query(50, ge=1),
        offset: int = Query(0, ge=0),
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
            if lifecycle is not None:
                stmt = stmt.where(MemoryObjectRecord.lifecycle == lifecycle)
                count_stmt = count_stmt.where(MemoryObjectRecord.lifecycle == lifecycle)
            if container_ref is not None:
                stmt = stmt.where(MemoryObjectRecord.container_ref == container_ref)
                count_stmt = count_stmt.where(MemoryObjectRecord.container_ref == container_ref)

            total = session.scalar(count_stmt) or 0

            stmt = stmt.order_by(MemoryObjectRecord.created_at.desc())
            stmt = stmt.offset(offset).limit(limit)
            records = session.scalars(stmt).all()

        memories = []
        for rec in records:
            payload = json.loads(rec.payload_json) if rec.payload_json else {}
            envelope = json.loads(rec.envelope_json) if rec.envelope_json else {}
            confidence = envelope.get("confidence", "unknown")
            created_at = rec.created_at
            if created_at and created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)

            memories.append({
                "id": rec.id,
                "type": rec.type,
                "lifecycle": rec.lifecycle,
                "container_ref": rec.container_ref,
                "display_text": _extract_display_text(payload),
                "confidence": confidence,
                "created_at": created_at.isoformat() if created_at else None,
            })

        return JSONResponse(content={
            "memories": memories,
            "total": total,
            "offset": offset,
            "limit": limit,
        })
