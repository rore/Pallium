from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="/proc/self/fd is Linux-specific")
def test_scope_guard_checks_integer_file_descriptors_in_child(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    child = r'''
import json
import os
import stat
import sys
from pathlib import Path
from tests.fixtures.hermes_scope_probe import install_guard

root = Path(sys.argv[1])
work = root / "work"
outside = root / "outside"
work.mkdir()
outside.mkdir()
owned = work / "owned.json"
external = outside / "external.json"
owned.write_text("owned")
external.write_text("outside")
owned.chmod(0o640)
external.chmod(0o640)
(work / "closed-marker").write_text("closed")
external_mode = stat.S_IMODE(external.stat().st_mode)
owned_fd = os.open(owned, os.O_RDONLY)
external_fd = os.open(external, os.O_RDONLY)
pipe_read, pipe_write = os.pipe()
closed_fd = os.open(work / "closed-marker", os.O_RDONLY)
os.close(closed_fd)
denied = install_guard(work, root, root / "sdk")
os.fchmod(owned_fd, 0o600)
assert stat.S_IMODE(owned.stat().st_mode) == 0o600
try:
    os.fchmod(external_fd, 0o600)
except PermissionError:
    pass
else:
    raise AssertionError("outside descriptor was allowed")
assert stat.S_IMODE(external.stat().st_mode) == external_mode
for descriptor in (pipe_read, closed_fd):
    try:
        os.fchmod(descriptor, 0o600)
    except PermissionError:
        pass
    else:
        raise AssertionError(f"unresolved descriptor {descriptor} was allowed")
assert len(denied) == 3, denied
assert [entry["event"] for entry in denied] == ["os.chmod"] * 3, denied
print(json.dumps(denied))
'''
    result = subprocess.run([sys.executable, "-c", child, str(tmp_path)], cwd=repo,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
