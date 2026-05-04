"""Note memory extraction — dedicated prompt for explicit ingest content."""
from __future__ import annotations

from core.contracts import ProcessResult
from core.indexing import VECTOR_INDEX_TYPE, build_index_entry
from core.models import MemoryObject, Relation, SourceItem
from core.text import normalize_for_index
from providers.llm.base import LLMProvider
from semantic.agent_conversation_memory_embedding import (
    VECTOR_EMBEDDING_PROVIDER_NAME,
    VECTOR_EMBEDDING_PROVIDER_VERSION,
    build_embedding_text,
)


_NOTE_EXTRACTION_SYSTEM_PROMPT = """\
Extract a concise title (1 sentence, max 15 words) that describes what this note is about.
The title should work as a heading — someone scanning a list of notes should immediately \
know what this one contains.

Do NOT paraphrase the content or add interpretation.
Focus on the subject/topic, not on the fact that it was saved.

Return JSON: {"title": "..."}"""

_NOTE_EXTRACTION_SCHEMA_DESCRIPTION = '{"title": "string (max 15 words)"}'


def _resolve_actor_ref(source_item: SourceItem) -> str | None:
    """Determine actor_ref for a memory created from a source item.

    Private containers: propagate the speaker's actor_ref (personal memory).
    Global: propagate actor_ref (required for cross-container actor gating).
    Shared containers (container/public): null (shared evidence).
    """
    if source_item.visibility in ("private", "global"):
        return source_item.actor_ref
    return None


def build_note_memory(source_item: SourceItem, *, provider: LLMProvider) -> ProcessResult:
    """Build a note memory object from an explicitly ingested source item.

    Uses a dedicated LLM prompt to extract retrieval metadata (title).
    Full content is always preserved verbatim in the payload.
    """
    content = source_item.content or ""

    # Extract title via LLM
    title = _extract_title(content, provider=provider)

    # Build memory object
    payload = {
        "content": content,
        "title": title,
        "source_type": source_item.source_type,
        "source_id": source_item.source_id,
    }

    memory_object = MemoryObject(
        type="note",
        schema_id="agent_conversation_memory.note",
        schema_version="v1",
        payload=payload,
        visibility=source_item.visibility,
        container_ref=source_item.container_ref,
        actor_ref=_resolve_actor_ref(source_item),
    )

    # Relation: memory -> source
    relation = Relation(
        from_kind="memory_object",
        from_id=memory_object.id,
        relation_type="supported_by",
        to_kind="source_item",
        to_id=source_item.id,
    )

    # Lexical index: title + content for full-text search
    index_text = " ".join(part for part in (title, content) if part)
    lexical_entry = build_index_entry(
        target_kind="memory_object",
        target_id=memory_object.id,
        index_type="lexical",
        text_view=normalize_for_index(index_text),
        text_view_name="memory_object.note_context",
    )

    # Vector index (will be None until embedding module adds note builder)
    index_entries = [lexical_entry]
    embedding_text = build_embedding_text(memory_object)
    if embedding_text is not None:
        vector_entry = build_index_entry(
            target_kind="memory_object",
            target_id=memory_object.id,
            index_type=VECTOR_INDEX_TYPE,
            text_view=embedding_text,
            text_view_name="memory_object.note_context.embedding",
            provider_name=VECTOR_EMBEDDING_PROVIDER_NAME,
            provider_version=VECTOR_EMBEDDING_PROVIDER_VERSION,
        )
        index_entries.append(vector_entry)

    return ProcessResult(
        memory_objects=[memory_object],
        relations=[relation],
        index_entries=index_entries,
        source_item_metadata_updates={},
        thread_rebuild_requested=False,
    )


def _extract_title(content: str, *, provider: LLMProvider) -> str:
    """Extract a concise title from the content via LLM.

    Falls back to first line of content (truncated) if LLM fails or returns empty.
    """
    if not content.strip():
        return "Note"

    try:
        response = provider.generate_json(
            system_prompt=_NOTE_EXTRACTION_SYSTEM_PROMPT,
            user_prompt=content,
            schema_description=_NOTE_EXTRACTION_SCHEMA_DESCRIPTION,
        )
        title = (response.parsed_json.get("title") or "").strip()
        if title:
            return title
    except Exception:
        pass

    # Fallback: first non-empty line, truncated
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped:
            # Strip markdown heading prefix if present
            if stripped.startswith("#"):
                stripped = stripped.lstrip("#").strip()
            return stripped[:100] if stripped else "Note"
    return "Note"
