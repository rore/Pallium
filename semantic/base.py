from __future__ import annotations

from abc import ABC, abstractmethod

from capabilities.thread_aggregation import ThreadAggregate
from core.contracts import ProcessResult
from core.models import MemoryObject, SourceItem


class SemanticPlugin(ABC):
    name: str

    @abstractmethod
    def process_item(self, source_item: SourceItem) -> ProcessResult:
        raise NotImplementedError


class ThreadAggregationSemanticPlugin(SemanticPlugin):
    @property
    @abstractmethod
    def thread_summary_schema_id(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def supports_thread_aggregation(self, source_item: SourceItem) -> bool:
        raise NotImplementedError

    @abstractmethod
    def build_thread_summary(self, aggregate: ThreadAggregate, conclusions: list[MemoryObject]) -> ProcessResult:
        raise NotImplementedError
