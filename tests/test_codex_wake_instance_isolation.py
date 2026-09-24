from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app import codex_wake, main
from app.config import AppConfig
from core.codex_wake import CodexWakeRegistry
from storage.vector_index import VectorIndexConfig
from tests.config_helpers import DEMO_SEMANTIC_PACKAGES


def _config(database: Path) -> AppConfig:
    return AppConfig(
        storage_backend="sqlite",
        sqlite_url=f"sqlite:///{database}",
        default_use_case="demo_agent_memory",
        semantic_packages=DEMO_SEMANTIC_PACKAGES,
        vector_index=VectorIndexConfig(enabled=False),
    )


def test_codex_wake_directory_tracks_relay_database_not_inherited_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PALLIUM_CODEX_WAKE_DIR")
    monkeypatch.setenv("PALLIUM_HOME", str(tmp_path / "unrelated"))
    standard = tmp_path / "installed" / "data" / "pallium-relay.db"
    custom = tmp_path / "isolated-λ" / "relay.db"

    standard_registry = codex_wake.get_codex_wake_registry_for_relay_database(
        f"sqlite:///{standard}"
    )
    custom_registry = codex_wake.get_codex_wake_registry_for_relay_database(
        f"sqlite:///{custom}"
    )
    assert standard_registry._path == standard.parent.parent / "codex-wake" / "reservations.json"
    assert custom_registry._path == custom.parent / "relay.db-codex-wake" / "reservations.json"
    assert standard_registry is not custom_registry
    other_extension = custom.with_suffix(".sqlite")
    other_registry = codex_wake.get_codex_wake_registry_for_relay_database(
        f"sqlite:///{other_extension}"
    )
    assert other_registry._path == custom.parent / "relay.sqlite-codex-wake" / "reservations.json"
    assert other_registry._path != custom_registry._path

    override = tmp_path / "explicit"
    monkeypatch.setenv("PALLIUM_CODEX_WAKE_DIR", str(override))
    explicit = codex_wake.get_codex_wake_registry_for_relay_database(f"sqlite:///{custom}")
    assert explicit._path == override / "reservations.json"


def test_in_memory_relay_gets_app_local_nonpersistent_wake_registries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PALLIUM_CODEX_WAKE_DIR")
    first = codex_wake.get_codex_wake_registry_for_relay_database("sqlite:///:memory:")
    second = codex_wake.get_codex_wake_registry_for_relay_database("sqlite:///:memory:")
    assert first is not second
    assert first._path is None and second._path is None


def test_isolated_app_startup_does_not_reconcile_another_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PALLIUM_CODEX_WAKE_DIR")
    app = main.create_app(_config(tmp_path / "isolated" / "memory.db"))
    isolated_path = app.state.codex_wake_registry._path
    assert isolated_path == tmp_path / "isolated" / "memory-relay.db-codex-wake" / "reservations.json"

    legacy_dir = tmp_path / "legacy-codex-wake"
    foreign = CodexWakeRegistry(legacy_dir)
    reservation = foreign.reserve(
        recipient_endpoint_id="relay-session-" + "a" * 32,
        delivery_id="relay-delivery-" + "b" * 32,
        session_ref="other-agent",
        container_ref="git:example.test/other",
    )
    assert reservation is not None
    before = (legacy_dir / "reservations.json").read_bytes()
    monkeypatch.setenv("PALLIUM_CODEX_WAKE_DIR", str(legacy_dir))

    class ImmediateReconciler:
        def signal(self) -> None:
            pass

        def stop(self) -> None:
            pass

    def start_reconciler(_registry, _relay_service, *, claim_recovery, **_kwargs):
        claim_recovery()
        return ImmediateReconciler()

    monkeypatch.setattr(main, "start_claude_wake_reconciler", start_reconciler)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200

    assert (legacy_dir / "reservations.json").read_bytes() == before
    assert CodexWakeRegistry(legacy_dir).reservations() == (reservation,)


def test_schedule_keys_are_isolated_by_registry(tmp_path: Path) -> None:
    first = CodexWakeRegistry(tmp_path / "first")
    second = CodexWakeRegistry(tmp_path / "second")
    reservations = []
    for registry, digit in ((first, "1"), (second, "2")):
        reservation = registry.reserve(
            recipient_endpoint_id="relay-session-" + digit * 32,
            delivery_id="relay-delivery-" + digit * 32,
            session_ref="same-session",
            container_ref="git:example.test/same",
        )
        assert reservation is not None
        reservations.append(reservation)
    keys = [
        (id(registry), reservation.session_ref, reservation.container_ref)
        for registry, reservation in zip((first, second), reservations, strict=True)
    ]
    assert keys[0] != keys[1]
    for key, reservation in zip(keys, reservations, strict=True):
        codex_wake._scheduled_session_generations[key] = reservation.generation
    codex_wake._clear_schedule(reservations[0], first)
    assert keys[0] not in codex_wake._scheduled_session_generations
    assert codex_wake._scheduled_session_generations[keys[1]] == reservations[1].generation
    codex_wake._clear_schedule(reservations[1], second)