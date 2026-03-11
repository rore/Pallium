from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from core.models import QueryFilters, QueryResultItem, QueryTrace


@dataclass(frozen=True)
class RetrievalQueryResult:
    results: list[QueryResultItem]
    trace: QueryTrace | None = None


class RetrievalProvider(ABC):
    @abstractmethod
    def query(
        self,
        text: str,
        limit: int,
        filters: QueryFilters | None = None,
        *,
        include_trace: bool = False,
    ) -> RetrievalQueryResult:
        raise NotImplementedError
