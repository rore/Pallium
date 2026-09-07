from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

from core.service import PalliumService


def _service(monkeypatch):
    service = object.__new__(PalliumService)
    service._audit_executor = ThreadPoolExecutor(max_workers=1)
    service._audit_slots = __import__("threading").BoundedSemaphore(2)
    service._logger = SimpleNamespace(warning=lambda *args, **kwargs: None)
    return service


def test_audit_population_is_per_row_and_idempotent(monkeypatch):
    service = _service(monkeypatch)
    rows = [{"id": "one", "memory_object_id": "mem-1"}, {"id": "two", "memory_object_id": "mem-2"}]
    updated = []
    service.list_pending_memory_usage_audit_by_thread = lambda *_args, **_kwargs: rows
    service.get_memory_expand = lambda memory_id: (None, [], "A useful stored canonical sentence that is long enough")
    def update(**kwargs):
        updated.append(kwargs)
        return True
    service.update_memory_usage_audit = update
    service.populate_memory_usage_audit("thread", "A useful stored canonical sentence that is long enough")
    assert [item["audit_row_id"] for item in updated] == ["one", "two"]
    service.close()


def test_audit_queue_saturation_and_shutdown_are_deterministic(monkeypatch):
    service = _service(monkeypatch)
    started, release, finished = Event(), Event(), Event()
    def work(*_args):
        started.set(); release.wait(); finished.set()
    service.populate_memory_usage_audit = work
    assert service.enqueue_memory_usage_audit("t", "r")
    assert started.wait(1)
    assert service.enqueue_memory_usage_audit("t", "r")
    assert not service.enqueue_memory_usage_audit("t", "r")
    release.set()
    service.close()
    assert finished.is_set()