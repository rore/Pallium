from __future__ import annotations

import json
from pathlib import Path

from app.config import AppConfig
from evals.public_corpus_benchmark import run_public_corpus_benchmark
from tests.stub_providers import PublicCorpusAnswerProvider, PublicCorpusSemanticProvider


FIXTURE = Path('tests/fixtures/wildbench_export_sample.json')
MANIFEST = Path('evals/public_corpus/wildbench_review_manifest.json')


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


def test_public_corpus_benchmark_reports_wildbench_failure_signal(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr('app.dependencies.build_llm_provider', lambda config, **_: PublicCorpusSemanticProvider())

    run_dir = run_public_corpus_benchmark(
        corpus_file=FIXTURE,
        reviewed_manifest=MANIFEST,
        output_root=tmp_path / 'output',
        config=_benchmark_config(),
        run_name='public-corpus-wildbench-stub',
        answer_provider=PublicCorpusAnswerProvider(),
    )

    summary = json.loads((run_dir / 'summary.json').read_text(encoding='utf-8'))
    results = _read_jsonl(run_dir / 'results.jsonl')

    assert summary['corpus_name'] == 'wildbench'
    assert summary['episodes_total'] == 4
    assert summary['should_memory_help_total'] == 3
    assert summary['no_value_guard_total'] == 1
    assert summary['memory_backed_wins'] == 2
    assert summary['policy_successes'] == 3
    assert summary['failure_families']['retrieval_recall_failure'] == 1

    by_id = {item['episode_id']: item for item in results}
    assert by_id['wildbench-k8s-memory-cap-recall']['top_layer'] in {'lower_level_memory', 'source_evidence'}
    assert by_id['wildbench-kyoto-no-value-guard']['winner'] != 'memory_backed'
    assert by_id['wildbench-overlap-log-line']['top_layer'] in {'source_evidence', 'lower_level_memory'}
    assert by_id['wildbench-scorecard-headings-recall']['failure_family'] == 'retrieval_recall_failure'
    assert by_id['wildbench-scorecard-headings-recall']['source_primary_tag'] == 'career'
