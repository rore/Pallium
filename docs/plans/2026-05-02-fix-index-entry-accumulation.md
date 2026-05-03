# Fix Task Checkpoint and Thread Summary Index Entry Accumulation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix index entry accumulation during thread rebuild supersession — each active memory object should have at most 3 index entries (lexical + vector + enrichment), not 3×N where N is the number of rebuilds.

**Architecture:** Change `_apply_supersession_pairs_in_session` in `storage/sqlite_queue.py` to DELETE the superseded object's index entries instead of retargeting them to the replacement. The replacement already has its own entries from `_persist_process_result_in_session`. The consolidation retarget path (which intentionally keeps old entries alive) is unaffected — it uses the separate `retarget_index_entries_for_target` public method directly.

**Tech Stack:** Python, SQLAlchemy, SQLite, pytest

---

## Root Cause Analysis

In `storage/sqlite_queue.py`, `commit_process_result_and_complete_scope` (the thread rebuild commit path):

1. `_persist_process_result_in_session(session, result)` — creates the NEW memory object + its NEW index entries
2. `_apply_supersession_pairs_in_session(session, all_pairs)` — marks old object as superseded, then RETARGETS old entries to the new object

Result after N rebuilds: the latest object has `3 × N` entries (3 own + 3 retargeted from each predecessor, accumulated through the chain).

The retarget behavior is intentional for the consolidation path (where atomic_fact entries are more focused than fact_summary's own entries and should be preserved). But consolidation uses `retarget_index_entries_for_target()` explicitly in `core/consolidation_runner.py:295`, completely separate from `_apply_supersession_pairs_in_session`.

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `storage/sqlite_queue.py` | Modify | Change `_apply_supersession_pairs_in_session` to delete old entries |
| `tests/test_index_entry_retargeting.py` | Modify | Update `TestAtomicCommitRetarget` to assert deletion + add accumulation regression test |

---

### Task 1: Add `_delete_index_entries_for_target_in_session` helper

**Files:**
- Modify: `storage/sqlite_queue.py:586-609`

- [ ] **Step 1: Write the failing test**

Add a test in `tests/test_index_entry_retargeting.py` that verifies supersession in `commit_process_result` DELETES old entries instead of retargeting:

```python
class TestAtomicCommitDeletesOnSupersession:

    def test_supersession_deletes_old_entries(self, test_db_url: str) -> None:
        """When supersession pairs are processed, old entries are deleted (not retargeted)."""
        storage = SQLiteStorageProvider(test_db_url)
        old_ts = _make_memory_object(memory_type="thread_summary", subject="summary-old")
        new_ts = _make_memory_object(memory_type="thread_summary", subject="summary-new")
        storage.create_memory_object(old_ts)
        storage.create_memory_object(new_ts)

        old_entry = _make_index_entry(
            "memory_object", old_ts.id, "lexical",
            text_view="discussion about reservation ordering",
            text_view_name="memory_object.summary",
        )
        storage.create_index_entry(old_entry)

        # New object has its own entry (simulating thread rebuild)
        new_entry = _make_index_entry(
            "memory_object", new_ts.id, "lexical",
            text_view="updated discussion about reservation ordering v2",
            text_view_name="memory_object.summary",
        )

        from core.contracts import ProcessResult
        result = ProcessResult(
            memory_objects=[],
            relations=[],
            index_entries=[new_entry],
        )
        storage.commit_process_result(result=result, supersession_pairs=[(old_ts.id, new_ts.id)])

        # Old entry should be DELETED, not retargeted
        with pytest.raises(KeyError):
            storage.get_index_entry(old_entry.id)

        # New object should only have its own entry
        entries = storage.list_index_entries_for_target("memory_object", new_ts.id)
        assert len(entries) == 1
        assert entries[0].id == new_entry.id
        assert storage.get_memory_object(old_ts.id).lifecycle == "superseded"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_index_entry_retargeting.py::TestAtomicCommitDeletesOnSupersession -x -v`
Expected: FAIL (old entry is retargeted instead of deleted)

- [ ] **Step 3: Implement `_delete_index_entries_for_target_in_session`**

In `storage/sqlite_queue.py`, add a method following the same pattern as `_delete_index_entry_in_session` from `sqlite_retention.py`:

```python
def _delete_index_entries_for_target_in_session(
    self,
    session: Session,
    target_kind: str,
    target_id: str,
) -> int:
    """Delete all index entries for a target within an open session.

    Removes both the IndexEntryRecord and associated FTS5 shadow rows.
    The in-memory vector index is NOT updated here — reconciliation handles gaps.
    """
    records = session.scalars(
        select(IndexEntryRecord).where(
            IndexEntryRecord.target_kind == target_kind,
            IndexEntryRecord.target_id == target_id,
        )
    ).all()
    if not records:
        return 0
    for record in records:
        if record.index_type == "lexical":
            session.execute(
                text("DELETE FROM lexical_fts WHERE index_entry_id = :id"),
                {"id": record.id},
            )
        session.delete(record)
    return len(records)
```

- [ ] **Step 4: Change `_apply_supersession_pairs_in_session` to delete instead of retarget**

Replace line 607-609 in `storage/sqlite_queue.py`:

```python
# Before:
self._retarget_index_entries_in_session(
    session, "memory_object", superseded_id, replacement_id,
)

# After:
self._delete_index_entries_for_target_in_session(
    session, "memory_object", superseded_id,
)
```

- [ ] **Step 5: Run the new test to verify it passes**

Run: `python -m pytest tests/test_index_entry_retargeting.py::TestAtomicCommitDeletesOnSupersession -x -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add storage/sqlite_queue.py tests/test_index_entry_retargeting.py
git commit -m "fix: delete superseded index entries instead of retargeting during thread rebuild"
```

---

### Task 2: Add accumulation regression test

**Files:**
- Modify: `tests/test_index_entry_retargeting.py`

- [ ] **Step 1: Write a test that simulates multiple thread rebuilds**

```python
class TestAccumulationRegression:

    def test_repeated_supersession_does_not_accumulate_entries(self, test_db_url: str) -> None:
        """Simulates 5 thread rebuilds — final object should have exactly its own entries."""
        storage = SQLiteStorageProvider(test_db_url)
        from core.contracts import ProcessResult

        previous_mo = None
        for i in range(5):
            current_mo = _make_memory_object(
                memory_type="task_checkpoint",
                subject=f"checkpoint-{i}",
                payload={"subject": f"checkpoint-{i}", "statement": f"state at rebuild {i}"},
            )
            storage.create_memory_object(current_mo)

            # Each rebuild produces lexical + vector + enrichment entries
            entries = [
                _make_index_entry(
                    "memory_object", current_mo.id, "lexical",
                    text_view=f"task state at rebuild {i}",
                    text_view_name="memory_object.task_checkpoint_context",
                ),
                _make_index_entry(
                    "memory_object", current_mo.id, "vector",
                    text_view=f"task checkpoint: state at rebuild {i}",
                    text_view_name="memory_object.task_checkpoint_context.embedding",
                ),
                _make_index_entry(
                    "memory_object", current_mo.id, "lexical",
                    text_view=f"enrichment context for rebuild {i}",
                    text_view_name="memory_object.write_enrichment_context",
                ),
            ]

            supersession_pairs = []
            if previous_mo is not None:
                supersession_pairs = [(previous_mo.id, current_mo.id)]

            result = ProcessResult(
                memory_objects=[],
                relations=[],
                index_entries=entries,
            )
            storage.commit_process_result(result=result, supersession_pairs=supersession_pairs)
            previous_mo = current_mo

        # Final object should have EXACTLY 3 entries (its own), not 15 (accumulated)
        final_entries = storage.list_index_entries_for_target("memory_object", current_mo.id)
        assert len(final_entries) == 3, (
            f"Expected 3 entries, got {len(final_entries)} — accumulation bug is back"
        )

        # All intermediate objects should have 0 entries
        # (their entries were deleted during supersession)
```

- [ ] **Step 2: Run the test**

Run: `python -m pytest tests/test_index_entry_retargeting.py::TestAccumulationRegression -x -v`
Expected: PASS (with the fix from Task 1 in place)

- [ ] **Step 3: Commit**

```bash
git add tests/test_index_entry_retargeting.py
git commit -m "test: add accumulation regression test for repeated thread rebuild supersession"
```

---

### Task 3: Update existing retargeting tests to reflect new behavior

**Files:**
- Modify: `tests/test_index_entry_retargeting.py`

- [ ] **Step 1: Update `TestAtomicCommitRetarget.test_supersession_pairs_retarget_entries`**

This test currently asserts retarget behavior for the `commit_process_result` path. It needs to assert deletion instead:

```python
def test_supersession_pairs_delete_old_entries(self, test_db_url: str) -> None:
    """_apply_supersession_pairs_in_session deletes old index entries."""
    storage = SQLiteStorageProvider(test_db_url)
    old_ts = _make_memory_object(memory_type="thread_summary", subject="summary-old")
    new_ts = _make_memory_object(memory_type="thread_summary", subject="summary-new")
    storage.create_memory_object(old_ts)
    storage.create_memory_object(new_ts)

    entry = _make_index_entry(
        "memory_object", old_ts.id, "lexical",
        text_view="discussion about reservation ordering",
        text_view_name="memory_object.summary",
    )
    storage.create_index_entry(entry)

    from core.contracts import ProcessResult
    result = ProcessResult(
        memory_objects=[],
        relations=[],
        index_entries=[],
    )
    storage.commit_process_result(result=result, supersession_pairs=[(old_ts.id, new_ts.id)])

    # Entry should be DELETED (not retargeted)
    with pytest.raises(KeyError):
        storage.get_index_entry(entry.id)
    assert storage.list_index_entries_for_target("memory_object", old_ts.id) == []
    assert storage.list_index_entries_for_target("memory_object", new_ts.id) == []
    assert storage.get_memory_object(old_ts.id).lifecycle == "superseded"
```

- [ ] **Step 2: Update `test_already_superseded_skips_retarget`**

Rename and adjust — it should still verify that already-superseded objects are skipped:

```python
def test_already_superseded_skips_deletion(self, test_db_url: str) -> None:
    """If memory is already superseded, no deletion happens."""
    storage = SQLiteStorageProvider(test_db_url)
    old_ts = _make_memory_object(memory_type="thread_summary")
    new_ts = _make_memory_object(memory_type="thread_summary")
    storage.create_memory_object(old_ts)
    storage.create_memory_object(new_ts)

    # Pre-supersede
    storage.update_memory_object_lifecycle(old_ts.id, "superseded")

    entry = _make_index_entry("memory_object", old_ts.id, "lexical", "already superseded text")
    storage.create_index_entry(entry)

    from core.contracts import ProcessResult
    result = ProcessResult(memory_objects=[], relations=[], index_entries=[])
    storage.commit_process_result(result=result, supersession_pairs=[(old_ts.id, new_ts.id)])

    # Entry stays (supersession was skipped, so no deletion)
    assert storage.get_index_entry(entry.id).target_id == old_ts.id
```

- [ ] **Step 3: Run all retargeting tests**

Run: `python -m pytest tests/test_index_entry_retargeting.py -x -v`
Expected: ALL PASS. Note: the `TestRetargetIndexEntries` and `TestConsolidationRunnerRetargets` classes should still pass unchanged — they use `retarget_index_entries_for_target` (the public method), which is unmodified.

- [ ] **Step 4: Commit**

```bash
git add tests/test_index_entry_retargeting.py
git commit -m "test: update atomic commit tests to assert delete-on-supersession behavior"
```

---

### Task 4: Run full test suite

**Files:** None (verification only)

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: ALL PASS

- [ ] **Step 2: If any tests fail, investigate and fix**

Likely culprits:
- Tests that assert `_apply_supersession_pairs_in_session` retargets (already handled in Task 3)
- Tests that rely on retargeted entries appearing under new targets via the `commit_process_result` path

- [ ] **Step 3: Run the consolidation retarget tests specifically**

Run: `python -m pytest tests/test_index_entry_retargeting.py::TestConsolidationRunnerRetargets -x -v`
Expected: PASS (consolidation uses separate path, unaffected by this change)

---

### Task 5: Vector index cleanup consideration

**Files:** No code changes needed.

- [ ] **Step 1: Verify vector reconciliation handles deleted entries**

The vector reconciliation in `core/vector_embed.py:154` (`reconcile()`) already handles stale entries:
- It checks `usearch_ids` against `storage.get_index_entries(stale_batch_ids)` 
- If an entry exists in usearch but NOT in SQLite, it calls `self._vector_index.remove(entry_id)`

So after our fix deletes SQLite index entry records, the next reconciliation cycle will clean up the corresponding usearch entries. No additional work needed.

- [ ] **Step 2: Document in commit message**

The vector index self-heals via existing reconciliation. No additional cleanup needed.

---

### Task 6: Document stale checkpoint TTL behavior

**Files:**
- Modify: `docs/context/state.md` (if appropriate)

- [ ] **Step 1: Verify existing retention handles stale checkpoints**

The retention system already expires `task_checkpoint` and `thread_summary` (they're in `working_types`) after `WORKING_MEMORY_TTL = 30 days`. The freshness timestamp (`freshness_at`) is updated on each rebuild. Stale checkpoints from inactive threads will be expired once their freshness is 30 days old.

Current state: 5 stale checkpoints from Apr 29-30 will be cleaned up by retention around May 29-30. After the accumulation fix, each has at most 3 entries (not 48), so the retrieval impact is minimal.

- [ ] **Step 2: No code change needed**

The existing 30-day TTL is acceptable. Reducing it would require changing `WORKING_MEMORY_TTL` which affects all working memory types. The accumulation fix reduces the pollution from stale checkpoints from 48+ entries to 3 entries — making the 30-day TTL tolerable.

---

## Summary of Changes

| What | Before | After |
|------|--------|-------|
| `_apply_supersession_pairs_in_session` | Retargets old entries to replacement | Deletes old entries |
| Thread rebuild: entries per active object | 3 × N (N = rebuild count) | 3 (constant) |
| 12 active checkpoints: total entries | 258 | ≤ 36 |
| 14 active thread summaries: total entries | 266 | ≤ 42 |
| Consolidation retarget (separate path) | Unaffected | Unaffected |
| Stale checkpoint TTL | 30 days (existing retention) | 30 days (unchanged, acceptable) |
