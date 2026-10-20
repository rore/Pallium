"""Disposable hosted Linux controller: fixed inputs, owned descendants, bounded evidence."""
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import selectors
import shlex
import signal
import stat
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
request = Path(sys.argv[1])
assert os.geteuid() == 0
owner = int(os.environ["SUDO_UID"])
assert owner > 0
info = request.lstat()
assert stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600 and info.st_uid == owner
parent = request.parent.lstat()
assert stat.S_ISDIR(parent.st_mode) and stat.S_IMODE(parent.st_mode) == 0o700 and parent.st_uid == owner
payload = json.loads(request.read_text())
assert payload["uid"] == owner
for key, name in (("helper", "restore-context.py"), ("runner", "qualification.py"), ("preflight", "native-preflight.py")):
    assert Path(payload[key]) == HERE / name
manifest = json.loads((HERE / "manifest.json").read_text())
for name, wanted in manifest["sha256"].items():
    path = HERE / name
    assert not path.is_symlink() and path.is_file()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == wanted
assert hashlib.sha256(Path(payload["python"]).read_bytes()).hexdigest() == "329d378575992732511d75b3bd675cb91b3c65f3082783cd97ccb14f0ecd5a74"
OUT = Path(payload["output"])
NATIVE = OUT / "native"
assert OUT.is_dir() and NATIVE.is_dir() and OUT.stat().st_uid == owner
assert not OUT.is_symlink() and not NATIVE.is_symlink()
os.environ["PALLIUM_DIAGNOSTIC_OUTPUT"] = str(OUT)
spec = importlib.util.spec_from_file_location("qualification", HERE / "qualification.py")
qualification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qualification)
processes = qualification.processes
libc = ctypes.CDLL(None, use_errno=True)
libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
libc.prctl.restype = ctypes.c_int
assert libc.prctl(36, 1, 0, 0, 0) == 0, "Cannot own orphan descendants"
LIMIT = 8 * 1024 * 1024
DEADLINE = time.monotonic() + 1020 - (time.time() - float(payload["environment"]["JOB_STARTED"]))
ledger, handles, children = {}, {}, {}
result = dict(preflight_exit=None, tracer_exit=None, errors=[], cleanup_signals=[], output_bytes=0,
              loss_checks={}, product="07697ac2b8f74e8503534a6586fb13dbb30bdeb4")


def sample():
    current = processes()
    for identity, handle in list(handles.items()):
        value = current.get(identity[0])
        if value is None or value["start"] != identity[1]:
            os.close(handle)
            del handles[identity]
    selected = {pid for pid, value in current.items() if value["ppid"] == os.getpid()}
    selected.update(pid for pid, value in current.items() if (pid, value["start"]) in ledger)
    while True:
        found = {pid for pid, value in current.items() if value["ppid"] in selected}
        if found <= selected:
            break
        selected.update(found)
    for pid in selected:
        value = current[pid]
        identity = (pid, value["start"])
        if identity in handles:
            continue
        try:
            handle = os.pidfd_open(pid)
        except ProcessLookupError:
            continue
        again = processes().get(pid)
        if again is None or again["start"] != identity[1]:
            os.close(handle)
            continue
        ledger[identity], handles[identity] = value, handle
    return current


def reap():
    for child in children.values():
        child.poll()
    while True:
        try:
            pid, status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            break
        if not pid:
            break
        if pid in children:
            children[pid].returncode = os.waitstatus_to_exitcode(status)


def live(current):
    return [identity for identity in handles if identity[0] in current
            and current[identity[0]]["start"] == identity[1] and current[identity[0]]["state"] != "Z"]


def drain():
    for sig in (signal.SIGTERM, signal.SIGKILL):
        end = time.monotonic() + 4
        while True:
            pending = live(sample())
            if not pending:
                break
            for identity in pending:
                try:
                    signal.pidfd_send_signal(handles[identity], sig)
                    result["cleanup_signals"].append(dict(pid=identity[0], start=identity[1], signal=int(sig)))
                except ProcessLookupError:
                    pass
            reap()
            if time.monotonic() >= end:
                break
            time.sleep(0.1)
    reap()
    remaining = live(sample())
    result["remaining"] = [dict(pid=p, start=s) for p, s in remaining]
    result["drained"] = not remaining


def run(command, label, environment=None):
    selector = selectors.DefaultSelector()
    child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             env=environment, start_new_session=True)
    children[child.pid] = child
    files = []
    try:
        for stream, suffix in ((child.stdout, "out"), (child.stderr, "err")):
            destination = (NATIVE / (label + "." + suffix)).open("xb")
            files.append(destination)
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, destination)
        while selector.get_map() or child.poll() is None:
            sample()
            assert time.monotonic() < DEADLINE, "Native controller deadline"
            for key, _ in selector.select(0.1):
                data = os.read(key.fileobj.fileno(), 65536)
                if not data:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    continue
                remaining = LIMIT - result["output_bytes"]
                key.data.write(data[:remaining])
                result["output_bytes"] += min(len(data), remaining)
                assert len(data) <= remaining, "Native output hard cap"
        return child.wait(timeout=1)
    finally:
        selector.close()
        for stream in (child.stdout, child.stderr):
            stream.close()
        for destination in files:
            destination.close()


def validate_native():
    stdout = (NATIVE / "tracer.out").read_text()
    stderr = (NATIVE / "tracer.err").read_text()
    assert not re.search(r"lost|dropped|error|failed|denied", stderr, re.I), "Tracer loss/error"
    for name in ("map_failure", "nesting", "missing_entry", "unfinished_exit", "output_cap"):
        found = [int(x) for x in re.findall(r"@" + name + r":\s*(\d+)", stdout)]
        result["loss_checks"][name] = sum(found)
        assert not any(found), name
    assert not re.search(r"@(start|active)\[[^\n]*:\s*[1-9]", stdout), "Unreturned native span"
    entries = {int(k): int(v) for k, v in re.findall(r"@entry\[(\d+)\]:\s*(\d+)", stdout)}
    returns = {int(k): int(v) for k, v in re.findall(r"@returned\[(\d+)\]:\s*(\d+)", stdout)}
    assert entries == returns and all(entries.get(k, 0) > 0 for k in range(1, 7)), "Missing/unbalanced native coverage"
    result["native_entries"], result["native_returns"] = entries, returns
    spans = []
    for line in stdout.splitlines():
        if line.startswith(("N,", "S,")):
            fields = line.split(",")
            assert len(fields) == 6
            values = list(map(int, fields[1:]))
            if fields[0] == "N":
                pid, tid, probe, start, end = values
            else:
                pid, tid, start, end, probe = values
            assert end >= start and pid > 0 and tid > 0
            spans.append(dict(kind=fields[0], pid=pid, tid=tid, probe_or_raw_state=probe, start=start, end=end))
    correlations = []
    for worker in ("gw0", "gw1", "gw2", "gw3"):
        report = json.loads((OUT / ("worker-" + worker + ".json")).read_text())
        assert report["performance_clock"] == "clock_gettime(CLOCK_MONOTONIC)"
        acquisitions = report["slow"] + ([report["control"]] if report["control"] else [])
        for acquisition in acquisitions:
            for event in acquisition["events"]:
                if event["name"] not in ("driver_return", "driver_error"):
                    continue
                before, after = event["before"][0], event["after"][0]
                matches = [span for span in spans if span["pid"] == acquisition["pid"]
                           and span["tid"] == acquisition["native_tid"] and span["start"] < after and span["end"] > before]
                correlations.append(dict(worker=worker, pid=acquisition["pid"], tid=acquisition["native_tid"],
                                         provider=acquisition["provider_lifetime"], acquisition=acquisition["acquisition"],
                                         sql_kind=event["sql_kind"], wall_ns=after-before,
                                         cpu_ns=event["after"][1]-event["before"][1], native=matches))
    (NATIVE / "correlations.json").write_text(json.dumps(dict(records=correlations,
        limitation="Overlapping native/scheduler intervals establish location, not disk or GIL causation. Fast native spans below 1ms are intentionally absent."), indent=2))


def interrupted(sig, frame):
    raise RuntimeError("Controller interrupted")


signal.signal(signal.SIGTERM, interrupted)
signal.signal(signal.SIGINT, interrupted)
try:
    assert DEADLINE - time.monotonic() > 60, "Insufficient job budget"
    helper = [payload["python"], "-I", "-S", payload["helper"], str(request)]
    result["preflight_exit"] = run(helper + ["preflight"], "preflight")
    drain()
    assert result["preflight_exit"] == 0 and result["drained"], "Preflight failed; no pytest"
    program = str(Path(payload["preflight_output"]) / "native.bt")
    environment = dict(os.environ, BPFTRACE_MAX_MAP_KEYS="4096", BPFTRACE_PERF_RB_PAGES="64")
    result["attach_exit"] = run(["/usr/bin/timeout", "--signal=INT", "--kill-after=2s", "10s",
                               "/usr/bin/bpftrace", "-B", "line", "-c", "/usr/bin/true", program],
                              "attach", environment)
    drain()
    attach_error = (NATIVE / "attach.err").read_text()
    assert result["attach_exit"] == 0 and result["drained"], "Native attach failed; no pytest"
    assert not re.search(r"lost|dropped|error|failed|denied", attach_error, re.I), "Native attach loss/error"
    (NATIVE / "preflight-result.json").write_text(json.dumps(dict(attachments=True, application_executed=False)))
    command = ["/usr/bin/bpftrace", "-B", "line", "-c", shlex.join(helper + ["runner"]),
               str(Path(payload["preflight_output"]) / "native.bt")]
    environment = dict(os.environ, BPFTRACE_MAX_MAP_KEYS="4096", BPFTRACE_PERF_RB_PAGES="64")
    result["tracer_exit"] = run(command, "tracer", environment)
    drain()
    assert result["tracer_exit"] == 0 and result["drained"], "Tracer/cleanup failed"
    context = json.loads((NATIVE / "launcher-context.json").read_text())
    for key in ("uid", "gid", "umask", "cwd"):
        assert context[key] == payload[key], "Child context differs: " + key
    assert context["groups"] == sorted(payload["groups"])
    expected_env = hashlib.sha256(json.dumps(payload["environment"], sort_keys=True).encode()).hexdigest()
    assert context["environment_sha256"] == expected_env
    validate_native()
    result["qualification"] = json.loads((OUT / "result.json").read_text())
except BaseException as error:
    result["errors"].append(type(error).__name__ + ":" + str(error))
finally:
    try:
        drain()
    except BaseException as error:
        result["errors"].append("cleanup:" + type(error).__name__)
        result["drained"] = False
    result["sampled_processes"] = list(ledger.values())
    result["runtime_preflight_required"] = True
    (NATIVE / "controller-result.json").write_text(json.dumps(result, indent=2))
    for path in NATIVE.iterdir():
        if path.is_file() and not path.is_symlink():
            os.chown(path, owner, payload["gid"])
            os.chmod(path, 0o600)
    for handle in handles.values():
        os.close(handle)
    if result["drained"]:
        assert libc.prctl(36, 0, 0, 0, 0) == 0
qualification_result = result.get("qualification", {})
sys.exit(0 if not result["errors"] and qualification_result.get("pytest_exit") == 0
         and qualification_result.get("adequate_fixture_observation") else 1)
