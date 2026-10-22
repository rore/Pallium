"""Pure observer/runner safety: no application, database, server or child journey."""
import asyncio
from contextlib import ExitStack
from contextlib import contextmanager
import io
import inspect
import json
import shutil
from types import SimpleNamespace

import pytest
from fastapi.routing import APIRoute

from scripts import relay_targeted_boundary_capture as capture


@pytest.mark.parametrize("failure", [None, ValueError("failure"), asyncio.CancelledError()])
def test_acquire_delegates_once_preserves_borrower_result_and_exception(failure):
    calls, borrower, result = [], object(), object()
    async def original(value):
        calls.append(value)
        if failure is not None:
            raise failure
        return result
    recorder = capture.Recorder()
    token = capture.REQUEST.set(7)
    try:
        if failure is None:
            assert asyncio.run(capture.acquire_observer(original, recorder)(borrower)) is result
        else:
            with pytest.raises(type(failure)) as raised:
                asyncio.run(capture.acquire_observer(original, recorder)(borrower))
            assert raised.value is failure
    finally:
        capture.REQUEST.reset(token)
    assert calls == [borrower]
    assert [event["stage"] for event in recorder.events] == ["acquire_start", "acquire_end"]
    assert {event["request"] for event in recorder.events} == {7}
    assert ("acquire_not_completed" in recorder.reasons) is (failure is not None)


def test_recorder_uncorrelated_caps_and_clock_fault_are_contained(monkeypatch):
    recorder = capture.Recorder()
    recorder.record("asgi_entry")
    assert recorder.events == [] and "uncorrelated" in recorder.reasons
    token = capture.REQUEST.set(1)
    try:
        for _ in range(capture.EVENT_LIMIT + 1):
            recorder.record("asgi_entry")
        assert len(recorder.events) == capture.EVENT_LIMIT
        assert "event_cap" in recorder.reasons
        monkeypatch.setattr(capture, "time", SimpleNamespace(monotonic=lambda: (_ for _ in ()).throw(ValueError())))
        recorder.record("route_entry")
        assert "observer_fault" in recorder.reasons
    finally:
        capture.REQUEST.reset(token)


def fake_client():
    calls = []
    class Limiter:
        async def acquire_on_behalf_of(self, borrower):
            calls.append(borrower)
            return "admitted"
    limiter = Limiter()
    borrower = object()
    async def endpoint():
        return await limiter.acquire_on_behalf_of(borrower)
    route = APIRoute("/relay/turn", endpoint, methods=["POST"])
    async def app(scope, receive, send):
        return await route.dependant.call()
    app.routes = [route]
    client = SimpleNamespace(app=app, _transport=SimpleNamespace(app=app))
    return client, route, limiter, borrower, calls


def test_actual_dependant_callable_and_transport_are_wrapped_and_restored():
    client, route, limiter, borrower, calls = fake_client()
    original_call, original_app = route.dependant.call, client.app
    recorder, stack = capture.Recorder(), ExitStack()
    capture.install(client, recorder, stack, limiter_lookup=lambda _: limiter)
    assert route.endpoint is original_call
    assert route.dependant.call is not original_call
    assert asyncio.run(client._transport.app({"type": "http"}, None, None)) == "admitted"
    assert calls == [borrower]
    assert [event["stage"] for event in recorder.events] == [
        "asgi_entry", "route_entry", "acquire_start", "acquire_end"]
    assert capture.REQUEST.get() is None
    stack.close()
    stack.close()
    assert client._transport.app is original_app
    assert route.dependant.call is original_call
    assert "acquire_on_behalf_of" not in vars(limiter)


def test_partial_install_can_restore_independently(monkeypatch):
    client, route, limiter, _, _ = fake_client()
    original_replace = capture.replace
    def fail_second(stack, owner, name, replacement):
        if owner is route.dependant:
            raise ValueError("partial install")
        return original_replace(stack, owner, name, replacement)
    monkeypatch.setattr(capture, "replace", fail_second)
    stack = ExitStack()
    with pytest.raises(ValueError):
        capture.install(client, capture.Recorder(), stack, limiter_lookup=lambda _: limiter)
    assert "acquire_on_behalf_of" in vars(limiter)
    stack.close()
    assert "acquire_on_behalf_of" not in vars(limiter)
    assert client._transport.app is client.app


@pytest.mark.parametrize("partial", [False, True])
def test_slotted_dependant_restores_saved_value_with_inherited_method_control(monkeypatch, partial):
    client, route, limiter, borrower, calls = fake_client()
    original_call = route.dependant.call
    class SlottedDependant:
        __slots__ = ("call",)
    route.dependant = SlottedDependant()
    route.dependant.call = original_call
    original_replace = capture.replace
    def fail_after_slot(stack, owner, name, replacement):
        if partial and owner is client._transport:
            raise ValueError("partial install after slot mutation")
        return original_replace(stack, owner, name, replacement)
    monkeypatch.setattr(capture, "replace", fail_after_slot)
    stack = ExitStack()
    try:
        if partial:
            with pytest.raises(ValueError, match="partial install"):
                capture.install(client, capture.Recorder(), stack, limiter_lookup=lambda _: limiter)
        else:
            capture.install(client, capture.Recorder(), stack, limiter_lookup=lambda _: limiter)
            assert asyncio.run(client._transport.app({"type": "http"}, None, None)) == "admitted"
            assert calls == [borrower]
        assert route.dependant.call is not original_call
        assert "acquire_on_behalf_of" in vars(limiter)
    finally:
        stack.close()
    assert route.dependant.call is original_call
    assert not hasattr(route.dependant, "__dict__")
    assert "acquire_on_behalf_of" not in vars(limiter)
    assert client._transport.app is client.app


def test_unsupported_descriptor_is_rejected_before_mutation():
    original, replacement = object(), object()
    mutations = []
    class Descriptor:
        def __get__(self, owner, cls):
            return original
        def __set__(self, owner, value):
            mutations.append(value)
    class Owner:
        call = Descriptor()
    owner = Owner()
    with ExitStack() as stack:
        with pytest.raises(ValueError, match="unsupported attribute descriptor"):
            capture.replace(stack, owner, "call", replacement)
    assert owner.call is original and mutations == []


@pytest.mark.parametrize("selected", [False, True])
@pytest.mark.parametrize("failure", [None, ValueError("native error"), asyncio.CancelledError()])
def test_slotted_class_guard_preserves_delegate_and_inherited_restoration(selected, failure):
    calls, result = [], object()
    class BaseLimiter:
        __slots__ = ()
        async def acquire_on_behalf_of(self, borrower):
            calls.append((self, borrower))
            if failure is not None:
                raise failure
            return result
    BaseLimiter.acquire_on_behalf_of.__module__ = "anyio.fake"
    class Limiter(BaseLimiter):
        __slots__ = ()
    limiter, unrelated, borrower = Limiter(), Limiter(), object()
    original = BaseLimiter.acquire_on_behalf_of
    recorder = capture.Recorder()
    token = capture.REQUEST.set(1)
    try:
        with ExitStack() as stack:
            capture.install_acquire(limiter, recorder, stack)
            assert Limiter.acquire_on_behalf_of is not original
            target = limiter if selected else unrelated
            if failure is None:
                assert asyncio.run(target.acquire_on_behalf_of(borrower)) is result
            else:
                with pytest.raises(type(failure)) as raised:
                    asyncio.run(target.acquire_on_behalf_of(borrower))
                assert raised.value is failure
            assert calls == [(target, borrower)]
            assert len(recorder.events) == (2 if selected else 0)
    finally:
        capture.REQUEST.reset(token)
    assert "acquire_on_behalf_of" not in vars(Limiter)
    assert Limiter.acquire_on_behalf_of is original


@pytest.mark.parametrize("conflict", [False, True])
def test_slotted_class_partial_restore_and_foreign_replacement_conflict(conflict):
    class Limiter:
        __slots__ = ()
        async def acquire_on_behalf_of(self, borrower):
            pass
    Limiter.acquire_on_behalf_of.__module__ = "anyio.fake"
    original = Limiter.acquire_on_behalf_of
    limiter, stack = Limiter(), ExitStack()
    try:
        capture.install_acquire(limiter, capture.Recorder(), stack)
        if conflict:
            async def foreign(self, borrower):
                pass
            Limiter.acquire_on_behalf_of = foreign
            with pytest.raises(RuntimeError, match="restoration conflict"):
                stack.close()
            assert Limiter.acquire_on_behalf_of is foreign
        else:
            with pytest.raises(ValueError, match="partial setup"):
                with stack:
                    raise ValueError("partial setup")
            assert Limiter.acquire_on_behalf_of is original
    finally:
        stack.close()
        Limiter.acquire_on_behalf_of = original


def test_real_selected_and_unrelated_anyio_limiters_preserve_native_contract():
    import anyio
    limiter, unrelated = anyio.CapacityLimiter(1), anyio.CapacityLimiter(1)
    original_static = inspect.getattr_static(limiter, "acquire_on_behalf_of")
    original_class = type(limiter).acquire_on_behalf_of
    recorder = capture.Recorder()
    async def journey():
        borrower, other_borrower = object(), object()
        token = capture.REQUEST.set(1)
        try:
            assert await limiter.acquire_on_behalf_of(borrower) is None
            assert limiter.statistics().borrowers == (borrower,)
            assert len(recorder.events) == 2
            assert await unrelated.acquire_on_behalf_of(other_borrower) is None
            assert unrelated.statistics().borrowers == (other_borrower,)
            assert len(recorder.events) == 2
            with pytest.raises(RuntimeError):
                await limiter.acquire_on_behalf_of(borrower)
            started = asyncio.Event()
            async def blocked():
                started.set()
                await limiter.acquire_on_behalf_of(object())
            task = asyncio.create_task(blocked())
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert len(recorder.events) == 6
            assert limiter.statistics().borrowers == (borrower,)
            assert "acquire_not_completed" in recorder.reasons
        finally:
            if borrower in limiter.statistics().borrowers:
                limiter.release_on_behalf_of(borrower)
            if other_borrower in unrelated.statistics().borrowers:
                unrelated.release_on_behalf_of(other_borrower)
            capture.REQUEST.reset(token)
    with ExitStack() as stack:
        capture.install_acquire(limiter, recorder, stack)
        asyncio.run(journey())
    assert inspect.getattr_static(limiter, "acquire_on_behalf_of") is original_static
    assert type(limiter).acquire_on_behalf_of is original_class
    assert limiter.borrowed_tokens == unrelated.borrowed_tokens == 0


def test_native_teardown_precedes_restoration_and_write(tmp_path, monkeypatch):
    order = []
    stack = ExitStack()
    stack.callback(lambda: order.append("restore"))
    recorder = capture.Recorder()
    item = SimpleNamespace(_boundary_capture=(recorder, stack, tmp_path))
    monkeypatch.setenv(capture.OUTPUT_ENV, str(tmp_path))
    def observed(*args):
        order.append("write")
        return {"complete": False}
    monkeypatch.setattr(capture, "observation", observed)
    hook = capture.pytest_runtest_teardown(item, None)
    next(hook)
    order.append("native_teardown")
    with pytest.raises(StopIteration):
        next(hook)
    assert order == ["native_teardown", "restore", "write"]


def test_non_target_fixture_does_not_resolve_client(monkeypatch):
    def forbidden(*args):
        raise AssertionError("must not request fixture")
    request = SimpleNamespace(node=SimpleNamespace(nodeid="unrelated"), getfixturevalue=forbidden)
    monkeypatch.setenv(capture.OUTPUT_ENV, "unused")
    capture._target_capture.__wrapped__(request)


def test_native_sanitization_retains_only_allowed_scalars(tmp_path):
    path = tmp_path / "stages.json"
    path.write_text(json.dumps([
        {"stage": "forward", "path": "/relay/turn", "entered": 1, "returned": 6,
         "error": {"secret": "payload"}, "delivery_id": "private"},
        {"stage": "worker", "submitted": 4, "entered": 4.1, "returned": 5},
        {"stage": "durable_turn", "entered": 4.2, "returned": 4.5},
    ]))
    recorder = capture.Recorder()
    recorder.events = [{"stage": stage, "request": 2, "time": index + 2}
                       for index, stage in enumerate(["asgi_entry", "route_entry", "acquire_start", "acquire_end"])]
    result = capture.observation(recorder, path)
    assert result["complete"]
    encoded = json.dumps(result)
    assert "private" not in encoded and "secret" not in encoded and "payload" not in encoded
    assert len(encoded.encode()) <= capture.JSON_LIMIT
    recorder.events.pop()
    assert not capture.observation(recorder, path)["complete"]


def test_closure_provenance_is_exact():
    value = object()
    def relay_turn():
        return value
    relay_turn.__module__ = "api.routes"
    assert capture.closure(relay_turn, "value", "api.routes", "relay_turn") is value
    with pytest.raises(ValueError):
        capture.closure(relay_turn, "value", "app.main", "relay_turn")
    with pytest.raises(KeyError):
        capture.closure(relay_turn, "unknown", "api.routes", "relay_turn")


def test_recover_exact_owned_limiter_chain_with_fake_instances(monkeypatch):
    import anyio
    class FakeLimiter:
        async def acquire_on_behalf_of(self, borrower):
            pass
    FakeLimiter.acquire_on_behalf_of.__module__ = "anyio.fake"
    monkeypatch.setattr(anyio, "CapacityLimiter", FakeLimiter)
    codex_admission_limiter = FakeLimiter()
    async def run_codex_relay_operation():
        return codex_admission_limiter
    run_codex_relay_operation.__module__ = "app.main"
    relay_codex_runner = run_codex_relay_operation
    async def _run_relay_operation():
        return relay_codex_runner
    _run_relay_operation.__module__ = "api.routes"
    async def relay_turn():
        return _run_relay_operation
    relay_turn.__module__ = "api.routes"
    assert capture.recover_limiter(relay_turn) is codex_admission_limiter
    codex_admission_limiter = object()
    with pytest.raises(ValueError):
        capture.recover_limiter(relay_turn)


def test_json_cap_and_observer_fault_do_not_change_delegate_result(monkeypatch):
    recorder = capture.Recorder()
    token = capture.REQUEST.set(1)
    try:
        monkeypatch.setattr(capture, "JSON_LIMIT", 4096)
        recorder.record("asgi_entry")
        assert recorder.events == [] and "json_cap" in recorder.reasons
        monkeypatch.setattr(capture, "time", SimpleNamespace(monotonic=lambda: (_ for _ in ()).throw(ValueError())))
        async def original(borrower):
            return borrower
        borrower = object()
        assert asyncio.run(capture.acquire_observer(original, recorder)(borrower)) is borrower
        assert "observer_fault" in recorder.reasons
    finally:
        capture.REQUEST.reset(token)


class FakeSelector:
    def __init__(self, *, ready=True):
        self.entries = {}
        self.ready = ready

    def register(self, stream, events, name):
        self.entries[stream.fileno()] = SimpleNamespace(fileobj=stream, data=name)

    def unregister(self, stream):
        del self.entries[stream.fileno()]

    def get_map(self):
        return self.entries

    def select(self, timeout):
        return [(entry, None) for entry in self.entries.values()] if self.ready else []

    def close(self):
        pass


def test_exited_root_stream_cap_preserves_native_exit_without_signal(tmp_path, monkeypatch):
    chunks = iter([b"0123456789", b""])
    monkeypatch.setattr(capture, "selectors", SimpleNamespace(DefaultSelector=FakeSelector, EVENT_READ=1))
    monkeypatch.setattr(capture, "os", SimpleNamespace(set_blocking=lambda *args: None, read=lambda *args: next(chunks)))
    signals = []
    monkeypatch.setattr(capture, "terminate_group", lambda process, sig: signals.append((process.pid, sig)))
    process = SimpleNamespace(pid=4321, returncode=9, poll=lambda: 9, wait=lambda timeout: 9)
    stream = SimpleNamespace(fileno=lambda: 42)
    result = capture.collect(process, {"stdout.log": stream}, tmp_path, limit=4)
    assert result["native_exit"] == 9
    assert "output_cap" in result["reasons"]
    assert (tmp_path / "stdout.log").read_bytes() == b"0123"
    assert signals == []


def test_owned_timeout_terminates_then_kills_and_bounds_unsettled_drain(tmp_path, monkeypatch):
    monkeypatch.setattr(capture, "signal", SimpleNamespace(SIGTERM=15, SIGKILL=9))
    monkeypatch.setattr(capture, "selectors", SimpleNamespace(DefaultSelector=lambda: FakeSelector(ready=False), EVENT_READ=1))
    monkeypatch.setattr(capture, "os", SimpleNamespace(set_blocking=lambda *args: None))
    ticks = iter(range(100))
    monkeypatch.setattr(capture, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    signals = []
    monkeypatch.setattr(capture, "terminate_group", lambda process, sig: signals.append(sig))
    process = SimpleNamespace(pid=4321, returncode=None, poll=lambda: None,
                              wait=lambda timeout: (_ for _ in ()).throw(capture.subprocess.TimeoutExpired("fake", timeout)))
    stream = SimpleNamespace(fileno=lambda: 42)
    result = capture.collect(process, {"stdout.log": stream}, tmp_path, wall=1, term=1, drain=1)
    assert signals[:2] == [capture.signal.SIGTERM, capture.signal.SIGKILL]
    assert {"timeout", "drain_incomplete", "owned_process_unsettled"}.issubset(result["reasons"])
    assert result["native_exit"] is None


def test_normal_exit_drains_without_signal_and_closes_fifo_keeper_once(tmp_path, monkeypatch):
    monkeypatch.setattr(capture, "selectors", SimpleNamespace(DefaultSelector=FakeSelector, EVENT_READ=1))
    monkeypatch.setattr(capture, "os", SimpleNamespace(set_blocking=lambda *args: None, read=lambda *args: b""))
    monkeypatch.setattr(capture, "terminate_group", lambda *args: pytest.fail("normal drain must not signal"))
    closed = []
    keeper = SimpleNamespace(close=lambda: closed.append(True))
    process = SimpleNamespace(pid=4321, returncode=1, poll=lambda: 1, wait=lambda timeout: 1)
    result = capture.collect(process, {"native-junit.xml": SimpleNamespace(fileno=lambda: 42)},
                             tmp_path, fifo_writer=keeper)
    assert result["reasons"] == [] and result["native_exit"] == 1
    assert result["owned_settled"] and closed == [True]


def test_exited_root_unresolved_stream_drain_is_incomplete_without_signal(tmp_path, monkeypatch):
    monkeypatch.setattr(capture, "selectors", SimpleNamespace(DefaultSelector=lambda: FakeSelector(ready=False), EVENT_READ=1))
    monkeypatch.setattr(capture, "os", SimpleNamespace(set_blocking=lambda *args: None))
    ticks = iter(range(100))
    monkeypatch.setattr(capture, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    monkeypatch.setattr(capture, "terminate_group", lambda *args: pytest.fail("reaped root must not signal"))
    process = SimpleNamespace(pid=4321, returncode=7, poll=lambda: 7)
    result = capture.collect(process, {"stdout.log": SimpleNamespace(fileno=lambda: 42)}, tmp_path, drain=1)
    assert result["native_exit"] == 7 and not result["owned_settled"]
    assert {"descendant_stream_drain", "drain_incomplete"}.issubset(result["reasons"])


def fake_owned_run(tmp_path, monkeypatch, *, failure, process, launches=None, harness_only=False):
    private = tmp_path / "private"
    private.mkdir()
    @contextmanager
    def temporary(**kwargs):
        if launches is not None:
            launches.append(("temporary", kwargs))
        try:
            yield str(private)
        finally:
            if failure != "root_left_behind":
                shutil.rmtree(private)
    monkeypatch.setattr(capture, "tempfile", SimpleNamespace(TemporaryDirectory=temporary))
    monkeypatch.setattr(capture, "sys", SimpleNamespace(platform="linux", version_info=(3, 12),
                                                       executable="fake-python", version="fake"))
    monkeypatch.setattr(capture, "importlib", SimpleNamespace(metadata=SimpleNamespace(distributions=lambda: [])))
    monkeypatch.setattr(capture, "signal", SimpleNamespace(SIGTERM=15, SIGKILL=9))
    monkeypatch.setattr(capture, "os", SimpleNamespace(environ={capture.OUTPUT_ENV: "inherited-output"}, mkfifo=lambda *args: None,
        open=lambda *args: 42, fdopen=lambda *args, **kwargs: io.BytesIO(),
        O_RDONLY=1, O_WRONLY=2, O_NONBLOCK=4))
    def popen(command, **kwargs):
        if launches is not None:
            launches.append(("launch", command, kwargs))
        return process
    monkeypatch.setattr(capture, "subprocess", SimpleNamespace(Popen=popen,
        TimeoutExpired=capture.subprocess.TimeoutExpired, PIPE=-1))
    calls = []
    before = {"git_status": " M dirty" if failure == "dirty" else "", "baseline_ok": True}
    def fence():
        calls.append(True)
        if len(calls) == 2 and failure == "fence":
            raise ValueError("post-success fence")
        if len(calls) == 2 and failure == "mutation":
            return {**before, "git_status": " M scripts/relay_targeted_boundary_capture.py"}
        return before
    monkeypatch.setattr(capture, "fences", fence)
    def collect(process, streams, output, **kwargs):
        if launches is not None:
            launches.append(("collect", kwargs))
        if failure == "collection":
            raise OSError("partial collection")
        (output / "observation.json").write_text('{"complete": true}')
        if harness_only:
            suite = capture.ET.Element("testsuite", tests="38", errors="0", failures="0", skipped="0")
            for module, names in capture.HARNESS_INVENTORY.items():
                for name in names:
                    capture.ET.SubElement(suite, "testcase", classname=module, name=name)
            cases = list(suite)
            if failure == "xml_duplicate":
                cases[-1].attrib.update(cases[0].attrib)
            if failure == "xml_wrong":
                cases[0].set("name", "unexpected_test")
            if failure == "xml_missing_case":
                suite.remove(cases[0])
                suite.set("tests", "37")
            if failure == "xml_declared":
                suite.set("tests", "37")
            if failure in {"failure", "error", "skipped"}:
                capture.ET.SubElement(cases[0], failure)
                suite.set({"failure": "failures", "error": "errors", "skipped": "skipped"}[failure], "1")
            report = capture.ET.Element("testsuites")
            report.append(suite)
            if failure != "xml_missing":
                capture.ET.ElementTree(report).write(output / "native-junit.xml")
            receipt = {"installed": True, "restored": True, "observation_complete": True,
                       "socket": {"bound_closed_removed": True, "native_path_bytes": 99,
                                  "modeled_linux_path_bytes": 100}}
            if failure == "receipt_invalid":
                receipt["installed"] = 1
            if failure == "socket_missing":
                receipt.pop("socket")
            if failure == "socket_unbound":
                receipt["socket"]["bound_closed_removed"] = False
            for scenario, key, value in [("native_overmax", "native_path_bytes", 101),
                                         ("modeled_overmax", "modeled_linux_path_bytes", 101),
                                         ("native_zero", "native_path_bytes", 0),
                                         ("modeled_negative", "modeled_linux_path_bytes", -1),
                                         ("native_boolean", "native_path_bytes", True)]:
                if failure == scenario:
                    receipt["socket"][key] = value
            if failure != "receipt_missing":
                (output / "fixture.json").write_text(json.dumps(receipt))
        elif failure != "stat":
            (output / "native-junit.xml").write_text("native")
        return {"native_exit": process.returncode, "reasons": [], "owned_settled": failure != "owned_unsettled"}
    monkeypatch.setattr(capture, "collect", collect)
    output = tmp_path / "output"
    expected = 0 if harness_only and failure is None and process.returncode == 0 else 1
    assert capture.run(output, harness_only=harness_only) == expected
    return json.loads((output / "runner.json").read_text())


def test_owned_run_passes_short_private_basetemp_to_actual_launch_command(tmp_path, monkeypatch):
    launches = []
    process = SimpleNamespace(pid=4321, returncode=7, poll=lambda: 7,
                              stdout=io.BytesIO(), stderr=io.BytesIO())
    result = fake_owned_run(tmp_path, monkeypatch, failure=None, process=process, launches=launches)
    assert launches[0] == ("temporary", {"prefix": "p"})
    _, command, options = launches[1]
    base, = [arg.split("=", 1)[1] for arg in command if arg.startswith("--basetemp=")]
    assert capture.Path(base) == tmp_path / "private" / "p"
    assert f"--basetemp={base}" in result["command"]
    assert command[command.index("tests/"):command.index("tests/") + 3] == ["tests/", "-x", "-q"]
    assert capture.Path(options["env"]["TMPDIR"]).parent == capture.Path(base).parent
    assert options["start_new_session"] is True
    assert launches[2][1]["wall"] == 1200
    assert result["mode"] == "full" and result["private_root_removed"]
    scenarios = [None, "xml_missing", "xml_duplicate", "xml_wrong", "xml_missing_case", "xml_declared",
                 "failure", "error", "skipped", "receipt_missing", "receipt_invalid", "socket_missing",
                 "socket_unbound", "native_overmax", "modeled_overmax", "native_zero", "modeled_negative",
                 "native_boolean", "root_left_behind", "owned_unsettled", "nonzero"]
    for index, scenario in enumerate(scenarios):
        case = tmp_path / f"harness-{index}"
        case.mkdir()
        launches = []
        exit_code = 7 if scenario == "nonzero" else 0
        process = SimpleNamespace(pid=4321, returncode=exit_code, poll=lambda: exit_code,
                                  stdout=io.BytesIO(), stderr=io.BytesIO())
        result = fake_owned_run(case, monkeypatch, failure=scenario, process=process,
                                launches=launches, harness_only=True)
        assert launches[0] == ("temporary", {"prefix": "p"})
        _, command, options = launches[1]
        assert command[3:5] == ["tests/test_relay_targeted_boundary_capture.py",
                                "tests/test_relay_targeted_boundary_fixture.py"]
        assert command[5:11] == ["-q", "-n", "0", "-o", "addopts=", "--durations=20"]
        assert "tests/" not in command and "-p" not in command
        assert not any("test_agent_relay_hooks" in part for part in command)
        base = case / "private" / "p" / "popen-gw3"
        assert f"--basetemp={base}" in command
        assert capture.OUTPUT_ENV not in options["env"]
        assert options["env"]["PALLIUM_HARNESS_EVIDENCE"] == str(case / "output" / "fixture.json")
        assert launches[2][1]["wall"] == 300
        assert result["mode"] == "harness_only" and result["native_exit"] == exit_code
        assert result["complete"] is (scenario is None)
        assert result["private_root_removed"] is (scenario != "root_left_behind")
        if scenario is None:
            assert result["native_all_normal"] and result["fixture_socket_receipts_valid"]


@pytest.mark.parametrize("failure", ["fence", "stat", "mutation"])
def test_post_success_tooling_failure_or_mutation_preserves_exit_without_signaling(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(capture, "terminate_group", lambda *args: pytest.fail("reaped root must not signal"))
    process = SimpleNamespace(pid=4321, returncode=7, poll=lambda: 7,
                              stdout=io.BytesIO(), stderr=io.BytesIO())
    result = fake_owned_run(tmp_path, monkeypatch, failure=failure, process=process)
    assert result["native_exit"] == 7 and not result["complete"]
    if failure == "mutation":
        assert result["after"]["git_status"]
        assert "source_fence_changed" in result["reasons"]
    else:
        assert any(reason.startswith("tooling_failure:") for reason in result["reasons"])


def test_partial_collection_exception_terminates_and_bounded_waits_owned_exit(tmp_path, monkeypatch):
    signals, waits = [], []
    process = SimpleNamespace(pid=4321, returncode=None, stdout=io.BytesIO(), stderr=io.BytesIO())
    process.poll = lambda: process.returncode
    def wait(timeout):
        waits.append(timeout)
        if timeout == 10:
            raise capture.subprocess.TimeoutExpired("fake", timeout)
        process.returncode = -9
        return -9
    process.wait = wait
    monkeypatch.setattr(capture, "terminate_group", lambda process, sig: signals.append(sig))
    result = fake_owned_run(tmp_path, monkeypatch, failure="collection", process=process)
    assert signals == [15, 9] and waits == [10, 5]
    assert result["native_exit"] == -9 and not result["complete"]
    assert process.stdout.closed and process.stderr.closed


def test_dirty_checkout_blocks_before_child_launch(tmp_path, monkeypatch):
    monkeypatch.setattr(capture, "terminate_group", lambda *args: pytest.fail("no child was launched"))
    result = fake_owned_run(tmp_path, monkeypatch, failure="dirty", process=None)
    assert result["native_exit"] is None and not result["complete"]
    assert result["before"]["git_status"]
    assert result["reasons"] == ["tooling_failure:ValueError"]


def test_fences_hash_all_diagnostic_paths_and_retain_dirty_status(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for name in capture.ALLOWED:
        path = capture.Path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
    capture.Path("product.py").write_text("unchanged")
    monkeypatch.setattr(capture, "subprocess", SimpleNamespace(check_output=lambda *args, **kwargs: b"product.py\0"))
    dirty = []
    def git(*args):
        if args[0] == "status":
            return " M scripts/relay_targeted_boundary_capture.py" if dirty else ""
        if args[0] == "diff":
            return "scripts/relay_targeted_boundary_capture.py"
        return "frozen"
    monkeypatch.setattr(capture, "git", git)
    before = capture.fences()
    assert set(before["diagnostic_sha256"]) == capture.ALLOWED
    capture.Path("scripts/relay_targeted_boundary_capture.py").write_text("changed")
    dirty.append(True)
    after = capture.fences()
    assert before["source_lock_sha256"] == after["source_lock_sha256"]
    assert before["diagnostic_sha256"] != after["diagnostic_sha256"]
    assert not before["git_status"] and after["git_status"] and after["baseline_ok"]
