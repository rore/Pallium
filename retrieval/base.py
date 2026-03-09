from __future__ import annotations

from abc import ABC, abstractmethod

from core.models import QueryResultItem


class RetrievalProvider(ABC):
    @abstractmethod
    def query(self, text: str, limit: int) -> list[QueryResultItem]:
        raise NotImplementedError
