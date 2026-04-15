from __future__ import annotations

import contextlib
import logging
import threading
import time
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from app.config import AppConfig
from app.dependencies import build_router, build_service
from core.service import PalliumService
from semantic.agent_conversation_memory_routing import RoutingOverrides
from storage.sqlite import SQLiteStorageProvider
from storage.sqlite_schema import MemoryObjectRecord, SourceItemRecord

logger = logging.getLogger(__name__)

RECONCILE_INTERVAL_SECONDS = 2.0


def _start_reconcile_thread(
    service: PalliumService,
    *,
    interval: float = RECONCILE_INTERVAL_SECONDS,
    reconcile_done: threading.Event | None = None,
) -> threading.Event:
    """Start a daemon thread that periodically reconciles SQLite → usearch.

    The server process is the sole vector index owner. This thread syncs
    IndexEntry records (written by processor subprocesses to SQLite) into
    the in-memory usearch index. usearch is concurrent by design, so
    search() and add() can run simultaneously without locks.
    """
    stop = threading.Event()

    def loop() -> None:
        while not stop.wait(interval):
            try:
                service.reconcile_vector_index()
                if reconcile_done is not None:
                    reconcile_done.set()
            except Exception:
                logger.debug("Vector reconciliation error in daemon thread", exc_info=True)

    thread = threading.Thread(target=loop, daemon=True, name="vector-reconcile")
    thread.start()
    return stop


def create_app(config: AppConfig | None = None, routing_overrides: RoutingOverrides | None = None) -> FastAPI:
    # Check MCP availability
    mcp_available = False
    mcp_app = None
    session_manager = None
    try:
        from app.mcp.server import create_server as create_mcp_server
        mcp_available = True
        mcp_server = create_mcp_server(host="0.0.0.0")
        mcp_app = mcp_server.streamable_http_app()
        session_manager = mcp_server._session_manager
    except ImportError:
        logger.warning("MCP endpoint not available: mcp[cli] not installed. Run: pip install 'mcp[cli]'")

    resolved_config = config or AppConfig.from_env()
    service = build_service(resolved_config, routing_overrides=routing_overrides)

    @contextlib.asynccontextmanager
    async def app_lifespan(app_instance: FastAPI) -> AsyncIterator[None]:
        # Start reconcile thread inside lifespan so shutdown stops it cleanly.
        stop: threading.Event | None = None
        if service._vector_index is not None:
            reconcile_done = threading.Event()
            app_instance.state._reconcile_done = reconcile_done
            stop = _start_reconcile_thread(
                service, reconcile_done=reconcile_done,
            )
            app_instance.state._reconcile_stop = stop
        else:
            app_instance.state._reconcile_done = None
        app_instance.state._lifespan_complete = True
        try:
            if mcp_available and session_manager is not None:
                async with session_manager.run():
                    yield
            else:
                yield
        finally:
            if stop is not None:
                stop.set()

    app = FastAPI(title="Pallium", version="0.1.0", lifespan=app_lifespan)
    app.state.pallium_service = service
    app.state._lifespan_complete = False
    app.state._reconcile_done = None
    app.state._start_time = time.monotonic()

    @app.get("/health")
    def health() -> JSONResponse:
        lifespan_ok = getattr(app.state, "_lifespan_complete", False)

        vector_index_configured = service._vector_index is not None
        reconcile_done_event = getattr(app.state, "_reconcile_done", None)
        vector_index_ready = (
            not vector_index_configured
            or (reconcile_done_event is not None and reconcile_done_event.is_set())
        )

        ready = lifespan_ok and vector_index_ready

        body = {
            "status": "ok" if ready else "initializing",
            "vector_index_ready": vector_index_ready,
        }
        status_code = 200 if ready else 503
        return JSONResponse(content=body, status_code=status_code)

    @app.get("/status")
    def status() -> JSONResponse:
        storage = service._storage
        if not isinstance(storage, SQLiteStorageProvider):
            return JSONResponse(content={"error": "status requires SQLite backend"}, status_code=501)
        session_factory = storage._session_factory

        with session_factory() as session:
            pending_count = session.scalar(
                select(func.count()).select_from(SourceItemRecord).where(
                    SourceItemRecord.processing_status == "pending"
                )
            ) or 0

            oldest_pending_created = session.scalar(
                select(func.min(SourceItemRecord.created_at)).where(
                    SourceItemRecord.processing_status == "pending"
                )
            )

            total_source = session.scalar(
                select(func.count()).select_from(SourceItemRecord)
            ) or 0

            total_memory = session.scalar(
                select(func.count()).select_from(MemoryObjectRecord)
            ) or 0

        oldest_pending_age: float | None = None
        if oldest_pending_created is not None:
            now_utc = datetime.now(timezone.utc)
            if oldest_pending_created.tzinfo is None:
                oldest_pending_created = oldest_pending_created.replace(tzinfo=timezone.utc)
            oldest_pending_age = round((now_utc - oldest_pending_created).total_seconds(), 1)

        # Snapshot status
        snapshot_config = resolved_config.snapshot
        snapshot_info: dict = {"enabled": snapshot_config.enabled}
        if snapshot_config.enabled and snapshot_config.snapshot_path:
            snapshot_dir = Path(snapshot_config.snapshot_path)
            snapshots = sorted(
                snapshot_dir.glob("pallium-*.db"),
                key=lambda p: p.name,
                reverse=True,
            ) if snapshot_dir.is_dir() else []
            snapshot_info["snapshot_count"] = len(snapshots)
            if snapshots:
                mtime = snapshots[0].stat().st_mtime
                snapshot_info["last_snapshot_at"] = (
                    datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
                )
            else:
                snapshot_info["last_snapshot_at"] = None
        else:
            snapshot_info["last_snapshot_at"] = None
            snapshot_info["snapshot_count"] = 0

        vector_index_configured = service._vector_index is not None
        reconcile_done_event = getattr(app.state, "_reconcile_done", None)
        vector_index_ready = (
            not vector_index_configured
            or (reconcile_done_event is not None and reconcile_done_event.is_set())
        )

        uptime = round(time.monotonic() - app.state._start_time, 1)

        return JSONResponse(content={
            "pending_items": pending_count,
            "oldest_pending_age_seconds": oldest_pending_age,
            "total_source_items": total_source,
            "total_memory_objects": total_memory,
            "snapshot": snapshot_info,
            "vector_index_ready": vector_index_ready,
            "uptime_seconds": uptime,
        })

    app.include_router(build_router(
        service, audit_log_enabled=resolved_config.observability.query_audit_log,
    ))
    if mcp_available and mcp_app is not None:
        app.mount("", mcp_app)
        logger.info("MCP endpoint available at /mcp")
    return app


def app() -> FastAPI:
    """ASGI factory for uvicorn --factory mode."""
    return create_app()
