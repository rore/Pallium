from __future__ import annotations

from datetime import datetime, timezone

from core.models import (
    EvidenceReference,
    QueryFilters,
    QueryResultItem,
    QueryRuntimeContext,
    QueryTrace,
)
from retrieval.base import RetrievalQueryResult
from semantic.agent_conversation_memory import AgentConversationMemoryPlugin
from semantic.agent_conversation_memory_routing import (
    CONSTRAINT_MEMORY_TYPE,
    LaneEligibility,
    LaneNarrowingResult,
    _determine_eligible_lanes,
    _build_policy_evidence,
    _compute_typed_candidate_evidence,
    _derive_query_signal_envelope,
    _work_state_evidence_gate_passes,
    _infer_query_intent,
    _routing_query_tokens,
)
from tests.agent_conversation_memory_routing_helpers import (
    _inventory_batch_typed_constraint_result,
    _memory_envelope,
)
from tests.tiered_memory_stub_providers import TieredMemorySemanticProvider


def _make_retrieval_result(results, query_text, query_filters=None):
    return RetrievalQueryResult(
        results=results,
        trace=QueryTrace(
            query_text=query_text,
            query_tokens=tuple(query_text.lower().split()),
            limit=4,
            filters=query_filters,
            stages=(),
        ),
    )


def _make_source_hit(source_id='source-evidence-1', score=18, excerpt='Prior finding about the library migration.'):
    return QueryResultItem(
        result_kind='source_hit',
        source_item_id=f'si-{source_id}',
        source_type='chat_message',
        source_id=source_id,
        excerpt=excerpt,
        occurred_at=datetime(2026, 3, 11, 10, 0, tzinfo=timezone.utc),
        container_ref='chat:test',
        thread_ref='chat:test:thread-1',
        artifact_kind='message',
        score=score,
        evidence=[
            EvidenceReference(
                source_item_id=f'si-{source_id}',
                source_type='chat_message',
                source_id=source_id,
                occurred_at=datetime(2026, 3, 11, 10, 0, tzinfo=timezone.utc),
                container_ref='chat:test',
                thread_ref='chat:test:thread-1',
                artifact_kind='message',
            )
        ],
    )


_CONSTRAINT_EVIDENCE = [
    EvidenceReference(
        source_item_id='si-constraint-source',
        source_type='chat_message',
        source_id='constraint-source',
        occurred_at=datetime(2026, 3, 11, 10, 0, tzinfo=timezone.utc),
        container_ref='chat:test',
        thread_ref='chat:test:thread-1',
        artifact_kind='message',
    ),
]


def _make_strong_constraint(score=20):
    base = _inventory_batch_typed_constraint_result(score=score)
    return QueryResultItem(
        result_kind=base.result_kind,
        memory_object_id=base.memory_object_id,
        type=base.type,
        payload=base.payload,
        freshness_at=base.freshness_at,
        score=base.score,
        evidence=_CONSTRAINT_EVIDENCE,
        container_ref=base.container_ref,
        thread_ref=base.thread_ref,
        envelope=base.envelope,
    )


def _make_task_checkpoint(
    memory_object_id='checkpoint-1',
    score=15,
    *,
    blocker_state='',
    next_step='Continue the migration.',
    task='Resume the library migration.',
):
    payload = {
        'summary': 'Library migration in progress.',
        'task': task,
        'current_state': 'Working on batch 5.',
        'next_step': next_step,
        'evidence': ['Prior batch completed.'],
        'freshness_signal': 'Latest explicit update at 2026-03-11T10:02:00Z.',
    }
    if blocker_state:
        payload['blocker_state'] = blocker_state
    return QueryResultItem(
        result_kind='memory_hit',
        memory_object_id=memory_object_id,
        type='task_checkpoint',
        payload=payload,
        freshness_at=datetime(2026, 3, 11, 10, 2, tzinfo=timezone.utc),
        score=score,
        evidence=[],
        container_ref='chat:test',
        thread_ref='chat:test:thread-1',
    )


def _make_pattern_memory(memory_object_id='pattern-1', score=16):
    return QueryResultItem(
        result_kind='memory_hit',
        memory_object_id=memory_object_id,
        type='pattern_memory',
        payload={
            'summary': 'The library migration follows a batch-by-batch approach.',
            'pattern_label': 'batch migration approach',
        },
        freshness_at=datetime(2026, 3, 11, 10, 1, tzinfo=timezone.utc),
        score=score,
        evidence=[],
        container_ref='chat:test',
        thread_ref='chat:test:thread-1',
        envelope=_memory_envelope('summary'),
    )


def _build_lane_result(text, candidates, runtime_context=None):
    query_tokens = _routing_query_tokens(text)
    policy_evidence = _build_policy_evidence(candidates)
    candidate_evidence = _compute_typed_candidate_evidence(
        candidates, QueryFilters(container_ref='chat:test', thread_ref='chat:test:thread-1'),
    )
    signal_envelope = _derive_query_signal_envelope(
        text=text, query_tokens=query_tokens,
        policy_evidence=policy_evidence,
        candidate_evidence=candidate_evidence,
        anchor_prefiltered_candidates=candidates,
        runtime_context=runtime_context,
    )
    # Derive shape tags from signal envelope (matches main route_query_results flow)
    envelope_shape_tags: list[str] = []
    if signal_envelope.resume_state:
        envelope_shape_tags.append("resume_state")
    if signal_envelope.evidence_request:
        envelope_shape_tags.append("evidence_request")
    family_inference = _infer_query_intent(
        text=text,
        query_tokens=query_tokens,
        retrieved_candidates=candidates,
        query_filters=QueryFilters(container_ref='chat:test'),
        runtime_context=runtime_context,
    )
    return _determine_eligible_lanes(
        text=text,
        query_shape_tags=envelope_shape_tags,
        policy_evidence=policy_evidence,
        anchor_prefiltered_candidates=candidates,
        family_inference=family_inference,
        runtime_context=runtime_context,
    )


def _route_full(text, candidates, runtime_context=None, query_filters=None, include_trace=True):
    qf = query_filters or QueryFilters(container_ref='chat:test', thread_ref='chat:test:thread-1')
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    retrieval_result = _make_retrieval_result(candidates, text, qf)
    return plugin.route_query_results(
        text=text,
        requested_limit=4,
        retrieval_result=retrieval_result,
        query_filters=qf,
        runtime_context=runtime_context,
        include_trace=include_trace,
    )


# ---------------------------------------------------------------------------
# Single-lane bypass tests
# ---------------------------------------------------------------------------

def test_work_resumption_lane_bypass_on_resumed_session():
    checkpoint = _make_task_checkpoint(blocker_state='Auth token expired.')
    text = 'Where were we?'
    runtime = QueryRuntimeContext(turn_kind='resumed_session')
    result = _build_lane_result(text, [checkpoint], runtime_context=runtime)
    assert result.selection_mode == 'single_lane_bypass'
    assert result.selected_lane == 'work_resumption'
    assert result.mapped_intent == 'work_resumption'
    assert result.lane_narrowing_used_intent is False


def test_work_resumption_plausible_without_resume_session_or_tag():
    """Without resumed_session context or resume_state tag in envelope,
    work_resumption is only plausible even with strong checkpoint evidence."""
    checkpoint = _make_task_checkpoint(blocker_state='Auth token expired.')
    text = 'What is the current state of the migration? What is blocked?'
    result = _build_lane_result(text, [checkpoint])
    work_lane = next(le for le in result.eligible_lanes if le.lane == 'work_resumption')
    assert work_lane.state == 'plausible'
    assert result.selection_mode == 'residual_fallthrough'


def test_evidence_trace_lane_plausible_without_resolver():
    """Without the resolver, evidence_request is never in the signal envelope.
    Source hits make evidence_trace plausible but not strongly eligible."""
    source = _make_source_hit()
    text = 'Show me the evidence for the library migration decision.'
    result = _build_lane_result(text, [source])
    evidence_lane = next(le for le in result.eligible_lanes if le.lane == 'evidence_trace')
    assert evidence_lane.state == 'plausible'
    assert result.selection_mode == 'residual_fallthrough'


# ---------------------------------------------------------------------------
# Query-shape guardrail tests
# ---------------------------------------------------------------------------

def test_resume_state_tag_without_checkpoint_evidence_is_plausible():
    pattern = _make_pattern_memory()
    text = 'What is currently blocked?'
    result = _build_lane_result(text, [pattern])
    work_lane = next(le for le in result.eligible_lanes if le.lane == 'work_resumption')
    assert work_lane.state in ('plausible', 'excluded')
    assert result.selection_mode == 'residual_fallthrough'


def test_source_hits_without_evidence_request_is_plausible():
    source = _make_source_hit()
    pattern = _make_pattern_memory()
    text = 'What do we know about the library migration?'
    result = _build_lane_result(text, [source, pattern])
    evidence_lane = next(le for le in result.eligible_lanes if le.lane == 'evidence_trace')
    assert evidence_lane.state == 'plausible'
    assert result.selection_mode == 'residual_fallthrough'


# ---------------------------------------------------------------------------
# Residual_recall conservative tests
# ---------------------------------------------------------------------------

def test_residual_recall_never_strongly_eligible():
    pattern = _make_pattern_memory()
    text = 'What was decided about the library catalog?'
    result = _build_lane_result(text, [pattern])
    residual = next(le for le in result.eligible_lanes if le.lane == 'residual_recall')
    assert residual.state != 'strongly_eligible'
    assert result.selection_mode == 'residual_fallthrough'


def test_residual_recall_does_not_win_over_named_lanes():
    pattern = _make_pattern_memory()
    text = 'What was the approach for the library catalog?'
    result = _build_lane_result(text, [pattern])
    assert result.selected_lane is None
    assert result.selection_mode == 'residual_fallthrough'


# ---------------------------------------------------------------------------
# Multi-lane ambiguity tests
# ---------------------------------------------------------------------------

def test_multi_lane_resumed_session_with_source_hits_selects_work():
    """With legacy English removed, evidence_request is never in shape tags from
    structural derivation. So evidence_trace is plausible (not strongly eligible)
    while work_resumption is strongly eligible via resumed_session + evidence gate.
    This results in single_lane_bypass for work_resumption."""
    source = _make_source_hit()
    checkpoint = _make_task_checkpoint(blocker_state='Token expired.')
    text = 'Show me the source evidence for this blocker. What is currently blocked?'
    runtime = QueryRuntimeContext(turn_kind='resumed_session')
    result = _build_lane_result(text, [source, checkpoint], runtime_context=runtime)
    evidence_lane = next(le for le in result.eligible_lanes if le.lane == 'evidence_trace')
    work_lane = next(le for le in result.eligible_lanes if le.lane == 'work_resumption')
    assert work_lane.state == 'strongly_eligible'
    assert evidence_lane.state == 'plausible'
    assert result.selection_mode == 'single_lane_bypass'
    assert result.selected_lane == 'work_resumption'


# ---------------------------------------------------------------------------
# Abstention tests
# ---------------------------------------------------------------------------

def test_abstention_returns_empty_with_lane_trace():
    """Verify lane_narrowing trace structure is present in residual recall queries."""
    pattern = _make_pattern_memory()
    text = 'What was decided about the library catalog?'
    outcome = _route_full(text, [pattern])
    assert outcome.trace is not None
    lane_trace = outcome.trace.routing.get('lane_narrowing', {})
    assert 'selection_mode' in lane_trace
    assert 'abstain_reason' in lane_trace


# ---------------------------------------------------------------------------
# Noise ordering tests
# ---------------------------------------------------------------------------

def test_noise_query_short_circuits_before_lane_narrowing():
    """Ultra-short queries (< 3 chars) are classified as low_value structurally."""
    checkpoint = _make_task_checkpoint()
    text = 'hi'
    outcome = _route_full(text, [checkpoint])
    assert outcome.should_inject is False
    assert outcome.decision_reason == 'low_value_query'
    if outcome.trace is not None:
        assert 'lane_narrowing' not in (outcome.trace.routing or {})


# ---------------------------------------------------------------------------
# Trace truthfulness tests
# ---------------------------------------------------------------------------

def test_single_lane_bypass_trace_shows_intent_not_used():
    checkpoint = _make_task_checkpoint(blocker_state='Token expired.')
    text = 'Where were we?'
    runtime = QueryRuntimeContext(turn_kind='resumed_session')
    outcome = _route_full(text, [checkpoint], runtime_context=runtime)
    assert outcome.trace is not None
    lane_trace = outcome.trace.routing.get('lane_narrowing', {})
    assert lane_trace.get('lane_narrowing_used_intent') is False
    assert lane_trace.get('final_intent_used') is False
    assert lane_trace.get('intent_effect') == 'none'


def test_residual_fallthrough_trace_shows_envelope_source():
    pattern = _make_pattern_memory()
    text = 'What was the approach for the library catalog?'
    outcome = _route_full(text, [pattern])
    assert outcome.trace is not None
    lane_trace = outcome.trace.routing.get('lane_narrowing', {})
    assert lane_trace.get('lane_narrowing_used_intent') is False
    assert lane_trace.get('selection_mode') == 'residual_fallthrough'
    # Envelope should be in trace
    envelope_trace = outcome.trace.routing.get('query_signal_envelope', {})
    assert 'source' in envelope_trace


def test_lane_narrowing_trace_structure():
    checkpoint = _make_task_checkpoint(blocker_state='Token expired.')
    text = 'Where were we?'
    runtime = QueryRuntimeContext(turn_kind='resumed_session')
    outcome = _route_full(text, [checkpoint], runtime_context=runtime)
    assert outcome.trace is not None
    lane_trace = outcome.trace.routing.get('lane_narrowing', {})
    required_keys = {
        'eligible_lanes', 'excluded_lanes', 'lane_exclusion_reasons',
        'lane_details', 'selected_lane', 'selection_mode',
        'lane_narrowing_used_intent', 'final_intent_used',
        'intent_effect', 'abstain_reason',
    }
    assert required_keys.issubset(set(lane_trace.keys()))
    for detail in lane_trace['lane_details']:
        assert 'lane' in detail
        assert 'state' in detail
        assert 'structural_signals' in detail
        assert 'shape_signals' in detail
        assert 'reason' in detail


# ---------------------------------------------------------------------------
# Regression safety tests
# ---------------------------------------------------------------------------

def test_broad_recall_query_unaffected_by_lane_narrowing():
    pattern = _make_pattern_memory()
    text = 'What was decided about the library catalog approach?'
    outcome = _route_full(text, [pattern])
    assert outcome.trace is not None
    lane_trace = outcome.trace.routing.get('lane_narrowing', {})
    assert lane_trace.get('selection_mode') == 'residual_fallthrough'
    assert outcome.trace.routing.get('query_intent') in (
        'recall', 'structured_recall',
    )
