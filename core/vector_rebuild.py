"""Rebuild the vector index by recomputing embedding text from source objects."""

from __future__ import annotations

import logging
from pathlib import Path

from core.models import IndexEntry, MemoryObject
from providers.embedding.base import EmbeddingProvider
from storage.base import StorageProvider

logger = logging.getLogger(__name__)

AUTO_REBUILD_THRESHOLD = 5000


def rebuild_vector_index(
    *,
    storage: StorageProvider,
    embedding_provider: EmbeddingProvider,
    index_path: Path,
    embedding_schema_version: int,
) -> "VectorIndex":
    """Rebuild the vector index from scratch, recomputing embedding text from source.

    1. Loads all vector index entries from SQLite.
    2. For each entry, recomputes embedding text from its source object.
    3. Updates stored text_view if it changed.
    4. Batch embeds all texts.
    5. Builds a new VectorIndex and saves it.
    """
    from storage.vector_index import VectorIndex

    entries = storage.list_index_entries_by_type("vector")
    logger.info("Rebuild: found %d vector index entries in SQLite.", len(entries))

    # Recompute text for each entry, skipping orphans
    valid_entries: list[IndexEntry] = []
    texts: list[str] = []

    for entry in entries:
        new_text = _recompute_embedding_text(storage, entry)
        if new_text is None:
            logger.debug("Rebuild: skipping orphaned entry %s (target %s/%s).", entry.id, entry.target_kind, entry.target_id)
            continue

        # Update stored text_view if it changed
        if new_text != entry.text_view:
            storage.update_index_entry_text_view(entry.id, new_text)

        valid_entries.append(entry)
        texts.append(new_text)

    logger.info("Rebuild: embedding %d entries (skipped %d orphans).", len(valid_entries), len(entries) - len(valid_entries))

    # Create fresh index
    vector_index = VectorIndex.create_empty(
        index_path,
        dimensions=embedding_provider.dimensions(),
        model_name=embedding_provider.model_name(),
        embedding_schema_version=embedding_schema_version,
    )

    if texts:
        batch_size = 128
        for batch_start in range(0, len(texts), batch_size):
            batch_texts = texts[batch_start:batch_start + batch_size]
            batch_entries = valid_entries[batch_start:batch_start + batch_size]
            vectors = embedding_provider.embed(batch_texts, mode="passage")
            for entry, vector in zip(batch_entries, vectors):
                vector_index.add(entry.id, vector)
            if batch_start + batch_size < len(texts):
                logger.info("Rebuild: embedded %d/%d entries...", batch_start + len(batch_texts), len(texts))

    vector_index.save()
    logger.info("Rebuild: vector index saved at %s with %d entries.", index_path, vector_index.entry_count())
    return vector_index


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
