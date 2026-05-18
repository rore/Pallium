"""Tests for service logging: startup rotation and supervisor log_file parameter."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.runtime_logging import _rotate_on_startup


class TestRotateOnStartup:
    def test_no_rotation_when_file_missing(self, tmp_path: Path):
        log_file = tmp_path / "pallium.log"
        _rotate_on_startup(log_file, max_bytes=100, keep=3)
        assert not log_file.exists()

    def test_no_rotation_when_under_threshold(self, tmp_path: Path):
        log_file = tmp_path / "pallium.log"
        log_file.write_bytes(b"x" * 50)
        _rotate_on_startup(log_file, max_bytes=100, keep=3)
        # File should remain untouched
        assert log_file.exists()
        assert log_file.stat().st_size == 50

    def test_rotates_when_over_threshold(self, tmp_path: Path):
        log_file = tmp_path / "pallium.log"
        log_file.write_bytes(b"x" * 200)
        _rotate_on_startup(log_file, max_bytes=100, keep=3)
        # Current should be gone (renamed to .1)
        assert not log_file.exists()
        backup = tmp_path / "pallium.log.1"
        assert backup.exists()
        assert backup.stat().st_size == 200

    def test_shifts_existing_backups(self, tmp_path: Path):
        log_file = tmp_path / "pallium.log"
        log_file.write_text("current-big-content" * 100)
        (tmp_path / "pallium.log.1").write_text("backup-1")
        (tmp_path / "pallium.log.2").write_text("backup-2")

        _rotate_on_startup(log_file, max_bytes=100, keep=5)

        assert not log_file.exists()
        assert (tmp_path / "pallium.log.1").read_text().startswith("current-big-content")
        assert (tmp_path / "pallium.log.2").read_text() == "backup-1"
        assert (tmp_path / "pallium.log.3").read_text() == "backup-2"

    def test_deletes_oldest_when_at_keep_limit(self, tmp_path: Path):
        log_file = tmp_path / "pallium.log"
        log_file.write_bytes(b"x" * 200)
        (tmp_path / "pallium.log.1").write_text("one")
        (tmp_path / "pallium.log.2").write_text("two")
        (tmp_path / "pallium.log.3").write_text("three-oldest")

        _rotate_on_startup(log_file, max_bytes=100, keep=3)

        # .3 (oldest at keep limit) was deleted, then shifts happen:
        # current→.1, old .1→.2, old .2→.3
        assert not log_file.exists()
        assert (tmp_path / "pallium.log.1").stat().st_size == 200  # was current
        assert (tmp_path / "pallium.log.2").read_text() == "one"
        assert (tmp_path / "pallium.log.3").read_text() == "two"

    def test_at_threshold_rotates(self, tmp_path: Path):
        log_file = tmp_path / "pallium.log"
        log_file.write_bytes(b"x" * 100)
        _rotate_on_startup(log_file, max_bytes=100, keep=3)
        # Exactly at threshold — rotates (uses < not <=)
        assert not log_file.exists()
        assert (tmp_path / "pallium.log.1").exists()

    def test_under_threshold_does_not_rotate(self, tmp_path: Path):
        log_file = tmp_path / "pallium.log"
        log_file.write_bytes(b"x" * 99)
        _rotate_on_startup(log_file, max_bytes=100, keep=3)
        assert log_file.exists()
        assert log_file.stat().st_size == 99


class TestSupervisorLogFile:
    def test_children_receive_log_file_handle(self, tmp_path: Path):
        """When log_file is set, child processes get stdout/stderr pointing to it."""
        from app.supervisor import run_supervisor

        log_file = tmp_path / "test.log"
        log_file.write_text("")

        spawned_kwargs: list[dict] = []

        def fake_popen(cmd, **kwargs):
            spawned_kwargs.append(kwargs)
            mock = MagicMock()
            mock.poll.return_value = None
            mock.pid = 999
            return mock

        stop_count = [0]

        def should_stop():
            stop_count[0] += 1
            return stop_count[0] > 2

        run_supervisor(
            ["--host", "127.0.0.1", "--port", "19999", "--processors", "1", "--cleaners", "0"],
            popen_factory=fake_popen,
            sleep_fn=lambda _: None,
            wait_for_api_fn=lambda *_, **__: True,
            kill_fn=lambda *_, **__: None,
            should_stop=should_stop,
            log_file=log_file,
        )

        # At least the API server was spawned with stdout/stderr
        assert len(spawned_kwargs) >= 1
        for kw in spawned_kwargs:
            assert "stdout" in kw, "stdout should be set when log_file is provided"
            assert "stderr" in kw, "stderr should be set when log_file is provided"

    def test_children_no_log_file_by_default(self, tmp_path: Path):
        """When log_file is None (dev mode), children inherit normal stdio."""
        from app.supervisor import run_supervisor

        spawned_kwargs: list[dict] = []

        def fake_popen(cmd, **kwargs):
            spawned_kwargs.append(kwargs)
            mock = MagicMock()
            mock.poll.return_value = None
            mock.pid = 999
            return mock

        stop_count = [0]

        def should_stop():
            stop_count[0] += 1
            return stop_count[0] > 2

        run_supervisor(
            ["--host", "127.0.0.1", "--port", "19999", "--processors", "1", "--cleaners", "0"],
            popen_factory=fake_popen,
            sleep_fn=lambda _: None,
            wait_for_api_fn=lambda *_, **__: True,
            kill_fn=lambda *_, **__: None,
            should_stop=should_stop,
            log_file=None,
        )

        # No stdout/stderr should be forced
        for kw in spawned_kwargs:
            assert "stdout" not in kw
            assert "stderr" not in kw

    def test_log_file_receives_child_output(self, tmp_path: Path):
        """The log file handle passed to children points to the correct path."""
        from app.supervisor import run_supervisor

        log_file = tmp_path / "test.log"
        log_file.write_text("")

        captured_paths: list[str] = []

        def fake_popen(cmd, **kwargs):
            if "stdout" in kwargs:
                captured_paths.append(kwargs["stdout"].name)
            mock = MagicMock()
            mock.poll.return_value = None
            mock.pid = 999
            return mock

        stop_count = [0]

        def should_stop():
            stop_count[0] += 1
            return stop_count[0] > 2

        run_supervisor(
            ["--host", "127.0.0.1", "--port", "19999", "--processors", "1", "--cleaners", "0"],
            popen_factory=fake_popen,
            sleep_fn=lambda _: None,
            wait_for_api_fn=lambda *_, **__: True,
            kill_fn=lambda *_, **__: None,
            should_stop=should_stop,
            log_file=log_file,
        )

        # All children got a handle pointing to the log file
        assert len(captured_paths) >= 1
        for path in captured_paths:
            assert Path(path) == log_file
