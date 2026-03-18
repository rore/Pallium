from __future__ import annotations

import re
from datetime import timezone

from core.models import (
    EvidenceReference,
    QueryFilters,
    QueryResultItem,
    QueryTrace,
    RetrievalStageTrace,
    RetrievalTraceHit,
    SourceItem,
)
from core.visibility import QueryVisibilityTrace, VisibilityContext, expand_visibility_context
from retrieval.base import RetrievalProvider, RetrievalQueryResult
from storage.base import IndexSearchHit, StorageProvider


TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
MAX_EXCERPT_LENGTH = 160
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


def _build_excerpt(text: str, *, max_length: int = MAX_EXCERPT_LENGTH) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 3].rstrip() + "..."


def _build_evidence(source_item: SourceItem) -> EvidenceReference:
    occurred_at = source_item.occurred_at
    if occurred_at is not None and occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=timezone.utc)
    return EvidenceReference(
        source_item_id=source_item.id,
        source_type=source_item.source_type,
        source_id=source_item.source_id,
        occurred_at=occurred_at,
        actor_ref=source_item.actor_ref,
        role=source_item.role,
        container_ref=source_item.container_ref,
        thread_ref=source_item.thread_ref,
        session_ref=source_item.session_ref,
        source_ref=source_item.source_ref,
        artifact_kind=source_item.artifact_kind,
        visibility_context=source_item.visibility_context,
    )


def _build_trace_hit(hit: IndexSearchHit) -> RetrievalTraceHit:
    return RetrievalTraceHit(
        target_kind=hit.target_kind,
        target_id=hit.target_id,
        index_entry_id=hit.index_entry_id,
        index_type=hit.index_type,
        text_view_name=hit.text_view_name,
        score=hit.score,
        matched_tokens=tuple(hit.matched_tokens),
        provider_name=hit.provider_name,
        provider_version=hit.provider_version,
    )


class LexicalRetrievalProvider(RetrievalProvider):
    def __init__(self, storage: StorageProvider) -> None:
        self._storage = storage

    def query(
        self,
        text: str,
        limit: int,
        filters: QueryFilters | None = None,
        *,
        visibility_context: VisibilityContext | None = None,
        include_trace: bool = False,
        require_visibility: bool = False,
    ) -> RetrievalQueryResult:
        tokens = sorted(set(_tokenize(text)))
        if require_visibility and visibility_context is None:
            trace = None
            if include_trace:
                trace = QueryTrace(
                    query_text=text,
                    query_tokens=tuple(tokens),
                    limit=limit,
                    filters=filters,
                    stages=tuple(),
                    visibility=QueryVisibilityTrace(
                        query_visibility_context=None,
                        expanded_visibility_contexts=tuple(),
                        fail_closed_reason="retrieval_visibility_context_required",
                    ),
                )
            return RetrievalQueryResult(results=[], trace=trace)
        visible_contexts = expand_visibility_context(visibility_context) if visibility_context is not None else None
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
                            query_visibility_context=visibility_context,
                            expanded_visibility_contexts=visible_contexts or tuple(),
                        )
                        if visibility_context is not None
                        else None
                    ),
                )
            return RetrievalQueryResult(results=[], trace=trace)

        search_result = self._storage.search_index_entries(
            tokens=tokens,
            limit=limit * 4,
            filters=filters,
            visibility_contexts=visible_contexts,
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
                        visibility_context=memory_object.visibility_context,
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
                        excerpt=_build_excerpt(source_item.content),
                        occurred_at=source_item.occurred_at,
                        actor_ref=source_item.actor_ref,
                        role=source_item.role,
                        container_ref=source_item.container_ref,
                        thread_ref=source_item.thread_ref,
                        session_ref=source_item.session_ref,
                        source_ref=source_item.source_ref,
                        artifact_kind=source_item.artifact_kind,
                        score=hit.score,
                        evidence=[_build_evidence(source_item)],
                        visibility_context=source_item.visibility_context,
                    )
                )
            else:
                continue

            if include_trace:
                selected_hits.append(_build_trace_hit(hit))

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
                        candidate_hits=tuple(_build_trace_hit(hit) for hit in hits),
                        selected_hits=tuple(selected_hits),
                        candidate_hits_before_visibility=search_result.total_hits_before_visibility,
                        candidate_hits_after_visibility=search_result.total_hits_after_visibility,
                    ),
                ),
                visibility=(
                    QueryVisibilityTrace(
                        query_visibility_context=visibility_context,
                        expanded_visibility_contexts=visible_contexts or tuple(),
                        excluded_candidates=search_result.visibility_exclusions,
                    )
                    if visibility_context is not None or search_result.visibility_exclusions
                    else None
                ),
            )

        return RetrievalQueryResult(results=results, trace=trace)
