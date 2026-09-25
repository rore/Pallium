"""Caller-surface regression for Claude wake intents crossing Relay instances."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from app.claude_wake_binding import (
    binding_fingerprint, binding_for_relay_database, claim_wake_directory, hook_binding_path, service_marker_path,
    write_json_atomic,
)
from app.cli import setup_claude_code
from app.config import AppConfig
from app.main import create_app
from storage.vector_index import VectorIndexConfig
from tests.config_helpers import DEMO_SEMANTIC_PACKAGES


def _app(tmp_path: Path, name: str):
    config = AppConfig(
        storage_backend="sqlite", sqlite_url=f"sqlite:///{tmp_path / name}",
        default_use_case="demo_agent_memory",
        semantic_packages=DEMO_SEMANTIC_PACKAGES,
        vector_index=VectorIndexConfig(enabled=False),
    )
    return create_app(config), binding_for_relay_database(config.resolved_relay_sqlite_url)


def _hook(monkeypatch: pytest.MonkeyPatch):
    path = Path("integrations/claude-code/hooks/common.py").resolve()
    spec = importlib.util.spec_from_file_location("claude_wake_isolation_hook", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def test_two_instances_real_hook_http_and_outage_recovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PALLIUM_CLAUDE_WAKE_DIR", raising=False)
    monkeypatch.delenv("PALLIUM_PORT", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    app_a, binding_a = _app(tmp_path, "first.db")
    app_b, binding_b = _app(tmp_path, "second.db")
    assert binding_a and binding_b and binding_a["wake_dir"] != binding_b["wake_dir"]
    write_json_atomic(service_marker_path(20101), {"port": 20101, **binding_a})
    write_json_atomic(service_marker_path(20102), {"port": 20102, **binding_b})
    monkeypatch.setattr(setup_claude_code, "_service_binding_id", lambda port: binding_fingerprint(binding_a) if port == 20101 else binding_fingerprint(binding_b))
    assert setup_claude_code._resolve_wake_binding(20101, online=True) == {"port": 20101, **binding_a}
    monkeypatch.setattr(setup_claude_code, "_service_binding_id", lambda *_: binding_fingerprint(binding_b))
    assert setup_claude_code._resolve_wake_binding(20101, online=True) is None
    monkeypatch.setattr(setup_claude_code, "_service_binding_id", lambda port: binding_fingerprint(binding_a) if port == 20101 else binding_fingerprint(binding_b))
    write_json_atomic(hook_binding_path(), {"port": 20101, **binding_a})
    hook = _hook(monkeypatch)
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_SOCKET", r"\\.\pipe\claude")
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_TOKEN", "secret-✓")
    session, container = "session-✓", "git:répo/π"
    a_dir, b_dir = Path(binding_a["wake_dir"]), Path(binding_b["wake_dir"])
    b_before = {p.name: p.read_bytes() for p in b_dir.iterdir() if p.is_file()}

    with TestClient(app_a, client=("127.0.0.1", 50001)) as http_a, TestClient(app_b, client=("127.0.0.1", 50002)):
        seen = []
        def open_a(request, **_kwargs):
            response = http_a.request(request.get_method(), urlsplit(request.full_url).path, content=request.data)
            seen.append((response.status_code, response.text))
            return nullcontext(response)

        monkeypatch.setattr(hook.urllib.request, "build_opener", lambda *_: SimpleNamespace(open=open_a))
        assert hook.register_claude_wake(session, container, idle=True), (hook._WAKE_BINDING, hook._wake_binding_matches_service(), hook.CLAUDE_WAKE_DIR, seen)
        assert seen == [(204, "")]
        assert app_a.state.claude_wake_registry.recovery_candidates()[0]["session_ref"] == session
        assert app_b.state.claude_wake_registry.recovery_candidates() == []
        assert hook.close_claude_wake(session, container)
        assert app_a.state.claude_wake_registry.recovery_candidates() == []
        assert app_b.state.claude_wake_registry.recovery_candidates() == []

        monkeypatch.setattr(hook.urllib.request, "build_opener", lambda *_: SimpleNamespace(open=lambda *_a, **_k: (_ for _ in ()).throw(OSError("offline"))))
        assert not hook.register_claude_wake(session, container, idle=True)
        intent = hook._wake_intent_path("claude-code", session, container)
        assert intent.parent == a_dir / "intents" and intent.exists()
        assert json.loads(intent.read_text(encoding="utf-8"))["token"] == "secret-✓"
        assert {p.name: p.read_bytes() for p in b_dir.iterdir() if p.is_file()} == b_before

    restarted, _ = _app(tmp_path, "first.db")
    with TestClient(restarted, client=("127.0.0.1", 50001)):
        assert restarted.state.claude_wake_registry.recovery_candidates()[0]["session_ref"] == session
        assert not intent.exists()
    assert {p.name: p.read_bytes() for p in b_dir.iterdir() if p.is_file()} == b_before


def test_changed_marker_and_unbound_hook_fail_before_intent_or_http(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PALLIUM_CLAUDE_WAKE_DIR", raising=False)
    monkeypatch.delenv("PALLIUM_PORT", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    _, binding_a = _app(tmp_path, "first.db")
    _, binding_b = _app(tmp_path, "second.db")
    assert binding_a and binding_b
    write_json_atomic(hook_binding_path(), {"port": 20101, **binding_a})
    write_json_atomic(service_marker_path(20101), {"port": 20101, **binding_b})
    hook = _hook(monkeypatch)
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_SOCKET", r"\\.\pipe\claude")
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_TOKEN", "secret")
    monkeypatch.setattr(hook.urllib.request, "build_opener", lambda *_: pytest.fail("mismatched hook must not send HTTP"))
    assert not hook.register_claude_wake("session", "git:example/repo")
    assert not (Path(binding_a["wake_dir"]) / "intents").exists()
    assert not (Path(binding_b["wake_dir"]) / "intents").exists()

    hook_binding_path().unlink()
    unbound = _hook(monkeypatch)
    assert not unbound.register_claude_wake("session", "git:example/repo")
    assert unbound.CLAUDE_WAKE_DIR is None
    monkeypatch.setenv("PALLIUM_CLAUDE_WAKE_DIR", binding_b["wake_dir"])
    unbound_override = _hook(monkeypatch)
    assert not unbound_override.register_claude_wake("session", "git:example/repo")
    assert not (Path(binding_b["wake_dir"]) / "intents").exists()


def test_conflicting_explicit_directory_is_rejected_before_replay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PALLIUM_CLAUDE_WAKE_DIR", str(tmp_path / "shared"))
    _app(tmp_path, "first.db")
    owner = (tmp_path / "shared" / "relay-owner.json").read_bytes()
    with pytest.raises(ValueError, match="another Relay database"):
        _app(tmp_path, "second.db")
    assert (tmp_path / "shared" / "relay-owner.json").read_bytes() == owner






def test_service_startup_marker_and_default_offline_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PALLIUM_CLAUDE_WAKE_DIR", raising=False)
    monkeypatch.delenv("PALLIUM_RELAY_SQLITE_URL", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    installed_url = f"sqlite:///{tmp_path / '.pallium' / 'data' / 'pallium-relay.db'}"
    installed = binding_for_relay_database(installed_url)
    assert installed and installed["wake_dir"] == str(tmp_path / ".pallium" / "claude-wake")
    assert setup_claude_code._resolve_wake_binding(19836, online=False) == {"port": 19836, **installed}
    app, binding = _app(tmp_path, "isolated.db")
    monkeypatch.setenv("PALLIUM_SERVICE_PORT", "20103")
    with TestClient(app) as http:
        assert http.get("/health").json()["claude_wake_relay_id"] == binding["relay_id"]
        assert http.get("/health").json()["claude_wake_binding_id"] == binding_fingerprint(binding)
        marker = json.loads(service_marker_path(20103).read_text(encoding="utf-8"))
        assert marker == {"port": 20103, **binding}
    monkeypatch.setattr(setup_claude_code, "_service_binding_id", lambda *_: binding_fingerprint(binding))
    assert setup_claude_code._resolve_wake_binding(20103, online=True) == marker
    assert setup_claude_code._resolve_wake_binding(20104, online=False) is None


def test_malformed_binding_and_conflicting_port_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PALLIUM_CLAUDE_WAKE_DIR", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    _, binding = _app(tmp_path, "first.db")
    assert binding
    hook_binding_path().parent.mkdir(parents=True)
    hook_binding_path().write_text("{broken", encoding="utf-8")
    malformed = _hook(monkeypatch)
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_SOCKET", r"\\.\pipe\claude")
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_TOKEN", "secret")
    assert not malformed.register_claude_wake("session", "git:example/repo")
    write_json_atomic(hook_binding_path(), {"port": 20101, **binding})
    monkeypatch.setenv("PALLIUM_PORT", "20102")
    conflict = _hook(monkeypatch)
    assert not conflict.register_claude_wake("session", "git:example/repo")
    assert not (Path(binding["wake_dir"]) / "intents").exists()


def test_custom_database_cannot_claim_legacy_installed_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    legacy = tmp_path / ".pallium" / "claude-wake"
    monkeypatch.setenv("PALLIUM_CLAUDE_WAKE_DIR", str(legacy))
    with pytest.raises(ValueError, match="installed Claude wake directory"):
        _app(tmp_path, "custom.db")
    assert not legacy.exists()


def test_setup_pins_custom_port_without_duplicate_hooks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PALLIUM_CLAUDE_WAKE_DIR", raising=False)
    monkeypatch.delenv("PALLIUM_PORT", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    _, binding = _app(tmp_path, "custom.db")
    assert binding
    write_json_atomic(service_marker_path(20105), {"port": 20105, **binding})
    monkeypatch.setattr(setup_claude_code, "_service_binding_id", lambda *_: binding_fingerprint(binding))
    settings = tmp_path / "settings.json"
    monkeypatch.setattr(setup_claude_code, "_claude_settings_path", lambda: settings)
    monkeypatch.setattr(setup_claude_code, "_register_mcp", lambda port: None)
    monkeypatch.setattr(setup_claude_code, "_append_claude_md_block", lambda *_: None)
    monkeypatch.setattr(setup_claude_code, "_install_skill", lambda: None)
    monkeypatch.setattr(setup_claude_code, "_ensure_state_dir", lambda: None)
    monkeypatch.setattr(setup_claude_code, "_verify_service", lambda *_: True)
    assert setup_claude_code.install(20105) == setup_claude_code.install(20105) == 0
    assert json.loads(hook_binding_path().read_text(encoding="utf-8")) == {"port": 20105, **binding}
    commands = [
        hook["command"] for entry in json.loads(settings.read_text(encoding="utf-8"))["hooks"]["SessionEnd"]
        for hook in entry["hooks"] if "session_end.py" in hook["command"]
    ]
    assert len(commands) == 1
    assert _hook(monkeypatch).PALLIUM_PORT == 20105


def test_unowned_custom_legacy_state_cannot_be_claimed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wake_dir = tmp_path / "custom-wake"
    wake_dir.mkdir()
    (wake_dir / "capabilities.json").write_text('{"version":1,"registrations":[]}', encoding="utf-8")
    monkeypatch.setenv("PALLIUM_CLAUDE_WAKE_DIR", str(wake_dir))
    with pytest.raises(ValueError, match="unowned Claude wake directory"):
        _app(tmp_path, "other.db")
    assert not (wake_dir / "relay-owner.json").exists()


def test_installed_default_offline_hook_write_restart_and_close(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PALLIUM_CLAUDE_WAKE_DIR", raising=False)
    monkeypatch.delenv("PALLIUM_PORT", raising=False)
    monkeypatch.delenv("PALLIUM_SERVICE_PORT", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    data = tmp_path / ".pallium" / "data"
    data.mkdir(parents=True)
    relay_url = f"sqlite:///{data / 'pallium-relay.db'}"
    binding = binding_for_relay_database(relay_url)
    assert binding and binding["wake_dir"] == str(tmp_path / ".pallium" / "claude-wake")
    claim_wake_directory(binding)
    write_json_atomic(hook_binding_path(), {"port": 19836, **binding})
    hook = _hook(monkeypatch)
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_SOCKET", r"\\.\pipe\claude")
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_TOKEN", "offline-secret")
    monkeypatch.setattr(hook.urllib.request, "build_opener", lambda *_: SimpleNamespace(open=lambda *_a, **_k: (_ for _ in ()).throw(OSError("offline"))))
    session, container = "installed-session", "git:example/repo"
    assert not hook.register_claude_wake(session, container, idle=True)
    intent = hook._wake_intent_path("claude-code", session, container)
    assert intent.exists()

    config = AppConfig(
        storage_backend="sqlite", sqlite_url=f"sqlite:///{data / 'pallium.db'}",
        relay_sqlite_url=relay_url, default_use_case="demo_agent_memory",
        semantic_packages=DEMO_SEMANTIC_PACKAGES,
        vector_index=VectorIndexConfig(enabled=False),
    )
    with TestClient(create_app(config)) as app:
        assert app.app.state.claude_wake_registry.recovery_candidates()[0]["session_ref"] == session
    assert not intent.exists()
    assert not hook.close_claude_wake(session, container)
    assert json.loads(intent.read_text(encoding="utf-8"))["closed"] is True
    with TestClient(create_app(config)) as app:
        assert app.app.state.claude_wake_registry.recovery_candidates() == []
    assert not intent.exists()


def test_offline_setup_rejects_another_instances_owned_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    wake_dir = tmp_path / "shared"
    monkeypatch.setenv("PALLIUM_CLAUDE_WAKE_DIR", str(wake_dir))
    _app(tmp_path, "first.db")
    owner = (wake_dir / "relay-owner.json").read_bytes()
    other_url = f"sqlite:///{tmp_path / 'second-relay.db'}"
    monkeypatch.setenv("PALLIUM_RELAY_SQLITE_URL", other_url)
    monkeypatch.setattr(setup_claude_code, "_verify_service", lambda *_: False)
    monkeypatch.setattr(setup_claude_code, "_register_mcp", lambda *_: pytest.fail("setup must fail before MCP mutation"))
    assert setup_claude_code.install(20109) == 1
    assert not hook_binding_path().exists()
    assert (wake_dir / "relay-owner.json").read_bytes() == owner


def test_pinned_hook_rejects_conflicting_directory_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PALLIUM_CLAUDE_WAKE_DIR", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    _, first = _app(tmp_path, "first.db")
    _, second = _app(tmp_path, "second.db")
    assert first and second
    write_json_atomic(hook_binding_path(), {"port": 20101, **first})
    monkeypatch.setenv("PALLIUM_CLAUDE_WAKE_DIR", second["wake_dir"])
    hook = _hook(monkeypatch)
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_SOCKET", r"\\.\pipe\claude")
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_TOKEN", "secret")
    monkeypatch.setattr(hook.urllib.request, "build_opener", lambda *_: pytest.fail("conflicting hook must not send HTTP"))
    assert not hook.register_claude_wake("session", "git:example/repo")
    assert not (Path(second["wake_dir"]) / "intents").exists()


def test_service_refuses_start_when_binding_marker_cannot_publish(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PALLIUM_CLAUDE_WAKE_DIR", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    app, binding = _app(tmp_path, "custom.db")
    assert binding
    monkeypatch.setenv("PALLIUM_SERVICE_PORT", "20107")
    launch_token = tmp_path / "launch-token.json"
    launch_token.write_text("active", encoding="utf-8")
    monkeypatch.setattr("app.main._write_launch_token", lambda: launch_token)
    monkeypatch.setattr("app.main.write_json_atomic", lambda *_: (_ for _ in ()).throw(PermissionError("marker denied")))
    with pytest.raises(PermissionError, match="marker denied"):
        with TestClient(app):
            pass
    assert not service_marker_path(20107).exists()
    assert not launch_token.exists()
