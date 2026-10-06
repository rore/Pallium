"""Isolation tests for temporary Codex hook fault wrappers."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from scripts import qualify_codex_relay_faults as harness


ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "integrations" / "codex" / "hooks"
SID = "codex-native-session-123"
MESSAGE = "relay-message-known-before-send"
DELIVERY = "relay-delivery-" + "a" * 32


def load_hook(name: str):
    spec = importlib.util.spec_from_file_location(name, HOOKS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


@pytest.fixture(params=["session_start", "user_prompt_submit"])
def module(request):
    result = load_hook(request.param)
    original_request = result._common.relay_request
    yield result
    # Avoid leaving shared module globals altered if an assertion fails.
    result._common.relay_request = original_request


def setup_manifest(tmp_path: Path, mode: str, **overrides):
    state = tmp_path / "fault-state"
    manifest = tmp_path / "manifest.json"
    evidence = tmp_path / "evidence.jsonl"
    value = {"version": 1, "mode": mode, "session_id": SID,
             "message_id": MESSAGE, "expires_at": time.time() + 60,
             "state_path": str(state)}
    value.update(overrides)
    manifest.write_text(json.dumps(value), encoding="utf-8")
    return manifest, evidence, value


def claimed(message_id=MESSAGE):
    return {"deliveries": [{"message_id": message_id, "delivery_id": DELIVERY,
                            "lease_expires_at": "2026-10-06T12:01:00Z",
                            "claim_token": "secret-never-log"}]}


def install_fake_turn(module, response=None, calls=None):
    calls = calls if calls is not None else []

    def original(runtime, sid, *args, **kwargs):
        calls.append((runtime, sid))
        request = kwargs["request"]
        actual = response if response is not None else claimed()
        return request("POST", "/relay/turn", {"session_ref": sid}, timeout=0.2) if response is None else actual

    module.relay_turn = original
    return calls


def test_claim_response_loss_is_actual_response_scoped_once_and_keeps_private_evidence(module, tmp_path):
    manifest, evidence, value = setup_manifest(tmp_path, "claim-response-loss")
    calls = install_fake_turn(module)
    undo = harness.wrap_hook(module, manifest, evidence)
    try:
        assert module.relay_turn("codex", SID, request=lambda *a, **k: claimed()) is None
        assert module.relay_turn("codex", SID, request=lambda *a, **k: claimed()) == claimed()
    finally:
        undo()
    assert calls == [("codex", SID), ("codex", SID)]
    line = evidence.read_text(encoding="utf-8")
    assert DELIVERY in line and "lease_expires_at" in line
    assert "secret-never-log" not in line and MESSAGE not in line
    marker = json.loads(Path(value["state_path"] + ".used").read_text(encoding="utf-8"))
    assert marker["delivery_id"] == DELIVERY


@pytest.mark.parametrize("wrong", ["wrong-session", "wrong-message", "expired", "malformed", "io-error"])
def test_nonmatching_or_uncertain_control_fails_open(module, tmp_path, wrong):
    manifest, evidence, value = setup_manifest(tmp_path, "claim-response-loss")
    if wrong == "expired":
        value["expires_at"] = time.time() - 1
        manifest.write_text(json.dumps(value), encoding="utf-8")
    elif wrong == "malformed":
        manifest.write_text("{", encoding="utf-8")
    elif wrong == "io-error":
        value["state_path"] = str(tmp_path / "missing" / "once")
        manifest.write_text(json.dumps(value), encoding="utf-8")
    calls = install_fake_turn(module)
    undo = harness.wrap_hook(module, manifest, evidence)
    try:
        sid = "wrong-session" if wrong == "wrong-session" else SID
        msg = "wrong-message" if wrong == "wrong-message" else MESSAGE
        response = claimed(msg)
        actual = module.relay_turn("codex", sid, request=lambda *a, **k: response)
    finally:
        undo()
    assert actual == response
    assert calls == [("codex", sid)]
    assert not evidence.exists()


@pytest.mark.parametrize("mode,should_forward", [("ack-precommit", False), ("ack-response-loss", True)])
def test_ack_faults_bind_real_claim_then_target_only_ack(module, tmp_path, mode, should_forward):
    manifest, evidence, _ = setup_manifest(tmp_path, mode)
    install_fake_turn(module, response=claimed())
    real_requests = []
    module._common.relay_request = lambda method, path, body, **opts: (
        real_requests.append((path, body.get("delivery_id"))) or
        {"delivery_id": DELIVERY, "state": "delivered", "already_delivered": False})
    undo = harness.wrap_hook(module, manifest, evidence)
    try:
        response = module.relay_turn("codex", SID, request=lambda *a, **k: None)
        assert response == claimed()
        assert module.acknowledge_relay([claimed()["deliveries"][0]], container_ref="scope") == []
    finally:
        undo()
    assert bool(real_requests) is should_forward
    event = json.loads(evidence.read_text(encoding="utf-8"))
    assert event["delivery_id"] == DELIVERY
    assert "claim_token" not in evidence.read_text(encoding="utf-8")


def test_ack_for_wrong_session_or_unbound_delivery_is_original(module, tmp_path):
    manifest, evidence, _ = setup_manifest(tmp_path, "ack-precommit")
    install_fake_turn(module, response=claimed())
    observed = []
    module._common.relay_request = lambda *a, **k: observed.append(a[1]) or {
        "delivery_id": DELIVERY, "state": "delivered", "already_delivered": False}
    undo = harness.wrap_hook(module, manifest, evidence)
    try:
        module.relay_turn("codex", "other", request=lambda *a, **k: None)
        actual = module.acknowledge_relay([claimed()["deliveries"][0]], container_ref="scope")
    finally:
        undo()
    assert len(actual) == 1
    assert observed == ["/relay/deliveries/ack"]
    assert not evidence.exists()


def test_existing_reservation_and_session_lock_do_not_deadlock_or_repeat_fault(module, tmp_path):
    manifest, evidence, value = setup_manifest(tmp_path, "claim-response-loss")
    Path(value["state_path"] + ".used").write_text("reserved", encoding="utf-8")
    install_fake_turn(module)
    undo = harness.wrap_hook(module, manifest, evidence)
    try:
        response = module.relay_turn("codex", SID, request=lambda *a, **k: claimed())
    finally:
        undo()
    assert response == claimed()


def test_duplicate_concurrent_claim_responses_consume_exactly_one_fault(module, tmp_path):
    manifest, evidence, _ = setup_manifest(tmp_path, "claim-response-loss")
    install_fake_turn(module)
    undo = harness.wrap_hook(module, manifest, evidence)
    barrier = threading.Barrier(3)
    results = []
    def invoke():
        barrier.wait()
        results.append(module.relay_turn("codex", SID, request=lambda *a, **k: claimed()))
    workers = [threading.Thread(target=invoke) for _ in range(2)]
    try:
        for worker in workers: worker.start()
        barrier.wait()
        for worker in workers: worker.join(timeout=2)
    finally:
        undo()
    assert sum(result is None for result in results) == 1
    assert sum(result == claimed() for result in results) == 1


def test_backed_up_hook_runs_with_original_file_and_preserves_backup_hash(tmp_path):
    source = tmp_path / "original.py"
    expected_file = tmp_path / "installed" / "session_start.py"
    expected_file.parent.mkdir()
    source.write_text(
        "_common = type('Common', (), {'relay_request': lambda *a, **k: None})()\n"
        "relay_turn = lambda *a, **k: None\n"
        "acknowledge_relay = lambda *a, **k: None\n"
        "def main():\n assert __file__ == EXPECTED\n assert __name__ == '__main__'\n"
        .replace("EXPECTED", repr(str(expected_file))), encoding="utf-8")
    manifest, evidence, _ = setup_manifest(tmp_path, "claim-response-loss")
    before = harness.sha256(source)
    harness.run_backed_up_hook(source, manifest, evidence, original_path=expected_file)
    assert harness.sha256(source) == before


def make_install_tree(tmp_path: Path):
    stable = tmp_path / "Pallium-installed"
    root = stable / "integrations" / "codex" / "hooks"
    scripts = stable / "scripts"
    root.mkdir(parents=True)
    scripts.mkdir()
    helper = scripts / "qualify_codex_relay_faults.py"
    helper.write_bytes((ROOT / "scripts" / "qualify_codex_relay_faults.py").read_bytes())
    for name in harness.HOOK_NAMES:
        (root / name).write_text(
            "import sys\n_common = type('Common', (), {'relay_request': lambda *a, **k: None})()\n"
            "def relay_turn(runtime, sid, *, request):\n return request('POST','/relay/turn',{'session_ref':sid},timeout=0.2)\n"
            "acknowledge_relay = lambda *a, **k: None\n"
            "def main():\n data=sys.stdin.buffer.read(); result=relay_turn('codex','other-session',request=lambda *a,**k:{'deliveries':[{'message_id':'relay-message-known-before-send','claim_token':'private'}]}); sys.stdout.buffer.write(data); "
            "sys.stdout.buffer.write(b'claim-visible' if result else b'claim-lost'); "
            "sys.stderr.write('hook-stderr\\n'); raise SystemExit(7)\n"
            "if __name__ == '__main__': main()\n", encoding="utf-8")
    config = tmp_path / "user" / ".codex" / "hooks.json"
    config.parent.mkdir(parents=True)
    config.write_text("{}", encoding="utf-8")
    return stable, root, helper, config


def test_install_creates_two_named_shims_and_restore_hashes(tmp_path):
    _, root, helper, config = make_install_tree(tmp_path)
    originals = {name: harness.sha256(root / name) for name in harness.HOOK_NAMES}
    harness.install_hooks(root, helper, mode="claim-response-loss", session_id=SID,
                          message_id=MESSAGE, expires_in=60, config_path=config)
    assert all(harness.sha256(root / name) != originals[name] for name in harness.HOOK_NAMES)
    assert config.read_text(encoding="utf-8") == "{}"
    harness.restore_hooks(root)
    assert {name: harness.sha256(root / name) for name in harness.HOOK_NAMES} == originals


def test_restore_refuses_any_changed_hook_or_config_without_partial_restore(tmp_path):
    _, root, helper, config = make_install_tree(tmp_path)
    originals = {name: harness.sha256(root / name) for name in harness.HOOK_NAMES}
    harness.install_hooks(root, helper, mode="ack-response-loss", session_id=SID,
                          message_id=MESSAGE, expires_in=60, config_path=config)
    (root / "user_prompt_submit.py").write_text("concurrent work", encoding="utf-8")
    before_other = (root / "session_start.py").read_bytes()
    with pytest.raises(RuntimeError, match="changed"):
        harness.restore_hooks(root)
    assert (root / "session_start.py").read_bytes() == before_other
    assert (root / "user_prompt_submit.py").read_text(encoding="utf-8") == "concurrent work"
    assert originals["session_start.py"] != harness.sha256(root / "session_start.py")


def test_restore_refuses_changed_global_hooks_config(tmp_path):
    _, root, helper, config = make_install_tree(tmp_path)
    harness.install_hooks(root, helper, mode="ack-precommit", session_id=SID,
                          message_id=MESSAGE, expires_in=60, config_path=config)
    config.write_text('{"changed":true}', encoding="utf-8")
    before = {name: (root / name).read_bytes() for name in harness.HOOK_NAMES}
    with pytest.raises(RuntimeError, match="configuration changed"):
        harness.restore_hooks(root)
    assert {name: (root / name).read_bytes() for name in harness.HOOK_NAMES} == before


def test_runner_finally_undoes_wrapper_on_hook_exception(tmp_path, monkeypatch):
    source = tmp_path / "hook.py"
    source.write_text(
        "_common=type('Common',(),{'relay_request':lambda *a,**k:None})()\n"
        "relay_turn=lambda *a,**k:None\nacknowledge_relay=lambda *a,**k:None\n"
        "def main(): raise RuntimeError('hook failure')\n", encoding="utf-8")
    manifest, evidence, _ = setup_manifest(tmp_path, "claim-response-loss")
    called = []
    monkeypatch.setattr(harness, "wrap_hook", lambda *a: lambda: called.append("undo"))
    with pytest.raises(RuntimeError, match="hook failure"):
        harness.run_backed_up_hook(source, manifest, evidence)
    assert called == ["undo"]


@pytest.mark.parametrize("which", ["session_start.py", "user_prompt_submit.py"])
def test_installed_shim_subprocess_passes_through_byte_exact_backup(tmp_path, which):
    _, root, helper, config = make_install_tree(tmp_path)
    harness.install_hooks(root, helper, mode="ack-precommit", session_id=SID,
                          message_id=MESSAGE, expires_in=60, config_path=config)
    backup = root / (which + ".relay-fault-backup")
    expected = b"original stdin\x00bytes\r\n"
    baseline = subprocess.run([sys.executable, str(backup)], input=expected,
                              capture_output=True, timeout=5)
    run = subprocess.run([sys.executable, str(root / which)], input=expected,
                         capture_output=True, timeout=5)
    assert (run.returncode, run.stdout, run.stderr) == (
        baseline.returncode, baseline.stdout, baseline.stderr
    )
    assert backup.is_file()
