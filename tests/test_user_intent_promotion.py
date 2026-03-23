"""Test that user-stated interest is promoted to the `interest` memory type.

Scenario: user discusses vector databases with the assistant across a thread,
then expresses specific interest in a tool (Chroma). After a thread boundary
(/new), a query asking what the user wanted to try should surface a specific
interest memory — not only generic discussion summaries.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.config_helpers import build_agent_conversation_client

CONTAINER_REF = 'chat:vector-db-intent-test'
THREAD_A = f'{CONTAINER_REF}:thread-a'
THREAD_B = f'{CONTAINER_REF}:thread-b'


def _build_client(monkeypatch, sqlite_url: str) -> TestClient:
    return build_agent_conversation_client(monkeypatch, sqlite_url)


THREAD_A_EVENTS = [
    {
        'source_type': 'chat_message',
        'source_id': f'{THREAD_A}-msg-1',
        'content_type': 'text/plain',
        'content': "I'm looking for a lightweight vector database for a side project.",
        'artifact_kind': 'message',
        'role': 'user',
        'container_ref': CONTAINER_REF,
        'thread_ref': THREAD_A,
        'container_visibility': 'private',
        'occurred_at': '2026-03-20T18:00:00Z',
    },
    {
        'source_type': 'assistant_artifact',
        'source_id': f'{THREAD_A}-asst-1',
        'content_type': 'text/plain',
        'content': (
            'Chroma is a great choice — simple Python API, runs locally, '
            'pip install chromadb and you are ready. Qdrant is another '
            'option if you need more performance.'
        ),
        'artifact_kind': 'assistant_output',
        'role': 'assistant',
        'container_ref': CONTAINER_REF,
        'thread_ref': THREAD_A,
        'container_visibility': 'private',
        'occurred_at': '2026-03-20T18:00:30Z',
    },
    {
        'source_type': 'chat_message',
        'source_id': f'{THREAD_A}-msg-2',
        'content_type': 'text/plain',
        'content': "ok, chroma sounds interesting. i should check it some time.",
        'artifact_kind': 'message',
        'role': 'user',
        'container_ref': CONTAINER_REF,
        'thread_ref': THREAD_A,
        'container_visibility': 'private',
        'occurred_at': '2026-03-20T18:01:00Z',
    },
    {
        'source_type': 'assistant_artifact',
        'source_id': f'{THREAD_A}-asst-2',
        'content_type': 'text/plain',
        'content': 'Great choice! Let me know how it goes.',
        'artifact_kind': 'assistant_output',
        'role': 'assistant',
        'container_ref': CONTAINER_REF,
        'thread_ref': THREAD_A,
        'container_visibility': 'private',
        'occurred_at': '2026-03-20T18:01:30Z',
    },
]


def test_user_intent_promoted_to_actionable_memory(monkeypatch, test_db_url: str) -> None:
    """After a user says 'chroma sounds interesting, i should check it some
    time', an interest memory should be created — not only generic summaries."""
    with _build_client(monkeypatch, test_db_url) as client:
        # Ingest thread A conversation
        response = client.post('/items', json=THREAD_A_EVENTS)
        assert response.status_code == 200
        client.app.state.pallium_service.drain_processing_queue(worker_id='intent-test')

        # Check what memory types were created
        storage = client.app.state.pallium_service._storage
        active_memories = storage.list_memory_objects(lifecycle='active')
        active_types = {m.type for m in active_memories}

        actionable_types = {'decision', 'task_checkpoint', 'continuity_memory', 'interest'}
        assert active_types & actionable_types, (
            f'Expected at least one actionable memory type {actionable_types}, '
            f'but only found: {active_types}'
        )

        # Verify the actionable memory mentions Chroma
        actionable_memories = [m for m in active_memories if m.type in actionable_types]
        chroma_mentioned = any(
            'chroma' in str(m.payload).lower()
            for m in actionable_memories
        )
        assert chroma_mentioned, (
            f'Actionable memory should mention Chroma. '
            f'Payloads: {[m.payload for m in actionable_memories]}'
        )


def test_cross_thread_query_surfaces_user_intent(monkeypatch, test_db_url: str) -> None:
    """From a new thread, asking 'what was the db I said I wanted to check?'
    should surface a specific memory about the user's interest in Chroma."""
    with _build_client(monkeypatch, test_db_url) as client:
        # Ingest thread A and process
        response = client.post('/items', json=THREAD_A_EVENTS)
        assert response.status_code == 200
        client.app.state.pallium_service.drain_processing_queue(worker_id='intent-test')

        # Query from thread B
        query_response = client.post('/query/debug', json={
            'text': 'what was the db i said i wanted to check?',
            'limit': 6,
            'container_ref': CONTAINER_REF,
            'thread_ref': THREAD_B,
        })
        assert query_response.status_code == 200
        payload = query_response.json()

        assert payload['should_inject'] is True

        # At least one injectable block should specifically mention Chroma
        # as something the user expressed interest in
        injectable_blocks = payload.get('injectable_blocks') or []
        chroma_intent_blocks = [
            block for block in injectable_blocks
            if 'chroma' in str(block.get('text', '')).lower()
            and block.get('memory_type') in {'decision', 'task_checkpoint', 'continuity_memory', 'interest'}
        ]
        assert chroma_intent_blocks, (
            f'Expected an actionable injectable block mentioning Chroma interest. '
            f'Got blocks: {[(b.get("memory_type"), b.get("text", "")[:80]) for b in injectable_blocks]}'
        )


def test_assistant_response_does_not_produce_interest(monkeypatch, test_db_url: str) -> None:
    """Assistant responses should never produce interest memories — only user messages can."""
    assistant_events = [
        {
            'source_type': 'assistant_artifact',
            'source_id': f'{THREAD_A}-asst-interest-check',
            'content_type': 'text/plain',
            'content': (
                'Chroma sounds interesting and you should check it out! '
                'It may be worth looking into for your use case.'
            ),
            'artifact_kind': 'assistant_output',
            'role': 'assistant',
            'container_ref': CONTAINER_REF,
            'thread_ref': THREAD_A,
            'occurred_at': '2026-03-20T18:02:00Z',
        },
    ]
    with _build_client(monkeypatch, test_db_url) as client:
        response = client.post('/items', json=assistant_events)
        assert response.status_code == 200
        client.app.state.pallium_service.drain_processing_queue(worker_id='intent-test')

        storage = client.app.state.pallium_service._storage
        active_memories = storage.list_memory_objects(lifecycle='active')
        interest_memories = [m for m in active_memories if m.type == 'interest']
        assert not interest_memories, (
            f'Assistant response should not create interest memories, '
            f'but found: {[m.payload for m in interest_memories]}'
        )
