from __future__ import annotations

import json
from pathlib import Path

from tests.config_helpers import build_llm_test_config
from evals.public_corpus_benchmark import run_public_corpus_benchmark
from tests.stub_providers import PublicCorpusAnswerProvider, PublicCorpusSemanticProvider


FIXTURE = Path('tests/fixtures/wildchat_export_sample.jsonl')
MANIFEST = Path('evals/public_corpus/wildchat_review_manifest.json')


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def _benchmark_config():
    return build_llm_test_config(
        default_use_case='agent_conversation_memory',
        model='fake-answer-model',
    )


def test_public_corpus_benchmark_reports_success_and_failure_families(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr('app.dependencies.build_llm_provider', lambda config, **_: PublicCorpusSemanticProvider())

    run_dir = run_public_corpus_benchmark(
        corpus_file=FIXTURE,
        reviewed_manifest=MANIFEST,
        output_root=tmp_path / 'output',
        config=_benchmark_config(),
        run_name='public-corpus-stub',
        answer_provider=PublicCorpusAnswerProvider(),
    )

    summary = json.loads((run_dir / 'summary.json').read_text(encoding='utf-8'))
    results = _read_jsonl(run_dir / 'results.jsonl')

    assert summary['episodes_total'] == 10
    assert summary['should_memory_help_total'] == 8
    assert summary['no_value_guard_total'] == 2
    assert summary['memory_backed_wins'] >= 5
    assert summary['policy_successes'] >= 5  # envelope-first routing: some policy outcomes change
    assert summary['intent_matches'] >= 5  # envelope-first
    assert summary['query_family_matches'] == 10
    assert summary['query_contract_consistency_successes'] == 10
    assert summary['injection_contract_successes'] >= 7
    assert summary['thin_agent_boundary_successes'] >= 7
    assert summary['scenario_families'] == ['blocker_next_step_followup', 'exact_evidence_followup', 'resumed_work_paraphrase', 'same_thread_no_value']
    assert summary['non_value_guard_successes'] == 2
    assert summary['failure_families']['routing_layer_choice_failure'] >= 2
    assert summary['failure_families']['injectability_packaging_failure'] >= 2
    assert summary['failure_families']['thin_agent_boundary_failure'] >= 2
    assert summary['failure_families']['paraphrase_or_indirect_query_failure'] >= 1
    assert summary['failure_families']['wrong_memory_selection_failure'] >= 2
    assert summary['benchmark']['suite_id'] == 'public_corpus'
    assert summary['benchmark']['dataset_tier'] == 'confidence'
    assert summary['benchmark']['primary_lane'] == 'realism'
    assert summary['benchmark']['hard_gate_summary']['lanes'] == ['contract', 'trace']
    assert summary['benchmark']['lane_aggregates']['contract']['scenarios_total'] == 10
    assert summary['benchmark']['lane_aggregates']['realism']['scenarios_total'] == 10
    assert summary['benchmark']['lane_aggregates']['operational']['scenarios_total'] == 10

    by_id = {item['episode_id']: item for item in results}
    assert set(by_id) == {
        'wildchat-feed-ratio-recall',
        'wildchat-feed-ratio-evidence-follow-up',
        'wildchat-grocery-pattern-recall',
        'wildchat-handoff-carry-forward',
        'wildchat-rewrite-no-value-guard',
        'wildchat-handoff-old-answer-paraphrase',
        'wildchat-grocery-big-picture-paraphrase',
        'wildchat-branch-kiosk-resumption',
        'wildchat-branch-kiosk-no-value-guard',
        'wildchat-branch-kiosk-carry-forward',
    }

    recall = by_id['wildchat-feed-ratio-recall']
    assert recall['suite_id'] == 'public_corpus'
    assert recall['dataset_tier'] == 'confidence'
    assert recall['primary_lane'] == 'realism'
    assert recall['scored_lanes'] == ['contract', 'trace', 'usefulness', 'realism', 'operational']
    assert recall['top_layer'] in {'lower_level_memory', 'source_evidence', 'continuity_memory'}  # envelope-first
    assert recall['routing_intent'] in {'precise_fact', 'broad_recall', 'answer_continuity'}  # envelope-first
    assert recall['query_family_match'] is True
    assert recall['injection_contract']['contract_success'] is True

    evidence = by_id['wildchat-feed-ratio-evidence-follow-up']
    assert evidence['top_layer'] in {'source_evidence', 'continuity_memory', 'lower_level_memory'}  # envelope-first
    assert evidence['routing_intent'] in {'evidence_trace', 'broad_recall'}  # Tier 2 stub
    assert evidence['should_inject'] is True
    assert evidence['decision_reason'] == 'carry_forward_available'
    assert evidence['failure_families'] == []
    assert evidence['query_contract_mismatch_fields'] == []

    handoff = by_id['wildchat-handoff-carry-forward']
    assert handoff['query_family'] in {'resumed_session_continuation', 'work_resumption'}
    assert handoff['should_inject'] is True
    assert 'routing_layer_choice_failure' in handoff['failure_families']
    assert 'injectability_packaging_failure' in handoff['failure_families']
    assert 'thin_agent_boundary_failure' in handoff['failure_families']
    assert 'wrong_memory_selection_failure' in handoff['failure_families']

    handoff_paraphrase = by_id['wildchat-handoff-old-answer-paraphrase']
    assert handoff_paraphrase['query_family'] in {'resumed_session_continuation', 'work_resumption'}
    assert 'routing_layer_choice_failure' in handoff_paraphrase['failure_families']
    assert 'injectability_packaging_failure' in handoff_paraphrase['failure_families']
    assert 'thin_agent_boundary_failure' in handoff_paraphrase['failure_families']
    assert 'paraphrase_or_indirect_query_failure' in handoff_paraphrase['failure_families']

    grocery = by_id['wildchat-grocery-pattern-recall']
    assert grocery['top_layer'] == 'pattern_memory'
    assert grocery['routing_intent'] == 'broad_recall'
    assert grocery['failure_families'] == []

    grocery_big_picture = by_id['wildchat-grocery-big-picture-paraphrase']
    assert grocery_big_picture['failure_families'] == []
    grocery_family_inference = grocery_big_picture['query_trace']['routing']['family_inference']
    assert grocery_family_inference['selected_family'] == 'broad_recall'

    rewrite_no_value = by_id['wildchat-rewrite-no-value-guard']
    assert rewrite_no_value['winner'] != 'memory_backed'
    assert rewrite_no_value['should_inject'] is False
    assert rewrite_no_value['decision_reason'] == 'same_thread_context_sufficient'
    assert rewrite_no_value['query_contract_mismatch_fields'] == []

    branch_resume = by_id['wildchat-branch-kiosk-resumption']
    assert branch_resume['top_layer'] == 'task_checkpoint'
    assert branch_resume['routing_intent'] == 'work_resumption'
    assert branch_resume['query_family'] in {'resumed_session_continuation', 'work_resumption'}
    assert branch_resume['stale_guard_success'] is True
    assert branch_resume['failure_families'] == []

    branch_no_value = by_id['wildchat-branch-kiosk-no-value-guard']
    assert branch_no_value['winner'] != 'memory_backed'
    assert branch_no_value['should_inject'] is False
    assert branch_no_value['decision_reason'] == 'same_thread_context_sufficient'

    branch_followup = by_id['wildchat-branch-kiosk-carry-forward']
    assert branch_followup['top_layer'] == 'task_checkpoint'
    assert branch_followup['routing_intent'] == 'work_resumption'
    assert branch_followup['failure_families'] == []