"""Capture original context privately and invoke only the frozen root controller."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
assert os.getuid() == os.geteuid() != 0
manifest = json.loads((HERE / "manifest.json").read_text())
for name, wanted in manifest["sha256"].items():
    path = HERE / name
    assert path.is_file() and not path.is_symlink()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == wanted, name
assert subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip() == "07697ac2b8f74e8503534a6586fb13dbb30bdeb4"
output = Path(os.environ["PALLIUM_DIAGNOSTIC_OUTPUT"]).resolve()
output.mkdir(exist_ok=False)
(output / "native").mkdir()
preflight_output = output / "native-preflight"
# Required process-local diagnostic variable; captured before privilege changes.
os.environ["PALLIUM_NATIVE_PREFLIGHT_OUTPUT"] = str(preflight_output)
mask = os.umask(0o077)
os.umask(mask)
private = Path(tempfile.mkdtemp(prefix="pr297-native-private-", dir=os.environ["RUNNER_TEMP"]))
request = private / "request.json"
payload = dict(uid=os.getuid(), gid=os.getgid(), groups=os.getgroups(), cwd=os.getcwd(),
               umask=mask, environment=dict(os.environ), python=str(Path(sys.executable).resolve()),
               preflight=str(HERE / "native-preflight.py"), runner=str(HERE / "qualification.py"),
               helper=str(HERE / "restore-context.py"), output=str(output), preflight_output=str(preflight_output))
with os.fdopen(os.open(request, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as file:
    json.dump(payload, file)
try:
    result = subprocess.run(["/usr/bin/sudo", "-n", payload["python"], "-I", "-S",
                             str(HERE / "native-controller.py"), str(request)])
    raise SystemExit(result.returncode)
finally:
    request.unlink(missing_ok=True)
    private.rmdir()

