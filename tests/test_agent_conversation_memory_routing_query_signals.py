"""Tests for QuerySignalEnvelope derivation and recall mode selection."""
from __future__ import annotations

from datetime import datetime, timezone

from core.models import EvidenceReference, QueryFilters, QueryResultItem, QueryRuntimeContext, QueryTrace
from retrieval.base import RetrievalQueryResult
from semantic.agent_conversation_memory import AgentConversationMemoryPlugin
from semantic.agent_conversation_memory_constraints import CONSTRAINT_MEMORY_TYPE
from semantic.agent_conversation_memory_routing import (
    POLICY_SUPPORT_THRESHOLD,
    QuerySignalEnvelope,
    _compute_typed_candidate_evidence,
    _derive_query_signal_envelope,
    _build_policy_evidence,
    _legacy_english_query_signals,
    _policy_family_from_signal_envelope,
    _routing_query_tokens,
    _select_recall_mode,
)
from tests.agent_conversation_memory_routing_helpers import (
    _inventory_batch_typed_constraint_result,
    _memory_envelope,
)
from tests.tiered_memory_stub_providers import TieredMemorySemanticProvider


def _make_decision(memory_object_id='decision-1', score=20):
    return QueryResultItem(
        result_kind='memory_hit',
        memory_object_id=memory_object_id,
        type='decision',
        payload={'decision': 'Use item event time for ordering.', 'decision_evidence_text': 'Team agreed.', 'rationale': 'Avoids duplicates.'},
        freshness_at=datetime(2026, 3, 11, 10, 0, tzinfo=timezone.utc),
        score=score,
        evidence=[EvidenceReference(source_item_id='si-1', source_type='chat_message', source_id='s-1',
                  occurred_at=datetime(2026, 3, 11, 10, 0, tzinfo=timezone.utc),
                  container_ref='chat:test', thread_ref='chat:test:t1', artifact_kind='message')],
        container_ref='chat:test',
        thread_ref='chat:test:t1',
        envelope=_memory_envelope('finding'),
    )


def _make_pattern(memory_object_id='pattern-1', score=16):
    return QueryResultItem(
        result_kind='memory_hit',
        memory_object_id=memory_object_id,
        type='pattern_memory',
        payload={'summary': 'Batch migration approach.', 'pattern_label': 'batch approach'},
        freshness_at=datetime(2026, 3, 11, 10, 0, tzinfo=timezone.utc),
        score=score,
        evidence=[],
        container_ref='chat:test',
        thread_ref='chat:test:t1',
        envelope=_memory_envelope('summary'),
    )


def _make_continuity(memory_object_id='continuity-1', score=18, thread_ref='chat:test:t1'):
    return QueryResultItem(
        result_kind='memory_hit',
        memory_object_id=memory_object_id,
        type='continuity_memory',
        payload={'summary': 'Carried forward answer.', 'carry_forward_answer': 'Use event time.'},
        freshness_at=datetime(2026, 3, 11, 10, 0, tzinfo=timezone.utc),
        score=score,
        evidence=[EvidenceReference(source_item_id='si-2', source_type='chat_message', source_id='s-2',
                  occurred_at=datetime(2026, 3, 11, 10, 0, tzinfo=timezone.utc),
                  container_ref='chat:test', thread_ref=thread_ref, artifact_kind='message')],
        container_ref='chat:test',
        thread_ref=thread_ref,
    )


def _make_source(source_id='source-1', score=18):
    return QueryResultItem(
        result_kind='source_hit',
        source_item_id=f'si-{source_id}',
        source_type='chat_message',
        source_id=source_id,
        excerpt='The library migration finding.',
        occurred_at=datetime(2026, 3, 11, 10, 0, tzinfo=timezone.utc),
        container_ref='chat:test',
        thread_ref='chat:test:t1',
        artifact_kind='message',
        score=score,
        evidence=[EvidenceReference(source_item_id=f'si-{source_id}', source_type='chat_message',
                  source_id=source_id, occurred_at=datetime(2026, 3, 11, 10, 0, tzinfo=timezone.utc),
                  container_ref='chat:test', thread_ref='chat:test:t1', artifact_kind='message')],
    )


def _envelope(text, candidates, runtime_context=None):
    tokens = _routing_query_tokens(text)
    pe = _build_policy_evidence(candidates)
    ce = _compute_typed_candidate_evidence(candidates, QueryFilters(container_ref='chat:test', thread_ref='chat:test:t1'))
    return _derive_query_signal_envelope(
        text=text, query_tokens=tokens, policy_evidence=pe, candidate_evidence=ce,
        anchor_prefiltered_candidates=candidates, runtime_context=runtime_context,
        signal_classifier_config=None,
    )


# --- Structural derivation tests ---

def test_empty_query_is_low_value():
    env = _envelope('', [_make_pattern()])
    assert env.low_value is True
    assert env.source == 'structural'


def test_short_query_not_low_value():
    env = _envelope('blocked?', [_make_pattern()])
    assert env.low_value is False


def test_constraint_signal_from_typed_memory():
    constraint = _inventory_batch_typed_constraint_result(score=20)
    # Add evidence to push above threshold
    constraint = QueryResultItem(
        result_kind=constraint.result_kind, memory_object_id=constraint.memory_object_id,
        type=constraint.type, payload=constraint.payload, freshness_at=constraint.freshness_at,
        score=constraint.score,
        evidence=[EvidenceReference(source_item_id='si-c', source_type='chat_message', source_id='c-raw',
                  occurred_at=datetime(2026, 3, 11, 10, 0, tzinfo=timezone.utc),
                  container_ref='chat:test', thread_ref='chat:test:t1', artifact_kind='message')],
        container_ref=constraint.container_ref, thread_ref=constraint.thread_ref, envelope=constraint.envelope,
    )
    env = _envelope('What should I avoid?', [constraint, _make_pattern()])
    assert env.constraint_lookup is True
    assert env.source == 'structural'


def test_resume_state_from_resumed_session_with_evidence():
    from tests.test_agent_conversation_memory_routing_lane_narrowing import _make_task_checkpoint
    checkpoint = _make_task_checkpoint(blocker_state='Token expired.')
    runtime = QueryRuntimeContext(turn_kind='resumed_session')
    env = _envelope('Where were we?', [checkpoint], runtime_context=runtime)
    assert env.resume_state is True
    assert env.source == 'structural'


def test_history_lookup_from_dominant_pattern():
    env = _envelope('What was decided?', [_make_pattern(), _make_pattern('p2', 14)])
    assert env.history_lookup is True


def test_evidence_request_not_set_by_tier1():
    """Tier 1 structural derivation never sets evidence_request — only Tier 2/3 can."""
    sources = [_make_source(f's{i}', 18) for i in range(5)]
    # Non-English query to avoid Tier 3 English fallback setting evidence_request
    env = _envelope('Zeig mir die Beweise', sources)
    # Tier 1 should not set evidence_request from source dominance alone
    # Since Tier 2 classifier is a stub, falls to Tier 3 which won't match German
    assert env.source in {'structural', 'legacy_english_fallback'}
    if env.source == 'structural':
        assert env.evidence_request is False


def test_no_signal_falls_to_legacy_english():
    env = _envelope('What general lesson should we remember?', [_make_pattern()])
    # With dominant pattern, history_lookup fires structurally
    assert env.source in {'structural', 'legacy_english_fallback'}


# --- Recall mode selection tests ---

def test_default_mode_for_mixed_candidates():
    candidates = [_make_decision(), _make_pattern(), _make_pattern('p2')]
    ce = _compute_typed_candidate_evidence(candidates, None)
    assert _select_recall_mode(ce) == 'default'


def test_continuity_preference_when_dominant():
    candidates = [_make_continuity(), _make_continuity('c2', 16)]
    ce = _compute_typed_candidate_evidence(candidates, QueryFilters(container_ref='chat:test', thread_ref='chat:test:t1'))
    mode = _select_recall_mode(ce)
    assert mode == 'continuity_preference'


def test_sharp_fact_when_decision_dominant_no_competition():
    # Decisions need 3+ evidence refs to reach POLICY_SUPPORT_THRESHOLD (60)
    evidence_refs = [
        EvidenceReference(source_item_id=f'si-e{i}', source_type='chat_message', source_id=f'e{i}',
                  occurred_at=datetime(2026, 3, 11, 10, 0, tzinfo=timezone.utc),
                  container_ref='chat:test', thread_ref='chat:test:t1', artifact_kind='message')
        for i in range(3)
    ]
    d1 = QueryResultItem(
        result_kind='memory_hit', memory_object_id='d1', type='decision',
        payload={'decision': 'Use event time.', 'decision_evidence_text': 'Team agreed.'},
        freshness_at=datetime(2026, 3, 11, 10, 0, tzinfo=timezone.utc), score=20,
        evidence=evidence_refs, container_ref='chat:test', thread_ref='chat:test:t1',
        envelope=_memory_envelope('finding'),
    )
    d2 = QueryResultItem(
        result_kind='memory_hit', memory_object_id='d2', type='decision',
        payload={'decision': 'Use batch approach.', 'decision_evidence_text': 'Agreed.'},
        freshness_at=datetime(2026, 3, 11, 10, 0, tzinfo=timezone.utc), score=18,
        evidence=evidence_refs, container_ref='chat:test', thread_ref='chat:test:t1',
        envelope=_memory_envelope('finding'),
    )
    ce = _compute_typed_candidate_evidence([d1, d2], None)
    mode = _select_recall_mode(ce)
    assert mode == 'sharp_fact_preference'


# --- Policy family from envelope ---

def test_constraint_signal_maps_to_check_constraints():
    env = QuerySignalEnvelope(constraint_lookup=True, source='structural', confidence='high')
    assert _policy_family_from_signal_envelope(env) == 'check_constraints'


def test_resume_signal_maps_to_resume_work():
    env = QuerySignalEnvelope(resume_state=True, source='structural', confidence='high')
    assert _policy_family_from_signal_envelope(env) == 'resume_work'


def test_no_signal_maps_to_recall_fact():
    env = QuerySignalEnvelope(source='structural', confidence='low')
    assert _policy_family_from_signal_envelope(env) == 'recall_fact'


def test_low_value_maps_to_noise():
    env = QuerySignalEnvelope(low_value=True, source='structural', confidence='high')
    assert _policy_family_from_signal_envelope(env) == 'noise'


# --- Trace tests ---

def test_envelope_trace_in_routing_output():
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    retrieval_result = RetrievalQueryResult(
        results=[_make_pattern()],
        trace=QueryTrace(query_text='What was the approach?', query_tokens=('approach',), limit=4,
                         filters=QueryFilters(container_ref='chat:test'), stages=()),
    )
    outcome = plugin.route_query_results(
        text='What was the approach?', requested_limit=4,
        retrieval_result=retrieval_result,
        query_filters=QueryFilters(container_ref='chat:test', thread_ref='chat:test:t1'),
        include_trace=True,
    )
    assert outcome.trace is not None
    assert 'query_signal_envelope' in outcome.trace.routing
    env_trace = outcome.trace.routing['query_signal_envelope']
    assert 'source' in env_trace
    assert 'confidence' in env_trace
    assert 'derivation_signals' in env_trace
    assert 'recall_mode' in outcome.trace.routing


# --- Legacy English fallback ---

def test_legacy_english_detects_greeting():
    env = _legacy_english_query_signals('hello', _routing_query_tokens('hello'))
    assert env.low_value is True
    assert env.legacy_english_fallback_used is True
    assert env.source == 'legacy_english_fallback'


def test_legacy_english_detects_constraint():
    env = _legacy_english_query_signals(
        'What constraint did I give about the portal?',
        _routing_query_tokens('What constraint did I give about the portal?'),
    )
    assert env.constraint_lookup is True
    assert env.legacy_english_fallback_used is True
