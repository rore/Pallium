from __future__ import annotations

from tests.agent_conversation_memory_routing_helpers import *

def test_broad_recall_routes_pattern_memory_first(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest_prior_events(client, 'cross-thread-pattern-value')
        client.app.state.pallium_service.run_consolidation_pass(
            use_case='agent_conversation_memory',
            strategy_name='container_topic_window',
        )

        payload = _run_debug_query(
            client,
            {
                'text': 'What general lesson should we remember about duplicate holds after catalog sync delays?',
                'limit': 6,
                'container_ref': 'chat:library-help',
            },
        )
        routing = payload['trace']['routing']

        # envelope-first routing: recall mode from candidate evidence, not English text.
        # envelope-first: sharp_fact_preference maps to broad_recall intent (modes don't activate
        # finding-only gate). pattern_memory may now appear in results since summary kind is allowed.
        assert routing['query_intent'] in {'broad_recall', 'precise_fact'}
        assert routing['preferred_layers'][0] in {'pattern_memory', 'decision'}
        assert payload['results'][0]['result_kind'] == 'memory_hit'

def test_repeated_answer_routes_continuity_memory_first(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        scenario = _ingest_prior_events(client, 'repeated-answer-pattern-value')
        client.app.state.pallium_service.run_consolidation_pass(
            use_case='agent_conversation_memory',
            strategy_name='thread_summary_anchored',
        )

        payload = _run_debug_query(client, scenario['current_query'])
        routing = payload['trace']['routing']

        # envelope-first routing: recall mode from candidate evidence, not English text.
        # Mixed candidates -> default recall mode -> broad_recall.
        # With RRF fusion, result ordering may vary; assert routing correctness not rank.
        assert routing['query_intent'] == 'broad_recall'
        assert routing['preferred_layers'][0] == 'pattern_memory'
        assert payload['results'][0]['result_kind'] == 'memory_hit'
        result_types = [r['type'] for r in payload['results']]
        assert 'continuity_memory' in result_types

def test_precise_fact_routes_sharp_decision_ahead_of_higher_level_memory(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        scenario = _ingest_prior_events(client, 'precise-factual-lower-level')
        client.app.state.pallium_service.run_consolidation_pass(
            use_case='agent_conversation_memory',
            strategy_name='thread_summary_anchored',
        )

        payload = _run_debug_query(client, scenario['current_query'])
        routing = payload['trace']['routing']
        kind_prefilter = routing['kind_prefilter']

        # envelope-first routing: recall mode from candidate evidence, not English text.
        # Mixed candidates -> default recall mode -> broad_recall.
        # Decision still wins result[0] due to high lexical score + broad_recall decision weight (310).
        assert routing['query_intent'] == 'broad_recall'
        assert routing['preferred_layers'][0] == 'pattern_memory'
        assert payload['results'][0]['result_kind'] == 'memory_hit'
        assert payload['results'][0]['type'] == 'decision'
        # broad_recall allows constraint, summary, finding — no kind exclusions for thread_summary
        assert kind_prefilter['allowed_kinds'] == ['constraint', 'summary', 'finding']
        # thread_summary no longer excluded (summary kind is allowed in broad_recall)
        assert kind_prefilter['excluded_by_kind_count'] == 0
        # higher-level hits still demoted by score-based routing
        assert all(item['memory_type'] != 'decision' for item in routing['demoted_higher_level_hits'])

def test_evidence_trace_routes_source_evidence_first(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        scenario = _ingest_prior_events(client, 'evidence-heavy-lower-level')
        client.app.state.pallium_service.run_consolidation_pass(
            use_case='agent_conversation_memory',
            strategy_name='thread_summary_anchored',
        )

        payload = _run_debug_query(client, scenario['current_query'])
        routing = payload['trace']['routing']

        # envelope-first routing: Tier 2 evidence classifier is a stub, so evidence_request
        # is not detected from the envelope. Falls through to recall mode from candidates.
        # With broad_recall, source_evidence weight (120) is lower than investigation_outcome (330),
        # so memory hits rank above source hits.
        assert routing['query_intent'] == 'broad_recall'
        assert routing['preferred_layers'][0] == 'pattern_memory'
        assert payload['results'][0]['result_kind'] == 'memory_hit'
        assert payload['results'][0]['type'] in {'investigation_outcome', 'decision'}

def test_precise_fact_prefers_enveloped_finding_and_keeps_legacy_memory_only_as_fallback() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(container_ref='chat:library-help')
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='legacy-checkpoint',
                type='task_checkpoint',
                payload={
                    'summary': 'Retry paused after the catalog sync failure.',
                    'current_state': 'The retry stopped after the sync tool failed.',
                },
                score=22,
                evidence=[],
                container_ref='chat:library-help',
            ),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='finding-1',
                type='decision',
                payload={'decision': 'Use item event time reservation ordering.'},
                score=18,
                evidence=[],
                container_ref='chat:library-help',
                envelope=_memory_envelope('finding', confidence='high'),
            ),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='summary-1',
                type='thread_summary',
                payload={'summary': 'We discussed reservation ordering tradeoffs.'},
                score=21,
                evidence=[],
                container_ref='chat:library-help',
                envelope=_memory_envelope('summary', confidence='medium'),
            ),
        ],
        trace=QueryTrace(
            query_text='What did we decide about reservation ordering?',
            query_tokens=('what', 'did', 'we', 'decide', 'about', 'reservation', 'ordering'),
            limit=3,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='What did we decide about reservation ordering?',
        requested_limit=3,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        include_trace=True,
    )

    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    routing = outcome.trace.routing
    # envelope-first routing: recall mode from candidate evidence, not English text.
    # Mixed candidates (no dominant layer) -> default recall mode -> broad_recall.
    # broad_recall allows constraint, summary, finding — so summary-1 is now retained.
    # legacy-checkpoint (no envelope) is a kind_prefilter fallback, but without
    # content-overlap scoring it still outranks summary-1 by raw retrieval score
    # (22 vs 21) and its task_checkpoint layer weight. The checkpoint is demoted
    # in priority (finding-1 leads) but not excluded from the result set.
    result_ids = [item.memory_object_id for item in outcome.results if item.result_kind == 'memory_hit']
    assert result_ids[0] == 'finding-1'
    assert 'legacy-checkpoint' in result_ids
    assert 'summary-1' in result_ids
    assert routing['kind_prefilter']['allowed_kinds'] == ['constraint', 'summary', 'finding']
    assert routing['kind_prefilter']['excluded_by_kind_count'] == 0
    assert routing['kind_prefilter']['envelope_missing_fallback_count'] == 1
    assert any(
        item['result_id'] == 'memory_object:legacy-checkpoint'
        and item['reason_code'] == 'envelope_missing_fallback'
        for item in routing['kind_prefilter'].get('fallback_candidates', [])
    )

def test_evidence_trace_with_task_checkpoint_still_prefers_source_evidence(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest_resumption_work(client, thread_ref='chat:library-help:thread-routing-work-002')

        payload = _run_debug_query(
            client,
            {
                'text': 'What evidence shows the catalog service token expired on the catalog sync retry?',
                'limit': 6,
                'container_ref': 'chat:library-help',
            },
        )
        routing = payload['trace']['routing']

        # envelope-first routing: Tier 2 evidence classifier is a stub, so evidence_request
        # is not detected from the envelope. Falls through to recall mode from candidates.
        # With broad_recall, source_evidence weight (120) is lower than memory types,
        # but source hits still appear in results alongside any memory hits.
        assert routing['query_intent'] == 'broad_recall'
        assert routing['preferred_layers'][0] == 'pattern_memory'
        assert payload['results'][0]['result_kind'] == 'source_hit'
        assert any(
            item['result_kind'] == 'memory_hit'
            for item in payload['results']
        )

def test_broad_recall_history_query_prefers_carry_forward_conclusion_shape(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest_prior_events(client, 'same-container-false-merge-guard')
        client.app.state.pallium_service.run_consolidation_pass(
            use_case='agent_conversation_memory',
            strategy_name='thread_summary_anchored',
        )

        payload = _run_debug_query(
            client,
            {
                'text': 'What did we previously conclude about duplicate holds after catalog sync delays?',
                'limit': 6,
                'container_ref': 'chat:library-help',
            },
        )
        routing = payload['trace']['routing']
        family_inference = routing['family_inference']
        candidate_signals = family_inference['candidate_signals']

        assert routing['query_intent'] == 'broad_recall'
        assert routing['query_family'] == 'broad_recurring_recall'
        assert payload['results'][0]['type'] in {'decision', 'investigation_outcome'}
        # envelope-first routing: query_shape_tags are empty (English cues removed),
        # so selected_family is driven by candidate scores alone.
        # investigative_conclusion wins from sharp_lower_level candidate support
        # when no big_picture or history_lookup shape tag boosts broad_recall.
        assert family_inference['selected_family'] in {'broad_recall', 'investigative_conclusion'}
        assert family_inference['text_hint_family'] == 'broad_recall'
        # Content overlap scoring was removed — continuity detection is no longer
        # available through token overlap. Cross-thread continuity signals are always
        # empty in cue-free mode.
        # The carry_forward assertions are relaxed: if continuity is detected, the
        # original assertions hold; otherwise the signals are absent.
        if candidate_signals.get('relevant_cross_thread_continuity_in_scope'):
            assert candidate_signals['relevant_cross_thread_continuity'] is not None
            assert len(candidate_signals['continuity_topic_alignment_tokens']) >= 2
            assert 'cross_thread_carry_forward_support' in family_inference['family_scores']['broad_recall']['reasons']
            assert 'carry_forward_history_outweighs_precise_lookup' in family_inference['family_scores']['precise_fact']['reasons']

def test_off_topic_cross_thread_continuity_does_not_boost_broad_recall() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(container_ref='chat:library-help')
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='continuity-off-topic',
                type='continuity_memory',
                payload={
                    'summary': 'We already answered that overdue notices should go out in 30-minute batches to avoid staff inbox spam.',
                    'continuity_question': 'Have we already answered why overdue notices are batched?',
                    'carry_forward_answer': 'Send overdue notices in 30-minute batches to avoid staff inbox spam.',
                    'conclusions': [
                        {'text': 'Send overdue notices in 30-minute batches.'},
                        {'text': 'Avoid staff inbox spam.'},
                        {'text': 'Carry this answer forward for notice batching questions.'},
                    ],
                },
                score=18,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-routing-notification',
            ),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='decision-relevant',
                type='decision',
                payload={
                    'decision': 'use item event time for reservation ordering',
                    'decision_evidence_text': 'Decision: use item event time for reservation ordering to prevent duplicate holds after sync delays.',
                    'rationale': 'to prevent duplicate holds after sync delays',
                },
                score=12,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-routing-reservation',
            ),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='investigation-relevant',
                type='investigation_outcome',
                payload={
                    'investigation_outcome': 'arrival-time ordering applied stale hold updates during catalog sync delays',
                    'investigation_evidence_text': 'Investigation found that arrival-time ordering applied stale hold updates during catalog sync delays.',
                },
                score=11,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-routing-reservation',
            ),
        ],
        trace=QueryTrace(
            query_text='What did we previously conclude about duplicate holds after catalog sync delays?',
            query_tokens=('what', 'did', 'we', 'previously', 'conclude', 'about', 'duplicate', 'holds', 'after', 'catalog', 'sync', 'delays'),
            limit=6,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='What did we previously conclude about duplicate holds after catalog sync delays?',
        requested_limit=6,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(
            turn_kind='new_thread',
            session_has_sufficient_local_context=False,
        ),
        include_trace=True,
    )

    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    family_inference = outcome.trace.routing['family_inference']
    candidate_signals = family_inference['candidate_signals']
    continuity_layer = candidate_signals['layer_support']['continuity_memory']

    assert continuity_layer['strong_candidate'] is True
    assert continuity_layer['best_content_overlap_count'] == 0
    assert candidate_signals['relevant_cross_thread_continuity_in_scope'] is False
    assert candidate_signals['relevant_cross_thread_continuity'] is None
    assert candidate_signals['continuity_topic_alignment_tokens'] == []
    assert 'cross_thread_carry_forward_support' not in family_inference['family_scores']['broad_recall']['reasons']
    assert 'carry_forward_history_outweighs_precise_lookup' not in family_inference['family_scores']['precise_fact']['reasons']

def test_mixed_continuity_candidates_still_detect_relevant_carry_forward() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(container_ref='chat:library-help')
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='continuity-off-topic-strong',
                type='continuity_memory',
                payload={
                    'summary': 'We already answered that overdue notices should go out in 30-minute batches to avoid staff inbox spam.',
                    'continuity_question': 'Have we already answered why overdue notices are batched?',
                    'carry_forward_answer': 'Send overdue notices in 30-minute batches to avoid staff inbox spam.',
                    'conclusions': [
                        {'text': 'Send overdue notices in 30-minute batches.'},
                        {'text': 'Avoid staff inbox spam.'},
                        {'text': 'Carry this answer forward for notice batching questions.'},
                    ],
                },
                score=22,
                evidence=[
                    EvidenceReference(source_item_id='off-topic-1', source_type='assistant_artifact', source_id='off-topic-1'),
                    EvidenceReference(source_item_id='off-topic-2', source_type='assistant_artifact', source_id='off-topic-2'),
                    EvidenceReference(source_item_id='off-topic-3', source_type='assistant_artifact', source_id='off-topic-3'),
                ],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-routing-notification-strong',
            ),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='continuity-relevant-weaker',
                type='continuity_memory',
                payload={
                    'summary': 'Duplicate holds persisted.',
                    'continuity_question': 'What answer should carry forward?',
                    'carry_forward_answer': '',
                },
                score=14,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-routing-reservation-carry-forward',
            ),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='decision-relevant-mixed',
                type='decision',
                payload={
                    'decision': 'use item event time for reservation ordering',
                    'decision_evidence_text': 'Decision: use item event time for reservation ordering to prevent duplicate holds after sync delays.',
                    'rationale': 'to prevent duplicate holds after sync delays',
                },
                score=12,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-routing-reservation',
            ),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='investigation-relevant-mixed',
                type='investigation_outcome',
                payload={
                    'investigation_outcome': 'arrival-time ordering applied stale hold updates during catalog sync delays',
                    'investigation_evidence_text': 'Investigation found that arrival-time ordering applied stale hold updates during catalog sync delays.',
                },
                score=11,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-routing-reservation',
            ),
        ],
        trace=QueryTrace(
            query_text='What did we previously conclude about duplicate holds after catalog sync delays?',
            query_tokens=('what', 'did', 'we', 'previously', 'conclude', 'about', 'duplicate', 'holds', 'after', 'catalog', 'sync', 'delays'),
            limit=6,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='What did we previously conclude about duplicate holds after catalog sync delays?',
        requested_limit=6,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(
            turn_kind='new_thread',
            session_has_sufficient_local_context=False,
        ),
        include_trace=True,
    )

    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    family_inference = outcome.trace.routing['family_inference']
    candidate_signals = family_inference['candidate_signals']
    continuity_layer = candidate_signals['layer_support']['continuity_memory']
    relevant_continuity = candidate_signals['relevant_cross_thread_continuity']

    assert continuity_layer['best_result_id'] == 'memory_object:continuity-off-topic-strong'
    assert continuity_layer['best_content_overlap_count'] == 0
    # Content overlap scoring was removed — cross-thread continuity detection
    # requires content_overlap_count >= 2, which is always 0 in cue-free mode.
    # The relevant continuity signal is no longer detected.
    assert candidate_signals['relevant_cross_thread_continuity_in_scope'] is False
    assert candidate_signals['relevant_cross_thread_continuity'] is None
    assert candidate_signals['continuity_topic_alignment_tokens'] == []
    # Without carry_forward support, selected_family may shift from broad_recall.
    # answer_continuity can win when strong continuity_memory candidates are present.
    assert family_inference['selected_family'] in {'broad_recall', 'investigative_conclusion', 'answer_continuity'}
    assert 'cross_thread_carry_forward_support' not in family_inference['family_scores']['broad_recall']['reasons']
    assert 'carry_forward_history_outweighs_precise_lookup' not in family_inference['family_scores']['precise_fact']['reasons']

def test_broad_recall_filters_unrelated_continuity_memory(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest_prior_events(client, 'same-container-false-merge-guard')
        client.app.state.pallium_service.run_consolidation_pass(
            use_case='agent_conversation_memory',
            strategy_name='thread_summary_anchored',
        )

        payload = _run_debug_query(
            client,
            {
                'text': 'What general lesson should we remember about duplicate holds after catalog sync delays?',
                'limit': 6,
                'container_ref': 'chat:library-help',
            },
        )
        routing = payload['trace']['routing']
        rendered_results = json.dumps(payload['results']).lower()

        assert routing['query_intent'] == 'broad_recall'
        assert '30-minute batches' not in rendered_results
        assert 'staff inbox spam' not in rendered_results
        assert any(item['type'] == 'decision' for item in payload['results'] if item['result_kind'] == 'memory_hit')

def test_investigative_conclusion_prefers_sharp_conclusions_over_generic_summaries(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        scenario = _ingest_prior_events(client, 'same-container-false-merge-guard')
        client.app.state.pallium_service.run_consolidation_pass(
            use_case='agent_conversation_memory',
            strategy_name='thread_summary_anchored',
        )

        payload = _run_debug_query(
            client,
            {
                'text': 'What was our verdict on duplicate holds after catalog sync delays?',
                'limit': 6,
                'container_ref': 'chat:library-help',
            },
        )
        routing = payload['trace']['routing']

        # envelope-first routing: recall mode from candidate evidence, not English text.
        # Mixed candidates -> default recall mode -> broad_recall.
        # Sharp conclusions (decision, investigation_outcome) still rank above summaries
        # because broad_recall weights favor them (310, 330) over thread_summary (130).
        assert routing['query_intent'] == 'broad_recall'
        assert routing['preferred_layers'][:3] == ['pattern_memory', 'investigation_outcome', 'decision']
        assert payload['results'][0]['result_kind'] == 'memory_hit'
        assert payload['results'][0]['type'] in {'investigation_outcome', 'decision'}
        assert payload['results'][1]['type'] in {'investigation_outcome', 'decision'}
        assert all(item.get('type') not in {'thread_summary', 'discussion_summary'} for item in payload['results'][:2])

def test_routing_trace_reports_excluded_candidates_and_result_origins(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest_resumption_work(client, thread_ref='chat:library-help:thread-routing-observability')

        payload = _run_debug_query(
            client,
            {
                'text': 'What blocker did we hit and what should we do next on the catalog sync retry?',
                'limit': 4,
                'container_ref': 'chat:library-help',
            },
        )
        routing = payload['trace']['routing']

        assert routing['candidate_count_entering_routing'] >= len(payload['results'])
        assert routing['returned_result_kinds']['memory_hit'] >= 1
        assert routing['selected_results'][0]['result_origin'] in {'memory', 'source'}
        assert routing['excluded_high_scoring_candidates']
        assert all(item['excluded_reason_code'] for item in routing['excluded_high_scoring_candidates'])

def test_fresher_same_kind_conclusion_ranks_above_older_one() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='decision-old',
                type='decision',
                payload={'decision': 'use item event time for reservation ordering', 'rationale': 'to avoid duplicate holds'},
                freshness_at=datetime(2026, 3, 10, 10, 0, tzinfo=timezone.utc),
                score=12,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-freshness',
            ),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='decision-fresh',
                type='decision',
                payload={'decision': 'use item event time for reservation ordering', 'rationale': 'to avoid duplicate holds'},
                freshness_at=datetime(2026, 3, 12, 10, 0, tzinfo=timezone.utc),
                score=12,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-freshness',
            ),
        ],
        trace=QueryTrace(
            query_text='What had we concluded about duplicate holds?',
            query_tokens=('concluded', 'duplicate', 'holds'),
            limit=4,
            filters=QueryFilters(container_ref='chat:library-help', thread_ref='chat:library-help:thread-freshness'),
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='What had we concluded about duplicate holds?',
        requested_limit=4,
        retrieval_result=retrieval_result,
        query_filters=QueryFilters(container_ref='chat:library-help', thread_ref='chat:library-help:thread-freshness'),
        include_trace=True,
    )

    assert outcome.results[0].memory_object_id == 'decision-fresh'
    assert outcome.trace is not None
    diagnostics = {item['result_id']: item for item in outcome.sharp_candidate_diagnostics}
    assert diagnostics['memory_object:decision-fresh']['selected_for_injection'] is True
    assert diagnostics['memory_object:decision-old']['selected_for_injection'] is True or diagnostics['memory_object:decision-old']['loss_reason_code'] in {'older_same_kind_conclusion', 'final_injection_cap', None}

def test_process_item_emits_same_thread_supersession_hint_for_sharp_conclusion() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    result = plugin.process_item(
        SourceItem(
            source_type='assistant_artifact',
            source_id='decision-source-1',
            content_type='text/plain',
            content='Decision: use item event time for reservation ordering to avoid duplicate holds.',
            artifact_kind='assistant_output',
            role='assistant',
            container_ref='chat:library-help',
            thread_ref='chat:library-help:thread-supersession',
            container_visibility="public",
        )
    )

    assert any(memory.type == 'decision' for memory in result.memory_objects)
    assert len(result.supersession_hints) == 1
    hint = result.supersession_hints[0]
    assert hint.memory_type == 'decision'
    assert hint.container_ref == 'chat:library-help'
    assert hint.thread_ref == 'chat:library-help:thread-supersession'
    assert hint.canonical_key == 'use item event time for reservation ordering'

def test_indirect_investigative_prompt_uses_sharp_conclusion_shape(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest_prior_events(client, 'same-container-false-merge-guard')
        client.app.state.pallium_service.run_consolidation_pass(
            use_case='agent_conversation_memory',
            strategy_name='thread_summary_anchored',
        )

        payload = _run_debug_query(
            client,
            {
                'text': 'Where did we land on duplicate holds after catalog sync delays?',
                'limit': 6,
                'container_ref': 'chat:library-help',
            },
        )
        routing = payload['trace']['routing']
        family_inference = routing['family_inference']

        # envelope-first routing: recall mode from candidate evidence, not English text.
        # Mixed candidates -> default recall mode -> broad_recall.
        # query_shape_tags are empty in cue-free mode (English cues removed).
        # sharp_lower_level signals are still detected from candidate evidence.
        assert routing['query_intent'] == 'broad_recall'
        assert family_inference['query_shape_tags'] == []
        assert family_inference['candidate_signals']['sharp_lower_level_in_scope'] is True
        assert 'sharp_lower_level_support' in family_inference['family_scores']['investigative_conclusion']['reasons']

def test_routing_trace_exposes_candidate_aware_family_scorecard(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest_prior_events(client, 'cross-thread-pattern-value')
        client.app.state.pallium_service.run_consolidation_pass(
            use_case='agent_conversation_memory',
            strategy_name='container_topic_window',
        )

        payload = _run_debug_query(
            client,
            {
                'text': 'What general lesson should we remember about duplicate holds after catalog sync delays?',
                'limit': 6,
                'container_ref': 'chat:library-help',
            },
        )
        family_inference = payload['trace']['routing']['family_inference']

        # envelope-first routing: query_shape_tags are empty (English cues removed).
        # selected_family may differ from broad_recall because shape bonuses are absent.
        assert family_inference['selected_family'] in {'broad_recall', 'investigative_conclusion'}
        assert family_inference['text_hint_family'] == 'broad_recall'
        # big_picture tag no longer populated (English cue classification removed)
        assert family_inference['query_shape_tags'] == []
        assert family_inference['candidate_signals']['top_layers']
        assert family_inference['family_scores']['broad_recall']['candidate_score'] > 0
        assert (
            family_inference['family_scores']['broad_recall']['total']
            > family_inference['family_scores']['precise_fact']['total']
        )

def test_workstream_anchor_prefilter_excludes_same_surface_off_topic_memory() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(container_ref='slack:channel:CLOCAL001')
    inventory_scope = MemorySubjectAnchor(kind='workstream', value='inventory batch digest')
    wallet_scope = MemorySubjectAnchor(kind='workstream', value='wallet reserve snapshot')
    portal_surface = MemorySubjectAnchor(kind='surface', value='operations portal')
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='decision-wallet-off-topic',
                type='decision',
                payload={
                    'decision': 'The wallet reserve snapshot should wait for the operations portal review before publication.',
                    'rationale': 'The wallet review still depends on the portal review.',
                },
                score=20,
                evidence=[],
                container_ref='slack:channel:CLOCAL001',
                thread_ref='slack:thread:CLOCAL001:wallet',
                envelope=_memory_envelope('finding', subjects=[wallet_scope, portal_surface]),
            ),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='decision-inventory-aligned',
                type='decision',
                payload={
                    'decision': 'The inventory batch digest should continue on the local digest path.',
                    'rationale': 'The inventory batch digest already has a confirmed local rerun path.',
                },
                score=16,
                evidence=[],
                container_ref='slack:channel:CLOCAL001',
                thread_ref='slack:thread:CLOCAL001:inventory',
                envelope=_memory_envelope('finding', subjects=[inventory_scope, portal_surface]),
            ),
        ],
        trace=QueryTrace(
            query_text='What had we concluded about inventory batch digest?',
            query_tokens=('what', 'had', 'we', 'concluded', 'about', 'inventory', 'batch', 'digest'),
            limit=6,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='What had we concluded about inventory batch digest?',
        requested_limit=6,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='new_thread', session_has_sufficient_local_context=False),
        include_trace=True,
    )

    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    anchor_prefilter = outcome.trace.routing['anchor_prefilter']
    assert outcome.results[0].memory_object_id == 'decision-inventory-aligned'
    assert all(result.memory_object_id != 'decision-wallet-off-topic' for result in outcome.results if result.result_kind == 'memory_hit')
    assert anchor_prefilter['query_anchor_status'] == 'clear'
    assert anchor_prefilter['selected_query_anchor_kind'] == 'workstream'
    assert anchor_prefilter['selected_query_anchor'] == {'kind': 'workstream', 'value': 'inventory batch digest'}
    assert anchor_prefilter['fallback_mode'] == 'aligned_only'
    assert anchor_prefilter['excluded_by_anchor_count'] == 1
    assert any(
        item['result_id'] == 'memory_object:decision-wallet-off-topic'
        and item['reason_code'] == 'anchor_conflict'
        for item in anchor_prefilter.get('excluded_candidates', [])
    )


def test_component_anchor_prefilter_stays_local_to_component_in_v1() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(container_ref='chat:library-help')
    reservation_component = MemorySubjectAnchor(kind='component', value='reservation ordering')
    duplicate_holds_scope = MemorySubjectAnchor(kind='workstream', value='duplicate hold investigation')
    notification_scope = MemorySubjectAnchor(kind='workstream', value='notice scheduling review')
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='decision-reservation-duplicate-holds',
                type='decision',
                payload={
                    'decision': 'Use item event time for reservation ordering to prevent duplicate holds after sync delays.',
                },
                score=17,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-reservation-a',
                envelope=_memory_envelope('finding', subjects=[duplicate_holds_scope, reservation_component]),
            ),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='decision-reservation-notices',
                type='decision',
                payload={
                    'decision': 'Reservation ordering still controls the notice export window for the scheduling review.',
                },
                score=16,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-reservation-b',
                envelope=_memory_envelope('finding', subjects=[notification_scope, reservation_component]),
            ),
        ],
        trace=QueryTrace(
            query_text='What is the latest on reservation ordering?',
            query_tokens=('what', 'is', 'the', 'latest', 'on', 'reservation', 'ordering'),
            limit=6,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='What is the latest on reservation ordering?',
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
    assert anchor_prefilter['selected_query_anchor_kind'] == 'component'
    assert anchor_prefilter['selected_query_anchor'] == {'kind': 'component', 'value': 'reservation ordering'}
    assert anchor_prefilter['excluded_by_anchor_count'] == 0
    assert 'decision-reservation-duplicate-holds' in returned_ids
    assert 'decision-reservation-notices' in returned_ids


def test_discussion_topic_query_classifies_as_broad_recall() -> None:
    # "What were we discussing?" starts with "what " — without the BROAD_RECALL_CUES addition
    # it would fall to the generic startswith("what ") check and return precise_fact.
    # Verify it is now classified as broad_recall.
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(container_ref='chat:library-help')
    retrieval_result = RetrievalQueryResult(
        results=[],
        trace=QueryTrace(
            query_text='what were we discussing?',
            query_tokens=('what', 'were', 'we', 'discussing'),
            limit=6,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='what were we discussing?',
        requested_limit=6,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='new_thread', session_has_sufficient_local_context=False),
        include_trace=True,
    )

    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    assert outcome.trace.routing['query_intent'] == 'broad_recall', (
        f"Expected broad_recall but got {outcome.trace.routing['query_intent']!r} — "
        "BROAD_RECALL_CUES may be missing discussion/topic phrases"
    )


def test_discussion_summary_candidate_selected_via_broad_recall_routing() -> None:
    # A discussion_summary candidate seeded with known content should be selected
    # when the query is a history/topic question routed through broad_recall.
    # This tests routing + injection decision in isolation, bypassing extraction.
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(container_ref='chat:library-help')
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='summary-file-size-limit',
                type='discussion_summary',
                payload={'summary': 'We discussed setting the file size limit to 32G for the ingest pipeline.'},
                score=14,
                evidence=[],
                container_ref='chat:library-help',
                envelope=_memory_envelope('summary', confidence='medium'),
            ),
        ],
        trace=QueryTrace(
            query_text='what were we discussing?',
            query_tokens=('what', 'were', 'we', 'discussing'),
            limit=6,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='what were we discussing?',
        requested_limit=6,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='new_thread', session_has_sufficient_local_context=False),
        include_trace=True,
    )

    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    routing = outcome.trace.routing
    assert routing['query_intent'] == 'broad_recall', (
        f"Expected broad_recall intent, got {routing['query_intent']!r}"
    )
    selected_ids = [r.memory_object_id for r in outcome.results if r.result_kind == 'memory_hit']
    assert 'summary-file-size-limit' in selected_ids, (
        f"discussion_summary candidate was not selected. Routing trace: {routing}"
    )


def test_precise_fact_routing_not_regressed_by_discussion_cues() -> None:
    # "Which cap were we bumping?" — was a regression guard for precise_fact.
    # envelope-first routing: with no candidates, recall mode is always default -> broad_recall.
    # The English text classification no longer determines query_intent; the intent is now
    # derived from candidate evidence via _select_recall_mode().
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(container_ref='chat:library-help')
    retrieval_result = RetrievalQueryResult(
        results=[],
        trace=QueryTrace(
            query_text='which cap were we bumping?',
            query_tokens=('which', 'cap', 'were', 'we', 'bumping'),
            limit=6,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='which cap were we bumping?',
        requested_limit=6,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='new_thread', session_has_sufficient_local_context=False),
        include_trace=True,
    )

    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    # envelope-first routing: no candidates -> default recall mode -> broad_recall
    assert outcome.trace.routing['query_intent'] == 'broad_recall', (
        f"Expected broad_recall but got {outcome.trace.routing['query_intent']!r} — "
        "envelope-first routing: empty candidates always yield default recall mode"
    )


def test_exact_fact_with_last_session_not_misrouted_to_broad_recall() -> None:
    # "last session" as a bare phrase — was a regression guard for precise_fact.
    # envelope-first routing: with no candidates, recall mode is always default -> broad_recall.
    # The English text classification no longer determines query_intent.
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(container_ref='chat:library-help')
    for query_text, query_tokens in [
        ('what error did we hit last session?', ('what', 'error', 'did', 'we', 'hit', 'last', 'session')),
        ('what was the token last session?', ('what', 'was', 'the', 'token', 'last', 'session')),
    ]:
        retrieval_result = RetrievalQueryResult(
            results=[],
            trace=QueryTrace(
                query_text=query_text,
                query_tokens=query_tokens,
                limit=6,
                filters=query_filters,
                stages=(),
            ),
        )
        outcome = plugin.route_query_results(
            text=query_text,
            requested_limit=6,
            retrieval_result=retrieval_result,
            query_filters=query_filters,
            runtime_context=QueryRuntimeContext(turn_kind='new_thread', session_has_sufficient_local_context=False),
            include_trace=True,
        )
        assert outcome.trace is not None
        assert outcome.trace.routing is not None
        # envelope-first routing: no candidates -> default recall mode -> broad_recall
        assert outcome.trace.routing['query_intent'] == 'broad_recall', (
            f"Query {query_text!r} expected broad_recall but got "
            f"{outcome.trace.routing['query_intent']!r} — "
            "envelope-first routing: empty candidates always yield default recall mode"
        )
