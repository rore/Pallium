"""Real pinned Hermes route probes, separate from full native UI qualification."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest

from tests.fixtures.hermes_linux_guard import require_contained_paths, require_linux_qualification


pytestmark = pytest.mark.slow


@pytest.mark.parametrize("case", ["live_restore", "gateway", "tui"])
def test_released_hermes_missing_route_boundaries(tmp_path, case):
    source, python = os.environ.get("HERMES_E2E_SOURCE"), os.environ.get("HERMES_E2E_PYTHON")
    if not source or not python:
        pytest.skip("set HERMES_E2E_SOURCE/PYTHON to the isolated v0.22.4 source/runtime")
    require_linux_qualification()
    driver = Path(__file__).parent / "fixtures" / "hermes_route_probe.py"
    require_contained_paths(Path(source), Path(python), driver, tmp_path)
    result = subprocess.run([
        python, str(driver), "--source", source, "--work", str(tmp_path / case), "--case", case,
    ], text=True, encoding="utf-8", capture_output=True, timeout=45)
    (tmp_path / "stdout.log").write_text(result.stdout, encoding="utf-8")
    (tmp_path / "stderr.log").write_text(result.stderr, encoding="utf-8")
    assert result.returncode == 0, (result.stdout, result.stderr)
    receipt = json.loads(result.stdout.splitlines()[-1])
    assert receipt["case"] == case and receipt["healthy_restore"] is True
    assert receipt["revision"] == "4d04303818b61bf3aa09278af48356315515965b"
    assert receipt["actual_source_modules"] > 0 and receipt["cleanup"]
    if case == "live_restore":
        assert receipt["admission_conflict"] and receipt["pauses"] == receipt["queued"] == 2
        assert receipt["cold_restore"] and receipt["non_stray_rival_refused"]
    elif case == "gateway":
        assert receipt["scheduled"] and receipt["not_routed"] and not receipt["dispatched"]
        assert receipt["queued"] == 0
    else:
        assert receipt["tui_queue"] and receipt["exact_session"] and not receipt["gateway_called"]
        assert receipt["queued"] == 1
    (tmp_path / "result.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
