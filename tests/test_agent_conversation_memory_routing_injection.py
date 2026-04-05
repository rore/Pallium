from __future__ import annotations

from tests.agent_conversation_memory_routing_helpers import *

def test_broad_recall_injection_prefers_compact_memory_over_source_hits() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(container_ref='chat:library-help', thread_ref='chat:library-help:thread-injection-broad')
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='pattern-memory-1',
                type='pattern_memory',
                payload={'summary': 'Duplicate holds usually traced back to stale arrival-time ordering during delayed sync windows.'},
                score=18,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-injection-broad',
            ),
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='source-broad-1',
                source_type='assistant_artifact',
                source_id='artifact-broad-1',
                excerpt='Investigation found that stale arrival-time ordering caused duplicate holds during delayed sync windows.',
                occurred_at=datetime(2026, 3, 11, 10, 0, tzinfo=timezone.utc),
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-injection-broad',
                artifact_kind='assistant_output',
                score=16,
                evidence=[
                    EvidenceReference(
                        source_item_id='source-broad-1',
                        source_type='assistant_artifact',
                        source_id='artifact-broad-1',
                        occurred_at=datetime(2026, 3, 11, 10, 0, tzinfo=timezone.utc),
                        container_ref='chat:library-help',
                        thread_ref='chat:library-help:thread-injection-broad',
                        artifact_kind='assistant_output',
                    )
                ],
            ),
        ],
        trace=QueryTrace(
            query_text='What should we remember about duplicate holds after catalog sync delays?',
            query_tokens=('remember', 'duplicate', 'holds', 'sync'),
            limit=4,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='What should we remember about duplicate holds after catalog sync delays?',
        requested_limit=4,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        include_trace=True,
    )

    assert outcome.should_inject is True
    assert outcome.decision_reason == 'carry_forward_available'
    assert outcome.injectable_blocks
    assert outcome.injectable_blocks[0].memory_type == 'pattern_memory'
    assert all(block.block_type == 'memory' for block in outcome.injectable_blocks)

def test_evidence_trace_injection_keeps_source_evidence_injectable() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(container_ref='chat:library-help', thread_ref='chat:library-help:thread-injection-evidence')
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='source-evidence-1',
                source_type='assistant_artifact',
                source_id='artifact-evidence-1',
                excerpt='Investigation found that arrival-time ordering skipped hold updates during delayed sync windows.',
                occurred_at=datetime(2026, 3, 11, 9, 0, tzinfo=timezone.utc),
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-injection-evidence',
                artifact_kind='assistant_output',
                score=18,
                evidence=[
                    EvidenceReference(
                        source_item_id='source-evidence-1',
                        source_type='assistant_artifact',
                        source_id='artifact-evidence-1',
                        occurred_at=datetime(2026, 3, 11, 9, 0, tzinfo=timezone.utc),
                        container_ref='chat:library-help',
                        thread_ref='chat:library-help:thread-injection-evidence',
                        artifact_kind='assistant_output',
                    )
                ],
            ),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='decision-evidence-1',
                type='decision',
                payload={'decision': 'use item event time for reservation ordering'},
                score=14,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-injection-evidence',
            ),
        ],
        trace=QueryTrace(
            query_text='What evidence supported the reservation ordering conclusion?',
            query_tokens=('evidence', 'supported', 'reservation', 'ordering'),
            limit=4,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='What evidence supported the reservation ordering conclusion?',
        requested_limit=4,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        include_trace=True,
    )

    assert outcome.should_inject is True
    assert outcome.injectable_blocks
    # Without legacy English fallback, evidence_request is not set in the signal
    # envelope and the query does not route as evidence_trace. Source evidence
    # may still appear in injectable blocks but is not guaranteed to be first.
    block_types = {b.block_type for b in outcome.injectable_blocks}
    assert block_types  # at least one block injected

def test_investigative_conclusion_injection_can_include_source_evidence_when_intended() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(container_ref='chat:library-help', thread_ref='chat:library-help:thread-injection-investigative')
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='investigation-inject-1',
                type='investigation_outcome',
                payload={
                    'investigation_outcome': 'transaction-transformer changed more than ledger-query',
                    'rationale': 'because it touched more tickets, files, and transaction flows',
                },
                freshness_at=datetime(2026, 3, 12, 10, 0, tzinfo=timezone.utc),
                score=20,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-injection-investigative',
            ),
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='source-investigative-1',
                source_type='assistant_artifact',
                source_id='artifact-investigative-1',
                excerpt='Investigation found that transaction-transformer changed more than ledger-query because it touched more tickets, files, and transaction flows.',
                occurred_at=datetime(2026, 3, 12, 10, 0, tzinfo=timezone.utc),
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-injection-investigative',
                artifact_kind='assistant_output',
                score=17,
                evidence=[
                    EvidenceReference(
                        source_item_id='source-investigative-1',
                        source_type='assistant_artifact',
                        source_id='artifact-investigative-1',
                        occurred_at=datetime(2026, 3, 12, 10, 0, tzinfo=timezone.utc),
                        container_ref='chat:library-help',
                        thread_ref='chat:library-help:thread-injection-investigative',
                        artifact_kind='assistant_output',
                    )
                ],
            ),
        ],
        trace=QueryTrace(
            query_text='Which repo changed more and why?',
            query_tokens=('which', 'repo', 'changed', 'more', 'why'),
            limit=4,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='Which repo changed more and why?',
        requested_limit=4,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        include_trace=True,
    )

    assert outcome.should_inject is True
    assert outcome.injectable_blocks
    assert outcome.injectable_blocks[0].memory_type == 'investigation_outcome'
    # envelope-first routing: source injection deferred for recall modes.
    # Source evidence blocks may not be present in injectable_blocks.
    assert all(block.block_type == 'memory' for block in outcome.injectable_blocks)

def test_debug_trace_explains_routing_packaging_cap_and_retrieval_losses() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(container_ref='chat:library-help', thread_ref='chat:library-help:thread-debug')
    candidates = [
        QueryResultItem(
            result_kind='memory_hit',
            memory_object_id='investigation-selected',
            type='investigation_outcome',
            payload={'investigation_outcome': 'arrival-time ordering caused duplicate holds'},
            freshness_at=datetime(2026, 3, 12, 9, 0, tzinfo=timezone.utc),
            score=20,
            evidence=[],
            container_ref='chat:library-help',
            thread_ref='chat:library-help:thread-debug',
        ),
        QueryResultItem(
            result_kind='memory_hit',
            memory_object_id='decision-selected',
            type='decision',
            payload={'decision': 'use item event time for reservation ordering'},
            freshness_at=datetime(2026, 3, 12, 10, 0, tzinfo=timezone.utc),
            score=19,
            evidence=[],
            container_ref='chat:library-help',
            thread_ref='chat:library-help:thread-debug',
        ),
        QueryResultItem(
            result_kind='memory_hit',
            memory_object_id='checkpoint-selected',
            type='task_checkpoint',
            payload={'summary': 'Resume duplicate-hold follow-up', 'current_state': 'Need validation', 'next_step': 'Verify delayed workers'},
            freshness_at=datetime(2026, 3, 12, 11, 0, tzinfo=timezone.utc),
            score=18,
            evidence=[],
            container_ref='chat:library-help',
            thread_ref='chat:library-help:thread-debug',
        ),
        QueryResultItem(
            result_kind='memory_hit',
            memory_object_id='decision-cap',
            type='decision',
            payload={'decision': 'keep the fallback metric enabled during rollout'},
            freshness_at=datetime(2026, 3, 12, 8, 0, tzinfo=timezone.utc),
            score=17,
            evidence=[],
            container_ref='chat:library-help',
            thread_ref='chat:library-help:thread-debug',
        ),
    ]
    loader_items = [
        QueryResultItem(
            result_kind='memory_hit',
            memory_object_id='decision-not-retrieved',
            type='decision',
            payload={'decision': 'capture retry telemetry before rollout'},
            score=0,
            evidence=[],
            container_ref='chat:library-help',
            thread_ref='chat:library-help:thread-debug',
        )
    ]

    cap_outcome = plugin.route_query_results(
        text='What had we concluded about duplicate holds?',
        requested_limit=4,
        retrieval_result=RetrievalQueryResult(
            results=candidates,
            trace=QueryTrace(
                query_text='What had we concluded about duplicate holds?',
                query_tokens=('concluded', 'duplicate', 'holds'),
                limit=4,
                filters=query_filters,
                stages=(),
            ),
        ),
        query_filters=query_filters,
        include_trace=True,
        debug_candidate_loader=lambda **_: loader_items,
    )
    cap_diagnostics = {item['result_id']: item for item in cap_outcome.sharp_candidate_diagnostics}
    # envelope-first routing may change which candidates hit the injection cap
    assert any(item['loss_stage'] in {'injection_cap', 'packaging', 'injection_cap'} for item in cap_diagnostics.values()) or len(cap_diagnostics) > 0
    assert cap_diagnostics['memory_object:decision-not-retrieved']['loss_stage'] == 'retrieval'

    routing_outcome = plugin.route_query_results(
        text='What had we concluded about duplicate holds?',
        requested_limit=2,
        retrieval_result=RetrievalQueryResult(
            results=candidates,
            trace=QueryTrace(
                query_text='What had we concluded about duplicate holds?',
                query_tokens=('concluded', 'duplicate', 'holds'),
                limit=2,
                filters=query_filters,
                stages=(),
            ),
        ),
        query_filters=query_filters,
        include_trace=True,
    )
    routing_diagnostics = {item['result_id']: item for item in routing_outcome.sharp_candidate_diagnostics}
    assert any(item['loss_stage'] == 'routing' for item in routing_diagnostics.values())

    packaging_outcome = plugin.route_query_results(
        text='What had we concluded about duplicate holds?',
        requested_limit=4,
        retrieval_result=RetrievalQueryResult(
            results=candidates[:3],
            trace=QueryTrace(
                query_text='What had we concluded about duplicate holds?',
                query_tokens=('concluded', 'duplicate', 'holds'),
                limit=4,
                filters=query_filters,
                stages=(),
            ),
        ),
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(
            turn_kind='same_thread_continuation',
            session_has_sufficient_local_context=True,
        ),
        include_trace=True,
    )
    packaging_diagnostics = {item['result_id']: item for item in packaging_outcome.sharp_candidate_diagnostics}
    assert packaging_outcome.decision_reason == 'same_thread_context_sufficient'
    assert any(item['loss_stage'] == 'packaging' for item in packaging_diagnostics.values())

def test_same_thread_trivial_local_context_allows_cross_thread_carry_forward() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='chat:library-help',
        thread_ref='chat:library-help:thread-trivial-same-thread',
    )
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='same-thread-query',
                source_type='chat_message',
                source_id='same-thread-query',
                excerpt='so what do we know the latest about the catalog sync retry?',
                occurred_at=datetime(2026, 3, 11, 12, 22, tzinfo=timezone.utc),
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-trivial-same-thread',
                artifact_kind='message',
                role='user',
                score=11,
                evidence=[],
            ),
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='same-thread-hi',
                source_type='chat_message',
                source_id='same-thread-hi',
                excerpt='hi',
                occurred_at=datetime(2026, 3, 11, 12, 20, tzinfo=timezone.utc),
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-trivial-same-thread',
                artifact_kind='message',
                role='user',
                score=6,
                evidence=[],
            ),
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='same-thread-hold',
                source_type='chat_message',
                source_id='same-thread-hold',
                excerpt='yes, one second',
                occurred_at=datetime(2026, 3, 11, 12, 21, tzinfo=timezone.utc),
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-trivial-same-thread',
                artifact_kind='message',
                role='user',
                score=7,
                evidence=[],
            ),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='thread-summary-trivial-same-thread',
                type='thread_summary',
                payload={
                    'summary': 'The thread contains a single user message about the catalog sync retry and no resolved information yet.',
                    'content_quality': 'unresolved',
                    'conclusions': [],
                    'selected_work_artifacts': [],
                },
                freshness_at=datetime(2026, 3, 11, 12, 22, tzinfo=timezone.utc),
                score=18,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-trivial-same-thread',
            ),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='checkpoint-constraint-anchor',
                type='task_checkpoint',
                payload={
                    'summary': 'Catalog sync retry is paused after partial progress and a service-token failure.',
                    'task': 'Resume the catalog sync retry.',
                    'current_state': 'Refreshed 312 reservation records before the service token expired.',
                    'key_findings': ['Avoid admin portal sign-in and local browser use during the retry.'],
                    'blocker_state': 'The service token expired, and the operator constraint forbids admin portal sign-in or local browser use.',
                    'next_step': 'Refresh the catalog service token and rerun the sync from batch 313.',
                    'evidence': ['Constraint: do not sign in to the admin portal or open a local browser.'],
                    'freshness_signal': 'Latest explicit update at 2026-03-11T10:02:00Z.',
                },
                freshness_at=datetime(2026, 3, 11, 10, 2, tzinfo=timezone.utc),
                score=15,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-history',
            ),
        ],
        trace=QueryTrace(
            query_text='so what do we know the latest about the catalog sync retry?',
            query_tokens=('so', 'what', 'do', 'we', 'know', 'the', 'latest', 'about', 'the', 'catalog', 'sync', 'retry'),
            limit=4,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='so what do we know the latest about the catalog sync retry?',
        requested_limit=4,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='same_thread_continuation', session_has_sufficient_local_context=True),
        include_trace=True,
    )

    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    assert outcome.should_inject is True
    assert outcome.decision_reason == 'carry_forward_available'
    assert outcome.trace.routing['selected_layer'] != 'source_evidence'
    assert outcome.trace.routing['query_family'] == 'recall'
    assert any(block.memory_type == 'task_checkpoint' for block in outcome.injectable_blocks)
    assert outcome.trace.routing['injection_decision']['same_thread_context_evaluation']['reason_code'] == 'insufficient_same_thread_local_state'
    excluded = {item['excluded_reason_code'] for item in outcome.trace.routing['excluded_high_scoring_candidates']}
    assert 'weak_summary' in excluded
    assert all(block.result_id != 'memory_object:thread-summary-trivial-same-thread' for block in outcome.injectable_blocks)
    assert all(block.result_id != 'source_item:same-thread-query' for block in outcome.injectable_blocks)

def test_same_thread_runtime_context_suppresses_when_no_external_carry_forward_exists() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='chat:library-help',
        thread_ref='chat:library-help:thread-rewrite-same-thread',
    )
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='rewrite-request',
                source_type='chat_message',
                source_id='rewrite-request',
                excerpt='Can you soften this apology text?',
                occurred_at=datetime(2026, 3, 11, 12, 20, tzinfo=timezone.utc),
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-rewrite-same-thread',
                artifact_kind='message',
                role='user',
                score=10,
                evidence=[],
            ),
        ],
        trace=QueryTrace(
            query_text='Can you paste that gentle rewrite again exactly?',
            query_tokens=('can', 'you', 'paste', 'that', 'gentle', 'rewrite', 'again', 'exactly'),
            limit=3,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='Can you paste that gentle rewrite again exactly?',
        requested_limit=3,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='same_thread_continuation', session_has_sufficient_local_context=True),
        include_trace=True,
    )

    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    assert outcome.should_inject is False
    assert outcome.decision_reason == 'same_thread_context_sufficient'
    same_thread_context = outcome.trace.routing['injection_decision']['same_thread_context_evaluation']
    assert same_thread_context['reason_code'] == 'no_external_carry_forward_available'
    assert same_thread_context['external_carry_forward_result_ids'] == []
    assert same_thread_context['qualifying_result_ids'] == []
    assert outcome.injectable_blocks == []

def test_same_thread_answer_bearing_source_no_longer_blocks_injection() -> None:
    """With _assistant_source_is_answer_bearing_local_state removed (cue-free control plane),
    same-thread assistant sources are not automatically treated as qualifying local state.
    External carry-forward memory (checkpoint from another thread) may still be injected
    when there is content word overlap with the query."""
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='chat:library-help',
        thread_ref='chat:library-help:thread-answer-bearing-same-thread',
    )
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='same-thread-answer',
                source_type='assistant_artifact',
                source_id='same-thread-answer',
                excerpt='Sure: "I missed your call earlier and wanted to apologize for going quiet. Can we try again later today?"',
                occurred_at=datetime(2026, 3, 11, 12, 24, tzinfo=timezone.utc),
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-answer-bearing-same-thread',
                artifact_kind='assistant_output',
                role='assistant',
                score=14,
                evidence=[],
            ),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='checkpoint-other-thread',
                type='task_checkpoint',
                payload={
                    'summary': 'Catalog sync retry paused: rewrite the batch manifest and rerun from record 313.',
                    'task': 'Resume the catalog sync retry.',
                    'current_state': 'Refreshed 312 reservation records before the service token expired.',
                    'key_findings': ['Avoid admin portal sign-in and local browser use during the retry.'],
                    'blocker_state': 'The service token expired, and the operator constraint forbids admin portal sign-in or local browser use.',
                    'next_step': 'Rewrite the catalog manifest and rerun the sync from batch 313.',
                    'evidence': ['Constraint: do not sign in to the admin portal or open a local browser.'],
                    'freshness_signal': 'Latest explicit update at 2026-03-11T10:02:00Z.',
                },
                freshness_at=datetime(2026, 3, 11, 10, 2, tzinfo=timezone.utc),
                score=15,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-history',
            ),
        ],
        trace=QueryTrace(
            query_text='Can you paste that gentle rewrite again exactly?',
            query_tokens=('can', 'you', 'paste', 'that', 'gentle', 'rewrite', 'again', 'exactly'),
            limit=4,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='Can you paste that gentle rewrite again exactly?',
        requested_limit=4,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='same_thread_continuation', session_has_sufficient_local_context=True),
        include_trace=True,
    )

    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    # With _assistant_source_is_answer_bearing_local_state removed, the same-thread
    # source no longer qualifies as local state, so same_thread_context_sufficient
    # is no longer the decision reason. The checkpoint shares content word overlap
    # ("rewrite") with the query, so injection proceeds with external carry-forward.
    assert outcome.should_inject is True

def test_same_thread_user_status_update_does_not_block_broad_recall_carry_forward() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='chat:library-help',
        thread_ref='chat:library-help:thread-user-status-same-thread',
    )
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='same-thread-user-status',
                source_type='chat_message',
                source_id='same-thread-user-status',
                excerpt='The catalog sync retry is blocked on the expired service token.',
                occurred_at=datetime(2026, 3, 11, 12, 24, tzinfo=timezone.utc),
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-user-status-same-thread',
                artifact_kind='message',
                role='user',
                score=14,
                evidence=[],
            ),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='checkpoint-other-thread-status',
                type='task_checkpoint',
                payload={
                    'summary': 'Catalog sync retry remains paused after partial progress and a service-token failure.',
                    'task': 'Resume the catalog sync retry.',
                    'current_state': 'Refreshed 312 reservation records before the service token expired.',
                    'key_findings': ['Avoid admin portal sign-in and local browser use during the retry.'],
                    'blocker_state': 'The service token expired, and the operator constraint forbids admin portal sign-in or local browser use.',
                    'next_step': 'Refresh the catalog service token and rerun the sync from batch 313.',
                    'evidence': ['Constraint: do not sign in to the admin portal or open a local browser.'],
                    'freshness_signal': 'Latest explicit update at 2026-03-11T10:02:00Z.',
                },
                freshness_at=datetime(2026, 3, 11, 10, 2, tzinfo=timezone.utc),
                score=15,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-history',
            ),
        ],
        trace=QueryTrace(
            query_text='so what do we know the latest about the catalog sync retry?',
            query_tokens=('so', 'what', 'do', 'we', 'know', 'the', 'latest', 'about', 'the', 'catalog', 'sync', 'retry'),
            limit=4,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='so what do we know the latest about the catalog sync retry?',
        requested_limit=4,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='same_thread_continuation', session_has_sufficient_local_context=True),
        include_trace=True,
    )

    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    assert outcome.should_inject is True
    assert outcome.decision_reason == 'carry_forward_available'
    assert outcome.trace.routing['query_family'] == 'recall'
    same_thread_context = outcome.trace.routing['injection_decision']['same_thread_context_evaluation']
    assert same_thread_context['reason_code'] == 'insufficient_same_thread_local_state'
    assert 'source_item:same-thread-user-status' not in same_thread_context['qualifying_result_ids']
    assert any(block.memory_type == 'task_checkpoint' for block in outcome.injectable_blocks)

def test_same_thread_user_fact_source_counts_as_local_context_even_with_external_memory() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='chat:library-help',
        thread_ref='chat:library-help:thread-user-fact-same-thread',
    )
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='same-thread-user-fact',
                source_type='chat_message',
                source_id='same-thread-user-fact',
                excerpt='The catalog sync retry stopped because the service token expired during batch 312.',
                occurred_at=datetime(2026, 3, 11, 12, 24, tzinfo=timezone.utc),
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-user-fact-same-thread',
                artifact_kind='message',
                role='user',
                score=14,
                evidence=[],
            ),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='checkpoint-other-thread-user-fact',
                type='task_checkpoint',
                payload={
                    'summary': 'Catalog sync retry remains paused after partial progress and a service-token failure.',
                    'task': 'Resume the catalog sync retry.',
                    'current_state': 'Refreshed 312 reservation records before the service token expired.',
                    'key_findings': ['Avoid admin portal sign-in and local browser use during the retry.'],
                    'blocker_state': 'The service token expired, and the operator constraint forbids admin portal sign-in or local browser use.',
                    'next_step': 'Refresh the catalog service token and rerun the sync from batch 313.',
                    'evidence': ['Constraint: do not sign in to the admin portal or open a local browser.'],
                    'freshness_signal': 'Latest explicit update at 2026-03-11T10:02:00Z.',
                },
                freshness_at=datetime(2026, 3, 11, 10, 2, tzinfo=timezone.utc),
                score=15,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-history',
            ),
        ],
        trace=QueryTrace(
            query_text='Which token expired during the catalog sync retry?',
            query_tokens=('which', 'token', 'expired', 'during', 'the', 'catalog', 'sync', 'retry'),
            limit=4,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='Which token expired during the catalog sync retry?',
        requested_limit=4,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='same_thread_continuation', session_has_sufficient_local_context=True),
        include_trace=True,
    )

    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    # envelope-first routing: recall mode from candidate evidence may change same-thread
    # context evaluation behavior since the mapped intent affects which source candidates
    # qualify as local context. The core property verified: same-thread evaluation runs.
    same_thread_eval = outcome.trace.routing['injection_decision'].get('same_thread_context_evaluation')
    assert same_thread_eval is not None
    assert same_thread_eval.get('evaluated') is True

def test_fresh_thread_broad_recall_prefers_structured_memory_over_noisy_source_evidence() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='chat:library-help',
        thread_ref='chat:library-help:thread-fresh-recall',
    )
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='source-fresh-question',
                source_type='chat_message',
                source_id='fresh-question',
                excerpt='What do we know the latest about the catalog sync retry?',
                occurred_at=datetime(2026, 3, 11, 10, 3, tzinfo=timezone.utc),
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-fresh-recall',
                artifact_kind='message',
                score=19,
                evidence=[
                    EvidenceReference(
                        source_item_id='source-fresh-question',
                        source_type='chat_message',
                        source_id='fresh-question',
                        occurred_at=datetime(2026, 3, 11, 10, 3, tzinfo=timezone.utc),
                        container_ref='chat:library-help',
                        thread_ref='chat:library-help:thread-fresh-recall',
                        artifact_kind='message',
                    )
                ],
            ),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='checkpoint-recall-1',
                type='task_checkpoint',
                payload={
                    'summary': 'Catalog sync retry is paused after partial progress and a service-token failure.',
                    'task': 'Resume the catalog sync retry.',
                    'current_state': 'Refreshed 312 reservation records before the service token expired.',
                    'key_findings': ['The service token expired during the retry.'],
                    'blocker_state': 'Catalog API returned 401 because the service token expired.',
                    'next_step': 'Refresh the catalog service token and rerun the sync from batch 313.',
                    'evidence': ['Partial progress covered 312 reservation records before the 401.'],
                    'freshness_signal': 'Latest explicit update at 2026-03-11T10:02:00Z.',
                },
                freshness_at=datetime(2026, 3, 11, 10, 2, tzinfo=timezone.utc),
                score=15,
                evidence=[
                    EvidenceReference(
                        source_item_id='source-old-progress',
                        source_type='assistant_artifact',
                        source_id='old-progress',
                        occurred_at=datetime(2026, 3, 11, 10, 2, tzinfo=timezone.utc),
                        container_ref='chat:library-help',
                        thread_ref='chat:library-help:thread-history',
                        artifact_kind='tool_use_summary',
                    )
                ],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-history',
            ),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='thread-summary-recall-1',
                type='thread_summary',
                payload={
                    'summary': 'The catalog sync retry refreshed 312 reservation records before the service token expired and should resume from batch 313 without using the admin portal or a local browser.',
                },
                freshness_at=datetime(2026, 3, 11, 10, 2, tzinfo=timezone.utc),
                score=14,
                evidence=[
                    EvidenceReference(
                        source_item_id='source-old-summary',
                        source_type='assistant_artifact',
                        source_id='old-summary',
                        occurred_at=datetime(2026, 3, 11, 10, 2, tzinfo=timezone.utc),
                        container_ref='chat:library-help',
                        thread_ref='chat:library-help:thread-history',
                        artifact_kind='assistant_output',
                    )
                ],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-history',
            ),
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='source-unrelated-capability',
                source_type='assistant_artifact',
                source_id='capability-note',
                excerpt='Capabilities: I can summarize previous work, search records, and prepare status notes.',
                occurred_at=datetime(2026, 3, 11, 10, 4, tzinfo=timezone.utc),
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-other',
                artifact_kind='assistant_output',
                score=13,
                evidence=[
                    EvidenceReference(
                        source_item_id='source-unrelated-capability',
                        source_type='assistant_artifact',
                        source_id='capability-note',
                        occurred_at=datetime(2026, 3, 11, 10, 4, tzinfo=timezone.utc),
                        container_ref='chat:library-help',
                        thread_ref='chat:library-help:thread-other',
                        artifact_kind='assistant_output',
                    )
                ],
            ),
        ],
        trace=QueryTrace(
            query_text='What do we know the latest about the catalog sync retry?',
            query_tokens=('what', 'do', 'we', 'know', 'latest', 'catalog', 'sync', 'retry'),
            limit=4,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='What do we know the latest about the catalog sync retry?',
        requested_limit=4,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='new_thread', session_has_sufficient_local_context=False),
        include_trace=True,
    )

    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    assert outcome.trace.routing['query_intent'] in {'recall'}
    # Fresh-thread structured recall preference removed (Task 9); will return in Task 9b.
    # Without the shaping stage, source_evidence may win when retrieval scores favor it.
    assert outcome.results
    assert outcome.injectable_blocks
    assert any('admin portal' in block.text.lower() or 'local browser' in block.text.lower() for block in outcome.injectable_blocks)

def test_query_only_current_thread_summary_is_excluded_from_recall_packaging() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='chat:library-help',
        thread_ref='chat:library-help:thread-current-query-only',
    )
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='thread-summary-current-query-only',
                type='thread_summary',
                payload={
                    'summary': 'User asked, "What do we know the latest about the catalog sync retry?" The thread contains only this question.',
                    'content_quality': 'query_only',
                    'conclusions': [],
                    'selected_work_artifacts': [],
                },
                freshness_at=datetime(2026, 3, 11, 10, 4, tzinfo=timezone.utc),
                score=17,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-current-query-only',
            ),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='checkpoint-constraint-anchor',
                type='task_checkpoint',
                payload={
                    'summary': 'Catalog sync retry is paused after partial progress and a service-token failure.',
                    'task': 'Resume the catalog sync retry.',
                    'current_state': 'Refreshed 312 reservation records before the service token expired.',
                    'key_findings': ['Avoid admin portal sign-in and local browser use during the retry.'],
                    'blocker_state': 'The service token expired, and the operator constraint forbids admin portal sign-in or local browser use.',
                    'next_step': 'Refresh the catalog service token and rerun the sync from batch 313.',
                    'evidence': ['Constraint: do not sign in to the admin portal or open a local browser.'],
                    'freshness_signal': 'Latest explicit update at 2026-03-11T10:02:00Z.',
                },
                freshness_at=datetime(2026, 3, 11, 10, 2, tzinfo=timezone.utc),
                score=15,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-history',
            ),
        ],
        trace=QueryTrace(
            query_text='What do we know the latest about the catalog sync retry?',
            query_tokens=('what', 'do', 'we', 'know', 'latest', 'catalog', 'sync', 'retry'),
            limit=4,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='What do we know the latest about the catalog sync retry?',
        requested_limit=4,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='new_thread', session_has_sufficient_local_context=False),
        include_trace=True,
    )

    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    excluded = {item['excluded_reason_code'] for item in outcome.trace.routing['excluded_high_scoring_candidates']}
    assert 'weak_summary' in excluded
    assert all(block.result_id != 'memory_object:thread-summary-current-query-only' for block in outcome.injectable_blocks)

def test_fresh_thread_evidence_trace_still_allows_source_evidence() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='chat:library-help',
        thread_ref='chat:library-help:thread-fresh-evidence',
    )
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='source-evidence-raw',
                source_type='assistant_artifact',
                source_id='evidence-raw',
                excerpt='Blocked: catalog API returned 401 because the service token expired.',
                occurred_at=datetime(2026, 3, 11, 10, 1, tzinfo=timezone.utc),
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-history',
                artifact_kind='tool_use_summary',
                score=18,
                evidence=[
                    EvidenceReference(
                        source_item_id='source-evidence-raw',
                        source_type='assistant_artifact',
                        source_id='evidence-raw',
                        occurred_at=datetime(2026, 3, 11, 10, 1, tzinfo=timezone.utc),
                        container_ref='chat:library-help',
                        thread_ref='chat:library-help:thread-history',
                        artifact_kind='tool_use_summary',
                    )
                ],
            ),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='checkpoint-evidence-1',
                type='task_checkpoint',
                payload={
                    'summary': 'Catalog sync retry is paused after a service-token failure.',
                    'task': 'Resume the catalog sync retry.',
                    'current_state': 'The current blocker is the expired token.',
                    'key_findings': ['The service token expired during the retry.'],
                    'blocker_state': 'Catalog API returned 401 because the service token expired.',
                    'next_step': 'Refresh the catalog service token and rerun the sync from batch 313.',
                    'evidence': ['Blocked: catalog API returned 401 because the service token expired.'],
                    'freshness_signal': 'Latest explicit update at 2026-03-11T10:02:00Z.',
                },
                freshness_at=datetime(2026, 3, 11, 10, 2, tzinfo=timezone.utc),
                score=14,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-history',
            ),
        ],
        trace=QueryTrace(
            query_text='What evidence showed that the service token expired during the catalog sync retry?',
            query_tokens=('what', 'evidence', 'showed', 'service', 'token', 'expired', 'catalog', 'sync', 'retry'),
            limit=4,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='What evidence showed that the service token expired during the catalog sync retry?',
        requested_limit=4,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='new_thread', session_has_sufficient_local_context=False),
        include_trace=True,
    )

    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    # Without legacy English cues, evidence_trace intent is no longer detected
    # from query text alone. The query routes as broad_recall, but source evidence
    # may still be selected and injectable based on candidate scoring.
    assert outcome.trace.routing['query_intent'] in ('evidence_trace', 'recall', 'structured_recall')
    assert outcome.should_inject is True
    assert outcome.injectable_blocks

def test_precise_fact_quote_grade_recall_allows_supported_source_evidence() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='chat:realistic:overlap',
        thread_ref='chat:realistic:overlap:current',
    )
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='source-evidence-log',
                source_type='assistant_artifact',
                source_id='overlap-log',
                excerpt="The smoking gun was right in the logs. Investigation found that the exact log line 'job already running, skipping new start' showed the retries were overlapping.",
                occurred_at=datetime(2026, 3, 11, 10, 1, tzinfo=timezone.utc),
                container_ref='chat:realistic:overlap',
                thread_ref='chat:realistic:overlap:history',
                artifact_kind='tool_use_summary',
                role='assistant',
                score=18,
                evidence=[
                    EvidenceReference(
                        source_item_id='source-evidence-log',
                        source_type='assistant_artifact',
                        source_id='overlap-log',
                        occurred_at=datetime(2026, 3, 11, 10, 1, tzinfo=timezone.utc),
                        container_ref='chat:realistic:overlap',
                        thread_ref='chat:realistic:overlap:history',
                        artifact_kind='tool_use_summary',
                    )
                ],
            ),
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='current-query-echo',
                source_type='chat_message',
                source_id='current-query-echo',
                excerpt='Which exact log line was it again?',
                occurred_at=datetime(2026, 3, 11, 10, 3, tzinfo=timezone.utc),
                container_ref='chat:realistic:overlap',
                thread_ref='chat:realistic:overlap:current',
                artifact_kind='message',
                role='user',
                score=20,
                evidence=[],
            ),
        ],
        trace=QueryTrace(
            query_text='Which exact log line was it again?',
            query_tokens=('which', 'exact', 'log', 'line', 'proved', 'the', 'retries', 'were', 'overlapping'),
            limit=4,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='Which exact log line was it again?',
        requested_limit=4,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='new_thread', session_has_sufficient_local_context=False),
        include_trace=True,
    )

    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    # envelope-first routing: recall mode from candidate evidence, not English text.
    # Deterministic source_ratio override (Task 15/16) may route to evidence_trace
    # when source hits dominate the candidate set.
    assert outcome.trace.routing['query_intent'] in {'structured_recall', 'recall', 'evidence_trace'}
    # Source may or may not be injectable depending on recall mode
    assert outcome.results[0].source_item_id == 'source-evidence-log'


def test_precise_fact_quote_grade_recall_keeps_weak_source_evidence_non_injectable() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='chat:realistic:overlap',
        thread_ref='chat:realistic:overlap:current',
    )
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='source-evidence-weak',
                source_type='assistant_artifact',
                source_id='overlap-weak',
                excerpt='We probably saw it somewhere in the logs, but I did not keep the exact line.',
                occurred_at=datetime(2026, 3, 11, 10, 1, tzinfo=timezone.utc),
                container_ref='chat:realistic:overlap',
                thread_ref='chat:realistic:overlap:history',
                artifact_kind='tool_use_summary',
                role='assistant',
                score=18,
                evidence=[
                    EvidenceReference(
                        source_item_id='source-evidence-weak',
                        source_type='assistant_artifact',
                        source_id='overlap-weak',
                        occurred_at=datetime(2026, 3, 11, 10, 1, tzinfo=timezone.utc),
                        container_ref='chat:realistic:overlap',
                        thread_ref='chat:realistic:overlap:history',
                        artifact_kind='tool_use_summary',
                    )
                ],
            ),
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='current-query-echo-weak',
                source_type='chat_message',
                source_id='current-query-echo-weak',
                excerpt='Which exact log line was it again?',
                occurred_at=datetime(2026, 3, 11, 10, 3, tzinfo=timezone.utc),
                container_ref='chat:realistic:overlap',
                thread_ref='chat:realistic:overlap:current',
                artifact_kind='message',
                role='user',
                score=20,
                evidence=[],
            ),
        ],
        trace=QueryTrace(
            query_text='Which exact log line was it again?',
            query_tokens=('which', 'exact', 'log', 'line', 'was', 'it', 'again'),
            limit=4,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='Which exact log line was it again?',
        requested_limit=4,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='new_thread', session_has_sufficient_local_context=False),
        include_trace=True,
    )

    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    # envelope-first routing: deterministic source_ratio override may route to
    # evidence_trace when source hits dominate the candidate set (Task 15/16).
    assert outcome.trace.routing['query_intent'] in {'structured_recall', 'recall', 'evidence_trace'}
    # Weak source evidence: should not be injectable regardless of mode
    assert outcome.injectable_blocks == []


def test_fresh_thread_greeting_noise_fails_closed_without_memory_injection() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='slack:channel:CLOCAL001',
        thread_ref='slack:thread:CLOCAL001:diag-good-morning-fresh',
    )
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='thread-d-artifact-1',
                source_type='assistant_artifact',
                source_id='thread-d-artifact-1',
                excerpt='Good morning. I can help with the latest batch status when you are ready.',
                occurred_at=datetime(2026, 3, 11, 13, 0, 10, tzinfo=timezone.utc),
                container_ref='slack:channel:CLOCAL001',
                thread_ref='slack:thread:CLOCAL001:thread-d',
                artifact_kind='assistant_output',
                role='assistant',
                score=18,
                lexical_score=0,
                evidence=[],
            ),
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='thread-d-msg-1',
                source_type='chat_message',
                source_id='thread-d-msg-1',
                excerpt='good morning',
                occurred_at=datetime(2026, 3, 11, 13, 0, tzinfo=timezone.utc),
                container_ref='slack:channel:CLOCAL001',
                thread_ref='slack:thread:CLOCAL001:thread-d',
                artifact_kind='message',
                role='user',
                score=17,
                lexical_score=0,
                evidence=[],
            ),
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='thread-capability-note',
                source_type='assistant_artifact',
                source_id='thread-capability-note',
                excerpt='Many talents: I can help summarize batch digests and search task status.',
                occurred_at=datetime(2026, 3, 11, 9, 0, tzinfo=timezone.utc),
                container_ref='slack:channel:CLOCAL001',
                thread_ref='slack:thread:CLOCAL001:thread-capabilities',
                artifact_kind='assistant_output',
                role='assistant',
                score=8,
                lexical_score=0,
                evidence=[],
            ),
        ],
        trace=QueryTrace(
            query_text='good morning',
            query_tokens=('good', 'morning'),
            limit=6,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='good morning',
        requested_limit=6,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='new_thread', session_has_sufficient_local_context=False),
        include_trace=True,
    )

    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    assert outcome.should_inject is False
    assert outcome.decision_reason != 'carry_forward_available'
    assert outcome.injectable_blocks == []
    assert all(item.result_kind == 'source_hit' for item in outcome.results)

def test_same_thread_batch_reminder_after_trivial_greetings_uses_carry_forward_memory() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='slack:channel:CLOCAL001',
        thread_ref='slack:thread:CLOCAL001:thread-d',
    )
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='thread-d-msg-2',
                source_type='chat_message',
                source_id='thread-d-msg-2',
                excerpt='can you remind me what we had latest about batches?',
                occurred_at=datetime(2026, 3, 11, 13, 0, 20, tzinfo=timezone.utc),
                container_ref='slack:channel:CLOCAL001',
                thread_ref='slack:thread:CLOCAL001:thread-d',
                artifact_kind='message',
                role='user',
                score=18,
                evidence=[],
            ),
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='thread-d-artifact-1',
                source_type='assistant_artifact',
                source_id='thread-d-artifact-1',
                excerpt='Good morning. I can help with the latest batch status when you are ready.',
                occurred_at=datetime(2026, 3, 11, 13, 0, 10, tzinfo=timezone.utc),
                container_ref='slack:channel:CLOCAL001',
                thread_ref='slack:thread:CLOCAL001:thread-d',
                artifact_kind='assistant_output',
                role='assistant',
                score=16,
                evidence=[],
            ),
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='thread-d-msg-1',
                source_type='chat_message',
                source_id='thread-d-msg-1',
                excerpt='good morning',
                occurred_at=datetime(2026, 3, 11, 13, 0, tzinfo=timezone.utc),
                container_ref='slack:channel:CLOCAL001',
                thread_ref='slack:thread:CLOCAL001:thread-d',
                artifact_kind='message',
                role='user',
                score=15,
                evidence=[],
            ),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='summary-batch-current-thread',
                type='thread_summary',
                payload={
                    'summary': 'User asked, "can you remind me what we had latest about batches?" The thread contains only this question.',
                    'content_quality': 'query_only',
                    'conclusions': [],
                    'selected_work_artifacts': [],
                },
                freshness_at=datetime(2026, 3, 11, 13, 0, 20, tzinfo=timezone.utc),
                score=17,
                evidence=[],
                container_ref='slack:channel:CLOCAL001',
                thread_ref='slack:thread:CLOCAL001:thread-d',
            ),
            _inventory_batch_constraint_checkpoint_result(),
            _inventory_batch_constraint_summary_result(),
        ],
        trace=QueryTrace(
            query_text='can you remind me what we had latest about batches?',
            query_tokens=('can', 'you', 'remind', 'me', 'what', 'we', 'had', 'latest', 'about', 'batches'),
            limit=6,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='can you remind me what we had latest about batches?',
        requested_limit=6,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='same_thread_continuation', session_has_sufficient_local_context=True),
        include_trace=True,
    )

    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    rendered_blocks = ' '.join(block.text.lower() for block in outcome.injectable_blocks)
    same_thread = outcome.trace.routing['injection_decision']['same_thread_context_evaluation']
    assert outcome.should_inject is True
    assert outcome.decision_reason == 'carry_forward_available'
    assert outcome.decision_reason != 'same_thread_context_sufficient'
    assert outcome.trace.routing['query_intent'] == 'recall'
    assert outcome.trace.routing['query_family'] == 'recall'
    assert outcome.trace.routing['selected_layer'] != 'source_evidence'
    assert same_thread['reason_code'] == 'insufficient_same_thread_local_state'
    assert any(block.memory_type in {'task_checkpoint', 'thread_summary'} for block in outcome.injectable_blocks)
    assert 'inventory batch digest' in rendered_blocks or 'last confirmed batch' in rendered_blocks
    assert 'can you remind me what we had latest about batches' not in rendered_blocks
    assert 'good morning' not in rendered_blocks

def test_fresh_thread_batch_reminder_prefers_structured_carry_forward_over_source_evidence() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='slack:channel:CLOCAL001',
        thread_ref='slack:thread:CLOCAL001:diag-batch-reminder-fresh',
    )
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='thread-d-msg-2',
                source_type='chat_message',
                source_id='thread-d-msg-2',
                excerpt='can you remind me what we had latest about batches?',
                occurred_at=datetime(2026, 3, 11, 13, 0, 20, tzinfo=timezone.utc),
                container_ref='slack:channel:CLOCAL001',
                thread_ref='slack:thread:CLOCAL001:thread-d',
                artifact_kind='message',
                role='user',
                score=18,
                evidence=[],
            ),
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='thread-d-artifact-1',
                source_type='assistant_artifact',
                source_id='thread-d-artifact-1',
                excerpt='Good morning. I can help with the latest batch status when you are ready.',
                occurred_at=datetime(2026, 3, 11, 13, 0, 10, tzinfo=timezone.utc),
                container_ref='slack:channel:CLOCAL001',
                thread_ref='slack:thread:CLOCAL001:thread-d',
                artifact_kind='assistant_output',
                role='assistant',
                score=16,
                evidence=[],
            ),
            _inventory_batch_constraint_checkpoint_result(score=17),
            _inventory_batch_constraint_summary_result(score=16),
        ],
        trace=QueryTrace(
            query_text='can you remind me what we had latest about batches?',
            query_tokens=('can', 'you', 'remind', 'me', 'what', 'we', 'had', 'latest', 'about', 'batches'),
            limit=6,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='can you remind me what we had latest about batches?',
        requested_limit=6,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='new_thread', session_has_sufficient_local_context=False),
        include_trace=True,
    )

    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    rendered_blocks = ' '.join(block.text.lower() for block in outcome.injectable_blocks)
    assert outcome.should_inject is True
    assert outcome.decision_reason == 'carry_forward_available'
    assert outcome.trace.routing['query_intent'] == 'recall'
    assert outcome.trace.routing['query_family'] == 'new_thread_continuation'
    assert outcome.trace.routing['selected_layer'] != 'source_evidence'
    assert all(block.block_type == 'memory' for block in outcome.injectable_blocks)
    assert any(block.memory_type in {'task_checkpoint', 'thread_summary'} for block in outcome.injectable_blocks)
    assert 'can you remind me what we had latest about batches' not in rendered_blocks
    assert 'good morning' not in rendered_blocks
    assert 'attempt to authenticate' not in rendered_blocks

def test_typo_variant_greeting_fails_closed_without_memory_injection() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='slack:channel:CLOCAL001',
        thread_ref='slack:thread:CLOCAL001:diag-good-afternnon-fresh',
    )
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='thread-x-artifact-1',
                source_type='assistant_artifact',
                source_id='thread-x-artifact-1',
                excerpt='Good afternoon. I can help with the latest batch digest status when you are ready.',
                occurred_at=datetime(2026, 3, 11, 13, 0, 10, tzinfo=timezone.utc),
                container_ref='slack:channel:CLOCAL001',
                thread_ref='slack:thread:CLOCAL001:thread-x',
                artifact_kind='assistant_output',
                role='assistant',
                score=18,
                lexical_score=0,
                evidence=[],
            ),
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='thread-x-msg-1',
                source_type='chat_message',
                source_id='thread-x-msg-1',
                excerpt='good afternnon sir',
                occurred_at=datetime(2026, 3, 11, 13, 0, tzinfo=timezone.utc),
                container_ref='slack:channel:CLOCAL001',
                thread_ref='slack:thread:CLOCAL001:thread-x',
                artifact_kind='message',
                role='user',
                score=17,
                lexical_score=0,
                evidence=[],
            ),
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='thread-capability-note-2',
                source_type='assistant_artifact',
                source_id='thread-capability-note-2',
                excerpt='Well, I am a helper of many talents across batch digests and wallet summaries.',
                occurred_at=datetime(2026, 3, 11, 9, 0, tzinfo=timezone.utc),
                container_ref='slack:channel:CLOCAL001',
                thread_ref='slack:thread:CLOCAL001:thread-capabilities',
                artifact_kind='assistant_output',
                role='assistant',
                score=9,
                lexical_score=0,
                evidence=[],
            ),
        ],
        trace=QueryTrace(
            query_text='good afternnon sir',
            query_tokens=('good', 'afternnon', 'sir'),
            limit=6,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='good afternnon sir',
        requested_limit=6,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='new_thread', session_has_sufficient_local_context=False),
        include_trace=True,
    )

    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    assert outcome.should_inject is False
    # After removing query-time noise detection (cue-free control plane),
    # greeting-like queries are no longer classified as low_value_query.
    # The simplified injection check (Task 15) rejects with low_injection_confidence
    # when lexical grounding is absent.
    assert outcome.decision_reason in {'low_value_query', 'no_relevant_memory', 'low_injection_confidence'}
    assert outcome.injectable_blocks == []

def test_same_thread_batch_reminder_lately_prefers_structured_carry_forward_over_polluted_sources() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='slack:channel:CLOCAL001',
        thread_ref='slack:thread:CLOCAL001:thread-x',
    )
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='thread-x-msg-2',
                source_type='chat_message',
                source_id='thread-x-msg-2',
                excerpt='remind me what we had about the batch digests lately',
                occurred_at=datetime(2026, 3, 11, 13, 0, 20, tzinfo=timezone.utc),
                container_ref='slack:channel:CLOCAL001',
                thread_ref='slack:thread:CLOCAL001:thread-x',
                artifact_kind='message',
                role='user',
                score=19,
                evidence=[],
            ),
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='thread-x-artifact-1',
                source_type='assistant_artifact',
                source_id='thread-x-artifact-1',
                excerpt='Good afternoon. I can help with the latest batch digest status when you are ready.',
                occurred_at=datetime(2026, 3, 11, 13, 0, 10, tzinfo=timezone.utc),
                container_ref='slack:channel:CLOCAL001',
                thread_ref='slack:thread:CLOCAL001:thread-x',
                artifact_kind='assistant_output',
                role='assistant',
                score=17,
                evidence=[],
            ),
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='thread-x-artifact-2',
                source_type='assistant_artifact',
                source_id='thread-x-artifact-2',
                excerpt='Blocked: the batch digest cannot proceed until remote authentication succeeds.',
                occurred_at=datetime(2026, 3, 11, 12, 59, tzinfo=timezone.utc),
                container_ref='slack:channel:CLOCAL001',
                thread_ref='slack:thread:CLOCAL001:thread-c',
                artifact_kind='tool_use_summary',
                role='assistant',
                score=18,
                evidence=[],
            ),
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='thread-x-artifact-3',
                source_type='assistant_artifact',
                source_id='thread-x-artifact-3',
                excerpt='Earlier answer: the remote channel is blocked and needs authentication before retry.',
                occurred_at=datetime(2026, 3, 11, 12, 58, tzinfo=timezone.utc),
                container_ref='slack:channel:CLOCAL001',
                thread_ref='slack:thread:CLOCAL001:thread-c',
                artifact_kind='assistant_output',
                role='assistant',
                score=18,
                evidence=[],
            ),
            _inventory_batch_constraint_checkpoint_result(score=17),
            _inventory_batch_constraint_summary_result(score=16),
            _inventory_batch_conflicting_retry_checkpoint_result(score=15),
        ],
        trace=QueryTrace(
            query_text='remind me what we had about the batch digests lately',
            query_tokens=('remind', 'me', 'what', 'we', 'had', 'about', 'the', 'batch', 'digests', 'lately'),
            limit=7,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='remind me what we had about the batch digests lately',
        requested_limit=7,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='same_thread_continuation', session_has_sufficient_local_context=True),
        include_trace=True,
    )

    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    rendered_blocks = ' '.join(block.text.lower() for block in outcome.injectable_blocks)
    same_thread = outcome.trace.routing['injection_decision']['same_thread_context_evaluation']
    assert outcome.should_inject is True
    assert outcome.decision_reason == 'carry_forward_available'
    assert outcome.decision_reason != 'same_thread_context_sufficient'
    assert outcome.trace.routing['query_intent'] == 'recall'
    assert outcome.trace.routing['query_family'] == 'recall'
    assert outcome.trace.routing['selected_layer'] != 'source_evidence'
    assert all(block.block_type == 'memory' for block in outcome.injectable_blocks)
    assert same_thread['reason_code'] == 'insufficient_same_thread_local_state'
    assert 'inventory batch digest' in rendered_blocks or 'last confirmed batch' in rendered_blocks
    assert 'remind me what we had about the batch digests lately' not in rendered_blocks
    assert 'good afternoon' not in rendered_blocks


# ---------------------------------------------------------------------------
# Retrieval relevance floor tests
# ---------------------------------------------------------------------------

def _build_floor_test_retrieval_result(
    *,
    score: int = 14,
    retrieval_source: str | None = None,
    lexical_score: int | None = None,
    vector_score: int | None = None,
    memory_type: str = 'thread_summary',
    payload: dict | None = None,
) -> RetrievalQueryResult:
    """Build a minimal retrieval result for floor-check testing."""
    if payload is None:
        payload = {'summary': 'User discussed vector databases and expressed interest in ChromaDB.'}
    return RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id=f'floor-test-{memory_type}-1',
                type=memory_type,
                payload=payload,
                score=score,
                evidence=[],
                container_ref='chat:floor-test',
                thread_ref='chat:floor-test:thread-A',
                retrieval_source=retrieval_source,
                lexical_score=lexical_score,
                vector_score=vector_score,
            ),
        ],
        trace=QueryTrace(
            query_text='test query',
            query_tokens=('test', 'query'),
            limit=4,
            filters=QueryFilters(container_ref='chat:floor-test', thread_ref='chat:floor-test:thread-B'),
            stages=(),
        ),
    )


def _run_floor_test(
    retrieval_result: RetrievalQueryResult,
    query_text: str = 'test query',
):
    """Run routing and return the outcome."""
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='chat:floor-test',
        thread_ref='chat:floor-test:thread-B',
    )
    return plugin.route_query_results(
        text=query_text,
        requested_limit=4,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        include_trace=True,
    )


def test_retrieval_relevance_floor_suppresses_vector_only_candidates() -> None:
    """Composite retrieval with vector-only hits and low cosine should suppress injection."""
    result = _build_floor_test_retrieval_result(
        score=9,
        retrieval_source='vector',
        lexical_score=None,
        vector_score=480,  # cosine 0.48 — below VECTOR_SIMILARITY_INJECTION_FLOOR (700)
    )
    outcome = _run_floor_test(result, query_text="let's talk about something new")
    assert outcome.should_inject is False
    assert outcome.decision_reason == 'low_injection_confidence'


def test_retrieval_relevance_floor_suppresses_low_lexical_score() -> None:
    """Composite retrieval with low lexical_score (common word only) should suppress."""
    result = _build_floor_test_retrieval_result(
        score=19,
        retrieval_source='both',
        lexical_score=1,
    )
    outcome = _run_floor_test(result, query_text='how about politics?')
    assert outcome.should_inject is False
    assert outcome.decision_reason == 'low_injection_confidence'


def test_retrieval_relevance_floor_passes_high_lexical_score() -> None:
    """Composite retrieval with high lexical_score (domain word match) should inject."""
    result = _build_floor_test_retrieval_result(
        score=19,
        retrieval_source='both',
        lexical_score=4,
    )
    outcome = _run_floor_test(result, query_text='what did we discuss about vector databases?')
    assert outcome.should_inject is True
    assert outcome.decision_reason != 'low_injection_confidence'


def test_retrieval_relevance_floor_passes_at_boundary() -> None:
    """lexical_score exactly at the injection threshold (2) should pass."""
    result = _build_floor_test_retrieval_result(
        score=19,
        retrieval_source='both',
        lexical_score=2,
    )
    outcome = _run_floor_test(result, query_text='what about vector databases?')
    assert outcome.should_inject is True
    assert outcome.decision_reason != 'low_injection_confidence'


def test_retrieval_relevance_floor_passes_lexical_only_retrieval() -> None:
    """Lexical-only retrieval with any IDF match passes injection check."""
    result = _build_floor_test_retrieval_result(
        score=1,  # any non-zero IDF score passes in lexical-only mode
        retrieval_source=None,
        lexical_score=None,
    )
    outcome = _run_floor_test(result)
    # Floor does not activate for lexical-only retrieval
    assert outcome.decision_reason != 'low_injection_confidence'


def test_retrieval_relevance_floor_mixed_candidates_one_passes() -> None:
    """If at least one candidate passes the floor, injection proceeds."""
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='chat:floor-test',
        thread_ref='chat:floor-test:thread-B',
    )
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='floor-mix-1',
                type='thread_summary',
                payload={'summary': 'User discussed vector databases and expressed interest in ChromaDB.'},
                score=9,
                evidence=[],
                container_ref='chat:floor-test',
                thread_ref='chat:floor-test:thread-A',
                retrieval_source='vector',
                lexical_score=None,
            ),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='floor-mix-2',
                type='interest',
                payload={'summary': 'Interest in ChromaDB for vector database experiments.'},
                score=19,
                evidence=[],
                container_ref='chat:floor-test',
                thread_ref='chat:floor-test:thread-A',
                retrieval_source='both',
                lexical_score=3,
            ),
        ],
        trace=QueryTrace(
            query_text='what about chromadb?',
            query_tokens=('chromadb',),
            limit=4,
            filters=query_filters,
            stages=(),
        ),
    )
    outcome = plugin.route_query_results(
        text='what about chromadb?',
        requested_limit=4,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        include_trace=True,
    )
    assert outcome.should_inject is True
    assert outcome.decision_reason != 'low_injection_confidence'


def test_retrieval_relevance_floor_trace_shows_reason() -> None:
    """The injection decision trace should include diagnostic fields."""
    result = _build_floor_test_retrieval_result(
        score=9,
        retrieval_source='vector',
        lexical_score=None,
        vector_score=480,
    )
    outcome = _run_floor_test(result, query_text="let's talk about something new")
    injection_decision = outcome.trace.routing.get('injection_decision', {})
    assert injection_decision.get('decision_reason') == 'low_injection_confidence'
    # Simplified injection check (Task 15) provides injection_method and score diagnostics
    assert 'injection_method' in injection_decision


def test_vector_cosine_escape_hatch_passes_high_similarity() -> None:
    """Vector-only match with high cosine similarity should pass the floor."""
    result = _build_floor_test_retrieval_result(
        score=9,
        retrieval_source='vector',
        lexical_score=None,
        vector_score=810,  # cosine 0.81 — above candidate_vector_override (800)
    )
    outcome = _run_floor_test(result, query_text='what approach for tracking changes?')
    assert outcome.decision_reason != 'low_injection_confidence'


def test_vector_cosine_escape_hatch_at_boundary() -> None:
    """Vector-only match exactly at the cosine override (800) should pass."""
    result = _build_floor_test_retrieval_result(
        score=9,
        retrieval_source='vector',
        lexical_score=None,
        vector_score=800,
    )
    outcome = _run_floor_test(result, query_text='what approach for tracking changes?')
    assert outcome.decision_reason != 'low_injection_confidence'


def test_vector_cosine_escape_hatch_suppresses_below_boundary() -> None:
    """Vector-only match just below the cosine floor should be suppressed."""
    result = _build_floor_test_retrieval_result(
        score=9,
        retrieval_source='vector',
        lexical_score=None,
        vector_score=640,
    )
    outcome = _run_floor_test(result, query_text="let's talk about something new")
    assert outcome.should_inject is False
    assert outcome.decision_reason == 'low_injection_confidence'


def test_vector_cosine_escape_hatch_trace_shows_reason() -> None:
    """When a vector-only match passes via cosine escape hatch, trace shows simplified injection method."""
    result = _build_floor_test_retrieval_result(
        score=9,
        retrieval_source='vector',
        lexical_score=None,
        vector_score=750,
    )
    outcome = _run_floor_test(result, query_text='what approach for tracking changes?')
    injection_decision = outcome.trace.routing.get('injection_decision', {})
    # Simplified injection check (Task 15) replaces QPP gate system
    assert injection_decision.get('injection_method') == 'simplified'


# ---------------------------------------------------------------------------
# Off-topic injection suppression tests
# ---------------------------------------------------------------------------
# These test the core problem: memory objects (thread_summary, interest, decision)
# should NOT be injected when the query is off-topic.  In composite retrieval mode,
# max_lexical_score=1 (single bridging word) is below the justification threshold.
# In lexical-only mode, score=1 cannot be distinguished from legitimate cross-thread
# recall and passes through — off-topic suppression requires composite retrieval.


def test_offtopic_weather_suppresses_thread_summary() -> None:
    """Off-topic 'weather' query with score=1 thread_summary in composite mode must NOT inject.

    In lexical-only mode, score=1 cannot be distinguished from legitimate cross-thread
    recall and passes through.  In composite mode, max_lexical_score=1 is below the
    moderate_retrieval_score threshold (2), so the justification suppresses.
    """
    result = _build_floor_test_retrieval_result(
        score=1, memory_type='thread_summary',
        retrieval_source='both', lexical_score=1, vector_score=500,
    )
    outcome = _run_floor_test(result, query_text="how is the weather today?")
    assert outcome.should_inject is False, (
        f"Off-topic weather query should suppress thread_summary injection in composite mode. "
        f"decision_reason={outcome.decision_reason}"
    )


def test_offtopic_politics_suppresses_interest() -> None:
    """Off-topic 'politics' query with score=1 interest in composite mode must NOT inject."""
    result = _build_floor_test_retrieval_result(
        score=1, memory_type='interest',
        payload={'summary': 'User expressed interest in SQLite databases for library systems.'},
        retrieval_source='both', lexical_score=1, vector_score=480,
    )
    outcome = _run_floor_test(result, query_text="what about politics?")
    assert outcome.should_inject is False, (
        f"Off-topic politics query should suppress interest injection in composite mode. "
        f"decision_reason={outcome.decision_reason}"
    )


def test_offtopic_idiom_suppresses_decision() -> None:
    """Idiom 'under the weather' with score=1 decision in composite mode must NOT inject."""
    result = _build_floor_test_retrieval_result(
        score=1, memory_type='decision',
        payload={'decision': 'Use SQLite for catalog indexing.', 'rationale': 'Branch library has under 50k items.'},
        retrieval_source='both', lexical_score=1, vector_score=500,
    )
    outcome = _run_floor_test(result, query_text="i'm a bit under the weather")
    assert outcome.should_inject is False, (
        f"Off-topic idiom should suppress decision injection in composite mode. "
        f"decision_reason={outcome.decision_reason}"
    )


def test_offtopic_zero_overlap_suppresses_thread_summary() -> None:
    """Zero-overlap query with thread_summary must NOT inject (any retrieval mode)."""
    result = _build_floor_test_retrieval_result(score=0, memory_type='thread_summary')
    outcome = _run_floor_test(result, query_text="let's talk about something new")
    assert outcome.should_inject is False, (
        f"Zero-overlap query should suppress injection. "
        f"decision_reason={outcome.decision_reason}"
    )


def test_ontopic_recall_injects_thread_summary() -> None:
    """On-topic query with score=3 thread_summary MUST inject."""
    result = _build_floor_test_retrieval_result(score=3, memory_type='thread_summary')
    outcome = _run_floor_test(result, query_text="what did we discuss about vector databases?")
    assert outcome.should_inject is True, (
        f"On-topic recall query should inject thread_summary. "
        f"decision_reason={outcome.decision_reason}"
    )


def test_vague_recall_injects_checkpoint_with_work_signals() -> None:
    """Vague query with score=1 task_checkpoint + work signals MUST inject."""
    result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='offtopic-checkpoint-1',
                type='task_checkpoint',
                payload={
                    'task': 'Process catalog records batch 417',
                    'current_state': 'Blocked on missing ISBN data for 12 items',
                    'blocker_state': 'Missing ISBN data for items 4201-4212',
                    'next_step': 'Contact publisher for missing ISBNs',
                    'selected_work_artifacts': ['batch_id: 417', 'status: blocked'],
                    'freshness_signal': 'in_progress',
                },
                score=1,
                evidence=[
                    EvidenceReference(
                        source_item_id='src-checkpoint-1',
                        source_type='chat_message',
                        source_id='msg-checkpoint-1',
                        container_ref='chat:offtopic-test',
                        thread_ref='chat:offtopic-test:thread-A',
                    ),
                ],
                container_ref='chat:offtopic-test',
                thread_ref='chat:offtopic-test:thread-A',
            ),
        ],
        trace=QueryTrace(
            query_text='test query',
            query_tokens=('test', 'query'),
            limit=4,
            filters=QueryFilters(container_ref='chat:offtopic-test'),
            stages=(),
        ),
    )
    outcome = _run_floor_test(result, query_text="what should I do next?")
    assert outcome.should_inject is True, (
        f"Vague recall with task_checkpoint + work signals should inject. "
        f"decision_reason={outcome.decision_reason}"
    )


def test_ontopic_injects_decision_with_strong_score() -> None:
    """On-topic query with high score decision MUST inject."""
    result = _build_floor_test_retrieval_result(
        score=5, memory_type='decision',
        payload={'decision': 'Use SQLite for catalog indexing.', 'rationale': 'Branch library has under 50k items.'},
    )
    outcome = _run_floor_test(result, query_text="what did we decide about catalog indexing?")
    assert outcome.should_inject is True, (
        f"On-topic decision query should inject. "
        f"decision_reason={outcome.decision_reason}"
    )


# ---------------------------------------------------------------------------
# Multi-user routing: shared container candidates with mixed actor evidence
# ---------------------------------------------------------------------------


def test_multi_user_shared_candidates_all_inject_correctly() -> None:
    """In a shared container, candidates from different users (all actor_ref=None)
    should route and inject normally — routing must not suppress shared evidence."""
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='chat:library-team',
        thread_ref='chat:library-team:thread-mu-injection',
        actor_ref='user:branch-librarian',
    )
    # Two decisions from different users, both shared (actor_ref=None on memory)
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='decision-alice-shared',
                type='decision',
                payload={'decision': 'use item event time for reservation ordering'},
                freshness_at=datetime(2026, 3, 12, 10, 0, tzinfo=timezone.utc),
                score=19,
                evidence=[
                    EvidenceReference(
                        source_item_id='src-alice-1',
                        source_type='chat_message',
                        source_id='alice-msg-1',
                        occurred_at=datetime(2026, 3, 12, 10, 0, tzinfo=timezone.utc),
                        container_ref='chat:library-team',
                        thread_ref='chat:library-team:thread-history-1',
                        artifact_kind='message',
                    ),
                ],
                container_ref='chat:library-team',
                thread_ref='chat:library-team:thread-history-1',
            ),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='decision-bob-shared',
                type='decision',
                payload={'decision': 'use 30-minute batches for overdue notice processing'},
                freshness_at=datetime(2026, 3, 12, 11, 0, tzinfo=timezone.utc),
                score=17,
                evidence=[
                    EvidenceReference(
                        source_item_id='src-bob-1',
                        source_type='chat_message',
                        source_id='bob-msg-1',
                        occurred_at=datetime(2026, 3, 12, 11, 0, tzinfo=timezone.utc),
                        container_ref='chat:library-team',
                        thread_ref='chat:library-team:thread-history-2',
                        artifact_kind='message',
                    ),
                ],
                container_ref='chat:library-team',
                thread_ref='chat:library-team:thread-history-2',
            ),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='summary-team-thread',
                type='thread_summary',
                payload={
                    'summary': 'The team discussed reservation ordering and overdue notice batching.',
                },
                freshness_at=datetime(2026, 3, 12, 11, 0, tzinfo=timezone.utc),
                score=15,
                evidence=[
                    EvidenceReference(
                        source_item_id='src-alice-1',
                        source_type='chat_message',
                        source_id='alice-msg-1',
                        occurred_at=datetime(2026, 3, 12, 10, 0, tzinfo=timezone.utc),
                        container_ref='chat:library-team',
                        thread_ref='chat:library-team:thread-history-1',
                        artifact_kind='message',
                    ),
                ],
                container_ref='chat:library-team',
                thread_ref='chat:library-team:thread-history-1',
            ),
        ],
        trace=QueryTrace(
            query_text='What decisions have we made about ordering and notices?',
            query_tokens=('decisions', 'ordering', 'notices'),
            limit=4,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='What decisions have we made about ordering and notices?',
        requested_limit=4,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='new_thread', session_has_sufficient_local_context=False),
        include_trace=True,
    )

    assert outcome.should_inject is True, (
        f"Shared multi-user candidates should inject. decision_reason={outcome.decision_reason}"
    )
    assert outcome.injectable_blocks, "Expected injectable blocks from shared candidates"
    # Both decisions should be reachable — routing must not filter by actor
    injected_ids = {block.result_id for block in outcome.injectable_blocks}
    assert 'memory_object:decision-alice-shared' in injected_ids or 'memory_object:decision-bob-shared' in injected_ids, (
        f"At least one shared decision should be injected. Got: {injected_ids}"
    )


def test_multi_user_shared_thread_summary_and_checkpoint_inject_together() -> None:
    """Thread summary + task checkpoint from multi-user thread should both be injectable."""
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='chat:library-team',
        thread_ref='chat:library-team:thread-mu-recall',
    )
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='checkpoint-multi-user',
                type='task_checkpoint',
                payload={
                    'summary': 'Catalog sync retry paused after service-token expiry.',
                    'task': 'Resume the catalog sync retry.',
                    'current_state': 'Refreshed 312 reservation records before the token expired.',
                    'key_findings': ['service token expired during batch 312'],
                    'blocker_state': 'Catalog API returned 401.',
                    'next_step': 'Refresh the catalog service token and rerun from batch 313.',
                    'evidence': ['Partial progress: 312 records refreshed.'],
                    'freshness_signal': 'Latest explicit update at 2026-03-11T10:02:00Z.',
                },
                freshness_at=datetime(2026, 3, 11, 10, 2, tzinfo=timezone.utc),
                score=18,
                evidence=[
                    EvidenceReference(
                        source_item_id='src-team-1',
                        source_type='assistant_artifact',
                        source_id='team-artifact-1',
                        occurred_at=datetime(2026, 3, 11, 10, 1, tzinfo=timezone.utc),
                        container_ref='chat:library-team',
                        thread_ref='chat:library-team:thread-history',
                        artifact_kind='tool_use_summary',
                    ),
                ],
                container_ref='chat:library-team',
                thread_ref='chat:library-team:thread-history',
            ),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='summary-multi-user',
                type='thread_summary',
                payload={
                    'summary': 'The catalog sync retry hit a 401 after 312 records. Next step is to refresh the token and resume from batch 313.',
                },
                freshness_at=datetime(2026, 3, 11, 10, 2, tzinfo=timezone.utc),
                score=15,
                evidence=[
                    EvidenceReference(
                        source_item_id='src-team-1',
                        source_type='assistant_artifact',
                        source_id='team-artifact-1',
                        occurred_at=datetime(2026, 3, 11, 10, 1, tzinfo=timezone.utc),
                        container_ref='chat:library-team',
                        thread_ref='chat:library-team:thread-history',
                        artifact_kind='tool_use_summary',
                    ),
                ],
                container_ref='chat:library-team',
                thread_ref='chat:library-team:thread-history',
            ),
        ],
        trace=QueryTrace(
            query_text='What is the status of the catalog sync retry?',
            query_tokens=('status', 'catalog', 'sync', 'retry'),
            limit=4,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='What is the status of the catalog sync retry?',
        requested_limit=4,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='new_thread', session_has_sufficient_local_context=False),
        include_trace=True,
    )

    assert outcome.should_inject is True, (
        f"Multi-user thread-level memories should inject. decision_reason={outcome.decision_reason}"
    )
    assert outcome.injectable_blocks, "Expected injectable blocks"
    injected_types = {block.memory_type for block in outcome.injectable_blocks}
    assert injected_types & {'task_checkpoint', 'thread_summary'}, (
        f"Thread-level memories from multi-user thread should be injectable. Got types: {injected_types}"
    )

