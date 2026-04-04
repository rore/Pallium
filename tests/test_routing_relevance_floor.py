"""Tests for the relevance floor pre-filter."""
import pytest
from unittest.mock import MagicMock
from semantic.agent_conversation_memory_routing_floor import apply_relevance_floor, FloorThresholds


def _make_result(lexical_score=0, vector_score=0):
    item = MagicMock()
    item.lexical_score = lexical_score
    item.vector_score = vector_score
    return item


def test_strong_vector_passes():
    items = [_make_result(lexical_score=0, vector_score=600)]
    result = apply_relevance_floor(items)
    assert len(result.survivors) == 1


def test_strong_lexical_passes():
    items = [_make_result(lexical_score=3, vector_score=0)]
    result = apply_relevance_floor(items)
    assert len(result.survivors) == 1


def test_weak_both_filtered():
    items = [_make_result(lexical_score=1, vector_score=500)]
    result = apply_relevance_floor(items)
    assert len(result.survivors) == 0
    assert result.filtered_count == 1


def test_empty_input():
    result = apply_relevance_floor([])
    assert len(result.survivors) == 0
    assert result.filtered_count == 0


def test_mixed_set():
    items = [
        _make_result(lexical_score=4, vector_score=700),  # passes both
        _make_result(lexical_score=1, vector_score=510),  # fails both
        _make_result(lexical_score=0, vector_score=620),  # passes vector
    ]
    result = apply_relevance_floor(items)
    assert len(result.survivors) == 2
    assert result.filtered_count == 1


def test_custom_thresholds():
    items = [_make_result(lexical_score=1, vector_score=500)]
    lenient = FloorThresholds(min_vector=400, min_lexical=1)
    result = apply_relevance_floor(items, thresholds=lenient)
    assert len(result.survivors) == 1


def test_filtered_score_ranges():
    items = [
        _make_result(lexical_score=1, vector_score=510),
        _make_result(lexical_score=0, vector_score=540),
    ]
    result = apply_relevance_floor(items)
    assert result.filtered_count == 2
    assert "vector" in result.filtered_score_ranges
    assert result.filtered_score_ranges["vector"] == (510, 540)
