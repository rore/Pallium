from __future__ import annotations

from semantic.agent_conversation_memory_resolver import (
    FALLBACK_RESULT,
    ResolverPacket,
    ResolverResult,
    build_resolver_packet,
    resolve_query_ambiguity,
)
from semantic.agent_conversation_memory_resolver_prompts import (
    DEFAULT_QAR_VARIANT,
    QAR_VARIANTS,
    get_qar_variant_text,
    list_qar_variants,
)


def _make_test_packet() -> ResolverPacket:
    return ResolverPacket(
        normalized_query_text="What's the latest on the deploy?",
        turn_kind="resumed_session",
        ambiguity_pair_type="latest_status_vs_resume_work",
        option_a_summary={"option_id": "A", "query_policy_family": "resume_work"},
        option_b_summary={"option_id": "B", "query_policy_family": "latest_status"},
        candidate_cards=[],
    )


def test_fallback_result_is_not_valid_selection() -> None:
    assert not FALLBACK_RESULT.is_valid_selection
    assert FALLBACK_RESULT.action == "FALLBACK"
    assert FALLBACK_RESULT.confidence == "low"


def test_valid_select_result() -> None:
    result = ResolverResult(
        action="SELECT", selected_option_id="A", confidence="high", reason_codes=("test",)
    )
    assert result.is_valid_selection


def test_low_confidence_is_not_valid() -> None:
    result = ResolverResult(
        action="SELECT", selected_option_id="A", confidence="low", reason_codes=("test",)
    )
    assert not result.is_valid_selection


def test_invalid_option_id_is_not_valid() -> None:
    result = ResolverResult(
        action="SELECT", selected_option_id="C", confidence="high", reason_codes=("test",)
    )
    assert not result.is_valid_selection


def test_resolve_query_ambiguity_stub_returns_fallback() -> None:
    # Phase 4 stub: always returns FALLBACK
    result = resolve_query_ambiguity(
        provider=None,
        model=None,
        prompt_variant=DEFAULT_QAR_VARIANT,
        resolver_packet=_make_test_packet(),
        timeout_ms=800,
    )
    assert result.action == "FALLBACK"
    assert result.latency_ms >= 0


def test_resolver_enabled_false_skips_invocation() -> None:
    # When resolver_enabled=false, the router should skip invocation.
    # This test verifies the resolver itself always returns FALLBACK in the stub.
    result = resolve_query_ambiguity(
        provider=None,
        model=None,
        prompt_variant=DEFAULT_QAR_VARIANT,
        resolver_packet=_make_test_packet(),
    )
    assert result.action == "FALLBACK"


def test_build_resolver_packet_structure() -> None:
    candidates = [
        {"result_id": "r1", "layer": "task_checkpoint", "memory_type": "task_checkpoint", "support_score": 80, "summary": "checkpoint A"},
        {"result_id": "r2", "layer": "continuity_memory", "memory_type": "continuity_memory", "support_score": 60, "summary": "continuity B"},
        {"result_id": "r3", "layer": "source_evidence", "memory_type": "source_hit", "support_score": 40, "summary": "source C"},
    ]
    option_a = {"query_policy_family": "resume_work", "allowed_query_intents": ["work_resumption"], "score": 50}
    option_b = {"query_policy_family": "latest_status", "allowed_query_intents": ["broad_recall"], "score": 45}

    packet = build_resolver_packet(
        query_text="What's the latest?",
        turn_kind="resumed_session",
        ambiguity_pair_type="latest_status_vs_resume_work",
        option_a=option_a,
        option_b=option_b,
        candidates=candidates,
    )

    assert packet.ambiguity_pair_type == "latest_status_vs_resume_work"
    assert len(packet.candidate_cards) <= 3
    assert len(packet.candidate_cards) >= 2
    assert packet.option_a_summary["option_id"] == "A"
    assert packet.option_b_summary["option_id"] == "B"


def test_build_resolver_packet_deduplicates_cards() -> None:
    candidates = [
        {"result_id": "r1", "layer": "task_checkpoint", "memory_type": "task_checkpoint", "support_score": 80, "summary": "only one"},
    ]
    option_a = {"query_policy_family": "resume_work"}
    option_b = {"query_policy_family": "latest_status"}

    packet = build_resolver_packet(
        query_text="What's the latest?",
        turn_kind=None,
        ambiguity_pair_type="latest_status_vs_resume_work",
        option_a=option_a,
        option_b=option_b,
        candidates=candidates,
    )

    # Only 1 candidate, so dedup means only 1 card
    assert len(packet.candidate_cards) == 1


def test_qar_variants_exist() -> None:
    variants = list_qar_variants()
    assert "qar_v1_compact_contract" in variants
    assert "qar_v1_compact_reasons" in variants
    assert "qar_v1_compact_examples" in variants
    assert len(variants) == 3


def test_qar_variant_text_retrieval() -> None:
    text = get_qar_variant_text("qar_v1_compact_contract")
    assert "FALLBACK" in text
    assert "SELECT" in text


def test_qar_variant_unknown_raises() -> None:
    try:
        get_qar_variant_text("nonexistent_variant")
        raise AssertionError("Should have raised ValueError")
    except ValueError:
        pass
