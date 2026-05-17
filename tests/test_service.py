"""Tests for app/cli/service.py — home resolution, lock, and CLI dispatch."""

from __future__ import annotations

import argparse
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
    _seed_config,
    _PalliumLock,
    _find_pallium_cmd,
    _start_windows,
    _cmd_restart,
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

    def test_default_is_dot_pallium(self, monkeypatch: pytest.MonkeyPatch):
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


class TestSeedConfig:
    def test_copies_env_file_when_toml_written(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """The .env file must be copied even when the toml config is successfully written."""
        home = tmp_path / "home"
        (home / "config").mkdir(parents=True)

        # Create a dev config with an LLM provider section
        dev_toml = tmp_path / "pallium.local.toml"
        dev_toml.write_text(
            "[llm_providers.test_provider]\n"
            'kind = "anthropic_claude"\n'
            'api_key_env = "TEST_KEY"\n'
        )

        # Create a dev env file with a secret
        dev_env = tmp_path / ".env.local"
        dev_env.write_text("TEST_KEY=secret123\n")

        monkeypatch.chdir(tmp_path)
        _seed_config(home)

        # Both files should exist
        assert (home / "config" / "pallium.toml").exists()
        assert (home / "config" / ".env").exists()
        assert "TEST_KEY=secret123" in (home / "config" / ".env").read_text()

    def test_skips_if_config_already_exists(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """If config already exists, don't overwrite it."""
        home = tmp_path / "home"
        (home / "config").mkdir(parents=True)
        (home / "config" / "pallium.toml").write_text("[existing]\n")

        dev_toml = tmp_path / "pallium.local.toml"
        dev_toml.write_text("[llm_providers.x]\nkind = \"test\"\n")

        monkeypatch.chdir(tmp_path)
        _seed_config(home)

        assert (home / "config" / "pallium.toml").read_text() == "[existing]\n"

    def test_filters_only_production_sections(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Only LLM providers and production packages are kept."""
        home = tmp_path / "home"
        (home / "config").mkdir(parents=True)

        dev_toml = tmp_path / "pallium.local.toml"
        dev_toml.write_text(
            "[llm_providers.my_llm]\n"
            'kind = "anthropic_claude"\n'
            "\n"
            "[semantic_packages.demo_agent_memory]\n"
            'implementation = "demo_agent_memory"\n'
            "\n"
            "[semantic_packages.agent_conversation_memory]\n"
            'implementation = "agent_conversation_memory"\n'
            'llm_provider = "my_llm"\n'
            "\n"
            "[semantic_packages.conversational_knowledge]\n"
            'implementation = "conversational_knowledge"\n'
            "\n"
            "[embedding_providers.onnx]\n"
            'kind = "onnx"\n'
        )

        monkeypatch.chdir(tmp_path)
        _seed_config(home)

        content = (home / "config" / "pallium.toml").read_text()
        assert "[llm_providers.my_llm]" in content
        assert "[semantic_packages.agent_conversation_memory]" in content
        assert "[semantic_packages.conversational_knowledge]" in content
        assert "[semantic_packages.demo_agent_memory]" not in content
        assert "[embedding_providers.onnx]" not in content

    def test_no_env_copy_when_env_already_exists(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Don't overwrite existing .env in service home."""
        home = tmp_path / "home"
        (home / "config").mkdir(parents=True)
        (home / "config" / ".env").write_text("EXISTING=yes\n")

        dev_toml = tmp_path / "pallium.local.toml"
        dev_toml.write_text("[llm_providers.x]\nkind = \"test\"\n")
        dev_env = tmp_path / ".env.local"
        dev_env.write_text("NEW_KEY=no\n")

        monkeypatch.chdir(tmp_path)
        _seed_config(home)

        assert (home / "config" / ".env").read_text() == "EXISTING=yes\n"

    def test_no_dev_env_file_does_not_crash(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """If no .env.local exists, seed_config still works (just no .env copy)."""
        home = tmp_path / "home"
        (home / "config").mkdir(parents=True)

        dev_toml = tmp_path / "pallium.local.toml"
        dev_toml.write_text("[llm_providers.x]\nkind = \"test\"\n")

        monkeypatch.chdir(tmp_path)
        _seed_config(home)

        assert (home / "config" / "pallium.toml").exists()
        assert not (home / "config" / ".env").exists()


class TestPalliumLockRetry:
    def test_acquire_retries_once_on_transient_failure(self, tmp_path: Path):
        """Lock acquisition retries once after 100ms on transient failure, then succeeds."""
        lock = _PalliumLock(tmp_path / "test.lock")

        call_count = [0]

        def mock_locking_win(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise OSError("transient lock failure")

        def mock_flock_linux(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise OSError("transient lock failure")

        with patch("time.sleep") as mock_sleep:
            if sys.platform == "win32":
                with patch("msvcrt.locking", side_effect=mock_locking_win):
                    result = lock.acquire()
            else:
                with patch("fcntl.flock", side_effect=mock_flock_linux):
                    result = lock.acquire()

        assert result is True
        mock_sleep.assert_called_once_with(0.1)

        if lock._fd is not None:
            lock.release()


class TestStartWindows:
    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_start_windows_raises_if_vbs_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """_start_windows raises RuntimeError when the VBS launcher does not exist."""
        monkeypatch.setenv("PALLIUM_HOME", str(tmp_path))
        (tmp_path / "run").mkdir(parents=True, exist_ok=True)

        with pytest.raises(RuntimeError, match="install"):
            _start_windows()

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_start_windows_launches_wscript_when_vbs_exists(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """_start_windows calls Popen with wscript.exe when VBS file is present."""
        monkeypatch.setenv("PALLIUM_HOME", str(tmp_path))
        run_dir = tmp_path / "run"
        run_dir.mkdir(parents=True, exist_ok=True)
        vbs_path = run_dir / "pallium_launcher.vbs"
        vbs_path.write_text("' stub\n", encoding="ascii")

        with patch("subprocess.Popen") as mock_popen:
            _start_windows()

        mock_popen.assert_called_once()
        call_args = mock_popen.call_args[0][0]
        assert call_args[0] == "wscript.exe"
        assert str(vbs_path) in call_args[1]


class TestCmdRestart:
    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only guard is Windows-specific")
    def test_cmd_restart_fails_before_stop_if_vbs_missing_on_windows(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """On Windows, _cmd_restart returns non-zero without calling _cmd_stop_impl when VBS missing."""
        monkeypatch.setenv("PALLIUM_HOME", str(tmp_path))
        (tmp_path / "run").mkdir(parents=True, exist_ok=True)

        args = argparse.Namespace(home=str(tmp_path))

        with patch("app.cli.service._cmd_stop_impl") as mock_stop:
            result = _cmd_restart(args)

        assert result != 0
        mock_stop.assert_not_called()
