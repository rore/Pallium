"""Fail-closed test-only network guard; loaded from a private PYTHONPATH."""
from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import time
import traceback
from pathlib import Path

_BLOCKED_PORT = 19836
_REAL_GETADDRINFO = socket.getaddrinfo
_REAL_GETHOSTBYNAME = socket.gethostbyname
_REAL_GETNAMEINFO = socket.getnameinfo
_REAL_BIND = socket.socket.bind
_REAL_CONNECT = socket.socket.connect
_REAL_CONNECT_EX = socket.socket.connect_ex
_REAL_SENDTO = socket.socket.sendto
try:
    _repo_root_value = os.environ.get("PALLIUM_NET_GUARD_REPO_ROOT")
    _REPO_ROOT = Path(_repo_root_value).resolve(strict=True) if _repo_root_value else None
    if _REPO_ROOT is not None and not _REPO_ROOT.is_dir():
        _REPO_ROOT = None
except (OSError, RuntimeError, ValueError):
    _REPO_ROOT = None


def _pytest_context() -> tuple[str, str]:
    raw = os.environ.get("PYTEST_CURRENT_TEST", "")
    node, marker, phase_text = raw.rpartition(" (")
    phase = phase_text[:-1] if marker and phase_text.endswith(")") else "unknown"
    if phase not in {"setup", "call", "teardown"}:
        phase = "unknown"
    node = node if marker else raw
    node = node.split("[", 1)[0].replace("\\", "/")
    if _REPO_ROOT is None or not re.fullmatch(r"tests/[A-Za-z0-9_./-]+(?:::[A-Za-z0-9_]+)+", node):
        return "unknown", phase
    module, *names = node.split("::")
    if any(part in {".", ".."} for part in module.split("/")) or not names:
        return "unknown", phase
    if not all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,99}", name) for name in names):
        return "unknown", phase
    try:
        resolved = (_REPO_ROOT / module).resolve(strict=True)
        relative = resolved.relative_to(_REPO_ROOT)
    except (OSError, RuntimeError, ValueError):
        return "unknown", phase
    if not resolved.is_file() or relative.suffix != ".py":
        return "unknown", phase
    safe_module = relative.as_posix()
    if not re.fullmatch(r"[A-Za-z0-9_./-]{1,180}", safe_module):
        return "unknown", phase
    return "::".join([safe_module, *names])[:240], phase


def _repo_stack() -> list[dict[str, object]]:
    if _REPO_ROOT is None:
        return []
    frames = []
    for frame in traceback.extract_stack(limit=32)[:-2]:
        try:
            resolved = Path(frame.filename).resolve(strict=True)
            relative = resolved.relative_to(_REPO_ROOT)
        except (OSError, RuntimeError, ValueError):
            continue
        safe_path = relative.as_posix()
        safe_function = "module" if frame.name == "<module>" else frame.name
        if (
            not re.fullmatch(r"[A-Za-z0-9_./-]{1,180}", safe_path)
            or any(part in {".", ".."} for part in safe_path.split("/"))
            or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,99}", safe_function)
        ):
            continue
        frames.append({"file": safe_path, "function": safe_function, "line": int(frame.lineno)})
    return frames[-8:]


def _record(message: str) -> None:
    path = os.environ.get("PALLIUM_NET_GUARD_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as log:
            log.write(message + "\n")


def _record_detail(category: str) -> None:
    path = os.environ.get("PALLIUM_NET_GUARD_DETAIL_LOG")
    if not path:
        return
    try:
        node, phase = _pytest_context()
        event = {
            "pid": os.getpid(),
            "monotonic_ns": time.monotonic_ns(),
            "category": category,
            "pytest_current_test_context": node,
            "pytest_phase_context": phase,
            "context_is_causal": False,
            "stack": _repo_stack(),
        }
        with open(path, "a", encoding="utf-8") as log:
            log.write(json.dumps(event, separators=(",", ":")) + "\n")
    except Exception:
        pass


def _deny(message: str, category: str) -> None:
    _record_detail(category)
    _record(message)
    raise PermissionError("full-suite network guard: " + message)


def _check(host: object, port: object, operation: str) -> None:
    try:
        port_number = int(port) if port is not None else None
    except (TypeError, ValueError):
        port_number = None
    host_text = host.decode("ascii") if isinstance(host, bytes) else str(host or "")
    host_text = host_text.strip("[]").rstrip(".").lower()
    if port_number == _BLOCKED_PORT:
        _deny(f"{operation} denied installed-service port {_BLOCKED_PORT}", "installed_service_port")
    if host_text == "localhost":
        return
    try:
        address = ipaddress.ip_address(host_text.split("%", 1)[0])
    except ValueError:
        _deny(f"{operation} denied remote DNS/name lookup", "remote_dns")
    if not address.is_loopback:
        _deny(f"{operation} denied non-loopback network address", "non_loopback_address")


def _guard_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    host_text = host.decode("ascii") if isinstance(host, bytes) else str(host or "")
    if host_text.rstrip(".").lower() == "localhost":
        results = []
        if family in (0, socket.AF_INET):
            results.extend(_REAL_GETADDRINFO("127.0.0.1", port, socket.AF_INET, type, proto, flags))
        if family in (0, socket.AF_INET6):
            try:
                results.extend(_REAL_GETADDRINFO("::1", port, socket.AF_INET6, type, proto, flags))
            except socket.gaierror:
                pass
        if not results:
            raise socket.gaierror("localhost has no allowed loopback address")
        _check("127.0.0.1", port, "DNS resolution")
        return results
    _check(host, port, "DNS resolution")
    return _REAL_GETADDRINFO(host, port, family, type, proto, flags)


def _guard_gethostbyname(host):
    host_text = host.decode("ascii") if isinstance(host, bytes) else str(host)
    if host_text.rstrip(".").lower() == "localhost":
        return "127.0.0.1"
    _check(host_text, None, "DNS resolution")
    return _REAL_GETHOSTBYNAME(host)


def _guard_gethostbyname_ex(host):
    host_text = host.decode("ascii") if isinstance(host, bytes) else str(host)
    if host_text.rstrip(".").lower() == "localhost":
        return ("localhost", [], ["127.0.0.1"])
    _check(host_text, None, "DNS resolution")
    return (host_text, [], [host_text])


def _guard_gethostbyaddr(host):
    host_text = host.decode("ascii") if isinstance(host, bytes) else str(host)
    _check(host_text, None, "reverse DNS")
    return (host_text, [], [host_text])


def _guard_getnameinfo(address, flags):
    _check(address[0], address[1], "reverse DNS")
    return _REAL_GETNAMEINFO(address, flags | socket.NI_NUMERICHOST)


def _guard_bind(sock, address):
    if sock.family in (socket.AF_INET, socket.AF_INET6):
        _check(address[0], address[1], "bind")
    return _REAL_BIND(sock, address)


def _guard_connect(sock, address):
    if sock.family in (socket.AF_INET, socket.AF_INET6):
        _check(address[0], address[1], "connect")
    return _REAL_CONNECT(sock, address)


def _guard_connect_ex(sock, address):
    if sock.family in (socket.AF_INET, socket.AF_INET6):
        _check(address[0], address[1], "connect_ex")
    return _REAL_CONNECT_EX(sock, address)


def _guard_sendto(sock, *args):
    if sock.family in (socket.AF_INET, socket.AF_INET6):
        address = args[-1]
        _check(address[0], address[1], "sendto")
    return _REAL_SENDTO(sock, *args)


socket.getaddrinfo = _guard_getaddrinfo
socket.gethostbyname = _guard_gethostbyname
socket.gethostbyname_ex = _guard_gethostbyname_ex
socket.gethostbyaddr = _guard_gethostbyaddr
socket.getnameinfo = _guard_getnameinfo
socket.socket.bind = _guard_bind
socket.socket.connect = _guard_connect
socket.socket.connect_ex = _guard_connect_ex
socket.socket.sendto = _guard_sendto
