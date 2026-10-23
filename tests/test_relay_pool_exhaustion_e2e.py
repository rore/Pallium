"""Finite native pool admission through the public Relay HTTP surface."""
from contextlib import ExitStack
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from api.routes import create_router
from core.relay import RelayService
from storage.sqlite import SQLiteStorageProvider


SCOPE = {"container_ref": "git:example.test/team/pool", "runtime": "hermes"}


@pytest.fixture(params=["split", "colocated"])
def pool_api(request, client, tmp_path):
    directory = tmp_path / "mémoire-漢"
    directory.mkdir()
    main = f"sqlite:///{directory / 'main.db'}"
    relay = f"sqlite:///{directory / 'relay.db'}" if request.param == "split" else None
    storage = SQLiteStorageProvider(main, relay_database_url=relay)
    # Co-located storage is supported by the reusable provider, not AppConfig.
    app = FastAPI()
    app.include_router(create_router(
        client.app.state.pallium_service, relay_service=RelayService(storage),
    ))
    http = TestClient(app, raise_server_exceptions=False)
    try:
        yield http, storage
    finally:
        http.close()
        storage.close()


def turn(http, session):
    return http.post("/relay/turn", json={**SCOPE, "session_ref": session})


def sessions(http):
    response = http.get("/relay/sessions", params={**SCOPE, "include_inactive": True})
    assert response.status_code == 200, response.text
    return {row["session_ref"] for row in response.json()}


def hold(pool_engine, count):
    handles = ExitStack()
    try:
        for _ in range(count):
            handles.enter_context(pool_engine.connect())
    except BaseException:
        handles.close()
        raise
    return handles


def exhausted_and_recovered(http, storage, cycles):
    pool = storage._relay_engine.pool
    capacity = pool.size() + pool._max_overflow
    assert capacity == 15 and pool.timeout() == 0
    expected = {"baseline-café漢"}
    assert turn(http, next(iter(expected))).status_code == 200
    for cycle in range(cycles):
        with hold(storage._relay_engine, capacity):
            assert pool.checkedout() == capacity
            started = time.monotonic()
            refused = turn(http, f"refused-{cycle}")
            assert time.monotonic() - started < 2
            assert refused.status_code == 503, refused.text
            assert refused.json() == {"detail": {"code": "relay_busy", "retryable": True}}
            assert refused.headers["Retry-After"] == "1"
            read = http.get("/relay/sessions", params=SCOPE)
            assert read.status_code == 503 and read.headers["Retry-After"] == "1"
            assert not storage._relay_writer_lock.locked()
            assert pool.checkedout() == capacity
            invalid = http.post("/relay/turn", json={**SCOPE, "runtime": "invalid", "session_ref": "bad"})
            assert invalid.status_code == 422
        assert pool.checkedout() == 0
        assert sessions(http) == expected
        recovered = f"recovered-{cycle}"
        assert turn(http, recovered).status_code == 200
        expected.add(recovered)
        assert sessions(http) == expected
    assert pool.checkedout() == 0 and not storage._relay_writer_lock.locked()


def test_native_full_pool_refuses_then_recovers_three_times(pool_api):
    exhausted_and_recovered(*pool_api, cycles=3)


def test_production_app_pool_refusal_and_recovery(client):
    storage = client.app.state.pallium_service._storage
    exhausted_and_recovered(client, storage, cycles=1)


@pytest.mark.parametrize("occupied", [0, 14])
def test_empty_and_near_full_pool_accepts_turn(pool_api, occupied):
    http, storage = pool_api
    with hold(storage._relay_engine, occupied):
        response = turn(http, "accepted-café漢")
        assert response.status_code == 200, response.text
        assert storage._relay_engine.pool.checkedout() == occupied
    assert sessions(http) == {"accepted-café漢"}
    assert storage._relay_engine.pool.checkedout() == 0


def test_main_pool_policy_and_occupancy_do_not_block_relay(pool_api):
    http, storage = pool_api
    assert storage._engine.pool.timeout() == 30
    assert storage._relay_engine.pool.timeout() == 0
    assert storage._engine is not storage._relay_engine
    with hold(storage._engine, 15):
        assert turn(http, "independent").status_code == 200
        assert sessions(http) == {"independent"}
        assert storage._engine.pool.checkedout() == 15
    assert storage._engine.pool.checkedout() == 0


@pytest.mark.parametrize("failure", [
    SQLAlchemyTimeoutError("unrelated timeout", code="other"),
    RuntimeError("unrelated connection failure"),
])
def test_unrelated_connection_failures_are_not_busy_responses(pool_api, monkeypatch, failure):
    http, storage = pool_api
    pool = storage._relay_engine.pool
    pool.dispose()

    def fail():
        raise failure

    with monkeypatch.context() as patch:
        patch.setattr(pool, "_creator", fail)
        response = turn(http, "failed")
        assert response.status_code == 500
        assert "Retry-After" not in response.headers
        assert not storage._relay_writer_lock.locked()
        assert pool.checkedout() == 0
    assert sessions(http) == set()
    assert turn(http, "recovered").status_code == 200
    assert sessions(http) == {"recovered"}
