from __future__ import annotations

import logging
from collections.abc import Iterator

from core.filters import matches_filters, target_visibility_and_container
from core.work_ref import work_refs_from_metadata
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
from retrieval.common import (
    build_evidence,
    build_excerpt,
    build_source_content_fingerprint,
)
from storage.base import StorageProvider
from storage.vector_index import VectorIndex

logger = logging.getLogger(__name__)

VECTOR_STAGE_NAME = "vector"

def _iter_vector_hit_batches(
    index: VectorIndex,
    query_vector: list[float],
    limit: int,
    *,
    target_kind: str | None,
) -> Iterator[list[tuple[str, float]]]:
    """Yield duplicate-free ordered prefixes within a start-of-query horizon."""
    if target_kind is None:
        yield index.search(query_vector, k=limit * 4)
        return
    horizon = index.entry_count()
    if horizon <= 0 or limit <= 0:
        return
    search_k = min(max(limit * 8, 1), horizon)
    seen_ids: set[str] = set()
    while True:
        batch = index.search(query_vector, k=search_k)
        new_hits: list[tuple[str, float]] = []
        for entry_id, similarity in batch:
            if entry_id in seen_ids:
                continue
            seen_ids.add(entry_id)
            new_hits.append((entry_id, similarity))
        if new_hits:
            yield new_hits
        if not batch or len(batch) < search_k or search_k >= horizon or not new_hits:
            return
        search_k = min(search_k * 2, horizon)


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

        if (
            target_kind == "source_item"
            and filters
            and filters.work_refs
            and not text.strip()
        ):
            return RetrievalQueryResult(results=[], trace=None)

        # Capture index reference once to avoid TOCTOU across search/remove
        index = self._vector_index
        if index is None:
            return RetrievalQueryResult(results=[], trace=None)

        # 1. Embed query text
        query_vectors = self._embedding_provider.embed([text], mode="query")
        query_vector = query_vectors[0]

        # 2. Search vector index. Default retrieval intentionally remains one
        # fixed overfetch; target-kind retrieval expands in bounded batches.
        results: list[QueryResultItem] = []
        pending_source_hits: list[tuple[IndexEntry, int, RetrievalTraceHit]] = []
        all_candidate_trace_hits: list[RetrievalTraceHit] = []
        selected_trace_hits: list[RetrievalTraceHit] = []
        seen: set[tuple[str, str]] = set()
        hits_before_visibility = 0
        hits_after_visibility = 0

        # Exact source work-ref queries can score the scoped vector universe
        # without invoking global ANN search when both optional capabilities exist.
        fast_source_scope = None
        if target_kind == "source_item" and filters and filters.work_refs and text.strip():
            candidate_loader = getattr(self._storage, "get_source_item_vector_candidates", None)
            subset_scorer = getattr(index, "score_subset", None)
            if callable(candidate_loader) and callable(subset_scorer):
                try:
                    candidates = candidate_loader(tuple(filters.work_refs))
                    candidate_by_id = {entry.id: (entry, projection) for entry, projection in candidates}
                    scored = subset_scorer(query_vector, list(candidate_by_id))
                except NotImplementedError:
                    pass
                else:
                    if isinstance(scored, list):
                        fast_source_scope = (
                            scored,
                            candidate_by_id,
                        )

        raw_hit_batches = (
            [fast_source_scope[0]]
            if fast_source_scope is not None
            else _iter_vector_hit_batches(index, query_vector, limit, target_kind=target_kind)
        )
        for raw_hits in raw_hit_batches:
            # 3. Resolve each newly exposed batch without materializing source content.
            resolved_hits: list[tuple[IndexEntry, float]] = []
            if fast_source_scope is not None:
                candidate_by_id = fast_source_scope[1]
                source_items = {}
                for entry_id, similarity in raw_hits:
                    candidate = candidate_by_id.get(entry_id)
                    if candidate is None:
                        continue
                    index_entry, source_item = candidate
                    resolved_hits.append((index_entry, similarity))
                    source_items[index_entry.target_id] = source_item
                matching_below_floor = any(
                    similarity < self._min_similarity for _entry_id, similarity in raw_hits
                )
            elif target_kind == "source_item":
                eligible_ids = [entry_id for entry_id, _similarity in raw_hits]
                try:
                    projections = self._storage.get_source_item_projections(eligible_ids)
                except NotImplementedError:
                    projections = None
                source_items = {}
                if isinstance(projections, dict):
                    for entry_id, similarity in raw_hits:
                        if entry_id not in projections:
                            logger.debug("Stale vector index entry %s; scheduling lazy removal", entry_id)
                            try:
                                index.remove(entry_id)
                            except KeyError:
                                pass
                            continue
                        projection = projections[entry_id]
                        if projection is None:
                            continue
                        index_entry, source_item = projection
                        resolved_hits.append((index_entry, similarity))
                        source_items[index_entry.target_id] = source_item
                else:
                    index_entries = self._storage.get_index_entries([entry_id for entry_id, _similarity in raw_hits])
                    if not isinstance(index_entries, dict):
                        index_entries = {}
                    for entry_id, similarity in raw_hits:
                        index_entry = index_entries.get(entry_id)
                        if index_entry is None:
                            try:
                                index_entry = self._storage.get_index_entry(entry_id)
                            except KeyError:
                                try:
                                    index.remove(entry_id)
                                except KeyError:
                                    pass
                                continue
                        resolved_hits.append((index_entry, similarity))
                    source_items = self._storage.get_source_items([entry.target_id for entry, similarity in resolved_hits if similarity >= self._min_similarity])
                    if not isinstance(source_items, dict):
                        source_items = {}
                matching_below_floor = any(similarity < self._min_similarity for _entry_id, similarity in raw_hits)
            else:
                index_entries = self._storage.get_index_entries([entry_id for entry_id, _similarity in raw_hits])
                if not isinstance(index_entries, dict):
                    index_entries = {}
                for entry_id, similarity in raw_hits:
                    index_entry = index_entries.get(entry_id)
                    if index_entry is None:
                        try:
                            index_entry = self._storage.get_index_entry(entry_id)
                        except KeyError:
                            logger.debug("Stale vector index entry %s; scheduling lazy removal", entry_id)
                            try:
                                index.remove(entry_id)
                            except KeyError:
                                pass
                            continue
                    resolved_hits.append((index_entry, similarity))
                source_items = self._storage.get_source_items(
                    [
                        index_entry.target_id
                        for index_entry, _similarity in resolved_hits
                        if index_entry.target_kind == "source_item" and _similarity >= self._min_similarity
                    ]
                )
                if not isinstance(source_items, dict):
                    source_items = {}
                matching_below_floor = any(
                    target_kind is not None
                    and index_entry.target_kind == target_kind
                    and similarity < self._min_similarity
                    for index_entry, similarity in resolved_hits
                )
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

                if index_entry.target_kind == "source_item" and index_entry.target_id not in source_items:
                    continue
                get_source_item = source_items.get
                # Apply min_similarity threshold
                if similarity < self._min_similarity:
                    continue

                # Apply filters (lifecycle check for memory_objects + field matching)
                if not matches_filters(
                    self._storage.get_memory_object,
                    get_source_item,
                    self._storage.get_evidence_for_memory_object,
                    index_entry.target_kind, index_entry.target_id, filters,
                ):
                    continue

                hits_before_visibility += 1

                # Apply visibility using new is_visible()
                candidate_visibility, candidate_container_ref, candidate_actor_ref = target_visibility_and_container(
                    get_source_item, self._storage.get_memory_object,
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
                elif index_entry.target_kind == "source_item" and target_kind == "source_item":
                    pending_source_hits.append((index_entry, score, trace_hit))
                elif index_entry.target_kind == "source_item":
                    try:
                        source_item = get_source_item(index_entry.target_id)
                    except KeyError:
                        logger.debug("Skipping deleted source_item %s during hydration", index_entry.target_id)
                        continue
                    results.append(
                        QueryResultItem(
                            result_kind="source_hit",
                            source_item_id=source_item.id,
                            source_type=source_item.source_type,
                            source_id=source_item.source_id,
                            excerpt=build_excerpt(source_item.content, query=text),
                            source_content_fingerprint=build_source_content_fingerprint(source_item.content),
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
                            work_refs=work_refs_from_metadata(source_item.metadata),
                        )
                    )
                else:
                    continue

                if include_trace:
                    selected_trace_hits.append(trace_hit)

                if len(results) + len(pending_source_hits) >= limit:
                    break

            if len(results) + len(pending_source_hits) >= limit or matching_below_floor:
                break
        if target_kind == "source_item" and pending_source_hits:
            emitted_source_ids = [entry.target_id for entry, _score, _trace in pending_source_hits]
            revalidated = self._storage.get_source_items(emitted_source_ids)
            results = []
            valid_source_ids: set[str] = set()
            for index_entry, score, _trace in pending_source_hits:
                source_item = revalidated.get(index_entry.target_id)
                if (
                    source_item is None
                    or source_item.forgotten
                    or not matches_filters(
                        self._storage.get_memory_object,
                        revalidated.get,
                        self._storage.get_evidence_for_memory_object,
                        "source_item",
                        index_entry.target_id,
                        filters,
                    )
                ):
                    continue
                candidate_visibility, candidate_container_ref, candidate_actor_ref = target_visibility_and_container(
                    revalidated.get,
                    self._storage.get_memory_object,
                    "source_item",
                    index_entry.target_id,
                )
                if not is_visible(
                    candidate_visibility,
                    candidate_container_ref,
                    query_container_ref,
                    candidate_actor_ref,
                    query_visibility=visibility,
                    query_actor_ref=query_actor_ref,
                ):
                    continue
                valid_source_ids.add(source_item.id)
                results.append(
                    QueryResultItem(
                        result_kind="source_hit",
                        source_item_id=source_item.id,
                        source_type=source_item.source_type,
                        source_id=source_item.source_id,
                        excerpt=build_excerpt(source_item.content, query=text),
                        source_content_fingerprint=build_source_content_fingerprint(source_item.content),
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
                        work_refs=work_refs_from_metadata(source_item.metadata),
                    )
                )
            selected_trace_hits = [
                trace for (entry, _score, trace) in pending_source_hits if entry.target_id in valid_source_ids
            ]
        else:
            emitted_source_ids = [
                item.source_item_id for item in results if item.result_kind == "source_hit"
            ]
            if emitted_source_ids:
                revalidated = self._storage.get_source_items(emitted_source_ids)
                dropped = {
                    source_id
                    for source_id in emitted_source_ids
                    if source_id not in revalidated or revalidated[source_id].forgotten
                }
                if dropped:
                    results = [
                        item
                        for item in results
                        if item.result_kind != "source_hit" or item.source_item_id not in dropped
                    ]
                    selected_trace_hits = [
                        hit
                        for hit in selected_trace_hits
                        if not (hit.target_kind == "source_item" and hit.target_id in dropped)
                    ]
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
