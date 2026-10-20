"""Verify that Claude Code and Codex common.py stay in sync for work trace features."""
from __future__ import annotations

import json

import pytest
from core import claude_wake as core_claude_wake

import importlib.util
import inspect
import sys
from pathlib import Path


def _load_module(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ROOT = Path(__file__).resolve().parent.parent

cc_common = _load_module(str(ROOT / "integrations" / "claude-code" / "hooks" / "common.py"), "cc_common_parity")
codex_common = _load_module(str(ROOT / "integrations" / "codex" / "hooks" / "common.py"), "codex_common_parity")


@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_atomic_state_reader_keeps_coherent_snapshot_during_replacement(module, tmp_path, monkeypatch):
    monkeypatch.setattr(module, "SESSIONS_DIR", tmp_path)
    before = {"container_ref": "git:例/old", "relay_turn_intent": {"runtime": "codex"}}
    after = {"container_ref": "git:例/new"}
    assert module._write_session_state_locked("session", before)
    with module._open_atomic_state_file(tmp_path / "session.json") as reader:
        assert module._write_session_state_locked("session", after)
        assert json.loads(reader.read()) == before
        assert module._read_session_state("session") == after
    assert reader.closed


@pytest.mark.parametrize("module", (cc_common, codex_common, core_claude_wake))
@pytest.mark.parametrize("phase,code", (("rename", 1), ("rename", 50), ("rename", 87),
                                        ("rename", 5), ("rename", 32), ("open", 5),
                                        ("close", 87), ("close_after_success", 5)))
def test_atomic_state_rename_fallback_is_capability_only_after_close(module, phase, code, tmp_path):
    import builtins
    import ctypes
    from ctypes import wintypes
    from types import FunctionType, SimpleNamespace

    calls = []
    failure = OSError(13, "native operation refused")
    failure.winerror = code
    close_failure = OSError(13, "native close refused")
    close_failure.winerror = 5
    native_code = [code]

    def create(_path, access, sharing, _security, disposition, attributes, _template):
        assert (access, sharing, disposition, attributes) == (0x10000, 7, 3, 0x80 | 0x00200000)
        calls.append("open")
        return ctypes.c_void_p(-1).value if phase == "open" else 123

    def close(handle):
        assert handle == 123
        calls.append("close")
        if phase in {"close", "close_after_success"}:
            native_code[0] = 5
            return False
        return True

    def rename(handle, information_class, _buffer, _length):
        assert (handle, information_class) == (123, 22)
        calls.append("rename")
        return phase == "close_after_success"

    def fallback(source, destination):
        assert calls == ["open", "rename", "close"]
        calls.append("fallback")

    native = SimpleNamespace(**dict(
        vars(ctypes), wintypes=wintypes,
        WinDLL=lambda *_args, **_kwargs: SimpleNamespace(CreateFileW=create, CloseHandle=close, SetFileInformationByHandle=rename),
        get_last_error=lambda: native_code[0],
        WinError=lambda _code: close_failure if phase in {"close", "close_after_success"} and _code == 5 else failure,
    ))
    def isolated_import(name, *args, **kwargs):
        return native if name == "ctypes" else builtins.__import__(name, *args, **kwargs)

    namespace = dict(module._replace_atomic_state_file.__globals__)
    namespace["__builtins__"] = dict(vars(builtins), __import__=isolated_import)
    namespace["os"] = SimpleNamespace(**dict(vars(module.os), name="nt", replace=fallback))
    replace = FunctionType(module._replace_atomic_state_file.__code__, namespace)
    if phase == "rename" and code in {1, 50, 87}:
        replace(tmp_path / "source", tmp_path / "状态-🚀.json")
        assert calls == ["open", "rename", "close", "fallback"]
    else:
        with pytest.raises(OSError) as caught:
            replace(tmp_path / "source", tmp_path / "状态-🚀.json")
        assert caught.value is (close_failure if phase in {"close", "close_after_success"} else failure)
        assert calls == (["open"] if phase == "open" else ["open", "rename", "close"])


@pytest.mark.skipif(sys.platform != "win32", reason="actual Windows information-class refusal")
@pytest.mark.parametrize("module", (cc_common, codex_common, core_claude_wake))
def test_atomic_state_invalid_native_class_preserves_files_before_compatibility_fallback(module, tmp_path):
    import builtins
    import ctypes
    from ctypes import wintypes
    from types import FunctionType, SimpleNamespace

    source, destination = tmp_path / "source.tmp", tmp_path / "状态-🚀.json"
    source.write_text("new", encoding="utf-8")
    destination.write_text("old", encoding="utf-8")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    native_rename = kernel.SetFileInformationByHandle
    native_rename.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    native_rename.restype = wintypes.BOOL
    closed, rejected = [], []
    native_close = kernel.CloseHandle
    native_close.argtypes, native_close.restype = [wintypes.HANDLE], wintypes.BOOL

    def reject_class(handle, _information_class, buffer, length):
        result = native_rename(handle, 0x7fffffff, buffer, length)
        code = ctypes.get_last_error()
        assert not result and code in {1, 50, 87}
        rejected.append(code)
        with module._open_atomic_state_file(source) as reader:
            assert reader.read() == "new"
        assert destination.read_text(encoding="utf-8") == "old"
        ctypes.set_last_error(code)
        return result

    def close(handle):
        result = native_close(handle)
        closed.append(bool(result))
        return result

    def fallback(old, new):
        assert closed == [True] and len(rejected) == 1
        assert source.read_text(encoding="utf-8") == "new"
        assert destination.read_text(encoding="utf-8") == "old"
        module.os.replace(old, new)

    native = SimpleNamespace(**dict(vars(ctypes), WinDLL=lambda *_args, **_kwargs: SimpleNamespace(
        CreateFileW=kernel.CreateFileW, CloseHandle=close, SetFileInformationByHandle=reject_class,
    )))
    def isolated_import(name, *args, **kwargs):
        return native if name == "ctypes" else builtins.__import__(name, *args, **kwargs)

    namespace = dict(module._replace_atomic_state_file.__globals__)
    namespace["__builtins__"] = dict(vars(builtins), __import__=isolated_import)
    namespace["os"] = SimpleNamespace(**dict(vars(module.os), replace=fallback))
    replace = FunctionType(module._replace_atomic_state_file.__code__, namespace)
    replace(source, destination)
    assert destination.read_text(encoding="utf-8") == "new" and not source.exists()


@pytest.mark.parametrize("module", (cc_common, codex_common, core_claude_wake))
@pytest.mark.parametrize("invalid_path", ("source", "destination"))
def test_atomic_state_rename_rejects_nul_before_native_admission(module, invalid_path, tmp_path):
    from contextlib import contextmanager
    from types import FunctionType, SimpleNamespace

    namespace = dict(module._replace_atomic_state_file.__globals__)
    namespace["os"] = SimpleNamespace(**dict(vars(module.os), name="nt"))
    replace = FunctionType(module._replace_atomic_state_file.__code__, namespace)
    source = tmp_path / ("source\0" if invalid_path == "source" else "source")
    destination = tmp_path / ("destination\0" if invalid_path == "destination" else "destination")
    with pytest.raises(ValueError, match="embedded null character"):
        replace(source, destination)
    implementation = module._open_atomic_state_file.__wrapped__
    read_namespace = dict(implementation.__globals__)
    read_namespace["os"] = namespace["os"]
    open_state = contextmanager(FunctionType(implementation.__code__, read_namespace))
    with pytest.raises(ValueError, match="embedded null character"):
        with open_state(source if invalid_path == "source" else destination):
            pytest.fail("invalid filename must not open a reader")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(sys.platform != "win32", reason="Windows readonly destination contract")
@pytest.mark.parametrize("module", (cc_common, codex_common, core_claude_wake))
def test_atomic_state_rename_does_not_bypass_readonly_destination(module, tmp_path):
    import stat

    source, destination = tmp_path / "source.tmp", tmp_path / "destination.json"
    source.write_text("new", encoding="utf-8")
    destination.write_text("old", encoding="utf-8")
    destination.chmod(stat.S_IREAD)
    try:
        with pytest.raises(OSError):
            module._replace_atomic_state_file(source, destination)
        assert source.read_text(encoding="utf-8") == "new"
        assert destination.read_text(encoding="utf-8") == "old"
    finally:
        destination.chmod(stat.S_IWRITE)


@pytest.mark.parametrize("module", (cc_common, codex_common))
@pytest.mark.parametrize("content", (b"not-json", b'"\xff"'))
def test_atomic_state_read_errors_close_reader(module, content, tmp_path, monkeypatch):
    from contextlib import contextmanager

    monkeypatch.setattr(module, "SESSIONS_DIR", tmp_path)
    (tmp_path / "session.json").write_bytes(content)
    original_open, readers = module._open_atomic_state_file, []

    @contextmanager
    def observe(path):
        with original_open(path) as reader:
            readers.append(reader)
            yield reader

    monkeypatch.setattr(module, "_open_atomic_state_file", observe)
    assert module._read_session_state("session") is None
    assert len(readers) == 1 and readers[0].closed
    assert module._read_session_state("missing") is None
    assert len(readers) == 1


@pytest.mark.parametrize("module", (cc_common, codex_common, core_claude_wake))
@pytest.mark.parametrize("failure_phase", ("native_open", "descriptor_transfer", "text_wrapper", "actual_text_wrapper"))
def test_atomic_state_native_failure_closes_only_owned_resource(module, failure_phase, tmp_path):
    import builtins
    import ctypes
    from ctypes import wintypes
    from types import FunctionType, SimpleNamespace
    from contextlib import contextmanager

    closed_handles, closed_descriptors, actual_descriptors = [], [], []
    failure = OSError(13, "injected native boundary failure")

    def create(*_args):
        return ctypes.c_void_p(-1).value if failure_phase == "native_open" else 123

    def close(handle):
        closed_handles.append(handle)
        return True

    def transfer(handle, flags):
        assert handle == 123
        if failure_phase == "descriptor_transfer":
            raise failure
        if failure_phase == "actual_text_wrapper":
            descriptor = module.os.open(tmp_path / "reader", module.os.O_CREAT | module.os.O_RDWR, 0o600)
            actual_descriptors.append(descriptor)
            return descriptor
        return 17

    def wrap(descriptor, mode, *, encoding, closefd):
        assert (mode, encoding, closefd) == ("r", "utf-8", False)
        if failure_phase == "actual_text_wrapper":
            assert descriptor == actual_descriptors[0]
            return module.os.fdopen(descriptor, mode, encoding="invalid-state-reader-codec", closefd=closefd)
        assert descriptor == 17
        raise failure

    def close_descriptor(descriptor):
        closed_descriptors.append(descriptor)
        if failure_phase == "actual_text_wrapper":
            module.os.close(descriptor)

    native = SimpleNamespace(
        WinDLL=lambda *_args, **_kwargs: SimpleNamespace(CreateFileW=create, CloseHandle=close),
        c_void_p=ctypes.c_void_p, get_last_error=lambda: 5, WinError=lambda _code: failure,
        wintypes=wintypes,
    )
    def isolated_import(name, *args, **kwargs):
        if name == "ctypes":
            return native
        if name == "msvcrt":
            return SimpleNamespace(open_osfhandle=transfer)
        return builtins.__import__(name, *args, **kwargs)

    implementation = module._open_atomic_state_file.__wrapped__
    namespace = dict(implementation.__globals__)
    namespace["__builtins__"] = dict(vars(builtins), __import__=isolated_import)
    namespace["os"] = SimpleNamespace(**dict(
        vars(module.os), name="nt", O_BINARY=getattr(module.os, "O_BINARY", 0x8000),
        fdopen=wrap, close=close_descriptor,
    ))
    open_state = contextmanager(FunctionType(implementation.__code__, namespace))
    with pytest.raises((OSError, LookupError)) as caught:
        with open_state(Path("unused.json")):
            pytest.fail("failed native open must not yield a reader")
    if failure_phase == "actual_text_wrapper":
        assert isinstance(caught.value, LookupError)
        with pytest.raises(OSError):
            module.os.fstat(actual_descriptors[0])
    else:
        assert caught.value is failure
    assert closed_handles == ([123] if failure_phase == "descriptor_transfer" else [])
    assert closed_descriptors == (
        actual_descriptors if failure_phase == "actual_text_wrapper"
        else [17] if failure_phase == "text_wrapper" else []
    )


@pytest.mark.parametrize("module", (cc_common, codex_common))
@pytest.mark.parametrize("phase", ("temporary_write", "atomic_replace"))
@pytest.mark.parametrize("mode", ("native_codes", "noninteger_codes", "stderr_failure"))
@pytest.mark.parametrize("writer", ("locked", "update"))
def test_session_state_write_failure_is_sanitized_and_preserves_state(
    module, phase, mode, writer, tmp_path, monkeypatch, capsys,
):
    from types import SimpleNamespace

    canonical = tmp_path / "private-session.json"
    canonical.write_text('{"old":true}', encoding="utf-8")
    failure = PermissionError(13, "private-marker", str(canonical))
    failure.winerror = 267
    if mode == "noninteger_codes":
        failure.errno, failure.winerror = True, "private-marker"

    class StatePath(type(tmp_path)):
        def write_text(self, *args, **kwargs):
            if phase == "temporary_write":
                raise failure
            return super().write_text(*args, **kwargs)

    def replace(*_args, **_kwargs):
        raise failure

    class BrokenStderr:
        def write(self, _text):
            raise OSError("private-marker")

    monkeypatch.setattr(module, "SESSIONS_DIR", StatePath(tmp_path))
    monkeypatch.setattr(module, "_replace_atomic_state_file", replace)
    if mode == "stderr_failure":
        monkeypatch.setattr(module, "sys", SimpleNamespace(**dict(vars(module.sys), stderr=BrokenStderr())))

    if writer == "update":
        assert module.pin_container("private-session", "git:example.test/repo") is False
    else:
        assert module._write_session_state_locked("private-session", {"new": "private-marker"}) is False
    assert canonical.read_text(encoding="utf-8") == '{"old":true}'
    assert list(tmp_path.glob("*.tmp")) == []
    output = capsys.readouterr()
    assert output.out == ""
    if mode == "stderr_failure":
        assert output.err == ""
    else:
        codes = "errno=None winerror=None" if mode == "noninteger_codes" else "errno=13 winerror=267"
        assert output.err == (
            f"pallium hook: session_state_write_failed phase={phase} "
            f"error=PermissionError {codes}\n"
        )
    assert "private-marker" not in output.err
    assert "private-session" not in output.err
    assert str(tmp_path) not in output.err


@pytest.mark.parametrize("module", (cc_common, codex_common))
@pytest.mark.parametrize("phase", ("pre_attempt_deadline", "native_wait_exhausted", "native_prepare", "lock_setup"))
def test_session_lock_failure_reports_actual_boundary_without_changing_wait(
    module, phase, tmp_path, capsys,
):
    import builtins
    from types import FunctionType, SimpleNamespace

    failure = PermissionError(13, "private-marker", str(tmp_path))
    failure.winerror = 32
    values = [0.0] if phase == "lock_setup" else (
        [0.0, 0.11] if phase == "pre_attempt_deadline" else [0.0, 0.01, 0.11, 0.12]
    )
    if phase in {"native_wait_exhausted", "native_prepare"} and module is cc_common:
        values.pop()
    if phase == "lock_setup" and module is codex_common:
        values.clear()
    clock_values, attempts, handles = list(values), [], []

    def clock():
        return clock_values.pop(0)

    def locking(*_args):
        attempts.append("native")
        raise failure

    def open_lock(*args, **kwargs):
        if phase == "lock_setup":
            raise failure
        handle = builtins.open(*args, **kwargs)
        handles.append(handle)
        if phase != "native_prepare":
            return handle

        class PreparedLock:
            def __getattr__(self, name):
                return getattr(handle, name)

            def seek(self, offset, whence=0):
                if whence == 0:
                    raise failure
                return handle.seek(offset, whence)

        return PreparedLock()

    def isolated_import(name, *args, **kwargs):
        if name == "msvcrt":
            return SimpleNamespace(locking=locking, LK_NBLCK=2)
        return builtins.__import__(name, *args, **kwargs)

    implementation = module._acquire_file_lock if module is cc_common else module._acquire_session_lock
    namespace = dict(implementation.__globals__)
    namespace["__builtins__"] = dict(vars(builtins), __import__=isolated_import)
    namespace["open"] = open_lock
    namespace["sys"] = SimpleNamespace(**dict(vars(module.sys), platform="win32"))
    namespace["os"] = SimpleNamespace(**dict(vars(module.os), name="nt"))
    namespace["SESSIONS_DIR"] = tmp_path
    sleeps = []
    namespace["time"] = SimpleNamespace(**dict(
        vars(module.time), monotonic=clock,
        sleep=sleeps.append,
    ))
    acquire = FunctionType(implementation.__code__, namespace)
    result = acquire(tmp_path / "private-session.lock", 0.1) if module is cc_common else acquire("private-session", timeout=0.1, deadline=None)
    assert result is None
    assert not clock_values
    assert attempts == (["native"] if phase == "native_wait_exhausted" else [])
    assert sleeps == ([0.0] if module is codex_common and phase in {"native_wait_exhausted", "native_prepare"} else [])
    assert all(handle.closed for handle in handles)
    expected_error = "None errno=None winerror=None" if phase == "pre_attempt_deadline" else "PermissionError errno=13 winerror=32"
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == f"pallium hook: session_state_write_failed phase={phase} error={expected_error}\n"
    assert "private-marker" not in output.err and str(tmp_path) not in output.err


@pytest.mark.parametrize("module", (cc_common, codex_common))
@pytest.mark.parametrize("path", ("/ok", "/redirect", "/missing"))
def test_plain_http_hook_request_does_not_initialize_tls(module, path, monkeypatch):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    initialized, routes = [], []
    original_init = module.urllib.request.HTTPSHandler.__init__

    def initialize(handler, *args, **kwargs):
        initialized.append(True)
        return original_init(handler, *args, **kwargs)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            route = module.urllib.parse.urlsplit(self.path).path
            routes.append(route)
            self.send_response(302 if route == "/redirect" else 404 if route == "/missing" else 200)
            if route == "/redirect":
                self.send_header("Location", "/ok")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def log_message(self, *_args):
            pass

    monkeypatch.setattr(module.urllib.request.HTTPSHandler, "__init__", initialize)
    monkeypatch.setattr(module.urllib.request, "_opener", None)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        monkeypatch.setattr(module, "PALLIUM_BASE_URL", f"http://127.0.0.1:{server.server_port}")
        result = module.relay_request("GET", path, {}, timeout=0.75)
        assert result == (None if path == "/missing" else {"ok": True})
        assert routes == (["/redirect", "/ok"] if path == "/redirect" else [path])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
    assert not thread.is_alive()
    assert initialized == []


@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_https_hook_opener_lazily_keeps_standard_verification(module, monkeypatch):
    import http.client
    import ssl

    initialized, observed = [], []
    original_init = module.urllib.request.HTTPSHandler.__init__

    def initialize(handler, *args, **kwargs):
        initialized.append(True)
        return original_init(handler, *args, **kwargs)

    def open_https(handler, request):
        context = http.client.HTTPSConnection("example.invalid", context=handler._context)._context
        observed.append((context.verify_mode, context.check_hostname,
                         handler._debuglevel, handler.parent, request.full_url))
        raise module.urllib.error.URLError("verified transport refusal")

    monkeypatch.setattr(module.urllib.request.HTTPSHandler, "__init__", initialize)
    monkeypatch.setattr(module.urllib.request.HTTPSHandler, "https_open", open_https)
    build = getattr(module, "_build_opener", module.urllib.request.build_opener)
    opener = build()
    before_https = len(initialized)
    handler = next(item for item in opener.handlers if isinstance(item, module.urllib.request.HTTPSHandler))
    handler.set_http_debuglevel(3)
    request = module.urllib.request.Request("https://example.invalid/verified")
    with pytest.raises(module.urllib.error.URLError, match="verified transport refusal"):
        handler.https_open(request)
    assert observed == [(ssl.CERT_REQUIRED, True, 3, opener, request.full_url)]
    assert len(initialized) == 1
    assert before_https == 0


@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_http_hook_redirect_uses_verified_https_transport(module, monkeypatch):
    import http.client
    import io
    import ssl
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.response import addinfourl

    observed = []
    destination = "https://example.invalid/verified"

    def https_open(handler, request):
        context = http.client.HTTPSConnection("example.invalid", context=handler._context)._context
        observed.append((request.full_url, context.verify_mode, context.check_hostname))
        response = addinfourl(io.BytesIO(b'{"ok":true}'), {}, request.full_url, 200)
        response.msg = "OK"
        return response

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", destination)
            self.end_headers()

        def log_message(self, *_args):
            pass

    monkeypatch.setattr(module.urllib.request.HTTPSHandler, "https_open", https_open)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        monkeypatch.setattr(module, "PALLIUM_BASE_URL", f"http://127.0.0.1:{server.server_port}")
        assert module.relay_request("GET", "/redirect", {}, timeout=0.75) == {"ok": True}
        assert observed == [(destination, ssl.CERT_REQUIRED, True)]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
    assert not thread.is_alive()


@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_failed_https_initialization_remains_retryable(module, monkeypatch):
    import http.client
    import ssl

    calls = []
    original_init = module.urllib.request.HTTPSHandler.__init__

    def initialize(handler, *args, **kwargs):
        calls.append(True)
        if len(calls) == 1:
            raise OSError("trust initialization failed")
        return original_init(handler, *args, **kwargs)

    monkeypatch.setattr(module.urllib.request.HTTPSHandler, "__init__", initialize)
    def https_open(handler, _request):
        context = http.client.HTTPSConnection("example.invalid", context=handler._context)._context
        return context.verify_mode, context.check_hostname

    monkeypatch.setattr(module.urllib.request.HTTPSHandler, "https_open", https_open)
    opener = module._build_opener()
    handler = next(item for item in opener.handlers if isinstance(item, module._LazyHTTPSHandler))
    request = module.urllib.request.Request("https://example.invalid/verified")
    with pytest.raises(OSError, match="trust initialization failed"):
        handler.https_open(request)
    assert handler._context is None
    assert not handler._https_initialized
    assert handler.https_open(request) == (ssl.CERT_REQUIRED, True)
    assert handler._https_initialized
    assert len(calls) == 2


class TestCommonParity:
    def test_read_turn_signature_matches(self):
        cc_sig = inspect.signature(cc_common.read_turn)
        codex_sig = inspect.signature(codex_common.read_turn)
        assert str(cc_sig) == str(codex_sig)

    def test_redaction_patterns_match(self):
        cc_patterns = [(p.pattern, r) for p, r in cc_common.REDACTION_PATTERNS]
        codex_patterns = [(p.pattern, r) for p, r in codex_common.REDACTION_PATTERNS]
        assert cc_patterns == codex_patterns

    def test_redact_sensitive_signature_matches(self):
        cc_sig = inspect.signature(cc_common.redact_sensitive)
        codex_sig = inspect.signature(codex_common.redact_sensitive)
        assert str(cc_sig) == str(codex_sig)

    def test_build_work_trace_metadata_signature_matches(self):
        cc_sig = inspect.signature(cc_common.build_work_trace_metadata)
        codex_sig = inspect.signature(codex_common.build_work_trace_metadata)
        assert str(cc_sig) == str(codex_sig)

    def test_build_work_trace_metadata_produces_same_output(self):
        """Behavioral parity: same input produces same output in both copies."""
        for files_modified in [[], ["src/b.py", "src/c.py"]]:
            cc_turn = cc_common.TurnData(
                assistant_text="test",
                tool_calls=[
                    {"tool": "Read", "file_path": "src/x.py"},
                    {"tool": "Bash", "command": "ls", "exit_code": 0, "output_tail": "", "failure_class": "success"},
                ],
                has_productive_action=bool(files_modified),
                files_modified=files_modified,
            )
            codex_turn = codex_common.TurnData(
                assistant_text="test",
                tool_calls=[
                    {"tool": "Read", "file_path": "src/x.py"},
                    {"tool": "Bash", "command": "ls", "exit_code": 0, "output_tail": "", "failure_class": "success"},
                ],
                has_productive_action=bool(files_modified),
                files_modified=files_modified,
            )
            assert cc_common.build_work_trace_metadata(cc_turn) == codex_common.build_work_trace_metadata(codex_turn)

    def test_tool_constants_match(self):
        assert cc_common.DISCOVERY_TOOLS == codex_common.DISCOVERY_TOOLS
        assert cc_common.PRODUCTIVE_TOOLS == codex_common.PRODUCTIVE_TOOLS
        assert cc_common.EXCLUDED_TOOLS == codex_common.EXCLUDED_TOOLS
        assert cc_common.BASH_OUTPUT_LIMIT == codex_common.BASH_OUTPUT_LIMIT

    def test_redact_sensitive_behavioral_parity(self):
        """Same inputs produce same outputs."""
        test_strings = [
            "Bearer sk-12345",
            "DB_PASSWORD=secret",
            "postgres://user:pass@host/db",
            "clean text here",
        ]
        for s in test_strings:
            assert cc_common.redact_sensitive(s) == codex_common.redact_sensitive(s), f"Mismatch on: {s}"

    def test_turn_data_fields_match(self):
        """TurnData dataclass fields are identical in both copies."""
        import dataclasses
        cc_fields = {f.name: f.type for f in dataclasses.fields(cc_common.TurnData)}
        codex_fields = {f.name: f.type for f in dataclasses.fields(codex_common.TurnData)}
        assert cc_fields == codex_fields


def test_cc_build_work_trace_metadata_captures_files_modified():
    """Edit/Write tool calls produce files_modified in turn metadata."""
    turn = cc_common.TurnData(
        assistant_text="done",
        tool_calls=[{"tool": "Read", "file_path": "src/a.py"}],
        has_productive_action=True,
        files_modified=["src/b.py"],
    )
    result = cc_common.build_work_trace_metadata(turn)
    assert result is not None
    assert result["files_modified"] == ["src/b.py"]


def test_codex_build_work_trace_metadata_captures_files_modified():
    """Codex common.py also captures files_modified."""
    turn = codex_common.TurnData(
        assistant_text="done",
        tool_calls=[{"tool": "Read", "file_path": "src/a.py"}],
        has_productive_action=True,
        files_modified=["src/b.py"],
    )
    result = codex_common.build_work_trace_metadata(turn)
    assert result is not None
    assert result["files_modified"] == ["src/b.py"]


@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_configured_actor_precedes_git_and_deadline_but_not_valid_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, module,
) -> None:
    """The integration-owned override is fresh-session only and never needs Git."""
    monkeypatch.setattr(module, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setenv("PALLIUM_HOOK_ACTOR_REF", "  מפעיל 統一  ")
    monkeypatch.setattr(
        module.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("configured actor must bypass Git"),
    )
    assert module.derive_actor_ref(str(tmp_path), "configured") == "מפעיל 統一"
    monkeypatch.setattr(module, "_HOOK_DEADLINE", None)

    module.start_hook_deadline(0, clock=lambda: 1.0)
    assert module.derive_actor_ref(str(tmp_path), "expired") == "מפעיל 統一"

    context = module._identity_context(str(tmp_path))
    assert context is not None
    monkeypatch.setattr(module, "_read_session_state", lambda _sid: {**context, "actor_ref": "cached actor"})
    assert module.derive_actor_ref(str(tmp_path), "resumed") == "cached actor"

    monkeypatch.setattr(module, "_read_session_state", lambda _sid: None)
    monkeypatch.setattr(module, "_cache_identity_context", lambda *_args, **_kwargs: False)
    assert module.derive_actor_ref(str(tmp_path), "cache-write-failure") == "מפעיל 統一"


@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_actor_cache_checks_expected_pin_inside_session_update(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, module,
) -> None:
    monkeypatch.setattr(module, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(module, "_HOOK_DEADLINE", None)
    session = "changed-pin"
    expected = "git:example.test/expected"
    replacement = "git:example.test/replacement"
    assert module.pin_container(session, expected)
    original_update = module._update_session_state
    replaced = []

    def update_after_pin_change(sid, update):
        # Change the actual pin before the cache's locked read, not a cached lookup.
        with monkeypatch.context() as patch:
            patch.setattr(module, "_update_session_state", original_update)
            assert module.pin_container(sid, replacement)
        replaced.append(module._read_session_state(sid))
        return original_update(sid, update)

    monkeypatch.setattr(module, "_update_session_state", update_after_pin_change)
    context = {"identity_cwd": "new-context", "repo_config_fingerprint": "new-fingerprint"}
    module._cache_identity_context(
        session, context, actor_ref="new actor", expected_container_ref=expected,
    )
    assert len(replaced) == 1
    assert module._read_session_state(session) == replaced[0]
    monkeypatch.setattr(module, "_update_session_state", original_update)
    assert module._cache_identity_context(
        session, context, actor_ref="new actor", expected_container_ref=replacement,
    )
    assert module._read_session_state(session) == {
        **replaced[0], **context, "actor_ref": "new actor",
        "identity_container_ref": {"container_ref": replacement, **context},
    }


@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_old_writer_context_overwrite_cannot_reuse_cache_association(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, module,
) -> None:
    import time
    from types import SimpleNamespace

    stages = []

    def observe(label, operation, *args, **kwargs):
        stage = {"phase": label, "entered": time.perf_counter()}
        stages.append(stage)
        try:
            return operation(*args, **kwargs)
        except (OSError, TypeError, ValueError) as error:
            stage.update(error_type=type(error).__name__, errno=getattr(error, "errno", None),
                         winerror=getattr(error, "winerror", None))
            raise
        finally:
            stage["finished"] = time.perf_counter()

    class StatePath(type(tmp_path)):
        def write_text(self, *args, **kwargs):
            stages.append({"phase": "temporary_path", "length": len(str(self))})
            return observe("write_text", super().write_text, *args, **kwargs)

    original_lock, original_os, original_json = module._acquire_session_lock, module.os, module.json
    observed_os, observed_json = SimpleNamespace(**vars(original_os)), SimpleNamespace(**vars(original_json))
    observed_os.replace = lambda *args, **kwargs: observe("replace", original_os.replace, *args, **kwargs)
    observed_json.dumps = lambda *args, **kwargs: observe("serialize", original_json.dumps, *args, **kwargs)

    def acquire(*args, **kwargs):
        lock = observe("session_lock", original_lock, *args, **kwargs)
        stages[-1]["acquired"] = lock is not None
        return lock

    monkeypatch.setattr(module, "os", observed_os)
    monkeypatch.setattr(module, "json", observed_json)
    monkeypatch.setattr(module, "_acquire_session_lock", acquire)
    monkeypatch.setattr(module, "SESSIONS_DIR", StatePath(tmp_path / "sessions"))
    monkeypatch.setattr(module, "_HOOK_DEADLINE", None)
    monkeypatch.delenv("PALLIUM_HOOK_ACTOR_REF", raising=False)
    _make_repo(tmp_path)
    (tmp_path / ".git" / "config").write_text(
        '[remote "origin"]\nurl = https://example.test/other.git\n', encoding="utf-8",
    )
    session, old = "old-writer", "git:example.test/repo"
    pinned = module.pin_container(session, old)
    stages.append({"phase": "pin_result", "returned": pinned})
    (tmp_path / "cache-publication-stages.json").write_text(json.dumps(stages), encoding="utf-8")
    assert pinned, stages
    old_context = {"identity_cwd": "previous", "repo_config_fingerprint": "previous"}
    cached = module._cache_identity_context(
        session, old_context, actor_ref="old actor", expected_container_ref=old,
    )
    stages.append({"phase": "cache_result", "returned": cached})
    (tmp_path / "cache-publication-stages.json").write_text(json.dumps(stages), encoding="utf-8")
    assert cached, stages
    binding = module._read_session_state(session)["identity_container_ref"]
    assert binding == {"container_ref": old, **old_context}
    context = module._identity_context(str(tmp_path))
    assert context is not None
    # The old writer does not know the association field and preserves it.
    assert module._update_session_state(session, lambda state: {
        **state, **context, "actor_ref": "old actor",
    })
    assert module._read_session_state(session)["identity_container_ref"] == binding
    calls = []

    def run(command, **kwargs):
        calls.append(command[1])
        return type("Result", (), {"returncode": 0, "stdout":
            "https://example.test/other.git\n" if command[1] == "remote" else "fresh actor\n"})()

    monkeypatch.setattr(module.subprocess, "run", run)
    resolved = module.resolve_container_ref(str(tmp_path), session, True, False)
    assert resolved == "git:example.test/other"
    assert calls == ["remote"]
    assert module.derive_actor_ref(str(tmp_path), session, resolved) == "fresh actor"
    assert calls == ["remote", "config"]


@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_refused_cache_association_stays_untrusted_until_locked_publication(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, module,
) -> None:
    monkeypatch.setattr(module, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(module, "_HOOK_DEADLINE", None)
    monkeypatch.delenv("PALLIUM_HOOK_ACTOR_REF", raising=False)
    _make_repo(tmp_path)
    (tmp_path / ".git" / "config").write_text(
        '[remote "origin"]\nurl = https://example.test/repo.git\n', encoding="utf-8",
    )
    session, scope = "legacy-cache", "git:example.test/repo"
    assert module.pin_container(session, scope)
    context = module._identity_context(str(tmp_path))
    assert context is not None
    assert module._update_session_state(session, lambda state: {
        **state, **context, "actor_ref": "legacy actor",
    })
    before = module._read_session_state(session)
    calls = []

    def run(command, **kwargs):
        calls.append(command[1])
        return type("Result", (), {"returncode": 0, "stdout":
            "https://example.test/repo.git\n" if command[1] == "remote" else "fresh actor\n"})()

    monkeypatch.setattr(module.subprocess, "run", run)
    lock = module._acquire_session_lock(session)
    assert lock is not None
    try:
        assert module.resolve_container_ref(str(tmp_path), session, True, False) == scope
        assert module.derive_actor_ref(str(tmp_path), session, scope) == "fresh actor"
        assert module._read_session_state(session) == before
    finally:
        module._release_session_lock(lock)
    assert calls == ["remote", "config"]
    assert module.resolve_container_ref(str(tmp_path), session, True, False) == scope
    assert calls == ["remote", "config", "remote"]
    assert module._read_session_state(session)["identity_container_ref"] == {
        "container_ref": scope, **context,
    }
    assert module.resolve_container_ref(str(tmp_path), session, True, False) == scope
    assert calls == ["remote", "config", "remote"]


@pytest.mark.parametrize("module", (cc_common, codex_common))
@pytest.mark.parametrize("configured", (None, "   "))
def test_blank_or_unset_configured_actor_keeps_git_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, module, configured: str | None,
) -> None:
    if configured is None:
        monkeypatch.delenv("PALLIUM_HOOK_ACTOR_REF", raising=False)
    else:
        monkeypatch.setenv("PALLIUM_HOOK_ACTOR_REF", configured)
    monkeypatch.setattr(module, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(module, "_bounded_timeout", lambda _timeout: 1.0)

    class Result:
        returncode = 0
        stdout = "Git Fallback\n"

    monkeypatch.setattr(module.subprocess, "run", lambda *_args, **_kwargs: Result())
    assert module.derive_actor_ref(str(tmp_path), "fallback") == "Git Fallback"
def _make_repo(root: Path, branch: str = "feature/item", *, record: bool = True) -> None:
    git_dir = root / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "HEAD").write_text(f"ref: refs/heads/{branch}\n", encoding="utf-8")
    if record:
        slug = branch
        for prefix in cc_common._WORK_REF_PREFIXES:
            if slug.startswith(prefix):
                slug = slug[len(prefix):]
                break
        slug = slug.replace("/", "-")
        tasks = root / ".agent-workflow" / "tasks"
        tasks.mkdir(parents=True)
        (tasks / f"{slug}.md").write_text(
            "before\n<!-- agent-workflow:start -->\nstate\n<!-- agent-workflow:end -->\nafter",
            encoding="utf-8",
        )


@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_work_refs_reads_local_metadata_without_spawning(monkeypatch, tmp_path, module):
    _make_repo(tmp_path)
    nested = tmp_path / "src" / "nested"
    nested.mkdir(parents=True)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_a, **_k: pytest.fail("structural resolver spawned a process"),
    )

    assert module.build_work_refs_metadata(
        str(nested), ["Ticket_Ünicode", 42, "Ticket_Ünicode"]
    ) == {
        "pallium_work_refs": [
            "git-branch:feature/item",
            "agent-workflow:item",
            "Ticket_Ünicode",
            "Ticket_Ünicode",
        ]
    }


@pytest.mark.parametrize("module", (cc_common, codex_common))
@pytest.mark.parametrize(
    "cwd",
    [
        None,
        "",
        ".",
        "relative/path",
        r"\\server\share\repo",
        r"\\?\C:\repo",
        r"\\.\C:\repo",
        "x" * 4097,
    ],
)
def test_work_refs_rejects_unsafe_cwd_and_preserves_explicit(module, cwd):
    assert module.build_work_refs_metadata(cwd, ["ISSUE-1"]) == {
        "pallium_work_refs": ["ISSUE-1"]
    }


@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_work_refs_nonexistent_and_permission_error_fail_open(monkeypatch, tmp_path, module):
    missing = tmp_path / "missing"
    assert module.build_work_refs_metadata(str(missing), ["ISSUE-1"]) == {
        "pallium_work_refs": ["ISSUE-1"]
    }

    original = module._safe_lstat
    def deny_marker(path):
        if path.name == ".git":
            raise PermissionError("denied")
        return original(path)
    monkeypatch.setattr(module, "_safe_lstat", deny_marker)
    assert module.build_work_refs_metadata(str(tmp_path), ["ISSUE-2"]) == {
        "pallium_work_refs": ["ISSUE-2"]
    }


@pytest.mark.skipif(sys.platform != "win32", reason="Windows drive classification")
@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_work_refs_rejects_mapped_remote_drive_before_filesystem_access(monkeypatch, module):
    monkeypatch.setattr(module, "_windows_drive_is_local", lambda _path: False)
    monkeypatch.setattr(
        module,
        "_safe_directory_chain",
        lambda _path: pytest.fail("mapped drive was probed"),
    )
    assert module.build_work_refs_metadata(r"Z:\repo", ["KEEP"]) == {
        "pallium_work_refs": ["KEEP"]
    }


@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_work_refs_rejects_non_link_reparse_attribute(monkeypatch, tmp_path, module):
    class CloudPlaceholder:
        st_mode = module.stat.S_IFREG
        st_file_attributes = 0x400

    monkeypatch.setattr(module.stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400, raising=False)
    monkeypatch.setattr(module.Path, "lstat", lambda _path: CloudPlaceholder())
    with pytest.raises(OSError, match="unsafe reparse point"):
        module._safe_lstat(tmp_path / "cloud-placeholder")


@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_work_refs_stops_parent_walk_at_64(tmp_path, module):
    _make_repo(tmp_path)
    deep = tmp_path
    for _ in range(65):
        deep = deep / "d"
        deep.mkdir()
    assert module.build_work_refs_metadata(str(deep), ["KEEP"]) == {
        "pallium_work_refs": ["KEEP"]
    }


@pytest.mark.parametrize("module", (cc_common, codex_common))
@pytest.mark.parametrize(
    "head",
    [
        "0123456789abcdef\n",
        "ref: refs/tags/release\n",
        "ref: refs/heads/main\n",
        "ref: refs/heads/feature/../escape\n",
        "ref: refs/heads/bad branch\n",
        "ref: refs/heads/feature/item\nsecond\n",
        "ref: refs/heads/fix/.hidden\n",
        "\ufeffref: refs/heads/fix/item\n",
    ],
)
def test_work_refs_rejects_detached_base_and_malformed_head(tmp_path, module, head):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text(head, encoding="utf-8")
    assert module.build_work_refs_metadata(str(tmp_path), ["KEEP"]) == {
        "pallium_work_refs": ["KEEP"]
    }


@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_work_refs_accepts_crlf_and_unicode_branch(tmp_path, module):
    _make_repo(tmp_path, "feature/任务", record=False)
    (tmp_path / ".git" / "HEAD").write_bytes("ref: refs/heads/feature/任务\r\n".encode())
    tasks = tmp_path / ".agent-workflow" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "任务.md").write_text(
        "<!-- agent-workflow:start -->\n<!-- agent-workflow:end -->",
        encoding="utf-8",
    )
    assert module.build_work_refs_metadata(str(tmp_path)) == {
        "pallium_work_refs": ["git-branch:feature/任务", "agent-workflow:任务"]
    }


@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_work_refs_linked_worktree_local_gitdir(tmp_path, module):
    worktree = tmp_path / "checkout"
    git_dir = tmp_path / "metadata" / "worktrees" / "one"
    worktree.mkdir()
    git_dir.mkdir(parents=True)
    (worktree / ".git").write_text(
        f"gitdir: {git_dir}\n", encoding="utf-8"
    )
    (git_dir / "HEAD").write_text("ref: refs/heads/fix/linked\n", encoding="utf-8")
    tasks = worktree / ".agent-workflow" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "linked.md").write_text(
        "<!-- agent-workflow:start -->\n<!-- agent-workflow:end -->",
        encoding="utf-8",
    )
    assert module.build_work_refs_metadata(str(worktree)) == {
        "pallium_work_refs": ["git-branch:fix/linked", "agent-workflow:linked"]
    }


@pytest.mark.parametrize("module", (cc_common, codex_common))
@pytest.mark.parametrize(
    "pointer",
    [
        "gitdir:",
        r"gitdir: \\server\share\repo" + "\n",
        "gitdir: C:\\repo\nextra\n",
        "other: metadata\n",
        "\ufeffgitdir: metadata\n",
    ],
)
def test_work_refs_rejects_malformed_or_remote_gitdir(tmp_path, module, pointer):
    (tmp_path / ".git").write_text(pointer, encoding="utf-8")
    assert module.build_work_refs_metadata(str(tmp_path), ["KEEP"]) == {
        "pallium_work_refs": ["KEEP"]
    }


@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_work_refs_record_is_rechecked_and_must_be_complete(tmp_path, module):
    _make_repo(tmp_path)
    record = tmp_path / ".agent-workflow" / "tasks" / "item.md"
    expected_branch = {"pallium_work_refs": ["git-branch:feature/item"]}

    record.unlink()
    assert module.build_work_refs_metadata(str(tmp_path)) == expected_branch
    record.write_text("<!-- agent-workflow:end -->\n<!-- agent-workflow:start -->", encoding="utf-8")
    assert module.build_work_refs_metadata(str(tmp_path)) == expected_branch
    record.write_bytes(b"x" * (256 * 1024 + 1))
    assert module.build_work_refs_metadata(str(tmp_path)) == expected_branch
    record.write_bytes(b"\xff\xfe")
    assert module.build_work_refs_metadata(str(tmp_path)) == expected_branch
    record.write_text(
        "<!-- agent-workflow:start -->\n<!-- agent-workflow:end -->", encoding="utf-8"
    )
    assert module.build_work_refs_metadata(str(tmp_path)) == {
        "pallium_work_refs": ["git-branch:feature/item", "agent-workflow:item"]
    }


@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_work_refs_rejects_symlink_marker_head_and_record(tmp_path, module):
    cases = ("marker", "head", "record")
    for index, case in enumerate(cases):
        root = tmp_path / str(index)
        root.mkdir()
        _make_repo(root)
        if case == "marker":
            target = root / "git-target"
            (root / ".git").rename(target)
            try:
                (root / ".git").symlink_to(target, target_is_directory=True)
            except OSError:
                pytest.skip("symlinks unavailable")
        elif case == "head":
            head = root / ".git" / "HEAD"
            target = root / "head-target"
            head.rename(target)
            try:
                head.symlink_to(target)
            except OSError:
                pytest.skip("symlinks unavailable")
        else:
            record = root / ".agent-workflow" / "tasks" / "item.md"
            target = root / "record-target"
            record.rename(target)
            try:
                record.symlink_to(target)
            except OSError:
                pytest.skip("symlinks unavailable")
        result = module.build_work_refs_metadata(str(root), ["KEEP"])
        if case == "record":
            assert result == {
                "pallium_work_refs": ["git-branch:feature/item", "KEEP"]
            }
        else:
            assert result == {"pallium_work_refs": ["KEEP"]}


@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_work_refs_checkout_race_fails_open(monkeypatch, tmp_path, module):
    _make_repo(tmp_path)
    original = module._bounded_text
    def disappear(path, limit):
        if path.name == "HEAD":
            raise FileNotFoundError
        return original(path, limit)
    monkeypatch.setattr(module, "_bounded_text", disappear)
    assert module.build_work_refs_metadata(str(tmp_path), ["KEEP"]) == {
        "pallium_work_refs": ["KEEP"]
    }


@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_work_refs_rejects_intermediate_symlink_components(tmp_path, module):
    real = tmp_path / "real"
    _make_repo(real)
    nested = real / "nested"
    nested.mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    assert module.build_work_refs_metadata(str(alias / "nested"), ["KEEP"]) == {
        "pallium_work_refs": ["KEEP"]
    }

    checkout = tmp_path / "checkout"
    checkout.mkdir()
    metadata = tmp_path / "metadata"
    git_dir = metadata / "one"
    git_dir.mkdir(parents=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/fix/link\n", encoding="utf-8")
    metadata_alias = tmp_path / "metadata-alias"
    metadata_alias.symlink_to(metadata, target_is_directory=True)
    (checkout / ".git").write_text(
        f"gitdir: {metadata_alias / 'one'}\n", encoding="utf-8"
    )
    assert module.build_work_refs_metadata(str(checkout), ["KEEP"]) == {
        "pallium_work_refs": ["KEEP"]
    }


@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_work_refs_git_path_environment_fails_open(monkeypatch, tmp_path, module):
    _make_repo(tmp_path)
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "elsewhere"))
    assert module.build_work_refs_metadata(str(tmp_path), ["KEEP"]) == {
        "pallium_work_refs": ["KEEP"]
    }


@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_work_refs_head_change_during_record_lookup_fails_open(monkeypatch, tmp_path, module):
    _make_repo(tmp_path)
    original = module._bounded_text
    reads = 0

    def change_head(path, limit):
        nonlocal reads
        text = original(path, limit)
        if path.name == "HEAD" and reads == 0:
            reads += 1
            path.write_text("ref: refs/heads/fix/other\n", encoding="utf-8")
        return text

    monkeypatch.setattr(module, "_bounded_text", change_head)
    assert module.build_work_refs_metadata(str(tmp_path), ["KEEP"]) == {
        "pallium_work_refs": ["KEEP"]
    }


@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_work_refs_large_explicit_list_does_not_suppress_metadata(module):
    explicit = ["KEEP"] * 200_000
    result = module.build_work_refs_metadata("", explicit)
    assert result["pallium_work_refs"] == explicit

@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_injected_work_ref_uses_first_safe_structural_ref_only(module):
    discovery = module.WorkRefDiscovery(
        ("git-branch:feature/任务", "agent-workflow:任务")
    )
    assert module.injected_work_ref(discovery) == "git-branch:feature/任务"
    assert module.build_work_refs_metadata("", ["EXPLICIT-ONLY"], discovery) == {
        "pallium_work_refs": [
            "git-branch:feature/任务",
            "agent-workflow:任务",
            "EXPLICIT-ONLY",
        ]
    }
    explicit_only = module.WorkRefDiscovery()
    assert module.injected_work_ref(explicit_only) is None
    assert module.build_work_refs_metadata("", ["EXPLICIT-ONLY"], explicit_only) == {
        "pallium_work_refs": ["EXPLICIT-ONLY"]
    }


@pytest.mark.parametrize("module", (cc_common, codex_common))
@pytest.mark.parametrize(
    "ref",
    (
        "",
        "___---",
        "x" * 129,
        "unsafe\nref",
        "[REDACTED]",
        "ghp_abcdefghijklmnopqrstuvwxyz1234567890",
        "xoxb-" + "1" * 10 + "-" + "2" * 10 + "-" + "a" * 24,
        "AKIAABCDEFGHIJKLMNOP",
        "eyJabcdefghijk.eyJabcdefghijk.abcdefghijk",
    ),
)
def test_injected_work_ref_rejects_unsafe_structural_refs(module, ref):
    assert module.injected_work_ref(module.WorkRefDiscovery((ref,))) is None


@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_format_injection_includes_safe_work_ref(module):
    rendered = module.format_injection(
        [],
        "git:example/repo",
        2000,
        thread_ref="session",
        work_ref="git-branch:feature/任务",
    )
    scope = json.loads(rendered[rendered.index("{") : rendered.rindex("}") + 1])
    assert scope["work_ref"] == "git-branch:feature/任务"


@pytest.mark.parametrize("module", (cc_common, codex_common))
@pytest.mark.parametrize(
    "work_ref",
    (
        "ghp_abcdefghijklmnopqrstuvwxyz1234567890",
        "[REDACTED]",
        "bad\nref",
        "x" * 129,
    ),
)
def test_format_injection_omits_only_unsafe_work_ref(module, work_ref):
    rendered = module.format_injection(
        [], "git:repo", 2000, thread_ref="session", work_ref=work_ref
    )
    scope = json.loads(rendered[rendered.index("{") : rendered.rindex("}") + 1])
    assert scope == {"container_ref": "git:repo", "thread_ref": "session"}


@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_work_ref_warning_is_bounded_truthful_and_secret_safe(module):
    registry = ["work:v1:" + character * 64 for character in ("a", "b", "c")]
    metadata = {
        "pallium_work_refs": ["one", "two", "three", "four", "five", *registry],
        "pallium_work_ref_sources": ["caller"] * 5 + ["registry"] * 3,
        "pallium_relay_work_refs_status": "complete",
    }
    warning = module.work_ref_warning(metadata)
    assert all(key in warning for key in registry)
    assert "not searchable from this turn" in warning
    assert len(warning) < 400

    unavailable = module.work_ref_warning({
        "pallium_work_refs": ["ghp_abcdefghijklmnopqrstuvwxyz1234567890"],
        "pallium_work_ref_sources": ["caller"],
        "pallium_relay_work_refs_status": "unavailable",
    })
    assert "association enrichment was unavailable" in unavailable
    assert "ghp_" not in unavailable

@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_work_ref_warning_uses_full_selection_but_bounded_diagnostics(module):
    registry = "work:v1:" + "a" * 64
    callers = ["same"] * 20 + ["two", "three", "four", "five"]
    warning = module.work_ref_warning({
        "pallium_work_refs": [*callers, registry],
        "pallium_work_ref_sources": ["caller"] * len(callers) + ["registry"],
        "pallium_relay_work_refs_status": "complete",
    })
    assert registry in warning
    assert "not searchable from this turn" in warning
    assert "4 caller ref(s) beyond the 20-item diagnostic bound" in warning


@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_empty_and_failed_relay_enrichment_preserve_status(monkeypatch, module):
    metadata = module.build_work_refs_metadata(
        "", discovery=module.WorkRefDiscovery(), relay_status="unavailable"
    )
    assert metadata == {
        "pallium_work_ref_sources": [],
        "pallium_relay_work_refs_status": "unavailable",
    }
    assert "association enrichment was unavailable" in module.work_ref_warning(metadata)
    monkeypatch.setattr(module, "relay_request", lambda *_args, **_kwargs: None)
    assert module.fetch_confirmed_work_refs("codex", "session", "container") == (
        [],
        "unavailable",
    )


@pytest.mark.parametrize("module", (cc_common, codex_common))
@pytest.mark.parametrize("cwd", [None, "checkout"], ids=["no-cwd", "with-cwd"])
def test_empty_structural_work_refs_skip_scope_lookups(monkeypatch, module, cwd):
    monkeypatch.setattr(
        module, "repository_scope_ref",
        lambda *_args: pytest.fail("empty discovery must skip repository lookup"),
    )
    monkeypatch.setattr(
        module, "roadmap_scope_ref",
        lambda *_args: pytest.fail("empty discovery must skip roadmap lookup"),
    )

    assert module.structural_work_refs_payload(
        "git:container", module.WorkRefDiscovery(), cwd
    ) == []


@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_relay_get_encodes_query_without_body(monkeypatch, module):
    observed = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b'{"work_refs":[]}'

    def open_request(request, timeout):
        observed["request"] = request
        observed["timeout"] = timeout
        return Response()

    monkeypatch.setattr(module, "_urlopen", open_request)
    result = module.relay_request(
        "GET",
        "/relay/sessions/work-refs",
        {"runtime": "codex", "session_ref": "session / one", "container_ref": "git:repo"},
        timeout=0.5,
    )
    request = observed["request"]
    assert result == {"work_refs": []}
    assert request.data is None
    query = module.urllib.parse.parse_qs(module.urllib.parse.urlsplit(request.full_url).query)
    assert query == {
        "runtime": ["codex"],
        "session_ref": ["session / one"],
        "container_ref": ["git:repo"],
    }
@pytest.mark.parametrize("module", (cc_common, codex_common))
def test_repository_scope_fallback_uses_full_root_hash(monkeypatch, module):
    root = "A" * 40

    class Result:
        def __init__(self, returncode, stdout=""):
            self.returncode = returncode
            self.stdout = stdout

    def run(args, **_kwargs):
        if args[1:3] == ["remote", "get-url"]:
            return Result(2)
        return Result(0, root + "\n")

    monkeypatch.setattr(module.subprocess, "run", run)
    assert module.repository_scope_ref("checkout") == "repo:" + root.lower()
