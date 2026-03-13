from __future__ import annotations

import json
from pathlib import Path

from app.config import AppConfig
from evals.memory_routing_benchmark import run_memory_routing_benchmark
from tests.stub_providers import TieredMemoryAnswerProvider, TieredMemorySemanticProvider


SCENARIOS = Path('evals/memory_routing/scenarios.json')


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


def test_memory_routing_benchmark_outputs_summary_results_and_report(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr('app.dependencies.build_llm_provider', lambda config, **_: TieredMemorySemanticProvider())

    run_dir = run_memory_routing_benchmark(
        scenario_file=SCENARIOS,
        output_root=tmp_path / 'output',
        config=_benchmark_config(),
        run_name='memory-routing-smoke',
        answer_provider=TieredMemoryAnswerProvider(),
    )

    summary = json.loads((run_dir / 'summary.json').read_text(encoding='utf-8'))
    results = _read_jsonl(run_dir / 'results.jsonl')
    report = (run_dir / 'report.md').read_text(encoding='utf-8')

    assert summary['scenarios_total'] == 10
    assert len(results) == 10
    assert summary['policy_successes'] == 10
    assert '## Aggregate' in report
    assert summary['false_merge_failures'] == 0


def test_memory_routing_benchmark_captures_expected_layer_choices(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr('app.dependencies.build_llm_provider', lambda config, **_: TieredMemorySemanticProvider())

    run_dir = run_memory_routing_benchmark(
        scenario_file=SCENARIOS,
        output_root=tmp_path / 'output',
        config=_benchmark_config(),
        run_name='memory-routing-layers',
        answer_provider=TieredMemoryAnswerProvider(),
    )
    results = {item['scenario_id']: item for item in _read_jsonl(run_dir / 'results.jsonl')}

    assert results['broad-recall-cross-thread']['top_layer'] == 'pattern_memory'
    assert results['answer-continuity-repeat']['top_layer'] == 'continuity_memory'
    assert results['precise-fact-ordering']['top_layer'] == 'lower_level_memory'
    assert results['broad-recall-paraphrase']['top_layer'] == 'pattern_memory'
    assert results['evidence-trace-exact']['top_layer'] == 'source_evidence'
    assert results['evidence-trace-paraphrase-challenge']['top_layer'] == 'source_evidence'
    assert results['same-container-false-merge-guard']['top_layer'] == 'lower_level_memory'
    assert results['same-thread-low-value']['top_layer'] == 'none'


def test_memory_routing_benchmark_handles_evidence_trace_paraphrase(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr('app.dependencies.build_llm_provider', lambda config, **_: TieredMemorySemanticProvider())

    run_dir = run_memory_routing_benchmark(
        scenario_file=SCENARIOS,
        output_root=tmp_path / 'output',
        config=_benchmark_config(),
        run_name='memory-routing-challenge',
        answer_provider=TieredMemoryAnswerProvider(),
    )
    results = {item['scenario_id']: item for item in _read_jsonl(run_dir / 'results.jsonl')}
    challenge = results['evidence-trace-paraphrase-challenge']
    fallback_case = results['same-container-false-merge-guard']

    assert challenge['intent_match'] is True
    assert challenge['policy_success'] is True
    assert challenge['expected_intent'] == 'evidence_trace'
    assert challenge['routing_intent'] == 'evidence_trace'
    assert fallback_case['top_layer'] == 'lower_level_memory'
    assert fallback_case['query_trace']['routing']['fallback']['applied'] is True
    assert fallback_case['query_trace']['routing']['fallback']['to_layer'] == 'lower_level_memory'
