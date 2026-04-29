"""Tests for multi-package processing infrastructure (Part 1).

Exercises the per-package processing tracking table, claim/complete/fail lifecycle,
source_item state sync, and the multi-package processing loop.
"""
from __future__ import annotations

from datetime import timedelta
from datetime import timezone

import pytest
from sqlalchemy import select, text

from core.contracts import ProcessResult
from core.models import SourceItem, utc_now
from core.service import PalliumService
from retrieval.lexical import LexicalRetrievalProvider
from semantic.base import SemanticPlugin
from semantic.demo_agent_memory import DemoAgentMemoryPlugin
from storage.sqlite import SQLiteStorageProvider


# ── Stub plugins ──────────────────────────────────────────────────────────

class NoOpPlugin(SemanticPlugin):
    """Plugin that returns an empty result (no memory objects)."""
    name = "noop_plugin"

    def process_item(self, source_item: SourceItem) -> ProcessResult:
        return ProcessResult(memory_objects=[], relations=[], index_entries=[])


class AlwaysFailPlugin(SemanticPlugin):
    """Plugin that always raises an error."""
    name = "always_fail"

    def process_item(self, source_item: SourceItem) -> ProcessResult:
        raise RuntimeError("boom")


# ── Helpers ───────────────────────────────────────────────────────────────

def _build_service(
    db_url: str,
    plugins: dict[str, SemanticPlugin],
    default_use_case: str,
) -> PalliumService:
    storage = SQLiteStorageProvider(db_url)
    return PalliumService(
        storage=storage,
        retrieval=LexicalRetrievalProvider(storage),
        semantic_plugins=plugins,
        default_use_case=default_use_case,
    )


def _ingest(service: PalliumService, source_id: str = "item-1", use_case: str | None = None):
    return service.ingest_item(
        source_type="test",
        source_id=source_id,
        content_type="text/plain",
        content="Test content for multi-package processing.",
        metadata=None,
        use_case=use_case,
        artifact_kind="assistant_output",
        role="assistant",
    )


# ── Tests: package processing record creation ─────────────────────────────

@pytest.fixture
def test_db_url(tmp_path):
    return f"sqlite:///{tmp_path / 'test.db'}"


def test_ingest_creates_package_processing_records(test_db_url):
    """Ingest should create one package_processing_status row per active package."""
    service = _build_service(
        test_db_url,
        plugins={"demo": DemoAgentMemoryPlugin()},
        default_use_case="demo",
    )
    result = _ingest(service, use_case="demo")
    assert result.processing_status == "pending"

    storage = service._storage
    from storage.sqlite_schema import PackageProcessingStatusRecord
    with storage._session_factory() as session:
        records = session.scalars(
            select(PackageProcessingStatusRecord).where(
                PackageProcessingStatusRecord.source_item_id == result.source_item_id,
            )
        ).all()
    assert len(records) == 1
    assert records[0].package_name == "demo"
    assert records[0].status == "pending"
    assert records[0].source_item_created_at is not None


def test_package_processing_source_item_created_at_backfills_on_startup(test_db_url):
    service = _build_service(
        test_db_url,
        plugins={"demo": DemoAgentMemoryPlugin()},
        default_use_case="demo",
    )
    ingest = _ingest(service, use_case="demo")
    storage = service._storage

    with storage._engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE package_processing_status "
                "SET source_item_created_at = NULL "
                "WHERE source_item_id = :source_item_id"
            ),
            {"source_item_id": ingest.source_item_id},
        )

    reloaded_storage = SQLiteStorageProvider(test_db_url)

    from storage.sqlite_schema import PackageProcessingStatusRecord
    with reloaded_storage._session_factory() as session:
        record = session.scalars(
            select(PackageProcessingStatusRecord).where(
                PackageProcessingStatusRecord.source_item_id == ingest.source_item_id,
            )
        ).one()
        source_item = reloaded_storage.get_source_item(ingest.source_item_id)

    assert record.source_item_created_at.replace(tzinfo=timezone.utc) == source_item.created_at


# ── Tests: claim/complete lifecycle ───────────────────────────────────────

def test_claim_next_package_task_returns_source_item_and_package(test_db_url):
    """claim_next_package_task should return (source_item, package_name, attempts)."""
    service = _build_service(
        test_db_url,
        plugins={"demo": DemoAgentMemoryPlugin()},
        default_use_case="demo",
    )
    _ingest(service, use_case="demo")

    storage = service._storage
    task = storage.claim_next_package_task(
        worker_id="test", lease_seconds=60, max_attempts=3,
    )
    assert task is not None
    source_item, package_name, attempts = task
    assert package_name == "demo"
    assert attempts == 1
    assert source_item.content == "Test content for multi-package processing."


def test_complete_package_task_marks_source_item_completed(test_db_url):
    """When all packages are completed, source_item should be marked completed."""
    service = _build_service(
        test_db_url,
        plugins={"demo": DemoAgentMemoryPlugin()},
        default_use_case="demo",
    )
    ingest = _ingest(service, use_case="demo")

    # Process through the multi-package loop
    result = service.process_next_source_item(worker_id="test")
    assert result is not None
    assert result.processing_status == "completed"
    assert result.processing_attempts >= 1


def test_multi_package_all_succeed(test_db_url):
    """When multiple packages are registered and all succeed, source_item is completed."""
    service = _build_service(
        test_db_url,
        plugins={"demo": DemoAgentMemoryPlugin(), "noop": NoOpPlugin()},
        default_use_case="demo",
    )
    # Manually create package records for both packages
    ingest = _ingest(service, use_case="demo")
    storage = service._storage
    # The ingest creates records only for the default use_case.
    # Manually add the second package to test multi-package.
    storage.create_package_processing_records(
        ingest.source_item_id, ["noop"],
    )

    # Process — should handle both packages
    result = service.process_next_source_item(worker_id="test")
    assert result is not None

    # Source item should be completed after both packages
    status = service.get_item_processing(ingest.source_item_id)
    assert status.processing_status == "completed"


def test_multi_package_one_fails(test_db_url):
    """When one package fails and others succeed, source_item is marked failed."""
    service = _build_service(
        test_db_url,
        plugins={"always_fail": AlwaysFailPlugin(), "demo": DemoAgentMemoryPlugin()},
        default_use_case="demo",
    )
    ingest = _ingest(service, use_case="demo")
    storage = service._storage
    # Add the failing package
    storage.create_package_processing_records(
        ingest.source_item_id, ["always_fail"],
    )

    # Process all packages
    result = service.process_next_source_item(worker_id="test", max_attempts=1)
    assert result is not None
    assert result.processing_status == "failed"
    assert result.processing_error == "boom"


# ── Tests: fail/retry lifecycle ───────────────────────────────────────────

def test_package_failure_allows_retry(test_db_url):
    """Failed package should be retriable if max_attempts not exhausted."""
    service = _build_service(
        test_db_url,
        plugins={"always_fail": AlwaysFailPlugin()},
        default_use_case="always_fail",
    )
    ingest = _ingest(service, use_case="always_fail")

    # Process with max_attempts=2 — first attempt should fail but not be final
    result = service.process_next_source_item(worker_id="test", max_attempts=2)
    assert result is not None
    # Source item should be "pending" (one attempt used, one left)
    assert result.processing_status == "pending"

    # Check the package task state
    storage = service._storage
    from sqlalchemy import select
    from storage.sqlite_schema import PackageProcessingStatusRecord
    with storage._session_factory() as session:
        records = session.scalars(
            select(PackageProcessingStatusRecord).where(
                PackageProcessingStatusRecord.source_item_id == ingest.source_item_id,
            )
        ).all()
    assert len(records) == 1
    assert records[0].status == "pending"  # Retriable
    assert records[0].attempts == 1
    assert records[0].error == "boom"
    assert records[0].next_attempt_at is not None

    # Process again with a future timestamp past the backoff
    future = records[0].next_attempt_at + timedelta(seconds=1)
    task = storage.claim_next_package_task(
        worker_id="test", lease_seconds=60, max_attempts=2, now=future,
    )
    assert task is not None
    _, pkg, attempts = task
    assert pkg == "always_fail"
    assert attempts == 2  # Second attempt


# ── Tests: claim_next_package_task_for_item ──────────────────────────────

def test_claim_for_specific_item(test_db_url):
    """claim_next_package_task_for_item should only return packages for the given item."""
    service = _build_service(
        test_db_url,
        plugins={"demo": DemoAgentMemoryPlugin(), "noop": NoOpPlugin()},
        default_use_case="demo",
    )
    ingest = _ingest(service, use_case="demo")
    storage = service._storage
    storage.create_package_processing_records(
        ingest.source_item_id, ["noop"],
    )

    # Claim first package for the item
    task1 = storage.claim_next_package_task(
        worker_id="test", lease_seconds=60, max_attempts=3,
    )
    assert task1 is not None
    _, pkg1, _ = task1
    storage.complete_package_task(ingest.source_item_id, pkg1)

    # Claim next package for same item
    task2 = storage.claim_next_package_task_for_item(
        ingest.source_item_id,
        worker_id="test", lease_seconds=60, max_attempts=3,
    )
    assert task2 is not None
    pkg2, attempts2 = task2
    assert pkg2 != pkg1  # Different package
    assert attempts2 == 1

    # No more packages for this item
    task3 = storage.claim_next_package_task_for_item(
        ingest.source_item_id,
        worker_id="test", lease_seconds=60, max_attempts=3,
    )
    assert task3 is None


# ── Tests: commit_package_process_result ──────────────────────────────────

def test_commit_package_process_result_does_not_change_source_item_state(test_db_url):
    """commit_package_process_result should not mark source_item as completed."""
    service = _build_service(
        test_db_url,
        plugins={"demo": DemoAgentMemoryPlugin(), "noop": NoOpPlugin()},
        default_use_case="demo",
    )
    ingest = _ingest(service, use_case="demo")
    storage = service._storage
    storage.create_package_processing_records(
        ingest.source_item_id, ["noop"],
    )

    # Commit an empty process result
    storage.commit_package_process_result(
        source_item_id=ingest.source_item_id,
        result=ProcessResult(memory_objects=[], relations=[], index_entries=[]),
    )

    # Source item should still be pending
    item = storage.get_source_item(ingest.source_item_id)
    assert item.processing_status == "pending"


# ── Tests: skipped packages ───────────────────────────────────────────────

def test_skipped_packages_count_as_terminal(test_db_url):
    """Skipped packages should not block source_item completion."""
    storage = SQLiteStorageProvider(test_db_url)
    service = PalliumService(
        storage=storage,
        retrieval=LexicalRetrievalProvider(storage),
        semantic_plugins={"demo": DemoAgentMemoryPlugin()},
        default_use_case="demo",
    )
    ingest = _ingest(service, use_case="demo")

    # Add a skipped package
    storage.create_package_processing_records(
        ingest.source_item_id, ["skipped_pkg"], skip_packages=["skipped_pkg"],
    )

    # Process the non-skipped package
    result = service.process_next_source_item(worker_id="test")
    assert result is not None
    assert result.processing_status == "completed"


# ── Tests: no package tasks available falls through to legacy ─────────────

def test_no_package_tasks_falls_back_to_legacy_claim(test_db_url):
    """When no package_processing_status rows exist, the legacy claim path should work."""
    storage = SQLiteStorageProvider(test_db_url)
    service = PalliumService(
        storage=storage,
        retrieval=LexicalRetrievalProvider(storage),
        semantic_plugins={"demo": DemoAgentMemoryPlugin()},
        default_use_case="demo",
    )
    # Create a source item directly via storage without package tracking rows
    from core.contracts import build_source_item
    from core.indexing import SOURCE_ITEM_CONTENT_TEXT_VIEW, build_index_entry
    item = build_source_item(
        source_type="test", source_id="legacy-1",
        content_type="text/plain", content="Legacy item.",
        metadata=None, use_case="demo",
        processing_status="pending",
    )
    storage.create_source_item(item)

    # No package_processing_status rows — legacy claim should work
    result = service.process_next_source_item(worker_id="test")
    assert result is not None
    assert result.processing_status == "completed"


# ── Tests: legacy claim excluded when package path is active ─────────────

def test_legacy_claim_excluded_when_packages_pending(test_db_url):
    """Legacy claim_next_source_item must not return items with pending package rows."""
    storage = SQLiteStorageProvider(test_db_url)
    service = PalliumService(
        storage=storage,
        retrieval=LexicalRetrievalProvider(storage),
        semantic_plugins={"demo": DemoAgentMemoryPlugin()},
        default_use_case="demo",
    )
    _ingest(service, use_case="demo")

    # Package rows exist with status='pending' — legacy path must skip this item
    claimed = storage.claim_next_source_item(
        worker_id="rival-worker", lease_seconds=60, max_attempts=3,
    )
    assert claimed is None


def test_legacy_claim_excluded_when_package_processing(test_db_url):
    """Legacy claim_next_source_item must not return items with in-progress package rows."""
    storage = SQLiteStorageProvider(test_db_url)
    service = PalliumService(
        storage=storage,
        retrieval=LexicalRetrievalProvider(storage),
        semantic_plugins={"demo": DemoAgentMemoryPlugin(), "noop": NoOpPlugin()},
        default_use_case="demo",
    )
    ingest = _ingest(service, use_case="demo")
    storage.create_package_processing_records(ingest.source_item_id, ["noop"])

    # Claim one package (now 'processing'), the other remains 'pending'
    task = storage.claim_next_package_task(
        worker_id="worker-1", lease_seconds=60, max_attempts=3,
    )
    assert task is not None

    # Legacy path from a second worker must still be blocked
    claimed = storage.claim_next_source_item(
        worker_id="worker-2", lease_seconds=60, max_attempts=3,
    )
    assert claimed is None


def test_legacy_claim_works_without_package_rows(test_db_url):
    """Items with no package_processing_status rows remain claimable by legacy path."""
    storage = SQLiteStorageProvider(test_db_url)
    service = PalliumService(
        storage=storage,
        retrieval=LexicalRetrievalProvider(storage),
        semantic_plugins={"demo": DemoAgentMemoryPlugin()},
        default_use_case="demo",
    )
    from core.contracts import build_source_item
    item = build_source_item(
        source_type="test", source_id="pre-migration-1",
        content_type="text/plain", content="Pre-migration item.",
        metadata=None, use_case="demo",
        processing_status="pending",
    )
    storage.create_source_item(item)

    claimed = storage.claim_next_source_item(
        worker_id="worker-1", lease_seconds=60, max_attempts=3,
    )
    assert claimed is not None
    assert claimed.id == item.id
