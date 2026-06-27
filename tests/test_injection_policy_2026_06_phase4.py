"""Phase 4 — trigger_origin plumbing + gate bypass.

See: docs/specs/2026-06-27-injection-policy-abstention.md (Phase 4).

These tests cover:
- API/MCP wire format accepts and validates trigger_origin
- The audit-log column is populated with the validated value
- The abstention gate's trigger-bypass semantics: a request carrying a
  deterministic on-demand trigger_origin allows event/on_demand/suspended
  type candidates through (proactive thresholds still apply)
"""

from __future__ import annotations

import pytest

from api.routes import _validate_trigger_origin, _VALID_TRIGGER_ORIGINS
from app.config import InjectionPolicyConfig, InjectionTypePolicy
from core.models import QueryResultItem
from fastapi import HTTPException
from semantic.agent_conversation_memory_routing_selection import (
    _TRIGGER_BYPASS_ORIGINS,
    _policy_allows_proactive_injection,
)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_validate_trigger_origin_accepts_none() -> None:
    assert _validate_trigger_origin(None) is None


@pytest.mark.parametrize("origin", sorted(_VALID_TRIGGER_ORIGINS))
def test_validate_trigger_origin_accepts_known_values(origin: str) -> None:
    assert _validate_trigger_origin(origin) == origin


def test_validate_trigger_origin_rejects_unknown() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_trigger_origin("nonsense")
    assert exc.value.status_code == 400
    assert "Unknown trigger_origin" in exc.value.detail


def test_valid_origins_includes_phase4_set() -> None:
    """Ensure the Phase 4 deterministic triggers are all whitelisted."""
    expected = {
        "session_start_orientation",
        "session_start_checkpoint",
        "user_prompt_submit",
        "pre_compact",
        "post_tool_failure",
        "retry_threshold",
        "user_explicit",
    }
    assert expected.issubset(_VALID_TRIGGER_ORIGINS)


def test_trigger_bypass_set_matches_phase4_deterministic_triggers() -> None:
    """Bypass set is the Phase 4 trigger origins that legitimately retrieve
    demoted types. session_start_orientation is the BROAD orientation query
    (covered by Phase 6 proactive default), NOT a deterministic on-demand
    trigger, so it stays OUT of the bypass set.
    """
    assert _TRIGGER_BYPASS_ORIGINS == frozenset({
        "session_start_checkpoint",
        "post_tool_failure",
        "retry_threshold",
        "user_explicit",
    })


# ---------------------------------------------------------------------------
# Gate-bypass semantics
# ---------------------------------------------------------------------------


def _candidate(memory_type: str = "investigation_outcome", score: float = 10.0) -> dict:
    return {
        "item": QueryResultItem(
            result_id=f"memory_object:m1",
            result_kind="memory_hit",
            score=score,
            evidence=[],
            memory_object_id="m1",
            type=memory_type,
        ),
    }


@pytest.mark.parametrize("mode", ["event", "on_demand", "suspended"])
def test_gate_drops_demoted_types_without_trigger(mode: str) -> None:
    """No trigger_origin → demoted-mode candidates are dropped, as in Phase 3a."""
    policy = InjectionPolicyConfig(types={
        "investigation_outcome": InjectionTypePolicy(mode=mode),
    })
    cand = _candidate()
    assert _policy_allows_proactive_injection(cand, policy, None) is False
    assert _policy_allows_proactive_injection(cand, policy, None, trigger_origin=None) is False


@pytest.mark.parametrize("mode", ["event", "on_demand", "suspended"])
@pytest.mark.parametrize("trigger", sorted(_TRIGGER_BYPASS_ORIGINS))
def test_gate_bypass_for_demoted_types_with_deterministic_trigger(
    mode: str, trigger: str
) -> None:
    """With a deterministic trigger, demoted modes are allowed through."""
    policy = InjectionPolicyConfig(types={
        "investigation_outcome": InjectionTypePolicy(mode=mode),
    })
    cand = _candidate()
    assert _policy_allows_proactive_injection(
        cand, policy, None, trigger_origin=trigger
    ) is True


def test_gate_bypass_does_not_apply_to_proactive_mode_thresholds() -> None:
    """A trigger_origin must NOT override a proactive min_score threshold.
    Demoted types are about *eligibility*; proactive types still gate on
    score regardless of trigger.
    """
    policy = InjectionPolicyConfig(types={
        "decision": InjectionTypePolicy(mode="proactive", min_score=22.0),
    })
    low_cand = _candidate(memory_type="decision", score=10.0)
    high_cand = _candidate(memory_type="decision", score=25.0)
    # Bypass-trigger does NOT magic-resurrect a below-threshold candidate.
    assert _policy_allows_proactive_injection(
        low_cand, policy, None, trigger_origin="post_tool_failure"
    ) is False
    # High score still passes regardless.
    assert _policy_allows_proactive_injection(
        high_cand, policy, None, trigger_origin="post_tool_failure"
    ) is True


def test_gate_bypass_does_not_apply_for_non_bypass_triggers() -> None:
    """session_start_orientation, user_prompt_submit, pre_compact are
    proactive default queries — they must NOT bypass demotions.
    """
    policy = InjectionPolicyConfig(types={
        "investigation_outcome": InjectionTypePolicy(mode="on_demand"),
    })
    cand = _candidate()
    for non_bypass in ("session_start_orientation", "user_prompt_submit", "pre_compact"):
        assert _policy_allows_proactive_injection(
            cand, policy, None, trigger_origin=non_bypass
        ) is False, f"trigger {non_bypass!r} unexpectedly bypassed the gate"


def test_gate_unknown_trigger_does_not_bypass() -> None:
    """A trigger_origin string not in the bypass set must not bypass."""
    policy = InjectionPolicyConfig(types={
        "investigation_outcome": InjectionTypePolicy(mode="on_demand"),
    })
    cand = _candidate()
    assert _policy_allows_proactive_injection(
        cand, policy, None, trigger_origin="bogus_value"
    ) is False


def test_gate_trigger_irrelevant_when_policy_empty() -> None:
    """With no policy, the gate is a no-op regardless of trigger_origin."""
    cand = _candidate()
    for trigger in (None, "post_tool_failure", "bogus"):
        assert _policy_allows_proactive_injection(
            cand, InjectionPolicyConfig(), None, trigger_origin=trigger
        ) is True
        assert _policy_allows_proactive_injection(
            cand, None, None, trigger_origin=trigger
        ) is True
