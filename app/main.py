from __future__ import annotations

import logging
import threading

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


def create_app(config: AppConfig | None = None, routing_overrides: RoutingOverrides | None = None) -> FastAPI:
    app = FastAPI(title="Pallium", version="0.1.0")
    service = build_service(config, routing_overrides=routing_overrides)
    app.state.pallium_service = service
    app.include_router(build_router(service))
    # Start vector reconciliation daemon if vector index is active
    if service._vector_index is not None:
        app.state._reconcile_stop = _start_reconcile_thread(service)
    # Mount MCP endpoint — the sub-app serves at /mcp internally,
    # so we mount at root to make the external path /mcp.
    # API routes are checked first; the mount is a fallback.
    try:
        from app.mcp.server import create_server as create_mcp_server
        mcp_server = create_mcp_server()
        app.mount("", mcp_server.streamable_http_app())
        logger.info("MCP endpoint available at /mcp")
    except ImportError:
        logger.warning("MCP endpoint not available: mcp[cli] not installed. Run: pip install 'mcp[cli]'")
    return app


def app() -> FastAPI:
    """ASGI factory for uvicorn --factory mode."""
    return create_app()
