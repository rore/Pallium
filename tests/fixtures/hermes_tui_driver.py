"""Task-local preflight and child network guards for native Hermes qualification."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

RELEASES = {
    "e06df9c2eae6901f4c88f464e0ae6e753c0428b8": "0.22.0",
    "d923a5eb487a17c0a68801bba9ef0f56c81040a8": "0.22.2",
}


def seed_models_dev_cache(profile: Path) -> Path:
    """Use the native provider/models/limit disk shape; a fresh cache avoids registry startup I/O."""
    registry = {"local": {"id": "local", "name": "Synthetic local provider", "models": {
        "pallium-local": {"id": "pallium-local", "limit": {"context": 128000, "output": 4096}},
    }}}
    path = profile / "models_dev_cache.json"
    with path.open("x", encoding="utf-8") as handle:
        json.dump(registry, handle)
    return path


def classify_bridge_connections(bridge: dict, service_endpoint: tuple[str, int]) -> dict:
    """Classify one identity-verified process snapshot; never pool connections across PIDs."""
    if not isinstance(bridge, dict):
        return {"pid": None, "accepted": False, "reason": "invalid_bridge_snapshot", "connections": []}
    pid, connections = bridge.get("pid"), bridge.get("connections")
    if type(pid) is not int or pid <= 0 or not isinstance(connections, list) or not connections:
        return {"pid": pid, "accepted": False, "reason": "invalid_bridge_snapshot", "connections": []}

    def local_tcp(row):
        return (isinstance(row, dict) and row.get("family") == "AF_INET"
                and row.get("type") == "SOCK_STREAM" and row.get("status") == "ESTABLISHED"
                and row.get("local_ip") == row.get("ip") == "127.0.0.1"
                and all(type(row.get(key)) is int and 1 <= row[key] <= 65535 for key in ("local_port", "port")))

    classified = []
    for index, row in enumerate(connections):
        reason, peer = "rejected_socket", None
        if local_tcp(row):
            if (row["ip"], row["port"]) == service_endpoint:
                reason = "explicit_service_endpoint"
            elif row["local_port"] != row["port"]:
                peer = next((other_index for other_index, other in enumerate(connections)
                             if other_index != index and local_tcp(other)
                             and (row["local_ip"], row["local_port"], row["ip"], row["port"])
                             == (other["ip"], other["port"], other["local_ip"], other["local_port"])), None)
                if peer is not None:
                    reason = "reciprocal_same_pid_tcp_ipc"
        classified.append({"connection": row, "accepted": reason != "rejected_socket", "reason": reason,
                           "peer_index": peer})
    return {"pid": pid, "expected_service_endpoint": service_endpoint,
            "accepted": all(row["accepted"] for row in classified), "connections": classified}


def python_guard_source() -> str:
    return '''import json, os, socket, threading

_ALLOWED = {tuple(x) for x in json.loads(os.environ.get("PALLIUM_TUI_ALLOWED_ENDPOINTS", "[]"))}
assert _ALLOWED and all(host == "127.0.0.1" and type(port) is int and 0 < port < 65536 for host, port in _ALLOWED)
_LOG = os.environ.get("PALLIUM_TUI_EGRESS_LOG")
_IPC_LOG = os.environ.get("PALLIUM_TUI_IPC_LOG")
_ipc = threading.local()
def _record(path, row):
    if path:
        with open(path, "a", encoding="utf-8") as f: f.write(json.dumps(row) + "\\n")
def _allowed(address):
    return isinstance(address, tuple) and len(address) >= 2 and (str(address[0]), int(address[1])) in _ALLOWED
def _deny(address):
    if getattr(_ipc, "active", False) and address[0] in ("127.0.0.1", "::1"):
        _record(_IPC_LOG, {"kind": "stdlib_socketpair", "address": repr(address)})
        return
    if not _allowed(address):
        _record(_LOG, {"address": repr(address)})
        raise PermissionError("Hermes TUI qualification blocked a non-allowlisted socket destination")
_orig_connect, _orig_connect_ex = socket.socket.connect, socket.socket.connect_ex
_orig_getaddrinfo, _orig_socketpair = socket.getaddrinfo, socket.socketpair
def _connect(self, address):
    if self.type & socket.SOCK_DGRAM: return _sendto(self, address)
    _deny(address)
    return _orig_connect(self, address)
def _connect_ex(self, address):
    if self.type & socket.SOCK_DGRAM: return _sendto(self, address)
    _deny(address)
    return _orig_connect_ex(self, address)
def _getaddrinfo(host, port, *args, **kwargs):
    _deny((host, port))
    return _orig_getaddrinfo(host, port, *args, **kwargs)
def _socketpair(*args, **kwargs):
    # Windows stdlib's peer-validated socketpair is asyncio IPC, with a temporary local TCP port.
    previous = getattr(_ipc, "active", False)
    _ipc.active = True
    try: return _orig_socketpair(*args, **kwargs)
    finally: _ipc.active = previous
def _sendto(self, *args, **kwargs):
    _record(_LOG, {"kind": "udp", "address": repr(args)})
    raise PermissionError("Hermes TUI qualification blocked UDP")
socket.socket.connect, socket.socket.connect_ex = _connect, _connect_ex
socket.getaddrinfo, socket.socketpair, socket.socket.sendto = _getaddrinfo, _socketpair, _sendto
if os.name == "nt":
    from asyncio.proactor_events import BaseProactorEventLoop
    from asyncio.windows_events import IocpProactor
    _original_sock_connect = BaseProactorEventLoop.sock_connect
    _original_iocp_connect = IocpProactor.connect
    async def _async_sock_connect(self, sock, address):
        if sock.type & socket.SOCK_DGRAM: return _sendto(sock, address)
        _deny(address)
        return await _original_sock_connect(self, sock, address)
    def _iocp_connect(self, sock, address):
        if sock.type & socket.SOCK_DGRAM: return _sendto(sock, address)
        _deny(address)
        return _original_iocp_connect(self, sock, address)
    BaseProactorEventLoop.sock_connect = _async_sock_connect
    IocpProactor.connect = _iocp_connect
'''


def node_preload_source() -> str:
    return '''const fs = require("node:fs");
const log = process.env.PALLIUM_TUI_EGRESS_LOG;
function deny(kind, target) {
  if (log) fs.appendFileSync(log, JSON.stringify({kind, target: String(target)}) + "\\n");
  throw new Error("Hermes TUI qualification blocked Node network access");
}
const net = require("node:net");
net.Socket.prototype.connect = function(...args) { return deny("socket", args[0]); };
net.Server.prototype.listen = function(...args) { return deny("listen", args[0]); };
const tls = require("node:tls");
tls.connect = (...args) => deny("tls", args[0]);
const dgram = require("node:dgram");
for (const method of ["send", "connect", "bind"]) dgram.Socket.prototype[method] = function(...args) { return deny("dgram", args[0]); };
for (const name of ["node:http", "node:https"]) {
  const mod = require(name);
  mod.request = (...args) => deny(name, args[0]);
  mod.get = (...args) => deny(name, args[0]);
}
globalThis.fetch = async (...args) => deny("fetch", args[0]);
globalThis.WebSocket = class { constructor(url) { return deny("WebSocket", url); } };
require("node:http2").connect = (...args) => deny("http2", args[0]);
for (const name of ["node:dns", "node:dns/promises"]) {
  const dns = require(name);
  for (const key of Object.keys(dns)) if (/^(lookup|resolve|reverse)/.test(key)) dns[key] = (...args) => deny("dns", args[0]);
  for (const key of Object.getOwnPropertyNames(dns.Resolver.prototype)) if (/^(lookup|resolve|reverse)/.test(key)) dns.Resolver.prototype[key] = (...args) => deny("dns", args[0]);
}
'''


def isolated_env(home: Path, *, source: Path, python: Path, node: Path,
                 guard_dir: Path, preload: Path, egress_log: Path,
                 endpoints: list[tuple[str, int]]) -> dict[str, str]:
    systemroot = os.environ["SYSTEMROOT"]
    env = {
        "SYSTEMROOT": systemroot,
        "WINDIR": systemroot,
        "COMSPEC": str(Path(systemroot) / "System32" / "cmd.exe"),
        "PATH": os.pathsep.join((str(Path(systemroot) / "System32"), str(node.parent), str(python.parent))),
        "PATHEXT": ".COM;.EXE;.BAT;.CMD",
        "OS": "Windows_NT",
        "HOME": str(home),
        "USERPROFILE": str(home),
        "HOMEDRIVE": home.drive,
        "HOMEPATH": str(home)[len(home.drive):],
        "APPDATA": str(home / "AppData" / "Roaming"),
        "LOCALAPPDATA": str(home / "AppData" / "Local"),
        "TEMP": str(home / "Temp"),
        "TMP": str(home / "Temp"),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_DATA_HOME": str(home / ".local" / "share"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_STATE_HOME": str(home / ".local" / "state"),
        "HERMES_HOME": str(home / ".hermes"),
        "HERMES_PYTHON": str(python),
        "HERMES_TUI_DIR": str(source / "ui-tui"),
        "HERMES_NODE": str(node),
        "HERMES_TUI": "1",
        "HERMES_MANAGED_DIR": str(home / "managed-empty"),
        "HERMES_CWD": str(home / "scratch"),
        "TERM": "xterm-256color",
        "NO_COLOR": "1",
        "PYTHONUNBUFFERED": "1",
        "PYTHONPATH": os.pathsep.join((str(source), str(guard_dir))),
        "NODE_OPTIONS": f'--require="{preload.as_posix()}"',
        "PALLIUM_TUI_ALLOWED_ENDPOINTS": json.dumps(endpoints),
        "PALLIUM_TUI_EGRESS_LOG": str(egress_log),
        "PALLIUM_TUI_IPC_LOG": str(egress_log.with_name("local-ipc.jsonl")),
    }
    assert_isolated_env(env, home)
    return env


def assert_isolated_env(env: dict[str, str], home: Path) -> None:
    expected = {
        "HOME": home, "USERPROFILE": home,
        "APPDATA": home / "AppData" / "Roaming", "LOCALAPPDATA": home / "AppData" / "Local",
        "TEMP": home / "Temp", "TMP": home / "Temp",
        "XDG_CONFIG_HOME": home / ".config", "XDG_DATA_HOME": home / ".local" / "share",
        "XDG_CACHE_HOME": home / ".cache", "XDG_STATE_HOME": home / ".local" / "state",
        "HERMES_HOME": home / ".hermes",
        "HERMES_MANAGED_DIR": home / "managed-empty",
    }
    for key, path in expected.items():
        actual = Path(env[key]).resolve()
        assert actual.is_relative_to(home.resolve()) and actual == path.resolve(), (key, actual, path)
    assert not any(any(word in key.upper() for word in ("API_KEY", "TOKEN", "SECRET", "ACCESS_KEY", "SIDECAR", "ATTACH"))
                   for key in env), "credential or host-attachment variable passed to Hermes"


def verify_source(source: Path, expected_entry_sha256: str) -> str:
    """Accept only the two reviewed releases, a clean checkout, and the supplied bundle digest."""
    source = source.resolve()
    assert not (source / ".env").exists(), "Hermes project .env must be absent; ignored files can contain credentials"
    git = os.environ.get("PALLIUM_TUI_GIT", "git")
    revision = subprocess.run([git, "-C", str(source), "rev-parse", "HEAD"], check=True,
                              capture_output=True, text=True, timeout=10).stdout.strip()
    assert revision in RELEASES, f"unqualified Hermes revision: {revision}"
    status = subprocess.run([git, "-C", str(source), "status", "--porcelain", "--untracked-files=all"],
                            check=True, capture_output=True, text=True, timeout=10).stdout
    assert not status.strip(), f"Hermes source is not clean: {status}"
    assert re.fullmatch(r"[0-9a-fA-F]{64}", expected_entry_sha256), "explicit TUI bundle SHA-256 is required"
    entry = source / "ui-tui" / "dist" / "entry.js"
    assert hashlib.sha256(entry.read_bytes()).hexdigest().lower() == expected_entry_sha256.lower(), (
        "Hermes TUI bundle identity changed"
    )
    return RELEASES[revision]


def verify_runtimes(python: Path, node: Path, *, python_sha256: str, node_sha256: str,
                    python_base_sha256: str) -> dict[str, str]:
    """Check the explicitly selected interpreters by path, version and caller-supplied digest."""
    python, node = python.resolve(), node.resolve()
    assert python.is_file() and node.is_file(), "Hermes Python or Node prerequisite is missing"
    assert re.fullmatch(r"[0-9a-fA-F]{64}", python_sha256), "explicit Hermes Python SHA-256 is required"
    assert re.fullmatch(r"[0-9a-fA-F]{64}", node_sha256), "explicit Node SHA-256 is required"
    assert hashlib.sha256(python.read_bytes()).hexdigest().lower() == python_sha256.lower(), "Hermes Python identity changed"
    assert hashlib.sha256(node.read_bytes()).hexdigest().lower() == node_sha256.lower(), "Node identity changed"
    runtime_env = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR") if key in os.environ}
    py_info = json.loads(subprocess.run([str(python), "-I", "-S", "-c",
        "import json,sys; print(json.dumps({'version':'.'.join(map(str,sys.version_info[:3])),'base':sys._base_executable}))"],
        env=runtime_env, check=True, capture_output=True, text=True, timeout=10).stdout)
    py_version = py_info["version"]
    base = Path(py_info["base"]).resolve()
    assert re.fullmatch(r"[0-9a-fA-F]{64}", python_base_sha256), "explicit base Python SHA-256 is required"
    assert hashlib.sha256(base.read_bytes()).hexdigest().lower() == python_base_sha256.lower(), "base Python identity changed"
    node_version = subprocess.run([str(node), "--version"], check=True, capture_output=True,
                                  env=runtime_env, text=True, timeout=10).stdout.strip()
    assert re.fullmatch(r"3\.14\.\d+", py_version), f"unsupported Hermes Python runtime: {py_version}"
    assert re.fullmatch(r"v\d+\.\d+\.\d+", node_version), f"unrecognized Node runtime: {node_version}"
    return {"python_version": py_version, "python_base": str(base), "python_base_sha256": python_base_sha256,
            "python_launcher_sha256": python_sha256, "node_version": node_version, "node_sha256": node_sha256}


def self_check_guards(root: Path, node: Path, python: Path | None = None) -> None:
    """Prove child-level guards only; this is not an OS or network sandbox."""
    import socket

    interpreter = str(python or sys.executable)
    root.mkdir(parents=True, exist_ok=True)
    guard_dir = root / "python-guard"
    guard_dir.mkdir(parents=True, exist_ok=True)
    (guard_dir / "sitecustomize.py").write_text(python_guard_source(), encoding="utf-8")
    preload = root / "node-deny.cjs"
    preload.write_text(node_preload_source(), encoding="utf-8")
    audit = root / "egress-attempts.jsonl"
    home = root / "profile"
    for folder in ("Temp", "AppData/Roaming", "AppData/Local", ".config", ".local/share", ".cache", ".local/state"):
        (home / folder).mkdir(parents=True, exist_ok=True)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        allowed = [("127.0.0.1", port)]
    env = {
        "SYSTEMROOT": os.environ["SYSTEMROOT"],
        "PATH": os.pathsep.join((str(Path(os.environ["SYSTEMROOT"]) / "System32"), str(node.parent))),
        "HOME": str(home), "USERPROFILE": str(home),
        "APPDATA": str(home / "AppData/Roaming"), "LOCALAPPDATA": str(home / "AppData/Local"),
        "TEMP": str(home / "Temp"), "TMP": str(home / "Temp"),
        "PYTHONPATH": str(guard_dir),
        "PALLIUM_TUI_ALLOWED_ENDPOINTS": json.dumps(allowed),
        "PALLIUM_TUI_EGRESS_LOG": str(audit),
        "PALLIUM_TUI_IPC_LOG": str(root / "local-ipc.jsonl"),
        "NODE_OPTIONS": f'--require="{preload.as_posix()}"',
    }
    allowed_check = subprocess.run(
        [interpreter, "-c", "import sitecustomize; assert sitecustomize._allowed(('127.0.0.1', int(__import__('json').loads(__import__('os').environ['PALLIUM_TUI_ALLOWED_ENDPOINTS'])[0][1]))); assert not sitecustomize._allowed(('127.0.0.1', 9)); assert not sitecustomize._allowed(('192.0.2.1', 9))"],
        env=env, capture_output=True, text=True, timeout=10,
    )
    assert allowed_check.returncode == 0, f"Python loopback allowlist self-check failed: {allowed_check.stderr}"
    denied = subprocess.run(
        [interpreter, "-c", "import socket;\ntry: socket.create_connection(('127.0.0.1',9))\nexcept PermissionError as e: assert 'blocked' in str(e)\nelse: raise AssertionError('socket was not blocked')"],
        env=env, capture_output=True, text=True, timeout=10,
    )
    assert denied.returncode == 0, f"Python socket guard self-check failed: {denied.stderr}"
    denied_external = subprocess.run(
        [interpreter, "-c", "import socket;\ntry: socket.create_connection(('192.0.2.1',9))\nexcept PermissionError as e: assert 'blocked' in str(e)\nelse: raise AssertionError('external socket was not blocked')"],
        env=env, capture_output=True, text=True, timeout=10,
    )
    assert denied_external.returncode == 0, f"Python non-loopback guard self-check failed: {denied_external.stderr}"
    ipc = subprocess.run([interpreter, "-c", '''import asyncio, socket, sitecustomize, os, json, threading
a, b = socket.socketpair()
address = a.getpeername()
a.close(); b.close()
if isinstance(address, tuple):
    try: socket.create_connection(address)
    except PermissionError: pass
    else: raise AssertionError("socketpair exception escaped its factory")
async def main():
    try: await asyncio.open_connection("127.0.0.1", 9)
    except PermissionError: pass
    else: raise AssertionError("async connection was not blocked")
    if os.name == "nt":
        original = sitecustomize._original_iocp_connect
        calls = []
        def forbidden(*args, **kwargs):
            calls.append(True)
            raise AssertionError("unapproved native ConnectEx ran")
        sitecustomize._original_iocp_connect = forbidden
        sock = socket.socket()
        try:
            try: await asyncio.get_running_loop().sock_connect(sock, ("127.0.0.1", 9))
            except PermissionError: pass
            else: raise AssertionError("Proactor socket connection was not blocked")
            try: asyncio.get_running_loop()._proactor.connect(sock, ("127.0.0.1", 9))
            except PermissionError: pass
            else: raise AssertionError("direct Proactor connection was not blocked")
            assert not calls
        finally:
            sock.close()
            sitecustomize._original_iocp_connect = original
    address = tuple(json.loads(os.environ["PALLIUM_TUI_ALLOWED_ENDPOINTS"])[0])
    listener = socket.socket(); listener.bind(address); listener.listen(1)
    def accept():
        conn, _ = listener.accept(); conn.close(); listener.close()
    thread = threading.Thread(target=accept); thread.start()
    _, writer = await asyncio.open_connection(*address)
    writer.close(); await writer.wait_closed(); thread.join(2)
    assert not thread.is_alive()
asyncio.run(main())
try: socket.getaddrinfo("example.invalid", 443)
except PermissionError: pass
else: raise AssertionError("external DNS was not blocked")
try: socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b"x", ("127.0.0.1", 9))
except PermissionError: pass
else: raise AssertionError("UDP was not blocked")
'''], env=env, capture_output=True, text=True, timeout=10)
    assert ipc.returncode == 0, f"Python asyncio/socketpair self-check failed: {ipc.stderr}"
    script = r'''(async()=>{const net=require("node:net");try{new net.Socket().connect(9,"127.0.0.1");throw Error("socket was not blocked")}catch(e){if(!String(e).includes("blocked"))throw e}try{await fetch("http://127.0.0.1:9");throw Error("fetch was not blocked")}catch(e){if(!String(e).includes("blocked"))throw e}try{new WebSocket("ws://127.0.0.1:9");throw Error("WebSocket was not blocked")}catch(e){if(!String(e).includes("blocked"))throw e}})().catch(e=>{console.error(e);process.exit(1)})'''
    node_check = subprocess.run([str(node), "-e", script], env=env, capture_output=True,
                                text=True, timeout=10)
    assert node_check.returncode == 0, f"Node network guard self-check failed: {node_check.stderr}"
    rows = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
    assert any("127.0.0.1" in row.get("address", "") for row in rows), rows
    assert {row.get("kind") for row in rows} >= {"socket", "fetch", "WebSocket"}, rows


ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][\s\S]*?(?:\x07|\x1b\\)")


class OwnedTree:
    """Retain process identity while the root lives, including children orphaned on exit."""

    def __init__(self, pid: int, executable: Path, *, ledger: Path | None = None):
        import psutil

        self.psutil = psutil
        self.root = psutil.Process(pid)
        self.identities = {}
        self.ledger = ledger
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.error = None
        self.record(self.root)
        self.thread = threading.Thread(target=self._monitor, daemon=True)
        self.thread.start()
        try:
            assert Path(self.root.exe()).resolve() == executable.resolve(), "unexpected owned executable"
        except BaseException:
            self.close()
            raise

    def record(self, proc):
        try:
            identity = (proc.create_time(), str(Path(proc.exe()).resolve()))
            with self.lock:
                if self.identities.get(proc.pid) == identity:
                    return
                self.identities[proc.pid] = identity
                if self.ledger is not None:
                    temporary = self.ledger.with_suffix(".tmp")
                    temporary.write_text(json.dumps([{"pid": pid, "birthtime": birth, "exe": exe}
                        for pid, (birth, exe) in self.identities.items()]), encoding="utf-8")
                    temporary.replace(self.ledger)
        except self.psutil.NoSuchProcess:
            pass

    def refresh(self):
        with self.lock:
            known = list(self.identities.items())
        for pid, (birth, executable) in known:
            try:
                proc = self.psutil.Process(pid)
                if proc.create_time() == birth and str(Path(proc.exe()).resolve()) == executable:
                    for child in proc.children(recursive=True):
                        self.record(child)
            except self.psutil.NoSuchProcess:
                pass

    def _monitor(self):
        while not self.stopped.wait(.05):
            try:
                self.refresh()
            except BaseException as exc:
                self.error = repr(exc)
                return

    def snapshot(self):
        self.refresh()
        rows = []
        with self.lock:
            known = list(self.identities.items())
        for pid, (birth, executable) in known:
            try:
                proc = self.psutil.Process(pid)
                if proc.create_time() == birth and str(Path(proc.exe()).resolve()) == executable:
                    rows.append({"pid": pid, "birthtime": birth, "exe": executable,
                                 "argv": proc.cmdline(), "env": proc.environ(),
                                 "connections": [{"ip": c.raddr.ip, "port": c.raddr.port,
                                                  "local_ip": c.laddr.ip, "local_port": c.laddr.port,
                                                  "family": c.family.name, "type": c.type.name,
                                                  "status": c.status}
                                                 for c in proc.net_connections() if c.raddr]})
            except self.psutil.NoSuchProcess:
                pass
        assert self.error is None, self.error
        return rows

    def close(self, *, include_root=True):
        # Stop the root first to prevent respawning; captured descendants remain independently owned.
        self.refresh()
        self.stopped.set()
        self.thread.join(2)
        with self.lock:
            known = list(self.identities.items())
        handles = []
        for pid, (birth, executable) in known:
            if not include_root and pid == self.root.pid:
                continue
            try:
                proc = self.psutil.Process(pid)
                assert proc.create_time() == birth and str(Path(proc.exe()).resolve()) == executable, (
                    "refusing cleanup after process identity changed", pid)
                handles.append(proc)
                proc.kill()
            except self.psutil.NoSuchProcess:
                pass
        _, alive = self.psutil.wait_procs(handles, timeout=8)
        assert not alive, f"owned processes survived cleanup: {[p.pid for p in alive]}"
        assert self.error is None, self.error


class TuiConsole:
    def __init__(self, python: Path, source: Path, home: Path, env: dict[str, str], artifacts: Path,
                 stopped: threading.Event, tree: OwnedTree):
        from winpty import PTY, Backend, WinptyError

        self.parts = []
        self.read_error = None
        self.pty_error = WinptyError
        self.artifacts = artifacts
        self.stopped = stopped
        preflight = (
            "import pathlib,runpy,sys,socket,sitecustomize;"
            "assert socket.socket.connect is sitecustomize._connect;"
            f"assert pathlib.Path(sys.executable).resolve()==pathlib.Path({str(python)!r}).resolve();"
            "assert sys.version_info[:2]==(3,14);"
            f"assert pathlib.Path.home().resolve()==pathlib.Path({str(home)!r}).resolve();"
            "print('PALLIUM_TUI_CHILD_PREFLIGHT_OK',flush=True);"
            "sys.argv=['hermes','--tui'];runpy.run_module('hermes_cli.main',run_name='__main__')"
        )
        # The public low-level API avoids PtyProcess's extra unauthenticated TCP reader wrapper.
        self.tree = tree
        self.proc = PTY(200, 55, backend=Backend.ConPTY, timeout=30_000)
        assert self.proc.spawn(str(python), cmdline=" " + subprocess.list2cmdline(["-c", preflight]),
                               cwd=str(home / "scratch"),
                               env="\0".join(f"{key}={value}" for key, value in env.items()) + "\0")
        tree.refresh()
        child = next(row for row in tree.snapshot() if row["pid"] == self.proc.pid)
        assert Path(child["exe"]).resolve() == python.resolve(), "unexpected ConPTY executable"
        self.reader = threading.Thread(target=self._pump, daemon=True)
        self.reader.start()

    def _pump(self):
        while True:
            try:
                chunk = self.proc.read(blocking=False)
                if chunk:
                    self.parts.append(chunk)
                elif not self.proc.isalive():
                    return
                else:
                    time.sleep(.03)
            except (EOFError, OSError, self.pty_error) as exc:
                self.read_error = repr(exc)
                return

    @property
    def raw_text(self):
        return "".join(self.parts)

    @property
    def text(self):
        return ANSI.sub("", self.raw_text)

    def wait(self, expected: str, *, after: int = 0, timeout: float = 90):
        """Keep cursors in raw output; completing an escape sequence can shrink normalized text."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            assert not self.stopped.is_set(), "driver shutdown requested"
            if expected in ANSI.sub("", self.raw_text[after:]):
                return
            assert self.proc.isalive(), f"TUI exited early: {self.read_error}; {self.text[-2000:]}"
            assert self.tree.error is None, self.tree.error
            time.sleep(.1)
        raise TimeoutError(f"TUI did not render {expected!r}: {self.text[-3000:]}")

    def submit(self, prompt: str, *, marker: str):
        prompt.encode("utf-8", errors="strict")
        assert marker and marker.isascii() and marker in prompt, "expected a unique visible ASCII input marker"
        offset = len(self.raw_text)
        self.proc.write(prompt)
        # Ink redraws and grapheme wrapping can split the echoed Unicode input; the provider checks it in full.
        self.wait(marker, after=offset, timeout=20)
        self.proc.write("\r")

    def close(self):
        self.proc.cancel_io()
        self.reader.join(2)
        (self.artifacts / "terminal.txt").write_text("".join(self.parts), encoding="utf-8", errors="backslashreplace")


def driver_main(spec_path: Path):
    """The explicit disposable 3.14 interpreter alone imports ConPTY and starts the real UI."""
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    home, source, python = (Path(spec[key]).resolve() for key in ("home", "source", "python"))
    assert Path(sys.executable).resolve() == python and sys.version_info[:2] == (3, 14)
    assert Path(sys._base_executable).resolve() == Path(spec["python_base"])
    assert hashlib.sha256(Path(sys._base_executable).read_bytes()).hexdigest() == spec["python_base_sha256"].lower()
    assert Path.cwd().resolve() == home / "scratch"
    assert_isolated_env(dict(os.environ), home)
    import socket
    import sitecustomize
    assert Path(sitecustomize.__file__).resolve() == Path(os.environ["PYTHONPATH"].split(os.pathsep)[-1]) / "sitecustomize.py"
    assert socket.socket.connect is sitecustomize._connect
    verify_source(source, spec["bundle_sha256"])
    import psutil
    import queue

    # Capture the still-live caller identity before launching ConPTY; venv redirectors may add a parent.
    parent = next(proc for proc in psutil.Process().parents() if proc.pid == spec["parent_pid"])
    parent_identity = (parent.create_time(), parent.exe())
    current = psutil.Process()
    ancestors = []
    for ancestor in current.parents():
        if ancestor.pid == parent.pid:
            break
        ancestors.append(ancestor)
    launcher = ancestors[-1] if ancestors else current
    assert Path(launcher.exe()).resolve() == python, "unexpected driver launcher"
    (spec_path.parent / "driver-identity.json").write_text(json.dumps({
        "pid": current.pid, "birthtime": current.create_time(), "exe": current.exe(),
        "launcher_pid": launcher.pid, "launcher_birthtime": launcher.create_time(), "launcher_exe": launcher.exe(),
        "parent_pid": parent.pid, "parent_birthtime": parent_identity[0], "parent_exe": parent_identity[1],
    }), encoding="utf-8")
    stopped = threading.Event()
    commands = queue.Queue()

    def read_commands():
        try:
            for line in sys.stdin:
                commands.put(json.loads(line))
        finally:
            stopped.set()

    def watchdog():
        deadline = time.monotonic() + 12 * 60
        while not stopped.wait(.2):
            try:
                current = psutil.Process(parent.pid)
                alive = (current.create_time(), current.exe()) == parent_identity
            except psutil.NoSuchProcess:
                alive = False
            if not alive or time.monotonic() >= deadline:
                stopped.set()

    threading.Thread(target=read_commands, daemon=True).start()
    threading.Thread(target=watchdog, daemon=True).start()
    # Own the entire driver subtree before any ConPTY constructor or spawn can fail.
    tree = OwnedTree(os.getpid(), Path(sys._base_executable), ledger=spec_path.parent / "owned-processes-ledger.json")
    console = None
    try:
        console = TuiConsole(python, source, home, dict(os.environ), spec_path.parent, stopped, tree)
        # Both released versions expose this normal composer placeholder.
        deadline = time.monotonic() + 60
        while not any(token in console.text for token in ("Ask me anything", 'Try "')):
            assert not stopped.is_set() and time.monotonic() < deadline and console.proc.isalive(), console.text[-3000:]
            time.sleep(.1)
        console.wait("ready │", timeout=90)
        print(json.dumps({"ready": True}), flush=True)
        while not stopped.is_set():
            try:
                command = commands.get(timeout=.2)
            except queue.Empty:
                continue
            op = command["op"]
            if op == "submit":
                console.submit(command["text"], marker=command["marker"])
            elif op == "wait":
                console.wait(command["text"], timeout=command.get("timeout", 90))
            elif op == "new":
                offset = len(console.raw_text)
                console.submit("/new", marker="/new")
                console.wait("Start a new session?", after=offset, timeout=20)
                # Both released ConfirmPrompt implementations expose the normal affirmative 'y' shortcut.
                console.proc.write("y")
                console.wait("new session started", after=offset, timeout=30)
                console.wait("ready │", after=offset, timeout=60)
            elif op == "inspect":
                print(json.dumps({"processes": console.tree.snapshot()}), flush=True)
                continue
            elif op == "close":
                stopped.set()
                break
            else:
                raise AssertionError(f"unknown driver operation: {op}")
            print(json.dumps({"ok": op}), flush=True)
    finally:
        stopped.set()
        try:
            try:
                tree.close(include_root=False)
            finally:
                if console is not None:
                    console.close()
        finally:
            verify_source(source, spec["bundle_sha256"])


def cleanup_ledger(path: Path):
    """Recovery process checks saved identities after a failed driver, including orphaned children."""
    import psutil

    assert sys.version_info[:2] == (3, 14), "ownership recovery requires the explicit Hermes interpreter"
    handles = []
    for row in json.loads(path.read_text(encoding="utf-8")):
        try:
            proc = psutil.Process(row["pid"])
            if (proc.create_time() == row["birthtime"]
                    and Path(proc.exe()).resolve() == Path(row["exe"]).resolve()):
                handles.append(proc)
        except psutil.NoSuchProcess:
            pass
    for proc in handles:
        try:
            proc.kill()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(handles, timeout=8)
    assert not alive, f"retained owned processes survived recovery: {[proc.pid for proc in alive]}"
    return {"recovered": [proc.pid for proc in handles], "alive": []}


def stop_owned_driver(proc, python: Path, helper: Path, artifacts: Path, env, *, grace=15):
    """Use the owned Popen handle, then exact process identity and System32 tree termination on timeout."""
    forced = False
    try:
        if proc.poll() is None:
            proc.stdin.close()
            try:
                proc.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                forced = True
                identity = artifacts / "driver-identity.json"
                check = '''import json,pathlib,psutil,sys
row=json.loads(pathlib.Path(sys.argv[1]).read_text())
proc=psutil.Process(int(sys.argv[2]))
assert proc.pid==row["launcher_pid"] and proc.create_time()==row["launcher_birthtime"]
assert pathlib.Path(proc.exe()).resolve()==pathlib.Path(row["launcher_exe"]).resolve()
'''
                try:
                    subprocess.run([str(python), "-I", "-c", check, str(identity), str(proc.pid)], env=env,
                                   capture_output=True, check=True, timeout=10)
                except BaseException:
                    # The Popen handle owns this root even before the ledger initializes.
                    proc.kill()
                    proc.wait(timeout=8)
                    raise
                if proc.poll() is None:
                    subprocess.run([str(Path(os.environ["SYSTEMROOT"]) / "System32" / "taskkill.exe"),
                                    "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=10, check=False)
                    proc.wait(timeout=8)
    finally:
        ledger = artifacts / "owned-processes-ledger.json"
        if ledger.exists():
            recovery = subprocess.run([str(python), "-I", str(helper), "--cleanup-owned", str(ledger)],
                                      env=env, capture_output=True, text=True, timeout=15, check=True)
            recovered = json.loads(recovery.stdout)
            if proc.poll() is None:
                proc.wait(timeout=8)
        else:
            assert not (artifacts / "driver-identity.json").exists(), "driver started without a durable ownership ledger"
            recovered = {"recovered": [], "alive": []}
    return {"forced": forced, **recovered}


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--cleanup-owned":
        print(json.dumps(cleanup_ledger(Path(sys.argv[2]))), flush=True)
    else:
        assert len(sys.argv) == 2, "expected an explicit native driver specification"
        driver_main(Path(sys.argv[1]))
