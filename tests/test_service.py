"""Tests for app/cli/service.py — home resolution, lock, and CLI dispatch."""

from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from app.cli.service import (
    _pallium_home,
    _apply_home_env,
    _ensure_dirs,
    _PalliumLock,
    _find_pallium_cmd,
    service_main,
)


class TestPalliumHome:
    def test_explicit_override(self, tmp_path: Path):
        result = _pallium_home(str(tmp_path / "custom"))
        assert result == tmp_path / "custom"

    def test_env_var_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("PALLIUM_HOME", str(tmp_path / "from-env"))
        result = _pallium_home()
        assert result == tmp_path / "from-env"

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific")
    def test_windows_default(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("PALLIUM_HOME", raising=False)
        monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\Test\AppData\Local")
        result = _pallium_home()
        assert result == Path(r"C:\Users\Test\AppData\Local\Pallium")

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX-specific")
    def test_linux_default(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("PALLIUM_HOME", raising=False)
        result = _pallium_home()
        assert result == Path.home() / ".pallium"


class TestApplyHomeEnv:
    @pytest.fixture(autouse=True)
    def _clean_pallium_env(self, monkeypatch: pytest.MonkeyPatch):
        """Ensure PALLIUM env vars are cleaned after each test."""
        yield
        for key in ("PALLIUM_SQLITE_URL", "PALLIUM_VECTOR_INDEX_PATH",
                    "PALLIUM_CONFIG_FILE", "PALLIUM_ENV_FILE"):
            os.environ.pop(key, None)

    def test_sets_sqlite_and_vector_paths(self, tmp_path: Path):
        os.environ.pop("PALLIUM_SQLITE_URL", None)
        os.environ.pop("PALLIUM_VECTOR_INDEX_PATH", None)
        os.environ.pop("PALLIUM_CONFIG_FILE", None)
        os.environ.pop("PALLIUM_ENV_FILE", None)

        _apply_home_env(tmp_path)

        expected_url = f"sqlite:///{tmp_path / 'data' / 'pallium.db'}"
        expected_vector = str(tmp_path / "data" / "vector_index")
        assert os.environ.get("PALLIUM_SQLITE_URL") == expected_url
        assert os.environ.get("PALLIUM_VECTOR_INDEX_PATH") == expected_vector

    def test_does_not_overwrite_existing(self, tmp_path: Path):
        os.environ["PALLIUM_SQLITE_URL"] = "sqlite:///custom.db"
        os.environ["PALLIUM_VECTOR_INDEX_PATH"] = "/existing/path"
        os.environ.pop("PALLIUM_CONFIG_FILE", None)
        os.environ.pop("PALLIUM_ENV_FILE", None)

        _apply_home_env(tmp_path)
        assert os.environ["PALLIUM_SQLITE_URL"] == "sqlite:///custom.db"
        assert os.environ["PALLIUM_VECTOR_INDEX_PATH"] == "/existing/path"

    def test_config_file_not_set_when_missing(self, tmp_path: Path):
        os.environ.pop("PALLIUM_CONFIG_FILE", None)
        os.environ.pop("PALLIUM_SQLITE_URL", None)
        os.environ.pop("PALLIUM_VECTOR_INDEX_PATH", None)
        os.environ.pop("PALLIUM_ENV_FILE", None)

        _apply_home_env(tmp_path)
        assert "PALLIUM_CONFIG_FILE" not in os.environ

    def test_config_file_set_when_exists(self, tmp_path: Path):
        os.environ.pop("PALLIUM_CONFIG_FILE", None)
        os.environ.pop("PALLIUM_SQLITE_URL", None)
        os.environ.pop("PALLIUM_VECTOR_INDEX_PATH", None)
        os.environ.pop("PALLIUM_ENV_FILE", None)

        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "pallium.toml").write_text("[test]\n")

        _apply_home_env(tmp_path)
        assert os.environ["PALLIUM_CONFIG_FILE"] == str(tmp_path / "config" / "pallium.toml")


class TestEnsureDirs:
    def test_creates_subdirs(self, tmp_path: Path):
        home = tmp_path / "pallium-test"
        _ensure_dirs(home)
        assert (home / "data").is_dir()
        assert (home / "logs").is_dir()
        assert (home / "run").is_dir()
        assert (home / "config").is_dir()

    def test_idempotent(self, tmp_path: Path):
        home = tmp_path / "pallium-test"
        _ensure_dirs(home)
        _ensure_dirs(home)
        assert (home / "data").is_dir()


class TestPalliumLock:
    def test_acquire_and_release(self, tmp_path: Path):
        lock = _PalliumLock(tmp_path / "test.lock")
        assert lock.acquire()
        lock.release()

    def test_double_acquire_fails(self, tmp_path: Path):
        lock_file = tmp_path / "test.lock"
        lock1 = _PalliumLock(lock_file)
        assert lock1.acquire()

        lock2 = _PalliumLock(lock_file)
        assert not lock2.acquire()

        lock1.release()

    def test_acquire_after_release(self, tmp_path: Path):
        lock_file = tmp_path / "test.lock"
        lock1 = _PalliumLock(lock_file)
        assert lock1.acquire()
        lock1.release()

        lock2 = _PalliumLock(lock_file)
        assert lock2.acquire()
        lock2.release()


class TestServiceMain:
    def test_no_action_prints_help(self, capsys: pytest.CaptureFixture):
        result = service_main([])
        assert result == 1

    def test_status_with_no_running_instance(self, tmp_path: Path):
        result = service_main(["status", "--home", str(tmp_path)])
        assert result == 1

    def test_stop_with_no_running_instance(self, tmp_path: Path, capsys: pytest.CaptureFixture):
        (tmp_path / "run").mkdir(parents=True)
        result = service_main(["stop", "--home", str(tmp_path)])
        assert result == 0
        captured = capsys.readouterr()
        assert "not running" in captured.out
