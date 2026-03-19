from __future__ import annotations

from core.models import IndexEntry


BUILTIN_INDEX_PROVIDER_NAME = "builtin"
BUILTIN_INDEX_PROVIDER_VERSION = "v1"
VECTOR_INDEX_TYPE = "vector"
SOURCE_ITEM_CONTENT_TEXT_VIEW = "source_item.content"


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
