from __future__ import annotations

import logging

from core.filters import matches_filters, target_visibility_and_container
from core.models import (
    IndexEntry,
    QueryFilters,
    QueryResultItem,
    QueryTrace,
    RetrievalStageTrace,
    RetrievalTraceHit,
)
from core.vector_index_holder import VectorIndexHolder
from core.visibility import (
    QueryVisibilityTrace,
    is_visible,
)
from providers.embedding.base import EmbeddingProvider
from retrieval.base import RetrievalProvider, RetrievalQueryResult
from retrieval.common import build_evidence, build_excerpt
from storage.base import StorageProvider
from storage.vector_index import VectorIndex

logger = logging.getLogger(__name__)

VECTOR_STAGE_NAME = "vector"


class VectorRetrievalProvider(RetrievalProvider):
    def __init__(
        self,
        storage: StorageProvider,
        embedding_provider: EmbeddingProvider,
        min_similarity: float = 0.3,
        *,
        index_holder: VectorIndexHolder,
    ) -> None:
        self._storage = storage
        self._holder = index_holder
        self._embedding_provider = embedding_provider
        self._min_similarity = min_similarity

    @property
    def _vector_index(self) -> VectorIndex | None:
        return self._holder.index

    def query(
        self,
        text: str,
        limit: int,
        filters: QueryFilters | None = None,
        *,
        visibility: str | None = None,
        query_container_ref: str | None = None,
        include_trace: bool = False,
        require_visibility: bool = False,
        query_actor_ref: str | None = None,
        target_kind: str | None = None,
    ) -> RetrievalQueryResult:
        if require_visibility and query_container_ref is None:
            trace = None
            if include_trace:
                trace = QueryTrace(
                    query_text=text,
                    query_tokens=(),
                    limit=limit,
                    filters=filters,
                    stages=tuple(),
                    visibility=QueryVisibilityTrace(
                        query_visibility=visibility,
                        query_container_ref=query_container_ref,
                        fail_closed_reason="retrieval_visibility_context_required",
                    ),
                )
            return RetrievalQueryResult(results=[], trace=trace)

        # Capture index reference once to avoid TOCTOU across search/remove
        index = self._vector_index
        if index is None:
            return RetrievalQueryResult(results=[], trace=None)

        # 1. Embed query text
        query_vectors = self._embedding_provider.embed([text], mode="query")
        query_vector = query_vectors[0]

        # 2. Search vector index (overfetch limit * 4). For source-only search
        # the ANN index cannot filter by target_kind, so over-fetch more widely
        # and skip non-matching kinds below — the guaranteed source coverage
        # comes from the lexical leg's SQL push-down; this just lets the vector
        # leg contribute source hits it would otherwise crowd out with memory.
        search_k = limit * 8 if target_kind is not None else limit * 4
        raw_hits = index.search(query_vector, k=search_k)

        # 3. Resolve entry_ids to IndexEntries, handle stale entries
        resolved_hits: list[tuple[IndexEntry, float]] = []
        index_entries = self._storage.get_index_entries([entry_id for entry_id, _similarity in raw_hits])
        if not isinstance(index_entries, dict):
            index_entries = {}

        for entry_id, similarity in raw_hits:
            index_entry = index_entries.get(entry_id)
            if index_entry is None:
                try:
                    index_entry = self._storage.get_index_entry(entry_id)
                except KeyError:
                    # Stale entry: index entry deleted by retention
                    logger.debug("Stale vector index entry %s; scheduling lazy removal", entry_id)
                    try:
                        index.remove(entry_id)
                    except KeyError:
                        pass  # Already removed
                    continue
            resolved_hits.append((index_entry, similarity))

        # Stale entry removal is in-memory only — reconcile handles disk persistence.
        # No save() call here; the query-serving process should not write the index file.

        # 4. Apply min_similarity threshold, filters, visibility, and dedup
        results: list[QueryResultItem] = []
        all_candidate_trace_hits: list[RetrievalTraceHit] = []
        selected_trace_hits: list[RetrievalTraceHit] = []
        seen: set[tuple[str, str]] = set()

        hits_before_visibility = 0
        hits_after_visibility = 0

        for index_entry, similarity in resolved_hits:
            score = int(similarity * 1000)

            # Source-only search (vNext P1): the ANN index can't filter by
            # target_kind, so skip non-matching kinds here (defense-in-depth
            # alongside the lexical SQL push-down). Skips before trace/threshold
            # so a source-only vector stage reflects only source candidates.
            if target_kind is not None and index_entry.target_kind != target_kind:
                continue

            # Build trace hit for all candidates (before filtering)
            trace_hit = RetrievalTraceHit(
                target_kind=index_entry.target_kind,
                target_id=index_entry.target_id,
                index_entry_id=index_entry.id,
                index_type="vector",
                text_view_name=index_entry.text_view_name,
                score=score,
                matched_tokens=(),
                provider_name=index_entry.provider_name,
                provider_version=index_entry.provider_version,
                cosine_similarity=similarity,
            )

            if include_trace:
                all_candidate_trace_hits.append(trace_hit)

            # Apply min_similarity threshold
            if similarity < self._min_similarity:
                continue

            # Apply filters (lifecycle check for memory_objects + field matching)
            if not matches_filters(
                self._storage.get_memory_object,
                self._storage.get_source_item,
                self._storage.get_evidence_for_memory_object,
                index_entry.target_kind, index_entry.target_id, filters,
            ):
                continue

            hits_before_visibility += 1

            # Apply visibility using new is_visible()
            candidate_visibility, candidate_container_ref, candidate_actor_ref = target_visibility_and_container(
                self._storage.get_source_item, self._storage.get_memory_object,
                index_entry.target_kind, index_entry.target_id,
            )
            if not is_visible(candidate_visibility, candidate_container_ref, query_container_ref, candidate_actor_ref, query_visibility=visibility, query_actor_ref=query_actor_ref):
                continue

            hits_after_visibility += 1

            # Dedup by (target_kind, target_id)
            key = (index_entry.target_kind, index_entry.target_id)
            if key in seen:
                continue
            seen.add(key)

            # 6. Hydrate into QueryResultItem (same pattern as lexical.py)
            if index_entry.target_kind == "memory_object":
                try:
                    memory_object = self._storage.get_memory_object(index_entry.target_id)
                    evidence = self._storage.get_evidence_for_memory_object(index_entry.target_id)
                except KeyError:
                    logger.debug("Skipping deleted memory_object %s during hydration", index_entry.target_id)
                    continue
                results.append(
                    QueryResultItem(
                        result_kind="memory_hit",
                        memory_object_id=memory_object.id,
                        type=memory_object.type,
                        payload=memory_object.payload,
                        freshness_at=memory_object.freshness_at,
                        envelope=memory_object.envelope,
                        score=score,
                        evidence=evidence,
                        visibility=memory_object.visibility,
                    )
                )
            elif index_entry.target_kind == "source_item":
                try:
                    source_item = self._storage.get_source_item(index_entry.target_id)
                except KeyError:
                    logger.debug("Skipping deleted source_item %s during hydration", index_entry.target_id)
                    continue
                results.append(
                    QueryResultItem(
                        result_kind="source_hit",
                        source_item_id=source_item.id,
                        source_type=source_item.source_type,
                        source_id=source_item.source_id,
                        excerpt=build_excerpt(source_item.content),
                        occurred_at=source_item.occurred_at,
                        actor_ref=source_item.actor_ref,
                        agent_ref=source_item.agent_ref,
                        role=source_item.role,
                        container_ref=source_item.container_ref,
                        thread_ref=source_item.thread_ref,
                        source_ref=source_item.source_ref,
                        artifact_kind=source_item.artifact_kind,
                        score=score,
                        evidence=[build_evidence(source_item)],
                        visibility=source_item.visibility,
                    )
                )
            else:
                continue

            if include_trace:
                selected_trace_hits.append(trace_hit)

            if len(results) >= limit:
                break

        # 7. Build trace
        trace = None
        if include_trace:
            trace = QueryTrace(
                query_text=text,
                query_tokens=(),
                limit=limit,
                filters=filters,
                stages=(
                    RetrievalStageTrace(
                        stage_name=VECTOR_STAGE_NAME,
                        candidate_hits_considered=len(all_candidate_trace_hits),
                        candidate_hits=tuple(all_candidate_trace_hits),
                        selected_hits=tuple(selected_trace_hits),
                        candidate_hits_before_visibility=hits_before_visibility,
                        candidate_hits_after_visibility=hits_after_visibility,
                    ),
                ),
                visibility=(
                    QueryVisibilityTrace(
                        query_visibility=visibility,
                        query_container_ref=query_container_ref,
                    )
                    if visibility is not None or query_container_ref is not None
                    else None
                ),
            )

        return RetrievalQueryResult(results=results, trace=trace)
