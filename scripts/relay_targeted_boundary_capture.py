"""One-shot, target-only pytest observer and bounded Linux owned runner.

No production import occurs until the exact target fixture is requested.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from contextvars import ContextVar
import hashlib
import importlib.metadata
import inspect
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
from types import MemberDescriptorType

import pytest

TARGET = "tests/test_agent_relay_hooks.py::test_codex_exact_wake_real_http_response_delay_is_bounded_and_traceable[1.15-False-delivered-True-False]"
OUTPUT_ENV = "PALLIUM_BOUNDARY_OUTPUT"
EVENT_LIMIT = 256
JSON_LIMIT = 64 * 1024
OUTPUT_LIMIT = 16 * 1024 * 1024
RESERVE = 128 * 1024
BASE = "e3117d2cac28046e701b707c38942d8b40ee881e"
ALLOWED = {"scripts/relay_targeted_boundary_capture.py", "tests/test_relay_targeted_boundary_capture.py",
           ".github/workflows/ci.yml", ".agent-workflow/tasks/service-performance.md"}
REQUEST = ContextVar("boundary_request", default=None)
STAGES = {"asgi_entry", "route_entry", "acquire_start", "acquire_end"}
NATIVE_FIELDS = {"submitted", "entered", "returned", "await_finished", "delay_entered",
                 "delay_finished", "send_finished", "status", "thread_id"}


class Recorder:
    def __init__(self):
        self.events = []
        self.reasons = set()
        self.ordinal = 0

    def incomplete(self, reason):
        # All reasons are fixed tokens; exception text and caller values are excluded.
        self.reasons.add(reason)

    def record(self, stage):
        try:
            ordinal = REQUEST.get()
            if ordinal is None:
                self.incomplete("uncorrelated")
                return
            event = {"stage": stage, "request": ordinal, "time": time.monotonic()}
            if stage not in STAGES or not math.isfinite(event["time"]):
                self.incomplete("unsupported_event")
                return
            if len(self.events) >= EVENT_LIMIT:
                self.incomplete("event_cap")
                return
            if len(json.dumps(self.events + [event]).encode()) > JSON_LIMIT - 4096:
                self.incomplete("json_cap")
                return
            self.events.append(event)
        except Exception:
            self.incomplete("observer_fault")


def replace(stack, owner, name, replacement):
    """Restore only our own mutation, including originally inherited methods."""
    original = getattr(owner, name)
    descriptor = inspect.getattr_static(type(owner), name, None)
    if isinstance(descriptor, MemberDescriptorType):
        owned = True
    else:
        if hasattr(descriptor, "__get__") and not inspect.isfunction(descriptor):
            raise ValueError("unsupported attribute descriptor")
        try:
            owned = name in vars(owner)
        except TypeError:
            raise ValueError("unsupported attribute owner") from None
    def restore():
        if getattr(owner, name) is replacement:
            if owned:
                setattr(owner, name, original)
            else:
                delattr(owner, name)
    stack.callback(restore)
    setattr(owner, name, replacement)
    return original


def closure(function, name, module, function_name):
    if not inspect.isfunction(function) or function.__module__ != module or function.__name__ != function_name:
        raise ValueError("unsupported callable provenance")
    cells = dict(zip(function.__code__.co_freevars, function.__closure__ or ()))
    return cells[name].cell_contents


def recover_limiter(route_call):
    operation = closure(route_call, "_run_relay_operation", "api.routes", "relay_turn")
    runner = closure(operation, "relay_codex_runner", "api.routes", "_run_relay_operation")
    limiter = closure(runner, "codex_admission_limiter", "app.main", "run_codex_relay_operation")
    import anyio
    if not isinstance(limiter, anyio.CapacityLimiter):
        raise ValueError("unsupported limiter provenance")
    method = limiter.acquire_on_behalf_of
    if getattr(method, "__self__", None) is not limiter or not method.__module__.startswith("anyio."):
        raise ValueError("unsupported bound method provenance")
    return limiter


def acquire_observer(original, recorder):
    async def acquire(borrower):
        recorder.record("acquire_start")
        try:
            return await original(borrower)
        except BaseException:
            recorder.incomplete("acquire_not_completed")
            raise
        finally:
            recorder.record("acquire_end")
    return acquire


def install(client, recorder, stack, *, limiter_lookup=recover_limiter):
    from fastapi.routing import APIRoute
    routes = [route for route in client.app.routes
              if isinstance(route, APIRoute) and route.path == "/relay/turn" and "POST" in route.methods]
    if len(routes) != 1 or client._transport.app is not client.app:
        raise ValueError("unsupported private transport or route")
    route = routes[0]
    call = route.dependant.call
    limiter = limiter_lookup(call)
    replace(stack, limiter, "acquire_on_behalf_of", acquire_observer(limiter.acquire_on_behalf_of, recorder))

    async def route_entry(*args, **kwargs):
        recorder.record("route_entry")
        return await call(*args, **kwargs)
    replace(stack, route.dependant, "call", route_entry)
    app = client._transport.app

    async def asgi(scope, receive, send):
        if scope.get("type") != "http":
            return await app(scope, receive, send)
        recorder.ordinal += 1
        token = REQUEST.set(recorder.ordinal)
        try:
            recorder.record("asgi_entry")
            return await app(scope, receive, send)
        finally:
            REQUEST.reset(token)
    replace(stack, client._transport, "app", asgi)


def observation(recorder, native_path):
    native = []
    try:
        if native_path.stat().st_size > JSON_LIMIT:
            raise ValueError("native stages too large")
        rows = json.loads(native_path.read_text(encoding="utf-8"))
        if not isinstance(rows, list) or len(rows) > EVENT_LIMIT:
            raise ValueError("unsupported native stages")
        for row in rows:
            if not isinstance(row, dict) or row.get("stage") not in {"forward", "worker", "durable_turn"}:
                raise ValueError("unsupported native stage")
            clean = {"stage": row["stage"]}
            if row.get("path") in {"/relay/turn", "/relay/deliveries/ack"}:
                clean["path"] = row["path"]
            for key in NATIVE_FIELDS:
                value = row.get(key)
                if type(value) in (int, float) and math.isfinite(value):
                    clean[key] = value
            if len(native) + len(recorder.events) >= EVENT_LIMIT:
                recorder.incomplete("event_cap")
                break
            native.append(clean)
    except Exception:
        recorder.incomplete("native_stages_missing_or_unsupported")
    turns = [row for row in native if row.get("path") == "/relay/turn"]
    if len(turns) != 1:
        recorder.incomplete("forward_unmatched")
    else:
        forward = turns[0]
        matches = [event for event in recorder.events if event["stage"] == "asgi_entry"
                   and forward.get("entered", math.inf) <= event["time"] <= forward.get("returned", -math.inf)]
        if len(matches) != 1:
            recorder.incomplete("request_unmatched")
        else:
            events = [event for event in recorder.events if event["request"] == matches[0]["request"]]
            if [event["stage"] for event in events] != ["asgi_entry", "route_entry", "acquire_start", "acquire_end"]:
                recorder.incomplete("target_spans_unmatched")
    if not {"forward", "worker", "durable_turn"}.issubset({row["stage"] for row in native}):
        recorder.incomplete("native_spans_missing")
    result = {"complete": not recorder.reasons, "reasons": sorted(recorder.reasons),
              "events": recorder.events, "native_stages": native,
              "limitation": "observer perturbation; admission holder and physical cause unknown"}
    if len(json.dumps(result).encode()) > JSON_LIMIT:
        result = {"complete": False, "reasons": ["json_cap"], "events": [], "native_stages": []}
    return result


@pytest.fixture(autouse=True)
def _target_capture(request):
    if request.node.nodeid != TARGET or not os.environ.get(OUTPUT_ENV):
        return
    recorder, stack = Recorder(), ExitStack()
    request.node._boundary_capture = (recorder, stack, request.getfixturevalue("tmp_path"))
    try:
        install(request.getfixturevalue("client"), recorder, stack)
    except Exception:
        recorder.incomplete("installation_unsupported")
        try:
            stack.close()
        except Exception:
            recorder.incomplete("restoration_fault")


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_teardown(item, nextitem):
    # Outermost post-yield runs after native fixtures, including private app drain.
    try:
        yield
    finally:
        state = getattr(item, "_boundary_capture", None)
        if state is not None:
            recorder, stack, tmp = state
            try:
                stack.close()
            except Exception:
                recorder.incomplete("restoration_fault")
            try:
                result = observation(recorder, tmp / "delayed-http-stages.json")
                path = Path(os.environ[OUTPUT_ENV]) / "observation.json"
                with path.open("x", encoding="utf-8") as output:
                    json.dump(result, output)
            except Exception:
                # Observation cannot change the native pytest result.
                pass


def git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


def fences():
    names = subprocess.check_output(["git", "ls-files", "-z"]).decode().split("\0")
    digest = hashlib.sha256()
    for name in sorted(name for name in names if name and name not in ALLOWED):
        digest.update(name.encode())
        digest.update(Path(name).read_bytes())
    changes = set(git("diff", "--name-only", BASE, "--").splitlines())
    return {"head": git("rev-parse", "HEAD"), "tree": git("rev-parse", "HEAD^{tree}"),
            "source_lock_sha256": digest.hexdigest(), "baseline": BASE,
            "baseline_ok": not bool(changes - ALLOWED),
            "diagnostic_sha256": {name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
                                  for name in sorted(ALLOWED)},
            "git_status": git("status", "--porcelain=v1", "--untracked-files=all")}


def terminate_group(process, sig):
    # A reaped root no longer reserves its PID/PGID for our owned process group.
    if process.returncode is not None:
        return
    try:
        os.killpg(process.pid, sig)
    except ProcessLookupError:
        pass


def settle_owned(process, result):
    """Terminate only an unreaped child, then bounded-wait for its native exit."""
    if process.poll() is None and "owned_process_unsettled" not in result["reasons"]:
        terminate_group(process, signal.SIGTERM)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            terminate_group(process, signal.SIGKILL)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                result["reasons"].append("owned_process_unsettled")
    result["native_exit"] = process.returncode


def collect(process, streams, output, *, wall=1200, term=10, drain=5,
            limit=OUTPUT_LIMIT - RESERVE - JSON_LIMIT, fifo_writer=None):
    """Drain all owned streams with one shared retained-byte cap."""
    selector = selectors.DefaultSelector()
    handles = {}
    started = time.monotonic()
    total, stop_at, killed_at, exited_at = 0, None, None, None
    reasons = set()
    settled = False
    try:
        for name, stream in streams.items():
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, name)
            handles[name] = (output / name).open("xb")
        while True:
            now = time.monotonic()
            exited = process.poll() is not None
            if exited and exited_at is None:
                exited_at = now
            if exited and fifo_writer is not None:
                fifo_writer.close()
                fifo_writer = None
            if stop_at is None and (now - started >= wall or "output_cap" in reasons):
                reasons.add("timeout" if now - started >= wall else "output_cap")
                if not exited:
                    terminate_group(process, signal.SIGTERM)
                stop_at = now
            if not exited and stop_at is not None and killed_at is None and now - stop_at >= term:
                terminate_group(process, signal.SIGKILL)
                killed_at = now
            if exited_at is not None and now - exited_at >= drain and selector.get_map():
                reasons.add("descendant_stream_drain")
                reasons.add("drain_incomplete")
                break
            if exited and not selector.get_map():
                break
            if killed_at is not None and now - killed_at >= drain:
                if selector.get_map():
                    reasons.add("drain_incomplete")
                break
            for key, _ in selector.select(timeout=0.1):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                keep = chunk[:max(0, limit - total)]
                handles[key.data].write(keep)
                total += len(keep)
                if len(keep) != len(chunk):
                    reasons.add("output_cap")
        if process.poll() is None:
            reasons.add("owned_process_unsettled")
        settled = process.returncode is not None and not selector.get_map()
    finally:
        selector.close()
        for handle in handles.values():
            handle.close()
    return {"native_exit": process.returncode, "reasons": sorted(reasons), "retained_stream_bytes": total,
            "owned_settled": settled}


def run(output):
    if sys.platform != "linux" or sys.version_info[:2] != (3, 12):
        raise ValueError("capture requires Linux Python 3.12")
    output = output.absolute()
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    result = {"complete": False, "native_exit": None, "reasons": []}
    process = None
    try:
        before = fences()
        result["before"] = before
        if before["git_status"]:
            raise ValueError("capture requires clean checkout")
        if not before["baseline_ok"]:
            raise ValueError("source baseline differs")
        result["versions"] = {dist.metadata["Name"]: dist.version for dist in importlib.metadata.distributions()}
        result["python"] = sys.version
        with tempfile.TemporaryDirectory(prefix="pallium-boundary-") as private:
            root = Path(private)
            env = os.environ.copy()
            for key in ("HOME", "USERPROFILE", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "TMPDIR", "TEMP", "TMP"):
                directory = root / key.lower()
                directory.mkdir()
                env[key] = str(directory)
            env.update({OUTPUT_ENV: str(output), "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"})
            fifo = root / "native-junit.fifo"
            os.mkfifo(fifo, 0o600)
            # Keep a writer until the owned child exits, then expose EOF to the drain.
            reader = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
            writer = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
            command = [sys.executable, "-m", "pytest", "-p", "scripts.relay_targeted_boundary_capture",
                       "tests/", "-x", "-q", f"--junitxml={fifo}"]
            result["command"] = command[:-1] + ["--junitxml=<private-fifo>"]
            try:
                with os.fdopen(reader, "rb", buffering=0) as junit, os.fdopen(writer, "wb", buffering=0) as keeper:
                    process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                               start_new_session=True)
                    # The collection loop closes the idempotent keeper on child exit.
                    result.update(collect(process, {"stdout.log": process.stdout, "stderr.log": process.stderr,
                                                    "native-junit.xml": junit}, output, fifo_writer=keeper))
            finally:
                if process is not None:
                    try:
                        settle_owned(process, result)
                    finally:
                        process.stdout.close()
                        process.stderr.close()
            result["after"] = fences()
            if before != result["after"]:
                result["reasons"].append("source_fence_changed")
        try:
            observed = json.loads((output / "observation.json").read_text(encoding="utf-8"))
            if not observed.get("complete"):
                result["reasons"].append("observation_incomplete")
        except Exception:
            result["reasons"].append("target_missing_or_observation_unreadable")
        if not (output / "native-junit.xml").stat().st_size:
            result["reasons"].append("junit_missing")
        result["complete"] = not result["reasons"]
    except Exception as exc:
        result["reasons"].append("tooling_failure:" + type(exc).__name__)
        if process is not None:
            result["native_exit"] = process.returncode
    encoded = json.dumps(result, indent=2).encode()
    if len(encoded) > RESERVE:
        encoded = json.dumps({"complete": False, "native_exit": result["native_exit"],
                              "reasons": ["metadata_cap"]}).encode()
    (output / "runner.json").write_bytes(encoded)
    return 0 if result["complete"] and result["native_exit"] == 0 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(run(args.output))
