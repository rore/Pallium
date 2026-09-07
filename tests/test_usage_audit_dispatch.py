from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Event, Thread
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app
from core.service import PalliumService
from storage.vector_index import VectorIndexConfig
from tests.config_helpers import DEMO_SEMANTIC_PACKAGES


def _service(monkeypatch):
    service = object.__new__(PalliumService)
    service._audit_executor = ThreadPoolExecutor(max_workers=1)
    service._audit_slots = __import__("threading").BoundedSemaphore(2)
    service._logger = SimpleNamespace(warning=lambda *args, **kwargs: None)
    service._storage = SimpleNamespace()
    return service


def test_audit_population_is_per_row_and_idempotent(monkeypatch):
    service = _service(monkeypatch)
    rows = [
        {"id": "one", "memory_object_id": "mem-1"},
        {"id": "two", "memory_object_id": "mem-2"},
    ]
    updated = []
    scopes = []

    def list_pending(thread_ref, **kwargs):
        scopes.append((thread_ref, kwargs["container_ref"]))
        return rows

    service.list_pending_memory_usage_audit_by_thread = list_pending
    service.get_memory_expand = lambda memory_id: (
        None, [], "A useful stored canonical sentence that is long enough",
    )

    def update(**kwargs):
        updated.append(kwargs)
        return True

    service.update_memory_usage_audit = update
    service.populate_memory_usage_audit(
        "container", "thread", "A useful stored canonical sentence that is long enough",
    )
    assert [item["audit_row_id"] for item in updated] == ["one", "two"]
    assert scopes == [("thread", "container")]
    service.close()


def test_audit_queue_saturation_and_shutdown_are_deterministic(monkeypatch):
    service = _service(monkeypatch)
    started, release, finished = Event(), Event(), Event()

    def work(*_args, **_kwargs):
        started.set()
        release.wait()
        finished.set()

    service.populate_memory_usage_audit = work
    service._storage.get_source_item = lambda _id: SimpleNamespace(
        role="assistant", container_ref="container", thread_ref="thread",
        content="persisted redacted",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert service.enqueue_memory_usage_audit("source-2")
    assert started.wait(1)
    assert service.enqueue_memory_usage_audit("source-2")
    assert not service.enqueue_memory_usage_audit("source-3")
    release.set()
    service.close()
    assert finished.is_set()


def test_source_miss_retries_on_later_assistant_ingest_idempotently(monkeypatch):
    service = _service(monkeypatch)
    lookup_done = Event()
    attempts = []
    item = SimpleNamespace(
        role="assistant", container_ref="container", thread_ref="thread",
        content="persisted",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    def get_source_item(source_id):
        attempts.append(source_id)
        if len(attempts) == 1:
            lookup_done.set()
            raise KeyError(source_id)
        return item

    service._storage.get_source_item = get_source_item
    populated = []
    populated_done = Event()

    def populate(container, thread, content, *, before_created_at):
        populated.append((container, thread, content, before_created_at))
        populated_done.set()

    service.populate_memory_usage_audit = populate
    assert service.enqueue_memory_usage_audit("source-retry")
    assert lookup_done.wait(1)
    assert service.enqueue_memory_usage_audit("source-retry")
    assert populated_done.wait(1)
    service.close()
    assert populated == [(
        "container", "thread", "persisted", datetime(2026, 1, 1, tzinfo=timezone.utc),
    )]
    assert attempts == ["source-retry", "source-retry"]


def test_app_shutdown_drains_http_audit_before_storage_close(monkeypatch, tmp_path):
    app = create_app(AppConfig(
        storage_backend="sqlite",
        sqlite_url=f"sqlite:///{tmp_path / 'shutdown.db'}",
        default_use_case="demo_agent_memory",
        semantic_packages=DEMO_SEMANTIC_PACKAGES,
        vector_index=VectorIndexConfig(enabled=False),
    ))
    service = app.state.pallium_service
    storage = service._storage
    started, release, finished = Event(), Event(), Event()
    close_started, storage_closed = Event(), Event()

    def work(*_args, **_kwargs):
        started.set()
        release.wait()
        finished.set()

    original_service_close = service.close
    original_storage_close = storage.close

    def close_service():
        close_started.set()
        original_service_close()

    def close_storage():
        assert finished.is_set()
        storage_closed.set()
        original_storage_close()

    service.populate_memory_usage_audit = work
    monkeypatch.setattr(service, "close", close_service)
    monkeypatch.setattr(storage, "close", close_storage)

    def release_during_shutdown():
        assert close_started.wait(2)
        assert not storage_closed.is_set()
        release.set()

    releaser = Thread(target=release_during_shutdown)
    with TestClient(app) as client:
        response = client.post("/items", json=[{
            "source_type": "chat_message",
            "source_id": "shutdown-audit",
            "content_type": "text/plain",
            "content": "The migration is complete.",
            "artifact_kind": "message",
            "role": "assistant",
            "container_ref": "room:shutdown",
            "thread_ref": "thread-shutdown",
            "visibility": "private",
        }])
        assert response.status_code == 200
        assert started.wait(2)
        releaser.start()

    releaser.join(2)
    assert not releaser.is_alive()
    assert finished.is_set()
    assert storage_closed.is_set()
