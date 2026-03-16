from __future__ import annotations

import json
from pathlib import Path

from app.config import AppConfig
from evals.developer_work_confidence import run_developer_work_confidence_suite
from evals.benchmark_architecture import build_suite_summary
from tests.stub_providers import (
    PublicCorpusAnswerProvider,
    PublicCorpusSemanticProvider,
    TieredMemoryAnswerProvider,
    TieredMemorySemanticProvider,
)
from tests.test_work_resumption_benchmark import StubWorkResumptionAnswerProvider

WORK_SCENARIOS = Path('evals/work_resumption/scenarios.json')
MEMORY_ROUTING_SCENARIOS = Path('evals/memory_routing/scenarios.json')
WILDCHAT_FIXTURE = Path('tests/fixtures/wildchat_export_sample.jsonl')
WILDCHAT_MANIFEST = Path('evals/public_corpus/wildchat_review_manifest.json')
WILDBENCH_FIXTURE = Path('tests/fixtures/wildbench_export_sample.json')
WILDBENCH_MANIFEST = Path('evals/public_corpus/wildbench_developer_continuation_manifest.json')

PUBLIC_CORPUS_MARKERS = (
    '1:2:2 starter feed',
    'done / waiting / next owner',
    'problem framing',
    'job already running, skipping new start',
    'fushimi inari',
    'arashiyama',
    'store section',
    'backtracking',
    'branch kiosk fallback coverage',
    'kiosk smoke tests',
    'retry window was exhausted',
    'batch 418',
)


class CompositeSemanticProvider:
    def __init__(self) -> None:
        self._tiered = TieredMemorySemanticProvider()
        self._public = PublicCorpusSemanticProvider()

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str):
        lowered = user_prompt.lower()
        delegate = self._public if any(marker in lowered for marker in PUBLIC_CORPUS_MARKERS) else self._tiered
        return delegate.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema_description=schema_description,
        )


def _benchmark_config() -> AppConfig:
    return AppConfig(
        default_use_case='agent_conversation_memory',
        llm_provider='openai_compatible',
        llm_model='fake-answer-model',
        llm_base_url='http://fake-provider.local',
        llm_prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )


def test_developer_work_confidence_suite_reports_hard_gates_and_pressure_signals(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr('app.dependencies.build_llm_provider', lambda config, **_: CompositeSemanticProvider())

    run_dir = run_developer_work_confidence_suite(
        work_scenario_file=WORK_SCENARIOS,
        memory_routing_scenario_file=MEMORY_ROUTING_SCENARIOS,
        wildchat_corpus_file=WILDCHAT_FIXTURE,
        wildchat_manifest=WILDCHAT_MANIFEST,
        wildbench_corpus_file=WILDBENCH_FIXTURE,
        wildbench_manifest=WILDBENCH_MANIFEST,
        output_root=tmp_path / 'output',
        config=_benchmark_config(),
        run_name='developer-work-confidence',
        work_answer_provider=StubWorkResumptionAnswerProvider(),
        memory_routing_answer_provider=TieredMemoryAnswerProvider(),
        public_corpus_answer_provider=PublicCorpusAnswerProvider(),
    )

    summary = json.loads((run_dir / 'summary.json').read_text(encoding='utf-8'))
    report = (run_dir / 'report.md').read_text(encoding='utf-8')

    assert summary['components']['work_resumption']['scenarios_total'] == 13
    assert summary['components']['memory_routing']['scenarios_total'] == 11
    assert summary['components']['wildchat_reviewed']['scenarios_total'] == 10
    assert summary['components']['wildbench_developer']['scenarios_total'] == 10
    assert summary['components']['low_value_churn']['scenarios_total'] == 3

    assert summary['components']['memory_routing']['dataset_tier'] == 'confidence'
    assert summary['components']['memory_routing']['primary_lane'] == 'trace'
    assert summary['components']['memory_routing']['benchmark']['hard_gate_summary']['all_green'] is True

    assert summary['aggregate']['scenarios_total'] == 47
    assert summary['aggregate']['policy_successes'] >= 37
    assert summary['aggregate']['dominant_tuning_bottleneck'] == 'packaging'
    assert summary['aggregate']['dominant_benchmark_lane'] in {'contract', 'trace'}
    assert summary['aggregate']['hard_gate_status']['lanes'] == ['contract', 'trace']
    assert summary['aggregate']['hard_gate_status']['coverage_complete'] is True
    assert summary['aggregate']['tier_aggregates']['confidence']['scenarios_total'] == 47
    assert summary['aggregate']['tier_aggregates']['replay']['scenarios_total'] == 0
    assert summary['aggregate']['benchmark']['replay_summary']['assets_total'] == 0
    assert summary['aggregate']['benchmark']['replay_summary']['has_replay_assets'] is False
    assert summary['aggregate']['failure_family_counts']['routing_layer_choice_failure'] >= 2
    assert summary['aggregate']['failure_family_counts']['injectability_packaging_failure'] >= 7
    assert summary['aggregate']['failure_family_counts']['thin_agent_boundary_failure'] >= 7
    assert summary['aggregate']['failure_family_counts']['paraphrase_or_indirect_query_failure'] >= 3
    assert summary['aggregate']['failure_family_counts']['wrong_memory_selection_failure'] >= 2
    assert summary['aggregate']['failure_family_counts']['low_value_promotion_failure'] == 0
    assert summary['aggregate']['failure_family_counts']['thread_rebuild_churn_failure'] == 0

    assert summary['gates']['contract_hard_gate_green'] is False
    assert summary['gates']['trace_hard_gate_green'] is False
    assert summary['gates']['hard_gate_passed'] is False
    assert summary['gates']['zero_privacy_leaks'] is True
    assert summary['gates']['zero_wrong_memory_failures'] is False
    assert summary['gates']['zero_low_value_promotion_failures'] is True
    assert summary['gates']['zero_thread_rebuild_churn_failures'] is True
    assert summary['gates']['memory_routing_suite_green'] is True
    assert summary['gates']['work_suite_green'] is False
    assert summary['gates']['wildchat_suite_green'] is False
    assert summary['gates']['wildbench_suite_green'] is False
    assert summary['gates']['low_value_churn_suite_green'] is True
    assert summary['gates']['realism_pressure_present'] is True
    assert summary['gates']['operational_drift_present'] is True
    assert summary['gates']['replay_assets_present'] is False
    assert summary['gates']['confidence_gate_passed'] is False

    assert '## Hard-Gate Foundation' in report
    assert '## Realism And Replay Pressure' in report
    assert '## Operational Drift' in report
    assert '`hard_gate_passed`: FAIL' in report
    assert '`confidence_gate_passed`: FAIL' in report
    assert '`memory_routing`' in report

def test_developer_work_confidence_suite_fails_closed_when_hard_gate_coverage_is_missing(tmp_path: Path, monkeypatch) -> None:
    def _write_stub_run(name: str, suite_id: str) -> Path:
        run_dir = tmp_path / name
        run_dir.mkdir(parents=True, exist_ok=True)
        summary = {
            'benchmark': build_suite_summary(suite_id=suite_id, results=[]),
        }
        (run_dir / 'summary.json').write_text(json.dumps(summary), encoding='utf-8')
        (run_dir / 'results.jsonl').write_text('', encoding='utf-8')
        return run_dir

    monkeypatch.setattr(
        'evals.developer_work_confidence.run_work_resumption_benchmark',
        lambda **kwargs: _write_stub_run('work_resumption', 'work_resumption'),
    )
    monkeypatch.setattr(
        'evals.developer_work_confidence.run_memory_routing_benchmark',
        lambda **kwargs: _write_stub_run('memory_routing', 'memory_routing'),
    )
    monkeypatch.setattr(
        'evals.developer_work_confidence.run_public_corpus_benchmark',
        lambda **kwargs: _write_stub_run(kwargs['run_name'], 'public_corpus'),
    )
    monkeypatch.setattr(
        'evals.developer_work_confidence.run_low_value_churn_benchmark',
        lambda **kwargs: _write_stub_run('low_value_churn', 'low_value_churn'),
    )

    run_dir = run_developer_work_confidence_suite(
        work_scenario_file=WORK_SCENARIOS,
        memory_routing_scenario_file=MEMORY_ROUTING_SCENARIOS,
        wildchat_corpus_file=WILDCHAT_FIXTURE,
        wildchat_manifest=WILDCHAT_MANIFEST,
        wildbench_corpus_file=WILDBENCH_FIXTURE,
        wildbench_manifest=WILDBENCH_MANIFEST,
        output_root=tmp_path / 'output',
        config=_benchmark_config(),
        run_name='developer-work-confidence-missing-coverage',
    )

    summary = json.loads((run_dir / 'summary.json').read_text(encoding='utf-8'))

    assert summary['aggregate']['hard_gate_status']['coverage_complete'] is False
    assert summary['aggregate']['hard_gate_status']['missing_lanes'] == ['contract', 'trace']
    assert summary['gates']['contract_hard_gate_green'] is False
    assert summary['gates']['trace_hard_gate_green'] is False
    assert summary['gates']['hard_gate_passed'] is False
    assert summary['gates']['confidence_gate_passed'] is False
