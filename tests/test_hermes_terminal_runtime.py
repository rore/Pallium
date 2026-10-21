"""Dependency preparation is tested with no installer or interpreter execution."""
import copy
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from tests.fixtures import hermes_terminal_runtime as runtime
from tests.fixtures.hermes_desktop_driver import RUNNER_MARKERS


def fixture_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "os", SimpleNamespace(name="nt"))
    prefix = tmp_path / "sdk2"
    python = prefix / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"synthetic interpreter identity")
    home, artifacts, source = (tmp_path / name for name in ("home", "artifacts", "source"))
    for path in (home, artifacts, source):
        path.mkdir()
    env = {**RUNNER_MARKERS, "RUNNER_TEMP": str(tmp_path), "USERPROFILE": str(home),
           "PATH": "synthetic path", "PYTHONPATH": "must-not-inherit", "NODE_OPTIONS": "must-not-inherit",
           "PRIVATE_API_KEY": "must-not-inherit"}
    modules = {name: {"version": "0.8.2" if name == "pyte" else "0.6.0",
                     "path": str(prefix / "Lib" / "site-packages" / name / "__init__.py"),
                     "files": {f"{name}/__init__.py": "synthetic recorded fingerprint"}}
               for name in ("wcwidth", "pyte")}
    state = {"prefix": str(prefix), "base_prefix": str(tmp_path / "base"),
             "modules": {"wcwidth": modules["wcwidth"], "pyte": None}}
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        assert not {"PYTHONPATH", "NODE_OPTIONS", "PRIVATE_API_KEY"} & kwargs["env"].keys()
        if "install" in argv:
            state["modules"]["pyte"] = copy.deepcopy(modules["pyte"])
            return SimpleNamespace(stdout="installed", stderr="")
        if "--version" in argv:
            return SimpleNamespace(stdout="pip synthetic-version", stderr="")
        return SimpleNamespace(stdout=json.dumps(state), stderr="")

    monkeypatch.setattr(runtime.subprocess, "run", run)
    args = (python, source, home, artifacts, env)
    return args, state, calls


def test_terminal_runtime_prepares_once_and_revalidates_exact_runtime(tmp_path, monkeypatch):
    args, state, calls = fixture_runtime(tmp_path, monkeypatch)
    first = runtime.prepare_terminal_runtime(*args)
    assert first["state"] == "ready" and first["pip_version"] == "pip synthetic-version"
    installs = [argv for argv, _ in calls if "install" in argv]
    assert len(installs) == 1
    argv = installs[0]
    assert argv[argv.index("--python") + 1] == str(args[0])
    assert {"-I", "--isolated", "--no-input", "--no-deps", "--only-binary=:all:",
            "--require-hashes", "--cache-dir"} <= set(argv)
    assert argv[argv.index("--index-url") + 1] == "https://pypi.org/simple"
    assert argv[argv.index("--keyring-provider") + 1] == "disabled"
    assert Path(argv[-1]).read_text(encoding="utf-8") == runtime.REQUIREMENT
    assert runtime.prepare_terminal_runtime(*args) == first
    assert len([argv for argv, _ in calls if "install" in argv]) == 1
    state["modules"]["pyte"]["files"]["pyte/__init__.py"] = "changed"
    with pytest.raises(AssertionError, match="drift"):
        runtime.prepare_terminal_runtime(*args)


@pytest.mark.parametrize("refusal", ["markers", "base-interpreter", "foreign-module", "missing-wcwidth", "unowned-pyte"])
def test_terminal_runtime_refuses_before_install(tmp_path, monkeypatch, refusal):
    args, state, calls = fixture_runtime(tmp_path, monkeypatch)
    if refusal == "markers":
        args[-1]["GITHUB_ACTIONS"] = "false"
    elif refusal == "base-interpreter":
        state["base_prefix"] = state["prefix"]
    elif refusal == "foreign-module":
        state["modules"]["wcwidth"]["path"] = str(tmp_path / "foreign" / "wcwidth.py")
    elif refusal == "missing-wcwidth":
        state["modules"]["wcwidth"] = None
    else:
        state["modules"]["pyte"] = copy.deepcopy(state["modules"]["wcwidth"])
    with pytest.raises(AssertionError):
        runtime.prepare_terminal_runtime(*args)
    assert not any("install" in argv for argv, _ in calls)
    assert not (tmp_path / "hermes-terminal-observer.json").exists()


def test_terminal_runtime_does_not_retry_failed_or_ambiguous_install(tmp_path, monkeypatch):
    args, state, calls = fixture_runtime(tmp_path, monkeypatch)
    original = runtime.subprocess.run

    def fail(argv, **kwargs):
        if "install" in argv:
            calls.append((argv, kwargs))
            raise subprocess.CalledProcessError(1, argv)
        return original(argv, **kwargs)

    monkeypatch.setattr(runtime.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        runtime.prepare_terminal_runtime(*args)
    with pytest.raises(AssertionError, match="unresolved"):
        runtime.prepare_terminal_runtime(*args)
    assert len([argv for argv, _ in calls if "install" in argv]) == 1
