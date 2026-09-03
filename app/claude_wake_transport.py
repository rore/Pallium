"""Transport layer for Claude Code wake via local socket/pipe messaging."""

from __future__ import annotations

import json
import os
import socket
import threading
import uuid


# ponytail: unresolved Windows I/O remains process-local until signal or exit; add completion callbacks only if leak telemetry warrants it.
_pending_windows_writes: list[tuple[object, object]] = []
_pending_windows_writes_lock = threading.Lock()


def _reap_pending_windows_writes(win32event, win32file) -> None:
    """Release completed timeout writes; unresolved I/O remains until signal or process exit."""
    with _pending_windows_writes_lock:
        pending = list(_pending_windows_writes)
        _pending_windows_writes.clear()
    retained = []
    for overlapped, event in pending:
        try:
            if win32event.WaitForSingleObject(event, 0) != win32event.WAIT_OBJECT_0:
                retained.append((overlapped, event))
                continue
            win32file.CloseHandle(event)
        except Exception:
            retained.append((overlapped, event))
    if retained:
        with _pending_windows_writes_lock:
            _pending_windows_writes.extend(retained)

def claude_wake_transport(socket_path: str, token: str) -> str:
    """Write auth and peer message to a registered Claude Code session endpoint.

    Args:
        socket_path: Unix domain socket path (POSIX) or named pipe path (Windows).
        token: Authentication token (never stored or logged).

    Returns:
        ``"accepted"`` on clean write, ``"terminal"`` only for a proven missing endpoint, and ``"retryable"`` for all uncertainty.

    Platform-specific:
        POSIX: AF_UNIX socket with ~2s timeout.
        Windows: Named pipe via win32file.CreateFile.

    ponytail: clean-write == success; skips reading peer_message_status receipt (add in S1).
    """
    if os.name == "nt":
        return _windows_transport(socket_path, token)
    else:
        return _posix_transport(socket_path, token)


def _posix_transport(socket_path: str, token: str) -> str:
    """Connect, authenticate, and classify a local Unix socket wake."""
    sock = None
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect(socket_path)
        sock.sendall((json.dumps({"type": "auth", "token": token}) + "\n").encode("utf-8"))
        frame = {"msgV": 1, "msg_id": uuid.uuid4().hex, "type": "user", "message": {"role": "user", "content": "Pallium Relay wake notice: new messages available."}, "priority": "next", "from": "pallium-relay"}
        sock.sendall((json.dumps(frame) + "\n").encode("utf-8"))
        return "accepted"
    except FileNotFoundError:
        return "terminal"
    except (OSError, ValueError, socket.timeout):
        return "retryable"
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

def _windows_transport(socket_path: str, token: str) -> str:
    """Open a named pipe and classify only proven endpoint absence as terminal."""
    try:
        import pywintypes
        import win32event
        import win32file
        import winerror
    except ImportError:
        return "retryable"
    handle = None
    try:
        handle = win32file.CreateFile(socket_path, win32file.GENERIC_WRITE, 0, None, win32file.OPEN_EXISTING, win32file.FILE_FLAG_OVERLAPPED, None)
        auth = (json.dumps({"type": "auth", "token": token}) + "\n").encode("utf-8")
        if not _windows_write(handle, auth, pywintypes, win32event, win32file, winerror):
            return "retryable"
        frame = {"msgV": 1, "msg_id": uuid.uuid4().hex, "type": "user", "message": {"role": "user", "content": "Pallium Relay wake notice: new messages available."}, "priority": "next", "from": "pallium-relay"}
        return "accepted" if _windows_write(handle, (json.dumps(frame) + "\n").encode("utf-8"), pywintypes, win32event, win32file, winerror) else "retryable"
    except pywintypes.error as exc:
        return "terminal" if exc.winerror == winerror.ERROR_FILE_NOT_FOUND else "retryable"
    except Exception:
        return "retryable"
    finally:
        if handle is not None:
            try:
                win32file.CloseHandle(handle)
            except (OSError, NameError):
                pass

def _windows_write(handle, data, pywintypes, win32event, win32file, winerror) -> bool:
    """Write one frame with bounded overlapped I/O and safe cancellation."""
    _reap_pending_windows_writes(win32event, win32file)
    overlapped = pywintypes.OVERLAPPED()
    overlapped.hEvent = win32event.CreateEvent(None, True, False, None)
    completed = False
    try:
        error_code, _ = win32file.WriteFile(handle, data, overlapped)
        if error_code == 0:
            completed = True
            return True
        if error_code != winerror.ERROR_IO_PENDING:
            completed = True
            return False
        if win32event.WaitForSingleObject(overlapped.hEvent, 2000) != win32event.WAIT_OBJECT_0:
            try:
                cancel = getattr(win32file, "CancelIoEx", None)
                if cancel is None:
                    win32file.CancelIo(handle)
                else:
                    cancel(handle, overlapped)
            except Exception:
                pass
            try:
                win32file.GetOverlappedResult(handle, overlapped, False)
                completed = True
            except Exception as exc:
                completed = getattr(exc, "winerror", None) == getattr(winerror, "ERROR_OPERATION_ABORTED", 995)
            if not completed:
                with _pending_windows_writes_lock:
                    _pending_windows_writes.append((overlapped, overlapped.hEvent))
            return False
        completed = True
        win32file.GetOverlappedResult(handle, overlapped, True)
        return True
    finally:
        if completed:
            win32file.CloseHandle(overlapped.hEvent)
