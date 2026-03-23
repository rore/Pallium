# Design: Decomposing core/service.py

## Status

Proposal (not yet accepted)

## Problem

`core/service.py` is 1,259 lines. `PalliumService` is a single class handling
8+ distinct responsibilities. Each responsibility has its own error handling,
storage interactions, observability emissions, and retry logic. The file is
becoming the default landing zone for new behavior because everything already
has access to all collaborators through `self`.

Concrete costs today:

- **Readability**: understanding the query path requires scrolling past 600
  lines of processing and thread rebuild code.
- **Test coupling**: test setup must construct a fully-wired `PalliumService`
  even when exercising a single responsibility.
- **Change risk**: a retention change can accidentally touch processing state
  because they share a single class namespace.
- **Onboarding**: new contributors must understand the full 1,259-line class
  before safely modifying any part of it.

## Current Responsibilities

Mapped by method group, with approximate line counts:

| # | Responsibility | Key methods | Lines |
|---|---|---|---|
| 1 | **Item ingestion** | `ingest_item`, `_build_ingest_result` | ~80 |
| 2 | **Source item processing** | `process_next_source_item`, `_process_source_item`, `drain_processing_queue`, failure classification, backoff | ~200 |
| 3 | **Thread rebuilding** | `process_next_thread_rebuild`, `_process_thread_rebuild_lease`, `_maybe_rebuild_thread_summary`, `_build_thread_processing_scope`, `_find_active_thread_memory_ids`, `_collect_thread_conclusions` | ~200 |
| 4 | **Query routing** | `query`, `_make_debug_candidate_loader`, `_evidence_matches_filters` | ~150 |
| 5 | **Consolidation** | `run_consolidation_pass`, `_build_consolidation_relations`, `_find_active_consolidated_memory_ids` | ~120 |
| 6 | **Retention management** | `run_retention_pass` | ~65 |
| 7 | **Vector embedding** | `_embed_vector_entries`, source-item vector entry creation inside `_process_source_item` | ~60 |
| 8 | **Memory supersession** | `supersede_memory_object` | ~20 |
| 9 | **Observability emission** | `_emit_processing_outcome`, `_emit_processing_failure`, `_emit_memory_creation_provenance`, `_emit_thread_rebuild_outcome` | ~80 |
| 10 | **Result building** | `_build_processing_result`, `_build_ingest_result`, `get_item_processing`, `get_queue_health` | ~60 |
| 11 | **Shared persistence** | `_persist_process_result` | ~10 |

Plus ~130 lines of module-level helpers (`_normalize_for_index`, `_query_tokens`,
`_observability_state`, `_with_observability_metadata`, `_build_memory_provenance`,
`_build_query_result_summary`, `_classify_failure`, `_preferred_active_summary_ref`).

## Proposed Extraction

### New modules inside `core/`

The extraction stays within `core/` because these are generic orchestration
concerns, not semantic-package behavior. Each new module gets a single class
and its closely-related helpers.

#### 1. `core/ingest.py` -- ItemIngestor

Owns `ingest_item` and its idempotency check, source-item creation, initial
lexical index entry, and the `_build_ingest_result` / `_build_processing_result`
result-assembly methods.

Collaborators: `StorageProvider`, `SemanticPlugin` (visibility check only).

```
class ItemIngestor:
    def __init__(self, storage, semantic_plugins, default_use_case): ...
    def ingest_item(self, ...) -> IngestResult: ...
    def get_item_processing(self, source_item_id) -> ItemProcessingResult: ...
    def get_queue_health(self, ...) -> QueueHealthSnapshot: ...
```

#### 2. `core/processing.py` -- ItemProcessor

Owns `process_next_source_item`, `_process_source_item`,
`drain_processing_queue`, failure classification, backoff calculation, and the
source-item vector entry creation that happens during processing.

Collaborators: `StorageProvider`, `SemanticPlugin`, `VectorEmbedder`,
`ThreadRebuilder`, `IntegrationDebugLogger`.

```
class ItemProcessor:
    def __init__(self, storage, semantic_plugins, default_use_case,
                 vector_embedder, thread_rebuilder, observability): ...
    def process_next_source_item(self, ...) -> ItemProcessingResult | None: ...
    def drain_processing_queue(self, ...) -> list[ItemProcessingResult]: ...
```

#### 3. `core/thread_rebuild.py` -- ThreadRebuilder

Owns `process_next_thread_rebuild`, `_process_thread_rebuild_lease`,
`_maybe_rebuild_thread_summary`, `_build_thread_processing_scope`,
`_find_active_thread_memory_ids`, `_collect_thread_conclusions`, and iteration
limiting.

Collaborators: `StorageProvider`, `SemanticPlugin`, `VectorEmbedder`,
`IntegrationDebugLogger`.

```
class ThreadRebuilder:
    def __init__(self, storage, semantic_plugins, vector_embedder,
                 observability): ...
    def process_next_thread_rebuild(self, ...) -> ThreadProcessingLease | None: ...
    def build_thread_processing_scope(self, ...) -> ThreadProcessingScope | None: ...
```

#### 4. `core/query.py` -- QueryExecutor

Owns `query`, `_make_debug_candidate_loader`, `_evidence_matches_filters`.

Collaborators: `StorageProvider`, `RetrievalProvider`, `SemanticPlugin`.

```
class QueryExecutor:
    def __init__(self, storage, retrieval, semantic_plugins,
                 default_use_case): ...
    def query(self, ...) -> QueryResult: ...
```

#### 5. `core/consolidation.py` -- ConsolidationRunner

Owns `run_consolidation_pass`, `_build_consolidation_relations`,
`_find_active_consolidated_memory_ids`, and the `supersede_memory_object`
call during consolidation.

Collaborators: `StorageProvider`, `SemanticPlugin`,
`ConsolidationCapability`, `VectorEmbedder`.

```
class ConsolidationRunner:
    def __init__(self, storage, semantic_plugins, default_use_case,
                 consolidation_capability, vector_embedder): ...
    def run_consolidation_pass(self, ...) -> ConsolidationRunResult | None: ...
```

#### 6. `core/retention.py` -- RetentionRunner

Owns `run_retention_pass`.

Collaborators: `StorageProvider`, `IntegrationDebugLogger`.

```
class RetentionRunner:
    def __init__(self, storage, observability, *, retention_enabled,
                 retention_lease_seconds, retention_batch_size): ...
    def run_retention_pass(self, ...) -> RetentionRunStats | None: ...
```

#### 7. `core/vector_embed.py` -- VectorEmbedder

Owns `_embed_vector_entries` and the source-item embedding logic currently
inline in `_process_source_item`. This is a thin internal service, not a
provider -- it composes `EmbeddingProvider` and `VectorIndex`.

Collaborators: `StorageProvider`, `EmbeddingProvider`, `VectorIndex`.

```
class VectorEmbedder:
    def __init__(self, storage, embedding_provider, vector_index): ...
    def embed_process_result(self, result: ProcessResult) -> None: ...
    def embed_source_item(self, plugin, source_item) -> IndexEntry | None: ...
    def embed_and_persist_source_vector(self, index_entry) -> None: ...
```

### Shared helpers stay in `core/service.py` or move to `core/service_helpers.py`

Module-level functions like `_normalize_for_index`, `_query_tokens`,
`_with_observability_metadata`, `_build_memory_provenance`,
`_classify_failure`, and `_preferred_active_summary_ref` either:

- Move to `core/service_helpers.py` as internal shared utilities, or
- Move into the specific module that is their sole consumer (preferred when
  there is only one).

### `supersede_memory_object` stays shared

This method is called by both `ConsolidationRunner` and `ThreadRebuilder`
(via supersession plans). It should live in a shared location accessible to
both -- either as a standalone function in `core/lifecycle.py` or kept on the
facade.

## How Composition Replaces the Monolith

`PalliumService` becomes a thin **composition root / facade**:

```python
class PalliumService:
    def __init__(self, storage, retrieval, semantic_plugins, default_use_case,
                 observability, *, retention_enabled, retention_lease_seconds,
                 retention_batch_size, embedding_provider, vector_index):
        vector_embedder = VectorEmbedder(storage, embedding_provider, vector_index)
        self._ingestor = ItemIngestor(storage, semantic_plugins, default_use_case)
        self._thread_rebuilder = ThreadRebuilder(storage, semantic_plugins,
                                                  vector_embedder, observability)
        self._processor = ItemProcessor(storage, semantic_plugins, default_use_case,
                                         vector_embedder, self._thread_rebuilder,
                                         observability)
        self._query_executor = QueryExecutor(storage, retrieval, semantic_plugins,
                                              default_use_case)
        self._consolidation_runner = ConsolidationRunner(
            storage, semantic_plugins, default_use_case,
            ConsolidationCapability(), vector_embedder)
        self._retention_runner = RetentionRunner(storage, observability,
                                                  retention_enabled=retention_enabled,
                                                  retention_lease_seconds=retention_lease_seconds,
                                                  retention_batch_size=retention_batch_size)

    # Delegate every public method
    def ingest_item(self, ...) -> IngestResult:
        return self._ingestor.ingest_item(...)

    def query(self, ...) -> QueryResult:
        return self._query_executor.query(...)

    def process_next_source_item(self, ...) -> ItemProcessingResult | None:
        return self._processor.process_next_source_item(...)

    # ... etc.
```

**The public API surface does not change.** All callers (`api/routes.py`,
`app/worker.py`, `app/cleaner.py`, eval runners, test helpers) continue to
call `PalliumService` methods. The facade delegates. No caller migration
is needed.

`app/dependencies.py` `build_service()` continues to return `PalliumService`.

## Migration Path (Incremental)

Each step is a standalone PR. Tests pass after each step. No caller changes
needed until the final optional cleanup.

### Step 1: Extract VectorEmbedder

**Why first:** It has the fewest callers (2 call sites in `_process_source_item`
and `_process_thread_rebuild_lease`), zero public API surface, and the clearest
boundary. Validates the pattern.

- Create `core/vector_embed.py` with `VectorEmbedder`.
- Wire it in `PalliumService.__init__`.
- Replace inline embedding calls with `self._vector_embedder.method()`.
- Run full test suite.

### Step 2: Extract RetentionRunner

**Why second:** `run_retention_pass` is completely self-contained. It has no
dependency on processing, query, or consolidation state. Single caller
(`app/cleaner.py` via the facade).

- Create `core/retention.py`.
- Delegate from facade.
- Run full test suite.

### Step 3: Extract QueryExecutor

**Why third:** The query path reads but never writes processing state. It
depends on `RetrievalProvider` and `SemanticPlugin` but not on the processing
pipeline. Clean read-only extraction.

- Create `core/query.py`.
- Move `_make_debug_candidate_loader` and `_evidence_matches_filters` along.
- Delegate from facade.
- Run full test suite.

### Step 4: Extract ThreadRebuilder

**Why fourth:** Thread rebuilding is called by `ItemProcessor` and by the
standalone `process_next_thread_rebuild` path. Extracting it before the
processor decouples them cleanly.

- Create `core/thread_rebuild.py`.
- Move thread-specific helpers along.
- Delegate from facade.
- Pass `ThreadRebuilder` as a collaborator to `ItemProcessor` in next step.
- Run full test suite.

### Step 5: Extract ItemProcessor

**Why fifth:** Depends on `VectorEmbedder` and `ThreadRebuilder`, both now
extracted. This is the largest extraction.

- Create `core/processing.py`.
- Move failure classification, backoff, processing-specific observability.
- Delegate from facade.
- Run full test suite.

### Step 6: Extract ConsolidationRunner

- Create `core/consolidation.py`.
- Move consolidation-specific relation building and supersession finding.
- Delegate from facade.
- Run full test suite.

### Step 7: Extract ItemIngestor

**Why last:** Simplest logic, fewest helpers. Low risk, low value relative to
earlier steps.

- Create `core/ingest.py`.
- Delegate from facade.
- Run full test suite.

### Step 8 (optional): Slim the facade

Once all responsibilities are extracted, `PalliumService` should be under
100 lines: constructor wiring + one-line delegating methods. At this point,
evaluate whether any callers should receive the inner components directly
(e.g., `app/worker.py` could take `ItemProcessor` directly). This is optional
and should not block the earlier steps.

## Risk Assessment

### Low risk

- **No public API change.** The facade preserves the existing method
  signatures. HTTP routes, workers, cleaners, eval runners, and test helpers
  are unaffected.
- **Incremental migration.** Each PR is independently shippable and
  revertible. No "big bang" commit required.
- **No new abstractions.** This is reorganization, not redesign. No new
  interfaces, protocols, or dependency injection frameworks.

### Medium risk

- **Shared state between processor and thread rebuilder.** Today
  `_process_source_item` directly calls `_process_thread_rebuild_lease`.
  After extraction, the processor needs a reference to `ThreadRebuilder`.
  This creates a one-way dependency (processor -> thread rebuilder) that
  must not become circular.
- **Observability helpers.** Several `_emit_*` methods are used only by
  processing/thread rebuild. If they reference each other or share
  intermediate state, the extraction boundary may need adjustment.
- **Module-level constants.** Constants like `DEFAULT_PROCESSING_LEASE_SECONDS`
  are imported by `app/worker.py` from `core.service`. These imports must be
  preserved or redirected.

### Mitigations

- **Dependency direction rule:** `ItemProcessor` may depend on
  `ThreadRebuilder`, but not the reverse. `VectorEmbedder` depends on
  neither. `QueryExecutor` depends on neither.
- **Constants file:** If multiple extracted modules need the same constants,
  create `core/constants.py` rather than cross-importing between siblings.
- **Integration test gate:** Each PR must pass the full 631-test suite before
  merge. The existing test coverage is high enough to catch regressions.

## What NOT to Split

### `supersede_memory_object` and `_persist_process_result`

These are shared primitives used by multiple responsibilities (thread rebuild,
consolidation, processing). They should either stay on the facade or move to
a small shared `core/lifecycle.py` module -- not be duplicated into each
extracted class.

### The facade itself

`PalliumService` should remain as the composition root and public API surface.
Removing it would force every caller to know which inner component to use,
which adds coupling rather than removing it. The facade is the stable contract.

### Plugin resolution logic

The logic that resolves `use_case` to a `SemanticPlugin` is used by ingestion,
processing, query, and consolidation. It should remain shared -- either as a
helper function or passed as a resolved plugin reference.

### `get_item_processing` and `get_queue_health`

These are lightweight read-only status methods. They could live on the facade
or on `ItemIngestor`. Splitting them into their own module would be
over-decomposition. Keep them with ingestion since they share the same
`_build_processing_result` helper.

### Module-level helper functions

Functions like `_normalize_for_index` and `_query_tokens` are pure functions
with no class state. They should move to wherever their sole consumer lives.
If shared, they go to `core/service_helpers.py` or `core/indexing.py` (which
already exists). They should not become their own module.
