from __future__ import annotations

import json
from pathlib import Path

from evals.public_corpus_wildbench_local import (
    benchmark_review_set,
    emit_review_candidates,
    ensure_local_layout,
    materialize_review_set,
    validate_local_corpus,
)
from tests.stub_providers import PublicCorpusAnswerProvider, PublicCorpusSemanticProvider


FIXTURE = Path('tests/fixtures/wildbench_export_sample.json')
MANIFEST = Path('evals/public_corpus/wildbench_review_manifest.json')


class _CombinedPublicCorpusProvider:
    def __init__(self) -> None:
        self._semantic = PublicCorpusSemanticProvider()
        self._answer = PublicCorpusAnswerProvider()

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str):
        if 'evidence_used' in schema_description:
            return self._answer.generate_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema_description=schema_description,
            )
        return self._semantic.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema_description=schema_description,
        )



def _seed_local_snapshot(root: Path) -> Path:
    layout = ensure_local_layout(root)
    target = layout['snapshot_dir'] / 'wildbench-export.json'
    target.write_text(FIXTURE.read_text(encoding='utf-8'), encoding='utf-8')
    return target



def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]



def _configure_local_benchmark_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv('PALLIUM_ENV_FILE', str(tmp_path / 'missing.env'))
    monkeypatch.setenv('PALLIUM_CONFIG_FILE', str(tmp_path / 'missing.toml'))
    monkeypatch.setenv('PALLIUM_DEFAULT_USE_CASE', 'agent_conversation_memory')
    monkeypatch.setenv('PALLIUM_LLM_PROVIDER', 'openai_compatible')
    monkeypatch.setenv('PALLIUM_LLM_MODEL', 'fake-answer-model')
    monkeypatch.setenv('PALLIUM_LLM_BASE_URL', 'http://fake-provider.local')
    monkeypatch.setenv('PALLIUM_LLM_PROMPT_VARIANT', 'strict_typed_memory_v4_evidence_guarded')



def test_validate_local_wildbench_corpus_reports_json_snapshot_layout(tmp_path: Path) -> None:
    _seed_local_snapshot(tmp_path)

    summary = validate_local_corpus(tmp_path)

    assert summary['root'] == str(tmp_path)
    assert summary['snapshot_dir'] == str(tmp_path / 'snapshot')
    assert summary['json_file_count'] == 1
    assert summary['snapshot_size_bytes'] > 0



def test_emit_review_candidates_uses_local_wildbench_layout(tmp_path: Path) -> None:
    _seed_local_snapshot(tmp_path)

    output_path = emit_review_candidates(root=tmp_path, output_file=None)
    candidates = _read_jsonl(output_path)

    assert output_path == tmp_path / 'derived' / 'review_candidates.jsonl'
    assert len(candidates) == 5
    assert all(item['episode_type'] == 'within_conversation_later_turn_recall' for item in candidates)



def test_materialize_wildbench_review_set_writes_small_local_review_bundle(tmp_path: Path) -> None:
    _seed_local_snapshot(tmp_path)

    review_dir = materialize_review_set(root=tmp_path, reviewed_manifest=MANIFEST, output_name='fixture-review')
    summary = json.loads((review_dir / 'summary.json').read_text(encoding='utf-8'))
    conversations = json.loads((review_dir / 'conversations.json').read_text(encoding='utf-8'))
    episodes = json.loads((review_dir / 'reviewed_episodes.json').read_text(encoding='utf-8'))

    assert review_dir == tmp_path / 'derived' / 'review_sets' / 'fixture-review'
    assert summary['conversation_count'] == 4
    assert len(conversations) == 4
    assert len(episodes) == 4
    assert {item['conversation_id'] for item in conversations} == {
        'wb-review-001',
        'wb-review-002',
        'wb-review-003',
        'wb-review-004',
    }



def test_benchmark_review_set_runs_end_to_end_from_materialized_local_review_bundle(monkeypatch, tmp_path: Path) -> None:
    _seed_local_snapshot(tmp_path)
    _configure_local_benchmark_env(monkeypatch, tmp_path)

    provider_factory = lambda config, **_: _CombinedPublicCorpusProvider()
    monkeypatch.setattr('app.dependencies.build_llm_provider', provider_factory)
    monkeypatch.setattr('evals.public_corpus_benchmark.build_llm_provider', provider_factory)

    run_dir = benchmark_review_set(
        root=tmp_path,
        reviewed_manifest=MANIFEST,
        output_name='fixture-review',
        run_name='wildbench-local-helper',
        default_consolidation_strategy='thread_summary_anchored',
    )

    summary = json.loads((run_dir / 'summary.json').read_text(encoding='utf-8'))
    results = _read_jsonl(run_dir / 'results.jsonl')

    assert run_dir == tmp_path / 'runs' / 'wildbench-local-helper'
    assert summary['corpus_name'] == 'wildbench'
    assert summary['corpus_file'] == str(tmp_path / 'derived' / 'review_sets' / 'fixture-review' / 'conversations.json')
    assert summary['episodes_total'] == 4
    assert summary['failure_families']['retrieval_recall_failure'] == 0
    assert summary['policy_successes'] == 4
    assert len(results) == 4
    assert (run_dir / 'report.md').exists()
    assert {item['episode_id'] for item in results} == {
        'wildbench-k8s-memory-cap-recall',
        'wildbench-kyoto-no-value-guard',
        'wildbench-scorecard-headings-recall',
        'wildbench-overlap-log-line',
    }

