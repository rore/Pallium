from __future__ import annotations

import contextlib
import logging
import threading
from collections.abc import AsyncIterator

from fastapi import FastAPI

from app.config import AppConfig
from app.dependencies import build_router, build_service
from core.service import PalliumService
from semantic.agent_conversation_memory_routing import RoutingOverrides

logger = logging.getLogger(__name__)

RECONCILE_INTERVAL_SECONDS = 2.0


def _start_reconcile_thread(
    service: PalliumService,
    interval: float = RECONCILE_INTERVAL_SECONDS,
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
            except Exception:
                logger.debug("Vector reconciliation error in daemon thread", exc_info=True)

    thread = threading.Thread(target=loop, daemon=True, name="vector-reconcile")
    thread.start()
    return stop


def _build_mcp_lifespan(app_ref: FastAPI):
    """Build a lifespan that initializes the MCP session manager if available."""
    try:
        from app.mcp.server import create_server as create_mcp_server
    except ImportError:
        logger.warning("MCP endpoint not available: mcp[cli] not installed. Run: pip install 'mcp[cli]'")
        return None

    mcp_server = create_mcp_server()
    mcp_app = mcp_server.streamable_http_app()
    # Get the session manager for lifespan management
    session_manager = mcp_server._session_manager

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with session_manager.run():
            yield

    # Mount the MCP sub-app at root — its internal route is /mcp
    app_ref.mount("", mcp_app)
    logger.info("MCP endpoint available at /mcp")
    return lifespan


def create_app(config: AppConfig | None = None, routing_overrides: RoutingOverrides | None = None) -> FastAPI:
    # Build MCP lifespan first (needs to mount before app is fully configured)
    # We create a temporary app to check MCP availability, then create the real one
    mcp_lifespan = None
    try:
        from app.mcp.server import create_server as create_mcp_server
        _mcp_available = True
    except ImportError:
        _mcp_available = False
        logger.warning("MCP endpoint not available: mcp[cli] not installed. Run: pip install 'mcp[cli]'")

    if _mcp_available:
        mcp_server = create_mcp_server()
        mcp_app = mcp_server.streamable_http_app()
        session_manager = mcp_server._session_manager

        @contextlib.asynccontextmanager
        async def mcp_lifespan(app: FastAPI) -> AsyncIterator[None]:
            async with session_manager.run():
                yield

    app = FastAPI(title="Pallium", version="0.1.0", lifespan=mcp_lifespan)
    service = build_service(config, routing_overrides=routing_overrides)
    app.state.pallium_service = service
    app.include_router(build_router(service))
    # Start vector reconciliation daemon if vector index is active
    if service._vector_index is not None:
        app.state._reconcile_stop = _start_reconcile_thread(service)
    # Mount MCP sub-app at root — its internal route is /mcp
    if _mcp_available:
        app.mount("", mcp_app)
        logger.info("MCP endpoint available at /mcp")
    return app


def app() -> FastAPI:
    """ASGI factory for uvicorn --factory mode."""
    return create_app()
