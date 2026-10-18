from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest

from fastapi.testclient import TestClient
from sqlalchemy import text

from api.schemas import QueueHealthResponse
from app.config import AppConfig, RetentionConfig
from storage.vector_index import VectorIndexConfig
from tests.config_helpers import DEMO_SEMANTIC_PACKAGES, _vector_index_path_for_sqlite
from app.main import create_app
from core.contracts import MemoryRetentionPolicy
from core.models import IndexEntry, MemoryObject, Relation, SourceItem
from core.service import PalliumService
from retrieval.lexical import LexicalRetrievalProvider
from storage.base import RetentionLeaseLostError
from storage.sqlite import MaintenanceStateRecord, SQLiteStorageProvider


UTC = timezone.utc

_TEST_RETENTION_POLICY = MemoryRetentionPolicy(
    durable_types=frozenset({"decision", "investigation_outcome"}),
    working_types=frozenset({"thread_summary", "task_checkpoint", "continuity_memory", "pattern_memory"}),
    orphan_delete_types=frozenset({"turn_summary"}),
)


def _make_source(
    storage: SQLiteStorageProvider,
    *,
    source_id: str,
    occurred_at: datetime,
    created_at: datetime | None = None,
    artifact_kind: str = "message",
    role: str = "assistant",
    metadata: dict | None = None,
) -> SourceItem:
    source_item = SourceItem(
        source_type="chat_message",
        source_id=source_id,
        content_type="text/plain",
        content=f"content for {source_id}",
        metadata=metadata,
        occurred_at=occurred_at,
        artifact_kind=artifact_kind,
        role=role,
        processing_status="completed",
        processing_completed_at=created_at or occurred_at,
        created_at=created_at or occurred_at,
    )
    storage.create_source_item(source_item)
    storage.create_index_entry(
        IndexEntry(
            target_kind="source_item",
            target_id=source_item.id,
            index_type="lexical",
            text_view=source_item.content.lower(),
            text_view_name="source_item.content",
        )
    )
    return source_item


def _make_memory(
    storage: SQLiteStorageProvider,
    *,
    memory_type: str,
    created_at: datetime,
    source_items: list[SourceItem],
    lifecycle: str = "active",
) -> MemoryObject:
    memory = MemoryObject(
        type=memory_type,
        schema_id=f"tests.{memory_type}",
        schema_version="v1",
        payload={"summary": memory_type, "latest_occurred_at": created_at.isoformat()},
        lifecycle=lifecycle,
        created_at=created_at,
    )
    storage.create_memory_object(memory)
    storage.create_index_entry(
        IndexEntry(
            target_kind="memory_object",
            target_id=memory.id,
            index_type="lexical",
            text_view=memory_type,
            text_view_name=f"memory_object.{memory_type}",
        )
    )
    for source_item in source_items:
        storage.create_relation(
            Relation(
                from_kind="memory_object",
                from_id=memory.id,
                relation_type="supported_by",
                to_kind="source_item",
                to_id=source_item.id,
            )
        )
    return storage.get_memory_object(memory.id)


def test_retention_lease_is_single_winner_and_expired_lease_is_reclaimable(test_db_url: str) -> None:
    storage = SQLiteStorageProvider(test_db_url)
    now = datetime(2026, 3, 15, tzinfo=UTC)

    first = storage.claim_retention_lease(worker_id="cleaner-a", lease_seconds=30, now=now)
    second = storage.claim_retention_lease(worker_id="cleaner-b", lease_seconds=30, now=now)

    assert first is not None
    assert second is None

    reclaimed = storage.claim_retention_lease(
        worker_id="cleaner-b",
        lease_seconds=30,
        now=now + timedelta(seconds=31),
    )
    assert reclaimed is not None
    assert reclaimed.claimed_by == "cleaner-b"


def test_working_memory_uses_freshness_instead_of_raw_source_age(test_db_url: str) -> None:
    storage = SQLiteStorageProvider(test_db_url)
    now = datetime(2026, 3, 15, tzinfo=UTC)
    old_source = _make_source(
        storage,
        source_id="thread-old-source",
        occurred_at=now - timedelta(days=40),
    )
    memory = _make_memory(
        storage,
        memory_type="thread_summary",
        created_at=now - timedelta(days=5),
        source_items=[old_source],
    )

    stats = storage.run_retention_pass(now=now, batch_size=10, retention_policy=_TEST_RETENTION_POLICY)

    assert stats.deleted_memory_objects == 0
    assert storage.get_memory_object(memory.id).freshness_at == now - timedelta(days=5)
    assert storage.get_source_item(old_source.id).id == old_source.id



def test_stale_working_memory_is_deleted_and_sources_delete_on_later_pass(test_db_url: str) -> None:
    storage = SQLiteStorageProvider(test_db_url)
    now = datetime(2026, 3, 15, tzinfo=UTC)
    source_item = _make_source(
        storage,
        source_id="thread-stale-source",
        occurred_at=now - timedelta(days=45),
    )
    memory = _make_memory(
        storage,
        memory_type="task_checkpoint",
        created_at=now - timedelta(days=35),
        source_items=[source_item],
    )

    first_stats = storage.run_retention_pass(now=now, batch_size=1, retention_policy=_TEST_RETENTION_POLICY)

    assert first_stats.deleted_memory_objects == 1
    with pytest.raises(KeyError):
        storage.get_memory_object(memory.id)
    assert storage.get_source_item(source_item.id).id == source_item.id

    second_stats = storage.run_retention_pass(now=now, batch_size=10, retention_policy=_TEST_RETENTION_POLICY)

    assert second_stats.deleted_source_items == 1
    with pytest.raises(KeyError):
        storage.get_source_item(source_item.id)
    assert storage.list_index_entries_for_target("memory_object", memory.id) == []
    assert storage.list_relations_for_source_item(source_item.id) == []



def test_durable_memory_protects_supporting_source_items(test_db_url: str) -> None:
    storage = SQLiteStorageProvider(test_db_url)
    now = datetime(2026, 3, 15, tzinfo=UTC)
    source_item = _make_source(
        storage,
        source_id="durable-source",
        occurred_at=now - timedelta(days=90),
        artifact_kind="assistant_output",
    )
    decision = _make_memory(
        storage,
        memory_type="decision",
        created_at=now - timedelta(days=90),
        source_items=[source_item],
    )

    stats = storage.run_retention_pass(now=now, batch_size=10, retention_policy=_TEST_RETENTION_POLICY)

    assert stats.deleted_source_items == 0
    assert stats.skipped_protected_source_items == 1
    assert storage.get_memory_object(decision.id).id == decision.id
    assert storage.get_source_item(source_item.id).id == source_item.id



def test_low_value_meta_rows_age_out_and_retained_rows_strip_debug_metadata(test_db_url: str) -> None:
    storage = SQLiteStorageProvider(test_db_url)
    now = datetime(2026, 3, 15, tzinfo=UTC)
    low_value = _make_source(
        storage,
        source_id="low-value-meta",
        occurred_at=now - timedelta(days=5),
        artifact_kind="assistant_output",
        metadata={"pallium_semantic_signals": {"is_low_value_meta": True}},
    )
    retained = _make_source(
        storage,
        source_id="retained-debug",
        occurred_at=now - timedelta(days=5),
        artifact_kind="assistant_output",
        metadata={
            "observability_debug": {"trace": "remove me"},
            "pallium_semantic_signals": {"key_finding_text": "keep me"},
        },
    )
    _make_memory(
        storage,
        memory_type="decision",
        created_at=now - timedelta(days=5),
        source_items=[retained],
    )

    stats = storage.run_retention_pass(now=now, batch_size=20, retention_policy=_TEST_RETENTION_POLICY)

    assert stats.deleted_source_items == 1
    assert stats.stripped_debug_metadata == 1
    with pytest.raises(KeyError):
        storage.get_source_item(low_value.id)
    retained_after = storage.get_source_item(retained.id)
    assert "observability_debug" not in retained_after.metadata
    assert retained_after.metadata["pallium_semantic_signals"]["key_finding_text"] == "keep me"



def test_queue_health_exposes_retention_stats(test_db_url: str) -> None:
    config = AppConfig(
        storage_backend="sqlite",
        sqlite_url=test_db_url,
        default_use_case="demo_agent_memory",
        semantic_packages=DEMO_SEMANTIC_PACKAGES,
        retention=RetentionConfig(enabled=True, run_interval_seconds=300, lease_seconds=300, batch_size=20),
        vector_index=VectorIndexConfig(index_path=_vector_index_path_for_sqlite(test_db_url)),
    )
    client = TestClient(create_app(config))
    service = client.app.state.pallium_service
    storage = service._storage
    now = datetime(2026, 3, 15, tzinfo=UTC)
    low_value = _make_source(
        storage,
        source_id="queue-health-low-value",
        occurred_at=now - timedelta(days=5),
        artifact_kind="assistant_output",
        metadata={"pallium_semantic_signals": {"is_low_value_meta": True}},
    )

    stats = service.run_retention_pass(worker_id="health-cleaner", now=now)
    assert stats is not None

    response = client.get("/debug/queue/health")
    assert response.status_code == 200
    payload = QueueHealthResponse.model_validate(response.json())
    assert payload.retention.enabled is True
    assert payload.retention.last_run_started_at is not None
    assert payload.retention.last_deleted_source_items == 1
    with pytest.raises(KeyError):
        storage.get_source_item(low_value.id)


class RecordingObservability:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def emit(self, event_type: str, **fields: object) -> None:
        self.events.append({"event_type": event_type, **fields})


class LeaseLostBeforeCompletionStorage(SQLiteStorageProvider):
    def run_retention_pass(
        self,
        *,
        now: datetime,
        batch_size: int,
        lease=None,
        lease_seconds: int | None = None,
        lease_now: datetime | None = None,
        retention_policy=None,
    ):
        stats = super().run_retention_pass(
            now=now,
            batch_size=batch_size,
            lease=lease,
            lease_seconds=lease_seconds,
            lease_now=lease_now,
            retention_policy=retention_policy,
        )
        with self._session_factory.begin() as session:
            record = session.get(MaintenanceStateRecord, "retention_compaction")
            assert record is not None
            claimed_at = self._normalize_datetime(record.claimed_at) or now
            record.lease_expires_at = claimed_at - timedelta(seconds=1)
        return stats


def test_upgrade_backfill_resolves_null_freshness_and_keeps_fresh_working_memory_protected(test_db_url: str) -> None:
    initial_storage = SQLiteStorageProvider(test_db_url)
    now = datetime(2026, 3, 15, tzinfo=UTC)
    protected_source = _make_source(
        initial_storage,
        source_id="legacy-null-freshness-source",
        occurred_at=now - timedelta(days=45),
    )
    memory = _make_memory(
        initial_storage,
        memory_type="thread_summary",
        created_at=now - timedelta(days=5),
        source_items=[protected_source],
    )

    with initial_storage._engine.begin() as connection:
        connection.execute(
            text("UPDATE memory_objects SET freshness_at = NULL WHERE id = :memory_id"),
            {"memory_id": memory.id},
        )

    upgraded_storage = SQLiteStorageProvider(test_db_url)
    upgraded_memory = upgraded_storage.get_memory_object(memory.id)
    assert upgraded_memory.freshness_at == now - timedelta(days=5)

    protect_stats = upgraded_storage.run_retention_pass(now=now, batch_size=10, retention_policy=_TEST_RETENTION_POLICY)
    assert protect_stats.deleted_memory_objects == 0
    assert protect_stats.deleted_source_items == 0
    assert upgraded_storage.get_source_item(protected_source.id).id == protected_source.id

    stale_now = now + timedelta(days=31)
    stale_stats = upgraded_storage.run_retention_pass(now=stale_now, batch_size=1, retention_policy=_TEST_RETENTION_POLICY)
    assert stale_stats.deleted_memory_objects == 1
    with pytest.raises(KeyError):
        upgraded_storage.get_memory_object(memory.id)
    assert upgraded_storage.get_source_item(protected_source.id).id == protected_source.id

    source_cleanup_stats = upgraded_storage.run_retention_pass(now=stale_now, batch_size=10, retention_policy=_TEST_RETENTION_POLICY)
    assert source_cleanup_stats.deleted_source_items == 1
    with pytest.raises(KeyError):
        upgraded_storage.get_source_item(protected_source.id)


def test_source_retention_progresses_past_old_protected_prefix(test_db_url: str) -> None:
    storage = SQLiteStorageProvider(test_db_url)
    now = datetime(2026, 3, 15, tzinfo=UTC)

    for index in range(8):
        source_item = _make_source(
            storage,
            source_id=f"protected-prefix-{index}",
            occurred_at=now - timedelta(days=90 - index),
        )
        _make_memory(
            storage,
            memory_type="decision",
            created_at=now - timedelta(days=90 - index),
            source_items=[source_item],
        )

    deletable_sources = [
        _make_source(storage, source_id="later-deletable-1", occurred_at=now - timedelta(days=60)),
        _make_source(storage, source_id="later-deletable-2", occurred_at=now - timedelta(days=59)),
    ]

    pass_stats = [storage.run_retention_pass(now=now, batch_size=1, retention_policy=_TEST_RETENTION_POLICY) for _ in range(4)]

    assert sum(stat.deleted_source_items for stat in pass_stats) == 2
    for source_item in deletable_sources:
        with pytest.raises(KeyError):
            storage.get_source_item(source_item.id)

    durable_sources = [
        storage.find_source_item("chat_message", f"protected-prefix-{index}")
        for index in range(8)
    ]
    assert all(source_item is not None for source_item in durable_sources)


def test_service_surfaces_retention_lease_loss_without_reporting_completion(test_db_url: str) -> None:
    storage = LeaseLostBeforeCompletionStorage(test_db_url)
    observability = RecordingObservability()
    service = PalliumService(
        storage=storage,
        retrieval=LexicalRetrievalProvider(storage),
        semantic_plugins={},
        default_use_case="demo_agent_memory",
        observability=observability,
        retention_enabled=True,
        retention_lease_seconds=30,
        retention_batch_size=10,
    )
    now = datetime(2026, 3, 15, tzinfo=UTC)

    with pytest.raises(RetentionLeaseLostError):
        service.run_retention_pass(worker_id="lease-loss-cleaner", now=now)

    health = service.get_queue_health()
    assert health.retention.last_run_started_at == now
    assert health.retention.last_run_completed_at is None
    assert [event["event_type"] for event in observability.events] == [
        "retention_pass_started",
        "retention_pass_failed",
    ]
    assert observability.events[-1]["failure_reason"] == "lease_lost"
    assert observability.events[-1]["lease_release_succeeded"] is False


def test_purge_suppressed_deletes_only_suppressed(test_db_url: str) -> None:
    storage = SQLiteStorageProvider(test_db_url)
    now = datetime(2026, 3, 15, tzinfo=UTC)
    source = _make_source(storage, source_id="src-purge", occurred_at=now)

    active = _make_memory(storage, memory_type="decision", created_at=now, source_items=[source])
    superseded = _make_memory(
        storage, memory_type="decision", created_at=now, source_items=[source], lifecycle="superseded"
    )
    suppressed = _make_memory(
        storage, memory_type="atomic_fact", created_at=now, source_items=[source], lifecycle="suppressed"
    )

    stats = storage.purge_suppressed()

    assert stats.deleted_memory_objects == 1
    assert stats.deleted_relations >= 1
    assert stats.deleted_index_entries >= 1
    assert storage.get_memory_object(active.id) is not None
    assert storage.get_memory_object(superseded.id) is not None
    with pytest.raises(KeyError):
        storage.get_memory_object(suppressed.id)


def test_purge_suppressed_empty(test_db_url: str) -> None:
    storage = SQLiteStorageProvider(test_db_url)
    stats = storage.purge_suppressed()
    assert stats.deleted_memory_objects == 0


def test_purge_suppressed_comprehensive_cascade_and_preservation(test_db_url: str) -> None:
    """Verify purge removes ALL artifacts of suppressed objects, preserves everything else."""
    from core.models import MemoryFlag
    storage = SQLiteStorageProvider(test_db_url)
    now = datetime(2026, 3, 15, tzinfo=UTC)

    shared_source = _make_source(storage, source_id="shared-src", occurred_at=now)
    suppressed_only_source = _make_source(storage, source_id="suppressed-only-src", occurred_at=now)

    active_mem = _make_memory(
        storage, memory_type="decision", created_at=now, source_items=[shared_source]
    )
    suppressed_mem_1 = _make_memory(
        storage, memory_type="atomic_fact", created_at=now,
        source_items=[shared_source], lifecycle="suppressed",
    )
    suppressed_mem_2 = _make_memory(
        storage, memory_type="fact_summary", created_at=now,
        source_items=[suppressed_only_source], lifecycle="suppressed",
    )

    storage.create_index_entry(
        IndexEntry(
            target_kind="memory_object",
            target_id=suppressed_mem_1.id,
            index_type="vector",
            text_view="vector content suppressed 1",
            text_view_name="embedding",
        )
    )
    storage.create_index_entry(
        IndexEntry(
            target_kind="memory_object",
            target_id=active_mem.id,
            index_type="vector",
            text_view="vector content active",
            text_view_name="embedding",
        )
    )

    storage.store_memory_flag(MemoryFlag(
        memory_object_id=suppressed_mem_1.id,
        reason="noisy fact", source_ref="test-agent",
    ))
    storage.store_memory_flag(MemoryFlag(
        memory_object_id=active_mem.id,
        reason="should survive", source_ref="test-agent",
    ))

    active_indexes_before = storage.list_index_entries_for_target("memory_object", active_mem.id)
    active_relations_before = len([
        r for r in storage.list_relations_for_source_item(shared_source.id)
        if r.from_id == active_mem.id
    ])

    with storage._engine.connect() as conn:
        fts_count_before = conn.execute(text("SELECT COUNT(*) FROM lexical_fts")).scalar()

    stats = storage.purge_suppressed()

    assert stats.deleted_memory_objects == 2
    assert stats.deleted_relations >= 2
    assert stats.deleted_index_entries >= 3

    with pytest.raises(KeyError):
        storage.get_memory_object(suppressed_mem_1.id)
    with pytest.raises(KeyError):
        storage.get_memory_object(suppressed_mem_2.id)

    assert storage.get_memory_object(active_mem.id) is not None

    assert storage.get_source_item(shared_source.id) is not None
    assert storage.get_source_item(suppressed_only_source.id) is not None

    assert storage.list_index_entries_for_target("memory_object", suppressed_mem_1.id) == []
    assert storage.list_index_entries_for_target("memory_object", suppressed_mem_2.id) == []

    active_indexes_after = storage.list_index_entries_for_target("memory_object", active_mem.id)
    assert len(active_indexes_after) == len(active_indexes_before)
    assert {e.id for e in active_indexes_after} == {e.id for e in active_indexes_before}

    active_relations_after = [
        r for r in storage.list_relations_for_source_item(shared_source.id)
        if r.from_id == active_mem.id
    ]
    assert len(active_relations_after) == active_relations_before

    with storage._engine.connect() as conn:
        fts_count_after = conn.execute(text("SELECT COUNT(*) FROM lexical_fts")).scalar()
        assert fts_count_after < fts_count_before
        for mem_id in (suppressed_mem_1.id, suppressed_mem_2.id):
            orphan_fts = conn.execute(
                text("SELECT COUNT(*) FROM lexical_fts WHERE target_id = :tid"),
                {"tid": mem_id},
            ).scalar()
            assert orphan_fts == 0, f"FTS5 orphan rows remain for {mem_id}"

    assert storage.count_total_flags(suppressed_mem_1.id) == 0
    assert storage.count_total_flags(active_mem.id) == 1


def test_purge_suppressed_batches_correctly(test_db_url: str) -> None:
    """Verify purge handles >50 items (multiple batches) without losing any."""
    storage = SQLiteStorageProvider(test_db_url)
    now = datetime(2026, 3, 15, tzinfo=UTC)
    source = _make_source(storage, source_id="batch-src", occurred_at=now)

    suppressed_ids = []
    for i in range(75):
        mem = _make_memory(
            storage, memory_type="atomic_fact", created_at=now + timedelta(seconds=i),
            source_items=[source], lifecycle="suppressed",
        )
        suppressed_ids.append(mem.id)

    active = _make_memory(storage, memory_type="decision", created_at=now, source_items=[source])

    stats = storage.purge_suppressed()

    assert stats.deleted_memory_objects == 75
    for mem_id in suppressed_ids:
        with pytest.raises(KeyError):
            storage.get_memory_object(mem_id)
    assert storage.get_memory_object(active.id) is not None
    assert storage.get_source_item(source.id) is not None


def test_purge_suppressed_lexical_search_intact_for_active(test_db_url: str) -> None:
    """After purge, lexical search still returns active memory hits — retrieval path unbroken."""
    storage = SQLiteStorageProvider(test_db_url)
    now = datetime(2026, 3, 15, tzinfo=UTC)
    source = _make_source(storage, source_id="search-src", occurred_at=now)

    active = _make_memory(storage, memory_type="decision", created_at=now, source_items=[source])
    storage.create_index_entry(
        IndexEntry(
            target_kind="memory_object",
            target_id=active.id,
            index_type="lexical",
            text_view="important architecture decision about caching",
            text_view_name="memory_object.summary",
        )
    )
    suppressed = _make_memory(
        storage, memory_type="atomic_fact", created_at=now,
        source_items=[source], lifecycle="suppressed",
    )
    storage.create_index_entry(
        IndexEntry(
            target_kind="memory_object",
            target_id=suppressed.id,
            index_type="lexical",
            text_view="noisy fact about caching layer implementation",
            text_view_name="memory_object.summary",
        )
    )

    from core.text import tokenize_text
    tokens = tokenize_text("caching")

    with storage._engine.connect() as conn:
        fts_rows_before = conn.execute(
            text("SELECT target_id FROM lexical_fts WHERE lexical_fts MATCH '\"caching\"'")
        ).fetchall()
    fts_target_ids_before = {row[0] for row in fts_rows_before}
    assert active.id in fts_target_ids_before
    assert suppressed.id in fts_target_ids_before

    storage.purge_suppressed()

    results_after = storage.search_index_entries(tokens, limit=10)
    hit_ids_after = {hit.target_id for hit in results_after.hits}
    assert active.id in hit_ids_after

    with storage._engine.connect() as conn:
        fts_rows_after = conn.execute(
            text("SELECT target_id FROM lexical_fts WHERE lexical_fts MATCH '\"caching\"'")
        ).fetchall()
    fts_target_ids_after = {row[0] for row in fts_rows_after}
    assert active.id in fts_target_ids_after
    assert suppressed.id not in fts_target_ids_after


def test_source_retention_prepares_protected_suffix_without_holding_writer(test_db_url, monkeypatch):
    import sqlite3
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path

    storage = SQLiteStorageProvider(test_db_url)
    now = datetime(2026, 10, 12, tzinfo=UTC)
    entered, release = threading.Event(), threading.Event()
    original = storage._source_item_is_protected
    future = None
    try:
        first = _make_source(storage, source_id="expired-first", occurred_at=now - timedelta(days=90))
        protected = _make_source(storage, source_id="protected-later", occurred_at=now - timedelta(days=89))
        memory = _make_memory(storage, memory_type="decision", created_at=protected.created_at, source_items=[protected])
        # Keep the existing marker case distinct from the zero-row writer proof.
        assert storage.claim_retention_lease(worker_id="private-proof", lease_seconds=60, now=now)

        def held_check(session, source_id, **kwargs):
            result = original(session, source_id, **kwargs)
            if source_id == protected.id and not release.is_set():
                entered.set()
                assert release.wait(5), "test did not release protected preparation"
            return result

        monkeypatch.setattr(storage, "_source_item_is_protected", held_check)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(storage.run_retention_pass, now=now, batch_size=2,
                                 retention_policy=_TEST_RETENTION_POLICY)
            try:
                assert entered.wait(5)
                uri = Path(storage._engine.url.database).resolve().as_uri() + "?mode=rw"
                with sqlite3.connect(uri, uri=True, timeout=0) as competitor:
                    competitor.execute("BEGIN IMMEDIATE")
                    competitor.execute("UPDATE source_items SET processing_status=processing_status WHERE id=?", (protected.id,))
                    competitor.commit()
            finally:
                release.set()
                stats = future.result(timeout=5)
        assert stats.deleted_source_items == 1
        assert stats.skipped_protected_source_items == 1
        with pytest.raises(KeyError):
            storage.get_source_item(first.id)
        assert storage.get_source_item(protected.id).content == protected.content
        assert storage.get_memory_object(memory.id).lifecycle == "active"
    finally:
        release.set()
        storage.close()


@pytest.mark.parametrize("marker_exists", [False, True])
def test_source_retention_owns_writer_before_fresh_checks(test_db_url, monkeypatch, marker_exists):
    import sqlite3
    from pathlib import Path

    storage = SQLiteStorageProvider(test_db_url)
    now = datetime(2026, 10, 12, tzinfo=UTC)
    try:
        source = _make_source(storage, source_id="expired", occurred_at=now - timedelta(days=90))
        if marker_exists:
            storage.claim_retention_lease(worker_id="marker", lease_seconds=60, now=now)
        original = storage._source_item_raw_ttl_expired
        observations = []

        def observe(record, **kwargs):
            uri = Path(storage._engine.url.database).resolve().as_uri() + "?mode=rw"
            with sqlite3.connect(uri, uri=True, timeout=0) as competitor:
                try:
                    competitor.execute("BEGIN IMMEDIATE")
                except sqlite3.OperationalError as exc:
                    assert exc.sqlite_errorcode & 255 == sqlite3.SQLITE_BUSY
                    observations.append("busy")
                else:
                    observations.append("free")
                    competitor.rollback()
            return original(record, **kwargs)

        monkeypatch.setattr(storage, "_source_item_raw_ttl_expired", observe)
        stats = storage.run_retention_pass(now=now, batch_size=1, retention_policy=_TEST_RETENTION_POLICY)
        assert observations == ["free", "busy"]
        assert stats.deleted_source_items == 1
        with pytest.raises(KeyError):
            storage.get_source_item(source.id)
    finally:
        storage.close()


@pytest.mark.parametrize("change", ["durable", "working", "processing-lease", "ttl", "status", "deleted", "created-at"])
def test_source_retention_rechecks_changes_after_preparation(test_db_url, monkeypatch, change):
    from sqlalchemy import update
    from storage.sqlite_schema import SourceItemRecord
    from core.retention import RETENTION_MAINTENANCE_KEY

    storage = SQLiteStorageProvider(test_db_url)
    now = datetime(2026, 10, 12, tzinfo=UTC)
    try:
        source = _make_source(storage, source_id="changing", occurred_at=now - timedelta(days=90))
        later = _make_source(storage, source_id="later", occurred_at=now - timedelta(days=89)) if change == "created-at" else None
        original_retry = storage._with_retry
        original_candidates = storage._next_source_retention_candidates_in_session
        prepared = changed = False

        def candidates(*args, **kwargs):
            nonlocal prepared
            result = original_candidates(*args, **kwargs)
            prepared = True
            return result

        def write(fn):
            nonlocal changed
            if prepared and not changed:
                changed = True
                if change in {"durable", "working"}:
                    _make_memory(storage, memory_type="decision" if change == "durable" else "thread_summary",
                                 created_at=now, source_items=[source])
                elif change == "deleted":
                    original_retry(lambda session: storage._delete_source_item_cascade_in_session(session, source.id,
                        durable_types=_TEST_RETENTION_POLICY.durable_types, working_types=_TEST_RETENTION_POLICY.working_types,
                        orphan_delete_types=_TEST_RETENTION_POLICY.orphan_delete_types))
                else:
                    values = {
                        "processing-lease": {"processing_claimed_by": "active-worker", "processing_lease_expires_at": now + timedelta(minutes=1)},
                        "ttl": {"occurred_at": now},
                        "status": {"processing_status": "processing"},
                        "created-at": {"created_at": now + timedelta(days=1)},
                    }[change]
                    original_retry(lambda session: session.execute(update(SourceItemRecord).where(
                        SourceItemRecord.id == source.id).values(**values)))
            return original_retry(fn)

        monkeypatch.setattr(storage, "_next_source_retention_candidates_in_session", candidates)
        monkeypatch.setattr(storage, "_with_retry", write)
        stats = storage.run_retention_pass(now=now, batch_size=1, retention_policy=_TEST_RETENTION_POLICY)
        assert changed
        if change in {"deleted", "created-at"}:
            with pytest.raises(KeyError):
                storage.get_source_item(source.id)
            assert stats.deleted_source_items == (1 if change == "created-at" else 0)
        else:
            assert storage.get_source_item(source.id).content == source.content
            assert stats.deleted_source_items == 0
        if change in {"durable", "working"}:
            assert stats.skipped_protected_source_items == 1
        if later is not None:
            with storage._session_factory() as session:
                marker = session.get(MaintenanceStateRecord, RETENTION_MAINTENANCE_KEY)
                assert marker.source_scan_cursor_id == source.id
                assert storage._normalize_datetime(marker.source_scan_cursor_created_at) == source.created_at
            second = storage.run_retention_pass(now=now, batch_size=1, retention_policy=_TEST_RETENTION_POLICY)
            assert second.deleted_source_items == 1
            with pytest.raises(KeyError):
                storage.get_source_item(later.id)
    finally:
        storage.close()


@pytest.mark.parametrize("change", ["replaced", "expired"])
def test_source_retention_validates_expected_lease_after_preparation(test_db_url, monkeypatch, change):
    from core.retention import RETENTION_MAINTENANCE_KEY

    storage = SQLiteStorageProvider(test_db_url)
    now = datetime(2026, 10, 12, tzinfo=UTC)
    try:
        source = _make_source(storage, source_id="leased", occurred_at=now - timedelta(days=90))
        lease = storage.claim_retention_lease(worker_id="expected", lease_seconds=60, now=now)
        assert lease is not None
        original_retry, original_candidates = storage._with_retry, storage._next_source_retention_candidates_in_session
        prepared = changed = False

        def candidates(*args, **kwargs):
            nonlocal prepared
            result = original_candidates(*args, **kwargs)
            prepared = True
            return result

        def write(fn):
            nonlocal changed
            if prepared and not changed:
                changed = True
                def replace(session):
                    marker = session.get(MaintenanceStateRecord, RETENTION_MAINTENANCE_KEY)
                    if change == "replaced":
                        marker.claimed_by, marker.claimed_at = "replacement", now + timedelta(seconds=1)
                    else:
                        marker.lease_expires_at = now - timedelta(seconds=1)
                original_retry(replace)
            return original_retry(fn)

        monkeypatch.setattr(storage, "_next_source_retention_candidates_in_session", candidates)
        monkeypatch.setattr(storage, "_with_retry", write)
        with pytest.raises(RetentionLeaseLostError):
            storage.run_retention_pass(now=now, batch_size=1, lease=lease, lease_seconds=60,
                lease_now=now, retention_policy=_TEST_RETENTION_POLICY)
        assert changed and storage.get_source_item(source.id).content == source.content
        with storage._session_factory() as session:
            marker = session.get(MaintenanceStateRecord, RETENTION_MAINTENANCE_KEY)
            assert marker.source_scan_cursor_id is None and marker.source_scan_cursor_created_at is None
    finally:
        storage.close()


@pytest.mark.parametrize("change", ["advance", "create", "wrap", "exhaustion"])
def test_source_retention_reprepares_on_cursor_or_marker_conflict(test_db_url, monkeypatch, change):
    from core.retention import RETENTION_MAINTENANCE_KEY

    storage = SQLiteStorageProvider(test_db_url)
    now = datetime(2026, 10, 12, tzinfo=UTC)
    try:
        first = _make_source(storage, source_id="first", occurred_at=now - timedelta(days=90))
        second = _make_source(storage, source_id="second", occurred_at=now - timedelta(days=89))
        if change != "create":
            storage.claim_retention_lease(worker_id="marker", lease_seconds=60, now=now)
        original_retry, original_candidates = storage._with_retry, storage._next_source_retention_candidates_in_session
        if change == "wrap":
            def seed(session):
                marker = session.get(MaintenanceStateRecord, RETENTION_MAINTENANCE_KEY)
                marker.source_scan_cursor_created_at, marker.source_scan_cursor_id = second.created_at, second.id
            original_retry(seed)
        generations = mutations = 0

        def candidates(*args, **kwargs):
            nonlocal generations
            result = original_candidates(*args, **kwargs)
            generations += 1
            return result

        def write(fn):
            nonlocal mutations
            if generations > mutations and (mutations == 0 or change == "exhaustion"):
                mutations += 1
                def advance(session):
                    marker = storage._ensure_maintenance_state_record_in_session(session, RETENTION_MAINTENANCE_KEY, now)
                    if change == "exhaustion" and marker.source_scan_cursor_id == first.id:
                        storage._clear_source_scan_cursor_in_session(marker)
                    else:
                        marker.source_scan_cursor_created_at, marker.source_scan_cursor_id = first.created_at, first.id
                original_retry(advance)
            return original_retry(fn)

        monkeypatch.setattr(storage, "_next_source_retention_candidates_in_session", candidates)
        monkeypatch.setattr(storage, "_with_retry", write)
        if change == "exhaustion":
            with pytest.raises(RuntimeError, match="cursor changed repeatedly"):
                storage.run_retention_pass(now=now, batch_size=1, retention_policy=_TEST_RETENTION_POLICY)
            assert generations == mutations == storage._LOCKED_MAX_RETRIES
            assert storage.get_source_item(second.id).content == second.content
        else:
            stats = storage.run_retention_pass(now=now, batch_size=1, retention_policy=_TEST_RETENTION_POLICY)
            assert generations == 2 and mutations == 1
            assert stats.deleted_source_items == 1
            with pytest.raises(KeyError):
                storage.get_source_item(second.id)
        assert storage.get_source_item(first.id).content == first.content
    finally:
        storage.close()


def test_source_retention_rollback_restores_cursor_source_and_fts(test_db_url):
    from sqlalchemy import event
    from core.retention import RETENTION_MAINTENANCE_KEY

    storage = SQLiteStorageProvider(test_db_url)
    now = datetime(2026, 10, 12, tzinfo=UTC)
    flushed = []
    listener = None
    try:
        source = _make_source(storage, source_id="rollback", occurred_at=now - timedelta(days=90))
        storage.claim_retention_lease(worker_id="marker", lease_seconds=60, now=now)

        def before_commit(session):
            if session.bind is not storage._engine:
                return
            if any(isinstance(record, MaintenanceStateRecord)
                   and record.source_scan_cursor_id == source.id for record in session.identity_map.values()):
                session.flush()
                flushed.append(True)
                raise RuntimeError("controlled failure after cursor and deletion flush")

        listener = before_commit
        event.listen(storage._session_factory.class_, "before_commit", listener)
        with pytest.raises(RuntimeError, match="controlled failure"):
            storage.run_retention_pass(now=now, batch_size=1, retention_policy=_TEST_RETENTION_POLICY)
        assert flushed == [True]
        assert storage.get_source_item(source.id).content == source.content
        assert storage.find_index_entry(target_kind="source_item", target_id=source.id,
            index_type="lexical", text_view_name="source_item.content") is not None
        assert source.id in {hit.target_id for hit in storage.search_index_entries(["rollback"], limit=10).hits}
        with storage._session_factory() as session:
            marker = session.get(MaintenanceStateRecord, RETENTION_MAINTENANCE_KEY)
            assert marker.source_scan_cursor_id is None and marker.source_scan_cursor_created_at is None
    finally:
        if listener is not None:
            event.remove(storage._session_factory.class_, "before_commit", listener)
        storage.close()


@pytest.mark.parametrize("exhausted", [False, True])
def test_source_retention_retries_transient_preparation_without_writes(test_db_url, monkeypatch, exhausted):
    import sqlite3
    from sqlalchemy import event
    from core.retention import RETENTION_MAINTENANCE_KEY

    storage = SQLiteStorageProvider(test_db_url)
    now = datetime(2026, 10, 12, tzinfo=UTC)
    statements, failures = [], []
    listener = None
    try:
        source = _make_source(storage, source_id="retry", occurred_at=now - timedelta(days=90))
        original = storage._source_item_is_protected
        original_candidates = storage._next_source_retention_candidates_in_session

        def preparation(*args, **kwargs):
            statements.clear()
            return original_candidates(*args, **kwargs)

        def fail_once(session, source_id, **kwargs):
            if exhausted or not failures:
                assert not any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql in statements)
                failures.append(True)
                raise sqlite3.OperationalError("database is locked")
            return original(session, source_id, **kwargs)

        def observe(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        listener = observe
        event.listen(storage._engine, "before_cursor_execute", listener)
        monkeypatch.setattr(storage, "_next_source_retention_candidates_in_session", preparation)
        monkeypatch.setattr(storage, "_source_item_is_protected", fail_once)
        if exhausted:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                storage.run_retention_pass(now=now, batch_size=1, retention_policy=_TEST_RETENTION_POLICY)
            assert len(failures) == storage._LOCKED_MAX_RETRIES
            assert storage.get_source_item(source.id).content == source.content
            with storage._session_factory() as session:
                assert session.get(MaintenanceStateRecord, RETENTION_MAINTENANCE_KEY) is None
        else:
            stats = storage.run_retention_pass(now=now, batch_size=1, retention_policy=_TEST_RETENTION_POLICY)
            assert failures == [True] and stats.deleted_source_items == 1
            with pytest.raises(KeyError):
                storage.get_source_item(source.id)
    finally:
        if listener is not None:
            event.remove(storage._engine, "before_cursor_execute", listener)
        storage.close()
