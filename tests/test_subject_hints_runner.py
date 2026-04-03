# tests/test_subject_hints_runner.py
from __future__ import annotations

import pytest
from core.models import MemorySubjectAnchor


# ---------------------------------------------------------------------------
# _normalize_hint
# ---------------------------------------------------------------------------

def test_normalize_hint_lowercases():
    from evals.subject_hints_runner import _normalize_hint
    kind, value = _normalize_hint("Component", "Catalog Sync")
    assert kind == "component"
    assert value == "catalog sync"


def test_normalize_hint_strips_leading_noise():
    from evals.subject_hints_runner import _normalize_hint
    # "the importer" -> noise token "the" stripped -> "importer"
    _, value = _normalize_hint("component", "the importer")
    assert value == "importer"


def test_normalize_hint_strips_trailing_noise():
    from evals.subject_hints_runner import _normalize_hint
    # "importer here" -> trailing "here" stripped -> "importer"
    _, value = _normalize_hint("component", "importer here")
    assert value == "importer"


# ---------------------------------------------------------------------------
# _score_item
# ---------------------------------------------------------------------------

def _make_anchor(kind: str, value: str) -> MemorySubjectAnchor:
    return MemorySubjectAnchor(kind=kind, value=value)


def test_score_item_all_hits():
    from evals.subject_hints_runner import _score_item
    extracted = [_make_anchor("component", "catalog sync")]
    expected = [{"kind": "component", "value": "catalog sync"}]
    hits, misses, spurious = _score_item(extracted, expected, [])
    assert len(hits) == 1
    assert len(misses) == 0
    assert len(spurious) == 0


def test_score_item_miss():
    from evals.subject_hints_runner import _score_item
    extracted = []
    expected = [{"kind": "component", "value": "importer"}]
    hits, misses, spurious = _score_item(extracted, expected, [])
    assert len(hits) == 0
    assert len(misses) == 1
    assert len(spurious) == 0


def test_score_item_spurious():
    from evals.subject_hints_runner import _score_item
    extracted = [_make_anchor("component", "importer")]
    expected = []
    forbidden = [{"kind": "component", "value": "importer"}]
    hits, misses, spurious = _score_item(extracted, expected, forbidden)
    assert len(hits) == 0
    assert len(misses) == 0
    assert len(spurious) == 1


def test_score_item_case_insensitive_match():
    from evals.subject_hints_runner import _score_item
    extracted = [_make_anchor("component", "Catalog Sync")]
    expected = [{"kind": "component", "value": "catalog sync"}]
    hits, misses, spurious = _score_item(extracted, expected, [])
    assert len(hits) == 1
    assert len(misses) == 0


def test_score_item_multi_anchor():
    from evals.subject_hints_runner import _score_item
    extracted = [
        _make_anchor("workstream", "LIB-4521"),
        _make_anchor("component", "title search filtering"),
        _make_anchor("surface", "patron portal"),
    ]
    expected = [
        {"kind": "workstream", "value": "LIB-4521"},
        {"kind": "component", "value": "title search filtering"},
        {"kind": "surface", "value": "patron portal"},
    ]
    hits, misses, spurious = _score_item(extracted, expected, [])
    assert len(hits) == 3
    assert len(misses) == 0
    assert len(spurious) == 0


def test_score_item_spurious_does_not_double_count_hit():
    from evals.subject_hints_runner import _score_item
    # an expected hint that is also in forbidden should be in hits (correct extraction)
    # and not spurious — forbidden is only checked against extracted, not against expected
    extracted = [_make_anchor("component", "importer")]
    expected = [{"kind": "component", "value": "importer"}]
    forbidden = [{"kind": "component", "value": "importer"}]
    hits, misses, spurious = _score_item(extracted, expected, forbidden)
    # hits: importer is in required ∩ extracted
    assert len(hits) == 1
    # spurious: importer is in extracted ∩ forbidden — the spec definition includes this
    assert len(spurious) == 1


# ---------------------------------------------------------------------------
# _aggregate_variant
# ---------------------------------------------------------------------------

def test_aggregate_variant_recall():
    from evals.subject_hints_runner import _aggregate_variant
    item_results = [
        {"hits_count": 2, "required_count": 2, "spurious_count": 0},
        {"hits_count": 1, "required_count": 2, "spurious_count": 0},
    ]
    summary = _aggregate_variant(item_results)
    assert summary["recall"] == pytest.approx(3 / 4)
    assert summary["spurious_count"] == 0
    assert summary["perfect_items"] == 1
    assert summary["items_total"] == 2


def test_aggregate_variant_all_perfect():
    from evals.subject_hints_runner import _aggregate_variant
    item_results = [
        {"hits_count": 1, "required_count": 1, "spurious_count": 0},
        {"hits_count": 3, "required_count": 3, "spurious_count": 0},
    ]
    summary = _aggregate_variant(item_results)
    assert summary["recall"] == 1.0
    assert summary["perfect_items"] == 2


def test_aggregate_variant_zero_required_no_division_error():
    from evals.subject_hints_runner import _aggregate_variant
    item_results = [
        {"hits_count": 0, "required_count": 0, "spurious_count": 0},
    ]
    summary = _aggregate_variant(item_results)
    assert summary["recall"] == 0.0
