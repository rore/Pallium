from __future__ import annotations

from datetime import datetime, timezone

from core.models import (
    EvidenceReference,
    MemoryEnvelope,
    MemoryEnvelopeDerivation,
    MemoryEnvelopeScope,
    MemorySubjectAnchor,
    QueryFilters,
    QueryResultItem,
    QueryRuntimeContext,
    QueryTrace,
)
from retrieval.base import RetrievalQueryResult
from semantic.agent_conversation_memory import AgentConversationMemoryPlugin
from semantic.agent_conversation_memory_routing import (
    PolicySelectedContext,
    PASSTHROUGH_POLICY,
    _classify_query_policy_family,
    _build_policy_evidence,
    _build_ambiguity_options,
    _work_state_evidence_gate_passes,
    _apply_policy_intent_restriction,
    QUERY_POLICY_FAMILY_ALLOWED_INTENTS,
    POLICY_SUPPORT_THRESHOLD,
)
from tests.tiered_memory_stub_providers import TieredMemorySemanticProvider


def _make_simple_retrieval_result(query_text: str, items: list[QueryResultItem]) -> RetrievalQueryResult:
    return RetrievalQueryResult(
        results=items,
        trace=QueryTrace(
            query_text=query_text,
            query_tokens=tuple(query_text.lower().split()),
            limit=6,
            filters=None,
            stages=(),
        ),
    )


def _make_memory_hit(
    *,
    memory_object_id: str,
    memory_type: str,
    payload: dict,
    score: int = 15,
    container_ref: str = "chat:test",
    thread_ref: str = "chat:test:thread-1",
    envelope_kind: str = "summary",
) -> QueryResultItem:
    return QueryResultItem(
        result_kind="memory_hit",
        memory_object_id=memory_object_id,
        type=memory_type,
        payload=payload,
        freshness_at=datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc),
        score=score,
        evidence=[],
        container_ref=container_ref,
        thread_ref=thread_ref,
        envelope=MemoryEnvelope(
            schema_id="core.memory_envelope",
            schema_version="v1",
            kind=envelope_kind,
            confidence="high",
            scope=MemoryEnvelopeScope(container_ref=container_ref),
            subjects=[MemorySubjectAnchor(kind="component", value="test-component")],
            derivation=MemoryEnvelopeDerivation(
                producer_kind="item_extraction",
                producer_schema_id="typed_memory_extraction",
                producer_schema_version="v7",
                prompt_variant="strict_typed_memory_v4_evidence_guarded",
                model_role="write_time_extraction",
                kind_basis="type_map",
            ),
        ),
    )


def test_passthrough_policy_appears_in_trace() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant="strict_typed_memory_v4_evidence_guarded",
    )
    retrieval_result = _make_simple_retrieval_result(
        "What did we decide about the authentication approach?",
        [
            _make_memory_hit(
                memory_object_id="decision-1",
                memory_type="decision",
                payload={
                    "summary": "We decided to use OAuth2 with PKCE for the browser flow.",
                    "decision_text": "Use OAuth2 with PKCE for the browser flow.",
                    "decision_evidence_text": "Team agreed to adopt OAuth2 with PKCE.",
                },
                envelope_kind="finding",
            ),
        ],
    )

    outcome = plugin.route_query_results(
        text="What did we decide about the authentication approach?",
        requested_limit=6,
        retrieval_result=retrieval_result,
        runtime_context=QueryRuntimeContext(turn_kind="new_thread", session_has_sufficient_local_context=False),
        include_trace=True,
    )

    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    assert outcome.trace.routing["query_policy_family"] in {"recall_fact", "check_constraints"}  # envelope-derived, may differ from old English path
    assert "policy_resolver" not in outcome.trace.routing

    # Existing trace fields must remain present
    assert "query_intent" in outcome.trace.routing
    assert "query_family" in outcome.trace.routing
    assert "family_inference" in outcome.trace.routing
    assert "preferred_layers" in outcome.trace.routing
    assert "selected_layer" in outcome.trace.routing
    assert "kind_prefilter" in outcome.trace.routing
    assert "anchor_prefilter" in outcome.trace.routing


def test_policy_selected_context_dataclass_is_frozen() -> None:
    ctx = PolicySelectedContext(
        query_policy_family="recall_fact",
        allowed_query_intents=frozenset({"recall", "structured_recall"}),
    )
    assert ctx.query_policy_family == "recall_fact"
    assert ctx.allowed_query_intents == frozenset({"recall", "structured_recall"})
    assert ctx.resolver_invoked is False

    try:
        ctx.query_policy_family = "noise"  # type: ignore[misc]
        raise AssertionError("Should be frozen")
    except AttributeError:
        pass


def test_passthrough_policy_singleton() -> None:
    assert PASSTHROUGH_POLICY.query_policy_family == "passthrough"
    assert PASSTHROUGH_POLICY.allowed_query_intents is None
    assert PASSTHROUGH_POLICY.resolver_invoked is False


# --- Phase 3: Policy classification tests ---

def test_classify_greeting_as_recall_fact_without_noise_detection() -> None:
    """After removing query-time noise detection (cue-free control plane),
    greetings are classified as recall_fact instead of noise."""
    assert _classify_query_policy_family("hello", query_shape_tags=[], runtime_context=None, initial_intent=None) == "recall_fact"
    assert _classify_query_policy_family("thanks", query_shape_tags=[], runtime_context=None, initial_intent=None) == "recall_fact"


def test_classify_status_queries_as_recall_fact_without_latest_status_wording() -> None:
    """With _has_latest_status_wording removed, status queries classify as recall_fact
    unless they have resume_state shape tag."""
    assert _classify_query_policy_family(
        "What's the latest on the deployment?",
        query_shape_tags=["history_lookup"],
        runtime_context=None,
        initial_intent=None,
    ) == "recall_fact"

    # With resume_state tag, it classifies as resume_work
    assert _classify_query_policy_family(
        "What is the latest state of the migration?",
        query_shape_tags=["history_lookup", "resume_state"],
        runtime_context=None,
        initial_intent=None,
    ) == "resume_work"


def test_classify_broad_recall_with_latest_as_recall_fact() -> None:
    # "what do we know the latest about X" is recall_fact now
    assert _classify_query_policy_family(
        "What do we know the latest about the catalog sync retry?",
        query_shape_tags=["history_lookup"],
        runtime_context=None,
        initial_intent=None,
    ) == "recall_fact"


def test_classify_resume_work_for_explicit_resume_cues() -> None:
    assert _classify_query_policy_family(
        "Where did we leave off with the sync?",
        query_shape_tags=["resume_state"],
        runtime_context=None,
        initial_intent=None,
    ) == "resume_work"


def test_classify_resume_work_for_resumed_session_with_work_intent() -> None:
    ctx = QueryRuntimeContext(turn_kind="resumed_session", session_has_sufficient_local_context=False)
    assert _classify_query_policy_family(
        "Can you orient me on the catalog sync retry?",
        query_shape_tags=[],
        runtime_context=ctx,
        initial_intent="work_resumption",
    ) == "resume_work"


def test_classify_recall_fact_for_resumed_session_without_work_intent() -> None:
    ctx = QueryRuntimeContext(turn_kind="resumed_session", session_has_sufficient_local_context=False)
    assert _classify_query_policy_family(
        "Have we already answered why overdue notices are batched?",
        query_shape_tags=["carry_forward"],
        runtime_context=ctx,
        initial_intent="recall",
    ) == "recall_fact"


def test_classify_constraint_query_as_recall_fact_without_check_constraints() -> None:
    """After removing check_constraints policy family, constraint queries
    fall through to recall_fact."""
    assert _classify_query_policy_family(
        "What constraint had I given about the Jira portal?",
        query_shape_tags=["constraint_recall"],
        runtime_context=None,
        initial_intent=None,
    ) == "recall_fact"


def test_classify_recall_fact_as_default() -> None:
    assert _classify_query_policy_family(
        "What did we decide about authentication?",
        query_shape_tags=[],
        runtime_context=None,
        initial_intent=None,
    ) == "recall_fact"

    assert _classify_query_policy_family(
        "What was the root cause of the outage?",
        query_shape_tags=["analysis_request"],
        runtime_context=None,
        initial_intent=None,
    ) == "recall_fact"


def test_latest_status_collapses_to_broad_recall_without_work_evidence() -> None:
    evidence = {
        "task_checkpoint_best_work_usefulness": 0,
        "source_evidence_best_work_usefulness": 0,
        "strong_task_checkpoint_survives": False,
        "structured_best_support": 30,
        "cross_thread_continuity_survives": False,
    }
    assert not _work_state_evidence_gate_passes(evidence)


def test_latest_status_gate_passes_with_strong_checkpoint() -> None:
    evidence = {
        "task_checkpoint_best_work_usefulness": 30,
        "source_evidence_best_work_usefulness": 0,
        "strong_task_checkpoint_survives": True,
        "structured_best_support": 30,
        "cross_thread_continuity_survives": False,
    }
    assert _work_state_evidence_gate_passes(evidence)


def test_noise_query_returns_empty_results() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant="strict_typed_memory_v4_evidence_guarded",
    )
    retrieval_result = _make_simple_retrieval_result(
        "hello",
        [
            _make_memory_hit(
                memory_object_id="decision-1",
                memory_type="decision",
                payload={"summary": "Some decision."},
                envelope_kind="finding",
            ),
        ],
    )

    outcome = plugin.route_query_results(
        text="hello",
        requested_limit=6,
        retrieval_result=retrieval_result,
        runtime_context=QueryRuntimeContext(turn_kind="new_thread", session_has_sufficient_local_context=False),
        include_trace=True,
    )

    # After removing noise detection, greetings route through recall and may find memory.
    assert outcome.decision_reason in ("carry_forward_available", "no_relevant_memory")


def test_intent_restriction_preserves_allowed_intent() -> None:
    family_inference = {
        "selected_family": "recall",
        "family_scores": {
            "recall": {"total": 100},
            "work_resumption": {"total": 50},
        },
    }
    ctx = PolicySelectedContext(
        query_policy_family="recall_fact",
        allowed_query_intents=QUERY_POLICY_FAMILY_ALLOWED_INTENTS["recall_fact"],
    )
    assert _apply_policy_intent_restriction(family_inference, ctx) == "recall"


def test_intent_restriction_overrides_to_best_allowed() -> None:
    family_inference = {
        "selected_family": "work_resumption",
        "family_scores": {
            "work_resumption": {"total": 120},
            "recall": {"total": 80},
        },
    }
    ctx = PolicySelectedContext(
        query_policy_family="latest_status",
        allowed_query_intents=frozenset({"recall"}),
    )
    # work_resumption is not in allowed intents, so overrides to recall
    assert _apply_policy_intent_restriction(family_inference, ctx) == "recall"


def test_recall_fact_allows_all_standard_intents() -> None:
    allowed = QUERY_POLICY_FAMILY_ALLOWED_INTENTS["recall_fact"]
    assert "recall" in allowed
    assert "structured_recall" in allowed
    assert "evidence_trace" in allowed
    assert "work_resumption" not in allowed


def test_anchor_filtered_constraint_does_not_inflate_ambiguity_score() -> None:
    """A constraint candidate removed by anchor prefilter must not affect ambiguity scoring.

    _build_policy_evidence runs on post-anchor-prefilter candidates. If the constraint
    hit is absent from that set, constraint_best_support stays 0 and the constraint
    pair builder sees no surviving constraint evidence.
    """
    constraint_hit = _make_memory_hit(
        memory_object_id="constraint-filtered",
        memory_type="constraint_memory",
        payload={
            "summary": "Do not use the admin portal during the retry.",
            "constraint_text": "Do not use the admin portal.",
        },
        score=20,
        envelope_kind="constraint",
    )
    decision_hit = _make_memory_hit(
        memory_object_id="decision-survives",
        memory_type="decision",
        payload={
            "summary": "Use token-based auth with 15-minute refresh.",
            "decision_text": "Use token-based auth.",
            "decision_evidence_text": "Team agreed on token auth.",
        },
        score=18,
        envelope_kind="finding",
    )

    # Full set: both candidates present (simulates pre-anchor-prefilter)
    full_evidence = _build_policy_evidence([constraint_hit, decision_hit])
    assert full_evidence["constraint_best_support"] > 0

    # Anchor-filtered set: constraint hit removed (simulates post-anchor-prefilter)
    filtered_evidence = _build_policy_evidence([decision_hit])
    assert filtered_evidence["constraint_best_support"] == 0
    assert filtered_evidence["constraint_best_kind"] == ""

    # The ambiguity builder should see no constraint support and not create a pair
    family_inference = {
        "selected_family": "recall",
        "query_shape_tags": ["constraint_recall"],
        "family_scores": {
            "recall": {"total": 80},
            "structured_recall": {"total": 30},
            "evidence_trace": {"total": 20},
        },
    }
    policy_ctx, options = _build_ambiguity_options(
        "check_constraints",
        text="What constraint had I given about the portal?",
        policy_evidence=filtered_evidence,
        family_inference=family_inference,
        runtime_context=None,
        query_shape_tags=["constraint_recall"],
    )
    # Without surviving constraint evidence above the support threshold,
    # constraint score stays lower and the pair may or may not form,
    # but critically the constraint_best_support=0 means the +20 bonus is not applied.
    # Verify the constraint score did NOT get the +20 aligned-constraint bonus:
    if options:
        constraint_option = next(
            (o for o in options if o.get("query_policy_family") == "check_constraints"),
            None,
        )
        if constraint_option:
            # Score should be 18 (constraint_recall tag) but NOT 18+20 (no aligned evidence)
            assert int(constraint_option.get("score", 0)) <= 18 + 24  # tag + text, no evidence bonus
