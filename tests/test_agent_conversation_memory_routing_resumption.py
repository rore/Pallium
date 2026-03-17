from __future__ import annotations

from tests.agent_conversation_memory_routing_helpers import *

def test_work_resumption_routes_task_checkpoint_first(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest_resumption_work(client, thread_ref='chat:library-help:thread-routing-work-001')

        payload = _run_debug_query(
            client,
            {
                'text': 'What blocker did we hit, what progress was preserved, and what should we do next on the catalog sync retry?',
                'limit': 6,
                'container_ref': 'chat:library-help',
            },
        )
        routing = payload['trace']['routing']

        assert routing['query_intent'] == 'work_resumption'
        assert routing['preferred_layers'][0] == 'task_checkpoint'
        assert routing['packaging']['mode'] == 'task_checkpoint_plus_adjacent_evidence'
        assert [item['signal_type'] for item in routing['packaging']['adjacent_evidence'][:2]] == ['blocker', 'next_step']
        assert payload['results'][0]['result_kind'] == 'memory_hit'
        assert payload['results'][0]['type'] == 'task_checkpoint'
        assert {payload['results'][1]['artifact_kind'], payload['results'][2]['artifact_kind']} == {'tool_use_summary', 'todo_snapshot'}
        checkpoint_payload = payload['results'][0]['payload']
        assert 'service token expired' in checkpoint_payload['blocker_state'].lower()
        assert 'refresh the catalog service token' in checkpoint_payload['next_step'].lower()
        assert 'blocker' in routing['selected_results'][0]['work_signal_types']
        assert 'freshness' in routing['selected_results'][0]['work_signal_types']
        assert routing['kind_prefilter']['allowed_kinds'] == ['episode', 'finding', 'summary']
        assert routing['selected_results'][0]['candidate_envelope_kind'] == 'episode'
        assert routing['selected_results'][0]['kind_prefilter_status'] == 'allowed'

def test_work_resumption_demotes_thin_checkpoint_when_fresher_source_state_is_sharper() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(container_ref='chat:library-help')
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='checkpoint-thin',
                type='task_checkpoint',
                payload={
                    'summary': 'Older catalog sync retry state.',
                    'task': 'Resume the catalog sync retry.',
                    'current_state': 'Earlier retry paused after the auth failure.',
                    'latest_occurred_at': '2026-03-11T10:02:00Z',
                },
                score=18,
                evidence=[
                    EvidenceReference(
                        source_item_id='source-old',
                        source_type='assistant_artifact',
                        source_id='artifact-old',
                        occurred_at=datetime(2026, 3, 11, 10, 2, tzinfo=timezone.utc),
                        container_ref='chat:library-help',
                        thread_ref='chat:library-help:thread-routing-work-thin',
                        artifact_kind='tool_use_summary',
                    )
                ],
            ),
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='source-fresh-blocker',
                source_type='assistant_artifact',
                source_id='artifact-fresh-blocker',
                excerpt='Blocked: catalog API returned 429 after batch 417 because the retry window was exhausted.',
                occurred_at=datetime(2026, 3, 11, 12, 1, tzinfo=timezone.utc),
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-routing-work-thin',
                artifact_kind='tool_use_summary',
                score=14,
                evidence=[
                    EvidenceReference(
                        source_item_id='source-fresh-blocker',
                        source_type='assistant_artifact',
                        source_id='artifact-fresh-blocker',
                        occurred_at=datetime(2026, 3, 11, 12, 1, tzinfo=timezone.utc),
                        container_ref='chat:library-help',
                        thread_ref='chat:library-help:thread-routing-work-thin',
                        artifact_kind='tool_use_summary',
                    )
                ],
            ),
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='source-fresh-next-step',
                source_type='assistant_artifact',
                source_id='artifact-fresh-next-step',
                excerpt='Next step: wait 15 minutes and resume from batch 418 with the refreshed token.',
                occurred_at=datetime(2026, 3, 11, 12, 2, tzinfo=timezone.utc),
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-routing-work-thin',
                artifact_kind='todo_snapshot',
                score=13,
                evidence=[
                    EvidenceReference(
                        source_item_id='source-fresh-next-step',
                        source_type='assistant_artifact',
                        source_id='artifact-fresh-next-step',
                        occurred_at=datetime(2026, 3, 11, 12, 2, tzinfo=timezone.utc),
                        container_ref='chat:library-help',
                        thread_ref='chat:library-help:thread-routing-work-thin',
                        artifact_kind='todo_snapshot',
                    )
                ],
            ),
        ],
        trace=QueryTrace(
            query_text='What blocker remains now and what should we do next on the catalog sync retry?',
            query_tokens=('blocker', 'next', 'retry', 'sync'),
            limit=3,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='What blocker remains now and what should we do next on the catalog sync retry?',
        requested_limit=3,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        include_trace=True,
    )

    results = outcome.results
    trace = outcome.trace
    assert results[0].result_kind == 'source_hit'
    assert results[1].result_kind == 'source_hit'
    assert {results[0].artifact_kind, results[1].artifact_kind} == {'tool_use_summary', 'todo_snapshot'}
    assert any(item.result_kind == 'memory_hit' and item.type == 'task_checkpoint' for item in results)
    assert trace is not None
    assert trace.routing is not None
    assert trace.routing['packaging']['demoted_task_checkpoint']['result_id'] == 'memory_object:checkpoint-thin'
    assert 'thin_checkpoint' in trace.routing['packaging']['demoted_task_checkpoint']['packaging_reasons']

def test_vague_resumed_session_prompt_uses_checkpoint_shape_without_resume_cues() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(container_ref='chat:library-help', thread_ref='chat:library-help:thread-routing-vague-work')
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='checkpoint-vague-work',
                type='task_checkpoint',
                payload={
                    'summary': 'Catalog sync retry remains blocked after partial progress.',
                    'task': 'Finish the catalog sync retry.',
                    'current_state': 'Refreshed 312 reservation records before the retry stopped.',
                    'key_findings': ['Service token expired during the retry window.'],
                    'blocker_state': 'Catalog API returned 401 because the service token expired.',
                    'next_step': 'Refresh the token and rerun from batch 313.',
                    'evidence': ['Tool run recorded the 401 on the catalog sync retry.'],
                    'freshness_signal': 'Latest explicit update at 2026-03-11T10:02:00Z.',
                },
                score=18,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-routing-vague-work',
            ),
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='source-vague-work',
                source_type='assistant_artifact',
                source_id='artifact-vague-work',
                excerpt='Blocked: catalog API returned 401 because the service token expired.',
                occurred_at=datetime(2026, 3, 11, 10, 1, tzinfo=timezone.utc),
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-routing-vague-work',
                artifact_kind='tool_use_summary',
                score=14,
                evidence=[
                    EvidenceReference(
                        source_item_id='source-vague-work',
                        source_type='assistant_artifact',
                        source_id='artifact-vague-work',
                        occurred_at=datetime(2026, 3, 11, 10, 1, tzinfo=timezone.utc),
                        container_ref='chat:library-help',
                        thread_ref='chat:library-help:thread-routing-vague-work',
                        artifact_kind='tool_use_summary',
                    )
                ],
            ),
        ],
        trace=QueryTrace(
            query_text='Can you orient me on the catalog sync retry?',
            query_tokens=('orient', 'catalog', 'sync', 'retry'),
            limit=4,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='Can you orient me on the catalog sync retry?',
        requested_limit=4,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(
            turn_kind='resumed_session',
            session_has_sufficient_local_context=False,
        ),
        include_trace=True,
    )

    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    family_inference = outcome.trace.routing['family_inference']
    assert outcome.trace.routing['query_intent'] == 'work_resumption'
    assert family_inference['candidate_signals']['strong_task_checkpoint_in_scope'] is True
    assert 'resumed_session_runtime' in family_inference['family_scores']['work_resumption']['reasons']
    assert 'missing_resume_query_shape' not in family_inference['family_scores']['work_resumption']['reasons']

def test_work_resumption_excludes_conflicting_checkpoint_but_keeps_compatible_status() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='chat:library-help',
        thread_ref='chat:library-help:thread-resume-conflict',
        session_ref='session:resume-conflict',
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
                score=20,
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
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='source-compatible-next-step',
                source_type='assistant_artifact',
                source_id='artifact-compatible-next-step',
                excerpt='Next step: refresh the catalog service token and rerun the sync from batch 313 without using the admin portal.',
                occurred_at=datetime(2026, 3, 11, 10, 2, tzinfo=timezone.utc),
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-history',
                artifact_kind='todo_snapshot',
                score=15,
                evidence=[
                    EvidenceReference(
                        source_item_id='source-compatible-next-step',
                        source_type='assistant_artifact',
                        source_id='artifact-compatible-next-step',
                        occurred_at=datetime(2026, 3, 11, 10, 2, tzinfo=timezone.utc),
                        container_ref='chat:library-help',
                        thread_ref='chat:library-help:thread-history',
                        artifact_kind='todo_snapshot',
                    )
                ],
            ),
        ],
        trace=QueryTrace(
            query_text='What blocker did we hit and what should we do next on the catalog sync retry?',
            query_tokens=('what', 'blocker', 'did', 'we', 'hit', 'what', 'should', 'we', 'do', 'next', 'catalog', 'sync', 'retry'),
            limit=4,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='What blocker did we hit and what should we do next on the catalog sync retry?',
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
    assert outcome.trace.routing['query_intent'] == 'work_resumption'
    assert outcome.trace.routing['selected_layer'] == 'task_checkpoint'
    assert outcome.trace.routing['packaging']['mode'] == 'compatible_work_resumption'
    assert 'refresh the catalog service token' in rendered_blocks
    assert 'reconnect the external workspace once access is restored' not in rendered_blocks
    assert 'conflicts_with_active_constraint' in excluded

def test_work_resumption_with_only_self_conflicting_checkpoint_fails_closed() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(
        container_ref='chat:library-help',
        thread_ref='chat:library-help:thread-resume-only-bad-checkpoint',
        session_ref='session:resume-only-bad-checkpoint',
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
            query_text='What blocker did we hit and what should we do next on the catalog sync retry?',
            query_tokens=('what', 'blocker', 'did', 'we', 'hit', 'what', 'should', 'we', 'do', 'next', 'catalog', 'sync', 'retry'),
            limit=4,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='What blocker did we hit and what should we do next on the catalog sync retry?',
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
    assert outcome.trace.routing['packaging']['mode'] == 'compatible_work_resumption'
    excluded = {item['excluded_reason_code'] for item in outcome.trace.routing['excluded_high_scoring_candidates']}
    assert 'conflicts_with_active_constraint' in excluded
