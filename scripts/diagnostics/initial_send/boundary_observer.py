"""Private, one-case diagnostic candidate. No dispatch or process inspection."""
import hashlib
import importlib.util
import os
import json
import sys
import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import event

ROOT = Path(__file__).resolve().parents[3]
ORIGINAL = Path(__file__).with_name("retained_recorder.py")
ORIGINAL_SHA = "f556fbc5ddbb4096f3bf65663f995c729d84b8fddefec8f1f48d2e3f5cc0b2fa"
if hashlib.sha256(ORIGINAL.read_bytes()).hexdigest() != ORIGINAL_SHA:
    raise pytest.UsageError("Retained recorder correspondence failed")
SPEC = importlib.util.spec_from_file_location("retained_pool_recorder", ORIGINAL)
recorder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recorder)

API = "tests/test_codex_wake.py::test_exclusive_trial_binding_and_spend_survive_restart_and_later_delivery[True]"
TARGETS = {API}
DIRECT = {}
C_METHODS = dict(recorder.C_METHODS)
STATE = {}
ACTIVE = None


def error(stage, exc):
    recorder.error(stage, exc)


def profile(frame, kind, argument):
    """Retained recorder's bounded pairing, with real file-IO labels added."""
    try:
        if kind in {"call", "return"}:
            label, token = recorder.PYTHON_CALLS.get(frame.f_code), frame.f_code
        elif kind in {"c_call", "c_return", "c_exception"}:
            owner = getattr(argument, "__self__", None)
            token = vars(type(owner)).get(getattr(argument, "__name__", ""))
            label = DIRECT.get(argument)
            if label is not None:
                token = argument
            elif argument is recorder.sqlite3.connect:
                label, token = "native_connect", argument
            else:
                label = C_METHODS.get(token)
        else:
            return
        if label is None:
            return
        if kind in {"call", "c_call"}:
            if recorder.SKIPPED_DEPTH or len(STATE["spans"]) + len(STATE["connection_events"]) + len(recorder.STACK) >= 128:
                recorder.SKIPPED_DEPTH += 1
                STATE["overflow"] = True
                return
            recorder.STACK.append((token, {
                "label": label, "category": recorder.sql_category(frame),
                "depth": len(recorder.STACK), "wall_start_ns": time.perf_counter_ns(),
                "cpu_start_ns": time.thread_time_ns(),
            }))
        elif recorder.SKIPPED_DEPTH:
            recorder.SKIPPED_DEPTH -= 1
        elif not recorder.STACK or recorder.STACK[-1][0] is not token:
            STATE["unmatched"] = True
        else:
            _, span = recorder.STACK.pop()
            span.update(wall_end_ns=time.perf_counter_ns(), cpu_end_ns=time.thread_time_ns(),
                        outcome="c_exception" if kind == "c_exception" else "return")
            STATE["spans"].append(span)
    except BaseException as exc:
        error("profile", exc)


def observe_call(operation, *args, **kwargs):
    global ACTIVE
    previous = sys.getprofile()
    ACTIVE = threading.get_ident()
    STATE["active_thread"] = ACTIVE
    STATE["call_wall_start_ns"], STATE["call_cpu_start_ns"] = time.perf_counter_ns(), time.thread_time_ns()
    try:
        try:
            sys.setprofile(profile)
        except BaseException as exc:
            error("profile_install", exc)
        return operation(*args, **kwargs)
    except BaseException as exc:
        STATE["exception"] = {"type": type(exc).__name__,
                              "acquisition_stage": getattr(exc, "acquisition_stage", None)}
        raise
    finally:
        try:
            sys.setprofile(previous)
        except BaseException as exc:
            error("profile_restore", exc)
        STATE["profile_restored"] = sys.getprofile() is previous
        STATE["call_wall_end_ns"], STATE["call_cpu_end_ns"] = time.perf_counter_ns(), time.thread_time_ns()
        STATE["unmatched"] |= bool(recorder.STACK or recorder.SKIPPED_DEPTH)
        STATE.pop("active_thread", None)
        ACTIVE = None


def pytest_collection_modifyitems(items):
    if len(items) != 1 or items[0].nodeid not in TARGETS:
        raise pytest.UsageError("Candidate requires exactly one named failed case")
    manifest = json.loads(Path(__file__).with_name("manifest.json").read_text(encoding="utf-8"))
    if manifest["execution_status"] != "AUTHORIZED_API_ONLY":
        raise pytest.UsageError("Execution remains held; source review is not an execution grant")
    name = "api"
    if (Path(os.environ["INITIAL_SEND_OUTPUT"]) / name / "receipt.json").exists():
        raise pytest.UsageError("This case already has a receipt; no replay in this package")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    global STATE
    STATE = {"node": item.nodeid, "spans": [], "connection_events": [], "errors": [],
             "overflow": False, "unmatched": False, "calls": 0,
             "profile_restored": False}
    recorder.STATE = STATE
    recorder.STACK.clear()
    recorder.PYTHON_CALLS.clear()
    recorder.SKIPPED_DEPTH = 0
    patches, listeners = pytest.MonkeyPatch(), []
    try:
        if item.nodeid == API:
            store = item.funcargs["client"].app.state.pallium_service._storage
            engine = store._relay_engine
            for label, function in (
                ("session_connection", recorder.Session.connection),
                ("session_bind", recorder.SessionTransaction._connection_for_bind),
                ("pool_connect", recorder.Pool.connect), ("pool_get", recorder.QueuePool._do_get),
                ("record_get", recorder._ConnectionRecord.get_connection),
                ("record_connect", recorder._ConnectionRecord._ConnectionRecord__connect),
                ("creator", engine.pool._creator), ("dialect_connect", engine.dialect.connect),
                ("set_isolation", engine.dialect.set_isolation_level),
                ("get_isolation", engine.dialect.get_isolation_level),
            ):
                recorder.add_callable(label, function)
            for index, callback in enumerate(engine.pool.dispatch.connect):
                recorder.add_callable("connect_callback" + str(index), callback)
            for stage in ("connect", "checkout"):
                def connection_event(connection, record, *extra, stage=stage):
                    try:
                        recorder.connection_event(stage, connection, record, *extra)
                    except BaseException as exc:
                        error("connection_event", exc)
                event.listen(engine, stage, connection_event)
                listeners.append((engine, stage, connection_event))
            original_send = store.relay_send
            original_begin = store._begin_immediate_for

            def begin(*args, **kwargs):
                if ACTIVE == threading.get_ident():
                    STATE["acquisition_deadline"] = kwargs.get("acquisition_deadline")
                return original_begin(*args, **kwargs)

            def send(*args, **kwargs):
                if STATE["calls"]:
                    return original_send(*args, **kwargs)
                STATE["calls"] += 1
                return observe_call(original_send, *args, **kwargs)

            patches.setattr(store, "_begin_immediate_for", begin)
            patches.setattr(store, "relay_send", send)
        yield
    finally:
        try:
            patches.undo()
        except BaseException as exc:
            error("patch_restore", exc)
        for engine, stage, callback in listeners:
            try:
                event.remove(engine, stage, callback)
            except BaseException as exc:
                error("event_remove", exc)
        STATE["listeners_restored"] = not any(event.contains(*entry) for entry in listeners)
        if STATE["calls"] != 1:
            STATE["unmatched"] = True
        STATE["limits"] = (
            "Observer overhead affects timing. Wall/CPU gaps cannot distinguish blocking from descheduling. "
            "Budget snapshots surround, not reproduce, decision-clock reads. Missing branches stay unknown. "
            "No process inventory, native cleanup substitution, replay qualification or physical-cause claim."
        )


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    result = yield
    report = result.get_result()
    if report.when == "call":
        try:
            name = "api"
            directory = Path(os.environ["INITIAL_SEND_OUTPUT"]) / name
            directory.mkdir(exist_ok=True)
            receipt = {
                "node": item.nodeid, "outcome": report.outcome,
                "diagnosis": "unknown; no reproduction proves no cure",
                "calls": STATE["calls"], "profile_restored": STATE["profile_restored"],
                "listeners_restored": STATE["listeners_restored"],
                "overflow": STATE["overflow"], "unmatched": STATE["unmatched"],
                "errors": STATE["errors"],
                "labels_seen": sorted({span["label"] for span in STATE["spans"]}),
                "limits": STATE["limits"],
            }
            with (directory / "receipt.json").open("x", encoding="utf-8") as handle:
                json.dump(receipt, handle, indent=2)
            if report.failed:
                with (directory / "observations.json").open("x", encoding="utf-8") as handle:
                    json.dump(STATE, handle, indent=2)
        except BaseException as exc:
            report.sections.append(("diagnostic receipt", "unavailable: " + type(exc).__name__))
