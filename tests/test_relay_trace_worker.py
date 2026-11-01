from concurrent.futures import Future
import threading

import pytest

from app import relay_trace
from app.relay_trace import RelayTraceWriter


def test_trace_capacity_snapshot_and_writer_failure(caplog):
    writer = RelayTraceWriter()
    entered, release = threading.Event(), threading.Event()
    received = []

    def hold(event):
        entered.set()
        assert release.wait(3)
        received.append(event)
        raise RuntimeError("private-payload-token")

    event = {"reason": "東京"}
    try:
        assert writer.enqueue(hold, event)
        assert entered.wait(3)
        event["reason"] = "changed"
        for _ in range(63):
            assert writer.enqueue(received.append, {"stage": "prepared"})
        assert not writer.enqueue(received.append, {"stage": "excess"})
        release.set()
        writer._executor.submit(lambda: None).result(3)
        assert received[0] == {"reason": "東京"} and len(received) == 64
        assert "private-payload-token" not in caplog.text
        assert writer.enqueue(received.append, {"stage": "later"})
        writer._executor.submit(lambda: None).result(3)
    finally:
        release.set()
        writer.close()
    assert received[-1] == {"stage": "later"}
    assert not writer.enqueue(received.append, {"stage": "after-close"})


@pytest.mark.parametrize("fault", ["submit", "snapshot"])
def test_trace_enqueue_failure_returns_all_capacity(monkeypatch, fault):
    writer = RelayTraceWriter()
    try:
        if fault == "submit":
            def fail(*args, **kwargs):
                raise RuntimeError("private-submit-failure")
            monkeypatch.setattr(writer._executor, "submit", fail)
        assert not writer.enqueue(lambda event: None, {} if fault == "submit" else object())
        for _ in range(64):
            assert writer._slots.acquire(blocking=False)
        assert not writer._slots.acquire(blocking=False)
        for _ in range(64):
            writer._slots.release()
    finally:
        writer.close()


@pytest.mark.parametrize("phase", ["submit", "warmup"])
def test_trace_partial_start_closes_executor_and_preserves_failure(monkeypatch, phase):
    sentinel = RuntimeError("private-constructor-failure")
    closed = []

    class BrokenExecutor:
        def __init__(self, **kwargs):
            assert kwargs == {"max_workers": 1, "thread_name_prefix": "relay-trace"}

        def submit(self, operation):
            if phase == "submit":
                raise sentinel
            future = Future()
            future.set_exception(sentinel)
            return future

        def shutdown(self, **kwargs):
            closed.append(kwargs)

    monkeypatch.setattr(relay_trace, "ThreadPoolExecutor", BrokenExecutor)
    with pytest.raises(RuntimeError) as error:
        RelayTraceWriter()
    assert error.value is sentinel
    assert closed == [{"wait": True, "cancel_futures": True}]


def test_trace_cancel_and_concurrent_close_settle_every_owner(monkeypatch):
    writer = RelayTraceWriter()
    entered, release, both_closing = (threading.Event() for _ in range(3))
    completed, future_list, closes = [], [], []
    original_submit = writer._executor.submit
    original_shutdown = writer._executor.shutdown
    lock = threading.Lock()

    def submit(*args, **kwargs):
        future = original_submit(*args, **kwargs)
        future_list.append(future)
        return future

    def shutdown(**kwargs):
        with lock:
            closes.append(True)
            if len(closes) == 2:
                both_closing.set()
        return original_shutdown(**kwargs)

    def hold(event):
        entered.set()
        assert release.wait(3)
        completed.append(event)

    monkeypatch.setattr(writer._executor, "submit", submit)
    monkeypatch.setattr(writer._executor, "shutdown", shutdown)
    threads = []
    try:
        assert writer.enqueue(hold, {"stage": "running"}) and entered.wait(3)
        assert writer.enqueue(completed.append, {"stage": "cancelled"})
        assert future_list[1].cancel()
        assert writer.enqueue(completed.append, {"stage": "shutdown-cancelled"})
        threads = [threading.Thread(target=writer.close) for _ in range(2)]
        for thread in threads:
            thread.start()
        assert both_closing.wait(3)
        assert all(thread.is_alive() for thread in threads)
        assert not writer.enqueue(completed.append, {"stage": "rejected"})
        release.set()
        for thread in threads:
            thread.join(3)
            assert not thread.is_alive()
        assert completed == [{"stage": "running"}]
        for _ in range(64):
            assert writer._slots.acquire(blocking=False)
        assert not writer._slots.acquire(blocking=False)
        for _ in range(64):
            writer._slots.release()
        writer.close()
    finally:
        release.set()
        for thread in threads:
            thread.join(3)
        writer.close()


def test_trace_logging_failure_cannot_change_lifetime_or_release(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("private-log-failure")

    monkeypatch.setattr(relay_trace.logger, "info", fail)
    monkeypatch.setattr(relay_trace.logger, "warning", fail)
    writer = RelayTraceWriter()
    assert writer.enqueue(fail, {"reason": "private-payload"})
    writer._executor.submit(lambda: None).result(3)
    writer.close()
    assert not writer.enqueue(fail, {})
