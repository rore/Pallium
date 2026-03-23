from __future__ import annotations

import re

from core.models import (
    QueryFilters,
    QueryResultItem,
    QueryTrace,
    RetrievalStageTrace,
)
from core.visibility import QueryVisibilityTrace, VisibilityExclusion, is_visible, visibility_label
from retrieval.base import RetrievalProvider, RetrievalQueryResult
from retrieval.common import build_evidence, build_excerpt, build_trace_hit
from storage.base import StorageProvider


TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
LEXICAL_STAGE_NAME = "lexical"


def _tokenize(text: str) -> list[str]:
    tokens = TOKEN_PATTERN.findall(text.lower())
    expanded: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        for variant in _token_variants(token):
            if variant in seen:
                continue
            seen.add(variant)
            expanded.append(variant)
    return expanded


def _token_variants(token: str) -> tuple[str, ...]:
    variants = [token]
    if len(token) > 4 and token.endswith("ies"):
        variants.append(token[:-3] + "y")
    elif len(token) > 5 and token.endswith("es") and not token.endswith(("ses", "xes", "zes")):
        variants.append(token[:-2])
    elif len(token) > 4 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        variants.append(token[:-1])
    return tuple(dict.fromkeys(variants))


class LexicalRetrievalProvider(RetrievalProvider):
    def __init__(self, storage: StorageProvider) -> None:
        self._storage = storage

    def query(
        self,
        text: str,
        limit: int,
        filters: QueryFilters | None = None,
        *,
        container_visibility: str | None = None,
        query_container_ref: str | None = None,
        include_trace: bool = False,
        require_visibility: bool = False,
    ) -> RetrievalQueryResult:
        tokens = sorted(set(_tokenize(text)))
        if require_visibility and query_container_ref is None and container_visibility != "public":
            trace = None
            if include_trace:
                trace = QueryTrace(
                    query_text=text,
                    query_tokens=tuple(tokens),
                    limit=limit,
                    filters=filters,
                    stages=tuple(),
                    visibility=QueryVisibilityTrace(
                        query_container_visibility=container_visibility,
                        query_container_ref=query_container_ref,
                        fail_closed_reason="retrieval_visibility_context_required",
                    ),
                )
            return RetrievalQueryResult(results=[], trace=trace)
        if not tokens:
            trace = None
            if include_trace:
                trace = QueryTrace(
                    query_text=text,
                    query_tokens=tuple(),
                    limit=limit,
                    filters=filters,
                    stages=tuple(),
                    visibility=(
                        QueryVisibilityTrace(
                            query_container_visibility=container_visibility,
                            query_container_ref=query_container_ref,
                        )
                        if container_visibility is not None or query_container_ref is not None
                        else None
                    ),
                )
            return RetrievalQueryResult(results=[], trace=trace)

        search_result = self._storage.search_index_entries(
            tokens=tokens,
            limit=limit * 4,
            filters=filters,
            query_container_ref=query_container_ref,
            include_visibility_trace=include_trace,
        )
        hits = search_result.hits
        results: list[QueryResultItem] = []
        selected_hits: list[RetrievalTraceHit] = []
        seen: set[tuple[str, str]] = set()

        for hit in hits:
            key = (hit.target_kind, hit.target_id)
            if key in seen:
                continue
            seen.add(key)

            if hit.target_kind == "memory_object":
                memory_object = self._storage.get_memory_object(hit.target_id)
                evidence = self._storage.get_evidence_for_memory_object(hit.target_id)
                results.append(
                    QueryResultItem(
                        result_kind="memory_hit",
                        memory_object_id=memory_object.id,
                        type=memory_object.type,
                        payload=memory_object.payload,
                        envelope=memory_object.envelope,
                        score=hit.score,
                        evidence=evidence,
                        container_visibility=memory_object.container_visibility,
                    )
                )
            elif hit.target_kind == "source_item":
                source_item = self._storage.get_source_item(hit.target_id)
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
                        score=hit.score,
                        evidence=[build_evidence(source_item)],
                        container_visibility=source_item.container_visibility,
                    )
                )
            else:
                continue

            if include_trace:
                selected_hits.append(build_trace_hit(hit))

            if len(results) >= limit:
                break

        trace = None
        if include_trace:
            trace = QueryTrace(
                query_text=text,
                query_tokens=tuple(tokens),
                limit=limit,
                filters=filters,
                stages=(
                    RetrievalStageTrace(
                        stage_name=LEXICAL_STAGE_NAME,
                        candidate_hits_considered=len(hits),
                        candidate_hits=tuple(build_trace_hit(hit) for hit in hits),
                        selected_hits=tuple(selected_hits),
                        candidate_hits_before_visibility=search_result.total_hits_before_visibility,
                        candidate_hits_after_visibility=search_result.total_hits_after_visibility,
                    ),
                ),
                visibility=(
                    QueryVisibilityTrace(
                        query_container_visibility=container_visibility,
                        query_container_ref=query_container_ref,
                        excluded_candidates=search_result.visibility_exclusions,
                    )
                    if container_visibility is not None or query_container_ref is not None or search_result.visibility_exclusions
                    else None
                ),
            )

        return RetrievalQueryResult(results=results, trace=trace)
