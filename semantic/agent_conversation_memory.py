from __future__ import annotations

from core.contracts import ProcessResult
from core.models import SourceItem
from providers.llm.base import LLMProvider
from semantic.base import SemanticPlugin
from semantic.llm_agent_memory import LLMAgentMemoryPlugin


class AgentConversationMemoryPlugin(SemanticPlugin):
    name = "agent_conversation_memory"

    def __init__(self, provider: LLMProvider, *, prompt_variant: str) -> None:
        self._delegate = LLMAgentMemoryPlugin(provider=provider, prompt_variant=prompt_variant)

    @property
    def prompt_variant(self) -> str:
        return self._delegate.prompt_variant

    def process_item(self, source_item: SourceItem) -> ProcessResult:
        return self._delegate.process_item(source_item)
