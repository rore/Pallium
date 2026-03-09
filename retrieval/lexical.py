from __future__ import annotations

import re

from core.models import EvidenceReference, QueryResultItem
from retrieval.base import RetrievalProvider
from storage.base import StorageProvider


TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text.lower())


class LexicalRetrievalProvider(RetrievalProvider):
    def __init__(self, storage: StorageProvider) -> None:
        self._storage = storage

    def query(self, text: str, limit: int) -> list[QueryResultItem]:
        tokens = sorted(set(_tokenize(text)))
        if not tokens:
            return []
        hits = self._storage.search_index_entries(tokens=tokens, limit=limit * 4)
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
                        content=source_item.content,
                        metadata=source_item.metadata or {},
                        score=hit.score,
                        evidence=[
                            EvidenceReference(
                                source_item_id=source_item.id,
                                source_type=source_item.source_type,
                                source_id=source_item.source_id,
                            )
                        ],
                    )
                )

            if len(results) >= limit:
                break

        return results
