from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
import time
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from app.asyncio_windows_accept import apply_patch as _apply_accept_patch
from app.config import AppConfig
from app.dashboard import mount_dashboard
from app.claude_wake import start_claude_wake_reconciler
from app.dependencies import (
    build_claude_wake_registry,
    build_router,
    build_service,
    build_storage_provider,
    recover_expired_relay_wakes,
)
from app.snapshot import resolve_live_db_path
from core.observability import QueryStats
from core.relay import RelayService, RelayUnavailableError
from core.service import PalliumService
from semantic.agent_conversation_memory_routing import RoutingOverrides
from storage.metrics import MetricsStore
from storage.sqlite import SQLiteStorageProvider
from storage.sqlite_schema import (
    HistoricalLookupReuseEventRecord,
    MemoryObjectRecord,
    SourceItemRecord,
)

if TYPE_CHECKING:
    from core.rebuild_coordinator import RebuildCoordinator

logger = logging.getLogger(__name__)

# Patch upstream CPython defect that closes the listening socket on a
# single misbehaving client (WinError 64 etc.). Must run before uvicorn
# binds the server, hence module-level. No-op on non-Windows.
_apply_accept_patch()

RECONCILE_INTERVAL_SECONDS = 2.0


def _write_launch_token() -> Path | None:
    """Write the supervisor-supplied launch nonce + our pid to the run dir.

    The supervisor uses this file to verify that the process bound to its API
    port is actually the one it just spawned (not an orphan from a prior
    generation still holding the socket). See app/supervisor._wait_for_api.

    No-op when ``PALLIUM_API_LAUNCH_TOKEN`` is unset, so this stays compatible
    with direct invocations (`python -m app.run serve ...`) that don't go
    through the supervisor.
    """
    nonce = os.environ.get("PALLIUM_API_LAUNCH_TOKEN")
    if not nonce:
        return None
    home_env = os.environ.get("PALLIUM_HOME")
    home = Path(home_env) if home_env else Path.home() / ".pallium"
    run_dir = home / "run"
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        token_path = run_dir / "api_token"
        # Write atomically: write to .tmp then rename. Without atomicity the
        # supervisor can read a half-written file and decide nonce-mismatch.
        tmp_path = token_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps({"nonce": nonce, "pid": os.getpid()}), encoding="utf-8")
        os.replace(tmp_path, token_path)
        return token_path
    except OSError as exc:
        logger.warning("failed to write launch token: %s", exc)
        return None


def _remove_launch_token(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


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
    early_storage: SQLiteStorageProvider | None = None
    try:
        early_storage = build_storage_provider(resolved_config)
        if isinstance(early_storage, SQLiteStorageProvider):
            metrics_store = MetricsStore(early_storage._session_factory)
    except Exception:
        logger.warning("MetricsStore could not be initialized; metrics persistence disabled", exc_info=True)

    query_stats = QueryStats(metrics_store=metrics_store)
    build_result = build_service(resolved_config, routing_overrides=routing_overrides, query_stats=query_stats, metrics_store=metrics_store)
    service = build_result.service

    # Record service_start lifecycle event (fire-and-forget)
    if metrics_store is not None:
        try:
            metrics_store.record(
                "system", "service_start",
                payload={"packages_enabled": list(resolved_config.semantic_packages.keys())},
            )
        except Exception:
            pass

    @contextlib.asynccontextmanager
    async def app_lifespan(app_instance: FastAPI) -> AsyncIterator[None]:
        # Write the launch token as early as possible so the supervisor's
        # readiness probe can self-identify this process before any heavy
        # startup (vector reconcile, rebuild) extends the window during which
        # an orphan from a prior generation could be mistaken for us.
        token_path = _write_launch_token()
        app_instance.state._launch_token_path = token_path

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

        claude_wake_reconciler = None
        try:
            claude_wake_registry.recover_intents()
            relay_service = RelayService(build_result.storage)
            claude_wake_reconciler = start_claude_wake_reconciler(
                claude_wake_registry,
                relay_service,
                claim_recovery=lambda: recover_expired_relay_wakes(
                    relay_service, claude_wake_registry
                ),
            )
            claude_wake_registry.set_reconcile_signal(
                None if claude_wake_reconciler is None else claude_wake_reconciler.signal,
            )
            app_instance.state._claude_wake_reconciler = claude_wake_reconciler
        except RelayUnavailableError:
            app_instance.state._claude_wake_reconciler = None

        app_instance.state._lifespan_complete = True
        try:
            if mcp_available and session_manager is not None:
                async with session_manager.run():
                    yield
            else:
                yield
        finally:
            claude_wake_registry.set_reconcile_signal(None)
            if claude_wake_reconciler is not None:
                claude_wake_reconciler.stop()
            if rebuild_coordinator is not None:
                rebuild_coordinator.stop()
            if stop is not None:
                stop.set()
            _remove_launch_token(token_path)
            for storage_provider in (service._storage, early_storage):
                if isinstance(storage_provider, SQLiteStorageProvider):
                    storage_provider.close()

    app = FastAPI(title="Pallium", version="0.1.0", lifespan=app_lifespan)
    app.state.pallium_service = service
    app.state.metrics_store = metrics_store
    app.state._lifespan_complete = False
    app.state._reconcile_done = None
    app.state._rebuild_coordinator = None
    app.state._start_time = time.monotonic()

    @app.get("/health")
    def health() -> JSONResponse:
        lifespan_ok = getattr(app.state, "_lifespan_complete", False)

        vector_index_configured = service._vector_index is not None
        reconcile_done_event = getattr(app.state, "_reconcile_done", None)
        reconcile_done = reconcile_done_event is not None and reconcile_done_event.is_set()

        # Vector was expected (configured on) but the embedding provider failed
        # to initialize (index is None) → functional but impaired, not "not configured".
        vector_expected = bool(resolved_config.vector_index.enabled)
        embedding_provider_ok = (not vector_expected) or vector_index_configured

        # Ready when: index present + reconciled, OR vector genuinely not expected.
        # An expected-but-absent index (provider failed) is NOT ready — don't let
        # "index is None" masquerade as "not configured, therefore ready".
        vector_index_ready = (
            reconcile_done if vector_index_configured else not vector_expected
        )

        ready = lifespan_ok and vector_index_ready

        if not embedding_provider_ok:
            # Impaired: keep HTTP 200 so orchestration doesn't hard-fail; the
            # signal is the status/reasons fields.
            body = {
                "status": "degraded",
                "vector_index_ready": vector_index_ready,
                "embedding_provider_ok": False,
                "degraded_reasons": ["vector_embedding_provider_unavailable"],
            }
            return JSONResponse(content=body, status_code=200)

        body = {
            "status": "ok" if ready else "initializing",
            "vector_index_ready": vector_index_ready,
            "embedding_provider_ok": True,
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
                    snapshot_dir.glob("pallium-*.manifest.json"),
                    key=lambda p: p.name,
                    reverse=True,
                ) if snapshot_dir.is_dir() else []
                if snapshot_dir.is_dir() and not snapshots:
                    snapshots = sorted(
                        (path for path in snapshot_dir.glob("pallium-*.db") if not path.name.endswith(("-main.db", "-relay.db"))),
                        key=lambda p: p.name,
                        reverse=True,
                    )
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
        reconcile_done = reconcile_done_event is not None and reconcile_done_event.is_set()
        # Expected-but-failed embedding provider: configured on, yet index is None.
        vector_expected = bool(resolved_config.vector_index.enabled)
        embedding_provider_ok = (not vector_expected) or vector_index_configured
        vector_index_ready = (
            reconcile_done if vector_index_configured else not vector_expected
        )

        # --- Storage sizes (best-effort) ---
        def _file_size_mb(path: str) -> float | None:
            try:
                p = Path(path)
                return round(p.stat().st_size / (1024 * 1024), 2) if p.exists() else None
            except Exception:
                return None

        storage_info: dict = {"sqlite_mb": None, "relay_sqlite_mb": None, "relay_migration_ready": None, "vector_index_mb": None}
        try:
            sqlite_path = resolve_live_db_path(resolved_config.sqlite_url)
            storage_info["sqlite_mb"] = _file_size_mb(sqlite_path)
            relay_path = resolve_live_db_path(resolved_config.resolved_relay_sqlite_url)
            storage_info["relay_sqlite_mb"] = _file_size_mb(relay_path)
            relay_status = getattr(storage, "relay_database_status", None)
            if callable(relay_status):
                result = relay_status()
                storage_info["relay_migration_ready"] = (
                    result.get("migration_ready", result.get("ready"))
                    if isinstance(result, dict) else bool(result)
                )
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

        # --- Metrics summary (best-effort, last 24h) ---
        metrics_summary: dict | None = None
        _ms = getattr(app.state, "metrics_store", None)
        if _ms is not None:
            try:
                from datetime import timedelta
                day_ago = datetime.now(timezone.utc) - timedelta(days=1)
                recent = _ms.query(since=day_ago, limit=1000)
                by_cat: dict[str, int] = {}
                for r in recent:
                    by_cat[r.category] = by_cat.get(r.category, 0) + 1
                metrics_summary = {
                    "events_24h": len(recent),
                    "events_24h_by_category": by_cat,
                }
            except Exception:
                logger.warning("status: metrics summary failed", exc_info=True)

        # --- Historical-lookup reuse funnel (armed state + telemetry count) ---
        funnel_info: dict = {
            "armed": resolved_config.observability.historical_lookup_funnel,
            "events_recorded": None,
        }
        try:
            session_factory = storage._session_factory
            with session_factory() as session:
                funnel_info["events_recorded"] = session.scalar(
                    select(func.count()).select_from(HistoricalLookupReuseEventRecord)
                ) or 0
        except Exception:
            logger.warning("status: funnel count failed", exc_info=True)

        ingestion_issues = []
        for package_name, package in resolved_config.semantic_packages.items():
            if (
                not package.enabled
                or package_name not in service._semantic_plugins
                or package.implementation == "demo_agent_memory"
            ):
                continue
            provider = resolved_config.llm_providers.get(package.llm_provider or "")
            if provider is not None and (provider.api_key_env or provider.api_key_file) and not provider.api_key:
                ingestion_issues.append({
                    "package": package_name,
                    "provider": provider.name,
                    "reason": "missing_api_key",
                    "api_key_env": provider.api_key_env,
                })
        ingestion_info = {
            "status": "degraded" if ingestion_issues else "ok",
            "issues": ingestion_issues,
        }

        return JSONResponse(content={
            "pending_items": pending_count,
            "oldest_pending_age_seconds": oldest_pending_age,
            "total_source_items": total_source,
            "total_memory_objects": total_memory,
            "active_memory_objects": active_memory,
            "snapshot": snapshot_info,
            "storage": storage_info,
            "vector_index_ready": vector_index_ready,
            "embedding_provider_ok": embedding_provider_ok,
            "ingestion": ingestion_info,
            "vector_expected": vector_expected,
            "vector_rebuild": rebuild_info,
            "uptime_seconds": uptime,
            "query": query_info,
            "metrics_summary": metrics_summary,
            "historical_lookup_funnel": funnel_info,
        })

    mount_dashboard(app)
    claude_wake_registry = build_claude_wake_registry()
    app.state.claude_wake_registry = claude_wake_registry
    app.include_router(build_router(
        service,
        audit_log_enabled=resolved_config.observability.query_audit_log,
        relay_storage=build_result.storage,
        claude_wake_registry=claude_wake_registry,
    ))
    if mcp_available and mcp_app is not None:
        app.mount("", mcp_app)
        logger.info("MCP endpoint available at /mcp")
    return app


def app() -> FastAPI:
    """ASGI factory for uvicorn --factory mode."""
    return create_app()
