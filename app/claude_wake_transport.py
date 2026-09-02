"""Transport layer for Claude Code wake via local socket/pipe messaging."""

from __future__ import annotations

import json
import os
import socket
import uuid


def claude_wake_transport(socket_path: str, token: str) -> bool:
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


def _posix_transport(socket_path: str, token: str) -> bool:
    """Connect to Unix domain socket, write auth line + peer frame."""
    sock = None
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect(socket_path)

        # Write auth line
        auth_frame = json.dumps({"type": "auth", "token": token}) + "\n"
        sock.sendall(auth_frame.encode("utf-8"))

        # Write peer message frame
        peer_frame = json.dumps({
            "msgV": 1,
            "msg_id": uuid.uuid4().hex,
            "type": "user",
            "message": {
                "role": "user",
                "content": "Pallium Relay wake notice: new messages available.",
            },
            "priority": "next",
            "from": "pallium-relay",
        }) + "\n"
        sock.sendall(peer_frame.encode("utf-8"))

        return True
    except (OSError, ValueError, socket.timeout):
        return False
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


def _windows_transport(socket_path: str, token: str) -> bool:
    """Open named pipe, write auth line + peer frame."""
    try:
        import pywintypes
        import win32event
        import win32file
        import winerror
    except ImportError:
        return False

    handle = None
    try:
        # Open the named pipe
        handle = win32file.CreateFile(
            socket_path,
            win32file.GENERIC_WRITE,
            0,
            None,
            win32file.OPEN_EXISTING,
            win32file.FILE_FLAG_OVERLAPPED,
            None,
        )

        # Write auth line
        auth_frame = json.dumps({"type": "auth", "token": token}) + "\n"
        if not _windows_write(handle, auth_frame.encode("utf-8"), pywintypes, win32event, win32file, winerror):
            return False

        # Write peer message frame
        peer_frame = json.dumps({
            "msgV": 1,
            "msg_id": uuid.uuid4().hex,
            "type": "user",
            "message": {
                "role": "user",
                "content": "Pallium Relay wake notice: new messages available.",
            },
            "priority": "next",
            "from": "pallium-relay",
        }) + "\n"
        return _windows_write(handle, peer_frame.encode("utf-8"), pywintypes, win32event, win32file, winerror)
    except Exception:
        return False
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
                pass
            return False
        completed = True
        win32file.GetOverlappedResult(handle, overlapped, True)
        return True
    finally:
        if completed:
            win32file.CloseHandle(overlapped.hEvent)
