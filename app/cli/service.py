"""Pallium local service lifecycle management.

Commands: install, uninstall, status, start, stop, restart, run.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
from pathlib import Path


# ---------------------------------------------------------------------------
# Home resolution
# ---------------------------------------------------------------------------

_DEFAULT_PORT = 19836
_SERVICE_NAME = "pallium.service"
_SERVICE_HOME_MARKER = ".pallium-service-home"

# Seeded into a fresh service config when the dev config has no [observability]
# section, so `pallium service install` arms the historical-lookup reuse funnel
# out of the box. Persistence itself is unconditional; this is the declared
# "armed" signal that `pallium service status` reports.
_FUNNEL_ARMED_BLOCK = (
    "[observability]",
    "historical_lookup_funnel = true",
)


def _pallium_home(override: str | None = None) -> Path:
    if override:
        return Path(override).expanduser().resolve()
    env = os.environ.get("PALLIUM_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".pallium"


def _apply_home_env(home: Path) -> None:
    data_dir = home / "data"
    os.environ.setdefault("PALLIUM_SQLITE_URL", f"sqlite:///{data_dir / 'pallium.db'}")
    os.environ.setdefault("PALLIUM_RELAY_SQLITE_URL", f"sqlite:///{data_dir / 'pallium-relay.db'}")
    os.environ.setdefault("PALLIUM_VECTOR_INDEX_PATH", str(data_dir / "vector_index"))
    config_file = home / "config" / "pallium.toml"
    if config_file.exists():
        os.environ.setdefault("PALLIUM_CONFIG_FILE", str(config_file))
    env_file = home / "config" / ".env"
    if env_file.exists():
        os.environ.setdefault("PALLIUM_ENV_FILE", str(env_file))


def _ensure_dirs(home: Path) -> None:
    for sub in ("data", "logs", "run", "config"):
        (home / sub).mkdir(parents=True, exist_ok=True)


def _validate_service_home(home: Path) -> None:
    if home == Path(home.anchor) or home == Path.home().resolve():
        raise ValueError(f"Refusing unsafe Pallium home: {home}")


def _mark_service_home(home: Path) -> None:
    marker = home / _SERVICE_HOME_MARKER
    expected = str(home) + "\n"
    if marker.exists() and marker.read_text(encoding="utf-8") != expected:
        raise RuntimeError(f"Invalid service-home marker: {marker}")
    marker.write_text(expected, encoding="utf-8")


def _remove_service_data(home: Path) -> None:
    _validate_service_home(home)
    default_home = (Path.home() / ".pallium").resolve()
    if home != default_home:
        raise RuntimeError(
            f"Refusing to remove custom Pallium home automatically: {home}\n"
            "Uninstall preserves custom homes; remove it manually after inspection."
        )
    marker = home / _SERVICE_HOME_MARKER
    if not marker.exists() or marker.read_text(encoding="utf-8") != str(home) + "\n":
        raise RuntimeError(
            f"Refusing to remove unmanaged data directory: {home}\n"
            "Run service install for this exact --home before using --remove-data."
        )
    if home.exists():
        import shutil
        shutil.rmtree(home)


def _seed_config(home: Path) -> None:
    """Write minimal service config if none exists.

    Only includes LLM provider and production package settings.
    Embedding, vector index, and storage all have correct defaults.
    """
    config_dest = home / "config" / "pallium.toml"
    # Config and credentials are independent. An existing TOML must not skip
    # the .env migration or providers start without authentication.
    local_toml = Path("pallium.local.toml")
    if not config_dest.exists() and local_toml.exists():
        lines = local_toml.read_text(encoding="utf-8").splitlines()
        keep_prefixes = (
            "[llm_providers.",
            "[semantic_packages.agent_conversation_memory",
            "[semantic_packages.conversational_knowledge",
        )
        output: list[str] = []
        in_section = False
        for line in lines:
            if line.startswith("["):
                in_section = any(line.startswith(p) for p in keep_prefixes)
            if in_section:
                output.append(line)
            elif output and output[-1] != "":
                output.append("")
        while output and output[-1] == "":
            output.pop()
        # Always seed a CLEAN armed [observability] block. We deliberately do NOT
        # copy the dev config's [observability] section: it can carry dev-only
        # values (e.g. query_audit_log = true, shadow-selector experiment flags)
        # into a fresh install. A fresh install must arm only the funnel signal.
        if not any(line.strip() == "[observability]" for line in output):
            if output:
                output.append("")
            output.extend(_FUNNEL_ARMED_BLOCK)
        if output:
            config_dest.write_text("\n".join(output) + "\n", encoding="utf-8")
            print(f"  Wrote minimal config → {config_dest}")
    elif not config_dest.exists():
        print(f"  No config written (configure LLM provider in {config_dest})")

    env_dest = home / "config" / ".env"
    if not env_dest.exists():
        local_env = Path(".env.local")
        if local_env.exists():
            import shutil
            shutil.copy2(local_env, env_dest)
            print(f"  Copied {local_env} → {env_dest}")


# ---------------------------------------------------------------------------
# File lock
# ---------------------------------------------------------------------------


class _PalliumLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._fd: int | None = None

    def acquire(self) -> bool:
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(path), os.O_CREAT | os.O_RDWR)
        for attempt in range(2):
            try:
                if sys.platform == "win32":
                    import msvcrt
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._fd = fd
                return True
            except (OSError, IOError):
                if attempt == 0:
                    time.sleep(0.1)
        os.close(fd)
        return False

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt
                try:
                    os.lseek(self._fd, 0, os.SEEK_SET)
                    msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl
                fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None


# ---------------------------------------------------------------------------
# Service health / status helpers
# ---------------------------------------------------------------------------


def _read_pid(home: Path) -> int | None:
    pid_file = home / "run" / "pallium.pid"
    if not pid_file.exists():
        return None
    try:
        return int(pid_file.read_text().strip())
    except (ValueError, OSError):
        return None


def _read_port(home: Path) -> int:
    port_file = home / "run" / "port"
    if port_file.exists():
        try:
            return int(port_file.read_text().strip())
        except (ValueError, OSError):
            pass
    return _DEFAULT_PORT


def _is_pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, timeout=5,
            )
            return str(pid) in result.stdout
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def _check_health(port: int, timeout: float = 3.0) -> dict | None:
    try:
        resp = urllib.request.urlopen(
            f"http://127.0.0.1:{port}/health", timeout=timeout
        )
        return json.loads(resp.read())
    except Exception:
        return None


def _read_endpoint_json(port: int, path: str, timeout: float = 3.0) -> dict | None:
    try:
        resp = urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout)
        payload = json.loads(resp.read())
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _service_ready(port: int, timeout: float = 1.0) -> bool:
    health = _check_health(port, timeout=timeout)
    if not health or health.get("status") != "ok":
        return False
    if health.get("vector_index_ready") is not True:
        return False
    if health.get("embedding_provider_ok") is not True:
        return False
    return (
        _read_endpoint_json(port, "/status", timeout=timeout) is not None
        and _read_endpoint_json(port, "/debug/queue/health", timeout=timeout) is not None
    )


def _wait_for_service(port: int, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(1)
        if _service_ready(port):
            return True
        print(".", end="", flush=True)
    return False


def _find_pallium_cmd() -> str:
    if sys.platform == "win32":
        venv_scripts = Path(sys.executable).parent
        cmd = venv_scripts / "pallium.exe"
        if cmd.exists():
            return str(cmd)
    else:
        cmd = Path(sys.executable).parent / "pallium"
        if cmd.exists():
            return str(cmd)
    return "pallium"


# ---------------------------------------------------------------------------
# Platform: Windows (Task Scheduler via schtasks)
# ---------------------------------------------------------------------------


def _install_windows(pallium_cmd: str, port: int, home: Path) -> None:
    task_name = "Pallium"
    username = os.environ.get("USERDOMAIN", "") + "\\" + os.environ.get("USERNAME", "")

    # Write VBS wrapper that launches service with hidden window.
    # WshShell.Run with 0 hides the console window regardless of process type.
    python_exe = sys.executable
    vbs_path = home / "run" / "pallium_launcher.vbs"
    vbs_content = (
        'Set WshShell = CreateObject("WScript.Shell")\n'
        f'WshShell.Run """{python_exe}"" -m app.run service run --port {port} --home ""{home}""", 0, False\n'
    )
    vbs_path.write_text(vbs_content, encoding="utf-16")

    xml_content = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Author>{username}</Author>
    <Description>Pallium local agent service</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{username}</UserId>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{username}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
    <StartWhenAvailable>true</StartWhenAvailable>
    <Enabled>true</Enabled>
    <Hidden>true</Hidden>
  </Settings>
  <Actions>
    <Exec>
      <Command>wscript.exe</Command>
      <Arguments>"{vbs_path}"</Arguments>
    </Exec>
  </Actions>
</Task>"""

    xml_file = Path(tempfile.mktemp(suffix=".xml"))
    try:
        xml_file.write_text(xml_content, encoding="utf-16")
        result = subprocess.run(
            ["schtasks", "/create", "/tn", task_name, "/xml", str(xml_file), "/f"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"  Error registering task: {result.stderr.strip()}", file=sys.stderr)
            raise SystemExit(1)
    finally:
        xml_file.unlink(missing_ok=True)

    print(f"  Registered scheduled task '{task_name}'")


def _uninstall_windows() -> None:
    task_name = "Pallium"
    subprocess.run(
        ["schtasks", "/delete", "/tn", task_name, "/f"],
        capture_output=True, text=True,
    )
    print(f"  Removed scheduled task '{task_name}'")


def _start_windows(home: Path | None = None) -> None:
    if home is None:
        home = _pallium_home()
    vbs_path = home / "run" / "pallium_launcher.vbs"
    if not vbs_path.exists():
        raise RuntimeError(
            f"Launcher not found: {vbs_path}\n"
            "Run 'pallium service install' to create it."
        )
    subprocess.Popen(
        ["wscript.exe", str(vbs_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# ---------------------------------------------------------------------------
# Platform: Linux (systemd user unit)
# ---------------------------------------------------------------------------


def _linux_unit_file() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / _SERVICE_NAME


def _systemd_quote(value: str) -> str:
    if "\x00" in value or "\n" in value or "\r" in value:
        raise ValueError("systemd unit values cannot contain NUL or newlines")
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    return f'"{escaped}"'


def _systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["systemctl", "--user", *args],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
        raise RuntimeError(f"systemctl --user {' '.join(args)} failed: {detail}")
    return result


def _linux_unit_home() -> Path | None:
    unit_file = _linux_unit_file()
    if not unit_file.exists():
        return None
    for line in unit_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("# PalliumHome="):
            try:
                return Path(json.loads(line.removeprefix("# PalliumHome="))).resolve()
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise RuntimeError(f"Invalid Pallium home marker in {unit_file}") from exc
        if line.startswith("Environment=PALLIUM_HOME="):
            return Path(line.removeprefix("Environment=PALLIUM_HOME=")).resolve()
    raise RuntimeError(f"Cannot determine Pallium home from existing unit: {unit_file}")


def _assert_linux_unit_home(home: Path) -> None:
    installed_home = _linux_unit_home()
    if installed_home is not None and installed_home != home:
        raise RuntimeError(
            f"{_SERVICE_NAME} already targets {installed_home}; refusing to retarget it to {home}. "
            f"Uninstall the existing service first."
        )


def _linux_unit_state() -> dict[str, str]:
    result = _systemctl(
        "show",
        _SERVICE_NAME,
        "--property=LoadState",
        "--property=ActiveState",
        "--property=SubState",
        "--property=MainPID",
        "--property=TasksCurrent",
        "--property=Result",
    )
    return dict(
        line.split("=", 1)
        for line in result.stdout.splitlines()
        if "=" in line
    )


def _install_linux(pallium_cmd: str, port: int, home: Path) -> None:
    _systemctl("show-environment")
    _assert_linux_unit_home(home)

    unit_file = _linux_unit_file()
    unit_file.parent.mkdir(parents=True, exist_ok=True)
    unit_content = f"""# PalliumHome={json.dumps(str(home), ensure_ascii=False)}
[Unit]
Description=Pallium local agent service
After=network.target

[Service]
Type=simple
ExecStart={_systemd_quote(pallium_cmd)} service run --port {port} --home {_systemd_quote(str(home))}
Environment={_systemd_quote(f"PALLIUM_HOME={home}")}
Environment=PYTHONUNBUFFERED=1
Restart=on-failure
RestartSec=5
KillMode=control-group
TimeoutStopSec=15

[Install]
WantedBy=default.target
"""
    unit_file.write_text(unit_content, encoding="utf-8")
    print(f"  Wrote {unit_file}")

    _systemctl("daemon-reload")
    _systemctl("enable", _SERVICE_NAME)
    (home / "run" / "port").write_text(str(port), encoding="utf-8")
    _systemctl("restart", _SERVICE_NAME)
    print(f"  Enabled and started {_SERVICE_NAME}")


def _uninstall_linux(home: Path) -> None:
    unit_file = _linux_unit_file()
    if not unit_file.exists():
        print(f"  {_SERVICE_NAME} is not installed")
        return
    _systemctl("show-environment")
    _assert_linux_unit_home(home)
    _systemctl("stop", _SERVICE_NAME)
    _systemctl("disable", _SERVICE_NAME)
    unit_file.unlink()
    _systemctl("daemon-reload")
    print(f"  Removed {_SERVICE_NAME}")


def _start_linux() -> None:
    _systemctl("start", _SERVICE_NAME)


def _stop_linux() -> None:
    _systemctl("stop", _SERVICE_NAME)


def _restart_linux() -> None:
    _systemctl("restart", _SERVICE_NAME)


# ---------------------------------------------------------------------------
# CLI subcommands
# ---------------------------------------------------------------------------


def _missing_declared_credentials(config) -> list[str]:
    missing = set()
    for package in config.semantic_packages.values():
        if not package.enabled or package.implementation == "demo_agent_memory" or not package.llm_provider:
            continue
        provider = config.llm_providers.get(package.llm_provider)
        if provider is not None and not provider.api_key:
            locator = provider.api_key_env or provider.api_key_file
            if locator:
                missing.add(locator)
    return sorted(missing)


def _processor_count(config) -> int:
    return 0 if _missing_declared_credentials(config) else 1


def _cmd_install(args: argparse.Namespace) -> int:
    home = _pallium_home(args.home)
    port = args.port

    print("Installing Pallium service...")
    print(f"  Home: {home}")
    print(f"  Port: {port}")

    try:
        _validate_service_home(home)
        if sys.platform == "linux":
            _systemctl("show-environment")
            _assert_linux_unit_home(home)
    except (RuntimeError, ValueError) as exc:
        print(f"  Error: {exc}", file=sys.stderr)
        return 1

    _ensure_dirs(home)
    try:
        _mark_service_home(home)
    except RuntimeError as exc:
        print(f"  Error: {exc}", file=sys.stderr)
        return 1

    # Copy local config to service home if none exists there yet.
    _seed_config(home)
    _apply_home_env(home)

    from app.config import AppConfig
    missing_credentials = _missing_declared_credentials(AppConfig.from_env())
    if missing_credentials:
        print(
            "  Missing configured credential(s): " + ", ".join(missing_credentials),
            file=sys.stderr,
        )
        print(
            "  Ingestion will stay paused; Relay and inspection remain available. "
            "Add credentials to " + str(home / "config" / ".env") + " and restart.",
            file=sys.stderr,
        )

    pallium_cmd = _find_pallium_cmd()
    print(f"  Command: {pallium_cmd}")

    if sys.platform == "win32":
        _install_windows(pallium_cmd, port, home)
    elif sys.platform != "linux":
        print(f"  macOS auto-start not yet supported. Run manually: pallium service run --port {port}")

    # Download before enabling the Linux unit so a slow first download cannot
    # race a separately started service process.
    print("  Downloading embedding model...")
    from app.run import _run_download_embedding_model
    _run_download_embedding_model()

    print("  Starting service...")
    try:
        if sys.platform == "win32":
            _start_windows(home)
        elif sys.platform == "linux":
            _install_linux(pallium_cmd, port, home)
    except RuntimeError as exc:
        print(f"  Error starting service: {exc}", file=sys.stderr)
        return 1

    print("  Waiting for health, status, and queue checks...", end="", flush=True)
    if _wait_for_service(port):
        print(" OK")
        print(f"\nPallium service installed and running on port {port}.")
        return 0

    print(" TIMEOUT", file=sys.stderr)
    print("  Service did not become ready within 30s.", file=sys.stderr)
    print("  Check logs at:", home / "logs", file=sys.stderr)
    return 1


def _cmd_uninstall(args: argparse.Namespace) -> int:
    home = _pallium_home(args.home if hasattr(args, "home") else None)

    print("Uninstalling Pallium service...")
    try:
        if sys.platform == "win32":
            _cmd_stop_impl(home)
            _uninstall_windows()
        elif sys.platform == "linux":
            _uninstall_linux(home)
        else:
            print("  No service registration to remove (macOS stub).")
    except RuntimeError as exc:
        print(f"  Error: {exc}", file=sys.stderr)
        return 1

    if args.remove_data:
        try:
            _remove_service_data(home)
        except (RuntimeError, ValueError) as exc:
            print(f"  Error: {exc}", file=sys.stderr)
            return 1
        print(f"  Removed data directory: {home}")
    else:
        print(f"  Data preserved at: {home}")

    print("Done.")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    home = _pallium_home(args.home if hasattr(args, "home") else None)
    port = _read_port(home)

    if sys.platform == "linux":
        try:
            _assert_linux_unit_home(home)
            state = _linux_unit_state()
        except RuntimeError as exc:
            print(f"Pallium: service-manager error: {exc}", file=sys.stderr)
            return 1
        if state.get("LoadState") != "loaded":
            print("Pallium: not installed")
            print(f"  Home: {home}")
            return 1
        if state.get("ActiveState") != "active":
            print(
                f"Pallium: not running "
                f"(systemd {state.get('ActiveState', '?')}/{state.get('SubState', '?')})"
            )
            print(f"  Home: {home}")
            return 1
        try:
            pid = int(state.get("MainPID", "0"))
        except ValueError:
            pid = 0
        if pid <= 0:
            print("Pallium: systemd is active but has no main process")
            print(f"  Home: {home}")
            return 1
    else:
        pid = _read_pid(home)
        if pid is None or not _is_pid_alive(pid):
            detail = "no PID file" if pid is None else f"stale PID {pid}"
            print(f"Pallium: not running ({detail})")
            print(f"  Home: {home}")
            return 1

    health = _check_health(port)
    if not health:
        print(f"Pallium: process alive (PID {pid}) but not responding on port {port}")
        print(f"  Home: {home}")
        return 1
    if sys.platform == "linux" and not _service_ready(port):
        print(f"Pallium: process alive (PID {pid}) but readiness checks are incomplete")
        print(f"  Home: {home}")
        return 1

    try:
        import importlib.metadata
        version = importlib.metadata.version("pallium")
    except Exception:
        version = "unknown"

    print("Pallium: running")
    print(f"  Version: {version}")
    print(f"  PID:     {pid}")
    print(f"  Port:    {port}")
    print(f"  Home:    {home}")
    print(f"  Health:  {health.get('status', '?')}")

    # Try to get extended status
    try:
        resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/status", timeout=3)
        status_data = json.loads(resp.read())
        uptime = status_data.get("uptime_seconds")
        if uptime is not None:
            print(f"  Uptime:  {int(uptime)}s")
        storage = status_data.get("storage", {})
        db_mb = storage.get("sqlite_mb")
        if db_mb is not None:
            print(f"  DB size: {db_mb} MB")
        relay_mb = storage.get("relay_sqlite_mb")
        if relay_mb is not None:
            print(f"  Relay DB size: {relay_mb} MB")
        funnel = status_data.get("historical_lookup_funnel")
        if isinstance(funnel, dict):
            armed = "yes" if funnel.get("armed") else "no"
            recorded = funnel.get("events_recorded")
            recorded_str = f", {recorded} events recorded" if recorded is not None else ""
            print(f"  Reuse funnel armed: {armed}{recorded_str}")
    except Exception:
        pass

    return 0


def _cmd_stop_impl(home: Path) -> bool:
    port = _read_port(home)
    pid = _read_pid(home)

    if pid is None or not _is_pid_alive(pid):
        return True

    # Try graceful HTTP shutdown
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/shutdown",
            method="POST",
            data=b"",
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass

    # Wait for exit
    for _ in range(20):
        time.sleep(0.5)
        if not _is_pid_alive(pid):
            return True

    # Force kill
    if sys.platform == "win32":
        # CREATE_NO_WINDOW (0x08000000): under pythonw.exe (no parent console)
        # a bare taskkill spawns a visible console window on each call.
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            creationflags=0x08000000,
        )
    else:
        os.kill(pid, signal.SIGKILL)

    time.sleep(1)
    return not _is_pid_alive(pid)


def _cmd_stop(args: argparse.Namespace) -> int:
    home = _pallium_home(args.home if hasattr(args, "home") else None)

    if sys.platform == "linux":
        try:
            _assert_linux_unit_home(home)
            state = _linux_unit_state()
            if state.get("LoadState") != "loaded" or state.get("ActiveState") != "active":
                print("Pallium: not running")
                return 0
            print(f"Stopping Pallium (PID {state.get('MainPID', '?')})...", end="", flush=True)
            _stop_linux()
            stopped = _linux_unit_state()
        except RuntimeError as exc:
            print(f" failed: {exc}", file=sys.stderr)
            return 1
        if (
            stopped.get("ActiveState") == "inactive"
            and stopped.get("MainPID") == "0"
            and stopped.get("TasksCurrent", "") in {"", "0", "[not set]"}
        ):
            print(" stopped.")
            return 0
        print(f" failed: systemd state is {stopped}", file=sys.stderr)
        return 1

    pid = _read_pid(home)
    if pid is None or not _is_pid_alive(pid):
        print("Pallium: not running")
        return 0

    print(f"Stopping Pallium (PID {pid})...", end="", flush=True)
    if _cmd_stop_impl(home):
        print(" stopped.")
        return 0
    print(" failed to stop.", file=sys.stderr)
    return 1


def _cmd_start(args: argparse.Namespace) -> int:
    home = _pallium_home(args.home if hasattr(args, "home") else None)
    port = _read_port(home)
    try:
        if sys.platform == "win32":
            _start_windows(home)
        elif sys.platform == "linux":
            _assert_linux_unit_home(home)
            _start_linux()
        else:
            print("Cannot auto-start on this platform. Run: pallium service run")
            return 1
    except RuntimeError as exc:
        print(f"Error starting service: {exc}", file=sys.stderr)
        return 1

    print(f"Starting Pallium on port {port}...", end="", flush=True)
    if _wait_for_service(port):
        print(" OK")
        return 0
    print(" TIMEOUT", file=sys.stderr)
    return 1


def _cmd_restart(args: argparse.Namespace) -> int:
    home = _pallium_home(args.home if hasattr(args, "home") else None)
    port = _read_port(home)

    if sys.platform == "win32":
        vbs_path = home / "run" / "pallium_launcher.vbs"
        if not vbs_path.exists():
            print(f"Error: launcher not found: {vbs_path}", file=sys.stderr)
            print("Run 'pallium service install' to create it.", file=sys.stderr)
            return 1

    try:
        if sys.platform == "win32":
            _cmd_stop_impl(home)
            _start_windows(home)
        elif sys.platform == "linux":
            _assert_linux_unit_home(home)
            _restart_linux()
        else:
            print("Cannot auto-start on this platform. Run: pallium service run")
            return 1
    except RuntimeError as exc:
        print(f"Error restarting service: {exc}", file=sys.stderr)
        return 1

    print(f"Restarting Pallium on port {port}...", end="", flush=True)
    if _wait_for_service(port):
        print(" OK")
        return 0
    print(" TIMEOUT", file=sys.stderr)
    return 1


def _cmd_run(args: argparse.Namespace) -> int:
    """Internal daemon entry point — what the OS service invokes."""
    home = _pallium_home(args.home if hasattr(args, "home") else None)
    port = args.port
    _ensure_dirs(home)
    _apply_home_env(home)

    # Acquire lock
    lock = _PalliumLock(home / "run" / "pallium.lock")
    if not lock.acquire():
        pid = _read_pid(home)
        print(f"Pallium is already running (PID {pid or '?'}). Exiting.", file=sys.stderr)
        return 1

    # Write PID and port
    (home / "run" / "pallium.pid").write_text(str(os.getpid()))
    (home / "run" / "port").write_text(str(port))

    # Configure file logging
    from app.runtime_logging import configure_file_logging
    log_stream = configure_file_logging(home / "logs")

    # Report active configuration
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO)
    from app.config import AppConfig
    config = AppConfig.from_env()
    from app.dependencies import build_semantic_plugins
    plugins = build_semantic_plugins(config)
    active_names = list(plugins.keys())
    processors = _processor_count(config)
    from app.runtime_logging import emit_runtime_log
    emit_runtime_log("service", f"Active packages: {', '.join(active_names)}")
    emit_runtime_log("service", f"Default use case: {config.default_use_case}")
    embedding_model = next(iter(config.embedding_providers.values()), None)
    if embedding_model:
        emit_runtime_log("service", f"Embedding model: {embedding_model.model}")
    if processors == 0:
        emit_runtime_log("service", "Ingestion paused: configured provider credential is missing")

    try:
        from app.supervisor import run_supervisor
        supervisor_args = [
            "--host", "127.0.0.1",
            "--port", str(port),
            "--processors", str(processors),
            "--cleaners", "1",
        ]
        return run_supervisor(
            supervisor_args,
            log_file=home / "logs" / "pallium.log",
            log_stream=log_stream,
        )
    finally:
        lock.release()
        pid_file = home / "run" / "pallium.pid"
        if pid_file.exists():
            pid_file.unlink(missing_ok=True)
        # The port describes the installed service, not process liveness.
        # Keep it across stop/start so custom-port lifecycle commands stay exact.


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def service_main(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="pallium service", description="Manage Pallium local service")
    sub = parser.add_subparsers(dest="action")

    install_p = sub.add_parser("install", help="Install and start Pallium as a local service")
    install_p.add_argument("--port", type=int, default=_DEFAULT_PORT)
    install_p.add_argument("--home", type=str, default=None)

    uninstall_p = sub.add_parser("uninstall", help="Remove service registration")
    uninstall_p.add_argument("--remove-data", action="store_true", help="Also delete memory data")
    uninstall_p.add_argument("--home", type=str, default=None)

    status_p = sub.add_parser("status", help="Show service status")
    status_p.add_argument("--home", type=str, default=None)

    start_p = sub.add_parser("start", help="Start the installed service")
    start_p.add_argument("--home", type=str, default=None)

    stop_p = sub.add_parser("stop", help="Stop the running service")
    stop_p.add_argument("--home", type=str, default=None)

    restart_p = sub.add_parser("restart", help="Restart the service")
    restart_p.add_argument("--home", type=str, default=None)

    run_p = sub.add_parser("run", help="Run the service (internal, used by OS service manager)")
    run_p.add_argument("--port", type=int, default=_DEFAULT_PORT)
    run_p.add_argument("--home", type=str, default=None)

    parsed = parser.parse_args(args)
    if not parsed.action:
        parser.print_help()
        return 1

    dispatch = {
        "install": _cmd_install,
        "uninstall": _cmd_uninstall,
        "status": _cmd_status,
        "start": _cmd_start,
        "stop": _cmd_stop,
        "restart": _cmd_restart,
        "run": _cmd_run,
    }
    return dispatch[parsed.action](parsed)
