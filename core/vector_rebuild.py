"""Recompute embedding text from source objects for vector index rebuilds."""

from __future__ import annotations

import logging

from core.models import IndexEntry, MemoryObject
from storage.base import StorageProvider

logger = logging.getLogger(__name__)


def _recompute_embedding_text(storage: StorageProvider, entry: IndexEntry) -> str | None:
    """Recompute embedding text for an index entry from its source object.

    Returns None if the source object no longer exists (orphaned entry).
    """
    if entry.target_kind == "memory_object":
        try:
            memory_object = storage.get_memory_object(entry.target_id)
        except KeyError:
            return None

        # Route based on text_view_name
        if "fact_embedding" in entry.text_view_name or "fact_summary_embedding" in entry.text_view_name:
            return _recompute_fact_embedding_text(memory_object)
        else:
            from semantic.agent_conversation_memory_embedding import build_embedding_text
            return build_embedding_text(memory_object)

    elif entry.target_kind == "source_item":
        try:
            source_item = storage.get_source_item(entry.target_id)
        except KeyError:
            return None

        from semantic.agent_conversation_memory_embedding import source_item_embedding_text
        return source_item_embedding_text(source_item)

    return None


def _recompute_fact_embedding_text(memory_object: MemoryObject) -> str | None:
    """Recompute embedding text for atomic_fact / fact_summary memory objects."""
    payload = memory_object.payload
    subject = payload.get("subject", "")
    memory_type = memory_object.type

    if memory_type == "atomic_fact":
        statement = payload.get("statement", "")
        raw_text = f"{subject}: {statement}" if subject else statement
        return f"[atomic_fact] {raw_text}" if raw_text else None
    elif memory_type == "fact_summary":
        summary = payload.get("summary", "")
        raw_text = f"{subject}: {summary}" if subject else summary
        return f"[fact_summary] {raw_text}" if raw_text else None
    return None
