from __future__ import annotations

from abc import ABC, abstractmethod

from core.contracts import ProcessResult
from core.models import SourceItem


class SemanticPlugin(ABC):
    name: str

    @abstractmethod
    def process_item(self, source_item: SourceItem) -> ProcessResult:
        raise NotImplementedError
