from __future__ import annotations

from copy import deepcopy

from evals.continuity_common import compare_query_contract_payloads, evaluate_query_contract, query_contract_payloads_consistent


def _evidence(*, source_item_id: str = 'source-1', source_id: str = 'artifact-1') -> dict[str, object]:
    return {
        'source_item_id': source_item_id,
        'source_type': 'assistant_artifact',
        'source_id': source_id,
        'occurred_at': '2026-03-12T10:00:00Z',
        'actor_ref': None,
        'role': 'assistant',
        'container_ref': 'chat:library-help',
        'thread_ref': 'chat:library-help:thread-1',
        'source_ref': None,
        'artifact_kind': 'assistant_output',
        "visibility": "public",
    }


def _block(
    *,
    result_id: str = 'memory_object:decision-1',
    block_type: str = 'memory',
    memory_type: str | None = 'decision',
    title: str = 'Decision',
    text: str = 'Use item event time for reservation ordering.',
    evidence: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        'result_id': result_id,
        'block_type': block_type,
        'memory_type': memory_type,
        'title': title,
        'text': text,
        'evidence': list(evidence or [_evidence()]),
    }


def _payload(*, blocks: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        'should_inject': True,
        'decision_reason': 'carry_forward_available',
        'injectable_blocks': list(blocks or [_block()]),
    }


def test_query_contract_consistency_accepts_identical_public_payload() -> None:
    query_payload = _payload(blocks=[_block(), _block(result_id='source_item:source-2', block_type='source_evidence', memory_type=None, title='Evidence', text='The retry failed with a 401.', evidence=[_evidence(source_item_id='source-2', source_id='artifact-2')])])
    debug_payload = deepcopy(query_payload)

    comparison = compare_query_contract_payloads(query_payload, debug_payload)

    assert comparison['consistent'] is True
    assert comparison['mismatch_fields'] == []
    assert query_contract_payloads_consistent(query_payload, debug_payload) is True


def test_query_contract_consistency_rejects_block_type_drift_with_same_count() -> None:
    query_payload = _payload()
    debug_payload = _payload(blocks=[_block(block_type='source_evidence', memory_type=None)])

    comparison = compare_query_contract_payloads(query_payload, debug_payload)

    assert comparison['consistent'] is False
    assert 'injectable_blocks[0].block_type' in comparison['mismatch_fields']
    assert 'injectable_blocks[0].memory_type' in comparison['mismatch_fields']
    assert query_contract_payloads_consistent(query_payload, debug_payload) is False



def test_query_contract_consistency_rejects_text_drift_with_same_count() -> None:
    query_payload = _payload()
    debug_payload = _payload(blocks=[_block(text='Use arrival time for reservation ordering.')])

    comparison = compare_query_contract_payloads(query_payload, debug_payload)

    assert comparison['consistent'] is False
    assert comparison['mismatch_fields'] == ['injectable_blocks[0].text']
    assert query_contract_payloads_consistent(query_payload, debug_payload) is False



def test_query_contract_consistency_rejects_result_linkage_and_evidence_drift_with_same_count() -> None:
    query_payload = _payload()
    debug_payload = _payload(
        blocks=[
            _block(
                result_id='memory_object:decision-2',
                evidence=[_evidence(source_item_id='source-9', source_id='artifact-9')],
            )
        ]
    )

    comparison = compare_query_contract_payloads(query_payload, debug_payload)

    assert comparison['consistent'] is False
    assert 'injectable_blocks[0].result_id' in comparison['mismatch_fields']
    assert 'injectable_blocks[0].evidence' in comparison['mismatch_fields']
    assert query_contract_payloads_consistent(query_payload, debug_payload) is False



def test_query_contract_consistency_rejects_block_order_drift() -> None:
    first = _block(result_id='memory_object:decision-1', title='Decision', text='Keep the rollout paused.')
    second = _block(result_id='source_item:source-2', block_type='source_evidence', memory_type=None, title='Evidence', text='Review blocker said branch kiosk fallback was missing.', evidence=[_evidence(source_item_id='source-2', source_id='artifact-2')])
    query_payload = _payload(blocks=[first, second])
    debug_payload = _payload(blocks=[second, first])

    comparison = compare_query_contract_payloads(query_payload, debug_payload)

    assert comparison['consistent'] is False
    assert 'injectable_blocks[0].result_id' in comparison['mismatch_fields']
    assert 'injectable_blocks[1].result_id' in comparison['mismatch_fields']
    assert query_contract_payloads_consistent(query_payload, debug_payload) is False


def test_evaluate_query_contract_scores_public_query_payload_instead_of_debug_payload() -> None:
    query_payload = {
        'should_inject': False,
        'decision_reason': 'same_thread_context_sufficient',
        'injectable_blocks': [],
    }
    debug_payload = _payload()

    evaluation = evaluate_query_contract(
        query_payload=query_payload,
        debug_payload=debug_payload,
        expected_should_inject=False,
        expected_decision_reason='same_thread_context_sufficient',
        acceptable_decision_reasons=[],
        expected_primary_block_types=[],
        acceptable_fallback_block_types=[],
        forbidden_block_types=[],
        acceptable_injected_block_count=0,
        expected_cap_behavior=None,
    )

    assert evaluation['query_contract_consistent'] is False
    assert 'should_inject' in evaluation['query_contract_mismatch_fields']
    assert evaluation['should_inject'] is False
    assert evaluation['decision_reason'] == 'same_thread_context_sufficient'
    assert evaluation['injectable_blocks'] == []
    assert evaluation['injection_contract']['should_inject_actual'] is False
    assert evaluation['injection_contract']['contract_success'] is True
