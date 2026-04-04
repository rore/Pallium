"""Tests for pre-computation annotation functions."""
import pytest
from datetime import datetime, timezone
from semantic.agent_conversation_memory_routing_annotations import (
    annotate_freshness_ranks,
    compute_structured_support_ratio,
    annotate_work_resumption_context,
)


def _ts(seconds):
    """Helper: create datetime from epoch seconds."""
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


class TestFreshnessRanks:
    def test_ranks_per_type(self):
        candidates = [
            {"layer": "decision", "freshness_timestamp_value": _ts(100)},
            {"layer": "decision", "freshness_timestamp_value": _ts(300)},
            {"layer": "decision", "freshness_timestamp_value": _ts(200)},
            {"layer": "investigation_outcome", "freshness_timestamp_value": _ts(50)},
        ]
        annotate_freshness_ranks(candidates)
        assert candidates[0]["freshness_rank_in_type"] == 3  # ts=100, oldest
        assert candidates[1]["freshness_rank_in_type"] == 1  # ts=300, freshest
        assert candidates[2]["freshness_rank_in_type"] == 2  # ts=200, middle
        assert candidates[3]["freshness_rank_in_type"] == 1  # only investigation

    def test_single_candidate(self):
        candidates = [{"layer": "decision", "freshness_timestamp_value": _ts(100)}]
        annotate_freshness_ranks(candidates)
        assert candidates[0]["freshness_rank_in_type"] == 1

    def test_empty_candidates(self):
        annotate_freshness_ranks([])  # should not raise

    def test_none_timestamp(self):
        candidates = [
            {"layer": "decision", "freshness_timestamp_value": None},
            {"layer": "decision", "freshness_timestamp_value": _ts(100)},
        ]
        annotate_freshness_ranks(candidates)
        assert candidates[1]["freshness_rank_in_type"] == 1  # has timestamp, freshest
        assert candidates[0]["freshness_rank_in_type"] == 2  # None → 0, oldest


class TestStructuredSupportRatio:
    def test_structured_dominates(self):
        candidates = [
            {"layer": "decision", "support_score": 80},
            {"layer": "decision", "support_score": 70},
            {"layer": "source_evidence", "support_score": 10},
        ]
        result = compute_structured_support_ratio(candidates)
        assert result["structured_dominates"] is True
        assert result["structured_supported_count"] == 2
        assert result["source_count"] == 1

    def test_source_dominates(self):
        candidates = [
            {"layer": "decision", "support_score": 20},  # below supported threshold
            {"layer": "source_evidence", "support_score": 10},
            {"layer": "source_evidence", "support_score": 10},
        ]
        result = compute_structured_support_ratio(candidates)
        assert result["structured_dominates"] is False

    def test_no_structured(self):
        candidates = [{"layer": "source_evidence", "support_score": 10}]
        result = compute_structured_support_ratio(candidates)
        assert result["structured_dominates"] is False

    def test_empty(self):
        result = compute_structured_support_ratio([])
        assert result["structured_dominates"] is False


class TestWorkResumptionContext:
    def test_stale_checkpoint(self):
        candidates = [
            {"layer": "task_checkpoint", "freshness_timestamp_value": _ts(1000),
             "same_container": True},
            {"layer": "task_checkpoint", "freshness_timestamp_value": _ts(5000),
             "same_container": True},
        ]
        annotate_work_resumption_context(candidates)
        # 5000 - 1000 = 4000 > 2700 (FRESHNESS_MARGIN_SECONDS)
        assert candidates[0]["work_resumption_stale"] is True
        assert candidates[1]["work_resumption_stale"] is False

    def test_fresh_checkpoint(self):
        candidates = [
            {"layer": "task_checkpoint", "freshness_timestamp_value": _ts(4000),
             "same_container": True},
            {"layer": "task_checkpoint", "freshness_timestamp_value": _ts(5000),
             "same_container": True},
        ]
        annotate_work_resumption_context(candidates)
        # 5000 - 4000 = 1000 < 2700
        assert candidates[0]["work_resumption_stale"] is False
        assert candidates[1]["work_resumption_stale"] is False

    def test_no_checkpoints(self):
        candidates = [{"layer": "decision", "freshness_timestamp_value": _ts(100)}]
        annotate_work_resumption_context(candidates)  # should not raise

    def test_non_checkpoint_candidates_ignored(self):
        candidates = [
            {"layer": "task_checkpoint", "freshness_timestamp_value": _ts(5000),
             "same_container": True},
            {"layer": "decision", "freshness_timestamp_value": _ts(100)},
        ]
        annotate_work_resumption_context(candidates)
        assert candidates[0]["work_resumption_stale"] is False
        assert "work_resumption_stale" not in candidates[1]  # not a checkpoint
