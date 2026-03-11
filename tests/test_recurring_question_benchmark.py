from __future__ import annotations

import json
from pathlib import Path

from app.config import AppConfig
from evals.recurring_question_benchmark import run_recurring_question_benchmark
from tests.stub_providers import TieredMemoryAnswerProvider, TieredMemorySemanticProvider


SCENARIOS = Path('evals/recurring_question/scenarios.json')


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def _benchmark_config() -> AppConfig:
    return AppConfig(
        default_use_case='agent_conversation_memory',
        llm_provider='openai_compatible',
        llm_model='fake-answer-model',
        llm_base_url='http://fake-provider.local',
        llm_prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )


def test_recurring_question_benchmark_outputs_expected_shape(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr('app.dependencies.build_llm_provider', lambda config, **_: TieredMemorySemanticProvider())

    run_dir = run_recurring_question_benchmark(
        scenario_file=SCENARIOS,
        output_root=tmp_path / 'output',
        config=_benchmark_config(),
        run_name='recurring-question-smoke',
        answer_provider=TieredMemoryAnswerProvider(),
    )

    summary = json.loads((run_dir / 'summary.json').read_text(encoding='utf-8'))
    results = _read_jsonl(run_dir / 'results.jsonl')

    assert summary['scenarios_total'] == 3
    assert summary['value_scenarios'] == 2
    assert summary['non_value_scenarios'] == 1
    assert len(results) == 3
    assert 'baseline_answer' in results[0]
    assert 'memory_backed_answer' in results[0]
    assert 'higher_level_memory_types' in results[0]
    assert results[0]['rubric']['comparison']['winner']


def test_cross_thread_scenario_marks_memory_backed_as_winner(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr('app.dependencies.build_llm_provider', lambda config, **_: TieredMemorySemanticProvider())

    run_dir = run_recurring_question_benchmark(
        scenario_file=SCENARIOS,
        output_root=tmp_path / 'output',
        config=_benchmark_config(),
        run_name='recurring-question-cross-thread',
        answer_provider=TieredMemoryAnswerProvider(),
    )
    results = _read_jsonl(run_dir / 'results.jsonl')
    cross_thread = next(item for item in results if item['scenario_id'] == 'cross-thread-prior-conclusion')

    assert cross_thread['winner'] == 'memory_backed'
    assert cross_thread['rubric']['memory_backed']['memory_carry_forward'] == 2
    assert cross_thread['expected_memory_types_found'] is True


def test_same_thread_low_value_does_not_mark_memory_as_winner(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr('app.dependencies.build_llm_provider', lambda config, **_: TieredMemorySemanticProvider())

    run_dir = run_recurring_question_benchmark(
        scenario_file=SCENARIOS,
        output_root=tmp_path / 'output',
        config=_benchmark_config(),
        run_name='recurring-question-low-value',
        answer_provider=TieredMemoryAnswerProvider(),
    )
    results = _read_jsonl(run_dir / 'results.jsonl')
    low_value = next(item for item in results if item['scenario_id'] == 'same-thread-low-value')

    assert low_value['winner'] != 'memory_backed'
    assert low_value['rubric']['comparison']['delta'] == 2


def test_repeated_answer_consistency_rewards_prior_conclusion_carry_forward(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr('app.dependencies.build_llm_provider', lambda config, **_: TieredMemorySemanticProvider())

    run_dir = run_recurring_question_benchmark(
        scenario_file=SCENARIOS,
        output_root=tmp_path / 'output',
        config=_benchmark_config(),
        run_name='recurring-question-repeat',
        answer_provider=TieredMemoryAnswerProvider(),
    )
    results = _read_jsonl(run_dir / 'results.jsonl')
    repeated = next(item for item in results if item['scenario_id'] == 'repeated-answer-consistency')

    assert repeated['winner'] == 'memory_backed'
    assert repeated['rubric']['memory_backed']['consistency'] == 2


def test_recurring_question_benchmark_reports_continuity_memory_for_repeated_answer_strategy(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr('app.dependencies.build_llm_provider', lambda config, **_: TieredMemorySemanticProvider())

    run_dir = run_recurring_question_benchmark(
        scenario_file=SCENARIOS,
        output_root=tmp_path / 'output',
        config=_benchmark_config(),
        run_name='recurring-question-tiered',
        answer_provider=TieredMemoryAnswerProvider(),
        consolidation_strategy='thread_summary_anchored',
    )
    summary = json.loads((run_dir / 'summary.json').read_text(encoding='utf-8'))
    results = _read_jsonl(run_dir / 'results.jsonl')
    repeated = next(item for item in results if item['scenario_id'] == 'repeated-answer-consistency')

    assert summary['consolidation_strategy'] == 'thread_summary_anchored'
    assert repeated['consolidation_run'] is not None
    assert 'continuity_memory' in repeated['higher_level_memory_types']
    assert repeated['expected_higher_level_memory_types_found'] is True