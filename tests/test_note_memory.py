import pytest
from api.schemas import ArtifactKind
from typing import get_args
from core.models import SourceItem


def _make_source_item(
    content: str,
    *,
    artifact_kind: str = "note",
    container_ref: str = "git:test/repo",
    actor_ref: str = "user:test",
    visibility: str = "private",
    role: str = "user",
    source_id: str = "test-source-1",
    thread_ref: str = "test-thread-1",
) -> SourceItem:
    return SourceItem(
        source_type="agent_artifact",
        source_id=source_id,
        content_type="text/plain",
        content=content,
        artifact_kind=artifact_kind,
        role=role,
        container_ref=container_ref,
        actor_ref=actor_ref,
        thread_ref=thread_ref,
        visibility=visibility,
    )


def test_note_is_valid_artifact_kind():
    valid_kinds = get_args(ArtifactKind)
    assert "note" in valid_kinds
