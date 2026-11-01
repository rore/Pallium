import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading

from fastapi.testclient import TestClient
import pytest

from app import main
from app.relay_trace import RelayTraceWriter
from tests.test_dashboard import _test_config


@pytest.fixture
def app_factory(tmp_path, monkeypatch):
    from app import codex_bridge_pipe

    monkeypatch.setenv("PALLIUM_HOME", str(tmp_path / "isolated-home"))
    monkeypatch.setattr(main, "_write_launch_token", lambda: None)
    monkeypatch.setattr(main, "_remove_launch_token", lambda path: None)
    monkeypatch.setattr(main, "start_claude_wake_reconciler", lambda *a, **kw: None)
    for name in ("start_shadow_service", "start_inventory_service", "start_retained_service"):
        monkeypatch.setattr(codex_bridge_pipe, name, lambda *a, **kw: None)
    apps = []

    def create():
        app = main.create_app(_test_config(tmp_path))
        apps.append(app)
        return app

    yield create
    for app in apps:
        app.state._close_constructed()


def test_http_trace_uses_app_owner_without_memory_trace_facade(client, monkeypatch):
    worker = client.app.state.relay_trace_writer
    service = client.app.state.pallium_service
    assert not hasattr(service, "enqueue_relay_trace_event")
    assert not hasattr(service, "_relay_trace_executor")

    def schedule(result, scope, *, trace_callback, **kwargs):
        delivery, = result["deliveries"]
        assert trace_callback({
            "attempt_id": "relay-activation-" + "a" * 32,
            "delivery_id": delivery["delivery_id"],
            "recipient_endpoint_id": delivery["recipient_endpoint_id"],
            "stage": "prepared",
        })

    monkeypatch.setattr("app.dependencies.schedule_codex_relay_wake", schedule)
    scope = {"container_ref": "git:example.test/app-trace-東京"}
    for session in ("sender", "target"):
        assert client.post("/relay/turn", json={"runtime": "codex", "session_ref": session, **scope}).status_code == 200
    sent = client.post("/relay/messages", json={"sender_runtime": "codex", "sender_session_ref": "sender",
        "recipient": "codex:target", "payload": "private message 東京", **scope})
    assert sent.status_code == 200
    worker._executor.submit(lambda: None).result(3)
    trace = client.get(f"/relay/messages/{sent.json()['message_id']}/trace", params=scope)
    assert trace.status_code == 200
    assert [row["stage"] for row in trace.json()["events"]] == ["prepared"]
    assert "private message" not in trace.text
    delivery, = sent.json()["deliveries"]
    claimed = client.post("/relay/turn", json={"runtime": "codex", "session_ref": "target",
        "wake_delivery_id": delivery["delivery_id"], **scope})
    assert claimed.status_code == 200
    claim, = claimed.json()["deliveries"]
    assert client.post("/relay/deliveries/ack", json={"delivery_id": claim["delivery_id"],
        "claim_token": claim["claim_token"], **scope}).status_code == 200
    assert client.app.state.relay_trace_writer is worker
    assert client.get(f"/relay/messages/{sent.json()['message_id']}", params=scope).json()["deliveries"][0]["state"] == "delivered"


def test_trace_constructor_failure_keeps_http_available(app_factory, monkeypatch, caplog):
    def failed():
        raise RuntimeError("private-constructor-token")

    monkeypatch.setattr(main, "RelayTraceWriter", failed)
    app = app_factory()
    assert app.state.relay_trace_writer is None
    with TestClient(app) as http:
        assert http.get("/health").status_code == 200
        assert http.post("/relay/turn", json={"runtime": "codex", "session_ref": "target",
            "container_ref": "git:example.test/optional-trace"}).status_code == 200
    assert "relay_trace_lifecycle outcome=unavailable reason=start_failed" in caplog.text
    assert "private-constructor-token" not in caplog.text


def test_full_trace_queue_keeps_http_send_claim_ack_and_recovers(client, monkeypatch):
    worker = client.app.state.relay_trace_writer
    entered, release = threading.Event(), threading.Event()
    accepted = []

    def schedule(result, scope, *, trace_callback, **kwargs):
        delivery, = result["deliveries"]
        accepted.append(trace_callback({
            "attempt_id": "relay-activation-" + "b" * 32,
            "delivery_id": delivery["delivery_id"],
            "recipient_endpoint_id": delivery["recipient_endpoint_id"],
            "stage": "prepared",
        }))

    def hold(event):
        entered.set()
        assert release.wait(10)

    monkeypatch.setattr("app.dependencies.schedule_codex_relay_wake", schedule)
    scope = {"container_ref": "git:example.test/trace-capacity"}
    for session in ("sender", "target"):
        assert client.post("/relay/turn", json={"runtime": "codex", "session_ref": session, **scope}).status_code == 200
    try:
        assert worker.enqueue(hold, {}) and entered.wait(3)
        for _ in range(63):
            assert worker.enqueue(lambda event: None, {})
        sent = client.post("/relay/messages", json={"sender_runtime": "codex", "sender_session_ref": "sender",
            "recipient": "codex:target", "payload": "accepted while tracing is full", **scope})
        assert sent.status_code == 200 and accepted == [False]
        delivery, = sent.json()["deliveries"]
        claimed = client.post("/relay/turn", json={"runtime": "codex", "session_ref": "target",
            "wake_delivery_id": delivery["delivery_id"], **scope})
        assert claimed.status_code == 200
        claim, = claimed.json()["deliveries"]
        assert claim["attempts"] == 1
        assert client.post("/relay/deliveries/ack", json={"delivery_id": claim["delivery_id"],
            "claim_token": claim["claim_token"], **scope}).status_code == 200
        assert client.get(f"/relay/messages/{sent.json()['message_id']}", params=scope).json()["deliveries"][0]["state"] == "delivered"
        assert client.get(f"/relay/messages/{sent.json()['message_id']}/trace", params=scope).json()["events"] == []
    finally:
        release.set()
        worker._executor.submit(lambda: None).result(3)
    later = client.post("/relay/messages", json={"sender_runtime": "codex", "sender_session_ref": "sender",
        "recipient": "codex:target", "payload": "later trace accepted", **scope})
    assert later.status_code == 200 and accepted == [False, True]
    worker._executor.submit(lambda: None).result(3)
    assert [row["stage"] for row in client.get(f"/relay/messages/{later.json()['message_id']}/trace", params=scope).json()["events"]] == ["prepared"]


def test_partial_app_construction_closes_trace_before_storage(app_factory, monkeypatch):
    workers, order = [], []
    original_storage = main.build_storage_provider
    sentinel = RuntimeError("controlled route construction failure")

    def worker():
        instance = RelayTraceWriter()
        workers.append(instance)
        return instance

    def storage(*args, **kwargs):
        instance = original_storage(*args, **kwargs)
        close = instance.close
        def checked_close():
            assert workers[0]._closed
            assert not any(thread.is_alive() for thread in workers[0]._executor._threads)
            order.append("storage")
            return close()
        instance.close = checked_close
        return instance

    def fail(*args, **kwargs):
        raise sentinel

    monkeypatch.setattr(main, "RelayTraceWriter", worker)
    monkeypatch.setattr(main, "build_storage_provider", storage)
    monkeypatch.setattr(main, "mount_dashboard", fail)
    with pytest.raises(RuntimeError) as error:
        app_factory()
    assert error.value is sentinel
    assert len(workers) == 1 and order == ["storage"]


@pytest.mark.parametrize("exit_kind", ["startup_failure", "shutdown", "cancel"])
def test_app_trace_drains_before_storage_on_every_lifecycle_exit(app_factory, monkeypatch, exit_kind):
    app = app_factory()
    worker = app.state.relay_trace_writer
    entered, release, closing, storage_closed = (threading.Event() for _ in range(4))
    trace_done = threading.Event()
    cancellation = []
    original_close = worker.close
    storage = app.state.pallium_service._storage
    original_storage_close = storage.close
    sentinel = RuntimeError("controlled startup failure")

    def hold(event):
        entered.set()
        assert release.wait(10)
        trace_done.set()

    def close():
        closing.set()
        return original_close()

    def close_storage():
        assert trace_done.is_set()
        assert not any(thread.is_alive() for thread in worker._executor._threads)
        storage_closed.set()
        return original_storage_close()

    monkeypatch.setattr(worker, "close", close)
    monkeypatch.setattr(storage, "close", close_storage)
    if exit_kind == "startup_failure":
        def fail(*args, **kwargs):
            assert worker.enqueue(hold, {"stage": "prepared"})
            assert entered.wait(3)
            raise sentinel
        monkeypatch.setattr(main, "recover_claude_registration_intents", fail)

    def run():
        if exit_kind == "cancel":
            async def lifespan():
                async with app.router.lifespan_context(app):
                    cancellation.append((asyncio.get_running_loop(), asyncio.current_task()))
                    assert worker.enqueue(hold, {"stage": "prepared"})
                    await asyncio.Event().wait()
            try:
                asyncio.run(lifespan())
            except asyncio.CancelledError:
                return "cancelled"
        else:
            try:
                with TestClient(app) as http:
                    assert http.get("/health").status_code == 200
                    assert worker.enqueue(hold, {"stage": "prepared"})
                    assert entered.wait(3)
            except RuntimeError as error:
                assert exit_kind == "startup_failure" and error is sentinel
                return "startup_failure"
            return "shutdown"

    with ThreadPoolExecutor(max_workers=1) as tasks:
        future = tasks.submit(run)
        try:
            assert entered.wait(10)
            if exit_kind == "cancel":
                loop, task = cancellation[0]
                loop.call_soon_threadsafe(task.cancel)
            assert closing.wait(3)
            assert not storage_closed.is_set() and not future.done()
            assert not worker.enqueue(lambda event: None, {})
        finally:
            release.set()
        assert future.result(10) == ("cancelled" if exit_kind == "cancel" else exit_kind)
    assert trace_done.is_set() and storage_closed.is_set()
    app.state._close_constructed()
