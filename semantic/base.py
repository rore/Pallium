from __future__ import annotations

from abc import ABC, abstractmethod

from capabilities.consolidation import ConsolidationGroup, ConsolidationPolicy
from capabilities.thread_aggregation import ThreadAggregate
from core.contracts import MemoryRetentionPolicy, ProcessResult
from core.models import MemoryObject, SourceItem


class SemanticPlugin(ABC):
    name: str

    @property
    def requires_visibility_context(self) -> bool:
        return False

    def source_item_embedding_text(self, source_item: SourceItem) -> str | None:
        """Return embedding text for this source item, or None to skip.
        Default: no source item embedding. Package overrides to select."""
        return None

    @property
    def memory_retention_policy(self) -> MemoryRetentionPolicy | None:
        """Return retention classification for this package's memory types.
        Default: None (no package-specific retention policy declared)."""
        return None

    @abstractmethod
    def process_item(self, source_item: SourceItem) -> ProcessResult:
        raise NotImplementedError


class ThreadAggregationSemanticPlugin(SemanticPlugin):
    @property
    @abstractmethod
    def thread_summary_schema_id(self) -> str:
        raise NotImplementedError

    @property
    def thread_conclusion_types(self) -> frozenset[str]:
        """Memory types that represent thread conclusions.
        Core uses this to filter memory objects before passing them to
        build_thread_summary(). Default: empty (pass all active memory)."""
        return frozenset()

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