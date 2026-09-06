"""Opt-in Linux user-service lifecycle E2E.

Run only in a disposable Linux user session with no installed Pallium unit:
PALLIUM_RUN_LINUX_SERVICE_E2E=1 python -m pytest \
    tests/test_linux_service_lifecycle_e2e.py -m slow -n 0 -q
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest


pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(sys.platform != "linux", reason="Linux-only"),
    pytest.mark.skipif(
        os.environ.get("PALLIUM_RUN_LINUX_SERVICE_E2E") != "1",
        reason="requires a disposable Linux user-service session",
    ),
]


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _json_endpoint(port: int, path: str, timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}{path}", timeout=1
            ) as response:
                payload = json.loads(response.read())
                if isinstance(payload, dict):
                    return payload
        except Exception:
            time.sleep(0.5)
    pytest.fail(f"endpoint did not become ready: {path}")


def test_linux_service_full_lifecycle(tmp_path: Path):
    unit = Path.home() / ".config/systemd/user/pallium.service"
    if unit.exists():
        pytest.skip(f"refusing to replace pre-existing unit: {unit}")

    subprocess.run(
        ["systemctl", "--user", "show-environment"],
        check=True,
        capture_output=True,
        text=True,
    )

    repo = Path(__file__).resolve().parents[1]
    pallium = Path(sys.executable).with_name("pallium")
    home = (tmp_path / "Pallium Linux בית").resolve()
    other_home = (tmp_path / "other home").resolve()
    unmanaged = (tmp_path / "unmanaged").resolve()
    port = _free_port()

    (home / "config").mkdir(parents=True)
    preexisting_sentinel = home / "keep-before-install"
    preexisting_sentinel.write_text("keep", encoding="utf-8")
    (home / "config/pallium.toml").write_text(
        'default_use_case = "demo_agent_memory"\n'
        "\n"
        "[semantic_packages.demo_agent_memory]\n"
        'implementation = "demo_agent_memory"\n'
        "\n"
        "[embedding_providers.onnx]\n"
        'kind = "onnx"\n'
        'model = "intfloat/multilingual-e5-base"\n'
        "\n"
        "[vector_index]\n"
        "enabled = true\n"
        'embedding_provider = "onnx"\n',
        encoding="utf-8",
    )

    def cli(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(pallium), "service", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=120,
        )

    try:
        installed = subprocess.run(
            [
                str(repo / "scripts/install-service.sh"),
                "--port",
                str(port),
                "--home",
                str(home),
                "--python",
                sys.executable,
            ],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert installed.returncode == 0, installed.stdout + installed.stderr
        reinstalled = cli("install", "--port", str(port), "--home", str(home))
        assert reinstalled.returncode == 0, reinstalled.stdout + reinstalled.stderr
        assert unit.exists()
        subprocess.run(
            ["systemd-analyze", "--user", "verify", str(unit)],
            check=True,
            capture_output=True,
            text=True,
        )

        health = _json_endpoint(port, "/health")
        assert health == {
            "status": "ok",
            "vector_index_ready": True,
            "embedding_provider_ok": True,
        }
        assert _json_endpoint(port, "/status")["storage"]["relay_migration_ready"]
        assert isinstance(_json_endpoint(port, "/debug/queue/health"), dict)

        status = cli("status", "--home", str(home))
        assert status.returncode == 0, status.stdout + status.stderr
        pid_file = home / "run/pallium.pid"
        actual_pid = pid_file.read_text(encoding="utf-8")
        pid_file.unlink()
        missing_pid_status = cli("status", "--home", str(home))
        assert missing_pid_status.returncode == 0, missing_pid_status.stdout + missing_pid_status.stderr
        pid_file.write_text("99999999", encoding="utf-8")
        stale_pid_status = cli("status", "--home", str(home))
        assert stale_pid_status.returncode == 0, stale_pid_status.stdout + stale_pid_status.stderr
        pid_file.write_text(actual_pid, encoding="utf-8")

        old_pid = subprocess.run(
            ["systemctl", "--user", "show", "pallium.service", "-p", "MainPID", "--value"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        restarted = cli("restart", "--home", str(home))
        assert restarted.returncode == 0, restarted.stdout + restarted.stderr
        new_pid = subprocess.run(
            ["systemctl", "--user", "show", "pallium.service", "-p", "MainPID", "--value"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert new_pid not in {"0", old_pid}

        wrapper = subprocess.run(
            [
                str(repo / "scripts/restart-service.sh"),
                "--home",
                str(home),
                "--python",
                sys.executable,
            ],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert wrapper.returncode == 0, wrapper.stdout + wrapper.stderr

        refused = cli("install", "--port", str(_free_port()), "--home", str(other_home))
        assert refused.returncode != 0
        assert not other_home.exists()
        assert _json_endpoint(port, "/health")["status"] == "ok"

        stopped = cli("stop", "--home", str(home))
        assert stopped.returncode == 0, stopped.stdout + stopped.stderr
        stopped_state = subprocess.run(
            [
                "systemctl",
                "--user",
                "show",
                "pallium.service",
                "-p",
                "ActiveState",
                "-p",
                "MainPID",
                "-p",
                "TasksCurrent",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        stopped_values = dict(
            line.split("=", 1) for line in stopped_state.splitlines() if "=" in line
        )
        assert stopped_values["ActiveState"] == "inactive"
        assert stopped_values["MainPID"] == "0"
        assert stopped_values.get("TasksCurrent", "") in {"", "0", "[not set]"}
        assert (home / "run/port").read_text() == str(port)
        with socket.socket() as probe:
            assert probe.connect_ex(("127.0.0.1", port)) != 0

        started = cli("start", "--home", str(home))
        assert started.returncode == 0, started.stdout + started.stderr
        crashed_pid = subprocess.run(
            ["systemctl", "--user", "show", "pallium.service", "-p", "MainPID", "--value"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        subprocess.run(
            [
                "systemctl",
                "--user",
                "kill",
                "--kill-whom=main",
                "--signal=SIGKILL",
                "pallium.service",
            ],
            check=True,
        )
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            recovered_pid = subprocess.run(
                [
                    "systemctl",
                    "--user",
                    "show",
                    "pallium.service",
                    "-p",
                    "MainPID",
                    "--value",
                ],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            if recovered_pid not in {"0", crashed_pid}:
                try:
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/health", timeout=1
                    ) as response:
                        if json.loads(response.read()).get("status") == "ok":
                            break
                except Exception:
                    pass
            time.sleep(1)
        else:
            pytest.fail("systemd did not recover the crashed service")

        unmanaged.mkdir()
        unmanaged_sentinel = unmanaged / "keep"
        unmanaged_sentinel.write_text("keep", encoding="utf-8")
        unit_before_refusal = unit.read_text(encoding="utf-8")
        unsafe = cli("uninstall", "--remove-data", "--home", str(unmanaged))
        assert unsafe.returncode != 0
        assert unmanaged_sentinel.read_text(encoding="utf-8") == "keep"
        assert unit.read_text(encoding="utf-8") == unit_before_refusal
        assert _json_endpoint(port, "/health")["status"] == "ok"

        sentinel = home / "data/preserve-me"
        sentinel.write_text("preserved", encoding="utf-8")
        removed_unit = subprocess.run(
            [
                str(repo / "scripts/uninstall-service.sh"),
                "--home",
                str(home),
                "--python",
                sys.executable,
            ],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert removed_unit.returncode == 0, removed_unit.stdout + removed_unit.stderr
        assert not unit.exists()
        assert sentinel.read_text(encoding="utf-8") == "preserved"
        assert cli("uninstall", "--home", str(home)).returncode == 0

        refused_data = cli("uninstall", "--remove-data", "--home", str(home))
        assert refused_data.returncode != 0
        assert preexisting_sentinel.read_text(encoding="utf-8") == "keep"
        assert home.exists()
    finally:
        if unit.exists():
            subprocess.run(
                ["systemctl", "--user", "stop", "pallium.service"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            cli("uninstall", "--home", str(home))
