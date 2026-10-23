"""Verify the live Linux namespace boundary for the released Hermes TUI lane."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat


ROOT = Path("/qualification")
ROOTFS_IDENTITY = {
    "distro": "Pallium-Hermes-Qualification-20261021",
    "rootfs_sha256": "2a790896740b14d637dbdc583cce1ba081ac53b9e9cdb46dc09a2f73abbd9934",
}
SCHEMA = "pallium-hermes-linux-qualification/v1"
ISSUER = Path("/opt/pallium-qualification/namespace.py")
HOST_MOUNT_TYPES = {"9p", "drvfs", "virtiofs", "cifs"}


def _stat_fields(text: str) -> list[str]:
    return text[text.rfind(")") + 2:].split()


def _namespace(path: Path) -> str:
    return os.readlink(path)


def _check_owner_mode(path: Path, info, *, mode: int | None = None) -> None:
    assert not stat.S_ISLNK(info.st_mode) and info.st_uid == 0, (path, info.st_uid, info.st_mode)
    if mode is not None:
        assert stat.S_IMODE(info.st_mode) == mode, (path, oct(stat.S_IMODE(info.st_mode)), oct(mode))


def _owned(path: Path, *, mode: int | None = None) -> os.stat_result:
    info = path.lstat()
    _check_owner_mode(path, info, mode=mode)
    return info


def _mounts(text: str) -> list[tuple[str, str, str, str]]:
    result = []
    for line in text.splitlines():
        left, right = line.split(" - ", 1)
        fields, fs = left.split(), right.split()
        mountpoint = re.sub(r"\\([0-7]{3})", lambda match: chr(int(match.group(1), 8)), fields[4])
        result.append((mountpoint, fs[0], fields[5], fs[1]))
    return result


def _maps(path: Path) -> list[list[int]]:
    return [[int(value) for value in line.split()] for line in path.read_text().splitlines()]


def _routes(path: Path, *, ipv6: bool = False) -> None:
    lines = path.read_text().splitlines()
    rows = lines if ipv6 else lines[1:]
    if ipv6:
        assert all(row.split()[-1] == "lo" for row in rows), rows
    else:
        assert all(row.split()[0] == "lo" for row in rows), rows


def _check_mount_boundary(mountinfo: str, expected_sha256: str) -> list[tuple[str, str, str, str]]:
    assert hashlib.sha256(mountinfo.encode()).hexdigest() == expected_sha256
    mounts = _mounts(mountinfo)
    assert not any(fs in HOST_MOUNT_TYPES for _mount, fs, _options, _source in mounts), mounts
    assert not any(mount == "/mnt" or mount.startswith("/mnt/") for mount, *_ in mounts), mounts
    assert not any(mount in {str(ROOT), str(ROOT / "manifests")}
                   for mount, *_ in mounts), mounts
    return mounts


def require_contained_paths(*paths: Path) -> None:
    """Require every resolved execution/input path to stay under the qualification root."""
    root = ROOT.resolve()
    for path in paths:
        resolved = Path(path).resolve()
        assert resolved.is_relative_to(root), ("path outside qualification root", resolved)


def _check_namespaces(expected: dict, actual: dict) -> None:
    assert expected == actual, (expected, actual)


def require_linux_qualification(env: dict[str, str] | None = None) -> dict:
    """Fail closed unless the caller is inside the independently provisioned Linux boundary."""
    env = os.environ if env is None else env
    assert env.get("PALLIUM_LINUX_QUALIFICATION_ROOT") == str(ROOT), "qualification root mismatch"
    assert os.name == "posix" and Path("/proc/self/status").is_file(), "Linux qualification required"
    manifest_path = Path(env.get("PALLIUM_LINUX_QUALIFICATION_MANIFEST", ""))
    assert manifest_path.is_absolute() and manifest_path.parent == ROOT / "manifests", "manifest path mismatch"
    assert re.fullmatch(r"[0-9a-f]{32}\.json", manifest_path.name), "manifest filename mismatch"
    for path in (*ROOT.parents, ROOT, ROOT / "manifests"):
        info = _owned(path, mode=0o755)
        assert stat.S_ISDIR(info.st_mode), path
    manifest_info = _owned(manifest_path, mode=0o444)
    assert stat.S_ISREG(manifest_info.st_mode)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest.get("schema") == SCHEMA and re.fullmatch(r"[0-9a-f]{32}", manifest.get("run_id", ""))
    assert manifest_path.stem == manifest["run_id"]
    assert manifest.get("qualification_root") == str(ROOT)
    assert manifest.get("rootfs_sha256") == ROOTFS_IDENTITY["rootfs_sha256"]
    assert manifest_info.st_uid == 0

    marker = Path("/etc/pallium-qualification.json")
    for parent in marker.parents:
        _owned(parent)
        assert not stat.S_IMODE(parent.lstat().st_mode) & 0o022, (parent, oct(parent.stat().st_mode))
    marker_info = _owned(marker, mode=0o644)
    assert stat.S_ISREG(marker_info.st_mode)
    identity = json.loads(marker.read_text(encoding="utf-8"))
    assert {key: identity.get(key) for key in ROOTFS_IDENTITY} == ROOTFS_IDENTITY

    for path in ISSUER.parents:
        _owned(path, mode=0o755)
    issuer_info = _owned(ISSUER, mode=0o644)
    assert stat.S_ISREG(issuer_info.st_mode)
    assert hashlib.sha256(ISSUER.read_bytes()).hexdigest() == manifest.get("issuer_sha256")

    uid, gid = os.getuid(), os.getgid()
    assert (uid, gid) == (1000, 1000)
    expected_map = [[0, 0, 65536]]
    assert manifest.get("uid") == uid and manifest.get("gid") == gid
    assert manifest.get("uid_map") == manifest.get("gid_map") == expected_map
    assert _maps(Path("/proc/self/uid_map")) == expected_map
    assert _maps(Path("/proc/self/gid_map")) == expected_map
    expected_ns = manifest.get("namespaces", {})
    actual_ns = {name: _namespace(Path(f"/proc/self/ns/{name}")) for name in ("pid", "user", "net")}
    _check_namespaces(expected_ns, actual_ns)
    owner = manifest.get("owner", {})
    owner_stat = _stat_fields(Path("/proc/1/stat").read_text(encoding="utf-8", errors="surrogateescape"))
    owner_status = Path("/proc/1/status").read_text(encoding="utf-8")
    owner_uid = next(line for line in owner_status.splitlines() if line.startswith("Uid:")).split()
    assert owner.get("pid") == 1 and owner.get("start_time") == int(owner_stat[19])
    assert owner_uid[1:3] == ["0", "0"]
    # The root-owned issuer records this binding before dropping privileges.
    # An unprivileged reader may be blocked from /proc/1/ns/* by ptrace rules.
    assert owner.get("pid_namespace") == actual_ns["pid"]
    assert owner.get("user_namespace") != actual_ns["user"]
    assert owner.get("network_namespace") != actual_ns["net"]

    status = Path("/proc/self/status").read_text(encoding="utf-8")
    status_values = {line.split(":", 1)[0]: line.split(":", 1)[1].strip()
                     for line in status.splitlines() if ":" in line}
    for key in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"):
        assert int(status_values[key], 16) == 0, (key, status_values[key])
    assert status_values.get("NoNewPrivs") == "1"

    mountinfo = Path("/proc/self/mountinfo").read_text(encoding="utf-8")
    mounts = _check_mount_boundary(mountinfo, manifest.get("mountinfo_sha256", ""))
    mnt = Path("/mnt")
    if os.path.lexists(mnt):
        assert not mnt.is_symlink() and mnt.is_dir()
        for path in mnt.iterdir():
            assert path.is_dir() and not path.is_symlink() and not any(path.iterdir()), path
    init = Path("/init")
    if os.path.lexists(init):
        info = init.lstat()
        assert not stat.S_ISLNK(info.st_mode) and not info.st_mode & 0o111, init
    for path in (Path("/usr/lib/wsl"), Path("/run/WSL")):
        if os.path.lexists(path):
            info = path.lstat()
            assert not stat.S_ISLNK(info.st_mode)
            mount = next(row for row in mounts if row[0] == str(path))
            assert info.st_uid == 0 and not info.st_mode & 0o111
            assert mount[1] == "tmpfs" and "ro" in mount[2].split(","), (path, mount)

    binfmt = Path("/proc/sys/fs/binfmt_misc")
    assert any(mount == str(binfmt) and fs == "binfmt_misc" for mount, fs, *_ in mounts)
    assert set(os.listdir(binfmt)) == {"register", "status"}
    assert socket.if_nameindex() == [(1, "lo")]
    _routes(Path("/proc/net/route"))
    ipv6_routes = Path("/proc/net/ipv6_route")
    if ipv6_routes.exists():
        _routes(ipv6_routes, ipv6=True)
    return manifest
