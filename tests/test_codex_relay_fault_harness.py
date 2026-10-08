"""Isolation tests for temporary Codex hook fault wrappers."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

import pytest

from scripts import qualify_codex_relay_faults as harness
from tests.test_codex_retained_wake import SCOPE as WAKE_SCOPE, TARGET as WAKE_TARGET
from tests.test_codex_retained_wake import _hook_runner, http_wake, retained


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


@pytest.fixture
def observation_reader(monkeypatch):
    """Wait for the real asynchronous observer append before reading its ledger."""
    original = harness._append_observation
    done = threading.Event()
    pause = threading.Event()
    opened = threading.Event()
    release = threading.Event()

    def append(path, snapshot):
        try:
            if pause.is_set():
                with path.open("ab"):
                    opened.set()
                    if not release.wait(3):
                        raise TimeoutError("test writer was not released")
            return original(path, snapshot)
        finally:
            done.set()

    monkeypatch.setattr(harness, "_append_observation", append)

    def wait(path):
        assert done.wait(2), "observer append did not complete"
        return path.read_text(encoding="utf-8")

    return {"wait": wait, "pause": pause, "opened": opened, "release": release}


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


@pytest.mark.parametrize("response", [
    None, {}, {"error": "unavailable"},
    {"delivery_id": "other", "state": "delivered", "already_delivered": False},
    {"delivery_id": DELIVERY, "state": "claimed", "already_delivered": False},
    {"delivery_id": DELIVERY, "state": "delivered", "already_delivered": 0},
])
def test_failed_ack_never_counts_as_injected_postcommit_response_loss(module, tmp_path, response):
    manifest, evidence, _ = setup_manifest(tmp_path, "ack-response-loss")
    install_fake_turn(module, response=claimed())
    forwarded = []
    module._common.relay_request = lambda *args, **kwargs: forwarded.append(args) or response
    undo = harness.wrap_hook(module, manifest, evidence)
    try:
        module.relay_turn("codex", SID, request=lambda *args, **kwargs: None)
        assert module.acknowledge_relay(claimed()["deliveries"], container_ref="scope") == []
    finally:
        undo()
    assert len(forwarded) == 1
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
    control = tmp_path / "operator-private"
    control.mkdir()
    return stable, root, helper, config, control


def test_install_creates_two_named_shims_and_restore_hashes(tmp_path):
    _, root, helper, config, control = make_install_tree(tmp_path)
    originals = {name: harness.sha256(root / name) for name in harness.HOOK_NAMES}
    harness.install_hooks(root, control, helper, mode="claim-response-loss", session_id=SID,
                          message_id=MESSAGE, expires_in=60, config_path=config)
    assert all(harness.sha256(root / name) != originals[name] for name in harness.HOOK_NAMES)
    assert (control / harness.INSTALL_RECORD).is_file()
    assert (control / harness.FAULT_MANIFEST).is_file()
    assert all((control / (name + ".relay-fault-backup")).is_file() for name in harness.HOOK_NAMES)
    assert not (root / harness.INSTALL_RECORD).exists()
    assert not (root / harness.FAULT_MANIFEST).exists()
    assert not any((root / (name + ".relay-fault-backup")).exists() for name in harness.HOOK_NAMES)
    assert config.read_text(encoding="utf-8") == "{}"
    harness.restore_hooks(root, control)
    assert {name: harness.sha256(root / name) for name in harness.HOOK_NAMES} == originals


def test_restore_refuses_any_changed_hook_or_config_without_partial_restore(tmp_path):
    _, root, helper, config, control = make_install_tree(tmp_path)
    originals = {name: harness.sha256(root / name) for name in harness.HOOK_NAMES}
    harness.install_hooks(root, control, helper, mode="ack-response-loss", session_id=SID,
                          message_id=MESSAGE, expires_in=60, config_path=config)
    (root / "user_prompt_submit.py").write_text("concurrent work", encoding="utf-8")
    before_other = (root / "session_start.py").read_bytes()
    with pytest.raises(RuntimeError, match="changed"):
        harness.restore_hooks(root, control)
    assert (root / "session_start.py").read_bytes() == before_other
    assert (root / "user_prompt_submit.py").read_text(encoding="utf-8") == "concurrent work"
    assert originals["session_start.py"] != harness.sha256(root / "session_start.py")


def test_restore_refuses_changed_global_hooks_config(tmp_path):
    _, root, helper, config, control = make_install_tree(tmp_path)
    harness.install_hooks(root, control, helper, mode="ack-precommit", session_id=SID,
                          message_id=MESSAGE, expires_in=60, config_path=config)
    config.write_text('{"changed":true}', encoding="utf-8")
    before = {name: (root / name).read_bytes() for name in harness.HOOK_NAMES}
    with pytest.raises(RuntimeError, match="configuration changed"):
        harness.restore_hooks(root, control)
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
@pytest.mark.parametrize("mode", ["ack-precommit", "observe"])
def test_installed_shim_subprocess_passes_through_byte_exact_backup(tmp_path, which, mode):
    _, root, helper, config, control = make_install_tree(tmp_path)
    harness.install_hooks(root, control, helper, mode=mode, session_id=SID,
                          message_id=MESSAGE, expires_in=60, config_path=config)
    backup = control / (which + ".relay-fault-backup")
    expected = b"original stdin\x00bytes\r\n"
    baseline = subprocess.run([sys.executable, str(backup)], input=expected,
                              capture_output=True, timeout=5)
    run = subprocess.run([sys.executable, str(root / which)], input=expected,
                         capture_output=True, timeout=5)
    assert (run.returncode, run.stdout, run.stderr) == (
        baseline.returncode, baseline.stdout, baseline.stderr
    )
    assert backup.is_file()


def _observed_claim():
    return {"session": {"endpoint_id": "endpoint", "container_ref": "container",
                        "scope_generation": 0},
            "has_more": False, "remaining_count": 0,
            "deliveries": [{
                "message_id": MESSAGE, "delivery_id": DELIVERY,
                "lease_expires_at": "2026-10-06T12:01:00Z",
                "claim_token": "secret-never-log", "sender_runtime": "codex",
                "sender_session_ref": "peer-session", "payload": "private payload",
                "created_at": "2026-10-06T12:00:00Z", "attempts": 1,
            }]}


def _configure_observation_hook(module, tmp_path, *, rendered=True,
                                emit_ok=True, ack_ok=True, unavailable=False,
                                malformed=False, state_writes=True):
    """Drive the real hook main() with deterministic local dependencies."""
    operations = []
    emitted = []
    module.start_hook_deadline = lambda *a, **k: None
    module.read_hook_input = lambda: {
        "source": "resume", "cwd": str(tmp_path), "session_id": SID,
        "prompt": "ordinary user prompt",
    }
    module.derive_container_ref = lambda cwd: "container"
    module.derive_actor_ref = lambda cwd, session: "actor"
    module.pin_container = lambda *a, **k: None
    module.resolve_container_ref = lambda *a, **k: "container"
    module.discover_work_refs = lambda *a, **k: {}
    module.injected_work_ref = lambda *a, **k: None
    module.structural_work_refs_payload = lambda *a, **k: None
    module.confirmed_registry_work_refs = lambda *a, **k: []
    module.build_work_refs_metadata = lambda *a, **k: {}
    module.work_ref_warning = lambda *a, **k: ""
    module.check_dedup = lambda *a, **k: False
    module.record_codex_hook_execution = lambda **k: True
    module.format_injection = lambda *a, **k: "scope-context"
    module.pallium_request = lambda *a, **k: None
    module._common.remaining_safe_time = lambda *a, **k: 7.0
    module._common.SESSIONS_DIR = tmp_path / "sessions"
    actual = (None if unavailable else
              {"deliveries": _observed_claim()["deliveries"]} if malformed else
              _observed_claim())
    module.relay_request = lambda method, path, body, **opts: (
        operations.append(("http", method, path)) or actual
    )
    module._common.relay_request = lambda method, path, body, **opts: (
        operations.append(("http", method, path)) or
        ({"delivery_id": DELIVERY, "state": "delivered", "already_delivered": False}
         if ack_ok else None)
    )
    writes = list(state_writes) if isinstance(state_writes, list) else None
    module._common._write_session_state_locked = lambda *a, **k: (
        writes.pop(0) if writes else True
    ) if writes is not None else state_writes
    module.format_relay = lambda deliveries, **kwargs: (
        ("rendered-context", list(deliveries)) if rendered else ("", [])
    )
    def emit_utf8(text, *, stream=None):
        document = json.loads(text)
        emitted.append((document["hookSpecificOutput"]["additionalContext"],
                        document["hookSpecificOutput"]["hookEventName"]))
        operations.append(("emit", document["hookSpecificOutput"]["hookEventName"]))
        return emit_ok

    module._common.emit_utf8 = emit_utf8
    if hasattr(module, "record_codex_wake_event"):
        module.record_codex_wake_event = lambda **k: True
    return operations, emitted, actual


def test_observer_runs_actual_hook_main_without_changing_calls_or_output(module, tmp_path, observation_reader):
    hook = module.__name__
    manifest, evidence, _ = setup_manifest(tmp_path, "observe")
    operations, emitted, actual = _configure_observation_hook(module, tmp_path)
    before = module._common.relay_request
    undo = harness.wrap_hook(module, manifest, evidence)
    try:
        with pytest.raises(SystemExit) as exit_info:
            module.main()
    finally:
        undo()
    assert exit_info.value.code == 0
    assert operations == [
        ("http", "POST", "/relay/turn"),
        ("emit", "SessionStart" if hook == "session_start" else "UserPromptSubmit"),
        ("http", "POST", "/relay/deliveries/ack"),
    ]
    assert emitted == [
        ("rendered-context\n\nscope-context",
         "SessionStart" if hook == "session_start" else "UserPromptSubmit")
    ]
    assert module._common.relay_request is before
    ledger = observation_reader["wait"](evidence)
    rows = [json.loads(line) for line in ledger.splitlines()]
    assert rows and all(row["hook"] == hook for row in rows)
    assert all(row["event"] == "codex_relay_observation" for row in rows)
    assert all(set(row) == {
        "event", "hook", "stage", "outcome", "target_present",
        "delivery_id", "elapsed_ms", "at",
    } for row in rows)
    assert any(row["stage"] == "format_relay" and row["target_present"] for row in rows)
    assert any(row["stage"] == "state_write_after" and row["outcome"] == "true" for row in rows)
    assert any(row["stage"] == "acknowledge_relay" and row["outcome"] == "confirmed" for row in rows)
    assert all(row["delivery_id"] in {None, DELIVERY} for row in rows)
    assert "secret-never-log" not in ledger and "private payload" not in ledger
    assert str(tmp_path) not in ledger


@pytest.mark.parametrize("rendered", [False, True])
def test_observer_distinguishes_fallback_or_emit_and_ack_results(module, tmp_path, rendered, observation_reader):
    hook = module.__name__
    manifest, evidence, _ = setup_manifest(tmp_path, "observe")
    operations, emitted, _ = _configure_observation_hook(
        module, tmp_path, rendered=rendered, emit_ok=True, ack_ok=False
    )
    undo = harness.wrap_hook(module, manifest, evidence)
    try:
        with pytest.raises(SystemExit):
            module.main()
    finally:
        undo()
    rows = [json.loads(line) for line in observation_reader["wait"](evidence).splitlines()]
    if rendered:
        assert emitted
        assert any(row["stage"] == "acknowledge_relay" and row["outcome"] == "returned" for row in rows)
    else:
        assert emitted == [("scope-context", "SessionStart" if hook == "session_start" else "UserPromptSubmit")]
        assert any(row["stage"] == "emit_context" and row["target_present"] is False for row in rows)
        assert not any(row["stage"] == "acknowledge_relay" and row["target_present"] for row in rows)


def test_observer_mode_is_exact_target_one_shot_and_bounded(module, tmp_path, monkeypatch, observation_reader):
    manifest, evidence, value = setup_manifest(tmp_path, "observe")
    calls = install_fake_turn(module)
    undo = harness.wrap_hook(module, manifest, evidence)
    try:
        assert module.relay_turn("codex", "other-session", request=lambda *a, **k: claimed()) == claimed()
        assert module.relay_turn("codex", SID, request=lambda *a, **k: None) is None
        assert module.relay_turn("codex", SID, request=lambda *a, **k: claimed()) == claimed()
    finally:
        undo()
    assert calls == [("codex", "other-session"), ("codex", SID), ("codex", SID)]
    ledger = observation_reader["wait"](evidence)
    rows = [json.loads(line) for line in ledger.splitlines()]
    assert rows and Path(value["state_path"] + ".used").exists()
    assert all(row["hook"] in {"session_start", "user_prompt_submit"} for row in rows)
    assert not any(row["target_present"] for row in rows if row["stage"] == "relay_response")
    assert len(rows) <= harness.OBSERVE_EVENT_LIMIT
    assert evidence.stat().st_size <= harness.OBSERVE_BYTES_LIMIT


@pytest.mark.parametrize("response_case", ["unavailable", "malformed"])
def test_observer_distinguishes_unavailable_from_malformed_target_response(
    module, tmp_path, response_case, observation_reader
):
    manifest, evidence, _ = setup_manifest(tmp_path, "observe")
    _configure_observation_hook(
        module, tmp_path, unavailable=response_case == "unavailable",
        malformed=response_case == "malformed",
    )
    undo = harness.wrap_hook(module, manifest, evidence)
    try:
        with pytest.raises(SystemExit):
            module.main()
    finally:
        undo()
    rows = [json.loads(line) for line in observation_reader["wait"](evidence).splitlines()]
    response_targets = [row["target_present"] for row in rows if row["stage"] == "relay_response"]
    assert any(response_targets) is (response_case == "malformed")
    assert not any(row["target_present"] for row in rows if row["stage"] == "format_relay")
    assert not any(row["target_present"] for row in rows if row["stage"] == "acknowledge_relay")
    assert any(row["delivery_id"] == DELIVERY for row in rows) is (response_case == "malformed")


def test_observer_rejects_post_response_state_write_and_does_not_mark_rendered(module, tmp_path, observation_reader):
    manifest, evidence, _ = setup_manifest(tmp_path, "observe")
    _configure_observation_hook(module, tmp_path, state_writes=[True, False])
    undo = harness.wrap_hook(module, manifest, evidence)
    try:
        with pytest.raises(SystemExit):
            module.main()
    finally:
        undo()
    rows = [json.loads(line) for line in observation_reader["wait"](evidence).splitlines()]
    assert any(row["stage"] == "relay_response" and row["target_present"] is True for row in rows)
    assert any(row["stage"] == "state_write_after" and row["outcome"] == "false" for row in rows)
    assert not any(row["target_present"] for row in rows if row["stage"] == "format_relay")


def test_observer_logger_failure_is_fail_open_and_restores_every_wrapper(
    module, tmp_path, monkeypatch, capsys
):
    manifest, evidence, _ = setup_manifest(tmp_path, "observe")
    _configure_observation_hook(module, tmp_path)
    original = (module.relay_turn, module.format_relay, module.emit_context,
                module.acknowledge_relay, module._common._write_session_state_locked,
                module._common.emit_utf8, getattr(module, "emit_utf8", None))
    append_entered = threading.Event()
    restored = []
    thread_errors = []
    monkeypatch.setattr(threading, "excepthook", lambda args: thread_errors.append(args.exc_value))

    def fail_append(*args):
        append_entered.set()
        restored.append((module.relay_turn, module.format_relay, module.emit_context,
                         module.acknowledge_relay,
                         module._common._write_session_state_locked,
                         module._common.emit_utf8, getattr(module, "emit_utf8", None)) == original)
        raise OSError("must not escape")

    monkeypatch.setattr(harness, "_append_observation", fail_append)
    undo = harness.wrap_hook(module, manifest, evidence)
    with pytest.raises(SystemExit):
        module.main()
    assert not append_entered.is_set()
    undo()
    assert append_entered.wait(1)
    assert restored == [True]
    assert (module.relay_turn, module.format_relay, module.emit_context,
            module.acknowledge_relay, module._common._write_session_state_locked,
            module._common.emit_utf8, getattr(module, "emit_utf8", None)) == original
    assert thread_errors == []
    assert capsys.readouterr().err == ""


def test_observer_blocked_logger_wait_is_bounded(module, tmp_path, monkeypatch):
    manifest, evidence, _ = setup_manifest(tmp_path, "observe")
    _configure_observation_hook(module, tmp_path)
    entered, release = threading.Event(), threading.Event()

    def blocked_append(*args):
        entered.set()
        release.wait(1)
        return True

    monkeypatch.setattr(harness, "_append_observation", blocked_append)
    undo = harness.wrap_hook(module, manifest, evidence)
    with pytest.raises(SystemExit):
        module.main()
    started = time.monotonic()
    try:
        undo()
        assert time.monotonic() - started < 0.5
        assert entered.wait(1)
    finally:
        release.set()


@pytest.mark.parametrize("failure", ["write", "flush"])
def test_observer_write_flush_failure_is_reported_without_claiming_emission(
    module, tmp_path, failure, observation_reader
):
    manifest, evidence, _ = setup_manifest(tmp_path, "observe")
    original_utf8 = module._common.emit_utf8
    _configure_observation_hook(module, tmp_path)
    module._common.emit_utf8 = original_utf8

    class BrokenStream:
        def write(self, value):
            if failure == "write":
                raise OSError("private write failure")
            return len(value)

        def flush(self):
            if failure == "flush":
                raise OSError("private flush failure")

    original_stdout = sys.stdout
    sys.stdout = BrokenStream()
    undo = harness.wrap_hook(module, manifest, evidence)
    try:
        with pytest.raises(SystemExit):
            module.main()
    finally:
        sys.stdout = original_stdout
        undo()
    rows = [json.loads(line) for line in observation_reader["wait"](evidence).splitlines()]
    assert any(row["stage"] == "emit_utf8" and row["outcome"] == "false" for row in rows)
    assert any(row["stage"] == "emit_context" and row["outcome"] == "exception" for row in rows)
    assert not any(row["stage"] == "acknowledge_relay" and row["target_present"] for row in rows)


def test_observer_preserves_module_emit_utf8_call_arguments(tmp_path, observation_reader):
    module = load_hook("user_prompt_submit")
    manifest, evidence, _ = setup_manifest(tmp_path, "observe")
    _configure_observation_hook(module, tmp_path, unavailable=True)
    module.read_hook_input = lambda: {
        "cwd": str(tmp_path), "session_id": SID, "prompt": module.RELAY_WAKE_PROMPT,
    }
    calls = []

    def emit_utf8(*args, **kwargs):
        calls.append((args, kwargs))
        return True

    module.emit_utf8 = emit_utf8
    undo = harness.wrap_hook(module, manifest, evidence)
    try:
        with pytest.raises(SystemExit):
            module.main()
    finally:
        undo()
    assert len(calls) == 1
    assert len(calls[0][0]) == 1 and calls[0][1] == {}
    assert json.loads(calls[0][0][0])["decision"] == "block"
    rows = [json.loads(line) for line in observation_reader["wait"](evidence).splitlines()]
    assert any(row["stage"] == "emit_utf8" and row["outcome"] == "true" for row in rows)


def test_observer_partial_setup_failure_restores_and_calls_original(module, tmp_path, monkeypatch, observation_reader):
    manifest, evidence, _ = setup_manifest(tmp_path, "observe")
    calls = install_fake_turn(module)
    original_turn = module.relay_turn
    original_writer = module._common._write_session_state_locked
    original_emit = module._common.emit_utf8
    original_patch = harness._Observation.patch

    def fail_after_common_patches(observer, obj, attr, replacement):
        if attr == "format_relay":
            raise OSError("private setup failure")
        original_patch(observer, obj, attr, replacement)

    monkeypatch.setattr(harness._Observation, "patch", fail_after_common_patches)
    undo = harness.wrap_hook(module, manifest, evidence)
    try:
        response = module.relay_turn("codex", SID, request=lambda *a, **k: claimed())
    finally:
        undo()
    assert response == claimed()
    assert calls == [("codex", SID)]
    assert module.relay_turn is original_turn
    assert module._common._write_session_state_locked is original_writer
    assert module._common.emit_utf8 is original_emit
    ledger = observation_reader["wait"](evidence)
    rows = [json.loads(line) for line in ledger.splitlines()]
    assert any(row["stage"] == "relay_turn" and row["outcome"] == "observer_setup_failed" for row in rows)
    assert "private setup failure" not in ledger


@pytest.mark.parametrize("outcome", ["return", "raise"])
def test_observer_teardown_failure_is_incomplete_and_preserves_caller_result(
    module, tmp_path, outcome, capsys, monkeypatch, observation_reader
):
    manifest, evidence, _ = setup_manifest(tmp_path, "observe")
    response = claimed()
    operation_error = RuntimeError("private operation failure")
    call_count = []

    def original_turn(*args, **kwargs):
        call_count.append("once")
        if outcome == "raise":
            raise operation_error
        return kwargs["request"]("POST", "/relay/turn", {}, timeout=0.1)

    originals = dict(module.__dict__)
    class RejectOneRestore:
        def __init__(self):
            self.__dict__.update(originals)
            self.fail_restore = False
            self.restore_failed_once = False

        def __setattr__(self, name, value):
            if (name == "format_relay" and self.fail_restore
                    and value is originals["format_relay"]
                    and not self.restore_failed_once):
                object.__setattr__(self, "restore_failed_once", True)
                raise RuntimeError("private restore failure")
            object.__setattr__(self, name, value)

    proxy = RejectOneRestore()
    proxy.relay_turn = original_turn
    original_format = proxy.format_relay
    undo = harness.wrap_hook(proxy, manifest, evidence)
    proxy.fail_restore = True
    thread_errors = []
    monkeypatch.setattr(threading, "excepthook", lambda args: thread_errors.append(args.exc_value))
    try:
        if outcome == "raise":
            with pytest.raises(RuntimeError) as caught:
                proxy.relay_turn(
                    "codex", SID, request=lambda *a, **k: response
                )
            assert caught.value is operation_error
        else:
            result = proxy.relay_turn(
                "codex", SID, request=lambda *a, **k: response
            )
            assert result is response
    finally:
        undo()
        # Undo intentionally reports incomplete evidence but the test removes its
        # one injected restore failure so this synthetic module cannot leak a patch.
        proxy.fail_restore = False
        proxy.format_relay = original_format

    assert call_count == ["once"]
    assert proxy.relay_turn is original_turn
    assert proxy.format_relay is original_format
    ledger = observation_reader["wait"](evidence)
    rows = [json.loads(line) for line in ledger.splitlines()]
    assert rows[-1]["stage"] == "observer_finished"
    assert rows[-1]["outcome"] == "incomplete"
    assert "private operation failure" not in ledger
    assert "private restore failure" not in ledger
    assert thread_errors == []
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


@pytest.mark.parametrize("bad_control", ["expired", "malformed", "used"])
def test_observer_bad_or_consumed_control_is_original_noop(module, tmp_path, bad_control):
    manifest, evidence, value = setup_manifest(tmp_path, "observe")
    if bad_control == "expired":
        value["expires_at"] = time.time() - 1
        manifest.write_text(json.dumps(value), encoding="utf-8")
    elif bad_control == "malformed":
        manifest.write_text("{", encoding="utf-8")
    else:
        Path(value["state_path"] + ".used").write_text("reserved", encoding="utf-8")
    calls = install_fake_turn(module)
    original = module.relay_turn
    undo = harness.wrap_hook(module, manifest, evidence)
    try:
        response = module.relay_turn("codex", SID, request=lambda *a, **k: claimed())
    finally:
        undo()
    assert response == claimed()
    assert calls == [("codex", SID)]
    assert module.relay_turn is original
    assert not evidence.exists()


def test_observer_event_overflow_keeps_the_ledger_bounded(module, tmp_path, monkeypatch, observation_reader):
    manifest, evidence, _ = setup_manifest(tmp_path, "observe")
    monkeypatch.setattr(harness, "OBSERVE_EVENT_LIMIT", 2)
    _configure_observation_hook(module, tmp_path)
    undo = harness.wrap_hook(module, manifest, evidence)
    try:
        with pytest.raises(SystemExit):
            module.main()
    finally:
        undo()
    ledger = observation_reader["wait"](evidence)
    rows = [json.loads(line) for line in ledger.splitlines()]
    assert len(rows) <= 2
    assert evidence.stat().st_size <= harness.OBSERVE_BYTES_LIMIT


def test_observer_byte_overflow_keeps_the_ledger_bounded(module, tmp_path, monkeypatch, observation_reader):
    manifest, evidence, _ = setup_manifest(tmp_path, "observe")
    monkeypatch.setattr(harness, "OBSERVE_BYTES_LIMIT", 600)
    _configure_observation_hook(module, tmp_path)
    undo = harness.wrap_hook(module, manifest, evidence)
    try:
        with pytest.raises(SystemExit):
            module.main()
    finally:
        undo()
    observation_reader["wait"](evidence)
    assert evidence.stat().st_size <= 600


def test_observer_concurrent_admission_is_one_shot(module, tmp_path, observation_reader):
    manifest, evidence, value = setup_manifest(tmp_path, "observe")
    calls = install_fake_turn(module)
    barrier = threading.Barrier(3)
    results = []
    undo = harness.wrap_hook(module, manifest, evidence)

    def invoke():
        barrier.wait()
        results.append(module.relay_turn(
            "codex", SID, request=lambda *a, **k: claimed()
        ))

    workers = [threading.Thread(target=invoke) for _ in range(2)]
    try:
        for worker in workers:
            worker.start()
        barrier.wait()
        for worker in workers:
            worker.join(timeout=2)
            assert not worker.is_alive()
    finally:
        undo()
    assert calls == [("codex", SID), ("codex", SID)]
    assert results == [claimed(), claimed()]
    assert Path(value["state_path"] + ".used").exists()
    rows = [json.loads(line) for line in observation_reader["wait"](evidence).splitlines()]
    assert len([row for row in rows if row["stage"] == "relay_response"]) == 1


def test_observer_concurrent_append_is_read_only_after_completion(module, tmp_path, observation_reader):
    manifest, evidence, value = setup_manifest(tmp_path, "observe")
    calls = install_fake_turn(module)
    responses = [claimed(), claimed()]
    results = []
    barrier = threading.Barrier(3)
    originals = (module.relay_turn, module.format_relay, module.emit_context,
                 module.acknowledge_relay, module._common._write_session_state_locked,
                 module._common.emit_utf8, getattr(module, "emit_utf8", None))
    observation_reader["pause"].set()
    undo = harness.wrap_hook(module, manifest, evidence)
    undone = False

    def invoke(response):
        barrier.wait()
        results.append(module.relay_turn(
            "codex", SID, request=lambda *a, **k: response
        ))

    workers = [threading.Thread(target=invoke, args=(response,)) for response in responses]
    try:
        for worker in workers:
            worker.start()
        barrier.wait()
        for worker in workers:
            worker.join(timeout=2)
            assert not worker.is_alive()
        assert calls == [("codex", SID), ("codex", SID)]
        assert len(results) == 2 and {id(result) for result in results} == {
            id(response) for response in responses
        }
        assert Path(value["state_path"] + ".used").exists()
        started = time.monotonic()
        undo()
        undone = True
        assert time.monotonic() - started < 0.5
        assert observation_reader["opened"].wait(1)
        assert (module.relay_turn, module.format_relay, module.emit_context,
                module.acknowledge_relay, module._common._write_session_state_locked,
                module._common.emit_utf8, getattr(module, "emit_utf8", None)) == originals
        assert evidence.read_bytes() == b""
    finally:
        observation_reader["release"].set()
        if not undone:
            undo()
    ledger = observation_reader["wait"](evidence)
    rows = [json.loads(line) for line in ledger.splitlines()]
    assert len([row for row in rows if row["stage"] == "relay_response"]) == 1
    assert rows[-1]["stage"] == "observer_finished" and rows[-1]["outcome"] == "captured"


def test_observer_preserves_original_exception_identity(module, tmp_path, observation_reader):
    manifest, evidence, _ = setup_manifest(tmp_path, "observe")
    original_error = RuntimeError("private operation exception")

    def original(*args, **kwargs):
        raise original_error

    module.relay_turn = original
    undo = harness.wrap_hook(module, manifest, evidence)
    try:
        with pytest.raises(RuntimeError) as caught:
            module.relay_turn("codex", SID, request=lambda *a, **k: claimed())
    finally:
        undo()
    assert caught.value is original_error
    assert "private operation exception" not in observation_reader["wait"](evidence)


@pytest.mark.parametrize("state", ["notLoaded", "idle"])
def test_observer_preserves_real_http_hook_emission_and_ack(http_wake, monkeypatch,
                                                            tmp_path, capsys, state, observation_reader):
    http = http_wake[0]
    script = "user_prompt_submit" if state == "idle" else "session_start"
    events = []
    hook_runner = _hook_runner(http, monkeypatch, state, events, tmp_path)

    def send(message_id):
        response = http.post("/relay/messages", json={
            "sender_runtime": "claude-code", "sender_session_ref": "sender",
            "recipient": f"codex:{WAKE_TARGET}", "message_id": message_id,
            "payload": "observer caller-surface payload", **WAKE_SCOPE,
        })
        assert response.status_code == 200, response.text
        return response.json()["deliveries"][0]

    baseline = send("observer-baseline")
    request_log = []
    original_request = http.request

    def request(method, url, *args, **kwargs):
        request_log.append((method, str(url)))
        return original_request(method, url, *args, **kwargs)

    monkeypatch.setattr(http, "request", request)
    hook = sys.modules[f"relay_test_retained_{script}"]
    actual_ack = hook._common.acknowledge_relay

    def relay_request(method, path, body, **kwargs):
        response = http.request(method, path, json=body)
        assert response.status_code == 200, response.text
        return response.json()

    monkeypatch.setattr(hook._common, "relay_request", relay_request)

    def acknowledge(deliveries, *, container_ref):
        assert events and events[-1][0] == "emit"
        result = actual_ack(deliveries, container_ref=container_ref)
        events.append(("ack",))
        return result

    monkeypatch.setattr(hook, "acknowledge_relay", acknowledge)
    # Compare hook behavior independently of disk time spent on local admission.
    from itertools import count

    common = hook._common
    native_clock = time.monotonic
    clock = count(start=10.0, step=.001).__next__
    original_start = hook.start_hook_deadline

    def start_deadline(*args, **kwargs):
        return original_start(*args, **kwargs, clock=clock)

    monkeypatch.setattr(hook, "start_hook_deadline", start_deadline)
    hook_runner()
    baseline_events = list(events)
    baseline_stdout = capsys.readouterr().out
    baseline_requests = list(request_log)
    assert baseline_requests == [("POST", "/relay/turn"), ("POST", "/relay/deliveries/ack")]
    assert [event[0] for event in baseline_events] == ["emit", "ack"]
    assert "observer caller-surface payload" in baseline_events[0][2]
    baseline_status = original_request(
        "GET", "/relay/messages/observer-baseline", params=WAKE_SCOPE,
    )
    assert baseline_status.status_code == 200, baseline_status.text
    baseline_delivery = baseline_status.json()["deliveries"][0]
    assert baseline_delivery["state"] == "delivered" and baseline_delivery["attempts"] == 1
    assert common.hook_deadline().clock is clock and time.monotonic is native_clock

    observed = send("observer-target")
    events.clear()
    request_log.clear()

    manifest, evidence, _ = setup_manifest(
        tmp_path, "observe", session_id=WAKE_TARGET,
        message_id="observer-target",
    )
    original_turn = hook.relay_turn
    undo = harness.wrap_hook(hook, manifest, evidence)
    try:
        hook_runner()
        assert not evidence.exists(), "observation must not append inside the hook"
    finally:
        undo()
    observed_events = list(events)
    observed_stdout = capsys.readouterr().out
    observed_requests = list(request_log)
    assert observed_requests == baseline_requests
    assert len(observed_events) == len(baseline_events) == 2
    assert [item[:2] for item in observed_events] == [item[:2] for item in baseline_events]
    def normalize(text, delivery, message_id):
        text = (text.replace(message_id, "<message>")
                .replace(delivery["delivery_id"], "<delivery>")
                .replace(delivery["created_at"], "<timestamp>"))
        return re.sub(r"sent_at: [^\r\n]+", "sent_at: <timestamp>", text)

    assert normalize(observed_events[0][2], observed, "observer-target") == normalize(
        baseline_events[0][2], baseline, "observer-baseline"
    )
    assert normalize(observed_stdout, observed, "observer-target") == normalize(
        baseline_stdout, baseline, "observer-baseline"
    )
    assert hook.relay_turn is original_turn
    ledger = observation_reader["wait"](evidence)
    rows = [json.loads(line) for line in ledger.splitlines()]
    assert rows and any(row["stage"] == "acknowledge_relay" and row["outcome"] == "confirmed" for row in rows)
    assert "observer caller-surface payload" not in ledger
    for message_id in ("observer-baseline", "observer-target"):
        state_response = http.get(f"/relay/messages/{message_id}", params=WAKE_SCOPE)
        assert state_response.status_code == 200
        assert state_response.json()["deliveries"][0]["state"] == "delivered"
