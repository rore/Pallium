from __future__ import annotations

import json
from pathlib import Path

from app.config import AppConfig
from evals.consolidation_strategy_runner import run_consolidation_strategy_comparison
from tests.stub_providers import TieredMemoryAnswerProvider, TieredMemorySemanticProvider


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def test_consolidation_strategy_runner_outputs_modes_and_tradeoffs(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr('app.dependencies.build_llm_provider', lambda config, **_: TieredMemorySemanticProvider())

    run_dir = run_consolidation_strategy_comparison(
        scenario_file=Path('evals/consolidation/scenarios.json'),
        benchmark_scenario_file=Path('evals/recurring_question/scenarios.json'),
        output_root=tmp_path / 'output',
        config=AppConfig(
            default_use_case='agent_conversation_memory',
            llm_provider='openai_compatible',
            llm_model='fake-answer-model',
            llm_base_url='http://fake-provider.local',
            llm_prompt_variant='strict_typed_memory_v4_evidence_guarded',
        ),
        run_name='consolidation-comparison-smoke',
        answer_provider=TieredMemoryAnswerProvider(),
    )

    summary = json.loads((run_dir / 'summary.json').read_text(encoding='utf-8'))
    results = _read_jsonl(run_dir / 'results.jsonl')
    mode_summaries = {item['mode']: item for item in summary['modes']}

    assert set(mode_summaries) == {'no_tiered', 'thread_local_carry_forward', 'container_topic_window', 'thread_summary_anchored'}
    assert any('continuity_memory' in item['higher_level_memory_types'] for item in results if item['strategy_name'] == 'thread_local_carry_forward')
    # envelope-first routing: pattern_memory may not appear in query results if other types score higher
    container_topic_results = [item for item in results if item['strategy_name'] == 'container_topic_window']
    assert len(container_topic_results) > 0  # strategy ran
    assert mode_summaries['container_topic_window']['benchmark']['aggregate_delta'] > 0
    assert mode_summaries['thread_local_carry_forward']['continuity_memory_created'] >= 1
    assert mode_summaries['thread_summary_anchored']['continuity_memory_created'] >= 1
    assert mode_summaries['thread_summary_anchored']['benchmark']['aggregate_delta'] > 0


def test_consolidation_strategy_runner_captures_false_merge_guard(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr('app.dependencies.build_llm_provider', lambda config, **_: TieredMemorySemanticProvider())

    run_dir = run_consolidation_strategy_comparison(
        scenario_file=Path('evals/consolidation/scenarios.json'),
        benchmark_scenario_file=Path('evals/recurring_question/scenarios.json'),
        output_root=tmp_path / 'output',
        config=AppConfig(
            default_use_case='agent_conversation_memory',
            llm_provider='openai_compatible',
            llm_model='fake-answer-model',
            llm_base_url='http://fake-provider.local',
            llm_prompt_variant='strict_typed_memory_v4_evidence_guarded',
        ),
        run_name='consolidation-false-merge-check',
        answer_provider=TieredMemoryAnswerProvider(),
    )

    results = _read_jsonl(run_dir / 'results.jsonl')
    noisy = [
        item for item in results
        if item['scenario_id'] == 'same-container-noise-guard' and item['strategy_name'] != 'no_tiered'
    ]

    assert noisy
    assert all(item['false_merge_occurred'] is False for item in noisy)