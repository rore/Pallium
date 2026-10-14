import json
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

# Keep harness mocks out of the actual plugin when this file is itself profiled.
spec = importlib.util.spec_from_file_location("ci_profile_test_subject", Path(__file__).parents[1] / "scripts/ci_cpu_gc_profile.py")
profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile)


def trace_event(name, pid=1, timestamp=1000, filename="profile.py"):
    return {"name": name, "pid": pid, "tid": pid * 10, "ts": timestamp,
            "ph": "B", "args": {"filename": filename, "line": 1}}


def capture(tmp_path, exit_code=0):
    directory = tmp_path / "artifact"
    directory.mkdir()
    anchors, events = [], []
    for name, start, timestamp in (("ci_profile_anchor_one", 1_000_000_000, 1000),
                                    ("ci_profile_anchor_two", 1_075_000_000, 76000)):
        anchors.append({"name": name, "start": {"pid": 1, "mono_ns": start},
                        "end": {"mono_ns": start + 75_000_000}})
        events.append(trace_event(name, timestamp=timestamp))
    for number, worker in enumerate(("controller", "gw0", "gw1", "gw2", "gw3"), 1):
        records = [{"kind": "manifest", "worker": worker, "pid": number,
                    "python": [3, 12, 0], "gc_enabled": True},
                   {"kind": "summary", "errors": 0, "capped": False, "dropped": 0, "unmatched": [0, 0, 0]}]
        (directory / f"process-{number}.jsonl").write_text("\n".join(map(json.dumps, records)))
        events.append(trace_event("work", pid=number, timestamp=200000))
    (directory / "anchors.json").write_text(json.dumps(anchors))
    (directory / "pytest-exit.json").write_text(json.dumps({"exit_code": exit_code}))
    raw = tmp_path / "private.json"
    raw.write_text(json.dumps(events))
    return directory, raw


@pytest.mark.parametrize("exit_code", [0, 1, 4])
def test_actual_pytest_exit_is_preserved_even_when_sampler_succeeds(tmp_path, exit_code):
    directory, raw = capture(tmp_path, exit_code)
    assert profile.finalize(directory, raw, 0) == exit_code
    manifest = json.loads((directory / "capture.json").read_text())
    assert manifest["usable"] and manifest["gc_complete"]
    assert manifest["clock_uncertainty_us"] == 75000
    assert not raw.exists()


def test_child_records_the_actual_pytest_main_result_without_changing_selection(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(profile, "pytest", SimpleNamespace(main=lambda args: seen.append(args) or 1))
    monkeypatch.setattr(profile, "ci_profile_anchor_one", lambda: None)
    monkeypatch.setattr(profile, "ci_profile_anchor_two", lambda: None)
    assert profile.child(tmp_path) == 1
    assert json.loads((tmp_path / "pytest-exit.json").read_text())["exit_code"] == 1
    assert seen[0][:4] == ["tests/", "-x", "-q", "--durations=20"]
    assert seen[0][-2:] == ["-p", "scripts.ci_cpu_gc_profile"]
    assert not any(argument.startswith("-n") for argument in seen[0])


@pytest.mark.parametrize("damage", ["missing_exit", "missing_anchor", "missing_worker_sample",
                                    "duplicate_worker", "missing_controller", "cap"])
def test_incomplete_capture_cannot_report_success(tmp_path, monkeypatch, damage):
    directory, raw = capture(tmp_path)
    if damage == "missing_exit":
        (directory / "pytest-exit.json").unlink()
    elif damage == "missing_anchor":
        (directory / "anchors.json").write_text("[]")
    elif damage == "missing_worker_sample":
        events = json.loads(raw.read_text())
        raw.write_text(json.dumps([event for event in events if event["pid"] != 5]))
    elif damage == "duplicate_worker":
        (directory / "process-6.jsonl").write_text((directory / "process-2.jsonl").read_text())
    elif damage == "missing_controller":
        (directory / "process-1.jsonl").unlink()
    else:
        monkeypatch.setattr(profile, "RAW_LIMIT", 1)
    assert profile.finalize(directory, raw, 0) == 2
    assert not raw.exists()
    assert json.loads((directory / "capture.json").read_text())["incomplete"]


def test_sanitizer_drops_command_names_custom_thread_names_and_extra_values():
    events = [trace_event('process 42:"private payload --token=secret"', filename=""),
              trace_event("thread (42): private identity", filename=""), trace_event("collect")]
    for event in events:
        event["locals"] = {"private": "payload"}
        event["args"]["sql"] = "private SQL parameter"
    encoded = json.dumps(profile.sanitize(events))
    assert all(secret not in encoded for secret in ("private", "payload", "token", "secret", "SQL", "locals"))
    assert "collect" in encoded and '"pid": 1' in encoded


def test_gc_callback_keeps_only_scalars_and_defers_io(tmp_path, monkeypatch):
    collector = profile.Collector(tmp_path, "gw0")
    before = collector.written
    stamps = iter(({"mono_ns": 0}, {"mono_ns": 2_000_000}))
    monkeypatch.setattr(profile, "stamp", lambda: next(stamps))
    collector.collection("start", {"generation": 2, "untrusted": object()})
    collector.collection("stop", {"generation": 2})
    assert collector.written == before
    assert collector.pending == [{"kind": "gc", "generation": 2,
                                  "start": {"mono_ns": 0}, "end": {"mono_ns": 2_000_000}}]
    monkeypatch.setattr(profile, "stamp", lambda: {})
    collector.close()
    assert collector.file.closed


def test_gc_drops_and_unmatched_spans_prevent_negative_gc_claim(tmp_path):
    directory, raw = capture(tmp_path)
    path = directory / "process-2.jsonl"
    records = [json.loads(line) for line in path.read_text().splitlines()]
    records[-1].update(dropped=1, unmatched=[1, 0, 0])
    path.write_text("\n".join(map(json.dumps, records)))
    assert profile.finalize(directory, raw, 0) == 0
    assert not json.loads((directory / "capture.json").read_text())["gc_complete"]


def test_plugin_removes_only_its_callback_and_closes_file(tmp_path, monkeypatch):
    existing = lambda *_args: None
    monkeypatch.setattr(profile, "gc", SimpleNamespace(callbacks=[existing],
                        isenabled=profile.gc.isenabled, get_threshold=profile.gc.get_threshold))
    monkeypatch.setenv("PALLIUM_CI_PROFILE_DIR", str(tmp_path))
    config = SimpleNamespace(workerinput={"workerid": "gw0"})
    profile.pytest_configure(config)
    collector = config._ci_cpu_gc_collector
    assert len(profile.gc.callbacks) == 2
    profile.pytest_unconfigure(config)
    assert profile.gc.callbacks == [existing] and collector.file.closed


def test_owned_group_cleanup_escalates_and_does_not_kill_unrelated_group(monkeypatch):
    calls = []
    clock = iter((0, 6, 10, 16))
    monkeypatch.setattr(profile, "time", SimpleNamespace(monotonic=lambda: next(clock)))
    monkeypatch.setattr(profile, "os", SimpleNamespace(killpg=lambda pid, sig: calls.append((pid, sig))))
    monkeypatch.setattr(profile, "signal", SimpleNamespace(SIGTERM=15, SIGKILL=9))
    with pytest.raises(RuntimeError, match="did not settle"):
        profile.drain_group(SimpleNamespace(pid=123, poll=lambda: None))
    assert calls == [(123, profile.signal.SIGTERM), (123, profile.signal.SIGKILL)]


def test_real_distributed_pytest_retains_original_failure_and_closes_each_collector(tmp_path):
    artifacts = tmp_path / "metadata"
    artifacts.mkdir()
    subject = tmp_path / "test_subject.py"
    subject.write_text("import gc\nimport pytest\n@pytest.mark.parametrize('case', range(8))\n"
                       "def test_original(case):\n    gc.collect()\n    assert case != 7\n")
    result = subprocess.run([sys.executable, "-m", "pytest", "--noconftest", "-q", "-n", "4",
                             "-p", "scripts.ci_cpu_gc_profile", str(subject)],
                            cwd=Path(__file__).parents[1],
                            env=os.environ | {"PALLIUM_CI_PROFILE_DIR": str(artifacts)},
                            text=True, capture_output=True, timeout=60)
    assert result.returncode == 1, result.stdout + result.stderr
    records = [[json.loads(line) for line in path.read_text().splitlines()]
               for path in artifacts.glob("process-*.jsonl")]
    assert {process[0]["worker"] for process in records} == {"controller", "gw0", "gw1", "gw2", "gw3"}
    assert all(process[-1]["kind"] == "summary" and not process[-1]["errors"] for process in records)
    assert sum(event["kind"] == "failure" for process in records for event in process) == 1
