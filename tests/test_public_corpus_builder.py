from __future__ import annotations

from pathlib import Path

from evals.public_corpus_builder import (
    build_candidate_episodes,
    build_reviewed_episodes,
    extract_review_conversation_ids,
    load_review_manifest,
    load_wildchat_conversations,
)


FIXTURE = Path('tests/fixtures/wildchat_export_sample.jsonl')
MANIFEST = Path('evals/public_corpus/wildchat_review_manifest.json')


def test_load_wildchat_conversations_filters_to_safe_english_multi_turn_rows() -> None:
    conversations = load_wildchat_conversations(FIXTURE)

    assert len(conversations) == 9
    by_id = {item['conversation_id']: item for item in conversations}
    assert set(by_id) == {
        'wc-review-001',
        'wc-review-002',
        'wc-review-003',
        'wc-review-004',
        'wc-review-005',
        'wc-review-006',
        'wc-review-007',
        'wc-review-008',
        'wc-review-009',
    }
    assert all(item['language'] == 'english' for item in conversations)
    assert all(item['safe'] is not False for item in conversations)
    assert by_id['wc-review-001']['safe'] is True
    assert by_id['wc-review-003']['safe'] is True
    assert by_id['wc-review-003']['container_ref'] == by_id['wc-review-004']['container_ref']
    assert by_id['wc-review-004']['container_ref'] == by_id['wc-review-008']['container_ref']
    assert by_id['wc-review-008']['container_ref'] == by_id['wc-review-009']['container_ref']
    assert by_id['wc-review-003']['session_ref'] != by_id['wc-review-004']['session_ref']



def test_load_wildchat_conversations_supports_directory_inputs_and_targeted_ids(tmp_path: Path) -> None:
    source_lines = [line for line in FIXTURE.read_text(encoding='utf-8').splitlines() if line.strip()]
    first_file = tmp_path / 'part-000.jsonl'
    second_file = tmp_path / 'part-001.jsonl'
    first_file.write_text('\n'.join(source_lines[:6]) + '\n', encoding='utf-8')
    second_file.write_text('\n'.join(source_lines[6:]) + '\n', encoding='utf-8')

    conversations = load_wildchat_conversations(tmp_path, conversation_ids={'wc-review-003', 'wc-review-004', 'wc-review-008'})

    assert [item['conversation_id'] for item in conversations] == ['wc-review-003', 'wc-review-008', 'wc-review-004']



def test_candidate_episode_generation_is_deterministic_and_includes_carry_forward() -> None:
    conversations = load_wildchat_conversations(FIXTURE)
    candidates = build_candidate_episodes(conversations)

    assert len(candidates) == 14
    assert any(item['episode_type'] == 'within_conversation_later_turn_recall' for item in candidates)
    assert any(item['episode_type'] == 'later_session_carry_forward' for item in candidates)
    assert any(item['target_conversation_id'] == 'wc-review-004' for item in candidates if item['episode_type'] == 'later_session_carry_forward')
    assert any(item['target_conversation_id'] == 'wc-review-009' for item in candidates if item['episode_type'] == 'later_session_carry_forward')



def test_reviewed_manifest_conversation_ids_cover_reviewed_slice() -> None:
    manifest = load_review_manifest(MANIFEST)

    assert extract_review_conversation_ids(manifest) == {
        'wc-review-001',
        'wc-review-002',
        'wc-review-003',
        'wc-review-004',
        'wc-review-005',
        'wc-review-006',
        'wc-review-007',
        'wc-review-008',
        'wc-review-009',
    }



def test_reviewed_episode_builder_emits_pallium_shaped_events() -> None:
    conversations = load_wildchat_conversations(FIXTURE)
    manifest = load_review_manifest(MANIFEST)
    episodes = build_reviewed_episodes(conversations=conversations, manifest=manifest)

    assert len(episodes) == 10
    by_id = {item['episode_id']: item for item in episodes}

    lower_level = by_id['wildchat-feed-ratio-recall']
    assert lower_level['should_memory_help'] is True
    assert lower_level['expected_winning_layer'] == 'lower_level_memory'
    assert lower_level['current_query']['text'] == 'What exact feed ratio did you tell me to use again?'
    assert lower_level['prior_events'][0]['artifact_kind'] == 'message'
    assert lower_level['prior_events'][1]['artifact_kind'] == 'assistant_output'

    evidence_followup = by_id['wildchat-feed-ratio-evidence-follow-up']
    assert evidence_followup['expected_intent'] == 'evidence_trace'
    assert evidence_followup['expected_winning_layer'] == 'source_evidence'

    continuity = by_id['wildchat-handoff-carry-forward']
    assert continuity['episode_type'] == 'later_session_carry_forward'
    assert continuity['source_conversation_ids'] == ['wc-review-003', 'wc-review-008']
    assert continuity['target_conversation_id'] == 'wc-review-004'
    assert continuity['current_query']['container_ref'].endswith('user:user-handoff')
    assert continuity['must_not_introduce'] == ['wrong_thread_state']

    pattern = by_id['wildchat-grocery-pattern-recall']
    assert pattern['source_conversation_ids'] == ['wc-review-005', 'wc-review-006']
    assert pattern['expected_higher_level_memory_types'] == ['pattern_memory']

    handoff_paraphrase = by_id['wildchat-handoff-old-answer-paraphrase']
    assert handoff_paraphrase['current_query']['text'].startswith('I just need the old handoff template answer')
    assert handoff_paraphrase['expected_winning_layer'] == 'continuity_memory'

    kiosk_resumption = by_id['wildchat-branch-kiosk-resumption']
    assert kiosk_resumption['expected_winning_layer'] == 'task_checkpoint'
    assert kiosk_resumption['must_not_introduce'] == ['stale_state']
    assert kiosk_resumption['prior_events'][1]['artifact_kind'] == 'tool_use_summary'
    assert kiosk_resumption['prior_events'][-1]['artifact_kind'] == 'todo_snapshot'

    kiosk_carry_forward = by_id['wildchat-branch-kiosk-carry-forward']
    assert kiosk_carry_forward['expected_intent'] == 'work_resumption'
    assert kiosk_carry_forward['target_conversation_id'] == 'wc-review-009'

    kiosk_no_value = by_id['wildchat-branch-kiosk-no-value-guard']
    assert kiosk_no_value['should_memory_help'] is False
    assert kiosk_no_value['current_thread_context'][0]['artifact_kind'] == 'tool_use_summary'

    grocery_paraphrase = by_id['wildchat-grocery-big-picture-paraphrase']
    assert grocery_paraphrase['expected_winning_layer'] == 'pattern_memory'
    assert grocery_paraphrase['target_question'].startswith('I want the big picture on why grocery trips keep dragging out')

