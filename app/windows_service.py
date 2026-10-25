"""Cooperative custody for newly generated Windows service launchers.

Native calls are lazy, so importing the service never opens a Job or a DLL.
An observer owns the Job until every contained process exits; controllers never
kill it and never infer settlement from a PID file or a free port.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
from ctypes import wintypes as w
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time


GENERATION_ENV = "PALLIUM_WINDOWS_GENERATION"
ADMISSION_ENV = "PALLIUM_WINDOWS_ADMISSION_DEADLINE"
MANAGED_MARKER = "' Pallium cooperative launcher v1"
SERVICE_INSTANCE_HEADER = "X-Pallium-Service-Instance"
_STILL_ACTIVE = 259
_NATIVE = None


def valid_service_instance(value):
    """Public opaque correlation value, restricted to nonempty HTTP-safe ASCII."""
    return isinstance(value, str) and re.fullmatch(r"[!-~]+", value) is not None


class Unknown(RuntimeError):
    """Custody or settlement could not be positively established."""


class FailedBeforeLaunch(Unknown):
    """CreateProcess failed without creating an application process."""


class Deadline:
    def __init__(self, seconds, *, clock=time.perf_counter, absolute=None):
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("operation budget must be finite and positive")
        self.clock = clock
        self.end = clock() + seconds
        if absolute is not None:
            if not math.isfinite(absolute):
                raise ValueError("absolute deadline must be finite")
            self.end = min(self.end, absolute)

    def remaining(self):
        remaining = self.end - self.clock()
        if remaining <= 0:
            raise Unknown("operation deadline elapsed; no replacement permitted")
        return remaining

    def read(self, operation):
        # Observations are synchronous: the OS/filesystem may return late.
        # This is an admission deadline, not an opaque cancellation watchdog.
        self.remaining()
        result = operation()
        self.remaining()
        return result


def _json(path):
    with path.open("rb") as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise Unknown("oversized lifecycle metadata")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise Unknown("invalid lifecycle metadata")
    return data


def _write(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _names(home, generation="control"):
    owner = hashlib.sha256(str(home).casefold().encode()).hexdigest()[:32]
    return "Local\\Pallium-" + owner + "-" + generation


def native():
    global _NATIVE
    if _NATIVE is None:
        _NATIVE = WindowsAPI()
    return _NATIVE


class _Security(ctypes.Structure):
    _fields_ = [("length", w.DWORD), ("descriptor", w.LPVOID), ("inherit", w.BOOL)]


class _Startup(ctypes.Structure):
    _fields_ = [("cb", w.DWORD), ("reserved", w.LPWSTR), ("desktop", w.LPWSTR),
                ("title", w.LPWSTR), ("x", w.DWORD), ("y", w.DWORD),
                ("xsize", w.DWORD), ("ysize", w.DWORD), ("xchars", w.DWORD),
                ("ychars", w.DWORD), ("fill", w.DWORD), ("flags", w.DWORD),
                ("show", w.WORD), ("reservedsize", w.WORD), ("reserved2", w.LPVOID),
                ("stdin", w.HANDLE), ("stdout", w.HANDLE), ("stderr", w.HANDLE)]


class _ProcessInfo(ctypes.Structure):
    _fields_ = [("process", w.HANDLE), ("thread", w.HANDLE), ("pid", w.DWORD), ("tid", w.DWORD)]


class _StartupEx(ctypes.Structure):
    _fields_ = [("startup", _Startup), ("attributes", w.LPVOID)]


class _Accounting(ctypes.Structure):
    _fields_ = [("user", ctypes.c_int64), ("kernel", ctypes.c_int64),
                ("period_user", ctypes.c_int64), ("period_kernel", ctypes.c_int64),
                ("faults", w.DWORD), ("total", w.DWORD), ("active", w.DWORD),
                ("terminated", w.DWORD)]


class WindowsAPI:
    """The only native boundary; tests replace it before construction."""
    def __init__(self):
        if sys.platform != "win32":
            raise Unknown("managed Windows lifecycle requires Windows")
        self.k = ctypes.WinDLL("kernel32", use_last_error=True)
        self.a = ctypes.WinDLL("advapi32", use_last_error=True)
        signatures = {
            "CloseHandle": ([w.HANDLE], w.BOOL),
            "LocalFree": ([w.LPVOID], w.LPVOID),
            "GetCurrentProcess": ([], w.HANDLE),
            "DuplicateHandle": ([w.HANDLE, w.HANDLE, w.HANDLE, ctypes.POINTER(w.HANDLE), w.DWORD, w.BOOL, w.DWORD], w.BOOL),
            "CreateEventW": ([ctypes.POINTER(_Security), w.BOOL, w.BOOL, w.LPCWSTR], w.HANDLE),
            "OpenEventW": ([w.DWORD, w.BOOL, w.LPCWSTR], w.HANDLE),
            "SetEvent": ([w.HANDLE], w.BOOL),
            "CreateMutexW": ([ctypes.POINTER(_Security), w.BOOL, w.LPCWSTR], w.HANDLE),
            "ReleaseMutex": ([w.HANDLE], w.BOOL),
            "WaitForSingleObject": ([w.HANDLE, w.DWORD], w.DWORD),
            "CreateJobObjectW": ([ctypes.POINTER(_Security), w.LPCWSTR], w.HANDLE),
            "OpenJobObjectW": ([w.DWORD, w.BOOL, w.LPCWSTR], w.HANDLE),
            "IsProcessInJob": ([w.HANDLE, w.HANDLE, ctypes.POINTER(w.BOOL)], w.BOOL),
            "QueryInformationJobObject": ([w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD, w.LPVOID], w.BOOL),
            "SetInformationJobObject": ([w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD], w.BOOL),
            "OpenProcess": ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            "GetExitCodeProcess": ([w.HANDLE, ctypes.POINTER(w.DWORD)], w.BOOL),
            "GetProcessTimes": ([w.HANDLE] + [w.LPVOID] * 4, w.BOOL),
            "QueryFullProcessImageNameW": ([w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)], w.BOOL),
            "ResumeThread": ([w.HANDLE], w.DWORD),
            "InitializeProcThreadAttributeList": ([w.LPVOID, w.DWORD, w.DWORD, ctypes.POINTER(ctypes.c_size_t)], w.BOOL),
            "UpdateProcThreadAttribute": ([w.LPVOID, w.DWORD, ctypes.c_size_t, w.LPVOID, ctypes.c_size_t, w.LPVOID, w.LPVOID], w.BOOL),
            "DeleteProcThreadAttributeList": ([w.LPVOID], None),
            "CreateProcessW": ([w.LPCWSTR, w.LPWSTR, w.LPVOID, w.LPVOID, w.BOOL,
                                w.DWORD, w.LPVOID, w.LPCWSTR, ctypes.POINTER(_Startup), ctypes.POINTER(_ProcessInfo)], w.BOOL),
            "CreateIoCompletionPort": ([w.HANDLE, w.HANDLE, ctypes.c_size_t, w.DWORD], w.HANDLE),
            "GetQueuedCompletionStatus": ([w.HANDLE, ctypes.POINTER(w.DWORD), ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(w.LPVOID), w.DWORD], w.BOOL),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.k, name)
            function.argtypes, function.restype = args, result
        for name, args in {
            "OpenProcessToken": [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)],
            "GetTokenInformation": [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD)],
            "ConvertSidToStringSidW": [w.LPVOID, ctypes.POINTER(w.LPWSTR)],
            "ConvertStringSecurityDescriptorToSecurityDescriptorW": [w.LPCWSTR, w.DWORD, ctypes.POINTER(w.LPVOID), w.LPVOID],
            "GetFileSecurityW": [w.LPCWSTR, w.DWORD, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD)],
            "ConvertSecurityDescriptorToStringSecurityDescriptorW": [w.LPVOID, w.DWORD, w.DWORD, ctypes.POINTER(w.LPWSTR), w.LPVOID],
        }.items():
            function = getattr(self.a, name)
            function.argtypes, function.restype = args, w.BOOL
        self.sid = self.user_sid(self.k.GetCurrentProcess())

    def user_sid(self, process):
        token, size = w.HANDLE(), w.DWORD()
        self.check(self.a.OpenProcessToken(process, 8, ctypes.byref(token)))
        try:
            self.a.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
            buffer = ctypes.create_string_buffer(size.value)
            self.check(self.a.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)))
            sid = w.LPWSTR()
            self.check(self.a.ConvertSidToStringSidW(ctypes.cast(buffer, ctypes.POINTER(w.LPVOID))[0], ctypes.byref(sid)))
            try:
                return sid.value
            finally:
                self.k.LocalFree(sid)
        finally:
            self.close(token)

    @staticmethod
    def check(result):
        if not result:
            raise Unknown(str(ctypes.WinError(ctypes.get_last_error())))
        return result

    def close(self, handle):
        if handle:
            self.check(self.k.CloseHandle(handle))

    @contextmanager
    def security(self):
        descriptor = w.LPVOID()
        self.check(self.a.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            "D:P(A;;GA;;;" + self.sid + ")", 1, ctypes.byref(descriptor), None))
        try:
            yield _Security(ctypes.sizeof(_Security), descriptor, False)
        finally:
            self.k.LocalFree(descriptor)

    def private_home(self, home):
        # Verify existing protection; never repair an ACL or add a principal.
        for path in (home, home / "run"):
            if path.is_symlink() or not path.is_dir():
                raise Unknown("existing private service home/run required")
            size = w.DWORD()
            self.a.GetFileSecurityW(str(path), 5, None, 0, ctypes.byref(size))
            buffer = ctypes.create_string_buffer(size.value)
            self.check(self.a.GetFileSecurityW(str(path), 5, buffer, size, ctypes.byref(size)))
            text = w.LPWSTR()
            self.check(self.a.ConvertSecurityDescriptorToStringSecurityDescriptorW(buffer, 1, 5, ctypes.byref(text), None))
            try:
                sddl = text.value
            finally:
                self.k.LocalFree(text)
            owner = re.match(r"O:([^:]+?)(?=[GDS]:|$)", sddl)
            allowed = {self.sid, "SY", "BA"}
            aces = re.findall(r"\(([^()]+)\)", sddl)
            if not owner or owner[1] != self.sid or not aces:
                raise Unknown("private service directory ownership is unverified")
            if any(ace.split(";")[0] in {"A", "OA"} and ace.split(";")[-1] not in allowed for ace in aces):
                raise Unknown("service directory permits another principal; no ACL change attempted")

    def event(self, name, *, create=False):
        if create:
            with self.security() as security:
                handle = self.k.CreateEventW(ctypes.byref(security), True, False, name)
                existed = ctypes.get_last_error() == 183
            if existed:
                self.close(handle)
                raise Unknown("generation event already exists")
        else:
            handle = self.k.OpenEventW(0x100002, False, name)
        return self.check(handle)

    def signaled(self, handle, seconds=0):
        result = self.k.WaitForSingleObject(handle, max(0, min(0xFFFFFFFE, math.ceil(seconds * 1000))))
        if result == 0:
            return True
        if result == 258:
            return False
        raise Unknown("event/process wait failed or was abandoned")

    def signal(self, handle):
        self.check(self.k.SetEvent(handle))

    @contextmanager
    def mutex(self, name, seconds):
        with self.security() as security:
            handle = self.check(self.k.CreateMutexW(ctypes.byref(security), False, name))
        acquired = False
        try:
            # Recompute after native creation, which itself may have returned late.
            available = seconds() if callable(seconds) else seconds
            result = self.k.WaitForSingleObject(handle, max(1, math.ceil(available * 1000)))
            if result == 0x80:
                self.k.ReleaseMutex(handle)
                raise Unknown("abandoned lifecycle mutex")
            if result != 0:
                raise Unknown("lifecycle mutex unavailable within deadline")
            acquired = True
            yield
        finally:
            if acquired:
                self.check(self.k.ReleaseMutex(handle))
            self.close(handle)

    def job(self, name, *, create=False):
        if not create:
            return self.check(self.k.OpenJobObjectW(4, False, name))
        with self.security() as security:
            handle = self.k.CreateJobObjectW(ctypes.byref(security), name)
            existed = ctypes.get_last_error() == 183
        if existed:
            self.close(handle)
            raise Unknown("generation Job already exists")
        # Deliberately no KILL_ON_JOB_CLOSE and no breakaway flags.
        return self.check(handle)

    def accounting(self, job):
        value = _Accounting()
        self.check(self.k.QueryInformationJobObject(job, 1, ctypes.byref(value), ctypes.sizeof(value), None))
        return value.total, value.active

    def observe_job(self, job):
        port = self.check(self.k.CreateIoCompletionPort(w.HANDLE(-1), None, 0, 1))
        association = (w.HANDLE * 2)(None, port)
        try:
            self.check(self.k.SetInformationJobObject(job, 7, association, ctypes.sizeof(association)))
            return port
        except BaseException:
            self.close(port)
            raise

    def notification(self, port):
        message, key, pid = w.DWORD(), ctypes.c_size_t(), w.LPVOID()
        if not self.k.GetQueuedCompletionStatus(port, ctypes.byref(message), ctypes.byref(key), ctypes.byref(pid), 0):
            if ctypes.get_last_error() == 258:
                return None
            raise Unknown("Job observation failed")
        return message.value, pid.value

    def process(self, pid):
        return self.check(self.k.OpenProcess(0x100000 | 0x1000, False, pid))

    def launcher(self):
        # Query only this observer's ancestry, never a machine process census.
        query = ctypes.WinDLL("ntdll").NtQueryInformationProcess
        query.argtypes = [w.HANDLE, w.ULONG, w.LPVOID, w.ULONG, w.LPVOID]
        query.restype = w.LONG
        pid, child_created = os.getpid(), None
        seen = set()
        handles, identities = [], []
        try:
            while len(seen) < 16 and pid not in seen:
                seen.add(pid)
                handle = self.check(self.k.OpenProcess(0x100000 | 0x400, False, pid))
                handles.append(handle)
                identity = self.identity(handle, pid)
                identities.append(identity)
                if self.user_sid(handle) != self.sid:
                    raise Unknown("launcher ancestry is not owned by this user")
                if child_created is not None and identity["created"] > child_created:
                    raise Unknown("launcher ancestry identity was reused")
                name = Path(identity["image"]).name.casefold()
                if name == "wscript.exe":
                    return handle, identity, handles, identities
                if name not in {"python.exe", "pythonw.exe"}:
                    raise Unknown("unsupported observer launcher ancestry")
                basic = (w.LPVOID * 6)()
                if query(handle, 0, basic, ctypes.sizeof(basic), None) != 0:
                    raise Unknown("cannot verify exact launcher ancestry")
                if int(basic[4] or 0) != pid or self.exit_code(handle) is not None:
                    raise Unknown("launcher ancestry changed during observation")
                pid, child_created = int(basic[5] or 0), identity["created"]
            raise Unknown("launcher ancestry missing or over bound")
        except BaseException:
            for handle in handles:
                self.close(handle)
            raise

    def identity(self, handle, pid):
        created, exited, kernel, user = (ctypes.c_uint64() for _ in range(4))
        self.check(self.k.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)))
        length, image = w.DWORD(32768), ctypes.create_unicode_buffer(32768)
        self.check(self.k.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(length)))
        return {"pid": pid, "created": created.value, "image": image.value.casefold()}

    def in_job(self, process, job):
        answer = w.BOOL()
        self.check(self.k.IsProcessInJob(process, job, ctypes.byref(answer)))
        return bool(answer.value)

    def owns_current_process(self, name):
        job = self.job(name)
        try:
            return self.in_job(self.k.GetCurrentProcess(), job)
        finally:
            self.close(job)

    def exit_code(self, process):
        if not self.signaled(process):
            return None
        code = w.DWORD()
        self.check(self.k.GetExitCodeProcess(process, ctypes.byref(code)))
        return code.value

    def contain(self, job, process):
        if not self.in_job(process.handle, job):
            raise Unknown("prelaunch Job containment failed; suspended process retained without resume")

    def spawn(self, command, *, cwd, env, stdout=None, stderr=None, job=None):
        extended, info = _StartupEx(), _ProcessInfo()
        startup = extended.startup
        startup.flags, startup.show = 1, 0
        inherited, attributes, null_input = [], [], None
        attribute_buffer = None
        attributes_initialized = False
        process = None
        cleanup_errors = []
        try:
            if stdout is not None:
                import msvcrt
                null_input = open(os.devnull, "rb")
                current = self.k.GetCurrentProcess()
                for stream in (null_input, stdout):
                    handle = w.HANDLE()
                    self.check(self.k.DuplicateHandle(current, msvcrt.get_osfhandle(stream.fileno()), current,
                                                      ctypes.byref(handle), 0, True, 2))
                    inherited.append(handle.value)
                startup.flags |= 0x100
                startup.stdin, startup.stdout, startup.stderr = inherited[0], inherited[1], inherited[1]
                attributes.append((0x20002, (w.HANDLE * len(inherited))(*inherited)))
            if job is not None:
                # Windows validates Job assignment during creation, before any application code.
                attributes.append((0x2000D, (w.HANDLE * 1)(job)))
            flags = 4 | 0x400 | 0x08000000
            if attributes:
                size = ctypes.c_size_t()
                self.k.InitializeProcThreadAttributeList(None, len(attributes), 0, ctypes.byref(size))
                attribute_buffer = ctypes.create_string_buffer(size.value)
                self.check(self.k.InitializeProcThreadAttributeList(attribute_buffer, len(attributes), 0, ctypes.byref(size)))
                attributes_initialized = True
                extended.attributes = ctypes.cast(attribute_buffer, w.LPVOID)
                for key, values in attributes:
                    self.check(self.k.UpdateProcThreadAttribute(attribute_buffer, 0, key, values, ctypes.sizeof(values), None, None))
                flags |= 0x80000
                startup.cb = ctypes.sizeof(extended)
            else:
                startup.cb = ctypes.sizeof(startup)
            environment = ctypes.create_unicode_buffer("\0".join(f"{key}={value}" for key, value in sorted(env.items())) + "\0\0")
            created = self.k.CreateProcessW(None, ctypes.create_unicode_buffer(subprocess.list2cmdline(command)),
                                           None, None, bool(inherited), flags, environment, str(cwd),
                                           ctypes.cast(ctypes.byref(extended), ctypes.POINTER(_Startup)), ctypes.byref(info))
            if not created:
                raise FailedBeforeLaunch(str(ctypes.WinError(ctypes.get_last_error())))
            # Creation is committed before cleanup: no cleanup exception may hide it.
            process = Process(self, info.process, info.pid)
            process.thread = info.thread
        finally:
            if attributes_initialized:
                try:
                    self.k.DeleteProcThreadAttributeList(attribute_buffer)
                except BaseException as exc:
                    cleanup_errors.append((attribute_buffer, exc))
            for handle in inherited:
                try:
                    self.close(handle)
                except BaseException as exc:
                    cleanup_errors.append((handle, exc))
            if null_input is not None:
                try:
                    null_input.close()
                except BaseException as exc:
                    cleanup_errors.append((null_input, exc))
            if process is not None:
                process.cleanup_errors = cleanup_errors
            elif cleanup_errors:
                raise Unknown("creation failed and native cleanup is uncertain")
        return process

    def resume(self, process):
        if process.cleanup_errors:
            raise Unknown("suspended creation retained after cleanup failure; no resume")
        if self.k.ResumeThread(process.thread) == 0xFFFFFFFF:
            raise Unknown("could not resume contained process")
        self.close(process.thread)
        process.thread = None


class Process:
    def __init__(self, api, handle, pid):
        self.api, self.handle, self.pid = api, handle, pid
        self.returncode = None
        self.thread = None
        self.cleanup_errors = []

    def poll(self):
        self.returncode = self.api.exit_code(self.handle)
        return self.returncode

    def wait(self, timeout=None):
        if not self.api.signaled(self.handle, timeout or 0):
            raise subprocess.TimeoutExpired(str(self.pid), timeout)
        return self.poll()


class StopChannel:
    def __init__(self, description, *, api=None):
        self.api = api or native()
        self.description = description
        self.event = self.api.event(description + "-stop")

    def requested(self):
        return self.api.signaled(self.event)

    def sleep(self, seconds):
        self.api.signaled(self.event, seconds)

    def request(self, seconds=1):
        with self.api.mutex(self.description + "-spawn", seconds):
            self.api.signal(self.event)

    def spawn(self, command, *, attempts, stop, **kwargs):
        with self.api.mutex(self.description + "-spawn", 1):
            if stop():
                raise Unknown("generation admission is closed")
            self.check_admission()
            # Inherited Job membership is established by Windows before child code runs.
            process = self.api.spawn(command, **kwargs)
            attempts.append(process)
            if stop():
                raise Unknown("stop raced suspended launch; process retained without resume")
            self.check_admission()
            self.api.resume(process)
            return process

    @staticmethod
    def check_admission():
        absolute = os.environ.get(ADMISSION_ENV)
        if absolute is not None and (not math.isfinite(float(absolute)) or time.perf_counter() >= float(absolute)):
            raise Unknown("transaction admission expired; suspended roots retained")

    def publish_bound(self, port, listeners, public_instance):
        # Only OwnedServer's post-bind lifecycle calls this; lifespan token != bind.
        if self.requested():
            return False
        if not listeners or any(not listener.is_serving() or not listener.sockets
                                or any(sock.fileno() < 0 or sock.getsockname()[1] != port
                                       for sock in listener.sockets) for listener in listeners):
            raise Unknown("owned API has not successfully bound its configured listener")
        home = Path(os.environ["PALLIUM_HOME"])
        path = home / "run" / "api_token"
        token = _json(path)
        if token.get("pid") != os.getpid() or token.get("nonce") != os.environ.get("PALLIUM_API_LAUNCH_TOKEN"):
            raise Unknown("post-bind token does not identify this API instance")
        if not valid_service_instance(public_instance) or public_instance == token.get("nonce"):
            raise Unknown("public service instance must be distinct from the startup nonce")
        record = _json(home / "run" / "windows-generation.json")
        if record.get("description") != self.description or record.get("manifest", {}).get("port") != port:
            raise Unknown("post-bind generation/port identity changed")
        token["bound"] = {"generation": self.description, "port": port}
        token["public_instance"] = public_instance
        _write(path, token)
        return True

    def clear_bound(self):
        path = Path(os.environ["PALLIUM_HOME"]) / "run" / "api_token"
        try:
            token = _json(path)
        except FileNotFoundError:
            return
        if token.get("pid") == os.getpid() and token.get("nonce") == os.environ.get("PALLIUM_API_LAUNCH_TOKEN"):
            token.pop("bound", None)
            _write(path, token)

    def bound_instance(self, nonce, run_dir, port):
        try:
            token = _json(run_dir / "api_token")
        except (OSError, ValueError):
            return None
        instance = token.get("public_instance")
        if (token.get("nonce") == nonce and type(token.get("pid")) is int
                and token.get("bound") == {"generation": self.description, "port": port}
                and valid_service_instance(instance) and instance != nonce):
            return instance
        return None

    def bound_ready(self, nonce, run_dir, port):
        return self.bound_instance(nonce, run_dir, port) is not None

    def publish_ready(self, nonce, run_dir):
        # Reuse the API's existing launch-token read path after supervisor startup.
        if self.requested():
            return
        token = _json(run_dir / "api_token")
        if token.get("nonce") != nonce or type(token.get("pid")) is not int:
            raise Unknown("API startup token does not match this attempt")
        process = self.api.process(token["pid"])
        job = None
        try:
            job = self.api.job(self.description)
            if not self.api.in_job(process, job) or self.api.exit_code(process) is not None:
                raise Unknown("ready API is not a live member of this generation")
            path = run_dir / "windows-generation.json"
            record = _json(path)
            if record.get("description") != self.description or record.get("outcome") != "running":
                raise Unknown("generation changed during API startup")
            if token.get("bound") != {"generation": self.description, "port": record["manifest"]["port"]}:
                raise Unknown("API startup token does not prove successful owned binding")
            instance = token.get("public_instance")
            if not valid_service_instance(instance) or instance == nonce:
                raise Unknown("public service instance correlation is missing or invalid")
            record["api_ready"] = {"nonce": nonce, "identity": self.api.identity(process, token["pid"]),
                                   "public_instance": instance}
            _write(path, record)
        finally:
            self.api.close(process)
            if job is not None:
                self.api.close(job)

    def close(self):
        self.api.close(self.event)


def inherited_stop():
    description = os.environ.get(GENERATION_ENV)
    if not description:
        return None
    channel = StopChannel(description)
    try:
        if not channel.api.owns_current_process(description):
            raise Unknown("managed generation is not containing this process")
        return channel
    except BaseException:
        channel.close()
        raise


def _config_identity(home, manifest):
    digest = hashlib.sha256()
    digest.update(json.dumps(manifest, sort_keys=True).encode())
    for name in ("pallium.toml", ".env"):
        path = home / "config" / name
        digest.update(path.read_bytes() if path.exists() else b"<absent>")
    digest.update(json.dumps({key: value for key, value in os.environ.items()
                              if key.startswith("PALLIUM_") and key not in {GENERATION_ENV, ADMISSION_ENV}}, sort_keys=True).encode())
    return digest.hexdigest()


def _apply_existing_home(home):
    from app.cli.service import _apply_home_env
    os.environ["PALLIUM_HOME"] = str(home)
    _apply_home_env(home)


def _existing_store(home):
    from app.config import AppConfig
    from app.codex_wake_lifecycle import _paths, _marker_present
    paths = _paths(AppConfig.from_env())
    if paths is not None and (not all(path.is_file() for path in paths[:2]) or not _marker_present(paths[1])):
        raise Unknown("existing live pair and wake authority required; setup/import/restore is separate")


def _task_arguments(manifest):
    return '"' + manifest["vbs"] + '" "$(Arg0)"'


def launcher_text(manifest):
    return (MANAGED_MARKER + "\n"
            'Set WshShell = CreateObject("WScript.Shell")\n'
            f'WshShell.CurrentDirectory = "{manifest["cwd"]}"\n'
            f'command = """{manifest["python"]}"" -m app.windows_service observe --home ""{manifest["home"]}"""\n'
            'If WScript.Arguments.Count = 1 Then\n'
            '  If WScript.Arguments(0) <> "$(Arg0)" Then command = command & " --deadline " & WScript.Arguments(0)\n'
            'End If\n'
            'WScript.Quit WshShell.Run(command, 0, True)\n')


def _manifest(home):
    value = _json(home / "run" / "windows-launch.json")
    port = value.get("port")
    if (value.get("version") != 1 or value.get("home") != str(home)
            or type(port) is not int or not 1 <= port <= 65535):
        raise Unknown("unsupported managed launcher metadata")
    for key in ("python", "cwd", "vbs"):
        if not isinstance(value.get(key), str) or not Path(value[key]).is_absolute():
            raise Unknown("managed launcher paths must be absolute")
    if (not Path(value["python"]).is_file() or not Path(value["cwd"]).is_dir()
            or Path(value["vbs"]).read_text(encoding="utf-16") != launcher_text(value)):
        raise Unknown("installed interpreter/cwd/launcher identity differs")
    return value


def observe(home, *, api=None, absolute_deadline=None):
    api = api or native()
    admission = Deadline(180, absolute=absolute_deadline) if absolute_deadline is not None else None
    api.private_home(home)
    manifest = _manifest(home)
    _apply_existing_home(home)
    _existing_store(home)
    config = _config_identity(home, manifest)
    with api.mutex(_names(home, "owner"), 1):
        _existing_store(home)
        if _config_identity(home, manifest) != config:
            raise Unknown("configuration changed before generation ownership")
        previous = home / "run" / "windows-generation.json"
        if previous.exists():
            raise Unknown("a previous generation requires controller-verified settlement")
        generation = secrets.token_hex(16)
        description = _names(home, generation)
        event = api.event(description + "-stop", create=True)
        job = api.job(description, create=True)
        port = api.observe_job(job)
        observer = api.process(os.getpid())
        launcher, launcher_identity, ancestors, ancestry = api.launcher()
        handles = {}
        unknown = False
        task = _task_info(Deadline(180))
        _validate_task(manifest, task)
        if len(task["instances"]) != 1:
            raise Unknown("observer is not bound to one registered task instance")
        record = {"version": 1, "generation": generation, "description": description,
                  "config": config, "manifest": manifest,
                  "observer": api.identity(observer, os.getpid()),
                  "launcher": launcher_identity, "ancestry": ancestry,
                  "task_instance": task["instances"][0], "outcome": "running"}
        if Path(record["launcher"]["image"]).name.casefold() != "wscript.exe":
            raise Unknown("managed observer must have the actual WScript launcher as parent")
        try:
            _write(previous, record)
            environment = {**os.environ, GENERATION_ENV: description}
            if admission is not None:
                environment[ADMISSION_ENV] = format(admission.end, ".17g")
            else:
                environment.pop(ADMISSION_ENV, None)
            command = [manifest["python"], "-m", "app.run", "service", "run", "--home", str(home), "--port", str(manifest["port"])]
            with api.mutex(description + "-spawn", 1):
                if api.signaled(event):
                    raise Unknown("stop closed admission before initial creation")
                if admission is not None:
                    admission.remaining()
                process = api.spawn(command, cwd=manifest["cwd"], env=environment, job=job)
                handles[process.pid] = process.handle
            try:
                record["supervisor"] = api.identity(process.handle, process.pid)
                _write(previous, record)
                with api.mutex(description + "-spawn", 1):
                    api.contain(job, process)
                    if api.signaled(event):
                        raise Unknown("stop raced suspended initial launch")
                    if admission is not None:
                        admission.remaining()
                    api.resume(process)
            except (Unknown, OSError, ValueError):
                # A partial creation stays suspended in observer custody, never retried.
                unknown = True
                try:
                    with api.mutex(description + "-spawn", 1):
                        api.signal(event)
                except Unknown:
                    # Keep custody even when stop signaling cannot be established.
                    pass
            while True:
                notification = api.notification(port)
                while notification is not None:
                    message, pid = notification
                    if message == 6 and pid not in handles:
                        try:
                            handle = api.process(pid)
                            if not api.in_job(handle, job):
                                api.close(handle)
                                raise Unknown("Job notification identity no longer owned")
                            handles[pid] = handle
                        except Unknown:
                            unknown = True
                    notification = api.notification(port)
                if process.poll() is not None and not api.signaled(event):
                    with api.mutex(description + "-spawn", 1):
                        api.signal(event)
                total, active = api.accounting(job)
                if active == 0 and all(api.exit_code(handle) is not None for handle in handles.values()):
                    break
                time.sleep(0.02)
            results = {str(pid): api.exit_code(handle) for pid, handle in handles.items()}
            unknown = unknown or len(results) != total or any(value is None for value in results.values())
            outcome = "unknown" if unknown else ("clean" if all(value == 0 for value in results.values()) and api.signaled(event) else "failed")
            record.update(outcome=outcome, empty=True, total=total, exits=results)
            _write(previous, record)
            return 0 if outcome == "clean" else 1
        finally:
            # No kill-on-close: observer loss does not force active writes.
            for handle in {event, port, observer, launcher, *ancestors, *handles.values(), job}:
                api.close(handle)


_TASK_QUERY = (
    "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); "
    "$s=New-Object -ComObject Schedule.Service; $s.Connect(); "
    "$t=$s.GetFolder('\\').GetTask('Pallium'); $a=$t.Definition.Actions; "
    "$instances=@($t.GetInstances(0)|ForEach-Object {[string]$_.InstanceGuid}); "
    "[pscustomobject]@{path=[string]$t.Path;name=[string]$t.Name;"
    "state=[int]$t.State;action_count=[int]$a.Count;action=[string]$a.Item(1).Path;"
    "arguments=[string]$a.Item(1).Arguments;cwd=[string]$a.Item(1).WorkingDirectory;"
    "retry=[int]$t.Definition.Settings.RestartCount;instances=$instances}|ConvertTo-Json -Compress"
)


def _task_info(deadline):
    result = subprocess.run(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", _TASK_QUERY],
        capture_output=True, text=True, encoding="utf-8", timeout=deadline.remaining(), creationflags=0x08000000,
    )
    deadline.remaining()
    if result.returncode != 0:
        raise Unknown("cannot verify exact registered managed task")
    task = json.loads(result.stdout)
    if (task.get("path") != "\\Pallium" or task.get("name") != "Pallium"
            or task.get("action_count") != 1 or not isinstance(task.get("instances"), list)):
        raise Unknown("registered task path/action/instance identity is ambiguous")
    return task


def _validate_task(manifest, task):
    if (task.get("path") != "\\Pallium" or task.get("name") != "Pallium"
            or task.get("action_count") != 1
            or Path(task.get("action", "")).name.casefold() != "wscript.exe"
            or task.get("arguments") != _task_arguments(manifest)
            or task.get("cwd") != manifest["cwd"] or task.get("retry") != 0
            or not isinstance(task.get("instances"), list) or len(task["instances"]) > 1):
        raise Unknown("legacy or mismatched exact task; separately approved installation required")


def _task_state(manifest, deadline):
    task = _task_info(deadline)
    _validate_task(manifest, task)
    if task["state"] in {1, 3} and task["instances"]:
        raise Unknown("task state contradicts retained running instance")
    return {1: "Disabled", 3: "Ready", 4: "Running"}.get(task["state"], "Unknown")


def _start_task(manifest, deadline):
    # Run the SAME registered task and return its exact instance, never bypass it.
    expected = json.dumps({"arguments": _task_arguments(manifest), "cwd": manifest["cwd"]})
    script = (
        "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); "
        "if(-not [Diagnostics.Stopwatch]::IsHighResolution) {throw 'QPC clock required'}; "
        "$s=New-Object -ComObject Schedule.Service; $s.Connect(); "
        "$t=$s.GetFolder('\\').GetTask('Pallium'); $a=$t.Definition.Actions; "
        "$e=$env:PALLIUM_CONTROL_EXPECTED|ConvertFrom-Json; "
        "if($t.Path -cne '\\Pallium' -or $a.Count -ne 1 -or "
        "[IO.Path]::GetFileName($a.Item(1).Path) -ine 'wscript.exe' -or "
        "$a.Item(1).Arguments -cne $e.arguments -or $a.Item(1).WorkingDirectory -cne $e.cwd -or "
        "$t.Definition.Settings.RestartCount -ne 0 -or $t.GetInstances(0).Count -ne 0) {throw 'task identity/settlement changed'}; "
        "if(([Diagnostics.Stopwatch]::GetTimestamp()/[double][Diagnostics.Stopwatch]::Frequency) -ge [double]::Parse($env:PALLIUM_CONTROL_DEADLINE,[Globalization.CultureInfo]::InvariantCulture)) {throw 'admission expired'}; "
        "$r=$t.Run([object[]]@($env:PALLIUM_CONTROL_DEADLINE)); "
        "[pscustomobject]@{path=[string]$r.Path;instance=[string]$r.InstanceGuid}|ConvertTo-Json -Compress"
    )
    deadline.remaining()
    result = subprocess.run(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        env={**os.environ, "PALLIUM_CONTROL_EXPECTED": expected,
             "PALLIUM_CONTROL_DEADLINE": format(deadline.end, ".17g")},
        capture_output=True, text=True, encoding="utf-8", creationflags=0x08000000,
    )
    # No subprocess timeout/kill for a mutating Scheduler call: retain its outcome.
    # It may return late. The observer independently gates application resume.
    result_value = json.loads(result.stdout) if result.returncode == 0 else None
    if (not isinstance(result_value, dict) or result_value.get("path") != "\\Pallium"
            or not result_value.get("instance")):
        raise Unknown("registered task start outcome unknown; no restoration")
    deadline.remaining()
    return result_value["instance"]


def _registered_home(deadline):
    task = _task_info(deadline)
    if (task.get("path") != "\\Pallium" or task.get("action_count") != 1
            or Path(task.get("action", "")).name.casefold() != "wscript.exe" or task.get("retry") != 0):
        raise Unknown("existing task is not a newly managed cooperative launcher")
    match = re.fullmatch(r'"([^"\r\n]+)" "\$\(Arg0\)"', task.get("arguments", ""))
    if match is None:
        raise Unknown("unsupported task action arguments")
    vbs = Path(match[1])
    text = deadline.read(lambda: vbs.read_text(encoding="utf-16"))
    match = re.search(r'--home\s+""([^"\r\n]+)""', text)
    if not text.startswith(MANAGED_MARKER) or not match:
        raise Unknown("unsupported legacy launcher; no stop or migration attempted")
    return Path(match[1])


def _pin(home, record, manifest, deadline, api):
    generation = record.get("generation", "")
    if (record.get("version") != 1 or record.get("manifest") != manifest
            or re.fullmatch("[0-9a-f]{32}", generation) is None
            or record.get("description") != _names(home, generation)
            or not isinstance(record.get("task_instance"), str) or not record["task_instance"]):
        raise Unknown("generation launch identity mismatch")
    handles = []
    try:
        for name in ("observer", "launcher"):
            identity = record[name]
            deadline.remaining()
            handle = api.process(identity["pid"])
            handles.append(handle)
            deadline.remaining()
            if deadline.read(lambda: api.identity(handle, identity["pid"])) != identity:
                raise Unknown("process identity changed")
        deadline.remaining()
        handles.append(api.job(record["description"]))
        deadline.remaining()
        ancestry = record.get("ancestry")
        if (not isinstance(ancestry, list) or not 2 <= len(ancestry) <= 16
                or ancestry[0] != record["observer"] or ancestry[-1] != record["launcher"]
                or len({item["pid"] for item in ancestry}) != len(ancestry)):
            raise Unknown("launcher ancestry receipt is incomplete")
        for identity in ancestry[1:-1]:
            deadline.remaining()
            handle = api.process(identity["pid"])
            handles.append(handle)
            deadline.remaining()
            if deadline.read(lambda: api.identity(handle, identity["pid"])) != identity:
                raise Unknown("launcher redirector identity changed")
        return handles
    except BaseException:
        for handle in handles:
            api.close(handle)
        raise


def _settle(home, record, manifest, deadline, api, *, pinned=None):
    handles = pinned if pinned is not None else _pin(home, record, manifest, deadline, api)
    try:
        if record.get("outcome") == "running":
            channel = StopChannel(record["description"], api=api)
            try:
                with api.mutex(record["description"] + "-spawn", deadline.remaining):
                    api.signal(channel.event)
            finally:
                channel.close()
        # The spawn mutex is released before every drain/receipt/Job wait.
        for handle in handles[:2] + handles[3:]:
            if not api.signaled(handle, deadline.remaining()):
                raise Unknown("observer/launcher still running; no replacement")
        terminal = deadline.read(lambda: _json(home / "run" / "windows-generation.json"))
        identity_keys = ("version", "generation", "description", "config", "manifest", "observer", "launcher", "ancestry", "supervisor", "task_instance")
        if any(terminal.get(key) != record.get(key) for key in identity_keys):
            raise Unknown("terminal receipt identity conflict")
        if terminal.get("empty") is not True or terminal.get("outcome") not in {"clean", "failed"}:
            raise Unknown("terminal outcome is unknown")
        exits = terminal.get("exits")
        if not isinstance(exits, dict) or not exits or any(type(code) is not int for code in exits.values()):
            raise Unknown("incomplete terminal process results")
        total, active = deadline.read(lambda: api.accounting(handles[2]))
        if active != 0 or terminal.get("total") != total or len(exits) != total:
            raise Unknown("entire owned Job/process set has not settled")
        if terminal["outcome"] == "clean" and any(code != 0 for code in exits.values()):
            raise Unknown("nonzero exit cannot be a clean shutdown")
        launcher_exits = [deadline.read(lambda: api.exit_code(handle)) for handle in handles[:2] + handles[3:]]
        if any(code is None for code in launcher_exits) or (terminal["outcome"] == "clean" and any(code != 0 for code in launcher_exits)):
            raise Unknown("observer/launcher exit status is unknown or contradicts clean receipt")
        if _task_state(manifest, deadline) not in {"Ready", "Disabled"}:
            raise Unknown("registered launcher task has not settled")
        return terminal
    finally:
        if pinned is None:
            for handle in handles:
                api.close(handle)


def _owned_ready(home, record, manifest, deadline, api, handles, ready):
    current = deadline.read(lambda: _json(home / "run" / "windows-generation.json"))
    for key in ("generation", "description", "config", "manifest", "observer", "launcher", "supervisor"):
        if current.get(key) != record.get(key):
            raise Unknown("generation changed during readiness")
    proof = current.get("api_ready")
    if not isinstance(proof, dict):
        return False
    instance = proof.get("public_instance")
    if not valid_service_instance(instance) or instance == proof.get("nonce"):
        return False
    identity = proof["identity"]
    deadline.remaining()
    api_handle = api.process(identity["pid"])
    supervisor = None
    stop_event = None
    try:
        deadline.remaining()
        supervisor = api.process(record["supervisor"]["pid"])
        stop_event = api.event(record["description"] + "-stop")
        deadline.remaining()
        def valid():
            token = _json(home / "run" / "api_token")
            return (token.get("nonce") == proof.get("nonce") and token.get("pid") == identity["pid"]
                    and token.get("bound") == {"generation": record["description"], "port": manifest["port"]}
                    and token.get("public_instance") == instance
                    and api.identity(api_handle, identity["pid"]) == identity
                    and api.identity(supervisor, record["supervisor"]["pid"]) == record["supervisor"]
                    and api.in_job(api_handle, handles[2]) and api.in_job(supervisor, handles[2])
                    and api.exit_code(api_handle) is None and api.exit_code(supervisor) is None
                    and api.exit_code(handles[0]) is None and not api.signaled(stop_event))
        if not deadline.read(valid):
            raise Unknown("API nonce/process ownership does not match this generation")
        result = deadline.read(lambda: ready(manifest["port"], deadline.remaining(), expected_instance=instance))
        if not deadline.read(valid):
            raise Unknown("API ownership changed during health probes")
        return result
    finally:
        api.close(api_handle)
        if supervisor is not None:
            api.close(supervisor)
        if stop_event is not None:
            api.close(stop_event)


def control(home, action, *, timeout=180, api=None, ready=None, absolute_deadline=None):
    deadline = Deadline(timeout, absolute=absolute_deadline)
    api = api or native()
    deadline.remaining()
    home = home if home is not None else _registered_home(deadline)
    home = deadline.read(lambda: home.resolve())
    deadline.read(lambda: api.private_home(home))
    manifest = deadline.read(lambda: _manifest(home))
    _apply_existing_home(home)
    deadline.read(lambda: _existing_store(home))
    config = deadline.read(lambda: _config_identity(home, manifest))
    path = home / "run" / "windows-generation.json"
    with api.mutex(_names(home), deadline.remaining):
        deadline.read(lambda: _existing_store(home))
        if deadline.read(lambda: _config_identity(home, manifest)) != config:
            raise Unknown("configuration changed before controller ownership")
        _task_state(manifest, deadline)
        try:
            record = deadline.read(lambda: _json(path))
        except FileNotFoundError:
            raise Unknown("no retained generation custody; manual setup/recovery is separate") from None
        if record.get("config") != config:
            raise Unknown("effective service configuration changed; no stop/replacement")
        task = _task_info(deadline)
        _validate_task(manifest, task)
        if task["instances"] and task["instances"] != [record.get("task_instance")]:
            raise Unknown("registered running instance differs from generation custody")
        old_pins = _pin(home, record, manifest, deadline, api)
        retained_failed = []
        try:
            if action == "start" and record.get("outcome") == "running":
                if ready is not None and _owned_ready(home, record, manifest, deadline, api, old_pins, ready):
                    return "already running"
                raise Unknown("existing generation running/unready; no replacement")
            settled = _settle(home, record, manifest, deadline, api, pinned=old_pins)
            if action == "stop":
                return "stopped; later independent start after custody loss requires manual recovery"
            if action not in {"start", "restart"}:
                raise ValueError("unsupported lifecycle action")
            # Custody is retained through the continuous settlement/replacement transaction.
            deadline.remaining()
            path.unlink()
            old_failed = settled.get("outcome") == "failed"
            for attempt in range(2):
                instance = _start_task(manifest, deadline)
                pinned = None
                try:
                    while True:
                        deadline.remaining()
                        try:
                            current = deadline.read(lambda: _json(path))
                        except FileNotFoundError:
                            current = None
                        if current is not None:
                            if current.get("config") != config or current.get("task_instance") != instance:
                                raise Unknown("new generation task/configuration identity mismatch")
                            if pinned is None:
                                pinned = _pin(home, current, manifest, deadline, api)
                            if current.get("outcome") == "running" and ready is not None and _owned_ready(home, current, manifest, deadline, api, pinned, ready):
                                return "recovered" if attempt or old_failed else "started"
                            if api.exit_code(pinned[0]) is not None:
                                terminal = _settle(home, current, manifest, deadline, api, pinned=pinned)
                                if attempt or terminal.get("outcome") != "failed":
                                    raise Unknown("restoration unavailable or exhausted")
                                deadline.remaining()
                                path.unlink()
                                # Keep failed NEW custody through restoration admission too.
                                retained_failed.extend(pinned)
                                pinned = None
                                break
                        time.sleep(min(0.05, deadline.remaining()))
                finally:
                    if pinned is not None:
                        for handle in pinned:
                            api.close(handle)
        finally:
            for handle in old_pins + retained_failed:
                api.close(handle)
    raise Unknown("service did not start")


def main(args=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("observe", "start", "stop", "restart"))
    parser.add_argument("--home")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--deadline", type=float)
    parsed = parser.parse_args(args)
    try:
        home = Path(parsed.home) if parsed.home else None
        if parsed.action == "observe":
            if home is None:
                raise Unknown("observer requires an explicit home")
            return observe(home, absolute_deadline=parsed.deadline)
        from app.cli.service import _managed_ready
        print(control(home, parsed.action, timeout=parsed.timeout, ready=_managed_ready, absolute_deadline=parsed.deadline))
        return 0
    except (Unknown, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(f"Windows lifecycle UNKNOWN/refused: {exc}", file=sys.stderr)
        if home is not None:
            print(f"Pallium log: {home / 'logs' / 'pallium.log'}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
