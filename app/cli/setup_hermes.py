"""Install the Pallium package into an explicitly selected Hermes profile."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any
from urllib.parse import urlsplit

from core.container_ref import validate_explicit_container_ref

PLUGIN_ID = "pallium-hermes-relay"
MARKER = ".pallium-package.json"
_CONFIG_HELPER = r'''
import hashlib, importlib.metadata, json, os, sys
from pathlib import Path

PLUGIN = "pallium-hermes-relay"
def fail(code):
    print(json.dumps({"ok": False, "error": code}))
    raise SystemExit(2)
try:
    from hermes_cli.config import (
        atomic_config_write, atomic_config_replace, get_config_path,
        require_readable_config_before_write,
    )
except Exception:
    fail("hermes_config_api_unavailable")
action = sys.argv[1]
try:
    version = importlib.metadata.version("mcp")
except Exception:
    version = ""
if action == "validate":
    try:
        major = int(version.split(".", 1)[0])
        import mcp.client.stdio
    except Exception:
        major = 0
    if major != 2:
        fail("hermes_mcp_sdk_v2_required")

try:
    path = get_config_path()
    raw = require_readable_config_before_write(path)
    original = path.read_bytes() if path.exists() else b""
except Exception:
    fail("hermes_config_unreadable")
request = json.loads(sys.stdin.read() or "{}")
digest = hashlib.sha256(original).hexdigest()
config = raw
if "plugins" in config and not isinstance(config["plugins"], dict):
    fail("invalid_plugins_section")
plugins = config.get("plugins")
plugins = plugins if isinstance(plugins, dict) else {}
enabled_present = "enabled" in plugins
enabled = plugins.get("enabled", [])
if not isinstance(enabled, list) or any(not isinstance(item, str) for item in enabled):
    fail("invalid_plugins_enabled")
if enabled.count(PLUGIN) > 1:
    fail("duplicate_plugin_enablement")
entries = plugins.get("entries", {})
if not isinstance(entries, dict):
    fail("invalid_plugin_entries")
entry = entries.get(PLUGIN)
if entry is not None and not isinstance(entry, dict):
    fail("plugin_config_conflict")
settings = request.get("settings")
old = request.get("old_settings")
if action in ("status", "remove") and entry is not None:
    expected_settings = settings if action == "status" else old
    if (expected_settings is not None
            and entry != {"allow_gateway_injection": True, "settings": expected_settings}):
        fail("plugin_config_conflict")
if action in ("validate", "status"):
    print(json.dumps({"ok": True, "config_sha256": digest,
                      "enabled_present": enabled_present, "enabled": enabled,
                      "entry": entry, "mcp_version": version}))
    raise SystemExit(0)

if action not in ("install", "remove"):
    fail("unknown_action")
if request.get("expected_sha256") != digest:
    fail("config_changed_during_operation")
if entry is not None and entry != {"allow_gateway_injection": True, "settings": old}:
    fail("plugin_config_conflict")
if entry is None and old is not None:
    fail("plugin_config_missing")
if action == "install":
    desired = request["settings"]
    new = dict(config)
    p = dict(plugins)
    if request.get("enable_plugin"):
        p["enabled"] = enabled if PLUGIN in enabled else [*enabled, PLUGIN]
    e = dict(entries)
    e[PLUGIN] = {"allow_gateway_injection": True, "settings": desired}
    p["entries"] = e
    new["plugins"] = p
    try:
        atomic_config_write(path, new)
    except Exception:
        fail("hermes_config_write_failed")
else:
    new = dict(config)
    p = dict(plugins)
    remaining = [item for item in enabled if item != PLUGIN]
    baseline = request.get("enabled_before", {})
    expected = list(baseline.get("value", [])) if baseline.get("present") else []
    if PLUGIN not in expected:
        expected.append(PLUGIN)
    # Restore absence as well as the list only while our install is still untouched.
    if enabled == expected:
        if baseline.get("present"):
            p["enabled"] = baseline.get("value", [])
        else:
            p.pop("enabled", None)
    elif remaining or request.get("enabled_present"):
        p["enabled"] = remaining
    else:
        p.pop("enabled", None)
    e = dict(entries)
    e.pop(PLUGIN, None)
    if e:
        p["entries"] = e
    else:
        p.pop("entries", None)
    if p:
        new["plugins"] = p
    else:
        new.pop("plugins", None)
    try:
        atomic_config_replace(path, new)
    except Exception:
        fail("hermes_config_write_failed")
print(json.dumps({"ok": True, "config_sha256": digest}))
'''


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _integration_dir() -> Path:
    return _repo_root() / "integrations" / "hermes"


def _is_loopback_http(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
                and parsed.port is not None and not parsed.username and not parsed.password
                and not parsed.query and not parsed.fragment and parsed.path in {"", "/"})
    except ValueError:
        return False


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_link_or_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _tree_digests(root: Path, *, exclude_marker: bool = True) -> dict[str, str]:
    if _is_link_or_reparse(root) or not root.is_dir():
        raise ValueError(f"package source is not a real directory: {root}")
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        info = path.lstat()
        if _is_link_or_reparse(path):
            raise ValueError(f"package tree contains a link: {relative}")
        if path.is_dir():
            continue
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"package tree contains a non-file: {relative}")
        if exclude_marker and relative == MARKER:
            continue
        if "__pycache__" in path.parts:
            continue
        result[relative] = _file_digest(path)
    return result


def _read_marker(root: Path) -> dict[str, Any] | None:
    marker = root / MARKER
    if _is_link_or_reparse(root):
        raise ValueError(f"unowned or unsafe package path: {root}")
    if not root.exists():
        return None
    if not root.is_dir() or _is_link_or_reparse(marker) or not marker.is_file():
        raise ValueError(f"unowned or unsafe package path: {root}")
    value = json.loads(marker.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("owner") != "pallium-hermes-package-v1":
        raise ValueError(f"unrecognized package ownership marker: {root}")
    return value


def _verify_owned_tree(root: Path, marker: dict[str, Any], key: str) -> None:
    if _tree_digests(root) != marker.get(key):
        raise ValueError(f"installed package files were changed: {root}")


def _run_hermes(python: Path, home: Path, action: str, request: dict[str, Any] | None = None) -> dict[str, Any]:
    env = os.environ.copy()
    env["HERMES_HOME"] = str(home)
    result = subprocess.run(
        [str(python), "-c", _CONFIG_HELPER, action], input=json.dumps(request or {}),
        capture_output=True, text=True, timeout=20, env=env, check=False,
    )
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        payload = {}
    if result.returncode != 0 or not payload.get("ok"):
        code = payload.get("error", "hermes_preflight_failed")
        raise ValueError(f"Hermes profile refused the operation ({code})")
    return payload


def _validate_pallium_mcp(python: Path) -> None:
    code = "import importlib.metadata as m; import mcp.server; v=m.version('mcp'); assert int(v.split('.')[0]) == 1"
    try:
        result = subprocess.run([str(python), "-c", code], capture_output=True, text=True,
                                timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("Pallium MCP SDK is unavailable in --mcp-python") from exc
    if result.returncode:
        raise ValueError("Pallium MCP SDK v1 is required in --mcp-python")


def _profile_paths(home: Path) -> tuple[Path, Path]:
    if _is_link_or_reparse(home) or not home.is_dir():
        raise ValueError("Hermes home must be an existing real directory")
    for name in ("plugins", "skills"):
        parent = home / name
        if _is_link_or_reparse(parent):
            raise ValueError(f"Hermes profile path is a symlink: {parent}")
    return home / "plugins" / PLUGIN_ID, home / "skills" / "pallium-memory"


def _resolve_profile(home: Path) -> Path:
    path = Path(home).expanduser()
    if _is_link_or_reparse(path) or not path.is_dir():
        raise ValueError("Hermes home must be an existing real directory")
    return path.resolve()


def _settings(args: argparse.Namespace, mcp_python: Path, repo: Path) -> dict[str, Any]:
    if not _is_loopback_http(args.service_url):
        raise ValueError("--service-url must be an explicit loopback HTTP URL")
    if (not isinstance(args.container_ref, str) or not args.container_ref.strip()
            or args.container_ref != args.container_ref.strip() or len(args.container_ref) > 512
            or not args.container_ref.isprintable()):
        raise ValueError("--container-ref must be a non-empty exact scope")
    container_ref = validate_explicit_container_ref(args.container_ref)
    if (not isinstance(args.actor_ref, str) or not args.actor_ref.strip()
            or args.actor_ref != args.actor_ref.strip() or len(args.actor_ref) > 255
            or not args.actor_ref.isprintable()):
        raise ValueError("--actor-ref must be a trimmed, printable static actor identity")
    if args.visibility != "private":
        raise ValueError("this Hermes package currently requires --visibility private")
    memory_enabled = getattr(args, "memory_enabled", False)
    if type(memory_enabled) is not bool:
        raise ValueError("memory_enabled must be a boolean")
    return {
        "service_url": args.service_url.rstrip("/"),
        "container_ref": container_ref,
        "mcp_python": str(mcp_python),
        "mcp_repo": str(repo),
        "actor_ref": args.actor_ref,
        "visibility": args.visibility,
        **({"memory_enabled": True} if memory_enabled else {}),
    }


def _copy_tree(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def _atomic_stage(source: Path, destination: Path, marker: dict[str, Any]) -> tuple[Path, Path | None]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{destination.name}.pallium-", dir=destination.parent))
    staged = stage / "new"
    backup = stage / "old"
    previous = None
    try:
        _copy_tree(source, staged)
        (staged / MARKER).write_text(json.dumps(marker, sort_keys=True, indent=2), encoding="utf-8")
        if destination.exists():
            destination.rename(backup)
            previous = backup
        try:
            staged.rename(destination)
        except BaseException:
            if previous is not None and previous.exists():
                try:
                    previous.rename(destination)
                except OSError as restore_error:
                    raise RuntimeError(f"could not restore {destination}; recovery copy remains at {previous}") from restore_error
            raise
        return stage, previous
    except BaseException:
        if previous is None or not previous.exists():
            shutil.rmtree(stage, ignore_errors=True)
        raise


def _restore_stage(destination: Path, stage: Path, previous: Path | None) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    if previous is not None and previous.exists():
        previous.rename(destination)
    shutil.rmtree(stage)


def _remove_owned(destination: Path) -> tuple[Path, Path | None]:
    parent = destination.parent
    stage = Path(tempfile.mkdtemp(prefix=f".{destination.name}.pallium-remove-", dir=parent))
    backup = stage / "old"
    destination.rename(backup)
    return stage, backup


def install(home: Path, hermes_python: Path, service_url: str, container_ref: str,
            actor_ref: str, visibility: str, mcp_python: Path, repo: Path,
            *, memory_enabled: bool = False) -> int:
    home = _resolve_profile(home)
    hermes_python, mcp_python, repo = (p.resolve() for p in (hermes_python, mcp_python, repo))
    source = _integration_dir()
    skill_source = source / "skills" / "pallium-memory"
    if not (source / "plugin.yaml").is_file() or not (source / "__init__.py").is_file():
        raise ValueError("Hermes plugin source is incomplete")
    if not (skill_source / "SKILL.md").is_file():
        raise ValueError("Pallium Hermes skill source is incomplete")
    if not mcp_python.is_file() or not (repo / "app" / "mcp" / "hermes.py").is_file():
        raise ValueError("--mcp-python or --mcp-repo does not identify the Pallium MCP adapter")
    settings = _settings(argparse.Namespace(service_url=service_url, container_ref=container_ref,
                                            actor_ref=actor_ref, visibility=visibility,
                                            memory_enabled=memory_enabled), mcp_python, repo)
    _validate_pallium_mcp(mcp_python)
    plugin_dir, skill_dir = _profile_paths(home)
    old_plugin = _read_marker(plugin_dir)
    old_skill = _read_marker(skill_dir)
    if bool(old_plugin) != bool(old_skill):
        raise ValueError("Pallium Hermes installation is partial; refusing to overwrite artifacts")
    if old_plugin:
        if old_plugin != old_skill:
            raise ValueError("Pallium Hermes ownership markers disagree")
        _verify_owned_tree(plugin_dir, old_plugin, "plugin_files")
        _verify_owned_tree(skill_dir, old_plugin, "skill_files")
    source_plugin_files = _tree_digests(source)
    source_skill_files = _tree_digests(skill_source)
    before = _run_hermes(hermes_python, home, "validate")
    if old_plugin:
        if before.get("entry") != {"allow_gateway_injection": True,
                                    "settings": old_plugin.get("settings")}:
            raise ValueError("Pallium Hermes config was edited; refusing to replace it")
        enabled_before = old_plugin.get("enabled_before")
    else:
        if PLUGIN_ID in before.get("enabled", []) or before.get("entry") is not None:
            raise ValueError("Hermes already has an unowned Pallium plugin config entry")
        enabled_before = {"present": before.get("enabled_present", False), "value": before.get("enabled", [])}
    marker = {
        "owner": "pallium-hermes-package-v1", "plugin_id": PLUGIN_ID,
        "settings": settings, "enabled_before": enabled_before,
        "plugin_files": source_plugin_files, "skill_files": source_skill_files,
    }
    if old_plugin and old_plugin == marker:
        print("Pallium Hermes package is already current.")
        return 0
    stages: list[tuple[Path, Path, Path | None]] = []
    try:
        for source_tree, destination, file_key in (
            (source, plugin_dir, "plugin_files"), (skill_source, skill_dir, "skill_files"),
        ):
            tree_marker = dict(marker)
            stage, previous = _atomic_stage(source_tree, destination, tree_marker)
            stages.append((destination, stage, previous))
        _run_hermes(hermes_python, home, "install", {
            "expected_sha256": before["config_sha256"],
            "old_settings": old_plugin.get("settings") if old_plugin else None,
            "settings": settings,
            "enable_plugin": old_plugin is None,
        })
    except BaseException as error:
        # The digest detects preflight conflicts, not overlapping writes. Preserve
        # current config on uncertainty; never restore a stale snapshot.
        for destination, stage, previous in reversed(stages):
            _restore_stage(destination, stage, previous)
        detail = str(error)[:300] if isinstance(error, ValueError) else type(error).__name__
        raise RuntimeError(
            f"Hermes config write did not complete ({detail}); current config bytes were preserved for review"
        ) from None
    for _destination, stage, _previous in stages:
        shutil.rmtree(stage, ignore_errors=True)
    print(f"Installed Pallium Hermes package in {home}.")
    print("Status reports configured artifacts only; it does not qualify a running Hermes host.")
    return 0


def status(home: Path, hermes_python: Path) -> int:
    home, hermes_python = _resolve_profile(home), hermes_python.resolve()
    try:
        plugin_dir, skill_dir = _profile_paths(home)
        plugin_marker, skill_marker = _read_marker(plugin_dir), _read_marker(skill_dir)
        if not plugin_marker and not skill_marker:
            state = _run_hermes(hermes_python, home, "status")
            if state.get("entry") is not None or PLUGIN_ID in state.get("enabled", []):
                raise ValueError("orphaned Hermes plugin config exists without owned files")
            print("Pallium Hermes package is not installed.")
            return 0
        if not plugin_marker or plugin_marker != skill_marker:
            raise ValueError("ownership markers are missing or disagree")
        _verify_owned_tree(plugin_dir, plugin_marker, "plugin_files")
        _verify_owned_tree(skill_dir, plugin_marker, "skill_files")
        state = _run_hermes(hermes_python, home, "status", {"settings": plugin_marker["settings"]})
        if state.get("entry") != {"allow_gateway_injection": True,
                                   "settings": plugin_marker.get("settings")}:
            raise ValueError("Hermes plugin config is missing or changed")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Pallium Hermes status conflict: {exc}", file=sys.stderr)
        return 2
    if PLUGIN_ID in state.get("enabled", []):
        print(f"Pallium Hermes package is installed and enabled in {home}.")
    else:
        print(f"Pallium Hermes package is installed but disabled in {home}.")
    print("The profile config and owned file fingerprints match; live MCP readiness is not tested.")
    print("Optional memory: " + ("enabled" if plugin_marker["settings"].get("memory_enabled", False) else "disabled"))
    return 0


def uninstall(home: Path, hermes_python: Path) -> int:
    home, hermes_python = _resolve_profile(home), hermes_python.resolve()
    try:
        plugin_dir, skill_dir = _profile_paths(home)
        plugin_marker, skill_marker = _read_marker(plugin_dir), _read_marker(skill_dir)
        if not plugin_marker and not skill_marker:
            state = _run_hermes(hermes_python, home, "status")
            if state.get("entry") is not None or PLUGIN_ID in state.get("enabled", []):
                raise ValueError("orphaned Hermes plugin config exists without owned files")
            print("Pallium Hermes package is not installed.")
            return 0
        if not plugin_marker or plugin_marker != skill_marker:
            raise ValueError("ownership markers are missing or disagree")
        _verify_owned_tree(plugin_dir, plugin_marker, "plugin_files")
        _verify_owned_tree(skill_dir, plugin_marker, "skill_files")
        state = _run_hermes(hermes_python, home, "status", {"settings": plugin_marker["settings"]})
        if state.get("entry") != {"allow_gateway_injection": True,
                                   "settings": plugin_marker.get("settings")}:
            raise ValueError("Hermes plugin config was edited; refusing removal")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Pallium Hermes removal refused: {exc}", file=sys.stderr)
        return 2
    before = state
    removed: list[tuple[Path, Path, Path]] = []
    try:
        for destination in (plugin_dir, skill_dir):
            stage, backup = _remove_owned(destination)
            removed.append((destination, stage, backup))
        _run_hermes(hermes_python, home, "remove", {
            "expected_sha256": before["config_sha256"],
            "old_settings": plugin_marker["settings"],
            "enabled_present": before.get("enabled_present", False),
            "enabled_before": plugin_marker["enabled_before"],
        })
    except BaseException as exc:
        # A failed CAS may indicate a concurrent user edit. Keep the current
        # config bytes and restore only the files removed by this operation.
        for destination, stage, backup in reversed(removed):
            if backup.exists():
                backup.rename(destination)
            shutil.rmtree(stage, ignore_errors=True)
        print(f"Pallium Hermes removal rolled back: {type(exc).__name__}; current config bytes were preserved for review.",
              file=sys.stderr)
        return 2
    for _destination, stage, _backup in removed:
        shutil.rmtree(stage, ignore_errors=True)
    print("Removed Pallium Hermes package; unrelated config and data were preserved.")
    return 0


def _required_file(parser: argparse.ArgumentParser, value: str, option: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_file():
        parser.error(f"{option} must name an existing file")
    return path.resolve()


def main(args: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install Pallium into an explicit Hermes profile")
    parser.add_argument("--home", required=True, help="Exact HERMES_HOME profile directory")
    parser.add_argument("--hermes-python", required=True, help="Hermes venv Python with MCP SDK v2")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--status", action="store_true", help="Read package state without modifying it")
    mode.add_argument("--uninstall", action="store_true", help="Remove unchanged Pallium-owned artifacts")
    parser.add_argument("--service-url")
    parser.add_argument("--container-ref")
    parser.add_argument("--actor-ref")
    parser.add_argument("--visibility", choices=("private",))
    parser.add_argument("--memory-enabled", action=argparse.BooleanOptionalAction, default=False,
                        help="Expose optional memory tools (disabled by default)")
    parser.add_argument("--mcp-python", default=sys.executable,
                        help="Pallium Python with MCP SDK v1 (defaults to this interpreter)")
    parser.add_argument("--mcp-repo", default=str(_repo_root()), help="Pallium checkout containing app/mcp/hermes.py")
    ns = parser.parse_args(args)
    home_arg = Path(ns.home).expanduser()
    if _is_link_or_reparse(home_arg):
        parser.error("--home must not be a symlink")
    home = home_arg.resolve()
    hermes_python = _required_file(parser, ns.hermes_python, "--hermes-python")
    if ns.status:
        return status(home, hermes_python)
    if ns.uninstall:
        return uninstall(home, hermes_python)
    missing = [name for name in ("service_url", "container_ref", "actor_ref", "visibility")
               if getattr(ns, name) is None]
    if missing:
        parser.error("install requires --" + ", --".join(name.replace("_", "-") for name in missing))
    if not home.is_dir():
        parser.error("--home must be an existing profile directory")
    try:
        return install(home, hermes_python, ns.service_url, ns.container_ref, ns.actor_ref,
                       ns.visibility, Path(ns.mcp_python).expanduser(), Path(ns.mcp_repo).expanduser(),
                       memory_enabled=ns.memory_enabled)
    except Exception as exc:
        print(f"Pallium Hermes setup refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
