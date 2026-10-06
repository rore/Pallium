"""Recovery after a conclusively drained retained Desktop read failure."""
import pytest

from tests.test_codex_retained_wake import (
    SCOPE, TARGET, _hook_runner, http_wake, recover, retained as retained_fixture,
)


@pytest.fixture
def retained(monkeypatch, tmp_path):
    yield from retained_fixture.__wrapped__(monkeypatch, tmp_path)


def _defer_on_state_timeout(http_wake, retained, bridge, *, unresolved=False, native_failure=False):
    http, _, _, service, first, send, _ = http_wake
    _, _, natives = retained
    first.state = "notLoaded"
    original_read = first.read

    def timeout_read(deadline):
        request = first.writes[-1]
        if request.get("params", {}).get("tool") == "read_thread":
            if native_failure:
                envelope = original_read(deadline)
                envelope["result"] = {"success": False, "contentItems": [
                    {"type": "inputText", "text": "private native failure sentinel"}]}
                first.unresolved = unresolved
                return envelope
            first.unresolved = unresolved
            raise bridge.ShadowUnavailable("deadline")
        return original_read(deadline)

    first.read = timeout_read
    send()
    return http, service, first, natives


def test_native_tool_failure_reopens_same_registration_for_hook_delivery(
        http_wake, retained, monkeypatch, capsys, tmp_path):
    from app import codex_bridge_pipe as bridge
    http, _, registry, service, first, send, _ = http_wake
    _, _, natives = retained
    events = []
    hook = _hook_runner(http, monkeypatch, "notLoaded", events, tmp_path)
    original_read = first.read

    def unavailable_read(deadline):
        envelope = original_read(deadline)
        if first.writes[-1].get("params", {}).get("tool") == "read_thread":
            envelope["result"] = {"success": False, "contentItems": [
                {"type": "inputText", "text": "private native failure sentinel"}]}
        return envelope

    first.read = unavailable_read
    delivery = send()
    assert first.owners == [] and registry.reservations() == ()
    assert service.retained_registration is not None
    assert http.get("/relay/messages/retained-journey", params={
        "container_ref": "git:example.test/retained-東京"}).json()["deliveries"][0]["state"] == "pending"
    failure_log = capsys.readouterr().err
    assert "category=native-tool-failed" in failure_log
    assert "stage=state-read" in failure_log
    from app.codex_wake import relay_wake_log_refs
    delivery_ref, _, _ = relay_wake_log_refs(
        delivery["delivery_id"], TARGET, SCOPE["container_ref"])
    assert f"delivery_ref={delivery_ref}" in failure_log and "generation=1" in failure_log
    assert "timestamp=20" in failure_log and "+00:00" in failure_log
    assert "private native failure sentinel" not in failure_log

    original_connect = bridge._DesktopIO

    def reconnect(*args):
        desktop = original_connect(*args)
        desktop.on_owner = lambda request: hook(request["params"]["arguments"]["prompt"])
        return desktop

    monkeypatch.setattr(bridge, "_DesktopIO", reconnect)
    recover(http_wake)

    assert len(natives) == 2 and natives[0].closed and len(natives[1].owners) == 1
    assert sum(w.get("params", {}).get("tool") == "read_thread" for w in first.writes) == 1
    assert sum(w.get("params", {}).get("tool") == "read_thread" for w in natives[1].writes) == 1
    assert [event[0] for event in events] == ["emit", "ack"]
    assert registry.reservations() == ()
    assert http.get("/relay/messages/retained-journey", params={
        "container_ref": "git:example.test/retained-東京"}).json()["deliveries"][0]["state"] == "delivered"


def test_drained_read_timeout_reopens_same_registration_for_hook_delivery(
        http_wake, retained, monkeypatch, capsys, tmp_path):
    from app import codex_bridge_pipe as bridge
    http, _, registry, service, first, send, _ = http_wake
    _, _, natives = retained
    events = []
    hook = _hook_runner(http, monkeypatch, "notLoaded", events, tmp_path)
    _defer_on_state_timeout(http_wake, retained, bridge)
    assert first.owners == []
    assert http.get("/relay/messages/retained-journey", params={"container_ref": "git:example.test/retained-東京"}).json()["deliveries"][0]["state"] == "pending"

    original_connect = bridge._DesktopIO

    def reconnect(*args):
        desktop = original_connect(*args)
        desktop.on_owner = lambda request: hook(request["params"]["arguments"]["prompt"])
        if len(natives) == 2:
            original_read = desktop.read

            def timeout_read(deadline):
                request = desktop.writes[-1]
                if request.get("params", {}).get("tool") == "read_thread":
                    raise bridge.ShadowUnavailable("deadline")
                return original_read(deadline)

            desktop.read = timeout_read
        return desktop

    monkeypatch.setattr(bridge, "_DesktopIO", reconnect)
    recover(http_wake)
    assert len(natives) == 2 and service.retained_registration is not None
    recover(http_wake)

    assert len(natives) == 3
    assert natives[0].closed and natives[1].closed and natives[2].owners
    assert [event[0] for event in events] == ["emit", "ack"]
    assert registry.reservations() == ()
    assert http.get("/relay/messages/retained-journey", params={"container_ref": "git:example.test/retained-東京"}).json()["deliveries"][0]["state"] == "delivered"
    assert "private-payload-東京" in capsys.readouterr().out


def test_reconnect_catalog_timeout_preserves_authority_for_next_recovery(http_wake, retained, monkeypatch):
    from app import codex_bridge_pipe as bridge
    _, service, _, natives = _defer_on_state_timeout(http_wake, retained, bridge)
    original_connect = bridge._DesktopIO

    def timeout_catalog(*args):
        desktop = original_connect(*args)
        original_read = desktop.read

        def read(deadline):
            if desktop.writes[-1].get("method") == "tools/list":
                raise bridge.ShadowUnavailable("deadline")
            return original_read(deadline)

        desktop.read = read
        return desktop

    monkeypatch.setattr(bridge, "_DesktopIO", timeout_catalog)
    recover(http_wake)
    assert len(natives) == 2 and service.retained_registration is not None

    monkeypatch.setattr(bridge, "_DesktopIO", original_connect)
    recover(http_wake)
    assert len(natives) == 3 and len(natives[2].owners) == 1


@pytest.mark.parametrize("initial_fault", ["timeout", "native-failure"])
@pytest.mark.parametrize("change", ["source", "epoch", "server", "schema", "unresolved"])
def test_reopen_denies_changed_registration_authority(
        http_wake, retained, monkeypatch, change, initial_fault):
    from app import codex_bridge_pipe as bridge

    http, service, _, natives = _defer_on_state_timeout(
        http_wake, retained, bridge, native_failure=initial_fault == "native-failure")
    original_connect = bridge._DesktopIO

    def reconnect(*args):
        desktop = original_connect(*args)
        if change == "schema":
            desktop.schemas = desktop.schemas[:1]
        return desktop

    if change == "source":
        service.source.gone = True
    elif change == "epoch":
        service.epoch = "changed-epoch"
    elif change == "unresolved":
        service.unresolved = True
    elif change == "server":
        monkeypatch.setattr(bridge, "_DesktopIO", reconnect)
        service.w.pipe.GetNamedPipeServerProcessId = lambda handle: 41
    elif change == "schema":
        monkeypatch.setattr(bridge, "_DesktopIO", reconnect)

    recover(http_wake)

    assert service.retained_registration is None
    assert not any(desktop.owners for desktop in natives)
    assert http.get("/relay/messages/retained-journey", params={
        "container_ref": "git:example.test/retained-東京"}).json()["deliveries"][0]["state"] == "pending"


@pytest.mark.parametrize("native_failure", [False, True])
def test_unresolved_read_cancellation_clears_reopen_authority(http_wake, retained, native_failure):
    from app import codex_bridge_pipe as bridge

    _, service, _, natives = _defer_on_state_timeout(
        http_wake, retained, bridge, unresolved=True, native_failure=native_failure)
    assert service.unresolved and service.retained_registration is None
    assert len(natives) == 1


def test_stop_and_source_disconnect_clear_reopen_authority(http_wake, retained):
    from app import codex_bridge_pipe as bridge_module

    _, service, _, _ = _defer_on_state_timeout(http_wake, retained, bridge_module)
    service._drop()  # The retained source channel's EOF path uses the ordinary drop.
    assert service.retained_registration is None

    _, service, _, _ = _defer_on_state_timeout(http_wake, retained, bridge_module)
    service.stop()
    assert service.retained_registration is None and service.stop_event.is_set()


@pytest.mark.parametrize("response", ["lost", "native-error"])
def test_post_owner_failure_keeps_spent_delivery_fenced(http_wake, response, capsys):
    http, _, registry, _, desktop, send, _ = http_wake
    desktop.response = response
    send()
    assert len(desktop.owners) == 1
    assert registry.reservations()[0].outcome == "uncertain"
    recover(http_wake)
    assert len(desktop.owners) == 1
    if response == "native-error":
        failure_log = capsys.readouterr().err
        assert "category=native-tool-failed" in failure_log and "stage=owner-result" in failure_log
    assert http.get("/relay/messages/retained-journey", params={
        "container_ref": "git:example.test/retained-東京"}).json()["deliveries"][0]["state"] == "pending"
