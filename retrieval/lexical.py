from __future__ import annotations

import re

from core.models import QueryResultItem
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
        hits = self._storage.search_index_entries(tokens=tokens, limit=limit)
        results: list[QueryResultItem] = []
        for hit in hits:
            memory_object = self._storage.get_memory_object(hit.target_id)
            evidence = self._storage.get_evidence_for_memory_object(hit.target_id)
            results.append(
                QueryResultItem(
                    memory_object_id=memory_object.id,
                    type=memory_object.type,
                    payload=memory_object.payload,
                    score=hit.score,
                    evidence=evidence,
                )
            )
        return results
