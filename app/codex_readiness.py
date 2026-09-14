"""Best-effort evidence for the installed Codex UserPromptSubmit hook."""

from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_MAX_BYTES = 32 * 1024
_STATES = {"unknown", "review_required", "verified"}
_LOCK_WAIT_SECONDS = 2.0
_HOOK_LOCK_WAIT_SECONDS = 0.15


def marker_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".pallium" / "hooks" / "readiness" / "codex.json"


@contextmanager
def _marker_lock(
    home: Path | None = None,
    *,
    wait_seconds: float | None = _LOCK_WAIT_SECONDS,
):
    """Serialize one bounded marker transition across setup and hook processes."""
    path = marker_path(home).with_suffix(".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = path.open("a+b")
    try:
        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write(b"\0")
            lock_file.flush()
        if wait_seconds is None:
            lock_file.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        else:
            deadline = time.monotonic() + max(0.0, wait_seconds)
            while True:
                try:
                    lock_file.seek(0)
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(
                            lock_file.fileno(),
                            fcntl.LOCK_EX | fcntl.LOCK_NB,
                        )
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("readiness marker lock timed out")
                    time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
        try:
            yield
        finally:
            lock_file.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    finally:
        lock_file.close()


def _path(value: object) -> str:
    if not isinstance(value, str) or not value:
        return ""
    try:
        normalized = str(Path(value).expanduser().resolve(strict=False))
    except (OSError, RuntimeError, ValueError):
        normalized = os.path.abspath(value)
    return os.path.normcase(os.path.normpath(normalized)).replace("\\", "/")


def expected(python: str, script: str) -> dict[str, str]:
    return {"python": _path(python), "script": _path(script)}


def _read(path: Path) -> dict[str, Any] | None:
    try:
        if path.stat().st_size > _MAX_BYTES:
            return None
        with path.open("rb") as handle:
            raw = handle.read(_MAX_BYTES + 1)
        if len(raw) > _MAX_BYTES:
            return None
        value = json.loads(raw.decode("utf-8"))
        definition = value.get("definition") if isinstance(value, dict) else None
        if (
            not isinstance(value, dict)
            or value.get("state") not in _STATES
            or not isinstance(definition, dict)
            or not _path(definition.get("python"))
            or not _path(definition.get("script"))
        ):
            return None
        return value
    except Exception:
        return None


def _public(value: dict[str, Any] | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "state": value.get("state", "unknown") if value else "unknown",
        "hook_trust": "unknown",
        "mcp_tool_exposure": "unknown",
    }
    if value:
        for key in ("updated_at", "observed_at"):
            if isinstance(value.get(key), str):
                result[key] = value[key]
    return result


def read(home: Path | None = None) -> dict[str, Any]:
    """Return bounded public evidence without local executable or script paths."""
    return _public(_read(marker_path(home)))


def _write(value: dict[str, Any], home: Path | None = None) -> None:
    path = marker_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
    if len(payload.encode("utf-8")) > _MAX_BYTES:
        raise OSError("readiness marker too large")
    fd, temporary = tempfile.mkstemp(prefix="codex-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            fd = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _setup_value(
    *,
    definition: dict[str, str],
    current: dict[str, Any] | None,
    changed: bool,
) -> dict[str, Any]:
    if not changed and (
        current is not None
        and current.get("definition") == definition
        and current.get("state") in {"review_required", "verified"}
    ):
        return current
    return {
        "version": 1,
        "state": "review_required" if changed else "unknown",
        "definition": definition,
        "updated_at": _now(),
    }


def reconcile_setup(
    *,
    python: str,
    script: str,
    install_definition: Callable[[], bool],
    home: Path | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Install a hook definition and readiness transition under one process lock."""
    definition = expected(python, script)
    with _marker_lock(home, wait_seconds=None):
        current = _read(marker_path(home))
        _write(
            {
                "version": 1,
                "state": "unknown",
                "definition": definition,
                "updated_at": _now(),
            },
            home,
        )
        changed = bool(install_definition())
        value = _setup_value(
            definition=definition,
            current=current,
            changed=changed,
        )
        _write(value, home)
    return changed, _public(value)


def reconcile_uninstall(
    *,
    uninstall_definition: Callable[[], None],
    home: Path | None = None,
) -> None:
    """Remove the hook definition and marker without a delayed observer race."""
    with _marker_lock(home, wait_seconds=None):
        current = _read(marker_path(home))
        if current is not None:
            try:
                _write(
                    {
                        "version": 1,
                        "state": "unknown",
                        "definition": current["definition"],
                        "updated_at": _now(),
                    },
                    home,
                )
            except Exception:
                pass
        uninstall_definition()
        marker_path(home).unlink(missing_ok=True)


def setup(
    *, python: str, script: str, changed: bool, home: Path | None = None
) -> dict[str, Any]:
    """Record definition reconciliation; never infer Codex-owned trust."""
    definition = expected(python, script)
    value = _setup_value(
        definition=definition,
        current=None,
        changed=changed,
    )
    try:
        with _marker_lock(home):
            current = _read(marker_path(home))
            value = _setup_value(
                definition=definition,
                current=current,
                changed=changed,
            )
            _write(value, home)
    except Exception:
        pass
    return _public(value)


def observe_execution(
    *, python: str, script: str, home: Path | None = None
) -> bool:
    """Record execution only when it matches the reconciled definition."""
    try:
        definition = expected(python, script)
        with _marker_lock(home, wait_seconds=_HOOK_LOCK_WAIT_SECONDS):
            current = _read(marker_path(home))
            if current is None or current.get("definition") != definition:
                return False
            now = _now()
            _write(
                {
                    "version": 1,
                    "state": "verified",
                    "definition": definition,
                    "observed_at": now,
                    "updated_at": now,
                },
                home,
            )
        return True
    except Exception:
        return False
