from __future__ import annotations

import json
from pathlib import Path

from evals.public_corpus_builder import (
    build_candidate_episodes,
    build_reviewed_episodes,
    extract_review_conversation_ids,
    load_public_corpus_conversations,
    load_review_manifest,
)


FIXTURE = Path('tests/fixtures/wildbench_export_sample.json')
MANIFEST = Path('evals/public_corpus/wildbench_review_manifest.json')
DEV_CONTINUATION_MANIFEST = Path('evals/public_corpus/wildbench_developer_continuation_manifest.json')


def _json_default(value: object) -> str:
    isoformat = getattr(value, 'isoformat', None)
    if callable(isoformat):
        return isoformat().replace('+00:00', 'Z')
    raise TypeError(f'Unsupported JSON value: {type(value).__name__}')



def test_load_wildbench_conversations_filters_to_safe_english_multi_turn_rows() -> None:
    conversations = load_public_corpus_conversations(FIXTURE, corpus_name='wildbench')

    assert len(conversations) == 5
    by_id = {item['conversation_id']: item for item in conversations}
    assert set(by_id) == {
        'wb-review-001',
        'wb-review-002',
        'wb-review-003',
        'wb-review-004',
        'wb-review-005',
    }
    assert all(item['language'] == 'english' for item in conversations)
    assert all(item['safe'] is not False for item in conversations)
    assert by_id['wb-review-001']['primary_tag'] == 'coding'
    assert by_id['wb-review-003']['intent'] == 'evaluation'
    assert by_id['wb-review-004']['reference_answer'] == "The exact log line was 'job already running, skipping new start'."
    assert by_id['wb-review-005']['reference_answer'].startswith('The current blocker is a 429')



def test_load_wildbench_conversations_accepts_materialized_review_set_rows(tmp_path: Path) -> None:
    conversations = load_public_corpus_conversations(FIXTURE, corpus_name='wildbench')
    materialized_path = tmp_path / 'conversations.json'
    materialized_path.write_text(json.dumps(conversations, indent=2, default=_json_default), encoding='utf-8')

    reloaded = load_public_corpus_conversations(materialized_path, corpus_name='wildbench')

    assert [item['conversation_id'] for item in reloaded] == [item['conversation_id'] for item in conversations]
    assert reloaded[0]['sort_key'] == conversations[0]['sort_key']
    assert reloaded[4]['reference_answer'] == conversations[4]['reference_answer']



def test_wildbench_candidate_episode_generation_is_within_conversation_only() -> None:
    conversations = load_public_corpus_conversations(FIXTURE, corpus_name='wildbench')
    candidates = build_candidate_episodes(conversations)

    assert len(candidates) == 5
    assert all(item['episode_type'] == 'within_conversation_later_turn_recall' for item in candidates)
    assert {item['primary_tag'] for item in candidates} == {'career', 'coding', 'travel'}



def test_wildbench_reviewed_manifest_conversation_ids_cover_reviewed_slice() -> None:
    manifest = load_review_manifest(MANIFEST)

    assert extract_review_conversation_ids(manifest) == {
        'wb-review-001',
        'wb-review-002',
        'wb-review-003',
        'wb-review-004',
    }



def test_wildbench_reviewed_episode_builder_emits_pallium_shaped_episodes() -> None:
    conversations = load_public_corpus_conversations(FIXTURE, corpus_name='wildbench')
    manifest = load_review_manifest(MANIFEST)
    episodes = build_reviewed_episodes(conversations=conversations, manifest=manifest)

    assert len(episodes) == 4
    by_id = {item['episode_id']: item for item in episodes}

    recall = by_id['wildbench-k8s-memory-cap-recall']
    assert recall['should_memory_help'] is True
    assert recall['expected_winning_layer'] == 'lower_level_memory'
    assert recall['source_primary_tag'] == 'coding'
    assert recall['source_checklist'] == ['mentions 1Gi limit', 'mentions 512Mi request']

    no_value = by_id['wildbench-kyoto-no-value-guard']
    assert no_value['should_memory_help'] is False
    assert no_value['current_thread_context'][0]['content'].startswith('Here is a relaxed plan.')

    source_evidence = by_id['wildbench-overlap-log-line']
    assert source_evidence['expected_winning_layer'] == 'source_evidence'
    assert source_evidence['reference_answer'] == "The exact log line was 'job already running, skipping new start'."



def test_wildbench_developer_continuation_manifest_stays_small_and_coding_weighted() -> None:
    conversations = load_public_corpus_conversations(FIXTURE, corpus_name='wildbench')
    manifest = load_review_manifest(DEV_CONTINUATION_MANIFEST)
    episodes = build_reviewed_episodes(conversations=conversations, manifest=manifest)

    assert len(episodes) == 10
    assert episodes[0]['episode_id'] == 'wildbench-k8s-memory-cap-recall'
    episode_ids = {item['episode_id'] for item in episodes}
    assert 'wildbench-overlap-log-line' in episode_ids
    assert 'wildbench-overlap-log-line-no-value' in episode_ids
    assert 'wildbench-sync-retry-current-blocker' in episode_ids
    assert 'wildbench-sync-retry-no-value' in episode_ids
    assert sum(1 for item in episodes if item['source_primary_tag'] == 'coding') == 8
