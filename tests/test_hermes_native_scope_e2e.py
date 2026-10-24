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


def test_native_metadata_git_audit_exact_source_only(tmp_path):
    if os.environ.get("PALLIUM_HERMES_SCOPE_PROBE") != "1":
        pytest.skip("explicit offline native scope qualification is not enabled")
    require_linux_qualification()
    source = Path(os.environ["HERMES_E2E_SOURCE"]).resolve()
    sdk1 = Path(os.environ["PALLIUM_HERMES_SCOPE_SDK1"])
    repo = Path(__file__).resolve().parents[1]
    manifest = Path(os.environ["PALLIUM_HERMES_SCOPE_SOURCE_MANIFEST"])
    require_contained_paths(source, sdk1, repo, manifest, tmp_path)
    verify_manifest(source, manifest, git_blobs=True)
    probe = r'''
import json, subprocess, sys
from pathlib import Path
from tests.fixtures.hermes_scope_probe import install_guard
work, source, repo, sdk1 = map(Path, sys.argv[1:5])
queries = [
    (["git", "branch", "--show-current"], "version_branch"),
    (["git", "log", "-1", "--format=%ct", "HEAD"], "version_commit_date"),
    (["git", "--no-optional-locks", "status", "--porcelain", "-uno"], "version_status"),
    (["git", "tag", "--merged", "HEAD", "--list", "v[0-9]*"], "version_tags"),
]
observed = []
granted = sys.argv[5] == "granted"
denied = install_guard(work, repo, sdk1, native_source=source if granted else None,
                       allowed_queries=observed)
if granted:
    for command, label in queries:
        result = subprocess.run(command, cwd=source, capture_output=True, timeout=3)
        assert result.returncode == 0
    assert observed == [{"query": label, "cwd": "native_source"} for _, label in queries]
    # The pre-existing private local-Git permissions remain available.
    subprocess.run(["git", "init", "-q"], cwd=work, capture_output=True, check=True, timeout=3)
    subprocess.run(["git", "config", "user.name", "qualification"], cwd=work,
                   capture_output=True, check=True, timeout=3)
negatives = [(command, cwd) for command, _ in queries
             for cwd in (work, source.parent, source / "hermes_cli", source.parent / "wrong-sibling")]
negatives += [(command + ["--extra"], source) for command, _ in queries]
negatives += [(["git", "branch", "--delete", "qualification"], source),
              (["git", "tag", "--delete", "qualification"], source),
              (["git", "log", "-2", "--format=%ct", "HEAD"], source),
              (["git", "fetch"], work), ("git", source), (b"git", source)]
if not granted:
    negatives += [(command, source) for command, _ in queries]
for command, cwd in negatives:
    try:
        subprocess.run(command, cwd=cwd, capture_output=True, timeout=3)
    except (PermissionError, TypeError):
        pass
    else:
        raise AssertionError("audit permitted a negative control")
try:
    (work.parent / "outside-write").write_text("refused", encoding="utf-8")
except PermissionError:
    pass
else:
    raise AssertionError("audit permitted an outside-work write")
assert not (work.parent / "outside-write").exists()
assert observed == ([{"query": label, "cwd": "native_source"} for _, label in queries] if granted else [])
assert denied
print(json.dumps({"queries": observed, "refused": len(negatives) + 1}))
'''
    for mode in ("granted", "default"):
        work = tmp_path / mode
        env = isolated_env(work, os.environ)
        env["PYTHONPATH"] = str(repo)
        result = subprocess.run([str(sdk1), "-B", "-c", probe, str(work), str(source),
                                 str(repo), str(sdk1), mode], cwd=work, env=env,
                                capture_output=True, text=True, timeout=20)
        (work / "probe.stdout").write_text(result.stdout, encoding="utf-8")
        (work / "probe.stderr").write_text(result.stderr, encoding="utf-8")
        assert result.returncode == 0, "native audit subprocess control failed; inspect private capture"
        proof = json.loads(result.stdout)
        assert proof["refused"] == (27 if mode == "granted" else 31)
        assert len(proof["queries"]) == (4 if mode == "granted" else 0)


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
    guard_names = ("PALLIUM_TUI_GUARD_PATH", "PALLIUM_TUI_GUARD_SHA256")
    assert all(os.environ.get(name) for name in guard_names), "explicit copied-runtime guard identity is required"
    host_env.update({name: os.environ[name] for name in guard_names})
    host_env.update({
        "PALLIUM_TUI_ALLOWED_ENDPOINTS": json.dumps([["127.0.0.1", port]]),
        "PALLIUM_TUI_ALLOWED_CONTROL_PATHS": "[]",
        "PALLIUM_TUI_EGRESS_LOG": str(host_work / "socket-egress.jsonl"),
        "PALLIUM_TUI_IPC_LOG": str(host_work / "socket-ipc.jsonl"),
    })
    expected_guard = {
        "path": host_env["PALLIUM_TUI_GUARD_PATH"], "sha256": host_env["PALLIUM_TUI_GUARD_SHA256"],
        "socket_guard_active": True, "allowed_endpoints": [["127.0.0.1", port]], "allowed_control_paths": [],
    }
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
        assert len(receipt["checks"]) == 6
        assert "empty native route refuses despite ambient session-key environment" in receipt["checks"]
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
            try:
                guard_receipt = host_work / "host-receipt.json"
                assert guard_receipt.is_file(), "loaded copied-runtime guard witness is missing"
                assert json.loads(guard_receipt.read_text(encoding="utf-8"))["socket_guard"] == expected_guard
            finally:
                try:
                    egress = host_work / "socket-egress.jsonl"
                    assert not egress.exists() or not egress.read_text(), "copied-runtime guard denied egress; inspect private receipt"
                finally:
                    for log in logs:
                        log.close()
                    assert libc.prctl(36, old_subreaper.value, 0, 0, 0) == 0
