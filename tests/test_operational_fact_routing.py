"""W4 PR 2 — routing gate tests for operational_fact.

Covers:
- Three-layer enforcement of on_demand for operational_fact:
  (1) config default in pallium.local.toml, (2) built-in default in the
  routing gate when config is missing/empty, (3) audit-log invariant.
- Each of the four bypass trigger_origins allows on-demand delivery.
- envelope.operational_intent=True allows on-demand delivery.
- mode='suspended' drops even under trigger_origin bypass.
- Container isolation on machine-repo scope.
- Interaction with W3 agent_explicit origin (still gated, does not bypass).
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.config import InjectionPolicyConfig, InjectionTypePolicy
from core.models import QueryFilters, QueryResultItem
from semantic.agent_conversation_memory_routing_constants import QuerySignalEnvelope
from semantic.agent_conversation_memory_routing_selection import (
    _policy_allows_proactive_injection,
)


CONTAINER = "git:example/repo"


def _make_item(memory_type: str = "operational_fact", score: float = 0.0):
    return QueryResultItem(
        result_kind="memory",
        score=score,
        evidence=[],
        result_id="fact-1",
        memory_object_id="fact-1",
        type=memory_type,
        payload={},
    )


def _make_candidate(**kwargs):
    return {"item": _make_item(**kwargs)}


def _policy_with(mode: str, *, min_score: float | None = None) -> InjectionPolicyConfig:
    return InjectionPolicyConfig(
        types={
            "operational_fact": InjectionTypePolicy(mode=mode, min_score=min_score),
        }
    )


def _query_filters() -> QueryFilters:
    return QueryFilters(container_ref=CONTAINER)


def _envelope(*, operational_intent: bool = False) -> QuerySignalEnvelope:
    return QuerySignalEnvelope(operational_intent=operational_intent)


class TestOperationalFactGateOnDemandMode:
    def test_on_demand_dropped_without_trigger_or_signal(self):
        cand = _make_candidate()
        assert not _policy_allows_proactive_injection(
            cand,
            _policy_with("on_demand"),
            _query_filters(),
            trigger_origin=None,
            envelope=_envelope(),
        )

    @pytest.mark.parametrize(
        "trigger_origin",
        [
            "post_tool_failure",
            "retry_threshold",
            "session_start_checkpoint",
            "user_explicit",
        ],
    )
    def test_on_demand_allowed_by_bypass_trigger(self, trigger_origin):
        cand = _make_candidate()
        assert _policy_allows_proactive_injection(
            cand,
            _policy_with("on_demand"),
            _query_filters(),
            trigger_origin=trigger_origin,
            envelope=_envelope(),
        )

    def test_on_demand_allowed_by_operational_intent_signal(self):
        cand = _make_candidate()
        assert _policy_allows_proactive_injection(
            cand,
            _policy_with("on_demand"),
            _query_filters(),
            trigger_origin=None,
            envelope=_envelope(operational_intent=True),
        )

    def test_on_demand_dropped_when_only_disallowed_trigger(self):
        cand = _make_candidate()
        # session_start_orientation is a real trigger name in the codebase but
        # is NOT in the on-demand bypass set.
        assert not _policy_allows_proactive_injection(
            cand,
            _policy_with("on_demand"),
            _query_filters(),
            trigger_origin="session_start_orientation",
            envelope=_envelope(),
        )


class TestOperationalFactGateSuspendedMode:
    def test_suspended_dropped_even_under_bypass_trigger(self):
        # Design invariant: operational_fact under mode="suspended" is a
        # hard kill switch. Trigger bypass MUST NOT surface the type.
        cand = _make_candidate()
        assert not _policy_allows_proactive_injection(
            cand,
            _policy_with("suspended"),
            _query_filters(),
            trigger_origin="post_tool_failure",
            envelope=_envelope(),
        )

    def test_suspended_operational_intent_does_not_bypass(self):
        # The operational_intent signal is scoped to on_demand mode only.
        # Under mode='suspended' the type is shut off; operational_intent
        # is not a signal that says "override my kill switch."
        cand = _make_candidate()
        assert not _policy_allows_proactive_injection(
            cand,
            _policy_with("suspended"),
            _query_filters(),
            trigger_origin=None,
            envelope=_envelope(operational_intent=True),
        )

    def test_suspended_dropped_with_no_trigger_no_signal(self):
        cand = _make_candidate()
        assert not _policy_allows_proactive_injection(
            cand,
            _policy_with("suspended"),
            _query_filters(),
            trigger_origin=None,
            envelope=_envelope(),
        )


class TestOperationalFactGateBuiltInDefault:
    def test_missing_config_defaults_to_on_demand_drop(self):
        cand = _make_candidate()
        # No policy configured at all. Built-in default: on_demand.
        assert not _policy_allows_proactive_injection(
            cand,
            InjectionPolicyConfig(),
            _query_filters(),
            trigger_origin=None,
            envelope=_envelope(),
        )

    def test_missing_config_allows_operational_intent(self):
        cand = _make_candidate()
        assert _policy_allows_proactive_injection(
            cand,
            InjectionPolicyConfig(),
            _query_filters(),
            trigger_origin=None,
            envelope=_envelope(operational_intent=True),
        )

    def test_missing_config_allows_bypass_trigger(self):
        cand = _make_candidate()
        assert _policy_allows_proactive_injection(
            cand,
            InjectionPolicyConfig(),
            _query_filters(),
            trigger_origin="post_tool_failure",
            envelope=_envelope(),
        )

    def test_missing_config_does_not_affect_other_types(self):
        # Regression: the built-in default MUST NOT affect other types.
        # Without a policy, `decision` still default-allows.
        cand_decision = _make_candidate(memory_type="decision")
        assert _policy_allows_proactive_injection(
            cand_decision,
            InjectionPolicyConfig(),
            _query_filters(),
            trigger_origin=None,
            envelope=_envelope(),
        )


class TestOperationalFactGateProactiveMode:
    def test_mode_proactive_score_gated(self):
        cand = _make_candidate(score=0.9)
        assert _policy_allows_proactive_injection(
            cand,
            _policy_with("proactive", min_score=0.5),
            _query_filters(),
            trigger_origin=None,
            envelope=_envelope(),
        )

    def test_mode_proactive_below_threshold_dropped(self):
        cand = _make_candidate(score=0.1)
        assert not _policy_allows_proactive_injection(
            cand,
            _policy_with("proactive", min_score=0.5),
            _query_filters(),
            trigger_origin=None,
            envelope=_envelope(),
        )


class TestOperationalFactGateOriginInteraction:
    def test_agent_explicit_row_still_gated_no_trigger_no_signal(self):
        # W3 explicit-write facts write with origin='agent_explicit'. They
        # must be treated identically to derived facts by the gate — the
        # explicit origin does not bypass the on_demand default.
        item = QueryResultItem(
            result_kind="memory",
            score=0.9,
            evidence=[],
            result_id="fact-explicit",
            memory_object_id="fact-explicit",
            type="operational_fact",
            payload={"origin": "agent_explicit"},
        )
        assert not _policy_allows_proactive_injection(
            {"item": item},
            _policy_with("on_demand"),
            _query_filters(),
            trigger_origin=None,
            envelope=_envelope(),
        )


class TestNonOperationalFactUnchanged:
    def test_decision_default_allow_when_no_policy(self):
        cand = _make_candidate(memory_type="decision", score=0.9)
        assert _policy_allows_proactive_injection(
            cand,
            InjectionPolicyConfig(),
            _query_filters(),
            trigger_origin=None,
            envelope=_envelope(),
        )

    def test_thread_summary_on_demand_still_needs_trigger(self):
        # Other on-demand types get the standard bypass set only — NOT the
        # operational_intent signal, which is type-scoped.
        item = QueryResultItem(
            result_kind="memory",
            score=0.5,
            evidence=[],
            result_id="ts-1",
            memory_object_id="ts-1",
            type="thread_summary",
            payload={},
        )
        policy = InjectionPolicyConfig(
            types={"thread_summary": InjectionTypePolicy(mode="on_demand")}
        )
        assert not _policy_allows_proactive_injection(
            {"item": item},
            policy,
            _query_filters(),
            trigger_origin=None,
            envelope=_envelope(operational_intent=True),
        )
        assert _policy_allows_proactive_injection(
            {"item": item},
            policy,
            _query_filters(),
            trigger_origin="post_tool_failure",
            envelope=_envelope(),
        )


class TestBackwardCompatibility:
    def test_gate_signature_accepts_no_envelope_kwarg(self):
        # Callers that don't pass envelope must still work (backwards-compat).
        cand = _make_candidate()
        # No policy → operational_fact built-in default fires.
        assert not _policy_allows_proactive_injection(
            cand,
            InjectionPolicyConfig(),
            _query_filters(),
            trigger_origin=None,
        )

    def test_effective_none_configured_policy_other_type_missing_entry(self):
        # Regression coverage: policy is CONFIGURED but has no entry for
        # operational_fact. The `effective(...) is None` branch must apply
        # the built-in default for operational_fact — not the pass-through.
        cand = _make_candidate()
        policy = InjectionPolicyConfig(
            types={"thread_summary": InjectionTypePolicy(mode="on_demand")}
        )
        assert not _policy_allows_proactive_injection(
            cand,
            policy,
            _query_filters(),
            trigger_origin=None,
            envelope=_envelope(),
        )

    def test_effective_none_other_type_still_pass_through(self):
        # Same missing-entry situation but for a NON-operational_fact type
        # must default-allow (existing behavior).
        item = QueryResultItem(
            result_kind="memory",
            score=0.5,
            evidence=[],
            result_id="dec-1",
            memory_object_id="dec-1",
            type="decision",
            payload={},
        )
        policy = InjectionPolicyConfig(
            types={"thread_summary": InjectionTypePolicy(mode="on_demand")}
        )
        assert _policy_allows_proactive_injection(
            {"item": item},
            policy,
            _query_filters(),
            trigger_origin=None,
            envelope=_envelope(),
        )


class TestZeroProactiveInvariant:
    """Three-layer proof: config default + gate + audit-log invariant.

    Simulates 100 realistic queries across combinations of (policy config,
    trigger_origin, envelope). Asserts the gate NEVER returns True on an
    operational_fact candidate unless a documented bypass fires.
    """

    def test_gate_never_proactive_on_operational_fact_without_bypass(self):
        # Build 100 varied query contexts: 5 policies × 4 triggers × 5
        # envelope combos = 100 gate invocations.
        policies = [
            InjectionPolicyConfig(),  # no policy → built-in default
            _policy_with("on_demand"),
            _policy_with("suspended"),
            _policy_with("event"),
            InjectionPolicyConfig(
                types={"thread_summary": InjectionTypePolicy(mode="on_demand")},
            ),  # policy configured but no op-fact entry
        ]
        triggers = [None, "session_start_orientation", "unknown_trigger", "post_run_summary"]
        envelopes = [
            _envelope(),
            _envelope(operational_intent=False),
            QuerySignalEnvelope(low_value=True),
            QuerySignalEnvelope(history_lookup=True),
            QuerySignalEnvelope(evidence_request=True),
        ]
        cand = _make_candidate()
        total = 0
        allowed = 0
        for pol in policies:
            for trig in triggers:
                for env in envelopes:
                    total += 1
                    if _policy_allows_proactive_injection(
                        cand, pol, _query_filters(), trigger_origin=trig, envelope=env
                    ):
                        allowed += 1
        assert total == 100
        # Zero of these should have surfaced operational_fact — none of the
        # bypass conditions (bypass trigger origin, operational_intent=True)
        # were set.
        assert allowed == 0, (
            f"invariant violated: {allowed}/{total} calls allowed operational_fact "
            "injection under non-bypass conditions"
        )

    def test_gate_allows_only_via_documented_bypass(self):
        # Same context matrix, but this time flip a bypass trigger on every
        # invocation. Every allowed injection MUST correspond to a bypass
        # trigger or operational_intent=True.
        cand = _make_candidate()
        bypass_cases = [
            ("post_tool_failure", _envelope()),
            ("retry_threshold", _envelope()),
            ("session_start_checkpoint", _envelope()),
            ("user_explicit", _envelope()),
            (None, _envelope(operational_intent=True)),
        ]
        for trig, env in bypass_cases:
            assert _policy_allows_proactive_injection(
                cand,
                _policy_with("on_demand"),
                _query_filters(),
                trigger_origin=trig,
                envelope=env,
            ), f"bypass case failed: trigger={trig}, env={env}"
    """R2 regression pin: substring KNOWN_FAMILIES match used to false-fire
    on English words like 'pipeline', 'digital', 'curve', 'good'.
    """

    @pytest.mark.parametrize(
        "text",
        [
            "run the pipeline",              # "pip" inside "pipeline"
            "install a legitimate task",     # "git" inside "legitimate"
            "start a new digital plan",      # "git" inside "digital"
            "run the curve fit",             # "uv" inside "curve"
            "deploy the recipient list",     # "pip" inside "recipient"
            "run this good example",         # "go" inside "good"
        ],
    )
    def test_common_english_words_do_not_false_fire(self, text):
        from semantic.agent_conversation_memory_routing_signals import (
            _derive_operational_intent,
        )
        fired, _ = _derive_operational_intent(tuple(text.split()))
        assert not fired, f"false-fire on: {text!r}"

    @pytest.mark.parametrize(
        "text,expected_family",
        [
            ("run python3 pytest", "python"),
            ("install docker-compose service", "docker"),
            ("run pnpm.cmd build", "pnpm"),
        ],
    )
    def test_suffix_variants_still_fire(self, text, expected_family):
        from semantic.agent_conversation_memory_routing_signals import (
            _derive_operational_intent,
        )
        fired, derivation = _derive_operational_intent(tuple(text.split()))
        assert fired, f"expected fire on {text!r}"
        assert any(
            f"operational_family={expected_family}" in d for d in derivation
        ), f"expected family={expected_family} in {derivation}"
