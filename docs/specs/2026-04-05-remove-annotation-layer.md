# Remove Persisted Annotation Layer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the persisted Annotation model, DB table, storage methods, and all annotation fields from the core data model, API surface, and processing pipeline — the annotation layer is a dead abstraction whose data is fully duplicated in MemoryObjects.

**Architecture:** Pure deletion refactor. The `Annotation` dataclass, `AnnotationRecord` ORM model, `annotations` DB table, and all code that creates/reads/persists/deletes annotations are removed. The `ProcessResult.annotations` field is removed. API response fields `annotation_ids` and `annotation_count` are removed. The one functional dependency (`_semantic_provenance_from_process_result`) is simplified to read only from memory_objects. The transient `SemanticExtraction` and routing `_routing_annotations.py` (transient dict keys) are NOT touched.

**Tech Stack:** Python 3.12+, SQLAlchemy, Pydantic 2, pytest

---

## File Map

### Files to modify

| File | Responsibility | What changes |
|------|---------------|-------------|
| `core/models.py` | Domain model | Delete `Annotation` dataclass |
| `core/contracts.py` | Processing contracts | Remove `annotations` from `ProcessResult`, `annotation_ids`/`annotation_count` from `IngestResult`/`ItemProcessingResult` |
| `api/schemas.py` | Pydantic API models | Remove `annotation_ids`/`annotation_count` from response schemas |
| `storage/sqlite_schema.py` | ORM schema | Delete `AnnotationRecord` class |
| `storage/sqlite_codec.py` | DB codec | Delete `_to_annotation` method, remove `Annotation`/`AnnotationRecord` imports |
| `storage/base.py` | Storage ABC | Delete `create_annotation`, `get_annotation`, `list_annotations_for_source_item` |
| `storage/sqlite.py` | Storage impl | Delete annotation methods |
| `storage/sqlite_queue.py` | Queue persistence | Remove annotation loop from `_persist_process_result_in_session` |
| `storage/sqlite_retention.py` | Retention cleanup | Remove annotation cascade delete |
| `semantic/common.py` | Shared build logic | Remove annotation construction from `build_process_result` |
| `semantic/agent_conversation_memory.py` | Production plugin | Remove `annotations=` pass-through |
| `semantic/agent_conversation_memory_memory.py` | Constraint memory | Remove annotation scan from `_semantic_provenance_from_process_result` |
| `semantic/agent_conversation_memory_threads.py` | Thread aggregation | Remove `annotations=[]` from ProcessResult constructions |
| `core/service.py` | Service orchestrator | Remove annotation reads/writes from `_build_processing_result`, `_persist_process_result`, `_build_ingest_result` |
| `core/processing.py` | Processing pipeline | Remove `annotation_count` observability, remove `annotations=` from ProcessResult wrapping |
| `core/thread_rebuild.py` | Thread rebuild | Remove `annotations=` from ProcessResult wrapping |
| `core/consolidation_runner.py` | Consolidation | Remove `annotations=` from ProcessResult wrapping |
| `docs/http-api.md` | API docs | Remove annotation_ids from documented fields |

### Files NOT touched (confirmed unrelated)

| File | Why untouched |
|------|--------------|
| `semantic/agent_conversation_memory_routing_annotations.py` | Transient scoring dict keys, not the persisted annotation model |
| `tests/test_routing_annotations.py` | Tests the routing module above, not persisted annotations |
| `semantic/common.py` `SemanticExtraction` | Transient extraction artifact, stays as-is |

---

### Task 1: Remove annotation construction from `semantic/common.py`

**Files:**
- Modify: `semantic/common.py:8` (remove `Annotation` import), `semantic/common.py:253-261` (remove summary annotation), `semantic/common.py:286-294` (remove decision annotation), `semantic/common.py:344-352` (remove investigation annotation), `semantic/common.py:482-483` (remove `annotations=` from ProcessResult)

- [ ] **Step 1: Remove `Annotation` import and annotation construction from `build_process_result`**

In `semantic/common.py`:

1. Remove `Annotation` from the import at line 8
2. Delete the `annotations` list initialization at lines 253-261 (the summary Annotation)
3. Delete the `annotations.append(Annotation(...))` block at lines 286-294 (decision typed_candidate)
4. Delete the `annotations.append(Annotation(...))` block at lines 344-352 (investigation typed_candidate)
5. Change the ProcessResult construction at line 482 from `annotations=annotations,` to remove that field entirely (it will use the default once we update the dataclass)

After this step, `build_process_result` no longer creates any Annotation objects. The `candidate_payload` dicts that were used only for annotation payloads can also be deleted (lines 274-285 for decision, lines 332-343 for investigation) since they duplicate what's in the MemoryObject payload.

- [ ] **Step 2: Verify common.py changes compile**

Run: `python -c "from semantic.common import build_process_result"`

This will fail until ProcessResult.annotations is removed in Task 2. That's expected — proceed.

---

### Task 2: Remove `annotations` from `ProcessResult` and annotation fields from contracts

**Files:**
- Modify: `core/contracts.py:8` (remove `Annotation` import), `core/contracts.py:32` (remove `annotations` field from `ProcessResult`), `core/contracts.py:44` (remove `annotation_ids` from `IngestResult`), `core/contracts.py:55` (remove from `as_dict`), `core/contracts.py:74` (remove `annotation_ids` from `ItemProcessingResult`), `core/contracts.py:79` (remove `annotation_count`), `core/contracts.py:94` (remove from `as_dict`)

- [ ] **Step 1: Remove annotation fields from contracts**

In `core/contracts.py`:

1. Remove `Annotation` from the import on line 8
2. Remove `annotations: list[Annotation]` from `ProcessResult` (line 32)
3. Remove `annotation_ids: list[str]` from `IngestResult` (line 44) and its entry in `as_dict()` (line 55)
4. Remove `annotation_ids: list[str]` from `ItemProcessingResult` (line 74), `annotation_count: int = 0` (line 79), and both entries in `as_dict()` (lines 94, 99)

- [ ] **Step 2: Verify contracts compile**

Run: `python -c "from core.contracts import ProcessResult, IngestResult, ItemProcessingResult"`

Expected: PASS

---

### Task 3: Remove `Annotation` dataclass from core model

**Files:**
- Modify: `core/models.py:61-69` (delete Annotation dataclass)

- [ ] **Step 1: Delete the `Annotation` dataclass**

In `core/models.py`, delete lines 61-69 (the full `Annotation` dataclass definition).

- [ ] **Step 2: Verify model compiles**

Run: `python -c "from core.models import SourceItem, MemoryObject"`

Expected: PASS

---

### Task 4: Remove annotation from storage layer

**Files:**
- Modify: `storage/sqlite_schema.py:53-62` (delete `AnnotationRecord`)
- Modify: `storage/sqlite_codec.py:8,22,72-81` (remove Annotation import, AnnotationRecord import, `_to_annotation` method)
- Modify: `storage/base.py:8,335-352` (remove Annotation import, delete 3 abstract methods)
- Modify: `storage/sqlite.py:7,14,114-139` (remove imports, delete 3 methods)
- Modify: `storage/sqlite_queue.py:23,456-468` (remove AnnotationRecord import, delete annotation persistence loop)
- Modify: `storage/sqlite_retention.py:25,604,616-617` (remove AnnotationRecord import, delete annotation cascade query+delete)

- [ ] **Step 1: Delete `AnnotationRecord` from schema**

In `storage/sqlite_schema.py`, delete lines 53-62 (the full `AnnotationRecord` class).

- [ ] **Step 2: Remove annotation codec**

In `storage/sqlite_codec.py`:
1. Remove `Annotation` from the `core.models` import (line 8)
2. Remove `AnnotationRecord` from the `storage.sqlite_schema` import (line 22)
3. Delete the `_to_annotation` static method (lines 72-81)

- [ ] **Step 3: Remove annotation abstract methods from storage base**

In `storage/base.py`:
1. Remove `Annotation` from the `core.models` import (line 8)
2. Delete `create_annotation` abstract method (lines 335-336)
3. Delete `get_annotation` abstract method (lines 347-348)
4. Delete `list_annotations_for_source_item` abstract method (lines 351-352)

- [ ] **Step 4: Remove annotation methods from SQLite storage**

In `storage/sqlite.py`:
1. Remove `Annotation` from imports (line 7)
2. Remove `AnnotationRecord` from imports (line 14)
3. Delete `create_annotation` method (lines 114-125)
4. Delete `get_annotation` method (lines 127-132)
5. Delete `list_annotations_for_source_item` method (lines 134-139)

- [ ] **Step 5: Remove annotation persistence from queue**

In `storage/sqlite_queue.py`:
1. Remove `AnnotationRecord` from imports (line 23)
2. Delete the annotation loop in `_persist_process_result_in_session` (lines 457-468)

- [ ] **Step 6: Remove annotation cascade from retention**

In `storage/sqlite_retention.py`:
1. Remove `AnnotationRecord` from imports (line 25)
2. Delete the annotation query at line 604: `annotation_records = session.scalars(select(AnnotationRecord).where(AnnotationRecord.source_item_id == source_item_id)).all()`
3. Delete the annotation delete loop at lines 616-617: `for annotation in annotation_records: session.delete(annotation)`

- [ ] **Step 7: Verify storage layer compiles**

Run: `python -c "from storage.sqlite import SQLiteStorageProvider; from storage.sqlite_queue import SQLiteQueueMixin"`

Expected: PASS

---

### Task 5: Remove annotation references from service, processing, thread_rebuild, consolidation

**Files:**
- Modify: `core/service.py:333-380,445-447` (remove annotation reads/writes)
- Modify: `core/processing.py:201,208-209,288` (remove annotation observability and pass-through)
- Modify: `core/thread_rebuild.py:217` (remove `annotations=` from ProcessResult)
- Modify: `core/consolidation_runner.py:76` (remove `annotations=` from ProcessResult)

- [ ] **Step 1: Clean up `core/service.py`**

1. In `_build_processing_result` (line 346-379):
   - Delete line 347: `annotations = self._storage.list_annotations_for_source_item(source_item.id)`
   - Remove `annotation_ids=[item.id for item in annotations],` (line 370)
   - Remove `annotation_count=int(observability.get("annotation_count", len(annotations))),` (line 375)

2. In `_build_ingest_result` (line 333-344):
   - Remove `annotation_ids=processing.annotation_ids,` (line 337)

3. In `_persist_process_result` (line 445-453):
   - Delete lines 446-447 (the annotation persistence loop)

- [ ] **Step 2: Clean up `core/processing.py`**

1. Remove `"annotation_count": len(direct_result.annotations),` from observability metadata (line 201)
2. Remove `annotations=direct_result.annotations,` from ProcessResult wrapping (line 209)
3. Remove `produced_annotation_count=len(result.annotations),` from event emission (line 288)

- [ ] **Step 3: Clean up `core/thread_rebuild.py`**

Remove `annotations=thread_result.annotations,` from ProcessResult construction (line 217)

- [ ] **Step 4: Clean up `core/consolidation_runner.py`**

Remove `annotations=synthesized.annotations,` from ProcessResult construction (line 76)

- [ ] **Step 5: Verify core layer compiles**

Run: `python -c "from core.service import PalliumService; from core.processing import SourceItemProcessor"`

Expected: PASS

---

### Task 6: Simplify provenance relay and plugin pass-through

**Files:**
- Modify: `semantic/agent_conversation_memory_memory.py:89-94` (remove annotation scan)
- Modify: `semantic/agent_conversation_memory.py:92` (remove `annotations=` pass-through)
- Modify: `semantic/agent_conversation_memory_threads.py:529,780,879` (remove `annotations=[]`)

- [ ] **Step 1: Simplify `_semantic_provenance_from_process_result`**

In `semantic/agent_conversation_memory_memory.py`, replace lines 89-100 with:

```python
def _semantic_provenance_from_process_result(result: ProcessResult) -> dict[str, object]:
    for memory_object in result.memory_objects:
        payload = memory_object.payload if isinstance(memory_object.payload, dict) else {}
        semantic_provenance = payload.get("semantic_provenance")
        if isinstance(semantic_provenance, dict) and semantic_provenance:
            return dict(semantic_provenance)
    return {}
```

- [ ] **Step 2: Remove annotation pass-through in plugin**

In `semantic/agent_conversation_memory.py`, remove `annotations=direct_result.annotations,` from the ProcessResult construction (line 92).

- [ ] **Step 3: Remove `annotations=[]` from thread aggregation**

In `semantic/agent_conversation_memory_threads.py`, remove the `annotations=[],` lines at approximately lines 529, 780, 879 (three ProcessResult constructions).

- [ ] **Step 4: Verify semantic layer compiles**

Run: `python -c "from semantic.agent_conversation_memory import AgentConversationMemoryPlugin"`

Expected: PASS

---

### Task 7: Remove annotation fields from API schemas and docs

**Files:**
- Modify: `api/schemas.py:59,85,90` (remove annotation fields from response models)
- Modify: `docs/http-api.md:107-108,141` (remove annotation_ids documentation)

- [ ] **Step 1: Remove annotation fields from Pydantic schemas**

In `api/schemas.py`:
1. Remove `annotation_ids: list[str]` from `ItemCreateResponse` (line 59)
2. Remove `annotation_ids: list[str]` from `ProcessingStatusResponse` (line 85)
3. Remove `annotation_count: int = 0` from `ProcessingStatusResponse` (line 90)

- [ ] **Step 2: Update API docs**

In `docs/http-api.md`:
1. Remove lines 107-108 mentioning `annotation_ids`
2. Remove "produced annotation" mention in the `/items/{source_item_id}/processing` section (line 141)

- [ ] **Step 3: Verify API compiles**

Run: `python -c "from api.schemas import ItemCreateResponse, ProcessingStatusResponse"`

Expected: PASS

---

### Task 8: Fix all tests

**Files:**
- Modify: `tests/test_storage_sqlite.py` (remove annotation round-trip test)
- Modify: `tests/test_thread_aggregation.py` (remove annotation assertion)
- Modify: `tests/test_semantic_llm_plugin.py` (remove `result.annotations` assertions)
- Modify: `tests/test_api.py` (remove `annotation_ids` assertions)
- Modify: `tests/test_async_worker.py` (remove `annotations=[]` from ProcessResult fixtures, remove `annotation_ids` assertions)
- Modify: `tests/test_observability.py` (remove `annotation_count` assertion)
- Modify: `tests/test_source_item_embedding.py` (remove `annotations=[]` from ProcessResult fixtures)
- Modify: any other test file that references `annotations=[]` in ProcessResult construction or asserts on `annotation_ids`/`annotation_count`

- [ ] **Step 1: Find all test files that need changes**

Run: `grep -rn "annotation" tests/ --include="*.py" | grep -v "from __future__" | grep -v "routing_annotations"` to get the exhaustive list.

- [ ] **Step 2: Fix each test file**

For each file found:
- Remove `annotations=[]` from any `ProcessResult(...)` construction
- Remove assertions on `result.annotations`, `annotation_ids`, `annotation_count`
- Remove annotation-specific test functions (e.g., `test_sqlite_storage_provider_contract` annotation round-trip, `test_low_value_meta_item_keeps_raw_source_and_summary_annotation_without_durable_memory`)
- Keep test functions that test non-annotation behavior — only remove the annotation-specific assertions within them

- [ ] **Step 3: Run the full test suite**

Run: `python -m pytest tests/ -x -q`

Expected: All tests pass (780+ tests, 0 failures)

---

### Task 9: Run full regression and evals

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -x -q`

Expected: All pass

- [ ] **Step 2: Run memory routing benchmark**

Run: `python -m pytest tests/test_memory_routing_benchmark.py -x -q`

Expected: All pass — routing benchmark does not depend on persisted annotations

- [ ] **Step 3: Run work resumption benchmark**

Run: `python -m pytest tests/test_work_resumption_benchmark.py -x -q`

Expected: All pass

- [ ] **Step 4: Run public corpus benchmarks**

Run: `python -m pytest tests/test_public_corpus_benchmark.py tests/test_public_corpus_wildbench_benchmark.py -x -q`

Expected: All pass

- [ ] **Step 5: Run developer work confidence harness**

Run: `python -m pytest tests/test_developer_work_confidence.py -x -q`

Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: remove persisted annotation layer — dead abstraction with fully duplicated data in MemoryObjects"
```

---

### Task 10: Update `docs/context/state.md`

- [ ] **Step 1: Note the removal in state.md**

Add a line to the Current Baseline section noting that the persisted annotation layer has been removed — annotations were a write-only abstraction whose data was fully duplicated in MemoryObjects. The `annotations` DB table, `Annotation` model, and `annotation_ids`/`annotation_count` API fields are removed.

- [ ] **Step 2: Commit docs update**

```bash
git add docs/context/state.md
git commit -m "docs: note annotation layer removal in state.md"
```
