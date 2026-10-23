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
from urllib.parse import urlsplit

RELEASES = {
    "e06df9c2eae6901f4c88f464e0ae6e753c0428b8": "0.22.0",
    "d923a5eb487a17c0a68801bba9ef0f56c81040a8": "0.22.2",
    "4d04303818b61bf3aa09278af48356315515965b": "0.22.4",
}

SYNTHETIC_OPENAI_API_KEY = "pallium-hermes-synthetic-openai-key"


def canonical_rpc(ws, method, params, *, timeout=3):
    """One bounded canonical request; notifications never substitute for its exact reply."""
    import uuid

    request_id = uuid.uuid4().hex
    ws.send(json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        frame = json.loads(ws.recv(timeout=max(.01, deadline - time.monotonic())))
        if frame.get("id") is None:
            continue
        assert frame["id"] == request_id, (method, frame)
        assert "error" not in frame, (method, frame)
        assert isinstance(frame.get("result"), dict), (method, frame)
        return frame["result"]
    raise TimeoutError(f"canonical {method} response timed out")


def canonical_authority_ready(ws, deadline):
    while time.monotonic() < deadline:
        frame = json.loads(ws.recv(timeout=max(.01, deadline - time.monotonic())))
        if frame.get("method") == "event" and frame.get("params", {}).get("type") == "gateway.ready":
            assert frame["params"]["payload"].get("session_authority") is True, frame
            return
    raise TimeoutError("ticketed canonical socket did not report session authority")


def canonical_same_session(result, session_id):
    assert isinstance(result, dict) and result.get("session_id") == session_id, result
    return result


def canonical_completed_detach(result, session_id, elapsed):
    canonical_same_session(result, session_id)
    assert result.get("detached") is True, result
    # The pinned gateway's 10s finalize timeout leaves its worker running.
    assert type(elapsed) in (int, float) and 0 <= elapsed < 9.0, elapsed
    return elapsed


def canonical_terminal_receipt(ws, session_id, admission_id, deadline):
    while time.monotonic() < deadline:
        receipt = canonical_rpc(ws, "prompt.receipt", {"session_id": session_id,
            "admission_id": admission_id}, timeout=min(1, max(.1, deadline - time.monotonic())))
        assert receipt.get("admission_id") == admission_id, receipt
        if receipt.get("status") == "terminal":
            assert receipt.get("outcome") == "completed", receipt
            assert receipt.get("ref", {}).get("session_id") == session_id, receipt
            return receipt
        time.sleep(.04)
    raise TimeoutError("canonical prompt did not reach successful terminal receipt")


def synthetic_openai_environment(base_url: str) -> dict[str, str]:
    parsed = urlsplit(base_url)
    assert (parsed.scheme == "http" and parsed.hostname == "127.0.0.1" and parsed.port
            and parsed.path == "/v1" and not parsed.query and not parsed.fragment and not parsed.username
            and not parsed.password), "built-in provider must use the numeric loopback v1 endpoint"
    return {"OPENAI_API_KEY": SYNTHETIC_OPENAI_API_KEY, "OPENAI_BASE_URL": base_url}


def assert_synthetic_openai_environment(env: dict[str, str], expected_url: str | None = None) -> None:
    key, url = env.get("OPENAI_API_KEY"), env.get("OPENAI_BASE_URL")
    assert (key is None) == (url is None), "synthetic OpenAI key and URL must be selected together"
    if key is None:
        return
    assert key == SYNTHETIC_OPENAI_API_KEY, "unexpected OpenAI credential in isolated environment"
    expected = synthetic_openai_environment(url)
    assert expected["OPENAI_BASE_URL"] == url
    if expected_url is not None:
        assert url == expected_url, "OpenAI URL must name this journey's owned provider"
    try:
        endpoints = json.loads(env["PALLIUM_TUI_ALLOWED_ENDPOINTS"])
    except (KeyError, json.JSONDecodeError) as exc:
        raise AssertionError("isolated provider endpoint allowlist is missing or malformed") from exc
    assert ["127.0.0.1", urlsplit(url).port] in endpoints, "OpenAI URL is outside the owned endpoint allowlist"


def synthetic_openai_request_evidence(path: str, body: dict, authorization: str | None) -> dict[str, object]:
    assert path == "/v1/chat/completions", f"unexpected built-in provider route: {path}"
    assert body.get("model") == "pallium-local", f"unexpected built-in provider model: {body.get('model')}"
    return {"path": path, "model": body["model"],
            "auth_matched": authorization == f"Bearer {SYNTHETIC_OPENAI_API_KEY}"}


def seed_models_dev_cache(profile: Path) -> Path:
    """Use the native provider/models/limit disk shape; a fresh cache avoids registry startup I/O."""
    registry = {"local": {"id": "local", "name": "Synthetic local provider", "models": {
        "pallium-local": {"id": "pallium-local", "limit": {"context": 128000, "output": 4096}},
    }}}
    path = profile / "models_dev_cache.json"
    with path.open("x", encoding="utf-8") as handle:
        json.dump(registry, handle)
    return path


def classify_bridge_connections(bridge: dict, service_endpoint: tuple[str, int], *,
                                collected_successfully: bool = False,
                                require_successful_snapshot: bool = False) -> dict:
    """Classify one identity-verified process snapshot; never pool connections across PIDs."""
    if not isinstance(bridge, dict):
        return {"pid": None, "accepted": False, "reason": "invalid_bridge_snapshot", "connections": []}
    pid, connections = bridge.get("pid"), bridge.get("connections")
    if type(pid) is not int or pid <= 0 or not isinstance(connections, list):
        return {"pid": pid, "accepted": False, "reason": "invalid_bridge_snapshot", "connections": []}
    if require_successful_snapshot and not collected_successfully:
        return {"pid": pid, "accepted": False, "reason": "invalid_bridge_snapshot", "connections": []}
    if not connections:
        accepted = collected_successfully
        return {"pid": pid, "expected_service_endpoint": service_endpoint, "accepted": accepted,
                "reason": "no_observed_remote_sockets" if accepted else "invalid_bridge_snapshot",
                "connections": []}

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
    return '''import json, os, socket, stat, threading
from pathlib import Path

def _configuration():
    try:
        raw = json.loads(os.environ["PALLIUM_TUI_ALLOWED_ENDPOINTS"])
        if not isinstance(raw, list) or not raw:
            raise ValueError()
        allowed = set()
        for row in raw:
            if (not isinstance(row, list) or len(row) != 2 or row[0] != "127.0.0.1"
                    or type(row[1]) is not int or not 1 <= row[1] <= 65535):
                raise ValueError()
            allowed.add((row[0], row[1]))
        control_raw = json.loads(os.environ.get("PALLIUM_TUI_ALLOWED_CONTROL_PATHS", "[]"))
        if not isinstance(control_raw, list) or (control_raw and os.name == "nt"):
            raise ValueError()
        controls = set()
        for raw_path in control_raw:
            if not isinstance(raw_path, str) or not raw_path or not Path(raw_path).is_absolute():
                raise ValueError()
            path = Path(raw_path)
            if str(path.resolve(strict=False)) != raw_path:
                raise ValueError()
            controls.add(raw_path)
        return allowed, controls
    except BaseException:
        os._exit(78)

_ALLOWED, _CONTROL_PATHS = _configuration()
_LOG = os.environ.get("PALLIUM_TUI_EGRESS_LOG")
_IPC_LOG = os.environ.get("PALLIUM_TUI_IPC_LOG")
_ipc = threading.local()
def _record(path, row):
    if path:
        with open(path, "a", encoding="utf-8") as f: f.write(json.dumps(row) + "\\n")
def _allowed(address):
    return isinstance(address, tuple) and len(address) >= 2 and (str(address[0]), int(address[1])) in _ALLOWED
def _allowed_control(sock, address):
    if not (sock is not None and sock.family == getattr(socket, "AF_UNIX", None)
            and sock.type == socket.SOCK_STREAM and isinstance(address, str) and address in _CONTROL_PATHS):
        return False
    try:
        path = Path(address)
        parent, node = path.parent.lstat(), path.lstat()
        return (str(path.resolve(strict=True)) == address
                and stat.S_ISDIR(parent.st_mode) and parent.st_uid == os.getuid()
                and stat.S_IMODE(parent.st_mode) == 0o700
                and stat.S_ISSOCK(node.st_mode) and node.st_uid == os.getuid()
                and stat.S_IMODE(node.st_mode) == 0o600)
    except (OSError, RuntimeError):
        return False
def _deny(address, sock=None):
    if _allowed_control(sock, address): return
    if (getattr(_ipc, "active", False) and isinstance(address, tuple) and address
            and address[0] in ("127.0.0.1", "::1")):
        _record(_IPC_LOG, {"kind": "stdlib_socketpair", "address": repr(address)})
        return
    if not _allowed(address):
        _record(_LOG, {"address": repr(address)})
        raise PermissionError("Hermes TUI qualification blocked a non-allowlisted socket destination")
_orig_connect, _orig_connect_ex = socket.socket.connect, socket.socket.connect_ex
_orig_getaddrinfo, _orig_socketpair = socket.getaddrinfo, socket.socketpair
def _connect(self, address):
    if self.type & socket.SOCK_DGRAM: return _sendto(self, address)
    _deny(address, self)
    return _orig_connect(self, address)
def _connect_ex(self, address):
    if self.type & socket.SOCK_DGRAM: return _sendto(self, address)
    _deny(address, self)
    return _orig_connect_ex(self, address)
def _getaddrinfo(host, port, *args, **kwargs):
    if type(host) is str and host == "127.0.0.1" and type(port) is int and port == 0:
        return _orig_getaddrinfo(host, port, *args, **kwargs)
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
        _deny(address, sock)
        return await _original_sock_connect(self, sock, address)
    def _iocp_connect(self, sock, address):
        if sock.type & socket.SOCK_DGRAM: return _sendto(sock, address)
        _deny(address, sock)
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
const rawGateway = process.env.PALLIUM_TUI_GATEWAY_WS;
let gateway = null, gatewayPort = null;
if (rawGateway !== undefined) {
  const match = /^ws:\\/\\/127\\.0\\.0\\.1:([1-9][0-9]{0,4})\\/api\\/ws$/.exec(rawGateway);
  if (!match || match[0] !== rawGateway || Number(match[1]) > 65535) process.exit(78);
  gateway = rawGateway;
  gatewayPort = Number(match[1]);
}
const net = require("node:net");
const originalConnect = net.Socket.prototype.connect;
function exactGatewayConnect(args) {
  if (args.length === 1 && Array.isArray(args[0])) args = args[0];
  if (args.length && typeof args[args.length - 1] === "function") args = args.slice(0, -1);
  if (args.length < 1 || args.length > 2) return false;
  const first = args[0];
  let host, port;
  if (first && typeof first === "object" && !Array.isArray(first)) {
    if (first.path !== undefined || first.socketPath !== undefined || first.lookup !== undefined
        || (first.localAddress !== undefined && first.localAddress !== null) || first.localPort !== undefined
        || (first.family !== undefined && first.family !== 4)
        || (first.host !== undefined && first.hostname !== undefined && first.host !== first.hostname)) return false;
    host = first.host === undefined ? first.hostname : first.host;
    port = first.port;
  } else if (typeof first === "number" && typeof args[1] === "string") {
    port = first;
    host = args[1];
  } else {
    return false;
  }
  return !!gateway && host === "127.0.0.1" && (port === gatewayPort || port === String(gatewayPort));
}
net.Socket.prototype.connect = function(...args) {
  if (!exactGatewayConnect(args)) return deny("socket", args[0]);
  return originalConnect.apply(this, args);
};
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
const OriginalWebSocket = globalThis.WebSocket;
if (typeof OriginalWebSocket === "function") {
  globalThis.WebSocket = class extends OriginalWebSocket {
    constructor(url, protocols) {
      const ticket = Array.isArray(protocols) && protocols.length === 2
        && protocols[0] === "hermes-gateway-v1" && typeof protocols[1] === "string"
        ? /^hermes-gateway-ticket\\.[A-Za-z0-9_-]{1,4096}$/.exec(protocols[1]) : null;
      if (!gateway || typeof url !== "string" || url !== gateway || !ticket || ticket[0] !== protocols[1])
        return deny("WebSocket", url);
      super(url, protocols);
    }
  };
} else {
  globalThis.WebSocket = class { constructor(url) { return deny("WebSocket", url); } };
}
require("node:http2").connect = (...args) => deny("http2", args[0]);
for (const name of ["node:dns", "node:dns/promises"]) {
  const dns = require(name);
  for (const key of Object.keys(dns)) if (/^(lookup|resolve|reverse)/.test(key)) dns[key] = (...args) => deny("dns", args[0]);
  for (const key of Object.getOwnPropertyNames(dns.Resolver.prototype)) if (/^(lookup|resolve|reverse)/.test(key)) dns.Resolver.prototype[key] = (...args) => deny("dns", args[0]);
}
'''


def isolated_env(home: Path, *, source: Path, python: Path, node: Path,
                 guard_dir: Path, preload: Path, egress_log: Path,
                 endpoints: list[tuple[str, int]], openai_base_url: str | None = None) -> dict[str, str]:
    if os.name != "nt":
        from tests.fixtures.hermes_linux_guard import require_contained_paths, require_linux_qualification

        require_linux_qualification()
        require_contained_paths(home, source, python, node, guard_dir, preload, egress_log)
        env = {
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": str(home), "TMPDIR": str(home / "Temp"),
            "XDG_CONFIG_HOME": str(home / ".config"), "XDG_DATA_HOME": str(home / ".local/share"),
            "XDG_CACHE_HOME": str(home / ".cache"), "XDG_STATE_HOME": str(home / ".local/state"),
            "HERMES_HOME": str(home / "hermes-profile"), "HERMES_PYTHON": str(python),
            "HERMES_TUI_DIR": str(source / "ui-tui"), "HERMES_NODE": str(node), "HERMES_TUI": "1",
            "HERMES_MANAGED_DIR": str(home / "managed-empty"), "HERMES_CWD": str(home / "scratch"),
            "TERM": "xterm-256color", "NO_COLOR": "1", "PYTHONUNBUFFERED": "1",
            "PYTHONPATH": os.pathsep.join((str(source), str(guard_dir))),
            "NODE_OPTIONS": f'--require="{preload.as_posix()}"',
            "PALLIUM_TUI_ALLOWED_ENDPOINTS": json.dumps(endpoints),
            "PALLIUM_TUI_EGRESS_LOG": str(egress_log),
            "PALLIUM_TUI_IPC_LOG": str(egress_log.with_name("local-ipc.jsonl")),
            "PALLIUM_LINUX_QUALIFICATION_ROOT": os.environ["PALLIUM_LINUX_QUALIFICATION_ROOT"],
            "PALLIUM_LINUX_QUALIFICATION_MANIFEST": os.environ["PALLIUM_LINUX_QUALIFICATION_MANIFEST"],
        }
        if openai_base_url is not None:
            env.update(synthetic_openai_environment(openai_base_url))
        assert_isolated_env(env, home, openai_base_url=openai_base_url)
        return env
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


def assert_isolated_env(env: dict[str, str], home: Path, *, openai_base_url: str | None = None) -> None:
    if os.name != "nt":
        expected = {
            "HOME": home, "TMPDIR": home / "Temp", "XDG_CONFIG_HOME": home / ".config",
            "XDG_DATA_HOME": home / ".local" / "share", "XDG_CACHE_HOME": home / ".cache",
            "XDG_STATE_HOME": home / ".local" / "state", "HERMES_HOME": home / "hermes-profile",
            "HERMES_MANAGED_DIR": home / "managed-empty",
        }
        assert env["LANG"] == env["LC_ALL"] == "C.UTF-8"
        assert env["PATH"] == "/usr/local/bin:/usr/bin:/bin"
        for key, path in expected.items():
            actual = Path(env[key]).resolve()
            assert actual.is_relative_to(home.resolve()) and actual == path.resolve(), (key, actual, path)
        default_hermes_home = (home / ".hermes").resolve()
        hermes_home = Path(env["HERMES_HOME"]).resolve()
        assert not hermes_home.is_relative_to(default_hermes_home), "synthetic Hermes home collides with platform default"
        assert (hermes_home / "state.db").resolve().is_relative_to(home.resolve())
        assert "HERMES_STATE_DB_GUARD_BYPASS" not in env, "do not disable Hermes's live-DB safety guard"
        assert_synthetic_openai_environment(env, openai_base_url)
        assert not any(any(word in key.upper() for word in (
            "API_KEY", "TOKEN", "SECRET", "ACCESS_KEY", "SIDECAR", "ATTACH"))
                        and key != "OPENAI_API_KEY" for key in env), (
                "credential or host-attachment variable passed to Hermes")
        return
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
    assert "OPENAI_API_KEY" not in env and "OPENAI_BASE_URL" not in env
    assert not any(any(word in key.upper() for word in ("API_KEY", "TOKEN", "SECRET", "ACCESS_KEY", "SIDECAR", "ATTACH"))
                   for key in env), "credential or host-attachment variable passed to Hermes"


def verify_source(source: Path, expected_entry_sha256: str, *, git: Path | str | None = None) -> str:
    """Accept only reviewed releases, a clean checkout, and the supplied bundle digest."""
    source = source.resolve()
    assert not (source / ".env").exists(), "Hermes project .env must be absent; ignored files can contain credentials"
    git = str(Path(git).resolve()) if git is not None else os.environ.get("PALLIUM_TUI_GIT", "git")
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
    env = ({
        "SYSTEMROOT": os.environ["SYSTEMROOT"],
        "PATH": os.pathsep.join((str(Path(os.environ["SYSTEMROOT"]) / "System32"), str(node.parent))),
        "HOME": str(home), "USERPROFILE": str(home),
        "APPDATA": str(home / "AppData/Roaming"), "LOCALAPPDATA": str(home / "AppData/Local"),
        "TEMP": str(home / "Temp"), "TMP": str(home / "Temp"),
    } if os.name == "nt" else {
        "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": str(home), "TMPDIR": str(home / "Temp"),
    })
    env.update({"PYTHONPATH": str(guard_dir),
        "PALLIUM_TUI_ALLOWED_ENDPOINTS": json.dumps(allowed),
        "PALLIUM_TUI_EGRESS_LOG": str(audit),
        "PALLIUM_TUI_IPC_LOG": str(root / "local-ipc.jsonl"),
        "NODE_OPTIONS": f'--require="{preload.as_posix()}"'})
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


def _linux_owned_state(psutil, pid, birth, executable):
    """Return live, zombie, or gone only after confirming the saved identity."""
    try:
        proc = psutil.Process(pid)
        assert proc.create_time() == birth, ("refusing cleanup after process birth identity changed", pid)
        status = proc.status()
        if status == psutil.STATUS_ZOMBIE:
            return "zombie", proc
        assert str(Path(proc.exe()).resolve()) == executable, (
            "refusing cleanup after process executable identity changed", pid)
        return "live", proc
    except psutil.NoSuchProcess:
        return "gone", None


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
                    connections = proc.net_connections()
                    rows.append({"pid": pid, "birthtime": birth, "exe": executable,
                                 "argv": proc.cmdline(), "env": proc.environ(),
                                 "connections_collected": True,
                                 "connections": [{"ip": c.raddr.ip, "port": c.raddr.port,
                                                  "local_ip": c.laddr.ip, "local_port": c.laddr.port,
                                                  "family": c.family.name, "type": c.type.name,
                                                  "status": c.status}
                                                 for c in connections if c.raddr]})
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
        if os.name != "nt":
            for pid, (birth, executable) in known:
                if not include_root and pid == self.root.pid:
                    continue
                state, proc = _linux_owned_state(self.psutil, pid, birth, executable)
                if state == "live":
                    handles.append(proc)
                    try:
                        proc.kill()
                    except self.psutil.NoSuchProcess:
                        pass
            _, alive = self.psutil.wait_procs(handles, timeout=8)
            for proc in alive:
                birth, executable = self.identities[proc.pid]
                state, _ = _linux_owned_state(self.psutil, proc.pid, birth, executable)
                assert state in ("zombie", "gone"), f"owned process survived cleanup: {proc.pid}"
            assert self.error is None, self.error
            return
        for pid, (birth, executable) in known:
            if not include_root and pid == self.root.pid:
                continue
            try:
                proc = self.psutil.Process(pid)
                expected = (birth, executable)
                observed = (proc.create_time(), str(Path(proc.exe()).resolve()))
                if observed != expected and observed[0] > expected[0]:
                    print(json.dumps({"pid": pid, "saved": expected, "observed": observed,
                                      "reason": "saved_identity_exited_pid_reused"}),
                          file=sys.stderr, flush=True)
                    continue
                assert observed == expected, (
                    "refusing cleanup after process identity changed", pid, expected, observed)
                handles.append(proc)
                proc.kill()
            except self.psutil.NoSuchProcess:
                pass
        _, alive = self.psutil.wait_procs(handles, timeout=8)
        assert not alive, f"owned processes survived cleanup: {[p.pid for p in alive]}"
        assert self.error is None, self.error


class TuiConsole:
    def __init__(self, python: Path, source: Path, home: Path, env: dict[str, str], artifacts: Path,
                 stopped: threading.Event, tree: OwnedTree, gateway=None):
        self.parts = []
        self._init_screen_observer()
        self.read_error = None
        self.artifacts = artifacts
        self.stopped = stopped
        self.gateway = gateway
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
        if os.name == "nt":
            from winpty import PTY, Backend, WinptyError

            self.pty_error = WinptyError
            self.proc = PTY(200, 55, backend=Backend.ConPTY, timeout=30_000)
            assert self.proc.spawn(str(python), cmdline=" " + subprocess.list2cmdline(["-c", preflight]),
                                   cwd=str(home / "scratch"),
                                   env="\0".join(f"{key}={value}" for key, value in env.items()) + "\0")
        else:
            self.pty_error = OSError
            self.proc = LinuxPTY(python, ["-c", preflight], cwd=home / "scratch", env=env)
        tree.refresh()
        child = next(row for row in tree.snapshot() if row["pid"] == self.proc.pid)
        assert Path(child["exe"]).resolve() == python.resolve(), "unexpected ConPTY executable"
        self.reader = threading.Thread(target=self._pump, daemon=True)
        self.reader.start()

    def _init_screen_observer(self):
        if __package__:
            from .hermes_terminal_screen import TerminalScreen
        else:
            from hermes_terminal_screen import TerminalScreen

        self._capture_lock = threading.RLock()
        self._raw_offset = 0
        self.screen = TerminalScreen(200, 55)

    def feed_output(self, chunk: str):
        """Append and parse one PTY chunk under the same cursor lock used by marks."""
        with self._capture_lock:
            self.parts.append(chunk)
            self._raw_offset += len(chunk)
            self.screen.feed(chunk)

    def mark(self):
        with self._capture_lock:
            return self.screen.mark(self._raw_offset)

    def _pump(self):
        while True:
            try:
                chunk = self.proc.read(blocking=False)
                if chunk:
                    self.feed_output(chunk)
                elif not self.proc.isalive():
                    return
                else:
                    time.sleep(.03)
            except (EOFError, OSError, self.pty_error) as exc:
                self.read_error = repr(exc)
                return

    @property
    def raw_text(self):
        with self._capture_lock:
            return "".join(self.parts)

    @property
    def text(self):
        return ANSI.sub("", self.raw_text)

    def wait(self, expected: str, *, after: int = 0, timeout: float = 90):
        """Wait for exact logical cell text rendered after a synchronized output mark."""
        deadline = time.monotonic() + timeout
        with self._capture_lock:
            visible = self.screen.rendered
        while time.monotonic() < deadline:
            assert not self.stopped.is_set(), "driver shutdown requested"
            with self._capture_lock:
                visible = self.screen.rendered
                observed = self.screen.contains(expected, after=after)
            if observed:
                return
            assert self.proc.isalive(), (
                f"TUI exited early: {self.read_error}; screen={visible[-2000:]}; raw={self.text[-1000:]}"
            )
            assert self.tree.error is None, self.tree.error
            time.sleep(.1)
        raise TimeoutError(f"TUI did not render {expected!r}: {visible[-3000:]}")

    def submit(self, prompt: str, *, marker: str):
        prompt.encode("utf-8", errors="strict")
        assert marker and marker.isascii() and marker in prompt, "expected a unique visible ASCII input marker"
        offset = self.mark()
        self.proc.write(prompt)
        # Ink redraws and grapheme wrapping can split the echoed Unicode input; the provider checks it in full.
        self.wait(marker, after=offset, timeout=20)
        self.proc.write("\r")

    def new_session(self):
        offset = self.mark()
        self.submit("/new", marker="/new")
        self.wait("new session started", after=offset, timeout=30)
        self.wait("ready │", after=offset, timeout=60)

    def ready(self):
        deadline = time.monotonic() + 60
        while not any(token in self.text for token in ("Ask me anything", 'Try "')):
            assert not self.stopped.is_set() and time.monotonic() < deadline and self.proc.isalive(), self.text[-3000:]
            time.sleep(.1)
        self.wait("ready │", timeout=90)
        if self.gateway is not None:
            self.gateway.verify_and_release()

    def close(self):
        self.proc.cancel_io()
        self.reader.join(2)
        with self._capture_lock:
            raw = "".join(self.parts)
            rendered = self.screen.rendered
        (self.artifacts / "terminal.txt").write_text(raw, encoding="utf-8", errors="backslashreplace")
        (self.artifacts / "terminal-screen.txt").write_text(rendered, encoding="utf-8", errors="backslashreplace")


class LinuxPTY:
    """Own a standard-library PTY and attach it to a fresh child session."""

    def __init__(self, python: Path, arguments: list[str], *, cwd: Path, env: dict[str, str]):
        import fcntl
        import pty
        import struct
        import termios

        master, slave = pty.openpty()
        attach = ("import fcntl,os,sys,termios; "
                  "fcntl.ioctl(0,termios.TIOCSCTTY,0); "
                  "os.execvpe(sys.argv[1],sys.argv[1:],os.environ)")
        try:
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 55, 200, 0, 0))
            os.set_blocking(master, False)
            self.process = subprocess.Popen(
                [sys.executable, "-I", "-c", attach, str(python), *arguments],
                cwd=cwd, env=env, stdin=slave, stdout=slave, stderr=slave,
                start_new_session=True,
            )
        except BaseException:
            os.close(master)
            raise
        finally:
            os.close(slave)
        self.master = master
        self.pid = self.process.pid
        self.decoder = __import__("codecs").getincrementaldecoder("utf-8")("replace")

    def read(self, *, blocking=False):
        import errno

        try:
            data = os.read(self.master, 65536)
        except BlockingIOError:
            return ""
        except OSError as exc:
            if exc.errno == errno.EIO:
                return ""
            raise
        return self.decoder.decode(data) if data else ""

    def write(self, text: str):
        import select
        import time

        data = memoryview(text.encode("utf-8", errors="strict"))
        deadline = time.monotonic() + 5
        while data:
            try:
                written = os.write(self.master, data)
                assert written > 0, "PTY accepted no input bytes"
                data = data[written:]
            except BlockingIOError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("timed out writing input to Hermes TUI PTY")
                select.select([], [self.master], [], min(.5, remaining))
                if self.process.poll() is not None:
                    raise BrokenPipeError("Hermes TUI exited while receiving input")

    def isalive(self):
        return self.process.poll() is None

    def cancel_io(self):
        if self.master is not None:
            os.close(self.master)
            self.master = None


def driver_main(spec_path: Path):
    """The explicit disposable 3.14 interpreter alone starts the real UI."""
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    home, source, python = (Path(spec[key]).resolve() for key in ("home", "source", "python"))
    surface = spec.get("surface", "tui")
    scope_mode = spec.get("scope_mode", "fixed")
    shared_gateway = spec.get("shared_gateway", False)
    canonical_only = spec.get("canonical_only", False)
    assert surface in {"tui", "desktop"}, "unknown native UI surface"
    assert type(scope_mode) is str and scope_mode in {"fixed", "cwd"}, "unknown native scope mode"
    assert type(shared_gateway) is bool, "shared_gateway must be a strict boolean"
    assert type(canonical_only) is bool, "canonical_only must be a strict boolean"
    if canonical_only:
        assert surface == "tui" and scope_mode == "cwd" and shared_gateway, (
            "canonical-only mode requires the shared cwd TUI gateway")
        assert type(spec.get("canonical_gateway")) is dict and type(spec.get("canonical_ui_driver")) is dict, (
            "canonical-only mode requires original gateway and UI identities")
    else:
        assert not ({"canonical_gateway", "canonical_ui_driver"} & spec.keys()), (
            "ordinary driver cannot accept canonical-only identities")
    from hermes_desktop_driver import DesktopConsole, require_runner_gate
    if os.name == "nt":
        require_runner_gate(dict(os.environ), home, source, spec_path.parent)
    else:
        from hermes_linux_guard import require_contained_paths, require_linux_qualification

        require_linux_qualification(dict(os.environ))
        require_contained_paths(home, source, python, spec_path)
    assert Path(sys.executable).resolve() == python and sys.version_info[:2] == (3, 14)
    assert Path(sys._base_executable).resolve() == Path(spec["python_base"])
    assert hashlib.sha256(Path(sys._base_executable).read_bytes()).hexdigest() == spec["python_base_sha256"].lower()
    assert Path.cwd().resolve() == home / "scratch"
    assert_isolated_env(dict(os.environ), home)
    import socket
    import sitecustomize
    guard_path = os.environ.get("PALLIUM_TUI_GUARD_PATH")
    guard_sha256 = os.environ.get("PALLIUM_TUI_GUARD_SHA256")
    assert (guard_path is None) == (guard_sha256 is None), "installed guard witness is incomplete"
    assert not shared_gateway or guard_path is not None, "shared gateway requires the copied-runtime guard"
    if guard_path is None:
        assert Path(sitecustomize.__file__).resolve() == Path(os.environ["PYTHONPATH"].split(os.pathsep)[-1]) / "sitecustomize.py"
    else:
        installed_guard = Path(guard_path).resolve()
        assert installed_guard == Path(sitecustomize.__file__).resolve()
        assert re.fullmatch(r"[0-9a-fA-F]{64}", guard_sha256)
        assert hashlib.sha256(installed_guard.read_bytes()).hexdigest() == guard_sha256.lower()
    assert socket.socket.connect is sitecustomize._connect
    git = Path(spec["git"]).resolve()
    assert git.is_file() and hashlib.sha256(git.read_bytes()).hexdigest() == spec["git_sha256"].lower(), (
        "qualification Git executable changed")
    release = verify_source(source, spec["bundle_sha256"], git=git)
    if shared_gateway:
        assert surface == "tui" and release == "0.22.4", "shared native gateway requires the released 0.22.4 TUI"
    revision = next(revision for revision, version in RELEASES.items() if version == release)
    canonical_receipt = None
    if canonical_only:
        from hermes_gateway_driver import validate_canonical_gateway

        assert os.name == "nt", "canonical-only mode is scoped to Windows qualification"
        canonical_receipt = spec["canonical_gateway"]
        canonical_home = Path(os.environ["HERMES_HOME"]).resolve()
        target = validate_canonical_gateway(canonical_receipt, spec["canonical_ui_driver"],
            home=canonical_home, revision=revision, python=python, python_base=Path(spec["python_base"]))
        assert sitecustomize._allowed(target), "canonical gateway was not granted before guard import"
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
    owned_python = Path(sys._base_executable if os.name == "nt" else sys.executable)
    tree = OwnedTree(os.getpid(), owned_python, ledger=spec_path.parent / "owned-processes-ledger.json")
    console, gateway = None, None
    canonical = {}

    def canonical_socket(*, deadline=None):
        from gateway.control_socket import query_gateway_control
        from websockets.sync.client import connect

        deadline = deadline or time.monotonic() + 5
        receipt = canonical_receipt if canonical_only else gateway.receipt
        if canonical_only:
            from hermes_gateway_driver import verify_canonical_gateway_identity

            validate_canonical_gateway(receipt, spec["canonical_ui_driver"],
                home=canonical_home, revision=revision, python=python, python_base=Path(spec["python_base"]))
            verify_canonical_gateway_identity(receipt, home=canonical_home,
                timeout=min(2, max(.1, deadline - time.monotonic())))
        grant = query_gateway_control(Path(os.environ["HERMES_HOME"]), "session-ticket", params={
            "profile_id": receipt["profile_id"], "instance_id": receipt["instance_id"],
            "purpose": "interactive"}, timeout=min(2, max(.1, deadline - time.monotonic())))
        assert isinstance(grant, dict) and isinstance(grant.get("ticket"), str), grant
        ws = connect(receipt["url"], subprotocols=[
            "hermes-gateway-v1", "hermes-gateway-ticket." + grant["ticket"]],
            open_timeout=min(2, max(.1, deadline - time.monotonic())),
            close_timeout=1)
        canonical_authority_ready(ws, deadline)
        return ws

    def canonical_turn(ws, session_id, text, *, deadline=None):
        import uuid

        deadline = deadline or time.monotonic() + 5
        admission = canonical_rpc(ws, "prompt.submit", {"session_id": session_id,
            "submission_id": uuid.uuid4().hex, "text": text},
            timeout=min(2, max(.1, deadline - time.monotonic())))
        admission_id = admission.get("admission_id")
        assert isinstance(admission_id, str) and admission_id, admission
        return canonical_terminal_receipt(ws, session_id, admission_id, deadline)
    try:
        console_class = DesktopConsole if surface == "desktop" else TuiConsole
        # Retain a partial Desktop constructor so failed startup logs can still be closed and saved.
        if canonical_only:
            pass  # The original UI driver alone owns its gateway and helper.
        elif surface == "desktop":
            console = console_class.__new__(console_class)
            console.__init__(python, source, home, dict(os.environ), spec_path.parent, stopped, tree,
                             reuse_user_data=spec.get("reuse_user_data", False),
                             previous_spec=spec.get("previous_spec"), scope_mode=scope_mode)
        else:
            tui_env = dict(os.environ)
            tui_env.pop("PALLIUM_TUI_GATEWAY_WS", None)
            if shared_gateway:
                from hermes_gateway_driver import OwnedGateway, gateway_target

                gateway = OwnedGateway(python, source, tui_env, spec_path.parent, tree, revision,
                                       python_base=Path(spec["python_base"]),
                                       python_base_sha256=spec["python_base_sha256"])
                gateway_url = gateway.receipt["url"]
                gateway_target(gateway_url)
                tui_env["PALLIUM_TUI_GATEWAY_WS"] = gateway_url
            console = console_class(python, source, home, tui_env, spec_path.parent, stopped, tree,
                                    gateway=gateway)
        if console is not None:
            console.ready()
        print(json.dumps({"ready": True}), flush=True)
        while not stopped.is_set():
            try:
                command = commands.get(timeout=.2)
            except queue.Empty:
                continue
            op = command["op"]
            assert not canonical_only or op not in {"submit", "wait", "new", "inspect"}, (
                "canonical-only driver cannot perform UI operations")
            if op == "submit":
                console.submit(command["text"], marker=command["marker"])
            elif op == "wait":
                console.wait(command["text"], timeout=command.get("timeout", 90))
            elif op == "new":
                console.new_session()
            elif op == "inspect":
                print(json.dumps({"processes": console.tree.snapshot()}), flush=True)
                continue
            elif op == "canonical_create":
                assert (gateway is not None or canonical_only) and not canonical
                ws = canonical_socket()
                canonical["a"] = ws
                created = canonical_rpc(ws, "session.create", {"source": "tui", "cwd": str(home / "scratch")})
                session_id, subscription_id = created["session_id"], created["subscription_id"]
                assert isinstance(session_id, str) and session_id
                assert isinstance(subscription_id, str) and subscription_id
                canonical.update(session_id=session_id, a_subscription=subscription_id)
                terminal = canonical_turn(ws, session_id, "native-finalize-race: initial")
                print(json.dumps({"session_id": session_id, "subscription_id": subscription_id,
                    "terminal": terminal}), flush=True)
                continue
            elif op == "canonical_detach":
                assert canonical["session_id"] == command["session_id"]
                assert "detach_thread" not in canonical
                def detached():
                    try:
                        started = time.monotonic()
                        canonical["detach_result"] = canonical_rpc(canonical["a"], "session.detach", {
                            "session_id": canonical["session_id"],
                            "subscription_id": canonical["a_subscription"], "end_reason": "tui_close"}, timeout=12)
                        canonical["detach_elapsed"] = time.monotonic() - started
                    except BaseException as exc:
                        canonical["detach_error"] = repr(exc)
                canonical["detach_thread"] = threading.Thread(target=detached, daemon=True)
                canonical["detach_thread"].start()
            elif op == "canonical_resume":
                assert canonical["session_id"] == command["session_id"]
                resume_deadline = time.monotonic() + 6
                ws = canonical_socket(deadline=resume_deadline)
                canonical["b"] = ws
                resumed = canonical_rpc(ws, "session.resume", {"session_id": canonical["session_id"]},
                    timeout=min(2, max(.1, resume_deadline - time.monotonic())))
                canonical_same_session(resumed, canonical["session_id"])
                assert resumed["subscription_id"]
                canonical["b_subscription"] = resumed["subscription_id"]
                terminal = canonical_turn(ws, canonical["session_id"], "native-finalize-race: resumed",
                    deadline=resume_deadline)
                print(json.dumps({"session_id": resumed["session_id"],
                    "subscription_id": resumed["subscription_id"], "terminal": terminal}), flush=True)
                continue
            elif op == "canonical_detach_complete":
                assert canonical["session_id"] == command["session_id"]
                canonical["detach_thread"].join(12)
                assert not canonical["detach_thread"].is_alive(), "old detach callback remained blocked"
                assert "detach_error" not in canonical, canonical.get("detach_error")
                elapsed = canonical_completed_detach(canonical["detach_result"],
                    canonical["session_id"], canonical["detach_elapsed"])
                canonical["detach_completed"] = True
                print(json.dumps({"session_id": canonical["session_id"],
                    "detached": canonical["detach_result"], "elapsed": elapsed}), flush=True)
                continue
            elif op == "canonical_finish":
                assert canonical["session_id"] == command["session_id"]
                assert canonical.get("detach_completed") is True
                terminal = canonical_turn(canonical["b"], canonical["session_id"],
                    "native-finalize-race: post-release")
                print(json.dumps({"session_id": canonical["session_id"], "terminal": terminal}), flush=True)
                continue
            elif op == "close":
                stopped.set()
                break
            else:
                raise AssertionError(f"unknown driver operation: {op}")
            print(json.dumps({"ok": op}), flush=True)
    finally:
        stopped.set()
        for ws in (canonical.get("a"), canonical.get("b")):
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass
        try:
            tree.close(include_root=False)
        finally:
            if console is not None:
                pending_error = sys.exc_info()[0] is not None
                try:
                    owned_popen = getattr(getattr(console, "proc", None), "process", None)
                    if os.name != "nt" and owned_popen is not None:
                        try:
                            owned_popen.wait(timeout=8)
                        except subprocess.TimeoutExpired:
                            if not pending_error:
                                raise
                finally:
                    console.close()


def cleanup_ledger(path: Path):
    """Recovery process checks saved identities after a failed driver, including orphaned children."""
    import psutil

    assert sys.version_info[:2] == (3, 14), "ownership recovery requires the explicit Hermes interpreter"
    rows = json.loads(path.read_text(encoding="utf-8"))
    if os.name != "nt":
        handles = []
        identities = {}
        for row in rows:
            pid, birth = row["pid"], row["birthtime"]
            executable = str(Path(row["exe"]).resolve())
            state, proc = _linux_owned_state(psutil, pid, birth, executable)
            identities[pid] = (birth, executable)
            if state == "live":
                handles.append(proc)
        for proc in handles:
            try:
                proc.kill()
            except psutil.NoSuchProcess:
                pass
        _, alive = psutil.wait_procs(handles, timeout=8)
        for proc in alive:
            birth, executable = identities[proc.pid]
            state, _ = _linux_owned_state(psutil, proc.pid, birth, executable)
            assert state in ("zombie", "gone"), f"retained owned process survived recovery: {proc.pid}"
        return {"recovered": [proc.pid for proc in handles], "alive": []}
    handles = []
    for row in rows:
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


def stop_owned_driver(proc, python: Path, helper: Path, artifacts: Path, env, *, grace=15, identity=None):
    """Use the owned Popen handle and platform-specific identity-safe recovery."""
    forced = False
    if os.name != "nt":
        from tests.test_hermes_relay_native_e2e import _stop_owned_host

        try:
            if proc is not None:
                if proc.stdin is not None and not proc.stdin.closed:
                    proc.stdin.close()
                try:
                    proc.wait(timeout=grace)
                except subprocess.TimeoutExpired:
                    forced = True
                _stop_owned_host(proc, identity)
        finally:
            ledger = artifacts / "owned-processes-ledger.json"
            if ledger.exists():
                recovery = subprocess.run([str(python), "-I", str(helper), "--cleanup-owned", str(ledger)],
                    env=env, capture_output=True, text=True, timeout=15, check=True)
                recovered = json.loads(recovery.stdout)
            else:
                assert not (artifacts / "driver-identity.json").exists(), (
                    "driver started without a durable ownership ledger")
                recovered = {"recovered": [], "alive": []}
        return {"forced": forced, **recovered}

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
