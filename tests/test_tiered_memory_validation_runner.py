from __future__ import annotations

import json
from pathlib import Path

from app.config import AppConfig
from evals.tiered_memory_validation_runner import run_tiered_memory_validation_benchmark
from tests.stub_providers import TieredMemoryAnswerProvider, TieredMemorySemanticProvider


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def test_tiered_memory_validation_runner_outputs_summary_and_results(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr('app.dependencies.build_llm_provider', lambda config, **_: TieredMemorySemanticProvider())

    run_dir = run_tiered_memory_validation_benchmark(
        scenario_file=Path('evals/tiered_memory_validation/scenarios.json'),
        output_root=tmp_path / 'output',
        config=AppConfig(
            default_use_case='agent_conversation_memory',
            llm_provider='openai_compatible',
            llm_model='fake-answer-model',
            llm_base_url='http://fake-provider.local',
            llm_prompt_variant='strict_typed_memory_v4_evidence_guarded',
        ),
        run_name='tiered-memory-validation-smoke',
        answer_provider=TieredMemoryAnswerProvider(),
    )

    summary = json.loads((run_dir / 'summary.json').read_text(encoding='utf-8'))
    results = _read_jsonl(run_dir / 'results.jsonl')

    assert len(results) == 6
    strategy_summaries = {item['strategy_name']: item for item in summary['strategies']}
    assert set(strategy_summaries) == {'thread_local_carry_forward', 'container_topic_window', 'thread_summary_anchored'}
    assert all('policy_successes' in item for item in summary['strategies'])
    assert strategy_summaries['container_topic_window']['helped_as_expected'] >= 1


def test_tiered_memory_validation_runner_captures_strategy_tradeoffs(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr('app.dependencies.build_llm_provider', lambda config, **_: TieredMemorySemanticProvider())

    run_dir = run_tiered_memory_validation_benchmark(
        scenario_file=Path('evals/tiered_memory_validation/scenarios.json'),
        output_root=tmp_path / 'output',
        config=AppConfig(
            default_use_case='agent_conversation_memory',
            llm_provider='openai_compatible',
            llm_model='fake-answer-model',
            llm_base_url='http://fake-provider.local',
            llm_prompt_variant='strict_typed_memory_v4_evidence_guarded',
        ),
        run_name='tiered-memory-validation-policy',
        answer_provider=TieredMemoryAnswerProvider(),
    )

    results = _read_jsonl(run_dir / 'results.jsonl')
    by_id = {item['scenario_id']: item for item in results}

    cross_thread = by_id['cross-thread-pattern-value']
    assert cross_thread['strategy_results']['container_topic_window']['wins_over_lower_level'] is True
    assert cross_thread['strategy_results']['thread_local_carry_forward']['wins_over_lower_level'] is False

    repeated_answer = by_id['repeated-answer-pattern-value']
    assert repeated_answer['strategy_results']['thread_local_carry_forward']['wins_over_lower_level'] is True

    precise = by_id['precise-factual-lower-level']
    assert precise['strategy_results']['container_topic_window']['loses_to_lower_level'] is True
    assert precise['strategy_results']['thread_summary_anchored']['loses_to_lower_level'] is True

    false_merge = by_id['same-container-false-merge-guard']
    assert all(result['false_merge_occurred'] is False for result in false_merge['strategy_results'].values())
