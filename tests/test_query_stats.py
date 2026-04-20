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
