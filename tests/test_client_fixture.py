from types import SimpleNamespace

import pytest

from app import main as app_main
from tests import conftest


@pytest.mark.parametrize(
    "failure", [None, "http", "wait", "service", "early_storage", "service_storage", "all"]
)
@pytest.mark.parametrize("shared_storage", [False, True])
def test_client_fixture_attempts_all_cleanup_in_order(monkeypatch, failure, shared_storage):
    if shared_storage and failure == "service_storage":
        failure = "early_storage"
    order = ["http", "wait", "service", "early_storage"]
    if not shared_storage:
        order.append("service_storage")
    events = []

    def cleanup(name):
        def close():
            events.append(name)
            if failure in (name, "all"):
                raise RuntimeError(f"failed:{name}")

        return close

    early_storage = SimpleNamespace(close=cleanup("early_storage"))
    service_storage = early_storage if shared_storage else SimpleNamespace(close=cleanup("service_storage"))
    service = SimpleNamespace(_storage=service_storage, close=cleanup("service"))
    app = SimpleNamespace(
        state=SimpleNamespace(pallium_service=service, _wait_for_operations=cleanup("wait"))
    )
    http = SimpleNamespace(close=cleanup("http"))

    def build_storage(config):
        return early_storage

    def create_app(config):
        assert app_main.build_storage_provider(config) is early_storage
        return app

    monkeypatch.setattr(app_main, "build_storage_provider", build_storage)
    monkeypatch.setattr(conftest, "create_app", create_app)
    monkeypatch.setattr(conftest, "TestClient", lambda actual_app: http)
    fixture = conftest.client.__wrapped__("sqlite:///fixture.db", monkeypatch)
    assert next(fixture) is http
    assert app_main.build_storage_provider is build_storage
    assert events == []

    if failure is None:
        with pytest.raises(StopIteration):
            next(fixture)
    else:
        last_failure = order[-1] if failure == "all" else failure
        with pytest.raises(RuntimeError, match=f"^failed:{last_failure}$"):
            next(fixture)
    assert events == order


@pytest.mark.parametrize("failure", ["constructor", "initialize", "first_turn", "second_turn"])
def test_wake_health_world_closes_resources_after_setup_failure(monkeypatch, tmp_path, failure):
    from tests import test_relay_wake_health as health

    events = []
    sentinel = RuntimeError("test client construction failed")
    storage = SimpleNamespace(close=lambda: events.append("storage"))
    service = SimpleNamespace(_storage=storage, close=lambda: events.append("service"))
    registry = SimpleNamespace(initialize=lambda **kwargs: failure != "initialize")
    app = SimpleNamespace(state=SimpleNamespace(pallium_service=service, codex_wake_registry=registry))
    turns = []

    def post(url, *, json):
        turns.append(json["session_ref"])
        refused = failure == "first_turn" or (failure == "second_turn" and len(turns) == 2)
        return SimpleNamespace(status_code=503 if refused else 200)

    http = SimpleNamespace(post=post, close=lambda: events.append("http"))

    def test_client(actual_app):
        assert actual_app is app
        if failure == "constructor":
            raise sentinel
        return http

    monkeypatch.setattr(health, "create_app", lambda config: app)
    monkeypatch.setattr(health, "TestClient", test_client)
    fixture = health.world.__wrapped__(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError if failure == "constructor" else AssertionError) as caught:
        next(fixture)
    if failure == "constructor":
        assert caught.value is sentinel
    assert turns == {"constructor": [], "initialize": [], "first_turn": ["sender"],
                     "second_turn": ["sender", "target"]}[failure]
    assert events == (["service", "storage"] if failure == "constructor" else ["http", "service", "storage"])


@pytest.mark.parametrize("fault", [
    "default", "complete", "excess", "overlap", "under-count", "active-exit",
    "late-entry", "original-base-exception", "body-base-exception",
])
def test_prerequisite_admission_audit(monkeypatch, fault):
    from contextlib import contextmanager, nullcontext
    from storage import sqlite_queue

    class Abort(BaseException):
        pass

    entered, exited = [], []

    class Store:
        @contextmanager
        def _begin_relay_immediate(self):
            entered.append(sqlite_queue.time.monotonic())
            try:
                if fault == "original-base-exception":
                    raise Abort()
                yield object()
            finally:
                exited.append(True)

    store = Store()
    if fault == "body-base-exception":
        store._begin_relay_immediate = store._begin_relay_immediate
    original_begin = store._begin_relay_immediate
    original_attributes = vars(store).copy()
    native_time = sqlite_queue.time
    scope = conftest.relay_admission_clock.__wrapped__(SimpleNamespace(param="semantic"), monkeypatch)
    expected = None if fault == "default" else 2 if fault in {"overlap", "under-count"} else 1
    failing = fault in {"excess", "overlap", "under-count", "active-exit"}
    outcome = (
        pytest.raises(Abort) if fault.endswith("base-exception") else
        pytest.raises(AssertionError, match="prerequisite admission audit failed") if failing else
        nullcontext()
    )
    held = None
    try:
        with outcome:
            with scope(store, expected_admissions=expected):
                policy_time = sqlite_queue.time
                cached = store._begin_relay_immediate
                if fault in {"overlap", "active-exit"}:
                    held = cached()
                    held.__enter__()
                    if fault == "overlap":
                        with pytest.raises(AssertionError, match="unexpected prerequisite writer"):
                            with cached():
                                pytest.fail("overlapping writer reached the original transaction")
                        held.__exit__(None, None, None)
                        held = None
                else:
                    with cached():
                        pass
                    if fault == "default":
                        with cached():
                            pass
                    elif fault == "excess":
                        with pytest.raises(AssertionError, match="unexpected prerequisite writer"):
                            with cached():
                                pytest.fail("excess writer reached the original transaction")
                    elif fault == "body-base-exception":
                        raise Abort()
    finally:
        if held is not None:
            held.__exit__(None, None, None)

    assert sqlite_queue.time is native_time
    assert store._begin_relay_immediate == original_begin
    if expected is not None:
        assert vars(store) == original_attributes
    assert len(entered) == len(exited) == (2 if fault == "default" else 1)
    assert entered == [0.0] * len(entered)
    before = native_time.monotonic()
    restored = policy_time.monotonic()
    assert before <= restored <= native_time.monotonic()
    if fault == "late-entry":
        with pytest.raises(AssertionError, match="unexpected prerequisite writer"):
            with cached():
                pytest.fail("closed cached writer reached the original transaction")
        assert len(entered) == len(exited) == 1
        assert vars(store) == original_attributes
