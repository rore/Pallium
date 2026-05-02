"""Reproduction eval for index entry accumulation bug during thread rebuild supersession.

Demonstrates that repeated thread rebuild supersession causes index entries to
accumulate on the latest memory object. Each rebuild creates a new object with
its own 3 entries, then retargets all entries from the superseded object to the
new one — so the new object ends up with 3 (own) + all previously accumulated.

After N rebuilds, the latest active object has 3*N index entries instead of 3.

Bug location: storage/sqlite_queue.py _apply_supersession_pairs_in_session()
calls _retarget_index_entries_in_session() which MOVES old entries to the new
target, but the new target ALSO has its own fresh entries from the same commit.
"""

from __future__ import annotations

import pytest

from core.contracts import ProcessResult
from core.models import (
    IndexEntry,
    MemoryEnvelope,
    MemoryEnvelopeDerivation,
    MemoryEnvelopeScope,
    MemoryObject,
    MemorySubjectAnchor,
    new_id,
)
from storage.sqlite import SQLiteStorageProvider


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ENTRIES_PER_OBJECT = 3  # lexical + vector + retrieval_context (typical)
NUM_REBUILDS = 5
CONTAINER_REF = "chat:test-accumulation"
THREAD_REF = "chat:test-accumulation:thread-001"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_thread_memory_object(
    memory_type: str = "task_checkpoint",
    container_ref: str = CONTAINER_REF,
    thread_ref: str = THREAD_REF,
    iteration: int = 0,
) -> MemoryObject:
    """Create a memory object mimicking what thread rebuild produces."""
    return MemoryObject(
        type=memory_type,
        schema_id=f"agent_conversation_memory.{memory_type}",
        schema_version="v1",
        payload={
            "summary": f"Thread state at rebuild iteration {iteration}",
            "task": "Resume previously recorded work.",
            "current_state": f"State after iteration {iteration}.",
        },
        visibility="container",
        container_ref=container_ref,
        envelope=MemoryEnvelope(
            schema_id="core.memory_envelope",
            schema_version="v1",
            kind="episode",
            scope=MemoryEnvelopeScope(
                container_ref=container_ref,
                thread_ref=thread_ref,
            ),
            subjects=[MemorySubjectAnchor(kind="thread", value=thread_ref)],
            confidence="high",
            derivation=MemoryEnvelopeDerivation(
                producer_kind="thread_rebuild",
                producer_schema_id="agent_conversation_memory",
                producer_schema_version="v1",
                prompt_variant="default",
                model_role="thread_rebuild",
                kind_basis="thread_aggregation",
            ),
        ),
    )


def _make_index_entries_for_object(
    target_id: str,
    iteration: int = 0,
    count: int = ENTRIES_PER_OBJECT,
) -> list[IndexEntry]:
    """Create index entries mimicking what thread rebuild produces per memory object."""
    entries = []
    view_specs = [
        ("lexical", f"thread state iteration {iteration} checkpoint", "memory_object.summary"),
        ("vector", f"thread: thread state iteration {iteration}", "memory_object.embedding"),
        ("lexical", f"resume work from iteration {iteration}", "memory_object.retrieval_context"),
    ]
    for i in range(count):
        idx_type, text_view, view_name = view_specs[i % len(view_specs)]
        entries.append(IndexEntry(
            target_kind="memory_object",
            target_id=target_id,
            index_type=idx_type,
            text_view=text_view,
            text_view_name=view_name,
        ))
    return entries


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestIndexEntryAccumulation:
    """Reproduction eval for index entry accumulation bug.

    Demonstrates that repeated thread rebuild supersession causes
    index entries to accumulate on the latest memory object.
    """

    def test_accumulation_baseline(self, test_db_url: str) -> None:
        """Baseline: shows the bug -- entries accumulate after repeated supersession.

        After N rebuilds, the final active object has 3*N entries because each
        supersession retargets previous entries while the object also has its own.
        """
        storage = SQLiteStorageProvider(test_db_url)

        previous_mo_id: str | None = None

        for iteration in range(NUM_REBUILDS):
            # Each rebuild creates a NEW memory object with its own index entries
            new_mo = _make_thread_memory_object(
                memory_type="task_checkpoint",
                iteration=iteration,
            )
            new_entries = _make_index_entries_for_object(new_mo.id, iteration=iteration)

            # Build the ProcessResult as thread rebuild does
            result = ProcessResult(
                memory_objects=[new_mo],
                relations=[],
                index_entries=new_entries,
            )

            # Supersession pairs: new object supersedes the previous one
            supersession_pairs: list[tuple[str, str]] = []
            if previous_mo_id is not None:
                supersession_pairs = [(previous_mo_id, new_mo.id)]

            # Commit — this is the atomic operation that exhibits the bug:
            # 1. Persists new_mo and its entries (3 entries pointing to new_mo)
            # 2. Applies supersession: retargets ALL entries from previous_mo to new_mo
            # Result: new_mo has 3 (own) + all retargeted from previous_mo
            storage.commit_process_result(
                result=result,
                supersession_pairs=supersession_pairs,
            )

            previous_mo_id = new_mo.id

        # Verify the accumulation bug:
        # The final active object should have 3 * NUM_REBUILDS entries (the bug)
        final_entries = storage.list_index_entries_for_target("memory_object", previous_mo_id)
        actual_count = len(final_entries)
        expected_buggy_count = ENTRIES_PER_OBJECT * NUM_REBUILDS  # 3 * 5 = 15

        assert actual_count == expected_buggy_count, (
            f"Expected {expected_buggy_count} entries (bug: 3*N accumulation), "
            f"got {actual_count}. "
            f"If this fails with {ENTRIES_PER_OBJECT}, the bug has been fixed!"
        )

        # Also verify that all intermediate (superseded) objects have 0 entries
        # (they were all retargeted away)
        all_mos = storage.list_memory_objects(
            memory_types=["task_checkpoint"],
            lifecycle="superseded",
        )
        for mo in all_mos:
            entries = storage.list_index_entries_for_target("memory_object", mo.id)
            assert len(entries) == 0, (
                f"Superseded object {mo.id} still has {len(entries)} entries"
            )

    @pytest.mark.xfail(
        reason="fix pending: _apply_supersession_pairs_in_session retargets instead of deletes"
    )
    def test_fixed_behavior(self, test_db_url: str) -> None:
        """Post-fix: entries should NOT accumulate. Max 3 per object.

        After the fix, supersession should DELETE old entries from the superseded
        object (since the new object has its own fresh entries that cover the same
        content) rather than retargeting them to the new object.

        This test will FAIL until the fix is applied.
        """
        storage = SQLiteStorageProvider(test_db_url)

        previous_mo_id: str | None = None

        for iteration in range(NUM_REBUILDS):
            new_mo = _make_thread_memory_object(
                memory_type="task_checkpoint",
                iteration=iteration,
            )
            new_entries = _make_index_entries_for_object(new_mo.id, iteration=iteration)

            result = ProcessResult(
                memory_objects=[new_mo],
                relations=[],
                index_entries=new_entries,
            )

            supersession_pairs: list[tuple[str, str]] = []
            if previous_mo_id is not None:
                supersession_pairs = [(previous_mo_id, new_mo.id)]

            storage.commit_process_result(
                result=result,
                supersession_pairs=supersession_pairs,
            )

            previous_mo_id = new_mo.id

        # After fix: the final active object should have ONLY its own entries
        final_entries = storage.list_index_entries_for_target("memory_object", previous_mo_id)
        actual_count = len(final_entries)

        assert actual_count == ENTRIES_PER_OBJECT, (
            f"Expected {ENTRIES_PER_OBJECT} entries (fixed: only own entries), "
            f"got {actual_count}. "
            f"Entries are still accumulating — fix not applied."
        )

    def test_accumulation_grows_linearly(self, test_db_url: str) -> None:
        """Verify the accumulation pattern is exactly linear: 3, 6, 9, 12, 15.

        This proves the bug is systematic and not a one-off issue.
        """
        storage = SQLiteStorageProvider(test_db_url)

        previous_mo_id: str | None = None
        entry_counts_per_iteration: list[int] = []

        for iteration in range(NUM_REBUILDS):
            new_mo = _make_thread_memory_object(
                memory_type="thread_summary",
                iteration=iteration,
            )
            new_entries = _make_index_entries_for_object(new_mo.id, iteration=iteration)

            result = ProcessResult(
                memory_objects=[new_mo],
                relations=[],
                index_entries=new_entries,
            )

            supersession_pairs: list[tuple[str, str]] = []
            if previous_mo_id is not None:
                supersession_pairs = [(previous_mo_id, new_mo.id)]

            storage.commit_process_result(
                result=result,
                supersession_pairs=supersession_pairs,
            )

            # Record entry count for this iteration's object IMMEDIATELY after commit
            entries = storage.list_index_entries_for_target("memory_object", new_mo.id)
            entry_counts_per_iteration.append(len(entries))

            previous_mo_id = new_mo.id

        # Expected pattern: [3, 6, 9, 12, 15] — grows by 3 each time
        expected_pattern = [ENTRIES_PER_OBJECT * (i + 1) for i in range(NUM_REBUILDS)]
        assert entry_counts_per_iteration == expected_pattern, (
            f"Expected linear growth pattern {expected_pattern}, "
            f"got {entry_counts_per_iteration}"
        )
