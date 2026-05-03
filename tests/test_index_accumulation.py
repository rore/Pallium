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

from core.contracts import ProcessResult
from core.models import (
    IndexEntry,
    MemoryEnvelope,
    MemoryEnvelopeDerivation,
    MemoryEnvelopeScope,
    MemoryObject,
    MemorySubjectAnchor,
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
        """After fix: entries do NOT accumulate after repeated supersession.

        After N rebuilds, the final active object has only its own ENTRIES_PER_OBJECT
        entries because supersession deletes old entries instead of retargeting them.
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

            # Commit — after fix, supersession DELETES old entries
            # so the new object only keeps its own fresh entries
            storage.commit_process_result(
                result=result,
                supersession_pairs=supersession_pairs,
            )

            previous_mo_id = new_mo.id

        # After fix: the final active object has ONLY its own entries
        final_entries = storage.list_index_entries_for_target("memory_object", previous_mo_id)
        actual_count = len(final_entries)

        assert actual_count == ENTRIES_PER_OBJECT, (
            f"Expected {ENTRIES_PER_OBJECT} entries (fixed: only own entries), "
            f"got {actual_count}. "
            f"Entries are still accumulating — fix not applied."
        )

        # Also verify that all intermediate (superseded) objects have 0 entries
        # (they were all deleted)
        all_mos = storage.list_memory_objects(
            memory_types=["task_checkpoint"],
            lifecycle="superseded",
        )
        for mo in all_mos:
            entries = storage.list_index_entries_for_target("memory_object", mo.id)
            assert len(entries) == 0, (
                f"Superseded object {mo.id} still has {len(entries)} entries"
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

    def test_no_accumulation_stays_constant(self, test_db_url: str) -> None:
        """After fix: entry count stays constant at ENTRIES_PER_OBJECT per object.

        Each rebuild's object retains only its own entries — no accumulation.
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

        # Expected pattern: [3, 3, 3, 3, 3] — stays constant (fixed)
        expected_pattern = [ENTRIES_PER_OBJECT] * NUM_REBUILDS
        assert entry_counts_per_iteration == expected_pattern, (
            f"Expected constant pattern {expected_pattern}, "
            f"got {entry_counts_per_iteration}"
        )


# ---------------------------------------------------------------------------
# Defensive invariant: max entries per memory object
# ---------------------------------------------------------------------------

MAX_ENTRIES_PER_MEMORY_OBJECT = 6  # lexical + vector + enrichment × 2 (generous)


def check_index_entry_accumulation_invariant(
    storage: SQLiteStorageProvider,
    *,
    memory_types: list[str] | None = None,
    max_entries: int = MAX_ENTRIES_PER_MEMORY_OBJECT,
) -> list[tuple[str, str, int]]:
    """Check no active memory object exceeds max_entries index entries.

    Returns list of (memory_object_id, type, entry_count) for violators.
    Use in tests or as a diagnostic against the live database.
    """
    types_to_check = memory_types or ["task_checkpoint", "thread_summary"]
    violators: list[tuple[str, str, int]] = []
    for memory_type in types_to_check:
        active_objects = storage.list_memory_objects(
            memory_types=[memory_type],
            lifecycle="active",
        )
        for mo in active_objects:
            entries = storage.list_index_entries_for_target("memory_object", mo.id)
            if len(entries) > max_entries:
                violators.append((mo.id, mo.type, len(entries)))
    return violators


class TestAccumulationInvariant:
    """Defensive guard: ensure the accumulation invariant holds after operations."""

    def test_invariant_after_repeated_supersession(self, test_db_url: str) -> None:
        """After repeated supersession, no object exceeds max entries."""
        storage = SQLiteStorageProvider(test_db_url)

        previous_mo_id: str | None = None
        for iteration in range(10):  # 10 iterations — well above typical
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

        violators = check_index_entry_accumulation_invariant(storage)
        assert violators == [], (
            f"Accumulation invariant violated — objects with excess entries: "
            f"{[(v[0][:8], v[1], v[2]) for v in violators]}"
        )

    def test_invariant_with_mixed_types(self, test_db_url: str) -> None:
        """Invariant holds for both task_checkpoint and thread_summary."""
        storage = SQLiteStorageProvider(test_db_url)

        for memory_type in ["task_checkpoint", "thread_summary"]:
            previous_mo_id: str | None = None
            for iteration in range(5):
                new_mo = _make_thread_memory_object(
                    memory_type=memory_type,
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

        violators = check_index_entry_accumulation_invariant(storage)
        assert violators == [], (
            f"Accumulation invariant violated: {violators}"
        )
