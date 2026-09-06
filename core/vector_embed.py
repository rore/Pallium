from __future__ import annotations

import logging

from core.contracts import ProcessResult
from core.indexing import (
    SOURCE_ITEM_VECTOR_TEXT_VIEW, VECTOR_EMBEDDING_PROVIDER_NAME,
    VECTOR_EMBEDDING_PROVIDER_VERSION, VECTOR_INDEX_TYPE,
    build_index_entry, source_item_embedding_text,
)
from core.models import IndexEntry, SourceItem
from core.vector_index_holder import VectorIndexHolder
from providers.embedding.base import EmbeddingProvider
from storage.base import StorageProvider
from storage.vector_index import VectorIndex


class VectorEmbedder:
    """Encapsulates vector embedding and index persistence for PalliumService.

    Handles:
    - Embedding ProcessResult index entries into the in-memory vector index
    - Building vector IndexEntries for source items via plugin embedding text
    - Embedding and persisting individual vector entries
    - Saving the in-memory vector index to disk

    All operations are no-ops when embedding_provider or vector_index is None.
    """

    def __init__(
        self,
        storage: StorageProvider,
        embedding_provider: EmbeddingProvider | None = None,
        *,
        index_holder: VectorIndexHolder,
        enabled: bool | None = None,
    ) -> None:
        self._storage = storage
        self._embedding_provider = embedding_provider
        self._holder = index_holder
        self._enabled = bool(embedding_provider or index_holder.index) if enabled is None else enabled
        self._logger = logging.getLogger(__name__)
        self._reconcile_after_id: str | None = None
        self._reconcile_stale_after_id: str | None = None

    @property
    def _vector_index(self) -> VectorIndex | None:
        return self._holder.index

    def reset_reconcile_state(self) -> None:
        """Reset pagination cursors after a hot-swap so reconcile starts fresh."""
        self._reconcile_after_id = None
        self._reconcile_stale_after_id = None

    def embed_process_result(self, process_result: ProcessResult) -> bool:
        """Add vector index entries to the in-memory index after SQLite commit.

        Filters committed index entries for index_type="vector", embeds them
        via the embedding provider, and adds them to the in-memory vector index.
        Does NOT save the index to disk -- the caller is responsible for calling
        save_vector_index() once all embedding work for the current processing
        cycle is complete.
        If either embedding_provider or vector_index is None, this is a no-op.
        If embedding fails, the error is logged and execution continues --
        reconciliation catches gaps.

        Returns True if any vectors were added to the in-memory index.
        """
        if self._embedding_provider is None or self._vector_index is None:
            return False
        vector_entries = [e for e in process_result.index_entries if e.index_type == VECTOR_INDEX_TYPE]
        if not vector_entries:
            return False
        try:
            texts = [entry.text_view for entry in vector_entries]
            vectors = self._embedding_provider.embed(texts, mode="passage")
            for entry, vector in zip(vector_entries, vectors):
                self._vector_index.add(entry.id, vector)
                self._storage.update_index_entry_provider(
                    entry.id,
                    provider_name=self._embedding_provider.model_name(),
                    provider_version=f"dim={self._embedding_provider.dimensions()}",
                )
            return True
        except Exception:
            self._logger.warning("Vector embedding failed after commit; reconciliation will catch gaps", exc_info=True)
            return False

    def build_source_item_vector_entry(self, source_item: SourceItem) -> IndexEntry | None:
        """Create and persist the eligible raw-source vector entry.

        The entry is persisted even when embedding is temporarily unavailable;
        reconciliation can embed it later.
        """
        if not self._enabled:
            return None
        try:
            embedding_text = source_item_embedding_text(source_item)
            if embedding_text is None:
                return None
            existing = self._storage.find_index_entry(
                target_kind="source_item",
                target_id=source_item.id,
                index_type=VECTOR_INDEX_TYPE,
                text_view_name=SOURCE_ITEM_VECTOR_TEXT_VIEW,
            )
            if existing is not None:
                return existing
            source_vector_entry = build_index_entry(
                target_kind="source_item",
                target_id=source_item.id,
                index_type=VECTOR_INDEX_TYPE,
                text_view=embedding_text,
                text_view_name=SOURCE_ITEM_VECTOR_TEXT_VIEW,
                provider_name=(
                    self._embedding_provider.model_name()
                    if self._embedding_provider is not None
                    else VECTOR_EMBEDDING_PROVIDER_NAME
                ),
                provider_version=(
                    f"dim={self._embedding_provider.dimensions()}"
                    if self._embedding_provider is not None
                    else VECTOR_EMBEDDING_PROVIDER_VERSION
                ),
            )
            self._storage.create_index_entry(source_vector_entry)
            return source_vector_entry
        except Exception:
            self._logger.warning("Source item vector entry creation failed", exc_info=True)
            return None

    def embed_and_persist_vector_entry(self, index_entry: IndexEntry) -> bool:
        """Embed a single index entry and add it to the in-memory vector index.

        Does NOT save the index to disk -- the caller is responsible for calling
        save_vector_index() once all embedding work for the current processing
        cycle is complete.

        Returns True if the vector was successfully added to the index.
        """
        if self._embedding_provider is None or self._vector_index is None:
            return False
        if self._vector_index.contains(index_entry.id):
            return False
        try:
            vectors = self._embedding_provider.embed([index_entry.text_view], mode="passage")
            self._vector_index.add(index_entry.id, vectors[0])
            self._storage.update_index_entry_provider(
                index_entry.id,
                provider_name=self._embedding_provider.model_name(),
                provider_version=f"dim={self._embedding_provider.dimensions()}",
            )
            return True
        except Exception:
            self._logger.warning("Source item vector embedding failed", exc_info=True)
            return False

    def save_vector_index(self) -> None:
        """Flush the in-memory vector index to disk.

        No-op when vector_index is None.  Failures are logged and swallowed --
        reconciliation via rebuild-vector-index recovers missing vectors.
        """
        if self._vector_index is None:
            return
        try:
            self._vector_index.save()
        except Exception:
            self._logger.warning("Vector index save failed; reconciliation will catch gaps", exc_info=True)

    def reconcile(self, batch_size: int = 50) -> int:
        """Find and fix mismatches between SQLite vector entries and usearch index.

        Forward direction: embed SQLite entries missing from usearch (batch-bounded).
        Reverse direction: remove usearch entries missing from SQLite (batch-bounded).
        Returns total number of entries changed (embedded + removed).
        """
        if self._embedding_provider is None or self._vector_index is None:
            return 0
        try:
            sqlite_count = self._storage.count_index_entries_by_type("vector")
            index_count = self._vector_index.entry_count()
            if sqlite_count == index_count:
                self._reconcile_after_id = None
                self._reconcile_stale_after_id = None
                return 0

            total_changed = 0

            usearch_ids = sorted(self._vector_index.known_entry_ids())
            if usearch_ids:
                stale_candidates = usearch_ids
                if self._reconcile_stale_after_id is not None:
                    stale_candidates = [
                        entry_id for entry_id in usearch_ids if entry_id > self._reconcile_stale_after_id
                    ]
                if not stale_candidates:
                    self._reconcile_stale_after_id = None
                    stale_candidates = usearch_ids
                stale_batch_ids = stale_candidates[:batch_size]
                existing_entries = self._storage.get_index_entries(stale_batch_ids)
                for entry_id in stale_batch_ids:
                    if entry_id in existing_entries:
                        continue
                    try:
                        self._vector_index.remove(entry_id)
                        total_changed += 1
                    except KeyError:
                        pass
                if len(stale_candidates) > len(stale_batch_ids):
                    self._reconcile_stale_after_id = stale_batch_ids[-1]
                else:
                    self._reconcile_stale_after_id = None

            sqlite_batch = self._storage.list_index_entries_by_type_page(
                "vector",
                after_id=self._reconcile_after_id,
                limit=batch_size,
            )
            if sqlite_batch:
                usearch_id_set = self._vector_index.known_entry_ids()
                missing_entries = [entry for entry in sqlite_batch if entry.id not in usearch_id_set]
                texts = [entry.text_view for entry in missing_entries]
                vectors = self._embedding_provider.embed(texts, mode="passage") if texts else []
                for entry, vector in zip(missing_entries, vectors):
                    self._vector_index.add(entry.id, vector)
                    self._storage.update_index_entry_provider(
                        entry.id,
                        provider_name=self._embedding_provider.model_name(),
                        provider_version=f"dim={self._embedding_provider.dimensions()}",
                    )
                    total_changed += 1
                self._reconcile_after_id = sqlite_batch[-1].id
            else:
                self._reconcile_after_id = None

            if total_changed > 0:
                self._vector_index.save()

            return total_changed
        except Exception:
            self._logger.warning("Vector reconciliation failed; will retry next cycle", exc_info=True)
            return 0
