"""vNext performance + DB round-trip measurement harness (MEASURE-ONLY).

This module measures the vNext historical-lookup hot paths WITHOUT editing any
product code. All timing and query counting is external, via two seams:

1. A SQLAlchemy ``after_cursor_execute`` listener attached to the storage
   engine (``service._storage._engine``). This counts DB round-trips for the
   REQUEST-PATH hot paths:
     - source_only query via ``POST /query``
     - source-context expansion via ``GET /source/{id}/context``
     - the ``matches_filters`` gate + the double ``get_source_item`` per
       candidate (exercised through a source_only query)
     - the reuse-funnel "lookup" event write

2. ``sqlite3.Connection.set_trace_callback`` (installed by monkeypatching
   ``sqlite3.connect`` in this process) to count the MEASUREMENT LOADER's raw
   ``sqlite3`` queries. The loader
   (``evals.historical_lookup_measurement.load_events_from_storage`` /
   ``load_visibility_violations``) opens its OWN ``sqlite3.connect``, which the
   SQLAlchemy listener never sees. This second seam is what surfaces the
   per-exposed-id N+1.

Deterministic backbone vs advisory:
- Query/round-trip COUNTS are the deterministic, committed, gated signal.
- Latency (median/p95) is ADVISORY only, never a committed threshold.

Run:
    python -m evals.vnext_perf_harness              # measure + compare vs baseline
    python -m evals.vnext_perf_harness --baseline   # regenerate committed baseline
    python -m evals.vnext_perf_harness --vector      # also exercise vector path (slow)

The committed count baseline lives at ``evals/vnext_perf_baseline.json``.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import sqlite3
import statistics
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

from sqlalchemy import event

# NOTE: guarded product modules are imported READ-ONLY (never edited).
from app.config import AppConfig
from app.main import create_app
from core.models import IndexEntry, SourceItem
from evals import historical_lookup_measurement as hlm
from storage.vector_index import VectorIndexConfig
from tests.config_helpers import DEMO_SEMANTIC_PACKAGES

BASELINE_PATH = Path(__file__).with_name("vnext_perf_baseline.json")
BASELINE_SCHEMA_VERSION = 1

# Shared lexical token every seeded turn carries, so a source_only query can
# return a full candidate window regardless of thread.
_COMMON_TOKEN = "sessionlog"


# ---------------------------------------------------------------------------
# Seam 1: SQLAlchemy engine query counter
# ---------------------------------------------------------------------------


@dataclass
class EngineCounter:
    count: int = 0
    statements: list[str] = field(default_factory=list)

    def reset(self) -> None:
        self.count = 0
        self.statements.clear()


@contextlib.contextmanager
def count_engine_queries(engine, *, capture: bool = False) -> Iterator[EngineCounter]:
    """Count every cursor execute on ``engine`` within the block."""
    counter = EngineCounter()

    def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        counter.count += 1
        if capture:
            counter.statements.append(statement)

    event.listen(engine, "after_cursor_execute", _after_cursor_execute)
    try:
        yield counter
    finally:
        event.remove(engine, "after_cursor_execute", _after_cursor_execute)


# ---------------------------------------------------------------------------
# Seam 2: raw sqlite3 loader query counter (set_trace_callback)
# ---------------------------------------------------------------------------


@dataclass
class LoaderCounter:
    count: int = 0
    statements: list[str] = field(default_factory=list)


@contextlib.contextmanager
def count_loader_queries(*, capture: bool = False) -> Iterator[LoaderCounter]:
    """Count every SQL statement on connections opened via ``sqlite3.connect``.

    The measurement loader opens its own raw ``sqlite3.connect`` -- the
    SQLAlchemy listener is blind to it. We monkeypatch ``sqlite3.connect`` for
    the duration of the block and install a trace callback on each returned
    connection. Only active for the brief window around a loader call, so no
    SQLAlchemy pool connection is affected.
    """
    counter = LoaderCounter()
    real_connect = sqlite3.connect

    def _traced_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)

        def _trace(sql: str) -> None:
            counter.count += 1
            if capture:
                counter.statements.append(sql)

        conn.set_trace_callback(_trace)
        return conn

    sqlite3.connect = _traced_connect  # type: ignore[assignment]
    try:
        yield counter
    finally:
        sqlite3.connect = real_connect  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# App / seeding
# ---------------------------------------------------------------------------


def build_app_config(db_path: Path, *, vector: bool = False, vector_dir: Path | None = None) -> AppConfig:
    """Purpose-built config: demo package, vector off by default.

    Uses the demo semantic package (no LLM / no visibility context required),
    exactly like the shared test client, so a source_only lexical query returns
    candidates without any network or model dependency.
    """
    if vector:
        assert vector_dir is not None
        vector_cfg = VectorIndexConfig(enabled=True, index_path=str(vector_dir))
    else:
        vector_cfg = VectorIndexConfig(enabled=False)
    return AppConfig(
        storage_backend="sqlite",
        sqlite_url=f"sqlite:///{db_path}",
        default_use_case="demo_agent_memory",
        semantic_packages=DEMO_SEMANTIC_PACKAGES,
        vector_index=vector_cfg,
    )


def seed_source_items(
    service,
    *,
    containers: int = 2,
    threads_per_container: int = 3,
    turns_per_thread: int = 150,
) -> dict[str, Any]:
    """Seed a realistically-sized corpus of source_items + lexical index entries.

    Each turn carries a shared token so a source_only query returns a full
    candidate window. Returns a small descriptor (counts + a mid-thread anchor
    id for the expansion path).
    """
    storage = service._storage
    total = 0
    anchor_id: str | None = None
    for c in range(containers):
        container_ref = f"container-{c}"
        for t in range(threads_per_container):
            thread_ref = f"thread-{c}-{t}"
            for i in range(turns_per_thread):
                role = "user" if i % 2 == 0 else "assistant"
                item = SourceItem(
                    source_type="conversation",
                    source_id=f"{thread_ref}-turn-{i:04d}",
                    content_type="text/plain",
                    content=f"{_COMMON_TOKEN} turn {i} in {thread_ref}: discussing topic alpha bravo charlie",
                    role=role,
                    container_ref=container_ref,
                    thread_ref=thread_ref,
                    visibility="private",
                    use_case="demo_agent_memory",
                )
                storage.create_source_item(item)
                storage.create_index_entry(
                    IndexEntry(
                        target_kind="source_item",
                        target_id=item.id,
                        index_type="lexical",
                        text_view=item.content,
                    )
                )
                total += 1
                # Grab a mid-thread anchor from the first thread.
                if c == 0 and t == 0 and i == turns_per_thread // 2:
                    anchor_id = item.id
    return {
        "source_items": total,
        "containers": containers,
        "threads_per_container": threads_per_container,
        "turns_per_thread": turns_per_thread,
        "anchor_id": anchor_id,
    }


def seed_reuse_events(
    service,
    *,
    events: int,
    exposed_per_event: int,
    container_ref: str = "container-0",
) -> dict[str, int]:
    """Seed historical_lookup_reuse_event rows with exposed sets referencing
    real seeded source_items, so the loader's per-exposed-id scan has work to
    do. Returns {events, exposed_ids}.
    """
    from core.models import new_id, utc_now  # read-only helpers

    storage = service._storage
    # Collect some real source_item ids to reference in exposed sets.
    real_ids = _sample_source_item_ids(service, exposed_per_event, container_ref)
    exposed_total = 0
    for _ in range(events):
        exposed = [
            {"source_item_id": sid, "raw_rank": rank + 1, "score": 1.0}
            for rank, sid in enumerate(real_ids[:exposed_per_event])
        ]
        exposed_total += len(exposed)
        storage.write_historical_lookup_event_row(
            {
                "id": new_id(),
                "created_at": utc_now(),
                "event_type": "lookup",
                "session_id": "thread-0-0",
                "container_ref": container_ref,
                "actor_ref": None,
                "trigger_origin": "agent_pull",
                "parent_lookup_id": None,
                "exposed_json": json.dumps(exposed),
                "visibility": "private",
            }
        )
    return {"events": events, "exposed_ids": exposed_total}


def _sample_source_item_ids(service, n: int, container_ref: str) -> list[str]:
    """Read a handful of real source_item ids straight from the DB file."""
    db_path = _engine_db_path(service._storage._engine)
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT id FROM source_items WHERE container_ref = ? LIMIT ?",
            (container_ref, max(n, 1)),
        ).fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]


def _engine_db_path(engine) -> Path:
    """Extract the on-disk sqlite file path from a SQLAlchemy engine URL."""
    database = engine.url.database
    return Path(database)


# ---------------------------------------------------------------------------
# Measurements
# ---------------------------------------------------------------------------


def _query_payload(text: str, limit: int) -> dict[str, Any]:
    return {"text": text, "limit": limit, "source_only": True, "trigger_origin": "agent_pull"}


def measure_source_only(client, engine, *, text: str, limit: int) -> dict[str, Any]:
    """Count engine queries for one source_only POST /query and report the
    number of source_hit candidates returned."""
    with count_engine_queries(engine) as counter:
        resp = client.post("/query", json=_query_payload(text, limit))
    resp.raise_for_status()
    body = resp.json()
    return {
        "engine_queries": counter.count,
        "results": len(body.get("results", [])),
        "lookup_event_id": body.get("lookup_event_id"),
    }


def measure_source_context(client, engine, source_item_id: str, *, before: int, after: int) -> dict[str, Any]:
    with count_engine_queries(engine) as counter:
        resp = client.get(
            f"/source/{source_item_id}/context",
            params={"before": before, "after": after},
        )
    resp.raise_for_status()
    body = resp.json()
    return {
        "engine_queries": counter.count,
        "items": len(body.get("items", [])),
        "before": before,
        "after": after,
    }


def measure_loader(db_path: Path, *, container_ref: str) -> dict[str, Any]:
    """Count the raw-sqlite3 loader queries via seam 2, for both loader
    functions. Proves the seam reports NON-ZERO."""
    with count_loader_queries() as ev_counter:
        eligible, events = hlm.load_events_from_storage(db_path, container_ref=container_ref, eligibility_n=1)
    with count_loader_queries() as vio_counter:
        report = hlm.load_visibility_violations(db_path, container_ref=container_ref)
    return {
        "load_events_loader_queries": ev_counter.count,
        "load_events_eligible": len(eligible),
        "load_events_events": len(events),
        "visibility_loader_queries": vio_counter.count,
        "visibility_events_checked": report.get("events_checked", 0),
        "visibility_exposed_ids_checked": report.get("exposed_ids_checked", 0),
    }


def measure_latency(fn: Callable[[], Any], *, reps: int) -> dict[str, float]:
    """Advisory latency only. Median / p95 over reps in milliseconds."""
    samples: list[float] = []
    for _ in range(reps):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000.0)
    samples_sorted = sorted(samples)
    p95_idx = min(len(samples_sorted) - 1, math.ceil(0.95 * len(samples_sorted)) - 1)
    return {
        "median_ms": round(statistics.median(samples), 3),
        "p95_ms": round(samples_sorted[p95_idx], 3),
        "reps": reps,
    }


# ---------------------------------------------------------------------------
# DB index check
# ---------------------------------------------------------------------------


def _explain(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[str]:
    rows = conn.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
    return [str(r[-1]) for r in rows]


def _index_used(detail_lines: list[str]) -> str | None:
    for line in detail_lines:
        if "USING INDEX" in line or "USING COVERING INDEX" in line:
            # e.g. "SEARCH source_items USING INDEX idx_... (container_ref=?)"
            idx = line.split("USING", 1)[1].strip()
            idx = idx.replace("COVERING INDEX", "").replace("INDEX", "").strip()
            return idx.split(" ")[0]
    return None


def check_indexes(db_path: Path) -> list[dict[str, Any]]:
    """EXPLAIN QUERY PLAN the hot-path queries; report index usage / scans."""
    conn = sqlite3.connect(str(db_path))
    try:
        checks: list[dict[str, Any]] = []

        neighbor_before = (
            "SELECT id FROM source_items WHERE container_ref = ? AND thread_ref = ? "
            "AND (created_at < ? OR (created_at = ? AND id < ?)) "
            "ORDER BY created_at DESC, id DESC LIMIT 10"
        )
        detail = _explain(conn, neighbor_before, ("container-0", "thread-0-0", "2020-01-01", "2020-01-01", "z"))
        checks.append(
            {
                "path": "neighbor_window_before (list_source_item_neighbors)",
                "expected_index": "idx_source_items_thread_lookup",
                "index_used": _index_used(detail),
                "full_scan": any("SCAN" in line and "USING" not in line for line in detail),
                "plan": detail,
            }
        )

        loader_vio = "SELECT container_ref, forgotten_at FROM source_items WHERE id = ?"
        detail = _explain(conn, loader_vio, ("x",))
        checks.append(
            {
                "path": "loader per-exposed-id lookup (historical_lookup_measurement:586-589)",
                "expected_index": "PRIMARY KEY (source_items.id)",
                "index_used": _index_used(detail) or ("PRIMARY KEY" if any("PRIMARY KEY" in x or "sqlite_autoindex" in x or "USING INTEGER PRIMARY KEY" in x for x in detail) else None),
                "full_scan": any("SCAN" in line and "USING" not in line and "PRIMARY KEY" not in line for line in detail),
                "plan": detail,
            }
        )

        loader_events = "SELECT id, session_id FROM historical_lookup_reuse_event WHERE event_type = 'lookup'"
        detail = _explain(conn, loader_events)
        checks.append(
            {
                "path": "loader reuse-event scan (_load_reuse_events)",
                "expected_index": "idx_historical_lookup_event_container_session (partial -- event_type not indexed)",
                "index_used": _index_used(detail),
                "full_scan": any("SCAN" in line and "USING" not in line for line in detail),
                "plan": detail,
            }
        )

        consensus = (
            "SELECT rater_seed, rung, created_at FROM historical_lookup_reuse_label "
            "WHERE lookup_event_id = ? ORDER BY created_at, id"
        )
        detail = _explain(conn, consensus, ("x",))
        checks.append(
            {
                "path": "loader consensus-rung lookup (_consensus_rung)",
                "expected_index": "idx_historical_lookup_label_event",
                "index_used": _index_used(detail),
                "full_scan": any("SCAN" in line and "USING" not in line for line in detail),
                "plan": detail,
            }
        )
        return checks
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_measurements(*, vector: bool = False, small: bool = False) -> dict[str, Any]:
    """Seed a temp DB, run all measurements, return a structured report."""
    tmp = Path(tempfile.mkdtemp(prefix="vnext_perf_"))
    db_path = tmp / "perf.db"
    vector_dir = tmp / "vector"
    config = build_app_config(db_path, vector=vector, vector_dir=vector_dir)
    app = create_app(config)

    from fastapi.testclient import TestClient

    report: dict[str, Any] = {"schema_version": BASELINE_SCHEMA_VERSION}
    with TestClient(app) as client:
        service = client.app.state.pallium_service
        engine = service._storage._engine

        if small:
            seed_meta = seed_source_items(service, containers=1, threads_per_container=1, turns_per_thread=30)
        else:
            seed_meta = seed_source_items(service)
        report["seed"] = seed_meta
        anchor_id = seed_meta["anchor_id"]

        # Warm up: establish the connection pool + run connect-time PRAGMAs so
        # per-op engine counts are stable (not polluted by first-connect setup).
        client.post("/query", json=_query_payload(_COMMON_TOKEN, 5))

        # ---- Request-path counts (seam 1) ----
        counts: dict[str, Any] = {}
        counts["source_only_query"] = measure_source_only(client, engine, text=_COMMON_TOKEN, limit=5)
        counts["source_only_query_no_match"] = measure_source_only(
            client, engine, text="tokenthatmatchesnothingxyzzy", limit=5
        )
        counts["source_context_expansion"] = measure_source_context(
            client, engine, anchor_id, before=10, after=10
        )
        report["counts"] = counts

        # ---- N+1 #1: double get_source_item per candidate (seam 1) ----
        # retrieval_limit = min(max(limit*4, 12), 50); each FTS candidate incurs
        # TWO get_source_item calls (matches_filters + target_visibility). Show
        # engine queries scale ~linearly with the candidate window.
        n1_double_get: list[dict[str, Any]] = []
        for limit in ([2, 5] if small else [2, 5, 10, 12]):
            m = measure_source_only(client, engine, text=_COMMON_TOKEN, limit=limit)
            retrieval_limit = min(max(limit * 4, 12), 50)
            n1_double_get.append(
                {
                    "limit": limit,
                    "retrieval_limit": retrieval_limit,
                    "candidates": m["results"],
                    "engine_queries": m["engine_queries"],
                }
            )
        report["n1_double_get_source_item"] = n1_double_get

        # ---- N+1 #2: loader per-exposed-id scan (seam 2) ----
        # Seed reuse events with exposed sets and show loader queries scale with
        # the number of exposed ids across events.
        n1_loader: list[dict[str, Any]] = []
        exposed_per_event = 3 if small else 5
        for n_events in ([2, 4] if small else [10, 20, 40]):
            # Fresh events each step so the exposed-id total grows monotonically.
            seed_reuse_events(service, events=n_events, exposed_per_event=exposed_per_event)
            loader_m = measure_loader(db_path, container_ref="container-0")
            n1_loader.append(
                {
                    "cumulative_events": loader_m["visibility_events_checked"],
                    "exposed_ids_checked": loader_m["visibility_exposed_ids_checked"],
                    "visibility_loader_queries": loader_m["visibility_loader_queries"],
                    "load_events_loader_queries": loader_m["load_events_loader_queries"],
                }
            )
        report["n1_loader_per_exposed_id"] = n1_loader
        # Final loader snapshot (proves seam reports NON-ZERO).
        report["loader"] = measure_loader(db_path, container_ref="container-0")

        # ---- DB index check ----
        report["index_check"] = check_indexes(db_path)

        # ---- Advisory latency (NOT gated) ----
        report["latency_advisory"] = {
            "source_only_query": measure_latency(
                lambda: client.post("/query", json=_query_payload(_COMMON_TOKEN, 5)),
                reps=3 if small else 25,
            ),
            "source_context_expansion": measure_latency(
                lambda: client.get(f"/source/{anchor_id}/context", params={"before": 10, "after": 10}),
                reps=3 if small else 25,
            ),
        }

        # ---- Optional vector-enabled path (opt-in, slow) ----
        if vector:
            report["vector"] = _measure_vector_path(client, engine)

    return report


def _measure_vector_path(client, engine) -> dict[str, Any]:
    """Best-effort vector path exercise. ONNX embeddings may be unavailable
    offline; skip gracefully rather than crash. Exercises the second
    materializing fetch at retrieval/vector.py:209 when it does run."""
    try:
        with count_engine_queries(engine) as counter:
            resp = client.post("/query", json={"text": _COMMON_TOKEN, "limit": 5, "source_only": True})
        resp.raise_for_status()
        return {
            "status": "ran",
            "engine_queries": counter.count,
            "results": len(resp.json().get("results", [])),
            "note": "vector-enabled config; second fetch at retrieval/vector.py:209 exercised when a vector hit hydrates",
        }
    except Exception as exc:  # pragma: no cover - environment dependent
        return {"status": "skipped", "reason": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Baseline (committed, gated) + compare
# ---------------------------------------------------------------------------


def build_count_baseline(report: dict[str, Any]) -> dict[str, Any]:
    """Extract only the DETERMINISTIC, gated count signal (no latency)."""
    return {
        "schema_version": BASELINE_SCHEMA_VERSION,
        # anchor_id is a per-run random UUID; exclude it so the committed
        # baseline is stable across regenerations.
        "seed": {k: v for k, v in report["seed"].items() if k != "anchor_id"},
        "counts": {
            k: {"engine_queries": v["engine_queries"]} for k, v in report["counts"].items()
        },
        "n1_double_get_source_item": [
            {"limit": e["limit"], "candidates": e["candidates"], "engine_queries": e["engine_queries"]}
            for e in report["n1_double_get_source_item"]
        ],
        "n1_loader_per_exposed_id": [
            {
                "cumulative_events": e["cumulative_events"],
                "exposed_ids_checked": e["exposed_ids_checked"],
                "visibility_loader_queries": e["visibility_loader_queries"],
                "load_events_loader_queries": e["load_events_loader_queries"],
            }
            for e in report["n1_loader_per_exposed_id"]
        ],
        "loader": {
            "load_events_loader_queries": report["loader"]["load_events_loader_queries"],
            "visibility_loader_queries": report["loader"]["visibility_loader_queries"],
        },
    }


def _regressed(baseline_val: int, measured_val: int) -> bool:
    """A count regresses if it grew beyond a small tolerance. Lower is fine.

    Counts are deterministic; the tolerance only absorbs incidental
    engine-setup drift across environments.
    """
    tolerance = max(2, math.ceil(baseline_val * 0.10))
    return measured_val > baseline_val + tolerance


def compare_to_baseline(report: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    """Return a list of regression messages (empty = pass)."""
    problems: list[str] = []
    fresh = build_count_baseline(report)

    for key, base in baseline.get("counts", {}).items():
        cur = fresh["counts"].get(key)
        if cur is None:
            continue
        if _regressed(base["engine_queries"], cur["engine_queries"]):
            problems.append(
                f"counts.{key}.engine_queries: baseline={base['engine_queries']} measured={cur['engine_queries']}"
            )

    base_map = {e["limit"]: e for e in baseline.get("n1_double_get_source_item", [])}
    for e in fresh["n1_double_get_source_item"]:
        b = base_map.get(e["limit"])
        if b and _regressed(b["engine_queries"], e["engine_queries"]):
            problems.append(
                f"n1_double_get_source_item[limit={e['limit']}].engine_queries: "
                f"baseline={b['engine_queries']} measured={e['engine_queries']}"
            )

    base_loader = {b["cumulative_events"]: b for b in baseline.get("n1_loader_per_exposed_id", [])}
    for e in fresh["n1_loader_per_exposed_id"]:
        b = base_loader.get(e["cumulative_events"])
        if b and _regressed(b["visibility_loader_queries"], e["visibility_loader_queries"]):
            problems.append(
                f"n1_loader_per_exposed_id[events={e['cumulative_events']}].visibility_loader_queries: "
                f"baseline={b['visibility_loader_queries']} measured={e['visibility_loader_queries']}"
            )

    return problems


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _slope(points: list[tuple[int, int]]) -> float | None:
    """Least-squares slope of y vs x (queries per unit). None if degenerate."""
    if len(points) < 2:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    n = len(points)
    mx = sum(xs) / n
    my = sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom


def print_report(report: dict[str, Any]) -> None:
    p = print
    p("=" * 78)
    p("vNext perf + DB round-trip report (MEASURE-ONLY; no product code touched)")
    p("=" * 78)
    seed = report["seed"]
    p(f"Seed: {seed['source_items']} source_items across "
      f"{seed['containers']} containers x {seed['threads_per_container']} threads "
      f"({seed['turns_per_thread']} turns/thread)")
    p("")

    p("-- Per-path DB round-trip counts (deterministic backbone) --")
    for key, v in report["counts"].items():
        extra = ""
        if "results" in v:
            extra = f"  (source_hit candidates={v['results']})"
        elif "items" in v:
            extra = f"  (context items={v['items']}, before={v['before']}, after={v['after']})"
        p(f"  {key:<32} engine_queries={v['engine_queries']}{extra}")
    p("")

    p("-- N+1 #1: repeated get_source_item per candidate (gate double-fetch + hydration) --")
    p("   sites: sqlite_search.py:84 (matches_filters) + :101 (target_visibility) + lexical.py:154 (hydration);")
    p("   FTS window = retrieval_limit*4 (lexical.py:113), so DB round-trips scale with the candidate window.")
    pts = []
    for e in report["n1_double_get_source_item"]:
        p(f"  limit={e['limit']:<3} retrieval_limit={e['retrieval_limit']:<3} "
          f"returned={e['candidates']:<3} engine_queries={e['engine_queries']}")
        pts.append((e["retrieval_limit"], e["engine_queries"]))
    slope = _slope(pts)
    if slope is not None:
        p(f"  -> engine_queries grow ~{slope:.2f} per retrieval_limit slot "
          f"(linear O(candidates), NOT O(1) -- the per-candidate get_source_item N+1)")
    p("")

    p("-- N+1 #2: loader per-exposed-id scan (evals/historical_lookup_measurement.py:586-589, raw sqlite3 -- seam 2) --")
    pts = []
    for e in report["n1_loader_per_exposed_id"]:
        p(f"  cumulative_events={e['cumulative_events']:<4} exposed_ids_checked={e['exposed_ids_checked']:<5} "
          f"visibility_loader_queries={e['visibility_loader_queries']:<5} "
          f"load_events_loader_queries={e['load_events_loader_queries']}")
        pts.append((e["exposed_ids_checked"], e["visibility_loader_queries"]))
    slope = _slope(pts)
    if slope is not None:
        p(f"  -> visibility_loader_queries grow ~{slope:.2f} per exposed id "
          f"(linear O(exposed ids) -- the per-exposed-id N+1)")
    ldr = report["loader"]
    p(f"  loader seam NON-ZERO check: load_events_loader_queries={ldr['load_events_loader_queries']}, "
      f"visibility_loader_queries={ldr['visibility_loader_queries']}")
    p("")

    p("-- DB index check (EXPLAIN QUERY PLAN) --")
    for c in report["index_check"]:
        flag = "  [FULL SCAN]" if c["full_scan"] else ""
        p(f"  {c['path']}")
        p(f"      expected: {c['expected_index']}")
        p(f"      used:     {c['index_used']}{flag}")
        p(f"      plan:     {c['plan']}")
    p("")

    p("-- Advisory latency (informational only; NEVER gated) --")
    for key, v in report.get("latency_advisory", {}).items():
        p(f"  {key:<32} median={v['median_ms']}ms  p95={v['p95_ms']}ms  (reps={v['reps']})")
    if "vector" in report:
        p("")
        p(f"-- Vector path: {report['vector']}")
    p("=" * 78)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="vNext perf + DB round-trip harness (measure-only).")
    parser.add_argument("--baseline", action="store_true", help="Regenerate the committed count baseline.")
    parser.add_argument("--vector", action="store_true", help="Also exercise the vector-enabled path (slow).")
    parser.add_argument("--small", action="store_true", help="Tiny/fast mode (for the guard test).")
    parser.add_argument("--json", action="store_true", help="Print the full report as JSON.")
    args = parser.parse_args(argv)

    report = run_measurements(vector=args.vector, small=args.small)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print_report(report)

    if args.baseline:
        baseline = build_count_baseline(report)
        BASELINE_PATH.write_text(json.dumps(baseline, indent=2, default=str) + "\n", encoding="utf-8")
        print(f"\nWrote count baseline -> {BASELINE_PATH}")
        return 0

    # Compare mode (default). Small mode never gates (shape differs).
    if args.small:
        return 0
    if not BASELINE_PATH.exists():
        print(f"\nNo baseline at {BASELINE_PATH}; run with --baseline first.", file=sys.stderr)
        return 1
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    problems = compare_to_baseline(report, baseline)
    if problems:
        print("\nCOUNT REGRESSION(S) vs committed baseline:", file=sys.stderr)
        for msg in problems:
            print(f"  - {msg}", file=sys.stderr)
        return 2
    print("\nCounts within tolerance of committed baseline. PASS.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
