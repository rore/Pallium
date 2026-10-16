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
