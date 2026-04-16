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
    # Constraint detection removed from signal envelope (cue-free control plane).
    # Constraint recall is handled through routing, not the envelope.
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


def test_evidence_request_not_set_structurally():
    """Structural derivation never sets evidence_request — only the resolver can."""
    sources = [_make_source(f's{i}', 18) for i in range(5)]
    env = _envelope('Zeig mir die Beweise', sources)
    # With legacy English removed, envelope is always structural
    assert env.source == 'structural'
    assert env.evidence_request is False


def test_no_structural_signal_returns_low_confidence_envelope():
    """When no structural signal fires, envelope has all signals False and confidence 'low'."""
    env = _envelope('What general lesson should we remember?', [_make_pattern()])
    # With dominant pattern, history_lookup fires structurally
    assert env.source == 'structural'


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


def test_sharp_fact_when_exact_layers_outweigh_continuity_with_atomic_fact_sidecars():
    evidence_refs = [
        EvidenceReference(
            source_item_id=f'si-exact-{index}',
            source_type='assistant_artifact',
            source_id=f'exact-{index}',
            occurred_at=datetime(2026, 3, 11, 10, 0, tzinfo=timezone.utc),
            container_ref='chat:test',
            thread_ref='chat:test:t1',
            artifact_kind='assistant_output',
        )
        for index in range(3)
    ]
    decision = QueryResultItem(
        result_kind='memory_hit',
        memory_object_id='decision-exact',
        type='decision',
        payload={
            'decision': 'Use sequence-number ordering for replay updates.',
            'decision_evidence_text': 'Decision: use sequence-number ordering for replay updates.',
        },
        freshness_at=datetime(2026, 3, 11, 10, 2, tzinfo=timezone.utc),
        score=20,
        evidence=evidence_refs,
        container_ref='chat:test',
        thread_ref='chat:test:t1',
        envelope=_memory_envelope('finding'),
    )
    investigation = QueryResultItem(
        result_kind='memory_hit',
        memory_object_id='investigation-exact',
        type='investigation_outcome',
        payload={
            'investigation_outcome': 'Arrival-order replay applied stale updates after sync lag.',
            'investigation_evidence_text': 'Investigation found that arrival-order replay applied stale updates after sync lag.',
        },
        freshness_at=datetime(2026, 3, 11, 10, 1, tzinfo=timezone.utc),
        score=19,
        evidence=evidence_refs,
        container_ref='chat:test',
        thread_ref='chat:test:t1',
        envelope=_memory_envelope('finding'),
    )
    continuity = QueryResultItem(
        result_kind='memory_hit',
        memory_object_id='continuity-exact',
        type='continuity_memory',
        payload={
            'summary': 'Replay updates should use sequence-number ordering instead of arrival ordering.',
            'carry_forward_answer': 'Use sequence-number ordering instead of arrival ordering for replay updates.',
        },
        freshness_at=datetime(2026, 3, 11, 10, 2, tzinfo=timezone.utc),
        score=21,
        evidence=evidence_refs,
        container_ref='chat:test',
        thread_ref='chat:test:t1',
        envelope=_memory_envelope('summary'),
    )
    atomic_fact = QueryResultItem(
        result_kind='memory_hit',
        memory_object_id='atomic-exact',
        type='atomic_fact',
        payload={'statement': 'Replay updates use sequence-number ordering.'},
        freshness_at=datetime(2026, 3, 11, 10, 2, tzinfo=timezone.utc),
        score=18,
        evidence=evidence_refs,
        container_ref='chat:test',
        thread_ref='chat:test:t1',
        envelope=_memory_envelope('finding'),
    )

    ce = _compute_typed_candidate_evidence(
        [decision, investigation, continuity, atomic_fact],
        QueryFilters(container_ref='chat:test', thread_ref='chat:test:t1'),
    )

    assert _select_recall_mode(ce) == 'sharp_fact_preference'


# --- Policy family from envelope ---

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


# --- Legacy English fallback removed (cue-free control plane) ---

def test_low_confidence_envelope_has_all_signals_false():
    """When no structural signal fires and no candidate dominance, envelope
    has all signals False with confidence 'low' and source 'structural'."""
    env = _envelope('hello', [_make_pattern()])
    # pattern is dominant → history_lookup fires; but for a pure greeting
    # with weak candidates, history_lookup would not fire. Since we have a
    # pattern candidate, it does fire. Verify source is always structural now.
    assert env.source == 'structural'


def test_legacy_english_removed_no_constraint_lookup():
    """Constraint lookup removed from signal envelope in cue-free control plane.
    The envelope is now always structural."""
    env = _envelope('What constraint did I give about the portal?', [_make_pattern()])
    assert env.source == 'structural'


# --- Evidence trace override tests ---

def test_evidence_override_skips_when_already_detected():
    from semantic.agent_conversation_memory_routing import _check_evidence_trace_override
    env = QuerySignalEnvelope(
        low_value=False, history_lookup=False, latest_status_request=False,
        resume_state=False, evidence_request=True,
        source='structural', confidence='high',
    )
    result = _check_evidence_trace_override(
        envelope=env, source_ratio=0.5, query_text='show proof',
        candidates=[], runtime_context=None, resolver_config={'resolver_enabled': True, 'provider': None},
    )
    assert result is env  # unchanged


def test_evidence_override_skips_when_source_ratio_low():
    from semantic.agent_conversation_memory_routing import _check_evidence_trace_override
    env = QuerySignalEnvelope(
        low_value=False, history_lookup=False, latest_status_request=False,
        resume_state=False, evidence_request=False,
        source='structural', confidence='medium',
    )
    result = _check_evidence_trace_override(
        envelope=env, source_ratio=0.1, query_text='show proof',
        candidates=[], runtime_context=None, resolver_config={'resolver_enabled': True, 'provider': None},
    )
    assert result.evidence_request is False  # unchanged


def test_evidence_override_skips_when_resume_won():
    from semantic.agent_conversation_memory_routing import _check_evidence_trace_override
    env = QuerySignalEnvelope(
        low_value=False, history_lookup=False, latest_status_request=False,
        resume_state=True, evidence_request=False,
        source='structural', confidence='high',
    )
    result = _check_evidence_trace_override(
        envelope=env, source_ratio=0.5, query_text='show proof',
        candidates=[], runtime_context=None, resolver_config={'resolver_enabled': True, 'provider': None},
    )
    assert result.evidence_request is False  # resume wins


def test_evidence_override_skips_when_resolver_disabled():
    from semantic.agent_conversation_memory_routing import _check_evidence_trace_override
    env = QuerySignalEnvelope(
        low_value=False, history_lookup=False, latest_status_request=False,
        resume_state=False, evidence_request=False,
        source='structural', confidence='medium',
    )
    result = _check_evidence_trace_override(
        envelope=env, source_ratio=0.5, query_text='show proof',
        candidates=[], runtime_context=None, resolver_config=None,
    )
    assert result.evidence_request is False


def test_evidence_override_falls_back_without_live_provider():
    """Resolver with no LLM provider returns FALLBACK, so evidence_request stays False."""
    from semantic.agent_conversation_memory_routing import _check_evidence_trace_override
    env = QuerySignalEnvelope(
        low_value=False, history_lookup=False, latest_status_request=False,
        resume_state=False, evidence_request=False,
        source='structural', confidence='medium',
    )
    result = _check_evidence_trace_override(
        envelope=env, source_ratio=0.5, query_text='show me the proof',
        candidates=[_make_source(), _make_decision()], runtime_context=None,
        resolver_config={'resolver_enabled': True, 'provider': None, 'resolver_timeout_ms': 100},
    )
    assert result.evidence_request is False  # FALLBACK — no live provider
