"""Opt-in native public-host hooks/tools qualification; no frontend or wake journey."""
from __future__ import annotations

import json
import ctypes
import os
from pathlib import Path
import shlex
import signal
import socket
import subprocess
import time

import pytest

from tests.fixtures.hermes_linux_guard import require_contained_paths, require_linux_qualification
from tests.fixtures.hermes_scope_probe import (
    capture_owned, http, identity_key, isolated_env, process_identity,
    remaining_owned, save_owned, signal_owned, verify_manifest,
)


pytestmark = pytest.mark.slow


def _refresh_owned(records, path, child_path, host_identity, controller):
    capture_owned(records, [controller])
    if host_identity is not None and child_path.exists():
        child = json.loads(child_path.read_text(encoding="utf-8"))
        assert child["schema"] == "pallium-owned-processes/v1" and child["owner"] == host_identity
        for record in child["processes"]:
            records.setdefault(identity_key(record), record)
    capture_owned(records)
    save_owned(path, records)


def _stop_owned(records, processes, refresh):
    """Exited group leaders do not erase independently sessioned MCP children."""
    actions, errors = [], []
    leader_pids = {process.pid for process in processes if process is not None}
    def update():
        try:
            refresh()
        except Exception as error:
            # A bad receipt must fail the proof without abandoning known children.
            errors.append(repr(error))
    update()
    for sig, seconds in ((signal.SIGTERM, 12), (signal.SIGKILL, 5)):
        deadline = time.monotonic() + seconds
        while True:
            update()
            for process in processes:
                if process is not None:
                    process.poll()  # reap only our own Popen leaders
            for record in remaining_owned(records):
                if record["pid"] not in leader_pids:
                    try:
                        os.waitpid(record["pid"], os.WNOHANG)
                    except ChildProcessError:
                        pass  # not orphaned; its live parent still owns reaping
            live = remaining_owned(records)
            if not live or time.monotonic() >= deadline:
                break
            for record in live:
                if signal_owned(record, sig):
                    actions.append({**record, "signal": int(sig)})
            time.sleep(0.05)
    return {"signals": actions, "remaining": remaining_owned(records), "errors": errors}


def test_actual_public_hermes_hooks_tools_and_scope_lifecycle(tmp_path):
    if os.environ.get("PALLIUM_HERMES_SCOPE_PROBE") != "1":
        pytest.skip("explicit offline native scope qualification is not enabled")
    boundary = require_linux_qualification()
    names = ("HERMES_E2E_SOURCE", "HERMES_E2E_PYTHON", "PALLIUM_HERMES_SCOPE_SDK1",
             "PALLIUM_HERMES_SCOPE_SOURCE_MANIFEST", "PALLIUM_HERMES_SCOPE_ARTIFACT_MANIFEST")
    assert all(os.environ.get(name) for name in names), "all pinned source/runtime/manifest inputs are required"
    inputs = [Path(os.environ[name]) for name in names]
    source, sdk2, sdk1, source_manifest, artifact_manifest = (
        Path(os.path.abspath(path)) if index in {1, 2} else path.resolve()
        for index, path in enumerate(inputs))
    repo = Path(__file__).resolve().parents[1]
    driver = repo / "tests" / "fixtures" / "hermes_scope_probe.py"
    require_contained_paths(source, sdk2, sdk1, source_manifest, artifact_manifest, repo, driver, tmp_path)
    assert sdk1.is_file() and sdk2.is_file() and sdk1 != sdk2
    assert hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"), "exact Linux process signaling is required"
    source_identity = verify_manifest(source, source_manifest, git_blobs=True)
    artifact_identity = verify_manifest(repo, artifact_manifest, git_blobs=False)
    work = tmp_path / "native-scope"
    work.mkdir(mode=0o700)
    service_work, host_work = work / "service", work / "host"
    service_env = isolated_env(service_work, os.environ)
    host_env = isolated_env(host_work, os.environ)
    # Bridge accepts an executable path. This task-owned launcher keeps SDK1
    # bytecode writes out of the reused, already-qualified environment.
    launcher = host_work / "pallium-python"
    launcher.write_text("#!/bin/sh\nexec " + shlex.quote(str(sdk1)) + ' -B "$@"\n', encoding="utf-8")
    launcher.chmod(0o700)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    service_process = host_process = None
    host_identity = None
    controller = process_identity(os.getpid())
    owned = {}
    capture_owned(owned, [controller])
    assert not owned, "qualification controller already owns unrelated children"
    # Adopt escaped MCP sessions locally, so forced cleanup can reap them too.
    libc = ctypes.CDLL(None, use_errno=True)
    old_subreaper = ctypes.c_int()
    assert libc.prctl(37, ctypes.byref(old_subreaper), 0, 0, 0) == 0
    assert libc.prctl(36, 1, 0, 0, 0) == 0
    def refresh():
        _refresh_owned(owned, work / "owned-processes.json", host_work / "owned-processes.json", host_identity, controller)
    def register(process):
        identity = process_identity(process.pid)
        assert identity is not None, "owned child exited before its identity was recorded"
        owned[identity_key(identity)] = identity
        refresh()
        return identity
    logs = []
    experiment_passed = False
    try:
        for name in ("service.stdout", "service.stderr", "host.stdout", "host.stderr"):
            logs.append((work / name).open("w", encoding="utf-8"))
        service_process = subprocess.Popen([
            str(sdk1), "-B", str(driver), "--mode", "service", "--work", str(service_work),
            "--repo", str(repo), "--sdk1", str(launcher), "--port", str(port),
        ], cwd=service_work, env=service_env, start_new_session=True, stdout=logs[0], stderr=logs[1])
        register(service_process)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            refresh()
            assert service_process.poll() is None, "native HTTP service exited; inspect private logs"
            try:
                health = http(base, "/health")
                assert health.get("embedding_provider_ok") is True
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise AssertionError("native HTTP service did not become ready")
        service_receipt = json.loads((service_work / "service-receipt.json").read_text())
        assert service_receipt["mcp_version"].startswith("1."), "service/MCP require existing SDK1"
        assert service_receipt["semantic_packages_enabled"] == []
        assert service_receipt["vector_index_enabled"] is False
        host_process = subprocess.Popen([
            str(sdk2), "-B", str(driver), "--mode", "host", "--work", str(host_work),
            "--repo", str(repo), "--sdk1", str(launcher), "--source", str(source),
            "--source-manifest", str(source_manifest), "--artifact-manifest", str(artifact_manifest),
            "--base", base,
        ], cwd=host_work, env=host_env, start_new_session=True, stdout=logs[2], stderr=logs[3])
        host_identity = register(host_process)
        deadline = time.monotonic() + 180
        while host_process.poll() is None and time.monotonic() < deadline:
            refresh()
            time.sleep(0.05)
        refresh()
        assert host_process.poll() == 0, "native host proof failed/timed out; inspect private logs/receipt"
        receipt = json.loads((host_work / "host-receipt.json").read_text(encoding="utf-8"))
        assert receipt["passed"] is True
        assert receipt["source"] == source_identity and receipt["artifact"] == artifact_identity
        assert receipt["qualification_run"] == boundary["run_id"]
        assert {row["surface"] for row in receipt["initial_contexts"]} == {"desktop", "tui"}
        assert len(receipt["checks"]) == 5
        assert not receipt["cleanup"]["remaining"] and not receipt["cleanup"]["bridge_threads"]
        assert receipt["denied_actions"] == []
        experiment_passed = True
    finally:
        try:
            cleanup = _stop_owned(owned, (host_process, service_process), refresh)
            (work / "process-receipt.json").write_text(json.dumps({
                "service_returncode": service_process.poll() if service_process else None,
                "host_returncode": host_process.poll() if host_process else None,
                "experiment_passed_before_shutdown": experiment_passed,
                "controller_cleanup": cleanup,
                "forced_failure_cleanup": not experiment_passed and bool(cleanup["signals"]),
                "controller_subreaper_previous": old_subreaper.value,
                "coverage": "public host hooks/tools, real MCP/HTTP and History; no wake admission/frontend/memory",
            }, indent=2), encoding="utf-8")
            assert not cleanup["remaining"], "exact owned processes remain; inspect cleanup receipt"
            assert not cleanup["errors"], "owned cleanup evidence failed; inspect cleanup receipt"
            for directory in (service_work, host_work):
                denials = directory / "guard-denials.jsonl"
                assert not denials.exists() or not denials.read_text(), "native audit denied an operation; inspect private receipt"
        finally:
            for log in logs:
                log.close()
            assert libc.prctl(36, old_subreaper.value, 0, 0, 0) == 0
