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
import threading
import time


GENERATION_ENV = "PALLIUM_WINDOWS_GENERATION"
MANAGED_MARKER = "' Pallium cooperative launcher v1"
_STILL_ACTIVE = 259
_NATIVE = None


class Unknown(RuntimeError):
    """Custody or settlement could not be positively established."""


class FailedBeforeLaunch(Unknown):
    """CreateProcess failed without creating an application process."""


class Deadline:
    def __init__(self, seconds, *, clock=time.monotonic):
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("operation budget must be finite and positive")
        self.clock = clock
        self.end = clock() + seconds

    def remaining(self):
        remaining = self.end - self.clock()
        if remaining <= 0:
            raise Unknown("operation deadline elapsed; no replacement permitted")
        return remaining

    def read(self, operation):
        # Timed-out reads may finish later; callers must never admit a later launch.
        done = threading.Event()
        result = []

        def read():
            try:
                result.append((True, operation()))
            except BaseException as exc:
                result.append((False, exc))
            finally:
                done.set()

        threading.Thread(target=read, daemon=True).start()
        if not done.wait(self.remaining()):
            raise Unknown("metadata read timed out; no replacement permitted")
        self.remaining()
        if not result[0][0]:
            raise result[0][1]
        return result[0][1]


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
            result = self.k.WaitForSingleObject(handle, max(1, math.ceil(seconds * 1000)))
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
        finally:
            if attributes_initialized:
                self.k.DeleteProcThreadAttributeList(attribute_buffer)
            for handle in inherited:
                self.close(handle)
            if null_input is not None:
                null_input.close()
        process = Process(self, info.process, info.pid)
        process.thread = info.thread
        return process

    def resume(self, process):
        if self.k.ResumeThread(process.thread) == 0xFFFFFFFF:
            raise Unknown("could not resume contained process")
        self.close(process.thread)
        process.thread = None


class Process:
    def __init__(self, api, handle, pid):
        self.api, self.handle, self.pid = api, handle, pid
        self.returncode = None
        self.thread = None

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
            # Inherited Job membership is established by Windows before child code runs.
            process = self.api.spawn(command, **kwargs)
            attempts.append(process)
            if stop():
                raise Unknown("stop raced suspended launch; process retained without resume")
            self.api.resume(process)
            return process

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
                              if key.startswith("PALLIUM_") and key != GENERATION_ENV}, sort_keys=True).encode())
    return digest.hexdigest()


def _existing_store(home):
    from app.cli.service import _apply_home_env
    from app.config import AppConfig
    from app.codex_wake_lifecycle import _paths, _marker_present
    os.environ["PALLIUM_HOME"] = str(home)
    _apply_home_env(home)
    paths = _paths(AppConfig.from_env())
    if paths is not None and (not all(path.is_file() for path in paths[:2]) or not _marker_present(paths[1])):
        raise Unknown("existing live pair and wake authority required; setup/import/restore is separate")


def _manifest(home):
    value = _json(home / "run" / "windows-launch.json")
    if value.get("version") != 1 or value.get("home") != str(home) or not 1 <= value.get("port", 0) <= 65535:
        raise Unknown("unsupported managed launcher metadata")
    if value.get("python") != sys.executable or value.get("cwd") != str(Path.cwd()):
        raise Unknown("interpreter or working directory differs from managed launcher")
    return value


def observe(home, *, api=None):
    api = api or native()
    api.private_home(home)
    manifest = _manifest(home)
    _existing_store(home)
    config = _config_identity(home, manifest)
    with api.mutex(_names(home, "owner"), 1):
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
        record = {"version": 1, "generation": generation, "description": description,
                  "config": config, "manifest": manifest,
                  "observer": api.identity(observer, os.getpid()),
                  "launcher": launcher_identity, "ancestry": ancestry, "outcome": "running"}
        if Path(record["launcher"]["image"]).name.casefold() != "wscript.exe":
            raise Unknown("managed observer must have the actual WScript launcher as parent")
        try:
            _write(previous, record)
            environment = {**os.environ, GENERATION_ENV: description}
            command = [manifest["python"], "-m", "app.run", "service", "run", "--home", str(home), "--port", str(manifest["port"])]
            process = api.spawn(command, cwd=manifest["cwd"], env=environment, job=job)
            handles[process.pid] = process.handle
            record["supervisor"] = api.identity(process.handle, process.pid)
            _write(previous, record)
            api.contain(job, process)
            api.resume(process)
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
                if active == 0:
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


def _task_info(deadline):
    result = subprocess.run(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
         "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); "
         "$t=Get-ScheduledTask -TaskName Pallium -ErrorAction Stop; "
         "[pscustomobject]@{state=[string]$t.State;action=$t.Actions[0].Execute;arguments=$t.Actions[0].Arguments;"
         "retry=$t.Settings.RestartCount}|ConvertTo-Json -Compress"],
        capture_output=True, text=True, encoding="utf-8", timeout=deadline.remaining(), creationflags=0x08000000,
    )
    deadline.remaining()
    if result.returncode != 0:
        raise Unknown("cannot verify registered managed task")
    return json.loads(result.stdout)


def _task_state(manifest, deadline):
    task = _task_info(deadline)
    if (Path(task.get("action", "")).name.casefold() != "wscript.exe"
            or task.get("arguments", "").strip('"') != manifest["vbs"] or task.get("retry") != 0):
        raise Unknown("legacy or mismatched task; separately approved installation required")
    return task["state"]


def _registered_home(deadline):
    task = _task_info(deadline)
    if Path(task.get("action", "")).name.casefold() != "wscript.exe" or task.get("retry") != 0:
        raise Unknown("existing task is not a newly managed cooperative launcher")
    vbs = Path(task["arguments"].strip('"'))
    text = deadline.read(lambda: vbs.read_text(encoding="utf-16"))
    match = re.search(r'--home\s+""([^"\r\n]+)""', text)
    if not text.startswith(MANAGED_MARKER) or not match:
        raise Unknown("unsupported legacy launcher; no stop or migration attempted")
    return Path(match[1])


def _pin(home, record, manifest, deadline, api):
    generation = record.get("generation", "")
    if (record.get("version") != 1 or record.get("manifest") != manifest
            or re.fullmatch("[0-9a-f]{32}", generation) is None
            or record.get("description") != _names(home, generation)):
        raise Unknown("generation launch identity mismatch")
    handles = []
    try:
        for name in ("observer", "launcher"):
            identity = record[name]
            handle = deadline.read(lambda: api.process(identity["pid"]))
            handles.append(handle)
            if deadline.read(lambda: api.identity(handle, identity["pid"])) != identity:
                raise Unknown("process identity changed")
        handles.append(deadline.read(lambda: api.job(record["description"])))
        ancestry = record.get("ancestry")
        if (not isinstance(ancestry, list) or not 2 <= len(ancestry) <= 16
                or ancestry[0] != record["observer"] or ancestry[-1] != record["launcher"]
                or len({item["pid"] for item in ancestry}) != len(ancestry)):
            raise Unknown("launcher ancestry receipt is incomplete")
        for identity in ancestry[1:-1]:
            handle = deadline.read(lambda: api.process(identity["pid"]))
            handles.append(handle)
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
                with api.mutex(record["description"] + "-spawn", deadline.remaining()):
                    api.signal(channel.event)
            finally:
                channel.close()
        # The spawn mutex is released before every drain/receipt/Job wait.
        for handle in handles[:2] + handles[3:]:
            if not api.signaled(handle, deadline.remaining()):
                raise Unknown("observer/launcher still running; no replacement")
        terminal = deadline.read(lambda: _json(home / "run" / "windows-generation.json"))
        identity_keys = ("version", "generation", "description", "config", "manifest", "observer", "launcher", "ancestry", "supervisor")
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


def control(home, action, *, timeout=180, api=None, ready=None):
    deadline = Deadline(timeout)
    api = api or deadline.read(native)
    home = home if home is not None else _registered_home(deadline)
    home = deadline.read(lambda: home.resolve())
    deadline.read(lambda: api.private_home(home))
    manifest = deadline.read(lambda: _manifest(home))
    deadline.read(lambda: _existing_store(home))
    config = deadline.read(lambda: _config_identity(home, manifest))
    path = home / "run" / "windows-generation.json"
    with api.mutex(_names(home), deadline.remaining()):
        _task_state(manifest, deadline)
        try:
            record = deadline.read(lambda: _json(path))
        except FileNotFoundError:
            # Only explicit installation can perform the first launch. Missing custody
            # during ordinary control can also mean observer loss; it is never absence proof.
            raise Unknown("no owned generation receipt; initial setup/manual recovery is separate") from None
        if record.get("config") != config:
            raise Unknown("effective service configuration changed; no stop/replacement")
        old_failed = record.get("outcome") == "failed"
        if action == "start" and record.get("outcome") == "running":
            pinned = _pin(home, record, manifest, deadline, api)
            try:
                if (api.exit_code(pinned[0]) is None and ready is not None
                        and deadline.read(lambda: ready(manifest["port"], deadline.remaining()))):
                    return "already running"
                raise Unknown("existing generation running/unready; no replacement")
            finally:
                for handle in pinned:
                    api.close(handle)
        _settle(home, record, manifest, deadline, api)
        if action == "stop":
            return "stopped"
        if action not in {"start", "restart"}:
            raise ValueError("unsupported lifecycle action")
        # Only positively settled records are removed, immediately before the next launch.
        # No later controller treats a missing receipt as permission to start.
        deadline.read(path.unlink)
        launch = ["wscript.exe", manifest["vbs"]]
        for attempt in range(2):
            deadline.remaining()
            try:
                process = api.spawn(launch, cwd=manifest["cwd"], env=os.environ.copy())
            except FailedBeforeLaunch:
                if attempt:
                    raise
                continue
            pinned = None
            try:
                deadline.remaining()
                api.resume(process)
                while True:
                    deadline.remaining()
                    try:
                        current = deadline.read(lambda: _json(path))
                    except FileNotFoundError:
                        current = None
                    if current is not None and current.get("config") != config:
                        raise Unknown("new generation configuration mismatch")
                    if current is not None and pinned is None:
                        pinned = _pin(home, current, manifest, deadline, api)
                    if current is not None and ready is not None and deadline.read(lambda: ready(manifest["port"], deadline.remaining())):
                        if (current.get("outcome") == "running" and process.poll() is None
                                and api.exit_code(pinned[0]) is None):
                            return "recovered" if attempt or old_failed else "started"
                    if process.poll() is not None:
                        if current is None:
                            raise Unknown("launcher exited without custody/terminal receipt")
                        _settle(home, current, manifest, deadline, api, pinned=pinned)
                        if attempt:
                            raise Unknown("one restoration attempt exhausted")
                        deadline.read(path.unlink)
                        break
                    time.sleep(min(0.05, deadline.remaining()))
            finally:
                api.close(process.handle)
                if getattr(process, "thread", None) is not None:
                    api.close(process.thread)
                if pinned is not None:
                    for handle in pinned:
                        api.close(handle)
    raise Unknown("service did not start")


def main(args=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("observe", "start", "stop", "restart"))
    parser.add_argument("--home")
    parser.add_argument("--timeout", type=float, default=180)
    parsed = parser.parse_args(args)
    try:
        home = Path(parsed.home) if parsed.home else None
        if parsed.action == "observe":
            if home is None:
                raise Unknown("observer requires an explicit home")
            return observe(home)
        from app.cli.service import _service_ready
        print(control(home, parsed.action, timeout=parsed.timeout, ready=_service_ready))
        return 0
    except (Unknown, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(f"Windows lifecycle UNKNOWN/refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
