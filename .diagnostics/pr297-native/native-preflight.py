"""Future-job preflight only: no application tests, package installs or sysctl writes."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import _sqlite3

HERE = Path(__file__).resolve().parent
OUTPUT = Path(os.environ["PALLIUM_NATIVE_PREFLIGHT_OUTPUT"])
OUTPUT.mkdir(exist_ok=False)
EXPECTED_PYTHON = "329d378575992732511d75b3bd675cb91b3c65f3082783cd97ccb14f0ecd5a74"


def command(*args):
    return subprocess.check_output(args, text=True, timeout=15)


def linked(binary, soname):
    output = command("/usr/bin/ldd", str(binary))
    match = re.search(r"^\s*" + re.escape(soname) + r"\s+=>\s+(/[^\s]+)", output, re.M)
    assert match, "Required shared library not resolved: " + soname
    path = Path(match[1]).resolve(strict=True)
    assert re.fullmatch(r"/[A-Za-z0-9_./+-]+", str(path)), "Unsafe probe path"
    return path


def symbols(path, wanted):
    table = command("/usr/bin/readelf", "--wide", "--dyn-syms", str(path))
    names = {line.split()[-1].split("@")[0] for line in table.splitlines() if " FUNC " in line and " UND " not in line}
    assert set(wanted) <= names, "Missing public native probe symbol"
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                build_id=command("/usr/bin/readelf", "-n", str(path)), symbols=wanted)


assert sys.platform == "linux" and sys.version_info[:3] == (3, 13, 16)
assert os.environ.get("ImageVersion") == "20261018.339.1", "Unreviewed image"
assert command("/usr/bin/uname", "-r").strip() == "7.0.0-1017-azure"
python = Path(sys.executable).resolve(strict=True)
assert hashlib.sha256(python.read_bytes()).hexdigest() == EXPECTED_PYTHON
assert _sqlite3.sqlite_version == "3.45.1"
assert "v0.20.2" in command("/usr/bin/bpftrace", "--version")
subprocess.run(["/usr/bin/sudo", "-n", "/usr/bin/true"], check=True, timeout=5)
sqlite_extension = Path(_sqlite3.__file__).resolve(strict=True)
libpython = linked(python, "libpython3.13.so.1.0")
libsqlite = linked(sqlite_extension, "libsqlite3.so.0")
sqlite_symbols = ["sqlite3_prepare_v2", "sqlite3_step", "sqlite3_reset", "sqlite3_column_count", "sqlite3_last_insert_rowid"]
provenance = dict(python=str(python), python_sha256=EXPECTED_PYTHON,
                  sqlite_extension=dict(path=str(sqlite_extension), sha256=hashlib.sha256(sqlite_extension.read_bytes()).hexdigest()),
                  libpython=symbols(libpython, ["PyEval_RestoreThread"]),
                  libsqlite=symbols(libsqlite, sqlite_symbols))
(OUTPUT / "native-identities.json").write_text(json.dumps(provenance, indent=2))
program = (HERE / "native.bt.in").read_text().replace("__SQLITE__", str(libsqlite)).replace("__PYTHON__", str(libpython))
(OUTPUT / "native.bt").write_text(program)
print("Native identities and probe program prepared; controller must prove attachment before pytest.")
