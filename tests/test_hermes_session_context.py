"""Opt-in, source-only qualification of the real public Hermes context API."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import textwrap
import uuid

import pytest


PROBE = r'''
import concurrent.futures
import contextvars
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import traceback
from types import SimpleNamespace

root, source, packages = (Path(arg).resolve() for arg in sys.argv[1:4])
os.chdir(root)
library_roots = [Path(p).resolve() for p in sys.path if p]
library_roots += [packages, Path(sys.base_prefix).resolve()]
sys.path[:0] = [str(source), str(packages)]
expected_denials = []
unexpected_denials = []
version_probe_denials = []
checking_guard = False

def within(path, roots):
    return any(path == base or base in path.parents for base in roots)

def deny(event, path=None):
    (expected_denials if checking_guard else unexpected_denials).append({"event": event,
        "path": str(path) if path else None, "stack": traceback.format_stack(limit=8)})
    raise PermissionError("qualification audit refused " + event)

def checked_path(raw, event, *, write=False):
    if isinstance(raw, int):
        return
    path = Path(os.fsdecode(raw)).resolve()
    if write:
        if not within(path, [root]):
            deny(event, path)
        return
    if within(path, [root]):
        return
    name = path.name.lower()
    code = path.suffix.lower() in {".py", ".pyc", ".pyd", ".dll", ".so", ".zip"}
    sensitive = name.startswith(".env") or any(word in name for word in (
        "credential", "secret", "token", "auth", "config", "history", "session", "settings", "profile"))
    bundled_manifest = name == "plugin.yaml" and path.parent.parent == source / "plugins" / "platforms"
    sensitive = sensitive or (path.suffix.lower() in {
        ".db", ".sqlite", ".sqlite3", ".yaml", ".yml", ".toml", ".ini"} and not bundled_manifest)
    if not within(path, [source, *library_roots]) or (sensitive and not code):
        deny(event, path)

def audit(event, args):
    if event == "subprocess.Popen" and not checking_guard:
        frames = traceback.extract_stack(limit=10)
        version_frames = {frame.name for frame in frames
                          if Path(frame.filename).resolve() == source / "hermes_cli" / "version_info.py"}
        command = args[1]
        if (command in ("git rev-parse HEAD", ["git", "rev-parse", "HEAD"], ("git", "rev-parse", "HEAD"))
                and args[2] and Path(args[2]).resolve() == source
                and {"_stamp_version_info", "_run_git"} <= version_frames):
            version_probe_denials.append({"command": ["git", "rev-parse", "HEAD"],
                "cwd": str(source), "stack": traceback.format_stack(limit=10), "executed": False})
            raise PermissionError("qualification denied optional version-stamp Git probe")
    if event == "open":
        path, mode, flags = args
        write = bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        checked_path(path, event, write=write)
    elif event in {"os.mkdir", "os.remove", "os.rmdir", "os.chmod", "os.utime", "os.truncate"}:
        checked_path(args[0], event, write=True)
    elif event in {"os.rename", "os.link", "os.symlink"}:
        checked_path(args[0], event, write=True)
        checked_path(args[1], event, write=True)
    elif event == "os.chdir":
        checked_path(args[0], event, write=True)
    elif event.startswith(("subprocess.", "os.spawn", "os.exec")) or event in {
        "os.system", "os.fork", "os.startfile", "socket.connect", "socket.connect_ex",
        "socket.bind", "socket.getaddrinfo", "socket.gethostbyname", "socket.sendto",
    } or event.startswith("winreg."):
        deny(event)

sys.addaudithook(audit)
checking_guard = True
for event, args in [
    ("open", (str(root.parent / "forbidden.env"), "r", 0)),
    ("open", (str(source / ".env"), "r", 0)),
    ("open", (str(source / "forbidden.txt"), "w", os.O_WRONLY)),
    ("subprocess.Popen", ("forbidden", [], None, {})),
    ("socket.connect", (None, ("127.0.0.1", 1))),
]:
    try:
        sys.audit(event, *args)
    except PermissionError:
        pass
    else:
        raise AssertionError("audit guard did not refuse " + event)
checking_guard = False

from hermes_cli.plugins import PluginContext, PluginManifest
from gateway.session_context import set_session_vars, clear_session_vars
import hermes_cli.plugins as plugins_module
import hermes_cli.plugin_session as session_module
import gateway.session_context as context_module
import agent.runtime_cwd as cwd_module

assert callable(getattr(PluginContext, "session_cwd", None)), "public session_cwd missing"
assert callable(getattr(PluginContext, "session_surface", None)), "public session_surface missing"
manifest = PluginManifest(name="pallium-context-qualification")
ctx = PluginContext(manifest, SimpleNamespace(_cli_ref=None))
assert ctx.session_cwd() == "", "unbound accessor fell back to process cwd"
assert ctx.session_surface() == ""
observations = []

def bound(surface, index, barrier):
    cwd = root / ("workspace-" + str(index))
    cwd.mkdir(exist_ok=True)
    tokens = set_session_vars(platform=surface, session_id="qualification-" + str(index),
                              session_key="key-" + str(index), cwd=str(cwd))
    try:
        barrier.wait(timeout=5)
        assert ctx.session_cwd() == str(cwd)
        assert ctx.session_surface() == surface
        copied = contextvars.copy_context()
        assert copied.run(ctx.session_cwd) == str(cwd)
        assert copied.run(ctx.session_surface) == surface
        barrier.wait(timeout=5)
        assert ctx.session_cwd() == str(cwd), "another task replaced cwd"
        return {"surface": surface, "cwd_is_exact": True, "copied_context_is_exact": True}
    finally:
        clear_session_vars(tokens)
        assert ctx.session_cwd() == "", "cleared context leaked cwd"
        assert ctx.session_surface() == "", "cleared context leaked surface"

with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
    for pair, surfaces in enumerate((("desktop", "tui"), ("cli", "acp"))):
        barrier = threading.Barrier(2)
        futures = [executor.submit(contextvars.copy_context().run, bound, surface,
                                   pair * 2 + n, barrier) for n, surface in enumerate(surfaces)]
        observations.extend(f.result(timeout=15) for f in futures)
        assert ctx.session_cwd() == "", "worker context leaked into parent"
        assert ctx.session_surface() == ""

tokens = set_session_vars(platform="desktop", session_id="missing-cwd", cwd="")
try:
    assert ctx.session_cwd() == "", "missing cwd borrowed process or another task cwd"
finally:
    clear_session_vars(tokens)

(root / "audit.json").write_text(json.dumps(unexpected_denials, indent=2), encoding="utf-8")
modules = [plugins_module, session_module, context_module, cwd_module]
receipt = {
    "qualification": "public-context-accessors-only",
    "source": str(source), "python": sys.executable,
    "source_head": (source / ".git" / "HEAD").read_text(encoding="utf-8").strip(),
    "modules": [{"path": m.__file__, "sha256": hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()}
                for m in modules],
    "observations": observations, "expected_guard_denials": expected_denials,
    "unexpected_guard_denials": unexpected_denials,
    "denied_optional_version_probes": version_probe_denials,
    "unbound_missing_cleared_and_parent_cwd_empty": True,
}
(root / "receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
assert not unexpected_denials, "imports/accessors attempted forbidden activity"
assert len(version_probe_denials) <= 1, "repeated optional version probes"
print("public session context qualification passed")
'''


def _dependency_directory(python):
    probe = subprocess.run([str(python), "-I", "-S", "-B", "-X", "utf8", "-c",
        "import sys,sysconfig; print(sysconfig.get_path('purelib', vars={'base':sys.argv[1],'platbase':sys.argv[1]}))",
        str(python.parent.parent)], check=True, capture_output=True, text=True, encoding="utf-8", timeout=10)
    return Path(probe.stdout.strip()).resolve()


def test_dependency_directory_uses_the_interpreters_layout():
    import sys
    import sysconfig
    assert _dependency_directory(Path(sys.executable)) == Path(sysconfig.get_path("purelib")).resolve()


def test_real_public_session_context_isolation():
    source = os.environ.get("PALLIUM_HERMES_CWD_SOURCE")
    python = os.environ.get("PALLIUM_HERMES_CWD_PYTHON")
    if not source and not python:
        pytest.skip("set PALLIUM_HERMES_CWD_SOURCE and PALLIUM_HERMES_CWD_PYTHON for source qualification")
    assert source and python, "source and interpreter must be configured together"
    source, python = Path(source).resolve(), Path(python).absolute()
    assert source.is_dir() and python.is_file(), "configured source/interpreter missing"
    packages = _dependency_directory(python)
    assert packages.is_dir(), "configured interpreter dependency directory missing"
    root = Path(__file__).resolve().parents[1] / "build" / ("hermes-context-probe-" + uuid.uuid4().hex)
    root.mkdir(parents=True)
    directories = {name: root / name.lower() for name in (
        "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP",
        "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME", "HERMES_HOME")}
    for directory in directories.values():
        directory.mkdir()
    # Allowlist startup essentials; no inherited provider, profile, or terminal scope.
    env = {key: value for key, value in os.environ.items()
           if key.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT"}}
    env.update({key: str(path) for key, path in directories.items()})
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
               PATH=str(python.parent))
    script = root / "probe.py"
    script.write_text(textwrap.dedent(PROBE), encoding="utf-8")
    result = subprocess.run([str(python), "-I", "-S", "-B", str(script), str(root), str(source), str(packages)],
                            cwd=root, env=env, capture_output=True, text=True,
                            encoding="utf-8", timeout=45)
    (root / "execution.json").write_text(json.dumps({"returncode": result.returncode,
        "stdout": result.stdout, "stderr": result.stderr}, indent=2), encoding="utf-8")
    assert result.returncode == 0, f"public context probe failed; private receipt: {root / 'execution.json'}"
    receipt = json.loads((root / "receipt.json").read_text(encoding="utf-8"))
    assert {row["surface"] for row in receipt["observations"]} == {"desktop", "tui", "cli", "acp"}
    assert len(receipt["expected_guard_denials"]) == 5
    assert receipt["unexpected_guard_denials"] == []
    assert len(receipt["denied_optional_version_probes"]) <= 1


@pytest.mark.skipif(os.name == "nt", reason="POSIX venv interpreter symlink layout")
def test_public_context_probe_keeps_configured_venv_symlink(tmp_path, monkeypatch):
    import sys
    source = tmp_path / "source"
    source.mkdir()
    python = tmp_path / "venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.symlink_to(Path(sys.executable))
    packages = python.parent.parent / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    packages.mkdir(parents=True)
    monkeypatch.setenv("PALLIUM_HERMES_CWD_SOURCE", str(source))
    monkeypatch.setenv("PALLIUM_HERMES_CWD_PYTHON", str(python))
    lookup = _dependency_directory
    checked = []
    class LayoutChecked(Exception):
        pass
    def check(configured):
        assert configured == python and configured != python.resolve()
        checked.append(lookup(configured))
        raise LayoutChecked
    monkeypatch.setattr(sys.modules[__name__], "_dependency_directory", check)
    with pytest.raises(LayoutChecked):
        test_real_public_session_context_isolation()
    assert checked == [packages.resolve()]
