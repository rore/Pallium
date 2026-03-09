from __future__ import annotations

import re
from datetime import timezone

from core.models import EvidenceReference, QueryFilters, QueryResultItem, SourceItem
from retrieval.base import RetrievalProvider
from storage.base import StorageProvider


TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
MAX_EXCERPT_LENGTH = 160


def _tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text.lower())


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
    )


class LexicalRetrievalProvider(RetrievalProvider):
    def __init__(self, storage: StorageProvider) -> None:
        self._storage = storage

    def query(self, text: str, limit: int, filters: QueryFilters | None = None) -> list[QueryResultItem]:
        tokens = sorted(set(_tokenize(text)))
        if not tokens:
            return []
        hits = self._storage.search_index_entries(tokens=tokens, limit=limit * 4, filters=filters)
        results: list[QueryResultItem] = []
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
                        score=hit.score,
                        evidence=evidence,
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
                    )
                )

            if len(results) >= limit:
                break

        return results
