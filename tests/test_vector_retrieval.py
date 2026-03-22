from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import MagicMock, call

import pytest

from core.models import (
    EvidenceReference,
    IndexEntry,
    MemoryObject,
    QueryFilters,
    SourceItem,
)
from providers.embedding.base import EmbeddingProvider
from retrieval.vector import VectorRetrievalProvider, VECTOR_STAGE_NAME
from storage.base import StorageProvider
from storage.vector_index import VectorIndex


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _public() -> str:
    return "public"


def _limited(value: str) -> str:
    return "limited"


def _user(value: str) -> str:
    return "private"


def _make_index_entry(
    entry_id: str = "idx-1",
    target_kind: str = "memory_object",
    target_id: str = "mo-1",
    text_view_name: str = "default",
    provider_name: str = "test-embed",
    provider_version: str = "v1",
) -> IndexEntry:
    return IndexEntry(
        id=entry_id,
        target_kind=target_kind,
        target_id=target_id,
        index_type="vector",
        text_view="embedded text",
        text_view_name=text_view_name,
        provider_name=provider_name,
        provider_version=provider_version,
    )


def _make_memory_object(
    mo_id: str = "mo-1",
    mo_type: str = "decision",
    visibility: str | None = None,
    lifecycle: str = "active",
    container_ref: str | None = None,
) -> MemoryObject:
    return MemoryObject(
        id=mo_id,
        type=mo_type,
        schema_id="test",
        schema_version="1",
        payload={"summary_text": "test decision content"},
        lifecycle=lifecycle,
        container_visibility=visibility or _public(),
        container_ref=container_ref,
    )


def _make_source_item(
    si_id: str = "si-1",
    source_type: str = "assistant_artifact",
    source_id: str = "src-1",
    content: str = "source content here",
    visibility: str | None = None,
    container_ref: str | None = "chat:test",
    thread_ref: str | None = "chat:test:thread-1",
    role: str | None = "assistant",
) -> SourceItem:
    return SourceItem(
        id=si_id,
        source_type=source_type,
        source_id=source_id,
        content_type="text/plain",
        content=content,
        container_visibility=visibility or _public(),
        container_ref=container_ref,
        thread_ref=thread_ref,
        role=role,
    )


def _make_evidence(
    source_item_id: str = "si-1",
    source_type: str = "assistant_artifact",
    source_id: str = "src-1",
    visibility: str | None = None,
    container_ref: str | None = "chat:test",
) -> EvidenceReference:
    return EvidenceReference(
        source_item_id=source_item_id,
        source_type=source_type,
        source_id=source_id,
        container_visibility=visibility or _public(),
        container_ref=container_ref,
    )


class FakeEmbeddingProvider(EmbeddingProvider):
    """Returns a fixed vector for any input."""

    def __init__(self, vector: list[float] | None = None, dims: int = 4) -> None:
        self._vector = vector or [0.1, 0.2, 0.3, 0.4]
        self._dims = dims

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector[:] for _ in texts]

    def dimensions(self) -> int:
        return self._dims

    def model_name(self) -> str:
        return "test-embed-model"


class FakeVectorIndex:
    """In-memory fake that replaces usearch-backed VectorIndex for tests."""

    def __init__(self, hits: list[tuple[str, float]] | None = None) -> None:
        self._hits = hits or []
        self._removed: list[str] = []
        self._saved = False

    def search(self, query_vector: list[float], k: int) -> list[tuple[str, float]]:
        return self._hits[:k]

    def remove(self, entry_id: str) -> None:
        self._removed.append(entry_id)

    def save(self) -> None:
        self._saved = True

    @property
    def removed_ids(self) -> list[str]:
        return self._removed

    @property
    def was_saved(self) -> bool:
        return self._saved


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestVectorRetrievalBasic:
    """Basic query returns correctly hydrated memory_hit results."""

    def test_returns_memory_hit(self) -> None:
        index_entry = _make_index_entry(entry_id="idx-1", target_kind="memory_object", target_id="mo-1")
        memory_obj = _make_memory_object(mo_id="mo-1")
        evidence = [_make_evidence()]

        storage = MagicMock(spec=StorageProvider)
        storage.get_index_entry.return_value = index_entry
        storage.get_memory_object.return_value = memory_obj
        storage.get_evidence_for_memory_object.return_value = evidence

        vector_index = FakeVectorIndex(hits=[("idx-1", 0.85)])
        embedding = FakeEmbeddingProvider()

        provider = VectorRetrievalProvider(storage, vector_index, embedding)
        result = provider.query("test query", limit=5)

        assert len(result.results) == 1
        item = result.results[0]
        assert item.result_kind == "memory_hit"
        assert item.memory_object_id == "mo-1"
        assert item.type == "decision"
        assert item.score == 850  # int(0.85 * 1000)
        assert item.evidence == evidence
        assert item.container_visibility == "public"

    def test_returns_source_hit(self) -> None:
        index_entry = _make_index_entry(entry_id="idx-2", target_kind="source_item", target_id="si-1")
        source_item = _make_source_item(si_id="si-1")

        storage = MagicMock(spec=StorageProvider)
        storage.get_index_entry.return_value = index_entry
        storage.get_source_item.return_value = source_item

        vector_index = FakeVectorIndex(hits=[("idx-2", 0.72)])
        embedding = FakeEmbeddingProvider()

        provider = VectorRetrievalProvider(storage, vector_index, embedding)
        result = provider.query("test query", limit=5)

        assert len(result.results) == 1
        item = result.results[0]
        assert item.result_kind == "source_hit"
        assert item.source_item_id == "si-1"
        assert item.score == 720
        assert item.excerpt is not None

    def test_deduplicates_by_target(self) -> None:
        """Two index entries pointing to the same target should produce one result."""
        entry_a = _make_index_entry(entry_id="idx-a", target_kind="memory_object", target_id="mo-1")
        entry_b = _make_index_entry(entry_id="idx-b", target_kind="memory_object", target_id="mo-1")
        memory_obj = _make_memory_object(mo_id="mo-1")
        evidence = [_make_evidence()]

        storage = MagicMock(spec=StorageProvider)
        storage.get_index_entry.side_effect = lambda eid: {"idx-a": entry_a, "idx-b": entry_b}[eid]
        storage.get_memory_object.return_value = memory_obj
        storage.get_evidence_for_memory_object.return_value = evidence

        vector_index = FakeVectorIndex(hits=[("idx-a", 0.9), ("idx-b", 0.8)])
        embedding = FakeEmbeddingProvider()

        provider = VectorRetrievalProvider(storage, vector_index, embedding)
        result = provider.query("test", limit=10)

        assert len(result.results) == 1

    def test_respects_limit(self) -> None:
        entries = {}
        memory_objs = {}
        hits = []
        for i in range(5):
            eid = f"idx-{i}"
            mid = f"mo-{i}"
            entries[eid] = _make_index_entry(entry_id=eid, target_kind="memory_object", target_id=mid)
            memory_objs[mid] = _make_memory_object(mo_id=mid)
            hits.append((eid, 0.9 - i * 0.05))

        storage = MagicMock(spec=StorageProvider)
        storage.get_index_entry.side_effect = lambda eid: entries[eid]
        storage.get_memory_object.side_effect = lambda mid: memory_objs[mid]
        storage.get_evidence_for_memory_object.return_value = [_make_evidence()]

        vector_index = FakeVectorIndex(hits=hits)
        embedding = FakeEmbeddingProvider()

        provider = VectorRetrievalProvider(storage, vector_index, embedding)
        result = provider.query("test", limit=2)

        assert len(result.results) == 2


class TestMinSimilarityThreshold:
    """Verify min_similarity threshold filtering."""

    def test_below_threshold_filtered(self) -> None:
        index_entry = _make_index_entry(entry_id="idx-1", target_kind="memory_object", target_id="mo-1")
        memory_obj = _make_memory_object(mo_id="mo-1")

        storage = MagicMock(spec=StorageProvider)
        storage.get_index_entry.return_value = index_entry
        storage.get_memory_object.return_value = memory_obj
        storage.get_evidence_for_memory_object.return_value = []

        vector_index = FakeVectorIndex(hits=[("idx-1", 0.2)])  # Below default 0.3
        embedding = FakeEmbeddingProvider()

        provider = VectorRetrievalProvider(storage, vector_index, embedding, min_similarity=0.3)
        result = provider.query("test query", limit=5)

        assert len(result.results) == 0

    def test_at_threshold_included(self) -> None:
        index_entry = _make_index_entry(entry_id="idx-1", target_kind="memory_object", target_id="mo-1")
        memory_obj = _make_memory_object(mo_id="mo-1")

        storage = MagicMock(spec=StorageProvider)
        storage.get_index_entry.return_value = index_entry
        storage.get_memory_object.return_value = memory_obj
        storage.get_evidence_for_memory_object.return_value = [_make_evidence()]

        vector_index = FakeVectorIndex(hits=[("idx-1", 0.3)])
        embedding = FakeEmbeddingProvider()

        provider = VectorRetrievalProvider(storage, vector_index, embedding, min_similarity=0.3)
        result = provider.query("test query", limit=5)

        assert len(result.results) == 1

    def test_custom_threshold(self) -> None:
        index_entry = _make_index_entry(entry_id="idx-1", target_kind="memory_object", target_id="mo-1")
        memory_obj = _make_memory_object(mo_id="mo-1")

        storage = MagicMock(spec=StorageProvider)
        storage.get_index_entry.return_value = index_entry
        storage.get_memory_object.return_value = memory_obj
        storage.get_evidence_for_memory_object.return_value = [_make_evidence()]

        # Similarity 0.5, threshold 0.6 -> filtered
        vector_index = FakeVectorIndex(hits=[("idx-1", 0.5)])
        embedding = FakeEmbeddingProvider()

        provider = VectorRetrievalProvider(storage, vector_index, embedding, min_similarity=0.6)
        result = provider.query("test query", limit=5)

        assert len(result.results) == 0

    def test_mixed_above_below_threshold(self) -> None:
        entry_above = _make_index_entry(entry_id="idx-above", target_kind="memory_object", target_id="mo-1")
        entry_below = _make_index_entry(entry_id="idx-below", target_kind="memory_object", target_id="mo-2")
        mo_1 = _make_memory_object(mo_id="mo-1")
        mo_2 = _make_memory_object(mo_id="mo-2")

        storage = MagicMock(spec=StorageProvider)
        storage.get_index_entry.side_effect = lambda eid: {"idx-above": entry_above, "idx-below": entry_below}[eid]
        storage.get_memory_object.side_effect = lambda mid: {"mo-1": mo_1, "mo-2": mo_2}[mid]
        storage.get_evidence_for_memory_object.return_value = [_make_evidence()]

        vector_index = FakeVectorIndex(hits=[("idx-above", 0.7), ("idx-below", 0.1)])
        embedding = FakeEmbeddingProvider()

        provider = VectorRetrievalProvider(storage, vector_index, embedding, min_similarity=0.3)
        result = provider.query("test", limit=10)

        assert len(result.results) == 1
        assert result.results[0].memory_object_id == "mo-1"


class TestVisibilityFiltering:
    """Verify visibility filtering follows the same patterns as lexical."""

    def test_public_query_sees_only_public(self) -> None:
        entry_pub = _make_index_entry(entry_id="idx-pub", target_kind="memory_object", target_id="mo-pub")
        entry_lim = _make_index_entry(entry_id="idx-lim", target_kind="memory_object", target_id="mo-lim")
        mo_pub = _make_memory_object(mo_id="mo-pub", visibility=_public())
        mo_lim = _make_memory_object(mo_id="mo-lim", visibility=_limited("channel-a"))

        storage = MagicMock(spec=StorageProvider)
        storage.get_index_entry.side_effect = lambda eid: {"idx-pub": entry_pub, "idx-lim": entry_lim}[eid]
        storage.get_memory_object.side_effect = lambda mid: {"mo-pub": mo_pub, "mo-lim": mo_lim}[mid]
        storage.get_evidence_for_memory_object.return_value = [_make_evidence()]

        vector_index = FakeVectorIndex(hits=[("idx-pub", 0.9), ("idx-lim", 0.8)])
        embedding = FakeEmbeddingProvider()

        provider = VectorRetrievalProvider(storage, vector_index, embedding)
        result = provider.query("test", limit=10, container_visibility="public", query_container_ref="channel-x")

        assert len(result.results) == 1
        assert result.results[0].memory_object_id == "mo-pub"

    def test_limited_query_sees_public_and_same_limited(self) -> None:
        entry_pub = _make_index_entry(entry_id="idx-pub", target_kind="memory_object", target_id="mo-pub")
        entry_lim_a = _make_index_entry(entry_id="idx-lim-a", target_kind="memory_object", target_id="mo-lim-a")
        entry_lim_b = _make_index_entry(entry_id="idx-lim-b", target_kind="memory_object", target_id="mo-lim-b")
        mo_pub = _make_memory_object(mo_id="mo-pub", visibility=_public())
        mo_lim_a = _make_memory_object(mo_id="mo-lim-a", visibility=_limited("channel-a"), container_ref="channel-a")
        mo_lim_b = _make_memory_object(mo_id="mo-lim-b", visibility=_limited("channel-b"), container_ref="channel-b")

        entries = {"idx-pub": entry_pub, "idx-lim-a": entry_lim_a, "idx-lim-b": entry_lim_b}
        objs = {"mo-pub": mo_pub, "mo-lim-a": mo_lim_a, "mo-lim-b": mo_lim_b}

        storage = MagicMock(spec=StorageProvider)
        storage.get_index_entry.side_effect = lambda eid: entries[eid]
        storage.get_memory_object.side_effect = lambda mid: objs[mid]
        storage.get_evidence_for_memory_object.return_value = [_make_evidence()]

        vector_index = FakeVectorIndex(
            hits=[("idx-pub", 0.9), ("idx-lim-a", 0.85), ("idx-lim-b", 0.8)]
        )
        embedding = FakeEmbeddingProvider()

        provider = VectorRetrievalProvider(storage, vector_index, embedding)
        result = provider.query("test", limit=10, container_visibility="limited", query_container_ref="channel-a")

        returned_ids = {r.memory_object_id for r in result.results}
        assert returned_ids == {"mo-pub", "mo-lim-a"}

    def test_no_visibility_context_sees_all(self) -> None:
        """When no visibility_context is provided and not required, all pass."""
        entry_pub = _make_index_entry(entry_id="idx-pub", target_kind="memory_object", target_id="mo-pub")
        entry_lim = _make_index_entry(entry_id="idx-lim", target_kind="memory_object", target_id="mo-lim")
        mo_pub = _make_memory_object(mo_id="mo-pub", visibility=_public())
        mo_lim = _make_memory_object(mo_id="mo-lim", visibility=_limited("channel-a"))

        storage = MagicMock(spec=StorageProvider)
        storage.get_index_entry.side_effect = lambda eid: {"idx-pub": entry_pub, "idx-lim": entry_lim}[eid]
        storage.get_memory_object.side_effect = lambda mid: {"mo-pub": mo_pub, "mo-lim": mo_lim}[mid]
        storage.get_evidence_for_memory_object.return_value = [_make_evidence()]

        vector_index = FakeVectorIndex(hits=[("idx-pub", 0.9), ("idx-lim", 0.8)])
        embedding = FakeEmbeddingProvider()

        provider = VectorRetrievalProvider(storage, vector_index, embedding)
        result = provider.query("test", limit=10, container_visibility=None)

        assert len(result.results) == 2


class TestRequireVisibilityFailClosed:
    """Verify require_visibility fail-closed behavior."""

    def test_require_visibility_without_context_returns_empty(self) -> None:
        storage = MagicMock(spec=StorageProvider)
        vector_index = FakeVectorIndex(hits=[("idx-1", 0.9)])
        embedding = FakeEmbeddingProvider()

        provider = VectorRetrievalProvider(storage, vector_index, embedding)
        result = provider.query("test", limit=5, require_visibility=True, container_visibility=None)

        assert result.results == []
        # Should not have called search at all
        storage.get_index_entry.assert_not_called()

    def test_require_visibility_without_context_trace_includes_reason(self) -> None:
        storage = MagicMock(spec=StorageProvider)
        vector_index = FakeVectorIndex(hits=[("idx-1", 0.9)])
        embedding = FakeEmbeddingProvider()

        provider = VectorRetrievalProvider(storage, vector_index, embedding)
        result = provider.query(
            "test", limit=5, require_visibility=True, container_visibility=None, include_trace=True
        )

        assert result.results == []
        assert result.trace is not None
        assert result.trace.visibility is not None
        assert result.trace.visibility.fail_closed_reason == "retrieval_visibility_context_required"

    def test_require_visibility_with_context_works_normally(self) -> None:
        index_entry = _make_index_entry()
        memory_obj = _make_memory_object(visibility=_public())

        storage = MagicMock(spec=StorageProvider)
        storage.get_index_entry.return_value = index_entry
        storage.get_memory_object.return_value = memory_obj
        storage.get_evidence_for_memory_object.return_value = [_make_evidence()]

        vector_index = FakeVectorIndex(hits=[("idx-1", 0.9)])
        embedding = FakeEmbeddingProvider()

        provider = VectorRetrievalProvider(storage, vector_index, embedding)
        result = provider.query(
            "test", limit=5, require_visibility=True, container_visibility="public"
        )

        assert len(result.results) == 1


class TestStaleEntryLazyRemoval:
    """Verify stale entry handling when get_index_entry raises KeyError."""

    def test_stale_entry_removed_from_vector_index(self) -> None:
        storage = MagicMock(spec=StorageProvider)
        storage.get_index_entry.side_effect = KeyError("idx-stale")

        vector_index = FakeVectorIndex(hits=[("idx-stale", 0.9)])
        embedding = FakeEmbeddingProvider()

        provider = VectorRetrievalProvider(storage, vector_index, embedding)
        result = provider.query("test", limit=5)

        assert result.results == []
        assert "idx-stale" in vector_index.removed_ids
        assert vector_index.was_saved

    def test_stale_entry_skipped_valid_entry_returned(self) -> None:
        index_entry = _make_index_entry(entry_id="idx-valid", target_kind="memory_object", target_id="mo-1")
        memory_obj = _make_memory_object(mo_id="mo-1")

        storage = MagicMock(spec=StorageProvider)
        storage.get_index_entry.side_effect = lambda eid: (
            index_entry if eid == "idx-valid" else (_ for _ in ()).throw(KeyError(eid))
        )
        storage.get_memory_object.return_value = memory_obj
        storage.get_evidence_for_memory_object.return_value = [_make_evidence()]

        vector_index = FakeVectorIndex(hits=[("idx-stale", 0.95), ("idx-valid", 0.85)])
        embedding = FakeEmbeddingProvider()

        provider = VectorRetrievalProvider(storage, vector_index, embedding)
        result = provider.query("test", limit=5)

        assert len(result.results) == 1
        assert result.results[0].memory_object_id == "mo-1"
        assert "idx-stale" in vector_index.removed_ids
        assert vector_index.was_saved

    def test_no_stale_entries_no_save(self) -> None:
        index_entry = _make_index_entry()
        memory_obj = _make_memory_object()

        storage = MagicMock(spec=StorageProvider)
        storage.get_index_entry.return_value = index_entry
        storage.get_memory_object.return_value = memory_obj
        storage.get_evidence_for_memory_object.return_value = [_make_evidence()]

        vector_index = FakeVectorIndex(hits=[("idx-1", 0.9)])
        embedding = FakeEmbeddingProvider()

        provider = VectorRetrievalProvider(storage, vector_index, embedding)
        result = provider.query("test", limit=5)

        assert len(result.results) == 1
        assert vector_index.removed_ids == []
        assert not vector_index.was_saved


class TestTraceOutput:
    """Verify trace includes vector stage with cosine_similarity."""

    def test_trace_includes_vector_stage(self) -> None:
        index_entry = _make_index_entry()
        memory_obj = _make_memory_object()

        storage = MagicMock(spec=StorageProvider)
        storage.get_index_entry.return_value = index_entry
        storage.get_memory_object.return_value = memory_obj
        storage.get_evidence_for_memory_object.return_value = [_make_evidence()]

        vector_index = FakeVectorIndex(hits=[("idx-1", 0.85)])
        embedding = FakeEmbeddingProvider()

        provider = VectorRetrievalProvider(storage, vector_index, embedding)
        result = provider.query("test query", limit=5, include_trace=True)

        assert result.trace is not None
        assert len(result.trace.stages) == 1
        stage = result.trace.stages[0]
        assert stage.stage_name == VECTOR_STAGE_NAME
        assert stage.candidate_hits_considered == 1
        assert len(stage.selected_hits) == 1

    def test_trace_hit_has_cosine_similarity(self) -> None:
        index_entry = _make_index_entry()
        memory_obj = _make_memory_object()

        storage = MagicMock(spec=StorageProvider)
        storage.get_index_entry.return_value = index_entry
        storage.get_memory_object.return_value = memory_obj
        storage.get_evidence_for_memory_object.return_value = [_make_evidence()]

        vector_index = FakeVectorIndex(hits=[("idx-1", 0.85)])
        embedding = FakeEmbeddingProvider()

        provider = VectorRetrievalProvider(storage, vector_index, embedding)
        result = provider.query("test", limit=5, include_trace=True)

        hit = result.trace.stages[0].selected_hits[0]
        assert hit.index_type == "vector"
        assert hit.matched_tokens == ()
        assert hit.cosine_similarity == 0.85
        assert hit.score == 850

    def test_trace_hit_fields(self) -> None:
        index_entry = _make_index_entry(
            entry_id="idx-1",
            target_kind="memory_object",
            target_id="mo-1",
            provider_name="test-embed",
            provider_version="v1",
        )
        memory_obj = _make_memory_object()

        storage = MagicMock(spec=StorageProvider)
        storage.get_index_entry.return_value = index_entry
        storage.get_memory_object.return_value = memory_obj
        storage.get_evidence_for_memory_object.return_value = [_make_evidence()]

        vector_index = FakeVectorIndex(hits=[("idx-1", 0.75)])
        embedding = FakeEmbeddingProvider()

        provider = VectorRetrievalProvider(storage, vector_index, embedding)
        result = provider.query("test", limit=5, include_trace=True)

        hit = result.trace.stages[0].selected_hits[0]
        assert hit.target_kind == "memory_object"
        assert hit.target_id == "mo-1"
        assert hit.index_entry_id == "idx-1"
        assert hit.provider_name == "test-embed"
        assert hit.provider_version == "v1"

    def test_no_trace_when_not_requested(self) -> None:
        index_entry = _make_index_entry()
        memory_obj = _make_memory_object()

        storage = MagicMock(spec=StorageProvider)
        storage.get_index_entry.return_value = index_entry
        storage.get_memory_object.return_value = memory_obj
        storage.get_evidence_for_memory_object.return_value = [_make_evidence()]

        vector_index = FakeVectorIndex(hits=[("idx-1", 0.85)])
        embedding = FakeEmbeddingProvider()

        provider = VectorRetrievalProvider(storage, vector_index, embedding)
        result = provider.query("test", limit=5, include_trace=False)

        assert result.trace is None

    def test_trace_query_tokens_empty_for_vector(self) -> None:
        index_entry = _make_index_entry()
        memory_obj = _make_memory_object()

        storage = MagicMock(spec=StorageProvider)
        storage.get_index_entry.return_value = index_entry
        storage.get_memory_object.return_value = memory_obj
        storage.get_evidence_for_memory_object.return_value = [_make_evidence()]

        vector_index = FakeVectorIndex(hits=[("idx-1", 0.85)])
        embedding = FakeEmbeddingProvider()

        provider = VectorRetrievalProvider(storage, vector_index, embedding)
        result = provider.query("test query text", limit=5, include_trace=True)

        assert result.trace.query_tokens == ()

    def test_trace_visibility_included_when_context_provided(self) -> None:
        index_entry = _make_index_entry()
        memory_obj = _make_memory_object(visibility=_public())

        storage = MagicMock(spec=StorageProvider)
        storage.get_index_entry.return_value = index_entry
        storage.get_memory_object.return_value = memory_obj
        storage.get_evidence_for_memory_object.return_value = [_make_evidence()]

        vector_index = FakeVectorIndex(hits=[("idx-1", 0.85)])
        embedding = FakeEmbeddingProvider()

        provider = VectorRetrievalProvider(storage, vector_index, embedding)
        result = provider.query("test", limit=5, include_trace=True, container_visibility="public")

        assert result.trace.visibility is not None
        assert result.trace.visibility.query_container_visibility == "public"


class TestFilterMatching:
    """Verify filter handling matches sqlite_search.py patterns."""

    def test_inactive_memory_object_filtered(self) -> None:
        index_entry = _make_index_entry(entry_id="idx-1", target_kind="memory_object", target_id="mo-1")
        memory_obj = _make_memory_object(mo_id="mo-1", lifecycle="superseded")

        storage = MagicMock(spec=StorageProvider)
        storage.get_index_entry.return_value = index_entry
        storage.get_memory_object.return_value = memory_obj

        vector_index = FakeVectorIndex(hits=[("idx-1", 0.9)])
        embedding = FakeEmbeddingProvider()

        provider = VectorRetrievalProvider(storage, vector_index, embedding)
        result = provider.query("test", limit=5)

        assert len(result.results) == 0

    def test_container_ref_filter_on_evidence(self) -> None:
        index_entry = _make_index_entry(entry_id="idx-1", target_kind="memory_object", target_id="mo-1")
        memory_obj = _make_memory_object(mo_id="mo-1")
        evidence_match = _make_evidence(container_ref="chat:target")
        evidence_no_match = _make_evidence(container_ref="chat:other")

        storage = MagicMock(spec=StorageProvider)
        storage.get_index_entry.return_value = index_entry
        storage.get_memory_object.return_value = memory_obj
        storage.get_evidence_for_memory_object.return_value = [evidence_match]

        vector_index = FakeVectorIndex(hits=[("idx-1", 0.9)])
        embedding = FakeEmbeddingProvider()

        filters = QueryFilters(container_ref="chat:target")
        provider = VectorRetrievalProvider(storage, vector_index, embedding)
        result = provider.query("test", limit=5, filters=filters)

        assert len(result.results) == 1

    def test_container_ref_filter_excludes_non_matching(self) -> None:
        index_entry = _make_index_entry(entry_id="idx-1", target_kind="memory_object", target_id="mo-1")
        memory_obj = _make_memory_object(mo_id="mo-1")
        evidence = _make_evidence(container_ref="chat:other", visibility="private")

        storage = MagicMock(spec=StorageProvider)
        storage.get_index_entry.return_value = index_entry
        storage.get_memory_object.return_value = memory_obj
        storage.get_evidence_for_memory_object.return_value = [evidence]

        vector_index = FakeVectorIndex(hits=[("idx-1", 0.9)])
        embedding = FakeEmbeddingProvider()

        filters = QueryFilters(container_ref="chat:target")
        provider = VectorRetrievalProvider(storage, vector_index, embedding)
        result = provider.query("test", limit=5, filters=filters)

        assert len(result.results) == 0

    def test_source_item_filter_matching(self) -> None:
        index_entry = _make_index_entry(entry_id="idx-1", target_kind="source_item", target_id="si-1")
        source_item = _make_source_item(si_id="si-1", role="assistant", container_ref="chat:target")

        storage = MagicMock(spec=StorageProvider)
        storage.get_index_entry.return_value = index_entry
        storage.get_source_item.return_value = source_item

        vector_index = FakeVectorIndex(hits=[("idx-1", 0.9)])
        embedding = FakeEmbeddingProvider()

        filters = QueryFilters(role="assistant", container_ref="chat:target")
        provider = VectorRetrievalProvider(storage, vector_index, embedding)
        result = provider.query("test", limit=5, filters=filters)

        assert len(result.results) == 1

    def test_source_item_filter_excludes_non_matching_role(self) -> None:
        index_entry = _make_index_entry(entry_id="idx-1", target_kind="source_item", target_id="si-1")
        source_item = _make_source_item(si_id="si-1", role="user")

        storage = MagicMock(spec=StorageProvider)
        storage.get_index_entry.return_value = index_entry
        storage.get_source_item.return_value = source_item

        vector_index = FakeVectorIndex(hits=[("idx-1", 0.9)])
        embedding = FakeEmbeddingProvider()

        filters = QueryFilters(role="assistant")
        provider = VectorRetrievalProvider(storage, vector_index, embedding)
        result = provider.query("test", limit=5, filters=filters)

        assert len(result.results) == 0


class TestScoreContract:
    """Verify score = int(cosine_similarity * 1000)."""

    @pytest.mark.parametrize(
        "similarity,expected_score",
        [
            (1.0, 1000),
            (0.5, 500),
            (0.3, 300),
            (0.0, 0),
            (0.85, 850),
            (0.123, 123),
        ],
    )
    def test_score_mapping(self, similarity: float, expected_score: int) -> None:
        index_entry = _make_index_entry()
        memory_obj = _make_memory_object()

        storage = MagicMock(spec=StorageProvider)
        storage.get_index_entry.return_value = index_entry
        storage.get_memory_object.return_value = memory_obj
        storage.get_evidence_for_memory_object.return_value = [_make_evidence()]

        vector_index = FakeVectorIndex(hits=[("idx-1", similarity)])
        embedding = FakeEmbeddingProvider()

        provider = VectorRetrievalProvider(storage, vector_index, embedding, min_similarity=0.0)
        result = provider.query("test", limit=5)

        assert len(result.results) == 1
        assert result.results[0].score == expected_score


class TestEmptyIndex:
    """Edge case: empty vector index returns empty results."""

    def test_empty_index_returns_empty(self) -> None:
        storage = MagicMock(spec=StorageProvider)
        vector_index = FakeVectorIndex(hits=[])
        embedding = FakeEmbeddingProvider()

        provider = VectorRetrievalProvider(storage, vector_index, embedding)
        result = provider.query("test", limit=5)

        assert result.results == []
        assert result.trace is None

    def test_empty_index_with_trace(self) -> None:
        storage = MagicMock(spec=StorageProvider)
        vector_index = FakeVectorIndex(hits=[])
        embedding = FakeEmbeddingProvider()

        provider = VectorRetrievalProvider(storage, vector_index, embedding)
        result = provider.query("test", limit=5, include_trace=True)

        assert result.results == []
        assert result.trace is not None
        assert result.trace.stages[0].stage_name == VECTOR_STAGE_NAME
        assert result.trace.stages[0].candidate_hits_considered == 0
        assert result.trace.stages[0].selected_hits == ()
