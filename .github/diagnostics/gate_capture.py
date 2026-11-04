"""Bounded native-gate diagnostic. Import is inert; CLI actions are explicit."""
from contextvars import ContextVar
from itertools import count
from pathlib import Path
from types import SimpleNamespace
import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import signal
import sqlite3
import subprocess
import sys
import sysconfig
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET

SOURCE = "5e526641db27a5a91655164ccbf7194f097cdaba"
TREE = "3b754f88f5da1dd73e477f257ebace9aca13810a"
REPO = "rore/Pallium"
REF = "feat/s3-linux313-native-gate-capture"
WORKFLOW = ".github/workflows/ci.yml"
WAIT = "tests/test_sqlite_write_retry.py::TestImmediateTransactionRetry::test_same_provider_writer_waits_locally_before_native_begin"
BUSY = "tests/test_relay_work_ref_associations_e2e.py::test_unsettled_relay_write_keeps_gate_until_observed_terminal_return[active]"
SUBJECT = "tests/test_codex_retained_wake.py::test_write_is_fenced_across_concurrency_recovery_restart[None]"
NODES = {"controls": (WAIT, BUSY), "subject": (SUBJECT,)}
PINS = (
    "tests/test_sqlite_write_retry.py", "tests/test_relay_work_ref_associations_e2e.py",
    "tests/test_codex_retained_wake.py", "tests/conftest.py", "pyproject.toml",
    "storage/sqlite_queue.py", "storage/sqlite_relay.py", "api/routes.py",
    "app/codex_wake.py", "app/codex_bridge_pipe.py", "app/relay_trace.py",
)
PROJECT = {"app", "api", "core", "storage", "tests", "capabilities", "semantic", "providers", "retrieval"}
OPERATIONS = {"unknown", "relay_turn", "relay_send", "relay_attach_work_ref", "relay_codex_wake_transition", "test_same_provider_writer_waits_locally_before_native_begin"}
TRANSITIONS = {"reserve", "begin_native_attempt", "outcome", "release", "reconcile", "retry_target"}
OPERATIONS |= {"wake:" + value for value in TRANSITIONS}
KINDS = {"acquire_entry", "acquire_return", "acquire_error", "release_entry", "release_return", "release_error", "http_entry", "http_return", "http_error", "call_end"}
REQUEST = ContextVar("native_gate_request", default=None)
STATE = None
LIMIT = 16 * 1024 * 1024


class Rejected(Exception):
    pass


def require(condition, code):
    if not condition:
        raise Rejected(code)


def integer(value):
    return type(value) is int and 0 <= value < 2**63


def sha(path):
    path = Path(path)
    require(not path.is_symlink() and all(not p.is_symlink() for p in path.parents), "file_symlink")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha_text(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def exact(value, fields):
    require(type(value) is dict and set(value) == set(fields), "schema_keys")


def load(path, limit=LIMIT):
    require(not path.is_symlink() and all(not p.is_symlink() for p in path.parents) and path.stat().st_size <= limit, "input_bound")
    data = path.read_bytes()
    require(len(data) <= limit, "input_bound")
    return json.loads(data, parse_constant=lambda _v: (_ for _ in ()).throw(Rejected("json_number")))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    require(not path.is_symlink() and all(not p.is_symlink() for p in path.parents), "output_symlink")
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    require(len(data) <= LIMIT, "output_bound")
    path.write_bytes(data)


def run_git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=15, check=True)
    return result.stdout.decode().strip()


def constraints(path):
    result = {}
    for line in path.read_text().splitlines():
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9.!+_-]{1,64})", line)
        require(match is not None, "constraint_format")
        name = re.sub(r"[-_.]+", "-", match[1]).lower()
        require(name not in result, "constraint_duplicate")
        result[name] = match[2]
    require(len(result) == 68, "constraint_count")
    return result


def identity(root, pinfile):
    require(sys.version_info[:3] == (3, 13, 17) and sqlite3.sqlite_version == "3.45.1", "interpreter_profile")
    environment = Path(os.environ["GATE_ENV_ROOT"]).resolve()
    require(Path(sys.prefix).resolve() == Path(sys.exec_prefix).resolve() == environment and environment != Path(sys.base_prefix).resolve(), "interpreter_environment")
    require(Path(sys.executable).absolute().parent.parent.resolve() == environment, "interpreter_location")
    osinfo = platform.freedesktop_os_release()
    require(osinfo.get("ID") == "ubuntu" and osinfo.get("VERSION_ID") == "24.04" and platform.machine() == "x86_64", "os_profile")
    expected = constraints(pinfile)
    installed = {}
    records = {}
    bootstrap = {}
    seen = set()
    for distribution in importlib.metadata.distributions():
        location = getattr(distribution, "_path", None)
        require(isinstance(location, Path), "metadata_location_type")
        location = location.resolve()
        editable = location.parent == root and location.name == "pallium.egg-info"
        require(location.is_relative_to(environment) or editable, "metadata_origin")
        name = re.sub(r"[-_.]+", "-", distribution.metadata["Name"]).lower()
        require(not editable or name == "pallium", "editable_project_identity")
        version = distribution.version
        require(re.fullmatch(r"[A-Za-z0-9.!+_-]{1,64}", version) is not None, "version_shape")
        record = distribution.read_text("RECORD") or distribution.read_text("METADATA") or distribution.read_text("PKG-INFO")
        require(record is not None, "distribution_record")
        record_sha = hashlib.sha256(record.encode()).hexdigest()
        marker = (name, version, str(Path(distribution.locate_file("")).resolve()), record_sha)
        if marker in seen:
            continue
        seen.add(marker)
        if name in {"pip", "setuptools", "wheel"}:
            require(name not in bootstrap, "bootstrap_duplicate")
            bootstrap[name] = version
            continue
        require(name in expected and expected[name] == version, "distribution_profile")
        require(name not in installed or name == "pallium", "distribution_duplicate")
        installed[name] = version
        records.setdefault(name, []).append(record_sha)
    require(installed == expected, "distribution_inventory")
    require(run_git(root, "rev-parse", "HEAD") == SOURCE, "source_revision")
    require(run_git(root, "rev-parse", "HEAD^{tree}") == TREE and not run_git(root, "status", "--porcelain"), "source_tree")
    require(all(len(values) <= (2 if name == "pallium" else 1) for name, values in records.items()), "metadata_duplicate_bound")
    point = re.search(r"24\.04(?:\.[0-9]{1,2})?", osinfo.get("VERSION", ""))
    image = os.environ.get("ImageVersion", "unknown")
    require(image == "unknown" or re.fullmatch(r"[0-9.]{1,32}", image), "image_metadata")
    return dict(source=SOURCE, tree=TREE, python=[3, 13, 17], sqlite="3.45.1", os="ubuntu-24.04", os_point=point[0] if point else "unknown", image_version=image, architecture="x86_64", environment_verified=True, environment_config=sha(environment / "pyvenv.cfg"), packages=installed, records={name: sorted(values) for name, values in records.items()}, bootstrap=bootstrap, pins={name: sha(root / name) for name in PINS}, module=sha(Path(__file__)), constraints=sha(pinfile))


def source_inputs(root):
    names = run_git(root, "ls-files", "-z").rstrip("\0").split("\0")
    require(len(names) <= 5000, "source_inventory_bound")
    result = []
    for name in names:
        path = Path(name)
        require(name and len(name) <= 512 and all(c.isalnum() or c in "_./-" for c in name) and not path.is_absolute() and ".." not in path.parts and "\\" not in name, "source_relative_path")
        require(not (root / path).is_symlink(), "source_symlink")
        result.append(dict(path=name, sha256=sha(root / path)))
    return result


def origins(root):
    environment = Path(os.environ["GATE_ENV_ROOT"]).resolve()
    paths = sysconfig.get_paths()
    sites = {Path(paths[name]).resolve() for name in ("purelib", "platlib")}
    standard = {Path(paths[name]).resolve() for name in ("stdlib", "platstdlib")}
    require(all(path.is_relative_to(environment) for path in sites), "site_environment")
    dependency_roots = {name for name, owners in importlib.metadata.packages_distributions().items() if any(re.sub(r"[-_.]+", "-", owner).lower() != "pallium" for owner in owners)}
    checked = {name: 0 for name in ("project", "dependencies", "stdlib", "observer", "builtin")}
    require(len(sys.modules) <= 10000, "module_inventory_bound")
    observer = Path(__file__).resolve()
    for name, module in tuple(sys.modules.items()):
        filename = getattr(module, "__file__", None)
        if not filename:
            require(getattr(getattr(module, "__spec__", None), "origin", None) in {None, "built-in", "frozen"}, "module_without_origin")
            namespace = tuple(getattr(module, "__path__", ()))
            require(len(namespace) <= 32, "namespace_bound")
            for entry in namespace:
                path = Path(entry).resolve()
                require(any(path.is_relative_to(site) for site in sites) or path.is_relative_to(root) or (not any(part in {"site-packages", "dist-packages"} for part in path.parts) and any(path.is_relative_to(base) for base in standard)), "foreign_namespace_origin")
            checked["builtin"] += 1
            continue
        path = Path(filename).resolve()
        top = name.split(".")[0]
        if path == observer and name in {"__main__", "gate_capture"}:
            category = "observer"
        elif top in dependency_roots:
            require(any(path.is_relative_to(site) for site in sites), "foreign_dependency_origin")
            category = "dependencies"
        elif top in PROJECT:
            require(path.is_relative_to(root), "foreign_project_origin")
            category = "project"
        elif any(path.is_relative_to(site) for site in sites):
            category = "dependencies"
        elif path.is_relative_to(root):
            category = "project"
        else:
            require(not any(part in {"site-packages", "dist-packages"} for part in path.parts) and any(path.is_relative_to(base) for base in standard), "foreign_runtime_origin")
            category = "stdlib"
        checked[category] += 1
    return checked


def origin_counts(value):
    exact(value, {"project", "dependencies", "stdlib", "observer", "builtin"})
    require(all(integer(count) and count <= 10000 for count in value.values()), "origin_counts")


def operation(root):
    frame = sys._getframe(1)
    label = "unknown"
    files = {str(root / p) for p in ("storage/sqlite_relay.py", "core/codex_wake.py", "tests/test_sqlite_write_retry.py")}
    try:
        for _ in range(40):
            if frame is None:
                break
            if frame.f_code.co_filename in files:
                name = frame.f_code.co_name
                if name in OPERATIONS:
                    label = name
                if name == "_transition":
                    value = frame.f_locals.get("operation")
                    if type(value) is str and value in TRANSITIONS:
                        return "wake:" + value
            frame = frame.f_back
        return label
    finally:
        del frame


class Capture:
    def __init__(self, item, state):
        self.item, self.state = item, state
        fixture = item.funcargs.get("http_wake")
        self.http = fixture[0] if fixture else item.funcargs.get("client")
        self.workers = fixture[6] if fixture else []
        self.storage = fixture[1]._store if fixture else (self.http.app.state.pallium_service._storage if self.http else item.funcargs["storage"])
        database = Path(self.storage._relay_engine.url.database).resolve()
        require(database.is_relative_to(Path(item.funcargs["tmp_path"]).resolve()) and not database.is_relative_to(state.root), "fixture_database")
        require(Path(sys.modules["storage.sqlite"].__file__).resolve() == state.root / "storage/sqlite.py", "fixture_source")
        self.gate = self.storage._relay_writer_lock
        require(type(self.gate).__module__ == "_thread", "fixture_native_gate")
        self.events, self.faults = [None] * 4096, []
        self.event_ids, self.tokens = count(), count(1)
        self.calls, self.forwarded = [count() for _ in range(3)], [count() for _ in range(3)]
        self.local, self.attempts, self.active = threading.local(), {}, True
        self.post_present = self.http is not None and "post" in vars(self.http)
        self.post_attribute = vars(self.http).get("post") if self.http else None
        self.original_post = self.http.post if self.http else None
        self.storage._relay_writer_lock = SimpleNamespace(acquire=self.acquire, release=self.release, locked=self.locked)
        if self.http:
            self.http.post = self.post

    def fault(self, code):
        if len(self.faults) < 16:
            self.faults.append(code)

    def emit(self, kind, **fields):
        if not self.active:
            return
        try:
            slot = next(self.event_ids)
            if slot >= len(self.events):
                self.fault("event_overflow")
                return
            self.events[slot] = dict(sequence=slot, kind=kind, tid=threading.get_ident(), wall_ns=time.perf_counter_ns(), cpu_ns=time.thread_time_ns(), request=REQUEST.get(), **fields)
        except BaseException:
            self.fault("observation")

    def acquire(self, *args, **kwargs):
        next(self.calls[0])
        token, label = None, "unknown"
        try:
            token, label = next(self.tokens), operation(self.state.root)
            primitive = lambda v: type(v) in (bool, int, float) and (type(v) is bool or 0 <= v <= 1)
            valid = len(args) <= 2 and all(primitive(v) for v in args) and set(kwargs) <= {"blocking", "timeout"} and all(primitive(v) for v in kwargs.values())
            if valid:
                self.emit("acquire_entry", token=token, operation=label, args=list(args), kwargs=dict(kwargs))
            else:
                self.fault("acquire_arguments")
        except BaseException:
            self.fault("acquire_observation")
        next(self.forwarded[0])
        try:
            result = self.gate.acquire(*args, **kwargs)
        except BaseException:
            self.emit("acquire_error", token=token, operation=label)
            raise
        self.emit("acquire_return", token=token, operation=label, result=result)
        if result:
            try:
                if getattr(self.local, "token", None) is not None:
                    self.fault("nested_success")
                self.local.token = token
            except BaseException:
                self.fault("token_publication")
        return result

    def release(self, *args, **kwargs):
        next(self.calls[1])
        token = None
        try:
            token = getattr(self.local, "token", None)
        except BaseException:
            self.fault("release_observation")
        self.emit("release_entry", token=token)
        next(self.forwarded[1])
        try:
            result = self.gate.release(*args, **kwargs)
        except BaseException:
            self.emit("release_error", token=token)
            raise
        try:
            self.local.token = None
        except BaseException:
            self.fault("release_publication")
        self.emit("release_return", token=token)
        return result

    def locked(self, *args, **kwargs):
        next(self.calls[2])
        next(self.forwarded[2])
        return self.gate.locked(*args, **kwargs)

    def post(self, *args, **kwargs):
        handle = None
        try:
            caller = threading.get_ident()
            attempt = self.attempts.get(caller, 0) + 1
            self.attempts[caller] = attempt
            handle = REQUEST.set((caller, attempt))
            self.emit("http_entry")
        except BaseException:
            self.fault("http_observation")
        try:
            response = self.original_post(*args, **kwargs)
            try:
                self.emit("http_return", status=response.status_code)
            except BaseException:
                self.fault("http_result")
            return response
        except BaseException:
            self.emit("http_error")
            raise
        finally:
            if handle is not None:
                try:
                    REQUEST.reset(handle)
                except BaseException:
                    self.fault("http_restoration")

    def finish(self):
        settled = not self.gate.locked() and not any(worker.is_alive() for worker in self.workers)
        require(settled, "unsettled_teardown")
        self.storage._relay_writer_lock = self.gate
        if self.http:
            if self.post_present:
                self.http.post = self.post_attribute
            else:
                vars(self.http).pop("post", None)
        restored = self.storage._relay_writer_lock is self.gate and (self.http is None or self.http.post == self.original_post)
        used = next(self.event_ids)
        require(used <= 4096 and all(e is not None for e in self.events[:used]), "capture_gap")
        report = dict(node=self.item.nodeid, worker=self.state.worker, pid=os.getpid(), events=self.events[:used], faults=self.faults, restored=restored, settled=settled, calls=[next(c) for c in self.calls], forwarded=[next(c) for c in self.forwarded])
        filename = hashlib.sha256(self.item.nodeid.encode()).hexdigest() + ".json"
        path = self.state.directory / filename
        write(path, report)
        self.state.reports.append(dict(node=self.item.nodeid, file=filename, sha256=sha(path)))


if __name__ != "__main__":
    import pytest

    def pytest_configure(config):
        global STATE
        root = Path.cwd().resolve()
        worker = config.workerinput["workerid"] if hasattr(config, "workerinput") else "controller"
        require(worker == "controller" or worker in {"gw0", "gw1", "gw2", "gw3"}, "worker_identity")
        if worker != "controller":
            require(config.workerinput["workercount"] == 4, "worker_count")
        stage = os.environ["GATE_STAGE"]
        require(stage in NODES, "stage")
        STATE = SimpleNamespace(root=root, worker=worker, stage=stage, directory=Path(os.environ["GATE_OUT"]) / worker / str(os.getpid()), pinfile=Path(os.environ["GATE_CONSTRAINTS"]), reports=[], outcomes={}, faults=[], nodes={})

    def pytest_sessionstart(session):
        STATE.early = identity(STATE.root, STATE.pinfile)
        STATE.early_origins = origins(STATE.root)
        require(session.config.pluginmanager.hasplugin("gate_capture"), "plugin_registration")
        STATE.registered = True
        STATE.directory.mkdir(parents=True, exist_ok=False)
        raw = []
        for name, plugin in session.config.pluginmanager.list_name_plugin():
            raw.append(dict(name=name, file=getattr(plugin, "__file__", None)))
        write(STATE.directory / "raw-plugins.private.json", raw)
        write(STATE.directory / "raw-origins.private.json", {name: str(getattr(module, "__file__")) for name, module in tuple(sys.modules.items()) if getattr(module, "__file__", None)})

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_runtest_call(item):
        require(STATE.worker != "controller" and item.nodeid in NODES[STATE.stage], "unexpected_node")
        observer = Capture(item, STATE)
        item._native_gate_capture = observer
        try:
            yield
        finally:
            observer.emit("call_end")
            observer.active = False

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_runtest_teardown(item, nextitem):
        yield
        observer = getattr(item, "_native_gate_capture", None)
        if observer is not None:
            try:
                observer.finish()
            except BaseException:
                STATE.faults.append("finish_failure")

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(item, call):
        result = yield
        report = result.get_result()
        require(item.nodeid in NODES[STATE.stage] and report.when in {"setup", "call", "teardown"}, "unexpected_report")
        phases = STATE.outcomes.setdefault(item.nodeid, {})
        require(report.when not in phases and report.outcome in {"passed", "failed", "skipped"}, "duplicate_report")
        phases[report.when] = report.outcome

    def pytest_testnodedown(node, error):
        worker = node.workerinput["workerid"]
        require(worker in {"gw0", "gw1", "gw2", "gw3"} and worker not in STATE.nodes and error is None, "worker_crash_or_replacement")
        STATE.nodes[worker] = node.workeroutput.get("native_gate")

    def pytest_sessionfinish(session, exitstatus):
        try:
            late = identity(STATE.root, STATE.pinfile)
            require(late == STATE.early, "worker_input_drift")
            meta = dict(worker=STATE.worker, pid=os.getpid(), identity=late, early_origins=STATE.early_origins, origins=origins(STATE.root), registered=STATE.registered, faults=STATE.faults, outcomes=STATE.outcomes, reports=STATE.reports, exit=int(exitstatus))
            write(STATE.directory / "meta.json", meta)
            if STATE.worker != "controller":
                session.config.workeroutput["native_gate"] = dict(worker=STATE.worker, pid=os.getpid(), meta_sha256=sha(STATE.directory / "meta.json"))
            else:
                write(STATE.directory / "workers.json", STATE.nodes)
        except BaseException:
            session.exitstatus = 1


def audit_report(report, node, worker, pid):
    exact(report, {"node", "worker", "pid", "events", "faults", "restored", "settled", "calls", "forwarded"})
    require(report["node"] == node and report["worker"] == worker and integer(report["pid"]) and report["pid"] == pid, "capture_binding")
    require(report["faults"] == [] and report["restored"] is True and report["settled"] is True, "capture_fault")
    for field in ("calls", "forwarded"):
        require(type(report[field]) is list and len(report[field]) == 3 and all(integer(v) and v <= 8192 for v in report[field]), "forward_shape")
    require(report["calls"] == report["forwarded"], "forward_count")
    events = report["events"]
    require(type(events) is list and 1 <= len(events) <= 4096, "event_bound")
    entries, returns, releases, ends, http = {}, {}, {}, {}, {}
    required = {"sequence", "kind", "tid", "wall_ns", "cpu_ns", "request"}
    for index, event in enumerate(events):
        require(type(event) is dict and event.get("kind") in KINDS, "event_kind")
        kind = event["kind"]
        extra = {"token", "operation", "args", "kwargs"} if kind == "acquire_entry" else {"token", "operation", "result"} if kind == "acquire_return" else {"token", "operation"} if kind == "acquire_error" else {"token"} if kind.startswith("release_") else {"status"} if kind == "http_return" else set()
        exact(event, required | extra)
        require(integer(event["sequence"]) and event["sequence"] == index and all(integer(event[k]) for k in ("tid", "wall_ns", "cpu_ns")), "event_number")
        request = event["request"]
        require(request is None or (type(request) is list and len(request) == 2 and all(integer(v) and v > 0 for v in request) and request[1] <= 16), "request_shape")
        if kind.startswith("acquire_"):
            require(integer(event["token"]) and event["token"] > 0 and event["operation"] in OPERATIONS, "acquire_shape")
        if kind == "acquire_entry":
            require(event["token"] not in entries and event["args"] == [] and type(event["kwargs"]) is dict and set(event["kwargs"]) == {"timeout"}, "acquire_arguments")
            timeout = event["kwargs"]["timeout"]
            require(type(timeout) in (int, float) and 0 <= timeout <= .45, "native_timeout")
            entries[event["token"]] = event
        elif kind == "acquire_return":
            require(type(event["result"]) is bool and event["token"] not in returns, "acquire_result")
            returns[event["token"]] = event
        elif kind in {"release_entry", "release_return"}:
            require(integer(event["token"]) and event["token"] > 0, "release_token")
            table = releases if kind == "release_entry" else ends
            require(event["token"] not in table, "release_duplicate")
            table[event["token"]] = event
        elif kind == "http_entry":
            require(request is not None and request[0] == event["tid"] and tuple(request) not in http, "http_identity")
            http[tuple(request)] = [event]
        elif kind == "http_return":
            require(request is not None and tuple(request) in http and len(http[tuple(request)]) == 1 and type(event["status"]) is int and 100 <= event["status"] <= 599, "http_result")
            http[tuple(request)].append(event)
        elif kind.endswith("error"):
            raise Rejected("operational_error_capture")
    require(events[-1]["kind"] == "call_end" and sum(e["kind"] == "call_end" for e in events) == 1, "call_boundary")
    require(set(entries) == set(returns), "acquire_pair")
    successes = {token for token, event in returns.items() if event["result"]}
    require(set(releases) == successes == set(ends), "release_pair")
    require(len(entries) <= report["calls"][0] and len(releases) <= report["calls"][1], "call_phase_count")
    for token, entry in entries.items():
        result = returns[token]
        require(entry["sequence"] < result["sequence"] and entry["tid"] == result["tid"] and entry["request"] == result["request"] and entry["operation"] == result["operation"], "token_identity")
        if token in successes:
            require(result["sequence"] < releases[token]["sequence"] < ends[token]["sequence"] and entry["tid"] == releases[token]["tid"] == ends[token]["tid"], "release_identity")
        if entry["request"] is not None:
            span = http.get(tuple(entry["request"]))
            require(span is not None and len(span) == 2 and span[0]["tid"] != entry["tid"] and span[0]["sequence"] < entry["sequence"] < result["sequence"] < span[1]["sequence"], "http_context")
    for span in http.values():
        require(len(span) == 2 and span[0]["tid"] == span[1]["tid"], "http_pair")
    refusals = []
    for token, refusal in returns.items():
        if refusal["result"]:
            continue
        entry = entries[token]
        holders = [owner for key, owner in returns.items() if key in successes and owner["tid"] != refusal["tid"] and owner["wall_ns"] <= entry["wall_ns"] <= refusal["wall_ns"] <= releases[key]["wall_ns"]]
        response = http.get(tuple(refusal["request"])) if refusal["request"] is not None else None
        if len(holders) == 1 and holders[0]["operation"] != "unknown" and response and response[1]["status"] == 503:
            owner = holders[0]
            refusals.append(dict(node=node, worker=worker, pid=pid, refusing_token=token, request=refusal["request"], refusing_tid=refusal["tid"], owner_token=owner["token"], owner_tid=owner["tid"], operation=owner["operation"], owner_return_ns=owner["wall_ns"], release_entry_ns=releases[owner["token"]]["wall_ns"]))
    if node == WAIT:
        require(len(successes) == 2 and not refusals, "wait_control")
        first, second = sorted((returns[token] for token in successes), key=lambda v: v["sequence"])
        require(first["tid"] != second["tid"] and entries[second["token"]]["sequence"] < releases[first["token"]]["sequence"] < second["sequence"], "native_handoff")
    if node == BUSY:
        require(len(refusals) == 1, "held_control_refusal")
        refusal = refusals[0]
        released = ends[refusal["owner_token"]]
        require(any(event["result"] and event["request"] is not None and event["request"][0] == refusal["request"][0] and event["request"][1] > refusal["request"][1] and event["wall_ns"] > released["wall_ns"] and http[tuple(event["request"])][1]["status"] == 200 for event in returns.values()), "held_control_recovery")
    if node == SUBJECT:
        callers = {request[0] for request in http}
        initial = [span[0] for request, span in http.items() if request[1] == 1]
        require(len(callers) == 3 and len(initial) == 3 and max(e["wall_ns"] for e in initial) < min(span[1]["wall_ns"] for span in http.values()), "three_concurrent_callers")
    return refusals


def check_identity(value, expected):
    require(value == expected, "identity_mismatch")


def stage_audit(stage, directory, expected_identity, controller_pid):
    controller_path = directory / "controller" / str(controller_pid) / "meta.json"
    controller = load(controller_path)
    metadata_fields = {"worker", "pid", "identity", "early_origins", "origins", "registered", "faults", "outcomes", "reports", "exit"}
    exact(controller, metadata_fields)
    check_identity(controller["identity"], expected_identity)
    origin_counts(controller["early_origins"])
    origin_counts(controller["origins"])
    require(controller["worker"] == "controller" and controller["pid"] == controller_pid and controller["faults"] == [] and controller["registered"] is True, "controller_state")
    workers = load(controller_path.with_name("workers.json"))
    exact(workers, {"gw0", "gw1", "gw2", "gw3"})
    captures, outcomes, metadata, correlated = {}, {}, [], []
    for worker, manifest in workers.items():
        exact(manifest, {"worker", "pid", "meta_sha256"})
        require(manifest["worker"] == worker and integer(manifest["pid"]) and manifest["pid"] > 0 and sha_text(manifest["meta_sha256"]), "worker_manifest")
        location = directory / worker / str(manifest["pid"])
        children = iter((directory / worker).iterdir())
        require(next(children).name == str(manifest["pid"]) and next(children, None) is None, "worker_replacement")
        path = location / "meta.json"
        require(sha(path) == manifest["meta_sha256"], "worker_meta_hash")
        meta = load(path)
        exact(meta, metadata_fields)
        require(meta["worker"] == worker and meta["pid"] == manifest["pid"] and meta["registered"] is True and meta["faults"] == [], "worker_meta")
        origin_counts(meta["origins"])
        origin_counts(meta["early_origins"])
        require(type(meta["exit"]) is int and meta["exit"] in ({0} if stage == "controls" else {0, 1}), "worker_exit")
        check_identity(meta["identity"], expected_identity)
        require(type(meta["outcomes"]) is dict and set(meta["outcomes"]) <= set(NODES[stage]) and type(meta["reports"]) is list and len(meta["reports"]) <= len(NODES[stage]), "worker_coverage")
        for node, phases in meta["outcomes"].items():
            require(node not in outcomes, "node_duplicate")
            exact(phases, {"setup", "call", "teardown"})
            require(all(value in {"passed", "failed", "skipped"} for value in phases.values()), "outcome_enum")
            outcomes[node] = phases
        for report in meta["reports"]:
            exact(report, {"node", "file", "sha256"})
            node = report["node"]
            require(node in NODES[stage] and node not in captures and report["file"] == hashlib.sha256(node.encode()).hexdigest() + ".json" and sha_text(report["sha256"]), "node_manifest")
            path = location / report["file"]
            require(sha(path) == report["sha256"], "capture_hash")
            capture = load(path)
            correlated.extend(audit_report(capture, node, worker, manifest["pid"]))
            captures[node] = capture
        metadata.append(dict(worker=worker, pid=meta["pid"], early_origins=meta["early_origins"], origins=meta["origins"], registered=True, metadata_sha256=manifest["meta_sha256"]))
    require(set(outcomes) == set(captures) == set(NODES[stage]), "stage_coverage")
    require(all(phases["setup"] == phases["teardown"] == "passed" for phases in outcomes.values()), "lifecycle_failure")
    if stage == "controls":
        require(controller["exit"] == 0 and all(p["call"] == "passed" for p in outcomes.values()), "control_failure")
    require(type(controller["exit"]) is int and controller["exit"] in {0, 1}, "pytest_exit")
    return dict(stage=stage, workers=metadata, captures=list(captures.values()), outcomes=outcomes, correlated=correlated, pytest_exit=controller["exit"])


def owned_group(command, cwd, environment, stdout, stderr, soft_seconds):
    require(sys.platform == "linux" and signal.getsignal(signal.SIGCHLD) == signal.SIG_DFL, "owned_wait_prerequisite")
    started = time.monotonic()
    soft, hard = started + soft_seconds, started + soft_seconds + 5
    with stdout.open("wb") as out, stderr.open("wb") as err:
        child = subprocess.Popen(command, cwd=cwd, env=environment, stdout=out, stderr=err, start_new_session=True)
        timed_out = False
        try:
            while os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None:
                now = time.monotonic()
                if now >= hard:
                    break
                if now >= soft and not timed_out:
                    timed_out = True
                    os.killpg(child.pid, signal.SIGTERM)
                time.sleep(min(.05, max(0, hard - time.monotonic())))
        finally:
            # WNOWAIT retains the leader PID. Never reap it before this final group signal:
            # leader exit must not suppress KILL or permit an unrelated reused group ID.
            os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            code = child.wait(timeout=max(0, hard - time.monotonic()))
        except subprocess.TimeoutExpired:
            raise Rejected("owned_group_exit_unconfirmed") from None
        require(not timed_out and time.monotonic() <= hard, "owned_group_timeout")
        return code, child.pid


def clean_child_environment(home, temporary):
    result = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "TZ", "LD_LIBRARY_PATH", "SSL_CERT_FILE", "SSL_CERT_DIR") if key in os.environ}
    result.update(HOME=str(home), USERPROFILE=str(home), TMPDIR=str(temporary), TMP=str(temporary), TEMP=str(temporary), PYTHONDONTWRITEBYTECODE="1", GITHUB_ACTIONS="true")
    result["ImageVersion"] = os.environ.get("ImageVersion", "unknown")
    if "GATE_ENV_ROOT" in os.environ:
        result["GATE_ENV_ROOT"] = os.environ["GATE_ENV_ROOT"]
    return result


def run_stage(stage, root, out, pinfile, module, expected):
    directory = out / "private" / stage
    directory.mkdir(parents=True, exist_ok=False)
    home, temporary = directory / "home", directory / "temp"
    home.mkdir()
    temporary.mkdir()
    require(not directory.resolve().is_relative_to(root), "scratch_source_overlap")
    for parent in (directory, *directory.parents):
        require(not parent.is_symlink() and not (parent / ".git").exists(), "scratch_ancestry")
    before = source_inputs(root)
    environment = clean_child_environment(home, temporary)
    environment.update(PYTHONPATH=str(module.parent) + os.pathsep + str(root), GATE_OUT=str(directory), GATE_STAGE=stage, GATE_CONSTRAINTS=str(pinfile))
    xml = directory / "result.private.xml"
    command = [sys.executable, "-B", "-m", "pytest", "-p", "gate_capture", *NODES[stage], "-q", "-n", "4", "--max-worker-restart=0", "-x", "--basetemp=" + str(directory / "tmp"), "-o", "cache_dir=" + str(directory / "cache"), "--junitxml=" + str(xml)]
    code, controller_pid = owned_group(command, root, environment, directory / "stdout.private", directory / "stderr.private", 55)
    after = source_inputs(root)
    require(before == after and identity(root, pinfile) == expected, "stage_input_drift")
    result = stage_audit(stage, directory, expected, controller_pid)
    require(code == result["pytest_exit"], "process_exit_binding")
    require(xml.stat().st_size <= LIMIT and not xml.is_symlink(), "junit_bound")
    cases = ET.parse(xml).getroot().findall(".//testcase")
    require(len(cases) == len(NODES[stage]), "junit_coverage")
    expected_names = {node.split("::")[-1] for node in NODES[stage]}
    require({case.attrib.get("name") for case in cases} == expected_names, "junit_identity")
    for node in NODES[stage]:
        parts = node.split("::")
        classname = parts[0].removesuffix(".py").replace("/", ".") + ("." + parts[1] if len(parts) == 3 else "")
        case = next(case for case in cases if case.attrib.get("name") == parts[-1])
        require(case.attrib.get("classname") == classname and not case.findall("error") and not case.findall("skipped"), "junit_lifecycle")
        require(len(case.findall("failure")) == (1 if result["outcomes"][node]["call"] == "failed" else 0), "junit_outcome")
    original_failure = stage == "subject" and code == 1 and any("assert errors == []" in (failure.text or "") and "relay_busy" in (failure.text or "") for case in cases for failure in case.findall("failure"))
    result.update(source_before=before, source_after=after, identity=expected, raw_hashes={name: sha(directory / name) for name in ("stdout.private", "stderr.private", "result.private.xml")})
    result["disposition"] = "controls_passed" if stage == "controls" else "observed_refusal_correlated" if original_failure and result["correlated"] else "inconclusive_nonreproduction" if code == 0 else "inconclusive_different_failure"
    return result


def install_environment(source, environment, pinfile):
    require(not environment.exists(), "environment_exists")
    subprocess.run([sys.executable, "-B", "-m", "venv", str(environment)], check=True)
    subprocess.run([str(environment / "bin/python"), "-B", "-m", "pip", "install", "--retries", "0", "--resume-retries", "0", "--timeout", "30", "--no-cache-dir", "-c", str(pinfile), "-e", str(source) + "[dev,vector,mcp]"], check=True)
    return 0


def setup(source, environment, pinfile, scratch):
    source, environment, pinfile, scratch = source.resolve(), environment.absolute(), pinfile.resolve(), scratch.absolute()
    require(not scratch.exists() and not environment.exists() and not scratch.is_relative_to(source) and not environment.is_relative_to(source), "setup_destination")
    for path in (scratch, environment):
        require(all(not parent.is_symlink() for parent in (path, *path.parents)), "setup_symlink")
    scratch.mkdir(parents=True)
    home, temporary = scratch / "home", scratch / "temp"
    home.mkdir()
    temporary.mkdir()
    child_environment = clean_child_environment(home, temporary)
    child_environment.update(PIP_RETRIES="0", PIP_RESUME_RETRIES="0", PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_NO_INPUT="1")
    command = [sys.executable, "-I", "-S", "-B", str(Path(__file__).resolve()), "install", "--source", str(source), "--environment", str(environment), "--constraints", str(pinfile)]
    code, _pid = owned_group(command, source, child_environment, scratch / "stdout.private", scratch / "stderr.private", 175)
    require(code == 0, "setup_failed_no_retry")
    print('{"setup":"completed","runtime_qualification_claim":false}')
    return 0


def job(root, out, pinfile):
    for parent in (out, *out.parents):
        require(not parent.is_symlink(), "job_symlink")
    root, out, pinfile = root.resolve(), out.resolve(), pinfile.resolve()
    require(not out.exists() and not out.is_relative_to(root) and sys.platform == "linux", "job_destination")
    out.mkdir(parents=True)
    sys.path.insert(0, str(root))
    public = out / "public"
    phase = "preflight"
    try:
        expected = identity(root, pinfile)
        phase = "controls"
        controls = run_stage("controls", root, out, pinfile, Path(__file__).resolve(), expected)
        require(controls["disposition"] == "controls_passed", "controls_gate")
        phase = "subject"
        subject = run_stage("subject", root, out, pinfile, Path(__file__).resolve(), expected)
        phase = "export"
        payload = dict(schema=1, runtime_unvalidated_before_job=True, controls=controls, subject=subject, historical_equivalence=False, overall_acceptance=False)
        encoded = json.dumps(payload, allow_nan=False, sort_keys=True).encode()
        require(len(encoded) <= LIMIT, "aggregate_export_bound")
        public.mkdir()
        write(public / "evidence.json", payload)
        ready = True
        status = subject["pytest_exit"]
    except BaseException:
        # No raw exception, stdout, JUnit, worker error or partial capture is exported.
        ready, status = False, 1
        if not public.exists():
            public.mkdir()
            write(public / "evidence.json", dict(schema=1, complete_evidence=False, failure_phase=phase, disposition="inconclusive_failed_closed", subject_authorized_by_controls=phase in {"subject", "export"}, historical_equivalence=False, overall_acceptance=False))
            ready = True
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as stream:
            stream.write("safe_upload=" + ("true" if ready else "false") + "\n")
    print(json.dumps(dict(safe_upload=ready, exit=status, runtime_qualification_claim=False)))
    return status


def api_child(method, path, body):
    prefix = "/repos/" + REPO
    allowed_get = path == prefix + "/git/ref/heads/" + REF or path == prefix + "/actions/workflows/ci.yml/runs?event=workflow_dispatch&branch=" + REF + "&per_page=20" or re.fullmatch(re.escape(prefix) + r"/actions/runs/[1-9][0-9]{0,17}", path)
    allowed_post = path == prefix + "/actions/workflows/ci.yml/dispatches" or re.fullmatch(re.escape(prefix) + r"/actions/runs/[1-9][0-9]{0,17}/cancel", path)
    require((method == "GET" and allowed_get) or (method == "POST" and allowed_post), "api_target")
    token = os.environ.get("GH_TOKEN", "")
    require(re.fullmatch(r"[A-Za-z0-9_]{20,512}", token) is not None and len(body.encode()) <= 4096, "api_input")

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise Rejected("api_redirect")

    request = urllib.request.Request("https://api.github.com" + path, data=body.encode() if method == "POST" else None, method=method, headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"})
    with urllib.request.build_opener(NoRedirect).open(request, timeout=8) as response:
        payload = response.read(1024 * 1024 + 1)
        require(len(payload) <= 1024 * 1024, "api_response_bound")
        value = json.loads(payload) if payload else {}
    if method == "POST":
        result = dict(accepted=True)
    elif "/git/ref/" in path:
        result = dict(sha=value["object"]["sha"])
    else:
        fields = ("id", "head_sha", "head_branch", "display_title", "event", "path", "status", "conclusion", "run_attempt")
        items = value.get("workflow_runs", []) if "/workflows/" in path else [value]
        require(type(items) is list and len(items) <= 20, "api_run_bound")
        result = dict(runs=[{key: item.get(key) for key in fields} for item in items])
    encoded = json.dumps(result, allow_nan=False)
    require(len(encoded.encode()) <= 128 * 1024, "api_result_bound")
    print(encoded)
    return 0


def request_child(method, path, body, token, deadline):
    remaining = deadline - time.monotonic()
    require(remaining > 0, "owner_budget")
    # This child alone receives the credential; no token-bearing pytest environment.
    environment = {"GH_TOKEN": token}
    result = subprocess.run([sys.executable, "-I", "-S", "-B", str(Path(__file__).resolve()), "api", method, path, json.dumps(body, separators=(",", ":"))], env=environment, capture_output=True, timeout=min(10, remaining))
    require(result.returncode == 0 and len(result.stdout) <= 128 * 1024, "api_request_failed")
    return json.loads(result.stdout)


def bound_run(value, definition, ticket):
    fields = {"id", "head_sha", "head_branch", "display_title", "event", "path", "status", "conclusion", "run_attempt"}
    exact(value, fields)
    require(integer(value["id"]) and value["id"] > 0 and value["head_sha"] == definition and value["head_branch"] == REF and value["display_title"] == "Native gate " + ticket and value["event"] == "workflow_dispatch" and value["path"] == WORKFLOW and value["run_attempt"] == 1, "owned_run_identity")
    require(value["status"] in {"queued", "in_progress", "completed", "waiting", "pending", "requested"} and value["conclusion"] in {None, "success", "failure", "cancelled", "skipped", "timed_out", "action_required", "neutral", "stale", "startup_failure"}, "run_state")
    return value


def owner(definition):
    require(re.fullmatch(r"[0-9a-f]{40}", definition) is not None, "definition_sha")
    token = os.environ.pop("GH_TOKEN", "")
    require(token, "owner_credential")
    started = time.monotonic()
    deadline, normal = started + 720, started + 710
    ticket = uuid.uuid4().hex
    print(json.dumps(dict(definition=definition, ref=REF, ticket=ticket, owner_wall_seconds=720)), flush=True)
    owned, cancel = None, "not_requested"
    dispatch = "not_requested"
    try:
        ref = request_child("GET", "/repos/" + REPO + "/git/ref/heads/" + REF, {}, token, normal)
        require(ref == {"sha": definition}, "definition_ref_drift")
        dispatch = "uncertain"
        request_child("POST", "/repos/" + REPO + "/actions/workflows/ci.yml/dispatches", {"ref": REF, "inputs": {"ticket": ticket}}, token, normal)
        dispatch = "accepted"
        while time.monotonic() < normal:
            if owned is None:
                value = request_child("GET", "/repos/" + REPO + "/actions/workflows/ci.yml/runs?event=workflow_dispatch&branch=" + REF + "&per_page=20", {}, token, normal)
                exact(value, {"runs"})
                candidates = [run for run in value["runs"] if run.get("display_title") == "Native gate " + ticket]
                require(len(candidates) <= 1, "ambiguous_owned_run")
                if candidates:
                    owned = bound_run(candidates[0], definition, ticket)
            else:
                value = request_child("GET", "/repos/" + REPO + "/actions/runs/" + str(owned["id"]), {}, token, normal)
                require(len(value.get("runs", [])) == 1, "owned_run_response")
                current = bound_run(value["runs"][0], definition, ticket)
                require(current["id"] == owned["id"], "owned_run_changed")
                owned = current
            if owned is not None and owned["status"] == "completed":
                print(json.dumps(dict(dispatch=dispatch, run=owned["id"], conclusion=owned["conclusion"], cancel=cancel, overall_acceptance=False)))
                return 0
            time.sleep(min(15, max(0, normal - time.monotonic())))
        if owned is not None:
            cancel = "uncertain"
            request_child("POST", "/repos/" + REPO + "/actions/runs/" + str(owned["id"]) + "/cancel", {}, token, deadline)
            cancel = "requested_completion_unknown"
    except BaseException:
        # A failed dispatch/read/cancel is never retried, and no guessed ID is used.
        pass
    print(json.dumps(dict(dispatch=dispatch, run=owned["id"] if owned else None, cancel=cancel, disposition="inconclusive_owner_stop", remote_termination="unknown", billing="unknown", overall_acceptance=False)))
    return 1


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    job_args = sub.add_parser("job")
    job_args.add_argument("--source", type=Path, required=True)
    job_args.add_argument("--out", type=Path, required=True)
    job_args.add_argument("--constraints", type=Path, required=True)
    for name in ("setup", "install"):
        install_args = sub.add_parser(name)
        install_args.add_argument("--source", type=Path, required=True)
        install_args.add_argument("--environment", type=Path, required=True)
        install_args.add_argument("--constraints", type=Path, required=True)
        if name == "setup":
            install_args.add_argument("--scratch", type=Path, required=True)
    owner_args = sub.add_parser("owner")
    owner_args.add_argument("--definition", required=True)
    api_args = sub.add_parser("api")
    api_args.add_argument("method")
    api_args.add_argument("path")
    api_args.add_argument("body")
    args = parser.parse_args()
    try:
        if args.mode == "job":
            return job(args.source, args.out, args.constraints)
        if args.mode == "setup":
            return setup(args.source, args.environment, args.constraints, args.scratch)
        if args.mode == "install":
            return install_environment(args.source, args.environment, args.constraints)
        if args.mode == "owner":
            return owner(args.definition)
        return api_child(args.method, args.path, args.body)
    except BaseException:
        print('{"disposition":"operation_failed","details_exported":false}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

