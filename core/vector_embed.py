from __future__ import annotations

import logging

from core.contracts import ProcessResult
from core.indexing import VECTOR_INDEX_TYPE, build_index_entry
from core.models import IndexEntry, SourceItem
from providers.embedding.base import EmbeddingProvider
from semantic.base import SemanticPlugin
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
        vector_index: VectorIndex | None = None,
    ) -> None:
        self._storage = storage
        self._embedding_provider = embedding_provider
        self._vector_index = vector_index
        self._logger = logging.getLogger(__name__)

    def embed_process_result(self, process_result: ProcessResult, plugin: SemanticPlugin | None = None) -> bool:
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
            vectors = self._embedding_provider.embed(texts)
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

    def build_source_item_vector_entry(self, plugin: SemanticPlugin, source_item: SourceItem) -> IndexEntry | None:
        """Create a vector IndexEntry for a source item using plugin embedding text.

        Returns the IndexEntry if created and persisted to storage, or None if:
        - embedding_provider or vector_index is None
        - the plugin returns no embedding text for the source item
        - a vector entry already exists for this source item
        - an error occurs during creation
        """
        if self._embedding_provider is None or self._vector_index is None:
            return None
        try:
            embedding_text = plugin.source_item_embedding_text(source_item)
            if embedding_text is None:
                return None
            existing = self._storage.find_index_entry(
                target_kind="source_item",
                target_id=source_item.id,
                index_type=VECTOR_INDEX_TYPE,
                text_view_name="source_content.embedding",
            )
            if existing is not None:
                return None
            source_vector_entry = build_index_entry(
                target_kind="source_item",
                target_id=source_item.id,
                index_type=VECTOR_INDEX_TYPE,
                text_view=embedding_text,
                text_view_name="source_content.embedding",
                provider_name=self._embedding_provider.model_name(),
                provider_version=f"dim={self._embedding_provider.dimensions()}",
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
        try:
            vectors = self._embedding_provider.embed([index_entry.text_view])
            self._vector_index.add(index_entry.id, vectors[0])
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
        Reverse direction: remove usearch entries missing from SQLite (unbounded, cheap).
        Returns total number of entries changed (embedded + removed).
        """
        if self._embedding_provider is None or self._vector_index is None:
            return 0
        try:
            sqlite_count = self._storage.count_index_entries_by_type("vector")
            index_count = self._vector_index.entry_count()
            if sqlite_count == index_count:
                return 0

            sqlite_entries = self._storage.list_index_entries_by_type("vector")
            sqlite_ids = {e.id for e in sqlite_entries}
            usearch_ids = self._vector_index.known_entry_ids()

            total_changed = 0

            # Reverse: remove stale usearch entries (cheap, no batching)
            stale_ids = usearch_ids - sqlite_ids
            for entry_id in stale_ids:
                try:
                    self._vector_index.remove(entry_id)
                    total_changed += 1
                except KeyError:
                    pass

            # Forward: embed missing entries (batch-bounded)
            missing_entries = [e for e in sqlite_entries if e.id not in usearch_ids]
            batch = missing_entries[:batch_size]
            if batch:
                texts = [e.text_view for e in batch]
                vectors = self._embedding_provider.embed(texts)
                for entry, vector in zip(batch, vectors):
                    self._vector_index.add(entry.id, vector)
                    self._storage.update_index_entry_provider(
                        entry.id,
                        provider_name=self._embedding_provider.model_name(),
                        provider_version=f"dim={self._embedding_provider.dimensions()}",
                    )
                    total_changed += 1

            if total_changed > 0:
                self._vector_index.save()

            return total_changed
        except Exception:
            self._logger.warning("Vector reconciliation failed; will retry next cycle", exc_info=True)
            return 0
