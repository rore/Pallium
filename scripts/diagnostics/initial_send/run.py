"""One fixed hosted diagnostic child; no discovery, retries or process inventory."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import tomllib

BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parents[2]
NODE = "tests/test_codex_wake.py::test_exclusive_trial_binding_and_spend_survive_restart_and_later_delivery[True]"
interrupted = False


def stop(_number, _frame):
    global interrupted
    interrupted = True
    raise InterruptedError("Hosted cancellation received")


def deadline(_number, _frame):
    raise TimeoutError("Diagnostic phase budget exhausted")


def digest(path):
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def write(path, value):
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2)


def preflight(output):
    manifest = json.loads((BUNDLE / "manifest.json").read_text(encoding="utf-8"))
    if digest(BUNDLE / "manifest.json") != os.environ["EXPECTED_MANIFEST_SHA256"]:
        raise ValueError("Manifest correspondence failed")
    profile = manifest["profile"]
    if (manifest["execution_status"] != "AUTHORIZED_API_ONLY" or profile["node"] != NODE
            or sys.version_info[:3] != (3, 13, 16) or sys.platform != "linux"
            or os.environ.get("ImageVersion") != "20261012.334.1"):
        raise ValueError("Fixed hosted runtime/profile mismatch")
    for name, expected in manifest["source_lf_sha256"].items():
        if digest(ROOT / name) != expected:
            raise ValueError("Source correspondence failed: " + name)
    for name, expected in manifest["bundle_lf_sha256"].items():
        if digest(BUNDLE / name) != expected:
            raise ValueError("Bundle correspondence failed: " + name)
    versions = {}
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    if project["version"] != "0.1.0":
        raise ValueError("Checkout project version mismatch")
    for pin in profile["dependencies"]:
        name, expected = pin.split("==")
        actual = project["version"] if name == "pallium" else importlib.metadata.version(name)
        if actual != expected:
            raise ValueError("Dependency correspondence failed: " + name)
        versions[name] = actual
    write(output / "preflight.json", {"node": NODE, "github_sha": os.environ.get("GITHUB_SHA"),
                                     "source_pin": manifest["source_pin"], "versions": versions,
                                     "image_version": profile["image_version"],
                                     "limits": "Application pins, not an OS/build-tool freeze"})


def drain(child, receipt):
    # Only the returned owned handle; no descendants are enumerated or certified.
    started = time.monotonic()
    for number in (signal.SIGINT, signal.SIGTERM):
        signal.signal(number, signal.SIG_IGN)
    try:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=7.5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=max(0, 15 - (time.monotonic() - started)))
        receipt["owned_root_exited"] = child.returncode is not None
        receipt["returncode"] = child.returncode
    except BaseException as error:
        receipt["cleanup_error"] = type(error).__name__
        receipt["owned_root_exited"] = False
    receipt["owned_drain_seconds"] = time.monotonic() - started


def main():
    output = Path(os.environ["RUNNER_TEMP"]) / "initial-send-proof"
    output.mkdir(exist_ok=False)
    receipt = {"node": NODE, "owned_root_exited": None, "spawn_attempted": False,
               "scope": "One exact case, no retry; no universal descendant clearance",
               "limits": "Signals, OS scheduling and hosted cancellation prevent exact resource-stop guarantees"}
    child = None
    exit_code = 2
    for number in (signal.SIGINT, signal.SIGTERM):
        signal.signal(number, stop)
    signal.signal(signal.SIGALRM, deadline)
    try:
        signal.alarm(10)
        preflight(output)
        scratch = Path(tempfile.mkdtemp(prefix="initial-send-", dir=os.environ["RUNNER_TEMP"]))
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("PALLIUM_", "CODEX_", "CLAUDE_"))
               and key not in {"PYTHONPATH", "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"}}
        env.update(HOME=str(scratch), XDG_CONFIG_HOME=str(scratch / "config"),
                   TMPDIR=str(scratch), TEMP=str(scratch), TMP=str(scratch),
                   PYTHONPATH=os.pathsep.join((str(BUNDLE), str(ROOT))),
                   INITIAL_SEND_OUTPUT=str(output))
        command = [sys.executable, "-B", "-X", "utf8", "-m", "pytest", NODE,
                   "-q", "-n", "0", "-p", "boundary_observer",
                   "--junitxml=" + str(output / "case.xml")]
        with (output / "pytest.log").open("xb") as log:
            # Check HOLD again after preflight, immediately before the one spawn.
            if interrupted:
                raise InterruptedError("Cancellation before child admission")
            signal.alarm(90)
            test_deadline = time.monotonic() + 90
            receipt["spawn_attempted"] = True
            child = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log,
                                     stderr=subprocess.STDOUT)
            receipt["owned_pid"] = child.pid
            try:
                exit_code = child.wait(timeout=max(0, test_deadline - time.monotonic()))
                receipt["test_outcome"] = "passed" if exit_code == 0 else "failed"
            except subprocess.TimeoutExpired:
                receipt["test_outcome"] = "capped"
                exit_code = 124
            finally:
                signal.alarm(0)
                drain(child, receipt)
    except InterruptedError:
        receipt["test_outcome"] = "cancelled"
        exit_code = 130
    except TimeoutError:
        receipt["test_outcome"] = "capped"
        exit_code = 124
    except BaseException as error:
        receipt["controller_error"] = type(error).__name__
        exit_code = 2
    finally:
        signal.alarm(0)
        if child is not None and receipt["owned_root_exited"] is None:
            drain(child, receipt)
        if child is None and receipt["spawn_attempted"]:
            receipt["ownership"] = "unknown: admission interrupted before handle returned"
        signal.alarm(15)
        try:
            if exit_code == 0 and (receipt["owned_root_exited"] is not True or "cleanup_error" in receipt):
                exit_code = 2
            if exit_code == 0:
                observation = json.loads((output / "api" / "receipt.json").read_text(encoding="utf-8"))
                valid = (observation["calls"] == 1 and observation["profile_restored"]
                         and observation["listeners_restored"] and not observation["overflow"]
                         and not observation["unmatched"] and not observation["errors"]
                         and "session_connection" in observation["labels_seen"])
                receipt["capture_integrity"] = bool(valid)
                receipt["diagnosis"] = "INCONCLUSIVE: original delay did not reproduce"
                if not valid:
                    exit_code = 2
            receipt["exit_code"] = exit_code
            write(output / "terminal.json", receipt)
        finally:
            signal.alarm(0)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
