from __future__ import annotations

from abc import ABC, abstractmethod

from capabilities.consolidation import ConsolidationGroup, ConsolidationPolicy
from capabilities.thread_aggregation import ThreadAggregate
from core.contracts import ProcessResult
from core.models import MemoryObject, SourceItem


class SemanticPlugin(ABC):
    name: str

    @property
    def requires_visibility_context(self) -> bool:
        return False

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


class ConsolidationSemanticPlugin(SemanticPlugin):
    @property
    @abstractmethod
    def consolidation_policy(self) -> ConsolidationPolicy | None:
        raise NotImplementedError

    @abstractmethod
    def supports_consolidation(self, memory_object: MemoryObject) -> bool:
        raise NotImplementedError

    @abstractmethod
    def build_consolidated_memory(self, group: ConsolidationGroup) -> ProcessResult:
        raise NotImplementedError