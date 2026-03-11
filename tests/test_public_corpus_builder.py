from __future__ import annotations

from pathlib import Path

from evals.public_corpus_builder import build_candidate_episodes, build_reviewed_episodes, load_review_manifest, load_wildchat_conversations


FIXTURE = Path('tests/fixtures/wildchat_export_sample.jsonl')
MANIFEST = Path('evals/public_corpus/wildchat_review_manifest.json')


def test_load_wildchat_conversations_filters_to_safe_english_multi_turn_rows() -> None:
    conversations = load_wildchat_conversations(FIXTURE)

    assert len(conversations) == 7
    by_id = {item['conversation_id']: item for item in conversations}
    assert set(by_id) == {
        'wc-review-001',
        'wc-review-002',
        'wc-review-003',
        'wc-review-004',
        'wc-review-005',
        'wc-review-006',
        'wc-review-007',
    }
    assert all(item['language'] == 'english' for item in conversations)
    assert all(item['safe'] is not False for item in conversations)
    assert by_id['wc-review-001']['safe'] is True
    assert by_id['wc-review-003']['safe'] is True
    assert by_id['wc-review-003']['container_ref'] == by_id['wc-review-004']['container_ref']
    assert by_id['wc-review-003']['session_ref'] != by_id['wc-review-004']['session_ref']


def test_candidate_episode_generation_is_deterministic_and_includes_carry_forward() -> None:
    conversations = load_wildchat_conversations(FIXTURE)
    candidates = build_candidate_episodes(conversations)

    assert len(candidates) == 10
    assert any(item['episode_type'] == 'within_conversation_later_turn_recall' for item in candidates)
    assert any(item['episode_type'] == 'later_session_carry_forward' for item in candidates)
    assert any(item['target_conversation_id'] == 'wc-review-004' for item in candidates if item['episode_type'] == 'later_session_carry_forward')


def test_reviewed_episode_builder_emits_pallium_shaped_events() -> None:
    conversations = load_wildchat_conversations(FIXTURE)
    manifest = load_review_manifest(MANIFEST)
    episodes = build_reviewed_episodes(conversations=conversations, manifest=manifest)

    assert len(episodes) == 4
    by_id = {item['episode_id']: item for item in episodes}

    lower_level = by_id['wildchat-feed-ratio-recall']
    assert lower_level['should_memory_help'] is True
    assert lower_level['expected_winning_layer'] == 'lower_level_memory'
    assert lower_level['current_query']['text'] == 'What exact feed ratio did you tell me to use again?'
    assert lower_level['prior_events'][0]['artifact_kind'] == 'message'
    assert lower_level['prior_events'][1]['artifact_kind'] == 'assistant_output'

    continuity = by_id['wildchat-handoff-carry-forward']
    assert continuity['episode_type'] == 'later_session_carry_forward'
    assert continuity['source_conversation_ids'] == ['wc-review-003']
    assert continuity['target_conversation_id'] == 'wc-review-004'
    assert continuity['current_query']['container_ref'].endswith('user:user-handoff')

    pattern = by_id['wildchat-grocery-pattern-recall']
    assert pattern['source_conversation_ids'] == ['wc-review-005', 'wc-review-006']
    assert pattern['expected_higher_level_memory_types'] == ['pattern_memory']
