"""Tests for concurrent queue claim exclusivity.

Exercises the BEGIN IMMEDIATE serialisation that prevents two workers from
claiming the same queue item.  Uses real threads hitting the same SQLite file
to reproduce the original double-pickup race condition.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest

from core.contracts import ProcessResult, build_source_item
from core.models import utc_now
from storage.base import ThreadProcessingScope
from storage.sqlite import SQLiteStorageProvider


@pytest.fixture
def storage(tmp_path):
    return SQLiteStorageProvider(f"sqlite:///{tmp_path / 'concurrent.db'}")


# ── Helpers ──────────────────────────────────────────────────────────────


def _ingest_pending_item(storage: SQLiteStorageProvider, source_id: str, use_case: str = "demo") -> str:
    item = build_source_item(
        source_type="test",
        source_id=source_id,
        content_type="text/plain",
        content=f"Concurrent claim test item {source_id}",
        metadata=None,
        use_case=use_case,
        processing_status="pending",
    )
    storage.create_source_item(item)
    return item.id


def _ingest_pending_item_with_packages(
    storage: SQLiteStorageProvider,
    source_id: str,
    packages: list[str],
    use_case: str = "demo",
) -> str:
    item_id = _ingest_pending_item(storage, source_id, use_case=use_case)
    storage.create_package_processing_records(item_id, packages)
    return item_id


# ── claim_next_source_item ───────────────────────────────────────────────


def test_concurrent_claim_next_source_item_single_winner(storage):
    """Two threads racing to claim the same source item: exactly one wins."""
    _ingest_pending_item(storage, "race-src-1")

    results = [None, None]
    barrier = threading.Barrier(2, timeout=5)

    def claim(index):
        barrier.wait()
        results[index] = storage.claim_next_source_item(
            worker_id=f"worker-{index}",
            lease_seconds=60,
            max_attempts=3,
        )

    threads = [threading.Thread(target=claim, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    winners = [r for r in results if r is not None]
    assert len(winners) == 1, f"Expected exactly 1 winner, got {len(winners)}"


def test_concurrent_claim_next_source_item_two_items_two_winners(storage):
    """Two items pending, two threads: each gets a different item."""
    id1 = _ingest_pending_item(storage, "race-src-2a")
    id2 = _ingest_pending_item(storage, "race-src-2b")

    results = [None, None]
    barrier = threading.Barrier(2, timeout=5)

    def claim(index):
        barrier.wait()
        results[index] = storage.claim_next_source_item(
            worker_id=f"worker-{index}",
            lease_seconds=60,
            max_attempts=3,
        )

    threads = [threading.Thread(target=claim, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    winners = [r for r in results if r is not None]
    assert len(winners) == 2, f"Expected 2 winners, got {len(winners)}"
    winner_ids = {w.id for w in winners}
    assert winner_ids == {id1, id2}, "Each worker should get a different item"


# ── claim_next_package_task ──────────────────────────────────────────────


def test_concurrent_claim_next_package_task_single_winner(storage):
    """Two threads racing to claim the same package task: exactly one wins."""
    _ingest_pending_item_with_packages(storage, "race-pkg-1", ["pkg_a"])

    results = [None, None]
    barrier = threading.Barrier(2, timeout=5)

    def claim(index):
        barrier.wait()
        results[index] = storage.claim_next_package_task(
            worker_id=f"worker-{index}",
            lease_seconds=60,
            max_attempts=3,
        )

    threads = [threading.Thread(target=claim, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    winners = [r for r in results if r is not None]
    assert len(winners) == 1, f"Expected exactly 1 winner, got {len(winners)}"


def test_concurrent_claim_next_package_task_different_packages(storage):
    """One item with two packages: each thread gets a different package."""
    _ingest_pending_item_with_packages(storage, "race-pkg-2", ["pkg_a", "pkg_b"])

    results = [None, None]
    barrier = threading.Barrier(2, timeout=5)

    def claim(index):
        barrier.wait()
        results[index] = storage.claim_next_package_task(
            worker_id=f"worker-{index}",
            lease_seconds=60,
            max_attempts=3,
        )

    threads = [threading.Thread(target=claim, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    winners = [r for r in results if r is not None]
    assert len(winners) == 2, f"Expected 2 winners, got {len(winners)}"
    package_names = {w[1] for w in winners}
    assert package_names == {"pkg_a", "pkg_b"}, "Each worker should get a different package"


# ── claim_next_package_task_for_item ─────────────────────────────────────


def test_concurrent_claim_next_package_task_for_item_single_winner(storage):
    """Two threads racing to claim the next package for the same item."""
    item_id = _ingest_pending_item_with_packages(storage, "race-pkg-item-1", ["pkg_a"])

    results = [None, None]
    barrier = threading.Barrier(2, timeout=5)

    def claim(index):
        barrier.wait()
        results[index] = storage.claim_next_package_task_for_item(
            item_id,
            worker_id=f"worker-{index}",
            lease_seconds=60,
            max_attempts=3,
        )

    threads = [threading.Thread(target=claim, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    winners = [r for r in results if r is not None]
    assert len(winners) == 1, f"Expected exactly 1 winner, got {len(winners)}"


# ── claim_thread_processing_scope ────────────────────────────────────────


def _create_thread_scope(storage, scope_key: str) -> ThreadProcessingScope:
    """Create a source item and thread scope ready for claiming."""
    item = build_source_item(
        source_type="test",
        source_id=f"seed-{scope_key}",
        content_type="text/plain",
        content="Thread scope seed.",
        metadata=None,
        use_case="test",
        container_ref="container:concurrent",
        thread_ref="thread:concurrent",
        visibility="public",
    )
    storage.create_source_item(item)
    scope = ThreadProcessingScope(
        scope_key=scope_key,
        use_case="test",
        container_ref="container:concurrent",
        thread_ref="thread:concurrent",
        visibility="public",
    )
    storage.commit_processed_source_item(
        source_item_id=item.id,
        result=ProcessResult(memory_objects=[], relations=[], index_entries=[]),
        thread_rebuild_scope=scope,
    )
    return scope


def test_concurrent_claim_thread_processing_scope_single_winner(storage):
    """Two threads racing to claim the same thread scope: exactly one wins."""
    scope = _create_thread_scope(storage, "scope-race-1")

    results = [None, None]
    barrier = threading.Barrier(2, timeout=5)

    def claim(index):
        barrier.wait()
        results[index] = storage.claim_thread_processing_scope(
            scope=scope,
            worker_id=f"worker-{index}",
            lease_seconds=60,
        )

    threads = [threading.Thread(target=claim, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    winners = [r for r in results if r is not None]
    assert len(winners) == 1, f"Expected exactly 1 winner, got {len(winners)}"


def test_concurrent_claim_next_thread_processing_scope_single_winner(storage):
    """Two threads racing to claim the next available thread scope."""
    _create_thread_scope(storage, "scope-race-next-1")

    results = [None, None]
    barrier = threading.Barrier(2, timeout=5)

    def claim(index):
        barrier.wait()
        results[index] = storage.claim_next_thread_processing_scope(
            worker_id=f"worker-{index}",
            lease_seconds=60,
        )

    threads = [threading.Thread(target=claim, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    winners = [r for r in results if r is not None]
    assert len(winners) == 1, f"Expected exactly 1 winner, got {len(winners)}"


# ── Stress: many workers, many items ─────────────────────────────────────


def test_concurrent_claim_many_workers_no_duplicates(storage):
    """5 workers, 3 items: no item is claimed by more than one worker."""
    item_ids = [_ingest_pending_item(storage, f"stress-{i}") for i in range(3)]

    results = [None] * 5
    barrier = threading.Barrier(5, timeout=5)

    def claim(index):
        barrier.wait()
        results[index] = storage.claim_next_source_item(
            worker_id=f"worker-{index}",
            lease_seconds=60,
            max_attempts=3,
        )

    threads = [threading.Thread(target=claim, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    winners = [r for r in results if r is not None]
    winner_ids = [w.id for w in winners]
    assert len(winners) == 3, f"Expected exactly 3 winners, got {len(winners)}"
    assert len(set(winner_ids)) == 3, f"Duplicate item claimed: {winner_ids}"


def test_concurrent_claim_package_task_many_workers_no_duplicates(storage):
    """5 workers, 3 package tasks: no task is claimed by more than one worker."""
    _ingest_pending_item_with_packages(
        storage, "stress-pkg-1", ["pkg_a", "pkg_b", "pkg_c"],
    )

    results = [None] * 5
    barrier = threading.Barrier(5, timeout=5)

    def claim(index):
        barrier.wait()
        results[index] = storage.claim_next_package_task(
            worker_id=f"worker-{index}",
            lease_seconds=60,
            max_attempts=3,
        )

    threads = [threading.Thread(target=claim, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    winners = [r for r in results if r is not None]
    package_names = [w[1] for w in winners]
    assert len(winners) == 3, f"Expected exactly 3 winners, got {len(winners)}"
    assert len(set(package_names)) == 3, f"Duplicate package claimed: {package_names}"


# ── Edge cases ───────────────────────────────────────────────────────────


def test_concurrent_claim_empty_queue_both_get_none(storage):
    """Two threads claiming from an empty queue: both get None, no errors."""
    results = [None, None]
    errors = [None, None]
    barrier = threading.Barrier(2, timeout=5)

    def claim(index):
        barrier.wait()
        try:
            results[index] = storage.claim_next_source_item(
                worker_id=f"worker-{index}",
                lease_seconds=60,
                max_attempts=3,
            )
        except Exception as exc:
            errors[index] = exc

    threads = [threading.Thread(target=claim, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert results == [None, None], "Both should get None from empty queue"
    assert errors == [None, None], f"No errors expected, got {errors}"


def test_concurrent_claim_expired_lease_single_winner(storage):
    """Two threads racing to reclaim an item whose lease has expired."""
    item_id = _ingest_pending_item(storage, "expired-lease-1")

    # First worker claims the item with a short lease
    first = storage.claim_next_source_item(
        worker_id="original-worker",
        lease_seconds=10,
        max_attempts=3,
    )
    assert first is not None

    # Simulate time passing beyond lease expiry
    expired_time = first.processing_claimed_at + timedelta(seconds=11)

    results = [None, None]
    barrier = threading.Barrier(2, timeout=5)

    def claim(index):
        barrier.wait()
        results[index] = storage.claim_next_source_item(
            worker_id=f"worker-{index}",
            lease_seconds=60,
            max_attempts=3,
            now=expired_time,
        )

    threads = [threading.Thread(target=claim, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    winners = [r for r in results if r is not None]
    assert len(winners) == 1, f"Expected exactly 1 winner for expired lease reclaim, got {len(winners)}"
    assert winners[0].id == item_id


def test_concurrent_claim_package_task_for_item_two_packages_two_winners(storage):
    """Two threads racing for the next package on an item with two pending packages."""
    item_id = _ingest_pending_item_with_packages(
        storage, "race-pkg-item-2", ["pkg_x", "pkg_y"],
    )

    results = [None, None]
    barrier = threading.Barrier(2, timeout=5)

    def claim(index):
        barrier.wait()
        results[index] = storage.claim_next_package_task_for_item(
            item_id,
            worker_id=f"worker-{index}",
            lease_seconds=60,
            max_attempts=3,
        )

    threads = [threading.Thread(target=claim, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    winners = [r for r in results if r is not None]
    assert len(winners) == 2, f"Expected 2 winners, got {len(winners)}"
    package_names = {w[0] for w in winners}
    assert package_names == {"pkg_x", "pkg_y"}, "Each worker should get a different package"


def test_concurrent_claim_after_complete_picks_next_item(storage):
    """Claim-complete-claim cycle: second claim picks the next pending item."""
    id1 = _ingest_pending_item(storage, "cycle-1")
    id2 = _ingest_pending_item(storage, "cycle-2")

    # Claim and complete first item
    first = storage.claim_next_source_item(
        worker_id="worker-a", lease_seconds=60, max_attempts=3,
    )
    assert first is not None
    storage.complete_source_item_processing(first.id)

    # Now two workers race for the remaining item
    results = [None, None]
    barrier = threading.Barrier(2, timeout=5)

    def claim(index):
        barrier.wait()
        results[index] = storage.claim_next_source_item(
            worker_id=f"worker-{index}",
            lease_seconds=60,
            max_attempts=3,
        )

    threads = [threading.Thread(target=claim, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    winners = [r for r in results if r is not None]
    assert len(winners) == 1, f"Expected exactly 1 winner, got {len(winners)}"
    # The winner must be the second item (first was completed)
    assert winners[0].id == id2


def test_concurrent_claim_failed_with_backoff_single_winner(storage):
    """Two threads racing to claim a failed item past its backoff time."""
    item_id = _ingest_pending_item(storage, "failed-backoff-1")

    # Claim and fail the item
    claimed = storage.claim_next_source_item(
        worker_id="original", lease_seconds=60, max_attempts=3,
    )
    assert claimed is not None
    backoff_time = claimed.processing_claimed_at + timedelta(seconds=30)
    storage.fail_source_item_processing(
        claimed.id,
        error="transient failure",
        next_attempt_at=backoff_time,
        final=False,
    )

    # Both workers race to claim the failed item after backoff
    past_backoff = backoff_time + timedelta(seconds=1)
    results = [None, None]
    barrier = threading.Barrier(2, timeout=5)

    def claim(index):
        barrier.wait()
        results[index] = storage.claim_next_source_item(
            worker_id=f"worker-{index}",
            lease_seconds=60,
            max_attempts=3,
            now=past_backoff,
        )

    threads = [threading.Thread(target=claim, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    winners = [r for r in results if r is not None]
    assert len(winners) == 1, f"Expected exactly 1 winner for failed item reclaim, got {len(winners)}"
    assert winners[0].id == item_id


def test_concurrent_claim_thread_scope_empty_queue_both_get_none(storage):
    """Two threads claiming from an empty thread scope queue: both get None."""
    results = [None, None]
    errors = [None, None]
    barrier = threading.Barrier(2, timeout=5)

    def claim(index):
        barrier.wait()
        try:
            results[index] = storage.claim_next_thread_processing_scope(
                worker_id=f"worker-{index}",
                lease_seconds=60,
            )
        except Exception as exc:
            errors[index] = exc

    threads = [threading.Thread(target=claim, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert results == [None, None], "Both should get None from empty queue"
    assert errors == [None, None], f"No errors expected, got {errors}"


def test_rapid_sequential_claims_exhaust_queue(storage):
    """Rapid sequential claims should exhaust the queue cleanly without skips."""
    item_count = 10
    item_ids = set()
    for i in range(item_count):
        item_ids.add(_ingest_pending_item(storage, f"exhaust-{i}"))

    claimed_ids = set()
    for i in range(item_count + 2):  # Over-claim to verify queue exhaustion
        result = storage.claim_next_source_item(
            worker_id=f"worker-{i}",
            lease_seconds=60,
            max_attempts=3,
        )
        if result is not None:
            claimed_ids.add(result.id)

    assert claimed_ids == item_ids, "All items should be claimed exactly once"


# ── Atomic ingest prevents legacy-path race ────────────────────────────


def test_atomic_ingest_prevents_legacy_claim_during_pps_gap(storage):
    """Item created with create_source_item_with_packages cannot be claimed by legacy path.

    Reproduces the race where a processor polls between create_source_item and
    create_package_processing_records — with atomic ingest, PPS rows exist from
    the start, so the NOT EXISTS guard in claim_next_source_item blocks it.
    """
    item = build_source_item(
        source_type="test",
        source_id="atomic-race-1",
        content_type="text/plain",
        content="Atomic ingest test item",
        metadata=None,
        use_case="demo",
        processing_status="pending",
    )
    storage.create_source_item_with_packages(item, ["pkg_a", "pkg_b"])

    # Legacy path must NOT find this item (PPS rows exist in pending state)
    legacy_claim = storage.claim_next_source_item(
        worker_id="legacy-worker",
        lease_seconds=60,
        max_attempts=3,
    )
    assert legacy_claim is None, "Legacy path must not claim items with pending PPS rows"

    # PPS path should find it
    pps_claim = storage.claim_next_package_task(
        worker_id="pps-worker",
        lease_seconds=60,
        max_attempts=3,
    )
    assert pps_claim is not None
    assert pps_claim[0].id == item.id
    assert pps_claim[1] in ("pkg_a", "pkg_b")


def test_atomic_ingest_integrity_error_on_duplicate(storage):
    """Duplicate source_id raises IntegrityError even with atomic ingest."""
    from sqlalchemy.exc import IntegrityError as SAIntegrityError

    item = build_source_item(
        source_type="test",
        source_id="dupe-atomic-1",
        content_type="text/plain",
        content="First ingest",
        metadata=None,
        use_case="demo",
        processing_status="pending",
    )
    storage.create_source_item_with_packages(item, ["pkg_a"])

    item2 = build_source_item(
        source_type="test",
        source_id="dupe-atomic-1",
        content_type="text/plain",
        content="Duplicate ingest",
        metadata=None,
        use_case="demo",
        processing_status="pending",
    )
    with pytest.raises(SAIntegrityError):
        storage.create_source_item_with_packages(item2, ["pkg_a"])

