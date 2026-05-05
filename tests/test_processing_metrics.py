"""Tests for metrics recording in the processing pipeline.

Verifies that ItemProcessor records processing/item_processed,
processing/extraction_failed, and work_trace/thread_rebuild events
via an injected MetricsStore.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, call

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.contracts import ProcessResult
from core.models import MemoryObject, SourceItem, new_id
from core.observability import IntegrationDebugLogger
from core.processing import ItemProcessor
from core.service import PalliumService
from core.thread_rebuild import ThreadRebuilder
from core.vector_embed import VectorEmbedder
from retrieval.lexical import LexicalRetrievalProvider
from semantic.base import SemanticPlugin
from storage.metrics import MetricsStore
from storage.sqlite import SQLiteStorageProvider
from storage.sqlite_schema import Base


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def db_url(tmp_path):
    return f"sqlite:///{tmp_path / 'test.db'}"


@pytest.fixture
def storage(db_url):
    return SQLiteStorageProvider(db_url)


@pytest.fixture
def metrics_store(db_url):
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    return MetricsStore(factory)


def _make_source_item(
    *,
    use_case: str = "test_pkg",
    container_ref: str = "git:example.com/repo",
    thread_ref: str = "thread-1",
) -> SourceItem:
    return SourceItem(
        source_type="test",
        source_id=f"src-{new_id()[:8]}",
        content_type="text/plain",
        content="some content",
        use_case=use_case,
        container_ref=container_ref,
        thread_ref=thread_ref,
        visibility="private",
    )


def _make_memory_object(
    type_: str = "decision",
    schema_id: str = "decision",
    payload: dict | None = None,
    container_ref: str = "git:example.com/repo",
) -> MemoryObject:
    return MemoryObject(
        type=type_,
        schema_id=schema_id,
        schema_version="1",
        payload=payload or {"content": "decided something"},
        container_ref=container_ref,
    )


class FixedResultPlugin(SemanticPlugin):
    """Plugin that returns a pre-configured ProcessResult."""

    name = "fixed_plugin"

    def __init__(self, result: ProcessResult):
        self._result = result

    def process_item(self, source_item: SourceItem) -> ProcessResult:
        return self._result


class AlwaysFailPlugin(SemanticPlugin):
    """Plugin that raises an exception."""

    name = "fail_plugin"

    def __init__(self, exc: Exception | None = None):
        self._exc = exc or RuntimeError("extraction failed")

    def process_item(self, source_item: SourceItem) -> ProcessResult:
        raise self._exc


def _build_processor(
    storage: SQLiteStorageProvider,
    plugin: SemanticPlugin,
    metrics_store=None,
) -> tuple[ItemProcessor, PalliumService]:
    """Build a minimal ItemProcessor backed by a real service (for get_item_processing)."""
    service = PalliumService(
        storage=storage,
        retrieval=LexicalRetrievalProvider(storage),
        semantic_plugins={plugin.name: plugin},
        default_use_case=plugin.name,
        metrics_store=metrics_store,
    )
    return service._processor, service


# ---------------------------------------------------------------------------
# Tests: item_processed
# ---------------------------------------------------------------------------


def test_item_processed_records_metric(db_url, metrics_store):
    """After successful processing, a processing/item_processed row exists."""
    storage = SQLiteStorageProvider(db_url)
    plugin = FixedResultPlugin(ProcessResult(memory_objects=[], relations=[], index_entries=[]))
    processor, service = _build_processor(storage, plugin, metrics_store=metrics_store)

    source_item = _make_source_item(use_case=plugin.name)
    storage.create_source_item_with_packages(source_item, [plugin.name])
    processor._process_source_item(source_item, max_attempts=3)

    rows = metrics_store.query(category="processing", event_type="item_processed")
    assert len(rows) == 1


def test_item_processed_records_package_name(db_url, metrics_store):
    """The package name is stored in the metric payload."""
    storage = SQLiteStorageProvider(db_url)
    plugin = FixedResultPlugin(ProcessResult(memory_objects=[], relations=[], index_entries=[]))
    processor, service = _build_processor(storage, plugin, metrics_store=metrics_store)

    source_item = _make_source_item(use_case=plugin.name)
    storage.create_source_item_with_packages(source_item, [plugin.name])
    processor._process_source_item(source_item, max_attempts=3)

    rows = metrics_store.query(category="processing", event_type="item_processed")
    assert rows[0].payload["package"] == plugin.name


def test_item_processed_records_memory_types(db_url, metrics_store):
    """memory_types_created lists the types of produced memory objects."""
    storage = SQLiteStorageProvider(db_url)
    mo1 = _make_memory_object(type_="decision")
    mo2 = _make_memory_object(type_="investigation_outcome")
    plugin = FixedResultPlugin(ProcessResult(memory_objects=[mo1, mo2], relations=[], index_entries=[]))
    processor, service = _build_processor(storage, plugin, metrics_store=metrics_store)

    source_item = _make_source_item(use_case=plugin.name)
    storage.create_source_item_with_packages(source_item, [plugin.name])
    processor._process_source_item(source_item, max_attempts=3)

    rows = metrics_store.query(category="processing", event_type="item_processed")
    assert set(rows[0].payload["memory_types_created"]) == {"decision", "investigation_outcome"}


# ---------------------------------------------------------------------------
# Tests: extraction_failed
# ---------------------------------------------------------------------------


def test_extraction_failed_records_metric(db_url, metrics_store):
    """On plugin failure, a processing/extraction_failed row is recorded."""
    storage = SQLiteStorageProvider(db_url)
    plugin = AlwaysFailPlugin()
    processor, service = _build_processor(storage, plugin, metrics_store=metrics_store)

    source_item = _make_source_item(use_case=plugin.name)
    storage.create_source_item_with_packages(source_item, [plugin.name])
    processor._process_source_item(source_item, max_attempts=3)

    rows = metrics_store.query(category="processing", event_type="extraction_failed")
    assert len(rows) == 1


def test_extraction_failed_records_package_and_error(db_url, metrics_store):
    """extraction_failed payload contains package name and error string."""
    storage = SQLiteStorageProvider(db_url)
    plugin = AlwaysFailPlugin(RuntimeError("specific boom"))
    processor, service = _build_processor(storage, plugin, metrics_store=metrics_store)

    source_item = _make_source_item(use_case=plugin.name)
    storage.create_source_item_with_packages(source_item, [plugin.name])
    processor._process_source_item(source_item, max_attempts=3)

    rows = metrics_store.query(category="processing", event_type="extraction_failed")
    assert rows[0].payload["package"] == plugin.name
    assert "specific boom" in rows[0].payload["error"]


# ---------------------------------------------------------------------------
# Tests: work_trace/thread_rebuild
# ---------------------------------------------------------------------------


def _make_task_trace_mo(
    *,
    container_ref: str = "git:example.com/repo",
    payload: dict | None = None,
) -> MemoryObject:
    default_payload = {
        "subject": "Fixed retrieval bug",
        "turn_count": 5,
        "exploratory_files": ["a.py", "b.py"],
        "productive_files": ["c.py"],
        "commands_succeeded": [{"cmd": "pytest"}, {"cmd": "git commit"}],
        "commands_failed": [{"cmd": "mypy"}],
        "outcome": "Identified and fixed the issue.",
    }
    return MemoryObject(
        type="task_trace",
        schema_id="agent_work_trace.task_trace",
        schema_version="1",
        payload=payload or default_payload,
        container_ref=container_ref,
    )


def test_task_trace_rebuild_records_work_trace_metric(db_url, metrics_store):
    """When a task_trace memory object is produced, a work_trace/thread_rebuild row is recorded."""
    storage = SQLiteStorageProvider(db_url)
    mo = _make_task_trace_mo()
    plugin = FixedResultPlugin(ProcessResult(memory_objects=[mo], relations=[], index_entries=[]))
    processor, service = _build_processor(storage, plugin, metrics_store=metrics_store)

    source_item = _make_source_item(use_case=plugin.name)
    storage.create_source_item_with_packages(source_item, [plugin.name])
    processor._process_source_item(source_item, max_attempts=3)

    rows = metrics_store.query(category="work_trace", event_type="thread_rebuild")
    assert len(rows) == 1


def test_task_trace_metric_extracts_file_counts(db_url, metrics_store):
    """work_trace/thread_rebuild payload contains correct file and command counts."""
    storage = SQLiteStorageProvider(db_url)
    mo = _make_task_trace_mo()
    plugin = FixedResultPlugin(ProcessResult(memory_objects=[mo], relations=[], index_entries=[]))
    processor, service = _build_processor(storage, plugin, metrics_store=metrics_store)

    source_item = _make_source_item(use_case=plugin.name)
    storage.create_source_item_with_packages(source_item, [plugin.name])
    processor._process_source_item(source_item, max_attempts=3)

    rows = metrics_store.query(category="work_trace", event_type="thread_rebuild")
    assert len(rows) == 1
    p = rows[0].payload
    assert p["exploratory_file_count"] == 2
    assert p["productive_file_count"] == 1
    assert p["commands_succeeded"] == 2
    assert p["commands_failed"] == 1
    assert p["has_outcome"] is True
    assert p["subject"] == "Fixed retrieval bug"
    assert rows[0].value == pytest.approx(5.0)


def test_non_task_trace_no_work_trace_metric(db_url, metrics_store):
    """Memory objects with other schema_ids do NOT trigger a work_trace event."""
    storage = SQLiteStorageProvider(db_url)
    mo = _make_memory_object(type_="decision", schema_id="decision")
    plugin = FixedResultPlugin(ProcessResult(memory_objects=[mo], relations=[], index_entries=[]))
    processor, service = _build_processor(storage, plugin, metrics_store=metrics_store)

    source_item = _make_source_item(use_case=plugin.name)
    storage.create_source_item_with_packages(source_item, [plugin.name])
    processor._process_source_item(source_item, max_attempts=3)

    rows = metrics_store.query(category="work_trace", event_type="thread_rebuild")
    assert len(rows) == 0


# ---------------------------------------------------------------------------
# Tests: None store safety
# ---------------------------------------------------------------------------


def test_metrics_store_none_safe(db_url):
    """Passing metrics_store=None does not crash the processor."""
    storage = SQLiteStorageProvider(db_url)
    plugin = FixedResultPlugin(ProcessResult(memory_objects=[], relations=[], index_entries=[]))
    processor, service = _build_processor(storage, plugin, metrics_store=None)

    source_item = _make_source_item(use_case=plugin.name)
    storage.create_source_item_with_packages(source_item, [plugin.name])
    # Should not raise
    processor._process_source_item(source_item, max_attempts=3)


def test_metrics_store_none_safe_on_failure(db_url):
    """Passing metrics_store=None does not crash on processing failure."""
    storage = SQLiteStorageProvider(db_url)
    plugin = AlwaysFailPlugin()
    processor, service = _build_processor(storage, plugin, metrics_store=None)

    source_item = _make_source_item(use_case=plugin.name)
    storage.create_source_item_with_packages(source_item, [plugin.name])
    # Should not raise
    processor._process_source_item(source_item, max_attempts=3)
