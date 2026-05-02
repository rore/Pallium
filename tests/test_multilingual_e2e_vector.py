"""Full end-to-end multilingual vector retrieval integration test.

Uses the REAL multilingual-e5-small ONNX model, REAL usearch VectorIndex,
REAL SQLiteStorageProvider, and REAL VectorRetrievalProvider. Embeds Hebrew
and English content, writes to the vector index, queries cross-language,
and verifies retrieval results.

Skipped when the model is not available (CI environments).
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

from core.models import IndexEntry, MemoryObject, Relation, SourceItem
from core.text import normalize_for_index
from core.vector_index_holder import VectorIndexHolder


def _try_load_model():
    try:
        from providers.embedding.onnx_provider import OnnxEmbeddingProvider
        provider = OnnxEmbeddingProvider(
            model="intfloat/multilingual-e5-small",
            query_prefix="query: ",
            passage_prefix="passage: ",
        )
        _ = provider.embed(["probe"], mode="passage")
        return provider, None
    except Exception as e:
        return None, str(e)


_provider, _skip_reason = _try_load_model()
skip_if_no_model = pytest.mark.skipif(
    _provider is None, reason=_skip_reason or "model not available"
)


def _make_source_item(source_id: str, content: str, **kwargs) -> SourceItem:
    defaults = dict(
        source_type="chat_message",
        content_type="text/plain",
        artifact_kind="message",
        role="user",
        container_ref="e2e:container",
        thread_ref="e2e:thread",
        visibility="private",
    )
    defaults.update(kwargs)
    return SourceItem(source_id=source_id, content=content, **defaults)


def _make_memory(type: str, payload: dict, **kwargs) -> MemoryObject:
    defaults = dict(
        schema_id="test",
        schema_version="v1",
        visibility="private",
        container_ref="e2e:container",
    )
    defaults.update(kwargs)
    return MemoryObject(type=type, payload=payload, **defaults)


@skip_if_no_model
class TestEndToEndMultilingualVectorRetrieval:
    """Full pipeline: embed → store → index → query → retrieve.

    Tests that Hebrew and English content can be embedded with the real
    multilingual-e5-small model, stored in a real usearch vector index,
    and retrieved via the real VectorRetrievalProvider.
    """

    @pytest.fixture
    def setup(self, test_db_url):
        """Create real storage, real vector index, real embedding provider."""
        from retrieval.vector import VectorRetrievalProvider
        from storage.sqlite import SQLiteStorageProvider
        from storage.vector_index import VectorIndex

        storage = SQLiteStorageProvider(test_db_url)

        # Create a temp vector index
        tmp = tempfile.mkdtemp()
        index_path = Path(tmp) / "test_vector.index"
        vector_index = VectorIndex(index_path, dimensions=384, model_name="intfloat/multilingual-e5-small")

        retrieval = VectorRetrievalProvider(
            storage=storage,
            embedding_provider=_provider,
            min_similarity=0.3,  # low threshold to see all results
            index_holder=VectorIndexHolder(vector_index),
        )

        return storage, vector_index, retrieval

    def _ingest_and_embed(self, storage, vector_index, source_id, content, memory_type, memory_payload):
        """Ingest a source item + memory object, create index entries, embed."""
        source = _make_source_item(source_id, content)
        storage.create_source_item(source)

        memory = _make_memory(memory_type, memory_payload)
        storage.create_memory_object(memory)

        storage.create_relation(Relation(
            from_kind="memory_object",
            from_id=memory.id,
            relation_type="supported_by",
            to_kind="source_item",
            to_id=source.id,
        ))

        # Create lexical index entry
        lexical_entry = IndexEntry(
            target_kind="memory_object",
            target_id=memory.id,
            index_type="lexical",
            text_view=normalize_for_index(content),
            text_view_name="default",
        )
        storage.create_index_entry(lexical_entry)

        # Create vector index entry and embed it
        embedding_text = f"{memory_type}: {memory_payload.get('decision', memory_payload.get('summary', content))}"
        vector_entry = IndexEntry(
            target_kind="memory_object",
            target_id=memory.id,
            index_type="vector",
            text_view=embedding_text,
            text_view_name="embedding",
        )
        storage.create_index_entry(vector_entry)

        # Embed and add to vector index
        vectors = _provider.embed([embedding_text], mode="passage")
        vector_index.add(vector_entry.id, vectors[0])

        return memory.id

    def test_hebrew_query_finds_hebrew_memory(self, setup):
        """Hebrew query retrieves Hebrew memory via vector similarity."""
        storage, vector_index, retrieval = setup

        mem_id = self._ingest_and_embed(
            storage, vector_index,
            source_id="heb-db-1",
            content="החלטנו להשתמש ב-PostgreSQL בשביל מסד הנתונים שלנו",
            memory_type="decision",
            memory_payload={"decision": "להשתמש ב-PostgreSQL למסד הנתונים"},
        )

        result = retrieval.query(
            "מה החלטנו לגבי מסד הנתונים",
            limit=5,
            query_container_ref="e2e:container",
        )

        assert len(result.results) >= 1, "Hebrew query returned no vector results"
        found_ids = [r.memory_object_id for r in result.results if r.result_kind == "memory_hit"]
        assert mem_id in found_ids, f"Hebrew memory not found. Got: {[r.result_kind for r in result.results]}"

    def test_hebrew_query_finds_english_memory_cross_language(self, setup):
        """Hebrew query retrieves English memory via cross-language embedding."""
        storage, vector_index, retrieval = setup

        mem_id = self._ingest_and_embed(
            storage, vector_index,
            source_id="eng-db-1",
            content="We decided to use PostgreSQL for the database because it has better concurrent write support.",
            memory_type="decision",
            memory_payload={"decision": "use PostgreSQL for the database"},
        )

        result = retrieval.query(
            "מה החלטנו לגבי מסד הנתונים",
            limit=5,
            query_container_ref="e2e:container",
        )

        assert len(result.results) >= 1, "Cross-language query returned no vector results"
        found_ids = [r.memory_object_id for r in result.results if r.result_kind == "memory_hit"]
        assert mem_id in found_ids, f"English memory not found via Hebrew query. Got: {[r.result_kind for r in result.results]}"

    def test_english_query_finds_hebrew_memory_cross_language(self, setup):
        """English query retrieves Hebrew memory via cross-language embedding."""
        storage, vector_index, retrieval = setup

        mem_id = self._ingest_and_embed(
            storage, vector_index,
            source_id="heb-cache-1",
            content="אנחנו צריכים להשתמש ב-Redis לשכבת המטמון",
            memory_type="decision",
            memory_payload={"decision": "להשתמש ב-Redis למטמון"},
        )

        result = retrieval.query(
            "what did we decide about caching",
            limit=5,
            query_container_ref="e2e:container",
        )

        assert len(result.results) >= 1, "English→Hebrew query returned no vector results"
        found_ids = [r.memory_object_id for r in result.results if r.result_kind == "memory_hit"]
        assert mem_id in found_ids, f"Hebrew memory not found via English query. Got: {[r.result_kind for r in result.results]}"

    def test_relevant_ranks_above_irrelevant(self, setup):
        """Relevant memory should rank above irrelevant memory regardless of language."""
        storage, vector_index, retrieval = setup

        relevant_id = self._ingest_and_embed(
            storage, vector_index,
            source_id="rel-1",
            content="We decided to use PostgreSQL for the database.",
            memory_type="decision",
            memory_payload={"decision": "use PostgreSQL for the database"},
        )

        irrelevant_id = self._ingest_and_embed(
            storage, vector_index,
            source_id="irr-1",
            content="I made chocolate cake last night for the birthday party.",
            memory_type="turn_summary",
            memory_payload={"summary": "chocolate cake for the birthday party"},
        )

        # Hebrew query about database
        result = retrieval.query(
            "מה החלטנו לגבי מסד הנתונים",
            limit=5,
            query_container_ref="e2e:container",
        )

        assert len(result.results) >= 2, f"Expected at least 2 results, got {len(result.results)}"
        result_ids = [r.memory_object_id for r in result.results if r.result_kind == "memory_hit"]
        assert relevant_id in result_ids, "Relevant memory not found"
        assert irrelevant_id in result_ids, "Irrelevant memory not found (needed for ranking check)"
        relevant_idx = result_ids.index(relevant_id)
        irrelevant_idx = result_ids.index(irrelevant_id)
        assert relevant_idx < irrelevant_idx, (
            f"Relevant memory should rank above irrelevant: "
            f"relevant at {relevant_idx}, irrelevant at {irrelevant_idx}"
        )

    def test_vector_index_persists_and_reloads(self, setup):
        """Vector index can be saved and reloaded, and still finds results."""
        from storage.vector_index import VectorIndex

        storage, vector_index, retrieval = setup

        mem_id = self._ingest_and_embed(
            storage, vector_index,
            source_id="persist-1",
            content="We decided to use PostgreSQL for the database.",
            memory_type="decision",
            memory_payload={"decision": "use PostgreSQL for the database"},
        )

        # Save index to disk
        vector_index.save()
        index_path = vector_index._index_path

        # Reload from disk
        reloaded_index = VectorIndex.load(index_path)
        assert reloaded_index.entry_count() == 1
        assert reloaded_index.model_name == "intfloat/multilingual-e5-small"

        # Query with reloaded index
        from retrieval.vector import VectorRetrievalProvider
        reloaded_retrieval = VectorRetrievalProvider(
            storage=storage,
            embedding_provider=_provider,
            min_similarity=0.3,
            index_holder=VectorIndexHolder(reloaded_index),
        )

        result = reloaded_retrieval.query(
            "מה החלטנו לגבי מסד הנתונים",
            limit=5,
            query_container_ref="e2e:container",
        )

        found_ids = [r.memory_object_id for r in result.results if r.result_kind == "memory_hit"]
        assert mem_id in found_ids, "Memory not found after index reload"
