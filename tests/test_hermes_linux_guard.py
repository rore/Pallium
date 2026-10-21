from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tests.fixtures.hermes_linux_guard import (
    _check_mount_boundary,
    _check_namespaces,
    _check_owner_mode,
    _maps,
    _mounts,
    _stat_fields,
    require_contained_paths,
    require_linux_qualification,
)
from tests.fixtures.hermes_tui_driver import LinuxPTY
from tests.fixtures.hermes_tui_driver import classify_bridge_connections


def test_linux_guard_parses_proc_stat_with_parenthesized_command():
    tail = ["S", "1", "123", "123", *("0" for _ in range(15)), "987654"]
    assert _stat_fields("123 (worker (with ) parens)) " + " ".join(tail))[19] == "987654"


def test_linux_guard_parses_mountinfo_escapes_and_mount_options():
    rows = _mounts("36 25 0:32 / /usr/lib/wsl rw,nosuid - tmpfs tmpfs ro,size=1m\n"
                   "37 25 0:1 / /mnt/host\\040share rw - 9p host rw\n")
    assert rows == [("/usr/lib/wsl", "tmpfs", "rw,nosuid", "tmpfs"),
                    ("/mnt/host share", "9p", "rw", "host")]


def test_linux_guard_maps_are_normalized_integer_triples(tmp_path):
    path = tmp_path / "uid_map"
    path.write_text("0 0 65536\n", encoding="ascii")
    assert _maps(path) == [[0, 0, 65536]]


def test_linux_guard_refuses_missing_boundary_before_reading_manifest():
    with pytest.raises(AssertionError, match="qualification root"):
        require_linux_qualification({})


def test_linux_guard_rejects_resolved_paths_outside_qualification_root():
    with pytest.raises(AssertionError, match="outside qualification root"):
        require_contained_paths(Path("/outside-qualification-root"))


@pytest.mark.parametrize("owner,mode", [(1, 0o444), (0, 0o644)])
def test_linux_guard_rejects_untrusted_manifest_owner_or_mode(owner, mode):
    from types import SimpleNamespace
    import stat

    info = SimpleNamespace(st_uid=owner, st_mode=stat.S_IFREG | mode)
    with pytest.raises(AssertionError):
        _check_owner_mode(Path("/qualification/manifests/run.json"), info, mode=0o444)


def test_linux_guard_rejects_namespace_and_host_mount_drift():
    expected = {"pid": "pid:[1]", "user": "user:[2]", "net": "net:[3]"}
    with pytest.raises(AssertionError):
        _check_namespaces(expected, {**expected, "net": "net:[4]"})
    safe_mountinfo = "36 25 0:32 / /usr/lib/wsl rw,nosuid - tmpfs tmpfs ro,size=1m\n"
    safe_hash = hashlib.sha256(safe_mountinfo.encode()).hexdigest()
    assert _check_mount_boundary(safe_mountinfo, safe_hash)[0][1] == "tmpfs"
    host_mountinfo = "37 25 0:1 / /mnt/host rw - 9p host rw\n"
    with pytest.raises(AssertionError):
        _check_mount_boundary(host_mountinfo, hashlib.sha256(host_mountinfo.encode()).hexdigest())


def test_linux_pty_uses_new_session_controlling_tty_and_incremental_utf8(tmp_path, monkeypatch):
    import os
    import struct
    import sys
    from types import SimpleNamespace

    calls = {"ioctl": [], "popen": [], "writes": [], "reads": [b"\xe2", b"\x82\xac"], "closed": []}
    monkeypatch.setitem(sys.modules, "pty", SimpleNamespace(openpty=lambda: (101, 102)))
    monkeypatch.setitem(sys.modules, "termios", SimpleNamespace(TIOCSWINSZ=7, TIOCSCTTY=8))
    monkeypatch.setitem(sys.modules, "fcntl", SimpleNamespace(ioctl=lambda *args: calls["ioctl"].append(args)))
    monkeypatch.setattr("tests.fixtures.hermes_tui_driver.subprocess.Popen", lambda *args, **kwargs:
        calls["popen"].append((args, kwargs)) or SimpleNamespace(pid=321, poll=lambda: None))
    monkeypatch.setattr(os, "set_blocking", lambda *args: calls.setdefault("blocking", []).append(args))
    monkeypatch.setattr(os, "close", lambda fd: calls["closed"].append(fd))

    def read(_fd, _size):
        return calls["reads"].pop(0)

    def write(_fd, data):
        chunk = bytes(data[:2])
        calls["writes"].append(chunk)
        return len(chunk)

    monkeypatch.setattr(os, "read", read)
    monkeypatch.setattr(os, "write", write)
    pty = LinuxPTY(Path(sys.executable), ["-c", "pass"], cwd=tmp_path, env={})
    assert struct.unpack("HHHH", calls["ioctl"][0][2]) == (55, 200, 0, 0)
    args, kwargs = calls["popen"][0]
    assert "TIOCSCTTY" in args[0][3] and "ioctl(0," in args[0][3]
    assert kwargs["start_new_session"] is True and "pass_fds" not in kwargs
    assert kwargs["stdin"] == kwargs["stdout"] == kwargs["stderr"] == 102
    assert pty.read() == "" and pty.read() == "€"
    pty.write("Grüße")
    assert b"".join(calls["writes"]) == "Grüße".encode()
    pty.cancel_io()
    assert calls["closed"] == [102, 101]


def test_linux_pty_eagain_write_has_a_deadline(tmp_path, monkeypatch):
    import os
    import sys
    import time
    from types import SimpleNamespace

    monkeypatch.setitem(sys.modules, "pty", SimpleNamespace(openpty=lambda: (101, 102)))
    monkeypatch.setitem(sys.modules, "termios", SimpleNamespace(TIOCSWINSZ=7, TIOCSCTTY=8))
    monkeypatch.setitem(sys.modules, "fcntl", SimpleNamespace(ioctl=lambda *args: None))
    monkeypatch.setattr("tests.fixtures.hermes_tui_driver.subprocess.Popen", lambda *args, **kwargs:
        SimpleNamespace(pid=321, poll=lambda: None))
    monkeypatch.setattr(os, "set_blocking", lambda *args: None)
    monkeypatch.setattr(os, "close", lambda _fd: None)
    monkeypatch.setattr(os, "write", lambda *_args: (_ for _ in ()).throw(BlockingIOError()))
    monkeypatch.setattr("select.select", lambda *args: ([], [], []))
    now = iter([0.0, 6.0])
    monkeypatch.setattr(time, "monotonic", lambda: next(now))
    pty = LinuxPTY(Path(sys.executable), ["-c", "pass"], cwd=tmp_path, env={})
    with pytest.raises(TimeoutError, match="timed out writing"):
        pty.write("x")


def test_bridge_empty_snapshot_requires_positive_linux_collection_evidence():
    service = ("127.0.0.1", 19836)
    empty = {"pid": 123, "connections": []}
    assert not classify_bridge_connections(empty, service)["accepted"]
    assert not classify_bridge_connections(empty, service, require_successful_snapshot=True)["accepted"]
    accepted = classify_bridge_connections(empty, service, collected_successfully=True,
                                            require_successful_snapshot=True)
    assert accepted["accepted"] and accepted["reason"] == "no_observed_remote_sockets"
    row = {"local_ip": "127.0.0.1", "local_port": 41000, "ip": "192.0.2.1", "port": 443,
           "family": "AF_INET", "type": "SOCK_STREAM", "status": "ESTABLISHED"}
    rejected = classify_bridge_connections({"pid": 123, "connections": [row]}, service,
                                           collected_successfully=True, require_successful_snapshot=True)
    assert not rejected["accepted"] and rejected["connections"][0]["reason"] == "rejected_socket"
    assert not classify_bridge_connections({"pid": 123, "connections": [row]}, service,
                                           require_successful_snapshot=True)["accepted"]
