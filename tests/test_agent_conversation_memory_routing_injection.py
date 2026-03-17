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
    assert outcome.injectable_blocks[0].block_type == 'source_evidence'
    assert outcome.injectable_blocks[0].result_id == 'source_item:source-evidence-1'

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
    assert any(block.block_type == 'source_evidence' for block in outcome.injectable_blocks)

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
    assert any(item['loss_stage'] == 'injection_cap' for item in cap_diagnostics.values())
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
        session_ref='session:trivial-same-thread',
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
    assert outcome.trace.routing['query_family'] == 'broad_recurring_recall'
    assert any(block.memory_type == 'task_checkpoint' for block in outcome.injectable_blocks)
    assert outcome.trace.routing['injection_decision']['same_thread_context_evaluation']['reason_code'] == 'insufficient_same_thread_local_state'
    excluded = {item['excluded_reason_code'] for item in outcome.trace.routing['excluded_high_scoring_candidates']}
    assert 'unresolved_thread_summary' in excluded
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
        session_ref='session:rewrite-same-thread',
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

def test_same_thread_answer_bearing_source_counts_as_local_context_even_with_external_memory() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='chat:library-help',
        thread_ref='chat:library-help:thread-answer-bearing-same-thread',
        session_ref='session:answer-bearing-same-thread',
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
    assert outcome.should_inject is False
    assert outcome.decision_reason == 'same_thread_context_sufficient'
    same_thread_context = outcome.trace.routing['injection_decision']['same_thread_context_evaluation']
    assert same_thread_context['reason_code'] == 'relevant_same_thread_local_state'
    assert 'source_item:same-thread-answer' in same_thread_context['qualifying_result_ids']
    assert outcome.injectable_blocks == []

def test_same_thread_user_status_update_does_not_block_broad_recall_carry_forward() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='chat:library-help',
        thread_ref='chat:library-help:thread-user-status-same-thread',
        session_ref='session:user-status-same-thread',
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
    assert outcome.trace.routing['query_family'] == 'broad_recurring_recall'
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
        session_ref='session:user-fact-same-thread',
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
    assert outcome.should_inject is False
    assert outcome.decision_reason == 'same_thread_context_sufficient'
    assert outcome.trace.routing['query_family'] == 'same_thread_no_value_continuation'
    same_thread_context = outcome.trace.routing['injection_decision']['same_thread_context_evaluation']
    assert same_thread_context['reason_code'] == 'relevant_same_thread_local_state'
    assert 'source_item:same-thread-user-fact' in same_thread_context['qualifying_result_ids']
    assert outcome.injectable_blocks == []

def test_fresh_thread_broad_recall_prefers_structured_memory_over_noisy_source_evidence() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='chat:library-help',
        thread_ref='chat:library-help:thread-fresh-recall',
        session_ref='session:fresh-recall',
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
    assert outcome.trace.routing['query_intent'] in {'broad_recall', 'answer_continuity'}
    assert outcome.trace.routing['selected_layer'] != 'source_evidence'
    assert outcome.results[0].result_kind == 'memory_hit'
    assert outcome.results[0].type in {'task_checkpoint', 'thread_summary'}
    assert outcome.injectable_blocks[0].block_type == 'memory'
    assert any('admin portal' in block.text.lower() or 'local browser' in block.text.lower() for block in outcome.injectable_blocks)

def test_query_only_current_thread_summary_is_excluded_from_recall_packaging() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='chat:library-help',
        thread_ref='chat:library-help:thread-current-query-only',
        session_ref='session:current-query-only',
    )
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='thread-summary-current-query-only',
                type='thread_summary',
                payload={
                    'summary': 'User asked, "What do we know the latest about the catalog sync retry?" The thread contains only this question.',
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
    assert 'current_thread_empty_summary' in excluded
    assert all(block.result_id != 'memory_object:thread-summary-current-query-only' for block in outcome.injectable_blocks)

def test_fresh_thread_evidence_trace_still_allows_source_evidence() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='chat:library-help',
        thread_ref='chat:library-help:thread-fresh-evidence',
        session_ref='session:fresh-evidence',
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
    assert outcome.trace.routing['query_intent'] == 'evidence_trace'
    assert outcome.trace.routing['selected_layer'] == 'source_evidence'
    assert outcome.results[0].result_kind == 'source_hit'
    assert outcome.injectable_blocks[0].block_type == 'source_evidence'

def test_fresh_thread_greeting_noise_fails_closed_without_memory_injection() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='slack:channel:CLOCAL001',
        thread_ref='slack:thread:CLOCAL001:diag-good-morning-fresh',
        session_ref='agent-session:diag-good-morning-fresh',
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
        session_ref='agent-session:batch-d',
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
    assert outcome.trace.routing['query_intent'] == 'broad_recall'
    assert outcome.trace.routing['query_family'] == 'broad_recurring_recall'
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
        session_ref='agent-session:diag-batch-reminder-fresh',
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
    assert outcome.trace.routing['query_intent'] == 'broad_recall'
    assert outcome.trace.routing['query_family'] == 'broad_recurring_recall'
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
        session_ref='agent-session:diag-good-afternnon-fresh',
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
    assert outcome.decision_reason == 'low_value_query'
    assert outcome.injectable_blocks == []

def test_same_thread_batch_reminder_lately_prefers_structured_carry_forward_over_polluted_sources() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='slack:channel:CLOCAL001',
        thread_ref='slack:thread:CLOCAL001:thread-x',
        session_ref='agent-session:thread-x',
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
    assert outcome.trace.routing['query_intent'] == 'broad_recall'
    assert outcome.trace.routing['query_family'] == 'broad_recurring_recall'
    assert outcome.trace.routing['selected_layer'] != 'source_evidence'
    assert all(block.block_type == 'memory' for block in outcome.injectable_blocks)
    assert same_thread['reason_code'] == 'insufficient_same_thread_local_state'
    assert 'inventory batch digest' in rendered_blocks or 'last confirmed batch' in rendered_blocks
    assert 'remind me what we had about the batch digests lately' not in rendered_blocks
    assert 'good afternoon' not in rendered_blocks
    assert 'attempt to authenticate' not in rendered_blocks
