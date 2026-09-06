from __future__ import annotations

from core.models import IndexEntry, SourceItem


BUILTIN_INDEX_PROVIDER_NAME = "builtin"
BUILTIN_INDEX_PROVIDER_VERSION = "v1"
VECTOR_INDEX_TYPE = "vector"
SOURCE_ITEM_CONTENT_TEXT_VIEW = "source_item.content"
SOURCE_ITEM_VECTOR_TEXT_VIEW = "source_content.embedding"
# Bump when any embedding text format changes.
EMBEDDING_SCHEMA_VERSION = 2
VECTOR_EMBEDDING_PROVIDER_NAME = "embedding"
VECTOR_EMBEDDING_PROVIDER_VERSION = "pending"


def build_index_entry(
    *,
    target_kind: str,
    target_id: str,
    index_type: str,
    text_view: str,
    text_view_name: str,
    provider_name: str = BUILTIN_INDEX_PROVIDER_NAME,
    provider_version: str = BUILTIN_INDEX_PROVIDER_VERSION,
) -> IndexEntry:
    return IndexEntry(
        target_kind=target_kind,
        target_id=target_id,
        index_type=index_type,
        text_view=text_view,
        text_view_name=text_view_name,
        provider_name=provider_name,
        provider_version=provider_version,
    )

def source_item_embedding_text(source_item: SourceItem) -> str | None:
    """Return the package-independent embedding view for an eligible raw source."""
    if source_item.artifact_kind not in ("message", "assistant_output"):
        return None
    if len(source_item.content) < 40:
        return None
    return source_item.content
