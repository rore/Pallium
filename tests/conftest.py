from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from itertools import count
import os
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.config import AppConfig, SemanticPackageConfig
from app.main import create_app
from tests.config_helpers import DEMO_SEMANTIC_PACKAGES


@pytest.fixture()
def test_db_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'test.db'}"


@pytest.fixture()
def client(test_db_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    from app import main as app_main

    monkeypatch.setattr("app.dependencies.schedule_codex_relay_wake", lambda *_args, **_kwargs: None)
    from storage.vector_index import VectorIndexConfig
    from storage.sqlite import SQLiteStorageProvider
    storages = []
    original_storage = app_main.build_storage_provider

    def owned_storage(*args, **kwargs):
        storage = original_storage(*args, **kwargs)
        storages.append(storage)
        return storage

    # Capture early metrics storage without starting the application's lifespan.
    with monkeypatch.context() as construction:
        construction.setattr(app_main, "build_storage_provider", owned_storage)
        app = create_app(
            AppConfig(
                storage_backend="sqlite",
                sqlite_url=test_db_url,
                default_use_case="demo_agent_memory",
                semantic_packages=DEMO_SEMANTIC_PACKAGES,
                vector_index=VectorIndexConfig(enabled=False),
            )
        )
    service = app.state.pallium_service
    if os.environ.get("GITHUB_ACTIONS") == "true" and isinstance(service._storage, SQLiteStorageProvider):
        from tests.codex_wake_setup import observe_relay_acquisition_failures
        observe_relay_acquisition_failures(service._storage, monkeypatch)
    if all(storage is not service._storage for storage in storages):
        storages.append(service._storage)
    http = TestClient(app)
    with ExitStack() as cleanup:
        for storage in reversed(storages):
            cleanup.callback(storage.close)
        cleanup.callback(service.close)
        trace_writer = getattr(app.state, "relay_trace_writer", None)
        if trace_writer is not None:
            cleanup.callback(trace_writer.close)
        cleanup.callback(app.state._wait_for_operations)
        cleanup.callback(http.close)
        yield http


@pytest.fixture()
def drain_queue():
    def _drain(client: TestClient, **kwargs):
        return client.app.state.pallium_service.drain_processing_queue(worker_id="test-worker", **kwargs)

    return _drain

@pytest.fixture()
def relay_admission_clock(request, monkeypatch):
    """Model explicit prerequisites; optionally audit their known admission count."""
    from storage import sqlite_queue

    native_time = sqlite_queue.time
    owner = threading.get_ident()
    active = False

    @contextmanager
    def admission_scope(storage, *, expected_admissions=None):
        nonlocal active
        assert threading.get_ident() == owner
        assert not active, "semantic admission scopes must not overlap"
        assert sqlite_queue.time is native_time
        if request.param == "native":
            assert expected_admissions is None
            yield
            assert sqlite_queue.time is native_time
            return
        assert request.param == "semantic"
        guarded = expected_admissions is not None
        if guarded:
            assert type(expected_admissions) is int and expected_admissions > 0
        audit_lock = threading.Lock()
        started = inflight = 0
        violation = closed = False
        local = threading.local()
        policy_time = SimpleNamespace(**vars(native_time))

        def monotonic():
            clock = getattr(local, "clock", None)
            return clock() if clock is not None else native_time.monotonic()

        policy_time.monotonic = monotonic
        original_begin = storage._begin_relay_immediate
        missing = object()
        original_attribute = vars(storage).get("_begin_relay_immediate", missing) if guarded else missing

        @contextmanager
        def begin():
            nonlocal started, inflight, violation
            if guarded:
                with audit_lock:
                    if closed or inflight or started >= expected_admissions:
                        violation = True
                        raise AssertionError("unexpected prerequisite writer")
                    started += 1
                    inflight += 1
            previous = getattr(local, "clock", None)
            local.clock = count(step=.001).__next__
            try:
                # Enter before the original creates its deadline; native IO still runs.
                with original_begin() as session:
                    yield session
            finally:
                local.clock = previous
                if guarded:
                    with audit_lock:
                        inflight -= 1

        active = True
        try:
            with monkeypatch.context() as policy:
                policy.setattr(sqlite_queue, "time", policy_time)
                policy.setattr(storage, "_begin_relay_immediate", begin)
                try:
                    yield
                    assert sqlite_queue.time is policy_time
                    if guarded:
                        assert storage._begin_relay_immediate is begin
                finally:
                    if guarded:
                        with audit_lock:
                            closed = True
        finally:
            active = False
            if guarded:
                with audit_lock:
                    closed = True
                if original_attribute is missing:
                    vars(storage).pop("_begin_relay_immediate", None)
                else:
                    storage._begin_relay_immediate = original_attribute
                assert sqlite_queue.time is native_time
                assert vars(storage).get("_begin_relay_immediate", missing) is original_attribute
                assert storage._begin_relay_immediate == original_begin
                with audit_lock:
                    assert not violation and not inflight and started == expected_admissions, (
                        "prerequisite admission audit failed"
                    )
        assert sqlite_queue.time is native_time

    return admission_scope


@pytest.fixture(autouse=True)
def isolated_claude_wake_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """Keep trusted-local capability tests out of the developer profile."""
    from app import codex_wake

    # Clock mocks must not disable SQLite backoff or unrelated worker timing.
    monkeypatch.setattr(codex_wake, "time", SimpleNamespace(**vars(time)))
    if request.node.path.name.startswith("test_claude_"):
        monkeypatch.setenv("PALLIUM_CLAUDE_WAKE_DIR", str(tmp_path / "claude-wake"))
    else:
        monkeypatch.delenv("PALLIUM_CLAUDE_WAKE_DIR", raising=False)
    monkeypatch.setenv("PALLIUM_CODEX_WAKE_DIR", str(tmp_path / "codex-wake"))
    monkeypatch.delenv("PALLIUM_HOOK_ACTOR_REF", raising=False)
