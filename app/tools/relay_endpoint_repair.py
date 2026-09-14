"""Offline, manifest-bound repair for stranded Relay endpoint deliveries."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from sqlalchemy.exc import SQLAlchemyError

from core.relay import RelayConflictError
from storage.sqlite import SQLiteStorageProvider

_SCHEMA_VERSION = 2
_ENVELOPE_KEYS = {"manifest", "sha256"}
_MANIFEST_KEYS = {"schema_version", "database_identity", "source_endpoint_ids", "destination_endpoint_id", "expected_scopes", "endpoint_preimage", "reservation_evidence", "dispositions"}
_ENDPOINT_KEYS = {"runtime", "session_ref", "container_ref", "title", "alias", "state", "first_seen_at", "last_seen_at", "closed_at", "generation", "aliases", "work_refs"}
_DELIVERY_KEYS = {"delivery_id", "message_id", "recipient_runtime", "recipient_session_ref", "recipient_endpoint_id", "recipient_container_ref", "state", "claim_token_fingerprint", "claimed_at", "lease_expires_at", "delivered_at", "attempts"}
_MESSAGE_KEYS = {"message_id", "sender_runtime", "sender_session_ref", "sender_endpoint_id", "recipient_selector", "container_ref", "payload_sha256", "payload_length", "redacted", "in_reply_to", "created_at", "expires_at"}
_ENDPOINT_RE = re.compile(r"^relay-session-[0-9a-f]{32}$")


def _path(url: str) -> Path:
    if not url.startswith("sqlite:///"):
        raise ValueError("only sqlite:/// URLs are supported")
    return Path(url[10:]).resolve()


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _claim_token_fingerprint(token: str | None) -> str | None:
    if token is None:
        return None
    return hashlib.sha256(("pallium-relay-repair-claim-token\x00" + token).encode()).hexdigest()


def _iso(value: object) -> str | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.isoformat()


def _identity(conn: sqlite3.Connection, path: Path) -> dict[str, Any]:
    return {
        "sqlite_path": str(path),
        "application_id": conn.execute("PRAGMA application_id").fetchone()[0],
        "user_version": conn.execute("PRAGMA user_version").fetchone()[0],
        "schema_version": conn.execute("PRAGMA schema_version").fetchone()[0],
    }


def _endpoint_preimage(conn: sqlite3.Connection, endpoint_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT runtime, session_ref, container_ref, title, alias, state, first_seen_at, last_seen_at, closed_at FROM relay_sessions WHERE id=?", (endpoint_id,)).fetchone()
    if row is None:
        raise ValueError("source or destination endpoint is missing")
    if row["state"] not in {"active", "unreachable", "closed"}:
        raise ValueError("endpoint state is invalid")
    generation = conn.execute("SELECT generation FROM relay_endpoint_generations WHERE endpoint_id=?", (endpoint_id,)).fetchone()
    if generation is not None and (type(generation["generation"]) is not int or generation["generation"] < 0):
        raise ValueError("endpoint generation is invalid")
    aliases = [dict(row) for row in conn.execute("SELECT alias, endpoint_id FROM relay_aliases WHERE endpoint_id=? ORDER BY alias", (endpoint_id,))]
    work_refs = [dict(row) for row in conn.execute("SELECT endpoint_id, work_ref, origin, scope_ref, local_ref, position, created_at, updated_at FROM relay_session_work_refs WHERE endpoint_id=? ORDER BY work_ref, origin", (endpoint_id,))]
    for item in work_refs:
        item["created_at"], item["updated_at"] = _iso(item["created_at"]), _iso(item["updated_at"])
    return {"runtime": row["runtime"], "session_ref": row["session_ref"], "container_ref": row["container_ref"], "title": row["title"], "alias": row["alias"], "state": row["state"], "first_seen_at": _iso(row["first_seen_at"]), "last_seen_at": _iso(row["last_seen_at"]), "closed_at": _iso(row["closed_at"]), "generation": 0 if generation is None else generation["generation"], "aliases": aliases, "work_refs": work_refs}


def _delivery_preimage(row: sqlite3.Row) -> dict[str, Any]:
    payload = row["payload"].encode()
    return {"delivery": {"delivery_id": row["delivery_id"], "message_id": row["message_id"], "recipient_runtime": row["recipient_runtime"], "recipient_session_ref": row["recipient_session_ref"], "recipient_endpoint_id": row["recipient_endpoint_id"], "recipient_container_ref": row["recipient_container_ref"], "state": row["state"], "claim_token_fingerprint": _claim_token_fingerprint(row["claim_token"]), "claimed_at": _iso(row["claimed_at"]), "lease_expires_at": _iso(row["lease_expires_at"]), "delivered_at": _iso(row["delivered_at"]), "attempts": row["attempts"]}, "message": {"message_id": row["message_id"], "sender_runtime": row["sender_runtime"], "sender_session_ref": row["sender_session_ref"], "sender_endpoint_id": row["sender_endpoint_id"], "recipient_selector": row["recipient_selector"], "container_ref": row["message_container_ref"], "payload_sha256": hashlib.sha256(payload).hexdigest(), "payload_length": len(payload), "redacted": bool(row["redacted"]), "in_reply_to": row["in_reply_to"], "created_at": _iso(row["message_created_at"]), "expires_at": _iso(row["message_expires_at"])}}


def _validate_inputs(source_ids: list[str], destination_id: str, expected_scopes: dict[str, str], dispositions: object) -> list[dict[str, str]]:
    if not 1 <= len(source_ids) <= 32 or len(set(source_ids)) != len(source_ids) or any(not isinstance(x, str) or not _ENDPOINT_RE.fullmatch(x) for x in source_ids):
        raise ValueError("supply 1..32 unique --source endpoint IDs")
    if not isinstance(destination_id, str) or not _ENDPOINT_RE.fullmatch(destination_id) or destination_id in source_ids:
        raise ValueError("supply one destination distinct from every source")
    if set(expected_scopes) != {*source_ids, destination_id} or any(not isinstance(v, str) or not v for v in expected_scopes.values()):
        raise ValueError("supply one exact --scope endpoint_id=container_ref for every endpoint")
    if not isinstance(dispositions, list) or not 1 <= len(dispositions) <= 512:
        raise ValueError("supply 1..512 dispositions")
    if any(not isinstance(item, dict) or set(item) != {"delivery_id", "disposition"} or not isinstance(item["delivery_id"], str) or not item["delivery_id"] or item["disposition"] not in {"adopt", "suppress"} for item in dispositions):
        raise ValueError("each disposition must contain exactly delivery_id and adopt or suppress")
    if len({item["delivery_id"] for item in dispositions}) != len(dispositions):
        raise ValueError("disposition delivery IDs must be unique")
    return dispositions


def build_manifest(db_url: str, source_ids: list[str], destination_id: str, expected_scopes: dict[str, str], dispositions: object) -> dict[str, Any]:
    dispositions = _validate_inputs(source_ids, destination_id, expected_scopes, dispositions)
    path = _path(db_url)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN")
        placeholders = ",".join("?" for _ in source_ids)
        endpoints = {endpoint_id: _endpoint_preimage(conn, endpoint_id) for endpoint_id in [*source_ids, destination_id]}
        if any(endpoints[source]["alias"] is not None or endpoints[source]["aliases"] or endpoints[source]["work_refs"] or endpoints[source]["container_ref"] != expected_scopes[source] for source in source_ids):
            raise ValueError("source alias, work-ref, or scope evidence is unsafe")
        if endpoints[destination_id]["container_ref"] != expected_scopes[destination_id]:
            raise ValueError("destination endpoint scope drifted")
        destination_alias = endpoints[destination_id]["alias"]
        alias_owner = None if destination_alias is None else conn.execute("SELECT endpoint_id FROM relay_aliases WHERE alias=?", (destination_alias,)).fetchone()
        if destination_alias is not None and (alias_owner is None or alias_owner["endpoint_id"] != destination_id):
            raise ValueError("destination alias ownership is inconsistent")
        expected_aliases = [] if destination_alias is None else [{"alias": destination_alias, "endpoint_id": destination_id}]
        if endpoints[destination_id]["aliases"] != expected_aliases:
            raise ValueError("destination alias ownership is inconsistent")
        siblings = {row["id"] for row in conn.execute("SELECT id FROM relay_sessions WHERE runtime=? AND session_ref=?", (endpoints[destination_id]["runtime"], endpoints[destination_id]["session_ref"]))}
        if siblings != {*source_ids, destination_id}:
            raise ValueError("same runtime/session endpoint set is incomplete")
        current = datetime.now(timezone.utc)
        claimed_rows = conn.execute("SELECT claim_token, lease_expires_at FROM relay_deliveries WHERE recipient_endpoint_id IN (" + placeholders + ") AND state='claimed'", source_ids).fetchall()
        for claimed in claimed_rows:
            if not isinstance(claimed["claim_token"], str) or not claimed["claim_token"]:
                raise ValueError("claimed source has missing claim token")
            try:
                lease = datetime.fromisoformat(str(claimed["lease_expires_at"]).replace("Z", "+00:00"))
            except (TypeError, ValueError) as exc:
                raise ValueError("claimed source has missing or malformed lease") from exc
            if (lease.replace(tzinfo=timezone.utc) if lease.tzinfo is None else lease.astimezone(timezone.utc)) > current:
                raise ValueError("a source has active claimed work")
        rows = conn.execute("SELECT d.id AS delivery_id, d.message_id, d.recipient_runtime, d.recipient_session_ref, d.recipient_endpoint_id, d.recipient_container_ref, d.state, d.claim_token, d.claimed_at, d.lease_expires_at, d.delivered_at, d.attempts, m.sender_runtime, m.sender_session_ref, m.sender_endpoint_id, m.recipient_selector, m.container_ref AS message_container_ref, m.payload, m.redacted, m.in_reply_to, m.created_at AS message_created_at, m.expires_at AS message_expires_at FROM relay_deliveries d JOIN relay_messages m ON m.id=d.message_id WHERE d.recipient_endpoint_id IN (" + placeholders + ") AND d.state IN ('pending','claimed') AND m.expires_at > CURRENT_TIMESTAMP ORDER BY d.id", source_ids).fetchall()
        if any(row["state"] == "pending" and row["claim_token"] is not None for row in rows):
            raise ValueError("pending source has unexpected claim token")
        by_id = {row["delivery_id"]: _delivery_preimage(row) for row in rows}
        if {item["delivery_id"] for item in dispositions} != set(by_id):
            raise ValueError("dispositions must classify every and only live repairable source delivery")
        if any(item["disposition"] == "adopt" and by_id[item["delivery_id"]]["delivery"]["state"] == "claimed" for item in dispositions):
            raise ValueError("expired claimed delivery may only be suppressed")
        manifest = {"schema_version": _SCHEMA_VERSION, "database_identity": _identity(conn, path), "source_endpoint_ids": source_ids, "destination_endpoint_id": destination_id, "expected_scopes": expected_scopes, "endpoint_preimage": endpoints, "dispositions": [{"delivery_id": item["delivery_id"], "disposition": item["disposition"], "preimage": by_id[item["delivery_id"]]} for item in sorted(dispositions, key=lambda item: item["delivery_id"])]}
        manifest["reservation_evidence"] = _wake_evidence(manifest)
        conn.execute("COMMIT")
        return {"manifest": manifest, "sha256": _digest(manifest)}
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"unreadable or malformed wake store: {path}") from exc


def _strings(row: dict[str, object], names: set[str]) -> bool:
    return all(isinstance(row[name], str) and row[name] for name in names)


def _valid_text(value: object, maximum: int) -> bool:
    return isinstance(value, str) and 0 < len(value) <= maximum and value.isprintable()


def _valid_claude_registration(row: object) -> bool:
    required = {
        "runtime", "session_ref", "container_ref", "socket_path", "token",
        "generation", "expires_at", "idle", "state", "delivery_id", "attempted_at",
    }
    if not isinstance(row, dict) or set(row) not in (required, required | {"recipient_endpoint_id"}):
        return False
    if not all(_valid_text(row[name], maximum) for name, maximum in (
        ("runtime", 32), ("session_ref", 512), ("container_ref", 512),
        ("socket_path", 4096), ("token", 8192),
    )):
        return False
    if (
        type(row["generation"]) is not int
        or row["generation"] < 0
        or type(row["expires_at"]) not in (int, float)
        or type(row["idle"]) is not bool
        or row["state"] not in {"idle", "busy", "wake_inflight", "unreachable"}
        or row["idle"] != (row["state"] == "idle")
    ):
        return False
    delivery_id = row["delivery_id"]
    attempted_at = row["attempted_at"]
    endpoint_id = row.get("recipient_endpoint_id")
    if row["state"] != "wake_inflight":
        return delivery_id is None and attempted_at is None and endpoint_id is None
    return (
        _valid_text(delivery_id, 128)
        and type(attempted_at) in (int, float)
        and math.isfinite(attempted_at)
        and (endpoint_id is None or (isinstance(endpoint_id, str) and bool(_ENDPOINT_RE.fullmatch(endpoint_id))))
    )


def _claude_store(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]] | None]:
    if not path.exists():
        return {"status": "missing", "sha256": None, "count": 0, "path": str(path.resolve())}, None
    raw = _load_json(path)
    if not isinstance(raw, dict) or set(raw) != {"version", "registrations"} or raw.get("version") != 1 or not isinstance(raw.get("registrations"), list) or len(raw["registrations"]) > 256:
        raise ValueError("unsupported or invalid Claude capability store")
    keys: set[tuple[str, str, str]] = set()
    inflight_deliveries: set[str] = set()
    inflight_endpoints: set[str] = set()
    for row in raw["registrations"]:
        if not _valid_claude_registration(row):
            raise ValueError("unsupported or invalid Claude capability store")
        key = (row["runtime"], row["session_ref"], row["container_ref"])
        endpoint_id = row.get("recipient_endpoint_id")
        if key in keys or (row["state"] == "wake_inflight" and (row["delivery_id"] in inflight_deliveries or endpoint_id is not None and endpoint_id in inflight_endpoints)):
            raise ValueError("unsupported or invalid Claude capability store")
        keys.add(key)
        if row["state"] == "wake_inflight":
            inflight_deliveries.add(row["delivery_id"])
            if endpoint_id is not None:
                inflight_endpoints.add(endpoint_id)
    return {"status": "valid", "sha256": _digest(raw), "count": len(raw["registrations"]), "path": str(path.resolve())}, raw["registrations"]


def _claude_intents(path: Path) -> tuple[dict[str, Any], set[tuple[str, str, str]]]:
    if not path.exists():
        return {"status": "valid", "sha256": _digest([]), "count": 0, "path": str(path.resolve())}, set()
    if not path.is_dir():
        raise ValueError("Claude intent store is invalid")
    try:
        paths = sorted(path.iterdir(), key=lambda value: value.name)
    except OSError as exc:
        raise ValueError("Claude intent store is unreadable") from exc
    if len(paths) > 256:
        raise ValueError("Claude intent store exceeds its supported bound")
    fingerprints: list[dict[str, str]] = []
    identities: set[tuple[str, str, str]] = set()
    register_keys = {"runtime", "session_ref", "container_ref", "socket_path", "token", "idle", "intent_id"}
    close_keys = {"runtime", "session_ref", "container_ref", "intent_id", "closed"}
    for item in paths:
        if not item.is_file() or item.suffix != ".json":
            raise ValueError("Claude intent store contains an unsupported entry")
        raw = _load_json(item)
        if not isinstance(raw, dict) or set(raw) not in (register_keys, close_keys):
            raise ValueError("Claude intent store contains an invalid intent")
        identity = (raw["runtime"], raw["session_ref"], raw["container_ref"])
        if not all(_valid_text(value, maximum) for value, maximum in zip(identity, (32, 512, 512), strict=True)) or not _valid_text(raw["intent_id"], 128):
            raise ValueError("Claude intent store contains an invalid intent")
        if set(raw) == register_keys and (not _valid_text(raw["socket_path"], 4096) or not _valid_text(raw["token"], 8192) or type(raw["idle"]) is not bool):
            raise ValueError("Claude intent store contains an invalid intent")
        if set(raw) == close_keys and raw["closed"] is not True:
            raise ValueError("Claude intent store contains an invalid intent")
        if item.name != _digest(list(identity)) + ".json" or identity in identities:
            raise ValueError("Claude intent store contains a misplaced or duplicate intent")
        identities.add(identity)
        fingerprints.append({"name": item.name, "sha256": _digest(raw)})
    return {"status": "valid", "sha256": _digest(fingerprints), "count": len(paths), "path": str(path.resolve())}, identities


def _wake_evidence(manifest: dict[str, Any]) -> dict[str, Any]:
    claude_dir = Path(os.environ["PALLIUM_CLAUDE_WAKE_DIR"]).resolve()
    if (claude_dir / "store-unusable").exists() or (claude_dir / "capabilities.unusable").exists():
        raise ValueError("Claude wake store is marked unusable")
    codex_meta, codex_rows = {"status": "missing", "sha256": None, "count": 0, "path": None}, None
    claude_meta, claude_rows = _claude_store(claude_dir / "capabilities.json")
    intent_meta, intents = _claude_intents(claude_dir / "intents")
    deliveries: list[dict[str, str]] = []
    for item in manifest["dispositions"]:
        delivery = item["preimage"]["delivery"]
        runtime = delivery["recipient_runtime"]
        scope = (runtime, delivery["recipient_session_ref"], delivery["recipient_container_ref"])
        if runtime == "codex":
            blocked = codex_rows is not None and any(
                row["delivery_id"] == item["delivery_id"]
                or row["recipient_endpoint_id"] == delivery["recipient_endpoint_id"]
                or (row["session_ref"], row["container_ref"]) == scope[1:]
                for row in codex_rows
            )
            status = "blocked" if blocked else "clean" if codex_rows is not None else "unknown"
        elif runtime == "claude-code":
            blocked = scope in intents or claude_rows is not None and any(
                row["state"] == "wake_inflight" and (
                    row["delivery_id"] == item["delivery_id"]
                    or row.get("recipient_endpoint_id") == delivery["recipient_endpoint_id"]
                    or (row["session_ref"], row["container_ref"]) == scope[1:]
                )
                for row in claude_rows
            )
            status = "blocked" if blocked else "clean" if claude_rows is not None else "unknown"
        else:
            status = "unknown"
        deliveries.append({"delivery_id": item["delivery_id"], "runtime": runtime, "status": status})
    return {
        "stores": {"codex": codex_meta, "claude": claude_meta, "claude_intents": intent_meta},
        "deliveries": sorted(deliveries, key=lambda value: value["delivery_id"]),
    }


def _clean_adoption_ids(manifest: dict[str, Any]) -> set[str]:
    actual = _wake_evidence(manifest)
    if manifest.get("reservation_evidence") != actual:
        raise ValueError("installed wake reservation evidence drifted")
    clean = {row["delivery_id"] for row in actual["deliveries"] if row["status"] == "clean"}
    return {item["delivery_id"] for item in manifest["dispositions"] if item["disposition"] == "adopt" and item["delivery_id"] in clean}


def _installed_urls(home: Path) -> tuple[str, str]:
    data = home.resolve() / "data"
    return f"sqlite:///{data / 'pallium.db'}", f"sqlite:///{data / 'pallium-relay.db'}"


def _validate_repair_database(db_url: str, home: Path) -> None:
    _, expected = _installed_urls(home)
    if _path(db_url) != _path(expected):
        raise ValueError("--db-url must match the installed home Relay database")
    path = _path(db_url)
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(relay_endpoint_repairs)")}
    except sqlite3.Error as exc:
        raise ValueError("installed Relay database is unreadable") from exc
    if columns != {"manifest_digest", "manifest_json", "result_json", "committed_at"}:
        raise ValueError("installed Relay database must be upgraded before repair")


def _repair_storage(db_url: str, home: Path) -> SQLiteStorageProvider:
    _validate_repair_database(db_url, home)
    return SQLiteStorageProvider.open_relay_maintenance(db_url)


@contextmanager
def _maintenance_fence(home: Path, claude_wake_dir: Path):
    from app.cli import service
    home = home.resolve()
    claude_wake_dir = claude_wake_dir.resolve()
    lock = service._PalliumLock(home / "run" / "pallium.lock")
    if not lock.acquire():
        raise ValueError("cannot acquire Pallium maintenance lock")
    keys = ("PALLIUM_SQLITE_URL", "PALLIUM_RELAY_SQLITE_URL", "PALLIUM_CLAUDE_WAKE_DIR")
    previous = {key: os.environ.get(key) for key in keys}
    main_url, relay_url = _installed_urls(home)
    os.environ.update({
        "PALLIUM_SQLITE_URL": main_url,
        "PALLIUM_RELAY_SQLITE_URL": relay_url,
        "PALLIUM_CLAUDE_WAKE_DIR": str(claude_wake_dir),
    })
    try:
        service.assert_service_stopped(home)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        lock.release()


def _manifest_claude_wake_dir(manifest: dict[str, Any]) -> Path:
    try:
        stores = manifest["reservation_evidence"]["stores"]
        claude_path = stores["claude"]["path"]
        intents_path = stores["claude_intents"]["path"]
    except (KeyError, TypeError) as exc:
        raise ValueError("manifest wake-store paths are invalid") from exc
    if not isinstance(claude_path, str) or not isinstance(intents_path, str):
        raise ValueError("manifest wake-store paths are invalid")
    directory = Path(claude_path).resolve().parent
    if Path(intents_path).resolve() != directory / "intents":
        raise ValueError("manifest wake-store paths are inconsistent")
    return directory

def apply_manifest(db_url: str, home: Path, envelope: object, acknowledge_digest: str) -> dict[str, Any]:
    if not isinstance(envelope, dict) or set(envelope) != _ENVELOPE_KEYS or not isinstance(envelope.get("manifest"), dict) or not isinstance(envelope.get("sha256"), str):
        raise ValueError("manifest envelope has invalid keys")
    if envelope["sha256"] != _digest(envelope["manifest"]) or acknowledge_digest != envelope["sha256"]:
        raise ValueError("manifest digest mismatch or not acknowledged")
    manifest = envelope["manifest"]
    with _maintenance_fence(home, _manifest_claude_wake_dir(manifest)):
        storage = _repair_storage(db_url, home)
        try:
            return storage.relay_endpoint_repair_apply(
                manifest,
                reservation_validator=lambda: _clean_adoption_ids(manifest),
            )
        finally:
            storage.close()

def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="relay_endpoint_repair")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    p.add_argument("--db-url", required=True); p.add_argument("--home", type=Path, required=True); p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--source", action="append", default=[]); p.add_argument("--destination"); p.add_argument("--scope", action="append", default=[]); p.add_argument("--dispositions", type=Path); p.add_argument("--acknowledge-digest"); p.add_argument("--claude-wake-dir", type=Path)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.dry_run:
            if not args.destination or not args.dispositions:
                raise ValueError("--destination and --dispositions are required for --dry-run")
            if args.claude_wake_dir is None:
                raise ValueError("--claude-wake-dir is required for --dry-run")
            pairs = [value.split("=", 1) for value in args.scope]
            if any(len(pair) != 2 or not pair[0] or not pair[1] for pair in pairs) or len({pair[0] for pair in pairs}) != len(pairs):
                raise ValueError("--scope must be unique endpoint_id=container_ref pairs")
            claude_wake_dir = args.claude_wake_dir.resolve()
            with _maintenance_fence(args.home, claude_wake_dir):
                _validate_repair_database(args.db_url, args.home)
                envelope = build_manifest(args.db_url, args.source, args.destination, dict(pairs), json.loads(args.dispositions.read_text(encoding="utf-8")))
            args.manifest.write_text(json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
            print(json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(json.dumps(apply_manifest(args.db_url, args.home, json.loads(args.manifest.read_text(encoding="utf-8")), args.acknowledge_digest or ""), sort_keys=True))
    except (OSError, RuntimeError, TypeError, ValueError, sqlite3.Error, SQLAlchemyError, json.JSONDecodeError, RelayConflictError) as exc:
        print(f"refusing: {exc}", file=sys.stderr); return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
