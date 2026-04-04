# Vector Index Self-Healing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make vector index recovery automatic — transient LLM failures and retention gaps should self-heal without manual intervention or restarts.

**Architecture:** Three independently committable changes: (1) fix the early `return` in the processing except block so source item vector embedding always runs regardless of LLM outcome; (2) change startup mismatch from "disable vector" to "warn + continue"; (3) add bidirectional reconciliation as an idle-time worker duty that embeds missing entries and removes stale ones. Each change has its own tests and can be committed separately.

**Tech Stack:** Python 3.12, pytest (`python -m pytest tests/ -x -q`). Changes span `core/`, `storage/`, `app/`, and `tests/`.

**Spec:** `docs/specs/2026-04-04-vector-index-self-healing-design.md`

---

## File Map

| File | Change |
|---|---|
| `core/processing.py` | Task 1: remove early return, init `memory_vectors_added` before try |
| `storage/vector_index.py` | Task 3: add `known_entry_ids()` accessor |
| `core/vector_embed.py` | Task 3: add `reconcile(batch_size)` method |
| `core/service.py` | Task 4: add `reconcile_vector_index()` delegation |
| `app/dependencies.py` | Task 2: mismatch → warn + continue |
| `app/worker.py` | Task 4: add reconciliation as third idle-time duty |
| `docs/context/decisions.md` | Task 1: strengthen "Plugin-owned SourceItem embedding" entry |
| `tests/test_vector_self_healing.py` | Tasks 1-4: all new tests in one focused test file |

---

## Task 1 — Change 1: Source vector embedding survives LLM failure

**Files:**
- Modify: `core/processing.py:177-268`
- Modify: `docs/context/decisions.md:178-182`
- Create: `tests/test_vector_self_healing.py`

**Context:** `_process_source_item` in `core/processing.py` calls `build_source_item_vector_entry` at line 177 (creates SQLite vector entry) then enters a try block for the LLM call. The except block at line 240 calls `fail_source_item_processing` and then `return` at line 261, skipping the source vector embedding at lines 263-268. The fix: initialize `memory_vectors_added = False` before the try, remove the `return`, so lines 263-268 always execute.

This preserves the accepted decision at `docs/context/decisions.md:178-182`: "Decoupled from semantic processing success (persisted before processing, survives extraction failures)."

---

- [ ] **Step 1.1: Write failing test — source vector embedded even when LLM fails**

Create `tests/test_vector_self_healing.py`:

```python
"""Tests for vector index self-healing: orphan prevention, startup mismatch, reconciliation."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.contracts import ProcessResult, build_source_item
from core.models import IndexEntry
from core.processing import ItemProcessor
from core.vector_embed import VectorEmbedder
from core.thread_rebuild import ThreadRebuilder
from core.observability import IntegrationDebugLogger
from providers.embedding.base import EmbeddingProvider
from semantic.base import SemanticPlugin
from semantic.demo_agent_memory import DemoAgentMemoryPlugin
from storage.sqlite import SQLiteStorageProvider
from storage.vector_index import VectorIndex

try:
    import usearch  # noqa: F401
    HAS_USEARCH = True
except ImportError:
    HAS_USEARCH = False

requires_usearch = pytest.mark.skipif(not HAS_USEARCH, reason="usearch not installed")


class StubEmbeddingProvider(EmbeddingProvider):
    def __init__(self, dims: int = 4, model: str = "test-model") -> None:
        self._dims = dims
        self._model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * self._dims for _ in texts]

    def dimensions(self) -> int:
        return self._dims

    def model_name(self) -> str:
        return self._model


class AlwaysFailPlugin(SemanticPlugin):
    """Plugin whose process_item always raises, but provides source_item_embedding_text."""
    name = "always_fail_with_embedding"

    def process_item(self, source_item):
        raise RuntimeError("LLM connection failed")

    def source_item_embedding_text(self, source_item):
        if len(source_item.content) >= 40:
            return source_item.content
        return None


@requires_usearch
def test_source_vector_embedded_even_when_llm_fails(test_db_url: str, tmp_path: Path) -> None:
    """When process_item raises, the source item vector entry is still embedded into usearch."""
    storage = SQLiteStorageProvider(test_db_url)
    embedding_provider = StubEmbeddingProvider()
    index_path = tmp_path / "test.index"
    vector_index = VectorIndex.create_empty(index_path, dimensions=4, model_name="test-model")

    vector_embedder = VectorEmbedder(storage, embedding_provider, vector_index)
    plugin = AlwaysFailPlugin()
    plugins = {plugin.name: plugin}
    observability = IntegrationDebugLogger(enabled=False)

    thread_rebuilder = ThreadRebuilder(
        storage=storage,
        semantic_plugins=plugins,
        vector_embedder=vector_embedder,
        observability=observability,
        persist_fn=lambda r: None,
        supersede_fn=lambda a, b: None,
    )
    processor = ItemProcessor(
        storage=storage,
        semantic_plugins=plugins,
        default_use_case=plugin.name,
        vector_embedder=vector_embedder,
        thread_rebuilder=thread_rebuilder,
        observability=observability,
        persist_fn=lambda r: None,
        supersede_fn=lambda a, b: None,
        get_item_processing_fn=lambda sid: None,
    )

    source_item = build_source_item(
        source_type="chat_message",
        source_id="fail-embed-test-1",
        content_type="text/plain",
        content="Decision: use item event time for reservation ordering to avoid duplicate holds.",
        metadata=None,
        use_case=plugin.name,
    )
    storage.create_source_item(source_item)

    claimed = storage.claim_next_source_item(worker_id="test", lease_seconds=60, max_attempts=3)
    assert claimed is not None

    processor._process_source_item(claimed, max_attempts=3, worker_id="test")

    # Source item should be marked as failed (LLM error)
    after = storage.get_source_item(claimed.id)
    assert after.processing_status == "pending"  # retryable, not final

    # But the source vector entry should exist in BOTH SQLite and usearch
    sqlite_vector_entries = storage.list_index_entries_by_type("vector")
    assert len(sqlite_vector_entries) == 1

    assert vector_index.entry_count() == 1, (
        "Source vector must be in usearch even when LLM fails"
    )
```

- [ ] **Step 1.2: Run test to verify it fails**

Run: `python -m pytest tests/test_vector_self_healing.py::test_source_vector_embedded_even_when_llm_fails -x -q`

Expected: FAIL — `assert vector_index.entry_count() == 1` fails because the `return` in the except block skips embedding.

- [ ] **Step 1.3: Fix `_process_source_item` — init `memory_vectors_added` and remove `return`**

In `core/processing.py`, make two changes:

First, add `memory_vectors_added = False` before the try block (after line 177):

```python
        source_vector_entry = self._vector_embedder.build_source_item_vector_entry(plugin, source_item)

        memory_vectors_added = False
        try:
```

Second, remove the `return` at line 261 (the last line in the except block). The except block should end after `_emit_processing_failure` with no `return`:

```python
            self._emit_processing_failure(
                source_item,
                worker_id=worker_label,
                failure_category=failure_category,
                error=error,
            )

        source_vector_added = False
```

And remove the now-redundant `memory_vectors_added` assignment inside the try block — wait, no. Keep the one inside the try block at line 221. It overwrites `False` with the actual result on success. On failure, it stays `False` from the pre-try init.

- [ ] **Step 1.4: Run test to verify it passes**

Run: `python -m pytest tests/test_vector_self_healing.py::test_source_vector_embedded_even_when_llm_fails -x -q`

Expected: PASS

- [ ] **Step 1.5: Run full test suite to verify no regressions**

Run: `python -m pytest tests/ -x -q`

Expected: All pass. The removed `return` only affects source vector embedding — all success-path logic (provenance, observability) is inside the try block and unchanged.

- [ ] **Step 1.6: Update decisions.md**

In `docs/context/decisions.md`, replace lines 178-182:

```markdown
### 2026-03-20 - Plugin-owned SourceItem embedding

SourceItem vector embedding is decided by the semantic plugin, not hard-coded in
core. Decoupled from semantic processing success (persisted before processing,
survives extraction failures). Policy: messages + assistant outputs >= 40 chars.
```

With:

```markdown
### 2026-03-20 - Plugin-owned SourceItem embedding

SourceItem vector embedding is decided by the semantic plugin, not hard-coded in
core. Decoupled from semantic processing success (persisted before processing,
survives extraction failures). The usearch embedding also runs regardless of LLM
outcome — the source item is vector-searchable even during sustained LLM outages.
Policy: messages + assistant outputs >= 40 chars.
```

- [ ] **Step 1.7: Commit**

```bash
git add core/processing.py tests/test_vector_self_healing.py docs/context/decisions.md
git commit -m "fix: embed source item vector entry regardless of LLM outcome

Remove early return in _process_source_item except block so the source
vector embedding at lines 263-268 always runs. Preserves the accepted
decision that source item embedding is decoupled from processing success."
```

---

## Task 2 — Change 2: Startup mismatch — warn and continue

**Files:**
- Modify: `app/dependencies.py:261-273`
- Modify: `tests/test_vector_startup.py:424-475`

**Context:** `build_service` in `app/dependencies.py` has a count reconciliation check at lines 261-273. When `sqlite_count != index_count`, it sets `vector_index = None` and `embedding_provider = None`, disabling vector entirely. Change this to a `WARNING` log and continue.

---

- [ ] **Step 2.1: Update existing mismatch test to expect warning, not disable**

In `tests/test_vector_startup.py`, replace the `TestCountMismatch` class (lines 424-475) with:

```python
class TestCountMismatch:

    def test_count_mismatch_logs_warning_and_keeps_vector_enabled(self, tmp_path: Path, monkeypatch, caplog) -> None:
        """When SQLite and index entry counts differ, a warning is logged but vector stays enabled."""
        from app.config import EmbeddingProviderConfig
        from storage.vector_index import VectorIndex

        index_path = tmp_path / "test.index"

        mock_index = MagicMock(spec=VectorIndex)
        mock_index.entry_count.return_value = 3
        mock_index.model_name = "test-model"

        stub_provider = StubEmbeddingProvider(model="test-model")

        # Mock storage to return a different count
        mock_storage = MagicMock()
        mock_storage.count_index_entries_by_type.return_value = 5

        config = _minimal_config(
            vector_index=VectorIndexConfig(
                enabled=True,
                index_path=str(index_path),
                embedding_provider="local",
            ),
            embedding_providers={
                "local": EmbeddingProviderConfig(
                    name="local", kind="fastembed", model="test-model",
                ),
            },
        )

        monkeypatch.setattr(
            "app.dependencies.build_embedding_provider",
            lambda config, *, provider_name: stub_provider,
        )
        monkeypatch.setattr(
            "app.dependencies._load_or_create_vector_index",
            lambda config, provider: mock_index,
        )
        monkeypatch.setattr(
            "app.dependencies.build_storage_provider",
            lambda config: mock_storage,
        )

        with caplog.at_level(logging.WARNING):
            service = build_service(config)

        # Vector stays enabled despite mismatch
        assert isinstance(service._retrieval, CompositeRetrievalProvider)
        assert service._vector_index is mock_index
        assert service._embedding_provider is stub_provider
        assert "mismatch" in caplog.text.lower()
```

- [ ] **Step 2.2: Run test to verify it fails**

Run: `python -m pytest tests/test_vector_startup.py::TestCountMismatch -x -q`

Expected: FAIL — `assert isinstance(service._retrieval, CompositeRetrievalProvider)` fails because the current code disables vector on mismatch.

- [ ] **Step 2.3: Change mismatch from disable to warn**

In `app/dependencies.py`, replace the count reconciliation block (lines 261-273):

```python
        # 4. Count reconciliation check — must run before building retrieval provider
        if vector_index is not None and embedding_provider is not None:
            sqlite_count = storage.count_index_entries_by_type("vector")
            index_count = vector_index.entry_count()
            if sqlite_count != index_count:
                logger.error(
                    "Vector index count mismatch: SQLite=%d, index=%d. "
                    "Vector disabled to prevent native crash. Run rebuild-vector-index to fix.",
                    sqlite_count,
                    index_count,
                )
                vector_index = None
                embedding_provider = None
```

With:

```python
        # 4. Count reconciliation check — warn but continue; runtime reconciliation fills gaps
        if vector_index is not None and embedding_provider is not None:
            sqlite_count = storage.count_index_entries_by_type("vector")
            index_count = vector_index.entry_count()
            if sqlite_count != index_count:
                logger.warning(
                    "Vector index count mismatch: SQLite=%d, index=%d. "
                    "Continuing with reduced recall; runtime reconciliation will backfill.",
                    sqlite_count,
                    index_count,
                )
```

- [ ] **Step 2.4: Run test to verify it passes**

Run: `python -m pytest tests/test_vector_startup.py::TestCountMismatch -x -q`

Expected: PASS

- [ ] **Step 2.5: Run full test suite**

Run: `python -m pytest tests/ -x -q`

Expected: All pass.

- [ ] **Step 2.6: Commit**

```bash
git add app/dependencies.py tests/test_vector_startup.py
git commit -m "fix: warn on vector index count mismatch instead of disabling

Transient failures should not permanently degrade vector retrieval.
The vector index works correctly for entries it has; runtime
reconciliation fills gaps."
```

---

## Task 3 — Change 3: Bidirectional reconciliation on VectorEmbedder

**Files:**
- Modify: `storage/vector_index.py`
- Modify: `core/vector_embed.py`
- Modify: `tests/test_vector_self_healing.py`

**Context:** Add `known_entry_ids()` to `VectorIndex` and `reconcile(batch_size)` to `VectorEmbedder`. The reconcile method finds SQLite entries missing from usearch (forward — embed) and usearch entries missing from SQLite (reverse — remove). Returns total count of changes.

---

- [ ] **Step 3.1: Write failing test — `known_entry_ids` accessor**

Append to `tests/test_vector_self_healing.py`:

```python
@requires_usearch
def test_vector_index_known_entry_ids(tmp_path: Path) -> None:
    index_path = tmp_path / "ids.index"
    vi = VectorIndex.create_empty(index_path, dimensions=4, model_name="test-model")
    assert vi.known_entry_ids() == frozenset()

    vi.add("entry-a", [0.1, 0.2, 0.3, 0.4])
    vi.add("entry-b", [0.5, 0.6, 0.7, 0.8])
    assert vi.known_entry_ids() == frozenset({"entry-a", "entry-b"})

    vi.remove("entry-a")
    assert vi.known_entry_ids() == frozenset({"entry-b"})
```

- [ ] **Step 3.2: Run test to verify it fails**

Run: `python -m pytest tests/test_vector_self_healing.py::test_vector_index_known_entry_ids -x -q`

Expected: FAIL — `AttributeError: 'VectorIndex' object has no attribute 'known_entry_ids'`

- [ ] **Step 3.3: Implement `known_entry_ids` on VectorIndex**

In `storage/vector_index.py`, add after the `dimensions` property (after line 151):

```python
    def known_entry_ids(self) -> frozenset[str]:
        """Return the set of entry IDs currently in the index."""
        return frozenset(self._id_to_key.keys())
```

- [ ] **Step 3.4: Run test to verify it passes**

Run: `python -m pytest tests/test_vector_self_healing.py::test_vector_index_known_entry_ids -x -q`

Expected: PASS

- [ ] **Step 3.5: Write failing tests — reconciliation forward, reverse, no-op, batch**

Append to `tests/test_vector_self_healing.py`:

```python
@requires_usearch
def test_reconcile_forward_embeds_missing_entries(test_db_url: str, tmp_path: Path) -> None:
    """Entries in SQLite but not in usearch are embedded by reconciliation."""
    storage = SQLiteStorageProvider(test_db_url)
    embedding_provider = StubEmbeddingProvider()
    index_path = tmp_path / "reconcile.index"
    vector_index = VectorIndex.create_empty(index_path, dimensions=4, model_name="test-model")

    vector_embedder = VectorEmbedder(storage, embedding_provider, vector_index)

    # Create a vector index entry in SQLite only (simulating an orphan)
    from core.indexing import build_index_entry
    orphan_entry = build_index_entry(
        target_kind="source_item",
        target_id="orphan-source-1",
        index_type="vector",
        text_view="Some text that should be embedded",
        text_view_name="source_content.embedding",
    )
    storage.create_index_entry(orphan_entry)

    assert storage.count_index_entries_by_type("vector") == 1
    assert vector_index.entry_count() == 0

    reconciled = vector_embedder.reconcile(batch_size=50)

    assert reconciled == 1
    assert vector_index.entry_count() == 1
    assert orphan_entry.id in vector_index.known_entry_ids()


@requires_usearch
def test_reconcile_reverse_removes_stale_entries(test_db_url: str, tmp_path: Path) -> None:
    """Entries in usearch but not in SQLite are removed by reconciliation."""
    storage = SQLiteStorageProvider(test_db_url)
    embedding_provider = StubEmbeddingProvider()
    index_path = tmp_path / "reconcile.index"
    vector_index = VectorIndex.create_empty(index_path, dimensions=4, model_name="test-model")

    vector_embedder = VectorEmbedder(storage, embedding_provider, vector_index)

    # Add an entry to usearch only (simulating retention deleting the SQLite row)
    vector_index.add("stale-entry-1", [0.1, 0.2, 0.3, 0.4])
    assert vector_index.entry_count() == 1
    assert storage.count_index_entries_by_type("vector") == 0

    reconciled = vector_embedder.reconcile(batch_size=50)

    assert reconciled == 1
    assert vector_index.entry_count() == 0


@requires_usearch
def test_reconcile_noop_when_counts_match(test_db_url: str, tmp_path: Path) -> None:
    """When SQLite and usearch counts match, reconciliation is a no-op."""
    storage = SQLiteStorageProvider(test_db_url)
    embedding_provider = StubEmbeddingProvider()
    index_path = tmp_path / "reconcile.index"
    vector_index = VectorIndex.create_empty(index_path, dimensions=4, model_name="test-model")

    vector_embedder = VectorEmbedder(storage, embedding_provider, vector_index)

    # Both empty — counts match
    reconciled = vector_embedder.reconcile(batch_size=50)
    assert reconciled == 0


@requires_usearch
def test_reconcile_forward_respects_batch_size(test_db_url: str, tmp_path: Path) -> None:
    """Forward reconciliation embeds at most batch_size entries per call."""
    storage = SQLiteStorageProvider(test_db_url)
    embedding_provider = StubEmbeddingProvider()
    index_path = tmp_path / "reconcile.index"
    vector_index = VectorIndex.create_empty(index_path, dimensions=4, model_name="test-model")

    vector_embedder = VectorEmbedder(storage, embedding_provider, vector_index)

    # Create 5 orphan entries in SQLite
    from core.indexing import build_index_entry
    for i in range(5):
        entry = build_index_entry(
            target_kind="source_item",
            target_id=f"batch-source-{i}",
            index_type="vector",
            text_view=f"Text for batch entry {i}",
            text_view_name="source_content.embedding",
        )
        storage.create_index_entry(entry)

    assert storage.count_index_entries_by_type("vector") == 5
    assert vector_index.entry_count() == 0

    # Reconcile with batch_size=2 — should embed exactly 2
    reconciled = vector_embedder.reconcile(batch_size=2)
    assert reconciled == 2
    assert vector_index.entry_count() == 2

    # Second call embeds 2 more
    reconciled = vector_embedder.reconcile(batch_size=2)
    assert reconciled == 2
    assert vector_index.entry_count() == 4

    # Third call embeds the last 1
    reconciled = vector_embedder.reconcile(batch_size=2)
    assert reconciled == 1
    assert vector_index.entry_count() == 5


@requires_usearch
def test_reconcile_noop_when_disabled(test_db_url: str) -> None:
    """Reconciliation returns 0 when embedding_provider or vector_index is None."""
    storage = SQLiteStorageProvider(test_db_url)
    embedder_no_provider = VectorEmbedder(storage, None, None)
    assert embedder_no_provider.reconcile(batch_size=50) == 0
```

- [ ] **Step 3.6: Run tests to verify they fail**

Run: `python -m pytest tests/test_vector_self_healing.py -k "reconcile" -x -q`

Expected: FAIL — `AttributeError: 'VectorEmbedder' object has no attribute 'reconcile'`

- [ ] **Step 3.7: Implement `reconcile` on VectorEmbedder**

In `core/vector_embed.py`, add after the `save_vector_index` method (after line 139):

```python
    def reconcile(self, batch_size: int = 50) -> int:
        """Find and fix mismatches between SQLite vector entries and usearch index.

        Forward direction: embed SQLite entries missing from usearch (batch-bounded).
        Reverse direction: remove usearch entries missing from SQLite (unbounded, cheap).
        Returns total number of entries changed (embedded + removed).
        """
        if self._embedding_provider is None or self._vector_index is None:
            return 0
        try:
            sqlite_count = self._storage.count_index_entries_by_type("vector")
            index_count = self._vector_index.entry_count()
            if sqlite_count == index_count:
                return 0

            sqlite_entries = self._storage.list_index_entries_by_type("vector")
            sqlite_ids = {e.id for e in sqlite_entries}
            usearch_ids = self._vector_index.known_entry_ids()

            total_changed = 0

            # Reverse: remove stale usearch entries (cheap, no batching)
            stale_ids = usearch_ids - sqlite_ids
            for entry_id in stale_ids:
                try:
                    self._vector_index.remove(entry_id)
                    total_changed += 1
                except KeyError:
                    pass

            # Forward: embed missing entries (batch-bounded)
            missing_entries = [e for e in sqlite_entries if e.id not in usearch_ids]
            batch = missing_entries[:batch_size]
            if batch:
                texts = [e.text_view for e in batch]
                vectors = self._embedding_provider.embed(texts)
                for entry, vector in zip(batch, vectors):
                    self._vector_index.add(entry.id, vector)
                    total_changed += 1

            if total_changed > 0:
                self._vector_index.save()

            return total_changed
        except Exception:
            self._logger.warning("Vector reconciliation failed; will retry next cycle", exc_info=True)
            return 0
```

- [ ] **Step 3.8: Run reconciliation tests**

Run: `python -m pytest tests/test_vector_self_healing.py -k "reconcile" -x -q`

Expected: All PASS

- [ ] **Step 3.9: Run full test suite**

Run: `python -m pytest tests/ -x -q`

Expected: All pass.

- [ ] **Step 3.10: Commit**

```bash
git add storage/vector_index.py core/vector_embed.py tests/test_vector_self_healing.py
git commit -m "feat: add bidirectional vector index reconciliation

VectorIndex.known_entry_ids() exposes the set of indexed entry IDs.
VectorEmbedder.reconcile() finds SQLite entries missing from usearch
(embeds them) and usearch entries missing from SQLite (removes them).
Batch-bounded forward direction, cheap unbounded reverse direction."
```

---

## Task 4 — Change 3 continued: Worker loop integration

**Files:**
- Modify: `core/service.py`
- Modify: `app/worker.py`
- Modify: `tests/test_vector_self_healing.py`

**Context:** Add `reconcile_vector_index()` delegation to `PalliumService`. Add reconciliation as the third idle-time duty in the worker loop in `app/worker.py`, following the same pattern as thread rebuilds. Add a `_log_reconciliation` helper matching the existing `_log_result` / `_log_thread_rebuild` pattern.

---

- [ ] **Step 4.1: Write failing test — service delegation**

Append to `tests/test_vector_self_healing.py`:

```python
@requires_usearch
def test_service_reconcile_vector_index_delegates(test_db_url: str, tmp_path: Path) -> None:
    """PalliumService.reconcile_vector_index() delegates to VectorEmbedder.reconcile()."""
    from core.service import PalliumService
    from retrieval.lexical import LexicalRetrievalProvider

    storage = SQLiteStorageProvider(test_db_url)
    embedding_provider = StubEmbeddingProvider()
    index_path = tmp_path / "svc.index"
    vector_index = VectorIndex.create_empty(index_path, dimensions=4, model_name="test-model")
    retrieval = LexicalRetrievalProvider(storage)
    plugins = {"demo_agent_memory": DemoAgentMemoryPlugin()}

    service = PalliumService(
        storage=storage,
        retrieval=retrieval,
        semantic_plugins=plugins,
        default_use_case="demo_agent_memory",
        embedding_provider=embedding_provider,
        vector_index=vector_index,
    )

    # Both empty — should return 0
    result = service.reconcile_vector_index()
    assert result == 0
```

- [ ] **Step 4.2: Run test to verify it fails**

Run: `python -m pytest tests/test_vector_self_healing.py::test_service_reconcile_vector_index_delegates -x -q`

Expected: FAIL — `AttributeError: 'PalliumService' object has no attribute 'reconcile_vector_index'`

- [ ] **Step 4.3: Add `reconcile_vector_index` to PalliumService**

In `core/service.py`, add after the `process_next_thread_rebuild` method (after line 283):

```python
    def reconcile_vector_index(self) -> int:
        """Reconcile SQLite ↔ usearch vector index gaps. Returns count of changes."""
        return self._vector_embedder.reconcile()
```

- [ ] **Step 4.4: Run test to verify it passes**

Run: `python -m pytest tests/test_vector_self_healing.py::test_service_reconcile_vector_index_delegates -x -q`

Expected: PASS

- [ ] **Step 4.5: Write failing test — worker loop calls reconciliation**

Append to `tests/test_vector_self_healing.py`:

```python
def test_worker_loop_calls_reconciliation_when_idle(test_db_url: str, monkeypatch) -> None:
    """Worker calls reconcile_vector_index when no source items or thread rebuilds pending."""
    from app.worker import run_worker
    from app.config import AppConfig
    from storage.vector_index import VectorIndexConfig

    reconcile_calls = []

    class TrackingService:
        def __init__(self, real_service):
            self._real = real_service

        def __getattr__(self, name):
            if name == "reconcile_vector_index":
                def tracked():
                    reconcile_calls.append(1)
                    return 0
                return tracked
            return getattr(self._real, name)

    from core.service import PalliumService
    from retrieval.lexical import LexicalRetrievalProvider

    storage = SQLiteStorageProvider(test_db_url)
    retrieval = LexicalRetrievalProvider(storage)
    plugins = {"demo_agent_memory": DemoAgentMemoryPlugin()}
    real_service = PalliumService(
        storage=storage,
        retrieval=retrieval,
        semantic_plugins=plugins,
        default_use_case="demo_agent_memory",
    )

    tracking_service = TrackingService(real_service)

    monkeypatch.setattr(
        "app.worker.build_service",
        lambda config: tracking_service,
    )

    run_worker(["--once"], config=AppConfig(
        storage_backend="sqlite",
        sqlite_url=test_db_url,
        default_use_case="demo_agent_memory",
        vector_index=VectorIndexConfig(enabled=False),
    ))

    assert len(reconcile_calls) >= 1, "Worker should call reconcile_vector_index when idle"
```

- [ ] **Step 4.6: Run test to verify it fails**

Run: `python -m pytest tests/test_vector_self_healing.py::test_worker_loop_calls_reconciliation_when_idle -x -q`

Expected: FAIL — `assert len(reconcile_calls) >= 1` fails because the worker doesn't call reconciliation yet.

- [ ] **Step 4.7: Add reconciliation to the worker loop**

In `app/worker.py`, add the reconciliation helper function after `_log_thread_rebuild` (after line 109):

```python
def _log_reconciliation(worker_id: str, reconciled: int) -> None:
    emit_runtime_log(
        "processor",
        f"worker_id={worker_id} vector_reconciliation changes={reconciled}",
    )
```

Then modify the worker loop (inside the `with graceful_stop` block). After the `_try_thread_rebuild` idle-time block (lines 79-83), add the reconciliation block:

```python
                if _try_thread_rebuild():
                    last_rebuild_check = clock()
                    if parsed.once or _stopping():
                        return 0
                    continue
                reconciled = service.reconcile_vector_index()
                if reconciled > 0:
                    _log_reconciliation(worker_id, reconciled)
                    if parsed.once or _stopping():
                        return 0
                    continue
                if parsed.once or _stopping():
```

- [ ] **Step 4.8: Run test to verify it passes**

Run: `python -m pytest tests/test_vector_self_healing.py::test_worker_loop_calls_reconciliation_when_idle -x -q`

Expected: PASS

- [ ] **Step 4.9: Run full test suite**

Run: `python -m pytest tests/ -x -q`

Expected: All pass.

- [ ] **Step 4.10: Commit**

```bash
git add core/service.py app/worker.py tests/test_vector_self_healing.py
git commit -m "feat: add vector reconciliation as worker idle-time duty

Worker loop now tries reconciliation when no source items or thread
rebuilds are pending. Reconciliation yields to higher-priority work
between batches. Logs reconciliation activity via runtime logging."
```

---

## Task 5 — Final verification and state update

**Files:**
- Modify: `docs/context/state.md`

---

- [ ] **Step 5.1: Run full test suite**

Run: `python -m pytest tests/ -x -q`

Expected: All pass.

- [ ] **Step 5.2: Update state.md**

Add to the end of the "Current Baseline" section in `docs/context/state.md`:

```markdown
- vector index self-healing is shipped:
  - source item vector embedding runs regardless of LLM outcome (survives extraction failures)
  - startup count mismatch logs a warning and continues with reduced recall instead of disabling vector
  - worker-integrated bidirectional reconciliation: embeds SQLite entries missing from usearch (batch-bounded), removes stale usearch entries missing from SQLite
  - reconciliation runs as idle-time worker duty alongside source item processing and thread rebuilds
  - `rebuild-vector-index` CLI command remains available for manual recovery
```

- [ ] **Step 5.3: Commit**

```bash
git add docs/context/state.md
git commit -m "docs: update state with vector index self-healing"
```
