"""Windows-only private shadow and inventory channels. Never consumes Relay work."""

from __future__ import annotations

import json
import hashlib
import logging
import os
import secrets
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

MAX_MESSAGE = 32 * 1024
EXCHANGE_SECONDS = 3.0
GRANT_SECONDS = 300.0
LEASE_SECONDS = 15.0
FIRST_PIPE_INSTANCE = 0x00080000  # Windows SDK FILE_FLAG_FIRST_PIPE_INSTANCE.
TRUSTED_INSTALLER_SID = "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"
_retained: list[object] = []
_native_uncertain = False
_policy_tokens: dict[object, tuple] = {}
_INVENTORY_FAILURE_STAGES = frozenset({
    "transfer-authority", "native-open", "native-peer", "before-source", "source-exit",
    "before-proof", "exit-proof", "after-proof",
    *(f"{phase}-{action}" for phase in ("before", "after")
      for action in ("authority", "peer", "write", "read", "validate", "result")),
    *(f"{phase}-validate-{check}" for phase in ("before", "after")
      for check in ("envelope", "version", "id-type", "id-match", "result-type",
                    "result-fields", "tools-type", "tools-limit", "tool-type", "tool-fields",
                    "tool-name", "tool-duplicate", "schema-type", "schema-object",
                    "error-invalid-request", "error-tool-list")),
})
_INVENTORY_FAILURE_CATEGORIES = frozenset({
    "busy", "deadline", "file-unavailable", "file-write-failed", "invalid-message", "invalid-path",
    "invalid-policy", "invalid-policy-lock", "invalid-response", "message-limit", "native-failed",
    "path-unavailable", "peer-gone", "peer-mismatch", "peer-unavailable", "policy-busy",
    "policy-changed", "policy-inactive", "stopped", "transport-failed", "unsafe-acl", "unsafe-owner",
    "unsafe-path", "unsupported-acl",
})


class _InventoryLogHandler(logging.Handler):
    def emit(self, record) -> None:
        try:
            sys.stderr.write(self.format(record) + "\n")
            sys.stderr.flush()
        except Exception:
            pass  # Never use logging's traceback fallback in a native exception handler.


_log = logging.Logger(__name__, logging.WARNING)
_log.propagate = False
_log.addHandler(_InventoryLogHandler())


class ShadowUnavailable(RuntimeError):
    """Only fixed categories leave this module; never native errors/paths."""

    def __init__(self, category: str, *, lock_contended: bool = False):
        super().__init__(category)
        self.category = category
        self.lock_contended = lock_contended


def _native():
    if sys.platform != "win32":
        raise ShadowUnavailable("unsupported-platform")
    try:
        import pywintypes
        import win32api
        import win32con
        import win32event
        import win32file
        import win32pipe
        import win32process
        import win32security
    except ImportError:
        raise ShadowUnavailable("native-unavailable") from None
    modules = SimpleNamespace(
        types=pywintypes, api=win32api, con=win32con, event=win32event,
        file=win32file, pipe=win32pipe, process=win32process, security=win32security,
    )
    required = (
        (win32pipe, ("CreateNamedPipe", "GetNamedPipeClientProcessId",
                     "GetNamedPipeServerProcessId", "PIPE_REJECT_REMOTE_CLIENTS")),
        (win32file, ("CreateDirectory", "CancelIo", "GetOverlappedResult", "GetDriveType",
                     "FILE_FLAG_OPEN_REPARSE_POINT", "SECURITY_IDENTIFICATION")),
        (win32security, ("GetSecurityInfo", "GetNamedSecurityInfo", "OpenProcessToken",
                         "GetTokenInformation", "ConvertStringSecurityDescriptorToSecurityDescriptor")),
        (win32process, ("GetProcessTimes",)),
    )
    if any(not hasattr(module, name) for module, names in required for name in names):
        raise ShadowUnavailable("native-unavailable")
    return modules


def native_available() -> bool:
    if _native_uncertain:
        return False
    try:
        _native()
        return True
    except Exception:
        return False


def _close(handle) -> None:
    if handle is not None:
        try:
            handle.Close()
        except (AttributeError, OSError):
            try:
                _native().file.CloseHandle(handle)
            except Exception:
                pass


def _sid(w, process) -> str:
    token = w.security.OpenProcessToken(process, w.con.TOKEN_QUERY)
    try:
        sid, _attributes = w.security.GetTokenInformation(token, w.security.TokenUser)
        return w.security.ConvertSidToStringSid(sid)
    finally:
        _close(token)


def _self_sid(w) -> str:
    return _sid(w, w.api.GetCurrentProcess())


def _security_attributes(w, sid: str, *, directory: bool = False):
    flags = "OICI" if directory else ""
    descriptor = w.security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        f"D:P(A;{flags};FA;;;{sid})(A;{flags};FA;;;SY)", 1,
    )
    attrs = w.types.SECURITY_ATTRIBUTES()
    attrs.SECURITY_DESCRIPTOR = descriptor
    attrs.bInheritHandle = False
    return attrs


def _validate_descriptor(w, descriptor, sid: str, *, private: bool) -> None:
    owner = descriptor.GetSecurityDescriptorOwner()
    if private and w.security.ConvertSidToStringSid(owner) != sid:
        raise ShadowUnavailable("unsafe-owner")
    dacl = descriptor.GetSecurityDescriptorDacl()
    if dacl is None:
        raise ShadowUnavailable("unsafe-acl")
    control, _ = descriptor.GetSecurityDescriptorControl()
    if private and not control & 0x1000:  # SE_DACL_PROTECTED.
        raise ShadowUnavailable("unsafe-acl")
    allowed = {sid, "S-1-5-18"}
    if w.security.ConvertSidToStringSid(owner) == sid:
        allowed.add("S-1-3-4")  # OWNER RIGHTS grants only this verified owner.
    if not private:
        allowed.add("S-1-5-32-544")  # Administrators are outside the threat boundary.
        # Windows system-volume roots commonly have this privileged OS owner.
        if w.security.ConvertSidToStringSid(owner) not in allowed | {TRUSTED_INSTALLER_SID}:
            raise ShadowUnavailable("unsafe-owner")
    dangerous = 0x00000040 | 0x00010000 | 0x00040000 | 0x00080000  # DELETE_CHILD/SELF, WRITE_DAC/OWNER.
    for index in range(dacl.GetAceCount()):
        (kind, flags), mask, principal = dacl.GetAce(index)
        if flags & 0x08:  # INHERIT_ONLY does not grant access to this object.
            continue
        if kind == 1:  # An ordinary deny ACE cannot broaden access.
            continue
        if kind != 0:
            raise ShadowUnavailable("unsupported-acl")
        value = w.security.ConvertSidToStringSid(principal)
        if value not in allowed and (private or mask & (dangerous | 0x10000000)):
            raise ShadowUnavailable("unsafe-acl")


def _check_path(w, path: Path, sid: str, *, private: bool = True) -> None:
    if not path.is_absolute() or w.file.GetDriveType(path.anchor) != w.con.DRIVE_FIXED:
        raise ShadowUnavailable("invalid-path")
    try:
        attrs = w.file.GetFileAttributes(str(path))
        if attrs & w.con.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ShadowUnavailable("unsafe-path")
        descriptor = w.security.GetNamedSecurityInfo(
            str(path), w.security.SE_FILE_OBJECT,
            w.security.OWNER_SECURITY_INFORMATION | w.security.DACL_SECURITY_INFORMATION,
        )
        _validate_descriptor(w, descriptor, sid, private=private)
    except ShadowUnavailable:
        raise
    except Exception:
        raise ShadowUnavailable("path-unavailable") from None


def _secure_directory(w, path: Path, sid: str) -> None:
    if not path.is_absolute() or w.file.GetDriveType(path.anchor) != w.con.DRIVE_FIXED:
        raise ShadowUnavailable("invalid-path")
    missing = []
    cursor = path
    while not cursor.exists():
        missing.append(cursor)
        if cursor.parent == cursor:
            raise ShadowUnavailable("invalid-path")
        cursor = cursor.parent
    for ancestor in (cursor, *cursor.parents):
        _check_path(w, ancestor, sid, private=False)
    for directory in reversed(missing):
        try:
            w.file.CreateDirectory(str(directory), _security_attributes(w, sid, directory=True))
        except Exception:
            raise ShadowUnavailable("directory-conflict") from None
        _check_path(w, directory, sid)
    _check_path(w, path, sid)


def _check_private_parent(w, path: Path, sid: str) -> None:
    _check_path(w, path.parent, sid)
    for ancestor in path.parent.parents:
        _check_path(w, ancestor, sid, private=False)


def _lock_file(w, path: Path, sid: str):
    try:
        _check_private_parent(w, path, sid)
        attrs = _security_attributes(w, sid)
        try:
            handle = w.file.CreateFile(
                str(path), w.con.GENERIC_READ | w.con.GENERIC_WRITE, 0,
                attrs, w.con.OPEN_ALWAYS,
                w.con.FILE_ATTRIBUTE_NORMAL | w.file.FILE_FLAG_OPEN_REPARSE_POINT, None,
            )
        except w.types.error as exc:
            if getattr(exc, "winerror", None) == 32:
                raise ShadowUnavailable("owner-busy", lock_contended=True) from None
            raise
        _check_path(w, path, sid)
        return handle
    except ShadowUnavailable:
        _close(locals().get("handle"))
        raise
    except Exception:
        _close(locals().get("handle"))
        raise ShadowUnavailable("owner-busy") from None


class _PolicyLock:
    def __init__(self, path: Path, sid: str, handle):
        self.path, self.sid, self.handle = path, sid, handle
        self.owner = threading.get_ident()

    def check(self, w, path: Path, sid: str) -> None:
        issued = _policy_tokens.get(self)
        if (issued is None or self.handle is not issued[2]
                or (self.path, self.sid, self.owner) != (issued[0], issued[1], issued[3])
                or self.owner != threading.get_ident()
                or issued[0] != path.parent / "policy.lock" or issued[1] != sid):
            raise ShadowUnavailable("invalid-policy-lock")
        try:
            w.file.GetFileInformationByHandle(self.handle)
        except Exception:
            raise ShadowUnavailable("invalid-policy-lock") from None

    def Close(self) -> None:
        issued = _policy_tokens.pop(self, None)
        if issued is not None:
            _close(issued[2])
        self.handle = None


def _policy_lock(w, path: Path, sid: str, deadline: float | None = None) -> _PolicyLock:
    end = min(deadline, time.monotonic() + .2) if deadline is not None else time.monotonic() + .2
    while True:
        if time.monotonic() >= end:
            raise ShadowUnavailable("policy-busy")
        try:
            handle = _lock_file(w, path.parent / "policy.lock", sid)
            if time.monotonic() >= end:
                _close(handle)
                raise ShadowUnavailable("policy-busy")
            token = _PolicyLock(path.parent / "policy.lock", sid, handle)
            _policy_tokens[token] = (token.path, token.sid, token.handle, token.owner)
            return token
        except ShadowUnavailable as exc:
            if not exc.lock_contended:
                raise
            time.sleep(min(.005, max(0, end - time.monotonic())))


def _read_private(w, path: Path, sid: str, *, policy_lock: _PolicyLock | None = None,
                  deadline: float | None = None) -> bytes:
    if policy_lock is not None:
        if path.name != "policy.json" or type(policy_lock) is not _PolicyLock:
            raise ShadowUnavailable("invalid-policy-lock")
        policy_lock.check(w, path, sid)
    elif path.name == "policy.json":
        lock = _policy_lock(w, path, sid, deadline)
        try:
            return _read_private(w, path, sid, policy_lock=lock, deadline=deadline)
        finally:
            _close(lock)
    handle = None
    try:
        _check_private_parent(w, path, sid)
        _check_path(w, path, sid)
        handle = w.file.CreateFile(
            str(path), w.con.GENERIC_READ,
            w.con.FILE_SHARE_READ | w.con.FILE_SHARE_DELETE, None, w.con.OPEN_EXISTING,
            w.con.FILE_ATTRIBUTE_NORMAL | w.file.FILE_FLAG_OPEN_REPARSE_POINT, None,
        )
        descriptor = w.security.GetSecurityInfo(
            handle, w.security.SE_FILE_OBJECT,
            w.security.OWNER_SECURITY_INFORMATION | w.security.DACL_SECURITY_INFORMATION,
        )
        _validate_descriptor(w, descriptor, sid, private=True)
        _, data = w.file.ReadFile(handle, MAX_MESSAGE + 1)
        if len(data) > MAX_MESSAGE:
            raise ShadowUnavailable("message-limit")
        return bytes(data)
    except ShadowUnavailable:
        raise
    except Exception:
        raise ShadowUnavailable("file-unavailable") from None
    finally:
        _close(handle)


def _atomic_private(w, path: Path, sid: str, data: bytes, *, policy_lock: _PolicyLock | None = None,
                    deadline: float | None = None) -> None:
    if len(data) > MAX_MESSAGE:
        raise ShadowUnavailable("message-limit")
    if policy_lock is not None:
        if path.name != "policy.json" or type(policy_lock) is not _PolicyLock:
            raise ShadowUnavailable("invalid-policy-lock")
        policy_lock.check(w, path, sid)
    elif path.name == "policy.json":
        lock = _policy_lock(w, path, sid, deadline)
        try:
            return _atomic_private(w, path, sid, data, policy_lock=lock, deadline=deadline)
        finally:
            _close(lock)
    _check_private_parent(w, path, sid)
    if path.exists():
        _check_path(w, path, sid)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(12)}.tmp")
    handle = None
    try:
        handle = w.file.CreateFile(
            str(temporary), w.con.GENERIC_WRITE, 0, _security_attributes(w, sid),
            w.con.CREATE_NEW, w.con.FILE_ATTRIBUTE_NORMAL, None,
        )
        _, written = w.file.WriteFile(handle, data)
        if written != len(data):
            raise ShadowUnavailable("file-write-failed")
        w.file.FlushFileBuffers(handle)
        _close(handle)
        handle = None
        os.replace(temporary, path)
    except ShadowUnavailable:
        raise
    except Exception:
        raise ShadowUnavailable("file-write-failed") from None
    finally:
        _close(handle)
        if temporary.exists():
            # Exact exclusively created file, inside the protected directory.
            temporary.unlink()


def _json(raw: bytes, *, limit: int = MAX_MESSAGE) -> dict:
    if not raw or len(raw) > limit:
        raise ShadowUnavailable("message-limit")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ShadowUnavailable("invalid-message")
            result[key] = value
        return result

    def constant(_value):
        raise ShadowUnavailable("invalid-message")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, ValueError, RecursionError):
        raise ShadowUnavailable("invalid-message") from None
    if not isinstance(value, dict):
        raise ShadowUnavailable("invalid-message")
    return value


def _text(value) -> bool:
    return isinstance(value, str) and value == value.strip() and 0 < len(value) <= 255 and value.isprintable()


def _integer(value, minimum=0) -> bool:
    return type(value) is int and minimum <= value <= 2**31 - 1


@dataclass(frozen=True)
class ShadowPolicy:
    controller_thread_ref: str
    recipient_endpoint_id: str
    recipient_session_ref: str
    recipient_container_ref: str
    recipient_scope_generation: int
    revision: int
    expires_at: datetime
    revoked: bool
    enabled: bool

    @classmethod
    def parse(cls, raw: bytes) -> "ShadowPolicy":
        value = _json(raw)
        fields = {
            "version", "controller_runtime", "controller_thread_ref", "recipient_runtime",
            "recipient_endpoint_id", "recipient_session_ref", "recipient_container_ref",
            "recipient_scope_generation", "action", "revision", "expires_at", "revoked", "enabled",
        }
        if set(value) != fields or value["version"] != 1 or type(value["version"]) is not int:
            raise ShadowUnavailable("invalid-policy")
        if value["controller_runtime"] != "codex" or value["recipient_runtime"] != "codex" or value["action"] != "shadow-only":
            raise ShadowUnavailable("invalid-policy")
        identifiers = ("controller_thread_ref", "recipient_endpoint_id", "recipient_session_ref", "recipient_container_ref")
        if any(not _text(value[name]) for name in identifiers):
            raise ShadowUnavailable("invalid-policy")
        if not value["recipient_endpoint_id"].startswith("relay-session-"):
            raise ShadowUnavailable("invalid-policy")
        if not _integer(value["recipient_scope_generation"]) or not _integer(value["revision"], 1):
            raise ShadowUnavailable("invalid-policy")
        if type(value["revoked"]) is not bool or type(value["enabled"]) is not bool:
            raise ShadowUnavailable("invalid-policy")
        try:
            expires = datetime.fromisoformat(value["expires_at"].replace("Z", "+00:00"))
            if expires.tzinfo is None or expires.utcoffset().total_seconds() != 0:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise ShadowUnavailable("invalid-policy") from None
        return cls(*(value[name] for name in identifiers), value["recipient_scope_generation"],
                   value["revision"], expires, value["revoked"], value["enabled"])

    def valid(self, now: datetime) -> bool:
        return self.enabled and not self.revoked and now < self.expires_at


def shadow_directory(home: Path | None = None) -> Path:
    home = home if home is not None else Path(os.environ.get("PALLIUM_HOME", str(Path.home() / ".pallium")))
    if not home.is_absolute():
        raise ShadowUnavailable("invalid-path")
    return home / "config" / "codex-shadow"


def provision_policy(source: Path, home: Path | None = None, *, expected_revision: int = 0) -> None:
    """Only a deliberate CLI operation provisions policy; never ordinary setup."""
    if not _integer(expected_revision):
        raise ShadowUnavailable("invalid-revision")
    try:
        with source.open("rb") as stream:
            raw = stream.read(MAX_MESSAGE + 1)
    except OSError:
        raise ShadowUnavailable("policy-unavailable") from None
    policy = ShadowPolicy.parse(raw)
    w = _native()
    sid = _self_sid(w)
    directory = shadow_directory(home)
    _secure_directory(w, directory, sid)
    lock = _policy_lock(w, directory / "policy.json", sid)
    try:
        destination = directory / "policy.json"
        previous = ShadowPolicy.parse(_read_private(w, destination, sid, policy_lock=lock)).revision if destination.exists() else 0
        if previous != expected_revision or policy.revision != previous + 1:
            raise ShadowUnavailable("revision-conflict")
        _atomic_private(w, destination, sid, raw, policy_lock=lock)
    finally:
        _close(lock)


class _Peer:
    def __init__(self, w, pid: int, sid: str, creation: str | None = None):
        self.w = w
        self.handle = None
        try:
            self.handle = w.api.OpenProcess(0x00101000, False, pid)  # SYNCHRONIZE | QUERY_LIMITED_INFORMATION.
            self.creation = w.process.GetProcessTimes(self.handle)["CreationTime"].isoformat()
            if _sid(w, self.handle) != sid or (creation is not None and self.creation != creation):
                raise ShadowUnavailable("peer-mismatch")
            self.pid = pid
            self.check()
        except ShadowUnavailable:
            self.close()
            raise
        except Exception:
            self.close()
            raise ShadowUnavailable("peer-unavailable") from None

    def check(self) -> None:
        if self.w.event.WaitForSingleObject(self.handle, 0) != self.w.event.WAIT_TIMEOUT:
            raise ShadowUnavailable("peer-gone")

    def close(self) -> None:
        _close(self.handle)
        self.handle = None


class _PipeIO:
    """All I/O/cancellation is owned by one dedicated daemon worker."""

    def __init__(self, w, handle, stop: threading.Event):
        self.w, self.handle, self.stop = w, handle, stop
        self.unresolved = False

    def _operation(self, operation, deadline: float, keepalive=None):
        w = self.w
        ov = w.types.OVERLAPPED()
        ov.hEvent = w.event.CreateEvent(None, True, False, None)
        buffer = None
        pending = False
        completed = False
        try:
            if self.stop.is_set() or time.monotonic() >= deadline:
                raise ShadowUnavailable("stopped" if self.stop.is_set() else "deadline")
            try:
                code, buffer = operation(ov)
            except w.types.error as exc:
                if getattr(exc, "winerror", None) == 535:  # ERROR_PIPE_CONNECTED.
                    completed = True
                    return 0, None
                raise
            if code not in (0, 997):  # ERROR_IO_PENDING.
                completed = True
                raise ShadowUnavailable("transport-failed")
            pending = code == 997
            while pending:
                if self.stop.is_set() or time.monotonic() >= deadline:
                    raise ShadowUnavailable("stopped" if self.stop.is_set() else "deadline")
                wait = min(50, max(1, int((deadline - time.monotonic()) * 1000)))
                outcome = w.event.WaitForSingleObject(ov.hEvent, wait)
                if outcome == w.event.WAIT_OBJECT_0:
                    break
                if outcome != w.event.WAIT_TIMEOUT:
                    raise ShadowUnavailable("transport-failed")
            try:
                count = w.file.GetOverlappedResult(self.handle, ov, False)
            except w.types.error as exc:
                # Known terminal pipe results prove completion; unknown API failures do not.
                completed = getattr(exc, "winerror", None) in {38, 109, 232, 233, 234, 995}
                raise
            completed = True
            return count, buffer
        except ShadowUnavailable:
            raise
        except Exception:
            # Native errors are bounded categories, never model-visible stderr.
            raise ShadowUnavailable("transport-failed") from None
        finally:
            if pending and not completed:
                try:
                    w.file.CancelIo(self.handle)
                    if w.event.WaitForSingleObject(ov.hEvent, 100) == w.event.WAIT_OBJECT_0:
                        try:
                            w.file.GetOverlappedResult(self.handle, ov, False)
                            completed = True
                        except w.types.error as exc:
                            completed = getattr(exc, "winerror", None) in {38, 109, 232, 233, 234, 995}
                except Exception:
                    pass
                if not completed:
                    global _native_uncertain
                    _native_uncertain = True
                    self.unresolved = True
                    _retained.append((self, ov, buffer, keepalive))
            if not self.unresolved:
                _close(ov.hEvent)

    def accept(self, deadline: float) -> None:
        def connect(ov):
            code = self.w.pipe.ConnectNamedPipe(self.handle, ov)
            return code or 0, None
        self._operation(connect, deadline)

    def read(self, deadline: float) -> dict:
        count, buffer = self._operation(
            lambda ov: self.w.file.ReadFile(self.handle, MAX_MESSAGE + 1, ov), deadline,
        )
        if count > MAX_MESSAGE:
            raise ShadowUnavailable("message-limit")
        return _json(bytes(buffer[:count]))

    def write(self, value: dict, deadline: float) -> None:
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        if len(raw) > MAX_MESSAGE:
            raise ShadowUnavailable("message-limit")
        count, _ = self._operation(lambda ov: self.w.file.WriteFile(self.handle, raw, ov), deadline, raw)
        if count != len(raw):
            raise ShadowUnavailable("transport-failed")

    def close(self) -> None:
        if self.unresolved:
            _retained.append(self)
            return
        _close(self.handle)
        self.handle = None


def _public(status: str, reason: str, ttl: float = 0) -> dict:
    return {"mode": "shadow", "status": status, "reason": reason,
            "ttl_seconds": max(0, min(int(ttl), int(GRANT_SECONDS)))}


class ShadowService:
    """One pair, one serial channel, transient authority only."""

    def __init__(self, directory: Path, snapshot, *, clock=time.monotonic, utc_clock=None):
        self.directory, self.snapshot, self.clock = directory, snapshot, clock
        self.utc_clock = utc_clock or (lambda: datetime.now(timezone.utc))
        self.stop_event = threading.Event()
        self.thread = None
        self.epoch = secrets.token_hex(16)
        self.grant = None


        self.last_sequence = 0
        self.policy = None
        self.unresolved = False

    def start(self):
        if not native_available():
            return None
        self.thread = threading.Thread(target=self._run, daemon=True, name="pallium-codex-shadow")
        self.thread.start()
        return self

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=0.5)
        if self.thread is not None and self.thread.is_alive():
            self.unresolved = True

    def _current_policy(self, w, sid) -> ShadowPolicy:
        policy = ShadowPolicy.parse(_read_private(w, self.directory / "policy.json", sid))
        if self.stop_event.is_set() or not policy.valid(self.utc_clock()):
            raise ShadowUnavailable("policy-inactive")
        if self.policy is not None and policy != self.policy:
            raise ShadowUnavailable("policy-changed")
        return policy

    def _snapshot(self, deadline: float) -> dict:
        p = self.policy
        if self.stop_event.is_set() or self.clock() >= deadline:
            raise ShadowUnavailable("stopped")
        value = self.snapshot(
            endpoint_id=p.recipient_endpoint_id, runtime="codex",
            session_ref=p.recipient_session_ref, container_ref=p.recipient_container_ref,
            scope_generation=p.recipient_scope_generation, deadline=deadline,
        )
        if self.stop_event.is_set() or self.clock() >= deadline:
            raise ShadowUnavailable("deadline")
        if not self.policy.valid(self.utc_clock()):
            raise ShadowUnavailable("policy-inactive")
        if not isinstance(value, dict) or value.get("endpoint_valid") is not True:
            raise ShadowUnavailable("endpoint-unavailable")
        return value

    def _process(self, request: dict, peer: _Peer, deadline: float) -> dict:
        common = {"version", "verb", "epoch", "policy_revision", "sequence"}
        verb = request.get("verb")
        fields = common | ({"thread_ref", "turn_ref"} if verb == "enroll" else {"grant"})
        if verb not in {"enroll", "renew", "status", "close"} or set(request) != fields:
            raise ShadowUnavailable("invalid-message")
        sequence = request.get("sequence")
        if (type(request.get("version")) is not int or request["version"] != 1
                or request.get("epoch") != self.epoch
                or type(request.get("policy_revision")) is not int
                or request["policy_revision"] != self.policy.revision
                or not _integer(sequence, 1) or sequence <= self.last_sequence):
            raise ShadowUnavailable("stale-request")
        peer.check()
        now = self.clock()
        if self.stop_event.is_set():
            raise ShadowUnavailable("stopped")
        if self.grant is not None and (now >= self.grant["expiry"] or now >= self.grant["lease"]):
            self.grant = None
        if verb == "enroll":
            if (not _text(request["turn_ref"]) or not _text(request["thread_ref"])
                    or request["thread_ref"] != self.policy.controller_thread_ref):
                raise ShadowUnavailable("controller-mismatch")
            self._snapshot(deadline)
            now = self.clock()
            if self.grant is not None and now >= min(self.grant["expiry"], self.grant["lease"]):
                raise ShadowUnavailable("grant-inactive")
            if self.grant is None:
                duration = min(GRANT_SECONDS, (self.policy.expires_at - self.utc_clock()).total_seconds())
                if duration <= 0:
                    raise ShadowUnavailable("policy-inactive")
                self.grant = {"handle": secrets.token_urlsafe(32),
                              "expiry": now + duration, "lease": now + min(LEASE_SECONDS, duration),
                              "renewed": now}
            result = _public("enrolled", "ok", self.grant["expiry"] - now)
            result["grant"] = self.grant["handle"]
        elif self.grant is None or not isinstance(request["grant"], str) or not secrets.compare_digest(request["grant"], self.grant["handle"]):
            raise ShadowUnavailable("grant-inactive")
        elif verb == "close":
            self.grant = None
            result = _public("inactive", "closed")
        else:
            snapshot = self._snapshot(deadline)
            now = self.clock()
            if now >= min(self.grant["expiry"], self.grant["lease"]):
                raise ShadowUnavailable("grant-inactive")
            if verb == "renew":
                if now - self.grant["renewed"] < 5:
                    raise ShadowUnavailable("renew-too-soon")
                self.grant["renewed"] = now
                self.grant["lease"] = min(self.grant["expiry"], now + LEASE_SECONDS)
            status = snapshot.get("category")
            if status not in {"eligible", "held", "inactive", "unavailable"}:
                status = "unavailable"
            # Never propagate store strings, IDs or payload into the channel.
            reason = {"held": "evidence-limited", "unavailable": "evidence-unavailable"}.get(status, "observed")
            result = _public(status, reason, self.grant["expiry"] - now)
        self.last_sequence = sequence
        result.update(version=1, epoch=self.epoch, sequence=sequence)
        return result

    def _run(self) -> None:
        w = None
        owner = None
        io = None
        peer = None
        try:
            w = _native()
            sid = _self_sid(w)
            _check_path(w, self.directory, sid)
            owner = _lock_file(w, self.directory / "service.lock", sid)
            self.policy = self._current_policy(w, sid)
            current = _Peer(w, os.getpid(), sid)
            creation = current.creation
            current.close()
            pipe_name = rf"\\.\pipe\pallium-shadow-{self.epoch}"
            handle = w.pipe.CreateNamedPipe(
                pipe_name, w.pipe.PIPE_ACCESS_DUPLEX | w.con.FILE_FLAG_OVERLAPPED | FIRST_PIPE_INSTANCE,
                w.pipe.PIPE_TYPE_MESSAGE | w.pipe.PIPE_READMODE_MESSAGE | w.pipe.PIPE_WAIT | w.pipe.PIPE_REJECT_REMOTE_CLIENTS,
                1, MAX_MESSAGE + 1, MAX_MESSAGE + 1, 2000, _security_attributes(w, sid),
            )
            io = _PipeIO(w, handle, self.stop_event)
            manifest = {"version": 1, "pid": os.getpid(), "creation": creation,
                        "epoch": self.epoch, "policy_revision": self.policy.revision,
                        "pipe": pipe_name}
            _atomic_private(w, self.directory / "active.json", sid, json.dumps(manifest).encode("utf-8"))
            while not self.stop_event.is_set():
                self._current_policy(w, sid)
                try:
                    io.accept(time.monotonic() + 5)
                except ShadowUnavailable as exc:
                    if exc.category == "deadline" and not io.unresolved:
                        continue
                    raise
                peer = _Peer(w, w.pipe.GetNamedPipeClientProcessId(handle), sid)
                self.grant = None
                self.last_sequence = 0
                try:
                    while not self.stop_event.is_set():
                        self._current_policy(w, sid)
                        peer.check()
                        if self.grant is not None and self.clock() >= min(self.grant["lease"], self.grant["expiry"]):
                            break
                        idle_end = time.monotonic() + 5
                        if self.grant is not None:
                            idle_end = min(idle_end, self.grant["lease"], self.grant["expiry"])
                        try:
                            request = io.read(idle_end)
                        except ShadowUnavailable as exc:
                            if exc.category == "deadline" and not io.unresolved:
                                continue
                            raise
                        self._current_policy(w, sid)
                        deadline = time.monotonic() + EXCHANGE_SECONDS
                        response = self._process(request, peer, deadline)
                        self._current_policy(w, sid)
                        io.write(response, min(deadline, time.monotonic() + 2))
                        if request.get("verb") == "close":
                            break
                except ShadowUnavailable:
                    if io.unresolved or self.stop_event.is_set():
                        raise
                finally:
                    self.grant = None
                    if not io.unresolved:
                        peer.close()
                        peer = None
                        w.pipe.DisconnectNamedPipe(handle)
        except Exception:
            # Isolated optional worker; ordinary service and logs remain unchanged.
            self.stop_event.set()
        finally:
            self.grant = None
            self.unresolved = io is not None and io.unresolved
            if self.unresolved:
                _retained.append((self, io, owner, peer))
            else:
                if peer is not None:
                    peer.close()
                if io is not None:
                    io.close()
                _close(owner)


def start_shadow_service(storage) -> ShadowService | None:
    if sys.platform != "win32":
        return None
    try:
        directory = shadow_directory()
        if not native_available():
            return None
        w = _native()
        if w.file.GetDriveType(directory.anchor) != w.con.DRIVE_FIXED:
            return None
        if not (directory / "policy.json").is_file():
            return None
        snapshot = getattr(storage, "relay_shadow_snapshot", None)
        if not callable(snapshot):
            return None
        return ShadowService(directory, snapshot).start()
    except ShadowUnavailable:
        return None


class NativeShadowClient:
    """Synchronous I/O API called only by the MCP child's dedicated daemon."""

    def __init__(self, bootstrap_path: Path, stop_event: threading.Event):
        self.w = _native()
        self.stop_event = stop_event
        self.io = None
        self.peer = None
        self.grant = None
        self.sequence = 0
        self.unresolved = False
        sid = _self_sid(self.w)
        self.bootstrap_path = Path(bootstrap_path)
        try:
            manifest = _json(_read_private(self.w, self.bootstrap_path, sid))
            fields = {"version", "pid", "creation", "epoch", "policy_revision", "pipe"}
            if (set(manifest) != fields or type(manifest["version"]) is not int or manifest["version"] != 1
                    or not _integer(manifest["pid"], 1) or not _integer(manifest["policy_revision"], 1)
                    or not _text(manifest["creation"]) or not _text(manifest["epoch"])
                    or manifest["pipe"] != rf"\\.\pipe\pallium-shadow-{manifest['epoch']}"):
                raise ShadowUnavailable("invalid-bootstrap")
            self.policy = ShadowPolicy.parse(_read_private(self.w, self.bootstrap_path.parent / "policy.json", sid))
            if self.policy.revision != manifest["policy_revision"] or not self.policy.valid(datetime.now(timezone.utc)):
                raise ShadowUnavailable("policy-inactive")
            self.epoch = manifest["epoch"]
            handle = self.w.file.CreateFile(
                manifest["pipe"], self.w.con.GENERIC_READ | self.w.con.GENERIC_WRITE,
                0, None, self.w.con.OPEN_EXISTING,
                self.w.con.FILE_FLAG_OVERLAPPED | self.w.con.SECURITY_SQOS_PRESENT | self.w.file.SECURITY_IDENTIFICATION,
                None,
            )
            self.io = _PipeIO(self.w, handle, self.stop_event)
            self.w.pipe.SetNamedPipeHandleState(handle, self.w.pipe.PIPE_READMODE_MESSAGE, None, None)
            pid = self.w.pipe.GetNamedPipeServerProcessId(handle)
            if pid != manifest["pid"]:
                raise ShadowUnavailable("peer-mismatch")
            self.peer = _Peer(self.w, pid, sid, manifest["creation"])
        except ShadowUnavailable:
            self.dispose()
            raise
        except Exception:
            self.dispose()
            raise ShadowUnavailable("channel-unavailable") from None

    def _exchange(self, verb: str, metadata: dict | None = None) -> dict:
        if self.stop_event.is_set() or self.io is None:
            raise ShadowUnavailable("stopped")
        sid = _self_sid(self.w)
        current = _json(_read_private(self.w, self.bootstrap_path, sid))
        if current.get("epoch") != self.epoch or current.get("policy_revision") != self.policy.revision:
            raise ShadowUnavailable("stale-bootstrap")
        policy = ShadowPolicy.parse(_read_private(self.w, self.bootstrap_path.parent / "policy.json", sid))
        if policy != self.policy or not policy.valid(datetime.now(timezone.utc)):
            raise ShadowUnavailable("policy-changed")
        self.peer.check()
        self.sequence += 1
        request = {"version": 1, "verb": verb, "epoch": self.epoch,
                   "policy_revision": self.policy.revision, "sequence": self.sequence}
        if verb == "enroll":
            if (not isinstance(metadata, dict) or set(metadata) != {"thread_ref", "turn_ref"}
                    or metadata["thread_ref"] != self.policy.controller_thread_ref
                    or not _text(metadata["thread_ref"]) or not _text(metadata["turn_ref"])):
                raise ShadowUnavailable("controller-mismatch")
            request.update(metadata)
        else:
            if self.grant is None:
                return _public("inactive", "not-enrolled")
            request["grant"] = self.grant
        deadline = time.monotonic() + EXCHANGE_SECONDS
        self.io.write(request, min(deadline, time.monotonic() + 2))
        response = self.io.read(min(deadline, time.monotonic() + 2))
        fields = {"mode", "status", "reason", "ttl_seconds", "version", "epoch", "sequence"}
        if verb == "enroll":
            fields.add("grant")
        if (set(response) != fields or type(response.get("version")) is not int
                or response.get("version") != 1 or response.get("mode") != "shadow"
                or response.get("epoch") != self.epoch or type(response.get("sequence")) is not int
                or response.get("sequence") != self.sequence
                or response.get("status") not in {"enrolled", "eligible", "held", "inactive", "unavailable"}
                or response.get("reason") not in {"ok", "observed", "evidence-limited", "evidence-unavailable", "closed"}
                or not _integer(response.get("ttl_seconds")) or response["ttl_seconds"] > GRANT_SECONDS):
            raise ShadowUnavailable("invalid-response")
        if self.stop_event.is_set():
            raise ShadowUnavailable("stopped")
        if verb == "enroll":
            if not _text(response.get("grant")) or response["status"] != "enrolled":
                raise ShadowUnavailable("invalid-response")
            self.grant = response["grant"]
        elif verb == "close":
            self.grant = None
        return _public(response["status"], response["reason"], response["ttl_seconds"])

    def enroll(self, metadata: dict) -> dict:
        return self._exchange("enroll", metadata)

    def status(self) -> dict:
        return self._exchange("status")

    def renew(self) -> dict:
        return self._exchange("renew")

    def close(self) -> dict:
        try:
            return self._exchange("close")
        finally:
            self.dispose()

    def dispose(self) -> None:
        self.unresolved = self.io is not None and self.io.unresolved
        if self.unresolved:
            _retained.append(self)
        else:
            if self.io is not None:
                self.io.close()
                self.io = None
            if self.peer is not None:
                self.peer.close()
                self.peer = None
        self.grant = None

# Inventory authority is intentionally independent of shadow enrollment.
MAX_DESKTOP_FRAME = 8 * 1024 * 1024


def _owner_tool_schema_valid(tools: object) -> bool:
    if not isinstance(tools, list):
        return False
    matches = [tool for tool in tools if isinstance(tool, dict)
               and tool.get("namespace") == "codex_app"
               and tool.get("name") == "send_message_to_thread"]
    if len(matches) != 1:
        return False
    schema = matches[0].get("inputSchema")
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return False
    required, properties = schema.get("required"), schema.get("properties")
    if (not isinstance(required, list) or len(required) != 2
            or any(type(name) is not str for name in required)
            or set(required) != {"threadId", "prompt"} or not isinstance(properties, dict)):
        return False
    return all(isinstance(properties.get(name), dict)
               and properties[name].get("type") == "string"
               for name in ("threadId", "prompt"))


@dataclass(frozen=True)
class InventoryPolicy:
    revision: int
    expires_at: datetime
    enabled: bool
    revoked: bool
    service_pid: int
    service_creation: str
    service_epoch: str
    source_pid: int
    source_creation: str
    desktop_pid: int
    desktop_creation: str
    desktop_user_sid: str
    desktop_executable: str
    desktop_version: str

    @classmethod
    def parse(cls, raw: bytes) -> "InventoryPolicy":
        value = _json(raw)
        fields = set(cls.__dataclass_fields__) | {"version", "action"}
        if (set(value) != fields or type(value["version"]) is not int or value["version"] != 1
                or value["action"] != "desktop-inventory-only"
                or not _integer(value["revision"], 1)
                or any(not _integer(value[name], 1) for name in ("service_pid", "source_pid", "desktop_pid"))
                or any(type(value[name]) is not bool for name in ("enabled", "revoked"))
                or any(not _text(value[name]) for name in (
                    "service_creation", "service_epoch", "source_creation", "desktop_creation",
                    "desktop_user_sid", "desktop_version"))):
            raise ShadowUnavailable("invalid-policy")
        executable = value["desktop_executable"]
        if (not isinstance(executable, str) or not 0 < len(executable) < 32768
                or not executable.isprintable() or executable != executable.strip()
                or not Path(executable).is_absolute()):
            raise ShadowUnavailable("invalid-policy")
        parts = value["desktop_version"].split(".")
        if len(parts) != 4 or any(not p.isascii() or not p.isdecimal() or int(p) > 65535 for p in parts):
            raise ShadowUnavailable("invalid-policy")
        try:
            expiry = datetime.fromisoformat(value["expires_at"].replace("Z", "+00:00"))
            if expiry.tzinfo is None or expiry.utcoffset().total_seconds() != 0:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise ShadowUnavailable("invalid-policy") from None
        value["expires_at"] = expiry
        return cls(**{name: value[name] for name in cls.__dataclass_fields__})

    def valid(self, now: datetime) -> bool:
        return self.enabled and not self.revoked and 0 < (self.expires_at - now).total_seconds() <= GRANT_SECONDS


def inventory_directory(home: Path | None = None) -> Path:
    return shadow_directory(home).with_name("codex-inventory")


def prepare_inventory_service(home: Path | None = None) -> Path:
    """Explicit operator preparation; setup/startup never creates this directory."""
    w = _native()
    directory = inventory_directory(home)
    _secure_directory(w, directory, _self_sid(w))
    return directory


def provision_inventory_policy(source: Path, home: Path | None = None, *, expected_revision: int = 0) -> None:
    if not _integer(expected_revision):
        raise ShadowUnavailable("invalid-revision")
    try:
        with source.open("rb") as stream:
            raw = stream.read(MAX_MESSAGE + 1)
    except OSError:
        raise ShadowUnavailable("policy-unavailable") from None
    policy = InventoryPolicy.parse(raw)
    now = datetime.now(timezone.utc)
    if policy.expires_at > now and (policy.expires_at - now).total_seconds() > GRANT_SECONDS:
        raise ShadowUnavailable("invalid-policy")
    if policy.enabled and not policy.revoked and not policy.valid(now):
        raise ShadowUnavailable("policy-inactive")
    w = _native()
    sid = _self_sid(w)
    directory = inventory_directory(home)
    _check_path(w, directory, sid)
    lock = _policy_lock(w, directory / "policy.json", sid)
    try:
        destination = directory / "policy.json"
        previous = InventoryPolicy.parse(_read_private(w, destination, sid, policy_lock=lock)).revision if destination.exists() else 0
        if previous != expected_revision or policy.revision != previous + 1:
            raise ShadowUnavailable("revision-conflict")
        _atomic_private(w, destination, sid, raw, policy_lock=lock)
    finally:
        _close(lock)


def _process_image(w, handle) -> tuple[str, str]:
    """Limited-query retained handle, bounded Win32 image name and fixed file version."""
    import ctypes
    from ctypes import wintypes

    try:
        query = ctypes.WinDLL("kernel32", use_last_error=True).QueryFullProcessImageNameW
        query.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        query.restype = wintypes.BOOL
        buffer = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(buffer))
        if not query(int(handle), 0, buffer, ctypes.byref(length)) or not 0 < length.value < len(buffer):
            raise ShadowUnavailable("peer-mismatch")
        path = buffer.value
        version = w.api.GetFileVersionInfo(path, "\\")
        ms, ls = version["FileVersionMS"], version["FileVersionLS"]
        return path, f"{ms >> 16}.{ms & 65535}.{ls >> 16}.{ls & 65535}"
    except ShadowUnavailable:
        raise
    except Exception:
        raise ShadowUnavailable("peer-mismatch") from None


class _DesktopPeer(_Peer):
    def __init__(self, w, policy: InventoryPolicy):
        self.policy = policy
        super().__init__(w, policy.desktop_pid, policy.desktop_user_sid, policy.desktop_creation)
        try:
            self.verify()
        except Exception:
            self.close()
            raise

    def verify(self) -> None:
        self.check()
        path, version = _process_image(self.w, self.handle)
        if (_sid(self.w, self.handle) != self.policy.desktop_user_sid
                or self.w.process.GetProcessTimes(self.handle)["CreationTime"].isoformat() != self.policy.desktop_creation
                or os.path.normcase(path) != os.path.normcase(self.policy.desktop_executable)
                or version != self.policy.desktop_version):
            raise ShadowUnavailable("peer-mismatch")


class _DesktopIO(_PipeIO):
    """Desktop byte stream: exact partial reads/writes, 4-byte LE length, no handshake."""

    def _read_exact(self, size: int, deadline: float) -> bytes:
        chunks = bytearray()
        while len(chunks) < size:
            remaining = size - len(chunks)
            count, buffer = self._operation(lambda ov: self.w.file.ReadFile(self.handle, remaining, ov), deadline)
            if not 0 < count <= remaining:
                raise ShadowUnavailable("invalid-response")
            chunks.extend(buffer[:count])
        return bytes(chunks)

    def read(self, deadline: float) -> dict:
        size = int.from_bytes(self._read_exact(4, deadline), "little")
        if not 0 < size <= MAX_DESKTOP_FRAME:
            raise ShadowUnavailable("message-limit")
        return _json(self._read_exact(size, deadline), limit=MAX_DESKTOP_FRAME)

    def write(self, value: dict, deadline: float) -> None:
        payload = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        if not 0 < len(payload) <= MAX_DESKTOP_FRAME:
            raise ShadowUnavailable("message-limit")
        raw = len(payload).to_bytes(4, "little") + payload
        offset = 0
        while offset < len(raw):
            chunk = raw[offset:]
            count, _ = self._operation(lambda ov: self.w.file.WriteFile(self.handle, chunk, ov), deadline, chunk)
            if not 0 < count <= len(chunk):
                raise ShadowUnavailable("transport-failed")
            offset += count


def _inventory_public(status: str, reason: str, ttl: float = 0, *, connected=False, inventory_ok=False, source_exited=False) -> dict:
    return {"mode": "inventory", "status": status, "reason": reason,
            "ttl_seconds": max(0, min(int(ttl), int(GRANT_SECONDS))),
            "connected": bool(connected), "inventory_ok": bool(inventory_ok), "source_exited": bool(source_exited)}


def _inventory_reason(exc: Exception) -> str:
    category = getattr(exc, "category", "native-failed")
    return {"deadline": "timeout", "invalid-policy": "policy-inactive", "file-unavailable": "policy-inactive",
            "path-unavailable": "policy-inactive", "policy-busy": "busy",
            "peer-gone": "peer-mismatch"}.get(category, category if category in {
                "policy-inactive", "policy-changed", "peer-mismatch", "busy", "stopped", "timeout"} else "native-failed")


def _inventory_fingerprint(policy: InventoryPolicy) -> str:
    value = {name: getattr(policy, name) for name in policy.__dataclass_fields__}
    value["expires_at"] = policy.expires_at.isoformat()
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


_PROOF_PHASES = ("before", "exit", "after", "failure")


def _phase_present(w, path: Path, sid: str) -> bool:
    """Only conclusive native absence may be skipped; never follow a phase link."""
    _check_private_parent(w, path, sid)
    try:
        attrs = w.file.GetFileAttributes(str(path))
        if attrs in (-1, 0xFFFFFFFF):
            if w.api.GetLastError() == 2:
                return False
            raise ShadowUnavailable("invalid-proof")
        if type(attrs) is not int:
            raise ShadowUnavailable("invalid-proof")
        return True
    except w.types.error as exc:
        if getattr(exc, "winerror", None) == 2:
            return False
        raise ShadowUnavailable("invalid-proof") from None
    except Exception:
        raise ShadowUnavailable("invalid-proof") from None


def _create_phase(w, path: Path, sid: str, data: bytes) -> None:
    """Publish once by atomic rename without replacement."""
    if len(data) > MAX_MESSAGE:
        raise ShadowUnavailable("message-limit")
    _check_private_parent(w, path, sid)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(12)}.tmp")
    handle = None
    try:
        handle = w.file.CreateFile(str(temporary), w.con.GENERIC_WRITE, 0, _security_attributes(w, sid),
            w.con.CREATE_NEW, w.con.FILE_ATTRIBUTE_NORMAL, None)
        _, written = w.file.WriteFile(handle, data)
        if written != len(data):
            raise ShadowUnavailable("file-write-failed")
        w.file.FlushFileBuffers(handle)
        _close(handle)
        handle = None
        w.file.MoveFileEx(str(temporary), str(path), 0)
    except ShadowUnavailable:
        raise
    except Exception:
        raise ShadowUnavailable("file-write-failed") from None
    finally:
        _close(handle)
        if temporary.exists():
            temporary.unlink()


def read_inventory_proof(directory: Path, expected_policy: InventoryPolicy) -> dict:
    """Fixed operator readback; historical evidence never grants current authority."""
    try:
        if type(expected_policy) is not InventoryPolicy or not isinstance(expected_policy.expires_at, datetime):
            raise ShadowUnavailable("invalid-policy")
        baseline = {name: getattr(expected_policy, name) for name in expected_policy.__dataclass_fields__}
        baseline.update(version=1, action="desktop-inventory-only", expires_at=expected_policy.expires_at.isoformat())
        expected = InventoryPolicy.parse(json.dumps(baseline, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        fingerprint = _inventory_fingerprint(expected)
        w = _native()
        sid = _self_sid(w)
        phases = {}
        fields = {"version", "epoch", "revision", "policy_fingerprint", "before_inventory_ok",
                  "after_inventory_ok", "source_exited", "failure"}
        for phase in _PROOF_PHASES:
            path = directory / f"proof-{phase}.json"
            if not _phase_present(w, path, sid):
                continue
            value = _json(_read_private(w, path, sid))
            if (set(value) != fields or type(value["version"]) is not int or value["version"] != 1
                    or type(value["revision"]) is not int or value["revision"] != expected.revision
                    or value["epoch"] != expected.service_epoch or value["policy_fingerprint"] != fingerprint
                    or any(type(value[name]) is not bool for name in ("before_inventory_ok", "after_inventory_ok", "source_exited"))
                    or not isinstance(value["failure"], str) or value["failure"] not in {
                        "none", "policy-inactive", "policy-changed", "peer-mismatch", "busy", "stopped", "timeout", "native-failed"}):
                raise ShadowUnavailable("invalid-response")
            state = (value["before_inventory_ok"], value["source_exited"], value["after_inventory_ok"])
            if phase == "failure":
                if (value["failure"] == "none" or (state[1] and not state[0])
                        or (state[2] and not (state[0] and state[1]))):
                    raise ShadowUnavailable("invalid-response")
            elif value["failure"] != "none" or state != {
                    "before": (True, False, False), "exit": (True, True, False), "after": (True, True, True)}[phase]:
                raise ShadowUnavailable("invalid-response")
            phases[phase] = value
        before, exited, after = (phases.get(name, {}) for name in ("before", "exit", "after"))
        failure = phases.get("failure")
        if failure is not None and (after or (before and not failure["before_inventory_ok"])
                                    or (exited and not failure["source_exited"])):
            raise ShadowUnavailable("invalid-response")
        passed = ("failure" not in phases and before.get("before_inventory_ok") is True
            and before.get("source_exited") is False and before.get("after_inventory_ok") is False
            and exited.get("before_inventory_ok") is True and exited.get("source_exited") is True
            and exited.get("after_inventory_ok") is False and after.get("before_inventory_ok") is True
            and after.get("source_exited") is True and after.get("after_inventory_ok") is True
            and all(value.get("failure") == "none" for value in (before, exited, after)))
        result = {"status": "incomplete", "reason": "missing-phase",
                  "source_exited": exited.get("source_exited") is True,
                  "before_inventory_ok": before.get("before_inventory_ok") is True,
                  "after_inventory_ok": after.get("after_inventory_ok") is True,
                  "historical_transport_pass": False}
        if not passed:
            return result
        result.update(status="historical", reason="observed", historical_transport_pass=True)
        return result
    except Exception:
        return {"status": "invalid", "reason": "invalid-proof", "source_exited": False,
                "before_inventory_ok": False, "after_inventory_ok": False, "historical_transport_pass": False}


class InventoryService:
    """One serial ready/admission slot, one RAM connection, one fixed operator action."""

    def __init__(self, directory: Path, *, utc_clock=None, trial_relay=None, trial_registry=None):
        self.directory = directory
        self.utc_clock = utc_clock or (lambda: datetime.now(timezone.utc))
        self.trial_relay = trial_relay
        self.trial_registry = trial_registry
        self._trial_install_seen = False
        self._trial_action_seen = False
        self._trial_owner_attempted = False
        self.trial_action = None
        self.stop_event = threading.Event()
        self.thread = None
        self.epoch = secrets.token_hex(16)
        self.unresolved = False
        self.source = self.desktop = self.custody = self.policy = None
        self.admitted = None
        self.caller = None
        self.owner_tool_before = False
        self.owner_tool_after = False
        self.ready_deadline = 0.0
        self.ready_announced = False
        self.replace_allowed = False
        self.release_revision = 0
        self.fenced = False
        self.native_sequence = 0
        self.proof = None
        self.published_phases = set()
        self.after_attempted = False
        self._failure_context = None
        self._failure_stage = "unknown"
        self._failure_diagnostic = None

    def _record_failure(self, exc: Exception) -> None:
        if self._failure_context is None or self._failure_diagnostic is not None:
            return
        if ("after" in self.published_phases and self.proof is not None
                and (self.proof.get("epoch"), self.proof.get("revision")) == self._failure_context):
            return
        stage = self._failure_stage
        stage = stage if type(stage) is str and stage in _INVENTORY_FAILURE_STAGES else "unknown"
        try:
            category = getattr(exc, "category", None)
        except Exception:
            category = None
        category = category if type(category) is str and category in _INVENTORY_FAILURE_CATEGORIES else "unexpected"
        # Latch before logging: a failed sink must not retry or replace the original attribution.
        self._failure_diagnostic = (stage, category)
        try:
            _log.warning("codex_inventory_failure stage=%s category=%s epoch=%s revision=%d",
                         stage, category, *self._failure_context)
        except Exception:
            pass  # Diagnostics must not change failure handling.

    def start(self):
        if not native_available():
            return None
        self.thread = threading.Thread(target=self._run, daemon=True, name="pallium-codex-inventory")
        self.thread.start()
        return self

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=.5)
            if self.thread.is_alive():
                self.unresolved = True

    def _result(self, status="registered", reason="ok", *, inventory_ok=False) -> dict:
        exited = False
        if self.source is not None:
            state = self.source.w.event.WaitForSingleObject(self.source.handle, 0)
            if state not in (self.source.w.event.WAIT_OBJECT_0, self.source.w.event.WAIT_TIMEOUT):
                raise ShadowUnavailable("peer-mismatch")
            exited = state == self.source.w.event.WAIT_OBJECT_0
        ttl = (self.policy.expires_at - self.utc_clock()).total_seconds() if self.policy else 0
        return _inventory_public(status, reason, ttl, connected=self.custody is not None,
                                 inventory_ok=inventory_ok, source_exited=exited)

    def _drop(self) -> None:
        self.admitted = None
        self.caller = None
        self.trial_action = None
        self.owner_tool_before = False
        self.owner_tool_after = False
        if self.custody is not None:
            if self.custody.unresolved:
                self.unresolved = True
                self.stop_event.set()
                return
            self.custody.close()
            self.custody = None
        if self.desktop is not None:
            self.desktop.close()
            self.desktop = None

    def _load(self) -> InventoryPolicy:
        path = self.directory / "policy.json"
        if not path.is_file():
            raise ShadowUnavailable("policy-inactive")
        return InventoryPolicy.parse(_read_private(self.w, path, self.sid))

    def _maintain(self) -> None:
        if self.policy is None or (self.replace_allowed and self.custody is None and self.desktop is None):
            return
        phase = "after" if self.after_attempted else "before"
        try:
            self._failure_stage = f"{phase}-authority"
            current = self._load()
            expired = self.utc_clock() >= self.policy.expires_at
            if expired or current.revoked or not current.enabled:
                self._record_failure(ShadowUnavailable("policy-inactive"))
                self._drop()
                self.replace_allowed = not self.unresolved
                released = current.revision if current.revoked or not current.enabled else self.policy.revision
                self.release_revision = max(self.release_revision, self.policy.revision, released)
                self.fenced = True
                self._proof_failure("policy-inactive")
                return
            if current != self.policy:
                raise ShadowUnavailable("policy-changed")
            if not current.valid(self.utc_clock()):
                raise ShadowUnavailable("policy-inactive")
            if self.desktop is not None:
                self._failure_stage = f"{phase}-peer"
                self.desktop.verify()
        except Exception as exc:
            self._record_failure(exc)
            self.fenced = True
            self._drop()
            self._proof_failure(_inventory_reason(exc))

    def _authorize(self, revision=None) -> InventoryPolicy:
        if self.stop_event.is_set() or self.unresolved or _native_uncertain:
            raise ShadowUnavailable("stopped")
        current = self._load()
        if not current.valid(self.utc_clock()):
            raise ShadowUnavailable("policy-inactive")
        if (current.service_pid != self.current.pid or current.service_creation != self.current.creation
                or current.service_epoch != self.epoch or self.source is None
                or current.source_pid != self.source.pid or current.source_creation != self.source.creation):
            raise ShadowUnavailable("peer-mismatch")
        self.current.check()
        self.source.check()
        if revision is not None and (type(revision) is not int or revision != current.revision):
            raise ShadowUnavailable("policy-changed")
        if self.policy is not None and current != self.policy:
            if not self.replace_allowed or current.revision <= max(self.policy.revision, self.release_revision):
                raise ShadowUnavailable("policy-changed")
        elif self.fenced:
            raise ShadowUnavailable("policy-changed")
        if self.policy is None or current != self.policy:
            if any(_phase_present(self.w, self.directory / f"proof-{phase}.json", self.sid) for phase in _PROOF_PHASES):
                raise ShadowUnavailable("busy")
        if self.desktop is None:
            self.desktop = _DesktopPeer(self.w, current)
        else:
            if self.desktop.policy != current:
                raise ShadowUnavailable("policy-changed")
            self.desktop.verify()
        self.policy = current
        self.fenced = False
        self.replace_allowed = False
        return current

    def _process(self, request: dict, peer: _Peer, sequence: int, deadline: float) -> dict:
        verb = request.get("verb")
        fields = {"version", "verb", "epoch", "sequence"}
        if verb == "admit":
            fields |= {"thread_ref", "turn_ref"}
        if verb == "transfer":
            fields |= {"revision", "endpoint"}
        if (not isinstance(verb, str) or verb not in {"ready", "admit", "transfer"} or set(request) != fields
                or type(request["version"]) is not int or request["version"] != 1
                or request["epoch"] != self.epoch or not _integer(request["sequence"], 1)
                or request["sequence"] <= sequence):
            raise ShadowUnavailable("invalid-message")
        peer.check()
        if self.source is not peer:
            raise ShadowUnavailable("busy")
        if verb == "ready":
            if time.monotonic() >= self.ready_deadline:
                raise ShadowUnavailable("policy-inactive")
            if not self.ready_announced:
                descriptor = {"version": 1, "service_pid": self.current.pid,
                              "service_creation": self.current.creation, "service_epoch": self.epoch,
                              "source_pid": peer.pid, "source_creation": peer.creation,
                              "expires_at": datetime.fromtimestamp(self.utc_clock().timestamp()
                                  + max(0, self.ready_deadline - time.monotonic()), timezone.utc).isoformat()}
                _atomic_private(self.w, self.directory / "ready.json", self.sid, json.dumps(descriptor).encode("utf-8"))
                self.ready_announced = True
            return self._result("ready", "ready")
        if not self.ready_announced or (self.custody is None and time.monotonic() >= self.ready_deadline):
            raise ShadowUnavailable("policy-inactive")
        policy = self._authorize(request.get("revision") if verb == "transfer" else None)
        if self.custody is not None:
            if verb == "admit" and self.caller != (request["thread_ref"], request["turn_ref"]):
                raise ShadowUnavailable("peer-mismatch")
            return self._result(inventory_ok=self.proof is not None and self.proof["before_inventory_ok"])
        if verb == "admit":
            if not _text(request["thread_ref"]) or not _text(request["turn_ref"]):
                raise ShadowUnavailable("invalid-message")
            self.admitted = (policy, min(deadline, time.monotonic() + EXCHANGE_SECONDS),
                             (request["thread_ref"], request["turn_ref"]))
            result = self._result("ready", "ok")
            result["revision"] = policy.revision
            return result
        if self.admitted is None or self.admitted[0] != policy or time.monotonic() >= self.admitted[1]:
            raise ShadowUnavailable("policy-inactive")
        endpoint = request["endpoint"]
        if (not isinstance(endpoint, str) or not endpoint.startswith("\\\\.\\pipe\\")
                or len(endpoint) > 512 or not endpoint.isprintable() or endpoint != endpoint.strip()):
            raise ShadowUnavailable("invalid-message")
        handle = None
        self._failure_context = (self.epoch, policy.revision)
        self._failure_diagnostic = None
        self._failure_stage = "transfer-authority"
        try:
            # Authority was independently checked before accepting the capability.
            self._authorize(policy.revision)
            self.proof = {"version": 1, "epoch": self.epoch, "revision": policy.revision,
                          "policy_fingerprint": _inventory_fingerprint(policy),
                          "before_inventory_ok": False, "after_inventory_ok": False,
                          "source_exited": False, "failure": "none"}
            self.after_attempted = False
            self.owner_tool_before = False
            self.owner_tool_after = False
            self.published_phases = set()
            self._failure_stage = "native-open"
            handle = self.w.file.CreateFile(endpoint, self.w.con.GENERIC_READ | self.w.con.GENERIC_WRITE,
                0, None, self.w.con.OPEN_EXISTING,
                self.w.con.FILE_FLAG_OVERLAPPED | self.w.con.SECURITY_SQOS_PRESENT | self.w.file.SECURITY_IDENTIFICATION, None)
            self.custody = _DesktopIO(self.w, handle, self.stop_event)
            self.native_sequence = 0
            handle = None
            self._failure_stage = "native-peer"
            if self.w.pipe.GetNamedPipeServerProcessId(self.custody.handle) != self.desktop.pid:
                raise ShadowUnavailable("peer-mismatch")
            self._failure_stage = "before-authority"
            self._authorize(policy.revision)
            caller = self.admitted[2]
            self.admitted = None
            self._failure_stage = "before-source"
            self.source.check()
            self._observe(deadline)
            # An exit crossing the first read is inconclusive, never the before witness.
            self._failure_stage = "before-source"
            self.source.check()
            self.proof["before_inventory_ok"] = True
            self._failure_stage = "before-proof"
            self._publish_proof()
            self._failure_stage = "before-result"
            result = self._result(inventory_ok=True)
            self.caller = caller
            return result
        except Exception as exc:
            self._record_failure(exc)
            _close(handle)
            self.fenced = True
            self._drop()
            self._proof_failure(_inventory_reason(exc))
            if isinstance(exc, ShadowUnavailable):
                raise
            raise ShadowUnavailable("native-failed") from None

    def _observe(self, deadline: float) -> dict:
        phase = "after" if self.after_attempted else "before"
        self._maintain()
        self._failure_stage = f"{phase}-authority"
        if self.custody is None:
            raise ShadowUnavailable("policy-inactive")
        if self.stop_event.is_set():
            raise ShadowUnavailable("stopped")
        self._failure_stage = f"{phase}-peer"
        self.desktop.verify()
        if self.w.pipe.GetNamedPipeServerProcessId(self.custody.handle) != self.desktop.pid:
            raise ShadowUnavailable("peer-mismatch")
        self.native_sequence += 1
        request_id = self.native_sequence
        self._failure_stage = f"{phase}-write"
        self.custody.write({"jsonrpc": "2.0", "id": request_id, "method": "tools/list"}, deadline)
        self._failure_stage = f"{phase}-read"
        value = self.custody.read(deadline)
        self._failure_stage = f"{phase}-validate-envelope"
        if set(value) != {"jsonrpc", "id", "result"}:
            error = value.get("error")
            if (set(value) == {"jsonrpc", "id", "error"} and value["jsonrpc"] == "2.0"
                    and type(value["id"]) is int and value["id"] == request_id
                    and type(error) is dict and set(error) == {"code", "message"}
                    and type(error["code"]) is int):
                if error["code"] == -32602 and error["message"] == "Invalid app tool request":
                    self._failure_stage = f"{phase}-validate-error-invalid-request"
                elif error["code"] == -32000 and error["message"] == "Codex app tool request failed":
                    self._failure_stage = f"{phase}-validate-error-tool-list"
            raise ShadowUnavailable("invalid-response")
        self._failure_stage = f"{phase}-validate-version"
        if value["jsonrpc"] != "2.0":
            raise ShadowUnavailable("invalid-response")
        self._failure_stage = f"{phase}-validate-id-type"
        if type(value["id"]) is not int:
            raise ShadowUnavailable("invalid-response")
        self._failure_stage = f"{phase}-validate-id-match"
        if value["id"] != request_id:
            raise ShadowUnavailable("invalid-response")
        self._failure_stage = f"{phase}-validate-result-type"
        if not isinstance(value["result"], dict):
            raise ShadowUnavailable("invalid-response")
        self._failure_stage = f"{phase}-validate-result-fields"
        if set(value["result"]) != {"tools"}:
            raise ShadowUnavailable("invalid-response")
        self._failure_stage = f"{phase}-validate-tools-type"
        if not isinstance(value["result"]["tools"], list):
            raise ShadowUnavailable("invalid-response")
        self._failure_stage = f"{phase}-validate-tools-limit"
        if len(value["result"]["tools"]) > 512:
            raise ShadowUnavailable("invalid-response")
        names = set()
        for tool in value["result"]["tools"]:
            self._failure_stage = f"{phase}-validate-tool-type"
            if not isinstance(tool, dict):
                raise ShadowUnavailable("invalid-response")
            self._failure_stage = f"{phase}-validate-tool-fields"
            if not {"name", "inputSchema"} <= set(tool):
                raise ShadowUnavailable("invalid-response")
            self._failure_stage = f"{phase}-validate-tool-name"
            if not _text(tool["name"]):
                raise ShadowUnavailable("invalid-response")
            self._failure_stage = f"{phase}-validate-tool-duplicate"
            if tool["name"] in names:
                raise ShadowUnavailable("invalid-response")
            self._failure_stage = f"{phase}-validate-schema-type"
            if not isinstance(tool["inputSchema"], dict):
                raise ShadowUnavailable("invalid-response")
            self._failure_stage = f"{phase}-validate-schema-object"
            if tool["inputSchema"].get("type") != "object":
                raise ShadowUnavailable("invalid-response")
            names.add(tool["name"])
        compatible = _owner_tool_schema_valid(value["result"]["tools"])
        if self.after_attempted:
            self.owner_tool_after = compatible
        else:
            self.owner_tool_before = compatible
        self._maintain()
        self._failure_stage = f"{phase}-authority"
        if self.custody is None or time.monotonic() >= deadline:
            raise ShadowUnavailable("policy-inactive")
        self._failure_stage = f"{phase}-peer"
        self.desktop.verify()
        self._failure_stage = f"{phase}-result"
        return self._result(reason="observed", inventory_ok=True)

    def _publish_proof(self) -> None:
        if self.proof is None:
            return
        phase = ("failure" if self.proof["failure"] != "none" else "after" if self.proof["after_inventory_ok"]
                 else "exit" if self.proof["source_exited"] else "before" if self.proof["before_inventory_ok"] else None)
        if phase is not None and phase not in self.published_phases:
            _create_phase(self.w, self.directory / f"proof-{phase}.json", self.sid, json.dumps(self.proof).encode("utf-8"))
            self.published_phases.add(phase)

    def _proof_failure(self, reason: str) -> None:
        if self.proof is not None and "after" not in self.published_phases and self.proof["failure"] == "none":
            self.proof["failure"] = reason
            self._publish_proof()

    def _after_source_exit(self) -> None:
        if (self.source is None or self.custody is None or self.proof is None
                or self.after_attempted or not self.proof["before_inventory_ok"]):
            return
        self._failure_stage = "source-exit"
        state = self.w.event.WaitForSingleObject(self.source.handle, 0)
        if state == self.w.event.WAIT_TIMEOUT:
            return
        self.after_attempted = True
        try:
            if state != self.w.event.WAIT_OBJECT_0:
                raise ShadowUnavailable("peer-mismatch")
            self.proof["source_exited"] = True
            self._failure_stage = "exit-proof"
            self._publish_proof()
            # No source liveness requirement here: the retained handle proved exit.
            self._maintain()
            self._failure_stage = "after-authority"
            if self.stop_event.is_set() or self.custody is None:
                raise ShadowUnavailable("policy-inactive")
            self._observe(time.monotonic() + EXCHANGE_SECONDS)
            self.proof["after_inventory_ok"] = True
            self._failure_stage = "after-proof"
            self._publish_proof()
        except Exception as exc:
            self._record_failure(exc)
            self.fenced = True
            self._drop()
            self._proof_failure(_inventory_reason(exc))

    def _maybe_install_trial(self) -> None:
        if (self._trial_install_seen or self.trial_relay is None or self.trial_registry is None
                or self.custody is None or self.caller is None or self.proof is None
                or self.proof.get("before_inventory_ok") is not True):
            return
        request_path = self.directory / "trial-request.json"
        if not request_path.is_file():
            return
        self._trial_install_seen = True
        try:
            value = _json(_read_private(self.w, request_path, self.sid))
            if (set(value) != {"version", "action", "service_epoch", "revision", "source_thread_ref",
                               "endpoint_id", "session_ref", "container_ref", "trial_id"}
                    or type(value["version"]) is not int or value["version"] != 1
                    or value["action"] != "codex-unloaded-payload-trial"
                    or value["service_epoch"] != self.epoch
                    or type(value["revision"]) is not int or value["revision"] != self.policy.revision
                    or value["source_thread_ref"] != self.caller[0]
                    or value["session_ref"] == self.caller[0]
                    or not all(_text(value[key]) for key in (
                        "endpoint_id", "session_ref", "container_ref", "trial_id"))):
                raise ShadowUnavailable("invalid-message")
            self._authorize(self.policy.revision)
            with self.trial_registry._lock:
                if self.trial_registry.reserved(value["endpoint_id"]):
                    return
                installed = self.trial_relay.enroll_codex_trial(
                    endpoint_id=value["endpoint_id"], session_ref=value["session_ref"],
                    container_ref=value["container_ref"], trial_id=value["trial_id"],
                )
            if not installed:
                return
            _create_phase(self.w, self.directory / "trial-installed.json", self.sid, json.dumps({
                "version": 1, "service_epoch": self.epoch, "revision": self.policy.revision,
                "status": "installed",
            }).encode("utf-8"))
        except Exception:
            _log.warning("codex_trial_install outcome=denied")

    def _maybe_bind_trial(self) -> None:
        if (self._trial_action_seen or self.trial_relay is None or self.trial_registry is None
                or self.custody is None or self.caller is None or self.policy is None
                or self.proof is None or self.proof.get("before_inventory_ok") is not True
                or not (self.directory / "trial-installed.json").is_file()):
            return
        path = self.directory / "trial-action.json"
        if not path.is_file():
            return
        self._trial_action_seen = True
        try:
            installed = _json(_read_private(self.w, self.directory / "trial-installed.json", self.sid))
            if (set(installed) != {"version", "service_epoch", "revision", "status"}
                    or installed != {"version": 1, "service_epoch": self.epoch,
                                     "revision": self.policy.revision, "status": "installed"}):
                raise ShadowUnavailable("invalid-proof")
            value = _json(_read_private(self.w, path, self.sid))
            if (set(value) != {"version", "action", "service_epoch", "revision", "source_thread_ref",
                               "endpoint_id", "trial_id", "delivery_id", "expires_at"}
                    or type(value["version"]) is not int or value["version"] != 1
                    or value["action"] != "codex-unloaded-payload-owner-call"
                    or value["service_epoch"] != self.epoch
                    or type(value["revision"]) is not int or value["revision"] != self.policy.revision
                    or value["source_thread_ref"] != self.caller[0]
                    or not all(_text(value[key]) for key in ("endpoint_id", "trial_id", "delivery_id"))):
                raise ShadowUnavailable("invalid-message")
            expiry = datetime.fromisoformat(value["expires_at"].replace("Z", "+00:00"))
            if (expiry.tzinfo is None or expiry.utcoffset().total_seconds() != 0
                    or not 0 < (expiry - self.utc_clock()).total_seconds() <= 180):
                raise ShadowUnavailable("policy-inactive")
            self.source.check()
            self._authorize(self.policy.revision)
            with self.trial_registry._lock:
                bound = self.trial_relay.bind_codex_trial_delivery(
                    endpoint_id=value["endpoint_id"], trial_id=value["trial_id"],
                    delivery_id=value["delivery_id"],
                )
            if not bound:
                return
            _create_phase(self.w, self.directory / "trial-bound.json", self.sid, json.dumps({
                "version": 1, "service_epoch": self.epoch, "revision": self.policy.revision,
                "status": "bound",
            }).encode("utf-8"))
            self.trial_action = (value, expiry)
        except Exception:
            _log.warning("codex_trial_bind outcome=denied")

    def _maybe_execute_trial(self) -> None:
        if (self._trial_owner_attempted or self.trial_action is None or self.trial_relay is None
                or self.trial_registry is None or self.policy is None or self.caller is None
                or self.custody is None or self.source is None or self.desktop is None
                or self.proof is None or self.proof.get("before_inventory_ok") is not True
                or self.proof.get("source_exited") is not True
                or self.proof.get("after_inventory_ok") is not True
                or "after" not in self.published_phases):
            return
        self._trial_owner_attempted = True
        action, expiry = self.trial_action
        outcome = "denied"
        try:
            if (not self.owner_tool_before or not self.owner_tool_after
                    or self.utc_clock() >= expiry or self.stop_event.is_set()
                    or self.w.event.WaitForSingleObject(self.source.handle, 0) != self.w.event.WAIT_OBJECT_0
                    or self._load() != self.policy):
                raise ShadowUnavailable("policy-inactive")
            self.current.check()
            self.desktop.verify()
            if self.w.pipe.GetNamedPipeServerProcessId(self.custody.handle) != self.desktop.pid:
                raise ShadowUnavailable("peer-mismatch")
            endpoint_id = action["endpoint_id"]
            trial_id = action["trial_id"]
            delivery_id = action["delivery_id"]
            with self.trial_registry._lock:
                target = self.trial_relay.session_scope_by_endpoint(endpoint_id)
                if (target.get("runtime") != "codex" or not _text(target.get("session_ref"))
                        or target["session_ref"] == self.caller[0]):
                    raise ShadowUnavailable("invalid-message")
                if not self.trial_relay.spend_codex_trial(
                        endpoint_id=endpoint_id, trial_id=trial_id, delivery_id=delivery_id):
                    raise ShadowUnavailable("policy-inactive")
                # The durable fence is now spent, including if any later operation is ambiguous.
                outcome = "inconclusive"
                if not self.trial_relay.codex_trial_action_ready(
                        endpoint_id=endpoint_id, trial_id=trial_id, delivery_id=delivery_id):
                    raise ShadowUnavailable("policy-inactive")
                if (self.stop_event.is_set() or self.utc_clock() >= expiry
                        or self._load() != self.policy):
                    raise ShadowUnavailable("policy-inactive")
                self.current.check()
                self.desktop.verify()
                if self.w.pipe.GetNamedPipeServerProcessId(self.custody.handle) != self.desktop.pid:
                    raise ShadowUnavailable("peer-mismatch")
                from app.codex_wake import _wake_prompt
                self.native_sequence += 1
                request_id = self.native_sequence
                deadline = time.monotonic() + EXCHANGE_SECONDS
                self.custody.write({"jsonrpc": "2.0", "id": request_id, "method": "tools/call",
                    "params": {"namespace": "codex_app", "tool": "send_message_to_thread",
                        "arguments": {"threadId": target["session_ref"],
                                      "prompt": _wake_prompt(delivery_id)},
                        "callerSource": "codex", "callId": secrets.token_hex(16),
                        "threadId": self.caller[0], "turnId": self.caller[1]}}, deadline)
                response = self.custody.read(deadline)
                if (set(response) == {"jsonrpc", "id", "result"}
                        and response["jsonrpc"] == "2.0"
                        and type(response["id"]) is int and response["id"] == request_id
                        and isinstance(response["result"], dict)
                        and response["result"].get("isError", False) is False):
                    outcome = "submitted"
        except Exception:
            pass  # Only the fixed outcome may leave this custody boundary.
        try:
            _create_phase(self.w, self.directory / "trial-outcome.json", self.sid, json.dumps({
                "version": 1, "service_epoch": self.epoch, "revision": self.policy.revision,
                "status": outcome,
            }).encode("utf-8"))
        except Exception:
            pass  # The spent SQLite fence is authoritative even without this advisory proof.
        _log.warning("codex_trial_owner outcome=%s", outcome)

    def _run(self) -> None:
        owner = io = peer = None
        self.current = None
        try:
            self.w = _native()
            self.sid = _self_sid(self.w)
            _check_path(self.w, self.directory, self.sid)
            owner = _lock_file(self.w, self.directory / "service.lock", self.sid)
            self.current = _Peer(self.w, os.getpid(), self.sid)
            pipe_name = rf"\\.\pipe\pallium-inventory-{self.epoch}"
            handle = self.w.pipe.CreateNamedPipe(pipe_name,
                self.w.pipe.PIPE_ACCESS_DUPLEX | self.w.con.FILE_FLAG_OVERLAPPED | FIRST_PIPE_INSTANCE,
                self.w.pipe.PIPE_TYPE_MESSAGE | self.w.pipe.PIPE_READMODE_MESSAGE | self.w.pipe.PIPE_WAIT | self.w.pipe.PIPE_REJECT_REMOTE_CLIENTS,
                1, MAX_MESSAGE + 1, MAX_MESSAGE + 1, 2000, _security_attributes(self.w, self.sid))
            io = _PipeIO(self.w, handle, self.stop_event)
            manifest = {"version": 1, "pid": self.current.pid, "creation": self.current.creation,
                        "epoch": self.epoch, "pipe": pipe_name}
            _atomic_private(self.w, self.directory / "active.json", self.sid, json.dumps(manifest).encode("utf-8"))
            while not self.stop_event.is_set():
                self._maintain()
                self._after_source_exit()
                self._maybe_install_trial()
                self._maybe_bind_trial()
                self._maybe_execute_trial()
                if (self.source is not None and (self.policy is None or self.replace_allowed)
                        and (time.monotonic() >= self.ready_deadline
                             or self.w.event.WaitForSingleObject(self.source.handle, 0) == self.w.event.WAIT_OBJECT_0)):
                    self.source.close()
                    self.source = None
                    self.ready_announced = False
                try:
                    io.accept(time.monotonic() + .1)
                except ShadowUnavailable as exc:
                    if exc.category == "deadline" and not io.unresolved:
                        continue
                    raise
                peer = _Peer(self.w, self.w.pipe.GetNamedPipeClientProcessId(handle), self.sid)
                sequence = 0
                if self.source is None or (self.replace_allowed and self.custody is None):
                    if self.source is not None:
                        self.source.close()
                    self.source = peer
                    if self.replace_allowed:
                        self.fenced = False
                    self.ready_announced = False
                    self.ready_deadline = time.monotonic() + GRANT_SECONDS
                elif self.source.pid == peer.pid and self.source.creation == peer.creation:
                    peer.close()
                    peer = self.source
                try:
                    while not self.stop_event.is_set():
                        self._maintain()
                        self._after_source_exit()
                        self._maybe_install_trial()
                        self._maybe_bind_trial()
                        self._maybe_execute_trial()
                        if self.custody is None and (self.fenced or time.monotonic() >= self.ready_deadline):
                            break
                        try:
                            request = io.read(time.monotonic() + .1)
                        except ShadowUnavailable as exc:
                            if exc.category == "deadline" and not io.unresolved:
                                continue
                            raise
                        deadline = time.monotonic() + EXCHANGE_SECONDS
                        try:
                            response = self._process(request, peer, sequence, deadline)
                        except ShadowUnavailable as exc:
                            response = _inventory_public("unavailable", _inventory_reason(exc))
                        else:
                            sequence = request["sequence"]
                        candidate = request.get("sequence")
                        response.update(version=1, epoch=self.epoch,
                                        sequence=candidate if _integer(candidate, 1) else sequence)
                        io.write(response, deadline)
                except ShadowUnavailable:
                    if io.unresolved or self.stop_event.is_set():
                        raise
                finally:
                    self.admitted = None
                    if not io.unresolved:
                        self.w.pipe.DisconnectNamedPipe(handle)
                        if (self.policy is None or self.replace_allowed) and self.custody is None and peer is self.source:
                            self.source.close()
                            self.source = None
                            self.ready_announced = False
                            peer = None
                        if peer is not self.source:
                            if peer is not None:
                                peer.close()
                        peer = None
        except Exception as exc:
            self._record_failure(exc)
            self.stop_event.set()
            try:
                self._proof_failure(_inventory_reason(exc))
            except Exception:
                pass
        finally:
            self._drop()
            self.unresolved = self.unresolved or (io is not None and io.unresolved)
            if self.unresolved:
                _retained.append((self, io, owner, peer, self.source, self.desktop, self.current))
            else:
                if self.source is not None:
                    self.source.close()
                if peer is not None and peer is not self.source:
                    peer.close()
                if self.current is not None:
                    self.current.close()
                if io is not None:
                    io.close()
                _close(owner)


def start_inventory_service(*, trial_relay=None, trial_registry=None) -> InventoryService | None:
    if sys.platform != "win32":
        return None
    try:
        directory = inventory_directory()
        if not native_available():
            return None
        w = _native()
        if w.file.GetDriveType(directory.anchor) != w.con.DRIVE_FIXED:
            return None
        if not directory.is_dir():
            return None
        _check_path(w, directory, _self_sid(w))
        _check_private_parent(w, directory / "active.json", _self_sid(w))
        return InventoryService(directory, trial_relay=trial_relay, trial_registry=trial_registry).start()
    except Exception:
        return None


class NativeInventoryClient:
    """Only its own inherited endpoint may cross the authenticated admission channel."""

    def __init__(self, bootstrap_path: Path, stop_event: threading.Event):
        self.w = _native()
        self.bootstrap_path, self.stop_event = Path(bootstrap_path), stop_event
        self.io = self.peer = self.source = None
        self.sequence = 0
        self.unresolved = False
        try:
            self.sid = _self_sid(self.w)
            self.manifest = _json(_read_private(self.w, self.bootstrap_path, self.sid))
            m = self.manifest
            if (set(m) != {"version", "pid", "creation", "epoch", "pipe"}
                    or type(m["version"]) is not int or m["version"] != 1
                    or not _integer(m["pid"], 1) or not _text(m["creation"]) or not _text(m["epoch"])
                    or m["pipe"] != rf"\\.\pipe\pallium-inventory-{m['epoch']}"):
                raise ShadowUnavailable("invalid-bootstrap")
            handle = self.w.file.CreateFile(m["pipe"], self.w.con.GENERIC_READ | self.w.con.GENERIC_WRITE,
                0, None, self.w.con.OPEN_EXISTING,
                self.w.con.FILE_FLAG_OVERLAPPED | self.w.con.SECURITY_SQOS_PRESENT | self.w.file.SECURITY_IDENTIFICATION, None)
            self.io = _PipeIO(self.w, handle, stop_event)
            self.w.pipe.SetNamedPipeHandleState(handle, self.w.pipe.PIPE_READMODE_MESSAGE, None, None)
            if self.w.pipe.GetNamedPipeServerProcessId(handle) != m["pid"]:
                raise ShadowUnavailable("peer-mismatch")
            self.peer = _Peer(self.w, m["pid"], self.sid, m["creation"])
            self.source = _Peer(self.w, os.getpid(), self.sid)
        except Exception:
            self.dispose()
            raise ShadowUnavailable("channel-unavailable") from None

    def _exchange(self, verb: str, **extra) -> dict:
        if self.stop_event.is_set() or self.io is None:
            raise ShadowUnavailable("stopped")
        if _json(_read_private(self.w, self.bootstrap_path, self.sid)) != self.manifest:
            raise ShadowUnavailable("peer-mismatch")
        self.peer.check()
        self.source.check()
        self.sequence += 1
        deadline = time.monotonic() + EXCHANGE_SECONDS
        self.io.write({"version": 1, "verb": verb, "epoch": self.manifest["epoch"],
                       "sequence": self.sequence, **extra}, deadline)
        response = self.io.read(deadline)
        fields = {"mode", "status", "reason", "ttl_seconds", "connected", "inventory_ok", "source_exited",
                  "version", "epoch", "sequence"}
        if verb == "admit" and response.get("status") == "ready":
            fields.add("revision")
        if (set(response) != fields or response.get("mode") != "inventory"
                or type(response.get("version")) is not int or response["version"] != 1
                or type(response.get("sequence")) is not int or response["sequence"] != self.sequence
                or response.get("epoch") != self.manifest["epoch"]
                or not isinstance(response.get("status"), str)
                or response.get("status") not in {"ready", "registered", "inactive", "unavailable"}
                or not isinstance(response.get("reason"), str)
                or response.get("reason") not in {"ready", "ok", "observed", "closed", "policy-inactive",
                    "policy-changed", "peer-mismatch", "busy", "stopped", "native-failed", "timeout"}
                or not _integer(response.get("ttl_seconds")) or response["ttl_seconds"] > GRANT_SECONDS
                or any(type(response.get(k)) is not bool for k in ("connected", "inventory_ok", "source_exited"))
                or ("revision" in fields and not _integer(response.get("revision"), 1))):
            raise ShadowUnavailable("invalid-response")
        return response

    @staticmethod
    def _public(response: dict) -> dict:
        return {k: response[k] for k in ("mode", "status", "reason", "ttl_seconds", "connected", "inventory_ok", "source_exited")}

    def ready(self) -> dict:
        return self._public(self._exchange("ready"))

    def register(self, metadata: dict[str, str]) -> dict:
        if (not isinstance(metadata, dict) or set(metadata) != {"thread_ref", "turn_ref"}
                or not all(_text(value) for value in metadata.values())):
            raise ShadowUnavailable("invalid-message")
        admitted = self._exchange("admit", **metadata)
        if admitted["status"] != "ready" or admitted["reason"] != "ok":
            return self._public(admitted)
        policy = InventoryPolicy.parse(_read_private(self.w, self.bootstrap_path.parent / "policy.json", self.sid))
        if not policy.valid(datetime.now(timezone.utc)) or policy.revision != admitted["revision"]:
            raise ShadowUnavailable("policy-inactive")
        if (policy.service_pid != self.peer.pid or policy.service_creation != self.peer.creation
                or policy.service_epoch != self.manifest["epoch"]
                or policy.source_pid != self.source.pid or policy.source_creation != self.source.creation):
            raise ShadowUnavailable("peer-mismatch")
        desktop = _DesktopPeer(self.w, policy)
        try:
            if InventoryPolicy.parse(_read_private(self.w, self.bootstrap_path.parent / "policy.json", self.sid)) != policy:
                raise ShadowUnavailable("policy-changed")
            self.peer.check()
            self.source.check()
            desktop.verify()
            # This read is deliberately after both independent finite-authority checks.
            endpoint = os.environ.get("CODEX_APP_TOOLS_PIPE_PATH")
            if not isinstance(endpoint, str) or not endpoint:
                raise ShadowUnavailable("channel-unavailable")
            return self._public(self._exchange("transfer", revision=policy.revision, endpoint=endpoint))
        finally:
            desktop.close()

    def dispose(self) -> None:
        """EOF closes the private source channel; service custody remains authorized."""
        self.unresolved = self.io is not None and self.io.unresolved
        if self.unresolved:
            _retained.append(self)
            return
        if self.io is not None:
            self.io.close()
            self.io = None
        for peer in (self.peer, self.source):
            if peer is not None:
                peer.close()
        self.peer = self.source = None
