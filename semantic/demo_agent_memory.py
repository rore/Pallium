from __future__ import annotations

from core.contracts import ProcessResult
from core.models import SourceItem
from semantic.base import SemanticPlugin
from semantic.common import build_process_result, deterministic_extraction


class DemoAgentMemoryPlugin(SemanticPlugin):
    name = "demo_agent_memory"

    def process_item(self, source_item: SourceItem) -> ProcessResult:
        extraction = deterministic_extraction(source_item)
        return build_process_result(source_item, extraction, schema_prefix="demo")
