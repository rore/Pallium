"""Tests that tentative/hedged statements do not produce constraint_memory,
while definitive statements do.

This validates both the stub provider's tentative-vs-definitive distinction
and the extraction-to-memory pipeline in AgentConversationMemoryPlugin.
"""
from __future__ import annotations

from datetime import datetime, timezone

from core.models import SourceItem
from providers.llm.base import LLMJsonResponse
from semantic.agent_conversation_memory import AgentConversationMemoryPlugin
from tests.tiered_memory_stub_providers import TieredMemorySemanticProvider


def _make_user_item(content: str, source_id: str) -> SourceItem:
    return SourceItem(
        source_type="chat_message",
        source_id=source_id,
        content_type="text/plain",
        content=content,
        artifact_kind="message",
        role="user",
        container_ref="chat:constraint-eval",
        thread_ref="chat:constraint-eval:t1",
        occurred_at=datetime(2026, 3, 23, 10, 0, tzinfo=timezone.utc),
        visibility="private",
    )


def _extract(plugin: AgentConversationMemoryPlugin, content: str, source_id: str) -> list:
    result = plugin.process_item(_make_user_item(content, source_id))
    return [m for m in result.memory_objects if m.type == "constraint_memory"]


class TestTentativeStatementsDoNotProduceConstraintMemory:
    """Hedged/tentative statements must NOT create constraint_memory."""

    def setup_method(self) -> None:
        self.plugin = AgentConversationMemoryPlugin(
            provider=TieredMemorySemanticProvider(),
            prompt_variant="strict_typed_memory_v5_compact_examples",
        )

    def test_i_think_python_service(self) -> None:
        constraints = _extract(self.plugin, "i think this will be a python service", "tentative-1")
        assert constraints == [], "Tentative 'I think' should not create constraint_memory"

    def test_maybe_latency(self) -> None:
        constraints = _extract(self.plugin, "maybe we should keep it under 100ms latency", "tentative-2")
        assert constraints == [], "Hedged 'maybe' should not create constraint_memory"

    def test_leaning_towards(self) -> None:
        constraints = _extract(self.plugin, "i'm leaning towards using postgres but not sure yet", "tentative-3")
        assert constraints == [], "Hedged 'leaning towards' + 'not sure' should not create constraint_memory"

    def test_id_prefer(self) -> None:
        constraints = _extract(self.plugin, "I'd prefer to keep it simple", "tentative-4")
        assert constraints == [], "Hedged 'I'd prefer' should not create constraint_memory"

    def test_could_probably(self) -> None:
        constraints = _extract(self.plugin, "We could probably use Redis for caching", "tentative-5")
        assert constraints == [], "Hedged 'could probably' should not create constraint_memory"

    def test_was_thinking_maybe(self) -> None:
        constraints = _extract(self.plugin, "I was thinking maybe FastAPI", "tentative-6")
        assert constraints == [], "Hedged 'was thinking maybe' should not create constraint_memory"

    def test_mixed_tentative_and_definitive_rejected(self) -> None:
        """When tentative hedging wraps a definitive marker, the tentative wins."""
        constraints = _extract(self.plugin, "I think we must avoid cloud services", "tentative-7")
        assert constraints == [], "Mixed tentative+definitive should not create constraint_memory"


class TestDefinitiveStatementsProduceConstraintMemory:
    """Definitive constraint statements MUST create constraint_memory."""

    def setup_method(self) -> None:
        self.plugin = AgentConversationMemoryPlugin(
            provider=TieredMemorySemanticProvider(),
            prompt_variant="strict_typed_memory_v5_compact_examples",
        )

    def test_not_going_saas(self) -> None:
        constraints = _extract(self.plugin, "not going saas or anything, like a sidecar", "definitive-1")
        assert len(constraints) == 1, "Definitive 'not going' should create constraint_memory"

    def test_has_to_run_linux(self) -> None:
        constraints = _extract(self.plugin, "it has to run on linux, that's non-negotiable", "definitive-2")
        assert len(constraints) == 1, "Definitive 'has to' + 'non-negotiable' should create constraint_memory"

    def test_absolutely_cannot(self) -> None:
        constraints = _extract(self.plugin, "we absolutely cannot use any cloud services", "definitive-3")
        assert len(constraints) == 1, "Definitive 'absolutely cannot' should create constraint_memory"

    def test_must_be_rest(self) -> None:
        constraints = _extract(self.plugin, "The API must be REST, not GraphQL", "definitive-4")
        assert len(constraints) == 1, "Definitive 'must be' should create constraint_memory"

    def test_no_external_deps(self) -> None:
        constraints = _extract(self.plugin, "No external dependencies allowed", "definitive-5")
        assert len(constraints) == 1, "Definitive 'No ... allowed' should create constraint_memory"

    def test_must_be_encrypted(self) -> None:
        constraints = _extract(self.plugin, "Security is critical — all data must be encrypted at rest", "definitive-6")
        assert len(constraints) == 1, "Definitive 'must be encrypted' should create constraint_memory"
