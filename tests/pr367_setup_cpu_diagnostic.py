"""Temporary, fixed-node PR367 phase attribution; never a release qualification."""
import cProfile
import gc
import json
from pathlib import Path
import sys
import threading
import time

import pytest


class PhaseSample:
    def __init__(self):
        self.profile = cProfile.Profile(timer=time.thread_time)
        self.wall = self.cpu = None
        self.collections = []
        self.gc_start = None

    def start(self):
        assert sys.getprofile() is None, "An existing profiler must not be replaced"
        self.wall = time.perf_counter_ns()
        self.cpu = time.thread_time_ns()
        self.profile.enable()

    def stop(self):
        self.profile.disable()
        self.wall = time.perf_counter_ns() - self.wall
        self.cpu = time.thread_time_ns() - self.cpu

    def gc_event(self, phase, info):
        if phase == "start":
            self.gc_start = (time.perf_counter_ns(), time.thread_time_ns())
        elif self.gc_start is not None:
            wall, cpu = self.gc_start
            if len(self.collections) < 8:
                self.collections.append({"generation": info["generation"],
                    "wall_ns": time.perf_counter_ns() - wall,
                    "thread_cpu_ns": time.thread_time_ns() - cpu})
            self.gc_start = None

    def result(self):
        rows, driver = [], []
        for entry in self.profile.getstats():
            code = entry.code
            row = {"function": getattr(code, "co_name", str(code))[:160],
                   "file": Path(code.co_filename).name if hasattr(code, "co_filename") else None,
                   "calls": entry.callcount, "self_cpu_s": entry.inlinetime,
                   "total_cpu_s": entry.totaltime}
            rows.append(row)
            if isinstance(code, str) and "sqlite3.Cursor" in code and "'execute'" in code:
                driver.append(row)
        return {"wall_ns": self.wall, "thread_cpu_ns": self.cpu,
                "sqlite_cursor_execute": driver, "gc": self.collections,
                "top_self_cpu": sorted(rows, key=lambda row: row["self_cpu_s"], reverse=True)[:16]}


@pytest.fixture(autouse=True)
def pr367_setup_cpu(client, monkeypatch, request):
    assert request.node.nodeid == (
        "tests/test_hermes_relay_plugin.py::test_hermes_pending_read_and_reply_lifecycle")
    from storage import sqlite_queue

    active_reply = threading.Event()
    local = threading.local()
    samples, errors = [], []
    prepared = [PhaseSample() for _ in range(4)]  # Allocate observer state before the subject.
    reply_calls = 0
    native_clock, native_post = sqlite_queue._acquisition_monotonic_ns, client.post

    def gc_event(phase, info):
        sample = getattr(local, "sample", None)
        if sample is not None:
            sample.gc_event(phase, info)

    def phase_clock():
        stamp = native_clock()  # Keep the original native clock value and call count.
        caller = sys._getframe(1)
        relevant = (active_reply.is_set() and caller.f_code.co_name == "acquire_phase"
                    and caller.f_locals.get("name") == "setup_pragma")
        ending = "started_ns" in caller.f_locals
        del caller
        if relevant:
            try:
                if not ending and len(samples) < 4:
                    sample = prepared[len(samples)]
                    sample.start()
                    local.sample = sample
                    samples.append(sample)
                elif ending and getattr(local, "sample", None) is not None:
                    local.sample.stop()
                    local.sample = None
            except Exception as error:
                errors.append(type(error).__name__)
        return stamp

    def post(url, *args, **kwargs):
        nonlocal reply_calls
        if url != "/relay/replies":
            return native_post(url, *args, **kwargs)
        reply_calls += 1
        assert reply_calls == 1, "The diagnostic must never replay the subject reply"
        active_reply.set()
        try:
            return native_post(url, *args, **kwargs)
        finally:
            active_reply.clear()

    monkeypatch.setattr(sqlite_queue, "_acquisition_monotonic_ns", phase_clock)
    monkeypatch.setattr(client, "post", post)
    gc.callbacks.append(gc_event)
    try:
        yield
    finally:
        gc.callbacks.remove(gc_event)
        output = Path("test-results")
        output.mkdir(exist_ok=True)
        (output / "pr367-phase-cpu.json").write_text(json.dumps({
            "subject_reply_calls": reply_calls, "samples": [sample.result() for sample in samples],
            "observer_errors": errors,
            "limits": "Intrusive profiler overhead is included; GC and driver intervals may overlap. "
                      "Only the fixed reply setup phase is observed; no suite-history reproduction is implied."
        }, indent=2), encoding="utf-8")
