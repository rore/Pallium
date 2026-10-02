from __future__ import annotations

from pathlib import Path
import sqlite3
from argparse import Namespace
from dataclasses import asdict
import json
import os
from unittest.mock import patch

import pytest

from app import run as run_module
from app.cli import service
from app.config import AppConfig
from app import codex_wake_lifecycle as lifecycle
from storage.sqlite import SQLiteStorageProvider
from core.relay import RelayService
from core.codex_wake import CodexWakeRegistry


@pytest.fixture
def lifecycle_config(tmp_path, monkeypatch):
    home = tmp_path / "home"
    config = AppConfig(sqlite_url=f"sqlite:///{home / 'data' / 'pallium.db'}",
                       relay_sqlite_url=f"sqlite:///{home / 'data' / 'pallium-relay.db'}")
    monkeypatch.setenv("PALLIUM_HOME", str(home))
    monkeypatch.delenv("PALLIUM_CODEX_WAKE_DIR", raising=False)
    monkeypatch.setattr(AppConfig, "from_env", staticmethod(lambda: config))
    with patch.dict(os.environ):
        yield config, home


def _marker(config):
    database = Path(config.resolved_relay_sqlite_url.removeprefix("sqlite:///"))
    with sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True) as connection:
        return connection.execute("SELECT generation FROM relay_codex_wake_state WHERE id=1").fetchone()


@pytest.mark.parametrize("mode", ["serve", "all"])
def test_fresh_foreground_initializes_before_native_start_without_installed_unit(lifecycle_config, monkeypatch, mode):
    config, _ = lifecycle_config
    calls = []

    def native(*args, **kwargs):
        assert _marker(config) == (0,)
        calls.append(mode)
        return 0

    monkeypatch.setattr(run_module.uvicorn, "run", native)
    monkeypatch.setattr(run_module, "run_supervisor", native)
    monkeypatch.setattr(service, "assert_service_stopped", lambda *a: pytest.fail("fresh install required service metadata"))
    assert run_module.run([mode]) == 0
    assert calls == [mode]


@pytest.mark.parametrize("mode", ["serve", "all"])
def test_competing_fresh_initializer_cannot_launch(lifecycle_config, monkeypatch, mode):
    _, home = lifecycle_config
    lock = service._PalliumLock(home / "run" / "pallium.lock")
    assert lock.acquire()
    monkeypatch.setattr(run_module.uvicorn, "run", lambda *a, **kw: pytest.fail("competing owner started API"))
    monkeypatch.setattr(run_module, "run_supervisor", lambda *a, **kw: pytest.fail("competing owner started supervisor"))
    try:
        assert run_module.run([mode]) == 1
    finally:
        lock.release()


@pytest.mark.parametrize("mode", ["serve", "all"])
def test_existing_unmarked_store_requires_offline_upgrade(lifecycle_config, monkeypatch, mode):
    config, home = lifecycle_config
    home.joinpath("data").mkdir(parents=True)
    with sqlite3.connect(home / "data" / "pallium-relay.db"):
        pass
    monkeypatch.setattr(run_module.uvicorn, "run", lambda *a, **kw: pytest.fail("unmigrated store started API"))
    monkeypatch.setattr(run_module, "run_supervisor", lambda *a, **kw: pytest.fail("unmigrated store started supervisor"))
    assert run_module.run([mode]) == 1


def test_fresh_service_run_initializes_under_existing_owner_lock_before_supervisor(lifecycle_config, monkeypatch):
    config, home = lifecycle_config
    monkeypatch.setattr("app.dependencies.build_semantic_plugins", lambda *a: {})
    monkeypatch.setattr(service, "_processor_count", lambda *a: 0)
    monkeypatch.setattr(service, "assert_service_stopped", lambda *a: pytest.fail("fresh service required installed unit"))

    def supervisor(*args, **kwargs):
        assert _marker(config) == (0,)
        contender = service._PalliumLock(home / "run" / "pallium.lock")
        assert not contender.acquire()
        return 0

    monkeypatch.setattr("app.supervisor.run_supervisor", supervisor)
    assert service._cmd_run(Namespace(home=str(home), port=19836)) == 0


def test_reinstall_refuses_unmigrated_store_before_replacing_old_metadata(lifecycle_config, monkeypatch):
    _, home = lifecycle_config
    (home / "data").mkdir(parents=True)
    (home / "data" / "pallium-relay.db").touch()
    launcher = home / "run" / "pallium_launcher.vbs"
    launcher.parent.mkdir()
    launcher.write_text("original launcher")
    monkeypatch.setattr(service, "_find_pallium_cmd", lambda: "pallium")
    monkeypatch.setattr(service, "_missing_declared_credentials", lambda *a: [])
    monkeypatch.setattr(service, "_install_windows", lambda *a: pytest.fail("old launcher replaced before import"))
    monkeypatch.setattr(service, "_install_linux", lambda *a: pytest.fail("old unit replaced before import"))
    monkeypatch.setattr("app.run._run_download_embedding_model", lambda: None)
    assert service._cmd_install(Namespace(home=str(home), port=19836)) == 1
    assert launcher.read_text() == "original launcher"


def test_offline_command_proves_stop_before_import_and_releases_lock(lifecycle_config, monkeypatch):
    config, home = lifecycle_config
    order = []
    original = lifecycle._initialize_and_verify
    monkeypatch.setattr(service, "assert_service_stopped", lambda actual_home: order.append("stopped"))

    def initialize(actual_config, legacy):
        order.append("initialize")
        contender = service._PalliumLock(home / "run" / "pallium.lock")
        assert not contender.acquire()
        original(actual_config, legacy)
        order.append("verified")

    monkeypatch.setattr(lifecycle, "_initialize_and_verify", initialize)
    assert service.service_main(["initialize-wakes", "--home", str(home)]) == 0
    assert order == ["stopped", "initialize", "verified"]
    assert _marker(config) == (0,)
    contender = service._PalliumLock(home / "run" / "pallium.lock")
    assert contender.acquire()
    contender.release()


def test_offline_failed_stop_proof_creates_no_database(lifecycle_config, monkeypatch):
    config, home = lifecycle_config
    monkeypatch.setattr(service, "assert_service_stopped", lambda *a: (_ for _ in ()).throw(RuntimeError("surviving old worker")))
    assert service.service_main(["initialize-wakes", "--home", str(home)]) == 1
    assert not Path(config.resolved_relay_sqlite_url.removeprefix("sqlite:///")).exists()


def test_completed_marker_child_needs_no_nested_owner_lock_or_legacy_read(lifecycle_config, monkeypatch):
    config, home = lifecycle_config
    lifecycle.prepare_codex_wake_start(config)
    legacy = home / "codex-wake" / "reservations.json"
    legacy.parent.mkdir()
    legacy.write_text("{", encoding="utf-8")
    owner = service._PalliumLock(home / "run" / "pallium.lock")
    assert owner.acquire()
    try:
        lifecycle.prepare_codex_wake_start(config)
    finally:
        owner.release()
    assert legacy.read_text() == "{"


def test_fresh_permission_error_is_not_absence(lifecycle_config, monkeypatch):
    config, _ = lifecycle_config
    original = Path.stat
    database = Path(config.resolved_relay_sqlite_url.removeprefix("sqlite:///"))

    def stat(path, *args, **kwargs):
        if path == database:
            raise PermissionError("injected metadata denial")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat)
    with pytest.raises(PermissionError):
        lifecycle.prepare_codex_wake_start(config)


def test_fresh_initializer_rechecks_under_lock(lifecycle_config, monkeypatch):
    config, _ = lifecycle_config
    original = service._PalliumLock.acquire
    database = Path(config.resolved_relay_sqlite_url.removeprefix("sqlite:///"))

    def acquire(lock):
        result = original(lock)
        database.parent.mkdir(parents=True, exist_ok=True)
        database.touch()
        return result

    monkeypatch.setattr(service._PalliumLock, "acquire", acquire)
    with pytest.raises(RuntimeError, match="appeared"):
        lifecycle.prepare_codex_wake_start(config)


def test_memory_and_non_sqlite_start_do_not_invent_file_paths(monkeypatch):
    monkeypatch.setattr(lifecycle, "_present", lambda *a: pytest.fail("memory/disabled configuration inspected file"))
    lifecycle.prepare_codex_wake_start(AppConfig(sqlite_url="sqlite:///:memory:"))
    lifecycle.prepare_codex_wake_start(AppConfig(storage_backend="unsupported"))


def test_invalid_mixed_memory_configuration_is_rejected_without_paths(monkeypatch):
    monkeypatch.setattr(lifecycle, "_present", lambda *a: pytest.fail("invalid mixed config inspected file"))
    with pytest.raises(ValueError):
        lifecycle.prepare_codex_wake_start(AppConfig(sqlite_url="sqlite:///:memory:", relay_sqlite_url="sqlite:///relay.db"))


@pytest.mark.parametrize("outcome", ["accepted", "uncertain"])
def test_foreground_offline_upgrade_preserves_legacy_fences(lifecycle_config, monkeypatch, outcome):
    config, home = lifecycle_config
    storage = SQLiteStorageProvider(config.sqlite_url, config.resolved_relay_sqlite_url)
    relay = RelayService(storage)
    scope = {"container_ref": "git:example.test/offline-upgrade"}
    for session in ("sender", "target"):
        relay.turn(runtime="codex", session_ref=session, **scope)
    delivery = relay.send(sender_runtime="codex", sender_session_ref="sender", recipient="codex:target",
                          payload="generic upgrade payload", **scope)["deliveries"][0]
    ephemeral = CodexWakeRegistry()
    fence = ephemeral.reserve(recipient_endpoint_id=delivery["recipient_endpoint_id"], delivery_id=delivery["delivery_id"],
                              session_ref="target", **scope)
    fence = ephemeral.begin_native_attempt(fence)
    assert fence is not None
    assert ephemeral.record_outcome(fence, outcome)
    fence = ephemeral.snapshot(fence.recipient_endpoint_id)
    legacy = home / "codex-wake" / "reservations.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"version": 2, "reservations": [asdict(fence)]}), encoding="utf-8")
    source = legacy.read_bytes()
    storage.close()
    monkeypatch.setattr(service, "assert_service_stopped", lambda *a: pytest.fail("foreground operator requested installed-unit proof"))
    assert service.service_main(["initialize-wakes", "--home", str(home), "--foreground-quiescent"]) == 0
    reopened = SQLiteStorageProvider(config.sqlite_url, config.resolved_relay_sqlite_url)
    try:
        registry = CodexWakeRegistry(relay_service=RelayService(reopened), legacy_state_dir=legacy.parent)
        assert registry.reservations() == (fence,)
        assert legacy.read_bytes() == source
    finally:
        reopened.close()


def test_unreadable_marker_schema_refuses_start_with_controlled_error(lifecycle_config):
    config, home = lifecycle_config
    (home / "data").mkdir(parents=True)
    with sqlite3.connect(home / "data" / "pallium-relay.db") as connection:
        connection.execute("CREATE TABLE relay_codex_wake_state(id INTEGER)")
    with pytest.raises(RuntimeError, match="inspect"):
        lifecycle.prepare_codex_wake_start(config)


def test_fresh_initialization_failure_leaves_marker_absent_and_refuses_native_start(lifecycle_config, monkeypatch):
    config, _ = lifecycle_config

    def fail_before_import(*args, **kwargs):
        raise RuntimeError("injected initialization failure")

    with monkeypatch.context() as fault:
        fault.setattr(SQLiteStorageProvider, "relay_codex_wake_initialize", fail_before_import)
        fault.setattr(run_module.uvicorn, "run", lambda *a, **kw: pytest.fail("failed initialization started API"))
        assert run_module.run(["serve"]) == 1
    assert not lifecycle._marker_present(Path(config.resolved_relay_sqlite_url.removeprefix("sqlite:///")))
    with pytest.raises(RuntimeError, match="offline"):
        lifecycle.prepare_codex_wake_start(config)
