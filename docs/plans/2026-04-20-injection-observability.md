# Injection Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add in-memory query/flag counters to Pallium, surfaced via the `/status` endpoint, so operators can see whether injection is working.

**Architecture:** A `QueryStats` class in `core/observability.py` with thread-safe counters. `QueryExecutor` calls `stats.record_query()` after every query. `PalliumService` calls `stats.record_flag()` after every flag. `/status` includes `stats.snapshot()` under a `"query"` key.

**Tech Stack:** Python threading.Lock, datetime, dataclasses. pytest for tests.

---

### Task 1: QueryStats class — basic counting (inject vs skip)

**Files:**
- Create: `tests/test_query_stats.py`
- Modify: `core/observability.py`

- [ ] **Step 1: Write failing tests for basic inject/skip counting**

In `tests/test_query_stats.py`:

```python
from __future__ import annotations

from core.contracts import QueryResult
from core.observability import QueryStats


def _make_result(*, should_inject: bool, decision_reason: str, block_count: int = 0) -> QueryResult:
    blocks = [object() for _ in range(block_count)]
    return QueryResult(
        results=[],
        should_inject=should_inject,
        decision_reason=decision_reason,
        injectable_blocks=blocks,
    )


class TestQueryStatsBasicCounting:
    def test_initial_snapshot_has_zero_counts(self):
        stats = QueryStats()
        snap = stats.snapshot()
        assert snap["total_queries"] == 0
        assert snap["total_injections"] == 0
        assert snap["total_skips"] == 0
        assert snap["total_blocks_injected"] == 0
        assert snap["last_query_at"] is None
        assert isinstance(snap["stats_since"], str)

    def test_injection_increments_correct_counters(self):
        stats = QueryStats()
        stats.record_query(_make_result(should_inject=True, decision_reason="inject", block_count=3))
        snap = stats.snapshot()
        assert snap["total_queries"] == 1
        assert snap["total_injections"] == 1
        assert snap["total_skips"] == 0
        assert snap["total_blocks_injected"] == 3

    def test_skip_increments_correct_counters(self):
        stats = QueryStats()
        stats.record_query(_make_result(should_inject=False, decision_reason="gate_blocked"))
        snap = stats.snapshot()
        assert snap["total_queries"] == 1
        assert snap["total_injections"] == 0
        assert snap["total_skips"] == 1
        assert snap["total_blocks_injected"] == 0

    def test_mixed_queries_accumulate(self):
        stats = QueryStats()
        stats.record_query(_make_result(should_inject=True, decision_reason="inject", block_count=2))
        stats.record_query(_make_result(should_inject=False, decision_reason="gate_blocked"))
        stats.record_query(_make_result(should_inject=True, decision_reason="inject", block_count=5))
        snap = stats.snapshot()
        assert snap["total_queries"] == 3
        assert snap["total_injections"] == 2
        assert snap["total_skips"] == 1
        assert snap["total_blocks_injected"] == 7
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_query_stats.py -x -q`
Expected: ImportError — `QueryStats` does not exist yet.

- [ ] **Step 3: Implement QueryStats with basic counting**

In `core/observability.py`, add after the existing `IntegrationDebugLogger` class:

```python
import threading


_MAX_SKIP_REASON_KEYS = 50
_SNAPSHOT_SKIP_REASON_LIMIT = 20


class QueryStats:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._total_queries = 0
        self._total_injections = 0
        self._total_skips = 0
        self._total_blocks_injected = 0
        self._total_flags = 0
        self._total_suppressions = 0
        self._skip_reasons: dict[str, int] = {}
        self._last_query_at: str | None = None
        self._stats_since = datetime.now(timezone.utc).isoformat()

    def record_query(self, result: object) -> None:
        try:
            should_inject = getattr(result, "should_inject", False)
            decision_reason = getattr(result, "decision_reason", "unknown")
            injectable_blocks = getattr(result, "injectable_blocks", [])
            with self._lock:
                self._total_queries += 1
                self._last_query_at = datetime.now(timezone.utc).isoformat()
                if should_inject and len(injectable_blocks) > 0:
                    self._total_injections += 1
                    self._total_blocks_injected += len(injectable_blocks)
                else:
                    self._total_skips += 1
                    reason = str(decision_reason) if decision_reason else "unknown"
                    if reason in self._skip_reasons:
                        self._skip_reasons[reason] += 1
                    elif len(self._skip_reasons) < _MAX_SKIP_REASON_KEYS:
                        self._skip_reasons[reason] = 1
                    else:
                        self._skip_reasons["_other"] = self._skip_reasons.get("_other", 0) + 1
        except Exception:
            pass

    def record_flag(self, suppressed: bool) -> None:
        try:
            with self._lock:
                self._total_flags += 1
                if suppressed:
                    self._total_suppressions += 1
        except Exception:
            pass

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            sorted_reasons = dict(
                sorted(self._skip_reasons.items(), key=lambda kv: kv[1], reverse=True)[:_SNAPSHOT_SKIP_REASON_LIMIT]
            )
            return {
                "total_queries": self._total_queries,
                "total_injections": self._total_injections,
                "total_skips": self._total_skips,
                "total_blocks_injected": self._total_blocks_injected,
                "total_flags": self._total_flags,
                "total_suppressions": self._total_suppressions,
                "skip_reasons": sorted_reasons,
                "last_query_at": self._last_query_at,
                "stats_since": self._stats_since,
            }
```

Also add `import threading` to the top of the file (alongside existing imports).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_query_stats.py -x -q`
Expected: All 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add core/observability.py tests/test_query_stats.py
git commit -m "feat: add QueryStats class with basic inject/skip counting"
```

---

### Task 2: Skip reason tracking and bounds

**Files:**
- Modify: `tests/test_query_stats.py`

- [ ] **Step 1: Write failing tests for skip reasons and bounds**

Append to `tests/test_query_stats.py`:

```python
class TestQueryStatsSkipReasons:
    def test_skip_reasons_accumulate_by_decision_reason(self):
        stats = QueryStats()
        stats.record_query(_make_result(should_inject=False, decision_reason="gate_blocked"))
        stats.record_query(_make_result(should_inject=False, decision_reason="gate_blocked"))
        stats.record_query(_make_result(should_inject=False, decision_reason="no_relevant_memory"))
        snap = stats.snapshot()
        assert snap["skip_reasons"] == {"gate_blocked": 2, "no_relevant_memory": 1}

    def test_skip_reasons_capped_at_50_keys(self):
        stats = QueryStats()
        for i in range(55):
            stats.record_query(_make_result(should_inject=False, decision_reason=f"reason_{i}"))
        snap = stats.snapshot()
        # 50 real keys + _other = at most 51, but snapshot caps at 20
        # Internally: first 50 distinct reasons stored, remaining 5 go to _other
        # Verify _other exists and has the overflow count
        full_snap = stats.snapshot()
        # Access internal state indirectly via snapshot
        # The snapshot returns top 20, so we check total counts
        total_skip_count = sum(full_snap["skip_reasons"].values())
        assert stats._total_skips == 55
        # _other should have count 5 (reasons 50-54)
        assert stats._skip_reasons.get("_other") == 5

    def test_snapshot_returns_top_20_skip_reasons_sorted_by_count(self):
        stats = QueryStats()
        # Create 30 distinct reasons with known counts
        for i in range(30):
            for _ in range(i + 1):
                stats.record_query(_make_result(should_inject=False, decision_reason=f"reason_{i}"))
        snap = stats.snapshot()
        reasons = snap["skip_reasons"]
        assert len(reasons) == 20
        counts = list(reasons.values())
        assert counts == sorted(counts, reverse=True)
        # Highest count reason should be reason_29 (count=30)
        assert list(reasons.keys())[0] == "reason_29"
```

- [ ] **Step 2: Run tests to verify they pass (these should already pass with existing implementation)**

Run: `python -m pytest tests/test_query_stats.py::TestQueryStatsSkipReasons -x -q`
Expected: All 3 pass (implementation was included in Task 1).

- [ ] **Step 3: Commit**

```bash
git add tests/test_query_stats.py
git commit -m "test: add skip reason tracking and bounds tests"
```

---

### Task 3: Flag counting, snapshot isolation, last_query_at, and exception safety

**Files:**
- Modify: `tests/test_query_stats.py`

- [ ] **Step 1: Write tests for flags, snapshot isolation, timestamps, and safety**

Append to `tests/test_query_stats.py`:

```python
from unittest.mock import patch


class TestQueryStatsFlagCounting:
    def test_flag_without_suppression(self):
        stats = QueryStats()
        stats.record_flag(suppressed=False)
        stats.record_flag(suppressed=False)
        snap = stats.snapshot()
        assert snap["total_flags"] == 2
        assert snap["total_suppressions"] == 0

    def test_flag_with_suppression(self):
        stats = QueryStats()
        stats.record_flag(suppressed=False)
        stats.record_flag(suppressed=True)
        stats.record_flag(suppressed=True)
        snap = stats.snapshot()
        assert snap["total_flags"] == 3
        assert snap["total_suppressions"] == 2


class TestQueryStatsSnapshotIsolation:
    def test_mutating_snapshot_does_not_affect_internal_state(self):
        stats = QueryStats()
        stats.record_query(_make_result(should_inject=False, decision_reason="gate_blocked"))
        snap1 = stats.snapshot()
        snap1["total_queries"] = 999
        snap1["skip_reasons"]["gate_blocked"] = 999
        snap2 = stats.snapshot()
        assert snap2["total_queries"] == 1
        assert snap2["skip_reasons"]["gate_blocked"] == 1


class TestQueryStatsTimestamps:
    def test_last_query_at_none_before_any_query(self):
        stats = QueryStats()
        assert stats.snapshot()["last_query_at"] is None

    def test_last_query_at_set_after_query(self):
        stats = QueryStats()
        stats.record_query(_make_result(should_inject=False, decision_reason="test"))
        snap = stats.snapshot()
        assert snap["last_query_at"] is not None
        assert "T" in snap["last_query_at"]  # ISO format

    def test_stats_since_set_at_construction(self):
        stats = QueryStats()
        snap = stats.snapshot()
        assert snap["stats_since"] is not None
        assert "T" in snap["stats_since"]


class TestQueryStatsExceptionSafety:
    def test_record_query_with_none_does_not_raise(self):
        stats = QueryStats()
        stats.record_query(None)
        # getattr(None, ...) returns defaults, so it counts as a skip — harmless
        snap = stats.snapshot()
        assert snap["total_queries"] >= 0  # key invariant: no exception raised

    def test_record_query_with_bad_object_does_not_raise(self):
        stats = QueryStats()
        stats.record_query("not a result")
        snap = stats.snapshot()
        assert snap["total_queries"] >= 0  # key invariant: no exception raised

    def test_record_flag_still_works_after_bad_record_query(self):
        stats = QueryStats()
        stats.record_query(None)
        stats.record_flag(suppressed=True)
        assert stats.snapshot()["total_flags"] == 1
        assert stats.snapshot()["total_suppressions"] == 1
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `python -m pytest tests/test_query_stats.py -x -q`
Expected: All tests pass. `record_query` wraps everything in try/except, so garbage input never raises. `getattr(None, ...)` returns defaults, so `None` counts as a skip — a harmless counter increment. The key invariant: **it must not raise**.

- [ ] **Step 3: Commit**

```bash
git add tests/test_query_stats.py
git commit -m "test: add flag counting, snapshot isolation, timestamp, and exception safety tests"
```

---

### Task 4: Thread safety test

**Files:**
- Modify: `tests/test_query_stats.py`

- [ ] **Step 1: Write thread safety test**

Append to `tests/test_query_stats.py`:

```python
from concurrent.futures import ThreadPoolExecutor


class TestQueryStatsThreadSafety:
    def test_concurrent_record_query_no_lost_increments(self):
        stats = QueryStats()
        n_threads = 8
        n_per_thread = 500

        def record_batch():
            for _ in range(n_per_thread):
                stats.record_query(_make_result(should_inject=True, decision_reason="inject", block_count=1))

        with ThreadPoolExecutor(max_workers=n_threads) as pool:
            futures = [pool.submit(record_batch) for _ in range(n_threads)]
            for f in futures:
                f.result()

        snap = stats.snapshot()
        expected = n_threads * n_per_thread
        assert snap["total_queries"] == expected
        assert snap["total_injections"] == expected
        assert snap["total_blocks_injected"] == expected

    def test_concurrent_record_flag_no_lost_increments(self):
        stats = QueryStats()
        n_threads = 8
        n_per_thread = 500

        def flag_batch():
            for i in range(n_per_thread):
                stats.record_flag(suppressed=(i % 2 == 0))

        with ThreadPoolExecutor(max_workers=n_threads) as pool:
            futures = [pool.submit(flag_batch) for _ in range(n_threads)]
            for f in futures:
                f.result()

        snap = stats.snapshot()
        assert snap["total_flags"] == n_threads * n_per_thread
        assert snap["total_suppressions"] == n_threads * (n_per_thread // 2)
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `python -m pytest tests/test_query_stats.py::TestQueryStatsThreadSafety -x -q`
Expected: Both pass — Lock prevents lost increments.

- [ ] **Step 3: Commit**

```bash
git add tests/test_query_stats.py
git commit -m "test: add thread safety tests for QueryStats"
```

---

### Task 5: Wire QueryStats into QueryExecutor

**Files:**
- Modify: `core/query.py` (lines 30-45 for __init__, lines 95, 152, 162 for return paths)
- Modify: `core/service.py` (line 65 for QueryExecutor construction)

- [ ] **Step 1: Write failing test for QueryExecutor integration**

Append to `tests/test_query_stats.py`:

```python
from core.query import QueryExecutor
from core.observability import QueryStats


class TestQueryExecutorStatsIntegration:
    def test_query_executor_records_stats_on_no_visibility_path(self):
        """QueryExecutor.query() calls stats.record_query() on the visibility fail-closed path."""
        from unittest.mock import MagicMock

        storage = MagicMock()
        retrieval = MagicMock()
        plugin = MagicMock()
        plugin.requires_visibility_context = True
        plugins = {"test": plugin}

        query_stats = QueryStats()
        executor = QueryExecutor(
            storage, retrieval, plugins, "test", query_stats=query_stats,
        )
        result = executor.query("hello", 5, container_ref=None, visibility=None)
        assert result.should_inject is False
        snap = query_stats.snapshot()
        assert snap["total_queries"] == 1
        assert snap["total_skips"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_query_stats.py::TestQueryExecutorStatsIntegration -x -q`
Expected: TypeError — `QueryExecutor.__init__()` got an unexpected keyword argument 'query_stats'.

- [ ] **Step 3: Add query_stats parameter to QueryExecutor and record on all return paths**

In `core/query.py`, modify `QueryExecutor.__init__` to accept an optional `query_stats` parameter:

Change the `__init__` method (lines 31-45) to:

```python
class QueryExecutor:
    def __init__(
        self,
        storage: StorageProvider,
        retrieval: RetrievalProvider,
        semantic_plugins: dict[str, SemanticPlugin],
        default_use_case: str,
        type_registry: TypeRegistry | None = None,
        routing_overrides=None,
        query_stats: QueryStats | None = None,
    ) -> None:
        self._storage = storage
        self._retrieval = retrieval
        self._semantic_plugins = semantic_plugins
        self._default_use_case = default_use_case
        self._type_registry = type_registry
        self._routing_overrides = routing_overrides
        self._query_stats = query_stats
```

Add import at top of `core/query.py`:

```python
from core.observability import QueryStats
```

Then wrap each of the three `return QueryResult(...)` paths to record before returning.

**Return path 1** (visibility fail-closed, around line 95-101): change to:

```python
            result = QueryResult(
                results=[],
                trace=trace,
                should_inject=False,
                decision_reason="no_relevant_memory",
                injectable_blocks=[],
            )
            if self._query_stats is not None:
                self._query_stats.record_query(result)
            return result
```

**Return path 2** (routed query, around line 152-158): change to:

```python
            result = QueryResult(
                results=outcome.results,
                trace=routed_trace,
                should_inject=outcome.should_inject,
                decision_reason=outcome.decision_reason,
                injectable_blocks=outcome.injectable_blocks,
            )
            if self._query_stats is not None:
                self._query_stats.record_query(result)
            return result
```

**Return path 3** (no routing, around line 162-168): change to:

```python
        result = QueryResult(
            results=retrieval_result.results,
            trace=trace,
            should_inject=False,
            decision_reason="injection_policy_unavailable",
            injectable_blocks=[],
        )
        if self._query_stats is not None:
            self._query_stats.record_query(result)
        return result
```

- [ ] **Step 4: Run the integration test to verify it passes**

Run: `python -m pytest tests/test_query_stats.py::TestQueryExecutorStatsIntegration -x -q`
Expected: PASS.

- [ ] **Step 5: Run full test suite to verify no regressions**

Run: `python -m pytest tests/ -x -q`
Expected: All tests pass. `QueryExecutor` callers don't pass `query_stats`, so the default `None` means no recording — existing behavior unchanged.

- [ ] **Step 6: Commit**

```bash
git add core/query.py tests/test_query_stats.py
git commit -m "feat: wire QueryStats into QueryExecutor return paths"
```

---

### Task 6: Wire QueryStats into PalliumService for flag recording

**Files:**
- Modify: `core/service.py` (lines 37-52 for __init__, lines 546-553 for flag_memory_object)

- [ ] **Step 1: Write failing test for flag recording via PalliumService**

Append to `tests/test_query_stats.py`:

```python
class TestServiceFlagStatsIntegration:
    def test_flag_memory_object_records_stats(self):
        from core.observability import QueryStats
        from storage.sqlite import SQLiteStorageProvider
        from core.models import MemoryObject, SourceItem, Relation
        from datetime import datetime, timezone
        from uuid import uuid4

        storage = SQLiteStorageProvider("sqlite:///:memory:")
        source = SourceItem(
            source_type="chat_message",
            source_id=f"src-{uuid4().hex[:8]}",
            content_type="text/plain",
            content="test",
            processing_status="completed",
            created_at=datetime.now(timezone.utc),
        )
        storage.create_source_item(source)
        memory = MemoryObject(
            type="decision",
            schema_id="test",
            schema_version="v1",
            payload={"summary": "test"},
            lifecycle="active",
            created_at=datetime.now(timezone.utc),
        )
        storage.create_memory_object(memory)
        storage.create_relation(
            Relation(
                from_kind="memory_object",
                from_id=memory.id,
                relation_type="supported_by",
                to_kind="source_item",
                to_id=source.id,
            )
        )

        from semantic.demo_agent_memory import DemoAgentMemoryPlugin
        from retrieval.lexical import LexicalRetrievalProvider

        plugin = DemoAgentMemoryPlugin()
        retrieval = LexicalRetrievalProvider(storage)
        query_stats = QueryStats()

        service = PalliumService(
            storage=storage,
            retrieval=retrieval,
            semantic_plugins={plugin.name: plugin},
            default_use_case=plugin.name,
            query_stats=query_stats,
        )

        service.flag_memory_object(
            memory_object_id=memory.id,
            reason="wrong",
            source_ref="user-1",
            immediate=True,
        )

        snap = query_stats.snapshot()
        assert snap["total_flags"] == 1
        assert snap["total_suppressions"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_query_stats.py::TestServiceFlagStatsIntegration -x -q`
Expected: TypeError — `PalliumService.__init__()` got an unexpected keyword argument 'query_stats'.

- [ ] **Step 3: Add query_stats parameter to PalliumService**

In `core/service.py`, add `query_stats` parameter to `__init__`:

Add import at top:
```python
from core.observability import QueryStats
```

Modify `__init__` signature (after `routing_overrides=None`):
```python
    def __init__(
        self,
        storage: StorageProvider,
        retrieval: RetrievalProvider,
        semantic_plugins: dict[str, SemanticPlugin],
        default_use_case: str,
        observability: IntegrationDebugLogger | None = None,
        *,
        retention_enabled: bool = False,
        retention_lease_seconds: int = 300,
        retention_batch_size: int = 200,
        embedding_provider: EmbeddingProvider | None = None,
        vector_index: VectorIndex | None = None,
        type_registry: TypeRegistry | None = None,
        routing_overrides=None,
        query_stats: QueryStats | None = None,
    ) -> None:
```

Add after `self._type_registry = type_registry`:
```python
        self._query_stats = query_stats
```

Pass `query_stats` through to `QueryExecutor` construction (around line 65):
```python
        self._query_executor = QueryExecutor(
            storage, retrieval, semantic_plugins, default_use_case,
            type_registry=type_registry,
            routing_overrides=routing_overrides,
            query_stats=query_stats,
        )
```

In `flag_memory_object` (around line 546-553), add stats recording before the return:
```python
        result = FlagResult(
            memory_object_id=memory_object_id,
            flag_count=self._storage.count_total_flags(memory_object_id),
            unique_sources=self._storage.count_unique_flag_sources(
                memory_object_id, self.FLAG_WINDOW_DAYS
            ),
            suppressed=suppressed,
        )
        if self._query_stats is not None:
            self._query_stats.record_flag(suppressed=result.suppressed)
        return result
```

- [ ] **Step 4: Run the integration test to verify it passes**

Run: `python -m pytest tests/test_query_stats.py::TestServiceFlagStatsIntegration -x -q`
Expected: PASS.

- [ ] **Step 5: Run full test suite to verify no regressions**

Run: `python -m pytest tests/ -x -q`
Expected: All tests pass. Existing PalliumService callers don't pass `query_stats`, so default `None` preserves behavior.

- [ ] **Step 6: Commit**

```bash
git add core/service.py tests/test_query_stats.py
git commit -m "feat: wire QueryStats into PalliumService for flag recording"
```

---

### Task 7: Surface QueryStats on /status endpoint

**Files:**
- Modify: `app/main.py` (lines 57-72 for create_app, lines 220-229 for /status handler)
- Modify: `app/dependencies.py` (lines 333-346 for build_service)

- [ ] **Step 1: Write failing test for /status query stats**

Append to `tests/test_query_stats.py`:

```python
from fastapi.testclient import TestClient


class TestStatusEndpointQueryStats:
    def test_status_includes_query_key(self):
        from app.main import create_app
        app = create_app()
        client = TestClient(app)
        resp = client.get("/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "query" in data
        query = data["query"]
        assert query["total_queries"] == 0
        assert query["total_injections"] == 0
        assert query["total_skips"] == 0
        assert query["total_blocks_injected"] == 0
        assert query["total_flags"] == 0
        assert query["total_suppressions"] == 0
        assert query["skip_reasons"] == {}
        assert query["last_query_at"] is None
        assert "stats_since" in query
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_query_stats.py::TestStatusEndpointQueryStats -x -q`
Expected: FAIL — `"query"` key not in /status response.

- [ ] **Step 3: Create QueryStats in create_app and pass through build_service**

In `app/dependencies.py`, modify `build_service` to accept and pass through `query_stats`:

Add import:
```python
from core.observability import QueryStats
```

Modify `build_service` signature:
```python
def build_service(
    config: AppConfig | None = None,
    routing_overrides: RoutingOverrides | None = None,
    *,
    enable_vector: bool = True,
    query_stats: QueryStats | None = None,
) -> PalliumService:
```

Modify the `return PalliumService(...)` call (around line 333) to include `query_stats`:
```python
    return PalliumService(
        storage=storage,
        retrieval=retrieval,
        semantic_plugins=plugins,
        default_use_case=resolved_config.default_use_case,
        observability=IntegrationDebugLogger(enabled=resolved_config.observability.integration_debug),
        retention_enabled=resolved_config.retention.enabled,
        retention_lease_seconds=resolved_config.retention.lease_seconds,
        retention_batch_size=resolved_config.retention.batch_size,
        embedding_provider=embedding_provider,
        vector_index=vector_index,
        type_registry=type_registry if len(type_registry) > 0 else None,
        routing_overrides=routing_overrides,
        query_stats=query_stats,
    )
```

In `app/main.py`, modify `create_app`:

Add import:
```python
from core.observability import QueryStats
```

After `resolved_config = config or AppConfig.from_env()` (line 71), create the stats instance:
```python
    query_stats = QueryStats()
    service = build_service(resolved_config, routing_overrides=routing_overrides, query_stats=query_stats)
```

In the `/status` handler, add after `uptime = round(...)` (line 218):
```python
        # --- Query stats (best-effort) ---
        query_info: dict | None = None
        try:
            query_info = query_stats.snapshot()
        except Exception:
            logger.warning("status: query stats failed", exc_info=True)
```

Modify the return JSONResponse to include the `"query"` key:
```python
        return JSONResponse(content={
            "pending_items": pending_count,
            "oldest_pending_age_seconds": oldest_pending_age,
            "total_source_items": total_source,
            "total_memory_objects": total_memory,
            "snapshot": snapshot_info,
            "storage": storage_info,
            "vector_index_ready": vector_index_ready,
            "uptime_seconds": uptime,
            "query": query_info,
        })
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_query_stats.py::TestStatusEndpointQueryStats -x -q`
Expected: PASS.

- [ ] **Step 5: Run full test suite to verify no regressions**

Run: `python -m pytest tests/ -x -q`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add app/main.py app/dependencies.py tests/test_query_stats.py
git commit -m "feat: surface QueryStats on /status endpoint under 'query' key"
```

---

### Task 8: Final full-suite verification

- [ ] **Step 1: Run all QueryStats tests**

Run: `python -m pytest tests/test_query_stats.py -v`
Expected: All tests pass with clear names.

- [ ] **Step 2: Run full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: All tests pass, no regressions.

- [ ] **Step 3: Verify /status endpoint shape manually (optional smoke test)**

Start the server if possible and hit `/status`:
```bash
curl http://127.0.0.1:8000/status | python -m json.tool
```
Expected: Response includes `"query": { ... }` with all expected fields.
