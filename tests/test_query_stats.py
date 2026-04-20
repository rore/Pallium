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


from core.query import QueryExecutor


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


class TestServiceFlagStatsIntegration:
    def test_flag_memory_object_records_stats(self):
        from core.observability import QueryStats
        from storage.sqlite import SQLiteStorageProvider
        from core.models import MemoryObject, SourceItem, Relation
        from core.service import PalliumService
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
