"""Exactly one disposable Linux full-suite diagnostic; no automatic retry."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import sysconfig
import time

PRODUCT = "07697ac2b8f74e8503534a6586fb13dbb30bdeb4"
COMMAND = [sys.executable, "-m", "pytest", "tests/", "-q", "--durations=20"]
ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
OUT = Path(os.environ["PALLIUM_DIAGNOSTIC_OUTPUT"])


def save(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot():
    paths = {ROOT / name for name in git("ls-files").splitlines()}
    paths.add(Path(sys.executable).resolve())
    for key in ("purelib", "platlib"):
        directory = Path(sysconfig.get_path(key))
        paths.update(p for p in directory.rglob("*") if p.is_file()
                     and (p.suffix in {".py", ".so", ".pyd"} or p.name in {"METADATA", "entry_points.txt"}))
    paths.update(p for p in HERE.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    return {str(path): digest(path) for path in sorted(paths)}


def processes():
    result = {}
    for directory in Path("/proc").iterdir():
        if not directory.name.isdecimal():
            continue
        try:
            raw = (directory / "stat").read_text()
            fields = raw[raw.rfind(")") + 2:].split()
            result[int(directory.name)] = dict(pid=int(directory.name), ppid=int(fields[1]),
                                               group=int(fields[2]), start=fields[19], state=fields[0])
        except (OSError, ValueError, IndexError):
            pass
    return result


def main():
    assert sys.platform == "linux" and sys.version_info[:3] == (3, 13, 16)
    assert os.environ["GITHUB_RUN_ATTEMPT"] == "1"
    assert git("rev-parse", "HEAD") == PRODUCT
    assert not git("diff", "--name-only", PRODUCT)
    assert not os.environ.get("PYTEST_ADDOPTS"), "Unexpected command overrides"
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "execution-intent.json").open("x", encoding="utf-8") as file:
        json.dump(dict(product=PRODUCT, diagnostic=os.environ["DIAGNOSTICS_SHA"],
                       run=os.environ["GITHUB_RUN_ID"], command=COMMAND), file)
    before = snapshot()
    save("inputs.json", dict(hashes=before, product=PRODUCT, diagnostic=os.environ["DIAGNOSTICS_SHA"],
                            python=sys.version, sqlite=__import__("sqlite3").sqlite_version,
                            dependencies=sorted((d.metadata["Name"], d.version) for d in importlib.metadata.distributions())))
    deadline = min(time.monotonic() + 840, time.monotonic() + 1020 - (time.time() - float(os.environ["JOB_STARTED"])))
    assert deadline - time.monotonic() > 60, "Insufficient time for a useful bounded observation"
    environment = dict(os.environ, PYTEST_PLUGINS="acquisition_observer",
                       PYTHONPATH=os.pathsep.join((str(HERE / "guard"), str(HERE), str(ROOT))),
                       PALLIUM_NET_GUARD_REPO_ROOT=str(ROOT),
                       PALLIUM_NET_GUARD_LOG=str(OUT / "guard.log"),
                       PALLIUM_NET_GUARD_DETAIL_LOG=str(OUT / "guard-detail.jsonl"))
    ledger, handles = {}, {}
    process = None
    root_identity = None
    result = dict(pytest_exit=None, timeout=False, collector_error=None, cleanup_signals=[])
    started = time.monotonic()

    def sample():
        current = processes()
        selected = set()
        if root_identity is not None:
            root = current.get(root_identity[0])
            root_matches = root is not None and root["start"] == root_identity[1]
            group_owned = root_matches or any(
                value["group"] == root_identity[0] and (pid, value["start"]) in ledger
                for pid, value in current.items())
            if root_matches:
                selected.add(root_identity[0])
            if group_owned:
                selected.update(pid for pid, value in current.items() if value["group"] == root_identity[0])
        selected.update(pid for pid, value in current.items() if (pid, value["start"]) in ledger)
        changed = True
        while changed:
            found = {pid for pid, value in current.items() if value["ppid"] in selected}
            changed = not found.issubset(selected)
            selected.update(found)
        for pid in selected:
            value = current.get(pid)
            if value is None:
                continue
            identity = (pid, value["start"])
            if identity not in ledger:
                ledger[identity] = value
                try:
                    handle = os.pidfd_open(pid)
                    again = processes().get(pid)
                    if again is None or again["start"] != value["start"]:
                        os.close(handle)
                    else:
                        handles[identity] = handle
                except OSError:
                    pass
        return current

    def live(current):
        return [(identity, value) for identity, value in ledger.items()
                if identity[0] in current and current[identity[0]]["start"] == identity[1]
                and current[identity[0]]["state"] != "Z"]

    try:
        with (OUT / "pytest.log").open("wb") as log:
            process = subprocess.Popen(COMMAND, stdout=log, stderr=subprocess.STDOUT, env=environment, start_new_session=True)
            root_entry = processes().get(process.pid)
            assert root_entry is not None, "Could not establish owned pytest root"
            root_identity = (process.pid, root_entry["start"])
            while True:
                sample()
                exitcode = process.poll()
                if exitcode is not None:
                    result["pytest_exit"] = exitcode
                    break
                if time.monotonic() >= deadline:
                    result["timeout"] = True
                    break
                time.sleep(0.25)
    except BaseException as error:
        result["collector_error"] = type(error).__name__
    finally:
        # Only pidfd-bound identities discovered in our owned group/descendant tree.
        for sig in (signal.SIGTERM, signal.SIGKILL):
            current = sample()
            pending = live(current)
            if not pending:
                break
            for identity, value in pending:
                handle = handles.get(identity)
                if handle is None:
                    result["cleanup_signals"].append(dict(pid=identity[0], signal="unavailable_pidfd"))
                    continue
                try:
                    signal.pidfd_send_signal(handle, sig)
                    result["cleanup_signals"].append(dict(pid=identity[0], start=identity[1], signal=int(sig)))
                except ProcessLookupError:
                    pass
            end = time.monotonic() + 5
            while time.monotonic() < end and live(sample()):
                if process is not None:
                    process.poll()
                time.sleep(0.1)
        current = sample()
        pending = live(current)
        result["drained"] = not pending
        result["remaining"] = [value for identity, value in pending]
        result["sampled_processes"] = list(ledger.values())
        result["sampling_limit"] = "250ms sampling may miss short-lived or escaped descendants; pidfds prevent PID-reuse kills."
        if process is not None:
            try:
                result["final_process_exit"] = process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                result["final_process_exit"] = None
        for handle in handles.values():
            os.close(handle)
        result["elapsed_seconds"] = time.monotonic() - started
        save("process-result.json", result)
        try:
            after = snapshot()
            drift = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
            save("custody.json", dict(unchanged=not drift, changed=drift, after_hashes=after,
                                     head=git("rev-parse", "HEAD"), diagnostic=os.environ["DIAGNOSTICS_SHA"]))
        except BaseException as error:
            drift = ["snapshot_error:" + type(error).__name__]
            save("custody.json", dict(unchanged=False, changed=drift))

    reports = {}
    errors = []
    for worker in ("gw0", "gw1", "gw2", "gw3"):
        path = OUT / ("worker-" + worker + ".json")
        try:
            report = json.loads(path.read_text())
            assert report["worker"] == worker
            reports[worker] = report
            counts = report["counts"]
            if not report["control"] or not counts.get("observed") or report["remaining_active"]:
                errors.append(worker + ":missing_control_or_active")
            if counts.get("incomplete_acquisitions") or counts.get("slow_buffer_overflow"):
                errors.append(worker + ":incomplete_or_overflow")
            if counts.get("bindings_registered") != counts.get("bindings_restored"):
                errors.append(worker + ":restoration_count")
            for reason in counts:
                if reason.startswith("gap:") and reason != "gap:incompatible_or_synthetic_acquisition":
                    errors.append(worker + ":" + reason)
        except (OSError, ValueError, KeyError, AssertionError) as error:
            errors.append(worker + ":invalid_or_missing_report:" + type(error).__name__)
    result["adequate_fixture_observation"] = not errors and not drift and result["drained"] and not result["timeout"] and result["collector_error"] is None
    result["adequacy_errors"] = errors
    result["retained_slow_count"] = sum(len(report["slow"]) for report in reports.values())
    result["interpretation"] = "Diagnostic only; no PR297 qualification. No slow event is inconclusive. Synthetic and unregistered coverage gaps remain even when bounded fixture observation is adequate."
    result["artifact_hashes"] = {p.name: digest(p) for p in OUT.iterdir() if p.is_file()}
    save("result.json", result)
    print(json.dumps({k: result[k] for k in ("pytest_exit", "timeout", "drained", "adequate_fixture_observation", "retained_slow_count", "adequacy_errors")}))
    return 0 if result["pytest_exit"] == 0 and result["adequate_fixture_observation"] else 1


if __name__ == "__main__":
    sys.exit(main())
