"""Tests for SQLite snapshot persistence."""
from __future__ import annotations

from pathlib import Path

from app.config import AppConfig, SnapshotConfig


# === Tier 6: Config tests ===

def test_config_snapshot_defaults() -> None:
    config = AppConfig()
    assert config.snapshot.enabled is False
    assert config.snapshot.snapshot_path is None
    assert config.snapshot.interval_seconds == 60
    assert config.snapshot.max_snapshots == 5


def test_config_snapshot_from_toml(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "pallium.local.toml"
    config_file.write_text(
        """
[snapshot]
enabled = true
snapshot_path = "/mnt/durable/snapshots"
interval_seconds = 30
max_snapshots = 10
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("PALLIUM_CONFIG_FILE", str(config_file))
    config = AppConfig.from_env()
    assert config.snapshot.enabled is True
    assert config.snapshot.snapshot_path == "/mnt/durable/snapshots"
    assert config.snapshot.interval_seconds == 30
    assert config.snapshot.max_snapshots == 10


def test_config_snapshot_from_env(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "pallium.local.toml"
    config_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("PALLIUM_CONFIG_FILE", str(config_file))
    monkeypatch.setenv("PALLIUM_SNAPSHOT_ENABLED", "true")
    monkeypatch.setenv("PALLIUM_SNAPSHOT_PATH", "/env/snapshots")
    monkeypatch.setenv("PALLIUM_SNAPSHOT_INTERVAL_SECONDS", "15")
    monkeypatch.setenv("PALLIUM_SNAPSHOT_MAX_SNAPSHOTS", "3")
    config = AppConfig.from_env()
    assert config.snapshot.enabled is True
    assert config.snapshot.snapshot_path == "/env/snapshots"
    assert config.snapshot.interval_seconds == 15
    assert config.snapshot.max_snapshots == 3


def test_config_snapshot_env_overrides_toml(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "pallium.local.toml"
    config_file.write_text(
        """
[snapshot]
enabled = false
snapshot_path = "/toml/path"
interval_seconds = 120
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("PALLIUM_CONFIG_FILE", str(config_file))
    monkeypatch.setenv("PALLIUM_SNAPSHOT_ENABLED", "true")
    monkeypatch.setenv("PALLIUM_SNAPSHOT_PATH", "/env/path")
    config = AppConfig.from_env()
    assert config.snapshot.enabled is True
    assert config.snapshot.snapshot_path == "/env/path"
    assert config.snapshot.interval_seconds == 120  # TOML value kept (no env override)
