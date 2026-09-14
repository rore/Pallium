from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.cli.service import _PalliumLock
from app.tools.relay_endpoint_repair import _clean_adoption_ids, _digest, _maintenance_fence, _repair_storage, _validate_inputs, build_manifest
from core.relay import RelayConflictError, RelayService
from storage.sqlite import SQLiteStorageProvider
from storage import sqlite_relay
from storage.sqlite_schema import RelayDeliveryRecord, RelayEndpointGenerationRecord, RelayEndpointRepairRecord, RelayMessageRecord, RelaySessionRecord, RelaySessionWorkRefRecord

SOURCE_A = "relay-session-" + "a" * 32
SOURCE_B = "relay-session-" + "b" * 32
DESTINATION = "relay-session-" + "d" * 32
DELIVERY_A = "relay-delivery-" + "1" * 32
DELIVERY_B = "relay-delivery-" + "2" * 32
MESSAGE_A = "relay-msg-" + "1" * 32
MESSAGE_B = "relay-msg-" + "2" * 32
MESSAGE_C = "relay-msg-" + "3" * 32
DELIVERY_C = "relay-delivery-" + "3" * 32


def _write_store(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")


def _clean_wake_stores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    codex, claude = tmp_path / "codex-wake", tmp_path / "claude-wake"
    _write_store(codex / "reservations.json", {"version": 1, "reservations": []})
    _write_store(claude / "capabilities.json", {"version": 1, "registrations": []})
    monkeypatch.setenv("PALLIUM_CODEX_WAKE_DIR", str(codex))
    monkeypatch.setenv("PALLIUM_CLAUDE_WAKE_DIR", str(claude))
    return codex, claude


def _seed(storage, now: datetime, *, runtime: str = "codex") -> None:
    with storage._begin_relay_immediate() as db:
        for endpoint_id, scope in ((SOURCE_A, "git:old-a"), (SOURCE_B, "git:old-b"), (DESTINATION, "git:new")):
            db.add(RelaySessionRecord(id=endpoint_id, runtime=runtime, session_ref="same-session", container_ref=scope, state="active", first_seen_at=now, last_seen_at=now))
        for message_id, delivery_id, endpoint_id, scope, payload in (
            (MESSAGE_A, DELIVERY_A, SOURCE_A, "git:old-a", "héllo"),
            (MESSAGE_B, DELIVERY_B, SOURCE_B, "git:old-b", "fallback"),
        ):
            db.add(RelayMessageRecord(id=message_id, sender_runtime="claude-code", sender_session_ref="sender", sender_endpoint_id=None, recipient_selector=endpoint_id, container_ref="git:sender", payload=payload, redacted=False, created_at=now, expires_at=now + timedelta(hours=1)))
            db.add(RelayDeliveryRecord(id=delivery_id, message_id=message_id, recipient_runtime=runtime, recipient_session_ref="same-session", recipient_endpoint_id=endpoint_id, recipient_container_ref=scope, state="pending", attempts=2))


def _manifest(storage, dispositions: list[dict[str, str]]) -> dict:
    scopes = {endpoint_id: storage.relay_session_scope_by_endpoint(endpoint_id)["container_ref"] for endpoint_id in (SOURCE_A, SOURCE_B, DESTINATION)}
    return build_manifest(str(storage._relay_engine.url), [SOURCE_A, SOURCE_B], DESTINATION, scopes, dispositions)["manifest"]


def _apply(storage, manifest: dict, now: datetime):
    return storage.relay_endpoint_repair_apply(manifest, reservation_validator=lambda: _clean_adoption_ids(manifest), now=now)


def test_repair_adopts_suppresses_and_replays_before_revalidation(client, tmp_path, monkeypatch):
    storage = client.app.state.pallium_service._storage
    now = datetime.now(timezone.utc)
    _clean_wake_stores(tmp_path, monkeypatch)
    _seed(storage, now, runtime="claude-code")
    manifest = _manifest(storage, [{"delivery_id": DELIVERY_A, "disposition": "adopt"}, {"delivery_id": DELIVERY_B, "disposition": "suppress"}])
    result = _apply(storage, manifest, now)
    assert result["adopted_delivery_ids"] == [DELIVERY_A]
    assert result["suppressed_delivery_ids"] == [DELIVERY_B]
    assert result["residual_split"] == {"alias_sends": "destination", "exact_source_sends_and_replies": "source", "occupied_scopes": "unchanged"}
    assert storage.relay_endpoint_repair_apply(manifest, reservation_validator=lambda: (_ for _ in ()).throw(AssertionError("must not revalidate")), now=now) == result
    with storage._relay_session_factory() as db:
        adopted, suppressed = db.get(RelayDeliveryRecord, DELIVERY_A), db.get(RelayDeliveryRecord, DELIVERY_B)
        assert (adopted.recipient_endpoint_id, adopted.recipient_container_ref, adopted.attempts) == (DESTINATION, "git:old-a", 2)
        assert suppressed.state == "suppressed"
        assert db.scalar(select(RelayEndpointRepairRecord.manifest_digest)) == result["manifest_digest"]
    conflicting = json.loads(json.dumps(manifest))
    conflicting["dispositions"][0]["disposition"] = "suppress"
    with pytest.raises(RelayConflictError, match="already dispositioned"):
        storage.relay_endpoint_repair_apply(conflicting, reservation_validator=lambda: set(), now=now)
    with storage._begin_relay_immediate() as db:
        db.add(RelayMessageRecord(id=MESSAGE_C, sender_runtime="codex", sender_session_ref="sender", sender_endpoint_id=None, recipient_selector=SOURCE_A, container_ref="git:sender", payload="later", redacted=False, created_at=now, expires_at=now + timedelta(hours=1)))
        db.add(RelayDeliveryRecord(id=DELIVERY_C, message_id=MESSAGE_C, recipient_runtime="claude-code", recipient_session_ref="same-session", recipient_endpoint_id=SOURCE_A, recipient_container_ref="git:old-a", state="pending", attempts=0))
    later = _manifest(storage, [{"delivery_id": DELIVERY_C, "disposition": "suppress"}])
    assert _apply(storage, later, now)["suppressed_delivery_ids"] == [DELIVERY_C]


def test_suppressed_is_terminal_across_http_dashboard_and_wake(client, tmp_path, monkeypatch):
    storage = client.app.state.pallium_service._storage
    now = datetime.now(timezone.utc)
    _clean_wake_stores(tmp_path, monkeypatch)
    _seed(storage, now)
    manifest = _manifest(storage, [{"delivery_id": DELIVERY_A, "disposition": "suppress"}, {"delivery_id": DELIVERY_B, "disposition": "suppress"}])
    _apply(storage, manifest, now)

    status = client.get(f"/relay/messages/{MESSAGE_A}", params={"container_ref": "git:sender"})
    assert status.status_code == 200 and status.json()["deliveries"][0]["state"] == "suppressed"
    turn = client.post("/relay/turn", json={"runtime": "codex", "session_ref": "same-session", "container_ref": "git:old-a"})
    assert turn.status_code == 200 and turn.json()["deliveries"] == []
    ack = client.post("/relay/deliveries/ack", json={"delivery_id": DELIVERY_A, "claim_token": "not-claimed", "container_ref": "git:old-a"})
    reply = client.post("/relay/replies", json={"delivery_id": DELIVERY_A, "payload": "must fail", "container_ref": "git:old-a"})
    assert ack.status_code == 409 and reply.status_code == 409
    relay = RelayService(storage)
    assert relay.pending_candidate(runtime="codex", session_ref="same-session", container_ref="git:old-a", delivery_id=DELIVERY_A)["state"] == "suppressed"
    assert relay.wake_candidates(delivery_id=DELIVERY_A) == []

    with storage._begin_relay_immediate() as db:
        db.get(RelayMessageRecord, MESSAGE_A).expires_at = now - timedelta(seconds=1)
        db.get(RelayMessageRecord, MESSAGE_B).expires_at = now - timedelta(seconds=1)
    suppressed = client.get("/dashboard/api/relay/messages", params={"delivery_state": "suppressed"}).json()
    expired = client.get("/dashboard/api/relay/messages", params={"delivery_state": "expired"}).json()
    assert suppressed["total"] == 2 and all(item["deliveries"][0]["state"] == "suppressed" for item in suppressed["messages"])
    assert expired["total"] == 0
    assert client.get("/dashboard/api/relay/summary").json()["deliveries"]["expired_last_24h"] == 0

def test_codex_history_remains_unknown_and_blocks_adoption(client, tmp_path, monkeypatch):
    storage = client.app.state.pallium_service._storage
    now = datetime.now(timezone.utc)
    _clean_wake_stores(tmp_path, monkeypatch)
    _seed(storage, now)
    adopt = _manifest(storage, [{"delivery_id": DELIVERY_A, "disposition": "adopt"}, {"delivery_id": DELIVERY_B, "disposition": "suppress"}])
    assert {row["status"] for row in adopt["reservation_evidence"]["deliveries"]} == {"unknown"}
    with pytest.raises(RelayConflictError, match="clean authoritative"):
        _apply(storage, adopt, now)
    suppress = _manifest(storage, [{"delivery_id": DELIVERY_A, "disposition": "suppress"}, {"delivery_id": DELIVERY_B, "disposition": "suppress"}])
    result = _apply(storage, suppress, now)
    assert result["adopted_delivery_ids"] == []
    assert set(result["suppressed_delivery_ids"]) == {DELIVERY_A, DELIVERY_B}

def test_wake_store_drift_and_active_reservation_fail_before_mutation(client, tmp_path, monkeypatch):
    storage = client.app.state.pallium_service._storage
    now = datetime.now(timezone.utc)
    _, claude = _clean_wake_stores(tmp_path, monkeypatch)
    _seed(storage, now, runtime="claude-code")
    manifest = _manifest(storage, [{"delivery_id": DELIVERY_A, "disposition": "adopt"}, {"delivery_id": DELIVERY_B, "disposition": "suppress"}])
    inflight = {"runtime": "claude-code", "session_ref": "same-session", "container_ref": "git:old-a", "socket_path": "pipe", "token": "secret", "generation": 1, "expires_at": 1.5, "idle": False, "state": "wake_inflight", "delivery_id": DELIVERY_A, "attempted_at": 2.0, "recipient_endpoint_id": SOURCE_A}
    _write_store(claude / "capabilities.json", {"version": 1, "registrations": [inflight]})
    with pytest.raises(ValueError, match="evidence drifted"):
        _apply(storage, manifest, now)
    with storage._relay_session_factory() as db:
        assert db.get(RelayDeliveryRecord, DELIVERY_A).recipient_endpoint_id == SOURCE_A
        assert db.scalar(select(RelayEndpointRepairRecord.manifest_digest)) is None
    blocked = _manifest(storage, [{"delivery_id": DELIVERY_A, "disposition": "adopt"}, {"delivery_id": DELIVERY_B, "disposition": "suppress"}])
    assert blocked["reservation_evidence"]["deliveries"][0]["status"] == "blocked"
    with pytest.raises(RelayConflictError, match="clean authoritative"):
        _apply(storage, blocked, now)

def test_suppression_preserves_blocking_claude_reservation(client, tmp_path, monkeypatch):
    storage = client.app.state.pallium_service._storage
    now = datetime.now(timezone.utc)
    _, claude = _clean_wake_stores(tmp_path, monkeypatch)
    _seed(storage, now, runtime="claude-code")
    inflight = {"runtime": "claude-code", "session_ref": "same-session", "container_ref": "git:old-a", "socket_path": "pipe", "token": "secret", "generation": 1, "expires_at": 1.5, "idle": False, "state": "wake_inflight", "delivery_id": DELIVERY_A, "attempted_at": 2.0, "recipient_endpoint_id": SOURCE_A}
    _write_store(claude / "capabilities.json", {"version": 1, "registrations": [inflight]})
    before = (claude / "capabilities.json").read_bytes()
    manifest = _manifest(storage, [{"delivery_id": DELIVERY_A, "disposition": "suppress"}, {"delivery_id": DELIVERY_B, "disposition": "suppress"}])

    assert set(_apply(storage, manifest, now)["suppressed_delivery_ids"]) == {DELIVERY_A, DELIVERY_B}
    assert (claude / "capabilities.json").read_bytes() == before

def test_claude_v1_numeric_fields_optional_endpoint_and_inflight_are_supported(client, tmp_path, monkeypatch):
    storage = client.app.state.pallium_service._storage
    now = datetime.now(timezone.utc)
    _, claude = _clean_wake_stores(tmp_path, monkeypatch)
    _seed(storage, now, runtime="claude-code")
    idle = {"runtime": "claude-code", "session_ref": "same-session", "container_ref": "git:old-a", "socket_path": "pipe", "token": "secret", "generation": 1, "expires_at": 1.5, "idle": True, "state": "idle", "delivery_id": None, "attempted_at": None, "recipient_endpoint_id": None}
    _write_store(claude / "capabilities.json", {"version": 1, "registrations": [idle]})
    clean = _manifest(storage, [{"delivery_id": DELIVERY_A, "disposition": "adopt"}, {"delivery_id": DELIVERY_B, "disposition": "suppress"}])
    assert clean["reservation_evidence"]["deliveries"][0]["status"] == "clean"
    inflight = {**idle, "idle": False, "state": "wake_inflight", "delivery_id": DELIVERY_A, "attempted_at": 2.0, "recipient_endpoint_id": SOURCE_A}
    _write_store(claude / "capabilities.json", {"version": 1, "registrations": [inflight]})
    blocked = _manifest(storage, [{"delivery_id": DELIVERY_A, "disposition": "adopt"}, {"delivery_id": DELIVERY_B, "disposition": "suppress"}])
    assert blocked["reservation_evidence"]["deliveries"][0]["status"] == "blocked"


def test_partial_claimed_and_preimage_drift_are_rejected(client, tmp_path, monkeypatch):
    storage = client.app.state.pallium_service._storage
    now = datetime.now(timezone.utc)
    _clean_wake_stores(tmp_path, monkeypatch)
    _seed(storage, now)
    with pytest.raises(ValueError, match="every and only"):
        _manifest(storage, [{"delivery_id": DELIVERY_A, "disposition": "suppress"}])
    with storage._begin_relay_immediate() as db:
        db.add(RelaySessionWorkRefRecord(endpoint_id=SOURCE_A, work_ref="work:v1:test", origin="explicit", scope_ref="git:old-a", local_ref="feature", position=None, created_at=now, updated_at=now))
    with pytest.raises(ValueError, match="work-ref"):
        _manifest(storage, [{"delivery_id": DELIVERY_A, "disposition": "suppress"}, {"delivery_id": DELIVERY_B, "disposition": "suppress"}])
    with storage._begin_relay_immediate() as db:
        db.delete(db.get(RelaySessionWorkRefRecord, {"endpoint_id": SOURCE_A, "work_ref": "work:v1:test", "origin": "explicit"}))
        extra = "relay-session-" + "e" * 32
        db.add(RelaySessionRecord(id=extra, runtime="codex", session_ref="same-session", container_ref="git:extra", state="active", first_seen_at=now, last_seen_at=now))
    with pytest.raises(ValueError, match="endpoint set is incomplete"):
        _manifest(storage, [{"delivery_id": DELIVERY_A, "disposition": "suppress"}, {"delivery_id": DELIVERY_B, "disposition": "suppress"}])
    with storage._begin_relay_immediate() as db:
        db.delete(db.get(RelaySessionRecord, "relay-session-" + "e" * 32))
    manifest = _manifest(storage, [{"delivery_id": DELIVERY_A, "disposition": "suppress"}, {"delivery_id": DELIVERY_B, "disposition": "suppress"}])
    manifest["dispositions"][0]["preimage"]["delivery"]["attempts"] = 99
    with pytest.raises(RelayConflictError, match="preimage drifted"):
        _apply(storage, manifest, now)
    with storage._begin_relay_immediate() as db:
        row = db.get(RelayDeliveryRecord, DELIVERY_A)
        row.state, row.claim_token, row.claimed_at, row.lease_expires_at = "claimed", "token", now, now + timedelta(minutes=1)
    with pytest.raises(ValueError, match="claimed work"):
        _manifest(storage, [{"delivery_id": DELIVERY_B, "disposition": "suppress"}])


def test_expiry_during_reservation_validation_rolls_back(client, tmp_path, monkeypatch):
    storage = client.app.state.pallium_service._storage
    now = datetime.now(timezone.utc)
    _clean_wake_stores(tmp_path, monkeypatch)
    _seed(storage, now)
    with storage._begin_relay_immediate() as db:
        expiry = now + timedelta(hours=1)
        db.get(RelayMessageRecord, MESSAGE_A).expires_at = expiry
        db.get(RelayMessageRecord, MESSAGE_B).expires_at = expiry
    manifest = _manifest(storage, [{"delivery_id": DELIVERY_A, "disposition": "suppress"}, {"delivery_id": DELIVERY_B, "disposition": "suppress"}])
    clock = [now]
    real_now = sqlite_relay._now
    monkeypatch.setattr(sqlite_relay, "_now", lambda value=None: clock[0] if value is None else real_now(value))

    def expire_then_validate():
        clock[0] = expiry + timedelta(seconds=1)
        return set()

    with pytest.raises(RelayConflictError, match="complete live source inventory"):
        storage.relay_endpoint_repair_apply(manifest, reservation_validator=expire_then_validate)
    with storage._relay_session_factory() as db:
        assert db.get(RelayDeliveryRecord, DELIVERY_A).state == "pending"
        assert db.get(RelayEndpointRepairRecord, _digest(manifest)) is None

def test_manifest_and_store_boundaries_fail_closed(client, tmp_path, monkeypatch):
    storage = client.app.state.pallium_service._storage
    now = datetime.now(timezone.utc)
    _, claude = _clean_wake_stores(tmp_path, monkeypatch)
    _seed(storage, now)
    scopes = {SOURCE_A: "git:old-a", SOURCE_B: "git:old-b", DESTINATION: "git:new"}
    for sources in ([], ["relay-session-" + f"{index:032x}" for index in range(33)]):
        with pytest.raises(ValueError, match="1..32"):
            _validate_inputs(sources, DESTINATION, {**scopes, **{item: "scope" for item in sources}}, [{"delivery_id": DELIVERY_A, "disposition": "suppress"}])
    for dispositions in ([], [{"delivery_id": f"relay-delivery-{index:032x}", "disposition": "suppress"} for index in range(513)]):
        with pytest.raises(ValueError, match="1..512"):
            _validate_inputs([SOURCE_A, SOURCE_B], DESTINATION, scopes, dispositions)
    with storage._begin_relay_immediate() as db:
        db.add(RelayEndpointGenerationRecord(endpoint_id=SOURCE_A, generation=-1))
    with pytest.raises(ValueError, match="generation"):
        _manifest(storage, [{"delivery_id": DELIVERY_A, "disposition": "suppress"}, {"delivery_id": DELIVERY_B, "disposition": "suppress"}])
    with storage._begin_relay_immediate() as db:
        db.delete(db.get(RelayEndpointGenerationRecord, SOURCE_A))
        db.get(RelaySessionRecord, DESTINATION).alias = "orphan"
    with pytest.raises(ValueError, match="alias ownership"):
        _manifest(storage, [{"delivery_id": DELIVERY_A, "disposition": "suppress"}, {"delivery_id": DELIVERY_B, "disposition": "suppress"}])
    with storage._begin_relay_immediate() as db:
        db.get(RelaySessionRecord, DESTINATION).alias = None
    (claude / "capabilities.json").write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="malformed wake store"):
        _manifest(storage, [{"delivery_id": DELIVERY_A, "disposition": "suppress"}, {"delivery_id": DELIVERY_B, "disposition": "suppress"}])


@pytest.mark.parametrize("corrupt_result", ["{", json.dumps({"manifest_digest": "0" * 64})])
def test_corrupt_committed_ledger_fails_closed(client, tmp_path, monkeypatch, corrupt_result):
    storage = client.app.state.pallium_service._storage
    now = datetime.now(timezone.utc)
    _clean_wake_stores(tmp_path, monkeypatch)
    _seed(storage, now)
    manifest = _manifest(storage, [{"delivery_id": DELIVERY_A, "disposition": "suppress"}, {"delivery_id": DELIVERY_B, "disposition": "suppress"}])
    result = _apply(storage, manifest, now)
    with storage._begin_relay_immediate() as db:
        db.get(RelayEndpointRepairRecord, result["manifest_digest"]).result_json = corrupt_result
    with pytest.raises(RelayConflictError, match="ledger is corrupt"):
        storage.relay_endpoint_repair_apply(manifest, reservation_validator=lambda: set(), now=now)


def test_maintenance_fence_binds_and_restores_installed_paths(tmp_path, monkeypatch):
    home = tmp_path / "installed"
    (home / "run").mkdir(parents=True)
    checked = []
    monkeypatch.setattr("app.cli.service.assert_service_stopped", lambda value: checked.append(value))
    monkeypatch.setenv("PALLIUM_SQLITE_URL", "sqlite:///stale-main.db")
    monkeypatch.setenv("PALLIUM_RELAY_SQLITE_URL", "sqlite:///stale-relay.db")
    monkeypatch.setenv("PALLIUM_CLAUDE_WAKE_DIR", str(tmp_path / "stale-wake"))

    with _maintenance_fence(home, home / "claude-wake"):
        assert os.environ["PALLIUM_SQLITE_URL"] == f"sqlite:///{home.resolve() / 'data' / 'pallium.db'}"
        assert os.environ["PALLIUM_RELAY_SQLITE_URL"] == f"sqlite:///{home.resolve() / 'data' / 'pallium-relay.db'}"
        assert os.environ["PALLIUM_CLAUDE_WAKE_DIR"] == str(home.resolve() / "claude-wake")
    assert checked == [home.resolve()]
    assert os.environ["PALLIUM_RELAY_SQLITE_URL"] == "sqlite:///stale-relay.db"


def test_existing_schema_open_does_not_migrate_refused_database(tmp_path):
    home = tmp_path / "installed"
    data = home / "data"
    data.mkdir(parents=True)
    main_url = f"sqlite:///{data / 'pallium.db'}"
    relay_url = f"sqlite:///{data / 'pallium-relay.db'}"
    SQLiteStorageProvider(main_url, relay_database_url=relay_url).close()
    relay_path = data / "pallium-relay.db"
    with sqlite3.connect(relay_path) as conn:
        conn.execute("DROP TABLE relay_endpoint_repairs")
        before = conn.execute("PRAGMA schema_version").fetchone()[0]
    with pytest.raises(ValueError, match="must be upgraded"):
        _repair_storage(relay_url, home)
    with sqlite3.connect(relay_path) as conn:
        assert conn.execute("PRAGMA schema_version").fetchone()[0] == before
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='relay_endpoint_repairs'").fetchone() is None

def test_subprocess_cli_source_and_disposition_boundaries(tmp_path):
    now = datetime.now(timezone.utc)
    home = tmp_path / "home"
    data = home / "data"
    data.mkdir(parents=True)
    (home / "run").mkdir()
    (home / "claude-wake" / "intents").mkdir(parents=True)
    _write_store(home / "claude-wake" / "capabilities.json", {"version": 1, "registrations": []})
    main_url = f"sqlite:///{data / 'pallium.db'}"
    relay_url = f"sqlite:///{data / 'pallium-relay.db'}"
    storage = SQLiteStorageProvider(main_url, relay_database_url=relay_url)
    sources = [f"relay-session-{index:032x}" for index in range(1, 33)]
    destination = "relay-session-" + "f" * 32
    dispositions = []
    with storage._begin_relay_immediate() as db:
        for endpoint_id in [*sources, destination]:
            db.add(RelaySessionRecord(id=endpoint_id, runtime="codex", session_ref="boundary-session", container_ref=f"scope:{endpoint_id}", state="active", first_seen_at=now, last_seen_at=now))
        for index in range(1, 513):
            source = sources[(index - 1) % len(sources)]
            message_id = f"relay-msg-{index:032x}"
            delivery_id = f"relay-delivery-{index:032x}"
            db.add(RelayMessageRecord(id=message_id, sender_runtime="claude-code", sender_session_ref="sender", sender_endpoint_id=None, recipient_selector=source, container_ref="scope:sender", payload="גבול" if index == 512 else "boundary", redacted=False, created_at=now, expires_at=now + timedelta(hours=1)))
            db.add(RelayDeliveryRecord(id=delivery_id, message_id=message_id, recipient_runtime="codex", recipient_session_ref="boundary-session", recipient_endpoint_id=source, recipient_container_ref=f"scope:{source}", state="pending", attempts=0))
            dispositions.append({"delivery_id": delivery_id, "disposition": "suppress"})
    disposition_path = tmp_path / "512.json"
    disposition_path.write_text(json.dumps(dispositions), encoding="utf-8")
    bootstrap = "from app.cli import service;service.assert_service_stopped=lambda home:None;from app.tools.relay_endpoint_repair import main;raise SystemExit(main())"
    base = [sys.executable, "-c", bootstrap, "--dry-run", "--db-url", relay_url, "--home", str(home), "--manifest", str(tmp_path / "manifest.json"), "--claude-wake-dir", str(home / "claude-wake"), "--destination", destination, "--dispositions", str(disposition_path)]
    scopes = sum((["--source", source, "--scope", f"{source}=scope:{source}"] for source in sources), []) + ["--scope", f"{destination}=scope:{destination}"]
    maximum = subprocess.run([*base, *scopes], cwd=Path(__file__).parents[1], text=True, capture_output=True)
    assert maximum.returncode == 0, maximum.stderr
    assert len(json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))["manifest"]["dispositions"]) == 512

    empty_path = tmp_path / "empty.json"
    empty_path.write_text("[]", encoding="utf-8")
    zero = subprocess.run([*base[:-1], str(empty_path), "--scope", f"{destination}=scope:{destination}"], cwd=Path(__file__).parents[1], text=True, capture_output=True)
    assert zero.returncode == 2 and "1..32" in zero.stderr
    extra_source = "relay-session-" + "0" * 32
    too_many_sources = subprocess.run([*base, *scopes, "--source", extra_source, "--scope", f"{extra_source}=scope:{extra_source}"], cwd=Path(__file__).parents[1], text=True, capture_output=True)
    assert too_many_sources.returncode == 2 and "1..32" in too_many_sources.stderr
    too_many_path = tmp_path / "513.json"
    too_many_path.write_text(json.dumps([*dispositions, {"delivery_id": "relay-delivery-" + "f" * 32, "disposition": "suppress"}]), encoding="utf-8")
    too_many_dispositions = subprocess.run([*base[:-1], str(too_many_path), *scopes], cwd=Path(__file__).parents[1], text=True, capture_output=True)
    assert too_many_dispositions.returncode == 2 and "1..512" in too_many_dispositions.stderr
    storage.close()

def test_subprocess_cli_dry_run_acknowledgement_and_apply(client, tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    home = tmp_path / "home"
    data = home / "data"
    data.mkdir(parents=True)
    main_url = f"sqlite:///{data / 'pallium.db'}"
    relay_url = f"sqlite:///{data / 'pallium-relay.db'}"
    storage = SQLiteStorageProvider(main_url, relay_database_url=relay_url)
    _seed(storage, now)
    (home / "run").mkdir()
    (home / "claude-wake" / "intents").mkdir(parents=True)
    _write_store(home / "claude-wake" / "capabilities.json", {"version": 1, "registrations": []})
    dispositions, manifest_path = tmp_path / "dispositions.json", tmp_path / "manifest.json"
    dispositions.write_text(json.dumps([{"delivery_id": DELIVERY_A, "disposition": "suppress"}, {"delivery_id": DELIVERY_B, "disposition": "suppress"}]), encoding="utf-8")
    bootstrap = "from app.cli import service;service.assert_service_stopped=lambda home:None;from app.tools.relay_endpoint_repair import main;raise SystemExit(main())"
    base, env, cwd = [sys.executable, "-c", bootstrap], os.environ.copy(), Path(__file__).parents[1]
    common = ["--db-url", relay_url, "--home", str(home), "--manifest", str(manifest_path)]
    wake_arg = ["--claude-wake-dir", str(home / "claude-wake")]
    missing_wake = subprocess.run(base + ["--dry-run", *common, "--destination", DESTINATION, "--dispositions", str(dispositions)], cwd=cwd, env=env, text=True, capture_output=True)
    assert missing_wake.returncode == 2 and "--claude-wake-dir is required" in missing_wake.stderr
    dry = subprocess.run(base + ["--dry-run", *common, *wake_arg, "--source", SOURCE_A, "--source", SOURCE_B, "--destination", DESTINATION, "--scope", f"{SOURCE_A}=git:old-a", "--scope", f"{SOURCE_B}=git:old-b", "--scope", f"{DESTINATION}=git:new", "--dispositions", str(dispositions)], cwd=cwd, env=env, text=True, capture_output=True)
    assert dry.returncode == 0, dry.stderr
    envelope = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert envelope["sha256"] == _digest(envelope["manifest"])
    assert envelope["manifest"]["reservation_evidence"]["stores"]["claude"]["path"] == str((home / "claude-wake" / "capabilities.json").resolve())
    held = _PalliumLock(home / "run" / "pallium.lock")
    assert held.acquire()
    locked = subprocess.run(base + ["--dry-run", *common, *wake_arg, "--source", SOURCE_A, "--source", SOURCE_B, "--destination", DESTINATION, "--scope", f"{SOURCE_A}=git:old-a", "--scope", f"{SOURCE_B}=git:old-b", "--scope", f"{DESTINATION}=git:new", "--dispositions", str(dispositions)], cwd=cwd, env=env, text=True, capture_output=True)
    held.release()
    assert locked.returncode == 2 and "maintenance lock" in locked.stderr
    refused = subprocess.run(base + ["--apply", *common, "--acknowledge-digest", "wrong"], cwd=cwd, env=env, text=True, capture_output=True)
    assert refused.returncode == 2 and "Traceback" not in refused.stderr
    stopped_bootstrap = "from app.cli import service;service.assert_service_stopped=lambda home:(_ for _ in ()).throw(RuntimeError('still running'));from app.tools.relay_endpoint_repair import main;raise SystemExit(main())"
    stopped = subprocess.run([sys.executable, "-c", stopped_bootstrap, "--dry-run", *common, *wake_arg, "--source", SOURCE_A, "--source", SOURCE_B, "--destination", DESTINATION, "--scope", f"{SOURCE_A}=git:old-a", "--scope", f"{SOURCE_B}=git:old-b", "--scope", f"{DESTINATION}=git:new", "--dispositions", str(dispositions)], cwd=cwd, env=env, text=True, capture_output=True)
    assert stopped.returncode == 2 and "still running" in stopped.stderr and "Traceback" not in stopped.stderr
    applied = subprocess.run(base + ["--apply", *common, "--acknowledge-digest", envelope["sha256"]], cwd=cwd, env=env, text=True, capture_output=True)
    assert applied.returncode == 0, applied.stderr
    replayed = subprocess.run(base + ["--apply", *common, "--acknowledge-digest", envelope["sha256"]], cwd=cwd, env=env, text=True, capture_output=True)
    assert replayed.returncode == 0 and json.loads(replayed.stdout) == json.loads(applied.stdout)
    with storage._relay_session_factory() as db:
        assert db.get(RelayDeliveryRecord, DELIVERY_A).state == "suppressed"
        assert db.get(RelayDeliveryRecord, DELIVERY_B).state == "suppressed"
    storage.close()

    bad_home = tmp_path / "bad-home"
    (bad_home / "data").mkdir(parents=True)
    (bad_home / "run").mkdir()
    bad_db = bad_home / "data" / "pallium-relay.db"
    bad_db.write_text("not sqlite", encoding="utf-8")
    bad = subprocess.run(base + ["--dry-run", "--db-url", f"sqlite:///{bad_db}", "--home", str(bad_home), "--manifest", str(tmp_path / "bad.json"), "--source", SOURCE_A, "--destination", DESTINATION, "--scope", f"{SOURCE_A}=a", "--scope", f"{DESTINATION}=d", "--dispositions", str(dispositions)], cwd=cwd, env=env, text=True, capture_output=True)
    assert bad.returncode == 2 and "refusing:" in bad.stderr and "Traceback" not in bad.stderr
