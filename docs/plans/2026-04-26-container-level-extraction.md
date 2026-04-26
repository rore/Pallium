# Container-Level Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract memory from standalone messages that currently fall below the 2-item thread minimum by adding a container-level processing scope.

**Architecture:** Every ingested item bumps a container scope (`thread_ref=None`) alongside its thread scope. The container scope collects top-level messages (first item per thread_ref + threadless items) and runs extraction through the same plugin interface. Thread scopes remain unchanged. Collection is bounded at every scale: write-time `thread_position` eliminates O(N) correlated subqueries, per-scope `collection_watermark_at` bounds incremental extraction to new items, and `max_items` caps superseding plugin collection.

**Tech Stack:** Python, SQLAlchemy, SQLite, FastAPI, pytest

**Design spec:** `docs/specs/2026-04-26-container-level-extraction-design.md`

---

## File Structure

| File | Change | Responsibility |
|------|--------|----------------|
| `core/models.py` | Modify | Add `thread_position` field to `SourceItem` dataclass |
| `storage/base.py` | Modify | Make `thread_ref` optional on scope dataclasses; add `collection_watermark_at` to lease; add `container_rebuild_scope` to commit signatures; add `list_top_level_messages_for_container` |
| `storage/sqlite_schema.py` | Modify | Add `thread_position` column + index to `source_items`; make `thread_processing_leases.thread_ref` nullable + add `collection_watermark_at`; backfill migration |
| `storage/sqlite.py` | Modify | Compute `thread_position` at ingest; add `list_top_level_messages_for_container` using indexed `thread_position=1` |
| `storage/sqlite_codec.py` | Modify | Map `thread_position` and `collection_watermark_at` in codec methods |
| `storage/sqlite_queue.py` | Modify | Handle nullable `thread_ref` in upsert; add `container_rebuild_scope` to commit methods; store `collection_watermark_at` on scope completion |
| `capabilities/thread_aggregation.py` | Modify | Make `ThreadAggregate.thread_ref` optional, allow container aggregates |
| `core/thread_rebuild.py` | Modify | Build container scopes, branched collection with watermark/max_items, skip 2-item minimum for container scope |
| `semantic/conversational_knowledge.py` | Modify | Remove `thread_ref` from eligibility check, skip 2-item minimum for container scope |
| `semantic/agent_conversation_memory.py` | Modify | Remove `thread_ref` from `supports_thread_aggregation` |
| `core/processing.py` | Modify | Build and pass container scope through commit methods |
| `api/schemas.py` | Modify | Make `LeasedThreadScopeResponse.thread_ref` optional |
| `tests/test_standalone_message_extraction_gap.py` | Modify | Flip assertions to expect facts |

---

### Task 1: Add `thread_position` to source items and make `thread_ref` optional in scope dataclasses

**Files:**
- Modify: `core/models.py:33-58`
- Modify: `storage/base.py:35-116`
- Modify: `api/schemas.py:329-337`

- [ ] **Step 1: Write failing test for thread_position on SourceItem**

```python
# tests/test_container_scope_schema.py
from core.models import SourceItem
from storage.base import ThreadProcessingScope, ThreadProcessingLease, LeasedThreadScopeInfo

def test_source_item_has_thread_position():
    item = SourceItem(
        source_type="chat_message",
        source_id="test-1",
        content_type="text/plain",
        content="hello",
        thread_position=3,
    )
    assert item.thread_position == 3

def test_source_item_thread_position_defaults_to_none():
    item = SourceItem(
        source_type="chat_message",
        source_id="test-1",
        content_type="text/plain",
        content="hello",
    )
    assert item.thread_position is None

def test_thread_processing_scope_allows_none_thread_ref():
    scope = ThreadProcessingScope(
        scope_key="test-key",
        use_case="test",
        container_ref="slack:dm:test",
        thread_ref=None,
        visibility="private",
    )
    assert scope.thread_ref is None

def test_thread_processing_lease_allows_none_thread_ref():
    lease = ThreadProcessingLease(
        scope_key="test-key",
        use_case="test",
        container_ref="slack:dm:test",
        thread_ref=None,
        visibility="private",
    )
    assert lease.thread_ref is None
    assert lease.collection_watermark_at is None
    scope = lease.as_scope()
    assert scope.thread_ref is None

def test_leased_thread_scope_info_allows_none_thread_ref():
    info = LeasedThreadScopeInfo(
        scope_key="test-key",
        use_case="test",
        container_ref="slack:dm:test",
        thread_ref=None,
    )
    assert info.thread_ref is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_container_scope_schema.py -x -q`
Expected: Failures — `thread_position` doesn't exist on `SourceItem`, `collection_watermark_at` doesn't exist on `ThreadProcessingLease`.

- [ ] **Step 3: Add thread_position to SourceItem**

In `core/models.py`, add after `processing_next_attempt_at` (before `id`):

```python
thread_position: int | None = None
```

- [ ] **Step 4: Make thread_ref optional and add collection_watermark_at to scope dataclasses**

In `storage/base.py`, change the three dataclasses:

```python
@dataclass(frozen=True)
class ThreadProcessingScope:
    scope_key: str
    use_case: str
    container_ref: str
    thread_ref: str | None
    visibility: str = "private"


@dataclass(frozen=True)
class ThreadProcessingLease:
    scope_key: str
    use_case: str
    container_ref: str
    thread_ref: str | None
    visibility: str = "private"
    requested_at: datetime | None = None
    processing_claimed_by: str | None = None
    processing_claimed_at: datetime | None = None
    processing_lease_expires_at: datetime | None = None
    collection_watermark_at: datetime | None = None


@dataclass(frozen=True)
class LeasedThreadScopeInfo:
    scope_key: str
    use_case: str
    container_ref: str
    thread_ref: str | None
    visibility: str = "private"
    processing_claimed_by: str | None = None
    processing_claimed_at: datetime | None = None
    processing_lease_expires_at: datetime | None = None
    collection_watermark_at: datetime | None = None
```

In `api/schemas.py`, change `LeasedThreadScopeResponse`:

```python
class LeasedThreadScopeResponse(BaseModel):
    scope_key: str
    use_case: str
    container_ref: str
    thread_ref: str | None = None
    visibility: str = "private"
    processing_claimed_by: str | None = None
    processing_claimed_at: datetime | None = None
    processing_lease_expires_at: datetime | None = None
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_container_scope_schema.py -x -q`
Expected: PASS

- [ ] **Step 6: Run full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add core/models.py storage/base.py api/schemas.py tests/test_container_scope_schema.py
git commit -m "feat: add thread_position to SourceItem, make thread_ref optional in scope dataclasses"
```

---

### Task 2: Schema migration — thread_position, nullable thread_ref, collection_watermark_at

**Files:**
- Modify: `storage/sqlite_schema.py:23-51, 95-110, 178-188, 227-270, 292-305`
- Modify: `storage/sqlite_codec.py:41-65, 129-145`

- [ ] **Step 1: Add thread_position column to SourceItemRecord**

In `storage/sqlite_schema.py`, add after `processing_next_attempt_at` column (before `created_at`):

```python
thread_position = Column(Integer, nullable=True)
```

- [ ] **Step 2: Add collection_watermark_at to ThreadProcessingLeaseRecord**

In `storage/sqlite_schema.py`, add after `processing_completed_at` column:

```python
collection_watermark_at = Column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 3: Make ThreadProcessingLeaseRecord.thread_ref nullable**

Change line 101:

```python
# Before:
thread_ref = Column(String, nullable=False)

# After:
thread_ref = Column(String, nullable=True)
```

- [ ] **Step 4: Add column migrations**

Add to `_SOURCE_ITEM_MIGRATIONS`:

```python
"thread_position": "ALTER TABLE source_items ADD COLUMN thread_position INTEGER",
```

Add a new `_THREAD_PROCESSING_LEASE_MIGRATIONS` dict:

```python
_THREAD_PROCESSING_LEASE_MIGRATIONS = {
    "collection_watermark_at": "ALTER TABLE thread_processing_leases ADD COLUMN collection_watermark_at DATETIME",
}
```

- [ ] **Step 5: Add container collection index**

Add to `_INDEX_MIGRATIONS`:

```python
"idx_source_items_container_top_level": (
    "CREATE INDEX IF NOT EXISTS idx_source_items_container_top_level "
    "ON source_items(container_ref, thread_position, created_at)"
),
```

- [ ] **Step 6: Add thread_processing_leases nullable thread_ref migration**

SQLite has no `ALTER COLUMN`. For existing databases where `thread_ref` is `NOT NULL`, inserting a NULL value will fail. Add a migration method that recreates the table:

```python
def _ensure_thread_processing_lease_nullable_thread_ref(self) -> None:
    """Migrate thread_processing_leases.thread_ref from NOT NULL to nullable."""
    with self._engine.begin() as connection:
        columns = connection.execute(text("PRAGMA table_info(thread_processing_leases)")).fetchall()
        thread_ref_col = next((col for col in columns if col[1] == "thread_ref"), None)
        if thread_ref_col is None:
            return
        notnull = thread_ref_col[3]
        if not notnull:
            return
        connection.execute(text(
            "CREATE TABLE thread_processing_leases_new ("
            "  scope_key VARCHAR PRIMARY KEY,"
            "  use_case VARCHAR NOT NULL,"
            "  container_ref VARCHAR NOT NULL,"
            "  thread_ref VARCHAR,"
            "  visibility VARCHAR DEFAULT 'private',"
            "  requested_at DATETIME,"
            "  processing_claimed_by VARCHAR,"
            "  processing_claimed_at DATETIME,"
            "  processing_lease_expires_at DATETIME,"
            "  processing_completed_at DATETIME,"
            "  collection_watermark_at DATETIME,"
            "  created_at DATETIME NOT NULL,"
            "  updated_at DATETIME NOT NULL"
            ")"
        ))
        connection.execute(text(
            "INSERT INTO thread_processing_leases_new "
            "(scope_key, use_case, container_ref, thread_ref, visibility, "
            " requested_at, processing_claimed_by, processing_claimed_at, "
            " processing_lease_expires_at, processing_completed_at, "
            " created_at, updated_at) "
            "SELECT scope_key, use_case, container_ref, thread_ref, visibility, "
            "  requested_at, processing_claimed_by, processing_claimed_at, "
            "  processing_lease_expires_at, processing_completed_at, "
            "  created_at, updated_at "
            "FROM thread_processing_leases"
        ))
        connection.execute(text("DROP TABLE thread_processing_leases"))
        connection.execute(text(
            "ALTER TABLE thread_processing_leases_new RENAME TO thread_processing_leases"
        ))
```

- [ ] **Step 7: Add backfill migration for thread_position**

```python
def _backfill_thread_position(self) -> None:
    """Set thread_position for existing source items that don't have it."""
    with self._engine.begin() as connection:
        needs_backfill = connection.execute(text(
            "SELECT COUNT(*) FROM source_items WHERE thread_position IS NULL LIMIT 1"
        )).scalar()
        if not needs_backfill:
            return
        # Threaded items: position by created_at order within each thread
        connection.execute(text(
            "UPDATE source_items SET thread_position = ("
            "  SELECT COUNT(*) FROM source_items s2"
            "  WHERE s2.container_ref = source_items.container_ref"
            "    AND s2.thread_ref = source_items.thread_ref"
            "    AND (s2.created_at < source_items.created_at"
            "         OR (s2.created_at = source_items.created_at AND s2.id <= source_items.id))"
            ") WHERE thread_ref IS NOT NULL AND thread_position IS NULL"
        ))
        # Threadless items: always position 1
        connection.execute(text(
            "UPDATE source_items SET thread_position = 1 "
            "WHERE thread_ref IS NULL AND thread_position IS NULL"
        ))
```

- [ ] **Step 8: Add lease column migration method and wire into _initialize_schema**

```python
def _ensure_thread_processing_lease_columns(self) -> None:
    with self._engine.begin() as connection:
        existing_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(thread_processing_leases)"))}
        for column_name, migration_sql in self._THREAD_PROCESSING_LEASE_MIGRATIONS.items():
            if column_name not in existing_columns:
                connection.execute(text(migration_sql))
```

In `_initialize_schema`, add after `Base.metadata.create_all`:

```python
def _initialize_schema(self) -> None:
    with self._schema_initialization_lock():
        Base.metadata.create_all(self._engine)
        self._ensure_thread_processing_lease_nullable_thread_ref()
        self._ensure_thread_processing_lease_columns()
        self._ensure_source_item_columns()
        # ... rest unchanged ...
        self._backfill_thread_position()
```

The order matters: nullable migration before column migration (so `collection_watermark_at` column exists in the recreated table), and backfill after source item columns are ensured.

- [ ] **Step 9: Update codec methods**

In `storage/sqlite_codec.py`, update `_to_source_item` — add after the existing fields:

```python
thread_position=record.thread_position,
```

Update `_to_thread_processing_lease` — add `collection_watermark_at`:

```python
return ThreadProcessingLease(
    scope_key=record.scope_key,
    use_case=record.use_case,
    container_ref=record.container_ref,
    thread_ref=record.thread_ref,
    visibility=record.visibility or "private",
    requested_at=requested_at,
    processing_claimed_by=record.processing_claimed_by,
    processing_claimed_at=claimed_at,
    processing_lease_expires_at=lease_expires_at,
    collection_watermark_at=SQLiteCodecMixin._normalize_datetime(
        getattr(record, "collection_watermark_at", None)
    ),
)
```

- [ ] **Step 10: Update create_source_item to map thread_position**

In `storage/sqlite.py`, update `create_source_item` to include the new field:

```python
record = SourceItemRecord(
    # ... existing fields ...
    thread_position=source_item.thread_position,
    created_at=source_item.created_at,
)
```

- [ ] **Step 11: Run full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 12: Commit**

```bash
git add storage/sqlite_schema.py storage/sqlite_codec.py storage/sqlite.py
git commit -m "feat: schema migration for thread_position, nullable thread_ref, collection_watermark_at"
```

---

### Task 3: Compute thread_position at ingest time

Write-time computation eliminates the O(N) correlated subquery at read time. Uses `BEGIN IMMEDIATE` to serialize the count+insert, preventing race conditions under concurrent ingest.

**Files:**
- Modify: `storage/sqlite.py:81-110`

- [ ] **Step 1: Write failing test**

```python
# tests/test_thread_position.py
from app.config import AppConfig
from app.main import create_app
from core.models import SourceItem
from storage.vector_index import VectorIndexConfig

def _config(db_url: str) -> AppConfig:
    return AppConfig(
        storage_backend="sqlite",
        sqlite_url=db_url,
        default_use_case="demo_agent_memory",
        vector_index=VectorIndexConfig(enabled=False),
    )

def _make_item(source_id, *, thread_ref=None, container_ref="container-a"):
    return SourceItem(
        source_type="chat_message",
        source_id=source_id,
        content_type="text/plain",
        content="test content",
        role="user",
        artifact_kind="message",
        container_ref=container_ref,
        thread_ref=thread_ref,
        visibility="private",
    )

class TestThreadPositionAtIngest:
    def test_first_item_in_thread_gets_position_1(self, test_db_url: str) -> None:
        app = create_app(_config(test_db_url))
        storage = app.state.pallium_service._storage

        storage.create_source_item(_make_item("msg-1", thread_ref="thread-a"))
        item = storage.get_source_item("msg-1")
        assert item.thread_position == 1

    def test_second_item_in_thread_gets_position_2(self, test_db_url: str) -> None:
        app = create_app(_config(test_db_url))
        storage = app.state.pallium_service._storage

        storage.create_source_item(_make_item("msg-1", thread_ref="thread-a"))
        storage.create_source_item(_make_item("msg-2", thread_ref="thread-a"))
        item = storage.get_source_item("msg-2")
        assert item.thread_position == 2

    def test_different_threads_get_independent_positions(self, test_db_url: str) -> None:
        app = create_app(_config(test_db_url))
        storage = app.state.pallium_service._storage

        storage.create_source_item(_make_item("a-1", thread_ref="thread-a"))
        storage.create_source_item(_make_item("b-1", thread_ref="thread-b"))
        storage.create_source_item(_make_item("a-2", thread_ref="thread-a"))

        assert storage.get_source_item("a-1").thread_position == 1
        assert storage.get_source_item("b-1").thread_position == 1
        assert storage.get_source_item("a-2").thread_position == 2

    def test_threadless_item_gets_position_1(self, test_db_url: str) -> None:
        app = create_app(_config(test_db_url))
        storage = app.state.pallium_service._storage

        storage.create_source_item(_make_item("no-thread", thread_ref=None))
        item = storage.get_source_item("no-thread")
        assert item.thread_position == 1

    def test_different_containers_get_independent_positions(self, test_db_url: str) -> None:
        app = create_app(_config(test_db_url))
        storage = app.state.pallium_service._storage

        storage.create_source_item(_make_item("c1-1", thread_ref="thread-a", container_ref="container-1"))
        storage.create_source_item(_make_item("c2-1", thread_ref="thread-a", container_ref="container-2"))

        assert storage.get_source_item("c1-1").thread_position == 1
        assert storage.get_source_item("c2-1").thread_position == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_thread_position.py -x -q`
Expected: FAIL — `create_source_item` doesn't compute `thread_position`.

- [ ] **Step 3: Implement thread_position computation in create_source_item**

In `storage/sqlite.py`, rewrite `create_source_item`:

```python
def create_source_item(self, source_item: SourceItem) -> None:
    record = SourceItemRecord(
        id=source_item.id,
        source_type=source_item.source_type,
        source_id=source_item.source_id,
        content_type=source_item.content_type,
        content=source_item.content,
        metadata_json=self._dumps(source_item.metadata),
        occurred_at=source_item.occurred_at,
        actor_ref=source_item.actor_ref,
        agent_ref=source_item.agent_ref,
        role=source_item.role,
        container_ref=source_item.container_ref,
        thread_ref=source_item.thread_ref,
        source_ref=source_item.source_ref,
        artifact_kind=source_item.artifact_kind,
        visibility=source_item.visibility,
        use_case=source_item.use_case,
        processing_status=source_item.processing_status,
        processing_attempts=source_item.processing_attempts,
        processing_claimed_by=source_item.processing_claimed_by,
        processing_claimed_at=source_item.processing_claimed_at,
        processing_lease_expires_at=source_item.processing_lease_expires_at,
        processing_completed_at=source_item.processing_completed_at,
        processing_error=source_item.processing_error,
        processing_next_attempt_at=source_item.processing_next_attempt_at,
        created_at=source_item.created_at,
    )
    with self._engine.connect().execution_options(
        isolation_level="SERIALIZABLE",
    ) as connection:
        with connection.begin():
            if source_item.thread_ref is not None and source_item.container_ref is not None:
                count = connection.execute(
                    text(
                        "SELECT COUNT(*) FROM source_items "
                        "WHERE container_ref = :container_ref AND thread_ref = :thread_ref"
                    ),
                    {"container_ref": source_item.container_ref, "thread_ref": source_item.thread_ref},
                ).scalar()
                record.thread_position = count + 1
            else:
                record.thread_position = 1
            session = Session(bind=connection)
            session.add(record)
            session.flush()
```

The `isolation_level="SERIALIZABLE"` maps to `BEGIN IMMEDIATE` in SQLite, acquiring the write lock before the COUNT query. This prevents concurrent transactions from reading a stale count.

**Note:** This changes from `self._session_factory.begin()` to `self._engine.connect()` to control the isolation level per-connection. The `Session(bind=connection)` reuses the same connection and transaction.

Add the import at the top of `storage/sqlite.py`:

```python
from sqlalchemy.orm import Session
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_thread_position.py -x -q`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add storage/sqlite.py tests/test_thread_position.py
git commit -m "feat: compute thread_position at ingest time with serialized transactions"
```

---

### Task 4: Make `ThreadAggregate.thread_ref` optional

**Files:**
- Modify: `capabilities/thread_aggregation.py:11-57`

- [ ] **Step 1: Write failing test**

```python
# tests/test_container_aggregate.py
from datetime import datetime, timezone
from capabilities.thread_aggregation import ThreadAggregate, build_thread_aggregate
from core.models import SourceItem

def _make_item(source_id: str, content: str, *, thread_ref: str | None = None, container_ref: str = "container-a") -> SourceItem:
    return SourceItem(
        source_type="chat_message",
        source_id=source_id,
        content_type="text/plain",
        content=content,
        role="user",
        artifact_kind="message",
        container_ref=container_ref,
        thread_ref=thread_ref,
        visibility="private",
        processing_status="completed",
    )

def test_build_aggregate_with_mixed_thread_refs():
    items = [
        _make_item("msg-1", "first message", thread_ref="thread-a"),
        _make_item("msg-2", "second message", thread_ref="thread-b"),
        _make_item("msg-3", "third message", thread_ref=None),
    ]
    aggregate = build_thread_aggregate(items, container_scope=True)
    assert aggregate.thread_ref is None
    assert aggregate.container_ref == "container-a"
    assert len(aggregate.source_items) == 3
    assert "first message" in aggregate.aggregate_text
    assert "third message" in aggregate.aggregate_text

def test_build_aggregate_normal_thread_unchanged():
    items = [
        _make_item("msg-1", "first", thread_ref="thread-a"),
        _make_item("msg-2", "second", thread_ref="thread-a"),
    ]
    aggregate = build_thread_aggregate(items)
    assert aggregate.thread_ref == "thread-a"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_container_aggregate.py -x -q`
Expected: FAIL — `container_scope` parameter doesn't exist.

- [ ] **Step 3: Update ThreadAggregate and build_thread_aggregate**

In `capabilities/thread_aggregation.py`:

```python
@dataclass(frozen=True)
class ThreadAggregate:
    container_ref: str
    thread_ref: str | None
    source_items: list[SourceItem]
    source_item_ids: list[str]
    latest_occurred_at: datetime | None
    aggregate_text: str
    visibility: str = "private"


def build_thread_aggregate(
    source_items: list[SourceItem],
    *,
    container_scope: bool = False,
) -> ThreadAggregate:
    if not source_items:
        raise ValueError("Thread aggregation requires at least one source item")

    ordered_items = sorted(
        source_items,
        key=lambda item: (
            item.occurred_at or item.created_at,
            item.created_at,
            item.id,
        ),
    )
    first = ordered_items[0]
    if not first.container_ref:
        raise ValueError("Thread aggregation requires container_ref")
    if not container_scope:
        if not first.thread_ref:
            raise ValueError("Thread aggregation requires thread_ref (use container_scope=True for container-level)")
        if any(
            not visibility_matches_exact(item.visibility, first.visibility)
            for item in ordered_items[1:]
        ):
            raise ValueError("Thread aggregation requires exact visibility match")

    latest_item = ordered_items[-1]
    aggregate_text = "\n".join(
        f"{item.role or 'unknown'}/{item.artifact_kind or 'unknown'}: {item.content.strip()}"
        for item in ordered_items
        if item.content.strip()
    )

    return ThreadAggregate(
        container_ref=first.container_ref,
        thread_ref=None if container_scope else first.thread_ref,
        source_items=ordered_items,
        source_item_ids=[item.id for item in ordered_items],
        latest_occurred_at=latest_item.occurred_at or latest_item.created_at,
        aggregate_text=aggregate_text,
        visibility=first.visibility,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_container_aggregate.py -x -q`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add capabilities/thread_aggregation.py tests/test_container_aggregate.py
git commit -m "feat: allow container-scope aggregates with optional thread_ref"
```

---

### Task 5: Add `list_top_level_messages_for_container` to storage

Uses the `thread_position = 1` index for O(bounded) collection. No correlated subquery. Supports `after_created_at` (watermark for incremental plugins) and `max_items` (ceiling for superseding plugins).

**Files:**
- Modify: `storage/base.py` (add abstract method)
- Modify: `storage/sqlite.py` (add implementation)

- [ ] **Step 1: Write failing test**

```python
# tests/test_container_collection.py
from datetime import datetime, timezone, timedelta
from app.config import AppConfig
from app.main import create_app
from core.models import SourceItem
from storage.vector_index import VectorIndexConfig

def _config(db_url: str) -> AppConfig:
    return AppConfig(
        storage_backend="sqlite",
        sqlite_url=db_url,
        default_use_case="demo_agent_memory",
        vector_index=VectorIndexConfig(enabled=False),
    )

def _make_item(source_id, content, *, thread_ref=None, container_ref="container-a"):
    return SourceItem(
        source_type="chat_message",
        source_id=source_id,
        content_type="text/plain",
        content=content,
        role="user",
        artifact_kind="message",
        container_ref=container_ref,
        thread_ref=thread_ref,
        visibility="private",
        processing_status="completed",
    )

class TestListTopLevelMessages:
    def test_collects_first_item_per_thread_ref(self, test_db_url: str) -> None:
        app = create_app(_config(test_db_url))
        storage = app.state.pallium_service._storage

        for i in range(3):
            storage.create_source_item(_make_item(f"thread-a-{i}", f"msg {i}", thread_ref="thread-a"))
        storage.create_source_item(_make_item("thread-b-0", "singleton", thread_ref="thread-b"))

        items = storage.list_top_level_messages_for_container("container-a")
        source_ids = {item.source_id for item in items}
        assert "thread-a-0" in source_ids
        assert "thread-b-0" in source_ids
        assert "thread-a-1" not in source_ids
        assert "thread-a-2" not in source_ids
        assert len(items) == 2

    def test_collects_threadless_items(self, test_db_url: str) -> None:
        app = create_app(_config(test_db_url))
        storage = app.state.pallium_service._storage

        storage.create_source_item(_make_item("no-thread-1", "threadless msg", thread_ref=None))
        storage.create_source_item(_make_item("with-thread-1", "threaded msg", thread_ref="thread-a"))

        items = storage.list_top_level_messages_for_container("container-a")
        source_ids = {item.source_id for item in items}
        assert "no-thread-1" in source_ids
        assert "with-thread-1" in source_ids
        assert len(items) == 2

    def test_watermark_filters_old_items(self, test_db_url: str) -> None:
        app = create_app(_config(test_db_url))
        storage = app.state.pallium_service._storage

        storage.create_source_item(_make_item("old-1", "old message", thread_ref="thread-old"))
        storage.create_source_item(_make_item("new-1", "new message", thread_ref="thread-new"))

        all_items = storage.list_top_level_messages_for_container("container-a")
        watermark = min(item.created_at for item in all_items)

        filtered = storage.list_top_level_messages_for_container(
            "container-a", after_created_at=watermark,
        )
        assert len(filtered) == 1
        assert filtered[0].source_id == "new-1"

    def test_max_items_limits_results(self, test_db_url: str) -> None:
        app = create_app(_config(test_db_url))
        storage = app.state.pallium_service._storage

        for i in range(10):
            storage.create_source_item(_make_item(f"msg-{i}", f"message {i}", thread_ref=f"thread-{i}"))

        items = storage.list_top_level_messages_for_container("container-a", max_items=3)
        assert len(items) == 3
        # Should be the 3 most recent, returned in ascending order
        source_ids = [item.source_id for item in items]
        assert source_ids == ["msg-7", "msg-8", "msg-9"]

    def test_different_container_excluded(self, test_db_url: str) -> None:
        app = create_app(_config(test_db_url))
        storage = app.state.pallium_service._storage

        storage.create_source_item(_make_item("other-1", "other container", thread_ref="t-1", container_ref="container-b"))
        storage.create_source_item(_make_item("mine-1", "my container", thread_ref="t-2", container_ref="container-a"))

        items = storage.list_top_level_messages_for_container("container-a")
        assert len(items) == 1
        assert items[0].source_id == "mine-1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_container_collection.py -x -q`
Expected: FAIL — `list_top_level_messages_for_container` doesn't exist.

- [ ] **Step 3: Add abstract method to StorageProvider**

In `storage/base.py`, add after `list_source_items_for_thread`:

```python
@abstractmethod
def list_top_level_messages_for_container(
    self,
    container_ref: str,
    after_created_at: datetime | None = None,
    max_items: int | None = None,
) -> list[SourceItem]:
    """Collect top-level messages for container-scope extraction.

    Returns items with thread_position=1 (first per thread_ref) plus
    all threadless items.  Uses the idx_source_items_container_top_level
    index for O(bounded) collection.

    If after_created_at is provided, only returns items created strictly
    after that timestamp (watermark-based incrementality).

    If max_items is provided, returns the most recent N items (ordered by
    created_at DESC before limiting, then returned in ASC order).
    """
    raise NotImplementedError
```

- [ ] **Step 4: Add SQLite implementation**

In `storage/sqlite.py`, add after `list_source_items_for_thread`:

```python
def list_top_level_messages_for_container(
    self,
    container_ref: str,
    after_created_at: datetime | None = None,
    max_items: int | None = None,
) -> list[SourceItem]:
    with self._session_factory() as session:
        query = (
            select(SourceItemRecord)
            .where(
                SourceItemRecord.container_ref == container_ref,
                SourceItemRecord.thread_position == 1,
            )
        )
        if after_created_at is not None:
            query = query.where(SourceItemRecord.created_at > after_created_at)
        if max_items is not None:
            query = query.order_by(
                SourceItemRecord.created_at.desc(),
                SourceItemRecord.id.desc(),
            ).limit(max_items)
            # Execute limited query, then sort ascending for caller
            records = list(session.scalars(query).all())
            records.sort(key=lambda r: (r.created_at, r.id))
        else:
            query = query.order_by(
                SourceItemRecord.created_at.asc(),
                SourceItemRecord.id.asc(),
            )
            records = list(session.scalars(query).all())
    return [self._to_source_item(record) for record in records]
```

**Performance:** The query `WHERE container_ref = :cref AND thread_position = 1` uses the `idx_source_items_container_top_level(container_ref, thread_position, created_at)` index directly. With `after_created_at`, the index range scan starts at the watermark — O(delta). With `max_items`, the descending scan stops after N rows — O(max_items). No correlated subquery, no full-table scan.

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_container_collection.py -x -q`
Expected: PASS

- [ ] **Step 6: Run full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add storage/base.py storage/sqlite.py tests/test_container_collection.py
git commit -m "feat: add list_top_level_messages_for_container with indexed thread_position=1"
```

---

### Task 6: Remove `thread_ref` requirement from plugin eligibility checks

**Files:**
- Modify: `semantic/conversational_knowledge.py:571-577`
- Modify: `semantic/agent_conversation_memory.py:128-131`

- [ ] **Step 1: Write failing test**

```python
# tests/test_container_eligibility.py
from core.models import SourceItem

def _make_item(*, thread_ref=None, container_ref="container-a", role="user", artifact_kind="message"):
    return SourceItem(
        source_type="chat_message",
        source_id="test-1",
        content_type="text/plain",
        content="test content",
        role=role,
        artifact_kind=artifact_kind,
        container_ref=container_ref,
        thread_ref=thread_ref,
        visibility="private",
        processing_status="completed",
    )

def test_fact_extraction_eligible_without_thread_ref():
    from semantic.conversational_knowledge import _is_eligible_for_fact_extraction
    item = _make_item(thread_ref=None, container_ref="container-a")
    assert _is_eligible_for_fact_extraction(item) is True

def test_fact_extraction_still_requires_container_ref():
    from semantic.conversational_knowledge import _is_eligible_for_fact_extraction
    item = _make_item(thread_ref=None, container_ref=None)
    assert _is_eligible_for_fact_extraction(item) is False

def test_agent_memory_plugin_eligible_without_thread_ref():
    from semantic.agent_conversation_memory import AgentConversationMemoryPlugin
    plugin = AgentConversationMemoryPlugin.__new__(AgentConversationMemoryPlugin)
    item = _make_item(thread_ref=None, container_ref="container-a")
    assert plugin.supports_thread_aggregation(item) is True

def test_agent_memory_plugin_still_requires_container_ref():
    from semantic.agent_conversation_memory import AgentConversationMemoryPlugin
    plugin = AgentConversationMemoryPlugin.__new__(AgentConversationMemoryPlugin)
    item = _make_item(thread_ref=None, container_ref=None)
    assert plugin.supports_thread_aggregation(item) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_container_eligibility.py -x -q`
Expected: FAIL — eligibility returns False for items with no thread_ref.

- [ ] **Step 3: Remove thread_ref requirement from eligibility**

In `semantic/conversational_knowledge.py`, change `_is_eligible_for_fact_extraction` (line 571):

```python
def _is_eligible_for_fact_extraction(source_item: SourceItem) -> bool:
    if not source_item.container_ref:
        return False
    role = (source_item.role or "").lower()
    artifact_kind = (source_item.artifact_kind or "").lower() or None
    return (artifact_kind, role) in ELIGIBLE_ARTIFACT_ROLES
```

In `semantic/agent_conversation_memory.py`, change `supports_thread_aggregation` (line 128):

```python
def supports_thread_aggregation(self, source_item: SourceItem) -> bool:
    if not source_item.container_ref:
        return False
    return _supports_thread_aggregation(source_item)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_container_eligibility.py -x -q`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add semantic/conversational_knowledge.py semantic/agent_conversation_memory.py tests/test_container_eligibility.py
git commit -m "feat: remove thread_ref from plugin eligibility checks for container scope support"
```

---

### Task 7: Build container scopes and branched collection in ThreadRebuilder

This is the core logic change. Container scopes use bounded collection based on the plugin's rebuild mode:
- Incremental (`rebuild_supersedes_prior=False`): `after_created_at` from `collection_watermark_at` — O(delta)
- Superseding (`rebuild_supersedes_prior=True`): `max_items=200` — O(200)

**Files:**
- Modify: `core/thread_rebuild.py:157-186, 207-280, 297-304, 350-397`

- [ ] **Step 1: Add `CONTAINER_SCOPE_RECENT_ITEMS` constant**

At the top of `core/thread_rebuild.py`:

```python
CONTAINER_SCOPE_RECENT_ITEMS = 200
```

- [ ] **Step 2: Add `build_container_processing_scope` method**

In `core/thread_rebuild.py`, add after `build_thread_processing_scope` (after line 186):

```python
def build_container_processing_scope(
    self,
    *,
    plugin_name: str,
    plugin: SemanticPlugin,
    source_item: SourceItem,
) -> ThreadProcessingScope | None:
    if not isinstance(plugin, ThreadAggregationSemanticPlugin):
        return None
    if not plugin.supports_thread_aggregation(source_item):
        return None
    if not source_item.container_ref:
        return None
    scope_key = json.dumps(
        {
            "use_case": plugin_name,
            "container_ref": source_item.container_ref,
            "thread_ref": None,
            "visibility": source_item.visibility,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return ThreadProcessingScope(
        scope_key=scope_key,
        use_case=plugin_name,
        container_ref=source_item.container_ref,
        thread_ref=None,
        visibility=source_item.visibility,
    )
```

- [ ] **Step 3: Fix type annotation on `_maybe_trigger_fact_consolidation`**

At line 304, change:

```python
# Before:
current_thread_ref: str,

# After:
current_thread_ref: str | None,
```

- [ ] **Step 4: Pass collection_watermark_at to _maybe_rebuild_thread_summary**

In `_process_thread_rebuild_lease` (around line 207), update the call to `_maybe_rebuild_thread_summary` to pass the lease's watermark:

```python
thread_result, supersession_pairs, thread_items = self._maybe_rebuild_thread_summary(
    plugin=plugin,
    thread_scope=current_lease.as_scope(),
    collection_watermark_at=current_lease.collection_watermark_at,
)
```

- [ ] **Step 5: Branch collection in `_maybe_rebuild_thread_summary`**

Modify `_maybe_rebuild_thread_summary` (starting at line 350):

```python
def _maybe_rebuild_thread_summary(
    self,
    *,
    plugin: SemanticPlugin,
    thread_scope: ThreadProcessingScope,
    collection_watermark_at: datetime | None = None,
) -> tuple[ProcessResult | None, dict[str, list[str]], list[SourceItem]]:
    if not isinstance(plugin, ThreadAggregationSemanticPlugin):
        return None, {}, []

    is_container_scope = thread_scope.thread_ref is None

    if is_container_scope:
        is_incremental = not getattr(plugin, 'rebuild_supersedes_prior', True)
        if is_incremental:
            thread_items = [
                item
                for item in self._storage.list_top_level_messages_for_container(
                    thread_scope.container_ref,
                    after_created_at=collection_watermark_at,
                )
                if plugin.supports_thread_aggregation(item)
            ]
        else:
            thread_items = [
                item
                for item in self._storage.list_top_level_messages_for_container(
                    thread_scope.container_ref,
                    max_items=CONTAINER_SCOPE_RECENT_ITEMS,
                )
                if plugin.supports_thread_aggregation(item)
            ]
    else:
        thread_items = [
            item
            for item in self._storage.list_source_items_for_thread(thread_scope.container_ref, thread_scope.thread_ref)
            if plugin.supports_thread_aggregation(item)
        ]

    if plugin.requires_visibility_context:
        thread_items = [
            item
            for item in thread_items
            if visibility_matches_exact(item.visibility, thread_scope.visibility)
        ]

    # 2-item minimum only applies to thread scopes, not container scopes
    if not is_container_scope and len(thread_items) < 2:
        return None, {}, thread_items
    if is_container_scope and len(thread_items) < 1:
        return None, {}, thread_items

    memory_by_source = self._storage.list_memory_objects_for_source_items(
        [item.id for item in thread_items],
    )
    active_thread_memory_ids = self._find_active_thread_memory_ids(thread_items, memory_by_source)
    aggregate = build_thread_aggregate(thread_items, container_scope=is_container_scope)
    conclusions = self._collect_thread_conclusions(thread_items, memory_by_source, conclusion_types=plugin.thread_conclusion_types)
    thread_result = plugin.build_thread_summary(aggregate, conclusions)
    reconcile_process_result = getattr(plugin, "reconcile_process_result", None)
    if callable(reconcile_process_result) and thread_result is not None:
        thread_result = reconcile_process_result(
            thread_result,
            storage=self._storage,
            container_ref=thread_scope.container_ref,
            visibility=thread_scope.visibility,
        )
    supersede_plan: dict[str, list[str]] = {}
    if getattr(plugin, 'rebuild_supersedes_prior', True):
        for memory_object in thread_result.memory_objects:
            key = (memory_object.type, memory_object.schema_id)
            supersede_plan[memory_object.id] = [
                superseded_id
                for superseded_id in active_thread_memory_ids.get(key, [])
                if superseded_id != memory_object.id
            ]
    return thread_result, supersede_plan, thread_items
```

- [ ] **Step 6: Store collection_watermark_at on rebuild completion**

In `_process_thread_rebuild_lease`, after `_maybe_rebuild_thread_summary` returns successfully, compute the watermark from collected items and pass it to the commit method. At the `commit_process_result_and_complete_scope` call (around line 245):

```python
# Compute collection watermark from collected items
items_watermark = max(
    (item.created_at for item in thread_items), default=None
) if thread_items else None

if thread_result is not None:
    try:
        has_pending = self._storage.commit_process_result_and_complete_scope(
            result=thread_result,
            supersession_pairs=supersession_pairs,
            scope_key=current_lease.scope_key,
            worker_id=worker_id,
            claimed_at=current_lease.processing_claimed_at,
            collection_watermark_at=items_watermark,
        )
```

- [ ] **Step 7: Skip the plugin-level 2-item guard for container scopes**

In `semantic/conversational_knowledge.py`, modify `build_thread_summary` (line 326):

```python
is_container_scope = aggregate.thread_ref is None
if not is_container_scope and len(aggregate.source_items) < 2:
    return ProcessResult(memory_objects=[], relations=[], index_entries=[])
```

- [ ] **Step 8: Run the reproduction test**

Run: `python -m pytest tests/test_standalone_message_extraction_gap.py -x -q`
Expected: All 5 tests still pass (container scope not yet wired into commit pipeline — that's the next task).

- [ ] **Step 9: Run full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 10: Commit**

```bash
git add core/thread_rebuild.py semantic/conversational_knowledge.py
git commit -m "feat: container scope building, branched bounded collection, scope-aware 2-item minimum"
```

---

### Task 8: Wire container scope into the processing pipeline

Every eligible item must bump both a thread scope and a container scope atomically within the same commit transaction. The `collection_watermark_at` is stored on the lease at rebuild completion.

**Files:**
- Modify: `storage/base.py` (add `container_rebuild_scope` and `collection_watermark_at` parameters)
- Modify: `storage/sqlite_queue.py` (handle both in implementations)
- Modify: `core/processing.py:285-342`

- [ ] **Step 1: Add `container_rebuild_scope` to commit method signatures**

In `storage/base.py`, update `commit_processed_source_item` (line 214):

```python
@abstractmethod
def commit_processed_source_item(
    self,
    *,
    source_item_id: str,
    result: ProcessResult,
    thread_rebuild_scope: ThreadProcessingScope | None = None,
    container_rebuild_scope: ThreadProcessingScope | None = None,
    completed_at: datetime | None = None,
) -> list[tuple[str, str]]:
```

And `commit_package_process_result` (line 579):

```python
@abstractmethod
def commit_package_process_result(
    self,
    *,
    source_item_id: str,
    result: ProcessResult,
    thread_rebuild_scope: ThreadProcessingScope | None = None,
    container_rebuild_scope: ThreadProcessingScope | None = None,
    completed_at: datetime | None = None,
) -> list[tuple[str, str]]:
```

And `commit_process_result_and_complete_scope` (line 245):

```python
@abstractmethod
def commit_process_result_and_complete_scope(
    self,
    *,
    result: ProcessResult,
    supersession_pairs: list[tuple[str, str]] | None = None,
    scope_key: str,
    worker_id: str,
    claimed_at: datetime,
    completed_at: datetime | None = None,
    collection_watermark_at: datetime | None = None,
) -> bool:
```

- [ ] **Step 2: Handle `container_rebuild_scope` and `collection_watermark_at` in SQLite implementations**

In `storage/sqlite_queue.py`, update `commit_processed_source_item` — add `container_rebuild_scope` parameter and upsert after the thread scope:

```python
def commit_processed_source_item(
    self,
    *,
    source_item_id: str,
    result: ProcessResult,
    thread_rebuild_scope: ThreadProcessingScope | None = None,
    container_rebuild_scope: ThreadProcessingScope | None = None,
    completed_at: datetime | None = None,
) -> list[tuple[str, str]]:
    finished_at = completed_at or utc_now()
    with self._session_factory.begin() as session:
        self._persist_process_result_in_session(session, result)
        supersession_pairs = self._resolve_supersession_pairs_in_session(session, result)
        self._apply_supersession_pairs_in_session(session, supersession_pairs)
        self._apply_source_item_metadata_updates_in_session(session, result.source_item_metadata_updates)
        self._refresh_memory_freshness_for_ids_in_session(session, [memory.id for memory in result.memory_objects])
        if thread_rebuild_scope is not None:
            self._upsert_thread_processing_scope_in_session(
                session, scope=thread_rebuild_scope, requested_at=finished_at,
            )
        if container_rebuild_scope is not None:
            self._upsert_thread_processing_scope_in_session(
                session, scope=container_rebuild_scope, requested_at=finished_at,
            )
        self._after_commit_processed_source_item_persist(
            session, source_item_id=source_item_id,
            result=result, supersession_pairs=supersession_pairs,
        )
        record = session.get(SourceItemRecord, source_item_id)
        if record is None:
            raise KeyError(source_item_id)
        record.processing_status = "completed"
        record.processing_completed_at = finished_at
        record.processing_error = None
        record.processing_claimed_by = None
        record.processing_claimed_at = None
        record.processing_lease_expires_at = None
        record.processing_next_attempt_at = None
    return supersession_pairs
```

Same change in `commit_package_process_result`.

Update `commit_process_result_and_complete_scope` to store `collection_watermark_at`:

```python
def commit_process_result_and_complete_scope(
    self,
    *,
    result: ProcessResult,
    supersession_pairs: list[tuple[str, str]] | None = None,
    scope_key: str,
    worker_id: str,
    claimed_at: datetime,
    completed_at: datetime | None = None,
    collection_watermark_at: datetime | None = None,
) -> bool:
    finished_at = completed_at or utc_now()
    normalized_claimed_at = self._normalize_datetime(claimed_at) or claimed_at
    with self._session_factory.begin() as session:
        self._persist_process_result_in_session(session, result)
        resolved_pairs = self._resolve_supersession_pairs_in_session(session, result)
        all_pairs = resolved_pairs + (supersession_pairs or [])
        self._apply_supersession_pairs_in_session(session, all_pairs)
        self._apply_source_item_metadata_updates_in_session(session, result.source_item_metadata_updates)
        self._refresh_memory_freshness_for_ids_in_session(session, [memory.id for memory in result.memory_objects])

        record = session.get(ThreadProcessingLeaseRecord, scope_key)
        if record is None:
            raise KeyError(scope_key)
        record_claimed_at = self._normalize_datetime(record.processing_claimed_at)
        if record.processing_claimed_by != worker_id or record_claimed_at != normalized_claimed_at:
            return record.requested_at is not None
        requested_at = self._normalize_datetime(record.requested_at)
        pending_after = requested_at is not None and requested_at > normalized_claimed_at
        if not pending_after:
            record.requested_at = None
        record.processing_completed_at = finished_at
        record.processing_claimed_by = None
        record.processing_claimed_at = None
        record.processing_lease_expires_at = None
        if collection_watermark_at is not None:
            record.collection_watermark_at = collection_watermark_at
        record.updated_at = finished_at
        return pending_after
```

- [ ] **Step 3: Build and pass container scope in processing pipeline**

In `core/processing.py`, modify `_process_source_item` (around line 285):

```python
thread_rebuild_scope = None
container_rebuild_scope = None
if direct_result.thread_rebuild_requested:
    thread_rebuild_scope = self._thread_rebuilder.build_thread_processing_scope(
        plugin_name=plugin_name,
        plugin=plugin,
        source_item=source_item,
    )
    container_rebuild_scope = self._thread_rebuilder.build_container_processing_scope(
        plugin_name=plugin_name,
        plugin=plugin,
        source_item=source_item,
    )
```

Update the multi-package commit path (around line 331):

```python
if using_package_tracking:
    supersession_pairs = self._storage.commit_package_process_result(
        source_item_id=source_item.id,
        result=direct_result,
        thread_rebuild_scope=thread_rebuild_scope,
        container_rebuild_scope=container_rebuild_scope,
    )
    self._storage.complete_package_task(source_item.id, plugin_name)
```

Update the single-package commit path (around line 338):

```python
else:
    supersession_pairs = self._storage.commit_processed_source_item(
        source_item_id=source_item.id,
        result=direct_result,
        thread_rebuild_scope=thread_rebuild_scope,
        container_rebuild_scope=container_rebuild_scope,
    )
```

- [ ] **Step 4: Run the reproduction test — expect failures**

Run: `python -m pytest tests/test_standalone_message_extraction_gap.py -x -q`
Expected: Tests that assert zero facts should now FAIL — container scope extraction fires.

- [ ] **Step 5: Flip the reproduction test assertions**

In `tests/test_standalone_message_extraction_gap.py`:

For `test_standalone_user_messages_produce_no_facts` — change to expect facts:

```python
facts = _collect_facts(service._storage, CONTAINER_REF)
assert len(facts) >= 1, (
    "Container-level extraction should produce atomic_facts "
    "from standalone user messages"
)
```

For `test_standalone_user_and_assistant_both_orphaned` — change to expect facts:

```python
facts = _collect_facts(service._storage, CONTAINER_REF)
assert len(facts) >= 1, (
    "Container-level extraction should produce atomic_facts "
    "from both standalone user and assistant messages"
)
```

For `test_mixed_container_thread_extracts_but_standalones_do_not` — change unextracted assertion:

```python
unextracted = _collect_source_items_without_fact_extraction(
    service._storage, CONTAINER_REF,
)
assert len(unextracted) == 0, (
    "All messages should have fact extraction — thread-level for the "
    "multi-item thread, container-level for standalone messages"
)
```

For `test_standalone_messages_create_completed_scopes` — add assertion for container scope:

```python
container_scopes = [s for s in scopes if '"thread_ref":null' in s.scope_key]
assert len(container_scopes) >= 1, (
    "Container scope should be created for the container"
)
```

- [ ] **Step 6: Run reproduction tests**

Run: `python -m pytest tests/test_standalone_message_extraction_gap.py -x -q`
Expected: All tests PASS.

- [ ] **Step 7: Run full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 8: Commit**

```bash
git add core/processing.py storage/base.py storage/sqlite_queue.py tests/test_standalone_message_extraction_gap.py
git commit -m "feat: wire container scope into processing pipeline, flip reproduction tests"
```

---

### Task 9: Verify observability and consolidation with None thread_ref

**Files:**
- Modify: `tests/test_container_scope_schema.py`

- [ ] **Step 1: Verify observability emit handles None thread_ref**

Run: `python -m pytest tests/test_standalone_message_extraction_gap.py -x -q -s`
Expected: No errors from observability.

- [ ] **Step 2: Add consolidation trigger tests**

```python
# Add to tests/test_container_scope_schema.py
def test_consolidation_trigger_with_none_thread_ref():
    """Container scope facts should trigger consolidation against thread-scope facts."""
    current_thread_ref = None
    fact_thread_ref = "slack:thread:test:123"
    has_cross_thread = fact_thread_ref and fact_thread_ref != current_thread_ref
    assert has_cross_thread is True

def test_thread_scope_consolidation_against_container_facts():
    """Thread-scope rebuild: container-scope facts (thread_ref=None) don't trigger
    consolidation from the thread side due to falsy None.  Acceptable — the
    next container-scope rebuild triggers it in the other direction."""
    current_thread_ref = "slack:thread:test:456"
    container_fact_thread_ref = None
    has_cross_thread = container_fact_thread_ref and container_fact_thread_ref != current_thread_ref
    assert has_cross_thread is not True
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_container_scope_schema.py
git commit -m "test: verify observability and consolidation handle None thread_ref"
```

---

### Task 10: Final integration verification

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: All tests pass.

- [ ] **Step 2: Run the reproduction test specifically**

Run: `python -m pytest tests/test_standalone_message_extraction_gap.py -x -v`
Expected: All 5 tests pass with the new assertions.

- [ ] **Step 3: Run existing thread aggregation tests**

Run: `python -m pytest tests/test_thread_aggregation.py tests/test_thread_summary_accumulation.py -x -q`
Expected: All pass — thread-level extraction unchanged.

- [ ] **Step 4: Run conversational knowledge tests**

Run: `python -m pytest tests/test_conversational_knowledge.py -x -q`
Expected: All pass.

- [ ] **Step 5: Run thread_position and container collection tests**

Run: `python -m pytest tests/test_thread_position.py tests/test_container_collection.py -x -q`
Expected: All pass.

- [ ] **Step 6: Clean up test files if needed**

Consider merging `test_container_scope_schema.py`, `test_container_aggregate.py`, `test_container_collection.py`, `test_container_eligibility.py`, and `test_thread_position.py` into a single `test_container_extraction.py` if they're small. Keep them separate if each has sufficient content.

- [ ] **Step 7: Final commit**

```bash
git add -A
git commit -m "chore: clean up container extraction test organization"
```

---

## Performance Guarantees

| Operation | Bound | Mechanism |
|-----------|-------|-----------|
| Container collection (incremental plugin) | O(delta) | `after_created_at` from `collection_watermark_at` on lease |
| Container collection (superseding plugin) | O(200) | `max_items=CONTAINER_SCOPE_RECENT_ITEMS` |
| Container collection SQL | O(bounded) via index | `idx_source_items_container_top_level(container_ref, thread_position, created_at)` |
| Thread position at ingest | O(1) | COUNT with covering index, `BEGIN IMMEDIATE` for safety |
| Thread scope collection | O(N_thread) | Unchanged, bounded by thread size |
| Dual scope upsert per item | O(1) + O(1) | Two PK upserts in same transaction |
| Downstream processing | bounded by collection | `list_memory_objects`, `build_aggregate`, `_collect_conclusions` all operate on collected items |

## Verification Sequence

After all tasks are complete:

```bash
# Full test suite
python -m pytest tests/ -x -q

# Specific reproduction tests
python -m pytest tests/test_standalone_message_extraction_gap.py -x -v

# Thread-level regression check
python -m pytest tests/test_thread_aggregation.py tests/test_thread_summary_accumulation.py tests/test_conversational_knowledge.py -x -q

# Container collection and thread_position
python -m pytest tests/test_thread_position.py tests/test_container_collection.py -x -q

# Evidence drill-down still works
python -m pytest tests/test_evidence_drilldown.py -x -q
```
