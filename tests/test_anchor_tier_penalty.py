from __future__ import annotations

import pytest
from semantic.agent_conversation_memory_routing_scoring import (
    _apply_anchor_tier_penalty,
)
from semantic.agent_conversation_memory_routing_constants import (
    ANCHOR_SECONDARY_TIER_PENALTY,
    ROUTING_FOCUS_BOOST,
)


def _make_candidate(status: str | None, base: int) -> dict:
    c: dict = {"base_routing_score": base}
    if status is not None:
        c["anchor_prefilter_status"] = status
    return c


def test_penalty_invariant_anchor_secondary_penalty_ge_focus_boost() -> None:
    assert ANCHOR_SECONDARY_TIER_PENALTY >= ROUTING_FOCUS_BOOST


def test_aligned_candidate_receives_zero_penalty() -> None:
    c = _make_candidate("aligned", 500)
    _apply_anchor_tier_penalty([c])
    assert c["anchor_tier_penalty"] == 0
    assert c["base_routing_score"] == 500


def test_no_status_candidate_receives_zero_penalty() -> None:
    c = _make_candidate(None, 400)
    _apply_anchor_tier_penalty([c])
    assert c["anchor_tier_penalty"] == 0
    assert c["base_routing_score"] == 400


def test_insufficient_retained_receives_full_penalty() -> None:
    c = _make_candidate("insufficient_retained", 600)
    _apply_anchor_tier_penalty([c])
    assert c["anchor_tier_penalty"] == ANCHOR_SECONDARY_TIER_PENALTY
    assert c["base_routing_score"] == 600 - ANCHOR_SECONDARY_TIER_PENALTY


def test_legacy_fallback_retained_receives_full_penalty() -> None:
    c = _make_candidate("legacy_fallback_retained", 550)
    _apply_anchor_tier_penalty([c])
    assert c["anchor_tier_penalty"] == ANCHOR_SECONDARY_TIER_PENALTY
    assert c["base_routing_score"] == 550 - ANCHOR_SECONDARY_TIER_PENALTY


def test_insufficient_retained_demoted_receives_full_penalty() -> None:
    c = _make_candidate("insufficient_retained_demoted", 620)
    _apply_anchor_tier_penalty([c])
    assert c["anchor_tier_penalty"] == ANCHOR_SECONDARY_TIER_PENALTY
    assert c["base_routing_score"] == 620 - ANCHOR_SECONDARY_TIER_PENALTY


def test_secondary_tier_receives_full_penalty() -> None:
    c = _make_candidate("secondary_tier", 580)
    _apply_anchor_tier_penalty([c])
    assert c["anchor_tier_penalty"] == ANCHOR_SECONDARY_TIER_PENALTY
    assert c["base_routing_score"] == 580 - ANCHOR_SECONDARY_TIER_PENALTY


def test_mixed_candidates_only_secondary_penalized() -> None:
    aligned = _make_candidate("aligned", 500)
    secondary = _make_candidate("insufficient_retained", 600)
    none_status = _make_candidate(None, 400)
    _apply_anchor_tier_penalty([aligned, secondary, none_status])
    assert aligned["base_routing_score"] == 500
    assert secondary["base_routing_score"] == 600 - ANCHOR_SECONDARY_TIER_PENALTY
    assert none_status["base_routing_score"] == 400
