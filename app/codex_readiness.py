"""Best-effort evidence for the installed Codex UserPromptSubmit hook."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_MAX_BYTES = 32 * 1024
_STATES = {"unknown", "review_required", "verified"}


def marker_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".pallium" / "hooks" / "readiness" / "codex.json"


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


def setup(
    *, python: str, script: str, changed: bool, home: Path | None = None
) -> dict[str, Any]:
    """Record definition reconciliation; never infer Codex-owned trust."""
    definition = expected(python, script)
    current = _read(marker_path(home))
    if changed:
        value = {
            "version": 1,
            "state": "review_required",
            "definition": definition,
            "updated_at": _now(),
        }
    elif (
        current is not None
        and current.get("definition") == definition
        and current.get("state") in {"review_required", "verified"}
    ):
        value = current
    else:
        value = {
            "version": 1,
            "state": "unknown",
            "definition": definition,
            "updated_at": _now(),
        }
    try:
        _write(value, home)
    except Exception:
        pass
    return _public(value)


def observe_execution(
    *, python: str, script: str, home: Path | None = None
) -> bool:
    """Record execution only when it matches the reconciled definition."""
    try:
        current = _read(marker_path(home))
        definition = expected(python, script)
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
