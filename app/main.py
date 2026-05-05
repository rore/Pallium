from __future__ import annotations

import contextlib
import logging
import threading
import time
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from app.config import AppConfig
from app.dashboard import mount_dashboard
from app.dependencies import build_router, build_service, build_storage_provider
from app.snapshot import resolve_live_db_path
from core.observability import QueryStats
from core.service import PalliumService
from semantic.agent_conversation_memory_routing import RoutingOverrides
from storage.metrics import MetricsStore
from storage.sqlite import SQLiteStorageProvider
from storage.sqlite_schema import MemoryObjectRecord, SourceItemRecord

if TYPE_CHECKING:
    from core.rebuild_coordinator import RebuildCoordinator

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


def _recover_interrupted_swap(index_path: Path) -> None:
    """Recover from a crash during atomic file swap.

    Two crash windows exist:
    1. After live→.old rename but before shadow→live: live files missing, .old has good copy → rollback
    2. After shadow→live but before .old cleanup: both live and .old exist → forward (delete .old)
    """
    old_meta = Path(f"{index_path}.meta.json.old")
    if not old_meta.exists():
        return

    live_meta = Path(f"{index_path}.meta.json")
    if not live_meta.exists():
        # Crash window 1: live files gone, .old is the only good copy → rollback
        from storage.vector_index import _replace_with_retry
        for suffix in ["", ".meta.json", ".idmap.json"]:
            old_path = Path(f"{index_path}{suffix}.old")
            live_path = Path(f"{index_path}{suffix}") if suffix else index_path
            if old_path.exists():
                _replace_with_retry(str(old_path), str(live_path))
        logger.info("Rolled back interrupted swap at %s (restored from .old)", index_path)
    else:
        # Crash window 2: swap completed, .old is stale backup → forward cleanup
        for suffix in ["", ".meta.json", ".idmap.json"]:
            Path(f"{index_path}{suffix}.old").unlink(missing_ok=True)
        logger.info("Cleaned interrupted swap remnants at %s", index_path)


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

    # Create MetricsStore from storage before building the service so we can
    # wire it into QueryStats at construction time.
    metrics_store: MetricsStore | None = None
    try:
        early_storage = build_storage_provider(resolved_config)
        if isinstance(early_storage, SQLiteStorageProvider):
            metrics_store = MetricsStore(early_storage._session_factory)
    except Exception:
        logger.warning("MetricsStore could not be initialized; metrics persistence disabled", exc_info=True)

    query_stats = QueryStats(metrics_store=metrics_store)
    build_result = build_service(resolved_config, routing_overrides=routing_overrides, query_stats=query_stats)
    service = build_result.service

    @contextlib.asynccontextmanager
    async def app_lifespan(app_instance: FastAPI) -> AsyncIterator[None]:
        # Start reconcile thread inside lifespan so shutdown stops it cleanly.
        stop: threading.Event | None = None
        rebuild_coordinator: "RebuildCoordinator | None" = None
        if build_result.index_holder.is_available:
            reconcile_done = threading.Event()
            app_instance.state._reconcile_done = reconcile_done
            stop = _start_reconcile_thread(
                service, reconcile_done=reconcile_done,
            )
            app_instance.state._reconcile_stop = stop
        else:
            app_instance.state._reconcile_done = None

        # Start background rebuild if needed
        if build_result.rebuild_needed and build_result.embedding_provider is not None:
            from core.rebuild_coordinator import RebuildCoordinator
            from semantic.agent_conversation_memory_embedding import EMBEDDING_SCHEMA_VERSION

            _recover_interrupted_swap(build_result.index_path)
            RebuildCoordinator.cleanup_orphaned_rebuild(build_result.index_path)

            rebuild_coordinator = RebuildCoordinator(
                storage=service._storage,
                embedding_provider=build_result.embedding_provider,
                index_holder=build_result.index_holder,
                index_path=build_result.index_path,
                target_model_name=build_result.embedding_provider.model_name(),
                target_dimensions=build_result.embedding_provider.dimensions(),
                target_schema_version=EMBEDDING_SCHEMA_VERSION,
                reason=build_result.rebuild_reason,
                on_swap_callback=service._vector_embedder.reset_reconcile_state,
            )
            rebuild_coordinator.start()
            app_instance.state._rebuild_coordinator = rebuild_coordinator

        app_instance.state._lifespan_complete = True
        try:
            if mcp_available and session_manager is not None:
                async with session_manager.run():
                    yield
            else:
                yield
        finally:
            if rebuild_coordinator is not None:
                rebuild_coordinator.stop()
            if stop is not None:
                stop.set()

    app = FastAPI(title="Pallium", version="0.1.0", lifespan=app_lifespan)
    app.state.pallium_service = service
    app.state._lifespan_complete = False
    app.state._reconcile_done = None
    app.state._rebuild_coordinator = None
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

    @app.post("/shutdown")
    def shutdown(request: Request) -> JSONResponse:
        client = request.client
        if client is None or client.host not in ("127.0.0.1", "::1"):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        import os, signal
        os.kill(os.getpid(), signal.SIGINT)
        return JSONResponse({"status": "shutting_down"})

    @app.get("/status")
    def status() -> JSONResponse:
        storage = service._storage
        if not isinstance(storage, SQLiteStorageProvider):
            return JSONResponse(content={"error": "status requires SQLite backend"}, status_code=501)

        # --- DB counts (best-effort) ---
        pending_count: int | None = None
        oldest_pending_age: float | None = None
        total_source: int | None = None
        total_memory: int | None = None
        active_memory: int | None = None
        try:
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

                active_memory = session.scalar(
                    select(func.count()).select_from(MemoryObjectRecord).where(
                        MemoryObjectRecord.lifecycle == "active"
                    )
                ) or 0

            if oldest_pending_created is not None:
                now_utc = datetime.now(timezone.utc)
                if oldest_pending_created.tzinfo is None:
                    oldest_pending_created = oldest_pending_created.replace(tzinfo=timezone.utc)
                oldest_pending_age = round((now_utc - oldest_pending_created).total_seconds(), 1)
        except Exception:
            logger.warning("status: db query failed", exc_info=True)

        # --- Snapshot status (best-effort) ---
        snapshot_info: dict = {"enabled": resolved_config.snapshot.enabled}
        try:
            snapshot_config = resolved_config.snapshot
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
        except Exception:
            logger.warning("status: snapshot info failed", exc_info=True)
            snapshot_info.setdefault("last_snapshot_at", None)
            snapshot_info.setdefault("snapshot_count", None)

        # --- Vector index readiness ---
        vector_index_configured = service._vector_index is not None
        reconcile_done_event = getattr(app.state, "_reconcile_done", None)
        vector_index_ready = (
            not vector_index_configured
            or (reconcile_done_event is not None and reconcile_done_event.is_set())
        )

        # --- Storage sizes (best-effort) ---
        def _file_size_mb(path: str) -> float | None:
            try:
                p = Path(path)
                return round(p.stat().st_size / (1024 * 1024), 2) if p.exists() else None
            except Exception:
                return None

        storage_info: dict = {"sqlite_mb": None, "vector_index_mb": None}
        try:
            sqlite_path = resolve_live_db_path(resolved_config.sqlite_url)
            storage_info["sqlite_mb"] = _file_size_mb(sqlite_path)
            vector_path = resolved_config.vector_index.index_path
            storage_info["vector_index_mb"] = _file_size_mb(vector_path) if vector_index_configured else None
        except Exception:
            logger.warning("status: storage size failed", exc_info=True)

        uptime = round(time.monotonic() - app.state._start_time, 1)

        # --- Query stats (best-effort) ---
        query_info: dict | None = None
        try:
            query_info = query_stats.snapshot()
        except Exception:
            logger.warning("status: query stats failed", exc_info=True)

        # --- Vector rebuild status ---
        rebuild_info: dict | None = None
        rebuild_coord = getattr(app.state, "_rebuild_coordinator", None)
        if rebuild_coord is not None:
            rebuild_info = rebuild_coord.status()

        return JSONResponse(content={
            "pending_items": pending_count,
            "oldest_pending_age_seconds": oldest_pending_age,
            "total_source_items": total_source,
            "total_memory_objects": total_memory,
            "active_memory_objects": active_memory,
            "snapshot": snapshot_info,
            "storage": storage_info,
            "vector_index_ready": vector_index_ready,
            "vector_rebuild": rebuild_info,
            "uptime_seconds": uptime,
            "query": query_info,
        })

    mount_dashboard(app)
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
