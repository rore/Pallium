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

    @property
    def parallel_processing(self) -> bool:
        """Whether this package should process every ingested item alongside the primary package.
        Default: False (only processes items assigned to this package).
        Packages that return True are added to the processing queue for all items."""
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

    @property
    def rebuild_supersedes_prior(self) -> bool:
        """Whether thread rebuild should supersede all prior memory objects of
        the same (type, schema_id) key.

        Default: True — the existing behavior where each rebuild fully replaces
        the prior memory set. Plugins returning False opt into additive mode:
        new memory objects accumulate alongside existing ones.
        """
        return True

    @property
    def non_superseding_types(self) -> frozenset[str]:
        """Memory types that should accumulate across rebuilds rather than supersede.

        When rebuild_supersedes_prior is True, types listed here are exempt from
        supersession — each rebuild window's instances accumulate alongside prior
        ones. This enables incremental extraction of decisions/investigations
        across windowed thread rebuilds.

        Default: empty (all types supersede as before).
        """
        return frozenset()

    @property
    def supports_container_aggregation(self) -> bool:
        """Whether this plugin should receive container-level aggregation scopes.

        Container-level scopes aggregate top-level messages across all threads
        in a container, enabling extraction from standalone messages that fall
        below the per-thread item minimum.

        Default: False — only thread-level scopes are created.
        """
        return False

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