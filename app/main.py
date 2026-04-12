from __future__ import annotations

import contextlib
import logging
import threading
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.config import AppConfig
from app.dependencies import build_router, build_service
from core.service import PalliumService
from semantic.agent_conversation_memory_routing import RoutingOverrides

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
        mcp_server = create_mcp_server()
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
