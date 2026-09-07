from concurrent.futures import ThreadPoolExecutor
from threading import Event, Thread
from types import SimpleNamespace

from core.service import PalliumService


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

    def work(*_args):
        started.set()
        release.wait()
        finished.set()

    service.populate_memory_usage_audit = work
    service._storage.get_source_item = lambda _id: SimpleNamespace(
        role="assistant", container_ref="container", thread_ref="thread",
        content="persisted redacted",
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

    def populate(container, thread, content):
        populated.append((container, thread, content))
        populated_done.set()

    service.populate_memory_usage_audit = populate
    assert service.enqueue_memory_usage_audit("source-retry")
    assert lookup_done.wait(1)
    assert service.enqueue_memory_usage_audit("source-retry")
    assert populated_done.wait(1)
    service.close()
    assert populated == [("container", "thread", "persisted")]
    assert attempts == ["source-retry", "source-retry"]


def test_close_drains_active_audit_before_storage_close(monkeypatch):
    service = _service(monkeypatch)
    started, release, finished = Event(), Event(), Event()
    storage_closed = Event()
    service._storage.get_source_item = lambda _id: SimpleNamespace(
        role="assistant", container_ref="container", thread_ref="thread",
        content="persisted",
    )

    def work(*_args):
        started.set()
        release.wait()
        finished.set()

    service.populate_memory_usage_audit = work
    assert service.enqueue_memory_usage_audit("source-close")
    assert started.wait(1)
    closer = Thread(target=service.close)
    closer.start()
    assert not finished.wait(0.05)
    assert not storage_closed.is_set()
    release.set()
    closer.join(1)
    storage_closed.set()
    assert finished.is_set()
    assert not closer.is_alive()