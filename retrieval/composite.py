from __future__ import annotations

from dataclasses import replace

from core.models import (
    FusionStageTrace,
    FusionTraceHit,
    QueryFilters,
    QueryResultItem,
    QueryTrace,
)
from retrieval.base import RetrievalProvider, RetrievalQueryResult
from retrieval.vector import VectorRetrievalProvider

RRF_K = 60
RRF_SCORE_SCALE = 600
RRF_LEXICAL_WEIGHT = 1.5
RRF_VECTOR_WEIGHT = 1.0


class CompositeRetrievalProvider(RetrievalProvider):
    """Retrieval provider that fuses lexical and vector results using Reciprocal Rank Fusion."""

    def __init__(
        self,
        lexical: RetrievalProvider,
        vector: VectorRetrievalProvider | None = None,
    ) -> None:
        self._lexical = lexical
        self._vector = vector

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
    ) -> RetrievalQueryResult:
        lexical_result = self._lexical.query(
            text,
            limit,
            filters,
            visibility=visibility,
            query_container_ref=query_container_ref,
            include_trace=include_trace,
            require_visibility=require_visibility,
            query_actor_ref=query_actor_ref,
        )
        if self._vector is None:
            return lexical_result
        vector_result = self._vector.query(
            text,
            limit,
            filters,
            visibility=visibility,
            query_container_ref=query_container_ref,
            include_trace=include_trace,
            require_visibility=require_visibility,
            query_actor_ref=query_actor_ref,
        )
        return self._rrf_merge(lexical_result, vector_result, limit, include_trace=include_trace)

    def _rrf_merge(
        self,
        lexical_result: RetrievalQueryResult,
        vector_result: RetrievalQueryResult,
        limit: int,
        *,
        include_trace: bool = False,
    ) -> RetrievalQueryResult:
        # 1. Build rank maps (1-indexed)
        lexical_ranks: dict[str | None, int] = {}
        for rank, item in enumerate(lexical_result.results, start=1):
            if item.result_id is not None:
                lexical_ranks[item.result_id] = rank

        vector_ranks: dict[str | None, int] = {}
        for rank, item in enumerate(vector_result.results, start=1):
            if item.result_id is not None:
                vector_ranks[item.result_id] = rank

        # 2. Collect all unique result_ids
        all_ids: list[str] = []
        seen_ids: set[str] = set()
        for item in lexical_result.results:
            if item.result_id is not None and item.result_id not in seen_ids:
                all_ids.append(item.result_id)
                seen_ids.add(item.result_id)
        for item in vector_result.results:
            if item.result_id is not None and item.result_id not in seen_ids:
                all_ids.append(item.result_id)
                seen_ids.add(item.result_id)

        # Build item lookup: prefer lexical version for dedup
        lexical_items: dict[str, QueryResultItem] = {}
        for item in lexical_result.results:
            if item.result_id is not None:
                lexical_items[item.result_id] = item

        vector_items: dict[str, QueryResultItem] = {}
        for item in vector_result.results:
            if item.result_id is not None:
                vector_items[item.result_id] = item

        # 3. Compute RRF scores and build fused items
        scored: list[tuple[float, str]] = []
        for result_id in all_ids:
            rrf_score = 0.0
            if result_id in lexical_ranks:
                rrf_score += RRF_LEXICAL_WEIGHT / (RRF_K + lexical_ranks[result_id])
            if result_id in vector_ranks:
                rrf_score += RRF_VECTOR_WEIGHT / (RRF_K + vector_ranks[result_id])
            scored.append((rrf_score, result_id))

        # 4. Sort by RRF score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        # 5. Build final results
        fused_results: list[QueryResultItem] = []
        fusion_trace_hits: list[FusionTraceHit] = []
        both_count = 0

        for rrf_rank, (rrf_score, result_id) in enumerate(scored, start=1):
            in_lexical = result_id in lexical_items
            in_vector = result_id in vector_items

            if in_lexical and in_vector:
                source = "both"
                item = lexical_items[result_id]
                both_count += 1
            elif in_lexical:
                source = "lexical"
                item = lexical_items[result_id]
            else:
                source = "vector"
                item = vector_items[result_id]

            fused_score = int(rrf_score * RRF_SCORE_SCALE)
            lexical_raw_score = lexical_items[result_id].score if result_id in lexical_items else None
            vector_raw_score = vector_items[result_id].score if result_id in vector_items else None
            fused_item = replace(item, retrieval_source=source, score=fused_score, lexical_score=lexical_raw_score, vector_score=vector_raw_score)
            fused_results.append(fused_item)

            if include_trace:
                fusion_trace_hits.append(
                    FusionTraceHit(
                        result_id=result_id,
                        rrf_score=rrf_score,
                        rrf_rank=rrf_rank,
                        fused_score=fused_score,
                        lexical_rank=lexical_ranks.get(result_id),
                        vector_rank=vector_ranks.get(result_id),
                        retrieval_source=source,
                    )
                )

            if len(fused_results) >= limit:
                break

        # 6. Merge traces
        all_stages: list = []
        if lexical_result.trace is not None:
            all_stages.extend(lexical_result.trace.stages)
        if vector_result.trace is not None:
            all_stages.extend(vector_result.trace.stages)

        fusion_trace = FusionStageTrace(
            k=RRF_K,
            rrf_score_scale=RRF_SCORE_SCALE,
            lexical_candidate_count=len(lexical_result.results),
            vector_candidate_count=len(vector_result.results),
            fused_candidate_count=len(scored),
            both_sources_count=both_count,
            selected_count=len(fused_results),
            lexical_weight=RRF_LEXICAL_WEIGHT,
            vector_weight=RRF_VECTOR_WEIGHT,
            hits=tuple(fusion_trace_hits),
        ) if include_trace else None

        # Use lexical trace as base when available, else vector
        base_trace = lexical_result.trace or vector_result.trace
        if base_trace is not None:
            trace = replace(
                base_trace,
                stages=tuple(all_stages),
                fusion_trace=fusion_trace,
            )
        elif include_trace:
            trace = QueryTrace(
                query_text="",
                query_tokens=(),
                limit=limit,
                filters=None,
                stages=tuple(all_stages),
                fusion_trace=fusion_trace,
            )
        else:
            trace = None

        return RetrievalQueryResult(results=fused_results, trace=trace)
