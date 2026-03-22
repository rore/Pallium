from __future__ import annotations

import json
from pathlib import Path

from app.config import AppConfig
from evals.external_memory_pressure_benchmark import run_external_memory_pressure_benchmark
from tests.stub_providers import TieredMemorySemanticProvider
import pytest

pytestmark = pytest.mark.slow

FIXTURE = Path('tests/fixtures/external_memory_pressure_longmemeval_sample.json')
MANIFEST = Path('evals/external_memory_pressure/longmemeval_review_manifest.json')


def _benchmark_config() -> AppConfig:
    return AppConfig(default_use_case='agent_conversation_memory', llm_provider='openai_compatible', llm_model='fake-answer-model', llm_base_url='http://fake-provider.local', llm_prompt_variant='strict_typed_memory_v4_evidence_guarded')


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def test_external_memory_pressure_benchmark_is_non_gating_and_emits_promotion_candidates(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr('app.dependencies.build_llm_provider', lambda config, **_: TieredMemorySemanticProvider())

    run_dir = run_external_memory_pressure_benchmark(
        transformed_fixture=FIXTURE,
        reviewed_manifest=MANIFEST,
        output_root=tmp_path / 'output',
        config=_benchmark_config(),
        run_name='external-memory-pressure-stub',
        default_consolidation_strategy='thread_summary_anchored',
    )

    summary = json.loads((run_dir / 'summary.json').read_text(encoding='utf-8'))
    results = _read_jsonl(run_dir / 'results.jsonl')
    promotion_candidates = _read_jsonl(run_dir / 'promotion_candidates.jsonl')
    report = (run_dir / 'report.md').read_text(encoding='utf-8')

    assert summary['episodes_total'] == 8
    assert summary['benchmark']['suite_id'] == 'external_memory_pressure'
    assert summary['benchmark']['dataset_tier'] == 'confidence'
    assert summary['benchmark']['primary_lane'] == 'realism'
    assert summary['benchmark']['hard_gate_lanes'] == []
    assert summary['benchmark']['hard_gate_summary']['lanes'] == []
    assert summary['benchmark']['lane_aggregates']['realism']['scenarios_total'] == 8
    assert summary['benchmark']['lane_aggregates']['operational']['scenarios_total'] == 8
    assert summary['promotion_candidates_total'] == len(promotion_candidates)
    assert '# External Memory Pressure Report' in report
    assert {row['source_benchmark_family'] for row in results} == {'longmemeval'}
    assert any(row['pressure_family'] == 'update_vs_stale_memory' for row in results)
    assert any(row['pressure_family'] == 'temporal_ordering' for row in results)
    assert any(row['pressure_family'] == 'cross_session_carry_forward' for row in results)
    assert any(row['pressure_family'] == 'unsupported_or_ambiguous_memory_abstention' for row in results)
    assert any(candidate['mapped_failure_family'] in {'update_conflict_handling_failure', 'unsupported_memory_overreach', 'temporal_reasoning_failure', 'retrieval_recall_failure', 'wrong_memory_selection_failure'} for candidate in promotion_candidates)
    assert all(candidate['promotable'] is True for candidate in promotion_candidates)
