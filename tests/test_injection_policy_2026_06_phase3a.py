"""Phase 3a — abstention policy gate (config + selection path).

See: docs/specs/2026-06-27-injection-policy-abstention.md.

These tests exercise the gate in isolation against synthetic candidate
dicts shaped like the production selection path expects. End-to-end
no-regression validation is delegated to the full existing
test_routing_selection.py + test_routing_injection_check.py suites,
which are unchanged and continue to pass with empty policy.
"""

from __future__ import annotations

import pytest

from app.config import (
    AppConfig,
    InjectionConfig,
    InjectionPolicyConfig,
    InjectionTypePolicy,
    _build_injection_config,
)
from core.models import QueryFilters, QueryResultItem
from semantic.agent_conversation_memory_routing_selection import (
    _policy_allows_proactive_injection,
    _SELECTION_DROP_HUMAN_REASONS,
)


# ---------------------------------------------------------------------------
# Config loader tests
# ---------------------------------------------------------------------------


def test_app_config_default_has_empty_injection_policy() -> None:
    config = AppConfig()
    assert isinstance(config.injection, InjectionConfig)
    assert config.injection.policy.is_empty()
    assert config.injection.policy.types == {}
    assert config.injection.policy.containers == {}


def test_build_injection_config_returns_empty_when_section_absent() -> None:
    cfg = _build_injection_config({})
    assert cfg.policy.is_empty()


def test_build_injection_config_parses_global_type() -> None:
    cfg = _build_injection_config({
        "injection": {
            "policy": {
                "types": {
                    "decision": {"mode": "proactive", "min_score": 22.0},
                    "constraint_memory": {"mode": "proactive", "min_score": 20.0},
                },
            },
        },
    })
    assert "decision" in cfg.policy.types
    assert cfg.policy.types["decision"].mode == "proactive"
    assert cfg.policy.types["decision"].min_score == 22.0
    assert cfg.policy.types["constraint_memory"].min_score == 20.0


def test_build_injection_config_parses_per_container_override() -> None:
    cfg = _build_injection_config({
        "injection": {
            "policy": {
                "types": {
                    "decision": {"mode": "proactive", "min_score": 22.0},
                },
                "containers": [
                    {
                        "container_ref": "git:github.com/rore/pallium",
                        "types": {
                            "decision": {"mode": "proactive", "min_score": 19.0},
                        },
                    },
                    {
                        "container_ref": "path:xlm:2889e4f8fd37",
                        "types": {
                            "decision": {"mode": "on_demand"},
                        },
                    },
                ],
            },
        },
    })
    assert "git:github.com/rore/pallium" in cfg.policy.containers
    assert "path:xlm:2889e4f8fd37" in cfg.policy.containers
    pallium_dec = cfg.policy.containers["git:github.com/rore/pallium"]["decision"]
    assert pallium_dec.min_score == 19.0
    xlm_dec = cfg.policy.containers["path:xlm:2889e4f8fd37"]["decision"]
    assert xlm_dec.mode == "on_demand"
    assert xlm_dec.min_score is None


def test_build_injection_config_rejects_duplicate_container_ref() -> None:
    with pytest.raises(ValueError, match="Duplicate container_ref"):
        _build_injection_config({
            "injection": {
                "policy": {
                    "containers": [
                        {"container_ref": "git:repo", "types": {}},
                        {"container_ref": "git:repo", "types": {}},
                    ],
                },
            },
        })


def test_build_injection_config_rejects_invalid_mode() -> None:
    with pytest.raises(ValueError, match="Invalid injection policy mode"):
        _build_injection_config({
            "injection": {
                "policy": {
                    "types": {"decision": {"mode": "bogus"}},
                },
            },
        })


def test_build_injection_config_proactive_requires_min_score() -> None:
    with pytest.raises(ValueError, match="requires a numeric min_score"):
        _build_injection_config({
            "injection": {
                "policy": {
                    "types": {"decision": {"mode": "proactive"}},
                },
            },
        })


def test_build_injection_config_non_proactive_does_not_require_min_score() -> None:
    cfg = _build_injection_config({
        "injection": {
            "policy": {
                "types": {
                    "task_checkpoint": {"mode": "event"},
                    "investigation_outcome": {"mode": "on_demand"},
                    "fact_summary": {"mode": "suspended"},
                },
            },
        },
    })
    assert cfg.policy.types["task_checkpoint"].mode == "event"
    assert cfg.policy.types["task_checkpoint"].min_score is None
    assert cfg.policy.types["investigation_outcome"].mode == "on_demand"
    assert cfg.policy.types["fact_summary"].mode == "suspended"


def test_build_injection_config_rejects_empty_container_ref() -> None:
    with pytest.raises(ValueError, match="container_ref"):
        _build_injection_config({
            "injection": {
                "policy": {
                    "containers": [{"container_ref": "", "types": {}}],
                },
            },
        })


def test_build_injection_config_rejects_non_dict_policy() -> None:
    with pytest.raises(ValueError, match=r"\[injection\.policy\] must be a table"):
        _build_injection_config({"injection": {"policy": "not-a-table"}})


# ---------------------------------------------------------------------------
# InjectionPolicyConfig.effective
# ---------------------------------------------------------------------------


def test_effective_returns_none_when_empty() -> None:
    policy = InjectionPolicyConfig()
    assert policy.effective("decision", "any") is None


def test_effective_uses_global_when_no_container_override() -> None:
    decision_policy = InjectionTypePolicy(mode="proactive", min_score=22.0)
    policy = InjectionPolicyConfig(types={"decision": decision_policy})
    eff = policy.effective("decision", "git:repo")
    assert eff is decision_policy


def test_effective_container_override_wins() -> None:
    global_policy = InjectionTypePolicy(mode="proactive", min_score=22.0)
    container_policy = InjectionTypePolicy(mode="proactive", min_score=19.0)
    policy = InjectionPolicyConfig(
        types={"decision": global_policy},
        containers={"git:repo": {"decision": container_policy}},
    )
    eff = policy.effective("decision", "git:repo")
    assert eff is container_policy
    other = policy.effective("decision", "git:other")
    assert other is global_policy


def test_effective_container_override_falls_through_when_type_missing() -> None:
    global_policy = InjectionTypePolicy(mode="proactive", min_score=22.0)
    container_policy = InjectionTypePolicy(mode="proactive", min_score=19.0)
    policy = InjectionPolicyConfig(
        types={
            "decision": global_policy,
            "constraint_memory": InjectionTypePolicy(mode="proactive", min_score=20.0),
        },
        # Container override only defines `decision`. constraint_memory should fall
        # through to global.
        containers={"git:repo": {"decision": container_policy}},
    )
    assert policy.effective("decision", "git:repo") is container_policy
    assert policy.effective(
        "constraint_memory", "git:repo"
    ).min_score == 20.0  # fall-through


# ---------------------------------------------------------------------------
# _policy_allows_proactive_injection gate
# ---------------------------------------------------------------------------


def _make_candidate(
    *,
    memory_type: str = "decision",
    score: float = 22.0,
    memory_id: str = "m1",
) -> dict[str, object]:
    item = QueryResultItem(
        result_id=f"memory_object:{memory_id}",
        result_kind="memory_hit",
        score=score,
        evidence=[],
        memory_object_id=memory_id,
        type=memory_type,
    )
    return {"item": item}


def test_gate_noop_when_policy_is_none() -> None:
    cand = _make_candidate()
    assert _policy_allows_proactive_injection(cand, None, None) is True


def test_gate_noop_when_policy_is_empty() -> None:
    cand = _make_candidate()
    policy = InjectionPolicyConfig()
    assert _policy_allows_proactive_injection(cand, policy, None) is True


def test_gate_passes_through_types_not_in_policy() -> None:
    cand = _make_candidate(memory_type="thread_summary", score=5.0)
    policy = InjectionPolicyConfig(types={
        "decision": InjectionTypePolicy(mode="proactive", min_score=22.0),
    })
    assert _policy_allows_proactive_injection(cand, policy, None) is True


def test_gate_drops_below_threshold() -> None:
    cand = _make_candidate(memory_type="decision", score=21.99)
    policy = InjectionPolicyConfig(types={
        "decision": InjectionTypePolicy(mode="proactive", min_score=22.0),
    })
    assert _policy_allows_proactive_injection(cand, policy, None) is False


def test_gate_keeps_at_threshold() -> None:
    cand = _make_candidate(memory_type="decision", score=22.0)
    policy = InjectionPolicyConfig(types={
        "decision": InjectionTypePolicy(mode="proactive", min_score=22.0),
    })
    assert _policy_allows_proactive_injection(cand, policy, None) is True


def test_gate_keeps_above_threshold() -> None:
    cand = _make_candidate(memory_type="decision", score=23.0)
    policy = InjectionPolicyConfig(types={
        "decision": InjectionTypePolicy(mode="proactive", min_score=22.0),
    })
    assert _policy_allows_proactive_injection(cand, policy, None) is True


def test_gate_uses_item_score_not_routing_score() -> None:
    """Phase 3a load-bearing test: the gate reads item.score, NOT
    routing_score. Two candidates with identical routing_score but
    different item.score must be gated by item.score.
    """
    cand_above = _make_candidate(memory_type="decision", score=25.0,
                                  memory_id="m_above")
    cand_below = _make_candidate(memory_type="decision", score=15.0,
                                  memory_id="m_below")
    # Both rows have a hypothetical routing_score=100 — the gate must
    # ignore it because routing_score is not exposed on QueryResultItem.
    cand_above["routing_score"] = 100.0
    cand_below["routing_score"] = 100.0
    policy = InjectionPolicyConfig(types={
        "decision": InjectionTypePolicy(mode="proactive", min_score=20.0),
    })
    assert _policy_allows_proactive_injection(cand_above, policy, None) is True
    assert _policy_allows_proactive_injection(cand_below, policy, None) is False


@pytest.mark.parametrize("mode", ["event", "on_demand", "suspended"])
def test_gate_drops_non_proactive_modes(mode: str) -> None:
    cand = _make_candidate(memory_type="task_checkpoint", score=999.0)
    policy = InjectionPolicyConfig(types={
        "task_checkpoint": InjectionTypePolicy(mode=mode),
    })
    assert _policy_allows_proactive_injection(cand, policy, None) is False


def test_gate_container_override_wins() -> None:
    cand = _make_candidate(memory_type="decision", score=19.5)
    global_policy = InjectionTypePolicy(mode="proactive", min_score=22.0)
    container_policy = InjectionTypePolicy(mode="proactive", min_score=19.0)
    policy = InjectionPolicyConfig(
        types={"decision": global_policy},
        containers={"git:repo": {"decision": container_policy}},
    )
    qf_in_container = QueryFilters(container_ref="git:repo")
    qf_other_container = QueryFilters(container_ref="git:other")
    # In container: 19.5 >= 19.0 → kept.
    assert _policy_allows_proactive_injection(cand, policy, qf_in_container) is True
    # Outside container: 19.5 < 22.0 → dropped.
    assert _policy_allows_proactive_injection(cand, policy, qf_other_container) is False


def test_gate_handles_candidate_with_no_item_defensively() -> None:
    policy = InjectionPolicyConfig(types={
        "decision": InjectionTypePolicy(mode="proactive", min_score=22.0),
    })
    # Should not raise; default-allow when item is missing.
    assert _policy_allows_proactive_injection({}, policy, None) is True


def test_gate_handles_proactive_with_no_min_score_defensively() -> None:
    """The loader rejects this config, but the gate must default-allow if
    somehow constructed in code so we don't crash production.
    """
    policy = InjectionPolicyConfig(types={
        "decision": InjectionTypePolicy(mode="proactive", min_score=None),
    })
    cand = _make_candidate(memory_type="decision", score=10.0)
    assert _policy_allows_proactive_injection(cand, policy, None) is True


def test_audit_drop_reason_registered() -> None:
    """The new selection_drop_reason_code must be in the human-reasons map
    so audit attribution surfaces it.
    """
    assert "displaced_by_injection_policy" in _SELECTION_DROP_HUMAN_REASONS
    text = _SELECTION_DROP_HUMAN_REASONS["displaced_by_injection_policy"]
    assert "abstention" in text.lower() or "policy" in text.lower()
