from __future__ import annotations

from abc import ABC, abstractmethod

from core.models import QueryFilters, QueryResultItem


class RetrievalProvider(ABC):
    @abstractmethod
    def query(self, text: str, limit: int, filters: QueryFilters | None = None) -> list[QueryResultItem]:
        raise NotImplementedError
