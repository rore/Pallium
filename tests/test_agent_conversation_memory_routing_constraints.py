from __future__ import annotations

from tests.agent_conversation_memory_routing_helpers import *

def test_process_item_emits_typed_constraint_memory() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=_FixedLLMProvider(
            {
                'summary': 'Constraint reminder',
                'candidate_type': None,
                'decision_text': None,
                'decision_evidence_text': None,
                'investigation_text': None,
                'investigation_evidence_text': None,
                'rationale_text': None,
                'is_low_value_meta': False,
                'constraint_text': 'Do not use the operations portal for the inventory batch digest.',
                'next_step_text': None,
                'blocker_text': None,
                'progress_text': None,
                'key_finding_text': None,
                'subject_hints': [{'kind': 'workstream', 'value': 'inventory batch digest'}],
                'constraint_candidates': [
                    {
                        'constraint_text': 'Do not use the operations portal for the inventory batch digest.',
                    }
                ],
            }
        ),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    result = plugin.process_item(
        SourceItem(
            source_type='assistant_output',
            source_id='constraint-source-1',
            content_type='text/plain',
            content='Do not use the operations portal for the inventory batch digest.',
            artifact_kind='assistant_output',
            role='assistant',
            container_ref='chat:library-help',
            thread_ref='chat:library-help:thread-constraint',
            occurred_at=datetime(2026, 3, 11, 12, 10, tzinfo=timezone.utc),
            container_visibility="public",
        )
    )

    constraint_memory = next(memory for memory in result.memory_objects if memory.type == 'constraint_memory')
    assert constraint_memory.schema_id == 'agent_conversation_memory.constraint_memory'
    assert constraint_memory.payload['constraint_text'] == 'Do not use the operations portal for the inventory batch digest.'
    assert constraint_memory.envelope is not None
    assert constraint_memory.envelope.kind == 'constraint'

def test_fresh_thread_constraint_recall_prefers_structured_memory_over_raw_source() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='chat:library-help',
        thread_ref='chat:library-help:thread-fresh-constraint',
    )
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='source-constraint-raw',
                source_type='chat_message',
                source_id='constraint-raw',
                excerpt='Please remember not to sign in to the admin portal or open a local browser.',
                occurred_at=datetime(2026, 3, 11, 10, 1, tzinfo=timezone.utc),
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-history',
                artifact_kind='message',
                score=18,
                evidence=[
                    EvidenceReference(
                        source_item_id='source-constraint-raw',
                        source_type='chat_message',
                        source_id='constraint-raw',
                        occurred_at=datetime(2026, 3, 11, 10, 1, tzinfo=timezone.utc),
                        container_ref='chat:library-help',
                        thread_ref='chat:library-help:thread-history',
                        artifact_kind='message',
                    )
                ],
            ),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='summary-constraint-1',
                type='thread_summary',
                payload={
                    'summary': 'The catalog sync retry should continue without admin portal sign-in or local browser use while the service token is refreshed.',
                },
                freshness_at=datetime(2026, 3, 11, 10, 2, tzinfo=timezone.utc),
                score=14,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-history',
            ),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='checkpoint-constraint-1',
                type='task_checkpoint',
                payload={
                    'summary': 'Catalog sync retry has an auth blocker and an operator constraint.',
                    'task': 'Resume the catalog sync retry.',
                    'current_state': 'Do not use the admin portal or a local browser while fixing the expired token.',
                    'key_findings': ['Avoid admin portal sign-in and local browser use during the retry.'],
                    'blocker_state': 'The service token expired, and the operator constraint forbids admin portal sign-in or local browser use.',
                    'next_step': 'Refresh the catalog service token and resume from batch 313.',
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
            query_text='What constraint had I given you about admin portal sign-in and browser use?',
            query_tokens=('what', 'constraint', 'had', 'i', 'given', 'you', 'about', 'admin', 'portal', 'sign', 'in', 'browser', 'use'),
            limit=4,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='What constraint had I given you about admin portal sign-in and browser use?',
        requested_limit=4,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='new_thread', session_has_sufficient_local_context=False),
        include_trace=True,
    )

    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    assert outcome.trace.routing['selected_layer'] != 'source_evidence'
    assert outcome.results[0].result_kind == 'memory_hit'
    assert any('admin portal' in block.text.lower() or 'local browser' in block.text.lower() for block in outcome.injectable_blocks)
    assert all(block.block_type == 'memory' for block in outcome.injectable_blocks)

def test_fresh_thread_recall_suppresses_duplicate_queries_and_meta_source_noise() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='chat:library-help',
        thread_ref='chat:library-help:thread-fresh-contaminated',
    )
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='source-current-question',
                source_type='chat_message',
                source_id='current-question',
                excerpt='What do we know the latest about the catalog sync retry?',
                occurred_at=datetime(2026, 3, 11, 10, 3, tzinfo=timezone.utc),
                role='user',
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-fresh-contaminated',
                artifact_kind='message',
                score=22,
                evidence=[
                    EvidenceReference(
                        source_item_id='source-current-question',
                        source_type='chat_message',
                        source_id='current-question',
                        occurred_at=datetime(2026, 3, 11, 10, 3, tzinfo=timezone.utc),
                        role='user',
                        container_ref='chat:library-help',
                        thread_ref='chat:library-help:thread-fresh-contaminated',
                        artifact_kind='message',
                    )
                ],
            ),
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='source-duplicate-question',
                source_type='chat_message',
                source_id='duplicate-question',
                excerpt='What do we know the latest about the catalog sync retry?',
                occurred_at=datetime(2026, 3, 11, 10, 1, tzinfo=timezone.utc),
                role='user',
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-old-duplicate',
                artifact_kind='message',
                score=20,
                evidence=[
                    EvidenceReference(
                        source_item_id='source-duplicate-question',
                        source_type='chat_message',
                        source_id='duplicate-question',
                        occurred_at=datetime(2026, 3, 11, 10, 1, tzinfo=timezone.utc),
                        role='user',
                        container_ref='chat:library-help',
                        thread_ref='chat:library-help:thread-old-duplicate',
                        artifact_kind='message',
                    )
                ],
            ),
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='source-capability-note',
                source_type='assistant_artifact',
                source_id='capability-note',
                excerpt='Capabilities: I can help summarize the latest catalog sync status and search records if needed.',
                occurred_at=datetime(2026, 3, 11, 10, 4, tzinfo=timezone.utc),
                role='assistant',
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-fresh-contaminated',
                artifact_kind='assistant_output',
                score=18,
                evidence=[
                    EvidenceReference(
                        source_item_id='source-capability-note',
                        source_type='assistant_artifact',
                        source_id='capability-note',
                        occurred_at=datetime(2026, 3, 11, 10, 4, tzinfo=timezone.utc),
                        role='assistant',
                        container_ref='chat:library-help',
                        thread_ref='chat:library-help:thread-fresh-contaminated',
                        artifact_kind='assistant_output',
                    )
                ],
            ),
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='source-heartbeat-note',
                source_type='assistant_artifact',
                source_id='heartbeat-note',
                excerpt='Heartbeat: still monitoring the catalog sync retry for the operations channel.',
                occurred_at=datetime(2026, 3, 11, 10, 5, tzinfo=timezone.utc),
                role='assistant',
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-fresh-contaminated',
                artifact_kind='assistant_output',
                score=17,
                evidence=[
                    EvidenceReference(
                        source_item_id='source-heartbeat-note',
                        source_type='assistant_artifact',
                        source_id='heartbeat-note',
                        occurred_at=datetime(2026, 3, 11, 10, 5, tzinfo=timezone.utc),
                        role='assistant',
                        container_ref='chat:library-help',
                        thread_ref='chat:library-help:thread-fresh-contaminated',
                        artifact_kind='assistant_output',
                    )
                ],
            ),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='checkpoint-contaminated-1',
                type='task_checkpoint',
                payload={
                    'summary': 'Catalog sync retry is paused after partial progress and a service-token failure.',
                    'task': 'Resume the catalog sync retry.',
                    'current_state': 'Refreshed 312 reservation records before the service token expired.',
                    'key_findings': ['Avoid admin portal sign-in and local browser use during the retry.'],
                    'blocker_state': 'Catalog API returned 401 because the service token expired; do not use the admin portal or a local browser while resolving it.',
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
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='thread-summary-contaminated-1',
                type='thread_summary',
                payload={
                    'summary': 'The catalog sync retry refreshed 312 reservation records before the service token expired and should resume from batch 313 without using the admin portal or a local browser.',
                },
                freshness_at=datetime(2026, 3, 11, 10, 2, tzinfo=timezone.utc),
                score=14,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-history',
            ),
        ],
        trace=QueryTrace(
            query_text='What do we know the latest about the catalog sync retry?',
            query_tokens=('what', 'do', 'we', 'know', 'latest', 'catalog', 'sync', 'retry'),
            limit=6,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='What do we know the latest about the catalog sync retry?',
        requested_limit=6,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='new_thread', session_has_sufficient_local_context=False),
        include_trace=True,
    )

    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    assert outcome.trace.routing['selected_layer'] != 'source_evidence'
    # After removing legacy English fallback (cue-free control plane),
    # only same-thread current-query echo suppression remains.
    # Cross-thread duplicate recall questions are no longer suppressed.
    excluded = {item['excluded_reason_code'] for item in outcome.trace.routing['excluded_high_scoring_candidates']}
    assert 'current_query_source_echo' in excluded
    assert 'generic_capability_source' not in excluded
    assert 'heartbeat_source_noise' not in excluded

def test_multi_token_wallet_recall_excludes_unrelated_batch_checkpoint() -> None:
    """With cue-free scoring, retrieval-score gap filters unrelated items.

    The batch checkpoint has a much lower retrieval score than the wallet items,
    so the gap filter (50% of primary) should exclude it."""
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='slack:channel:CLOCAL001',
        thread_ref='slack:thread:CLOCAL001:thread-y',
    )
    retrieval_result = RetrievalQueryResult(
        results=[
            _wallet_snapshot_checkpoint_result(score=18),
            _wallet_snapshot_summary_result(score=17),
            _inventory_batch_constraint_checkpoint_result(score=8),
            _inventory_batch_constraint_summary_result(score=7),
        ],
        trace=QueryTrace(
            query_text='what is the latest we have in wallet reserve snapshot?',
            query_tokens=('what', 'is', 'the', 'latest', 'we', 'have', 'in', 'wallet', 'reserve', 'snapshot'),
            limit=6,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='what is the latest we have in wallet reserve snapshot?',
        requested_limit=6,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='same_thread_continuation', session_has_sufficient_local_context=True),
        include_trace=True,
    )

    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    rendered_blocks = ' '.join(block.text.lower() for block in outcome.injectable_blocks)
    assert outcome.should_inject is True
    assert outcome.decision_reason != 'same_thread_context_sufficient'
    assert outcome.trace.routing['query_family'] == 'broad_recurring_recall'
    assert outcome.trace.routing['selected_layer'] != 'source_evidence'
    assert 'wallet reserve snapshot' in rendered_blocks
    # Wallet checkpoint must rank first (highest retrieval score + evidence shape)
    assert outcome.injectable_blocks[0].result_id == 'memory_object:checkpoint-wallet-snapshot'
