"""Transport layer for Claude Code wake via local socket/pipe messaging."""

from __future__ import annotations

import json
import os
import socket
import uuid


def claude_wake_transport(socket_path: str, token: str) -> str:
    """Write auth and peer message to a registered Claude Code session endpoint.

    Args:
        socket_path: Unix domain socket path (POSIX) or named pipe path (Windows).
        token: Authentication token (never stored or logged).

    Returns:
        True on clean write, False on any error (swallows all exceptions).

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
                win32file.GetOverlappedResult(handle, overlapped, True)
                completed = True
            except Exception:
                completed = True
            return False
        completed = True
        win32file.GetOverlappedResult(handle, overlapped, True)
        return True
    finally:
        if completed:
            win32file.CloseHandle(overlapped.hEvent)
