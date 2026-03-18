from __future__ import annotations

import json
from pathlib import Path

from tests.config_helpers import build_llm_test_config
from evals.low_value_churn_benchmark import run_low_value_churn_benchmark
from tests.stub_providers import TieredMemorySemanticProvider


SCENARIOS = Path('evals/low_value_churn/scenarios.json')


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def _benchmark_config():
    return build_llm_test_config(
        default_use_case='agent_conversation_memory',
        model='fake-answer-model',
    )


def test_low_value_churn_benchmark_keeps_low_value_threads_and_churn_controls_green(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr('app.dependencies.build_llm_provider', lambda config, **_: TieredMemorySemanticProvider())

    run_dir = run_low_value_churn_benchmark(
        scenario_file=SCENARIOS,
        output_root=tmp_path / 'output',
        config=_benchmark_config(),
        run_name='low-value-churn-smoke',
    )

    summary = json.loads((run_dir / 'summary.json').read_text(encoding='utf-8'))
    results = _read_jsonl(run_dir / 'results.jsonl')
    report = (run_dir / 'report.md').read_text(encoding='utf-8')

    assert summary['scenarios_total'] == 3
    assert len(results) == 3
    assert summary['policy_successes'] == 3
    assert summary['low_value_promotion_successes'] == 3
    assert summary['thread_rebuild_churn_successes'] == 3
    assert summary['failure_family_counts']['low_value_promotion_failure'] == 0
    assert summary['failure_family_counts']['thread_rebuild_churn_failure'] == 0
    assert summary['benchmark']['suite_id'] == 'low_value_churn'
    assert summary['benchmark']['dataset_tier'] == 'confidence'
    assert summary['benchmark']['primary_lane'] == 'operational'
    assert summary['benchmark']['lane_aggregates']['trace']['scenarios_total'] == 3
    assert summary['benchmark']['lane_aggregates']['operational']['scenarios_total'] == 3
    assert '# Low-Value And Churn Benchmark Report' in report

    by_id = {item['scenario_id']: item for item in results}
    for scenario_id in by_id:
        assert by_id[scenario_id]['suite_id'] == 'low_value_churn'
        assert by_id[scenario_id]['dataset_tier'] == 'confidence'
        assert by_id[scenario_id]['primary_lane'] == 'operational'
        assert by_id[scenario_id]['scored_lanes'] == ['trace', 'operational']
        assert by_id[scenario_id]['failure_families'] == []
        assert by_id[scenario_id]['policy_success'] is True

    assert by_id['single-low-value-meta-turn']['low_value_promotion_failures'] == []
    assert by_id['single-low-value-meta-turn']['low_value_rebuild_failures'] == []
    assert by_id['single-low-value-meta-turn']['summary_churn']['active_summary_count'] == 0
    assert by_id['low-value-only-thread-stays-quiet']['summary_churn']['active_summary_count'] == 0
    assert by_id['sharp-decision-thread-avoids-noisy-summary-churn']['summary_churn']['active_summary_count'] == 1
    assert by_id['sharp-decision-thread-avoids-noisy-summary-churn']['summary_churn']['superseded_summary_count'] == 0