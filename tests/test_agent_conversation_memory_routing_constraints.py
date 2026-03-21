from __future__ import annotations

from tests.agent_conversation_memory_routing_helpers import *

def test_process_item_emits_typed_constraint_memory_and_supersession_hint() -> None:
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
                        'primary_scope_anchor': {'kind': 'workstream', 'value': 'inventory batch digest'},
                        'target_anchor': {'kind': 'surface', 'value': 'operations portal'},
                        'action_class': 'use_surface',
                        'polarity': 'prohibit',
                        'confidence': 'high',
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
    assert constraint_memory.payload['polarity'] == 'prohibit'
    assert constraint_memory.payload['action_class'] == 'use_surface'
    assert constraint_memory.payload['primary_scope_anchor'] == {'kind': 'workstream', 'value': 'inventory batch digest'}
    assert constraint_memory.payload['target_anchor'] == {'kind': 'surface', 'value': 'operations portal'}
    assert constraint_memory.envelope is not None
    assert constraint_memory.envelope.kind == 'constraint'
    assert len(result.supersession_hints) == 1
    hint = result.supersession_hints[0]
    assert hint.memory_type == 'constraint_memory'
    assert hint.canonical_key == 'workstream:inventory batch digest|surface:operations portal|use_surface'

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
    assert all(item.result_kind == 'memory_hit' for item in outcome.results)
    assert all(block.block_type == 'memory' for block in outcome.injectable_blocks)
    excluded = {item['excluded_reason_code'] for item in outcome.trace.routing['excluded_high_scoring_candidates']}
    assert {'current_query_source_echo', 'duplicate_recall_query_source', 'generic_capability_source', 'heartbeat_source_noise'}.issubset(excluded)

def test_fresh_thread_recall_excludes_conflicting_structured_checkpoint() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='chat:library-help',
        thread_ref='chat:library-help:thread-fresh-conflict',
    )
    retrieval_result = RetrievalQueryResult(
        results=[
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
                score=16,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-history',
            ),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='checkpoint-conflicting-follow-up',
                type='task_checkpoint',
                payload={
                    'summary': 'The newer export follow-up is waiting on external workspace access.',
                    'task': 'Resume the catalog sync retry.',
                    'current_state': 'The workspace will need reconnection once portal access returns.',
                    'key_findings': ['External workspace access is currently unavailable.'],
                    'blocker_state': 'Retry the external workspace connection after admin portal access is restored.',
                    'next_step': 'Sign in to the admin portal and reconnect the external workspace once access is restored.',
                    'evidence': ['The follow-up relied on external workspace access.'],
                    'freshness_signal': 'Latest explicit update at 2026-03-11T11:02:00Z.',
                },
                freshness_at=datetime(2026, 3, 11, 11, 2, tzinfo=timezone.utc),
                score=18,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-conflicting-history',
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
    rendered_blocks = ' '.join(block.text.lower() for block in outcome.injectable_blocks)
    excluded = {item['excluded_reason_code'] for item in outcome.trace.routing['excluded_high_scoring_candidates']}
    assert outcome.trace.routing['selected_layer'] == 'task_checkpoint'
    assert 'admin portal' in rendered_blocks
    assert 'reconnect the external workspace once access is restored' not in rendered_blocks
    assert 'conflicts_with_active_constraint' in excluded
    assert outcome.trace.routing['packaging']['mode'] == 'compatible_structured_recall'

def test_fresh_thread_constraint_recall_prefers_constraint_anchor_over_conflicting_checkpoint() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='chat:library-help',
        thread_ref='chat:library-help:thread-fresh-constraint-conflict',
    )
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='checkpoint-conflicting-follow-up',
                type='task_checkpoint',
                payload={
                    'summary': 'The newer export follow-up is waiting on external workspace access.',
                    'task': 'Resume the catalog sync retry.',
                    'current_state': 'The workspace will need reconnection once portal access returns.',
                    'key_findings': ['External workspace access is currently unavailable.'],
                    'blocker_state': 'Retry the external workspace connection after admin portal access is restored.',
                    'next_step': 'Sign in to the admin portal and reconnect the external workspace once access is restored.',
                    'evidence': ['The follow-up relied on external workspace access.'],
                    'freshness_signal': 'Latest explicit update at 2026-03-11T11:02:00Z.',
                },
                freshness_at=datetime(2026, 3, 11, 11, 2, tzinfo=timezone.utc),
                score=18,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-conflicting-history',
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
                score=16,
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
    assert outcome.injectable_blocks
    assert 'admin portal' in outcome.injectable_blocks[0].text.lower()
    assert 'reconnect the external workspace once access is restored' not in ' '.join(block.text.lower() for block in outcome.injectable_blocks)
    assert outcome.trace.routing['packaging']['constraint_anchor_result_id'] == 'memory_object:checkpoint-constraint-anchor'

def test_broad_recall_with_only_self_conflicting_checkpoint_fails_closed() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='chat:library-help',
        thread_ref='chat:library-help:thread-recall-only-bad-checkpoint',
    )
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='checkpoint-only-conflicting',
                type='task_checkpoint',
                payload={
                    'summary': 'The export retry depends on reconnecting the external workspace.',
                    'task': 'Resume the catalog sync retry.',
                    'current_state': 'Portal access has not been restored yet.',
                    'key_findings': ['Do not sign in to the admin portal or open a local browser during this task.'],
                    'blocker_state': 'Reconnect the external workspace after admin portal access is restored.',
                    'next_step': 'Sign in to the admin portal and reconnect the external workspace once access is restored.',
                    'evidence': ['Constraint: do not sign in to the admin portal or open a local browser.'],
                    'freshness_signal': 'Latest explicit update at 2026-03-11T11:02:00Z.',
                },
                freshness_at=datetime(2026, 3, 11, 11, 2, tzinfo=timezone.utc),
                score=20,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-conflicting-history',
            ),
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='source-only-conflicting',
                source_type='assistant_artifact',
                source_id='artifact-only-conflicting',
                excerpt='Next step: sign in to the admin portal and reconnect the external workspace once access is restored.',
                occurred_at=datetime(2026, 3, 11, 11, 2, tzinfo=timezone.utc),
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-conflicting-history',
                artifact_kind='assistant_output',
                score=19,
                evidence=[
                    EvidenceReference(
                        source_item_id='source-only-conflicting',
                        source_type='assistant_artifact',
                        source_id='artifact-only-conflicting',
                        occurred_at=datetime(2026, 3, 11, 11, 2, tzinfo=timezone.utc),
                        container_ref='chat:library-help',
                        thread_ref='chat:library-help:thread-conflicting-history',
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
    assert outcome.results == []
    assert outcome.injectable_blocks == []
    assert outcome.trace.routing['packaging']['mode'] == 'compatible_structured_recall'
    excluded = {item['excluded_reason_code'] for item in outcome.trace.routing['excluded_high_scoring_candidates']}
    assert 'conflicts_with_active_constraint' in excluded

def test_constraint_recall_prefers_explicit_no_login_constraint_over_auth_retry_guidance() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='slack:channel:CLOCAL001',
        thread_ref='slack:thread:CLOCAL001:diag-constraint-fresh',
    )
    retrieval_result = RetrievalQueryResult(
        results=[
            _inventory_batch_constraint_checkpoint_result(score=17),
            _inventory_batch_constraint_summary_result(score=16),
            _inventory_batch_conflicting_retry_checkpoint_result(score=15),
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='thread-c-artifact-2',
                source_type='assistant_artifact',
                source_id='thread-c-artifact-2',
                excerpt='Next step: attempt to authenticate to the operations portal and the message console before retrying the inventory batch digest.',
                occurred_at=datetime(2026, 3, 11, 12, 2, tzinfo=timezone.utc),
                container_ref='slack:channel:CLOCAL001',
                thread_ref='slack:thread:CLOCAL001:thread-c',
                artifact_kind='todo_snapshot',
                role='assistant',
                score=14,
                evidence=[],
            ),
        ],
        trace=QueryTrace(
            query_text='what constraint had I given you about operations portal sign-in and browser use?',
            query_tokens=('what', 'constraint', 'had', 'i', 'given', 'you', 'about', 'operations', 'portal', 'sign', 'in', 'browser', 'use'),
            limit=6,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='what constraint had I given you about operations portal sign-in and browser use?',
        requested_limit=6,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='new_thread', session_has_sufficient_local_context=False),
        include_trace=True,
    )

    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    rendered_blocks = ' '.join(block.text.lower() for block in outcome.injectable_blocks)
    excluded = {item['excluded_reason_code'] for item in outcome.trace.routing['excluded_high_scoring_candidates']}
    assert outcome.should_inject is True
    assert outcome.decision_reason == 'carry_forward_available'
    assert outcome.trace.routing['query_intent'] == 'broad_recall'
    assert outcome.trace.routing['query_family'] == 'broad_recurring_recall'
    assert outcome.trace.routing['selected_layer'] == 'task_checkpoint'
    assert 'do not try to sign in to the operations portal' in rendered_blocks
    assert 'local browser' in rendered_blocks
    assert 'attempt to authenticate' not in rendered_blocks
    assert 'retry after authentication is restored' not in rendered_blocks
    assert 'conflicts_with_active_constraint' in excluded

def test_constraint_recall_prefers_typed_constraint_memory_and_excludes_conflicting_guidance() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='slack:channel:CLOCAL001',
        thread_ref='slack:thread:CLOCAL001:diag-typed-constraint',
    )
    retrieval_result = RetrievalQueryResult(
        results=[
            _inventory_batch_typed_constraint_result(score=19),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='checkpoint-batch-auth-retry-enveloped',
                type='task_checkpoint',
                payload={
                    'summary': 'A newer mirror-based batch digest is blocked by remote authentication.',
                    'task': 'Resume the mirror-based batch digest.',
                    'current_state': 'The mirror-based batch digest is prepared, but remote authentication still blocks it.',
                    'key_findings': [
                        'The mirror-based batch digest is prepared for the batch manifests.',
                        'Remote authentication still blocks it.',
                    ],
                    'blocker_state': 'The mirror-based batch digest cannot proceed until remote authentication succeeds.',
                    'next_step': 'Attempt to authenticate to the operations portal before retrying the inventory batch digest.',
                    'evidence': [
                        'Blocked: the mirror-based batch digest cannot proceed until remote authentication succeeds.',
                        'Next step: attempt to authenticate to the operations portal before retrying the inventory batch digest.',
                    ],
                    'freshness_signal': 'Latest explicit update at 2026-03-11T12:12:00Z.',
                },
                freshness_at=datetime(2026, 3, 11, 12, 12, tzinfo=timezone.utc),
                score=18,
                evidence=[],
                container_ref='slack:channel:CLOCAL001',
                thread_ref='slack:thread:CLOCAL001:thread-c',
                envelope=_memory_envelope(
                    'episode',
                    subjects=[MemorySubjectAnchor(kind='workstream', value='inventory batch digest')],
                ),
            ),
        ],
        trace=QueryTrace(
            query_text='what constraint had i given you about operations portal use?',
            query_tokens=('what', 'constraint', 'had', 'i', 'given', 'you', 'about', 'operations', 'portal', 'use'),
            limit=5,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='what constraint had i given you about operations portal use?',
        requested_limit=5,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='new_thread', session_has_sufficient_local_context=False),
        include_trace=True,
    )

    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    rendered_blocks = ' '.join(block.text.lower() for block in outcome.injectable_blocks)
    active_typed = outcome.trace.routing['packaging']['active_typed_constraints']
    assert outcome.should_inject is True
    assert outcome.results[0].type == 'constraint_memory'
    assert 'do not use the operations portal' in rendered_blocks
    assert 'attempt to authenticate' not in rendered_blocks
    assert active_typed[0]['memory_type'] == 'constraint_memory'
    assert all(result.result_id != 'memory_object:checkpoint-batch-auth-retry-enveloped' for result in outcome.results)

def test_multi_token_wallet_recall_excludes_unrelated_batch_checkpoint() -> None:
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
            _inventory_batch_constraint_checkpoint_result(score=18),
            _inventory_batch_constraint_summary_result(score=17),
            _wallet_snapshot_checkpoint_result(score=16),
            _wallet_snapshot_summary_result(score=15),
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
    selected_ids = {block.result_id for block in outcome.injectable_blocks}
    assert outcome.should_inject is True
    assert outcome.decision_reason != 'same_thread_context_sufficient'
    assert outcome.trace.routing['query_family'] == 'broad_recurring_recall'
    assert outcome.trace.routing['selected_layer'] != 'source_evidence'
    assert 'wallet reserve snapshot' in rendered_blocks
    assert 'inventory batch digest' not in rendered_blocks
    assert 'memory_object:checkpoint-batch-constraint' not in selected_ids

def test_constraint_conflict_detection_treats_single_tool_prohibition_as_conflicting() -> None:
    profile = _structured_constraint_profile_from_payload(
        memory_type='task_checkpoint',
        payload={
            'summary': '',
            'evidence': ['Constraint: do not open a local browser.'],
        },
        result_id='memory_object:browser-only-constraint',
    )

    assert profile is not None
    assert profile['focus_tokens'] == ['browser']
    assert _structured_text_conflicts_with_constraint('Next step: open the local browser.', profile) is True
    assert _structured_text_conflicts_with_constraint('Next step: sign in with the local browser.', profile) is True
    assert _structured_text_conflicts_with_constraint('Next step: refresh the local digest token.', profile) is False
    assert _structured_text_conflicts_with_constraint('Next step: retry after authentication is restored.', profile) is False

def test_constraint_conflict_detection_enforces_use_only_clause_tokens() -> None:
    profile = _structured_constraint_profile_from_payload(
        memory_type='task_checkpoint',
        payload={
            'summary': '',
            'evidence': [
                'Constraint: do not sign in to the operations portal; use only local mirror snapshots for the batch digest.'
            ],
        },
        result_id='memory_object:mirror-only-constraint',
    )

    assert profile is not None
    assert {'mirror', 'snapshots'}.issubset(set(profile['protected_tokens']))
    assert {'mirror', 'snapshots'}.issubset(set(profile['focus_tokens']))
    assert _structured_text_conflicts_with_constraint(
        'Next step: fetch tracker data instead of the local mirror snapshots.',
        profile,
    ) is True
    assert _structured_text_conflicts_with_constraint(
        'Next step: use the local mirror snapshots for the next batch digest.',
        profile,
    ) is False
    assert _structured_text_conflicts_with_constraint(
        'Next step: use the local mirror snapshots instead of the tracker export.',
        profile,
    ) is False

def test_constraint_conflict_detection_keeps_single_tool_focus_with_context_nouns() -> None:
    profile = _structured_constraint_profile_from_payload(
        memory_type='task_checkpoint',
        payload={
            'summary': '',
            'evidence': ['Constraint: do not open a local browser for the batch digest export.'],
        },
        result_id='memory_object:browser-context-constraint',
    )

    assert profile is not None
    assert profile['focus_tokens'] == ['browser']
    assert _structured_text_conflicts_with_constraint('Next step: open the local browser.', profile) is True
    assert _structured_text_conflicts_with_constraint('Next step: sign in with the local browser.', profile) is True
    assert _structured_text_conflicts_with_constraint('Next step: refresh the batch digest export token.', profile) is False

def test_same_thread_local_constraint_correction_prefers_constraint_memory_and_excludes_conflicting_guidance() -> None:
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
                source_item_id='thread-x-msg-3',
                source_type='chat_message',
                source_id='thread-x-msg-3',
                excerpt='no, remember that we cannot use the operations portal here so no point trying to connect to it',
                occurred_at=datetime(2026, 3, 11, 13, 0, 30, tzinfo=timezone.utc),
                container_ref='slack:channel:CLOCAL001',
                thread_ref='slack:thread:CLOCAL001:thread-x',
                artifact_kind='message',
                role='user',
                score=20,
                evidence=[],
            ),
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='thread-capability-note-3',
                source_type='assistant_artifact',
                source_id='thread-capability-note-3',
                excerpt='Many talents: I can help summarize batch digests and wallet snapshots.',
                occurred_at=datetime(2026, 3, 11, 9, 5, tzinfo=timezone.utc),
                container_ref='slack:channel:CLOCAL001',
                thread_ref='slack:thread:CLOCAL001:thread-capabilities',
                artifact_kind='assistant_output',
                role='assistant',
                score=11,
                evidence=[],
            ),
            _inventory_batch_constraint_checkpoint_result(score=17),
            _inventory_batch_constraint_summary_result(score=16),
            _inventory_batch_conflicting_retry_checkpoint_result(score=18),
        ],
        trace=QueryTrace(
            query_text='no, remember that we cannot use the operations portal here so no point trying to connect to it',
            query_tokens=('no', 'remember', 'that', 'we', 'cannot', 'use', 'the', 'operations', 'portal', 'here', 'so', 'no', 'point', 'trying', 'to', 'connect', 'to', 'it'),
            limit=6,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='no, remember that we cannot use the operations portal here so no point trying to connect to it',
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
    assert outcome.decision_reason == 'carry_forward_available'
    assert outcome.trace.routing['query_family'] == 'broad_recurring_recall'
    assert outcome.trace.routing['selected_layer'] != 'source_evidence'
    assert all(block.block_type == 'memory' for block in outcome.injectable_blocks)
    assert 'do not try to sign in to the operations portal' in rendered_blocks
    assert 'local browser' in rendered_blocks
    assert 'attempt to authenticate' not in rendered_blocks
    assert 'retry after authentication is restored' not in rendered_blocks
    assert 'connect to it' not in rendered_blocks
    assert 'many talents' not in rendered_blocks

def test_same_thread_local_typed_constraint_shares_domain_with_durable_constraint_and_excludes_conflicting_guidance() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='slack:channel:CLOCAL001',
        thread_ref='slack:thread:CLOCAL001:thread-x',
    )
    inventory_scope = MemorySubjectAnchor(kind='workstream', value='inventory batch digest')
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='thread-x-msg-4',
                source_type='chat_message',
                source_id='thread-x-msg-4',
                excerpt='no, remember that we cannot use the operations portal here so no point trying to connect to it',
                occurred_at=datetime(2026, 3, 11, 13, 0, 30, tzinfo=timezone.utc),
                container_ref='slack:channel:CLOCAL001',
                thread_ref='slack:thread:CLOCAL001:thread-x',
                artifact_kind='message',
                role='user',
                score=20,
                evidence=[],
            ),
            _inventory_batch_typed_constraint_result(score=19),
            _inventory_batch_conflicting_retry_checkpoint_result(
                score=18,
                envelope=_memory_envelope('episode', subjects=[inventory_scope]),
            ),
        ],
        trace=QueryTrace(
            query_text='no, remember that we cannot use the operations portal here so no point trying to connect to it',
            query_tokens=('no', 'remember', 'that', 'we', 'cannot', 'use', 'the', 'operations', 'portal', 'here', 'so', 'no', 'point', 'trying', 'to', 'connect', 'to', 'it'),
            limit=6,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='no, remember that we cannot use the operations portal here so no point trying to connect to it',
        requested_limit=6,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='same_thread_continuation', session_has_sufficient_local_context=True),
        include_trace=True,
    )

    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    packaging = outcome.trace.routing['packaging']
    active_typed = packaging['active_typed_constraints']
    shadowed_typed = packaging['shadowed_typed_constraints']
    expected_domain = 'workstream:inventory batch digest|use_surface'
    expected_key = 'workstream:inventory batch digest|surface:operations portal|use_surface'
    assert outcome.should_inject is True
    assert any(
        profile['result_id'] == 'query_text:local_constraint'
        and profile['profile_source'] == 'local_typed'
        and profile['compatibility_domain'] == expected_domain
        and profile['precise_coverage_key'] == expected_key
        for profile in active_typed
    )
    assert any(
        profile['result_id'] == 'memory_object:constraint-batch-portal'
        and profile['profile_source'] == 'durable_typed'
        and profile['compatibility_domain'] == expected_domain
        and profile['precise_coverage_key'] == expected_key
        for profile in shadowed_typed
    )
    assert all(result.result_id != 'memory_object:checkpoint-batch-auth-retry' for result in outcome.results)
    rendered_blocks = ' '.join(block.text.lower() for block in outcome.injectable_blocks)
    assert 'attempt to authenticate' not in rendered_blocks

def test_same_thread_local_typed_constraint_abstains_when_scope_is_ambiguous() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='slack:channel:CLOCAL001',
        thread_ref='slack:thread:CLOCAL001:thread-x',
    )
    inventory_scope = MemorySubjectAnchor(kind='workstream', value='inventory batch digest')
    wallet_scope = MemorySubjectAnchor(kind='workstream', value='wallet reserve snapshot')
    wallet_constraint = QueryResultItem(
        result_kind='memory_hit',
        memory_object_id='constraint-wallet-portal',
        type='constraint_memory',
        payload={
            'summary': 'Constraint: do not use operations portal for wallet reserve snapshot.',
            'constraint_text': 'Do not use the operations portal for the wallet reserve snapshot.',
            'primary_scope_anchor': {'kind': 'workstream', 'value': 'wallet reserve snapshot'},
            'target_anchor': {'kind': 'surface', 'value': 'operations portal'},
            'action_class': 'use_surface',
            'polarity': 'prohibit',
            'strength': 'hard',
            'status': 'active',
            'evidence': ['Do not use the operations portal for the wallet reserve snapshot.'],
            'freshness_signal': 'Latest explicit update at 2026-03-11T12:15:00Z.',
            'confidence': 'high',
        },
        freshness_at=datetime(2026, 3, 11, 12, 15, tzinfo=timezone.utc),
        score=18,
        evidence=[],
        container_ref='slack:channel:CLOCAL001',
        thread_ref='slack:thread:CLOCAL001:thread-wallet-constraint',
        envelope=_memory_envelope('constraint', confidence='high', subjects=[wallet_scope, MemorySubjectAnchor(kind='surface', value='operations portal')]),
    )
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='thread-x-msg-5',
                source_type='chat_message',
                source_id='thread-x-msg-5',
                excerpt='no, remember that we cannot use the operations portal here so no point trying to connect to it',
                occurred_at=datetime(2026, 3, 11, 13, 1, tzinfo=timezone.utc),
                container_ref='slack:channel:CLOCAL001',
                thread_ref='slack:thread:CLOCAL001:thread-x',
                artifact_kind='message',
                role='user',
                score=20,
                evidence=[],
            ),
            _inventory_batch_typed_constraint_result(score=19),
            wallet_constraint,
        ],
        trace=QueryTrace(
            query_text='no, remember that we cannot use the operations portal here so no point trying to connect to it',
            query_tokens=('no', 'remember', 'that', 'we', 'cannot', 'use', 'the', 'operations', 'portal', 'here', 'so', 'no', 'point', 'trying', 'to', 'connect', 'to', 'it'),
            limit=6,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='no, remember that we cannot use the operations portal here so no point trying to connect to it',
        requested_limit=6,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='same_thread_continuation', session_has_sufficient_local_context=True),
        include_trace=True,
    )

    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    packaging = outcome.trace.routing['packaging']
    active_typed = packaging['active_typed_constraints']
    shadowed_typed = packaging.get('shadowed_typed_constraints', [])
    assert all(profile['profile_source'] != 'local_typed' for profile in active_typed)
    assert all(profile['profile_source'] != 'local_typed' for profile in shadowed_typed)

def test_legacy_mixed_mode_normalization_abstains_when_scope_is_ambiguous() -> None:
    inventory_scope = MemorySubjectAnchor(kind='workstream', value='inventory batch digest')
    wallet_scope = MemorySubjectAnchor(kind='workstream', value='wallet reserve snapshot')
    ambiguous_legacy = QueryResultItem(
        result_kind='memory_hit',
        memory_object_id='checkpoint-ambiguous-legacy-constraint',
        type='task_checkpoint',
        payload={
            'summary': 'The carried context says not to use the operations portal.',
            'task': 'Resume the carried work.',
            'current_state': 'Both workstreams are mentioned near the same portal warning.',
            'key_findings': ['Do not use the operations portal for this carried work.'],
            'blocker_state': 'The carried note forbids operations-portal sign-in.',
            'next_step': 'Proceed with the confirmed local path instead.',
            'evidence': ['Constraint: do not use the operations portal for this carried work.'],
            'freshness_signal': 'Latest explicit update at 2026-03-11T11:50:00Z.',
        },
        freshness_at=datetime(2026, 3, 11, 11, 50, tzinfo=timezone.utc),
        score=17,
        evidence=[],
        container_ref='slack:channel:CLOCAL001',
        thread_ref='slack:thread:CLOCAL001:thread-ambiguous-legacy',
        envelope=_memory_envelope('episode', subjects=[inventory_scope, wallet_scope]),
    )

    constraint_state = _build_constraint_state(
        [{'item': ambiguous_legacy}],
        local_constraint_profile=None,
    )

    assert constraint_state['retained_legacy_profiles'] == []
    assert any(
        profile['result_id'] == 'memory_object:checkpoint-ambiguous-legacy-constraint'
        for profile in constraint_state['opaque_legacy_profiles']
    )

def test_typed_precise_coverage_suppresses_only_equivalent_legacy_fallback() -> None:
    inventory_scope = MemorySubjectAnchor(kind='workstream', value='inventory batch digest')
    wallet_scope = MemorySubjectAnchor(kind='workstream', value='wallet reserve snapshot')
    constraint_state = _build_constraint_state(
        [
            {'item': _inventory_batch_typed_constraint_result(score=20)},
            {
                'item': _inventory_batch_constraint_checkpoint_result(
                    memory_object_id='checkpoint-batch-constraint-covered-legacy',
                    score=18,
                    envelope=_memory_envelope('episode', subjects=[inventory_scope]),
                )
            },
            {
                'item': QueryResultItem(
                    result_kind='memory_hit',
                    memory_object_id='checkpoint-wallet-constraint-legacy',
                    type='task_checkpoint',
                    payload={
                        'summary': 'The wallet reserve snapshot carries an explicit no-login constraint.',
                        'task': 'Resume the wallet reserve snapshot review.',
                        'current_state': 'The wallet reserve snapshot is prepared for WAL-102 and WAL-208.',
                        'key_findings': [
                            'Do not use the operations portal for the wallet reserve snapshot.',
                        ],
                        'blocker_state': 'The wallet reserve snapshot forbids operations-portal sign-in during this review.',
                        'next_step': 'Confirm the local snapshot before publishing the wallet reserve note.',
                        'evidence': [
                            'Constraint: do not use the operations portal for the wallet reserve snapshot.',
                        ],
                        'freshness_signal': 'Latest explicit update at 2026-03-11T11:20:00Z.',
                    },
                    freshness_at=datetime(2026, 3, 11, 11, 20, tzinfo=timezone.utc),
                    score=17,
                    evidence=[],
                    container_ref='slack:channel:CLOCAL001',
                    thread_ref='slack:thread:CLOCAL001:thread-wallet-constraint',
                    envelope=_memory_envelope('episode', subjects=[wallet_scope]),
                )
            },
        ],
        local_constraint_profile=None,
    )

    active_typed = constraint_state['active_typed_profiles']
    retained_legacy = constraint_state['retained_legacy_profiles']
    typed_inventory_key = 'workstream:inventory batch digest|surface:operations portal|use_surface'
    wallet_legacy_key = 'workstream:wallet reserve snapshot|surface:operations portal|use_surface'
    assert any(profile['precise_coverage_key'] == typed_inventory_key for profile in active_typed)
    assert all(profile['precise_coverage_key'] != typed_inventory_key for profile in retained_legacy)
    assert any(
        profile['anchor_result_id'] == 'memory_object:checkpoint-wallet-constraint-legacy'
        and profile['precise_coverage_key'] == wallet_legacy_key
        for profile in retained_legacy
    )

def test_same_thread_wallet_recall_prefers_wallet_memory_over_adjacent_batch_auth_pollution() -> None:
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
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='thread-y-msg-1',
                source_type='chat_message',
                source_id='thread-y-msg-1',
                excerpt='hello again',
                occurred_at=datetime(2026, 3, 11, 13, 5, tzinfo=timezone.utc),
                container_ref='slack:channel:CLOCAL001',
                thread_ref='slack:thread:CLOCAL001:thread-y',
                artifact_kind='message',
                role='user',
                score=18,
                evidence=[],
            ),
            _inventory_batch_constraint_checkpoint_result(score=18),
            _inventory_batch_constraint_summary_result(score=17),
            _inventory_batch_conflicting_retry_checkpoint_result(score=16),
            _wallet_snapshot_checkpoint_result(score=15),
            _wallet_snapshot_summary_result(score=14),
        ],
        trace=QueryTrace(
            query_text='what is the latest we have in wallet?',
            query_tokens=('what', 'is', 'the', 'latest', 'we', 'have', 'in', 'wallet'),
            limit=6,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='what is the latest we have in wallet?',
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
    assert any(block.memory_type in {'task_checkpoint', 'thread_summary'} for block in outcome.injectable_blocks)
    assert 'wallet reserve snapshot' in rendered_blocks
    assert 'inventory batch digest' not in rendered_blocks
    assert 'attempt to authenticate' not in rendered_blocks
    assert 'operations portal' not in rendered_blocks
    assert 'hello again' not in rendered_blocks

def test_surface_anchor_prefilter_keeps_same_surface_constraints_even_with_different_workstreams_in_v1() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(container_ref='slack:channel:CLOCAL001')
    inventory_scope = MemorySubjectAnchor(kind='workstream', value='inventory batch digest')
    wallet_scope = MemorySubjectAnchor(kind='workstream', value='wallet reserve snapshot')
    retrieval_result = RetrievalQueryResult(
        results=[
            _inventory_batch_typed_constraint_result(score=19),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='constraint-wallet-portal-surface-query',
                type='constraint_memory',
                payload={
                    'summary': 'Constraint: do not use operations portal for wallet reserve snapshot.',
                    'constraint_text': 'Do not use the operations portal for the wallet reserve snapshot.',
                    'primary_scope_anchor': {'kind': 'workstream', 'value': 'wallet reserve snapshot'},
                    'target_anchor': {'kind': 'surface', 'value': 'operations portal'},
                    'action_class': 'use_surface',
                    'polarity': 'prohibit',
                    'strength': 'hard',
                    'status': 'active',
                    'evidence': ['Do not use the operations portal for the wallet reserve snapshot.'],
                    'freshness_signal': 'Latest explicit update at 2026-03-11T12:15:00Z.',
                    'confidence': 'high',
                },
                freshness_at=datetime(2026, 3, 11, 12, 15, tzinfo=timezone.utc),
                score=18,
                evidence=[],
                container_ref='slack:channel:CLOCAL001',
                thread_ref='slack:thread:CLOCAL001:thread-wallet-constraint',
                envelope=_memory_envelope('constraint', confidence='high', subjects=[wallet_scope, MemorySubjectAnchor(kind='surface', value='operations portal')]),
            ),
        ],
        trace=QueryTrace(
            query_text='What constraint had I given you about operations portal?',
            query_tokens=('what', 'constraint', 'had', 'i', 'given', 'you', 'about', 'operations', 'portal'),
            limit=6,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='What constraint had I given you about operations portal?',
        requested_limit=6,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='new_thread', session_has_sufficient_local_context=False),
        include_trace=True,
    )

    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    anchor_prefilter = outcome.trace.routing['anchor_prefilter']
    returned_ids = [result.memory_object_id for result in outcome.results if result.result_kind == 'memory_hit']
    assert anchor_prefilter['query_anchor_status'] == 'clear'
    assert anchor_prefilter['selected_query_anchor_kind'] == 'surface'
    assert anchor_prefilter['selected_query_anchor'] == {'kind': 'surface', 'value': 'operations portal'}
    assert anchor_prefilter['excluded_by_anchor_count'] == 0
    assert 'constraint-batch-portal' in returned_ids
    assert 'constraint-wallet-portal-surface-query' in returned_ids


def test_workstream_anchor_prefilter_excludes_same_surface_off_topic_constraint() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(container_ref='slack:channel:CLOCAL001')
    inventory_scope = MemorySubjectAnchor(kind='workstream', value='inventory batch digest')
    wallet_scope = MemorySubjectAnchor(kind='workstream', value='wallet reserve snapshot')
    wallet_constraint = QueryResultItem(
        result_kind='memory_hit',
        memory_object_id='constraint-wallet-portal-off-topic',
        type='constraint_memory',
        payload={
            'summary': 'Constraint: do not use operations portal for wallet reserve snapshot.',
            'constraint_text': 'Do not use the operations portal for the wallet reserve snapshot.',
            'primary_scope_anchor': {'kind': 'workstream', 'value': 'wallet reserve snapshot'},
            'target_anchor': {'kind': 'surface', 'value': 'operations portal'},
            'action_class': 'use_surface',
            'polarity': 'prohibit',
            'strength': 'hard',
            'status': 'active',
            'evidence': ['Do not use the operations portal for the wallet reserve snapshot.'],
            'freshness_signal': 'Latest explicit update at 2026-03-11T12:15:00Z.',
            'confidence': 'high',
        },
        freshness_at=datetime(2026, 3, 11, 12, 15, tzinfo=timezone.utc),
        score=20,
        evidence=[],
        container_ref='slack:channel:CLOCAL001',
        thread_ref='slack:thread:CLOCAL001:thread-wallet-constraint',
        envelope=_memory_envelope('constraint', confidence='high', subjects=[wallet_scope, MemorySubjectAnchor(kind='surface', value='operations portal')]),
    )
    retrieval_result = RetrievalQueryResult(
        results=[
            wallet_constraint,
            _inventory_batch_typed_constraint_result(score=18),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='checkpoint-inventory-anchor',
                type='task_checkpoint',
                payload={
                    'summary': 'The inventory batch digest is prepared for the local rerun.',
                    'task': 'Resume the inventory batch digest.',
                    'current_state': 'The local digest is prepared for BIN-103, BIN-204, BIN-317, and BIN-418.',
                    'blocker_state': 'The local digest token expired before the final rerun.',
                    'next_step': 'Refresh the local digest token and rerun the inventory batch digest.',
                },
                score=16,
                evidence=[],
                container_ref='slack:channel:CLOCAL001',
                thread_ref='slack:thread:CLOCAL001:thread-inventory-anchor',
                envelope=_memory_envelope('episode', subjects=[inventory_scope, MemorySubjectAnchor(kind='surface', value='operations portal')]),
            ),
        ],
        trace=QueryTrace(
            query_text='What constraint did we have on inventory batch digest?',
            query_tokens=('what', 'constraint', 'did', 'we', 'have', 'on', 'inventory', 'batch', 'digest'),
            limit=6,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='What constraint did we have on inventory batch digest?',
        requested_limit=6,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='new_thread', session_has_sufficient_local_context=False),
        include_trace=True,
    )

    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    anchor_prefilter = outcome.trace.routing['anchor_prefilter']
    returned_ids = [result.memory_object_id for result in outcome.results if result.result_kind == 'memory_hit']
    assert anchor_prefilter['query_anchor_status'] == 'clear'
    assert anchor_prefilter['selected_query_anchor_kind'] == 'workstream'
    assert anchor_prefilter['selected_query_anchor'] == {'kind': 'workstream', 'value': 'inventory batch digest'}
    assert anchor_prefilter['fallback_mode'] == 'aligned_only'
    assert anchor_prefilter['excluded_by_anchor_count'] == 1
    assert 'constraint-wallet-portal-off-topic' not in returned_ids
    assert 'constraint-batch-portal' in returned_ids
    assert any(
        item['result_id'] == 'memory_object:constraint-wallet-portal-off-topic'
        and item['reason_code'] == 'anchor_conflict'
        for item in anchor_prefilter.get('excluded_candidates', [])
    )


# ---------------------------------------------------------------------------
# Fix 1: evidence_trace preserves source_evidence under weak lexical support
# ---------------------------------------------------------------------------

def test_evidence_trace_preserves_source_evidence_under_weak_support() -> None:
    """evidence_trace must not fall back to lower_level_memory when source_evidence
    candidates exist but have weak query overlap.  The routing contract requires
    that raw source preference is preserved unless source_evidence is absent."""
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='chat:library-help',
        thread_ref='chat:library-help:thread-evidence-weak',
    )
    # source_hit has low lexical score (weak overlap); decision has high lexical score
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='source-evidence-weak-1',
                source_type='assistant_artifact',
                source_id='evidence-weak-artifact',
                excerpt='Partial progress: refreshed 87 catalog records before the batch token expired.',
                occurred_at=datetime(2026, 3, 11, 10, 0, tzinfo=timezone.utc),
                role='assistant',
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-evidence-weak',
                artifact_kind='tool_use_summary',
                score=3,
                evidence=[
                    EvidenceReference(
                        source_item_id='source-evidence-weak-1',
                        source_type='assistant_artifact',
                        source_id='evidence-weak-artifact',
                        occurred_at=datetime(2026, 3, 11, 10, 0, tzinfo=timezone.utc),
                        role='assistant',
                        container_ref='chat:library-help',
                        thread_ref='chat:library-help:thread-evidence-weak',
                        artifact_kind='tool_use_summary',
                    )
                ],
            ),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='decision-evidence-weak-1',
                type='decision',
                payload={
                    'summary': 'Decided to refresh the batch token and retry the catalog sync from batch 88.',
                    'decision_text': 'Refresh the batch token and retry the catalog sync from batch 88.',
                    'evidence': ['Batch token expired after refreshing 87 catalog records.'],
                    'freshness_signal': 'Latest explicit update at 2026-03-11T10:05:00Z.',
                },
                freshness_at=datetime(2026, 3, 11, 10, 5, tzinfo=timezone.utc),
                score=10,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-evidence-weak',
            ),
        ],
        trace=QueryTrace(
            query_text='Show me the raw output from the catalog sync run',
            query_tokens=('show', 'me', 'raw', 'output', 'catalog', 'sync', 'run'),
            limit=6,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='Show me the raw output from the catalog sync run',
        requested_limit=6,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='new_thread', session_has_sufficient_local_context=False),
        include_trace=True,
    )

    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    assert outcome.trace.routing['selected_layer'] == 'source_evidence', (
        f"expected source_evidence but got {outcome.trace.routing['selected_layer']!r}; "
        "evidence_trace must not fall back to lower_level_memory under weak support"
    )


def test_evidence_trace_allows_fallback_when_source_evidence_absent() -> None:
    """When no source_evidence candidates are present, evidence_trace must still be
    allowed to fall back to derived memory (lower_level_memory / decision)."""
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='chat:library-help',
        thread_ref='chat:library-help:thread-evidence-absent',
    )
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='decision-evidence-absent-1',
                type='decision',
                payload={
                    'summary': 'Decided to retry the catalog sync from batch 88 after refreshing the token.',
                    'decision_text': 'Retry the catalog sync from batch 88 after refreshing the token.',
                    'evidence': ['Token refreshed successfully.'],
                    'freshness_signal': 'Latest explicit update at 2026-03-11T11:00:00Z.',
                },
                freshness_at=datetime(2026, 3, 11, 11, 0, tzinfo=timezone.utc),
                score=12,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-evidence-absent',
            ),
        ],
        trace=QueryTrace(
            query_text='Show me the raw output from the catalog sync run',
            query_tokens=('show', 'me', 'raw', 'output', 'catalog', 'sync', 'run'),
            limit=6,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='Show me the raw output from the catalog sync run',
        requested_limit=6,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='new_thread', session_has_sufficient_local_context=False),
        include_trace=True,
    )

    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    # No source_evidence in retrieval — fallback to lower_level_memory is valid
    assert outcome.trace.routing['selected_layer'] != 'source_evidence', (
        "source_evidence was absent from retrieval results; fallback should be permitted"
    )
    assert len(outcome.results) > 0, "at least one derived memory result expected when source_evidence is absent"


# ---------------------------------------------------------------------------
# Fix 2: answer_continuity cross-thread contamination — thread affinity scoring
# ---------------------------------------------------------------------------

def test_answer_continuity_prefers_same_thread_continuity_when_no_topic_overlap() -> None:
    """When an answer_continuity query has no topic signal and two continuity_memory
    candidates are present, the one from the same thread must score higher.

    The query uses "already answered" to trigger answer_continuity intent.  The
    query tokens ('already','answered','this','before') do not appear in either
    candidate's payload text, so topic_overlap_tokens is empty for both — the
    continuity_compatibility_adjustment fires and thread affinity decides.
    """
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    # query_filters.thread_ref matches thread-b (the second candidate)
    query_filters = QueryFilters(
        container_ref='chat:library-help',
        thread_ref='chat:library-help:thread-b',
    )
    retrieval_result = RetrievalQueryResult(
        results=[
            # Slightly higher lexical score but wrong thread — gap = 5*10 = 50.
            # Adjustment delta for correct-thread: +60 (same_thread) vs +10 (same_container) = net +50.
            # Net effect: correct-thread wins by a small margin.
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='continuity-wrong-thread',
                type='continuity_memory',
                payload={
                    'summary': 'Wallet reserve snapshot reconciled for WAL-102.',
                    'answer_text': 'WAL-102 and WAL-208 are reconciled.',
                    'evidence': ['Reserve snapshot done.'],
                    'freshness_signal': '2026-03-11T12:35:00Z.',
                },
                freshness_at=datetime(2026, 3, 11, 12, 35, tzinfo=timezone.utc),
                score=15,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-a',  # wrong thread
            ),
            # Lower lexical score but correct thread
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='continuity-correct-thread',
                type='continuity_memory',
                payload={
                    'summary': 'Catalog sync token expired at batch 313.',
                    'answer_text': 'Token expired at batch 313.',
                    'evidence': ['Token expired.'],
                    'freshness_signal': '2026-03-11T10:02:00Z.',
                },
                freshness_at=datetime(2026, 3, 11, 10, 2, tzinfo=timezone.utc),
                score=10,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-b',  # same thread as query
            ),
        ],
        trace=QueryTrace(
            # "already answered" cue triggers answer_continuity intent.
            # Tokens ('already','answered','this','before') do not appear in
            # either candidate payload, so topic_overlap_tokens will be empty.
            query_text='You already answered this before.',
            query_tokens=('already', 'answered', 'this', 'before'),
            limit=4,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='You already answered this before.',
        requested_limit=4,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='new_thread', session_has_sufficient_local_context=False),
        include_trace=True,
    )

    assert outcome.trace is not None
    returned_ids = [result.memory_object_id for result in outcome.results if result.result_kind == 'memory_hit']
    assert returned_ids, "expected at least one continuity_memory result"
    assert returned_ids[0] == 'continuity-correct-thread', (
        f"expected same-thread candidate first but got {returned_ids[0]!r}; "
        "thread affinity must override higher lexical score when topic signal is absent"
    )


def test_answer_continuity_does_not_suppress_cross_thread_continuity_when_both_unanchored() -> None:
    """When both continuity_memory candidates have no thread or container affinity,
    neither should be suppressed — the higher lexical score must win and both must
    be returned (no hard filter from the compatibility adjustment)."""
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='chat:library-help',
        thread_ref='chat:library-help:thread-new',
    )
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='continuity-unanchored-high',
                type='continuity_memory',
                payload={
                    'summary': 'Catalog sync token expired at batch 313.',
                    'answer_text': 'Token expired at batch 313.',
                    'evidence': ['Token expired.'],
                    'freshness_signal': '2026-03-11T10:02:00Z.',
                },
                freshness_at=datetime(2026, 3, 11, 10, 2, tzinfo=timezone.utc),
                score=16,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-x',  # neither thread matches
            ),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='continuity-unanchored-low',
                type='continuity_memory',
                payload={
                    'summary': 'Wallet reserve snapshot reconciled for WAL-102.',
                    'answer_text': 'WAL-102 and WAL-208 are reconciled.',
                    'evidence': ['Reserve snapshot done.'],
                    'freshness_signal': '2026-03-11T12:35:00Z.',
                },
                freshness_at=datetime(2026, 3, 11, 12, 35, tzinfo=timezone.utc),
                score=14,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-y',  # neither thread matches
            ),
        ],
        trace=QueryTrace(
            query_text='You already answered this before.',
            query_tokens=('already', 'answered', 'this', 'before'),
            limit=4,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='You already answered this before.',
        requested_limit=4,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='new_thread', session_has_sufficient_local_context=False),
        include_trace=True,
    )

    memory_results = [r for r in outcome.results if r.result_kind == 'memory_hit']
    returned_ids = [r.memory_object_id for r in memory_results]
    # Both cross-thread candidates must survive — no hard suppression
    assert 'continuity-unanchored-high' in returned_ids, (
        "higher-scored cross-thread continuity candidate must not be suppressed"
    )
    assert 'continuity-unanchored-low' in returned_ids, (
        "lower-scored cross-thread continuity candidate must not be suppressed when no affinity exists"
    )
    # Higher lexical score wins when both have equal (no) affinity
    assert returned_ids[0] == 'continuity-unanchored-high', (
        f"expected higher-lexical-score candidate first but got {returned_ids[0]!r}"
    )


def test_answer_continuity_same_container_alone_does_not_override_wrong_candidate() -> None:
    """Container affinity alone must not promote a cross-thread candidate over a
    same-thread candidate when both share the same container."""
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='chat:library-help',
        thread_ref='chat:library-help:thread-c',
    )
    retrieval_result = RetrievalQueryResult(
        results=[
            # Higher lexical score, same container, wrong thread.
            # Adjustment: same_container only → +10.  Same-thread candidate gets +60.
            # Score gap = 4*10 = 40, adjustment gap = 50 → same-thread wins.
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='continuity-same-container-wrong-thread',
                type='continuity_memory',
                payload={
                    'summary': 'Wallet reserve snapshot reconciled for WAL-102.',
                    'answer_text': 'WAL-102 and WAL-208 are reconciled.',
                    'evidence': ['Reserve snapshot done.'],
                    'freshness_signal': '2026-03-11T12:35:00Z.',
                },
                freshness_at=datetime(2026, 3, 11, 12, 35, tzinfo=timezone.utc),
                score=14,
                evidence=[],
                container_ref='chat:library-help',  # same container
                thread_ref='chat:library-help:thread-a',  # wrong thread
            ),
            # Lower lexical score, same container, same thread
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='continuity-same-thread',
                type='continuity_memory',
                payload={
                    'summary': 'Catalog sync token expired at batch 313.',
                    'answer_text': 'Token expired at batch 313.',
                    'evidence': ['Token expired.'],
                    'freshness_signal': '2026-03-11T10:02:00Z.',
                },
                freshness_at=datetime(2026, 3, 11, 10, 2, tzinfo=timezone.utc),
                score=10,
                evidence=[],
                container_ref='chat:library-help',  # same container
                thread_ref='chat:library-help:thread-c',  # same thread as query
            ),
        ],
        trace=QueryTrace(
            query_text='You already answered this before.',
            query_tokens=('already', 'answered', 'this', 'before'),
            limit=4,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='You already answered this before.',
        requested_limit=4,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='new_thread', session_has_sufficient_local_context=False),
        include_trace=True,
    )

    returned_ids = [r.memory_object_id for r in outcome.results if r.result_kind == 'memory_hit']
    assert returned_ids, "expected at least one continuity_memory result"
    assert returned_ids[0] == 'continuity-same-thread', (
        f"expected same-thread candidate first but got {returned_ids[0]!r}; "
        "same-container-only affinity must not override thread affinity"
    )


# ---------------------------------------------------------------------------
# Fix B: negative-source suppression for evidence_trace (interim guardrail)
# ---------------------------------------------------------------------------

def test_evidence_trace_suppresses_source_that_disclaims_having_exact_evidence() -> None:
    """evidence_trace must not inject source text that explicitly states the
    exact evidence was not retained ("did not keep the exact line", etc.).

    The source excerpt says "I did not keep the exact line."  Pallium should
    return no_relevant_memory rather than injecting a source that explicitly
    disclaims having what the user is asking for.
    """
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='chat:library-help',
        thread_ref='chat:library-help:thread-evidence-disclaimer',
    )
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='weak-evidence-1',
                source_type='assistant_artifact',
                source_id='assistant-output-weak',
                excerpt=(
                    'We probably saw it in the logs, but I did not keep the exact line. '
                    'The general takeaway was that the retries looked like they were colliding.'
                ),
                score=6,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-evidence-disclaimer',
            ),
        ],
        trace=QueryTrace(
            query_text='I need the exact quote for the incident note, not the general takeaway.',
            query_tokens=('exact', 'for', 'general', 'i', 'incident', 'need', 'not', 'note', 'quote', 'takeaway', 'the'),
            limit=5,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='I need the exact quote for the incident note, not the general takeaway.',
        requested_limit=5,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='new_thread', session_has_sufficient_local_context=False),
        include_trace=True,
    )

    assert outcome.should_inject is False, (
        "source explicitly disclaims having the exact evidence; must not inject"
    )
    assert outcome.decision_reason == 'no_relevant_memory', (
        f"expected no_relevant_memory but got {outcome.decision_reason!r}"
    )


def test_evidence_trace_injects_source_without_evidence_disclaimer() -> None:
    """evidence_trace must still inject a source that does not disclaim
    having the evidence — the negative-source guard should only fire on
    explicit disclaimers, not on all source evidence.
    """
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='chat:library-help',
        thread_ref='chat:library-help:thread-evidence-present',
    )
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='strong-evidence-1',
                source_type='assistant_artifact',
                source_id='assistant-output-strong',
                excerpt=(
                    'The exact log output for the incident shows the catalog API '
                    'returned 429 for every retry — not a transient blip, a sustained limit.'
                ),
                score=8,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-evidence-present',
            ),
        ],
        trace=QueryTrace(
            query_text='I need the exact quote for the incident note, not the general takeaway.',
            query_tokens=('exact', 'for', 'general', 'i', 'incident', 'need', 'not', 'note', 'quote', 'takeaway', 'the'),
            limit=5,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='I need the exact quote for the incident note, not the general takeaway.',
        requested_limit=5,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='new_thread', session_has_sufficient_local_context=False),
        include_trace=True,
    )

    assert outcome.should_inject is True, (
        "source does not disclaim having the evidence; injection must proceed"
    )
    assert len(outcome.results) == 1
    assert outcome.results[0].source_item_id == 'strong-evidence-1'


def test_evidence_trace_disclaimer_variants_all_suppress() -> None:
    """Each recognized disclaimer phrase must individually trigger suppression."""
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    disclaimer_excerpts = [
        "I did not keep the exact line from the log.",
        "We didn't keep that output anywhere.",
        "I don't have the exact wording from before.",
        "The output was not preserved after the session.",
        "That detail wasn't preserved in my notes.",
    ]
    for excerpt in disclaimer_excerpts:
        query_filters = QueryFilters(
            container_ref='chat:library-help',
            thread_ref='chat:library-help:thread-disclaimer-variants',
        )
        retrieval_result = RetrievalQueryResult(
            results=[
                QueryResultItem(
                    result_kind='source_hit',
                    source_item_id='weak-evidence-variant',
                    source_type='assistant_artifact',
                    source_id='assistant-output-variant',
                    excerpt=excerpt,
                    score=5,
                    evidence=[],
                    container_ref='chat:library-help',
                    thread_ref='chat:library-help:thread-disclaimer-variants',
                ),
            ],
            trace=QueryTrace(
                query_text='I need the exact quote for the incident note, not the general takeaway.',
                query_tokens=('exact', 'quote', 'incident', 'note'),
                limit=5,
                filters=query_filters,
                stages=(),
            ),
        )
        outcome = plugin.route_query_results(
            text='I need the exact quote for the incident note, not the general takeaway.',
            requested_limit=5,
            retrieval_result=retrieval_result,
            query_filters=query_filters,
            runtime_context=QueryRuntimeContext(turn_kind='new_thread', session_has_sufficient_local_context=False),
        )
        assert outcome.should_inject is False, (
            f"disclaimer phrase in excerpt {excerpt[:60]!r} did not suppress injection"
        )


# ---------------------------------------------------------------------------
# Fix D — packaging: _task_checkpoint_injection_text leads with active blocker
# ---------------------------------------------------------------------------

from semantic.agent_conversation_memory_routing import _task_checkpoint_injection_text


def test_task_checkpoint_injection_text_leads_with_blocker_when_present() -> None:
    # When an active blocker is present, it must appear before current_state.
    payload = {
        "summary": "Working on catalog sync.",
        "current_state": "Partial sync completed through batch 417.",
        "blocker_state": "Rate-limiting on the catalog API is blocking further progress.",
        "next_step": "Wait for rate-limit window to reset.",
    }
    text = _task_checkpoint_injection_text(payload)
    blocker_pos = text.lower().find("rate-limiting")
    current_state_pos = text.lower().find("partial sync")
    assert blocker_pos != -1, "blocker text must appear in injection text"
    assert current_state_pos != -1, "current_state text must appear in injection text"
    assert blocker_pos < current_state_pos, (
        f"blocker must precede current_state in injection text; got:\n{text!r}"
    )


def test_task_checkpoint_injection_text_no_blocker_leads_with_current_state() -> None:
    # When no blocker is present, current_state leads as before.
    payload = {
        "summary": "Working on catalog sync.",
        "current_state": "Sync completed through batch 417.",
        "blocker_state": "",
        "next_step": "Proceed to batch 418.",
    }
    text = _task_checkpoint_injection_text(payload)
    assert "Sync completed through batch 417" in text
    # No blocker label should appear
    assert "Blocker:" not in text


def test_task_checkpoint_injection_text_blocker_only_no_current_state() -> None:
    # When only a blocker is present (no current_state), the blocker is still emitted.
    payload = {
        "summary": "Debugging catalog sync failures.",
        "current_state": "",
        "blocker_state": "The catalog API returns 429 on every retry.",
        "next_step": "",
    }
    text = _task_checkpoint_injection_text(payload)
    assert "429" in text
    assert "Blocker:" in text


# ---------------------------------------------------------------------------
# Fix C — abstract constraint-intent phrase/token expansion
# "Anything I should avoid relying on here?" must route as constraint_recall
# ---------------------------------------------------------------------------


def test_abstract_avoidance_query_routes_as_constraint_recall() -> None:
    # The query uses abstract meta-vocabulary ("avoid relying") with no domain-
    # specific tool names.  After Fix C, the constraint_recall token set includes
    # "avoid" and "relying", so this query must produce a constraint_recall shape
    # tag and route to structured constraint memory.
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='chat:library-help',
        thread_ref='chat:library-help:thread-abstract-constraint',
    )
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='summary-abstract-constraint',
                type='thread_summary',
                payload={
                    'summary': (
                        'Constraint: do not rely on the Jira API or the admin portal during this session. '
                        'The operator has restricted both external service endpoints for this context.'
                    ),
                },
                freshness_at=datetime(2026, 3, 11, 10, 2, tzinfo=timezone.utc),
                score=4,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-history-constraint',
            ),
        ],
        trace=QueryTrace(
            query_text='Anything I should avoid relying on here?',
            query_tokens=('anything', 'i', 'should', 'avoid', 'relying', 'on', 'here'),
            limit=4,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='Anything I should avoid relying on here?',
        requested_limit=4,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='new_thread', session_has_sufficient_local_context=False),
        include_trace=True,
    )

    assert outcome.should_inject is True, "abstract avoidance query must inject constraint memory"
    assert outcome.trace is not None
    routing = outcome.trace.routing
    assert routing is not None
    family_inference = routing.get('family_inference', {})
    query_shape_tags = list(family_inference.get('query_shape_tags', []))
    assert 'constraint_recall' in query_shape_tags, (
        f"'constraint_recall' shape tag missing; got shape tags: {query_shape_tags}"
    )


def test_abstract_avoid_phrase_routes_as_constraint_recall() -> None:
    # "Anything I should avoid" (phrase match) must also trigger constraint_recall.
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(container_ref='chat:library-help')
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='summary-avoid-phrase',
                type='thread_summary',
                payload={
                    'summary': (
                        'Constraint: avoid using the operations portal for the inventory batch digest.'
                    ),
                },
                freshness_at=datetime(2026, 3, 11, 10, 2, tzinfo=timezone.utc),
                score=3,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-avoid-phrase',
            ),
        ],
        trace=QueryTrace(
            query_text='Anything I should avoid here for this batch run?',
            query_tokens=('anything', 'i', 'should', 'avoid', 'here', 'for', 'this', 'batch', 'run'),
            limit=4,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='Anything I should avoid here for this batch run?',
        requested_limit=4,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='new_thread', session_has_sufficient_local_context=False),
        include_trace=True,
    )

    assert outcome.trace is not None
    routing = outcome.trace.routing
    family_inference = routing.get('family_inference', {})
    query_shape_tags = list(family_inference.get('query_shape_tags', []))
    assert 'constraint_recall' in query_shape_tags, (
        f"'constraint_recall' shape tag missing for 'anything i should avoid'; got: {query_shape_tags}"
    )


def test_generic_negated_question_does_not_trigger_constraint_recall() -> None:
    # "Anything I should not miss before continuing?" is a planning/resumption
    # question, not a constraint-recall query.  It must NOT carry the
    # constraint_recall shape tag (the phrase "anything i should not" was
    # removed because it matched too broadly).
    from semantic.agent_conversation_memory_routing import _routing_query_tokens, _query_shape_tags
    texts = [
        "Anything I should not miss before continuing?",
        "Anything I should not change yet?",
        "Anything I should not forget to check?",
    ]
    for text in texts:
        tokens = _routing_query_tokens(text)
        tags = _query_shape_tags(text, tokens)
        assert 'constraint_recall' not in tags, (
            f"generic negated question {text!r} must not trigger constraint_recall; got tags: {tags}"
        )
