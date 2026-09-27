"""Windows-only, shadow-only channel. Never dispatches or consumes Relay work."""

from __future__ import annotations

import json
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


class ShadowUnavailable(RuntimeError):
    """Only fixed categories leave this module; never native errors/paths."""

    def __init__(self, category: str):
        super().__init__(category)
        self.category = category


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
        handle = w.file.CreateFile(
            str(path), w.con.GENERIC_READ | w.con.GENERIC_WRITE, 0,
            _security_attributes(w, sid), w.con.OPEN_ALWAYS,
            w.con.FILE_ATTRIBUTE_NORMAL | w.file.FILE_FLAG_OPEN_REPARSE_POINT, None,
        )
        _check_path(w, path, sid)
        return handle
    except ShadowUnavailable:
        _close(locals().get("handle"))
        raise
    except Exception:
        raise ShadowUnavailable("owner-busy") from None


def _read_private(w, path: Path, sid: str) -> bytes:
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


def _atomic_private(w, path: Path, sid: str, data: bytes) -> None:
    if len(data) > MAX_MESSAGE:
        raise ShadowUnavailable("message-limit")
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


def _json(raw: bytes) -> dict:
    if not raw or len(raw) > MAX_MESSAGE:
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
    lock = _lock_file(w, directory / "policy.lock", sid)
    try:
        destination = directory / "policy.json"
        previous = ShadowPolicy.parse(_read_private(w, destination, sid)).revision if destination.exists() else 0
        if previous != expected_revision or policy.revision != previous + 1:
            raise ShadowUnavailable("revision-conflict")
        _atomic_private(w, destination, sid, raw)
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
        if not (directory / "policy.json").is_file() or not native_available():
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
