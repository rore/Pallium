from types import SimpleNamespace

import pytest

from app import main as app_main
from tests import conftest


@pytest.mark.parametrize(
    "failure", [None, "http", "wait", "service", "early_storage", "service_storage", "all"]
)
def test_client_fixture_attempts_all_cleanup_in_order(monkeypatch, failure):
    order = ["http", "wait", "service", "early_storage", "service_storage"]
    events = []

    def cleanup(name):
        def close():
            events.append(name)
            if failure in (name, "all"):
                raise RuntimeError(f"failed:{name}")

        return close

    early_storage = SimpleNamespace(close=cleanup("early_storage"))
    service_storage = SimpleNamespace(close=cleanup("service_storage"))
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
        last_failure = "service_storage" if failure == "all" else failure
        with pytest.raises(RuntimeError, match=f"^failed:{last_failure}$"):
            next(fixture)
    assert events == order
