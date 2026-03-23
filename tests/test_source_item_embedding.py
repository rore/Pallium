from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.contracts import ProcessResult
from core.indexing import VECTOR_INDEX_TYPE
from core.models import IndexEntry, SourceItem
from core.service import PalliumService
from providers.embedding.base import EmbeddingProvider
from retrieval.lexical import LexicalRetrievalProvider
from semantic.agent_conversation_memory_embedding import source_item_embedding_text
from semantic.base import SemanticPlugin
from semantic.demo_agent_memory import DemoAgentMemoryPlugin
from storage.sqlite import SQLiteStorageProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_source_item(
    *,
    artifact_kind: str = "message",
    content: str = "This is a user message that is definitely over forty characters long.",
    source_id: str = "src-1",
) -> SourceItem:
    return SourceItem(
        source_type="chat_message",
        source_id=source_id,
        content_type="text/plain",
        content=content,
        artifact_kind=artifact_kind,
    )


class FakeEmbeddingProvider(EmbeddingProvider):
    """Returns a fixed vector for any input."""

    def __init__(self, dims: int = 4) -> None:
        self._dims = dims
        self.embed_calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.embed_calls.append(list(texts))
        return [[0.1] * self._dims for _ in texts]

    def dimensions(self) -> int:
        return self._dims

    def model_name(self) -> str:
        return "test-embed-model"


class FakeVectorIndex:
    """Minimal stand-in for VectorIndex."""

    def __init__(self) -> None:
        self.entries: dict[str, list[float]] = {}
        self.save_count = 0

    def add(self, entry_id: str, vector: list[float]) -> None:
        self.entries[entry_id] = vector

    def save(self) -> None:
        self.save_count += 1


class SelectiveEmbeddingPlugin(SemanticPlugin):
    """Plugin that selects 'message' and 'assistant_output' source items for embedding."""
    name = "selective_embedding"

    def source_item_embedding_text(self, source_item: SourceItem) -> str | None:
        from semantic.agent_conversation_memory_embedding import source_item_embedding_text
        return source_item_embedding_text(source_item)

    def process_item(self, source_item: SourceItem) -> ProcessResult:
        return ProcessResult(annotations=[], memory_objects=[], relations=[], index_entries=[])


class VectorProducingPlugin(SemanticPlugin):
    """Plugin that produces vector index entries from process_item, simulating
    memory objects that need embedding (like the production LLM plugin does)."""
    name = "vector_producing"

    def source_item_embedding_text(self, source_item: SourceItem) -> str | None:
        from semantic.agent_conversation_memory_embedding import source_item_embedding_text
        return source_item_embedding_text(source_item)

    def process_item(self, source_item: SourceItem) -> ProcessResult:
        from core.indexing import VECTOR_INDEX_TYPE, build_index_entry
        vector_entry = build_index_entry(
            target_kind="source_item",
            target_id=source_item.id,
            index_type=VECTOR_INDEX_TYPE,
            text_view="memory embedding text that is long enough for the minimum threshold",
            text_view_name="test_memory.embedding",
        )
        return ProcessResult(
            annotations=[], memory_objects=[], relations=[],
            index_entries=[vector_entry],
        )


class NoMemoryPlugin(SemanticPlugin):
    """Plugin whose process_item produces no memory objects but still supports embedding."""
    name = "no_memory"

    def source_item_embedding_text(self, source_item: SourceItem) -> str | None:
        from semantic.agent_conversation_memory_embedding import source_item_embedding_text
        return source_item_embedding_text(source_item)

    def process_item(self, source_item: SourceItem) -> ProcessResult:
        return ProcessResult(annotations=[], memory_objects=[], relations=[], index_entries=[])


def _build_service(
    test_db_url: str,
    *,
    plugins: dict[str, SemanticPlugin] | None = None,
    default_use_case: str = "demo_agent_memory",
    embedding_provider: EmbeddingProvider | None = None,
    vector_index: FakeVectorIndex | None = None,
) -> PalliumService:
    storage = SQLiteStorageProvider(test_db_url)
    retrieval = LexicalRetrievalProvider(storage)
    resolved_plugins: dict[str, SemanticPlugin] = {"demo_agent_memory": DemoAgentMemoryPlugin()}
    if plugins:
        resolved_plugins.update(plugins)
    return PalliumService(
        storage=storage,
        retrieval=retrieval,
        semantic_plugins=resolved_plugins,
        default_use_case=default_use_case,
        embedding_provider=embedding_provider,
        vector_index=vector_index,
    )


# ---------------------------------------------------------------------------
# source_item_embedding_text() function tests
# ---------------------------------------------------------------------------

class TestSourceItemEmbeddingTextFunction:
    def test_returns_content_for_message_with_50_chars(self):
        item = _make_source_item(
            artifact_kind="message",
            content="A" * 50,
        )
        result = source_item_embedding_text(item)
        assert result == "A" * 50

    def test_returns_content_for_assistant_output(self):
        item = _make_source_item(
            artifact_kind="assistant_output",
            content="This is an assistant output message that is long enough to pass the threshold",
        )
        result = source_item_embedding_text(item)
        assert result is not None
        assert "assistant output" in result

    def test_returns_none_for_tool_use_summary(self):
        item = _make_source_item(
            artifact_kind="tool_use_summary",
            content="Tool summary that is definitely over forty characters long.",
        )
        result = source_item_embedding_text(item)
        assert result is None

    def test_returns_none_for_short_content(self):
        item = _make_source_item(
            artifact_kind="message",
            content="Short msg",  # < 40 chars
        )
        result = source_item_embedding_text(item)
        assert result is None

    def test_returns_none_for_exactly_39_chars(self):
        item = _make_source_item(
            artifact_kind="message",
            content="A" * 39,
        )
        assert source_item_embedding_text(item) is None

    def test_returns_content_for_exactly_40_chars(self):
        item = _make_source_item(
            artifact_kind="message",
            content="A" * 40,
        )
        assert source_item_embedding_text(item) == "A" * 40


# ---------------------------------------------------------------------------
# Default SemanticPlugin.source_item_embedding_text() returns None
# ---------------------------------------------------------------------------

class TestDefaultPluginEmbeddingText:
    def test_default_returns_none(self):
        """DemoAgentMemoryPlugin inherits from SemanticPlugin and should return None by default."""
        plugin = DemoAgentMemoryPlugin()
        item = _make_source_item()
        assert plugin.source_item_embedding_text(item) is None


# ---------------------------------------------------------------------------
# AgentConversationMemoryPlugin.source_item_embedding_text() delegates
# ---------------------------------------------------------------------------

class TestAgentConversationMemoryPluginDelegation:
    def test_delegates_for_qualifying_item(self):
        """AgentConversationMemoryPlugin should delegate to the standalone function."""
        from semantic.agent_conversation_memory import AgentConversationMemoryPlugin

        provider = MagicMock()
        plugin = AgentConversationMemoryPlugin(
            provider=provider,
            prompt_variant="strict_typed_memory_v5_compact_examples",
        )
        item = _make_source_item(
            artifact_kind="message",
            content="This is a qualifying user message that exceeds forty characters",
        )
        result = plugin.source_item_embedding_text(item)
        assert result == item.content

    def test_returns_none_for_non_qualifying(self):
        from semantic.agent_conversation_memory import AgentConversationMemoryPlugin

        provider = MagicMock()
        plugin = AgentConversationMemoryPlugin(
            provider=provider,
            prompt_variant="strict_typed_memory_v5_compact_examples",
        )
        item = _make_source_item(artifact_kind="tool_use_summary")
        result = plugin.source_item_embedding_text(item)
        assert result is None


# ---------------------------------------------------------------------------
# Background processor creates vector entry for qualifying source items
# ---------------------------------------------------------------------------

class TestBackgroundProcessorCreatesVectorEntry:
    def test_creates_vector_entry_for_qualifying_item(self, test_db_url):
        embedding = FakeEmbeddingProvider()
        vector_idx = FakeVectorIndex()
        service = _build_service(
            test_db_url,
            plugins={"selective_embedding": SelectiveEmbeddingPlugin()},
            default_use_case="selective_embedding",
            embedding_provider=embedding,
            vector_index=vector_idx,
        )

        service.ingest_item(
            source_type="chat_message",
            source_id="embed-test-1",
            content_type="text/plain",
            content="This is a user message that is definitely over forty characters long.",
            metadata=None,
            use_case="selective_embedding",
            artifact_kind="message",
        )
        service.drain_processing_queue(worker_id="test")

        # Embedding provider should have been called for the source item
        assert len(embedding.embed_calls) >= 1
        # Vector index should have at least one entry
        assert len(vector_idx.entries) >= 1
        assert vector_idx.save_count >= 1

    def test_no_vector_entry_for_non_qualifying_item(self, test_db_url):
        embedding = FakeEmbeddingProvider()
        vector_idx = FakeVectorIndex()
        service = _build_service(
            test_db_url,
            plugins={"selective_embedding": SelectiveEmbeddingPlugin()},
            default_use_case="selective_embedding",
            embedding_provider=embedding,
            vector_index=vector_idx,
        )

        service.ingest_item(
            source_type="tool_summary",
            source_id="embed-test-2",
            content_type="text/plain",
            content="Tool use summary that should not be embedded even though it is long enough.",
            metadata=None,
            use_case="selective_embedding",
            artifact_kind="tool_use_summary",
        )
        service.drain_processing_queue(worker_id="test")

        # No source item embedding should be created (tool_use_summary is excluded)
        assert len(vector_idx.entries) == 0


# ---------------------------------------------------------------------------
# Source item vectorized even when plugin processing produces no memory
# ---------------------------------------------------------------------------

class TestSourceItemVectorizedWithNoMemory:
    def test_vector_entry_created_even_without_memory_output(self, test_db_url):
        embedding = FakeEmbeddingProvider()
        vector_idx = FakeVectorIndex()
        service = _build_service(
            test_db_url,
            plugins={"no_memory": NoMemoryPlugin()},
            default_use_case="no_memory",
            embedding_provider=embedding,
            vector_index=vector_idx,
        )

        service.ingest_item(
            source_type="chat_message",
            source_id="no-memory-1",
            content_type="text/plain",
            content="This user message should be vectorized even though no memory is produced.",
            metadata=None,
            use_case="no_memory",
            artifact_kind="message",
        )
        service.drain_processing_queue(worker_id="test")

        assert len(vector_idx.entries) >= 1
        assert len(embedding.embed_calls) >= 1


# ---------------------------------------------------------------------------
# Retry idempotency: repeated calls don't create duplicate entries
# ---------------------------------------------------------------------------

class TestRetryIdempotency:
    def test_repeated_processing_does_not_duplicate_vector_entry(self, test_db_url):
        storage = SQLiteStorageProvider(test_db_url)
        retrieval = LexicalRetrievalProvider(storage)
        embedding = FakeEmbeddingProvider()
        vector_idx = FakeVectorIndex()
        service = PalliumService(
            storage=storage,
            retrieval=retrieval,
            semantic_plugins={"selective_embedding": SelectiveEmbeddingPlugin()},
            default_use_case="selective_embedding",
            embedding_provider=embedding,
            vector_index=vector_idx,
        )

        ingest = service.ingest_item(
            source_type="chat_message",
            source_id="idempotent-1",
            content_type="text/plain",
            content="This is a user message that is definitely over forty characters long.",
            metadata=None,
            use_case="selective_embedding",
            artifact_kind="message",
        )
        service.drain_processing_queue(worker_id="test")

        # Count vector index entries for this source item
        source_item_id = ingest.source_item_id
        vector_entries = storage.list_index_entries_for_target(
            target_kind="source_item",
            target_id=source_item_id,
        )
        vector_type_entries = [e for e in vector_entries if e.index_type == VECTOR_INDEX_TYPE]
        assert len(vector_type_entries) == 1

        # The find_index_entry should find the existing one
        existing = storage.find_index_entry(
            target_kind="source_item",
            target_id=source_item_id,
            index_type=VECTOR_INDEX_TYPE,
            text_view_name="source_content.embedding",
        )
        assert existing is not None
        assert existing.id == vector_type_entries[0].id


# ---------------------------------------------------------------------------
# Vector index save frequency: one save per processing cycle, not per phase
# ---------------------------------------------------------------------------

class TestVectorIndexSaveFrequency:
    def test_single_item_saves_vector_index_once(self, test_db_url):
        """Processing one item that produces both source item AND memory object
        vector entries should save the vector index exactly once, not once per
        embedding phase."""
        embedding = FakeEmbeddingProvider()
        vector_idx = FakeVectorIndex()
        service = _build_service(
            test_db_url,
            plugins={"vector_producing": VectorProducingPlugin()},
            default_use_case="vector_producing",
            embedding_provider=embedding,
            vector_index=vector_idx,
        )

        service.ingest_item(
            source_type="chat_message",
            source_id="save-freq-1",
            content_type="text/plain",
            content="This is a user message that is definitely over forty characters long.",
            metadata=None,
            use_case="vector_producing",
            artifact_kind="message",
        )
        service.drain_processing_queue(worker_id="test")

        # Both memory object vector + source item vector should be in the index
        assert len(vector_idx.entries) == 2
        # But save should only be called once (batched), not twice
        assert vector_idx.save_count == 1

    def test_multiple_items_save_once_per_item(self, test_db_url):
        """Processing N items should save the vector index N times (once per item),
        not 2N times."""
        embedding = FakeEmbeddingProvider()
        vector_idx = FakeVectorIndex()
        service = _build_service(
            test_db_url,
            plugins={"vector_producing": VectorProducingPlugin()},
            default_use_case="vector_producing",
            embedding_provider=embedding,
            vector_index=vector_idx,
        )

        for i in range(3):
            service.ingest_item(
                source_type="chat_message",
                source_id=f"save-freq-{i}",
                content_type="text/plain",
                content=f"User message number {i} that is definitely over forty characters long.",
                metadata=None,
                use_case="vector_producing",
                artifact_kind="message",
            )
        service.drain_processing_queue(worker_id="test")

        # 3 items × 2 vectors each = 6 entries
        assert len(vector_idx.entries) == 6
        # 3 saves (one per item), not 6
        assert vector_idx.save_count == 3

    def test_non_qualifying_item_does_not_save(self, test_db_url):
        """Items that don't qualify for source embedding and produce no memory
        vectors should not trigger a save."""
        embedding = FakeEmbeddingProvider()
        vector_idx = FakeVectorIndex()
        service = _build_service(
            test_db_url,
            plugins={"selective_embedding": SelectiveEmbeddingPlugin()},
            default_use_case="selective_embedding",
            embedding_provider=embedding,
            vector_index=vector_idx,
        )

        service.ingest_item(
            source_type="tool_summary",
            source_id="no-save-1",
            content_type="text/plain",
            content="Tool use summary that should not be embedded even though it is long enough.",
            metadata=None,
            use_case="selective_embedding",
            artifact_kind="tool_use_summary",
        )
        service.drain_processing_queue(worker_id="test")

        assert len(vector_idx.entries) == 0
        assert vector_idx.save_count == 0


# ---------------------------------------------------------------------------
# Storage: find_index_entry
# ---------------------------------------------------------------------------

class TestFindIndexEntry:
    def test_returns_entry_when_exists(self, test_db_url):
        storage = SQLiteStorageProvider(test_db_url)
        entry = IndexEntry(
            target_kind="source_item",
            target_id="si-abc",
            index_type="vector",
            text_view="some text",
            text_view_name="source_content.embedding",
            provider_name="test",
            provider_version="v1",
        )
        storage.create_index_entry(entry)

        found = storage.find_index_entry(
            target_kind="source_item",
            target_id="si-abc",
            index_type="vector",
            text_view_name="source_content.embedding",
        )
        assert found is not None
        assert found.id == entry.id
        assert found.target_kind == "source_item"
        assert found.target_id == "si-abc"
        assert found.text_view == "some text"

    def test_returns_none_when_not_exists(self, test_db_url):
        storage = SQLiteStorageProvider(test_db_url)

        found = storage.find_index_entry(
            target_kind="source_item",
            target_id="nonexistent",
            index_type="vector",
            text_view_name="source_content.embedding",
        )
        assert found is None

    def test_returns_none_when_different_type(self, test_db_url):
        storage = SQLiteStorageProvider(test_db_url)
        entry = IndexEntry(
            target_kind="source_item",
            target_id="si-xyz",
            index_type="lexical",
            text_view="some text",
            text_view_name="source_item.content",
        )
        storage.create_index_entry(entry)

        found = storage.find_index_entry(
            target_kind="source_item",
            target_id="si-xyz",
            index_type="vector",
            text_view_name="source_content.embedding",
        )
        assert found is None
