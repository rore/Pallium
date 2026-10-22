"""Qualify the default observer against the shared private application fixture."""
from contextlib import ExitStack
import ast
import inspect
import json
import os
from pathlib import Path
import re
import socket
import time

import anyio
import fastapi.routing
import pytest

from core.relay import RelayService
from scripts import relay_targeted_boundary_capture as capture


def private_route_state(client):
    iterate = getattr(fastapi.routing, "iter_route_contexts", None)
    contexts = iterate(client.app.routes) if iterate is not None else client.app.routes
    matches = [context for context in contexts
               if isinstance(getattr(context, "original_route", context), fastapi.routing.APIRoute)
               and context.path == "/relay/turn" and "POST" in context.methods]
    assert len(matches) == 1
    context = matches[0]
    original_route = getattr(context, "original_route", context)
    dependant = context.dependant
    if iterate is not None:
        assert dependant is not original_route.dependant
    limiter = capture.recover_limiter(dependant.call)
    witness = {
        "direct_candidates": sum(isinstance(route, fastapi.routing.APIRoute)
                                 and route.path == "/relay/turn" and "POST" in route.methods
                                 for route in client.app.routes),
        "effective_candidates": len(matches),
        "effective_dependant_is_original": dependant is original_route.dependant,
    }
    return dependant, original_route, limiter, witness


def test_actual_private_fixture_installs_correlates_and_restores(client, monkeypatch, tmp_path):
    dependant, original_route, limiter, witness = private_route_state(client)
    witness.update(installed=False, restored=False, observation_complete=False)
    evidence = os.environ.get("PALLIUM_HARNESS_EVIDENCE")
    if evidence:
        Path(evidence).write_text(json.dumps(witness), encoding="utf-8")
    original_call = dependant.call
    original_route_call = original_route.dependant.call
    original_app = client._transport.app
    original_acquire = limiter.acquire_on_behalf_of
    original_acquire_static = inspect.getattr_static(limiter, "acquire_on_behalf_of")
    original_acquire_type = type(limiter).acquire_on_behalf_of
    recorder, cleanup = capture.Recorder(), ExitStack()
    stages = []
    original_sync, original_turn = anyio.to_thread.run_sync, RelayService.turn

    async def observe_sync(operation, *args, **kwargs):
        span = {"stage": "worker", "submitted": time.monotonic()}
        stages.append(span)
        def work(*worker_args):
            span["entered"] = time.monotonic()
            try:
                return operation(*worker_args)
            finally:
                span["returned"] = time.monotonic()
        try:
            return await original_sync(work, *args, **kwargs)
        finally:
            span["await_finished"] = time.monotonic()

    def observe_turn(service, *args, **kwargs):
        span = {"stage": "durable_turn", "entered": time.monotonic()}
        stages.append(span)
        try:
            return original_turn(service, *args, **kwargs)
        finally:
            span["returned"] = time.monotonic()

    try:
        capture.install(client, recorder, cleanup)
        witness["installed"] = True
        assert dependant.call is not original_call
        if dependant is not original_route.dependant:
            assert original_route.dependant.call is original_route_call
        with monkeypatch.context() as passive:
            passive.setattr(anyio.to_thread, "run_sync", observe_sync)
            passive.setattr(RelayService, "turn", observe_turn)
            forward = {"stage": "forward", "path": "/relay/turn", "entered": time.monotonic()}
            stages.append(forward)
            try:
                # Exact Codex mode uses one admission acquisition even with no queued delivery.
                response = client.post("/relay/turn", json={
                    "runtime": "codex", "session_ref": "private-observer-session",
                    "container_ref": "git:example/observer", "max_messages": 1,
                    "wake_delivery_id": "relay-delivery-" + "0" * 32,
                })
            finally:
                forward["returned"] = time.monotonic()
            assert response.status_code == 200
            forward["status"] = response.status_code
        assert [event["stage"] for event in recorder.events] == [
            "asgi_entry", "route_entry", "acquire_start", "acquire_end"]
        assert len({event["request"] for event in recorder.events}) == 1
        assert len([span for span in stages if span["stage"] == "durable_turn"]) == 1
        native = tmp_path / "fixture-boundaries.json"
        native.write_text(json.dumps(stages), encoding="utf-8")
        witness["observation_complete"] = capture.observation(recorder, native)["complete"]
        assert witness["observation_complete"], witness
    finally:
        cleanup.close()
        assert client._transport.app is original_app
        assert dependant.call is original_call
        assert original_route.dependant.call is original_route_call
        assert limiter.acquire_on_behalf_of == original_acquire
        assert inspect.getattr_static(limiter, "acquire_on_behalf_of") is original_acquire_static
        assert type(limiter).acquire_on_behalf_of is original_acquire_type
        witness["restored"] = True
        if evidence:
            Path(evidence).write_text(json.dumps(witness), encoding="utf-8")


def test_short_private_worker_path_binds_longest_existing_unix_socket_fixture(tmp_path):
    source = Path(__file__).with_name("test_claude_wake_dispatch.py")
    tree = ast.parse(source.read_text(encoding="utf-8"))
    candidates = []
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef) or not function.name.startswith("test_"):
            continue
        if not any(isinstance(node, ast.Attribute) and node.attr == "AF_UNIX" for node in ast.walk(function)):
            continue
        for node in ast.walk(function):
            if (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
                    and isinstance(node.left, ast.Name) and node.left.id == "tmp_path"
                    and isinstance(node.right, ast.Constant) and isinstance(node.right.value, str)
                    and node.right.value.endswith(".sock")):
                # Pytest's numbered leaf rule, including the observed suffix.
                leaf = re.sub(r"[\W]", "_", function.name)[:30] + "0"
                candidates.append((leaf, node.right.value))
    assert candidates, "No actual native socket fixture was found"
    leaf, filename = max(candidates, key=lambda pair: len(os.fsencode("/".join(pair))))
    assert re.fullmatch(r"popen-gw[0-3]", tmp_path.parent.name), "Use the reviewed short worker-shaped basetemp"
    address = tmp_path.parent / leaf / filename
    linux_path = "/tmp/p12345678/p/popen-gw3/" + leaf + "/" + filename
    assert len(linux_path.encode("utf-8")) <= 100
    if not hasattr(socket, "AF_UNIX"):
        pytest.skip("Native AF_UNIX is unavailable on this platform")
    address.parent.mkdir()
    bound = False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(address))
            bound = True
    finally:
        address.unlink(missing_ok=True)
        address.parent.rmdir()
    assert bound and not address.exists() and not address.parent.exists()
    evidence = os.environ.get("PALLIUM_HARNESS_EVIDENCE")
    if evidence:
        path = Path(evidence)
        receipt = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        receipt["socket"] = {"native_path_bytes": len(os.fsencode(str(address))),
                             "modeled_linux_path_bytes": len(linux_path.encode("utf-8")),
                             "bound_closed_removed": True,
                             "limitation": "Native host bind; modeled path is not Linux execution"}
        path.write_text(json.dumps(receipt), encoding="utf-8")


def test_default_install_partial_real_fixture_restores_effective_route_and_limiter(client, monkeypatch):
    dependant, original_route, limiter, _ = private_route_state(client)
    original_call = dependant.call
    original_route_call = original_route.dependant.call
    original_app = client._transport.app
    original_acquire = limiter.acquire_on_behalf_of
    original_acquire_static = inspect.getattr_static(limiter, "acquire_on_behalf_of")
    original_acquire_type = type(limiter).acquire_on_behalf_of
    original_replace = capture.replace
    injected = []
    def fail_transport(stack, owner, name, replacement):
        if owner is client._transport and name == "app":
            assert dependant.call is not original_call
            assert limiter.acquire_on_behalf_of != original_acquire
            if dependant is not original_route.dependant:
                assert original_route.dependant.call is original_route_call
            injected.append(True)
            raise RuntimeError("transport replacement blocked for restoration check")
        return original_replace(stack, owner, name, replacement)
    monkeypatch.setattr(capture, "replace", fail_transport)
    cleanup = ExitStack()
    try:
        with pytest.raises(RuntimeError, match="transport replacement blocked"):
            capture.install(client, capture.Recorder(), cleanup)
        assert injected == [True]
    finally:
        cleanup.close()
        assert client._transport.app is original_app
        assert dependant.call is original_call
        assert original_route.dependant.call is original_route_call
        assert limiter.acquire_on_behalf_of == original_acquire
        assert inspect.getattr_static(limiter, "acquire_on_behalf_of") is original_acquire_static
        assert type(limiter).acquire_on_behalf_of is original_acquire_type
