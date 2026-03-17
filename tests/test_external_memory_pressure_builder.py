from __future__ import annotations

from pathlib import Path

from evals.external_memory_pressure_builder import build_reviewed_external_pressure_episodes, extract_review_episode_ids, load_review_manifest, load_transformed_episodes

FIXTURE = Path('tests/fixtures/external_memory_pressure_longmemeval_sample.json')
MANIFEST = Path('evals/external_memory_pressure/longmemeval_review_manifest.json')


def test_external_pressure_builder_filters_reviewed_slice_and_preserves_labels() -> None:
    fixture_rows = load_transformed_episodes(FIXTURE)
    manifest = load_review_manifest(MANIFEST)
    reviewed = build_reviewed_external_pressure_episodes(episodes=fixture_rows, manifest=manifest)

    assert len(reviewed) == 8
    assert extract_review_episode_ids(manifest) == [row['episode_id'] for row in reviewed]
    assert {row['source_benchmark_family'] for row in reviewed} == {'longmemeval'}
    assert {row['dataset_tier'] for row in reviewed} == {'confidence'}
    assert {row['pressure_family'] for row in reviewed} == {
        'update_vs_stale_memory',
        'temporal_ordering',
        'cross_session_carry_forward',
        'unsupported_or_ambiguous_memory_abstention',
    }
    assert reviewed[0]['expected_failure_target'] == 'update_conflict_handling_failure'
    assert reviewed[0]['suggested_native_lane'] == 'work_resumption'
    assert reviewed[0]['promotable'] is True
