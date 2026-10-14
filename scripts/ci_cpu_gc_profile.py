"""Temporary, explicit CI-only sampling companion; never imported by production."""
import argparse
from contextlib import contextmanager
import gc
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

import pytest

RAW_LIMIT = 256 * 1024 * 1024
METADATA_LIMIT = 8 * 1024 * 1024


def stamp():
    return {"mono_ns": time.monotonic_ns(), "epoch_ns": time.time_ns(),
            "cpu_ns": time.thread_time_ns(), "pid": os.getpid(),
            "tid": threading.get_ident(), "native_tid": threading.get_native_id()}


class Collector:
    def __init__(self, directory, worker):
        self.file = (directory / f"process-{os.getpid()}.jsonl").open("x", encoding="utf-8")
        self.written = self.dropped = self.errors = 0
        self.capped = False
        self.pending, self.active = [], {}
        self.starts, self.stops, self.maximum_ns = [0] * 3, [0] * 3, [0] * 3
        self.emit({"kind": "manifest", "worker": worker,
                   "python": list(sys.version_info[:3]), "gc_enabled": gc.isenabled(),
                   "gc_thresholds": gc.get_threshold(), **stamp()})

    def emit(self, event, *, final=False):
        try:
            line = json.dumps(event, ensure_ascii=True) + "\n"
            if self.written + len(line) > METADATA_LIMIT - (0 if final else 4096):
                self.capped = True
                return
            self.file.write(line)
            self.file.flush()
            self.written += len(line)
        except Exception:
            self.errors += 1

    def collection(self, phase, info):
        try:
            generation = info["generation"]
            if type(generation) is not int or not 0 <= generation <= 2:
                return
            now = stamp()
            if phase == "start":
                self.starts[generation] += 1
                self.active[generation] = now
            elif phase == "stop":
                self.stops[generation] += 1
                start = self.active.pop(generation, None)
                if start is not None:
                    elapsed = now["mono_ns"] - start["mono_ns"]
                    self.maximum_ns[generation] = max(self.maximum_ns[generation], elapsed)
                    if elapsed >= 1_000_000:
                        if len(self.pending) < 128:
                            self.pending.append({"kind": "gc", "generation": generation,
                                                 "start": start, "end": now})
                        else:
                            self.dropped += 1
        except Exception:
            self.errors += 1

    def flush(self):
        events, self.pending = self.pending, []
        for event in events:
            self.emit(event)

    @contextmanager
    def phase(self, item, phase):
        identity = hashlib.sha256(item.nodeid.encode()).hexdigest()[:16]
        self.flush()
        self.emit({"kind": "phase", "item": identity, "phase": phase, "edge": "start", **stamp()})
        try:
            yield
        finally:
            self.flush()
            self.emit({"kind": "phase", "item": identity, "phase": phase, "edge": "end", **stamp()})

    def close(self):
        self.flush()
        self.emit({"kind": "summary", "starts": self.starts, "stops": self.stops,
                   "maximum_ns": self.maximum_ns, "dropped": self.dropped,
                   "errors": self.errors, "capped": self.capped,
                   "unmatched": [a - b for a, b in zip(self.starts, self.stops)], **stamp()}, final=True)
        self.file.close()


def pytest_configure(config):
    directory = Path(os.environ["PALLIUM_CI_PROFILE_DIR"])
    worker = getattr(config, "workerinput", {}).get("workerid", "controller")
    collector = Collector(directory, worker)
    config._ci_cpu_gc_collector = collector
    gc.callbacks.append(collector.collection)


def pytest_unconfigure(config):
    collector = getattr(config, "_ci_cpu_gc_collector", None)
    if collector is not None:
        try:
            gc.callbacks.remove(collector.collection)
        finally:
            collector.close()
            del config._ci_cpu_gc_collector


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_setup(item):
    with item.config._ci_cpu_gc_collector.phase(item, "setup"):
        yield


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    with item.config._ci_cpu_gc_collector.phase(item, "call"):
        yield


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item):
    with item.config._ci_cpu_gc_collector.phase(item, "teardown"):
        yield


def pytest_runtest_makereport(item, call):
    if call.excinfo is not None:
        item.config._ci_cpu_gc_collector.emit({
            "kind": "failure", "item": hashlib.sha256(item.nodeid.encode()).hexdigest()[:16],
            "phase": call.when, **stamp()})


def ci_profile_anchor_one():
    time.sleep(0.075)


def ci_profile_anchor_two():
    time.sleep(0.075)


def child(directory):
    anchors = []
    for function in (ci_profile_anchor_one, ci_profile_anchor_two):
        start = stamp()
        function()
        anchors.append({"name": function.__name__, "start": start, "end": stamp()})
    (directory / "anchors.json").write_text(json.dumps(anchors), encoding="utf-8")
    result = int(pytest.main(["tests/", "-x", "-q", "--durations=20",
                             "--log-format=%(created).9f pid=%(process)d tid=%(thread)d %(levelname)s %(name)s %(message)s",
                             "-p", "scripts.ci_cpu_gc_profile"]))
    (directory / "pytest-exit.json").write_text(json.dumps({"exit_code": result, **stamp()}), encoding="utf-8")
    return result


def sanitize(events):
    output = []
    for event in events:
        filename = event["args"]["filename"]
        name = event["name"]
        if not filename and name.startswith("process "):
            name = "process"
        elif not filename and name.startswith("thread ("):
            name = "thread"
        output.append({key: event[key] for key in ("pid", "tid", "ts", "ph")}
                      | {"name": name, "cat": "py-spy", "args": {"filename": filename, "line": event["args"].get("line")}})
    return output


def finalize(directory, raw, sampler_exit):
    manifest = {"sampler_exit": sampler_exit, "usable": False, "qualification":
                "Observer-inclusive diagnostic; samples are not exact CPU durations. GC below 1ms is counted only.",
                "raw_limit_scope": "post-capture parse/upload bound; not a sampling-time disk or memory cap"}
    status = 2
    try:
        if raw.stat().st_size > RAW_LIMIT:
            raise ValueError("raw artifact cap exceeded")
        events = sanitize(json.loads(raw.read_text(encoding="utf-8")))
        anchors = json.loads((directory / "anchors.json").read_text())
        offsets, timestamps = [], set()
        for anchor in anchors:
            matches = [event for event in events if event["pid"] == anchor["start"]["pid"]
                       and event["name"] == anchor["name"] and event["ph"] == "B"]
            if not matches:
                raise ValueError("clock anchor not sampled")
            sampled = matches[0]["ts"]
            timestamps.add(sampled)
            offsets.append((anchor["start"]["mono_ns"] / 1000 - sampled,
                            anchor["end"]["mono_ns"] / 1000 - sampled))
        lower, upper = max(a for a, _ in offsets), min(b for _, b in offsets)
        manifest["clock_offset_us"] = [lower, upper]
        manifest["clock_uncertainty_us"] = upper - lower
        if len(timestamps) < 2 or not 0 <= upper - lower <= 100_000:
            raise ValueError("clock alignment incomplete")
        workers, summaries, controllers = {}, [], []
        for path in directory.glob("process-*.jsonl"):
            if path.stat().st_size > METADATA_LIMIT:
                raise ValueError("metadata cap exceeded")
            records = [json.loads(line) for line in path.read_text().splitlines()]
            identity = records[0]
            if identity["python"][:2] != [3, 12] or identity["gc_enabled"] is not True:
                raise ValueError("unexpected profiling runtime")
            if identity["worker"] != "controller":
                if identity["worker"] in workers or identity["pid"] in workers.values():
                    raise ValueError("duplicate worker identity")
                workers[identity["worker"]] = identity["pid"]
            else:
                controllers.append(identity["pid"])
            if records[-1]["kind"] != "summary" or records[-1]["errors"] or records[-1]["capped"]:
                raise ValueError("metadata incomplete")
            summaries.append(records[-1])
        if set(workers) != {"gw0", "gw1", "gw2", "gw3"} or len(controllers) != 1:
            raise ValueError("four-worker identity proof missing")
        sampled_pids = {event["pid"] for event in events if event["ph"] == "B"}
        if not set(workers.values()) <= sampled_pids:
            raise ValueError("worker sampling coverage missing")
        manifest["workers"] = workers
        manifest["gc_complete"] = all(not summary["dropped"] and not any(summary["unmatched"])
                                      for summary in summaries)
        manifest["gc_summaries"] = summaries
        proof = json.loads((directory / "pytest-exit.json").read_text())
        manifest["pytest_exit"] = proof["exit_code"]
        manifest["usable"] = sampler_exit == 0
        encoded = json.dumps(events)
        if len(encoded.encode("utf-8")) > RAW_LIMIT:
            raise ValueError("sanitized artifact cap exceeded")
        (directory / "stacks.json").write_text(encoded, encoding="utf-8")
        status = proof["exit_code"] if manifest["usable"] else 2
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        manifest["usable"] = False
        manifest["incomplete"] = True
    finally:
        try:
            raw.unlink(missing_ok=True)
        except OSError:
            manifest["raw_cleanup_failed"] = True
            status = 2
        (directory / "capture.json").write_text(json.dumps(manifest), encoding="utf-8")
    return status


def run(directory):
    if sys.platform != "linux":
        raise RuntimeError("This isolated profile is Linux-only")
    directory.mkdir(parents=True, exist_ok=False)
    version = subprocess.run(["py-spy", "--version"], capture_output=True, text=True, check=True).stdout.strip()
    if version != "py-spy 0.4.2":
        raise RuntimeError("unexpected profiler version")
    (directory / "profiler.json").write_text(json.dumps({"version": version, "rate": 25,
                                                        "sampling_seconds": 900}), encoding="utf-8")
    raw = directory.parent / (directory.name + "-private-raw.json")
    environment = os.environ | {"PALLIUM_CI_PROFILE_DIR": str(directory)}
    command = ["py-spy", "record", "--format", "chrometrace", "--subprocesses", "--threads",
               "--native", "--idle", "--rate", "25", "--duration", "900", "--output", str(raw),
               "--", sys.executable, "-m", "scripts.ci_cpu_gc_profile", "--child", str(directory)]
    process, status, cleanup_ok = None, 2, True
    try:
        process = subprocess.Popen(command, env=environment, start_new_session=True)
        try:
            status = process.wait(timeout=1200)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGINT)
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        status = 2
    finally:
        if process is not None:
            try:
                drain_group(process)
            except (OSError, RuntimeError):
                cleanup_ok, status = False, 2
        result = finalize(directory, raw, status)
        if not cleanup_ok:
            manifest = json.loads((directory / "capture.json").read_text())
            manifest["cleanup_complete"] = False
            (directory / "capture.json").write_text(json.dumps(manifest), encoding="utf-8")
    return result


def drain_group(process):
    for requested in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, requested)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            process.poll()
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.05)
    raise RuntimeError("owned profile process group did not settle")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path)
    parser.add_argument("--child", type=Path)
    arguments = parser.parse_args()
    raise SystemExit(child(arguments.child) if arguments.child else run(arguments.run))
