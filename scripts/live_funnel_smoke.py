#!/usr/bin/env python
"""Live-service smoke for the historical-lookup reuse funnel.

WHAT THIS VALIDATES (read carefully — this framing is deliberate):

  (a) The installed service (default :19836) is UP and the reuse funnel is
      ARMED, via a strictly READ-ONLY ``GET /status``. No write of any kind
      ever touches the installed service.

  (b) The search -> expand -> persist chain works on PRODUCTION-SHAPED data.
      It does this by snapshotting the live SQLite DB into a *disposable*
      copy (via ``VACUUM INTO``) and driving the chain against a SHORT-LIVED
      scratch server bound to that COPY on a scratch port.

WHAT THIS DOES **NOT** VALIDATE:

  The scratch server runs THIS working tree's code, not the installed
  binary. So check (b) does NOT exercise the installed service's write path
  — it is equivalent to the in-process e2e, just over real HTTP on a scratch
  port against a production-shaped DB. A PASS here is NOT a deploy
  verification of the installed write path. The only signal that touches the
  installed service is the read-only ``/status`` armed check (a).

WHY THE REAL KPI IS NEVER POLLUTED:

  ``/status.historical_lookup_funnel.events_recorded`` is an UNSCOPED global
  ``COUNT(*)`` over the whole reuse-event table on whatever DB the server is
  bound to (see ``app/main.py``). Every write this smoke performs lands in a
  ``VACUUM INTO`` snapshot copy served by the scratch server on a scratch
  port — never the real DB, never the installed service. The installed
  service is only ever READ (``GET /status``). ``VACUUM INTO`` produces a
  coherent single-file snapshot regardless of the live server's ``-wal`` /
  ``-shm`` sidecars and never takes a write lock that would block the live
  writer — so a plain (tearable) file copy is deliberately avoided.

USAGE (post-deploy / post-restart):

    python scripts/live_funnel_smoke.py \\
        --container-ref "<a container that has data in the live DB>" \\
        --query-text "<text likely to match prior turns in that container>"

  The default ``--live-db`` is discovered from the standard install location
  (``$PALLIUM_HOME/data/pallium.db`` or ``~/.pallium/data/pallium.db``). Point
  ``--container-ref`` at a container that actually has ingested source turns,
  otherwise the search returns no hits and the expand half of the chain
  cannot run. Use ``--skip-real-status`` when the installed service is not
  running (the copy-driven chain check still runs).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Ensure the repo root is importable when run as a bare script.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


DEFAULT_REAL_URL = "http://127.0.0.1:19836"
DEFAULT_SCRATCH_PORT = 19940
DEFAULT_CONTAINER = "chat:live-funnel-smoke-scratch"
DEFAULT_QUERY_TEXT = "reservation ordering duplicate holds"


# ---------------------------------------------------------------------------
# Result accounting
# ---------------------------------------------------------------------------


@dataclass
class SmokeResult:
    checks: list[tuple[str, bool, str]] = field(default_factory=list)

    def record(self, name: str, passed: bool, detail: str = "") -> bool:
        self.checks.append((name, passed, detail))
        return passed

    @property
    def passed(self) -> bool:
        return all(ok for _, ok, _ in self.checks)

    def print_summary(self) -> None:
        print("\n" + "=" * 68)
        print("LIVE FUNNEL SMOKE — SUMMARY")
        print("=" * 68)
        for name, ok, detail in self.checks:
            marker = "PASS" if ok else "FAIL"
            line = f"  [{marker}] {name}"
            if detail:
                line += f" — {detail}"
            print(line)
        print("-" * 68)
        print(f"  OVERALL: {'PASS' if self.passed else 'FAIL'}")
        print("=" * 68)


# ---------------------------------------------------------------------------
# Live DB discovery + WAL-safe snapshot
# ---------------------------------------------------------------------------


def resolve_default_live_db() -> Path:
    """Discover the installed service's SQLite DB path.

    Mirrors ``app/cli/service._apply_home_env``: the installed service binds
    ``$PALLIUM_HOME/data/pallium.db`` (default home ``~/.pallium``).
    """
    override = os.environ.get("PALLIUM_SQLITE_URL")
    if override and override.startswith("sqlite:///"):
        return Path(override[len("sqlite:///"):])
    home_env = os.environ.get("PALLIUM_HOME")
    home = Path(home_env).expanduser() if home_env else Path.home() / ".pallium"
    return home / "data" / "pallium.db"


def snapshot_db_wal_safe(live_db: Path, scratch_db: Path) -> None:
    """Snapshot the live DB into ``scratch_db`` via ``VACUUM INTO``.

    ``VACUUM INTO`` yields a coherent single-file copy regardless of any
    ``-wal`` / ``-shm`` sidecars the live server holds, and only takes a
    read lock — it never blocks the live writer. The target must not already
    exist. ``scratch_db`` is generated internally by this harness (never
    caller-supplied SQL), so the path is safe to interpolate; single quotes
    are doubled defensively regardless.
    """
    if scratch_db.exists():
        scratch_db.unlink()
    # SQLite string-literal escaping: double any single quotes.
    target_literal = str(scratch_db).replace("'", "''")
    src = sqlite3.connect(str(live_db), timeout=10)
    try:
        src.execute(f"VACUUM INTO '{target_literal}'")
    finally:
        src.close()
    if not scratch_db.exists() or scratch_db.stat().st_size == 0:
        raise RuntimeError(f"VACUUM INTO produced no snapshot at {scratch_db}")


def cleanup_scratch_files(scratch_db: Path, vector_path: Path) -> None:
    """Delete the scratch DB (+ WAL/SHM sidecars) and vector index path."""
    for suffix in ("", "-wal", "-shm", "-journal", ".schema.lock"):
        p = Path(str(scratch_db) + suffix)
        _unlink_with_retry(p)
    # Vector path can be a file or a directory depending on config; remove both shapes.
    if vector_path.exists():
        try:
            if vector_path.is_dir():
                shutil.rmtree(vector_path, ignore_errors=True)
            else:
                vector_path.unlink()
        except OSError:
            pass
    # usearch sidecar files (index_path + suffixes) if any leaked.
    for suffix in (".meta.json", ".idmap.json"):
        p = Path(str(vector_path) + suffix)
        try:
            p.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _unlink_with_retry(path: Path, retries: int = 10, delay: float = 0.2) -> None:
    """Unlink with retries — Windows holds file handles briefly after engine dispose."""
    for attempt in range(retries):
        try:
            path.unlink()
            return
        except FileNotFoundError:
            return
        except OSError:
            if attempt == retries - 1:
                return
            time.sleep(delay)


def dispose_app_engines(app: Any) -> None:
    """Dispose every SQLAlchemy engine bound to the copy so Windows releases
    the file handle before we unlink it. There are two: the service's storage
    engine and the separate metrics-store engine (built independently in
    ``create_app``)."""
    service = getattr(getattr(app, "state", None), "pallium_service", None)
    storage = getattr(service, "_storage", None)
    engine = getattr(storage, "_engine", None)
    if engine is not None:
        try:
            engine.dispose()
        except Exception:  # noqa: BLE001
            pass
    metrics_store = getattr(getattr(app, "state", None), "metrics_store", None)
    session_factory = getattr(metrics_store, "_session_factory", None)
    if session_factory is not None:
        bind = None
        try:
            bind = session_factory.kw.get("bind")
        except Exception:  # noqa: BLE001
            bind = None
        if bind is None:
            try:
                with session_factory() as s:
                    bind = s.get_bind()
            except Exception:  # noqa: BLE001
                bind = None
        if bind is not None:
            try:
                bind.dispose()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Scratch server (short-lived, bound to the disposable copy)
# ---------------------------------------------------------------------------


def build_scratch_config(copy_db: Path, vector_path: Path):
    """Build a purpose-built AppConfig for the scratch server.

    NEVER derived from the installed config — sqlite_url points at the
    disposable COPY and the vector index is disabled (its own scratch path is
    still set so any stray artifact is easy to clean up). A lazily-constructed
    fake LLM provider satisfies the visibility-enforcing package's build
    requirement; the ``source_only`` search path (see ``core/query.py``)
    bypasses routing/resolution and never calls the LLM, so no real provider
    or secret is needed.
    """
    from app.config import (
        AppConfig,
        LLMProviderConfig,
        ObservabilityConfig,
        SemanticPackageConfig,
    )
    from storage.vector_index import VectorIndexConfig

    return AppConfig(
        storage_backend="sqlite",
        sqlite_url=f"sqlite:///{copy_db}",
        default_use_case="agent_conversation_memory",
        llm_providers={
            "smoke_scratch": LLMProviderConfig(
                name="smoke_scratch",
                kind="openai_compatible",
                base_url="http://scratch.invalid",
                api_key="scratch-not-used",
                timeout_seconds=5.0,
            )
        },
        semantic_packages={
            "agent_conversation_memory": SemanticPackageConfig(
                name="agent_conversation_memory",
                implementation="agent_conversation_memory",
                llm_provider="smoke_scratch",
                model="scratch-model",
                prompt_variant="strict_typed_memory_v6_work_state_examples",
            )
        },
        vector_index=VectorIndexConfig(enabled=False, index_path=str(vector_path)),
        observability=ObservabilityConfig(historical_lookup_funnel=True),
    )


class ScratchServer:
    """Runs a uvicorn server for the scratch app in a background thread.

    uvicorn only installs signal handlers on the main thread, so running
    ``Server.run()`` in a worker thread is safe. Stop via ``should_exit``.
    """

    def __init__(self, app: Any, host: str, port: int) -> None:
        import uvicorn

        self._config = uvicorn.Config(app, host=host, port=port, log_level="warning")
        self._server = uvicorn.Server(self._config)
        self._thread: threading.Thread | None = None
        self.base_url = f"http://{host}:{port}"

    def __enter__(self) -> "ScratchServer":
        self._thread = threading.Thread(target=self._server.run, name="scratch-server", daemon=True)
        self._thread.start()
        self._wait_healthy()
        return self

    def _wait_healthy(self, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        last_err: str = ""
        while time.monotonic() < deadline:
            if getattr(self._server, "should_exit", False):
                raise RuntimeError("scratch server exited during startup")
            try:
                body = http_get_json(f"{self.base_url}/health", timeout=2.0)
                if body.get("status") == "ok":
                    return
                last_err = f"health={body}"
            except Exception as exc:  # noqa: BLE001 - startup polling
                last_err = str(exc)
            time.sleep(0.25)
        raise RuntimeError(f"scratch server did not become healthy in {timeout}s ({last_err})")

    def __exit__(self, *exc: Any) -> None:
        self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=15.0)


# ---------------------------------------------------------------------------
# HTTP helpers (stdlib only)
# ---------------------------------------------------------------------------


def http_get_json(url: str, timeout: float = 10.0) -> dict[str, Any]:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_post_json(url: str, payload: Any, timeout: float = 30.0) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST", headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# Direct (read-only) inspection of the copy
# ---------------------------------------------------------------------------


def count_events_by_type(copy_db: Path) -> dict[str, int]:
    conn = sqlite3.connect(str(copy_db), timeout=10)
    try:
        rows = conn.execute(
            "SELECT event_type, COUNT(*) FROM historical_lookup_reuse_event GROUP BY event_type"
        ).fetchall()
    finally:
        conn.close()
    return {str(et): int(n) for et, n in rows}


def expansion_parents(copy_db: Path) -> list[str | None]:
    conn = sqlite3.connect(str(copy_db), timeout=10)
    try:
        rows = conn.execute(
            "SELECT parent_lookup_id FROM historical_lookup_reuse_event WHERE event_type = 'expansion'"
        ).fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Core smoke
# ---------------------------------------------------------------------------


def run_smoke(
    *,
    live_db: Path,
    scratch_port: int,
    real_url: str,
    container_ref: str,
    thread_ref: str,
    visibility: str,
    query_text: str,
    skip_real_status: bool,
    scratch_host: str = "127.0.0.1",
) -> SmokeResult:
    result = SmokeResult()

    # Guard: never let the scratch server collide with the real service port.
    real_port = urllib.parse.urlparse(real_url).port
    if real_port is not None and scratch_port == real_port:
        raise ValueError(
            f"scratch_port ({scratch_port}) must differ from the real service port ({real_port})"
        )

    if not live_db.exists():
        result.record("live-db-exists", False, f"no DB at {live_db}")
        return result
    result.record("live-db-exists", True, str(live_db))

    # Scratch artifacts live next to a unique temp name so parallel runs never clash.
    tag = uuid.uuid4().hex[:8]
    scratch_db = live_db.parent / f"pallium-smoke-{tag}.db"
    vector_path = live_db.parent / f"pallium-smoke-{tag}.vector.index"
    app: Any = None

    # (a) READ-ONLY armed check against the real installed service.
    if skip_real_status:
        result.record("real-status-armed", True, "skipped (--skip-real-status)")
    else:
        try:
            status = http_get_json(f"{real_url}/status", timeout=10.0)
            funnel = status.get("historical_lookup_funnel") or {}
            armed = bool(funnel.get("armed"))
            result.record(
                "real-status-armed",
                armed,
                f"{real_url} armed={armed}, events_recorded={funnel.get('events_recorded')} (READ-ONLY)",
            )
        except Exception as exc:  # noqa: BLE001
            result.record("real-status-armed", False, f"GET {real_url}/status failed: {exc}")

    try:
        # WAL-safe snapshot into the disposable copy.
        snapshot_db_wal_safe(live_db, scratch_db)
        result.record("snapshot-vacuum-into", True, f"copy at {scratch_db.name}")

        app_config = build_scratch_config(scratch_db, vector_path)
        from app.main import create_app

        app = create_app(app_config)

        with ScratchServer(app, scratch_host, scratch_port) as server:
            base = server.base_url

            # Baseline unscoped global count on the COPY (never the real DB).
            status0 = http_get_json(f"{base}/status")
            events0 = (status0.get("historical_lookup_funnel") or {}).get("events_recorded") or 0

            # search_history: source_only + agent_pull (what pallium_search_history sends).
            search = http_post_json(
                f"{base}/query",
                {
                    "text": query_text,
                    "container_ref": container_ref,
                    "thread_ref": thread_ref,
                    "visibility": visibility,
                    "limit": 5,
                    "source_only": True,
                    "trigger_origin": "agent_pull",
                },
            )
            lookup_id = search.get("lookup_event_id")
            source_hits = [
                r for r in search.get("results", []) if r.get("result_kind") == "source_hit"
            ]
            result.record(
                "search-lookup-persisted",
                bool(lookup_id),
                f"lookup_event_id={lookup_id}, source_hits={len(source_hits)}",
            )

            expanded = False
            if lookup_id and source_hits:
                anchor_id = source_hits[0]["source_item_id"]
                # expand_source: GET /source/{id}/context with parent_lookup_id.
                params = urllib.parse.urlencode(
                    {"container_ref": container_ref, "parent_lookup_id": lookup_id}
                )
                ctx = http_get_json(f"{base}/source/{anchor_id}/context?{params}")
                expanded = ctx.get("parent_lookup_id") == lookup_id
                result.record(
                    "expand-source-context",
                    expanded,
                    f"anchor={anchor_id}, echoed_parent={ctx.get('parent_lookup_id')}",
                )
            else:
                result.record(
                    "expand-source-context",
                    False,
                    "no source hits to expand — point --container-ref/--query-text at populated data",
                )

            # events_recorded incremented ON THE COPY (via scratch /status).
            status1 = http_get_json(f"{base}/status")
            events1 = (status1.get("historical_lookup_funnel") or {}).get("events_recorded") or 0
            delta = events1 - events0
            expected = 2 if expanded else 1
            result.record(
                "events-recorded-incremented",
                delta >= expected,
                f"copy events_recorded {events0} -> {events1} (delta={delta}, expected>={expected})",
            )

        # Direct read-only assertion on the copy: a lookup and (when expanded)
        # a chained expansion row persisted.
        by_type = count_events_by_type(scratch_db)
        result.record(
            "copy-has-lookup-row",
            by_type.get("lookup", 0) >= 1,
            f"event_type counts={by_type}",
        )
        if expanded:
            parents = expansion_parents(scratch_db)
            linked = lookup_id in parents
            result.record(
                "copy-expansion-links-lookup",
                linked,
                f"expansion parent_lookup_ids={parents}",
            )
    finally:
        if app is not None:
            dispose_app_engines(app)
        cleanup_scratch_files(scratch_db, vector_path)
        # Confirm the copy is gone — the disposable snapshot must not linger.
        result.record(
            "scratch-cleanup",
            not scratch_db.exists(),
            f"removed {scratch_db.name}" if not scratch_db.exists() else f"LEFTOVER {scratch_db}",
        )

    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Live-service smoke for the historical-lookup reuse funnel "
        "(drives a search->expand->persist chain against a disposable VACUUM INTO "
        "copy on a scratch server; only ever READS the installed service).",
    )
    parser.add_argument(
        "--live-db",
        type=str,
        default=None,
        help="Path to the live SQLite DB to snapshot (default: discover from "
        "$PALLIUM_SQLITE_URL / $PALLIUM_HOME / ~/.pallium/data/pallium.db). "
        "Snapshot only — never written.",
    )
    parser.add_argument("--scratch-port", type=int, default=DEFAULT_SCRATCH_PORT,
                        help=f"Port for the short-lived scratch server (default {DEFAULT_SCRATCH_PORT}; must NOT be the real service port).")
    parser.add_argument("--real-url", type=str, default=DEFAULT_REAL_URL,
                        help=f"Installed service base URL for the READ-ONLY armed check (default {DEFAULT_REAL_URL}).")
    parser.add_argument("--container-ref", type=str, default=DEFAULT_CONTAINER,
                        help="Container to search within on the copy. Point this at a container that HAS data for a full chain.")
    parser.add_argument("--thread-ref", type=str, default=None,
                        help="Thread/session ref used for the reuse-event session_id (default: a scratch-tagged value).")
    parser.add_argument("--visibility", type=str, default="private", help="Query visibility (default private).")
    parser.add_argument("--query-text", type=str, default=DEFAULT_QUERY_TEXT,
                        help="Search text for the source_only query.")
    parser.add_argument("--skip-real-status", action="store_true",
                        help="Skip the read-only armed check against the installed service (use when it is not running).")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    live_db = Path(args.live_db).expanduser() if args.live_db else resolve_default_live_db()
    thread_ref = args.thread_ref or f"{args.container_ref}:smoke-{uuid.uuid4().hex[:6]}"

    print(__doc__.split("USAGE")[0].strip())
    print(f"\nlive DB (snapshot source, never written): {live_db}")
    print(f"scratch server: http://127.0.0.1:{args.scratch_port}  (disposable copy)")
    print(f"real service (READ-ONLY /status): {args.real_url}"
          f"{'  [SKIPPED]' if args.skip_real_status else ''}")

    result = run_smoke(
        live_db=live_db,
        scratch_port=args.scratch_port,
        real_url=args.real_url,
        container_ref=args.container_ref,
        thread_ref=thread_ref,
        visibility=args.visibility,
        query_text=args.query_text,
        skip_real_status=args.skip_real_status,
    )
    result.print_summary()
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
