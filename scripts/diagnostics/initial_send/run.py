"""Fixed two-node capture, adapted from initial_send/run.py; no retries or discovery."""
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parents[2]
NODES = (
    "tests/test_agent_relay_hooks.py::test_codex_exact_wake_real_http_response_delay_is_bounded_and_traceable[1.15-False-delivered-True-False]",
    "tests/test_health.py::test_production_codex_shutdown_settles_pretracking_and_worker_tail[worker_start_failed]",
)
SETUP, SUBJECT, ROOT_DRAIN, STREAM_DRAIN, RECEIPTS = 30, 120, 10, 10, 10
assert SETUP + SUBJECT + ROOT_DRAIN + STREAM_DRAIN + RECEIPTS == 180
LIMIT = 1024 * 1024
interrupted = False
child = None
streams = None
logs = {}
process_receipt = None


def stop(_number, _frame):
    global interrupted
    interrupted = True
    raise InterruptedError("Hosted cancellation received")


def deadline(_number, _frame):
    raise TimeoutError("Cumulative diagnostic allowance exhausted")


def arm(until):
    remaining = until - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("No phase allowance remains")
    signal.setitimer(signal.ITIMER_REAL, remaining)


def digest(path):
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def write(path, value):
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2)


def pump(until):
    while streams.get_map():
        remaining = until - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Combined stream allowance exhausted")
        ready = streams.select(min(.05, remaining))
        for key, _ in ready:
            data = os.read(key.fileobj.fileno(), 8192)
            if not data:
                streams.unregister(key.fileobj)
                key.fileobj.close()
                continue
            name = key.data
            process_receipt[name + "_bytes"] += len(data)
            if process_receipt[name + "_bytes"] > LIMIT:
                process_receipt["output_overflow"] = True
                raise ValueError("Owned output exceeded one MiB per stream")
            logs[name].write(data)
        if ready:
            return


def close_streams(until):
    global streams
    resources, errors = [], []
    if streams is not None:
        try:
            resources.extend(key.fileobj for key in list(streams.get_map().values()))
        except BaseException as error:
            errors.append(type(error).__name__)
        resources.append(streams)
        streams = None
    resources.extend(logs.values())
    logs.clear()
    for resource in resources:
        try:
            arm(until)
            resource.close()
        except BaseException as error:
            errors.append(type(error).__name__)
    if errors and process_receipt is not None:
        process_receipt["stream_close_errors"] = errors[:8]


def own(command, until, label, output, env, receipt):
    """Every successful command must settle inside its original work allowance."""
    global child, streams, process_receipt
    arm(until)  # Deadline protection includes Popen admission.
    process_receipt = {"label": label, "spawn_attempted": False,
                       "owned_root_exited": False, "streams_complete": False,
                       "stdout_bytes": 0, "stderr_bytes": 0,
                       "output_overflow": False}
    receipt["processes"].append(process_receipt)
    for name in ("stdout", "stderr"):
        logs[name] = (output / (label + "." + name + ".log")).open("xb")
    streams = selectors.DefaultSelector()
    if interrupted:
        raise InterruptedError("Cancellation before child admission")
    process_receipt["spawn_attempted"] = True
    child = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, bufsize=0)
    process_receipt["owned_pid"] = child.pid
    for name, pipe in (("stdout", child.stdout), ("stderr", child.stderr)):
        os.set_blocking(pipe.fileno(), False)
        streams.register(pipe, selectors.EVENT_READ, name)
    while child.poll() is None or streams.get_map():
        if time.monotonic() >= until:
            raise TimeoutError("Owned command exceeded its work allowance")
        pump(until)
        if not streams.get_map() and child.poll() is None:
            time.sleep(min(.01, max(0, until - time.monotonic())))
    if time.monotonic() >= until:
        raise TimeoutError("Owned command returned after its work allowance")
    process_receipt.update(owned_root_exited=True, returncode=child.returncode,
                           streams_complete=True)
    returncode = child.returncode
    close_streams(until)
    child = None
    if interrupted:
        raise InterruptedError("Cancellation during owned stream closure")
    if time.monotonic() >= until:
        raise TimeoutError("Owned stream closure exceeded its original allowance")
    if process_receipt.get("stream_close_errors"):
        raise RuntimeError("Owned stream closure was incomplete")
    if returncode:
        raise RuntimeError(label + " exited unsuccessfully")


def drain(anchor, receipt):
    """One final root allowance followed by one combined stream allowance."""
    global child
    for number in (signal.SIGINT, signal.SIGTERM):
        signal.signal(number, signal.SIG_IGN)
    if process_receipt is None:
        return
    try:
        root_until = min(anchor + 160, time.monotonic() + ROOT_DRAIN)
        arm(root_until)
        if child is None and process_receipt["spawn_attempted"] and "owned_pid" not in process_receipt:
            process_receipt["ownership"] = "unknown: admission interrupted before handle returned"
        if child is not None:
            if child.poll() is None:
                process_receipt["terminate_requested"] = True
                child.terminate()
                try:
                    child.wait(timeout=max(0, min(5, root_until - time.monotonic())))
                except subprocess.TimeoutExpired:
                    process_receipt["kill_requested"] = True
                    child.kill()
                    child.wait(timeout=max(0, root_until - time.monotonic()))
            process_receipt.update(owned_root_exited=child.returncode is not None,
                                   returncode=child.returncode)
    except BaseException as error:
        process_receipt["cleanup_error"] = type(error).__name__
    try:
        stream_until = min(anchor + 170, time.monotonic() + STREAM_DRAIN)
        arm(stream_until)
        if streams is not None:
            while streams.get_map():
                pump(stream_until)
            process_receipt["streams_complete"] = True
    except BaseException as error:
        process_receipt["stream_error"] = type(error).__name__
    finally:
        close_streams(stream_until)
    receipt["cleanup_scope"] = "Returned owned roots and their streams only; no descendant census or clearance"


def identity(manifest):
    if sys.platform != "linux" or sys.version_info[:3] != (3, 12, 15) or sys.flags.optimize != 0:
        raise ValueError("Python/platform correspondence failed")
    release = dict(line.split("=", 1) for line in Path("/etc/os-release").read_text().splitlines()
                   if "=" in line)
    if release.get("ID", "").strip('"') != "ubuntu" or release.get("VERSION_ID", "").strip('"') != "24.04":
        raise ValueError("Ubuntu family correspondence failed")
    if os.environ.get("ImageVersion") != "20261012.334.1":
        raise ValueError("Historical hosted image unavailable or mismatched")
    for name, expected in manifest["source_lf_sha256"].items():
        if digest(ROOT / name) != expected:
            raise ValueError("Source correspondence failed: " + name)
    for name, expected in manifest["bundle_lf_sha256"].items():
        if digest(BUNDLE / name) != expected:
            raise ValueError("Bundle correspondence failed: " + name)


def main():
    global child
    anchor = float(os.environ["CAPTURE_STARTED_MONOTONIC"])
    if not math.isfinite(anchor) or not 0 <= anchor <= time.monotonic():
        raise ValueError("Invalid first-step monotonic anchor")
    output = Path(os.environ["RUNNER_TEMP"]) / "relay-two-node-proof"
    output.mkdir(exist_ok=False)
    receipt = {"nodes": NODES, "processes": [], "subject_attempted": False,
               "test_outcome": "not_admitted", "exit_code": 2,
               "limits": "Fresh hosted version correspondence only; not original physical runner, wheels, build tools, preinstalled state, ordering or full-suite load. Pre-anchor bootstrap and artifact upload are outside this managed clock; platform cancellation can interrupt receipts."}
    for number in (signal.SIGINT, signal.SIGTERM):
        signal.signal(number, stop)
    signal.signal(signal.SIGALRM, deadline)
    exit_code = 2
    try:
        arm(anchor + SETUP)
        manifest = json.loads((BUNDLE / "manifest.json").read_text())
        if digest(BUNDLE / "manifest.json") != os.environ["EXPECTED_MANIFEST_SHA256"]:
            raise ValueError("Manifest correspondence failed")
        if manifest["execution_status"] != "AUTHORIZED_TWO_NODE":
            receipt["test_outcome"] = "not_admitted_review_only"
            raise ValueError("Inert source package has no execution authorization")
        if tuple(manifest["nodes"]) != NODES:
            raise ValueError("Literal selector correspondence failed")
        identity(manifest)
        scratch = Path(tempfile.mkdtemp(prefix="relay-two-node-", dir=os.environ["RUNNER_TEMP"]))
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("PALLIUM_", "CODEX_", "CLAUDE_", "HERMES_", "OPENCODE_",
                                      "OPENAI_", "ANTHROPIC_", "AZURE_", "AWS_", "GOOGLE_", "HF_", "PYTHON", "PYTEST", "UV_", "CONDA"))
               and not key.endswith(("_TOKEN", "_SECRET", "_PASSWORD", "_API_KEY"))
               and key not in {"PYTHONPATH", "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
                               "PYTEST_ADDOPTS", "PYTEST_PLUGINS", "VIRTUAL_ENV"}}
        env.update(HOME=str(scratch / "home"), XDG_CONFIG_HOME=str(scratch / "config"),
                   XDG_STATE_HOME=str(scratch / "state"), XDG_DATA_HOME=str(scratch / "data"),
                   XDG_CACHE_HOME=str(scratch / "cache"), TMPDIR=str(scratch / "temp"),
                   TEMP=str(scratch / "temp"), TMP=str(scratch / "temp"),
                   PYTHONPYCACHEPREFIX=str(scratch / "pycache"), PYTHONDONTWRITEBYTECODE="1", PYTHONOPTIMIZE="0",
                   PALLIUM_HOME=str(scratch / "pallium"), HERMES_HOME=str(scratch / "hermes"))
        for name in ("home", "config", "state", "data", "cache", "temp", "pycache", "pallium", "hermes"):
            (scratch / name).mkdir()
        own(["git", "diff", "--name-only", manifest["source_pin"], "HEAD"], anchor + SETUP,
            "source-diff", output, env, receipt)
        changed = (output / "source-diff.stdout.log").read_text().splitlines()
        if not set(changed) <= set(manifest["allowed_publication_paths"]):
            raise ValueError("Publication contains an unexpected changed path")
        own(["git", "status", "--porcelain", "--untracked-files=all"], anchor + SETUP,
            "source-status", output, env, receipt)
        if (output / "source-status.stdout.log").read_text().strip():
            raise ValueError("Checkout is not clean")
        tools = {name: importlib.metadata.version(name) for name in ("pip", "setuptools", "wheel")}
        if int(tools["setuptools"].split(".", 1)[0]) < 68:
            raise ValueError("Existing build prerequisites are insufficient; no fallback allowed")
        receipt["unmatched_existing_build_versions"] = tools
        own([sys.executable, "-m", "pip", "install", "--no-input", "--disable-pip-version-check",
             "--no-cache-dir", "--only-binary=:all:", "--no-deps", "-r", str(BUNDLE / "requirements.txt")],
            anchor + SETUP, "install-pins", output, env, receipt)
        own([sys.executable, "-m", "pip", "install", "--no-input", "--disable-pip-version-check",
             "--no-cache-dir", "--no-deps", "--no-build-isolation", "-e", "."],
            anchor + SETUP, "install-source", output, env, receipt)
        versions = {name: importlib.metadata.version(name) for name in manifest["versions"]}
        if versions != manifest["versions"]:
            raise ValueError("Installed distribution version correspondence failed")
        write(output / "preflight.json", {"versions": versions, "source_pin": manifest["source_pin"],
              "github_sha": os.environ.get("GITHUB_SHA"), "image": os.environ.get("ImageVersion"),
              "build_versions_unmatched": tools, "setup_elapsed": time.monotonic() - anchor})
        if interrupted or time.monotonic() >= anchor + SETUP:
            raise TimeoutError("Setup did not finish inside its original 30s allowance")
        receipt["subject_attempted"] = True
        subject_until = min(anchor + SETUP + SUBJECT, time.monotonic() + SUBJECT)
        command = [sys.executable, "-B", "-X", "utf8", "-m", "pytest", *NODES,
                   "-q", "-n", "0", "--durations=20", "--junitxml=" + str(output / "cases.xml"),
                   "--basetemp=" + str(scratch / "pytest"), "-o", "cache_dir=" + str(scratch / "pytest-cache")]
        try:
            own(command, subject_until, "pytest", output, env, receipt)
            receipt["test_outcome"] = "passed_nonreproduction"
        except RuntimeError:
            receipt["test_outcome"] = "failed_requires_review"
        tree = ET.parse(output / "cases.xml")
        cases = []
        for case in tree.iter("testcase"):
            identifier = case.get("classname", "").replace(".", "/") + ".py::" + case.get("name", "")
            state = next((tag for tag in ("failure", "error", "skipped") if case.find(tag) is not None), "passed")
            cases.append({"id": identifier, "state": state})
        receipt["cases"] = cases
        if len(cases) != 2 or {case["id"] for case in cases} != set(NODES):
            raise ValueError("Missing, duplicate or unexpected JUnit cases")
        receipt["case_inventory_valid"] = True
        receipt["diagnosis"] = "INCONCLUSIVE STOP: original failure identity and observations require separate result review; no retry or repair claim"
        exit_code = 1 if any(case["state"] != "passed" for case in cases) else 2
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
        signal.setitimer(signal.ITIMER_REAL, 0)
        try:
            drain(anchor, receipt)
        except BaseException as error:
            receipt["cleanup_error"] = type(error).__name__
        try:
            arm(min(anchor + 180, time.monotonic() + RECEIPTS))
            receipt["elapsed_seconds"] = time.monotonic() - anchor
            receipt["complete_owned_capture"] = all(
                row["owned_root_exited"] and row["streams_complete"] and not row["output_overflow"]
                and "cleanup_error" not in row and "stream_error" not in row
                and not row.get("stream_close_errors")
                for row in receipt["processes"]) and "cleanup_error" not in receipt
            if not receipt["complete_owned_capture"] or time.monotonic() >= anchor + 180:
                exit_code = 2
                receipt["capture_integrity"] = False
            receipt["exit_code"] = exit_code
            write(output / "terminal.json", receipt)
            print(json.dumps(receipt), flush=True)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
