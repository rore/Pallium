"""Tests for the launch-token write/remove contract in app.main.

The supervisor uses these helpers to self-identify the API child it just
spawned, distinguishing it from any orphan process still bound to the same
port from a previous generation.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.main import _write_launch_token, _remove_launch_token


def test_write_launch_token_writes_nonce_and_pid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PALLIUM_HOME", str(tmp_path))
    monkeypatch.setenv("PALLIUM_API_LAUNCH_TOKEN", "the-nonce-xyz")

    path = _write_launch_token()

    assert path is not None
    assert path == tmp_path / "run" / "api_token"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["nonce"] == "the-nonce-xyz"
    assert data["pid"] == os.getpid()


def test_write_launch_token_noop_when_env_unset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """No PALLIUM_API_LAUNCH_TOKEN → caller is not running under supervisor;
    don't write anything (back-compat for `python -m app.run serve` direct use)."""
    monkeypatch.setenv("PALLIUM_HOME", str(tmp_path))
    monkeypatch.delenv("PALLIUM_API_LAUNCH_TOKEN", raising=False)

    path = _write_launch_token()

    assert path is None
    assert not (tmp_path / "run" / "api_token").exists()


def test_write_launch_token_creates_run_dir_if_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Fresh ~/.pallium without a run/ subdir → must be created on the fly."""
    monkeypatch.setenv("PALLIUM_HOME", str(tmp_path))
    monkeypatch.setenv("PALLIUM_API_LAUNCH_TOKEN", "abc")

    assert not (tmp_path / "run").exists()
    path = _write_launch_token()
    assert path is not None
    assert (tmp_path / "run").is_dir()


def test_write_launch_token_overwrites_stale_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A leftover token from a prior crashed generation must be replaced —
    otherwise the supervisor probe would see the stale nonce and refuse the
    new (correct) child indefinitely."""
    monkeypatch.setenv("PALLIUM_HOME", str(tmp_path))
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "api_token").write_text(
        json.dumps({"nonce": "old-stale", "pid": 9999}), encoding="utf-8"
    )

    monkeypatch.setenv("PALLIUM_API_LAUNCH_TOKEN", "fresh-nonce")
    path = _write_launch_token()

    assert path is not None
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["nonce"] == "fresh-nonce"
    assert data["pid"] == os.getpid()


def test_write_launch_token_atomic_via_replace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify a .tmp file isn't left around after a successful write —
    proxy assertion that the implementation used os.replace (atomic on
    Windows and POSIX) rather than streaming directly into api_token."""
    monkeypatch.setenv("PALLIUM_HOME", str(tmp_path))
    monkeypatch.setenv("PALLIUM_API_LAUNCH_TOKEN", "x")

    _write_launch_token()
    leftovers = list((tmp_path / "run").glob("*.tmp"))
    assert leftovers == [], f"expected no .tmp leftovers, got {leftovers}"


def test_write_launch_token_default_home_when_pallium_home_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """No PALLIUM_HOME set → falls back to ~/.pallium. We redirect home to
    tmp_path so we don't pollute the real home dir."""
    monkeypatch.delenv("PALLIUM_HOME", raising=False)
    monkeypatch.setenv("PALLIUM_API_LAUNCH_TOKEN", "tk")

    fake_home = tmp_path / "fakehome"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    path = _write_launch_token()
    assert path == fake_home / ".pallium" / "run" / "api_token"
    assert path.exists()


def test_remove_launch_token_idempotent(tmp_path: Path):
    target = tmp_path / "api_token"
    target.write_text("{}", encoding="utf-8")

    _remove_launch_token(target)
    assert not target.exists()

    # Second call must not raise even though file is gone
    _remove_launch_token(target)


def test_remove_launch_token_handles_none():
    """No-op when path is None (e.g. _write_launch_token returned None
    because the env var was unset)."""
    _remove_launch_token(None)  # must not raise
