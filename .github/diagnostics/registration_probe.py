"""One second-registration observation; imported retained hooks are never registered."""
import gc
import inspect
import json
import sys
import threading
import time
from pathlib import Path

import pytest
import retained_recorder as recorder
from gc_overlap_helpers import _make_gc_overlap_observer, _remove_exact_gc_observer

TARGET = "tests/test_codex_wake.py::test_atomic_reply_releases_first_and_dispatches_next_pending_once[claude-code]"
REPORT = {"target": TARGET, "turn_calls": 0, "observations": 0, "phases": [], "errors": []}
PHASE_CODE = None
ACTIVE_PHASE = False


def observe(frame, event, arg):
    global ACTIVE_PHASE
    try:
        if frame.f_code is PHASE_CODE:
            name = frame.f_locals.get("name")
            if name not in {"setup_pragma", "begin_immediate"}:
                return
            if event == "call":
                ACTIVE_PHASE = True
                if len(REPORT["phases"]) < 8:
                    REPORT["phases"].append({"phase": name, "deadline": frame.f_locals.get("acquisition_deadline"),
                                             "monotonic_ns": time.monotonic_ns()})
                else:
                    recorder.STATE["overflow"] = True
            recorder.profile(frame, event, arg)
            if event == "return":
                ACTIVE_PHASE = False
        elif ACTIVE_PHASE:
            recorder.profile(frame, event, arg)
    except BaseException as exc:
        recorder.error("adapter_profile", exc)


def capture(call):
    REPORT["observations"] += 1
    previous = sys.getprofile()
    REPORT["preexisting_profiler"] = previous is not None
    if previous is not None:
        return call()
    observer, events, starts, status = _make_gc_overlap_observer(time)
    callbacks = tuple(gc.callbacks)
    enabled, thresholds = gc.isenabled(), gc.get_threshold()
    REPORT.update(thread_id=threading.get_ident(), wall_start_ns=time.perf_counter_ns(),
                  cpu_start_ns=time.thread_time_ns())
    gc.callbacks.append(observer)
    try:
        sys.setprofile(observe)
        return call()
    finally:
        sys.setprofile(previous)
        REPORT.update(wall_end_ns=time.perf_counter_ns(), cpu_end_ns=time.thread_time_ns(),
                      profile_restored=sys.getprofile() is previous,
                      callback_removed=_remove_exact_gc_observer(gc.callbacks, observer),
                      callbacks_preserved=tuple(gc.callbacks) == callbacks,
                      gc_policy_unchanged=(gc.isenabled(), gc.get_threshold()) == (enabled, thresholds),
                      gc_events=events, gc_unmatched_starts=bool(starts), gc_status=status)


def pytest_collection_modifyitems(items):
    if [item.nodeid for item in items] != [TARGET]:
        raise pytest.UsageError("Diagnostic requires its one fixed original node")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    global PHASE_CODE
    from core.relay import RelayService
    from storage.sqlite_queue import SQLiteQueueMixin
    from sqlalchemy.engine import Connection
    from sqlalchemy.engine.default import DefaultDialect
    from sqlalchemy.sql.elements import TextClause, ClauseElement

    body = inspect.unwrap(SQLiteQueueMixin._begin_immediate_for)
    PHASE_CODE = next(code for code in body.__code__.co_consts
                      if inspect.iscode(code) and code.co_name == "acquire_phase")
    recorder.PYTHON_CALLS[PHASE_CODE] = "acquire_phase"
    for label, function in (("connection_execute", Connection.execute),
                            ("execute_clauseelement", Connection._execute_clauseelement),
                            ("execute_context", Connection._execute_context),
                            ("text_init", TextClause.__init__),
                            ("text_execute", TextClause._execute_on_connection),
                            ("compile_cache", ClauseElement._compile_w_cache),
                            ("dialect_execute", DefaultDialect.do_execute)):
        recorder.add_callable(label, function)
    original = RelayService.turn

    def turn(self, *args, **kwargs):
        REPORT["turn_calls"] += 1
        if REPORT["turn_calls"] == 2:
            REPORT["expected_registration"] = (kwargs.get("runtime") == "claude-code"
                                                and kwargs.get("session_ref") == "target")
            return capture(lambda: original(self, *args, **kwargs))
        return original(self, *args, **kwargs)

    item.funcargs["monkeypatch"].setattr(RelayService, "turn", turn)
    yield


def pytest_sessionfinish(session, exitstatus):
    state = recorder.STATE
    REPORT["pytest_exitstatus"] = int(exitstatus)
    REPORT["capture_integrity_complete"] = (
        REPORT["observations"] == 1 and REPORT.get("expected_registration", False)
        and REPORT.get("profile_restored", False) and REPORT.get("callback_removed", False)
        and REPORT.get("callbacks_preserved", False) and REPORT.get("gc_policy_unchanged", False)
        and not REPORT.get("gc_unmatched_starts", True)
        and not any(REPORT.get("gc_status", {"missing": True}).values())
        and not state["overflow"] and not state["unmatched"] and not state["errors"]
        and not recorder.STACK and not recorder.SKIPPED_DEPTH and not ACTIVE_PHASE
        and any(s["label"] == "cursor_execute" and s["category"] == "busy_timeout" for s in state["spans"])
        and any(s["label"] == "acquire_phase" for s in state["spans"]))
    REPORT["recorder"] = {k: state[k] for k in ("spans", "errors", "overflow", "unmatched")}
    REPORT["limits"] = ("One targeted observation with profiler overhead; no historical SQLite version. "
                        "Native wall/CPU gaps include scheduling/GIL and do not prove blocking. GC overlap is correlation. "
                        "Missing spans/incomplete capture or nonreproduction leaves cause unknown; no retry.")
    output = Path("test-results/registration-probe.json")
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(REPORT, indent=2), encoding="utf-8")