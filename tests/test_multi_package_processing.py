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


def test_expired_final_attempt_package_lease_is_terminalized(test_db_url):
    service = _build_service(
        test_db_url,
        plugins={"demo": DemoAgentMemoryPlugin(), "noop": NoOpPlugin()},
        default_use_case="demo",
    )
    ingest = _ingest(service, use_case="demo")
    storage = service._storage
    storage.create_package_processing_records(ingest.source_item_id, ["noop"])
    storage.complete_package_task(ingest.source_item_id, "noop")
    now = utc_now()

    with storage._engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE package_processing_status "
                "SET status='processing', attempts=3, claimed_by='dead-worker', "
                "claimed_at=:past, lease_expires_at=:past, error='provider failed' "
                "WHERE source_item_id=:source_item_id AND package_name='demo'"
            ),
            {"source_item_id": ingest.source_item_id, "past": now - timedelta(seconds=1)},
        )

    assert storage.claim_next_package_task(
        worker_id="recovery", lease_seconds=60, max_attempts=3, now=now,
    ) is None
    assert storage.claim_next_package_task(
        worker_id="recovery", lease_seconds=60, max_attempts=3, now=now,
    ) is None

    with storage._session_factory() as session:
        from storage.sqlite_schema import PackageProcessingStatusRecord
        package = session.scalars(
            select(PackageProcessingStatusRecord).where(
                PackageProcessingStatusRecord.source_item_id == ingest.source_item_id,
                PackageProcessingStatusRecord.package_name == "demo",
            )
        ).one()
    assert package.status == "failed"
    assert package.attempts == 3
    assert package.error == "provider failed"
    assert package.claimed_by is None
    assert package.lease_expires_at is None

    source = service.get_item_processing(ingest.source_item_id)
    assert source.processing_status == "failed"
    assert source.processing_attempts == 3


def test_expired_package_lease_below_ceiling_remains_reclaimable(test_db_url):
    service = _build_service(
        test_db_url,
        plugins={"demo": DemoAgentMemoryPlugin()},
        default_use_case="demo",
    )
    ingest = _ingest(service, use_case="demo")
    storage = service._storage
    now = utc_now()
    with storage._engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE package_processing_status "
                "SET status='processing', attempts=2, claimed_by='dead-worker', "
                "claimed_at=:past, lease_expires_at=:past "
                "WHERE source_item_id=:source_item_id"
            ),
            {"source_item_id": ingest.source_item_id, "past": now - timedelta(seconds=1)},
        )

    task = storage.claim_next_package_task(
        worker_id="recovery", lease_seconds=60, max_attempts=3, now=now,
    )
    assert task is not None
    assert task[1:] == ("demo", 3)


def test_active_final_attempt_package_lease_is_not_terminalized(test_db_url):
    service = _build_service(
        test_db_url,
        plugins={"demo": DemoAgentMemoryPlugin()},
        default_use_case="demo",
    )
    ingest = _ingest(service, use_case="demo")
    storage = service._storage
    now = utc_now()
    with storage._engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE package_processing_status "
                "SET status='processing', attempts=3, claimed_by='live-worker', "
                "claimed_at=:now, lease_expires_at=:future "
                "WHERE source_item_id=:source_item_id"
            ),
            {
                "source_item_id": ingest.source_item_id,
                "now": now,
                "future": now + timedelta(seconds=60),
            },
        )

    assert storage.claim_next_package_task(
        worker_id="other", lease_seconds=60, max_attempts=3, now=now,
    ) is None
    with storage._session_factory() as session:
        from storage.sqlite_schema import PackageProcessingStatusRecord
        package = session.scalars(
            select(PackageProcessingStatusRecord).where(
                PackageProcessingStatusRecord.source_item_id == ingest.source_item_id,
            )
        ).one()
    assert package.status == "processing"
    assert package.claimed_by == "live-worker"

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


def test_claim_for_specific_item_settles_expired_final_attempt(test_db_url):
    service = _build_service(
        test_db_url,
        plugins={"demo": DemoAgentMemoryPlugin()},
        default_use_case="demo",
    )
    ingest = _ingest(service, use_case="demo")
    storage = service._storage
    now = utc_now()
    with storage._session_factory() as session:
        session.execute(
            text(
                "UPDATE package_processing_status "
                "SET status='processing', attempts=3, claimed_by='dead-worker', "
                "claimed_at=:past, lease_expires_at=:past "
                "WHERE source_item_id=:source_item_id"
            ),
            {"source_item_id": ingest.source_item_id, "past": now - timedelta(seconds=1)},
        )
        session.commit()

    assert storage.claim_next_package_task_for_item(
        ingest.source_item_id,
        worker_id="recovery",
        lease_seconds=60,
        max_attempts=3,
        now=now,
    ) is None
    result = service.get_item_processing(ingest.source_item_id)
    assert result.processing_status == "failed"
    assert result.processing_claimed_at is None


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
def test_explicit_disabled_package_ingests_raw_without_package_work(test_db_url):
    storage = SQLiteStorageProvider(test_db_url)
    service = PalliumService(
        storage=storage,
        retrieval=LexicalRetrievalProvider(storage),
        semantic_plugins={},
        default_use_case="demo",
        configured_use_cases=("demo",),
    )

    result = _ingest(service, use_case="demo")

    assert result.processing_status == "completed"
    with storage._session_factory() as session:
        assert session.execute(text("SELECT COUNT(*) FROM package_processing_status")).scalar() == 0


def test_explicit_unknown_package_is_rejected_without_storing_raw(test_db_url):
    storage = SQLiteStorageProvider(test_db_url)
    service = PalliumService(
        storage=storage,
        retrieval=LexicalRetrievalProvider(storage),
        semantic_plugins={},
        default_use_case="demo",
        configured_use_cases=("demo",),
    )

    with pytest.raises(ValueError, match="Unsupported use case: unknown"):
        _ingest(service, use_case="unknown")
    assert storage.find_source_item(source_type="test", source_id="item-1") is None

@pytest.mark.parametrize("task_state", ["pending", "failed", "processing", "expired"])
def test_cancel_disabled_package_work_clears_all_unfinished_states_and_scopes(
    test_db_url, task_state,
):
    from core.models import MemoryObject
    from storage.base import ThreadProcessingScope
    from storage.sqlite_schema import PackageProcessingStatusRecord

    service = _build_service(
        test_db_url,
        plugins={"disabled": NoOpPlugin(), "keep": NoOpPlugin()},
        default_use_case="disabled",
    )
    active = _ingest(service, source_id=f"active-{task_state}", use_case="disabled")
    completed = _ingest(service, source_id=f"completed-{task_state}", use_case="keep")
    storage = service._storage

    completed_task = storage.claim_next_package_task_for_item(
        completed.source_item_id, worker_id="keep-worker", lease_seconds=60, max_attempts=3,
    )
    assert completed_task is not None
    _, completed_attempts = completed_task
    kept_memory = MemoryObject(
        type="decision", schema_id="test.decision", schema_version="1",
        payload={"decision": "preserve completed data"}, visibility="private",
    )
    assert storage.commit_package_process_result(
        source_item_id=completed.source_item_id,
        package_name="keep",
        result=ProcessResult(memory_objects=[kept_memory], relations=[], index_entries=[]),
        worker_id="keep-worker", attempts=completed_attempts,
    ) == []
    storage.complete_package_task(completed.source_item_id, "keep")

    thread_scope = ThreadProcessingScope(
        scope_key=f"disabled-thread-{task_state}", use_case="disabled",
        container_ref="container-a", thread_ref="thread-a",
    )
    container_scope = ThreadProcessingScope(
        scope_key=f"disabled-container-{task_state}", use_case="disabled",
        container_ref="container-a", thread_ref=None,
    )
    storage.commit_package_process_result(
        source_item_id=active.source_item_id,
        package_name="disabled",
        result=ProcessResult(memory_objects=[], relations=[], index_entries=[]),
        thread_rebuild_scope=thread_scope,
        container_rebuild_scope=container_scope,
    )

    task = storage.claim_next_package_task_for_item(
        active.source_item_id, worker_id="disabled-worker", lease_seconds=60, max_attempts=3,
    )
    assert task is not None
    _, attempts = task
    if task_state == "failed":
        with storage._engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE package_processing_status "
                    "SET status = 'failed', error = 'retryable', next_attempt_at = :next_attempt "
                    "WHERE source_item_id = :source_item_id AND package_name = 'disabled'"
                ),
                {"next_attempt": utc_now() - timedelta(seconds=1), "source_item_id": active.source_item_id},
            )
    elif task_state in {"processing", "expired"}:
        if task_state == "expired":
            with storage._engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE package_processing_status SET lease_expires_at = :expired "
                        "WHERE source_item_id = :source_item_id AND package_name = 'disabled'"
                    ),
                    {"expired": utc_now() - timedelta(seconds=1), "source_item_id": active.source_item_id},
                )
    else:
        with storage._engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE package_processing_status "
                    "SET status = 'pending', attempts = 0, claimed_by = NULL, "
                    "claimed_at = NULL, lease_expires_at = NULL "
                    "WHERE source_item_id = :source_item_id AND package_name = 'disabled'"
                ),
                {"source_item_id": active.source_item_id},
            )

    if task_state in {"processing", "expired"}:
        assert storage.claim_thread_processing_scope(
            scope=thread_scope, worker_id="rebuild-worker", lease_seconds=60,
        ) is not None
        assert storage.claim_thread_processing_scope(
            scope=container_scope, worker_id="rebuild-worker", lease_seconds=60,
        ) is not None
        if task_state == "expired":
            with storage._engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE thread_processing_leases "
                        "SET processing_lease_expires_at = :expired "
                        "WHERE scope_key IN (:thread_key, :container_key)"
                    ),
                    {
                        "expired": utc_now() - timedelta(seconds=1),
                        "thread_key": thread_scope.scope_key,
                        "container_key": container_scope.scope_key,
                    },
                )

    assert storage.cancel_disabled_package_work(("disabled",)) == {
        "package_tasks": 1, "legacy_source_items": 0, "rebuild_scopes": 2,
    }
    assert storage.cancel_disabled_package_work(("disabled",)) == {
        "package_tasks": 0, "legacy_source_items": 0, "rebuild_scopes": 0,
    }

    with storage._session_factory() as session:
        package = session.scalars(
            select(PackageProcessingStatusRecord).where(
                PackageProcessingStatusRecord.source_item_id == active.source_item_id,
                PackageProcessingStatusRecord.package_name == "disabled",
            )
        ).one()
        kept_package = session.scalars(
            select(PackageProcessingStatusRecord).where(
                PackageProcessingStatusRecord.source_item_id == completed.source_item_id,
                PackageProcessingStatusRecord.package_name == "keep",
            )
        ).one()
        assert package.status == "skipped"
        assert package.error == "package_disabled"
        assert package.claimed_by is None
        assert package.claimed_at is None
        assert package.lease_expires_at is None
        assert package.next_attempt_at is None
        assert kept_package.status == "completed"
        assert kept_package.error is None

    assert storage.get_memory_object(kept_memory.id).payload == kept_memory.payload
    for scope in (thread_scope, container_scope):
        lease = storage.get_thread_processing_lease(scope.scope_key)
        assert lease is not None
        assert lease.requested_at is None
        assert lease.processing_claimed_by is None
        assert lease.processing_lease_expires_at is None

# ── Tests: disabled-package transition and stale-claim fencing ─────────────

def test_disabling_package_cancels_unfinished_work_and_fences_stale_result(test_db_url):
    from core.models import IndexEntry, MemoryObject
    from storage.base import ThreadProcessingScope
    from storage.sqlite_schema import PackageProcessingStatusRecord

    enabled = _build_service(
        test_db_url,
        plugins={"demo": DemoAgentMemoryPlugin()},
        default_use_case="demo",
    )
    ingest = _ingest(enabled, use_case="demo")
    storage = enabled._storage
    task = storage.claim_next_package_task(
        worker_id="old-worker", lease_seconds=60, max_attempts=3,
    )
    assert task is not None
    _, package_name, attempts = task
    scope = ThreadProcessingScope(
        scope_key="disabled-thread",
        use_case="demo",
        container_ref="container-a",
        thread_ref="thread-a",
    )
    storage.commit_package_process_result(
        source_item_id=ingest.source_item_id,
        result=ProcessResult(memory_objects=[], relations=[], index_entries=[]),
        thread_rebuild_scope=scope,
    )
    assert storage.claim_thread_processing_scope(
        scope=scope, worker_id="old-rebuilder", lease_seconds=60,
    ) is not None

    PalliumService(
        storage=storage,
        retrieval=LexicalRetrievalProvider(storage),
        semantic_plugins={},
        default_use_case="demo",
        configured_use_cases=("demo",),
    )

    stale_memory = MemoryObject(
        type="decision",
        schema_id="test.decision",
        schema_version="1",
        payload={"decision": "must never be persisted"},
        container_ref="container-a",
        visibility="private",
    )
    stale_index = IndexEntry(
        target_kind="memory_object", target_id=stale_memory.id,
        index_type="lexical", text_view="stale side effect",
    )
    assert storage.commit_package_process_result(
        source_item_id=ingest.source_item_id,
        result=ProcessResult(
            memory_objects=[stale_memory],
            relations=[],
            index_entries=[stale_index],
            source_item_metadata_updates={ingest.source_item_id: {"stale_marker": True}},
        ),
        package_name=package_name,
        thread_rebuild_scope=scope,
        worker_id="old-worker",
        attempts=attempts,
    ) is None
    assert storage.fail_package_task(
        ingest.source_item_id,
        package_name,
        error="late failure",
        next_attempt_at=None,
        final=True,
        worker_id="old-worker",
        attempts=attempts,
    ) is False
    assert storage.list_memory_objects(include_candidates=True) == []
    assert storage.list_index_entries_for_target("memory_object", stale_memory.id) == []
    assert storage.get_thread_processing_lease(scope.scope_key).requested_at is None
    assert storage.get_source_item(ingest.source_item_id).metadata.get("stale_marker") is None
    assert enabled.get_item_processing(ingest.source_item_id).processing_status == "completed"
    with storage._session_factory() as session:
        package = session.scalars(
            select(PackageProcessingStatusRecord).where(
                PackageProcessingStatusRecord.source_item_id == ingest.source_item_id,
            )
        ).one()
    assert package.status == "skipped"
    assert package.error == "package_disabled"
    assert package.claimed_by is None


def test_atomic_package_commit_completes_only_the_current_claim(test_db_url):
    service = _build_service(
        test_db_url,
        plugins={"demo": DemoAgentMemoryPlugin()},
        default_use_case="demo",
    )
    ingest = _ingest(service, use_case="demo")
    storage = service._storage
    task = storage.claim_next_package_task(
        worker_id="winner", lease_seconds=60, max_attempts=3,
    )
    assert task is not None
    _, package_name, attempts = task

    assert storage.commit_package_process_result(
        source_item_id=ingest.source_item_id,
        result=ProcessResult(memory_objects=[], relations=[], index_entries=[]),
        package_name=package_name,
        worker_id="winner",
        attempts=attempts,
    ) == []
    assert service.get_item_processing(ingest.source_item_id).processing_status == "completed"
    assert storage.commit_package_process_result(
        source_item_id=ingest.source_item_id,
        result=ProcessResult(memory_objects=[], relations=[], index_entries=[]),
        package_name=package_name,
        worker_id="winner",
        attempts=attempts,
    ) is None
# ── Tests: legacy rows during disable/re-enable ───────────────────────────

@pytest.mark.parametrize("task_state", ["pending", "failed", "processing", "expired"])
def test_disable_cancels_untracked_legacy_source_rows_and_reenable_skips(
    test_db_url, task_state,
):
    from core.contracts import build_source_item

    storage = SQLiteStorageProvider(test_db_url)
    item = build_source_item(
        source_type="test",
        source_id=f"legacy-disabled-{task_state}",
        content_type="text/plain",
        content="Legacy source work must not resume after package disable.",
        metadata={"state": task_state},
        use_case="legacy",
        processing_status="pending",
    )
    storage.create_source_item(item)
    now = utc_now()
    if task_state == "failed":
        status = "failed"
        attempts = 2
        error = "retryable legacy failure"
        claimed_by = None
        claimed_at = None
        lease_expires_at = None
    else:
        status = "processing" if task_state in {"processing", "expired"} else "pending"
        attempts = 1 if status == "processing" else 0
        error = None
        claimed_by = "legacy-worker" if status == "processing" else None
        claimed_at = now - timedelta(seconds=2) if status == "processing" else None
        lease_expires_at = (
            now - timedelta(seconds=1) if task_state == "expired"
            else now + timedelta(seconds=60) if status == "processing"
            else None
        )
    with storage._engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE source_items SET processing_status = :status, "
                "processing_attempts = :attempts, processing_error = :error, "
                "processing_claimed_by = :claimed_by, processing_claimed_at = :claimed_at, "
                "processing_lease_expires_at = :lease_expires_at WHERE id = :source_id"
            ),
            {
                "status": status,
                "attempts": attempts,
                "error": error,
                "claimed_by": claimed_by,
                "claimed_at": claimed_at,
                "lease_expires_at": lease_expires_at,
                "source_id": item.id,
            },
        )

    assert storage.cancel_disabled_package_work(("legacy",)) == {
        "package_tasks": 0, "legacy_source_items": 1, "rebuild_scopes": 0,
    }
    canceled = storage.get_source_item(item.id)
    assert canceled.processing_status == "skipped"
    assert canceled.processing_error == "package_disabled"
    assert canceled.processing_claimed_by is None
    assert canceled.processing_lease_expires_at is None
    assert canceled.processing_completed_at is not None
    assert storage.claim_next_source_item(
        worker_id="new-worker", lease_seconds=60, max_attempts=3,
    ) is None

    reenabled = _build_service(
        test_db_url, plugins={"legacy": NoOpPlugin()}, default_use_case="legacy",
    )
    assert reenabled.process_next_source_item(worker_id="reenabled") is None
    assert reenabled.process_next_thread_rebuild(worker_id="reenabled") is None
    assert reenabled.get_item_processing(item.id).processing_status == "skipped"
    with storage._engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM package_processing_status WHERE source_item_id = :source_id"),
            {"source_id": item.id},
        ).scalar_one() == 0


def test_completed_untracked_legacy_source_and_memory_survive_disable(test_db_url):
    from core.contracts import build_source_item
    from core.models import MemoryObject

    storage = SQLiteStorageProvider(test_db_url)
    service = PalliumService(
        storage=storage,
        retrieval=LexicalRetrievalProvider(storage),
        semantic_plugins={"legacy": NoOpPlugin()},
        default_use_case="legacy",
    )
    item = build_source_item(
        source_type="test",
        source_id="legacy-completed",
        content_type="text/plain",
        content="Completed legacy source remains usable after package disable.",
        metadata={"keep": True},
        use_case="legacy",
        processing_status="pending",
    )
    storage.create_source_item(item)
    claimed = storage.claim_next_source_item(
        worker_id="legacy-worker", lease_seconds=60, max_attempts=3,
    )
    assert claimed is not None
    memory = MemoryObject(
        type="decision",
        schema_id="test.decision",
        schema_version="1",
        payload={"decision": "completed legacy data survives"},
    )
    assert storage.commit_processed_source_item(
        source_item_id=item.id,
        result=ProcessResult(memory_objects=[memory], relations=[], index_entries=[]),
        worker_id="legacy-worker",
        attempts=claimed.processing_attempts,
    ) == []
    assert service.get_item_processing(item.id).processing_status == "completed"

    assert storage.cancel_disabled_package_work(("legacy",)) == {
        "package_tasks": 0, "legacy_source_items": 0, "rebuild_scopes": 0,
    }
    assert storage.get_source_item(item.id).processing_status == "completed"
    assert storage.get_memory_object(memory.id).payload == memory.payload


@pytest.mark.parametrize("stale_worker, stale_attempts", [("other-worker", 1), ("legacy-worker", 99)])
def test_stale_legacy_commit_and_fail_have_no_side_effects(
    test_db_url, stale_worker, stale_attempts,
):
    from core.contracts import build_source_item
    from core.models import IndexEntry, MemoryObject
    from storage.base import ThreadProcessingScope

    storage = SQLiteStorageProvider(test_db_url)
    item = build_source_item(
        source_type="test",
        source_id="legacy-stale",
        content_type="text/plain",
        metadata={"keep": "original"},
        content="Stale legacy result must not persist any derived side effect.",
        use_case="legacy",
        processing_status="pending",
    )
    storage.create_source_item(item)
    claimed = storage.claim_next_source_item(
        worker_id="legacy-worker", lease_seconds=60, max_attempts=3,
    )
    assert claimed is not None
    memory = MemoryObject(
        type="decision",
        schema_id="test.decision",
        schema_version="1",
        payload={"decision": "stale must be rejected"},
    )
    index = IndexEntry(
        target_kind="memory_object",
        target_id=memory.id,
        index_type="lexical",
        text_view="stale derived index",
    )
    scope = ThreadProcessingScope(
        scope_key="stale-legacy-rebuild",
        use_case="legacy",
        container_ref="legacy-container",
        thread_ref="legacy-thread",
    )
    result = ProcessResult(
        memory_objects=[memory],
        relations=[],
        index_entries=[index],
        source_item_metadata_updates={item.id: {"stale_marker": True}},
    )
    assert storage.commit_processed_source_item(
        source_item_id=item.id,
        result=result,
        thread_rebuild_scope=scope,
        worker_id=stale_worker,
        attempts=stale_attempts,
    ) is None
    assert storage.fail_source_item_processing(
        item.id,
        error="late legacy failure",
        next_attempt_at=None,
        final=True,
        worker_id=stale_worker,
        attempts=stale_attempts,
    ) is False

    current = storage.get_source_item(item.id)
    assert current.processing_status == "processing"
    assert current.processing_claimed_by == "legacy-worker"
    assert current.processing_attempts == 1
    assert current.metadata == {"keep": "original"}
    assert storage.list_memory_objects(include_candidates=True) == []
    assert storage.list_index_entries_for_target("memory_object", memory.id) == []
    assert storage.get_thread_processing_lease(scope.scope_key) is None
