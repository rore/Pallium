"""Local, database-scoped ownership for Claude wake write-ahead state."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path


def binding_for_relay_database(relay_sqlite_url: str) -> dict[str, str] | None:
    if relay_sqlite_url == "sqlite:///:memory:":
        return None
    if not relay_sqlite_url.startswith("sqlite:///"):
        raise ValueError("Claude wake requires a SQLite Relay database")
    relay_path = Path(relay_sqlite_url[len("sqlite:///"):]).resolve()
    if relay_path.parent.name == "data" and relay_path.name == "pallium-relay.db":
        default_dir = relay_path.parent.parent / "claude-wake"
    else:
        default_dir = relay_path.with_name(relay_path.name + "-claude-wake")
    wake_dir = Path(os.environ.get("PALLIUM_CLAUDE_WAKE_DIR", str(default_dir))).resolve()
    installed_dir = (Path.home() / ".pallium" / "claude-wake").resolve()
    installed_db = (Path.home() / ".pallium" / "data" / "pallium-relay.db").resolve()
    if wake_dir == installed_dir and relay_path != installed_db:
        raise ValueError("custom Relay database cannot own the installed Claude wake directory")
    return {
        "relay_id": hashlib.sha256(str(relay_path).encode("utf-8")).hexdigest(),
        "wake_dir": str(wake_dir),
    }


def binding_fingerprint(binding: dict[str, object]) -> str:
    identity = f"{binding['relay_id']}\0{binding['wake_dir']}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def hook_binding_path() -> Path:
    return Path.home() / ".pallium" / "hooks" / "claude-wake-binding.json"


def service_marker_path(port: int) -> Path:
    if not 1 <= port <= 65535:
        raise ValueError("invalid Pallium port")
    return Path.home() / ".pallium" / "hooks" / f"claude-wake-service-{port}.json"


def read_binding(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict) or set(value) != {"port", "relay_id", "wake_dir"}:
        return None
    if not isinstance(value["port"], int) or not 1 <= value["port"] <= 65535:
        return None
    if not isinstance(value["relay_id"], str) or len(value["relay_id"]) != 64:
        return None
    if not isinstance(value["wake_dir"], str) or not Path(value["wake_dir"]).is_absolute():
        return None
    return value


def write_json_atomic(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")
        if os.name != "nt":
            os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def claim_wake_directory(binding: dict[str, str]) -> None:
    """Refuse a second Relay database before loading any persisted credentials."""
    state_dir = Path(binding["wake_dir"])
    state_dir.mkdir(parents=True, exist_ok=True)
    owner = state_dir / "relay-owner.json"
    installed_db = (Path.home() / ".pallium" / "data" / "pallium-relay.db").resolve()
    legacy_installed = (
        state_dir == (Path.home() / ".pallium" / "claude-wake").resolve()
        and binding["relay_id"] == hashlib.sha256(str(installed_db).encode("utf-8")).hexdigest()
    )
    if not owner.exists() and any(state_dir.iterdir()) and not legacy_installed:
        raise ValueError("unowned Claude wake directory contains existing state")
    try:
        handle = os.open(owner, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        try:
            current = json.loads(owner.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError("Claude wake directory owner is unreadable") from exc
        if current != {"relay_id": binding["relay_id"]}:
            raise ValueError("Claude wake directory belongs to another Relay database")
    else:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump({"relay_id": binding["relay_id"]}, stream)
            stream.flush()
            os.fsync(stream.fileno())
