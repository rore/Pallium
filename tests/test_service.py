"""Tests for app/cli/service.py — home resolution, lock, and CLI dispatch."""

from __future__ import annotations

import argparse
import os
import sys
import subprocess
from types import SimpleNamespace
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
    _missing_declared_credentials,
    _processor_count,
    _start_windows,
    _cmd_restart,
    _cmd_status,
    _cmd_stop,
    _install_linux,
    _remove_service_data,
    _systemctl,
    _wait_for_service,
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


class TestDeclaredCredentialPreflight:
    def test_reports_only_declared_missing_credentials(self):
        config = SimpleNamespace(
            semantic_packages={
                "memory": SimpleNamespace(
                    enabled=True,
                    implementation="agent_conversation_memory",
                    llm_provider="remote",
                ),
                "demo": SimpleNamespace(
                    enabled=True,
                    implementation="demo_agent_memory",
                    llm_provider=None,
                ),
            },
            llm_providers={
                "remote": SimpleNamespace(
                    api_key=None,
                    api_key_env="PALLIUM_REMOTE_KEY",
                    api_key_file=None,
                )
            },
        )
        assert _missing_declared_credentials(config) == ["PALLIUM_REMOTE_KEY"]
        assert _processor_count(config) == 0
        config.llm_providers["remote"].api_key = "configured"
        assert _missing_declared_credentials(config) == []
        assert _processor_count(config) == 1


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

    def test_stop_with_no_running_instance(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ):
        (tmp_path / "run").mkdir(parents=True)
        if sys.platform == "linux":
            monkeypatch.setattr("app.cli.service._assert_linux_unit_home", lambda _home: None)
            monkeypatch.setattr(
                "app.cli.service._linux_unit_state",
                lambda: {"LoadState": "not-found", "ActiveState": "inactive"},
            )
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
        dev_env = tmp_path / ".env.local"
        dev_env.write_text("TEST_KEY=secret123\n")

        monkeypatch.chdir(tmp_path)
        _seed_config(home)

        assert (home / "config" / "pallium.toml").read_text() == "[existing]\n"
        assert (home / "config" / ".env").read_text() == "TEST_KEY=secret123\n"

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

    def test_dev_observability_values_not_carried_into_fresh_install(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """A dev [observability] section must NOT be copied verbatim: dev-only
        values (e.g. query_audit_log = true, shadow-selector flags) must not leak
        into a fresh install. The install seeds only the clean armed funnel."""
        home = tmp_path / "home"
        (home / "config").mkdir(parents=True)

        dev_toml = tmp_path / "pallium.local.toml"
        dev_toml.write_text(
            "[llm_providers.my_llm]\n"
            'kind = "anthropic_claude"\n'
            "\n"
            "[observability]\n"
            "query_audit_log = true\n"
            "shadow_subtask_selector_enabled = true\n"
            "historical_lookup_funnel = false\n"
        )

        monkeypatch.chdir(tmp_path)
        _seed_config(home)

        content = (home / "config" / "pallium.toml").read_text()
        import tomllib

        parsed = tomllib.loads(content)
        obs = parsed["observability"]
        # Only the clean armed signal — no dev carry-over.
        assert obs == {"historical_lookup_funnel": True}
        assert "query_audit_log" not in content
        assert "shadow_subtask_selector_enabled" not in content

    def test_seeds_armed_observability_when_absent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """When the dev config has no [observability] section, a fresh install
        seeds one that arms the funnel."""
        home = tmp_path / "home"
        (home / "config").mkdir(parents=True)

        dev_toml = tmp_path / "pallium.local.toml"
        dev_toml.write_text("[llm_providers.x]\nkind = \"test\"\n")

        monkeypatch.chdir(tmp_path)
        _seed_config(home)

        content = (home / "config" / "pallium.toml").read_text()
        assert "[observability]" in content
        assert "historical_lookup_funnel = true" in content
        # The seeded config must parse and resolve to armed=True.
        import tomllib

        parsed = tomllib.loads(content)
        assert parsed["observability"]["historical_lookup_funnel"] is True


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

        assert lock._fd is not None, "fd must be captured on successful second attempt"
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

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    @pytest.mark.parametrize("home_name", [None, "custom", "home with spaces", "בית עם רווחים"])
    def test_install_carries_exact_home_in_unicode_launcher(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        home_name: str | None,
    ):
        profile = tmp_path / "profile"
        monkeypatch.setattr(Path, "home", lambda: profile)
        expected_home = profile / ".pallium" if home_name is None else tmp_path / home_name
        python_exe = tmp_path / "פייתון with spaces" / "python.exe"
        monkeypatch.setattr(sys, "executable", str(python_exe))
        monkeypatch.setattr("app.cli.service._find_pallium_cmd", lambda: "pallium")
        monkeypatch.setattr("app.cli.service._seed_config", lambda _home: None)
        monkeypatch.setattr("app.cli.service._apply_home_env", lambda _home: None)
        monkeypatch.setattr("app.cli.service._missing_declared_credentials", lambda _config: [])
        monkeypatch.setattr("app.config.AppConfig.from_env", lambda: object())
        monkeypatch.setattr("app.run._run_download_embedding_model", lambda: None)
        monkeypatch.setattr("app.cli.service._service_ready", lambda _port: True)
        monkeypatch.setattr("app.cli.service.time.sleep", lambda _seconds: None)

        task_xml: list[str] = []

        def fake_run(argv, **_kwargs):
            task_xml.append(Path(argv[5]).read_text(encoding="utf-16"))
            return subprocess.CompletedProcess(argv, 0, "", "")

        monkeypatch.setattr("app.cli.service.subprocess.run", fake_run)
        popen_calls: list[list[str]] = []
        monkeypatch.setattr(
            "app.cli.service.subprocess.Popen",
            lambda argv, **_kwargs: popen_calls.append(argv),
        )

        args = ["install", "--port", "21987"]
        if home_name is not None:
            args.extend(["--home", str(expected_home)])
        assert service_main(args) == 0

        expected_home = expected_home.resolve()
        vbs_path = expected_home / "run" / "pallium_launcher.vbs"
        raw = vbs_path.read_bytes()
        assert raw.startswith(b"\xff\xfe")
        assert vbs_path.read_text(encoding="utf-16") == (
            'Set WshShell = CreateObject("WScript.Shell")\n'
            f'WshShell.Run """{python_exe}"" -m app.run service run --port 21987 '
            f'--home ""{expected_home}""", 0, False\n'
        )
        assert len(task_xml) == 1
        assert f'<Arguments>"{vbs_path}"</Arguments>' in task_xml[0]
        assert popen_calls == [["wscript.exe", str(vbs_path)]]

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_run_uses_explicit_unicode_home_for_runtime_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        home = (tmp_path / "שירות with spaces").resolve()
        config = SimpleNamespace(
            semantic_packages={},
            llm_providers={},
            default_use_case="test",
            embedding_providers={},
        )
        monkeypatch.setattr("app.config.AppConfig.from_env", lambda: config)
        monkeypatch.setattr("app.dependencies.build_semantic_plugins", lambda _config: {})
        monkeypatch.setattr("app.runtime_logging.configure_file_logging", lambda _path: None)
        monkeypatch.setattr("app.runtime_logging.emit_runtime_log", lambda *_args: None)

        observed: dict[str, Path] = {}

        def fake_supervisor(_args, *, log_file, log_stream):
            assert log_stream is None
            observed["log_file"] = log_file
            assert (home / "run" / "pallium.pid").read_text() == str(os.getpid())
            assert (home / "run" / "port").read_text() == "21987"
            return 0

        monkeypatch.setattr("app.supervisor.run_supervisor", fake_supervisor)

        with patch.dict(os.environ):
            assert service_main(["run", "--port", "21987", "--home", str(home)]) == 0
        assert observed == {"log_file": home / "logs" / "pallium.log"}
        assert not (home / "run" / "pallium.pid").exists()
        assert (home / "run" / "port").read_text() == "21987"

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


class TestLinuxServiceLifecycle:
    @pytest.fixture(autouse=True)
    def _linux_only(self):
        if sys.platform != "linux":
            pytest.skip("Linux-only")

    def test_systemctl_failure_is_actionable(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            "app.cli.service.subprocess.run",
            lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", "user bus unavailable"),
        )
        with pytest.raises(RuntimeError, match="user bus unavailable"):
            _systemctl("start", "pallium.service")

    def test_wait_for_service_uses_monotonic_deadline(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        clock = iter([100.0, 100.0, 131.0])
        monkeypatch.setattr("app.cli.service.time.monotonic", lambda: next(clock))
        monkeypatch.setattr("app.cli.service.time.sleep", lambda _seconds: None)
        monkeypatch.setattr("app.cli.service._service_ready", lambda _port: False)

        assert not _wait_for_service(21987, timeout=30.0)

    def test_install_writes_safe_unit_and_starts_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        profile = tmp_path / "profile"
        home = (tmp_path / "home with spaces" / "בית").resolve()
        executable = str(tmp_path / "venv with spaces" / "pallium%test")
        monkeypatch.setattr(Path, "home", lambda: profile)
        (home / "run").mkdir(parents=True)

        calls: list[list[str]] = []

        def fake_run(argv, **_kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, "", "")

        monkeypatch.setattr("app.cli.service.subprocess.run", fake_run)
        _install_linux(executable, 21987, home)

        unit = (profile / ".config/systemd/user/pallium.service").read_text(encoding="utf-8")
        assert f"# PalliumHome={home!s}" not in unit
        assert f'"{executable.replace("%", "%%")}" service run --port 21987' in unit
        assert f'--home "{home}"' in unit
        assert f'Environment="PALLIUM_HOME={home}"' in unit
        assert "KillMode=control-group" in unit
        assert "TimeoutStopSec=15" in unit
        assert calls == [
            ["systemctl", "--user", "show-environment"],
            ["systemctl", "--user", "daemon-reload"],
            ["systemctl", "--user", "enable", "pallium.service"],
            ["systemctl", "--user", "restart", "pallium.service"],
        ]

    def test_install_refuses_cross_home_retarget(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        profile = tmp_path / "profile"
        unit = profile / ".config/systemd/user/pallium.service"
        unit.parent.mkdir(parents=True)
        unit.write_text('# PalliumHome="/existing/home"\n', encoding="utf-8")
        monkeypatch.setattr(Path, "home", lambda: profile)
        calls: list[list[str]] = []
        monkeypatch.setattr(
            "app.cli.service.subprocess.run",
            lambda argv, **kwargs: (
                calls.append(argv)
                or subprocess.CompletedProcess(argv, 0, "", "")
            ),
        )

        with pytest.raises(RuntimeError, match="refusing to retarget"):
            _install_linux("/venv/bin/pallium", 21987, (tmp_path / "other").resolve())

        assert calls == [["systemctl", "--user", "show-environment"]]
        assert unit.read_text(encoding="utf-8") == '# PalliumHome="/existing/home"\n'

    def test_stop_uses_systemd_not_pid_shutdown(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        states = iter([
            {"LoadState": "loaded", "ActiveState": "active", "MainPID": "123"},
            {"LoadState": "loaded", "ActiveState": "inactive", "MainPID": "0", "TasksCurrent": ""},
        ])
        monkeypatch.setattr("app.cli.service._assert_linux_unit_home", lambda _home: None)
        monkeypatch.setattr("app.cli.service._linux_unit_state", lambda: next(states))
        stop_calls: list[bool] = []
        monkeypatch.setattr("app.cli.service._stop_linux", lambda: stop_calls.append(True))
        monkeypatch.setattr(
            "app.cli.service._cmd_stop_impl",
            lambda _home: pytest.fail("Linux stop must not use PID/HTTP/SIGKILL"),
        )

        assert _cmd_stop(argparse.Namespace(home=str(tmp_path))) == 0
        assert stop_calls == [True]

    def test_status_uses_systemd_main_pid_not_pid_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ):
        monkeypatch.setattr("app.cli.service._assert_linux_unit_home", lambda _home: None)
        monkeypatch.setattr(
            "app.cli.service._linux_unit_state",
            lambda: {
                "LoadState": "loaded",
                "ActiveState": "active",
                "SubState": "running",
                "MainPID": "321",
            },
        )
        monkeypatch.setattr("app.cli.service._read_port", lambda _home: 21987)
        monkeypatch.setattr("app.cli.service._check_health", lambda _port: {"status": "ok"})
        monkeypatch.setattr("app.cli.service._service_ready", lambda _port: True)
        monkeypatch.setattr(
            "app.cli.service._read_pid",
            lambda _home: pytest.fail("Linux status must not read the PID file"),
        )
        monkeypatch.setattr(
            "app.cli.service._is_pid_alive",
            lambda _pid: pytest.fail("Linux status must trust systemd"),
        )

        assert _cmd_status(argparse.Namespace(home=str(tmp_path))) == 0
        assert "PID:     321" in capsys.readouterr().out

    def test_restart_uses_systemd_not_pid_shutdown(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr("app.cli.service._assert_linux_unit_home", lambda _home: None)
        restart_calls: list[bool] = []
        monkeypatch.setattr("app.cli.service._restart_linux", lambda: restart_calls.append(True))
        monkeypatch.setattr("app.cli.service._read_port", lambda _home: 21987)
        monkeypatch.setattr("app.cli.service._wait_for_service", lambda _port: True)
        monkeypatch.setattr(
            "app.cli.service._cmd_stop_impl",
            lambda _home: pytest.fail("Linux restart must not use PID/HTTP/SIGKILL"),
        )

        assert _cmd_restart(argparse.Namespace(home=str(tmp_path))) == 0
        assert restart_calls == [True]

    def test_remove_data_refuses_unmanaged_custom_home(self, tmp_path: Path):
        home = (tmp_path / "unmanaged").resolve()
        home.mkdir()
        sentinel = home / "keep.txt"
        sentinel.write_text("keep", encoding="utf-8")

        with pytest.raises(RuntimeError, match="custom Pallium home"):
            _remove_service_data(home)

        assert sentinel.read_text(encoding="utf-8") == "keep"

    @pytest.mark.parametrize(
        ("script", "option"),
        [
            ("install-service.sh", "--port"),
            ("install-service.sh", "--home"),
            ("install-service.sh", "--python"),
            ("restart-service.sh", "--home"),
            ("restart-service.sh", "--python"),
            ("uninstall-service.sh", "--home"),
            ("uninstall-service.sh", "--python"),
        ],
    )
    def test_wrappers_reject_missing_option_values(self, script: str, option: str):
        repo = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [str(repo / "scripts" / script), option],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=10,
        )

        output = result.stdout + result.stderr
        assert result.returncode != 0
        assert "Usage:" in output
        assert "unbound variable" not in output

    def test_remove_data_refuses_unmanaged_default_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        profile = (tmp_path / "profile").resolve()
        home = profile / ".pallium"
        home.mkdir(parents=True)
        sentinel = home / "keep.txt"
        sentinel.write_text("keep", encoding="utf-8")
        monkeypatch.setattr(Path, "home", lambda: profile)

        with pytest.raises(RuntimeError, match="unmanaged"):
            _remove_service_data(home)
        assert sentinel.read_text(encoding="utf-8") == "keep"

    def test_remove_data_accepts_exact_managed_default_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        profile = (tmp_path / "profile").resolve()
        home = profile / ".pallium"
        home.mkdir(parents=True)
        monkeypatch.setattr(Path, "home", lambda: profile)
        (home / ".pallium-service-home").write_text(str(home) + "\n", encoding="utf-8")
        (home / "data").mkdir()
        (home / "data/record").write_text("test", encoding="utf-8")

        _remove_service_data(home)

        assert not home.exists()

    @pytest.mark.parametrize("unsafe", ["/"])
    def test_remove_data_refuses_filesystem_root(self, unsafe: str):
        with pytest.raises(ValueError, match="unsafe"):
            _remove_service_data(Path(unsafe).resolve())
